"""Tests for `crumb resume` and the resume packet (MVP-core / 19a).

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
                "source",
                "project",
                "current_focus",
                "next_action",
                "active_decisions",
                "failed_attempts",
                "known_traps",
                "open_questions",
                "warnings",
                "approx_tokens",
            ):
                self.assertIn(key, payload)
            self.assertEqual(len(payload["active_decisions"]), 1)
            self.assertEqual(
                payload["active_decisions"][0]["id"], "dec_20260510_markdown-source-of-truth"
            )
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
                    mem,
                    root,
                    "decision",
                    f"decision number {i} about subsystem {i}",
                    {"Rationale": "because " + ("context " * 20)},
                    evidence=[{"type": "commit", "ref": "abc1234"}],
                )
            code, out = run(["resume", "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertLessEqual(payload["approx_tokens"], crumb.TOKEN_BUDGET_MAX)
            # Per-section cap + budget trim must have kicked in.
            self.assertLessEqual(
                len(payload["active_decisions"]), crumb.SECTION_CAPS["active_decisions"]
            )
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


class StalenessFieldNamingTests(unittest.TestCase):
    """The threshold and the measured ages are separate, distinctly named fields.

    `stale_days` used to be the only staleness number in the packet — a *threshold*
    named as if it were an age, while the actual age ("handoff is 6 day(s) old") was
    reachable only by parsing English out of a warning string.
    """

    def test_threshold_and_ages_are_separate_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = root / crumb.MEMORY_DIRNAME
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            run(["capture", "session", "--project", tmp, "--fast", "--next", "x"])
            handoff = mem / "handoff.md"
            handoff.write_text(
                re.sub(
                    r"_Last updated:.*_",
                    "_Last updated: 2020-01-01T00:00:00-05:00_",
                    handoff.read_text(),
                )
            )
            commit(root, "a.txt", "c1")
            commit(root, "b.txt", "c2")

            code, out = run(["resume", "--project", tmp, "--json", "--stale-days", "14"])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            # The threshold is the value the caller passed, under a name that says so.
            self.assertEqual(payload["stale_after_days"], 14)
            self.assertNotIn("stale_days", payload)
            # The measured age is data, not prose — and agrees with the prose.
            self.assertGreater(payload["handoff_age_days"], 365)
            self.assertEqual(payload["handoff_commit_distance"], 2)
            warning = next(w for w in payload["warnings"] if w.startswith("⚠ handoff is"))
            self.assertIn(f"{payload['handoff_age_days']} day(s) old", warning)

    def test_rendered_packet_names_the_cutoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            run(["capture", "session", "--project", tmp, "--fast", "--next", "x"])
            _, out = run(["resume", "--project", str(root), "--stale-days", "14"])
            self.assertIn("the cutoff is 14 days", out)

    def test_unknown_age_and_distance_are_null_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture(tmp)  # a store with no git repo around it
            code, out = run(["resume", "--project", str(root), "--json"])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["stale_after_days"], crumb.STALE_AGE_DAYS)
            self.assertIsNone(payload["handoff_commit_distance"])


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

    def _store_committed_on_feature_branch(self, root: Path, *, squash: bool = False) -> str:
        """Write the store on `feature-a`, land it on the original branch, return that branch."""
        base = crumb.git_branch(root)
        git(root, "checkout", "-q", "-b", "feature-a")
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
        run(["capture", "session", "--project", str(root), "--fast", "--next", "x"])
        crumb.main(
            [
                "remember",
                "decision",
                "--project",
                str(root),
                "--title",
                "written on the feature branch",
                "--set",
                "Decision",
                "chosen",
            ]
        )
        git(root, "add", "-A")
        git(root, "commit", "-qm", "memory: written on feature-a")
        git(root, "checkout", "-q", base)
        if squash:
            git(root, "merge", "-q", "--squash", "feature-a")
            git(root, "commit", "-qm", "squash of feature-a")
        else:
            git(root, "merge", "-q", "--no-ff", "-m", "merge feature-a", "feature-a")
        return base

    def test_merged_branch_is_not_a_mismatch(self):
        # Branch-per-session workflow: the handoff and every record name a
        # branch that has since been merged into HEAD. The files reached this
        # line of history, so there is nothing to warn about.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            base = self._store_committed_on_feature_branch(root)
            text = (root / crumb.MEMORY_DIRNAME / "handoff.md").read_text()
            self.assertIn("_Branch: feature-a_", text)  # the mismatch is real on paper
            self.assertNotEqual(base, "feature-a")
            _, out = run(["resume", "--project", str(root)])
            self.assertNotIn("branch mismatch", out)
            self.assertNotIn("written on other branches", out)

    def test_squash_merged_branch_is_not_a_mismatch(self):
        # A squash merge leaves no feature-a sha in HEAD's ancestry; the test is
        # on the file, so it still counts as landed.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._store_committed_on_feature_branch(root, squash=True)
            _, out = run(["resume", "--project", str(root)])
            self.assertNotIn("branch mismatch", out)
            self.assertNotIn("written on other branches", out)

    def test_modified_handoff_from_merged_branch_still_warns(self):
        # A worktree edit means the copy being read is not what HEAD holds; the
        # branch line then describes an unknown provenance again.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._store_committed_on_feature_branch(root)
            handoff = root / crumb.MEMORY_DIRNAME / "handoff.md"
            handoff.write_text(handoff.read_text() + "\n- an uncommitted edit\n")
            _, out = run(["resume", "--project", str(root)])
            self.assertIn("branch mismatch", out)
            self.assertIn("feature-a", out)

    def test_guard_path_drops_the_merged_handoff_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._store_committed_on_feature_branch(root)
            mem = root / crumb.MEMORY_DIRNAME
            meta = crumb.parse_handoff_meta((mem / "handoff.md").read_text())
            self.assertEqual(meta.get("branch"), "feature-a")
            risks = crumb.compute_staleness(
                root, meta, [], [], [], 30, risks_only=True, memory_dir=mem
            )
            self.assertEqual([w for w in risks if "branch mismatch" in w], [])
            # Without the store location the handoff file cannot be judged, so
            # the old unconditional report stands (callers that pass no
            # memory_dir keep their behaviour).
            legacy = crumb.compute_staleness(root, meta, [], [], [], 30, risks_only=True)
            self.assertTrue(any("branch mismatch" in w for w in legacy), legacy)

    def test_nested_project_root_is_resolved_against_the_repo_root(self):
        # The project (and its store) sits below the git toplevel: ls-tree and
        # status print repo-root-relative paths, so the prefix must be applied.
        with tempfile.TemporaryDirectory() as tmp:
            top = make_repo(tmp)
            root = top / "pkg" / "app"
            root.mkdir(parents=True)
            base = self._store_committed_on_feature_branch(root)
            self.assertNotEqual(base, "feature-a")
            _, out = run(["resume", "--project", str(root)])
            self.assertNotIn("branch mismatch", out)
            self.assertNotIn("written on other branches", out)


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
            run(
                [
                    "remember",
                    "decision",
                    "--project",
                    tmp,
                    "--title",
                    "Keep memory in plain files",
                    "--set",
                    "Rationale",
                    "a read-only cloud agent can read them",
                    "--evidence",
                    "commit",
                    "abc1234",
                ]
            )
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


class PacketTruthTests(unittest.TestCase):
    """0.1.10 field-test P1-5/P1-6: the packet's headline claims must be
    checkable, and Current Focus must not be a verbatim copy of Next Action."""

    def _init_and_capture(self, root: Path, next_action: str) -> None:
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
        crumb.main(["capture", "session", "--project", str(root), "--next", next_action, "--fast"])

    def test_capture_without_focus_does_not_duplicate_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._init_and_capture(root, "wire the flurble widget into the launcher")
            _, out = run(["resume", "--project", str(root), "--json"])
            packet = json.loads(out)
            self.assertEqual(packet["next_action"], "wire the flurble widget into the launcher")
            self.assertNotEqual(
                packet["current_focus"],
                packet["next_action"],
                "Current Focus must no longer mirror Next Action verbatim",
            )

    def test_explicit_focus_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            crumb.main(
                [
                    "capture",
                    "session",
                    "--project",
                    str(root),
                    "--next",
                    "run the flurble suite",
                    "--focus",
                    "flurble hardening sprint",
                    "--fast",
                ]
            )
            _, out = run(["resume", "--project", str(root), "--json"])
            packet = json.loads(out)
            self.assertEqual(packet["current_focus"], "flurble hardening sprint")

    def test_legacy_duplicate_focus_is_collapsed_at_render_time(self):
        packet_md = crumb.render_packet_markdown(
            {
                "fast": True,
                "source": {"commit": "c", "inputs_hash": "h", "generated_at": "now"},
                "stale_after_days": 21,
                "handoff_age_days": None,
                "handoff_commit_distance": None,
                "project": {
                    "name": "p",
                    "path": ".",
                    "branch": "b",
                    "commit": "c",
                    "dirty": 0,
                    "dirty_state": "clean",
                },
                "current_focus": "finish the rollout",
                "next_action": "finish the rollout",
                "warnings": [],
                "omitted": {},
                "omitted_reason": {},
            }
        )
        self.assertIn("_(same as Next Action)_", packet_md)
        self.assertEqual(packet_md.count("finish the rollout"), 1)

    def test_commits_since_handoff_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._init_and_capture(root, "ship the flurble widget")
            commit(root, "a.txt", "land the flurble widget")
            commit(root, "b.txt", "fix the spinner")
            _, out = run(["resume", "--project", str(root), "--json"])
            packet = json.loads(out)
            subjects = " ".join(packet["commits_since_handoff"])
            self.assertIn("land the flurble widget", subjects)
            self.assertIn("fix the spinner", subjects)
            _, md = run(["resume", "--project", str(root)])
            self.assertIn("Landed Since The Handoff", md)

    def test_no_commits_since_handoff_renders_no_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._init_and_capture(root, "anything")
            _, md = run(["resume", "--project", str(root)])
            self.assertNotIn("Landed Since The Handoff", md)

    def test_fixed_verification_contradicting_focus_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            crumb.main(
                [
                    "verify",
                    "flurble widget rollout",
                    "--project",
                    str(root),
                    "--status",
                    "fixed",
                    "--evidence",
                    "command",
                    "make test",
                ]
            )
            crumb.main(
                [
                    "capture",
                    "session",
                    "--project",
                    str(root),
                    "--next",
                    "finish the flurble widget rollout",
                    "--fast",
                ]
            )
            _, out = run(["resume", "--project", str(root), "--json"])
            packet = json.loads(out)
            drift = [w for w in packet["warnings"] if "possible drift" in w]
            self.assertTrue(drift, packet["warnings"])
            self.assertIn("flurble widget rollout", drift[0])

    def _verify_fixed_then_capture(self, root: Path, subject: str, next_action: str) -> list:
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
        crumb.main(
            [
                "verify",
                subject,
                "--project",
                str(root),
                "--status",
                "fixed",
                "--evidence",
                "command",
                "make test",
            ]
        )
        crumb.main(["capture", "session", "--project", str(root), "--next", next_action, "--fast"])
        _, out = run(["resume", "--project", str(root), "--json"])
        return [w for w in json.loads(out)["warnings"] if "possible drift" in w]

    def test_two_incidental_shared_words_do_not_count_as_drift(self):
        # Observed on the tool's own store: "remember --set validates section
        # headings exactly as capture session does" fired against a focus that
        # mentioned a CHANGELOG *section* and a work *session*. Two shared
        # stems out of seven is what any two sentences about one project share.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            drift = self._verify_fixed_then_capture(
                root,
                "remember --set validates section headings exactly as capture session does",
                "release: confirm the dated CHANGELOG section, then work a real session",
            )
            self.assertEqual(drift, [])

    def test_version_fragments_do_not_count_as_drift(self):
        # "0.1.11" tokenizes to a bare "11"; with the project's own name that
        # made two shared stems and a drift line about a verification whose
        # subject has nothing to do with the focus.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            drift = self._verify_fixed_then_capture(
                root,
                "crumb mark-status can retire a trap in 0.1.11",
                "crumb: PyPI latest is still 0.1.11 while __version__ says 0.1.12",
            )
            self.assertEqual(drift, [])

    def test_subject_mostly_restated_by_the_focus_is_drift(self):
        # The intended catch survives the tighter rule: the focus restates the
        # bulk of the subject (four of five stems, "cluster" dropped, "widgets"
        # inflected) among unrelated words.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            drift = self._verify_fixed_then_capture(
                root,
                "flurble widget rollout to the staging cluster",
                "finish the flurble widgets rollout to staging, then update the docs",
            )
            self.assertEqual(len(drift), 1, drift)
            self.assertIn("flurble widget rollout", drift[0])

    def test_open_verification_does_not_warn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            crumb.main(
                [
                    "verify",
                    "flurble widget rollout",
                    "--project",
                    str(root),
                    "--status",
                    "open",
                    "--evidence",
                    "command",
                    "make test",
                ]
            )
            crumb.main(
                [
                    "capture",
                    "session",
                    "--project",
                    str(root),
                    "--next",
                    "finish the flurble widget rollout",
                    "--fast",
                ]
            )
            _, out = run(["resume", "--project", str(root), "--json"])
            packet = json.loads(out)
            self.assertEqual([w for w in packet["warnings"] if "possible drift" in w], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
