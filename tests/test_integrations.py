"""Tests for the `crumb init` bootstrapper: adapter block, .mcp.json,
hooks, flags, dry-run, and reversal.

Run with:  python -m pytest tests/
       or:  python tests/test_integrations.py
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import subprocess
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

    def test_signpost_does_not_tell_an_agent_to_run_the_interactive_form(self):
        """The session-end line named a command that cannot run unattended.

        Bare `crumb capture session` prompts for five sections; under an agent it
        died on the first read, after printing its git summary. Every command the
        signpost names must be runnable by the reader it is written for.
        """
        block = crumb.adapter_block()
        self.assertIn("crumb capture session --next", block)
        self.assertNotIn("`crumb capture session`", block)
        self.assertIn("Stop", block)  # says the hook already does this for you


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
            self.assertIn(crumb.hook_command("guard"), cmds)
            self.assertIn("SessionStart", data["hooks"])
            self.assertIn("Stop", data["hooks"])

    def test_install_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))
            data = json.loads((root / ".claude" / "settings.json").read_text())
            self.assertEqual(len(data["hooks"]["PreToolUse"]), 1)

    @staticmethod
    def _sh(command: str, cwd: str, **env: str) -> subprocess.CompletedProcess:
        """Run an installed hook command through /bin/sh, as Claude Code would."""
        sh = shutil.which("sh") or "/bin/sh"
        if not Path(sh).exists():  # pragma: no cover - POSIX-only assertion
            raise unittest.SkipTest("no POSIX shell available")
        return subprocess.run([sh, "-c", command], cwd=cwd, env=env, capture_output=True, text=True)

    def test_missing_binary_degrades_instead_of_erroring(self):
        """A hook that fires before crumb is on PATH must not error the session.

        In a containerized session crumb is provisioned into a venv at SessionStart
        and exported via CLAUDE_ENV_FILE, which sibling hooks in the same batch may
        not see. The bare command printed `crumb: command not found` every session.
        """
        with tempfile.TemporaryDirectory() as tmp:
            for event in crumb.HOOK_EVENTS:
                proc = self._sh(crumb.hook_command(event), tmp, PATH="/nonexistent")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(proc.stderr.strip(), "")
                json.loads(proc.stdout)  # always a valid hook payload

    def test_session_fallback_says_memory_is_inactive(self):
        """`{}` is a valid "no opinion" for every event, so an unresolvable install
        would look healthy forever while loading nothing. Say so instead."""
        with tempfile.TemporaryDirectory() as tmp:
            proc = self._sh(crumb.hook_command("session"), tmp, PATH="/nonexistent")
            payload = json.loads(proc.stdout)["hookSpecificOutput"]
            self.assertEqual(payload["hookEventName"], "SessionStart")
            self.assertIn("INACTIVE", payload["additionalContext"])
            self.assertIn("pip install crumb-kit", payload["additionalContext"])
            # the quiet events stay quiet
            for event in ("guard", "capture"):
                quiet = self._sh(crumb.hook_command(event), tmp, PATH="/nonexistent")
                self.assertEqual(json.loads(quiet.stdout), {})

    def test_venv_fallback_is_used_when_path_has_no_crumb(self):
        with tempfile.TemporaryDirectory() as tmp:
            shim = Path(tmp) / ".venv" / "bin" / "crumb"
            shim.parent.mkdir(parents=True)
            shim.write_text('#!/bin/sh\necho "ran $*"\n', encoding="utf-8")
            shim.chmod(0o755)
            proc = self._sh(
                crumb.hook_command("guard"), tmp, PATH="/nonexistent", CLAUDE_PROJECT_DIR=tmp
            )
            self.assertEqual(proc.stdout.strip(), "ran hook guard")

    def test_interpreter_fallback_runs_the_module(self):
        """The Windows `pip install --user` case: the console script is not on the
        PATH bash inherited, but the package is importable by python on it."""
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = Path(tmp) / "bin"
            bin_dir.mkdir()
            shim = bin_dir / "python3"
            shim.write_text('#!/bin/sh\necho "python $*"\n', encoding="utf-8")
            shim.chmod(0o755)
            proc = self._sh(crumb.hook_command("capture"), tmp, PATH=str(bin_dir))
            self.assertIn("-m breadcrumbs hook capture", proc.stdout)

    def test_a_legacy_bare_hook_entry_is_upgraded_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_settings(
                root,
                {
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": "crumb hook session"}]}
                        ]
                    }
                },
            )
            crumb.install_claude_hooks(root, ["session"])
            data = json.loads((root / ".claude" / "settings.json").read_text())
            cmds = [h["command"] for g in data["hooks"]["SessionStart"] for h in g["hooks"]]
            self.assertEqual(cmds, [crumb.hook_command("session")])
            # and it is still ours to remove — install stamped the marker
            self.assertEqual(len(crumb.remove_claude_hooks(root)["removed"]), 1)


# --------------------------------------------------------------------------- #
# Hooks installed through a wrapper are still breadcrumbs' hooks
# --------------------------------------------------------------------------- #
WRAPPER = "$CLAUDE_PROJECT_DIR/.claude/hooks/crumb-hook.sh"


def _write_settings(root: Path, data: dict) -> None:
    (root / ".claude").mkdir(exist_ok=True)
    (root / ".claude" / "settings.json").write_text(json.dumps(data), encoding="utf-8")


def _read_settings(root: Path) -> dict:
    return json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))


class WrappedHookIdentityTests(unittest.TestCase):
    """Identifying our hooks by command text made any indirection invisible.

    Reproduced live against a wrapper script: `doctor` reported "no hooks
    installed" while all three fired (the PreToolUse guard was returning READ_FIRST
    verdicts on real records at the time), `--remove-integrations` left them in
    place while reporting a clean uninstall, and a re-`init` stacked a second copy
    that fired alongside the first.
    """

    def _wrapped(self, root: Path, extra: dict | None = None) -> None:
        hooks = {
            "SessionStart": [{"hooks": [{"type": "command", "command": f"{WRAPPER} session"}]}],
            "PreToolUse": [
                {
                    "matcher": "Bash|Edit|Write|MultiEdit",
                    "hooks": [{"type": "command", "command": f"{WRAPPER} guard"}],
                }
            ],
            "Stop": [{"hooks": [{"type": "command", "command": f"{WRAPPER} capture"}]}],
        }
        for event, groups in (extra or {}).items():
            hooks.setdefault(event, []).extend(groups)
        _write_settings(root, {"hooks": hooks})

    def test_doctor_sees_hooks_installed_through_a_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(["init", "--project", tmp, "--session-tracking", "full"])
            self._wrapped(Path(tmp))
            _, out = run(["doctor", "--project", tmp, "--json"])
            hooks = {c["check"]: c for c in json.loads(out)["checks"]}["hooks"]
            self.assertTrue(hooks["ok"], hooks["detail"])
            self.assertIn("3 crumb hook(s)", hooks["detail"])

    def test_adopting_a_wrapper_then_removing_takes_it_and_nothing_else(self):
        """The supported clean uninstall for a launcher you wrote: adopt, then remove."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run(["init", "--project", tmp, "--session-tracking", "full"])
            self._wrapped(
                root,
                extra={
                    "PreToolUse": [
                        {"matcher": "Bash", "hooks": [{"type": "command", "command": "mine"}]}
                    ],
                    "Notification": [{"hooks": [{"type": "command", "command": "notify-send hi"}]}],
                },
            )
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))  # adopt: stamps the marker
            code, out = run(["init", "--project", tmp, "--remove-integrations"])
            self.assertEqual(code, 0)
            self.assertIn("3 crumb hook(s) removed", out)
            self.assertNotIn("LEFT IN PLACE", out)
            hooks = _read_settings(root)["hooks"]
            self.assertNotIn("SessionStart", hooks)
            self.assertNotIn("Stop", hooks)
            pre = [h["command"] for g in hooks["PreToolUse"] for h in g["hooks"]]
            self.assertEqual(pre, ["mine"])
            self.assertEqual(len(hooks["Notification"]), 1)

    def test_reinstalling_over_a_wrapper_does_not_duplicate_or_clobber_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._wrapped(root)
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))
            hooks = _read_settings(root)["hooks"]
            for cc_event, event in (
                ("SessionStart", "session"),
                ("PreToolUse", "guard"),
                ("Stop", "capture"),
            ):
                entries = [h for g in hooks[cc_event] for h in g["hooks"]]
                self.assertEqual(len(entries), 1, cc_event)  # no second copy firing
                # the user's launcher is theirs; we only stamp it as ours
                self.assertEqual(entries[0]["command"], f"{WRAPPER} {event}")
                self.assertEqual(entries[0][crumb.HOOK_MARKER], event)

    def test_a_marked_entry_is_recognized_whatever_the_command_says(self):
        """The marker is the real identity; the text heuristic is only a fallback."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_settings(
                root,
                {
                    "hooks": {
                        "Stop": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "uv run --project . memory-snapshot",
                                        crumb.HOOK_MARKER: "capture",
                                    }
                                ]
                            }
                        ]
                    }
                },
            )
            crumb.install_claude_hooks(root, ["capture"])
            entries = [h for g in _read_settings(root)["hooks"]["Stop"] for h in g["hooks"]]
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["command"], "uv run --project . memory-snapshot")
            self.assertEqual(len(crumb.remove_claude_hooks(root)["removed"]), 1)
            self.assertEqual(_read_settings(root).get("hooks", {}), {})

    def test_an_unrelated_hook_is_never_mistaken_for_ours(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_settings(
                root,
                {
                    "hooks": {
                        "Stop": [
                            {"hooks": [{"type": "command", "command": "./scripts/session-end.sh"}]}
                        ]
                    }
                },
            )
            report = crumb.remove_claude_hooks(root)
            self.assertEqual(report["removed"], [])
            self.assertEqual(report["left"], [])  # not even a heuristic match
            self.assertEqual(len(_read_settings(root)["hooks"]["Stop"]), 1)

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
            self.assertEqual(len(crumb.remove_claude_hooks(root)["removed"]), 3)
            data = json.loads((root / ".claude" / "settings.json").read_text())
            cmds = [h["command"] for g in data["hooks"].get("PreToolUse", []) for h in g["hooks"]]
            self.assertEqual(cmds, ["mine"])
            self.assertNotIn("SessionStart", data["hooks"])


class MarkerAuthoritativeRemovalTests(unittest.TestCase):
    """Detection may guess; deletion may not.

    Removal keys on `HOOK_MARKER` alone. Detection stays heuristic (over-reporting
    a hook as installed costs nothing), but a heuristic match is never deleted —
    it is reported, because silently leaving a hook behind while claiming a clean
    uninstall is the failure mode this whole mechanism exists to prevent.
    """

    # A real launcher of ours, but hand-written, so it carries no marker.
    WRAPPER = "$CLAUDE_PROJECT_DIR/.claude/hooks/crumb-hook.sh session"
    # A neighbouring script that is NOT ours: the event name appears only inside a
    # hyphenated filename, never as an argument.
    DECOY = "$CLAUDE_PROJECT_DIR/.claude/hooks/crumb-session-setup.sh"

    def _with_hook(self, root: Path, command: str) -> None:
        _write_settings(
            root,
            {"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": command}]}]}},
        )

    def _commands(self, root: Path) -> list[str]:
        hooks = _read_settings(root).get("hooks", {}).get("SessionStart", [])
        return [h["command"] for g in hooks for h in g["hooks"]]

    def test_an_unmarked_launcher_is_left_in_place_not_deleted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._with_hook(root, self.WRAPPER)
            report = crumb.remove_claude_hooks(root)
            self.assertEqual(report["removed"], [])
            self.assertEqual(report["left"], [self.WRAPPER])
            self.assertEqual(self._commands(root), [self.WRAPPER])

    def test_the_user_is_told_rather_than_left_believing_it_reverted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run(["init", "--project", tmp, "--session-tracking", "full"])
            self._with_hook(root, self.WRAPPER)
            code, out = run(["init", "--project", tmp, "--remove-integrations"])
            self.assertEqual(code, 0)
            self.assertIn("LEFT IN PLACE", out)
            self.assertIn(self.WRAPPER, out)
            self.assertIn(crumb.HOOK_MARKER, out)
            self.assertIn("--with-hooks", out)  # names the way to finish the job

    def test_an_event_name_inside_a_filename_is_not_a_match(self):
        """`\\bsession\\b` hits inside `crumb-session-setup.sh` — `-` is a word
        boundary — so a neighbour was read as ours. The event must be an argument."""
        self.assertIsNone(crumb._hook_command_event(self.DECOY))
        self.assertIsNone(crumb._hook_command_event("./scripts/crumb-guard-helper.sh"))
        self.assertEqual(crumb._hook_command_event(self.WRAPPER), "session")
        self.assertEqual(crumb._hook_command_event("crumb hook capture"), "capture")

    def test_the_decoy_survives_a_full_adopt_then_remove_cycle(self):
        """The end-to-end shape of the hazard: adopt must not stamp a neighbour,
        because a stamped entry is deletable on the very next command."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run(["init", "--project", tmp, "--session-tracking", "full"])
            _write_settings(
                root,
                {
                    "hooks": {
                        "SessionStart": [
                            {"hooks": [{"type": "command", "command": self.WRAPPER}]},
                            {"hooks": [{"type": "command", "command": self.DECOY}]},
                        ]
                    }
                },
            )
            run(["init", "--project", tmp, "--with-hooks"])
            code, out = run(["init", "--project", tmp, "--remove-integrations"])
            self.assertEqual(code, 0)
            self.assertNotIn("LEFT IN PLACE", out)
            self.assertEqual(self._commands(root), [self.DECOY])

    def test_a_marked_entry_is_removed_however_odd_its_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_settings(
                root,
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "uv run memory-snapshot",
                                        crumb.HOOK_MARKER: "session",
                                    }
                                ]
                            }
                        ]
                    }
                },
            )
            report = crumb.remove_claude_hooks(root)
            self.assertEqual(report["removed"], ["uv run memory-snapshot"])
            self.assertEqual(report["left"], [])
            self.assertEqual(_read_settings(root).get("hooks", {}), {})

    def test_json_output_stays_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            run(["init", "--project", tmp, "--session-tracking", "full", "--with-hooks"])
            code, out = run(["init", "--project", tmp, "--remove-integrations", "--json"])
            self.assertEqual(code, 0)
            hooks = json.loads(out)["removed"]["hooks"]
            self.assertEqual(len(hooks["removed"]), 3)
            self.assertEqual(hooks["left"], [])


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

    def test_bare_with_adapter_on_green_field_creates_agents_md(self):
        # The flag IS the ask for a signpost. Resolving bare --with-adapter to a
        # no-op on a project with no guidance file left the one-command wire-up
        # (`init --with-adapter --with-mcp --with-hooks`) silently unwired on
        # every green-field agent project; AGENTS.md is the cross-agent
        # standard, so that is the file the fallback creates.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, _ = run(
                ["init", "--project", tmp, "--session-tracking", "full", "--with-adapter"]
            )
            self.assertEqual(code, 0)
            self.assertTrue((root / "AGENTS.md").is_file())
            self.assertIn(crumb.ADAPTER_BEGIN, (root / "AGENTS.md").read_text())
            # explicitly created nothing else
            self.assertFalse((root / "CLAUDE.md").exists())

    def test_bare_with_adapter_prefers_detected_files_over_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "CLAUDE.md").write_text("# guidance\n")
            code, _ = run(
                ["init", "--project", tmp, "--session-tracking", "full", "--with-adapter"]
            )
            self.assertEqual(code, 0)
            self.assertIn(crumb.ADAPTER_BEGIN, (root / "CLAUDE.md").read_text())
            self.assertFalse((root / "AGENTS.md").exists())


class AdapterCreationTests(unittest.TestCase):
    """An *explicitly named* adapter file is created, not silently skipped.

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
# Integration flags are validated BEFORE any filesystem mutation
#
# --------------------------------------------------------------------------- #
class IntegrationFlagValidationTests(unittest.TestCase):
    def test_bogus_hook_event_is_rejected_cleanly(self):
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

    def test_bogus_hook_event_leaves_the_project_untouched(self):
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

    def test_unknown_adapter_name_is_rejected_before_injection(self):
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

    def test_valid_flags_still_apply(self):
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

    def test_resolve_integration_plan_refuses_unknown_values(self):
        """The backstop for callers that don't go through cmd_init."""
        with tempfile.TemporaryDirectory() as tmp:
            args = argparse.Namespace(adapter=None, mcp=False, hooks="bogus")
            with self.assertRaises(ValueError) as ctx:
                crumb.resolve_integration_plan(Path(tmp), args)
            self.assertIn("bogus", str(ctx.exception))

    def test_removal_finds_a_block_injected_into_a_stray_file(self):
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

    def test_discovery_ignores_oversized_and_unrelated_files(self):
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
# Ctrl+C at a consent prompt aborts; it is not consent
# EOF is the same class: a shell that cannot answer answered nothing.
# The gate itself now needs both ends to be a terminal, so the prompt tests
# mock stdout's isatty alongside stdin's.
# --------------------------------------------------------------------------- #
def _fake_tty_stdout() -> mock.Mock:
    """A stdout stand-in that claims to be a terminal — safely on 3.14.

    Python 3.14 colorizes argparse output, so *constructing* a parser reaches
    `_colorize.can_colorize()` → `os.isatty(sys.stdout.fileno())`. A bare
    `mock.Mock()` returns a Mock from `fileno()` and that raises `TypeError:
    'Mock' object cannot be interpreted as an integer` — which is a defect in the
    double, not in the CLI: every real stream returns an int or raises. A real
    non-file text stream raises `io.UnsupportedOperation`, and `can_colorize`
    catches exactly that and falls back to `isatty()`, so raising it is both the
    faithful behaviour and the one that leaves this test in control.
    """
    out = mock.Mock()
    out.isatty.return_value = True
    out.fileno.side_effect = io.UnsupportedOperation("fileno")
    return out


class ConsentPromptTests(unittest.TestCase):
    def test_ctrl_c_does_not_answer_yes(self):
        with mock.patch("builtins.input", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                crumb._prompt_yes("Register the MCP server in .mcp.json?", True)

    def test_eof_declines_even_a_yes_default(self):
        """EOF used to take the default — under an agent harness whose stdin
        passes isatty() but reads EOF, that turned the MCP prompt's [Y/n] into
        an unasked .mcp.json write (field test 2026-08-04)."""
        with mock.patch("builtins.input", side_effect=EOFError):
            self.assertFalse(crumb._prompt_yes("q", True))
            self.assertFalse(crumb._prompt_yes("q", False))

    def test_stdin_tty_alone_is_not_interactive(self):
        """The observed harness: stdin claims TTY, stdout is a pipe."""
        with mock.patch("sys.stdin") as stdin, mock.patch("sys.stdout") as stdout:
            stdin.isatty.return_value = True
            stdout.isatty.return_value = False
            self.assertFalse(crumb._interactive())
            stdout.isatty.return_value = True
            self.assertTrue(crumb._interactive())

    def test_eof_at_the_picker_registers_nothing(self):
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

    def test_ctrl_c_at_the_policy_prompt_aborts_init(self):
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

    def test_main_reports_an_abort_instead_of_a_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            err = io.StringIO()
            out = _fake_tty_stdout()
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


class ParserUnderAPatchedStdoutTests(unittest.TestCase):
    """CI was red on Python 3.14 only, on all three 3.14 jobs.

    3.14 colorizes argparse output, so building a parser now asks
    `os.isatty(sys.stdout.fileno())`. Any test that patches `sys.stdout` with a
    double whose `fileno()` is not an int makes *parser construction* raise —
    which reads like a CLI regression and is not one. These pin the contract the
    doubles have to meet, so the next one that patches stdout fails here, with a
    name that says why, instead of inside an unrelated assertion.
    """

    def test_building_the_parser_survives_a_non_file_stdout(self):
        with mock.patch("sys.stdout", _fake_tty_stdout()):
            self.assertIsNotNone(crumb.build_parser())
            self.assertIsNotNone(crumb.build_parser("init"))

    def test_a_command_runs_under_a_non_file_stdout(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("sys.stdout", _fake_tty_stdout()):
                code = crumb.main(["validate", "--project", tmp])
            self.assertEqual(code, 2)  # no store here — but it got that far

    def test_the_stdout_double_answers_fileno_like_a_real_stream(self):
        out = _fake_tty_stdout()
        self.assertTrue(out.isatty())
        with self.assertRaises(io.UnsupportedOperation):
            out.fileno()


class TrustReportingTests(unittest.TestCase):
    """0.1.10 field-test P2-12/P2-13/P2-14: say what actually happened, leave
    other people's config bytes alone, and let doctor go green right after init."""

    def _git_repo(self, tmp: str) -> Path:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=tmp, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=tmp, check=True)
        (root / "f.txt").write_text("a\n")
        subprocess.run(["git", "add", "f.txt"], cwd=tmp, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp, check=True)
        return root

    def test_repeat_adapter_install_reports_already_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._git_repo(tmp)
            run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter=CLAUDE.md",
                ]
            )
            before = (root / "CLAUDE.md").read_bytes()
            code, out = run(["init", "--project", tmp, "--with-adapter=CLAUDE.md", "--json"])
            self.assertEqual(code, 0)
            applied = json.loads(out)["integrations"]
            self.assertEqual(applied["adapter_states"]["CLAUDE.md"], "already current")
            # Reporting matches reality: the file is byte-identical.
            self.assertEqual((root / "CLAUDE.md").read_bytes(), before)

    def test_adapter_install_reports_updated_when_it_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._git_repo(tmp)
            code, out = run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter=CLAUDE.md",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)
            applied = json.loads(out)["integrations"]
            self.assertEqual(applied["adapter_states"]["CLAUDE.md"], "updated")
            self.assertTrue((root / "CLAUDE.md").is_file())

    def test_mcp_register_leaves_other_servers_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Deliberately NOT this tool's serialization style: one-line arrays,
            # 4-space indent. Registering must not reformat the firebase entry.
            original = (
                "{\n"
                '    "mcpServers": {\n'
                '        "firebase": {"command": "npx", '
                '"args": ["-y", "firebase-tools@latest", "mcp"]}\n'
                "    }\n"
                "}\n"
            )
            (root / ".mcp.json").write_text(original, encoding="utf-8")
            path, changed = crumb.register_mcp(root)
            self.assertTrue(changed)
            text = (root / ".mcp.json").read_text(encoding="utf-8")
            self.assertIn(
                '"firebase": {"command": "npx", "args": ["-y", "firebase-tools@latest", "mcp"]}',
                text,
                "the firebase entry must keep its exact original formatting",
            )
            data = json.loads(text)
            self.assertEqual(data["mcpServers"]["breadcrumbs"], crumb.mcp_server_entry())

    def test_mcp_register_is_a_no_op_when_already_current(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.register_mcp(root)
            before = (root / ".mcp.json").read_bytes()
            path, changed = crumb.register_mcp(root)
            self.assertFalse(changed)
            self.assertEqual((root / ".mcp.json").read_bytes(), before)

    def test_doctor_is_green_immediately_after_init(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._git_repo(tmp)
            run(
                [
                    "init",
                    "--project",
                    tmp,
                    "--session-tracking",
                    "full",
                    "--with-adapter=CLAUDE.md",
                ]
            )
            code, out = run(["doctor", "--project", tmp, "--json"])
            report = json.loads(out)
            packet = next(c for c in report["checks"] if c["check"] == "resume_packet")
            self.assertTrue(packet["ok"], report)
            self.assertEqual(code, 0, out)


# --------------------------------------------------------------------------- #
# F-7 (0.1.11 field audit) — the Windows upgrade lock is a packaging problem
# --------------------------------------------------------------------------- #
class WindowsMcpEntryTests(unittest.TestCase):
    """`pip install --user --upgrade "crumb-kit[mcp]"` fails on Windows with
    `OSError: [WinError 32]` on `Scripts\\breadcrumbs-mcp.exe` while any MCP
    server runs — and every live editor session holds that shim open. The shim is
    opened without FILE_SHARE_DELETE, so rename-aside does not work either.

    Registering the module entry point instead makes a running server hold the
    interpreter, which pip never needs to delete. `python -m breadcrumbs mcp
    serve` was verified to speak stdio identically to the console script before
    this changed.
    """

    def test_windows_registers_the_module_entry_point(self):
        entry = crumb.mcp_server_entry(windows=True)
        self.assertEqual(entry["command"], sys.executable)
        self.assertEqual(entry["args"], ["-m", "breadcrumbs", "mcp", "serve"])
        # Never the .exe shim — that is the file pip cannot delete.
        self.assertNotIn("breadcrumbs-mcp", entry["command"])

    def test_posix_keeps_the_console_script(self):
        entry = crumb.mcp_server_entry(windows=False)
        self.assertEqual(entry["command"], "breadcrumbs-mcp")
        self.assertEqual(entry["args"], [])

    def test_both_platforms_keep_the_project_env_and_stdio_type(self):
        for windows in (True, False):
            entry = crumb.mcp_server_entry(windows=windows)
            self.assertEqual(entry["type"], "stdio")
            self.assertEqual(entry["env"]["BREADCRUMBS_PROJECT"], "${CLAUDE_PROJECT_DIR:-.}")

    def test_the_registered_argv_reaches_cmd_mcp_serve(self):
        """`-m breadcrumbs mcp serve` must be a real parse, not a plausible string.

        Parses the registered argv through the actual CLI parser and asserts it
        dispatches to the serve branch — the SDK itself is optional, so this
        stops at dispatch rather than starting a server.
        """
        args = crumb.mcp_server_entry(windows=True)["args"]
        self.assertEqual(args[:2], ["-m", "breadcrumbs"])
        parser = crumb.build_parser()
        ns = parser.parse_args(args[2:])  # ["mcp", "serve"]
        self.assertEqual(getattr(ns, "mcp_what", None), "serve")
        self.assertIs(ns.func, crumb.cmd_mcp)


if __name__ == "__main__":
    unittest.main()
