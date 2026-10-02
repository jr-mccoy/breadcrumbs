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
        (self.root / "src" / "cache").mkdir(parents=True)
        (self.root / "src" / "cache" / "zebra.py").write_text("x = 1\n")
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


class EvidenceSuggestionTests(unittest.TestCase):
    """DoWhat retest of 0.5.0, item 10: repair suggested evidence that was not a
    file at all."""

    PROSE = (
        "# Remote Config quota\n\nThe device clock was Asia/Tokyo. and the fetch "
        "errors/skips/cache path ran through Route/ViewModel/coordinator. Note/Shopping "
        "and admission/binding were fine; npm lives in APPDATA/npm and the SDK in "
        "/home/user/android-sdk. The push key families/-OzbgqHU and the route "
        "/v1/projects/<id>/remoteConfig were checked. The fix is in app/src/main/Config.kt "
        "and tools/remote-config.sh, and docs/old-notes.md is committed.\n"
    )

    def test_only_files_that_exist_are_suggested(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q")
            git(root, "config", "user.email", "t@t")
            git(root, "config", "user.name", "Pat")
            run(["init", "--project", str(root), "--session-tracking", "full"])
            mem = root / crumb.MEMORY_DIRNAME
            (root / "app" / "src" / "main").mkdir(parents=True)
            (root / "app" / "src" / "main" / "Config.kt").write_text("val x = 1\n")
            (root / "tools").mkdir()
            (root / "tools" / "remote-config.sh").write_text("#!/bin/sh\n")
            (root / "docs").mkdir()
            (root / "docs" / "old-notes.md").write_text("notes\n")
            git(root, "add", "docs/old-notes.md")
            git(root, "commit", "-qm", "notes")
            (root / "docs" / "old-notes.md").unlink()  # still in HEAD
            (mem / "verifications" / "2026-09-20-remote-config-quota.md").write_text(self.PROSE)
            code, out = run(["repair", "--project", str(root), "--json"])
            doc = json.loads(out)
            proposals = " ".join(doc["proposals"])
            self.assertIn("app/src/main/Config.kt", proposals)
            self.assertIn("tools/remote-config.sh", proposals)
            self.assertIn("docs/old-notes.md", proposals)
            for bogus in (
                "Asia/Tokyo",
                "errors/skips/cache",
                "Route/ViewModel",
                "Note/Shopping",
                "admission/binding",
                "APPDATA/npm",
                "android-sdk",
                "families/",
                "/v1/projects",
            ):
                self.assertNotIn(bogus, proposals)


if __name__ == "__main__":
    unittest.main()
