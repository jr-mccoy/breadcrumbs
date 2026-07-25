"""Tests for `crumb init` (Phase 1).

Run with:  python -m pytest tests/         (if pytest is installed)
       or:  python tests/test_init.py       (stdlib-only fallback runner)

Covers the §5 tree, manifest policies, .gitignore policy writing, the
full/distillate x git/non-git matrix, the clobber guard, and JSON output.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Make crumb.py importable regardless of cwd.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402


# Files/dirs the §5 tree must contain after init.
EXPECTED_TREE = [
    "README.md",
    "manifest.yml",
    "current.md",
    "handoff.md",
    "open-questions.md",
    "known-traps.md",
    "decisions/.gitkeep",
    "attempts/.gitkeep",
    "sessions/.gitkeep",
    "ideas/.gitkeep",
    "evidence/refs.yml",
    "generated/README.md",
    "generated/resume-packet.md",
    "private/README.md",
    "index/README.md",
]


def run_init(root: Path, *extra: str):
    """Invoke the init command in-process; returns the exit code."""
    argv = ["init", "--project", str(root), *extra]
    return crumb.main(argv)


def parse_manifest(memory_dir: Path) -> dict:
    """Tiny key: value parser sufficient for the flat manifest."""
    out: dict[str, str] = {}
    for line in (memory_dir / "manifest.yml").read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        out[key.strip()] = val.strip()
    return out


def git_init(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True)


class InitTreeTests(unittest.TestCase):
    def test_creates_full_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code = run_init(root, "--session-tracking", "full")
            self.assertEqual(code, 0)
            memory = root / ".project-memory"
            for rel in EXPECTED_TREE:
                self.assertTrue((memory / rel).exists(), f"missing {rel}")

    def test_manifest_records_both_policies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_init(root, "--session-tracking", "full")
            m = parse_manifest(root / ".project-memory")
            self.assertEqual(m["schema_version"], "1")
            self.assertEqual(m["project"], root.resolve().name)
            self.assertEqual(m["session_tracking"], "full")
            self.assertEqual(m["commit_generated_projections"], "true")
            self.assertIn("created_at", m)

    def test_clobber_guard_then_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertEqual(run_init(root, "--session-tracking", "full"), 0)
            # second run without --force must refuse
            self.assertEqual(run_init(root, "--session-tracking", "full"), 1)
            # with --force it succeeds
            self.assertEqual(run_init(root, "--session-tracking", "distillate", "--force"), 0)
            m = parse_manifest(root / ".project-memory")
            self.assertEqual(m["session_tracking"], "distillate")


class GitignorePolicyTests(unittest.TestCase):
    def read_gitignore(self, root: Path) -> str:
        return (root / ".gitignore").read_text()

    def test_full_committed_generated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_init(root, "--session-tracking", "full")
            gi = self.read_gitignore(root)
            self.assertIn(".project-memory/private/**", gi)
            self.assertIn(".project-memory/index/**", gi)
            self.assertIn("!.project-memory/index/README.md", gi)
            # generated committed -> no blanket generated/*.md ignore
            self.assertNotIn(".project-memory/generated/*.md", gi)
            # full -> sessions are committed (not ignored)
            self.assertNotIn(".project-memory/sessions/", gi)

    def test_distillate_ignores_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_init(root, "--session-tracking", "distillate")
            gi = self.read_gitignore(root)
            self.assertIn(".project-memory/sessions/", gi)

    def test_no_commit_generated_ignores_generated_md_but_keeps_readme(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_init(root, "--session-tracking", "full", "--no-commit-generated")
            gi = self.read_gitignore(root)
            self.assertIn(".project-memory/generated/*.md", gi)
            self.assertIn("!.project-memory/generated/README.md", gi)
            m = parse_manifest(root / ".project-memory")
            self.assertEqual(m["commit_generated_projections"], "false")

    def test_gitignore_block_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # pre-existing user content must be preserved
            (root / ".gitignore").write_text("node_modules/\n")
            run_init(root, "--session-tracking", "full")
            run_init(root, "--session-tracking", "distillate", "--force")
            gi = self.read_gitignore(root)
            self.assertIn("node_modules/", gi)
            # exactly one managed block
            self.assertEqual(gi.count(crumb.GITIGNORE_BEGIN), 1)
            self.assertEqual(gi.count(crumb.GITIGNORE_END), 1)
            # second run's policy (distillate) is what remains
            self.assertIn(".project-memory/sessions/", gi)


class GitDetectionTests(unittest.TestCase):
    def test_non_git_succeeds_with_json_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # capture JSON to confirm git_repo flag + notice
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = run_init(root, "--session-tracking", "full", "--json")
            self.assertEqual(code, 0)
            summary = json.loads(buf.getvalue())
            self.assertFalse(summary["git_repo"])
            self.assertIn("git_notice", summary)
            self.assertEqual(summary["session_tracking"], "full")

    def test_git_repo_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git_init(root)
            import io
            import contextlib

            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = run_init(root, "--session-tracking", "distillate", "--json")
            self.assertEqual(code, 0)
            summary = json.loads(buf.getvalue())
            self.assertTrue(summary["git_repo"])
            self.assertNotIn("git_notice", summary)
            self.assertEqual(summary["session_tracking"], "distillate")


if __name__ == "__main__":
    unittest.main(verbosity=2)
