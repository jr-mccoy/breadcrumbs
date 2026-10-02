"""Reading refs from .git without starting git (DoWhat retest of 0.5.0, item 7).

A full guard firing started five `git` processes: ~5 ms on Linux, 250-400 ms
with Git for Windows. `breadcrumbs.gitrefs` answers the branch, HEAD and the
default branch from files. Each answer here is checked against git itself, in
the layouts git produces: loose and packed refs, a linked worktree, a detached
HEAD, an unborn branch, and `origin/HEAD`.

Run with:  python -m unittest discover -s tests -p test_gitrefs.py
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
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import gitrefs, handoffs  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    git(path, "config", "user.email", "t@t")
    git(path, "config", "user.name", "t")
    (path / "f.txt").write_text("a\n")
    git(path, "add", "f.txt")
    git(path, "commit", "-qm", "initial")
    return path


class ReadsLikeGitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_repo(self.tmp / "repo")

    def tearDown(self):
        self._tmp.cleanup()

    def test_branch_and_head_of_a_plain_repo(self):
        self.assertEqual(gitrefs.branch(self.root), "main")
        self.assertEqual(gitrefs.head_sha(self.root), git(self.root, "rev-parse", "HEAD"))

    def test_packed_refs(self):
        git(self.root, "branch", "side")
        git(self.root, "pack-refs", "--all")
        self.assertFalse((self.root / ".git" / "refs" / "heads" / "main").exists())
        self.assertEqual(gitrefs.head_sha(self.root), git(self.root, "rev-parse", "HEAD"))
        self.assertTrue(gitrefs.has_ref(self.root, "refs/heads/side"))
        self.assertFalse(gitrefs.has_ref(self.root, "refs/heads/nope"))

    def test_a_detached_head(self):
        git(self.root, "checkout", "-q", "--detach")
        self.assertEqual(gitrefs.branch(self.root), "HEAD")
        self.assertEqual(
            _cli._git_branch(self.root), git(self.root, "rev-parse", "--abbrev-ref", "HEAD")
        )

    def test_an_unborn_branch(self):
        fresh = self.tmp / "fresh"
        fresh.mkdir()
        git(fresh, "init", "-q", "-b", "trunk")
        self.assertEqual(gitrefs.branch(fresh), "trunk")
        self.assertIsNone(gitrefs.head_sha(fresh))

    def test_a_linked_worktree(self):
        wt = self.tmp / "wt"
        git(self.root, "worktree", "add", "-q", "-b", "feature", str(wt))
        self.assertTrue((wt / ".git").is_file())
        self.assertEqual(gitrefs.branch(wt), "feature")
        self.assertEqual(gitrefs.head_sha(wt), git(wt, "rev-parse", "HEAD"))
        self.assertTrue(gitrefs.has_ref(wt, "refs/heads/main"))

    def test_a_subdirectory_finds_its_repo(self):
        sub = self.root / "a" / "b"
        sub.mkdir(parents=True)
        self.assertEqual(gitrefs.branch(sub), "main")

    def test_the_default_branch_from_origin_head(self):
        clone = self.tmp / "clone"
        git(self.tmp, "clone", "-q", str(self.root), str(clone))
        git(clone, "checkout", "-q", "-b", "work")
        self.assertEqual(
            gitrefs.symbolic_target(clone, "refs/remotes/origin/HEAD"), "refs/remotes/origin/main"
        )
        self.assertEqual(handoffs._default_branch(clone), "main")

    def test_no_repo_is_none(self):
        bare = self.tmp / "plain"
        bare.mkdir()
        self.assertIsNone(gitrefs.git_dir(bare))
        self.assertIsNone(gitrefs.branch(bare))

    def test_a_reftable_store_is_left_to_git(self):
        (self.root / ".git" / "reftable").mkdir()
        self.assertIsNone(gitrefs.branch(self.root))


class NoGitProcessesTests(unittest.TestCase):
    """A full guard firing at a stable HEAD starts no `git` process."""

    def test_a_full_guard_firing_starts_no_git_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp) / "repo")
            with (
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                crumb.main(["init", "--project", str(root)])
                crumb.main(
                    [
                        "remember",
                        "attempt",
                        "--project",
                        str(root),
                        "--title",
                        "Deleted app/build/test-results while a test task ran",
                        "--set",
                        "Do Not Retry Unless",
                        "no Gradle daemon is running",
                        "--evidence",
                        "file",
                        "app/build/test-results",
                        "--confidence",
                        "low",
                    ]
                )
            payload = {
                "cwd": str(root),
                "session_id": "S",
                "tool_name": "Bash",
                "tool_input": {"command": "rm -rf app/build/test-results"},
            }

            def fire() -> tuple[dict, int]:
                _cli._IS_GIT_REPO_CACHE.clear()
                before = _cli.GIT_CALLS[0]
                old = sys.stdin
                sys.stdin = io.StringIO(json.dumps(payload))
                buf = io.StringIO()
                try:
                    with contextlib.redirect_stdout(buf):
                        crumb.main(["hook", "guard"])
                finally:
                    sys.stdin = old
                return json.loads(buf.getvalue()), _cli.GIT_CALLS[0] - before

            first, _spawned = fire()  # may build the commit-order cache
            self.assertIn("hookSpecificOutput", first)
            second, spawned = fire()
            self.assertIn("hookSpecificOutput", second)
            self.assertEqual(spawned, 0)
            log = (root / ".project-memory" / "private" / "hook-log.jsonl").read_text()
            last = json.loads(log.splitlines()[-1])
            self.assertEqual(last.get("git"), 0)
            self.assertIn("import_ms", last)
            self.assertIn("git_ms", last)
            from breadcrumbs import hooklog

            summary = hooklog.summarize(hooklog.read_log(root / ".project-memory"))
            phases = summary["events"]["guard"]["phases_p50"]
            self.assertEqual(sorted(phases), ["git", "git_ms", "import_ms"])


if __name__ == "__main__":
    unittest.main()
