"""Writer coordination with real processes (audit F06, F08; WP05).

The write lock used to be an exclusive-create file with a heartbeat: a lock not
touched for 60 seconds was "stale" and could be broken, so a suspended writer
or a clock jump let a second writer in while the first was still alive. And
`crumb resume` republished the generated projections without taking it at all.

These use separate processes, because the lock is now an OS lock and a pid
written into a file proves nothing to the kernel.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import crumb  # noqa: E402
from breadcrumbs import lock  # noqa: E402
from _lockproc import can_take, held_by_another_process, spawn_holder  # noqa: E402

PROJECTIONS = ("resume-packet.md", "guard-prefilter.json", "related.json", "conflicts.json")


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


class LockCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def projections(self) -> dict[str, bytes]:
        gen = self.mem / "generated"
        return {name: (gen / name).read_bytes() for name in PROJECTIONS if (gen / name).exists()}


class ResumeTests(LockCase):
    def test_resume_does_not_publish_under_foreign_writer(self):
        # A record the projections do not include yet, so a publish would show.
        crumb.write_record(
            self.mem, self.root, "decision", "Use the blue queue", {"Decision": "d"},
            confidence="low",
        )  # fmt: skip
        before = self.projections()
        with held_by_another_process(self.mem) as pid:
            start = time.monotonic()
            code, out, err = run(["resume", "--project", str(self.root), "--json"])
            elapsed = time.monotonic() - start
            self.assertEqual(self.projections(), before, "resume wrote under a foreign lock")
        self.assertEqual(code, 0, err)
        payload = json.loads(out)
        # The packet is still built and shown, and says what it did not publish.
        self.assertIn("Use the blue queue", [d["title"] for d in payload["active_decisions"]])
        self.assertFalse(payload["publication"]["published"])
        self.assertIn(f"pid {pid}", payload["publication"]["reason"])
        self.assertLess(elapsed, lock.HOOK_TIMEOUT + 3)

        # With the writer gone, the next resume publishes.
        code, out, _err = run(["resume", "--project", str(self.root), "--json"])
        self.assertTrue(json.loads(out)["publication"]["published"])
        self.assertNotEqual(self.projections(), before)

    def test_a_view_is_reported_as_unpublished(self):
        code, out, _err = run(["resume", "--project", str(self.root), "--fast", "--json"])
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(out)["publication"]["published"])


class OwnershipTests(LockCase):
    def test_process_death_releases_os_lock(self):
        holder = spawn_holder(self.mem)
        self.assertFalse(can_take(self.mem))
        holder.kill()  # SIGKILL: no cleanup code runs in the holder
        holder.wait()
        start = time.monotonic()
        with lock.store_lock(self.mem, timeout=2):
            self.assertLess(time.monotonic() - start, 1.0)

    def test_live_owner_is_not_stolen_after_clock_gap(self):
        with held_by_another_process(self.mem):
            # The old rule broke a lock untouched for 60 s. Make the file look
            # an hour old and jump this process's clock forward too.
            ancient = time.time() - 3600
            os.utime(lock.lock_path(self.mem), (ancient, ancient))
            later = time.time() + 3600
            with mock.patch.object(lock.time, "time", return_value=later):
                with self.assertRaises(lock.StoreLocked):
                    with lock.store_lock(self.mem, timeout=0.3):
                        self.fail("took a lock a live process holds")
            self.assertFalse(can_take(self.mem, timeout=0.3))

    @unittest.skipUnless(os.name == "posix", "SIGSTOP is POSIX")
    def test_a_suspended_owner_keeps_its_lock(self):
        holder = spawn_holder(self.mem)
        try:
            os.kill(holder.pid, signal.SIGSTOP)
            self.assertFalse(can_take(self.mem, timeout=0.5))
        finally:
            os.kill(holder.pid, signal.SIGCONT)
            holder.stdin.close()
            holder.wait(timeout=10)
        self.assertTrue(can_take(self.mem))

    def test_force_init_preserves_coordination(self):
        crumb.write_record(
            self.mem, self.root, "decision", "Keep me", {"Decision": "d"}, confidence="low"
        )
        inode = lock.lock_path(self.mem).stat().st_ino
        with held_by_another_process(self.mem), mock.patch.object(lock, "CLI_TIMEOUT", 0.3):
            code, _out, err = run(
                ["init", "--project", str(self.root), "--force", "--session-tracking", "full"]
            )
        self.assertEqual(code, 1, err)
        self.assertIn("locked", err)
        self.assertEqual(len(list((self.mem / "decisions").glob("*.md"))), 1, "store replaced")
        # Uncontended, it runs and keeps the same lock file.
        code, _out, err = run(
            ["init", "--project", str(self.root), "--force", "--session-tracking", "full"]
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(lock.lock_path(self.mem).stat().st_ino, inode)
        self.assertTrue(can_take(self.mem))


class ConcurrencyTests(LockCase):
    def _crumb(self, *argv: str) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "crumb.py"), *argv, "--project", str(self.root)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def test_parallel_writers_lose_nothing_they_acknowledge(self):
        procs = [
            self._crumb("jot", f"parallel observation number {i} about the {w} queue")
            for i, w in enumerate(("amber", "blue", "cyan", "dusk", "ember", "fern"))
        ]
        results = [(p.wait(timeout=60), p.stderr.read()) for p in procs]
        written = len(list((self.mem / "inbox").glob("*.md")))
        succeeded = sum(1 for code, _ in results if code == 0)
        # Every acknowledged write is on disk; a refused one says it was locked.
        self.assertEqual(written, succeeded)
        for code, err in results:
            if code != 0:
                self.assertIn("locked", err)
        fails = [f for f in crumb.run_validate(self.mem) if f["status"] == "fail"]
        self.assertEqual(fails, [], "projections left inconsistent")

    def test_two_reindexes_leave_consistent_projections(self):
        procs = [self._crumb("reindex") for _ in range(3)]
        for p in procs:
            p.wait(timeout=60)
        fails = [f for f in crumb.run_validate(self.mem) if f["status"] == "fail"]
        self.assertEqual(fails, [])
        leftovers = [p.name for p in (self.mem / "index").glob("*.tmp")] + [
            p.name for p in (self.mem / "generated").glob("*.tmp")
        ]
        self.assertEqual(leftovers, [])


class CompatibilityTests(LockCase):
    def test_an_older_version_s_live_lock_is_waited_on_and_never_removed(self):
        legacy = lock.legacy_lock_path(self.mem)
        old_writer = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        try:
            legacy.write_text(f"{old_writer.pid} {time.time():.3f} {lock._host()}\n")
            with self.assertRaises(lock.StoreLocked) as ctx:
                with lock.store_lock(self.mem, timeout=0.3):
                    pass
            self.assertEqual(ctx.exception.pid, old_writer.pid)
            self.assertTrue(legacy.exists())
            # One its writer stopped touching long ago is ignored, not deleted.
            ancient = time.time() - 3600
            os.utime(legacy, (ancient, ancient))
            with lock.store_lock(self.mem, timeout=0.3):
                pass
            self.assertTrue(legacy.exists())
        finally:
            old_writer.kill()
            old_writer.wait()

    def test_a_filesystem_without_locks_is_reported(self):
        refused = OSError(errno.ENOLCK, "No locks available")
        with mock.patch.object(lock, "_try_os_lock", side_effect=refused):
            with self.assertRaises(lock.LockUnsupported) as ctx:
                with lock.store_lock(self.mem, timeout=0.1):
                    pass
            self.assertIn("local filesystem", str(ctx.exception))
            code, _out, err = run(["jot", "an observation", "--project", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("local filesystem", err)


if __name__ == "__main__":
    unittest.main()
