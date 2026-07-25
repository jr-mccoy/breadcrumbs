"""Tests for `crumb audit` (Phase 6, plan §10/§15/§16 note/§19b).

`audit` is the heuristic safety net `validate`'s determinism intentionally excludes.
Covered here:
  - severity ladder + exit codes (only secrets block);
  - the 19b.9 health view (stale handoff, missing evidence, invalid status,
    private-path violation, branch mismatch, packet drift);
  - instruction-like flagging (Fixture 7) with the data-not-instruction posture;
  - generated-packet drift (Fixture 8);
  - bloat (adapter duplication, over-budget packet, sessions growth).

Run with:  python -m unittest discover -s tests
       or:  python tests/test_audit.py
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402

FIXTURES = REPO_ROOT / "fixtures"
DATA = REPO_ROOT / "tests" / "data"


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def fresh_store(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


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


def audit_findings(project: str) -> list[dict]:
    code, out = run(["audit", "--project", project, "--json"])
    return json.loads(out)["findings"]


def checks(findings: list[dict]) -> set[str]:
    return {f["check"] for f in findings}


def warns_text(findings: list[dict]) -> str:
    return " ".join(f["message"] for f in findings).lower()


# --------------------------------------------------------------------------- #
# Severity ladder + exit codes
# --------------------------------------------------------------------------- #
class SeverityTests(unittest.TestCase):
    def test_only_secret_blocks(self):
        # A fresh store with a clean handoff: warnings at most, never a failure.
        with tempfile.TemporaryDirectory() as tmp:
            fresh_store(tmp)
            code, out = run(["audit", "--project", tmp, "--json"])
            self.assertEqual(code, 0, out)
            payload = json.loads(out)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["failed"], 0)

    def test_secret_makes_audit_nonzero(self):
        code, out = run(["audit", "--project", str(FIXTURES / "fixture-06-secret-leak")])
        self.assertEqual(code, 1, out)

    def test_warnings_do_not_change_exit_code(self):
        # fixture-07 has instruction-like warnings but no secret -> exit 0.
        code, _ = run(["audit", "--project", str(FIXTURES / "fixture-07-poisoned-text")])
        self.assertEqual(code, 0)


# --------------------------------------------------------------------------- #
# 19b.9 health view — audit surfaces what validate gates
# --------------------------------------------------------------------------- #
class HealthViewTests(unittest.TestCase):
    def _inject(self, mem: Path, subdir: str, fixture: str) -> None:
        shutil.copy(DATA / subdir / fixture, mem / subdir)

    def test_missing_evidence_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            self._inject(mem, "decisions", "2026-06-25-missing-evidence.md")
            self.assertIn("evidence", checks(crumb.run_audit(mem, Path(tmp))))

    def test_invalid_status_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            self._inject(mem, "decisions", "2026-06-25-bad-status.md")
            self.assertIn("status", checks(crumb.run_audit(mem, Path(tmp))))

    def test_private_path_violation_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = fresh_store(tmp)
            self._inject(mem, "decisions", "2026-06-25-local-private.md")
            self.assertIn("privacy", checks(crumb.run_audit(mem, Path(tmp))))

    def test_stale_handoff_surfaced(self):
        findings = audit_findings(str(FIXTURES / "fixture-04-stale-handoff"))
        blob = warns_text([f for f in findings if f["check"] == "staleness"])
        self.assertIn("handoff", blob)
        self.assertIn("old", blob)

    def test_branch_mismatch_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = fresh_store(tmp)
            crumb.write_record(
                mem,
                root,
                "decision",
                "keep accounts immutable",
                {"Decision": "never drop accounts", "Rationale": "billing depends on it"},
                tags=["accounts"],
                evidence=[
                    {"type": "file", "ref": "src/db/accounts.ts"},
                    {"type": "commit", "ref": "abc1234"},
                ],
            )
            git(root, "checkout", "-q", "-b", "feature-x")
            findings = crumb.run_audit(mem, root)
            # The record was written on the original branch; HEAD is now on
            # feature-x. (The handoff-level "branch mismatch" line no longer
            # fires here: a fresh store's handoff carries only the template
            # placeholder branch, which is placeholder-aware since review #3 R19.)
            self.assertIn("written on other branches", warns_text(findings))


# --------------------------------------------------------------------------- #
# Fixture 7 — instruction-like flag; guard treats it as data
# --------------------------------------------------------------------------- #
class InstructionLikeTests(unittest.TestCase):
    def test_audit_flags_override_phrasing(self):
        findings = audit_findings(str(FIXTURES / "fixture-07-poisoned-text"))
        il = [f for f in findings if f["check"] == "instruction-like"]
        self.assertTrue(il, "expected an instruction-like flag")
        self.assertTrue(all(f["severity"] == crumb.AUDIT_WARN for f in il))

    def test_validate_does_not_flag_instruction_like(self):
        """The same store must validate clean — instruction-like is heuristic only."""
        mem = FIXTURES / "fixture-07-poisoned-text" / ".project-memory"
        fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
        self.assertEqual(fails, [])

    def test_guard_treats_poisoned_text_as_data(self):
        res_code, out = run(
            [
                "guard",
                "speed up the test runner",
                "--files",
                "src/runner.ts",
                "--project",
                str(FIXTURES / "fixture-07-poisoned-text"),
                "--json",
            ]
        )
        self.assertEqual(res_code, 0)
        res = json.loads(out)
        self.assertTrue(res["matches"])  # the record surfaces...
        na = res["next_action"].lower()
        # ...but the imperative is never lifted into the recommended action.
        self.assertNotIn("ignore the tests", na)
        self.assertNotIn("skip verification", na)


# --------------------------------------------------------------------------- #
# Fixture 8 — generated-packet drift
# --------------------------------------------------------------------------- #
class PacketDriftTests(unittest.TestCase):
    def test_audit_flags_stale_packet(self):
        findings = audit_findings(str(FIXTURES / "fixture-08-packet-stale"))
        drift = [f for f in findings if f["check"] == "packet-drift"]
        self.assertTrue(drift, "expected a packet-drift flag")
        self.assertEqual(drift[0]["severity"], crumb.AUDIT_WARN)

    def test_matching_hash_is_not_flagged(self):
        # fixture-09 ships an accurate packet -> no drift.
        findings = audit_findings(str(FIXTURES / "fixture-09-cloud-fallback"))
        self.assertEqual([f for f in findings if f["check"] == "packet-drift"], [])

    def test_drift_detect_unit(self):
        mem = FIXTURES / "fixture-08-packet-stale" / ".project-memory"
        drift = crumb.detect_packet_drift(mem)
        self.assertTrue(drift)
        self.assertEqual(drift[0]["stamped"], "000000000000")
        self.assertNotEqual(drift[0]["stamped"], drift[0]["current"])


# --------------------------------------------------------------------------- #
# Bloat
# --------------------------------------------------------------------------- #
class BloatTests(unittest.TestCase):
    def test_sessions_growth_note(self):
        findings = audit_findings(str(FIXTURES / "fixture-10-many-sessions"))
        bloat = [
            f for f in findings if f["check"] == "bloat" and f.get("kind") == "sessions-growth"
        ]
        self.assertTrue(bloat)
        self.assertEqual(bloat[0]["severity"], crumb.AUDIT_INFO)

    def test_adapter_duplication_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mem = fresh_store(tmp)
            rec_path, _ = crumb.write_record(
                mem,
                root,
                "decision",
                "keep memory in plain files",
                {
                    "Decision": "plain markdown is canonical",
                    "Rationale": "a read-only agent can read it",
                },
                tags=["memory"],
                evidence=[{"type": "commit", "ref": "abc1234"}],
            )
            body = Path(rec_path).read_text(encoding="utf-8")
            # An adapter file that copies the record body verbatim.
            (root / "CLAUDE.md").write_text("# signpost\n\n" + body, encoding="utf-8")
            findings = crumb.run_audit(mem, root)
            kinds = {f.get("kind") for f in findings if f["check"] == "bloat"}
            self.assertIn("adapter-duplication", kinds)


# --------------------------------------------------------------------------- #
# CLI surface
# --------------------------------------------------------------------------- #
class CliTests(unittest.TestCase):
    def test_json_shape(self):
        code, out = run(["audit", "--project", str(FIXTURES / "fixture-01-fresh-resume"), "--json"])
        payload = json.loads(out)
        for key in ("ok", "failed", "warnings", "info", "findings"):
            self.assertIn(key, payload)

    def test_missing_store_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(["audit", "--project", tmp])
            self.assertEqual(code, 2)

    def test_human_output_renders(self):
        _, out = run(["audit", "--project", str(FIXTURES / "fixture-06-secret-leak")])
        self.assertIn("Blocking", out)
        self.assertIn("secret", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
