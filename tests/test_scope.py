"""Tests for branch-scoped records (WM-52).

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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import inbox, mcp_core  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


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
    git(root, "checkout", "-q", "-b", "feature-a")
    return root, root / crumb.MEMORY_DIRNAME


class ScopeTests(unittest.TestCase):
    def test_a_branch_scoped_jot_leaves_the_packet_on_another_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            code, out = run(
                [
                    "jot",
                    "the parser rewrite half-done",
                    "--scope",
                    "branch",
                    "--project",
                    tmp,
                    "--json",
                ]
            )
            self.assertEqual(code, 0, out)
            jid = json.loads(out)["id"]
            self.assertEqual(crumb.find_record_by_id(mem, jid).meta["scope"], "branch")
            ids = [j["id"] for j in crumb.build_resume_packet(mem, root)["inbox"]]
            self.assertIn(jid, ids)
            git(root, "checkout", "-q", "-b", "other")
            ids = [j["id"] for j in crumb.build_resume_packet(mem, root)["inbox"]]
            self.assertNotIn(jid, ids)
            # …but search still finds it.
            matches, _ = crumb.search(mem, root, "parser rewrite", include_ideas=True)
            self.assertIn(jid, [m["id"] for m in matches])

    def test_a_project_jot_stays_everywhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            jid = inbox.write_jot(mem, root, "the flaky test is timing dependent")["id"]
            self.assertEqual(crumb.find_record_by_id(mem, jid).meta["scope"], "project")
            git(root, "checkout", "-q", "-b", "other")
            ids = [j["id"] for j in crumb.build_resume_packet(mem, root)["inbox"]]
            self.assertIn(jid, ids)

    def test_hook_written_jots_default_to_branch_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            res = inbox.write_jot(mem, root, "mined from the transcript", local=True, source="stop")
            self.assertEqual(crumb.find_record_by_id(mem, res["id"]).meta["scope"], "branch")

    def test_a_branch_scoped_verification_is_live_only_on_its_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            code, out = run(
                [
                    "verify",
                    "src/parser.py still fails on nested input",
                    "--status",
                    "regressed",
                    "--scope",
                    "branch",
                    "--evidence",
                    "file",
                    "src/parser.py",
                    "--project",
                    tmp,
                    "--json",
                ]
            )
            self.assertEqual(code, 0, out)
            vid = json.loads(out)["id"]
            action = "edit src/parser.py"
            here = crumb.guard(mem, root, action, files=["src/parser.py"])
            self.assertIn(vid, [m["id"] for m in here["matches"]])
            self.assertIn(
                vid, [v["id"] for v in crumb.build_resume_packet(mem, root)["verifications"]]
            )

            git(root, "checkout", "-q", "main")
            there = crumb.guard(mem, root, action, files=["src/parser.py"])
            self.assertNotIn(vid, [m["id"] for m in there["matches"]])
            self.assertIn(vid, [m["id"] for m in there["history"]])
            self.assertNotIn(
                vid, [v["id"] for v in crumb.build_resume_packet(mem, root)["verifications"]]
            )

    def test_a_project_verification_is_live_on_every_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            vid = crumb.verify(
                mem,
                root,
                "src/parser.py fails on nested input",
                status="regressed",
                evidence=[{"type": "file", "ref": "src/parser.py"}],
            )["id"]
            git(root, "checkout", "-q", "main")
            g = crumb.guard(mem, root, "edit src/parser.py", files=["src/parser.py"])
            self.assertIn(vid, [m["id"] for m in g["matches"]])

    def test_mcp_writers_take_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = repo_with_store(tmp)
            res = mcp_core.tool_jot("scoped over mcp", scope="branch", root=tmp)
            self.assertEqual(crumb.find_record_by_id(mem, res["id"]).meta["scope"], "branch")
            res = mcp_core.tool_verify(
                "checked over mcp", "fixed", scope="branch", root=tmp, allow_duplicate=True
            )
            self.assertEqual(crumb.find_record_by_id(mem, res["id"]).meta["scope"], "branch")

    def test_without_git_nothing_is_elsewhere(self):
        self.assertFalse(
            crumb.branch_scoped_elsewhere({"scope": "branch", "branch": "x"}, crumb.NO_GIT_BRANCH)
        )
        self.assertFalse(crumb.branch_scoped_elsewhere({"scope": "project", "branch": "x"}, "y"))
        self.assertTrue(crumb.branch_scoped_elsewhere({"scope": "branch", "branch": "x"}, "y"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
