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

import re
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

# Derived, not hand-listed (MF-63). This file kept a second, independent copy of
# the fixture roster that silently fell behind the one in `test_fixtures.py` —
# the same drift that let CI's numeric globs skip a new fixture.
ALL_FIXTURES = sorted(p.name for p in FIXTURES.iterdir() if p.name.startswith("fixture-"))


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
        # `memory_search` is the lookup surface, so it uses the same wider corpus
        # `crumb search` does — ideas in, sessions out (MF-57 / O1).
        matches, _ = cli.search(mem_of(name), root, "sqlite", include_ideas=True)
        tool = mcp_core.tool_search("sqlite", root=root)
        self.assertEqual(tool["count"], len(matches))
        self.assertEqual([m["id"] for m in tool["matches"]], [m["id"] for m in matches])

    def test_search_tool_sees_ideas_and_guard_tool_does_not(self):
        """MF-57 / O1 — the corpus split holds across the MCP surface too."""
        root = root_of("fixture-12-speculative-idea")
        found = mcp_core.tool_search("auth middleware cache", root=root)
        self.assertEqual({m["kind"] for m in found["matches"]}, {"idea"})
        verdict = mcp_core.tool_guard_before_action(
            "rewrite the auth middleware to cache parsed sessions",
            files=["src/auth/middleware.ts"],
            root=root,
        )
        self.assertEqual(verdict["verdict"], "PROCEED")
        self.assertEqual(verdict["matches"], [])

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
        code = crumb.main(["init", "--project", str(self.tmp), "--session-tracking", "full"])
        self.assertEqual(code, 0)

    def test_record_writes_valid_decision(self):
        res = mcp_core.tool_record(
            "decision",
            {
                "title": "Use markdown as the source of truth",
                "sections": {
                    "Decision": "Records are plain markdown.",
                    "Rationale": "Human-readable + diffable.",
                },
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
            {
                "title": "Pick a queue",
                "sections": {"Decision": "Use a queue."},
                "evidence": [{"type": "commit", "ref": "deadbee"}],
            },
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

    def test_MF16_write_error_uses_the_structured_envelope(self):
        """`cli.write_record` was called bare, so a ValueError escaped as a ToolError.

        Every other write path wraps it; `docs/mcp-spec.md` promises
        `{ok: false, error}` for all of them (review #5 M8).
        """
        for payload in (
            {"title": "bad\ntitle", "confidence": "low"},
            {
                "title": "bad evidence",
                "confidence": "low",
                "evidence": [{"type": "commit", "ref": "abc\n1234"}],
            },
            {"title": "bad tag", "confidence": "low", "tags": ["multi\nline"]},
        ):
            with self.subTest(payload=payload):
                res = mcp_core.tool_record("decision", payload, root=self.tmp)
                self.assertIsInstance(res, dict)
                self.assertFalse(res["ok"], res)
                self.assertTrue(res["error"])
                # …and the failed write left nothing behind.
                self.assertTrue(mcp_core.tool_validate(root=self.tmp)["ok"])

    def test_MF24_omitted_confidence_matches_the_documented_mcp_behavior(self):
        """The MCP default (low) deliberately differs from the CLI's exit 2.

        The code comment used to claim exact parity, which was false (review #5
        Low). Only the *explicit* medium/high-without-evidence case is an error.
        """
        res = mcp_core.tool_record("decision", {"title": "no confidence stated"}, root=self.tmp)
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["confidence"], "low")
        bad = mcp_core.tool_record(
            "decision", {"title": "stated high", "confidence": "high"}, root=self.tmp
        )
        self.assertFalse(bad["ok"])
        self.assertIn("evidence", bad["error"])


# --------------------------------------------------------------------------- #
# MF-17 — no absolute host path in any tool payload (audit #6 N5)
# --------------------------------------------------------------------------- #
class ToolPathTests(unittest.TestCase):
    """`mcp_core` states the rule at the top of the module and then broke it.

    Every write tool returned `str(path)` — the record's absolute path on the
    author's machine. Store-relative is the form validate/audit/doctor findings
    already use, and the only one an MCP client can act on.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.assertEqual(
            crumb.main(["init", "--project", str(self.tmp), "--session-tracking", "full"]), 0
        )
        self.mem = self.tmp / crumb.MEMORY_DIRNAME

    def _assert_store_relative(self, res: dict, expected: str) -> None:
        path = res["path"]
        self.assertEqual(path, expected)
        self.assertFalse(Path(path).is_absolute(), path)
        self.assertNotIn(str(self.tmp), path)
        self.assertNotIn(str(self.tmp.parent), path)
        # …and it still resolves to the real file inside the store.
        self.assertTrue((self.mem / path).exists(), path)

    def test_MF17_record_path_is_store_relative(self):
        res = mcp_core.tool_record(
            "decision",
            {
                "title": "Pick a store",
                "sections": {"Decision": "Use markdown."},
                "evidence": [{"type": "commit", "ref": "abc1234"}],
            },
            root=self.tmp,
        )
        self.assertTrue(res["ok"], res)
        self._assert_store_relative(res, f"decisions/{Path(res['path']).name}")

    def test_MF17_note_paths_are_store_relative(self):
        for kind, text, expected in (
            ("question", "Does the cache need eviction?", "open-questions.md"),
            ("trap", "the daemon holds a lock", "known-traps.md"),
        ):
            with self.subTest(kind=kind):
                res = mcp_core.tool_note(kind, text, root=self.tmp)
                self.assertTrue(res["ok"], res)
                self._assert_store_relative(res, expected)

    def test_MF17_idea_note_path_is_store_relative(self):
        res = mcp_core.tool_note("idea", "Try a columnar layout", root=self.tmp)
        self.assertTrue(res["ok"], res)
        self._assert_store_relative(res, f"ideas/{Path(res['path']).name}")

    def test_MF17_verify_path_is_store_relative(self):
        res = mcp_core.tool_verify(
            "the cache eviction path", "open", method="static", confidence="low", root=self.tmp
        )
        self.assertTrue(res["ok"], res)
        self._assert_store_relative(res, f"verifications/{Path(res['path']).name}")

    def test_MF17_reindex_path_is_store_relative(self):
        res = mcp_core.tool_reindex(root=self.tmp)
        self._assert_store_relative(res, "generated/resume-packet.md")

    def test_MF17_mark_status_path_is_store_relative(self):
        rec = mcp_core.tool_record(
            "decision",
            {
                "title": "Adopt a queue",
                "sections": {"Decision": "Use a queue."},
                "evidence": [{"type": "commit", "ref": "deadbee"}],
            },
            root=self.tmp,
        )
        res = mcp_core.tool_mark_status(rec["id"], "stale", "superseded by reality", root=self.tmp)
        self.assertTrue(res["ok"], res)
        self._assert_store_relative(res, f"decisions/{Path(res['path']).name}")

    def test_MF17_no_tool_payload_contains_a_host_path(self):
        """A sweep, so the next tool added does not quietly reintroduce the leak."""
        results = [
            mcp_core.tool_record(
                "attempt", {"title": "Tried a ram cache", "confidence": "low"}, root=self.tmp
            ),
            mcp_core.tool_note("question", "Is the queue durable?", root=self.tmp),
            mcp_core.tool_verify(
                "queue durability", "open", method="static", confidence="low", root=self.tmp
            ),
            mcp_core.tool_reindex(root=self.tmp),
            mcp_core.tool_search("queue", root=self.tmp),
            mcp_core.tool_validate(root=self.tmp),
            mcp_core.tool_build_resume_packet(root=self.tmp),
            mcp_core.tool_scan_secrets(root=self.tmp),
            mcp_core.tool_guard_before_action("edit the queue", root=self.tmp),
        ]
        blob = repr(results)
        self.assertNotIn(str(self.tmp), blob)
        self.assertNotIn(str(self.tmp.parent), blob)

    def test_MF17_cli_still_prints_absolute_paths_for_humans(self):
        """The relativization belongs to the MCP layer, not to `cli`."""
        res = crumb.note(
            self.mem, self.tmp, "question", "Human-facing path?", fields={}, tags=[], agent="test"
        )
        self.assertTrue(Path(res["path"]).is_absolute(), res["path"])


# --------------------------------------------------------------------------- #
# Prompts exist for every §13 flow and carry the data-not-instruction posture
# --------------------------------------------------------------------------- #
class PromptTests(unittest.TestCase):
    def test_all_six_prompts_present_and_nonempty(self):
        expected = {
            "resume_project",
            "capture_session",
            "remember_decision",
            "remember_attempt",
            "guard_before_action",
            "audit_project_memory",
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
        """*Every* tool reports a missing store as {ok: False, error} (issue #7).

        All ten, checked by name against the documented surface: the tuple used to
        cover eight, and the two it omitted (`tool_verify`, `tool_reindex`) are
        exactly the ones whose envelope nothing else exercised (review #5 Low).
        """
        empty = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, empty, ignore_errors=True)
        calls = {
            "tool_search": lambda: mcp_core.tool_search("q", root=empty),
            "tool_guard_before_action": lambda: mcp_core.tool_guard_before_action(
                "do x", root=empty
            ),
            "tool_build_resume_packet": lambda: mcp_core.tool_build_resume_packet(root=empty),
            "tool_validate": lambda: mcp_core.tool_validate(root=empty),
            "tool_scan_secrets": lambda: mcp_core.tool_scan_secrets(root=empty),
            "tool_record": lambda: mcp_core.tool_record("decision", {"title": "x"}, root=empty),
            "tool_note": lambda: mcp_core.tool_note("question", "x", root=empty),
            "tool_mark_status": lambda: mcp_core.tool_mark_status(
                "dec_x", "stale", "why", root=empty
            ),
            "tool_verify": lambda: mcp_core.tool_verify("subj", "open", root=empty),
            "tool_reindex": lambda: mcp_core.tool_reindex(root=empty),
        }
        # No tool may be added without an entry here.
        exported = {n for n in dir(mcp_core) if n.startswith("tool_")}
        self.assertEqual(exported, set(calls), "a tool is missing from this test")
        for name, call in calls.items():
            with self.subTest(tool=name):
                res = call()
                self.assertIsInstance(res, dict)
                self.assertFalse(res.get("ok", None), res)
                self.assertIn("error", res)
                self.assertNotIn(str(empty), res["error"])  # no host path leaked

    def test_record_resource_rejects_an_unknown_id(self):
        """`memory://decisions/{id}` / `attempts/{id}` reject an id they don't hold.

        Lookup is by record id against the loaded records, never by path — so a
        traversal-shaped id is just another miss, not a file read.
        """
        for fn, rid in (
            (mcp_core.resource_decision, "dec_20200101_nope"),
            (mcp_core.resource_attempt, "att_20200101_nope"),
            (mcp_core.resource_attempt, "../../../etc/passwd"),
        ):
            with self.subTest(fn=fn.__name__, rid=rid):
                with self.assertRaises(KeyError) as ctx:
                    fn(rid, root=root_of("fixture-01-fresh-resume"))
                self.assertIn(rid, str(ctx.exception))
                self.assertNotIn(str(FIXTURES), str(ctx.exception))


# --------------------------------------------------------------------------- #
# The resource manifest and the server's explicit bindings cannot drift
# --------------------------------------------------------------------------- #
class ResourceRegistryTests(unittest.TestCase):
    """`STATIC_RESOURCES`/`TEMPLATE_RESOURCES` were dead code with a comment
    claiming the server consumed them; nothing referenced them (review #5 Low).

    `build_server` binds each URI explicitly on purpose — one visible endpoint per
    resource — so the registries are kept as the *declared* surface (the "8
    resources" the README and mcp-spec advertise) and pinned to the bindings here.
    Read from the AST rather than from a built server so the check runs without the
    optional SDK installed; the CI `mcp` job asserts the live count too.
    """

    def _bound_uris(self) -> set[str]:
        import ast
        import inspect
        import textwrap

        tree = ast.parse(textwrap.dedent(inspect.getsource(mcp_server.build_server)))
        uris = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for dec in node.decorator_list:
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "resource"
                    and dec.args
                ):
                    arg = dec.args[0]
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        uris.add(arg.value)
        return uris

    def test_bound_uris_equal_the_registry_keys(self):
        declared = set(mcp_core.STATIC_RESOURCES) | set(mcp_core.TEMPLATE_RESOURCES)
        self.assertEqual(self._bound_uris(), declared)

    def test_the_advertised_count_is_eight(self):
        self.assertEqual(len(mcp_core.STATIC_RESOURCES) + len(mcp_core.TEMPLATE_RESOURCES), 8)

    def test_every_registry_target_is_callable(self):
        for uri, fn in {**mcp_core.STATIC_RESOURCES, **mcp_core.TEMPLATE_RESOURCES}.items():
            with self.subTest(uri=uri):
                self.assertTrue(callable(fn))

    def test_live_server_binds_the_same_resources(self):
        if not mcp_server.sdk_available():
            self.skipTest("MCP SDK not installed; the CI `mcp` job covers the live count")
        import asyncio

        server = mcp_server.build_server()
        static = {str(r.uri) for r in asyncio.run(server.list_resources())}
        templates = {
            sdk_field(t, "uriTemplate") for t in asyncio.run(server.list_resource_templates())
        }
        self.assertEqual(static, set(mcp_core.STATIC_RESOURCES))
        self.assertEqual(templates, set(mcp_core.TEMPLATE_RESOURCES))


def sdk_field(model, json_key: str):
    """Read an SDK model field by its **JSON** name, on either SDK major (MF-66).

    SDK 2.0 renamed every camelCase attribute on its models to snake_case —
    `Tool.inputSchema` → `input_schema`, `Resource.mimeType` → `mime_type`,
    `ResourceTemplate.uriTemplate` → `uri_template`, and so on. The serialized
    form did *not* change: each keeps its camelCase alias, so an MCP client sees
    identical JSON either way and only in-process readers like this suite are
    affected. Reading by the stable JSON key beats hand-writing a
    `getattr(x, "uriTemplate", None) or x.uri_template` fallback at each site —
    which is what `docs/mcp-spec.md` used to imply was the whole of the problem.
    """
    if hasattr(model, json_key):
        return getattr(model, json_key)
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", json_key).lower()
    return getattr(model, snake)


class SdkFieldAliasTests(unittest.TestCase):
    """The camelCase→snake_case rename is an attribute rename, not a wire change.

    Pinned because `docs/mcp-spec.md` now says so, and because a future reader of
    a *different* renamed field (`mimeType`, `inputSchema`) needs the claim to
    still hold. Runs on whichever major is installed; the CI `mcp` job runs it on
    both.
    """

    RENAMED = (
        ("tool", "inputSchema"),
        ("tool", "outputSchema"),
        ("resource", "mimeType"),
        ("template", "mimeType"),
        ("template", "uriTemplate"),
    )

    def _models(self):
        import asyncio

        server = mcp_server.build_server()
        return {
            "tool": asyncio.run(server.list_tools())[0],
            "resource": asyncio.run(server.list_resources())[0],
            "template": asyncio.run(server.list_resource_templates())[0],
        }

    def test_the_json_key_is_the_same_on_either_major(self):
        if not mcp_server.sdk_available():
            self.skipTest("MCP SDK not installed; the CI `mcp` job runs this on both majors")
        models = self._models()
        for kind, json_key in self.RENAMED:
            with self.subTest(model=kind, field=json_key):
                self.assertIn(json_key, models[kind].model_dump(by_alias=True))

    def test_sdk_field_reads_every_renamed_attribute(self):
        if not mcp_server.sdk_available():
            self.skipTest("MCP SDK not installed; the CI `mcp` job runs this on both majors")
        models = self._models()
        for kind, json_key in self.RENAMED:
            with self.subTest(model=kind, field=json_key):
                # No exception on either major is the assertion; the value may be
                # None (an optional field) but the attribute must resolve.
                sdk_field(models[kind], json_key)


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
            {"sections", "evidence", "tags", "confidence", "privacy", "scope", "status", "agent"},
        )

    def test_evidence_item_keys(self):
        self.assertEqual(set(mcp_server.EvidenceItem.__required_keys__), {"type", "ref"})

    def test_MF25_install_hint_names_the_python_floor(self):
        """`pip install "crumb-kit[mcp]"` succeeds and installs nothing on 3.9.

        The extra's marker is `python_version >= '3.10'`, so the hint was a
        no-op instruction for exactly the users who needed it (review #5 Low).
        """
        self.assertIn("3.10", mcp_server._INSTALL_HINT)
        self.assertIn('pip install "crumb-kit[mcp]"', mcp_server._INSTALL_HINT)

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


# --------------------------------------------------------------------------- #
# MF-59 / MF-60 — the SDK moved its server class in 2.0
# --------------------------------------------------------------------------- #
class SdkMajorCompatibilityTests(unittest.TestCase):
    """The `[mcp]` extra had no upper bound, so `pip install "crumb-kit[mcp]"`
    resolved to SDK 2.x, where `mcp.server.fastmcp` no longer exists. The single
    hardcoded import raised ModuleNotFoundError, the module's own degradation path
    swallowed it, and every SDK-present surface — `crumb mcp serve`, `crumb mcp
    doctor`, `crumb doctor` — reported the SDK as "not installed", pointing the
    user at the install command that had just succeeded.

    These run without the SDK: they pin the shim's shape and the extra's bound,
    which is what regressed. The CI `mcp` job runs the real thing on both majors.
    """

    def test_both_sdk_spellings_are_tried_newest_first(self):
        self.assertEqual(
            mcp_server._SDK_SERVER_CLASSES,
            (("mcp.server.mcpserver", "MCPServer"), ("mcp.server.fastmcp", "FastMCP")),
        )

    def test_loader_never_raises_on_a_missing_sdk(self):
        """Importing this module must work on an SDK-less install — the whole
        point of the optional extra. A loader that raised would break `crumb`."""
        cls, err = mcp_server._load_server_class()
        if cls is None:
            self.assertIsNotNone(err)
        else:
            self.assertIsNone(err)

    def test_install_hint_names_the_supported_sdk_range(self):
        self.assertIn("<3", mcp_server._INSTALL_HINT)

    def test_extra_is_upper_bounded(self):
        """An unbounded `mcp>=1.2` is what let 2.0 in unannounced."""
        text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("mcp = [\"mcp>=1.2,<3; python_version >= '3.10'\"]", text)

    def test_version_is_passed_only_when_the_constructor_takes_it(self):
        """D3 / MF-60. SDK 1.x has no `version` parameter and raises TypeError on
        one, so the decision is read from the signature, never guessed."""
        if not mcp_server.sdk_available():
            self.skipTest("MCP SDK not installed; the CI `mcp` job covers both majors")
        import inspect

        takes_it = "version" in inspect.signature(mcp_server.FastMCP.__init__).parameters
        self.assertIs(mcp_server._SERVER_ACCEPTS_VERSION, takes_it)
        server = mcp_server.build_server()
        if takes_it:
            self.assertEqual(server.version, crumb.get_version())

    def test_ci_exercises_both_sdk_majors(self):
        """Only CI can catch this class of break; pin that it still tries both."""
        ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn('mcp-version: ["<2", ">=2,<3"]', ci)


if __name__ == "__main__":
    unittest.main()
