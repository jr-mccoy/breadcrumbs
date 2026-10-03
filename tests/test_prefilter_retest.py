"""The guard pre-filter file (DoWhat retest of 0.5.0, items 8 and 9).

- Item 8: `generated/guard-prefilter.json` grew to 476 KB, pretty-printed one
  token per line, so every rebuild was a ~33,000-line diff in a committed file
  that conflicted on merges. Decision D8: it is machine-local (index/), compact
  and stably sorted; the committed copy is removed by the next reindex.
- Item 9: it copied words out of records. It must never carry a secret-shaped
  or opaque value, and `scan-secrets` must cover generated/.

Run with:  python -m unittest discover -s tests -p test_prefilter_retest.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import projections  # noqa: E402
from breadcrumbs import hooks_guard  # noqa: E402
from breadcrumbs import scoring as _scoring  # noqa: E402

AWS_SHAPED = "AKIAZ7QW4ERTY8UIOP3A"
RANDOM_SHAPED = "Xk9fQ2mZ7pL4vR8tW3nB6yH1cJ5sD0gA"


def run(argv: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return crumb.main(argv)


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def tearDown(self):
        self._tmp.cleanup()

    def decision(self, title: str, tags: str = "build") -> None:
        run(
            [
                "remember",
                "decision",
                "--project",
                str(self.root),
                "--title",
                title,
                "--set",
                "Decision",
                title,
                "--tags",
                tags,
                "--confidence",
                "low",
                "--allow-duplicate",  # alike on purpose
            ]
        )


class MachineLocalPrefilterTests(StoreCase):
    def test_it_lives_in_index_and_the_committed_copy_goes(self):
        legacy = self.mem / "generated" / crumb.GUARD_PREFILTER_FILENAME
        legacy.write_text('{"format": 4}\n', encoding="utf-8")
        self.decision("Gradle builds use the configuration cache")
        self.assertFalse(legacy.exists(), "the 0.5.0 copy under generated/ was left behind")
        path = crumb.guard_prefilter_path(self.mem)
        self.assertEqual(path.parent.name, "index")
        self.assertIsNotNone(
            projections.verified(self.mem, self.root, crumb.GUARD_PREFILTER_FILENAME)
        )

    def test_it_is_one_compact_line(self):
        for i in range(5):
            self.decision(f"Decision number {i} about the release pipeline", tags=f"t{i}")
        text = crumb.guard_prefilter_path(self.mem).read_text(encoding="utf-8")
        self.assertEqual(text.count("\n"), 1)
        self.assertNotIn(", ", text)
        self.assertNotIn(": ", text)

    def test_the_same_records_give_the_same_bytes_in_any_order(self):
        words = ("alpha", "bravo", "charlie", "delta", "echo", "foxtrot")
        for w in words:
            self.decision(f"Decision on the {w} module caching", tags=f"{w},shared")
        items = _scoring._candidate_items(self.mem, include_ideas=False)
        self.assertGreaterEqual(len(items), 6)
        forward = _cli._build_guard_prefilter(self.mem)
        with mock.patch.object(_scoring, "_candidate_items", return_value=list(reversed(items))):
            backward = _cli._build_guard_prefilter(self.mem)
        self.assertEqual(
            json.dumps(forward, separators=(",", ":"), sort_keys=True),
            json.dumps(backward, separators=(",", ":"), sort_keys=True),
        )

    def test_the_hook_still_trusts_it(self):
        self.decision("Gradle builds use the configuration cache", tags="gradle")
        # Verified, and nothing in it matches: the hook may stay silent.
        self.assertFalse(hooks_guard._prefilter_trap_hit(self.mem, "ls -la docs", None))
        self.assertTrue(
            hooks_guard._prefilter_trap_hit(self.mem, "./gradlew build --configuration-cache", None)
        )


class NoSecretsInThePrefilterTests(StoreCase):
    def _write_secret_record(self) -> None:
        (self.mem / "decisions" / "2026-06-01-cloud-credentials.md").write_text(
            "---\n"
            "id: dec_20260601_cloud-credentials\n"
            "type: decision\n"
            "slug: cloud-credentials\n"
            "title: Cloud credentials come from the environment\n"
            "status: active\n"
            "created_at: 2026-06-01T12:00:00+00:00\n"
            "updated_at: 2026-06-01T12:00:00+00:00\n"
            "scope: project\n"
            "confidence: low\n"
            "tags:\n  - credentials\n"
            "evidence: []\n"
            "---\n\n"
            f"## Decision\nNever paste a key like {AWS_SHAPED} or {RANDOM_SHAPED} into a "
            "script; read it from the environment.\n",
            encoding="utf-8",
        )
        run(["reindex", "--project", str(self.root)])

    def test_secret_shaped_values_are_left_out(self):
        self._write_secret_record()
        text = crumb.guard_prefilter_path(self.mem).read_text(encoding="utf-8").lower()
        self.assertNotIn(AWS_SHAPED.lower(), text)
        self.assertNotIn(RANDOM_SHAPED.lower(), text)
        self.assertIn("credential", text)  # the ordinary words are still there

    def test_an_action_holding_one_still_runs_full_guard(self):
        self._write_secret_record()
        self.assertTrue(hooks_guard._prefilter_trap_hit(self.mem, f"echo {RANDOM_SHAPED}", None))

    def test_scan_secrets_covers_generated(self):
        packet = self.mem / "generated" / "resume-packet.md"
        packet.write_text(
            packet.read_text(encoding="utf-8") + f"\n{AWS_SHAPED}\n", encoding="utf-8"
        )
        hits = [h for h in _cli.scan_secrets(self.mem) if h["path"].startswith("generated/")]
        self.assertTrue(hits, "a secret in a committed projection went unreported")


if __name__ == "__main__":
    unittest.main()
