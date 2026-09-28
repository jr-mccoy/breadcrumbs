"""Onboarding and operation (audit WP20).

- The quickstart runs as written (`tools/quickstart_check.py`, which the CI
  `package` job also runs against the installed wheel).
- `crumb doctor` names the fix for each state an operator must recover from.
- This repository's default handoff is reconciled after its latest release,
  so it cannot send the next agent back to finished work (F24).
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs.adapters import claude  # noqa: E402

AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")


def _run(argv):
    with (
        contextlib.redirect_stdout(io.StringIO()) as out,
        contextlib.redirect_stderr(io.StringIO()),
    ):
        try:
            code = crumb.main(argv)
        except SystemExit as exc:
            code = exc.code
    return code, out.getvalue()


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in AGENT_MARKERS}


def _checks(root: Path) -> dict:
    return {c["check"]: c for c in _cli.doctor_report(root)["checks"]}


class QuickstartTests(unittest.TestCase):
    def test_quickstart_works_as_written(self):
        p = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "quickstart_check.py")],
            capture_output=True,
            text=True,
            env=_clean_env(),
        )
        self.assertEqual(p.returncode, 0, p.stdout[-3000:] + p.stderr[-1000:])
        self.assertIn("works as written", p.stdout)


class DoctorRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, _clean_env(), clear=True)
        self.env.start()
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        _run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_a_record_that_fails_validation_is_named_with_its_fix(self):
        code, out = _run(
            [
                "remember",
                "decision",
                "--title",
                "Doctor fixture decision",
                "--set",
                "Decision",
                "x",
                "--evidence",
                "file",
                "a.py",
                "--project",
                str(self.root),
            ]
        )
        self.assertEqual(code, 0, out)
        self.assertTrue(_checks(self.root)["records"]["ok"])
        path = next((self.mem / "decisions").glob("*.md"))
        path.write_text(path.read_text().replace("confidence: medium", "confidence: certainly"))
        check = _checks(self.root)["records"]
        self.assertFalse(check["ok"])
        self.assertIn("crumb validate", check["detail"])

    def test_a_store_this_build_cannot_write_is_named(self):
        self.assertTrue(_checks(self.root)["compatibility"]["ok"])
        manifest = self.mem / "manifest.yml"
        manifest.write_text(manifest.read_text() + "requires: some-future-feature\n")
        check = _checks(self.root)["compatibility"]
        self.assertFalse(check["ok"])
        self.assertIn("some-future-feature", check["detail"])
        self.assertIn("writes are refused", check["detail"])

    def test_an_outdated_guard_matcher_is_named_with_its_fix(self):
        _cli.install_claude_hooks(self.root, ["guard"])
        self.assertTrue(_checks(self.root)["hook_matcher"]["ok"])
        settings = self.root / ".claude" / "settings.json"
        data = json.loads(settings.read_text())
        data["hooks"]["PreToolUse"][0]["matcher"] = "Bash|Edit|Write|MultiEdit|Task|Agent"
        settings.write_text(json.dumps(data))
        check = _checks(self.root)["hook_matcher"]
        self.assertFalse(check["ok"])
        self.assertIn("crumb init --with-hooks", check["detail"])
        _cli.install_claude_hooks(self.root, ["guard"])  # the fix it names
        self.assertTrue(_checks(self.root)["hook_matcher"]["ok"])
        self.assertIn(claude.GUARD_MATCHER, _checks(self.root)["hook_matcher"]["detail"])

    def test_an_incomplete_related_map_is_named(self):
        from breadcrumbs import related

        for i in range(6):
            _run(
                [
                    "remember",
                    "decision",
                    "--title",
                    f"Shared tag decision number {i}",
                    "--set",
                    "Decision",
                    f"x{i}",
                    "--evidence",
                    "file",
                    "a.py",
                    "--tags",
                    "shared",
                    "--allow-duplicate",
                    "--project",
                    str(self.root),
                ]
            )
        self.assertNotIn("related_map", _checks(self.root))
        with mock.patch.object(related, "RELATED_PAIR_BUDGET", 1):
            _run(["reindex", "--project", str(self.root)])
        self.assertFalse(_checks(self.root)["related_map"]["ok"])


class DogfoodHandoffTests(unittest.TestCase):
    def test_default_handoff_is_reconciled_after_the_latest_release(self):
        """F24: the default handoff said Phase 2 was next long after it shipped.
        After a release, `handoff.md` must be updated (operator-guide §6)."""
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        released = [
            date.fromisoformat(d)
            for d in re.findall(r"^## \[\d+\.\d+\.\d+\] — (\d{4}-\d{2}-\d{2})", changelog, re.M)
        ]
        handoff = (ROOT / crumb.MEMORY_DIRNAME / "handoff.md").read_text(encoding="utf-8")
        stamp = re.search(r"_Last updated: (\d{4}-\d{2}-\d{2})", handoff)
        self.assertIsNotNone(stamp, "handoff.md has no _Last updated_ line")
        self.assertGreaterEqual(
            date.fromisoformat(stamp.group(1)),
            max(released),
            "handoff.md predates the latest release: reconcile it (docs/operator-guide.md §6)",
        )


if __name__ == "__main__":
    unittest.main()
