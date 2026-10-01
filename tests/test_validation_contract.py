"""The record contract (audit F05, WP01): breadcrumbs/validation.py.

`validate` used to establish presence, not shape: `confidence: certainly`, a
free-text `scope`, an evidence item with no ref, an `expires_at` nothing could
parse and a `superseded_by` naming no record all passed. These pin the stricter
contract, the stable codes it reports under, and the compatibility rules around
it: a new write is held to the contract, a legacy record is reported but never
rewritten, and a legacy problem never blocks retiring the record that has it.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import mcp_core, validation  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue() + err.getvalue()


class ContractCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        code, _ = run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.assertEqual(code, 0)
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def decision(self, title: str = "Route amber traffic through the queue", **meta_overrides):
        """A valid decision, then `meta_overrides` written straight into its frontmatter."""
        path, meta = crumb.write_record(
            self.mem,
            self.root,
            "decision",
            title,
            {"Decision": "Route amber traffic through the dedicated queue."},
            evidence=[{"type": "file", "ref": "queue.py"}],
        )
        if meta_overrides:
            self.rewrite(path, **meta_overrides)
        return path, meta["id"]

    def rewrite(self, path: Path, **fields) -> None:
        meta, body = crumb.parse_frontmatter(path.read_text(encoding="utf-8"))
        meta.update(fields)
        path.write_text(crumb.render_frontmatter(meta) + "\n" + body, encoding="utf-8")

    def codes(self, path: Path) -> list[str]:
        rel = path.relative_to(self.mem).as_posix()
        return [
            f["code"]
            for f in crumb.run_validate(self.mem)
            if f["status"] == "fail" and f["path"] == rel
        ]


class FieldContractTests(ContractCase):
    def test_invalid_confidence_evidence_and_dates_are_reported(self):
        cases = {
            "confidence": ("certainly", validation.CONFIDENCE_INVALID),
            "review_status": ("approved-by-me", validation.REVIEW_STATUS_INVALID),
            "evidence": ([{"nonsense": "not evidence"}], validation.EVIDENCE_MALFORMED),
            "expires_at": ("12345", validation.TIMESTAMP_INVALID),
            "created_at": ("yesterday", validation.TIMESTAMP_INVALID),
            "last_confirmed": ("2026-02-30", validation.TIMESTAMP_INVALID),
        }
        for field, (value, code) in cases.items():
            with self.subTest(field=field):
                path, _rid = self.decision(f"Record with a bad {field}", **{field: value})
                self.assertIn(code, self.codes(path))
                # Reported, never repaired: validate does not touch the file.
                self.assertIn(field, crumb.parse_frontmatter(path.read_text(encoding="utf-8"))[0])
                path.unlink()

    def test_malformed_evidence_does_not_satisfy_the_evidence_rule(self):
        # Any non-empty `evidence` used to count, so a pointer to nothing let a
        # claim stand at medium confidence.
        path, _rid = self.decision(evidence=[{"type": "file"}])
        codes = self.codes(path)
        self.assertIn(validation.EVIDENCE_MALFORMED, codes)
        self.assertIn("evidence", codes)  # the evidence-or-low-confidence rule
        self.rewrite(path, confidence="low")
        self.assertEqual(self.codes(path), [validation.EVIDENCE_MALFORMED])

    def test_valid_values_pass(self):
        path, _rid = self.decision(
            confidence="high",
            review_status="needs-review",
            scope="branch",
            expires_at="2026-12-31",
            last_confirmed="2026-09-01T00:00:00Z",
        )
        self.assertEqual(self.codes(path), [])

    def test_timestamps_are_the_same_on_every_interpreter(self):
        # fromisoformat accepts much more on 3.11+ than on 3.9 (and no `Z` before
        # 3.11); the contract accepts one subset everywhere.
        self.assertIsNotNone(validation.parse_timestamp("2026-09-01T10:00:00Z"))
        self.assertIsNotNone(validation.parse_timestamp("2026-09-01 10:00:00.123+02:00"))
        self.assertIsNotNone(validation.parse_timestamp("2026-09-01"))
        for bad in ("20260901", "2026-W35", "2026-09-01T10", "12345", 12345, None):
            with self.subTest(value=bad):
                self.assertIsNone(validation.parse_timestamp(bad))
        # ...and a reader accepts what the validator accepts.
        self.assertIsNotNone(crumb._parse_iso("2026-09-01T10:00:00Z"))

    def test_every_validate_finding_carries_a_code(self):
        self.decision(confidence="certainly")
        findings = crumb.run_validate(self.mem)
        self.assertTrue(all(f.get("code") for f in findings), findings)
        # Pre-existing checks keep their check name as their code.
        self.assertIn("frontmatter", {f["code"] for f in findings})


class ScopeContractTests(ContractCase):
    def test_new_write_rejects_unknown_scope_without_widening_legacy_scope(self):
        # Every new-write surface refuses a scope other than project|branch.
        with self.assertRaises(ValueError):
            crumb.write_record(
                self.mem, self.root, "decision", "Free scope", {"Decision": "d"},
                confidence="low", scope="all-machines",
            )  # fmt: skip
        with self.assertRaises(SystemExit) as exited:  # argparse `choices`
            run(
                [
                    "remember", "decision", "--project", str(self.root), "--title", "Free scope",
                    "--set", "Decision", "d", "--confidence", "low", "--scope", "all-machines",
                ]
            )  # fmt: skip
        self.assertEqual(exited.exception.code, 2)
        res = mcp_core.tool_record(
            "decision",
            {"title": "Free scope", "sections": {"Decision": "d"}, "scope": "all-machines"},
            root=self.root,
        )
        self.assertFalse(res["ok"])
        self.assertIn("scope", res["error"])
        self.assertEqual(list((self.mem / "decisions").glob("*.md")), [])

        # A legacy record keeps its text: reported, not converted to `project`.
        path, rid = self.decision(scope="this-machine-only")
        self.assertIn(validation.SCOPE_UNSUPPORTED, self.codes(path))
        run(["resume", "--project", str(self.root)])
        run(["reindex", "--project", str(self.root)])
        self.assertEqual(crumb.parse_frontmatter(path.read_text())[0]["scope"], "this-machine-only")
        # Retiring it still works, and the rewrite keeps the author's text.
        res = crumb.set_record_status(self.mem, rid, "stale", "scope unclear", agent="t")
        self.assertTrue(res["ok"], res)
        meta = crumb.parse_frontmatter(path.read_text())[0]
        self.assertEqual((meta["status"], meta["scope"]), ("stale", "this-machine-only"))


class LinkContractTests(ContractCase):
    def test_missing_replacement_self_link_and_cycle_are_reported(self):
        missing, _ = self.decision(
            "Retired for nothing", status="superseded", superseded_by="dec_20260101_gone"
        )
        self_path, self_id = self.decision("Retired for itself")
        self.rewrite(self_path, status="superseded", superseded_by=self_id)
        a_path, a_id = self.decision("Alpha queue policy")
        b_path, b_id = self.decision("Beta queue policy")
        self.rewrite(a_path, status="superseded", superseded_by=b_id)
        self.rewrite(b_path, status="superseded", superseded_by=a_id)

        self.assertIn(validation.SUPERSEDED_BY_MISSING, self.codes(missing))
        self.assertIn(validation.SUPERSESSION_SELF, self.codes(self_path))
        self.assertIn(validation.SUPERSESSION_CYCLE, self.codes(a_path))
        self.assertIn(validation.SUPERSESSION_CYCLE, self.codes(b_path))

    def test_a_chain_into_a_cycle_reports_only_the_cycle(self):
        entries = [
            ("a.md", "a", {"superseded_by": "b"}),
            ("b.md", "b", {"superseded_by": "c"}),
            ("c.md", "c", {"superseded_by": "b"}),
            ("d.md", "d", {"superseded_by": "a"}),
        ]
        issues = validation.store_issues(entries)
        self.assertEqual(sorted(issues), ["b.md", "c.md"])

    def test_historical_supersedes_may_name_rolled_up_records(self):
        # `rollup sessions` deletes the snapshots it folds; the rollup's
        # `supersedes` naming them is history, not a dangling link.
        path, _rid = self.decision(supersedes=["ses_20260101_folded-away"])
        self.assertEqual(self.codes(path), [])

    def test_a_malformed_target_is_still_a_target(self):
        target, target_id = self.decision("Replacement with broken frontmatter")
        target.write_text("---\ntitle: [unterminated\n", encoding="utf-8")
        old, _ = self.decision("Old policy", status="superseded", superseded_by=target_id)
        self.assertNotIn(validation.SUPERSEDED_BY_MISSING, self.codes(old))

    def test_mark_status_cannot_create_a_dangling_replacement(self):
        _path, rid = self.decision()
        res = crumb.set_record_status(
            self.mem, rid, "superseded", "replaced", agent="t", superseded_by="dec_20260101_gone"
        )
        self.assertFalse(res["ok"])
        self.assertIn("names no record", res["error"])


class CompatibilityTests(ContractCase):
    def test_unknown_metadata_round_trips_without_loss(self):
        path, rid = self.decision(x_team_owner="payments", x_ticket="PAY-12")
        self.assertEqual(self.codes(path), [])
        res = crumb.set_record_status(self.mem, rid, "stale", "reorg", agent="t")
        self.assertTrue(res["ok"], res)
        meta = crumb.parse_frontmatter(path.read_text(encoding="utf-8"))[0]
        self.assertEqual((meta["x_team_owner"], meta["x_ticket"]), ("payments", "PAY-12"))
        self.assertEqual(meta["id"], rid)

    def test_a_legacy_problem_never_blocks_retiring_the_record(self):
        path, rid = self.decision(confidence="certainly", expires_at="someday")
        res = crumb.set_record_status(self.mem, rid, "stale", "bad metadata", agent="t")
        self.assertTrue(res["ok"], res)
        # The problems are still reported; nothing was "fixed" behind the author.
        codes = self.codes(path)
        self.assertIn(validation.CONFIDENCE_INVALID, codes)
        self.assertIn(validation.TIMESTAMP_INVALID, codes)

    def test_existing_stores_still_validate(self):
        stores = [REPO_ROOT / ".project-memory"] + sorted(
            p for p in (REPO_ROOT / "fixtures").glob("*/.project-memory")
        )
        contract_codes = set(validation.__dict__[n] for n in dir(validation) if n.isupper())
        for mem in stores:
            with self.subTest(store=str(mem.relative_to(REPO_ROOT))):
                bad = [
                    f
                    for f in crumb.run_validate(mem)
                    if f["status"] == "fail" and f["code"] in contract_codes
                ]
                self.assertEqual(bad, [])

    def test_mcp_refuses_evidence_with_no_ref(self):
        res = mcp_core.tool_record(
            "decision",
            {
                "title": "Pointer to nothing",
                "sections": {"Decision": "d"},
                "evidence": [{"type": "file"}],
                "confidence": "high",
            },
            root=self.root,
        )
        self.assertFalse(res["ok"])
        self.assertIn("evidence item 1 has no ref", res["error"])


class DegradedReadTests(ContractCase):
    def test_packet_names_contract_breaks_and_still_builds(self):
        self.decision("A healthy decision")
        _path, bad_id = self.decision("A broken decision", confidence="certainly")
        packet = crumb.build_resume_packet(self.mem, self.root)
        warning = [w for w in packet["warnings"] if "record contract" in w]
        self.assertEqual(len(warning), 1, packet["warnings"])
        self.assertIn(bad_id, warning[0])
        self.assertIn(validation.CONFIDENCE_INVALID, warning[0])
        # Still read: the malformed record is isolated, not dropped.
        self.assertIn(bad_id, [d["id"] for d in packet["active_decisions"]])

    def test_a_clean_store_has_no_contract_warning(self):
        self.decision()
        packet = crumb.build_resume_packet(self.mem, self.root)
        self.assertFalse([w for w in packet["warnings"] if "record contract" in w])

    def test_an_invalid_status_is_named_and_its_effect_said(self):
        # Field report 2026-10-01, N3: a decision marked `fixed` vanished from
        # Active Decisions and the warning still said "they are still read".
        _path, bad_id = self.decision("Never use the porpoise queue", status="fixed")
        packet = crumb.build_resume_packet(self.mem, self.root)
        warning = [w for w in packet["warnings"] if "record contract" in w]
        self.assertEqual(len(warning), 1, packet["warnings"])
        self.assertIn(bad_id, warning[0])
        self.assertIn("status-invalid", warning[0])
        self.assertIn("left out of resume and guard", warning[0])

    def test_a_hand_written_verification_is_named_and_not_shown_open(self):
        vdir = self.mem / "verifications"
        vdir.mkdir(exist_ok=True)
        (vdir / "2026-09-20-zebra-cache-race-fixed.md").write_text(
            "# Zebra cache race\n\nFixed. Re-ran the soak test for an hour.\n", encoding="utf-8"
        )
        packet = crumb.build_resume_packet(self.mem, self.root)
        warning = " ".join(w for w in packet["warnings"] if "record contract" in w)
        self.assertIn("zebra-cache-race-fixed", warning)
        self.assertIn("no-frontmatter", warning)
        outcomes = [v.get("outcome") for v in packet.get("verifications", [])]
        self.assertNotIn("open", outcomes)

    def test_machine_local_jots_do_not_change_the_committed_packet(self):
        jot = self.mem / "private" / "inbox" / "2026-09-01-local-note-abcd.md"
        jot.parent.mkdir(parents=True, exist_ok=True)
        jot.write_text(
            crumb.render_frontmatter({"title": "local", "confidence": "certainly"}) + "\n",
            encoding="utf-8",
        )
        self.assertEqual(crumb.record_contract_warnings(self.mem), [])


if __name__ == "__main__":
    unittest.main()
