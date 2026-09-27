"""Truthful tool-call outcomes in the transcript miner (audit F01, WP02).

A call with no result used to count as a success, so an unanswered `pytest`
became a "pytest passed" candidate. Failure was detected on a 400-character
excerpt, so a failure printed later read as a pass. And "15 passed, 0 failed"
matched the failure pattern. These pin the replacement: every call has an
explicit outcome, only a received success is ever "passed", and an attempt
states the sequence it saw rather than a cause.

The result shapes below are the ones Claude Code writes: a non-zero exit sets
`is_error` and starts the text with `Exit code N`, a blocked call is a
`<tool_use_error>`, and a Bash entry carries `toolUseResult.interrupted`.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from breadcrumbs import transcript as tr  # noqa: E402
from _jsonl import bash, edit, tool_result, tool_use  # noqa: E402


def titles(entries: list[dict], kind: str | None = None) -> list[str]:
    return [c.title for c in tr.mine(entries)[0] if kind is None or c.kind == kind]


def outcome(entries: list[dict]) -> str:
    return tr.pair_tool_calls(entries)[0].outcome


def with_structured(entry: dict, **fields) -> dict:
    return {**entry, "toolUseResult": {"stdout": "", "stderr": "", "interrupted": False, **fields}}


class MissingResultTests(unittest.TestCase):
    def test_missing_result_never_produces_passed_candidate(self):
        entries = [tool_use("a", "Bash", {"command": "python -m pytest"})]
        call = tr.pair_tool_calls(entries)[0]
        self.assertFalse(call.result_received)
        self.assertEqual(call.outcome, tr.UNKNOWN)
        self.assertFalse(call.is_error)  # not a failure either
        self.assertEqual(tr.mine(entries)[0], [])

    def test_an_unanswered_rerun_does_not_close_an_attempt(self):
        entries = (
            bash("a", "pytest", "FAILED tests/x.py", is_error=True)
            + edit("b", "src/x.py")
            + [tool_use("c", "Bash", {"command": "pytest"})]
        )
        self.assertEqual(titles(entries, "attempt"), [])


class ExcerptTests(unittest.TestCase):
    def test_failure_after_excerpt_limit_is_failure(self):
        text = "x" * 450 + "\nFAILED test_real_failure"
        entries = bash("a", "pytest", text)
        call = tr.pair_tool_calls(entries)[0]
        self.assertEqual(call.outcome, tr.FAILURE)
        # The excerpt is still bounded, and shows the failure rather than the wall.
        self.assertLessEqual(len(call.result_text), tr.RESULT_SNIPPET_CHARS)
        self.assertIn("FAILED test_real_failure", call.result_text)
        self.assertEqual(titles(entries, "verification"), [])

    def test_an_early_failure_keeps_the_head_of_the_output(self):
        call = tr.pair_tool_calls(bash("a", "pytest", "FAILED at once " + "y" * 900))[0]
        self.assertTrue(call.result_text.startswith("FAILED at once"))
        self.assertEqual(len(call.result_text), tr.RESULT_SNIPPET_CHARS)


class ZeroCountTests(unittest.TestCase):
    def test_zero_failed_summary_is_not_failure(self):
        for text in (
            "15 passed, 0 failed",
            "test result: ok. 3 passed; 0 failed; 0 ignored",
            "Tests: 12 passed. failures: 0",
            "Found no errors",
            "0 errors, 0 warnings",
        ):
            with self.subTest(text=text):
                entries = bash("a", "npm test", text)
                self.assertEqual(outcome(entries), tr.SUCCESS)
                self.assertEqual(titles(entries, "verification"), ["npm test passed"])

    def test_a_real_failure_count_is_still_a_failure(self):
        for text in ("14 passed, 1 failed", "10 failed", "0 failed ... then 2 failed on retry"):
            with self.subTest(text=text):
                self.assertEqual(outcome(bash("a", "npm test", text)), tr.FAILURE)

    def test_a_test_named_after_failure_is_not_a_failure(self):
        self.assertEqual(
            outcome(bash("a", "pytest", "test_failed_login_is_rejected PASSED\n1 passed")),
            tr.SUCCESS,
        )


class CausalityTests(unittest.TestCase):
    def test_edit_then_success_does_not_assert_unproven_causality(self):
        entries = (
            bash("a", "pytest tests/x.py", "Exit code 1\nFAILED tests/x.py::t", is_error=True)
            + edit("b", "src/x.py")
            + bash("c", "pytest tests/x.py", "1 passed")
        )
        found = [c for c in tr.mine(entries)[0] if c.kind == "attempt"]
        self.assertEqual(len(found), 1)
        title, note = found[0].title, found[0].note
        self.assertEqual(title, "pytest tests/x.py failed, then passed after 1 file(s) changed")
        for causal in ("until", "fixed", "Fixed", "because"):
            self.assertNotIn(causal, title)
        self.assertNotIn("Fixed after", note)
        self.assertIn("not shown to be the fix", note)
        self.assertEqual(found[0].confidence, "low")

    def test_a_failed_edit_is_not_an_edit(self):
        entries = (
            bash("a", "pytest", "FAILED", is_error=True)
            + [
                tool_use("b", "Edit", {"file_path": "src/x.py"}),
                tool_result("b", "<tool_use_error>String to replace not found", True),
            ]
            + bash("c", "pytest", "1 passed")
        )
        # The only "edit" never happened, so this is a bare retry, not an attempt.
        self.assertEqual(titles(entries, "attempt"), [])

    def test_churn_counts_only_edits_that_happened(self):
        entries = []
        for i in range(tr.CHURN_MIN_EDITS):
            entries += [
                tool_use(f"e{i}", "Edit", {"file_path": "a.py"}),
                tool_result(f"e{i}", "String to replace not found", True),
            ]
        self.assertEqual(titles(entries, "trap"), [])


class InterruptedAndRefusedTests(unittest.TestCase):
    def test_a_refused_call_is_not_run(self):
        # A hook blocking the call is not the command failing.
        entries = bash("a", "pytest", "<tool_use_error>Blocked: sleep 60</tool_use_error>", True)
        self.assertEqual(outcome(entries), tr.NOT_RUN)
        entries += edit("b", "a.py") + bash("c", "pytest", "1 passed")
        self.assertEqual(titles(entries, "attempt"), [])

    def test_a_rejected_call_is_not_run(self):
        text = "The user doesn't want to proceed with this tool use. The tool use was rejected."
        self.assertEqual(outcome(bash("a", "pytest", text, True)), tr.NOT_RUN)

    def test_an_interrupted_call_is_neither_failure_nor_success(self):
        text = "[Request interrupted by user for tool use]"
        for flagged in (True, False):
            with self.subTest(flagged=flagged):
                entries = bash("a", "pytest", text, flagged)
                self.assertEqual(outcome(entries), tr.INTERRUPTED)
                self.assertEqual(tr.mine(entries)[0], [])

    def test_the_structured_interrupt_flag_is_read(self):
        use, res = bash("a", "npm test", "12 passed")
        entries = [use, with_structured(res, interrupted=True)]
        self.assertEqual(outcome(entries), tr.INTERRUPTED)
        self.assertEqual(titles(entries), [])

    def test_a_structured_flag_is_not_misattributed_between_results(self):
        # Two results in one entry: `toolUseResult` cannot say which it belongs to.
        entry = {
            "type": "user",
            "toolUseResult": {"interrupted": True},
            "message": {
                "content": [
                    {"type": "tool_result", "tool_use_id": "a", "content": "1 passed"},
                    {"type": "tool_result", "tool_use_id": "b", "content": "1 passed"},
                ]
            },
        }
        entries = [
            tool_use("a", "Bash", {"command": "pytest"}),
            tool_use("b", "Bash", {"command": "ruff check ."}),
            entry,
        ]
        self.assertEqual([c.outcome for c in tr.pair_tool_calls(entries)], [tr.SUCCESS] * 2)


class HarnessSignalTests(unittest.TestCase):
    def test_a_flagged_exit_is_a_failure_whatever_the_text_says(self):
        text = "Exit code 1\n1 file reformatted\nAll checks passed!"
        self.assertEqual(outcome(bash("a", "ruff check .", text, True)), tr.FAILURE)

    def test_a_masked_pipeline_failure_is_read_from_the_output(self):
        # `pytest | tail` exits 0 with tail's status; the summary still says failed.
        entries = bash("a", "pytest | tail -3", "==== 2 failed, 10 passed in 1.2s ====")
        self.assertEqual(outcome(entries), tr.FAILURE)
        self.assertEqual(titles(entries, "verification"), [])

    def test_output_that_may_be_data_settles_nothing(self):
        # A grep or cat of source that contains "error:" or "FAILED" has not
        # failed, and a masked `python x.py | tail` printing a traceback has not
        # passed: only a test, lint or build run's output is a verdict.
        for command in ("grep -rn FAILED tests/", "sed -n 1,80p cli.py", "python x.py | tail"):
            with self.subTest(command=command):
                entries = bash("a", command, "Traceback: raise ValueError('error: x')")
                call = tr.pair_tool_calls(entries)[0]
                self.assertEqual((call.result_received, call.outcome), (True, tr.UNKNOWN))

    def test_an_ambiguous_rerun_does_not_close_an_attempt(self):
        entries = (
            bash("a", "python x.py", "Exit code 1\nTraceback ...", is_error=True)
            + edit("b", "x.py")
            + bash("c", "python x.py | tail", "Traceback (most recent call last): ...")
        )
        self.assertEqual(titles(entries, "attempt"), [])

    def test_a_masked_build_failure_is_read_from_the_output(self):
        entries = bash("a", "npm run build 2>&1 | tail -5", "error: Cannot find module 'x'")
        self.assertEqual(outcome(entries), tr.FAILURE)

    def test_a_quoted_marker_is_not_the_harness_speaking(self):
        text = 'x = "[Request interrupted by user for tool use]"  # <tool_use_error>'
        self.assertEqual(outcome(bash("a", "cat tests/fixture.py", text)), tr.SUCCESS)

    def test_every_outcome_is_in_the_vocabulary(self):
        cases = [
            [tool_use("a", "Bash", {"command": "x"})],
            bash("a", "x", "ok"),
            bash("a", "pytest", "FAILED"),
            bash("a", "x", "[Request interrupted by user]"),
            bash("a", "x", "<tool_use_error>no</tool_use_error>", True),
        ]
        got = {outcome(c) for c in cases}
        self.assertEqual(got, set(tr.OUTCOMES))


if __name__ == "__main__":
    unittest.main()
