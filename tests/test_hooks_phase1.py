"""Tests for the Phase 1 capture hooks (WM-10 to WM-16).

`UserPromptSubmit`, `PreCompact`, `SubagentStop`, the source-aware
`SessionStart`, the widened Stop-hook extraction turn, and the guard's new
reach over subagent launches.

Two properties matter more than any individual behaviour here and are asserted
throughout: a hook never raises and never exits non-zero, and nothing written
automatically ever lands in the committed store.

Run with:  python -m pytest tests/
       or:  python tests/test_hooks_phase1.py
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import hooks_common, hooks_prompt  # noqa: E402
from breadcrumbs import inbox as ibx  # noqa: E402
from _jsonl import FIXED_TRANSCRIPT, bash, user_text, write_transcript  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


def make_repo(tmp: str) -> Path:
    root = Path(tmp)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("a\n")
    git(root, "add", "f.txt")
    git(root, "commit", "-qm", "init")
    return root


def run_hook(event: str, payload: dict) -> dict:
    """Invoke `crumb hook <event>` in-process with `payload` on stdin."""
    out = io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(out):
            code = crumb.main(["hook", event])
    finally:
        sys.stdin = saved
    assert code == 0, f"a hook must always exit 0, got {code}"
    text = out.getvalue().strip()
    return json.loads(text) if text else {}


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def init_store(root: Path) -> Path:
    with contextlib.redirect_stdout(io.StringIO()):
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def a_decision(root: Path, title: str, *, file: str, tags: str = "parser") -> str:
    code, out = run(
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
            file,
            "--tags",
            tags,
            "--json",
        ]
    )
    assert code == 0, out
    return json.loads(out)["id"]


# --------------------------------------------------------------------------- #
# WM-10 — UserPromptSubmit
# --------------------------------------------------------------------------- #


class PromptHookTests(unittest.TestCase):
    def test_a_relevant_prompt_surfaces_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            rid = a_decision(root, "The parser uses a depth counter", file="src/parser.py")
            out = run_hook(
                "prompt",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "prompt": "rewrite src/parser.py to use a stack instead of the depth counter",
                },
            )
            hso = out["hookSpecificOutput"]
            self.assertEqual(hso["hookEventName"], "UserPromptSubmit")
            self.assertIn(rid, hso["additionalContext"])
            self.assertIn("data, not instruction", hso["additionalContext"])
            # It never blocks: blocking this event erases the user's prompt.
            self.assertNotIn("decision", out)

    def test_the_same_records_twice_in_one_session_say_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            a_decision(root, "The parser uses a depth counter", file="src/parser.py")
            payload = {
                "cwd": str(root),
                "session_id": "s1",
                "prompt": "rewrite src/parser.py to use a stack instead of the depth counter",
            }
            self.assertTrue(run_hook("prompt", payload))
            self.assertEqual(run_hook("prompt", payload), {})

    def test_a_generic_prompt_surfaces_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            a_decision(root, "The parser uses a depth counter", file="src/parser.py")
            out = run_hook(
                "prompt",
                {"cwd": str(root), "session_id": "s1", "prompt": "what should we do next here"},
            )
            self.assertEqual(out, {})

    def test_slash_commands_short_prompts_and_empty_stores_are_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            for prompt in ("/clear", "ok", "   "):
                with self.subTest(prompt=prompt):
                    self.assertEqual(
                        run_hook(
                            "prompt", {"cwd": str(root), "session_id": "s1", "prompt": prompt}
                        ),
                        {},
                    )
            self.assertEqual(
                run_hook(
                    "prompt",
                    {"cwd": str(root), "session_id": "s1", "prompt": "a perfectly normal request"},
                ),
                {},
                "an empty store has nothing to surface",
            )

    def test_no_store_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                run_hook("prompt", {"cwd": tmp, "session_id": "s1", "prompt": "anything at all"}),
                {},
            )

    def test_the_injection_stays_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            for i in range(40):
                a_decision(
                    root,
                    f"Decision {i} about the parser module and its depth counter",
                    file="src/parser.py",
                )
            out = run_hook(
                "prompt",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "prompt": "rewrite src/parser.py depth counter handling",
                },
            )
            text = out["hookSpecificOutput"]["additionalContext"]
            self.assertLessEqual(crumb.approx_tokens(text), hooks_prompt.PROMPT_HOOK_TOKEN_BUDGET)
            self.assertLessEqual(text.count("\n- "), hooks_prompt.PROMPT_HOOK_MAX_MATCHES)

    def test_a_correction_is_captured_privately(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            run_hook(
                "prompt",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "prompt": "No, don't rewrite the parser, keep the depth counter",
                },
            )
            jots = ibx.load_jots(mem)
            self.assertEqual(len(jots), 1)
            self.assertEqual(jots[0].meta["source"], "prompt")
            self.assertIn("correction", jots[0].meta["tags"])
            self.assertTrue(ibx.is_private(mem, jots[0]))
            self.assertEqual(
                list((mem / "inbox").glob("*.md")), [], "a hook never writes to committed inbox/"
            )

    def test_the_same_correction_twice_is_captured_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            payload = {
                "cwd": str(root),
                "session_id": "s1",
                "prompt": "No, don't rewrite the parser",
            }
            run_hook("prompt", payload)
            run_hook("prompt", payload)
            self.assertEqual(len(ibx.load_jots(mem)), 1)

    def test_capture_corrections_can_be_switched_off(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            manifest = mem / "manifest.yml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8") + "capture_corrections: false\n",
                encoding="utf-8",
            )
            run_hook(
                "prompt",
                {"cwd": str(root), "session_id": "s1", "prompt": "No, don't do that at all"},
            )
            self.assertEqual(ibx.load_jots(mem), [])

    def test_a_prompt_carrying_a_credential_is_never_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            out = run_hook(
                "prompt",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "prompt": "No, use AKIAIOSFODNN7EXAMPLE for the bucket instead",
                },
            )
            self.assertEqual(ibx.load_jots(mem), [])
            self.assertIsInstance(out, dict)  # still well-formed

    def test_session_state_is_recorded_for_the_compaction_handoff(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            rid = a_decision(root, "The parser uses a depth counter", file="src/parser.py")
            run_hook(
                "prompt",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "prompt": "rewrite src/parser.py to use a stack instead of the depth counter",
                },
            )
            state = hooks_common.prompt_state(mem, "s1")
            self.assertIn("src/parser.py", state["last_prompt"])
            self.assertIn(rid, state["matched"])


# --------------------------------------------------------------------------- #
# WM-11 / WM-13 — PreCompact and SubagentStop
# --------------------------------------------------------------------------- #


class CompactHookTests(unittest.TestCase):
    def test_it_mines_and_leaves_a_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            path = write_transcript(root, FIXED_TRANSCRIPT)
            out = run_hook(
                "compact",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "trigger": "auto",
                    "transcript_path": str(path),
                },
            )
            self.assertEqual(out, {}, "PreCompact output never reaches the model")
            jots = ibx.load_jots(mem)
            self.assertTrue(jots)
            self.assertTrue(all(ibx.is_private(mem, j) for j in jots))
            marker = hooks_common.compaction_marker(mem, "s1")
            self.assertEqual(marker["trigger"], "auto")
            self.assertTrue(marker["jots"])

    def test_the_cursor_stops_a_second_firing_duplicating(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            path = write_transcript(root, FIXED_TRANSCRIPT)
            payload = {"cwd": str(root), "session_id": "s1", "transcript_path": str(path)}
            run_hook("compact", payload)
            before = len(ibx.load_jots(mem))
            run_hook("compact", payload)
            self.assertEqual(len(ibx.load_jots(mem)), before)

    def test_a_marker_is_written_even_when_nothing_was_mined(self):
        """ "Compacted and nothing survived" is a different fact from "no compaction"."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            path = write_transcript(root, [user_text("just chatting")])
            run_hook(
                "compact", {"cwd": str(root), "session_id": "s1", "transcript_path": str(path)}
            )
            self.assertTrue(hooks_common.compaction_marker(mem, "s1"))

    def test_a_missing_transcript_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            self.assertEqual(run_hook("compact", {"cwd": str(root), "session_id": "s1"}), {})
            self.assertEqual(ibx.load_jots(mem), [])

    def test_no_store_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(run_hook("compact", {"cwd": tmp, "session_id": "s1"}), {})


class SubagentHookTests(unittest.TestCase):
    def test_it_mines_the_subagents_transcript_and_tags_the_agent_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            path = write_transcript(root, bash("c1", "go test ./...", "ok 0.2s"), name="sub.jsonl")
            out = run_hook(
                "subagent",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "agent_type": "Explore",
                    "transcript_path": str(path),
                },
            )
            self.assertEqual(out, {}, "this plan does not hold a subagent")
            jots = ibx.load_jots(mem)
            self.assertEqual(len(jots), 1)
            tags = jots[0].meta["tags"]
            self.assertIn("subagent", tags)
            self.assertIn("agent:Explore", tags)
            # Keyed to the parent session so the Stop hook can find it.
            self.assertEqual(jots[0].meta["host_session"], "s1")

    def test_a_transcript_with_nothing_to_mine_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            path = write_transcript(root, [user_text("looked around")], name="sub.jsonl")
            run_hook(
                "subagent", {"cwd": str(root), "session_id": "s1", "transcript_path": str(path)}
            )
            self.assertEqual(ibx.load_jots(mem), [])


# --------------------------------------------------------------------------- #
# WM-12 — SessionStart after a compaction
# --------------------------------------------------------------------------- #


class SessionStartSourceTests(unittest.TestCase):
    def _prepare(self, root: Path) -> Path:
        mem = init_store(root)
        a_decision(root, "The parser uses a depth counter", file="src/parser.py")
        run_hook(
            "prompt",
            {
                "cwd": str(root),
                "session_id": "s1",
                "prompt": "rewrite src/parser.py to use a stack instead of the depth counter",
            },
        )
        path = write_transcript(root, FIXED_TRANSCRIPT)
        run_hook("compact", {"cwd": str(root), "session_id": "s1", "transcript_path": str(path)})
        return mem

    def test_compact_source_prepends_what_was_in_flight(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._prepare(root)
            text = run_hook("session", {"cwd": str(root), "session_id": "s1", "source": "compact"})[
                "hookSpecificOutput"
            ]["additionalContext"]
            self.assertIn("context was compacted", text)
            self.assertIn("Last prompt before compaction", text)
            self.assertIn("src/parser.py", text)
            self.assertIn("crumb inbox promote", text)
            self.assertIn("# Resume Packet", text, "the full packet still follows")

    def test_startup_source_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._prepare(root)
            text = run_hook("session", {"cwd": str(root), "session_id": "s1", "source": "startup"})[
                "hookSpecificOutput"
            ]["additionalContext"]
            self.assertNotIn("context was compacted", text)

    def test_an_absent_source_reads_as_startup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._prepare(root)
            text = run_hook("session", {"cwd": str(root), "session_id": "s1"})[
                "hookSpecificOutput"
            ]["additionalContext"]
            self.assertNotIn("context was compacted", text)

    def test_compact_with_no_marker_is_the_plain_packet(self):
        """No marker means no compaction was observed, whatever `source` says."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            text = run_hook(
                "session", {"cwd": str(root), "session_id": "unseen", "source": "compact"}
            )["hookSpecificOutput"]["additionalContext"]
            self.assertNotIn("context was compacted", text)


# --------------------------------------------------------------------------- #
# WM-15 — the widened extraction turn
# --------------------------------------------------------------------------- #


class ExtractionTurnTests(unittest.TestCase):
    def test_candidates_alone_earn_an_extraction_turn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            path = write_transcript(root, FIXED_TRANSCRIPT)
            out = run_hook(
                "capture",
                {"cwd": str(root), "session_id": "s1", "transcript_path": str(path)},
            )
            self.assertEqual(out["decision"], "block")
            self.assertIn("crumb inbox promote", out["reason"])
            self.assertIn("jot_", out["reason"])
            self.assertIn("no commits landed", out["reason"])

    def test_one_verification_alone_does_not(self):
        """Under both thresholds: one passing test is not a session's findings."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            path = write_transcript(root, bash("c1", "ruff check .", "All checks passed!"))
            out = run_hook(
                "capture",
                {"cwd": str(root), "session_id": "s1", "transcript_path": str(path)},
            )
            self.assertEqual(out, {})
            self.assertEqual(len(ibx.load_jots(mem)), 1, "but it was still mined")

    def test_three_candidates_of_any_kind_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            entries = (
                bash("c1", "ruff check .", "All checks passed!")
                + bash("c2", "mypy", "Success")
                + bash("c3", "go test ./...", "ok")
            )
            out = run_hook(
                "capture",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "transcript_path": str(write_transcript(root, entries)),
                },
            )
            self.assertEqual(out["decision"], "block")

    def test_commits_and_candidates_both_appear_commits_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            run_hook("capture", {"cwd": str(root), "session_id": "s0"})  # silent baseline
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "add g")
            path = write_transcript(root, FIXED_TRANSCRIPT)
            out = run_hook(
                "capture",
                {"cwd": str(root), "session_id": "s1", "transcript_path": str(path)},
            )
            reason = out["reason"]
            self.assertLess(reason.index("new commit(s) landed"), reason.index("Candidates mined"))

    def test_the_same_jots_are_never_offered_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            path = write_transcript(root, FIXED_TRANSCRIPT)
            payload = {"cwd": str(root), "session_id": "s1", "transcript_path": str(path)}
            self.assertEqual(run_hook("capture", payload)["decision"], "block")
            self.assertEqual(run_hook("capture", payload), {})

    def test_a_continuation_never_blocks_but_still_mines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            path = write_transcript(root, FIXED_TRANSCRIPT)
            out = run_hook(
                "capture",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "transcript_path": str(path),
                    "stop_hook_active": True,
                },
            )
            self.assertEqual(out, {})
            self.assertTrue(ibx.load_jots(mem), "mining is a side effect, not a decision")

    def test_the_kill_switch_stops_the_prompt_not_the_mining(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            manifest = mem / "manifest.yml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8").replace(
                    "extraction_prompt: true", "extraction_prompt: false"
                ),
                encoding="utf-8",
            )
            path = write_transcript(root, FIXED_TRANSCRIPT)
            out = run_hook(
                "capture",
                {"cwd": str(root), "session_id": "s1", "transcript_path": str(path)},
            )
            self.assertEqual(out, {})
            self.assertTrue(ibx.load_jots(mem))

    def test_a_turn_with_nothing_at_all_still_snapshots_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            out = run_hook("capture", {"cwd": str(root), "session_id": "s1"})
            self.assertEqual(out, {})
            self.assertTrue(crumb.load_records(mem, types=("session",)))


# --------------------------------------------------------------------------- #
# WM-16 — the guard reaches subagent launches
# --------------------------------------------------------------------------- #


class SubagentGuardTests(unittest.TestCase):
    def _store_with_a_do_not_retry(self, root: Path) -> None:
        init_store(root)
        code, out = run(
            [
                "remember",
                "attempt",
                "--project",
                str(root),
                "--title",
                "Tried deleting src/parser.py and regenerating it",
                "--result",
                "lost the depth handling",
                "--do-not-retry",
                "do not delete src/parser.py; edit it in place",
                "--evidence",
                "file",
                "src/parser.py",
            ]
        )
        assert code == 0, out

    def test_a_launch_gets_context_and_never_a_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._store_with_a_do_not_retry(root)
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "tool_name": "Task",
                    "tool_input": {
                        "prompt": "delete src/parser.py and regenerate it from the grammar"
                    },
                },
            )
            hso = out["hookSpecificOutput"]
            self.assertIn("additionalContext", hso)
            self.assertIn("src/parser.py", hso["additionalContext"])
            self.assertNotIn(
                "permissionDecision", hso, "a launch is not itself the irreversible act"
            )

    def test_the_same_action_as_bash_still_escalates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._store_with_a_do_not_retry(root)
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "session_id": "s1",
                    "tool_name": "Bash",
                    "tool_input": {"command": "rm -rf src/parser.py"},
                },
            )
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_an_empty_launch_prompt_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._store_with_a_do_not_retry(root)
            self.assertEqual(
                run_hook(
                    "guard",
                    {"cwd": str(root), "tool_name": "Task", "tool_input": {}},
                ),
                {},
            )

    def test_the_description_field_is_used_when_there_is_no_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            self._store_with_a_do_not_retry(root)
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "tool_name": "Agent",
                    "tool_input": {"description": "delete src/parser.py and regenerate"},
                },
            )
            self.assertIn("additionalContext", out["hookSpecificOutput"])


# --------------------------------------------------------------------------- #
# Installation
# --------------------------------------------------------------------------- #


class InstallationTests(unittest.TestCase):
    def test_every_event_installs_detects_and_removes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))
            data = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
            for event, (cc_event, matcher) in _cli._HOOK_SPECS.items():
                with self.subTest(event=event):
                    groups = data["hooks"][cc_event]
                    entries = [h for g in groups for h in g["hooks"]]
                    self.assertTrue(any(h.get(crumb.HOOK_MARKER) == event for h in entries))
                    if matcher is None:
                        self.assertTrue(all("matcher" not in g for g in groups))
                    else:
                        self.assertTrue(any(g.get("matcher") == matcher for g in groups))
            removed = crumb.remove_claude_hooks(root)
            self.assertEqual(len(removed["removed"]), len(crumb.HOOK_EVENTS))
            self.assertEqual(removed["left"], [])

    def test_reinstalling_brings_an_owned_matcher_up_to_date(self):
        """The guard's matcher grew `Task|Agent`; an existing install must follow."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".claude" / "settings.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Bash|Edit|Write|MultiEdit",
                                    "hooks": [
                                        {
                                            "type": "command",
                                            "command": crumb.hook_command("guard"),
                                            crumb.HOOK_MARKER: "guard",
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            crumb.install_claude_hooks(root, ["guard"])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                data["hooks"]["PreToolUse"][0]["matcher"], _cli._HOOK_SPECS["guard"][1]
            )

    def test_an_unowned_entrys_matcher_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / ".claude" / "settings.json"
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "PreToolUse": [
                                {
                                    "matcher": "Bash",
                                    "hooks": [
                                        {"type": "command", "command": "./my-crumb.sh guard"}
                                    ],
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            crumb.install_claude_hooks(root, ["guard"])
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["hooks"]["PreToolUse"][0]["matcher"], "Bash")

    def test_doctor_sees_the_new_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            crumb.install_claude_hooks(root, list(crumb.HOOK_EVENTS))
            code, out = run(["doctor", "--project", str(root), "--json"])
            self.assertEqual(code, 0, out)
            hooks = [r for r in json.loads(out)["items"] if r["check"] == "hooks"][0]
            self.assertTrue(hooks["ok"])


class BadPayloadTests(unittest.TestCase):
    """Every hook degrades to `{}` rather than raising, on any shape of junk."""

    def test_malformed_payloads_never_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            payloads = [
                {},
                {"cwd": str(root)},
                {"cwd": str(root), "prompt": None, "tool_input": "not a dict"},
                {"cwd": str(root), "session_id": 17, "transcript_path": 42},
                {"cwd": str(root), "transcript_path": str(root)},  # a directory
            ]
            for event in crumb.HOOK_EVENTS:
                for payload in payloads:
                    with self.subTest(event=event, payload=payload):
                        self.assertIsInstance(run_hook(event, payload), dict)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
