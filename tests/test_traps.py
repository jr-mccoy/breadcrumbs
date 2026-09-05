"""Tests for `crumb traps` — trap staleness and always-on context cost (R6).

Traps are appended to known-traps.md and nothing ever ages out: 77 active traps
and 167 KB in the field store, loaded at the start of every session. Age alone
must not retire a trap — an old trap can be perfectly live — so the missing fact
is when somebody last checked, and the missing tool is a report that names the
candidates.

Run with:  python -m unittest discover -s tests
       or:  python tests/test_traps.py
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def init_store(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


def add_trap(tmp: str, summary: str) -> str:
    _code, out = run(
        [
            "note",
            "trap",
            summary,
            "--project",
            tmp,
            "--area",
            "app/x.py",
            "--symptom",
            "it breaks",
            "--why",
            "because",
            "--safe",
            "do the other thing",
            "--verify",
            "run the suite",
            "--json",
        ]
    )
    return json.loads(out)["id"]


class TrapReportTests(unittest.TestCase):
    def test_a_new_trap_reports_as_never_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tid = add_trap(tmp, "the first trap")
            rows = _cli.trap_report(mem)
            row = next(r for r in rows if r["id"] == tid)
            self.assertIsNone(row["last_confirmed"])
            self.assertGreater(row["approx_tokens"], 0)

    def test_confirm_stamps_the_bullet_and_the_report_reads_it_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tid = add_trap(tmp, "the first trap")
            code, out = run(["traps", "--confirm", tid, "--project", tmp])
            self.assertEqual(code, 0, out)
            self.assertIn(_cli.TRAP_CONFIRMED_KEY, (mem / "known-traps.md").read_text("utf-8"))
            row = next(r for r in _cli.trap_report(mem) if r["id"] == tid)
            self.assertIsNotNone(row["last_confirmed"])
            self.assertEqual(row["age_days"], 0)

    def test_confirming_twice_updates_rather_than_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tid = add_trap(tmp, "the first trap")
            run(["traps", "--confirm", tid, "--project", tmp])
            run(["traps", "--confirm", tid, "--project", tmp])
            text = (mem / "known-traps.md").read_text("utf-8")
            self.assertEqual(text.count(f"- {_cli.TRAP_CONFIRMED_KEY}:"), 1)

    def test_confirming_preserves_the_rest_of_the_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tid = add_trap(tmp, "the first trap")
            run(["traps", "--confirm", tid, "--project", tmp])
            text = (mem / "known-traps.md").read_text("utf-8")
            for kept in ("Area / files: app/x.py", "Symptom: it breaks", "Why: because"):
                self.assertIn(kept, text)

    def test_stale_filters_to_what_nobody_has_confirmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            fresh = add_trap(tmp, "recently checked")
            never = add_trap(tmp, "nobody has looked at this in years")
            run(["traps", "--confirm", fresh, "--project", tmp])
            stale_ids = [r["id"] for r in _cli.trap_report(mem, stale_days=180)]
            self.assertIn(never, stale_ids)
            self.assertNotIn(fresh, stale_ids)

    def test_an_old_confirmation_goes_stale_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tid = add_trap(tmp, "checked once, long ago")
            _cli.set_trap_confirmed(mem, tid, when="2020-01-01")
            self.assertIn(tid, [r["id"] for r in _cli.trap_report(mem, stale_days=180)])

    def test_never_confirmed_traps_sort_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            fresh = add_trap(tmp, "recently checked")
            never = add_trap(tmp, "never checked")
            run(["traps", "--confirm", fresh, "--project", tmp])
            self.assertEqual(_cli.trap_report(mem)[0]["id"], never)

    def test_a_retired_trap_can_be_filtered_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tid = add_trap(tmp, "no longer true")
            run(["mark-status", tid, "stale", "--reason", "fixed", "--project", tmp])
            active = [r["id"] for r in _cli.trap_report(mem, status="active")]
            self.assertNotIn(tid, active)

    def test_json_reports_the_context_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            add_trap(tmp, "the first trap")
            code, out = run(["traps", "--project", tmp, "--json"])
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertEqual(payload["summary"]["count"], 1)
            self.assertGreater(payload["summary"]["approx_tokens"], 0)
            self.assertEqual(payload["items"], payload["traps"])

    def test_confirm_of_an_unknown_trap_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, _ = run(["traps", "--confirm", "trap_nope", "--project", tmp])
            self.assertEqual(code, 1)

    def test_an_empty_store_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(["traps", "--project", tmp])
            self.assertEqual(code, 0, out)
            self.assertIn("none", out)


class TrapBudgetTests(unittest.TestCase):
    def test_audit_names_the_report_when_traps_outgrow_the_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            add_trap(tmp, "one real trap")
            with (mem / "known-traps.md").open("a", encoding="utf-8") as fh:
                fh.write("\n" + ("- padding words that cost tokens " * 40 + "\n") * 40)
            findings = _cli._audit_bloat(mem, Path(tmp))
            growth = [f for f in findings if f["kind"] == "traps-growth"]
            self.assertTrue(growth, findings)
            self.assertIn("crumb traps --stale", growth[0]["message"])

    def test_a_small_store_is_not_nagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            add_trap(tmp, "one real trap")
            kinds = {f["kind"] for f in _cli._audit_bloat(mem, Path(tmp))}
            self.assertNotIn("traps-growth", kinds)


class TrapContextCostTests(unittest.TestCase):
    """The two bugs that made the trap problem self-sustaining.

    Retiring a trap is the whole remediation this feature exists to enable, and
    both halves of it were broken: the metric counted retired traps, so five
    retirements moved 90 traps/42,585 tokens to 85/42,991 — following the advice
    made the number worse — and the fix command the tool printed
    (`crumb mark-status <id> resolved`) is not in any status vocabulary, so it
    exits with "invalid choice".
    """

    def test_retiring_a_trap_lowers_the_reported_context_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            keep = add_trap(tmp, "the trap that still applies")
            drop = add_trap(tmp, "the trap that was fixed weeks ago")
            before = json.loads(run(["traps", "--project", tmp, "--json"])[1])["summary"]
            run(["mark-status", drop, "stale", "--reason", "fixed", "--project", tmp])
            after = json.loads(run(["traps", "--project", tmp, "--json"])[1])["summary"]
            self.assertLess(after["approx_tokens"], before["approx_tokens"])
            self.assertEqual(after["active"], 1)
            # The retired trap is still listed; it just stops being counted as cost.
            self.assertEqual(after["count"], 2)
            self.assertIn(keep, [r["id"] for r in _cli.trap_report(mem, status="active")])

    def test_the_audit_finding_falls_when_a_trap_is_retired(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for i in range(8):
                add_trap(tmp, f"trap number {i} " + "with a body long enough to cost tokens " * 150)

            def reported() -> tuple[int, int]:
                growth = [
                    f for f in _cli._audit_bloat(mem, Path(tmp)) if f["kind"] == "traps-growth"
                ]
                self.assertTrue(
                    growth, "the store must be over budget for this test to mean anything"
                )
                n, toks = re.search(
                    r"(\d+) active trap\(s\), ~(\d+) tokens", growth[0]["message"]
                ).groups()
                return int(n), int(toks)

            before_n, before_toks = reported()
            tid = _cli.load_traps(mem)[0]["id"]
            run(["mark-status", tid, "stale", "--reason", "fixed", "--project", tmp])
            after_n, after_toks = reported()
            self.assertEqual((after_n, before_n), (before_n - 1, 8))
            self.assertLess(after_toks, before_toks, "retiring a trap must not raise the metric")

    def test_the_printed_fix_command_is_a_real_status(self):
        """`crumb traps` tells you how to retire one; that command must parse."""
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            tid = add_trap(tmp, "a trap to retire")
            _code, out = run(["traps", "--project", tmp])
            advised = re.findall(r"crumb mark-status <id> (\w+)", out)
            self.assertTrue(advised, out)
            for status in advised:
                self.assertIn(status, _cli.MARK_STATUS_CHOICES)
                code, _ = run(["mark-status", tid, status, "--reason", "x", "--project", tmp])
                self.assertEqual(code, 0, f"advised `{status}` does not work")


class TrapSummaryCapTests(unittest.TestCase):
    """A trap summary is re-read on every tool call, so it is bounded.

    One field-store trap carried an 1,123-character summary and surfaced 15
    times in a session: 16,845 bytes, 40% of that session's entire guard cost.
    Nothing is lost — the heading carries the cap, the body carries the sentence
    the author wrote, and guard still scores against both.
    """

    LONG = (
        "the accrual shim must wrap every ledger mutation because the reconciler "
        "reads the shim's journal rather than the table, and a direct write is "
        "invisible to it until the nightly sweep, at which point the imbalance is "
        "attributed to whichever batch happened to run last "
    ) * 3

    def test_the_heading_is_capped_and_the_full_text_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            add_trap(tmp, self.LONG)
            trap = _cli.load_traps(mem)[0]
            self.assertLessEqual(len(trap["summary"]), _cli.TRAP_SUMMARY_MAX_CHARS + 1)
            self.assertTrue(trap["summary"].endswith("…"))
            # Parked, not dropped: still in the file and still scored against.
            self.assertIn(self.LONG.strip(), trap["content"])

    def test_a_short_summary_is_left_exactly_as_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            add_trap(tmp, "the accrual shim must wrap ledger mutations")
            trap = _cli.load_traps(mem)[0]
            self.assertEqual(trap["summary"], "the accrual shim must wrap ledger mutations")
            self.assertNotIn(_cli.TRAP_DETAIL_KEY, trap["content"])

    def test_the_resume_packet_caps_a_trap_written_before_the_cap(self):
        """Where the cost actually lives: traps already in a store."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with (mem / "known-traps.md").open("a", encoding="utf-8") as fh:
                fh.write(f"\n## trap_legacy: {self.LONG}\n- Status: active\n")
            packet = _cli.build_resume_packet(mem, Path(tmp))
            line = next(t for t in packet["known_traps"] if "trap_legacy" in t)
            self.assertLessEqual(len(line), _cli.TRAP_SUMMARY_MAX_CHARS + 1)

    def test_the_guard_advisory_caps_a_long_title(self):
        result = {
            "verdict": "READ_FIRST",
            "matches": [{"id": "trap_legacy", "title": f"trap_legacy: {self.LONG}", "reason": ""}],
        }
        reason = _cli._hook_guard_reason(result)
        self.assertLess(len(reason), _cli.TRAP_SUMMARY_MAX_CHARS + 80)


if __name__ == "__main__":
    unittest.main()
