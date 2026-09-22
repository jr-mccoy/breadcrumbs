"""Tests for the bridge to long-term memory (Phase 4: WM-40 to WM-43).

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from _schema2 import downgrade_to_schema2  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import promote  # noqa: E402

CLAUDE_MD = "# Project instructions\n\nWrite tests first.\n"


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


def store(tmp: str, *, claude_md: bool = True) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    if claude_md:
        (Path(tmp) / "CLAUDE.md").write_text(CLAUDE_MD, encoding="utf-8")
    return Path(tmp) / crumb.MEMORY_DIRNAME


def decide(tmp: str, title: str = "Ledger rows are append-only", *extra: str) -> str:
    code, out, err = run(
        [
            "remember",
            "decision",
            "--project",
            tmp,
            "--title",
            title,
            "--set",
            "Decision",
            f"{title}; never update a row in place.",
            "--set",
            "Rationale",
            "the audit trail needs every historical row",
            "--evidence",
            "file",
            "src/ledger.py",
            "--allow-duplicate",
            "--json",
            *extra,
        ]
    )
    assert code == 0, err
    return json.loads(out)["id"]


def claude(tmp: str) -> str:
    return (Path(tmp) / "CLAUDE.md").read_text("utf-8")


class PromoteTests(unittest.TestCase):
    def test_promote_writes_one_bullet_and_records_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            code, _out, err = run(["promote", rid, "--project", tmp])
            self.assertEqual(code, 0, err)
            text = claude(tmp)
            self.assertTrue(text.startswith(CLAUDE_MD.rstrip("\n")), "user content kept")
            self.assertEqual(text.count(f"source: `{rid}`"), 1)
            self.assertIn(promote.PROMOTED_HEADING, text)
            self.assertIn("why: the audit trail needs every historical row", text)
            meta = crumb.find_record_by_id(mem, rid).meta
            self.assertEqual(meta["promoted_to"], "CLAUDE.md")
            self.assertTrue(meta["promoted_at"])
            self.assertEqual(meta["status"], "active")

    def test_promoting_again_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            first = claude(tmp)
            run(["promote", rid, "--project", tmp])
            self.assertEqual(claude(tmp).count(f"source: `{rid}`"), 1)
            self.assertEqual(claude(tmp), first)

    def test_the_packet_leaves_it_out_and_counts_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            other = decide(tmp, "Invoices are immutable once sent")
            run(["promote", rid, "--project", tmp])
            packet = crumb.build_resume_packet(mem, Path(tmp))
            ids = [d["id"] for d in packet["active_decisions"]]
            self.assertNotIn(rid, ids)
            self.assertIn(other, ids)
            self.assertEqual(packet["promoted"], {"active_decisions": 1})
            md = crumb.render_packet_markdown(packet)
            self.assertIn("1 promoted to the instruction file", md)

    def test_guard_still_uses_it_and_search_marks_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            g = crumb.guard(mem, Path(tmp), "update rows in src/ledger.py", files=["src/ledger.py"])
            self.assertIn(rid, [m["id"] for m in g["matches"]])
            matches, _ = crumb.search(mem, Path(tmp), "ledger rows")
            self.assertTrue(next(m for m in matches if m["id"] == rid)["promoted"])
            _code, out, _err = run(["search", "ledger rows", "--project", tmp])
            self.assertIn("[active, promoted]", out)

    def test_attempts_and_traps_render_as_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            code, out, err = run(
                [
                    "remember",
                    "attempt",
                    "--project",
                    tmp,
                    "--title",
                    "Stopping the gradle daemon between builds",
                    "--tried",
                    "gradlew --stop",
                    "--result",
                    "failed",
                    "--why",
                    "it killed the live test daemons",
                    "--do-not-retry",
                    "the daemon owner changes",
                    "--evidence",
                    "commit",
                    "abc1234",
                    "--json",
                ]
            )
            aid = json.loads(out)["id"]
            tid = crumb.note(
                mem,
                Path(tmp),
                "trap",
                "the daemon holds the sqlite lock",
                fields={"safe": "stop the daemon before migrating", "why": "it keeps a write lock"},
            )["id"]
            for rid in (aid, tid):
                code, _out, err = run(["promote", rid, "--project", tmp])
                self.assertEqual(code, 0, err)
            text = claude(tmp)
            self.assertIn("Do not retry: Stopping the gradle daemon between builds — unless", text)
            self.assertIn("why: it killed the live test daemons", text)
            self.assertIn(
                "The daemon holds the sqlite lock: stop the daemon before migrating", text
            )
            packet = crumb.build_resume_packet(mem, Path(tmp))
            self.assertEqual(packet["failed_attempts"], [])
            self.assertEqual(packet["known_traps"], [])

    def test_rule_override_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--rule", "Never UPDATE the ledger table", "--project", tmp])
            self.assertIn("- Never UPDATE the ledger table.", claude(tmp))
            self.assertEqual(
                crumb.find_record_by_id(mem, rid).meta["promoted_rule"],
                "Never UPDATE the ledger table",
            )

    def test_refusals(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            run(["mark-status", rid, "stale", "--project", tmp, "--reason", "x"])
            code, _o, err = run(["promote", rid, "--project", tmp])
            self.assertEqual(code, 2)
            self.assertIn("stale", err)
            low = decide(tmp, "A guess about caching", "--confidence", "low")
            # (evidence was given, so force low by hand)
            path = crumb.find_record_by_id(mem, low).path
            meta, body = crumb.parse_frontmatter(path.read_text("utf-8"))
            meta["confidence"] = "low"
            path.write_text(crumb.render_frontmatter(meta) + "\n" + body, encoding="utf-8")
            code, _o, err = run(["promote", low, "--project", tmp])
            self.assertEqual(code, 2)
            self.assertIn("confidence: low", err)
            qid = crumb.note(mem, Path(tmp), "question", "Should we shard?")["id"]
            code, _o, err = run(["promote", qid, "--project", tmp])
            self.assertEqual(code, 2)

    def test_no_instruction_file_is_refused_and_nothing_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp, claude_md=False)
            rid = decide(tmp)
            code, _o, err = run(["promote", rid, "--project", tmp])
            self.assertEqual(code, 2)
            self.assertIn("never creates", err)
            self.assertFalse((Path(tmp) / "CLAUDE.md").exists())
            self.assertFalse((Path(tmp) / "AGENTS.md").exists())

    def test_agents_md_is_used_when_it_is_the_one_that_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp, claude_md=False)
            (Path(tmp) / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            rid = decide(tmp)
            code, _o, err = run(["promote", rid, "--project", tmp])
            self.assertEqual(code, 0, err)
            self.assertIn(rid, (Path(tmp) / "AGENTS.md").read_text("utf-8"))
            self.assertEqual(crumb.find_record_by_id(mem, rid).meta["promoted_to"], "AGENTS.md")

    def test_moving_between_files_leaves_one_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp)
            (Path(tmp) / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            run(["promote", rid, "--to", "AGENTS.md", "--project", tmp])
            self.assertNotIn(rid, claude(tmp))
            self.assertIn(rid, (Path(tmp) / "AGENTS.md").read_text("utf-8"))

    def test_a_schema2_trap_block_is_promoted_with_a_bullet(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = downgrade_to_schema2(store(tmp))
            tid = crumb.note(
                mem,
                Path(tmp),
                "trap",
                "the daemon holds the lock",
                fields={"safe": "stop it first"},
            )["id"]
            code, _o, err = run(["promote", tid, "--project", tmp])
            self.assertEqual(code, 0, err)
            self.assertIn("- Promoted to: CLAUDE.md", (mem / "known-traps.md").read_text("utf-8"))
            self.assertEqual(crumb.build_resume_packet(mem, Path(tmp))["known_traps"], [])
            # The bookkeeping bullet never reaches keyword matching.
            trap = crumb.find_trap_by_id(mem, tid)
            self.assertNotIn("Promoted", trap["content"])
            run(["demote", tid, "--project", tmp])
            self.assertNotIn("Promoted to", (mem / "known-traps.md").read_text("utf-8"))


class DemoteTests(unittest.TestCase):
    def test_demote_removes_exactly_one_bullet(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            a = decide(tmp)
            b = decide(tmp, "Invoices are immutable once sent")
            run(["promote", a, "--project", tmp])
            run(["promote", b, "--project", tmp])
            code, _o, err = run(["demote", a, "--project", tmp])
            self.assertEqual(code, 0, err)
            self.assertNotIn(a, claude(tmp))
            self.assertIn(b, claude(tmp))
            self.assertNotIn("promoted_to", crumb.find_record_by_id(mem, a).meta)

    def test_the_block_disappears_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            run(["demote", rid, "--project", tmp])
            self.assertEqual(claude(tmp).strip(), CLAUDE_MD.strip())
            self.assertNotIn(promote.PROMOTED_BEGIN, claude(tmp))

    def test_retiring_a_promoted_record_demotes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            code, out, _err = run(
                ["mark-status", rid, "stale", "--project", tmp, "--reason", "moved on"]
            )
            self.assertEqual(code, 0)
            self.assertIn("also demoted", out)
            self.assertNotIn(rid, claude(tmp))
            self.assertNotIn("promoted_to", crumb.find_record_by_id(mem, rid).meta)

    def test_superseding_through_a_writer_demotes_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            decide(tmp, "Ledger rows are append-only, compacted nightly", "--supersedes", rid)
            self.assertNotIn(rid, claude(tmp))

    def test_demoting_something_not_promoted_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp)
            rid = decide(tmp)
            code, _o, err = run(["demote", rid, "--project", tmp])
            self.assertEqual(code, 1)
            self.assertIn("not promoted", err)


class AuditTests(unittest.TestCase):
    def _checks(self, mem: Path, tmp: str) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for f in crumb.run_audit(mem, Path(tmp)):
            out.setdefault(f["check"], []).append(f)
        return out

    def test_a_promoted_rule_saying_never_is_not_instruction_like(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            run(
                [
                    "promote",
                    rid,
                    "--rule",
                    "Never update or delete ledger rows, ever",
                    "--project",
                    tmp,
                ]
            )
            checks = self._checks(mem, tmp)
            self.assertNotIn("instruction-like", checks)
            self.assertNotIn(
                "bloat",
                {
                    k
                    for k, v in checks.items()
                    if any(f.get("kind") == "adapter-duplication" for f in v)
                },
            )

    def test_twenty_rules_fit_or_the_bloat_finding_fires(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            topics = [
                "ledger",
                "invoice",
                "payment",
                "refund",
                "webhook",
                "queue",
                "worker",
                "cache",
                "session",
                "token",
                "export",
                "import",
                "search",
                "index",
                "backup",
                "restore",
                "billing",
                "tax",
                "audit",
                "report",
            ]
            for t in topics:
                rid = decide(tmp, f"The {t} module owns its own schema and migrations")
                run(["promote", rid, "--project", tmp])
            block = promote.block_text(claude(tmp))
            self.assertEqual(len(promote.read_bullets(Path(tmp) / "CLAUDE.md")), 20)
            bloat = self._checks(mem, tmp).get("promoted-bloat", [])
            if len(block) > _cli.ADAPTER_BLOAT_CHARS:
                self.assertEqual(len(bloat), 1)
            else:
                self.assertEqual(bloat, [])

    def test_a_bullet_for_a_missing_record_is_a_demote_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            crumb.find_record_by_id(mem, rid).path.unlink()
            found = self._checks(mem, tmp).get("demote-candidate", [])
            self.assertEqual([f["id"] for f in found], [rid])
            code, _o, err = run(["demote", rid, "--project", tmp])
            self.assertEqual(code, 0, err)
            self.assertNotIn(rid, claude(tmp))

    def test_a_hand_edit_is_drift_and_repromoting_clears_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            self.assertNotIn("promoted-drift", self._checks(mem, tmp))
            path = Path(tmp) / "CLAUDE.md"
            path.write_text(
                claude(tmp).replace(
                    "- Ledger rows are append-only.", "- Ledger rows are mostly append-only."
                ),
                encoding="utf-8",
            )
            self.assertEqual(
                [f["id"] for f in self._checks(mem, tmp).get("promoted-drift", [])], [rid]
            )
            run(["promote", rid, "--project", tmp])
            self.assertNotIn("promoted-drift", self._checks(mem, tmp))

    def test_a_retitled_record_is_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            run(["retitle", rid, "Ledger rows are never updated in place", "--project", tmp])
            self.assertIn("promoted-drift", self._checks(mem, tmp))

    def test_a_long_lived_often_surfaced_decision_is_a_promote_candidate(self):
        from breadcrumbs import usage

        with tempfile.TemporaryDirectory() as tmp:
            mem = store(tmp)
            rid = decide(tmp)
            for i in range(5):
                usage.record_surfaced(mem, [rid], "resume", session_id=f"s{i}")
            self.assertNotIn("promote-candidate", self._checks(mem, tmp))  # too young
            later = _cli._now() + timedelta(days=61)
            with mock.patch.object(_cli, "_now", return_value=later):
                found = self._checks(mem, tmp).get("promote-candidate", [])
                self.assertEqual([f["id"] for f in found], [rid])
                self.assertIn(f"crumb promote {rid}", found[0]["message"])
            run(["promote", rid, "--project", tmp])
            with mock.patch.object(_cli, "_now", return_value=later):
                self.assertNotIn("promote-candidate", self._checks(mem, tmp))

    def test_doctor_reports_the_promoted_rules(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp)
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            _code, out, _err = run(["doctor", "--project", tmp])
            row = next(line for line in out.splitlines() if "promoted_rules" in line)
            self.assertIn("CLAUDE.md: 1 rule(s)", row)

    def test_remove_integrations_leaves_the_promoted_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            store(tmp)
            crumb.main(["init", "--project", tmp, "--with-adapter", "--session-tracking", "full"])
            rid = decide(tmp)
            run(["promote", rid, "--project", tmp])
            crumb.main(["init", "--project", tmp, "--remove-integrations"])
            self.assertIn(rid, claude(tmp))
            self.assertNotIn(_cli.ADAPTER_BEGIN, claude(tmp))


if __name__ == "__main__":
    unittest.main(verbosity=2)
