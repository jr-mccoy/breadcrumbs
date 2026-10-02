"""`crumb repair` (field report 2026-10-01, issue 12): records written by hand
while the CLI was unavailable fail validation, and readers drop or misread
them. Repair derives what it honestly can and lists what needs a person.

Run with:  python -m unittest discover -s tests -p test_repair.py
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


HAND_VERIFICATION = "# Zebra cache race\n\nFixed. Re-ran the soak test; see src/cache/zebra.py.\n"


class RepairTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        git(self.root, "init", "-q")
        git(self.root, "config", "user.email", "t@t")
        git(self.root, "config", "user.name", "Pat")
        run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME
        (self.mem / "verifications" / "2026-09-20-zebra-cache-race-fixed.md").write_text(
            HAND_VERIFICATION
        )
        run(
            [
                "remember",
                "decision",
                "--project",
                str(self.root),
                "--title",
                "Use the porpoise queue",
                "--set",
                "Decision",
                "porpoise",
                "--confidence",
                "low",
            ]
        )
        self.decision = next((self.mem / "decisions").glob("*.md"))
        text = self.decision.read_text()
        self.decision.write_text(
            text.replace("status: active", "status: resolved 2026-09-18 in PR 41").replace(
                "scope: project", "scope: breadcrumbs"
            )
        )
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", "hand-written records")

    def tearDown(self):
        self._tmp.cleanup()

    def fails(self) -> list[str]:
        return [
            f["path"] + ": " + f["message"]
            for f in crumb.run_validate(self.mem)
            if f["status"] == "fail" and f["check"] != "freshness"
        ]

    def test_preview_changes_nothing_and_lists_what_needs_a_person(self):
        before = self.decision.read_text()
        code, out = run(["repair", "--project", str(self.root), "--json"])
        self.assertEqual(code, 0)
        doc = json.loads(out)
        self.assertFalse(doc["applied"])
        self.assertEqual(self.decision.read_text(), before)
        self.assertTrue(any("outcome" in n for n in doc["needs"]))
        self.assertTrue(any("src/cache/zebra.py" in p for p in doc["proposals"]))

    def test_apply_fixes_the_derivable_and_never_invents_an_outcome(self):
        run(["repair", "--project", str(self.root), "--apply"])
        meta, _ = crumb.parse_frontmatter(self.decision.read_text())
        self.assertEqual(meta["status"], "stale")
        self.assertEqual(meta["scope"], "project")
        self.assertIn("status: resolved 2026-09-18 in PR 41", meta["repaired_from"])
        vpath = self.mem / "verifications" / "2026-09-20-zebra-cache-race-fixed.md"
        vmeta, body = crumb.parse_frontmatter(vpath.read_text())
        self.assertEqual(vmeta["title"], "Zebra cache race")
        self.assertEqual(vmeta["subject"], "Zebra cache race")
        self.assertEqual(vmeta["created_by"], "Pat")
        self.assertTrue(str(vmeta["created_at"]).startswith("2026-09-20"))
        self.assertEqual(vmeta["confidence"], "low")
        self.assertNotIn("outcome", vmeta)
        self.assertIn("Fixed. Re-ran the soak test", body)
        self.assertEqual([f for f in self.fails() if "outcome" not in f], [])

    def test_a_given_outcome_completes_the_repair(self):
        run(
            [
                "repair",
                "--project",
                str(self.root),
                "--apply",
                "--set",
                "ver_20260920_zebra-cache-race-fixed.outcome=fixed",
            ]
        )
        self.assertEqual(self.fails(), [])
        code, out = run(["repair", "--project", str(self.root)])
        self.assertIn("nothing to repair", out)

    def test_repair_is_read_only_to_guard_until_applied(self):
        from breadcrumbs import shellcmd

        self.assertTrue(shellcmd.is_read_only("crumb repair"))
        self.assertFalse(shellcmd.is_read_only("crumb repair --apply"))


if __name__ == "__main__":
    unittest.main()
