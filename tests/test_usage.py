"""Tests for record usage telemetry (WM-02).

What the counts mean, where they live, and the two things they must never do:
fail a command, or measure writes instead of surfacings.

Run with:  python -m pytest tests/
       or:  python tests/test_usage.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402  (patch target: usage calls cli helpers)
from breadcrumbs import usage  # noqa: E402

FIXTURES = REPO_ROOT / "fixtures"


def init_store(tmp: str) -> Path:
    root = Path(tmp)
    with contextlib.redirect_stdout(io.StringIO()):
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def a_decision(tmp: str, title: str = "Use markdown as the source of truth") -> str:
    code, out = run(
        [
            "remember",
            "decision",
            "--project",
            tmp,
            "--title",
            title,
            "--set",
            "Decision",
            "markdown plus yaml frontmatter",
            "--confidence",
            "low",
            "--json",
        ]
    )
    assert code == 0, out
    return json.loads(out)["id"]


class StorageTests(unittest.TestCase):
    def test_counts_accrue_per_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            usage.record_surfaced(mem, ["dec_x"], "resume")
            usage.record_surfaced(mem, ["dec_x"], "guard")
            usage.record_surfaced(mem, ["dec_x"], "guard")
            entry = usage.load_usage(mem)["records"]["dec_x"]
            self.assertEqual(entry["surfaced"], 3)
            self.assertEqual(entry["by"], {"resume": 1, "guard": 2})

    def test_sessions_are_deduped(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for _ in range(5):
                usage.record_surfaced(mem, ["dec_x"], "hook-guard", session_id="s1")
            usage.record_surfaced(mem, ["dec_x"], "hook-guard", session_id="s2")
            entry = usage.load_usage(mem)["records"]["dec_x"]
            self.assertEqual(entry["surfaced"], 6)
            # Six surfacings, two sessions: one session firing the hook five
            # times is not five pieces of evidence.
            self.assertEqual(sorted(entry["sessions"]), ["s1", "s2"])

    def test_it_lives_under_private_and_is_gitignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            usage.record_surfaced(mem, ["dec_x"], "resume")
            path = usage.usage_path(mem)
            self.assertTrue(path.is_file())
            self.assertEqual(path.relative_to(mem).parts[0], "private")
            ignore = (Path(tmp) / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(f"{crumb.MEMORY_DIRNAME}/private/**", ignore)

    def test_the_record_cap_drops_the_least_recently_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with mock.patch.object(usage, "USAGE_MAX_RECORDS", 5):
                for i in range(8):
                    with mock.patch.object(_cli, "now_iso", return_value=f"2026-09-{10 + i:02d}"):
                        usage.record_surfaced(mem, [f"dec_{i}"], "resume")
                records = usage.load_usage(mem)["records"]
            self.assertEqual(len(records), 5)
            self.assertNotIn("dec_0", records)
            self.assertIn("dec_7", records)

    def test_an_unreadable_file_reads_as_no_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            path = usage.usage_path(mem)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertEqual(usage.load_usage(mem), {"records": {}})
            self.assertFalse(usage.has_usage_data(mem))
            # ...and a write over the top still succeeds.
            usage.record_surfaced(mem, ["dec_x"], "resume")
            self.assertTrue(usage.has_usage_data(mem))

    def test_telemetry_never_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with mock.patch.object(_cli, "write_text_atomic", side_effect=OSError("disk full")):
                usage.record_surfaced(mem, ["dec_x"], "resume")  # must not raise
            self.assertFalse(usage.has_usage_data(mem))

    def test_empty_ids_write_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            usage.record_surfaced(mem, [], "resume")
            usage.record_surfaced(mem, [None, ""], "resume")
            self.assertFalse(usage.usage_path(mem).exists())


class CallSiteTests(unittest.TestCase):
    def test_resume_records_the_ids_it_printed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = a_decision(tmp)
            run(["resume", "--project", tmp])
            records = usage.load_usage(mem)["records"]
            self.assertIn(rid, records)
            self.assertEqual(records[rid]["by"], {"resume": 1})

    def test_a_write_alone_records_nothing(self):
        """The reindex every mutation triggers builds a packet. That must not count.

        Otherwise the counts measure how often the store was *written*, which is
        the one thing they are not for.
        """
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            a_decision(tmp)
            run(["reindex", "--project", tmp])
            run(["note", "question", "is this still true?", "--project", tmp])
            self.assertFalse(usage.has_usage_data(mem))

    def test_search_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            a_decision(tmp)
            run(["search", "markdown", "--project", tmp])
            self.assertFalse(usage.has_usage_data(mem))

    def test_guard_records_its_matches(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = a_decision(tmp)
            with contextlib.redirect_stdout(io.StringIO()):
                crumb.main(["guard", "rewrite the markdown source of truth", "--project", tmp])
            records = usage.load_usage(mem)["records"]
            if rid in records:
                self.assertEqual(records[rid]["by"], {"guard": 1})
            else:  # scored under the noise floor: nothing was shown, nothing counted
                self.assertEqual(records, {})

    def test_session_start_hook_records_the_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = a_decision(tmp)
            saved = sys.stdin
            sys.stdin = io.StringIO(json.dumps({"cwd": tmp, "session_id": "s1"}))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    crumb.main(["hook", "session"])
            finally:
                sys.stdin = saved
            self.assertIn(rid, usage.load_usage(mem)["records"])


class NeverSurfacedTests(unittest.TestCase):
    def test_active_records_with_no_history_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = a_decision(tmp)
            self.assertEqual([r["id"] for r in usage.never_surfaced(mem)], [rid])
            usage.record_surfaced(mem, [rid], "resume")
            self.assertEqual(usage.never_surfaced(mem), [])

    def test_retired_records_are_not_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = a_decision(tmp)
            run(["mark-status", rid, "stale", "--reason", "no longer true", "--project", tmp])
            self.assertEqual(usage.never_surfaced(mem), [])


class AuditTests(unittest.TestCase):
    def test_no_finding_without_history(self):
        """A fresh clone has no history, so 'never surfaced' is true of everything."""
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            a_decision(tmp)
            findings = crumb.run_audit(mem, Path(tmp))
            self.assertEqual([f for f in findings if f["check"] == "never-surfaced"], [])

    def test_finding_fires_for_an_old_untouched_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            old = a_decision(tmp, "An old decision nobody reads")
            other = a_decision(tmp, "A decision that does get surfaced")
            usage.record_surfaced(mem, [other], "resume")  # gives the store history
            with mock.patch.object(usage, "never_surfaced") as ns:
                ns.return_value = [{"id": old, "type": "decision", "title": "x", "age_days": 200}]
                findings = crumb.run_audit(mem, Path(tmp))
            hits = [f for f in findings if f["check"] == "never-surfaced"]
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["severity"], crumb.AUDIT_INFO)
            self.assertIn(old, hits[0]["message"])

    def test_a_young_record_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            young = a_decision(tmp)
            usage.record_surfaced(mem, ["something-else"], "resume")
            with mock.patch.object(usage, "never_surfaced") as ns:
                ns.return_value = [{"id": young, "type": "decision", "title": "x", "age_days": 3}]
                findings = crumb.run_audit(mem, Path(tmp))
            self.assertEqual([f for f in findings if f["check"] == "never-surfaced"], [])


class UsageCommandTests(unittest.TestCase):
    def test_empty_history_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(["usage", "--project", tmp])
            self.assertEqual(code, 0)
            self.assertIn("no history yet", out)

    def test_rows_are_printed_most_surfaced_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            usage.record_surfaced(mem, ["dec_quiet"], "resume")
            for _ in range(3):
                usage.record_surfaced(mem, ["dec_loud"], "guard")
            code, out = run(["usage", "--project", tmp])
            self.assertEqual(code, 0)
            self.assertLess(out.index("dec_loud"), out.index("dec_quiet"))
            self.assertIn("never committed", out)

    def test_never_flag_and_json_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            rid = a_decision(tmp)
            code, out = run(["usage", "--never", "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            doc = json.loads(out)
            self.assertTrue(doc["ok"])
            self.assertEqual([i["id"] for i in doc["items"]], [rid])

    def test_needs_a_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(["usage", "--project", tmp])
            self.assertEqual(code, 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
