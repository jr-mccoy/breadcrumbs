"""Tests for the `crumb init` bootstrapper (review §5/§7): adapter block, .mcp.json,
hooks, flags, dry-run, and reversal.

Run with:  python -m pytest tests/
       or:  python tests/test_integrations.py
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


class ManagedBlockTests(unittest.TestCase):
    def test_insert_replace_remove_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "CLAUDE.md"
            p.write_text("# Title\n\nuser text\n", encoding="utf-8")
            crumb.write_adapter_block(Path(tmp), "CLAUDE.md")
            after = p.read_text()
            self.assertIn("Project memory (breadcrumbs)", after)
            self.assertIn("user text", after)
            # idempotent: re-running keeps exactly one block
            crumb.write_adapter_block(Path(tmp), "CLAUDE.md")
            self.assertEqual(p.read_text().count("breadcrumbs managed block (managed"), 1)
            # removal restores original content
            self.assertTrue(crumb.remove_adapter_block(Path(tmp), "CLAUDE.md"))
            self.assertEqual(p.read_text(), "# Title\n\nuser text\n")

    def test_adapter_block_under_bloat_threshold(self):
        self.assertLess(len(crumb.adapter_block()), crumb.ADAPTER_BLOAT_CHARS)


class MergeJsonTests(unittest.TestCase):
    def test_mcp_register_preserves_siblings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".mcp.json").write_text(
                json.dumps({"mcpServers": {"other": {"command": "x"}}, "k": 1}),
                encoding="utf-8",
            )
            crumb.register_mcp(root)
            data = json.loads((root / ".mcp.json").read_text())
            self.assertIn("other", data["mcpServers"])
            self.assertIn("breadcrumbs", data["mcpServers"])
            self.assertEqual(data["k"], 1)
            self.assertEqual(data["mcpServers"]["breadcrumbs"]["type"], "stdio")

    def test_unregister_only_removes_breadcrumbs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.register_mcp(root)
            # add a sibling, then unregister breadcrumbs
            data = json.loads((root / ".mcp.json").read_text())
            data["mcpServers"]["other"] = {"command": "x"}
            (root / ".mcp.json").write_text(json.dumps(data), encoding="utf-8")
            self.assertTrue(crumb.unregister_mcp(root))
            data = json.loads((root / ".mcp.json").read_text())
            self.assertNotIn("breadcrumbs", data["mcpServers"])
            self.assertIn("other", data["mcpServers"])

    def test_merge_rejects_non_object_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / ".mcp.json"
            p.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(ValueError):
                crumb.register_mcp(Path(tmp))


class HookMergeTests(unittest.TestCase):
    def test_install_preserves_foreign_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [{"type": "command", "command": "mine"}],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))
            data = json.loads((root / ".claude" / "settings.json").read_text())
            cmds = [h["command"] for g in data["hooks"]["PreToolUse"] for h in g["hooks"]]
            self.assertIn("mine", cmds)
            self.assertIn("crumb hook guard", cmds)
            self.assertIn("SessionStart", data["hooks"])
            self.assertIn("Stop", data["hooks"])

    def test_install_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))
            data = json.loads((root / ".claude" / "settings.json").read_text())
            self.assertEqual(len(data["hooks"]["PreToolUse"]), 1)

    def test_remove_only_strips_breadcrumbs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".claude").mkdir()
            (root / ".claude" / "settings.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [{"type": "command", "command": "mine"}],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))
            self.assertTrue(crumb.remove_claude_hooks(root))
            data = json.loads((root / ".claude" / "settings.json").read_text())
            cmds = [h["command"] for g in data["hooks"].get("PreToolUse", []) for h in g["hooks"]]
            self.assertEqual(cmds, ["mine"])
            self.assertNotIn("SessionStart", data["hooks"])


class InitFlagTests(unittest.TestCase):
    def test_default_init_writes_no_integrations(self):
        # Non-interactive default must stay byte-identical to before (no adapter/mcp/hooks).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("# x\n", encoding="utf-8")
            run(["init", "--project", tmp, "--session-tracking", "full"])
            self.assertNotIn("breadcrumbs managed", (root / "CLAUDE.md").read_text())
            self.assertFalse((root / ".mcp.json").exists())
            self.assertFalse((root / ".claude" / "settings.json").exists())

    def test_with_flags_apply_detected_adapter_and_mcp(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("# x\n", encoding="utf-8")
            code, _ = run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter",
                    "--with-mcp",
                    "--no-hooks",
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("breadcrumbs managed", (root / "CLAUDE.md").read_text())
            self.assertTrue((root / ".mcp.json").exists())
            self.assertFalse((root / ".claude" / "settings.json").exists())

    def test_no_adapter_file_means_nothing_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, out = run(
                ["init", "--project", tmp, "--session-tracking", "full", "--with-adapter"]
            )
            self.assertEqual(code, 0)
            # A *bare* --with-adapter means "every guidance file I can detect", so
            # with none detected we still invent nothing (MF-65 kept this half).
            self.assertFalse((root / "CLAUDE.md").exists())
            # ...but it may no longer be silent about it: `doctor` reports ✗ on
            # this very check and the first-run nudge recommends the command that
            # just ran, so the no-op has to say why and how to get past it.
            self.assertIn("no agent-guidance file detected", out)
            self.assertIn("--with-adapter=AGENTS.md", out)


class AdapterCreationTests(unittest.TestCase):
    """MF-65 — an *explicitly named* adapter file is created, not silently skipped.

    A name only reaches the plan by detection (existing files only) or by
    `--with-adapter=NAME`, so a planned name that is not on disk was asked for by
    name. `apply_integrations` used to guard on `is_file()` and drop it — after
    `--print-integrations` had promised to write it.
    """

    def test_named_adapter_that_does_not_exist_is_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _ = run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter=CLAUDE.md",
                    "--no-mcp",
                    "--no-hooks",
                ]
            )
            self.assertEqual(code, 0)
            self.assertTrue((root / "CLAUDE.md").exists())
            self.assertIn("breadcrumbs managed", (root / "CLAUDE.md").read_text())

    def test_the_created_adapter_clears_the_doctor_check(self):
        """The loop this closes: doctor said ✗, the fix produced no adapter, repeat."""
        with tempfile.TemporaryDirectory() as tmp:
            run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter=AGENTS.md",
                    "--no-mcp",
                    "--no-hooks",
                ]
            )
            _, out = run(["doctor", "--project", tmp, "--json"])
            checks = {c["check"]: c for c in json.loads(out)["checks"]}
            self.assertTrue(checks["adapter"]["ok"], checks["adapter"])

    def test_the_doctor_miss_message_names_a_command_that_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(["init", "--project", tmp, "--session-tracking", "full"])
            _, out = run(["doctor", "--project", tmp, "--json"])
            checks = {c["check"]: c for c in json.loads(out)["checks"]}
            self.assertFalse(checks["adapter"]["ok"])
            self.assertIn("--with-adapter=AGENTS.md", checks["adapter"]["detail"])

    def test_a_nested_adapter_path_creates_its_directory(self):
        """`.github/copilot-instructions.md` is the one name inside a subdirectory."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _ = run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter=.github/copilot-instructions.md",
                    "--no-mcp",
                    "--no-hooks",
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn(
                "breadcrumbs managed",
                (root / ".github" / "copilot-instructions.md").read_text(),
            )

    def test_the_dry_run_marks_a_file_it_would_create(self):
        """`--print-integrations` printed a bare name for a file it then skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            run(["init", "--project", tmp, "--session-tracking", "full"])
            code, out = run(
                ["init", "--project", tmp, "--print-integrations", "--with-adapter=CLAUDE.md"]
            )
            self.assertEqual(code, 0)
            self.assertIn("CLAUDE.md (will be created)", out)

    def test_a_created_adapter_is_still_reversible(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter=CLAUDE.md",
                    "--no-mcp",
                    "--no-hooks",
                ]
            )
            code, out = run(["init", "--project", tmp, "--remove-integrations"])
            self.assertEqual(code, 0)
            self.assertIn("CLAUDE.md", out)
            # The block is gone; the (now empty) file it was created in remains,
            # which is the same thing removal does to a file it did not create.
            self.assertNotIn("breadcrumbs managed", (root / "CLAUDE.md").read_text())

    def test_print_integrations_is_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("# x\n", encoding="utf-8")
            run(["init", "--project", tmp, "--session-tracking", "full"])
            code, out = run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--print-integrations",
                    "--with-adapter",
                    "--with-mcp",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertEqual(payload["would_apply"]["adapters"], ["CLAUDE.md"])
            self.assertTrue(payload["would_apply"]["mcp"])
            # dry run wrote nothing
            self.assertNotIn("breadcrumbs managed", (root / "CLAUDE.md").read_text())

    def test_remove_integrations_reverses_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("# keep me\n", encoding="utf-8")
            run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter",
                    "--with-mcp",
                    "--with-hooks",
                ]
            )
            run(["init", "--project", tmp, "--remove-integrations"])
            self.assertEqual((root / "CLAUDE.md").read_text(), "# keep me\n")
            mcp = json.loads((root / ".mcp.json").read_text())
            self.assertNotIn("breadcrumbs", mcp.get("mcpServers", {}))


# --------------------------------------------------------------------------- #
# MF-14 — integration flags are validated BEFORE any filesystem mutation
# (review #5 M6 + M7 + audit #6 N4)
# --------------------------------------------------------------------------- #
class IntegrationFlagValidationTests(unittest.TestCase):
    def test_MF14_bogus_hook_event_is_rejected_cleanly(self):
        """`--with-hooks=bogus` used to escape as a raw KeyError from _HOOK_SPECS."""
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code, _ = run(
                    [
                        "init",
                        "--project",
                        tmp,
                        "--session-tracking",
                        "full",
                        "--with-hooks=bogus",
                    ]
                )
            self.assertEqual(code, 2)
            message = err.getvalue()
            self.assertIn("--with-hooks", message)
            self.assertIn("bogus", message)
            for valid in crumb.HOOK_EVENTS:  # the message names what IS valid
                self.assertIn(valid, message)

    def test_MF14_bogus_hook_event_leaves_the_project_untouched(self):
        """Ordering is the whole point: nothing may be written before validation."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                code, _ = run(
                    [
                        "init",
                        "--project",
                        tmp,
                        "--session-tracking",
                        "full",
                        "--with-hooks=bogus",
                    ]
                )
            self.assertEqual(code, 2)
            # The old order scaffolded the store and wrote .gitignore first, then
            # died — leaving a store `init` would refuse to touch again and no hooks.
            self.assertFalse((root / crumb.MEMORY_DIRNAME).exists())
            self.assertFalse((root / ".gitignore").exists())
            self.assertEqual(sorted(p.name for p in root.iterdir()), [])

    def test_MF14_unknown_adapter_name_is_rejected_before_injection(self):
        """`--with-adapter=README.md` injected the block into an arbitrary file."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# hello\n", encoding="utf-8")
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                code, _ = run(
                    [
                        "init",
                        "--project",
                        tmp,
                        "--session-tracking",
                        "full",
                        "--with-adapter=README.md",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("--with-adapter", err.getvalue())
            self.assertIn("README.md", err.getvalue())
            self.assertEqual((root / "README.md").read_text(), "# hello\n")
            self.assertFalse((root / crumb.MEMORY_DIRNAME).exists())

    def test_MF14_valid_flags_still_apply(self):
        """The guard must not reject the names it is there to protect."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text("# x\n", encoding="utf-8")
            code, _ = run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter=AGENTS.md",
                    "--with-hooks=session,capture",
                    "--no-mcp",
                ]
            )
            self.assertEqual(code, 0)
            self.assertIn("breadcrumbs managed", (root / "AGENTS.md").read_text())
            hooks = json.loads((root / ".claude" / "settings.json").read_text())["hooks"]
            self.assertIn("SessionStart", hooks)
            self.assertIn("Stop", hooks)
            self.assertNotIn("PreToolUse", hooks)  # `guard` was not requested

    def test_MF14_resolve_integration_plan_refuses_unknown_values(self):
        """The backstop for callers that don't go through cmd_init."""
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(adapter=None, mcp=False, hooks="bogus")
            with self.assertRaises(ValueError) as ctx:
                crumb.resolve_integration_plan(Path(tmp), args)
            self.assertIn("bogus", str(ctx.exception))

    def test_MF14_removal_finds_a_block_injected_into_a_stray_file(self):
        """Recovery for stores already in the bad state (the injection predates the fix)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# keep me\n", encoding="utf-8")
            run(["init", "--project", tmp, "--session-tracking", "full"])
            crumb.write_adapter_block(root, "README.md")  # what the old flag did
            self.assertEqual(crumb.discover_adapter_blocks(root), ["README.md"])
            code, out = run(["init", "--project", tmp, "--remove-integrations"])
            self.assertEqual(code, 0)
            self.assertIn("README.md", out)
            self.assertEqual((root / "README.md").read_text(), "# keep me\n")

    def test_MF14_discovery_ignores_oversized_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.md").write_text("nothing managed here\n", encoding="utf-8")
            (root / "blob.bin").write_bytes(b"\xff\xfe" * 32)
            big = root / "huge.md"
            big.write_text(
                crumb.ADAPTER_BEGIN + "\n" + "x" * crumb.ADAPTER_SCAN_MAX_BYTES,
                encoding="utf-8",
            )
            self.assertEqual(crumb.discover_adapter_blocks(root), [])


# --------------------------------------------------------------------------- #
# MF-21 — Ctrl+C at a consent prompt aborts; it is not consent (review #5 Low)
# MF-73 — EOF is the same class: a shell that cannot answer answered nothing.
# The gate itself now needs both ends to be a terminal, so the prompt tests
# mock stdout's isatty alongside stdin's.
# --------------------------------------------------------------------------- #
class ConsentPromptTests(unittest.TestCase):
    def test_MF21_ctrl_c_does_not_answer_yes(self):
        with mock.patch("builtins.input", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                crumb._prompt_yes("Register the MCP server in .mcp.json?", True)

    def test_MF73_eof_declines_even_a_yes_default(self):
        """EOF used to take the default — under an agent harness whose stdin
        passes isatty() but reads EOF, that turned the MCP prompt's [Y/n] into
        an unasked .mcp.json write (field test 2026-08-04)."""
        with mock.patch("builtins.input", side_effect=EOFError):
            self.assertFalse(crumb._prompt_yes("q", True))
            self.assertFalse(crumb._prompt_yes("q", False))

    def test_MF73_stdin_tty_alone_is_not_interactive(self):
        """The observed harness: stdin claims TTY, stdout is a pipe."""
        with mock.patch("sys.stdin") as stdin, mock.patch("sys.stdout") as stdout:
            stdin.isatty.return_value = True
            stdout.isatty.return_value = False
            self.assertFalse(crumb._interactive())
            stdout.isatty.return_value = True
            self.assertTrue(crumb._interactive())

    def test_MF73_eof_at_the_picker_registers_nothing(self):
        """End to end: interactive-looking shell, every read EOFs — the resolved
        plan must not carry mcp=True (it did; the default counted as consent)."""
        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch("sys.stdin") as stdin,
                mock.patch("sys.stdout") as stdout,
                mock.patch("builtins.input", side_effect=EOFError),
            ):
                stdin.isatty.return_value = True
                stdout.isatty.return_value = True
                args = argparse.Namespace(adapter=None, hooks=None, mcp=None)
                plan = crumb.resolve_integration_plan(Path(tmp), args)
            self.assertFalse(plan["mcp"])
            self.assertEqual(plan["adapters"], [])
            self.assertEqual(plan["hooks"], [])

    def test_MF21_ctrl_c_at_the_policy_prompt_aborts_init(self):
        """It used to pick `full` silently and scaffold a store anyway."""
        with (
            mock.patch("sys.stdin") as stdin,
            mock.patch("sys.stdout") as stdout,
            mock.patch("builtins.input", side_effect=KeyboardInterrupt),
        ):
            stdin.isatty.return_value = True
            stdout.isatty.return_value = True
            with self.assertRaises(KeyboardInterrupt):
                crumb.prompt_session_tracking()

    def test_MF21_main_reports_an_abort_instead_of_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            err = io.StringIO()
            out = mock.Mock()
            out.isatty.return_value = True
            with (
                mock.patch("sys.stdin") as stdin,
                mock.patch("sys.stdout", out),
                mock.patch("builtins.input", side_effect=KeyboardInterrupt),
                contextlib.redirect_stderr(err),
            ):
                stdin.isatty.return_value = True
                code = crumb.main(["init", "--project", tmp])
            self.assertEqual(code, 130)  # shell convention for SIGINT
            self.assertIn("aborted", err.getvalue())
            self.assertFalse((root / crumb.MEMORY_DIRNAME).exists())


if __name__ == "__main__":
    unittest.main()
