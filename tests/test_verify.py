"""Tests for the verification record type and the write→project→trust loop.

Covers the second-pass agentic review findings:
  - F1: `crumb verify` / `memory_verify` — a first-class verification result
    (a finding about reality), searchable and surfaced in the resume packet.
  - F2: reindex-on-write — every canonical mutation refreshes generated/.
  - F3: `validate` flags a stale projection (freshness check).
  - F4: task-scoped `likely_files` (resume --task).

Run with:  python -m pytest tests/
       or:  python tests/test_verify.py
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
from breadcrumbs import mcp_core  # noqa: E402


def init_store(tmp: str) -> Path:
    root = Path(tmp)
    crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def no_fails(mem: Path) -> list[dict]:
    return [f for f in crumb.run_validate(mem) if f["status"] == "fail"]


# --------------------------------------------------------------------------- #
# F1 — verification record type
# --------------------------------------------------------------------------- #
class VerifyWriteTests(unittest.TestCase):
    def test_verify_writes_valid_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            code, out = run([
                "verify", "perf-audit#F1", "--status", "fixed", "--method", "static",
                "--evidence", "file", "app/Foo.kt:170", "--project", tmp, "--json",
            ])
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertTrue(payload["id"].startswith("ver_"))
            self.assertEqual(payload["outcome"], "fixed")
            recs = crumb.load_records(mem, types=("verification",))
            self.assertEqual(len(recs), 1)
            meta = recs[0].meta
            self.assertEqual(meta["subject"], "perf-audit#F1")
            self.assertEqual(meta["outcome"], "fixed")
            self.assertEqual(meta["method"], "static")
            self.assertEqual(meta["status"], "active")  # lifecycle, distinct from outcome
            self.assertEqual(no_fails(mem), [])

    def test_no_evidence_forces_low_confidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            code, out = run(["verify", "claim X", "--status", "open", "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["confidence"], "low")
            self.assertEqual(no_fails(mem), [])

    def test_invalid_outcome_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            with self.assertRaises(SystemExit):  # argparse choices gate
                run(["verify", "x", "--status", "bogus", "--project", tmp])

    def test_invalid_outcome_rejected_at_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            res = crumb.verify(mem, Path(tmp), "x", status="bogus")
            self.assertFalse(res["ok"])

    def test_invalid_method_rejected_at_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            res = crumb.verify(mem, Path(tmp), "x", status="open", method="bogus")
            self.assertFalse(res["ok"])

    def test_empty_subject_rejected_at_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            res = crumb.verify(mem, Path(tmp), "   ", status="open")
            self.assertFalse(res["ok"])


class VerifyValidateTests(unittest.TestCase):
    def test_validate_flags_bad_outcome_in_frontmatter(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            crumb.verify(mem, Path(tmp), "subj", status="fixed",
                         evidence=[{"type": "file", "ref": "a.py:1"}])
            rec = crumb.load_records(mem, types=("verification",))[0]
            text = rec.path.read_text(encoding="utf-8").replace("outcome: fixed", "outcome: maybe")
            rec.path.write_text(text, encoding="utf-8")
            fails = no_fails(mem)
            self.assertTrue(any(f["check"] == "verification" for f in fails))


class VerifySearchTests(unittest.TestCase):
    def test_search_filters_verification_by_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            root = Path(tmp)
            crumb.verify(mem, root, "F1", status="fixed",
                         evidence=[{"type": "file", "ref": "a.py:1"}])
            crumb.verify(mem, root, "F2", status="open",
                         evidence=[{"type": "file", "ref": "b.py:2"}])
            matches, _ = crumb.search(mem, root, "", filters={"type": "verification", "status": "open"})
            self.assertEqual([m["status"] for m in matches], ["open"])
            self.assertTrue(matches[0]["id"].startswith("ver_"))


class VerifyGuardTests(unittest.TestCase):
    """review #5 M1 — a verification could never influence a guard verdict.

    `_item_from_record` stores a verification's *outcome* in `status`, and guard's
    liveness test only accepted `"active"`, so every verification landed in
    history: a `regressed` finding on the exact file being touched scored 17 and
    still produced `PROCEED` with `matches: []`.
    """

    def _guard(self, outcome: str, **meta):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        mem = init_store(tmp.name)
        root = Path(tmp.name)
        res = crumb.verify(mem, root, "reconciliation ledger rounding", status=outcome,
                           evidence=[{"type": "file", "ref": "src/payments/ledger.py"}])
        self.assertTrue(res["ok"], res)
        if meta:
            p = Path(res["path"])
            text = p.read_text(encoding="utf-8")
            for k, v in meta.items():
                text = text.replace(f"{k}: active", f"{k}: {v}", 1)
            p.write_text(text, encoding="utf-8")
        return crumb.guard(mem, root, "rewrite the reconciliation ledger rounding",
                           files=["src/payments/ledger.py"])

    def test_regressed_verification_drives_the_verdict(self):
        result = self._guard("regressed")
        self.assertNotEqual(result["verdict"], "PROCEED")
        self.assertEqual([m["kind"] for m in result["matches"]], ["verification"])

    def test_open_and_inconclusive_are_live_too(self):
        for outcome in ("open", "inconclusive"):
            with self.subTest(outcome=outcome):
                result = self._guard(outcome)
                self.assertNotEqual(result["verdict"], "PROCEED")

    def test_settled_outcomes_stay_history(self):
        """`fixed` / `not_applicable` are answers, not warnings — mention only."""
        for outcome in ("fixed", "not_applicable"):
            with self.subTest(outcome=outcome):
                result = self._guard(outcome)
                self.assertEqual(result["verdict"], "PROCEED")
                self.assertEqual(result["matches"], [])
                self.assertEqual([m["kind"] for m in result["history"]], ["verification"])

    def test_superseded_verification_is_not_live(self):
        """Liveness needs both halves: an actionable outcome AND a live record."""
        result = self._guard("regressed", status="superseded")
        self.assertEqual(result["verdict"], "PROCEED")
        self.assertEqual([m["kind"] for m in result["history"]], ["verification"])


class VerifyResumeTests(unittest.TestCase):
    def test_packet_surfaces_verifications_actionable_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            root = Path(tmp)
            crumb.verify(mem, root, "already-done", status="fixed",
                         evidence=[{"type": "file", "ref": "a.py:1"}])
            crumb.verify(mem, root, "still-broken", status="open",
                         evidence=[{"type": "file", "ref": "b.py:2"}])
            packet = crumb.build_resume_packet(mem, root)
            outcomes = [v["outcome"] for v in packet["verifications"]]
            self.assertEqual(outcomes, ["open", "fixed"])  # open (actionable) first
            md = crumb.render_packet_markdown(packet)
            self.assertIn("## Verifications", md)
            self.assertIn("still-broken", md)


# --------------------------------------------------------------------------- #
# F2 — reindex-on-write
# --------------------------------------------------------------------------- #
class ReindexOnWriteTests(unittest.TestCase):
    def _packet(self, mem: Path) -> str:
        return (mem / "generated" / "resume-packet.md").read_text(encoding="utf-8")

    def test_remember_refreshes_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(["remember", "decision", "--title", "pin the build cache",
                 "--evidence", "commit", "abc1234", "--project", tmp])
            self.assertEqual(no_fails(mem), [])  # projection is fresh -> no F3 fail

    def test_verify_refreshes_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(["verify", "subj", "--status", "fixed",
                 "--evidence", "file", "a.py:1", "--project", tmp])
            self.assertIn("subj", self._packet(mem))
            self.assertEqual(no_fails(mem), [])

    def test_mark_status_refreshes_projection(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            _, out = run(["remember", "decision", "--title", "temporary call",
                          "--evidence", "commit", "abc1234", "--project", tmp, "--json"])
            rid = json.loads(out)["id"]
            run(["resume", "--project", tmp])  # stamp a fresh packet
            res = crumb.set_record_status(mem, rid, "stale", "needs revalidation")
            self.assertTrue(res["ok"])
            # The flip dropped the decision from the active set; the projection
            # must follow, so validate's freshness check stays clean.
            self.assertEqual([f for f in no_fails(mem) if f["check"] == "freshness"], [])

    def test_reindex_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            code, _ = run(["reindex", "--project", tmp])
            self.assertEqual(code, 0)
            self.assertTrue((mem / "generated" / "resume-packet.md").is_file())

    def test_mcp_record_reindexes(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            res = mcp_core.tool_record(
                "decision",
                {"title": "via mcp", "evidence": [{"type": "commit", "ref": "abc1234"}]},
                root=tmp,
            )
            self.assertTrue(res["ok"])
            self.assertEqual([f for f in no_fails(mem) if f["check"] == "freshness"], [])

    def test_mcp_verify_and_reindex_tools(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            res = mcp_core.tool_verify("subj", "open",
                                       evidence=[{"type": "file", "ref": "a.py:1"}], root=tmp)
            self.assertTrue(res["ok"])
            self.assertEqual(res["outcome"], "open")
            ri = mcp_core.tool_reindex(root=tmp)
            self.assertTrue(ri["ok"])


# --------------------------------------------------------------------------- #
# F3 — validate freshness check
# --------------------------------------------------------------------------- #
class FreshnessTests(unittest.TestCase):
    def test_handedit_drift_fails_validate_then_reindex_heals(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(["remember", "decision", "--title", "seed",
                 "--evidence", "commit", "abc1234", "--project", tmp])
            run(["resume", "--project", tmp])  # stamp a fresh packet
            self.assertEqual(no_fails(mem), [])
            # Hand-edit a canonical record without reindexing.
            dec = next((mem / "decisions").glob("*.md"))
            dec.write_text(dec.read_text(encoding="utf-8") + "\n<!-- drift -->\n", encoding="utf-8")
            fails = no_fails(mem)
            self.assertTrue(any(f["check"] == "freshness" for f in fails))
            run(["reindex", "--project", tmp])
            self.assertEqual(no_fails(mem), [])


# --------------------------------------------------------------------------- #
# F4 — task-scoped likely_files
# --------------------------------------------------------------------------- #
class TaskScopedFilesTests(unittest.TestCase):
    def test_cold_task_labels_empty_likely_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            packet = crumb.build_resume_packet(mem, Path(tmp), task="rewrite k8s ingress")
            self.assertEqual(packet["likely_files"], [])
            self.assertIn("starting cold", packet["likely_files_note"])
            self.assertEqual(packet["requested_task"], "rewrite k8s ingress")

    def test_matching_task_scopes_to_record_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            root = Path(tmp)
            run(["remember", "decision", "--title", "startup db validation moved",
                 "--evidence", "file", "app/Startup.kt:170", "--tags", "startup",
                 "--project", tmp])
            packet = crumb.build_resume_packet(mem, root, task="startup db validation in app/Startup.kt")
            self.assertIn("app/Startup.kt:170", packet["likely_files"])
            self.assertNotIn("likely_files_note", packet)


if __name__ == "__main__":
    unittest.main()
