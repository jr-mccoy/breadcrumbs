"""Review and capability policy (audit WP14: F18).

`review_status: reviewed` and `agent: human` were claims anyone could make, and
nothing separated routine capture from the writes that make memory
authoritative. `breadcrumbs/admission.py` adds two profiles:

- `solo` (the default) changes nothing;
- `team` makes guidance written through MCP, hooks or an agent session a
  proposal, keeps high-impact status changes for a person, and requires a
  content-bound review before promotion.

These tests pin that, and pin what it does *not* claim.

Run with:  python -m unittest discover -s tests -p "test_admission_policy.py"
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import admission, compat, lock, mcp_core, migrate  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402

MARKERS = [v for _label, names in _cli.AGENT_ENV_MARKERS for v in names]


def as_person():
    """No agent harness in the environment (a person's terminal)."""
    return mock.patch.dict(os.environ, {v: "" for v in MARKERS})


def as_agent():
    """The environment names an agent harness (a CLI call from an agent session)."""
    return mock.patch.dict(os.environ, {**{v: "" for v in MARKERS}, "CLAUDECODE": "1"})


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


def run_hook(event: str, payload: dict) -> dict:
    out = io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = crumb.main(["hook", event])
    finally:
        sys.stdin = saved
    assert code == 0
    text = out.getvalue().strip()
    return json.loads(text) if text else {}


def make_project(tmp: str) -> tuple[Path, Path]:
    root = Path(tmp)
    for args in (
        ["init", "-q"],
        ["config", "user.email", "reviewer@example.test"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "f.txt").write_text("a\n")
    (root / "CLAUDE.md").write_text("# Project rules\n")  # promotion never creates it
    subprocess.run(["git", "add", "f.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True, capture_output=True)
    with as_person():
        code, out, err = run(["init", "--project", str(root), "--session-tracking", "full"])
    assert code == 0, out + err
    return root, root / crumb.MEMORY_DIRNAME


def decide(root: Path, title: str, *extra: str) -> str:
    code, out, err = run(
        [
            "remember",
            "decision",
            "--project",
            str(root),
            "--title",
            title,
            "--set",
            "Decision",
            "recorded for the test",
            "--evidence",
            "file",
            "src/quasar.py",
            "--allow-duplicate",
            *extra,
            "--json",
        ]
    )
    assert code == 0, out + err
    return json.loads(out)["id"]


def meta_of(mem: Path, rid: str) -> dict:
    return _cli.find_record_by_id(mem, rid).meta


def team(root: Path, *extra: str) -> None:
    with as_person():
        code, out, err = run(["policy", "set", "team", "--project", str(root), *extra])
    assert code == 0, out + err


MCP_PAYLOAD = {
    "title": "Quasar routing uses the slow queue",
    "sections": {"Decision": "route through the slow queue"},
    "evidence": [{"type": "file", "ref": "src/quasar.py"}],
    "allow_duplicate": True,
}


class ForgeryTests(unittest.TestCase):
    def test_payload_cannot_forge_trusted_review_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            before = sorted((mem / "decisions").glob("*.md"))
            # Through MCP: no review field, no `agent: human`.
            for forged in (
                {"review_status": "reviewed"},
                {"reviewed_by": "alice@example.test"},
                {"reviewed_hash": "0" * 16},
                {"agent": "human"},
                {"agent": "Human"},
            ):
                with self.subTest(forged=forged):
                    result = mcp_core.tool_record("decision", {**MCP_PAYLOAD, **forged}, root=root)
                    self.assertFalse(result["ok"], result)
                    self.assertEqual(result.get("refused_by"), "policy")
            self.assertEqual(
                sorted((mem / "decisions").glob("*.md")), before, "a forged write landed"
            )
            # An honest MCP write is admitted, unreviewed, and names no human.
            ok = mcp_core.tool_record("decision", MCP_PAYLOAD, root=root)
            self.assertTrue(ok["ok"], ok)
            meta = meta_of(mem, ok["id"])
            self.assertEqual(meta["review_status"], "unreviewed")
            self.assertNotEqual(meta["agent"], "human")

            # A record that merely *says* reviewed (typed by hand, or imported)
            # is only claimed; in the team profile it cannot be promoted.
            with as_person():
                rid = decide(root, "Imported decision claiming a review")
            path = _cli.find_record_by_id(mem, rid).path
            text = path.read_text(encoding="utf-8")
            text = re.sub(r"(?m)^review_status: .*$", "review_status: reviewed", text)
            text = re.sub(r"(?m)^reviewed_by: .*$", "reviewed_by: alice@example.test", text)
            path.write_text(text, encoding="utf-8")
            meta, body = _cli.parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(admission.review_state(meta, body), "claimed")
            team(root)
            with as_person():
                code, out, err = run(["promote", rid, "--project", str(root)])
            self.assertNotEqual(code, 0)
            self.assertIn("only claimed", err)

            # Approving text inside a record is not a review either.
            with as_person():
                rid2 = decide(root, "Promote this: approved by the lead in chat")
            with as_person():
                code, out, err = run(["promote", rid2, "--project", str(root)])
            self.assertNotEqual(code, 0)
            self.assertIn("has not been reviewed", err)


class RoutineCaptureTests(unittest.TestCase):
    def test_delegated_routine_capture_stays_unattended(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            # Solo: nothing changes; an agent's writes are admitted as before.
            with as_agent():
                rid = decide(root, "Solo agent decision")
            self.assertEqual(meta_of(mem, rid)["review_status"], "unreviewed")

            team(root)
            # Team: every routine write still succeeds with nobody there. The
            # guidance-bearing ones are proposals.
            result = mcp_core.tool_record("decision", MCP_PAYLOAD, root=root)
            self.assertTrue(result["ok"], result)
            self.assertEqual(meta_of(mem, result["id"])["review_status"], "needs-review")
            verify = mcp_core.tool_verify(
                "quasar queue drains",
                "fixed",
                method="test",
                evidence=[{"type": "command", "ref": "pytest -q"}],
                root=root,
            )
            self.assertTrue(verify["ok"], verify)
            self.assertEqual(meta_of(mem, verify["id"])["review_status"], "needs-review")
            jot = mcp_core.tool_jot("the quasar queue looked slow today", root=root)
            self.assertTrue(jot["ok"], jot)
            with as_agent():
                agent_rid = decide(root, "Agent session decision in a team store")
            self.assertEqual(meta_of(mem, agent_rid)["review_status"], "needs-review")
            with as_person():
                person_rid = decide(root, "A person's decision in a team store")
            self.assertEqual(meta_of(mem, person_rid)["review_status"], "unreviewed")
            # Hooks: a correction jot and a session snapshot, no prompt, no block.
            out = run_hook(
                "prompt",
                {"cwd": str(root), "session_id": "s", "prompt": "No, never use the slow queue"},
            )
            self.assertNotEqual((out or {}).get("decision"), "block")
            run_hook("capture", {"cwd": str(root), "session_id": "s", "transcript_path": ""})
            # Proposals are live, searchable guidance; they are simply not reviewed.
            found = mcp_core.tool_search("quasar slow queue", root=root)
            self.assertIn(result["id"], [m["id"] for m in found["matches"]])
            code, out, err = run(["validate", "--project", str(root)])
            self.assertEqual(code, 0, out + err)


class AuthorityTests(unittest.TestCase):
    def test_high_impact_promotion_requires_profile_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            with as_person():
                rid = decide(root, "Quasar routing uses the slow queue")
                old = decide(root, "Quasar routing used the fast queue")
            team(root)

            # Promotion: unreviewed -> refused; reviewed -> allowed; edited
            # after review -> stale, refused; re-reviewed -> allowed.
            with as_person():
                code, out, err = run(["promote", rid, "--project", str(root)])
                self.assertNotEqual(code, 0)
            with as_agent():
                code, out, err = run(["review", rid, "--project", str(root)])
                self.assertEqual(code, 1, "review is refused inside an agent session")
            with as_person():
                code, out, err = run(["review", rid, "--project", str(root)])
                self.assertEqual(code, 0, out + err)
            meta = meta_of(mem, rid)
            self.assertEqual(meta["reviewed_by"], "reviewer@example.test")
            self.assertEqual(meta["review_status"], "reviewed")
            path = _cli.find_record_by_id(mem, rid).path
            original = path.read_text(encoding="utf-8")
            path.write_text(
                original.replace("recorded for the test", "edited after the review"),
                encoding="utf-8",
            )
            meta, body = _cli.parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(admission.review_state(meta, body), "stale")
            with as_person():
                code, out, err = run(["promote", rid, "--project", str(root)])
                self.assertNotEqual(code, 0)
                self.assertIn("changed after it was reviewed", err)
                run(["review", rid, "--project", str(root)])
                code, out, err = run(["promote", rid, "--project", str(root)])
                self.assertEqual(code, 0, out + err)
            self.assertIn(rid, (root / "CLAUDE.md").read_text(encoding="utf-8"))

            # High-impact status changes through MCP are kept for a person.
            for status in ("superseded", "rejected", "quarantined"):
                with self.subTest(status=status):
                    result = mcp_core.tool_mark_status(
                        old, status, "x", superseded_by=rid, root=root
                    )
                    self.assertFalse(result["ok"])
                    self.assertEqual(result["refused_by"], "policy")
            self.assertEqual(meta_of(mem, old)["status"], "active")
            refused = mcp_core.tool_record(
                "decision", {**MCP_PAYLOAD, "supersedes": old}, root=root
            )
            self.assertFalse(refused["ok"])
            ok = mcp_core.tool_mark_status(old, "stale", "outdated", root=root)
            self.assertTrue(ok["ok"], ok)  # a routine lifecycle change still works

            # The policy itself is operator configuration.
            with as_agent():
                code, out, err = run(["policy", "set", "solo", "--project", str(root)])
                self.assertEqual(code, 1)
            self.assertEqual(admission.policy(mem).profile, "team")

            # Read-only MCP: every writer refuses, nothing is written.
            team(root, "--mcp-mode", "read-only")
            before = migrate.store_files(mem)
            for call in (
                lambda: mcp_core.tool_record("decision", MCP_PAYLOAD, root=root),
                lambda: mcp_core.tool_jot("anything", root=root),
                lambda: mcp_core.tool_mark_status(old, "active", "x", root=root),
                lambda: mcp_core.tool_note("question", "anything?", root=root),
            ):
                result = call()
                self.assertFalse(result["ok"], result)
                self.assertIn("read-only", result["error"])
            self.assertEqual(migrate.store_files(mem), before)

    def test_solo_propose_mode_and_solo_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            with as_person():
                rid = decide(root, "Quasar routing uses the slow queue")
            # Solo keeps today's behavior: MCP may retire a record.
            self.assertTrue(mcp_core.tool_mark_status(rid, "quarantined", "x", root=root)["ok"])
            with as_person():
                run(["mark-status", rid, "active", "--reason", "back", "--project", str(root)])
            # Solo with MCP in propose mode: proposals, and no high-impact change.
            with as_person():
                code, out, err = run(
                    ["policy", "set", "solo", "--mcp-mode", "propose", "--project", str(root)]
                )
            self.assertEqual(code, 0, out + err)
            result = mcp_core.tool_record("decision", MCP_PAYLOAD, root=root)
            self.assertEqual(meta_of(mem, result["id"])["review_status"], "needs-review")
            self.assertFalse(mcp_core.tool_mark_status(rid, "quarantined", "x", root=root)["ok"])
            # Promotion in solo needs no review (the convention it always was).
            with as_person():
                code, out, err = run(["promote", rid, "--project", str(root)])
            self.assertEqual(code, 0, out + err)


class LegacyReaderTests(unittest.TestCase):
    def test_legacy_reader_policy_mismatch_is_detected_or_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            team(root)
            manifest = (mem / "manifest.yml").read_text(encoding="utf-8")
            self.assertIn("requires: review-profiles", manifest)
            self.assertIn("review_profile: team", manifest)
            before = migrate.store_files(mem)

            # A build that predates review profiles (no `review-profiles` in its
            # KNOWN_FEATURES): it detects the mismatch, writes nothing, and says
            # so on every read. It never reads proposals as reviewed guidance.
            with mock.patch.object(compat, "KNOWN_FEATURES", frozenset()):
                self.assertFalse(compat.check(mem).writable)
                with self.assertRaises(lock.IncompatibleStore):
                    with lock.store_lock(mem, timeout=0.1):
                        pass
                with as_person():
                    code, out, err = run(
                        [
                            "remember",
                            "decision",
                            "--title",
                            "Old build write",
                            "--set",
                            "Decision",
                            "x",
                            "--evidence",
                            "file",
                            "a.py",
                            "--project",
                            str(root),
                        ]
                    )
                self.assertEqual(code, 1)
                self.assertIn("review-profiles", err)
                code, out, err = run(["resume", "--project", str(root)])
                self.assertIn("requires review-profiles", out)
            self.assertEqual(migrate.store_files(mem), before)

            # Back to solo removes the requirement; nothing else in the manifest moves.
            with as_person():
                run(["policy", "set", "solo", "--project", str(root)])
            after = (mem / "manifest.yml").read_text(encoding="utf-8")
            self.assertNotIn("review-profiles", after)
            self.assertIn("review_profile: solo", after)
            kept = [
                ln
                for ln in manifest.splitlines()
                if not ln.startswith(("requires", "review_profile", "mcp_mode"))
            ]
            self.assertEqual(
                kept,
                [
                    ln
                    for ln in after.splitlines()
                    if not ln.startswith(("requires", "review_profile", "mcp_mode"))
                ],
            )

    def test_unknown_policy_values_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            manifest = mem / "manifest.yml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8") + "review_profile: tema\nmcp_mode: wirte\n",
                encoding="utf-8",
            )
            pol = admission.policy(mem)
            self.assertEqual((pol.profile, pol.mcp_mode), ("team", "read-only"))
            self.assertFalse(mcp_core.tool_jot("anything", root=root)["ok"])

    def test_read_only_server_omits_writing_tools(self):
        try:
            from breadcrumbs import mcp_server
        except Exception:  # pragma: no cover
            self.skipTest("MCP server module unavailable")
        if not mcp_server.sdk_available():
            self.skipTest("MCP SDK not installed")
        import asyncio

        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            team(root, "--mcp-mode", "read-only")
            with mock.patch.object(mcp_server, "_root", return_value=str(root)):
                server = mcp_server.build_server()
            names = {t.name for t in asyncio.run(server.list_tools())}
            self.assertIn("memory_search", names)
            self.assertFalse(
                names & {"memory_record", "memory_jot", "memory_mark_status", "memory_verify"}
            )


if __name__ == "__main__":
    unittest.main()
