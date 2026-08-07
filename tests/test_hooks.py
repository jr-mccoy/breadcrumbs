"""Tests for `crumb hook session|guard|capture`.

These drive the hook translators by feeding a JSON payload on stdin and asserting
the emitted JSON matches the verified Claude Code contract.

Run with:  python -m pytest tests/
       or:  python tests/test_hooks.py
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
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402  (patch target: `_hook_guard` resolves `guard` here)


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
    """Invoke `crumb hook <event>` in-process with `payload` on stdin; parse stdout."""
    out = io.StringIO()
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(out):
            code = crumb.main(["hook", event])
    finally:
        sys.stdin = saved_stdin
    assert code == 0, code
    text = out.getvalue().strip()
    return json.loads(text) if text else {}


def init_store(root: Path) -> Path:
    crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


class HookSessionTests(unittest.TestCase):
    def test_emits_resume_packet_as_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            out = run_hook("session", {"cwd": str(root), "hook_event_name": "SessionStart"})
            hso = out["hookSpecificOutput"]
            self.assertEqual(hso["hookEventName"], "SessionStart")
            self.assertIn("additionalContext", hso)
            self.assertTrue(hso["additionalContext"].strip())

    def test_no_store_emits_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_hook("session", {"cwd": tmp})
            self.assertEqual(out, {})


class HookGuardTests(unittest.TestCase):
    def test_routine_action_is_silent_allow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls -la"},
                },
            )
            self.assertEqual(out, {})

    def test_risky_action_escalates_with_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            crumb.main(["note", "trap", "force-push to main loses history", "--project", str(root)])
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git push --force origin main"},
                },
            )
            hso = out["hookSpecificOutput"]
            self.assertEqual(hso["hookEventName"], "PreToolUse")
            # memory informs; it never allows or denies on its own, so whichever
            # band this lands in, the reason reaches someone.
            self.assertNotIn(hso.get("permissionDecision"), ("allow", "deny"))
            reason = hso.get("permissionDecisionReason") or hso.get("additionalContext") or ""
            self.assertIn("guard", reason.lower())

    def test_high_impact_deletion_asks_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            # a decision touching the schema makes a deletion of it high-impact
            crumb.main(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    "users table schema is canonical",
                    "--set",
                    "Decision",
                    "keep users schema",
                    "--confidence",
                    "low",
                    "--tags",
                    "schema,database",
                ]
            )
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "drop table users schema"},
                },
            )
            # deletion is a high-impact class; with a memory hit this escalates to ask
            if "hookSpecificOutput" in out:
                self.assertNotIn(
                    out["hookSpecificOutput"].get("permissionDecision"), ("allow", "deny")
                )

    def test_verdict_to_permission_decision_mapping(self):
        """All four verdicts map the same way: never `allow`, never `deny`.

        `permissionDecision: "allow"` auto-approves the call and hides the reason
        from the model — the inverse of "memory informs, never decides". PROCEED
        stays silent, READ_FIRST informs via additionalContext with no decision,
        PAUSE/ASK_HUMAN ask.
        """
        expected = {
            "PROCEED": (None, None),
            "READ_FIRST": (None, "additionalContext"),
            "PAUSE": ("ask", "permissionDecisionReason"),
            "ASK_HUMAN": ("ask", "permissionDecisionReason"),
        }
        self.assertEqual(set(expected), set(_cli._VERDICTS))
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            payload = {
                "cwd": str(root),
                "tool_name": "Bash",
                "tool_input": {"command": "git push --force origin main"},
            }
            real_guard = _cli.guard
            for verdict, (decision, reason_key) in expected.items():
                with self.subTest(verdict=verdict):

                    def fake_guard(*a, _v=verdict, **kw):
                        result = real_guard(*a, **kw)
                        result["verdict"] = _v
                        return result

                    _cli.guard = fake_guard
                    try:
                        out = run_hook("guard", payload)
                    finally:
                        _cli.guard = real_guard
                    if decision is None and reason_key is None:
                        self.assertEqual(out, {})
                        continue
                    hso = out["hookSpecificOutput"]
                    self.assertEqual(hso["hookEventName"], "PreToolUse")
                    self.assertEqual(hso.get("permissionDecision"), decision)
                    self.assertIn(verdict, hso[reason_key])


class HookCaptureTests(unittest.TestCase):
    def test_writes_session_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            out = run_hook("capture", {"cwd": str(root), "stop_reason": "end_turn"})
            self.assertEqual(out, {})
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 1)
            # the written record must validate clean (diff-stat summarized, no bloat)
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    def test_repeat_firings_write_one_record_and_keep_next_action(self):
        """`Stop` fires every turn, not once per session.

        Three consecutive firings against one store must leave exactly one
        session record, and must not overwrite a Next Action a human set.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            crumb.main(
                [
                    "capture",
                    "session",
                    "--project",
                    str(root),
                    "--fast",
                    "--next",
                    "wire the parser into the CLI",
                ]
            )
            before = sorted(p.name for p in (mem / "sessions").glob("*.md"))

            for _ in range(3):
                self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})

            self.assertEqual(sorted(p.name for p in (mem / "sessions").glob("*.md")), before)
            handoff = crumb.split_md_sections((mem / "handoff.md").read_text())
            self.assertEqual(handoff["Next Action"].strip(), "wire the parser into the CLI")

    def test_new_work_since_the_last_record_is_captured(self):
        """The dedupe guard must not swallow a firing after real work."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 1)
            # a second firing with nothing changed adds nothing …
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 1)
            # … but a new commit is new work.
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "more work")
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 2)
            # as is an uncommitted edit outside the store.
            (root / "h.txt").write_text("c\n")
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 3)

    def test_stop_hook_active_is_honored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            out = run_hook("capture", {"cwd": str(root), "stop_hook_active": True})
            self.assertEqual(out, {})
            self.assertEqual(list((mem / "sessions").glob("*.md")), [])

    def test_no_store_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_hook("capture", {"cwd": tmp})
            self.assertEqual(out, {})


class HookUsageTests(unittest.TestCase):
    """`crumb hook` with no subcommand read stdin before validating the event.

    From a terminal that blocks until EOF, so the usage error a user is waiting
    for looks like a hang instead.
    """

    def test_missing_subcommand_never_reads_stdin(self):
        def explode():
            raise AssertionError("stdin was read before the event was validated")

        err = io.StringIO()
        with (
            mock.patch.object(_cli, "_read_hook_stdin", side_effect=explode),
            contextlib.redirect_stderr(err),
        ):
            code = crumb.main(["hook"])
        self.assertEqual(code, 2)
        self.assertIn("session|guard|capture", err.getvalue())

    def test_does_not_block_on_a_terminal(self):
        """End to end: a real process with a tty-less pipe that never sends EOF."""
        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "crumb.py"), "hook"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _, stderr = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - the bug being fixed
            proc.kill()
            self.fail("`crumb hook` blocked on stdin instead of reporting usage")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("session|guard|capture", stderr)

    def test_valid_events_still_read_their_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            self.assertIsInstance(run_hook("session", {"cwd": str(root)}), dict)


if __name__ == "__main__":
    unittest.main()
