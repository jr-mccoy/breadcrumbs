"""Tests for `crumb capture session`.

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
import unittest.mock
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli  # noqa: E402  (`crumb` is a flat re-export; patching needs the module)


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
            #: the path itself must not appear in the committed record.
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


class LookbackCapTests(unittest.TestCase):
    """The first capture after a gap must not claim every commit since.

    The diff base is the newest session record's commit. On a store idle for six
    weeks that handed one session ~50 commits and "807 files changed" — wrong in
    exactly the run where someone is deciding whether the tool is trustworthy.
    """

    def _work(self, tmp: str) -> str:
        mem = Path(tmp) / crumb.MEMORY_DIRNAME
        path = next(p for p in (mem / "sessions").glob("*.md") if "gapped" in p.name)
        _, body = crumb.parse_frontmatter(path.read_text(encoding="utf-8"))
        return crumb.Record(path, "session", {}, body).sections["Work Completed"]

    def test_window_is_capped_and_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            run(["capture", "session", "--project", tmp, "--fast", "--next", "n", "--title", "old"])
            for i in range(crumb.GIT_PREFILL_MAX_COMMITS + 5):
                commit(root, f"c{i}.txt", f"commit {i}")
            run(
                [
                    "capture",
                    "session",
                    "--project",
                    tmp,
                    "--fast",
                    "--next",
                    "n",
                    "--title",
                    "gapped",
                ]
            )
            work = self._work(tmp)
            bullets = [ln for ln in work.splitlines() if ln.startswith("- ")]
            self.assertEqual(len(bullets), crumb.GIT_PREFILL_MAX_COMMITS)
            self.assertNotIn("commit 0", work)  # older than the window
            self.assertIn("Prefill window", work)
            self.assertIn("too far to attribute", work)

    def test_a_normal_gap_keeps_the_full_since_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            run(["capture", "session", "--project", tmp, "--fast", "--next", "n", "--title", "old"])
            for i in range(3):
                commit(root, f"c{i}.txt", f"commit {i}")
            run(
                [
                    "capture",
                    "session",
                    "--project",
                    tmp,
                    "--fast",
                    "--next",
                    "n",
                    "--title",
                    "gapped",
                ]
            )
            work = self._work(tmp)
            self.assertIn("commit 0", work)
            self.assertIn("3 commit(s) since the last session record", work)

    def test_uncommitted_work_is_not_reported_as_no_changes(self):
        """The record used to contradict its own frontmatter: "no file changes
        detected" in the body, 25 paths in `dirty_files`. A reader concludes the
        session did nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            # Work in progress: written, not committed — the normal state at the
            # moment a Stop hook fires.
            for name in ("a.kt", "b.kt", "c.kt"):
                (root / name).write_text("x\n", encoding="utf-8")
            run(["capture", "session", "--project", tmp, "--fast", "--next", "n", "--title", "wip"])
            path = next((mem / "sessions").glob("*wip*.md"))
            meta, body = crumb.parse_frontmatter(path.read_text(encoding="utf-8"))
            files = crumb.Record(path, "session", {}, body).sections["Files Touched"]
            self.assertNotIn("no file changes detected", files)
            self.assertIn("uncommitted", files)
            self.assertTrue(meta.get("dirty_files"), "frontmatter records the dirty files")
            # the count agrees with the frontmatter, and no path leaks into the body
            self.assertIn(str(len(meta["dirty_files"])), files)
            for name in ("a.kt", "b.kt", "c.kt"):
                self.assertNotIn(name, files)

    def test_files_touched_names_its_diff_base(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            commit(root, "g.txt", "add g")
            run(["capture", "session", "--project", tmp, "--fast", "--next", "n", "--title", "s"])
            path = next((Path(tmp) / crumb.MEMORY_DIRNAME / "sessions").glob("*.md"))
            _, body = crumb.parse_frontmatter(path.read_text(encoding="utf-8"))
            files = crumb.Record(path, "session", {}, body).sections["Files Touched"]
            self.assertIn("files changed", files)
            self.assertIn("vs `", files)


class NonInteractiveCaptureTests(unittest.TestCase):
    """An unanswerable prompt is "no answer", not a traceback."""

    def test_eof_on_stdin_reports_the_missing_next_action(self):
        """A harness whose stdin passes isatty() but reads EOF took the whole
        command down with an EOFError, after it had printed its git summary."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            stdin = sys.stdin
            with unittest.mock.patch.object(cli, "_interactive", lambda: True):
                sys.stdin = io.StringIO("")  # every read is EOF
                try:
                    with (
                        contextlib.redirect_stdout(io.StringIO()),
                        contextlib.redirect_stderr(io.StringIO()),
                    ):
                        code = crumb.main(["capture", "session", "--project", tmp, "--title", "s"])
                finally:
                    sys.stdin = stdin
            self.assertEqual(code, 2)  # a clean "needs --next", not an EOFError


class PruneSessionsTests(unittest.TestCase):
    """P1-9 (0.1.10 field test): the Stop hook creates the session bloat audit
    warns about; `crumb prune sessions` is the explicit retention act. Machine
    snapshots only — a session with a human Next Action is a deliberate
    handoff — and the newest N are never touched."""

    def _store_with_sessions(self, tmp: str) -> tuple[Path, Path]:
        root = make_repo(tmp)
        mem = init_store(root)
        # Titles a..e make the filename order deterministic (same date, slug sorts).
        for title, next_action in (
            ("session a", cli.HOOK_SESSION_NEXT_ACTION),
            ("session b", cli.HOOK_SESSION_NEXT_ACTION),
            ("session c", cli.HOOK_SESSION_NEXT_ACTION),
            ("session d", "finish the flurble rollout"),  # human handoff
            ("session e", cli.HOOK_SESSION_NEXT_ACTION),  # newest
        ):
            crumb.write_record(
                mem,
                root,
                "session",
                title,
                {"Next Action": next_action, "Work Completed": "w"},
            )
        return root, mem

    def test_dry_run_lists_without_deleting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_sessions(tmp)
            code, out = run(
                ["prune", "sessions", "--keep", "1", "--dry-run", "--project", str(root), "--json"]
            )
            self.assertEqual(code, 0)
            res = json.loads(out)
            self.assertTrue(res["dry_run"])
            self.assertEqual(len(res["deleted"]), 3, res)
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 5)

    def test_prune_deletes_machine_snapshots_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_sessions(tmp)
            code, out = run(["prune", "sessions", "--keep", "1", "--project", str(root), "--json"])
            self.assertEqual(code, 0)
            res = json.loads(out)
            remaining = sorted(p.name for p in (mem / "sessions").glob("*.md"))
            # The human handoff (d) and the newest session (e) survive.
            self.assertEqual(len(remaining), 2, (remaining, res))
            self.assertTrue(any("session-d" in n for n in remaining), remaining)
            self.assertTrue(any("session-e" in n for n in remaining), remaining)
            # The store still validates and the projections were rebuilt.
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertEqual(fails, [])

    def test_newest_sessions_are_never_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_sessions(tmp)
            code, out = run(["prune", "sessions", "--project", str(root), "--json"])
            self.assertEqual(code, 0)
            res = json.loads(out)
            # Default keep (20) exceeds the 5 sessions: nothing to delete.
            self.assertEqual(res["deleted"], [])
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
