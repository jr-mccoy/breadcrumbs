"""Regressions for the §3 tables of docs/reviews/2026-11-13-system-review.md.

Each test names its row (R3, W4, H1, …) and fails on the code the review read.

Run with:  python -m unittest discover -s tests -p test_review_tables.py
"""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
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
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import hooks_stop  # noqa: E402
from breadcrumbs import lock as _lock  # noqa: E402
from breadcrumbs import transcript as _transcript  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
    ).stdout


def make_repo(tmp: str) -> Path:
    root = Path(tmp)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    git(root, "config", "maintenance.auto", "false")
    git(root, "config", "gc.auto", "0")
    (root / "f.txt").write_text("a\n")
    git(root, "add", "f.txt")
    git(root, "commit", "-qm", "init")
    return root


def init_store(root: Path) -> Path:
    with contextlib.redirect_stdout(io.StringIO()):
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


def run_hook_bytes(event: str, data: bytes, encoding: str = "utf-8") -> tuple[int, dict]:
    """`crumb hook <event>` in-process, stdin a text stream over `data`
    decoded as `encoding` would be by default (the locale of the pipe)."""
    saved = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(data), encoding=encoding)
    try:
        code, out, _err = run(["hook", event])
    finally:
        sys.stdin = saved
    text = out.strip()
    return code, (json.loads(text) if text else {})


def remember(root: Path, *extra: str) -> tuple[int, str, str]:
    return run(
        [
            "remember",
            "decision",
            "--project",
            str(root),
            "--title",
            "Cache rates per publication date",
            "--set",
            "Rationale",
            "The upstream publishes once a day.",
            "--confidence",
            "low",
            *extra,
        ]
    )


class ReadPathTests(unittest.TestCase):
    def test_r3_a_directory_named_like_a_record_is_a_finding_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            (mem / "decisions" / "x.md").mkdir()
            code, out, err = run(["validate", "--project", str(root)])
            self.assertEqual(code, 1)
            self.assertNotIn("Errno 21] Is a directory: 3", out + err)
            self.assertIn("decisions/x.md", out)
            code, out, err = run(["resume", "--fast", "--project", str(root)])
            self.assertEqual(code, 0, err)

    def test_r9_a_closed_pipe_is_not_a_crumb_error(self):
        class Closed(io.StringIO):
            def write(self, s):
                raise BrokenPipeError(errno.EPIPE, "Broken pipe")

            def flush(self):
                raise BrokenPipeError(errno.EPIPE, "Broken pipe")

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            for argv in (["resume"], ["--json", "resume"]):
                with self.subTest(argv=argv):
                    err = io.StringIO()
                    with (
                        mock.patch.object(sys, "stdout", Closed()),
                        contextlib.redirect_stderr(err),
                    ):
                        code = crumb.main([*argv, "--project", str(root)])
                    self.assertEqual(code, 141)
                    self.assertNotIn(_cli.ERROR_PREFIX, err.getvalue())
                    self.assertNotIn("Traceback", err.getvalue())

    @unittest.skipUnless(sys.platform.startswith("linux"), "F_SETPIPE_SZ is Linux-only")
    def test_r9_piped_to_head(self):
        import fcntl

        r, w = os.pipe()
        fcntl.fcntl(w, 1031, 4096)  # F_SETPIPE_SZ: smaller than the output
        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "crumb.py"), "--json", "search", "guard"],
            cwd=str(REPO_ROOT),
            stdout=w,
            stderr=subprocess.PIPE,
        )
        os.close(w)
        os.read(r, 10)
        os.close(r)
        err = proc.stderr.read().decode()
        proc.stderr.close()
        self.assertIn(proc.wait(), (0, 141))
        self.assertEqual(err, "")


class WritePathTests(unittest.TestCase):
    def test_w4_local_private_is_refused_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            code, _out, err = remember(root, "--privacy", "local-private")
            self.assertNotEqual(code, 0)
            self.assertIn("jot --local", err)
            self.assertEqual(list((mem / "decisions").glob("*.md")), [])
            self.assertEqual(remember(root)[0], 0)

    def test_w5_a_read_only_store_still_resumes_and_writers_say_why(self):
        def read_only(path):
            raise OSError(errno.EROFS, "Read-only file system", str(path))

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            with mock.patch.object(_lock, "_open_lock_file", read_only):
                code, out, err = run(["resume", "--project", str(root)])
                self.assertEqual(code, 0, err)
                self.assertIn("Resume Packet", out)
                code, _out, err = remember(root)
                self.assertEqual(code, 1)
                self.assertIn("read-only", err)
                self.assertNotIn("Traceback", err)
                payload = json.dumps({"cwd": str(root), "session_id": "s", "prompt": "hi"})
                for event in ("session", "prompt", "capture"):
                    with self.subTest(event=event):
                        self.assertEqual(run_hook_bytes(event, payload.encode())[0], 0)

    def test_w7_an_interrupted_writes_temp_file_is_ignored_reported_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            self.assertEqual(remember(root)[0], 0)
            record = next((mem / "decisions").glob("*.md"))
            orphan = record.with_name(f".{record.name}.0123456789ab.tmp")
            orphan.write_bytes(record.read_bytes())
            fresh = record.with_name(f".{record.name}.ba9876543210.tmp")
            fresh.write_bytes(b"in progress")
            old = time.time() - 600
            os.utime(orphan, (old, old))

            # Not committable.
            git(root, "check-ignore", "-q", str(orphan))
            # Reported; one young enough to be a live write is not.
            code, out, _err = run(["validate", "--project", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[temp-files]", out)
            self.assertIn(orphan.name, out)
            self.assertNotIn(fresh.name, out)
            code, out, _err = run(["recover", "--project", str(root)])
            self.assertIn(orphan.name, out)
            self.assertTrue(orphan.exists())
            # Removed.
            run(["recover", "--apply", "--project", str(root)])
            self.assertFalse(orphan.exists())
            self.assertTrue(fresh.exists())
            fresh.unlink()
            self.assertEqual(run(["validate", "--project", str(root)])[0], 0)


class HookTests(unittest.TestCase):
    def test_h1_the_payload_is_utf8_whatever_the_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projét-Á"
            project.mkdir()
            root = make_repo(str(project))
            init_store(root)
            payload = json.dumps({"cwd": str(root), "prompt": "Á fix it"}, ensure_ascii=False)
            # cp1252 is a Windows pipe's default; the host writes UTF-8.
            code, out = run_hook_bytes("session", payload.encode("utf-8"), encoding="cp1252")
            self.assertEqual(code, 0)
            self.assertIn("additionalContext", out.get("hookSpecificOutput", {}))
            code, _out = run_hook_bytes("prompt", payload.encode("utf-8"), encoding="cp1252")
            self.assertEqual(code, 0)

    def test_h5_hostile_payloads_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            (mem / "index").mkdir(exist_ok=True)
            (mem / "index" / "commit-order.txt").write_bytes(b"\xff\xfe garbage \x00\n")
            head = git(root, "rev-parse", "HEAD").strip()
            payloads = [
                '{"cwd": %s, "prompt": "x \\ud800 y", "session_id": "s"}' % json.dumps(str(root)),
                '{"cwd": %s, "n": %s}' % (json.dumps(str(root)), "9" * 5000),
                '{"cwd": %s, "prompt": "hi"}' % json.dumps(str(root) + "\u0000x"),
                '{"cwd": 5, "prompt": "hi"}',
            ]
            for event in ("session", "prompt", "guard", "capture", "compact", "subagent"):
                for raw in payloads:
                    with self.subTest(event=event, payload=raw[:40]):
                        code, _out = run_hook_bytes(event, raw.encode())
                        self.assertEqual(code, 0)
            # A cache that names HEAD but holds junk is a miss, not a history.
            (mem / "index" / "commit-order.txt").write_text(f"{head} 5000\nnot-a-sha\n")
            self.assertEqual(_cli._cached_commit_order(root)[0], head)

    def test_h7_a_tilde_transcript_path_is_expanded(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            root = make_repo(tmp)
            mem = init_store(root)
            (Path(home) / "t.jsonl").write_text("")
            with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}):
                report = _transcript.mine_transcript_into_jots(
                    mem, root, "~/t.jsonl", session_id="s"
                )
                self.assertFalse(report["missing"], report)
                report = _transcript.mine_transcript_into_jots(
                    mem, root, "~/absent.jsonl", session_id="s"
                )
                self.assertTrue(report["missing"])

    def test_h8_the_hook_log_records_no_path(self):
        status = (
            "failed: PermissionError: [Errno 13] Permission denied: "
            "'/home/someone/proj/.project-memory/sessions/a.md'"
        )
        kind = hooks_stop._error_kind(status)
        self.assertIn("Permission denied", kind)
        self.assertNotIn("/home", kind)
        self.assertNotIn("sessions/a.md", hooks_stop._error_kind("failed: exit 1: sessions/a.md"))
        self.assertEqual(hooks_stop._error_kind("failed: OSError: disk full"), "OSError: disk full")

    def test_h8_a_settings_file_of_the_wrong_shape_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            settings = root / ".claude" / "settings.json"
            settings.parent.mkdir()
            for text in ('{"hooks": []}', '{"hooks": {"PreToolUse": {"x": 1}}}', "[1]"):
                with self.subTest(settings=text):
                    settings.write_text(text)
                    code, _out, err = run(
                        ["init", "--with-hooks=session,guard", "--project", str(root)]
                    )
                    self.assertNotIn("Traceback", err)
                    self.assertEqual(settings.read_text(), text)  # nothing written
                    code, _out, err = run(["doctor", "--project", str(root)])
                    self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
