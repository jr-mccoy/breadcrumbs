"""Tests for the MCP server layer (Phase 8, plan §13).

These exercise the stdlib-only adapter core (`breadcrumbs.mcp_core`) plus the
graceful-degradation contract of the server module. They require NO third-party
MCP SDK — that is the point: the wrappers must be one source of behavior over the
CLI, and the server must degrade cleanly when the SDK is absent.

Run with:  python -m pytest tests/
       or:  python -m unittest discover -s tests
       or:  python tests/test_mcp.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli, mcp_core, mcp_server  # noqa: E402

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


def root_of(name: str) -> Path:
    return FIXTURES / name


def mem_of(name: str) -> Path:
    return root_of(name) / ".project-memory"


# --------------------------------------------------------------------------- #
# Resources return the SAME content the plain files / CLI show
# --------------------------------------------------------------------------- #
class ResourceParityTests(unittest.TestCase):
    def test_singletons_are_verbatim(self):
        name = "fixture-01-fresh-resume"
        root = root_of(name)
        for fname, fn in [
            ("current.md", mcp_core.resource_current),
            ("handoff.md", mcp_core.resource_handoff),
            ("open-questions.md", mcp_core.resource_open_questions),
            ("known-traps.md", mcp_core.resource_known_traps),
        ]:
            with self.subTest(resource=fname):
                expected = (mem_of(name) / fname).read_text(encoding="utf-8")
                self.assertEqual(fn(root), expected)

    def test_resume_packet_matches_cli_render(self):
        name = "fixture-10-many-sessions"
        root = root_of(name)
        # Pin the clock: `build_resume_packet` stamps `generated_at` via
        # `now_iso()` at call time, and this test builds the packet twice
        # (directly and through the MCP resource). Without a fixed clock the
        # two builds can straddle a second boundary and disagree only on the
        # timestamp line — a spurious failure.
        with mock.patch.object(cli, "now_iso", return_value="2026-01-01T00:00:00+00:00"):
            packet = cli.build_resume_packet(mem_of(name), root)
            expected = cli.render_packet_markdown(packet)
            self.assertEqual(mcp_core.resource_resume_packet(root), expected)

    def test_decisions_index_lists_active_ids(self):
        name = "fixture-01-fresh-resume"
        root = root_of(name)
        index = mcp_core.resource_decisions(root)
        for r in cli.active_decisions(mem_of(name)):
            self.assertIn(r.meta.get("id", r.stem), index)

    def test_decision_by_id_is_verbatim_file(self):
        name = "fixture-01-fresh-resume"
        root = root_of(name)
        decisions = cli.active_decisions(mem_of(name))
        self.assertTrue(decisions, "fixture must have a decision to test by-id read")
        rec = decisions[0]
        rid = rec.meta["id"]
        self.assertEqual(
            mcp_core.resource_decision(rid, root),
            rec.path.read_text(encoding="utf-8"),
        )

    def test_unknown_decision_id_raises(self):
        with self.assertRaises(KeyError):
            mcp_core.resource_decision("dec_20200101_nope", root_of("fixture-01-fresh-resume"))


# --------------------------------------------------------------------------- #
# memory_guard_before_action matches CLI `guard` verdicts on the fixtures
# --------------------------------------------------------------------------- #
class GuardParityTests(unittest.TestCase):
    ACTIONS = {
        "fixture-02-guard-true-positive": "switch the data store to sqlite",
        "fixture-03-guard-false-positive": "add a unit test for the parser",
        "fixture-05-superseded-decision": "switch the data store to sqlite",
    }

    def test_guard_tool_matches_cli_guard(self):
        for name in ALL_FIXTURES:
            action = self.ACTIONS.get(name, "refactor the resume packet builder")
            root = root_of(name)
            with self.subTest(fixture=name):
                cli_result = cli.guard(mem_of(name), root, action)
                tool_result = mcp_core.tool_guard_before_action(action, root=root)
                self.assertEqual(tool_result["verdict"], cli_result["verdict"])
                self.assertEqual(
                    [m["id"] for m in tool_result["matches"]],
                    [m["id"] for m in cli_result["matches"]],
                )


# --------------------------------------------------------------------------- #
# search / validate / scan_secrets parity
# --------------------------------------------------------------------------- #
class ToolParityTests(unittest.TestCase):
    def test_search_matches_cli(self):
        name = "fixture-02-guard-true-positive"
        root = root_of(name)
        matches, _ = cli.search(mem_of(name), root, "sqlite")
        tool = mcp_core.tool_search("sqlite", root=root)
        self.assertEqual(tool["count"], len(matches))
        self.assertEqual([m["id"] for m in tool["matches"]], [m["id"] for m in matches])

    def test_validate_reports_clean_fixtures(self):
        # fixture-08 ships a deliberately stale projection; the freshness check
        # (review F3) now flags it via validate, so it is no longer "clean".
        for name in ALL_FIXTURES:
            if name == "fixture-08-packet-stale":
                continue
            with self.subTest(fixture=name):
                self.assertTrue(mcp_core.tool_validate(root=root_of(name))["ok"])

    def test_validate_flags_stale_projection(self):
        result = mcp_core.tool_validate(root=root_of("fixture-08-packet-stale"))
        self.assertFalse(result["ok"])
        self.assertTrue(
            any(f["check"] == "freshness" for f in result["findings"] if f["status"] == "fail")
        )

    def test_scan_secrets_flags_only_the_secret_fixture(self):
        clean = mcp_core.tool_scan_secrets(root=root_of("fixture-01-fresh-resume"))
        leaky = mcp_core.tool_scan_secrets(root=root_of("fixture-06-secret-leak"))
        self.assertTrue(clean["clean"])
        self.assertFalse(leaky["clean"])
        self.assertGreater(leaky["count"], 0)


# --------------------------------------------------------------------------- #
# Writes go through the SAME validate gate (record + mark_status)
# --------------------------------------------------------------------------- #
class WriteGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # A real, initialized project (init writes the template tree + manifest).
        code = crumb.main(
            ["init", "--project", str(self.tmp), "--session-tracking", "full"]
        )
        self.assertEqual(code, 0)

    def test_record_writes_valid_decision(self):
        res = mcp_core.tool_record(
            "decision",
            {
                "title": "Use markdown as the source of truth",
                "sections": {"Decision": "Records are plain markdown.",
                             "Rationale": "Human-readable + diffable."},
                "evidence": [{"type": "commit", "ref": "abc1234"}],
            },
            root=self.tmp,
        )
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["type"], "decision")
        # The written record passes the global validate.
        self.assertTrue(mcp_core.tool_validate(root=self.tmp)["ok"])

    def test_record_without_evidence_is_forced_low_confidence(self):
        res = mcp_core.tool_record(
            "attempt",
            {"title": "Tried an in-memory store", "sections": {"What I tried": "RAM cache"}},
            root=self.tmp,
        )
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["confidence"], "low")

    def test_record_bad_type_rejected(self):
        res = mcp_core.tool_record("note", {"title": "x"}, root=self.tmp)
        self.assertFalse(res["ok"])

    def test_mark_status_is_validate_gated(self):
        rec = mcp_core.tool_record(
            "decision",
            {"title": "Pick a queue", "sections": {"Decision": "Use a queue."},
             "evidence": [{"type": "commit", "ref": "deadbee"}]},
            root=self.tmp,
        )
        rid = rec["id"]
        # A clean status change (stale) succeeds...
        ok = mcp_core.tool_mark_status(rid, "stale", "no longer current", root=self.tmp)
        self.assertTrue(ok["ok"], ok)
        self.assertEqual(ok["to"], "stale")
        self.assertTrue(mcp_core.tool_validate(root=self.tmp)["ok"])
        # ...but `superseded` without superseded_by is rejected by the gate (§16.6).
        bad = mcp_core.tool_mark_status(rid, "superseded", "replaced", root=self.tmp)
        self.assertFalse(bad["ok"])
        self.assertIn("validate", bad["error"])

    def test_mark_status_unknown_id(self):
        res = mcp_core.tool_mark_status("dec_20200101_nope", "stale", "x", root=self.tmp)
        self.assertFalse(res["ok"])


# --------------------------------------------------------------------------- #
# Prompts exist for every §13 flow and carry the data-not-instruction posture
# --------------------------------------------------------------------------- #
class PromptTests(unittest.TestCase):
    def test_all_six_prompts_present_and_nonempty(self):
        expected = {
            "resume_project", "capture_session", "remember_decision",
            "remember_attempt", "guard_before_action", "audit_project_memory",
        }
        self.assertEqual(set(mcp_core.PROMPTS), expected)
        for name, fn in mcp_core.PROMPTS.items():
            with self.subTest(prompt=name):
                self.assertTrue(fn().strip())


# --------------------------------------------------------------------------- #
# Graceful degradation: server imports without the SDK; no memory dir errors
# --------------------------------------------------------------------------- #
class GracefulDegradationTests(unittest.TestCase):
    def test_server_module_imports_without_sdk(self):
        # Import already succeeded at module top; assert the contract explicitly.
        self.assertTrue(hasattr(mcp_server, "build_server"))

    def test_build_server_raises_clear_error_when_sdk_missing(self):
        if mcp_server.sdk_available():
            self.skipTest("MCP SDK is installed; degradation path not exercised here")
        with self.assertRaises(RuntimeError) as ctx:
            mcp_server.build_server()
        self.assertIn("pip install", str(ctx.exception))

    def test_main_exits_nonzero_without_sdk(self):
        if mcp_server.sdk_available():
            self.skipTest("MCP SDK is installed")
        self.assertEqual(mcp_server.main([]), 1)

    def test_missing_memory_dir_resources_raise_project_relative(self):
        """Resources still signal absence by raising — but with no host path (issue #7)."""
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        with self.assertRaises(FileNotFoundError) as ctx:
            mcp_core.resource_current(empty)
        msg = str(ctx.exception)
        self.assertIn("Run `crumb init`", msg)
        self.assertNotIn(str(empty), msg)  # no absolute host path leaked
        self.assertNotIn(str(empty.parent), msg)

    def test_missing_memory_dir_tools_return_structured_error(self):
        """Every tool reports a missing store as {ok: False, error} (issue #7)."""
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        calls = (
            lambda: mcp_core.tool_search("q", root=empty),
            lambda: mcp_core.tool_guard_before_action("do x", root=empty),
            lambda: mcp_core.tool_build_resume_packet(root=empty),
            lambda: mcp_core.tool_validate(root=empty),
            lambda: mcp_core.tool_scan_secrets(root=empty),
            lambda: mcp_core.tool_record("decision", {"title": "x"}, root=empty),
            lambda: mcp_core.tool_note("question", "x", root=empty),
            lambda: mcp_core.tool_mark_status("dec_x", "stale", "why", root=empty),
        )
        for call in calls:
            res = call()
            self.assertIsInstance(res, dict)
            self.assertFalse(res.get("ok", None), res)
            self.assertIn("error", res)
            self.assertNotIn(str(empty), res["error"])  # no host path leaked


# --------------------------------------------------------------------------- #
# Issue #6 — tool inputs advertise structured schemas, not opaque dicts
# --------------------------------------------------------------------------- #
class InputSchemaTests(unittest.TestCase):
    def test_search_filters_typeddict_keys(self):
        self.assertEqual(
            set(mcp_server.SearchFilters.__optional_keys__),
            {"type", "status", "tag", "file"},
        )
        self.assertEqual(set(mcp_server.SearchFilters.__required_keys__), set())

    def test_record_payload_requires_title_only(self):
        self.assertEqual(set(mcp_server.RecordPayload.__required_keys__), {"title"})
        self.assertEqual(
            set(mcp_server.RecordPayload.__optional_keys__),
            {"sections", "evidence", "tags", "confidence", "privacy", "scope",
             "status", "agent"},
        )

    def test_evidence_item_keys(self):
        self.assertEqual(set(mcp_server.EvidenceItem.__required_keys__), {"type", "ref"})

    def test_tools_advertise_properties_when_sdk_present(self):
        if not mcp_server.sdk_available():
            self.skipTest("MCP SDK not installed; schema derivation not exercised")
        server = mcp_server.build_server()
        tools = {t.name: t for t in server._tool_manager.list_tools()}
        record_schema = tools["memory_record"].parameters
        payload_schema = record_schema["properties"]["payload"]
        # FastMCP/pydantic may inline or $ref the TypedDict; resolve a $ref.
        if "$ref" in payload_schema:
            ref = payload_schema["$ref"].split("/")[-1]
            payload_schema = record_schema["$defs"][ref]
        self.assertIn("title", payload_schema.get("properties", {}))
        self.assertIn("title", payload_schema.get("required", []))


if __name__ == "__main__":
    unittest.main()
