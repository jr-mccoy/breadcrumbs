"""Tests for `crumb capture session` (Phase 3).

Run with:  python -m pytest tests/
       or:  python tests/test_capture.py
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


def make_repo(tmp: str) -> Path:
    root = Path(tmp)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("a\n")
    git(root, "add", "f.txt")
    git(root, "commit", "-qm", "initial commit")
    return root


def commit(root: Path, name: str, msg: str) -> None:
    (root / name).write_text("x\n")
    git(root, "add", name)
    git(root, "commit", "-qm", msg)


def init_store(root: Path, tracking: str = "full") -> Path:
    crumb.main(["init", "--project", str(root), "--session-tracking", tracking])
    return root / crumb.MEMORY_DIRNAME


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


class CapturePrefillTests(unittest.TestCase):
    def test_prefills_work_and_files_from_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            commit(root, "g.txt", "add g.txt feature")
            code, _ = run(
                ["capture", "session", "--project", tmp, "--next", "wire resume", "--title", "work"]
            )
            self.assertEqual(code, 0)
            path = next((mem / "sessions").glob("*.md"))
            _, body = crumb.parse_frontmatter(path.read_text())
            rec = crumb.Record(path, "session", {}, body)
            self.assertIn("add g.txt feature", rec.sections["Work Completed"])
            # Files Touched is a counts-only summary, not an inlined per-file --stat
            # (review §6.1): the path itself must not appear in the committed record.
            self.assertIn("files changed", rec.sections["Files Touched"])
            self.assertNotIn("g.txt", rec.sections["Files Touched"])
            self.assertEqual(rec.sections["Next Action"], "wire resume")
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    def test_since_window_only_new_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            commit(root, "second.txt", "second feature")
            run(["capture", "session", "--project", tmp, "--next", "n1", "--title", "first"])
            commit(root, "third.txt", "third feature")
            run(["capture", "session", "--project", tmp, "--next", "n2", "--title", "secondcap"])
            path = next((mem / "sessions").glob("*secondcap*.md"))
            _, body = crumb.parse_frontmatter(path.read_text())
            rec = crumb.Record(path, "session", {}, body)
            work = rec.sections["Work Completed"]
            self.assertIn("third feature", work)
            self.assertNotIn("second feature", work)

    def test_updates_handoff_and_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            run(
                [
                    "capture",
                    "session",
                    "--project",
                    tmp,
                    "--next",
                    "do the thing",
                    "--focus",
                    "phase 3",
                ]
            )
            handoff = (mem / "handoff.md").read_text()
            self.assertIn("## Next Action", handoff)
            self.assertIn("do the thing", handoff)
            self.assertIn("phase 3", handoff)
            # handoff still satisfies validate's structural check
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])
            current = (mem / "current.md").read_text()
            self.assertIn("phase 3", current)


class DiffStatSummaryTests(unittest.TestCase):
    def test_summarizes_counts(self):
        self.assertEqual(
            crumb._summarize_diffstat(" 93 files changed, 1200 insertions(+), 56 deletions(-)"),
            "93 files changed, +1200/-56",
        )

    def test_singular_and_partial(self):
        self.assertEqual(
            crumb._summarize_diffstat(" 1 file changed, 2 insertions(+)"),
            "1 files changed, +2/-0",
        )

    def test_empty_means_no_changes(self):
        self.assertEqual(crumb._summarize_diffstat(""), "_(no file changes detected)_")
        self.assertEqual(crumb._summarize_diffstat(None), "_(no file changes detected)_")


class CaptureFastTests(unittest.TestCase):
    def test_fast_writes_minimal_valid_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            code, _ = run(
                ["capture", "session", "--project", tmp, "--fast", "--next", "tired, resume here"]
            )
            self.assertEqual(code, 0)
            path = next((mem / "sessions").glob("*.md"))
            _, body = crumb.parse_frontmatter(path.read_text())
            rec = crumb.Record(path, "session", {}, body)
            self.assertEqual(rec.sections["Next Action"], "tired, resume here")
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    def test_fast_requires_next(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            # non-interactive + --fast without --next -> error, no prompts
            code, _ = run(["capture", "session", "--project", tmp, "--fast"])
            self.assertEqual(code, 2)

    def test_json_summary_reports_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            code, out = run(
                ["capture", "session", "--project", tmp, "--fast", "--next", "x", "--json"]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertTrue(payload["fast"])
            self.assertEqual(payload["session_tracking"], "full")


class CaptureTrackingPolicyTests(unittest.TestCase):
    def _ignored(self, root: Path, rel: str) -> bool:
        r = subprocess.run(
            ["git", "check-ignore", rel], cwd=str(root), capture_output=True, text=True
        )
        return r.returncode == 0

    def test_distillate_session_is_gitignored_but_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root, tracking="distillate")
            run(["capture", "session", "--project", tmp, "--fast", "--next", "x", "--title", "s"])
            path = next((mem / "sessions").glob("*.md"))
            self.assertTrue(path.exists())
            rel = str(path.relative_to(root))
            self.assertTrue(self._ignored(root, rel), "distillate sessions/ should be gitignored")

    def test_full_session_is_not_gitignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root, tracking="full")
            run(["capture", "session", "--project", tmp, "--fast", "--next", "x", "--title", "s"])
            path = next((mem / "sessions").glob("*.md"))
            rel = str(path.relative_to(root))
            self.assertFalse(self._ignored(root, rel), "full sessions/ should be tracked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
