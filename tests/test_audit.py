"""Tests for `crumb audit` (§19b).

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
from breadcrumbs import cli  # noqa: E402  (`crumb` is a flat re-export; patching needs the module)

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
            # placeholder branch, and that placeholder is recognized as one.)
            self.assertIn("written on other branches", warns_text(findings))

    def test_records_from_a_merged_branch_are_not_a_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            base = crumb.git_branch(root)
            git(root, "checkout", "-q", "-b", "feature-x")
            mem = fresh_store(tmp)
            crumb.write_record(
                mem,
                root,
                "decision",
                "keep accounts immutable",
                {"Decision": "never drop accounts", "Rationale": "billing depends on it"},
                tags=["accounts"],
            )
            git(root, "add", "-A")
            git(root, "commit", "-qm", "memory on feature-x")
            git(root, "checkout", "-q", base)
            git(root, "merge", "-q", "--no-ff", "-m", "merge feature-x", "feature-x")
            findings = crumb.run_audit(mem, root)
            # The record still says `branch: feature-x`, and that branch has
            # been merged into HEAD: its file is committed here, unmodified.
            self.assertNotIn("written on other branches", warns_text(findings))
            self.assertNotIn("branch mismatch", warns_text(findings))


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

    def test_factual_never_run_is_not_flagged(self):
        """P2-11 (0.1.10 field test): all 7 instruction-like warnings fired on
        factual past/passive phrasing like 'E2E has never run in production'."""
        factual = [
            "E2E has never run in production",
            "the migration was never run against the replica",
            "these checks have never run on Windows",
            "the suite is never run on release branches",
        ]
        imperative = [
            "never run the migration by hand",
            "always run the formatter before committing",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mem = root / crumb.MEMORY_DIRNAME
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            lines = "".join(f"- {s}\n" for s in factual + imperative)
            (mem / "known-traps.md").write_text(f"# Known Traps\n\n## trap_t: t\n{lines}")
            hits = crumb.scan_instruction_like(mem)
            phrases_at = {h["line"] for h in hits if h["path"] == "known-traps.md"}
            # Lines 1-3 are headers; the bullets start at line 4.
            factual_lines = set(range(4, 4 + len(factual)))
            imperative_lines = set(range(4 + len(factual), 4 + len(factual) + len(imperative)))
            self.assertEqual(phrases_at & factual_lines, set(), hits)
            self.assertEqual(phrases_at & imperative_lines, imperative_lines, hits)

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
        res = json.loads(out)
        # Exit code is verdict-mapped (P0-1); this test cares about content, not band.
        self.assertEqual(res_code, crumb.GUARD_VERDICT_EXIT_CODES[res["verdict"]])
        self.assertTrue(res["matches"])  # the record surfaces...
        na = res["recommended_action"].lower()
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
                    # Long enough that the body clears the duplication check's
                    # 200-char substance floor now that empty sections are
                    # omitted instead of stubbed (P2-10).
                    "Rationale": "a read-only agent can read it without any tooling, "
                    "a human can review it in any diff view, and no database or index "
                    "has to exist for the memory to survive a checkout on a new machine",
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

    def test_a_large_host_file_with_a_small_signpost_is_not_bloat(self):
        """The signpost is ours to keep small; the instruction file is not ours."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mem = fresh_store(tmp)
            (root / "CLAUDE.md").write_text(
                "# FamilyHub\n\n" + ("project guidance\n" * 4000), encoding="utf-8"
            )
            crumb.write_adapter_block(root, "CLAUDE.md")
            self.assertGreater(
                len((root / "CLAUDE.md").read_text(encoding="utf-8")),
                10 * crumb.ADAPTER_BLOAT_CHARS,
            )
            kinds = {f.get("kind") for f in crumb.run_audit(mem, root) if f["check"] == "bloat"}
            self.assertNotIn("adapter-bloat", kinds)

    def test_a_bloated_managed_block_is_still_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mem = fresh_store(tmp)
            (root / "CLAUDE.md").write_text(
                crumb.ADAPTER_BEGIN + "\n" + ("x" * (crumb.ADAPTER_BLOAT_CHARS + 1)) + "\n"
                "" + crumb.ADAPTER_END + "\n",
                encoding="utf-8",
            )
            kinds = {f.get("kind") for f in crumb.run_audit(mem, root) if f["check"] == "bloat"}
            self.assertIn("adapter-bloat", kinds)


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


class FreshnessComplementarityTests(unittest.TestCase):
    """Pin that the two staleness checks answer *different* questions.

    The fix list files "three competing notions of projection freshness" as the
    strongest argument for splitting `cli.py`. Two of the three are not
    competing: `_inputs_hash` is the primitive, and the other two are complementary
    detectors, each catching a class the other cannot. This test reproduces both
    directions, so a future split (or a well-meant "deduplicate these") cannot
    collapse them without going red. The map is in the comment above `_inputs_hash`.
    """

    def _store(self, tmp: str) -> tuple[Path, Path]:
        root = Path(tmp)
        self.assertEqual(
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"]), 0
        )
        self.assertEqual(
            crumb.main(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    "Use markdown as the source of truth",
                    "--evidence",
                    "commit",
                    "abc1234",
                    "--set",
                    "Decision",
                    "Markdown files are canonical.",
                ]
            ),
            0,
        )
        mem = root / crumb.MEMORY_DIRNAME
        crumb.reindex_projections(mem, root)
        return root, mem

    def test_hash_drift_fires_where_a_byte_compare_cannot(self):
        """An edit the *bounded* packet never renders still invalidates the stamp."""
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                root, mem = self._store(tmp)
            self.assertFalse(crumb.detect_packet_drift(mem))
            self.assertFalse(crumb._packet_is_stale(mem, root))

            rec = next((mem / "decisions").glob("*.md"))
            rec.write_text(
                rec.read_text(encoding="utf-8")
                + "\n\n## Consequences\nDetail the bounded packet never prints.\n",
                encoding="utf-8",
            )
            self.assertTrue(crumb.detect_packet_drift(mem), "stamp must go stale")
            self.assertFalse(crumb._packet_is_stale(mem, root), "rendered bytes are unchanged here")

    def test_byte_compare_fires_where_a_hash_over_inputs_cannot(self):
        """A renderer change leaves every input untouched — no hash can see it."""
        with tempfile.TemporaryDirectory() as tmp:
            with contextlib.redirect_stdout(io.StringIO()):
                root, mem = self._store(tmp)
            real = cli.render_packet_markdown
            cli.render_packet_markdown = lambda p: real(p) + "\n<!-- newer renderer -->\n"
            try:
                self.assertFalse(crumb.detect_packet_drift(mem), "inputs are untouched")
                self.assertTrue(crumb._packet_is_stale(mem, root), "output would differ")
            finally:
                cli.render_packet_markdown = real


# --------------------------------------------------------------------------- #
# Guard reachability (field test 2026-08-04): a record with no tags and
# no file evidence can only surface through generic keyword overlap, which the
# stale factors readily push under the noise floor. Audit must say so while the
# author is still around to fix it.
# --------------------------------------------------------------------------- #
class UnreachableRecordTests(unittest.TestCase):
    def _store(self, tmp: str) -> tuple[Path, Path]:
        root = Path(tmp)
        self.assertEqual(
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"]), 0
        )
        return root, root / crumb.MEMORY_DIRNAME

    def test_prose_only_record_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store(tmp)
            path, _meta = crumb.write_record(
                mem,
                root,
                "decision",
                "Guest handling",
                {"Decision": "Keep the guest role internal to the enum"},
            )
            hits = [f for f in crumb.run_audit(mem, root) if f["check"] == "unreachable"]
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]["severity"], crumb.AUDIT_WARN)
            self.assertIn(path.name, hits[0]["path"])

    def test_tags_or_file_evidence_silence_the_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store(tmp)
            crumb.write_record(
                mem,
                root,
                "decision",
                "Tagged decision",
                {"Decision": "internal only"},
                tags=["roles"],
            )
            crumb.write_record(
                mem,
                root,
                "attempt",
                "Filed attempt",
                {"Tried": "a role refactor", "Outcome": "failed"},
                evidence=[{"type": "file", "ref": "src/roles.kt"}],
            )
            findings = crumb.run_audit(mem, root)
            self.assertEqual([f for f in findings if f["check"] == "unreachable"], [])

    def test_non_active_records_are_exempt(self):
        """A superseded record no longer drives verdicts; do not nag about it."""
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store(tmp)
            crumb.write_record(
                mem,
                root,
                "decision",
                "Old prose decision",
                {"Decision": "gone"},
                status="superseded",
            )
            findings = crumb.run_audit(mem, root)
            self.assertEqual([f for f in findings if f["check"] == "unreachable"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
