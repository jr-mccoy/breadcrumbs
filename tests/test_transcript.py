"""Tests for the deterministic transcript miner (WM-14).

Four narrow rules over a JSONL transcript, and the three properties that make
them safe to run from a hook: they never raise, they never write a credential,
and they never write the same candidate twice.

Run with:  python -m pytest tests/
       or:  python tests/test_transcript.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import inbox as ibx  # noqa: E402
from breadcrumbs import transcript as tr  # noqa: E402
from _jsonl import bash, edit, tool_result, tool_use, user_text, write_transcript  # noqa: E402


def init_store(tmp: str) -> Path:
    root = Path(tmp)
    with contextlib.redirect_stdout(io.StringIO()):
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def kinds(candidates: list[tr.Candidate]) -> list[str]:
    return [c.kind for c in candidates]


# --------------------------------------------------------------------------- #


class ReadingTests(unittest.TestCase):
    def test_malformed_lines_are_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "t.jsonl"
            path.write_text(
                json.dumps(user_text("hello"))
                + "\n{ truncated\n"
                + "not json at all\n"
                + json.dumps({"type": "user"})  # no message key
                + "\n",
                encoding="utf-8",
            )
            entries = tr.read_transcript(path)
            self.assertEqual(len(entries), 2)
            self.assertEqual(tr.mine(entries)[0], [])

    def test_a_missing_file_is_empty_not_an_error(self):
        self.assertEqual(tr.read_transcript("/nonexistent/x.jsonl"), [])

    def test_only_the_tail_is_read_and_lines_stay_whole(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = [user_text(f"message number {i} " + "p" * 200) for i in range(400)]
            path = write_transcript(Path(tmp), entries)
            full = tr.read_transcript(path)
            self.assertEqual(len(full), 400)
            tail = tr.read_transcript(path, max_bytes=5_000)
            self.assertLess(len(tail), 400)
            self.assertGreater(len(tail), 0)
            # Every line that survived parses, which is the point: the seek
            # landed mid-record and that partial line was discarded.
            self.assertTrue(all(isinstance(e, dict) and e.get("message") for e in tail))


class NormalizeCommandTests(unittest.TestCase):
    def test_folds_the_shapes_a_retry_actually_differs_by(self):
        base = "python -m pytest tests/test_parser.py"
        for variant in (
            base,
            f"cd /repo && {base}",
            f"{base} 2>&1",
            f"{base} | head -20",
            f"cd /repo && {base} 2>&1 | tail -5",
            f"   {base}   ",
        ):
            with self.subTest(variant=variant):
                self.assertEqual(tr.normalize_command(variant), base)

    def test_it_is_bounded(self):
        self.assertLessEqual(len(tr.normalize_command("x " * 500)), tr.COMMAND_MAX_CHARS)


class PairingTests(unittest.TestCase):
    def test_a_bash_failure_is_detected_from_text_when_is_error_is_absent(self):
        calls = tr.pair_tool_calls(bash("c1", "pytest", "FAILED tests/x.py::test_a"))
        self.assertTrue(calls[0].is_error)

    def test_an_edit_is_not_a_failure_just_because_its_content_says_failed(self):
        entries = [
            tool_use(
                "c1", "Edit", {"file_path": "a.py", "new_string": "raise Exception('failed')"}
            ),
            tool_result("c1", "wrote failed handler"),
        ]
        self.assertFalse(tr.pair_tool_calls(entries)[0].is_error)

    def test_a_call_with_no_result_survives(self):
        """The session ended mid-tool: that it was attempted is still a fact."""
        calls = tr.pair_tool_calls([tool_use("c1", "Bash", {"command": "sleep 100"})])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].result_text, "")


class AttemptRuleTests(unittest.TestCase):
    def test_failed_then_edited_then_passed(self):
        entries = (
            bash("c1", "python -m pytest tests/test_parser.py", "FAILED - AssertionError: x")
            + edit("c2", "src/parser.py")
            + edit("c3", "tests/test_parser.py")
            + bash("c4", "cd /repo && python -m pytest tests/test_parser.py 2>&1", "2 passed")
        )
        found = [c for c in tr.mine(entries)[0] if c.kind == "attempt"]
        self.assertEqual(len(found), 1)
        c = found[0]
        self.assertIn("failed until 2 file(s) changed", c.title)
        self.assertEqual(c.files, ["src/parser.py", "tests/test_parser.py"])
        self.assertEqual(c.command, "python -m pytest tests/test_parser.py")
        self.assertIn({"type": "command", "ref": c.command}, c.evidence)
        self.assertIn({"type": "file", "ref": "src/parser.py"}, c.evidence)
        self.assertEqual(c.confidence, "low")

    def test_a_bare_retry_with_no_edit_is_not_an_attempt(self):
        """It passed on a rerun with nothing changed: that is flaky, not fixed."""
        entries = bash("c1", "pytest", "FAILED") + bash("c2", "pytest", "1 passed")
        self.assertNotIn("attempt", kinds(tr.mine(entries)[0]))

    def test_a_failure_that_never_passes_is_not_an_attempt(self):
        entries = (
            bash("c1", "pytest", "FAILED") + edit("c2", "a.py") + bash("c3", "pytest", "FAILED")
        )
        self.assertNotIn("attempt", kinds(tr.mine(entries)[0]))

    def test_it_is_capped(self):
        entries = []
        for i in range(tr.MAX_ATTEMPTS + 4):
            entries += (
                bash(f"f{i}", f"pytest tests/t{i}.py", "FAILED")
                + edit(f"e{i}", f"src/m{i}.py")
                + bash(f"p{i}", f"pytest tests/t{i}.py", "1 passed")
            )
        found = [c for c in tr.mine(entries)[0] if c.kind == "attempt"]
        self.assertLessEqual(len(found), tr.MAX_ATTEMPTS)


class VerificationRuleTests(unittest.TestCase):
    def test_a_passing_test_command_is_recorded_once(self):
        entries = bash("c1", "ruff check .", "All checks passed!") + bash(
            "c2", "ruff check . 2>&1", "All checks passed!"
        )
        found = [c for c in tr.mine(entries)[0] if c.kind == "verification"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].title, "ruff check . passed")
        self.assertEqual(found[0].evidence, [{"type": "command", "ref": "ruff check ."}])

    def test_a_failing_test_command_is_not_a_verification(self):
        entries = bash("c1", "pytest", "FAILED tests/x")
        self.assertNotIn("verification", kinds(tr.mine(entries)[0]))

    def test_an_arbitrary_command_is_not_a_verification(self):
        entries = bash("c1", "ls -la", "a b c")
        self.assertEqual(tr.mine(entries)[0], [])


class ChurnRuleTests(unittest.TestCase):
    def test_four_edits_to_one_file(self):
        entries = []
        for i in range(tr.CHURN_MIN_EDITS):
            entries += edit(f"c{i}", "src/hot.py")
        found = [c for c in tr.mine(entries)[0] if c.kind == "trap"]
        self.assertEqual(len(found), 1)
        self.assertIn("edited 4 times", found[0].title)
        self.assertEqual(found[0].files, ["src/hot.py"])

    def test_three_edits_is_not_churn(self):
        entries = []
        for i in range(tr.CHURN_MIN_EDITS - 1):
            entries += edit(f"c{i}", "src/warm.py")
        self.assertNotIn("trap", kinds(tr.mine(entries)[0]))


class CorrectionRuleTests(unittest.TestCase):
    def test_a_user_correction_is_captured(self):
        entries = [user_text("No, don't touch the migration, revert it")]
        found = [c for c in tr.mine(entries)[0] if c.kind == "correction"]
        self.assertEqual(len(found), 1)
        self.assertIn("revert it", found[0].note)

    def test_a_tool_result_is_never_a_correction(self):
        """`tool_result` arrives in a user-role message; error output is not the user."""
        entries = tool_result("c1", "Error: no such file", True)
        self.assertEqual(tr.mine([entries])[0], [])

    def test_ordinary_prose_containing_dont_is_not_a_correction(self):
        entries = [user_text("I don't think we need to change the parser, but check it")]
        self.assertEqual(tr.mine(entries)[0], [])

    def test_a_long_message_is_a_specification_not_a_correction(self):
        entries = [user_text("No, " + "and also " * 120)]
        self.assertEqual(tr.mine(entries)[0], [])


class RedactionTests(unittest.TestCase):
    def test_a_structured_credential_drops_the_candidate(self):
        self.assertIsNone(tr.redact_secrets("use AKIAIOSFODNN7EXAMPLE for the bucket"))
        self.assertIsNone(tr.redact_secrets("-----BEGIN RSA PRIVATE KEY-----"))

    def test_ordinary_text_passes_through_unchanged(self):
        text = "pytest tests/test_parser.py failed until 2 file(s) changed"
        self.assertEqual(tr.redact_secrets(text), text)

    def test_a_build_hash_is_not_treated_as_a_secret(self):
        """The high-entropy heuristic is warn-only and deliberately not used here."""
        text = "inputs_hash 9ae96adff345 matched after the rebuild"
        self.assertEqual(tr.redact_secrets(text), text)


class WriteCandidatesTests(unittest.TestCase):
    def _candidates(self, n: int) -> list[tr.Candidate]:
        return [
            tr.Candidate(kind="verification", title=f"command {i} passed", note=f"note {i}")
            for i in range(n)
        ]

    def test_candidates_become_private_jots(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            report = tr.write_candidates(mem, Path(tmp), self._candidates(2), session_id="s1")
            self.assertEqual(len(report["written"]), 2)
            for rec in ibx.load_jots(mem):
                self.assertTrue(ibx.is_private(mem, rec), "a mined jot must never be committed")
                self.assertEqual(rec.meta["source"], "transcript")
                self.assertEqual(rec.meta["host_session"], "s1")
                self.assertTrue(rec.meta["fingerprint"])
                self.assertIn("mined", rec.meta["tags"])
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    def test_the_headline_and_the_body_are_kept_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tr.write_candidates(
                mem,
                Path(tmp),
                [
                    tr.Candidate(
                        kind="trap",
                        title="src/x.py was edited 4 times",
                        note="Repeated edits suggest…",
                    )
                ],
                session_id="s1",
            )
            row = ibx.jot_rows(mem)[0]
            self.assertEqual(row["title"], "src/x.py was edited 4 times")
            self.assertIn("Repeated edits", row["text"])

    def test_writing_twice_writes_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            candidates = self._candidates(2)
            tr.write_candidates(mem, Path(tmp), candidates, session_id="s1")
            second = tr.write_candidates(mem, Path(tmp), candidates, session_id="s1")
            self.assertEqual(second["written"], [])
            self.assertEqual(second["skipped"], 2)
            self.assertEqual(len(ibx.load_jots(mem)), 2)

    def test_a_different_session_writes_again(self):
        """The same failure recurring in a later session is news again."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            candidates = self._candidates(1)
            tr.write_candidates(mem, Path(tmp), candidates, session_id="s1")
            tr.write_candidates(mem, Path(tmp), candidates, session_id="s2")
            self.assertEqual(len(ibx.load_jots(mem)), 2)

    def test_the_per_firing_cap_holds(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            report = tr.write_candidates(
                mem, Path(tmp), self._candidates(tr.MINER_MAX_JOTS_PER_FIRING + 4), session_id="s1"
            )
            self.assertEqual(len(report["written"]), tr.MINER_MAX_JOTS_PER_FIRING)
            self.assertEqual(report["skipped"], 4)

    def test_a_secret_bearing_candidate_is_dropped_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            report = tr.write_candidates(
                mem,
                Path(tmp),
                [
                    tr.Candidate(
                        kind="attempt",
                        title="deploy failed",
                        note="the key AKIAIOSFODNN7EXAMPLE was rejected",
                    )
                ],
                session_id="s1",
            )
            self.assertEqual(report["written"], [])
            self.assertEqual(report["dropped_for_secrets"], 1)
            self.assertEqual(ibx.load_jots(mem), [])


class CursorTests(unittest.TestCase):
    def test_mining_reports_how_far_it_read(self):
        entries = [user_text("hello"), user_text("No, stop that")]
        candidates, read_to = tr.mine(entries)
        self.assertEqual(read_to, 2)
        self.assertEqual(kinds(candidates), ["correction"])

    def test_since_index_skips_what_was_already_mined(self):
        entries = [user_text("No, stop that"), user_text("ordinary follow-up")]
        self.assertEqual(tr.mine(entries, since_index=1)[0], [])

    def test_end_to_end_mining_is_idempotent_across_firings(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            path = write_transcript(Path(tmp), bash("c1", "ruff check .", "All checks passed!"))
            first = tr.mine_transcript_into_jots(mem, Path(tmp), str(path), session_id="s1")
            second = tr.mine_transcript_into_jots(mem, Path(tmp), str(path), session_id="s1")
            self.assertEqual(len(first["written"]), 1)
            self.assertEqual(second["written"], [])
            self.assertEqual(len(ibx.load_jots(mem)), 1)

    def test_a_missing_transcript_is_an_empty_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            self.assertEqual(
                tr.mine_transcript_into_jots(mem, Path(tmp), None, session_id="s1")["written"], []
            )
            self.assertEqual(
                tr.mine_transcript_into_jots(mem, Path(tmp), "/nope.jsonl", session_id="s1")[
                    "written"
                ],
                [],
            )


class PerformanceTests(unittest.TestCase):
    def test_a_large_transcript_mines_quickly(self):
        """A hook has a time budget; the miner is the expensive part of it."""
        with tempfile.TemporaryDirectory() as tmp:
            entries = []
            for i in range(5000):
                entries += bash(f"c{i}", f"echo {i}", "ok " + "x" * 200)
            path = write_transcript(Path(tmp), entries)
            started = time.monotonic()
            mined = tr.mine(tr.read_transcript(path))[0]
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 5.0, f"mining 10k entries took {elapsed:.2f}s")
            self.assertEqual(mined, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
