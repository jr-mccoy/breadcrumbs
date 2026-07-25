"""Tests for `crumb resume` and the resume packet (Phase 4 — MVP-core / 19a).

Run with:  python -m pytest tests/
       or:  python -m unittest discover -s tests
       or:  python tests/test_resume.py
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

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402

FIXTURE = REPO_ROOT / "fixtures" / "fixture-01-fresh-resume"


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


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def copy_fixture(dest_parent: str) -> Path:
    """Copy the committed fixture's .project-memory into a NON-git tmp dir.

    Resolving git from the in-repo fixture would pick up this repo's branch/commit
    and make assertions non-deterministic; a plain copy yields the (no-git)
    sentinels and keeps the six-question test about content, not git state.
    """
    dest = Path(dest_parent)
    shutil.copytree(FIXTURE / ".project-memory", dest / crumb.MEMORY_DIRNAME)
    return dest


class FixtureSixQuestionsTests(unittest.TestCase):
    """§17 Fixture 1: a fresh resume must answer the six reorientation questions."""

    def test_fixture_validates(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = copy_fixture(tmp) / crumb.MEMORY_DIRNAME
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertEqual(fails, [], f"fixture should validate cleanly: {fails}")

    def test_resume_answers_six_questions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            code, out = run(["resume", "--project", str(root)])
            self.assertEqual(code, 0)
            # 1. What is the project?
            self.assertIn("demo-service", out)
            # 2. What is active? (active decision id surfaced)
            self.assertIn("dec_20260510_markdown-source-of-truth", out)
            # 3. What was decided? (rationale text)
            self.assertIn("no vendor lock-in", out)
            # 4. What failed before? (attempt id surfaced)
            self.assertIn("att_20260512_sqlite-store-too-heavy", out)
            # 5. What is next?
            self.assertIn("## Next Action", out)
            self.assertIn("build_resume_packet", out)
            # 6. What should not be retried? (do-not-retry condition)
            self.assertIn("do not retry:", out)
            self.assertIn("plain-file export is automatic", out)

    def test_no_raw_transcripts(self):
        """Packet summarizes records; it must not dump session bodies."""
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            _, out = run(["resume", "--project", str(root)])
            # Session-only body headings/content must not leak into the packet.
            self.assertNotIn("## Starting Context", out)
            self.assertNotIn("## Work Completed", out)


class ResumeJsonTests(unittest.TestCase):
    def test_json_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            code, out = run(["resume", "--project", str(root), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            for key in (
                "source", "project", "current_focus", "next_action",
                "active_decisions", "failed_attempts", "known_traps",
                "open_questions", "warnings", "approx_tokens",
            ):
                self.assertIn(key, payload)
            self.assertEqual(len(payload["active_decisions"]), 1)
            self.assertEqual(payload["active_decisions"][0]["id"], "dec_20260510_markdown-source-of-truth")
            self.assertIn("inputs_hash", payload["source"])
            self.assertIn("generated_at", payload["source"])
            self.assertTrue(payload["warnings"], "fixture should compute staleness warnings")


class SourceHeaderTests(unittest.TestCase):
    def test_packet_carries_source_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            run(["capture", "session", "--project", tmp, "--fast", "--next", "x"])
            _, out = run(["resume", "--project", tmp])
            self.assertIn(crumb.GENERATED_MARKER, out)
            self.assertRegex(out, r"source_commit:\s*\S+")
            self.assertRegex(out, r"inputs_hash:\s*[0-9a-f]{12}")
            self.assertRegex(out, r"generated_at:\s*\S+")


class FastModeTests(unittest.TestCase):
    def test_fast_drops_record_sections_keeps_reorientation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            _, out = run(["resume", "--project", str(root), "--fast"])
            self.assertIn("## Current Focus", out)
            self.assertIn("## Next Action", out)
            self.assertIn("## Stale / Risk Warnings", out)
            # Reduced view: no fuller record summaries.
            self.assertNotIn("## Active Decisions", out)
            self.assertNotIn("## Failed Attempts", out)

    def test_fast_does_not_overwrite_committed_packet(self):
        """--fast is print-only; it must not clobber the full cloud-fallback artifact."""
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)
            mem = root / crumb.MEMORY_DIRNAME
            run(["resume", "--project", str(root)])  # full packet -> writes the file
            full = (mem / "generated" / "resume-packet.md").read_text()
            self.assertIn("## Active Decisions", full)
            run(["resume", "--project", str(root), "--fast"])  # must not rewrite it
            still = (mem / "generated" / "resume-packet.md").read_text()
            self.assertEqual(full, still)


class TokenBoundTests(unittest.TestCase):
    def test_many_records_stay_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = root / crumb.MEMORY_DIRNAME
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            # Synthesize many decisions directly (faster than 40 CLI round-trips).
            for i in range(40):
                crumb.write_record(
                    mem, root, "decision",
                    f"decision number {i} about subsystem {i}",
                    {"Rationale": "because " + ("context " * 20)},
                    evidence=[{"type": "commit", "ref": "abc1234"}],
                )
            code, out = run(["resume", "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertLessEqual(payload["approx_tokens"], crumb.TOKEN_BUDGET_MAX)
            # Per-section cap + budget trim must have kicked in.
            self.assertLessEqual(len(payload["active_decisions"]), crumb.SECTION_CAPS["active_decisions"])
            self.assertGreater(payload["omitted"].get("active_decisions", 0), 0)


class StalenessAgeDistanceTests(unittest.TestCase):
    def test_age_and_commit_distance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = root / crumb.MEMORY_DIRNAME
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            run(["capture", "session", "--project", tmp, "--fast", "--next", "x"])
            # Backdate the handoff timestamp; keep its recorded commit, then advance HEAD.
            handoff = mem / "handoff.md"
            text = re.sub(
                r"_Last updated:.*_",
                "_Last updated: 2020-01-01T00:00:00-05:00_",
                handoff.read_text(),
            )
            handoff.write_text(text)
            commit(root, "a.txt", "c1")
            commit(root, "b.txt", "c2")
            commit(root, "c.txt", "c3")
            _, out = run(["resume", "--project", tmp])
            self.assertIn("commit(s) behind current HEAD", out)
            self.assertRegex(out, r"handoff is \d+ day\(s\) old")
            self.assertIn("3 commit(s) behind", out)


class BranchMismatchTests(unittest.TestCase):
    def test_handoff_branch_mismatch_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            run(["capture", "session", "--project", tmp, "--fast", "--next", "x"])
            git(root, "checkout", "-q", "-b", "feature-branch")
            _, out = run(["resume", "--project", tmp])
            self.assertIn("branch mismatch", out)
            self.assertIn("feature-branch", out)


class CloudFallbackTests(unittest.TestCase):
    """§19a.7 / Fixture 9 preview: the committed packet supports CLI-less resume."""

    def _ignored(self, root: Path, rel: str) -> bool:
        r = subprocess.run(
            ["git", "check-ignore", rel], cwd=str(root), capture_output=True, text=True
        )
        return r.returncode == 0

    def test_committed_packet_is_self_sufficient_and_tracked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = root / crumb.MEMORY_DIRNAME
            # Default policy commits generated projections.
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            run([
                "remember", "decision", "--project", tmp,
                "--title", "Keep memory in plain files",
                "--set", "Rationale", "a read-only cloud agent can read them",
                "--evidence", "commit", "abc1234",
            ])
            run(["capture", "session", "--project", tmp, "--fast", "--next", "ship the fallback"])
            run(["resume", "--project", tmp])

            packet = mem / "generated" / "resume-packet.md"
            self.assertTrue(packet.is_file(), "resume must write the committed packet artifact")
            rel = str(packet.relative_to(root))
            self.assertFalse(
                self._ignored(root, rel),
                "with commit_generated_projections: true the packet must be tracked",
            )
            # A CLI-less agent reads ONLY this file and still reorients.
            text = packet.read_text()
            self.assertIn("# Resume Packet", text)
            self.assertIn("ship the fallback", text)
            self.assertIn("a read-only cloud agent can read them", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
