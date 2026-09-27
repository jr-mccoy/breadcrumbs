"""Tests for the store write lock (WM-51).

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

sys.path.insert(0, str(Path(__file__).resolve().parent))

import crumb  # noqa: E402
from breadcrumbs import inbox, lock, mcp_core  # noqa: E402
from _lockproc import can_take, held_by_another_process  # noqa: E402


def _cli_module():
    from breadcrumbs import cli

    return cli


def run(argv: list[str], stdin: str | None = None) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        if stdin is not None:
            with mock.patch.object(sys, "stdin", io.StringIO(stdin)):
                code = crumb.main(argv)
        else:
            code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


def init_store(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


class StoreLockTests(unittest.TestCase):
    def test_the_lock_is_held_only_inside_the_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with lock.store_lock(mem):
                self.assertTrue(lock.holds_lock(mem))
                self.assertFalse(can_take(mem), "another process took a held lock")
                self.assertEqual(lock.lock_owner(mem), os.getpid())
            self.assertFalse(lock.holds_lock(mem))
            self.assertTrue(can_take(mem))
            # The file is permanent (an OS lock lives on its inode); only the
            # owner line is cleared.
            self.assertTrue(lock.lock_path(mem).exists())
            self.assertIsNone(lock.lock_owner(mem))

    def test_it_is_reentrant_in_one_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with lock.store_lock(mem, timeout=0.1):
                with lock.store_lock(mem, timeout=0.1):
                    self.assertTrue(lock.holds_lock(mem))
                self.assertTrue(lock.holds_lock(mem))
                self.assertFalse(can_take(mem), "inner exit must not release")
            self.assertTrue(can_take(mem))

    def test_two_threads_writing_jots_produce_two_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            order: list[str] = []
            errors: list[BaseException] = []

            def writer(text: str, hold: float) -> None:
                try:
                    with lock.store_lock(mem, timeout=5):
                        order.append(f"start {text}")
                        res = inbox.write_jot(mem, Path(tmp), text)
                        assert res["ok"], res
                        time.sleep(hold)
                        order.append(f"end {text}")
                except BaseException as exc:  # pragma: no cover - reported below
                    errors.append(exc)

            a = threading.Thread(target=writer, args=("first observation about ledgers", 0.3))
            b = threading.Thread(target=writer, args=("second observation about queues", 0.0))
            a.start()
            time.sleep(0.05)
            b.start()
            a.join()
            b.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(list((mem / "inbox").glob("*.md"))), 2)
            # Serialised: the second writer started only after the first ended.
            self.assertEqual(
                order.index("end first observation about ledgers") + 1,
                order.index("start second observation about queues"),
            )

    def test_an_old_owner_line_does_not_block(self):
        # Only the kernel's lock decides; what the file says is for messages.
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            path = lock.lock_path(mem)
            path.parent.mkdir(parents=True, exist_ok=True)
            old = time.time() - 120
            path.write_text(f"{os.getppid()} {old:.3f}\n", encoding="utf-8")
            os.utime(path, (old, old))  # no heartbeat has touched it since
            with lock.store_lock(mem, timeout=0.1):
                self.assertIn(str(os.getpid()), path.read_text("utf-8"))

    def test_a_dead_process_s_owner_line_does_not_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            proc = subprocess.Popen([sys.executable, "-c", "pass"])
            proc.wait()
            path = lock.lock_path(mem)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{proc.pid} {time.time():.3f}\n", encoding="utf-8")
            with lock.store_lock(mem, timeout=0.1):
                pass

    def test_a_live_foreign_lock_times_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with held_by_another_process(mem) as pid:
                start = time.monotonic()
                with self.assertRaises(lock.StoreLocked) as ctx:
                    with lock.store_lock(mem, timeout=0.2):
                        pass
                self.assertLess(time.monotonic() - start, 2)
                self.assertEqual(ctx.exception.pid, pid)


class CallerTests(unittest.TestCase):
    def test_a_cli_write_fails_with_exit_1_and_names_the_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with held_by_another_process(mem) as pid, mock.patch.object(lock, "CLI_TIMEOUT", 0.2):
                code, _out, err = run(["jot", "something worth noting here", "--project", tmp])
            self.assertEqual(code, 1)
            self.assertIn(f"store is locked by pid {pid}", err)
            self.assertEqual(list((mem / "inbox").glob("*.md")), [])

    def test_a_read_command_does_not_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with held_by_another_process(mem):
                start = time.monotonic()
                code, _out, _err = run(["search", "anything", "--project", tmp])
                self.assertEqual(code, 0)
                self.assertLess(time.monotonic() - start, lock.CLI_TIMEOUT)

    def test_a_writing_hook_prints_empty_json_fast(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            payload = json.dumps({"cwd": tmp, "session_id": "s1", "transcript_path": ""})
            with held_by_another_process(mem):
                start = time.monotonic()
                code, out, _err = run(["hook", "capture"], stdin=payload)
                elapsed = time.monotonic() - start
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), "{}")
            self.assertLess(elapsed, lock.HOOK_TIMEOUT + 1.0)
            self.assertEqual(list((mem / "sessions").glob("*.md")), [])

    def test_an_mcp_writer_returns_a_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with held_by_another_process(mem) as pid, mock.patch.object(lock, "MCP_TIMEOUT", 0.2):
                res = mcp_core.tool_jot("an observation over mcp", root=tmp)
            self.assertFalse(res["ok"])
            self.assertIn(f"pid {pid}", res["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)


class LockFixTests(unittest.TestCase):
    def test_listings_and_resume_do_not_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            with held_by_another_process(mem), mock.patch.object(lock, "CLI_TIMEOUT", 5):
                for argv in (["inbox"], ["traps"], ["consolidate"], ["resume"]):
                    with self.subTest(cmd=argv[0]):
                        start = time.monotonic()
                        code, _out, err = run([*argv, "--project", tmp])
                        self.assertEqual(code, 0, err)
                        self.assertLess(time.monotonic() - start, 3)

    def test_init_force_keeps_its_own_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            inode = lock.lock_path(mem).stat().st_ino
            seen: list[tuple[bool, bool]] = []
            real = _cli_module().try_reindex_projections

            def spy(memory_dir, project_root, **kwargs):
                seen.append((lock.holds_lock(memory_dir), can_take(memory_dir)))
                return real(memory_dir, project_root, **kwargs)

            with mock.patch.object(_cli_module(), "try_reindex_projections", side_effect=spy):
                code, _o, err = run(
                    ["init", "--project", tmp, "--force", "--session-tracking", "full"]
                )
            self.assertEqual(code, 0, err)
            # Held, and exclusive, after the store's contents were replaced.
            self.assertEqual(seen, [(True, False)])
            self.assertEqual(lock.lock_path(mem).stat().st_ino, inode, "the lock file was replaced")
            self.assertTrue(can_take(mem), "released at the end")

    def test_a_thread_timeout_does_not_blame_this_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            release = threading.Event()
            holding = threading.Event()

            def holder() -> None:
                with lock.store_lock(mem):
                    holding.set()
                    release.wait(5)

            t = threading.Thread(target=holder)
            t.start()
            holding.wait(5)
            try:
                with self.assertRaises(lock.StoreLocked) as ctx:
                    with lock.store_lock(mem, timeout=0.1):
                        pass
                self.assertIn("another thread", str(ctx.exception))
            finally:
                release.set()
                t.join()
