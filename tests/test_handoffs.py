"""Tests for one handoff per branch (WM-50, schema 4).

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import handoffs, migrate  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
    ).stdout


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def repo_with_store(tmp: str) -> tuple[Path, Path]:
    root = Path(tmp)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("a\n")
    git(root, "add", "f.txt")
    git(root, "commit", "-qm", "initial")
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    git(root, "add", "-A")
    git(root, "commit", "-qm", "store")
    return root, root / crumb.MEMORY_DIRNAME


def capture(tmp: str, next_action: str, *extra: str) -> dict:
    code, out = run(
        ["capture", "session", "--project", tmp, "--fast", "--next", next_action, "--json", *extra]
    )
    assert code == 0, out
    return json.loads(out)


class BranchHandoffTests(unittest.TestCase):
    def test_a_feature_branch_capture_writes_its_own_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            capture(tmp, "ship the main-line fix")
            main_handoff = (mem / "handoff.md").read_text("utf-8")
            git(root, "checkout", "-q", "-b", "feature/parser-rewrite")
            res = capture(tmp, "finish the parser rewrite")
            branch_file = mem / "handoffs" / "feature-parser-rewrite.md"
            self.assertEqual(Path(res["handoff"]), branch_file)
            self.assertIn("finish the parser rewrite", branch_file.read_text("utf-8"))
            self.assertIn("_Branch: feature/parser-rewrite_", branch_file.read_text("utf-8"))
            self.assertEqual((mem / "handoff.md").read_text("utf-8"), main_handoff)

    def test_resume_reads_the_branch_handoff_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            capture(tmp, "ship the main-line fix")
            git(root, "checkout", "-q", "-b", "feature-x")
            capture(tmp, "finish feature x")
            packet = crumb.build_resume_packet(mem, root)
            self.assertIn("finish feature x", packet["next_action"])
            self.assertEqual(packet["project"]["handoff"], "handoffs/feature-x.md")
            self.assertIn("handoff: handoffs/feature-x.md", crumb.render_packet_markdown(packet))
            # No branch mismatch: the chosen file was written on this branch.
            self.assertFalse(any("branch mismatch" in w for w in packet["warnings"]))

            git(root, "checkout", "-q", "main")
            packet = crumb.build_resume_packet(mem, root)
            self.assertIn("ship the main-line fix", packet["next_action"])
            self.assertEqual(packet["project"]["handoff"], "handoff.md")

    def test_a_branch_with_no_handoff_falls_back_and_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            capture(tmp, "ship the main-line fix")
            git(root, "checkout", "-q", "-b", "feature-new")
            packet = crumb.build_resume_packet(mem, root)
            self.assertEqual(packet["project"]["handoff"], "handoff.md (no branch handoff)")
            self.assertIn("ship the main-line fix", packet["next_action"])

    def test_the_first_branch_capture_carries_the_focus_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            capture(tmp, "ship it", "--focus", "the parser rewrite")
            git(root, "checkout", "-q", "-b", "feature-y")
            capture(tmp, "keep going")
            text = (mem / "handoffs" / "feature-y.md").read_text("utf-8")
            self.assertIn("the parser rewrite", text)

    def test_a_schema3_store_keeps_one_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            migrate.set_manifest_version(mem, 3)
            git(root, "checkout", "-q", "-b", "feature-z")
            res = capture(tmp, "on the old layout")
            self.assertEqual(Path(res["handoff"]), mem / "handoff.md")

    def test_without_git_everything_is_handoff_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            res = capture(tmp, "no git here")
            self.assertEqual(Path(res["handoff"]), Path(tmp) / crumb.MEMORY_DIRNAME / "handoff.md")

    def test_origin_head_names_the_default_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _mem = repo_with_store(tmp)
            git(root, "branch", "trunk")
            git(root, "update-ref", "refs/remotes/origin/trunk", "HEAD")
            git(root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
            self.assertEqual(handoffs.default_branch(root), "trunk")
            # …so `main` is now a feature branch like any other.
            self.assertEqual(
                handoffs.write_path(root / crumb.MEMORY_DIRNAME, root, "main").name, "main.md"
            )


class PruneTests(unittest.TestCase):
    def test_prune_removes_an_old_orphan_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            capture(tmp, "main work")
            for branch in ("gone-branch", "live-branch"):
                git(root, "checkout", "-q", "-b", branch)
                capture(tmp, f"work on {branch}")
                git(root, "checkout", "-q", "main")
            git(root, "branch", "-D", "gone-branch")
            # Too young to prune yet.
            self.assertEqual(handoffs.orphan_handoffs(mem, root), [])
            later = _cli._now() + timedelta(days=31)
            with mock.patch.object(_cli, "_now", return_value=later):
                code, out = run(["prune", "handoffs", "--dry-run", "--project", tmp, "--json"])
                self.assertEqual(
                    [o["path"] for o in json.loads(out)["items"]], ["handoffs/gone-branch.md"]
                )
                self.assertTrue((mem / "handoffs" / "gone-branch.md").exists())
                code, _ = run(["prune", "handoffs", "--project", tmp])
                self.assertEqual(code, 0)
            self.assertFalse((mem / "handoffs" / "gone-branch.md").exists())
            self.assertTrue((mem / "handoffs" / "live-branch.md").exists())

    def test_a_branch_that_only_exists_on_origin_is_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            git(root, "checkout", "-q", "-b", "pushed")
            capture(tmp, "work")
            git(root, "checkout", "-q", "main")
            git(root, "update-ref", "refs/remotes/origin/pushed", "pushed")
            git(root, "branch", "-D", "pushed")
            later = _cli._now() + timedelta(days=31)
            with mock.patch.object(_cli, "_now", return_value=later):
                self.assertEqual(handoffs.orphan_handoffs(mem, root), [])


class MigrationTests(unittest.TestCase):
    def test_step_4_adds_the_directory_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            mem = Path(tmp) / crumb.MEMORY_DIRNAME
            import shutil

            shutil.rmtree(mem / "handoffs")
            migrate.set_manifest_version(mem, 3)
            res = migrate.migrate(mem, Path(tmp))
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["to"], 4)
            self.assertTrue((mem / "handoffs" / ".gitkeep").exists())
            self.assertEqual(migrate._m4_branch_handoffs(mem, Path(tmp)), [])

    def test_init_creates_the_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            self.assertTrue((Path(tmp) / crumb.MEMORY_DIRNAME / "handoffs").is_dir())


if __name__ == "__main__":
    unittest.main(verbosity=2)
