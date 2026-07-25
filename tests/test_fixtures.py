"""End-to-end fixture suite (Phase 6, plan §17 / §19b.11).

Runs all eleven evaluation fixtures through `validate` and `audit`, and pins the
fixtures that assert a whole-system property rather than a single check:
  - Fixture 9 (cloud fallback): plain files + a committed packet answer the six
    reorientation questions with NO CLI execution;
  - Fixture 10 (many sessions): the resume packet stays bounded and prioritises
    current/handoff/active decisions over old session observations;
  - Fixture 11 (multi-machine): a distillate store with no `sessions/` stays clean
    from two different checkout paths — pinned in `tests/test_multi_machine.py`.

Run with:  python -m unittest discover -s tests
       or:  python tests/test_fixtures.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402

FIXTURES = REPO_ROOT / "fixtures"

ALL_FIXTURES = [
    "fixture-01-fresh-resume",
    "fixture-02-guard-true-positive",
    "fixture-03-guard-false-positive",
    "fixture-04-stale-handoff",
    "fixture-05-superseded-decision",
    "fixture-06-secret-leak",
    "fixture-07-poisoned-text",
    "fixture-08-packet-stale",
    "fixture-09-cloud-fallback",
    "fixture-10-many-sessions",
    "fixture-11-multi-machine",
]

# fixture-06 is the one fixture whose audit is expected to BLOCK (a committed secret).
AUDIT_SHOULD_FAIL = {"fixture-06-secret-leak"}

# fixture-08 ships a deliberately stale generated projection. The projection-
# freshness check (review F3) makes `validate` flag it, so it is excluded from the
# "validates clean" set and pinned by its own freshness test below.
VALIDATE_SHOULD_FLAG_FRESHNESS = {"fixture-08-packet-stale"}


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def mem_of(name: str) -> Path:
    return FIXTURES / name / ".project-memory"


# --------------------------------------------------------------------------- #
# Every fixture validates (structure is well-formed even when audit objects)
# --------------------------------------------------------------------------- #
class ValidateAllTests(unittest.TestCase):
    def test_all_fixtures_validate_clean(self):
        for name in ALL_FIXTURES:
            if name in VALIDATE_SHOULD_FLAG_FRESHNESS:
                continue
            with self.subTest(fixture=name):
                fails = [f for f in crumb.run_validate(mem_of(name)) if f["status"] == "fail"]
                self.assertEqual(fails, [], f"{name}: {fails}")

    def test_stale_projection_fails_validate_freshness(self):
        # review F3: validate must not stay green while a projection is stale.
        for name in VALIDATE_SHOULD_FLAG_FRESHNESS:
            with self.subTest(fixture=name):
                fails = [f for f in crumb.run_validate(mem_of(name)) if f["status"] == "fail"]
                self.assertTrue(
                    any(f["check"] == "freshness" for f in fails),
                    f"{name}: expected a freshness fail, got {fails}",
                )


# --------------------------------------------------------------------------- #
# Audit runs on every fixture; only the secret fixture blocks
# --------------------------------------------------------------------------- #
class AuditAllTests(unittest.TestCase):
    def test_audit_exit_codes(self):
        for name in ALL_FIXTURES:
            with self.subTest(fixture=name):
                code, out = run(["audit", "--project", str(FIXTURES / name)])
                expected = 1 if name in AUDIT_SHOULD_FAIL else 0
                self.assertEqual(code, expected, f"{name}: exit {code}\n{out}")

    def test_audit_never_crashes_and_emits_json(self):
        for name in ALL_FIXTURES:
            with self.subTest(fixture=name):
                _, out = run(["audit", "--project", str(FIXTURES / name), "--json"])
                payload = json.loads(out)
                self.assertIn("findings", payload)


# --------------------------------------------------------------------------- #
# Fixture 9 — cloud fallback: plain files + committed packet, no CLI
# --------------------------------------------------------------------------- #
class CloudFallbackTests(unittest.TestCase):
    """A read-only agent with no CLI must reorient from committed files alone."""

    def test_committed_packet_answers_the_six_questions(self):
        packet = mem_of("fixture-09-cloud-fallback") / "generated" / "resume-packet.md"
        self.assertTrue(packet.is_file(), "fixture 9 must ship a committed packet")
        text = packet.read_text(encoding="utf-8")
        # 1 project, 2 current focus, 3 next action, 4 a decision, 5 a failed attempt.
        self.assertIn("demo-service", text)
        self.assertIn("Plain-file portability", text)
        self.assertIn("Next Action", text)
        self.assertIn("dec_20260610_markdown-source-of-truth", text)
        self.assertIn("att_20260612_sqlite-store", text)

    def test_plain_files_alone_answer_the_questions(self):
        """Without running any command, the plain files carry the answers."""
        mem = mem_of("fixture-09-cloud-fallback")
        handoff = (mem / "handoff.md").read_text(encoding="utf-8")
        self.assertIn("Current Focus", handoff)
        self.assertIn("Next Action", handoff)
        decisions = list((mem / "decisions").glob("*.md"))
        attempts = list((mem / "attempts").glob("*.md"))
        self.assertTrue(decisions, "a decision file must exist for plain-file resume")
        self.assertTrue(attempts, "an attempt file must exist for plain-file resume")

    def test_committed_packet_is_tracked_not_ignored(self):
        rel = "fixtures/fixture-09-cloud-fallback/.project-memory/generated/resume-packet.md"
        import subprocess
        r = subprocess.run(
            ["git", "check-ignore", rel], cwd=str(REPO_ROOT), capture_output=True, text=True
        )
        self.assertNotEqual(r.returncode, 0, "fixture-9 packet must be committed, not ignored")


# --------------------------------------------------------------------------- #
# Fixture 10 — many sessions: bounded + prioritised
# --------------------------------------------------------------------------- #
class ManySessionsTests(unittest.TestCase):
    def test_one_hundred_session_records_exist(self):
        sessions = list((mem_of("fixture-10-many-sessions") / "sessions").glob("*.md"))
        self.assertEqual(len(sessions), 100, len(sessions))

    def test_resume_packet_stays_bounded_and_prioritised(self):
        mem = mem_of("fixture-10-many-sessions")
        root = FIXTURES / "fixture-10-many-sessions"
        packet = crumb.build_resume_packet(mem, root)
        md = crumb.render_packet_markdown(packet)
        self.assertLessEqual(crumb.approx_tokens(md), crumb.TOKEN_BUDGET_MAX)
        # Current/handoff/active-decisions are present (the prioritised core)...
        self.assertTrue(packet["current_focus"])
        self.assertTrue(packet["next_action"])
        self.assertIn("dec_20260601_bounded-packet", [d["id"] for d in packet["active_decisions"]])
        # ...and no raw session transcript leaks into the packet.
        self.assertNotIn("old observation #50", md)
        self.assertNotIn("Routine session", md)


if __name__ == "__main__":
    unittest.main(verbosity=2)
