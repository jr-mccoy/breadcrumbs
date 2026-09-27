"""Jot promotion preserves meaning (audit F03, WP03).

Promoting a jot without explicit sections used to write an empty stub. The note,
the one thing the jot said, was not in the record future sessions read. The
record also came out `scope: project` and `confidence: medium` whatever the jot
was, and skipped the near-duplicate gate. These pin the replacement: the note
survives into every target type, scope and confidence are inherited unless the
caller widens or raises them, the duplicate gate applies, and a failed target
write leaves the jot live.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import inbox, mcp_core  # noqa: E402

NOTE = "Invalidate both the tenant cache and the role cache before rotating the auth epoch."


def run(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, out.getvalue()


class PromotionCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def jot(self, text: str = NOTE, **kwargs) -> str:
        kwargs.setdefault("title", "Cache invalidation finding")
        kwargs.setdefault("evidence", [{"type": "file", "ref": "src/cache.py"}])
        res = inbox.write_jot(self.mem, self.root, text, **kwargs)
        self.assertTrue(res["ok"], res)
        return res["id"]

    def promote(self, jot_id: str, target: str, **kwargs) -> dict:
        return inbox.promote_jot(self.mem, self.root, jot_id, target, **kwargs)

    def record(self, rid: str):
        rec = crumb.find_record_by_id(self.mem, rid)
        self.assertIsNotNone(rec, rid)
        return rec

    def jot_status(self, jot_id: str) -> str:
        return inbox.find_jot(self.mem, jot_id).meta["status"]

    def assert_store_valid(self):
        fails = [f for f in crumb.run_validate(self.mem) if f["status"] == "fail"]
        self.assertEqual(fails, [])


class TextTests(PromotionCase):
    def test_promote_without_sections_preserves_note_text(self):
        for target in inbox.PROMOTE_TARGETS:
            with self.subTest(target=target):
                jot_id = self.jot(f"{target}: {NOTE}", title=f"{target} cache note")
                res = self.promote(jot_id, target, allow_duplicate=True)
                self.assertTrue(res["ok"], res)
                rec = self.record(res["promoted_to"])
                self.assertIn(f"{target}: {NOTE}", rec.body)
                self.assertEqual(rec.meta["promoted_from"], jot_id)
                self.assertEqual(
                    rec.meta["promoted_from_digest"], inbox.jot_digest(f"{target}: {NOTE}")
                )
                self.assertEqual(self.jot_status(jot_id), "superseded")
        self.assert_store_valid()

    def test_the_note_is_the_section_the_packet_reads(self):
        res = self.promote(self.jot(), "decision")
        self.assertEqual(self.record(res["promoted_to"]).sections["Decision"].strip(), NOTE)

    def test_explicit_sections_keep_the_source_trail(self):
        jot_id = self.jot()
        res = self.promote(jot_id, "decision", sections={"Rationale": "Stale roles leak access."})
        rec = self.record(res["promoted_to"])
        self.assertEqual(rec.sections["Rationale"].strip(), "Stale roles leak access.")
        self.assertIn(f"From jot {jot_id}: {NOTE}", rec.sections["Context"])

    def test_a_section_that_quotes_the_note_is_not_repeated(self):
        res = self.promote(self.jot(), "decision", sections={"Decision": f"Adopted. {NOTE}"})
        self.assertEqual(self.record(res["promoted_to"]).body.count(NOTE), 1)

    def test_trap_fields_keep_the_source_trail(self):
        jot_id = self.jot()
        res = self.promote(jot_id, "trap", fields={"why": "role cache outlives the epoch"})
        rec = self.record(res["promoted_to"])
        self.assertIn("role cache outlives the epoch", rec.body)
        self.assertIn(NOTE, rec.sections["Notes"])


class ScopeAndConfidenceTests(PromotionCase):
    def test_private_branch_promotion_does_not_default_to_project_medium(self):
        for target in ("decision", "attempt", "verification", "trap", "question", "idea"):
            with self.subTest(target=target):
                jot_id = self.jot(f"{target} {NOTE}", local=True, scope="branch")
                res = self.promote(jot_id, target, allow_duplicate=True)
                self.assertTrue(res["ok"], res)
                meta = self.record(res["promoted_to"]).meta
                self.assertEqual((meta["scope"], meta["confidence"]), ("branch", "low"))
                self.assertEqual((res["scope"], res["confidence"]), ("branch", "low"))
                self.assertTrue(res["from_private"])
                self.assertFalse(res["scope_widened"])

    def test_widening_and_raising_are_explicit_and_reported(self):
        jot_id = self.jot(local=True, scope="branch")
        res = self.promote(jot_id, "decision", scope="project", confidence="high")
        self.assertTrue(res["ok"], res)
        meta = self.record(res["promoted_to"]).meta
        self.assertEqual((meta["scope"], meta["confidence"]), ("project", "high"))
        self.assertTrue(res["scope_widened"])

    def test_the_cli_says_what_it_did(self):
        jot_id = self.jot(local=True, scope="branch")
        code, out = run(["inbox", "promote", jot_id, "decision", "--project", str(self.root)])
        self.assertEqual(code, 0, out)
        self.assertIn("scope: branch · confidence: low", out)
        self.assertIn("its text is now in committed memory", out)

    def test_a_private_credential_is_not_published(self):
        jot_id = self.jot("deploy key AKIAIOSFODNN7EXAMPLE works for staging", local=True)
        res = self.promote(jot_id, "decision")
        self.assertFalse(res["ok"])
        self.assertIn("credential", res["error"])
        self.assertEqual(self.jot_status(jot_id), "active")
        self.assertEqual(crumb.load_records(self.mem, types=("decision",)), [])


class GateTests(PromotionCase):
    def _existing_decision(self) -> str:
        _path, meta = crumb.write_record(
            self.mem,
            self.root,
            "decision",
            "Invalidate tenant and role caches before rotating the auth epoch",
            {"Decision": NOTE},
            evidence=[{"type": "file", "ref": "src/cache.py"}],
            tags=["cache"],
        )
        return meta["id"]

    def test_promotion_obeys_duplicate_gate(self):
        old = self._existing_decision()
        jot_id = self.jot(tags=["cache"])
        res = self.promote(jot_id, "decision")
        self.assertFalse(res["ok"])
        self.assertEqual(res["error"], "near-duplicate")
        self.assertEqual(res["duplicates"][0]["id"], old)
        self.assertEqual(self.jot_status(jot_id), "active")
        self.assertEqual(len(crumb.load_records(self.mem, types=("decision",))), 1)

        # The CLI reports it like `remember` does: exit 3.
        code, out = run(
            ["inbox", "promote", jot_id, "decision", "--project", str(self.root), "--json"]
        )
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out)["error"], "near-duplicate")

        # --supersedes answers the refusal and retires the old decision.
        res = self.promote(jot_id, "decision", supersedes=old)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["supersedes"], [old])
        self.assertEqual(self.record(old).meta["status"], "superseded")
        self.assert_store_valid()

    def test_allow_duplicate_writes_both(self):
        self._existing_decision()
        res = self.promote(self.jot(tags=["cache"]), "decision", allow_duplicate=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(len(crumb.load_records(self.mem, types=("decision",))), 2)

    def test_failed_target_leaves_source_live(self):
        cases = [
            # A claim raised above low with no evidence: the evidence rule refuses.
            ("decision", {"confidence": "medium"}, {"evidence": []}),
            # An unsupported scope: the record contract refuses.
            ("verification", {"scope": "everywhere"}, {}),
            # A trap slug that already exists: the trap writer refuses.
            ("trap", {"fields": {"slug": "taken"}}, {}),
        ]
        crumb.note(self.mem, self.root, "trap", "Already recorded trap", fields={"slug": "taken"})
        for target, promote_kwargs, jot_kwargs in cases:
            with self.subTest(target=target):
                before = {p.name for p in self.mem.rglob("*.md")}
                jot_id = self.jot(f"{target} failure {NOTE}", **jot_kwargs)
                res = self.promote(jot_id, target, **promote_kwargs)
                self.assertFalse(res["ok"], res)
                self.assertEqual(self.jot_status(jot_id), "active")
                after = {p.name for p in self.mem.rglob("*.md")}
                self.assertEqual(after - before, {inbox.find_jot(self.mem, jot_id).path.name})

    def test_mcp_promote_has_the_same_contract(self):
        jot_id = self.jot(local=True, scope="branch")
        res = mcp_core.tool_inbox_promote(jot_id, "decision", root=self.root)
        self.assertTrue(res["ok"], res)
        self.assertEqual((res["scope"], res["confidence"]), ("branch", "low"))
        self.assertIn(NOTE, self.record(res["promoted_to"]).body)
        dup = mcp_core.tool_inbox_promote(self.jot(tags=["x"]), "decision", root=self.root)
        self.assertEqual(dup.get("error"), "near-duplicate")


if __name__ == "__main__":
    unittest.main()
