"""`breadcrumbs.git` is the one owner of git state (deferred health review, 2.2).

Git used to be read two ways: `cli._git_out` started `git` and `gitrefs` read
`.git`, and a short sha from one was compared by string with a full sha from
the other (field-report item N8). These tests pin the module's answers against
git itself, its fall-back to `git` where the disk reader cannot answer, and the
rule that no other module starts `git` or reads `.git` on its own.

Run with:  python -m unittest discover -s tests -p test_git.py
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from breadcrumbs import git as _git  # noqa: E402
from breadcrumbs import gitrefs  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path: Path, branch: str = "main", commit: bool = True) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    git(path, "config", "user.email", "t@t")
    git(path, "config", "user.name", "t")
    if commit:
        (path / "f.txt").write_text("a\n")
        git(path, "add", "f.txt")
        git(path, "commit", "-qm", "initial")
    return path


class HeadTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = make_repo(self.tmp / "repo")

    def tearDown(self):
        self._tmp.cleanup()

    def test_head_is_the_full_sha(self):
        self.assertEqual(_git.head(self.root), git(self.root, "rev-parse", "HEAD"))

    def test_head_asks_git_when_the_disk_reader_cannot_answer(self):
        with mock.patch.object(gitrefs, "head_sha", return_value=None):
            before = _git.CALLS[0]
            self.assertEqual(_git.head(self.root), git(self.root, "rev-parse", "HEAD"))
            self.assertGreater(_git.CALLS[0], before)

    def test_head_without_spawning_reads_disk_only(self):
        before = _git.CALLS[0]
        self.assertEqual(_git.head(self.root, spawn=False), git(self.root, "rev-parse", "HEAD"))
        with mock.patch.object(gitrefs, "head_sha", return_value=None):
            self.assertIsNone(_git.head(self.root, spawn=False))
        self.assertEqual(_git.CALLS[0], before)

    def test_short_head_abbreviates_head(self):
        short = _git.short_head(self.root)
        self.assertEqual(short, git(self.root, "rev-parse", "--short", "HEAD"))
        self.assertTrue(_git.head(self.root).startswith(short))
        self.assertTrue(_git.same_commit(short, _git.head(self.root)))

    def test_an_unborn_branch_has_a_name_but_no_head(self):
        fresh = make_repo(self.tmp / "fresh", branch="trunk", commit=False)
        self.assertIsNone(_git.head(fresh))
        self.assertEqual(_git.short_head(fresh), _git.NO_COMMIT)
        self.assertEqual(_git.branch(fresh), "trunk")

    def test_outside_a_repo(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        with mock.patch.dict("os.environ", {"GIT_CEILING_DIRECTORIES": str(self.tmp)}):
            self.assertFalse(_git.is_repo(plain))
            self.assertIsNone(_git.head(plain))
            self.assertEqual(_git.short_head(plain), _git.NO_COMMIT)
            self.assertEqual(_git.branch(plain), _git.NO_BRANCH)
            self.assertEqual(_git.status_paths(plain), [])
            self.assertIsNone(_git.branch_names(plain))


class SameCommitTests(unittest.TestCase):
    def test_any_abbreviation_of_one_commit_is_the_same_commit(self):
        full = "0123456789abcdef0123456789abcdef01234567"
        self.assertTrue(_git.same_commit("0123456", full))
        self.assertTrue(_git.same_commit("0123456789ab", "0123456"))
        self.assertTrue(_git.same_commit(full, full))

    def test_different_or_too_short_ids_are_not(self):
        self.assertFalse(_git.same_commit("0123456", "0123457"))
        self.assertFalse(_git.same_commit("012", "0123456"))
        self.assertFalse(_git.same_commit("", "0123456"))
        self.assertFalse(_git.same_commit(_git.NO_COMMIT, "0123456"))
        self.assertTrue(_git.same_commit(_git.NO_COMMIT, _git.NO_COMMIT))


class CheckIgnoreTests(unittest.TestCase):
    def test_reports_the_rule_and_its_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp) / "repo")
            (root / ".gitignore").write_text("build/\n!keep/\n")
            (root / "build").mkdir()  # `build/` matches a directory only
            matches = _git.check_ignore(root, ["build", "src"])
            self.assertEqual(matches, [(".gitignore", "build/", "build")])


class OwnershipTests(unittest.TestCase):
    """Only `breadcrumbs/git.py` starts `git` or reads `.git` (via `gitrefs`)."""

    SPAWN = re.compile(r"""\[\s*["']git["']\s*,""")
    READER = re.compile(r"\bgitrefs\b")

    def test_no_other_module_starts_git_or_reads_dot_git(self):
        offenders = []
        for path in sorted((REPO_ROOT / "breadcrumbs").rglob("*.py")):
            if path.name in ("git.py", "gitrefs.py"):
                continue
            text = path.read_text(encoding="utf-8")
            for n, line in enumerate(text.splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue
                if self.SPAWN.search(line) or self.READER.search(line):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT).as_posix()}:{n}: {line.strip()}"
                    )
        self.assertEqual(offenders, [], "use breadcrumbs.git instead:\n" + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
