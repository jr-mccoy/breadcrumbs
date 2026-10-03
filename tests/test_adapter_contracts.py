"""Adapter and MCP contracts (audit WP17, findings F22).

- The Claude Code adapter normalizes every tool it declares, the installed
  hook matcher is built from that declaration, and an unknown tool is
  reported, never guessed at (`fixtures/claude_hook_payloads.json`).
- The MCP surface — tools, parameters, annotations, resources, prompts and
  the error envelope — matches the versioned contract in `mcp_core`, which is
  pinned to `fixtures/mcp_contract_v1.json`. With the SDK installed (the CI
  `mcp` job runs both SDK majors), the live server is held to it too.
- A second harness resuming the same store sees the same canonical records
  and the same effective rules.
"""

from __future__ import annotations

import asyncio
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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import mcp_core, promote  # noqa: E402
from breadcrumbs.adapters import claude  # noqa: E402
from breadcrumbs import hooks_guard  # noqa: E402
from breadcrumbs import packet as _packet  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")


def _run(argv, stdin=None):
    out = io.StringIO()
    saved = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = crumb.main(argv)
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.stdin = saved
    return code, out.getvalue()


def make_store(parent: Path, name: str = "proj") -> Path:
    root = parent / name
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "i"], cwd=root, check=True)
    _run(["init", "--project", str(root), "--session-tracking", "full"])
    return root


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in AGENT_MARKERS}


class ClaudeAdapterTests(unittest.TestCase):
    def test_supported_tool_names_normalize_expected_actions(self):
        cases = json.loads((FIXTURES / "claude_hook_payloads.json").read_text(encoding="utf-8"))[
            "cases"
        ]
        seen = set()
        for case in cases:
            tool, expect = case["tool_name"], case["expect"]
            with self.subTest(tool=tool, input=case["tool_input"]):
                action = claude.normalize_tool(
                    tool, case["tool_input"], paths_from_text=_cli._paths_from_text
                )
                self.assertEqual(action.kind, expect["kind"])
                self.assertEqual(action.text, expect["text"])
                self.assertEqual(action.files, expect["files"])
                self.assertEqual(action.supported, expect.get("supported", True))
                # The CLI's hook translation is the adapter's.
                text, files = hooks_guard._hook_action_from_tool(tool, case["tool_input"])
                self.assertEqual((text, files or []), (expect["text"], expect["files"]))
                seen.add(tool)
        # Every tool the adapter declares is covered by a fixture.
        self.assertLessEqual(set(claude.GUARDED_TOOLS), seen)
        self.assertTrue(set(claude.IGNORED_TOOLS) & seen)

    def test_installed_matcher_is_the_declared_tool_set(self):
        """`init --with-hooks` installs the adapter's matcher: every guarded
        tool matches it, and no ignored tool does."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _cli.install_claude_hooks(root, ["guard"])
            settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
            (group,) = settings["hooks"]["PreToolUse"]
            matcher = group["matcher"]
        self.assertEqual(matcher, claude.GUARD_MATCHER)
        pattern = re.compile(f"^(?:{matcher})$")
        for tool in claude.GUARDED_TOOLS:
            self.assertTrue(pattern.match(tool), tool)
        for tool in claude.IGNORED_TOOLS:
            self.assertFalse(pattern.match(tool), tool)
        self.assertEqual(claude.capabilities()["guard_matcher"], matcher)

    def test_powershell_and_notebook_edits_reach_the_guard(self):
        """End to end through `crumb hook guard`: before WP17 a PowerShell
        command normalized to an empty action and the hook said nothing."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, _clean_env(), clear=True),
        ):
            root = make_store(Path(tmp))
            _run(
                [
                    "remember",
                    "attempt",
                    "--title",
                    "Deleting the pricing cache directory broke warm starts",
                    "--problem",
                    "slow deploys",
                    "--tried",
                    "Remove-Item the cache directory recursively",
                    "--result",
                    "cold caches for an hour",
                    "--do-not-retry",
                    "the warmup job exists",
                    "--evidence",
                    "file",
                    "nb/analysis.ipynb",
                    "--tags",
                    "cache,pricing",
                    "--project",
                    str(root),
                ]
            )
            hook = {"cwd": str(root), "session_id": "s-ps"}
            code, out = _run(
                ["hook", "guard"],
                stdin=json.dumps(
                    {
                        **hook,
                        "tool_name": "PowerShell",
                        "tool_input": {"command": "Remove-Item ./cache -Recurse -Force"},
                    }
                ),
            )
            self.assertEqual(code, 0)
            context = json.loads(out).get("hookSpecificOutput", {})
            self.assertIn("Deleting the pricing cache", json.dumps(context))
            code, out = _run(
                ["hook", "guard"],
                stdin=json.dumps(
                    {
                        **hook,
                        "session_id": "s-nb",
                        "tool_name": "NotebookEdit",
                        "tool_input": {
                            "notebook_path": str(root / "nb/analysis.ipynb"),
                            "new_source": "clear_cache()",
                            "edit_mode": "replace",
                        },
                    }
                ),
            )
            self.assertEqual(code, 0)
            self.assertIn("Deleting the pricing cache", out)


class McpContractTests(unittest.TestCase):
    def test_mcp_errors_and_resources_match_versioned_contract(self):
        pinned = json.loads((FIXTURES / "mcp_contract_v1.json").read_text(encoding="utf-8"))
        current = json.loads(json.dumps(mcp_core.contract()))
        self.assertEqual(current["version"], pinned["version"])
        self.assertEqual(
            current, pinned, "the MCP contract changed: bump MCP_CONTRACT_VERSION and the fixture"
        )

        # Every tool answers the same envelope when there is no store.
        with tempfile.TemporaryDirectory() as tmp:
            calls = {
                "memory_search": lambda r: mcp_core.tool_search("x", root=r),
                "memory_record": lambda r: mcp_core.tool_record("decision", {"title": "t"}, root=r),
                "memory_guard_before_action": lambda r: mcp_core.tool_guard_before_action(
                    "x", root=r
                ),
                "memory_build_resume_packet": lambda r: mcp_core.tool_build_resume_packet(root=r),
                "memory_validate": lambda r: mcp_core.tool_validate(root=r),
                "memory_show": lambda r: mcp_core.tool_show("dec_x", root=r),
                "memory_jot": lambda r: mcp_core.tool_jot("x", root=r),
                "memory_inbox_promote": lambda r: mcp_core.tool_inbox_promote(
                    "jot_x", "decision", root=r
                ),
                "memory_note": lambda r: mcp_core.tool_note("question", "x?", root=r),
                "memory_mark_status": lambda r: mcp_core.tool_mark_status(
                    "dec_x", "stale", "r", root=r
                ),
                "memory_verify": lambda r: mcp_core.tool_verify("x", "fixed", root=r),
                "memory_reindex": lambda r: mcp_core.tool_reindex(root=r),
                "memory_scan_secrets": lambda r: mcp_core.tool_scan_secrets(root=r),
            }
            self.assertEqual(set(calls), set(mcp_core.TOOL_CONTRACT))
            for name, call in calls.items():
                with self.subTest(name):
                    res = call(tmp)
                    self.assertIs(res.get("ok"), False)
                    self.assertIsInstance(res.get("error"), str)

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, _clean_env(), clear=True),
        ):
            root = make_store(Path(tmp))
            # Refusals carry `refused_by: policy`, and only refusals do.
            res = mcp_core.tool_record(
                "decision", {"title": "t", "agent": "human", "confidence": "low"}, root=root
            )
            self.assertEqual(set(res), set(mcp_core.REFUSAL_ENVELOPE))
            self.assertEqual(res["refused_by"], "policy")
            res = mcp_core.tool_record("idea", {"title": "t"}, root=root)
            self.assertEqual(set(res), set(mcp_core.ERROR_ENVELOPE))
            res = mcp_core.tool_show("dec_does_not_exist", root=root)
            self.assertEqual(set(res), set(mcp_core.ERROR_ENVELOPE))
            # Resources: every static one serves text; a template naming no
            # record is an error, not an empty success.
            for uri, fn in mcp_core.STATIC_RESOURCES.items():
                with self.subTest(uri):
                    self.assertIsInstance(fn(root), str)
            for uri, fn in mcp_core.TEMPLATE_RESOURCES.items():
                with self.subTest(uri):
                    with self.assertRaises(KeyError):
                        fn("does_not_exist", root)

    def test_live_server_matches_the_contract(self):
        from breadcrumbs import mcp_server

        if not mcp_server.sdk_available():
            self.skipTest("MCP SDK not installed (the CI mcp job runs this on both SDK majors)")
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, _clean_env(), clear=True),
        ):
            root = make_store(Path(tmp))
            with mock.patch.object(mcp_server, "_root", lambda: str(root)):
                server = mcp_server.build_server()
                tools = {
                    t.name: t.model_dump(by_alias=True) for t in asyncio.run(server.list_tools())
                }
                prompts = [p.name for p in asyncio.run(server.list_prompts())]
        self.assertEqual(set(tools), set(mcp_core.TOOL_CONTRACT))
        self.assertEqual(sorted(prompts), sorted(mcp_core.PROMPTS))
        accepts = "annotations" in __import__("inspect").signature(server.tool).parameters
        for name, spec in mcp_core.TOOL_CONTRACT.items():
            with self.subTest(name):
                schema = tools[name]["inputSchema"]
                self.assertEqual(sorted(schema.get("properties") or {}), sorted(spec["params"]))
                self.assertEqual(sorted(schema.get("required") or []), sorted(spec["required"]))
                if accepts:
                    got = {
                        k: v
                        for k, v in (tools[name].get("annotations") or {}).items()
                        if k != "title"
                    }
                    self.assertEqual(got, spec["annotations"])


class CrossHarnessTests(unittest.TestCase):
    def test_cross_harness_resume_uses_same_records_and_rules(self):
        """Claude Code (hooks, CLAUDE.md loaded) and a second harness (MCP, the
        portable packet) resume one store: the same canonical record ids, and
        the same rules in effect — Claude's from CLAUDE.md, the other's carried
        in its packet."""
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, _clean_env(), clear=True),
        ):
            root = make_store(Path(tmp))
            mem = root / crumb.MEMORY_DIRNAME
            (root / "CLAUDE.md").write_text("# project\n", encoding="utf-8")
            ids = []
            for title, text in (
                ("Pricing cache TTL is five minutes", "cache pricing responses for 300 seconds"),
                (
                    "Billing retries use exponential backoff",
                    "retry the billing webhook with jitter",
                ),
            ):
                code, out = _run(
                    [
                        "remember",
                        "decision",
                        "--title",
                        title,
                        "--set",
                        "Decision",
                        text,
                        "--evidence",
                        "file",
                        "src/app.py",
                        "--project",
                        str(root),
                        "--json",
                    ]
                )
                ids.append(json.loads(out)["id"])
            code, _ = _run(
                [
                    "promote",
                    ids[0],
                    "--rule",
                    "Cache pricing responses for 300 seconds",
                    "--project",
                    str(root),
                ]
            )
            self.assertEqual(code, 0)

            # Harness 1: Claude Code's SessionStart packet, CLAUDE.md loaded.
            loaded = promote.loaded_rules(root)
            claude_packet = _packet.build_resume_packet(
                mem, root, loaded_rules=loaded, loaded_rules_from=("CLAUDE.md",)
            )
            claude_ids = {d["id"] for d in claude_packet["active_decisions"]} | set(loaded)
            claude_rules = {sid: promote.rule_text(line) for sid, line in loaded.items()}

            # Harness 2: an MCP client with no hooks, reading the portable packet.
            mcp_packet = mcp_core.tool_build_resume_packet(root=root)
            mcp_ids = {d["id"] for d in mcp_packet["active_decisions"]}
            mcp_rules = {
                d["id"]: d["rule"] for d in mcp_packet["active_decisions"] if d.get("rule")
            }

            self.assertEqual(claude_ids, set(ids))
            self.assertEqual(mcp_ids, set(ids))
            self.assertEqual(claude_rules, mcp_rules)
            self.assertEqual(set(mcp_rules), {ids[0]})
            # And the packet Claude gets does not repeat what it already loaded.
            self.assertNotIn(ids[0], {d["id"] for d in claude_packet["active_decisions"]})


if __name__ == "__main__":
    if "--write-contract" in sys.argv:
        path = FIXTURES / f"mcp_contract_v{mcp_core.MCP_CONTRACT_VERSION}.json"
        path.write_text(
            json.dumps(mcp_core.contract(), indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {path}")
    else:
        unittest.main()
