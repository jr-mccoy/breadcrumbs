"""Tests for the hook log (WM-62).

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import hooklog, lock  # noqa: E402


def init_store(tmp: str) -> Path:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


def hook(event: str, payload: dict) -> str:
    out = io.StringIO()
    with (
        mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        code = crumb.main(["hook", event])
    assert code == 0
    return out.getvalue()


def run(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, out.getvalue()


class HookLogTests(unittest.TestCase):
    def test_every_hook_logs_one_line_and_its_output_is_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            base = {"cwd": tmp, "session_id": "sess-1"}
            outputs = {
                "session": hook("session", base),
                "guard": hook(
                    "guard", {**base, "tool_name": "Bash", "tool_input": {"command": "ls"}}
                ),
                "prompt": hook("prompt", {**base, "prompt": "tidy up the README headings"}),
                "capture": hook("capture", {**base, "transcript_path": ""}),
                "compact": hook("compact", {**base, "transcript_path": ""}),
                "subagent": hook("subagent", {**base, "transcript_path": ""}),
            }
            entries = hooklog.read_log(mem)
            self.assertEqual([e["event"] for e in entries], list(outputs))
            for e in entries:
                self.assertEqual(e["session"], "sess-1")
                self.assertIsInstance(e["ms"], float)
                self.assertIn("at", e)
            by = {e["event"]: e for e in entries}
            self.assertEqual(by["session"]["outcome"], "context")
            self.assertIn("additionalContext", outputs["session"])
            self.assertEqual(by["guard"]["tool"], "Bash")
            self.assertEqual(json.loads(outputs["guard"]), {})
            self.assertEqual(by["guard"]["outcome"], "silent")

    def test_the_log_never_holds_what_the_hook_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            base = {"cwd": tmp, "session_id": "s"}
            hook("prompt", {**base, "prompt": "no, use the zebracorn endpoint instead"})
            hook(
                "guard",
                {**base, "tool_name": "Bash", "tool_input": {"command": "rm -rf quokkadir"}},
            )
            text = hooklog.log_path(mem).read_text("utf-8")
            self.assertNotIn("zebracorn", text)
            self.assertNotIn("quokkadir", text)
            ignore = (Path(tmp) / ".gitignore").read_text("utf-8")
            self.assertIn(f"{crumb.MEMORY_DIRNAME}/private/**", ignore)

    def test_a_writer_skipped_by_the_lock_is_logged_as_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
            try:
                path = lock.lock_path(mem)
                path.write_text(f"{proc.pid} {time.time():.3f}\n", encoding="utf-8")
                out = hook("capture", {"cwd": tmp, "session_id": "s", "transcript_path": ""})
            finally:
                proc.kill()
                proc.wait()
                lock.lock_path(mem).unlink(missing_ok=True)
            self.assertEqual(out.strip(), "{}")
            self.assertEqual(hooklog.read_log(mem)[-1]["outcome"], "locked")

    def test_no_store_means_no_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            hook("guard", {"cwd": tmp, "tool_name": "Bash", "tool_input": {"command": "ls"}})
            self.assertFalse((Path(tmp) / crumb.MEMORY_DIRNAME).exists())

    def test_the_log_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with (
                mock.patch.object(hooklog, "HOOK_LOG_MAX_LINES", 10),
                mock.patch.object(hooklog, "HOOK_LOG_TRIM_TO", 6),
                mock.patch.object(hooklog, "_MIN_LINE_BYTES", 1),
            ):
                for i in range(25):
                    hooklog.append(mem, {"event": "guard", "n": i})
                    lines = hooklog.log_path(mem).read_text("utf-8").splitlines()
                    self.assertLessEqual(len(lines), 10)
            self.assertEqual(json.loads(lines[-1])["n"], 24)

    def test_output_survives_a_handler_that_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)

            def handler() -> int:
                print('{"partial": true}')
                raise RuntimeError("boom")

            out = io.StringIO()
            with contextlib.redirect_stdout(out), self.assertRaises(RuntimeError):
                hooklog.run_logged("guard", mem, {}, handler, crumb.now_iso)
            self.assertIn('"partial"', out.getvalue())

    def test_outcomes_read_off_the_printed_json(self):
        cases = {
            "{}": "silent",
            '{"decision": "block", "reason": "x"}': "block",
            '{"hookSpecificOutput": {"permissionDecision": "ask"}}': "ask",
            '{"hookSpecificOutput": {"additionalContext": "x"}}': "context",
            "not json": "unparsed",
        }
        for text, outcome in cases.items():
            with self.subTest(text=text):
                self.assertEqual(hooklog.outcome_of(text), outcome)


class DoctorHookLogTests(unittest.TestCase):
    def test_an_empty_log_says_so(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(["doctor", "--hook-log", "--project", tmp])
            self.assertEqual(code, 0)
            self.assertIn("no hook firings logged yet", out)

    def test_the_summary_counts_outcomes_verdicts_and_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for i, (outcome, verdict) in enumerate(
                [("silent", "PROCEED"), ("context", "READ_FIRST"), ("ask", "PAUSE")]
            ):
                hooklog.append(
                    mem,
                    {
                        "event": "guard",
                        "at": f"2026-09-0{i + 1}T00:00:00+00:00",
                        "ms": float(i + 1),
                        "outcome": outcome,
                        "verdict": verdict,
                        "session": f"s{i % 2}",
                    },
                )
            hooklog.append(mem, {"event": "capture", "ms": 5.0, "outcome": "locked"})
            hooklog.append(
                mem,
                {"event": "capture", "ms": 5.0, "outcome": "silent", "mined": 2, "snapshot": True},
            )
            hooklog.append(mem, {"event": "capture", "ms": 5.0, "outcome": "block", "mined": 1})
            code, out = run(["doctor", "--hook-log", "--project", tmp, "--json"])
            data = json.loads(out)
            self.assertEqual(code, 0)
            self.assertEqual(data["entries"], 6)
            self.assertEqual(data["events"]["capture"]["counts"], {"mined": 3, "snapshot": 1})
            self.assertEqual(data["events"]["capture"]["spoke_rate"], round(1 / 3, 3))
            self.assertEqual(data["sessions"], 2)
            self.assertEqual(data["locked"], 1)
            guard = data["events"]["guard"]
            self.assertEqual(guard["count"], 3)
            self.assertEqual(guard["verdicts"], {"PROCEED": 1, "READ_FIRST": 1, "PAUSE": 1})
            self.assertEqual(guard["spoke_rate"], round(2 / 3, 3))
            self.assertEqual(guard["ms_max"], 3.0)
            code, text = run(["doctor", "--hook-log", "--project", tmp])
            self.assertIn("skipped because another writer held the store lock", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
