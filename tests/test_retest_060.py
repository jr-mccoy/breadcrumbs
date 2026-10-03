"""The DoWhat retest of 0.6.0 (docs/reviews/2026-10-03-dowhat-0.6.0-retest-plan.md).

One class per item of the report. Each test failed at 60ff21b (0.6.0 plus the
health-review extraction) and passes after its fix.

Run with:  python -m unittest discover -s tests -p test_retest_060.py
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli  # noqa: E402
from breadcrumbs import git as _git  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    for key, value in (
        ("user.email", "t@t"),
        ("user.name", "t"),
        ("commit.gpgsign", "false"),
        # Git 2.47+ runs post-commit maintenance detached; keep the tree still.
        ("maintenance.auto", "false"),
        ("gc.auto", "0"),
    ):
        git(path, "config", key, value)
    (path / "f.txt").write_text("a\n")
    git(path, "add", "f.txt")
    git(path, "commit", "-qm", "initial")
    return path


def quiet(argv: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return crumb.main(argv)


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)


class GitSpy:
    """Counts every `git` process started while it is active, by argv."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __enter__(self):
        real = subprocess.Popen.__init__
        calls = self.calls

        def spy(popen, args, *a, **k):
            if (
                isinstance(args, (list, tuple))
                and args
                and Path(str(args[0])).name
                in (
                    "git",
                    "git.exe",
                )
            ):
                calls.append([str(x) for x in args[1:]])
            return real(popen, args, *a, **k)

        self._patch = mock.patch.object(subprocess.Popen, "__init__", spy)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


def fire_guard(root: Path, tool: str, tool_input: dict, session: str = "S") -> tuple[dict, list]:
    """One `crumb hook guard` firing, with fresh per-process memos, as the host runs it."""
    _git._IS_REPO_CACHE.clear()
    cli._OP_MEMO.clear() if hasattr(cli, "_OP_MEMO") else None
    payload = {"cwd": str(root), "session_id": session, "tool_name": tool, "tool_input": tool_input}
    old = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    buf = io.StringIO()
    try:
        with GitSpy() as spy, contextlib.redirect_stdout(buf):
            crumb.main(["hook", "guard"])
    finally:
        sys.stdin = old
    return json.loads(buf.getvalue() or "{}"), spy.calls


def set_handoff(root: Path, branch: str, commit: str) -> None:
    path = root / ".project-memory" / "handoff.md"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"_Branch: .*_", f"_Branch: {branch}_", text)
    text = re.sub(r"_Commit: .*_", f"_Commit: {commit}_", text)
    path.write_text(text, encoding="utf-8")


ATTEMPT = [
    "remember",
    "attempt",
    "--title",
    "Deleted app/build/test-results while a test task ran",
    "--set",
    "Do Not Retry Unless",
    "no Gradle daemon is running",
    "--evidence",
    "file",
    "app/build/test-results",
]
RM = {"command": "rm -rf app/build/test-results"}


# --------------------------------------------------------------------------- #
# Item 1: git processes on every guard firing
# --------------------------------------------------------------------------- #


class NoGitOnTheGuardHookTests(unittest.TestCase):
    """At a stable HEAD a full guard firing starts no `git` process, whatever
    branch the handoff and the matched records were written on."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(Path(self._tmp.name) / "repo")
        quiet(["init", "--project", str(self.root)])
        quiet([*ATTEMPT, "--project", str(self.root)])
        commit_all(self.root, "store")
        for i in range(3):
            (self.root / f"w{i}.txt").write_text(f"{i}\n")
            commit_all(self.root, f"work {i}")

    def tearDown(self):
        self._tmp.cleanup()

    def _settled_firing(self) -> tuple[dict, list]:
        fire_guard(self.root, "Bash", RM)  # may build the per-HEAD caches
        return fire_guard(self.root, "Bash", RM)

    def test_a_handoff_from_another_branch_costs_no_git(self):
        # The handoff's commit is behind HEAD and its branch is a cloud
        # session's: 0.6.0 asked git for the distance (2 processes) and whether
        # handoff.md had reached HEAD (3 more) on every firing.
        set_handoff(
            self.root, "claude/cloud-session-x1", git(self.root, "rev-parse", "--short", "HEAD~2")
        )
        commit_all(self.root, "handoff")
        out, calls = self._settled_firing()
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(calls, [])

    def test_a_record_from_another_branch_costs_no_git(self):
        # Cloud sessions write records on claude/… branches that are merged
        # later; scoring asks whether each matched one has reached HEAD.
        rec = next((self.root / ".project-memory" / "attempts").glob("*.md"))
        rec.write_text(
            re.sub(r"(?m)^branch: .*$", "branch: claude/cloud-session-x1", rec.read_text("utf-8")),
            encoding="utf-8",
        )
        quiet(["reindex", "--project", str(self.root)])
        commit_all(self.root, "record from a cloud branch")
        out, calls = self._settled_firing()
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(calls, [])

    def test_reached_head_still_tells_committed_from_modified(self):
        # The cached answer must be the answer git gave.
        from breadcrumbs import scoring

        rec = next((self.root / ".project-memory" / "attempts").glob("*.md"))
        rec.write_text(
            re.sub(r"(?m)^branch: .*$", "branch: claude/cloud-session-x1", rec.read_text("utf-8")),
            encoding="utf-8",
        )
        quiet(["reindex", "--project", str(self.root)])
        commit_all(self.root, "record from a cloud branch")
        memory = self.root / ".project-memory"

        def mismatch() -> bool:
            result = scoring.guard(memory, self.root, RM["command"])
            return any(m.get("branch_mismatch") for m in result["matches"] + result["history"])

        self.assertFalse(mismatch())  # committed and clean: it reached HEAD
        # CRLF in the work tree is how a Windows checkout (`core.autocrlf`)
        # holds the same text: it has reached HEAD all the same.
        rec.write_bytes(rec.read_bytes().replace(b"\n", b"\r\n"))
        self.assertFalse(mismatch())
        rec.write_bytes(rec.read_bytes().replace(b"\r\n", b"\n") + b"\nedited\n")
        self.assertTrue(mismatch())  # modified: not what HEAD has

    def test_the_dowhat_clone_layout_needs_no_git(self):
        # Shallow, blob-filtered, worktreeConfig, leftover REBASE_HEAD and
        # ORIG_HEAD. The origin is then removed, so any fetch would fail.
        set_handoff(
            self.root, "claude/cloud-session-x1", git(self.root, "rev-parse", "--short", "HEAD~1")
        )
        commit_all(self.root, "handoff")
        git(self.root, "config", "uploadpack.allowFilter", "true")
        clone = Path(self._tmp.name) / "DoWhat"
        git(
            Path(self._tmp.name),
            "clone",
            "-q",
            "--depth",
            "3",
            "--filter=blob:limit=1048576",
            "--no-local",
            self.root.resolve().as_uri(),
            str(clone),
        )
        git(clone, "config", "extensions.worktreeConfig", "true")
        git(clone, "config", "--worktree", "core.sparseCheckout", "false")
        git(clone, "config", "maintenance.auto", "false")
        head = git(clone, "rev-parse", "HEAD")
        (clone / ".git" / "REBASE_HEAD").write_text(head + "\n")
        (clone / ".git" / "ORIG_HEAD").write_text(head + "\n")
        self.assertTrue((clone / ".git" / "shallow").is_file())
        shutil.rmtree(self.root)
        quiet(["reindex", "--project", str(clone)])
        fire_guard(clone, "Bash", RM)
        out, calls = fire_guard(clone, "Bash", RM)
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
