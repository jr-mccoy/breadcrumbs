"""Replay is execution, not proof (audit F04, F25; WP04).

`crumb verify --recheck` used to write `fixed` whenever every recorded command
exited 0, and `open` otherwise. So a `python -c pass` "fixed" an authentication
bug, and a test-file path was run as a program. The new record also lost the
original's branch scope. The run itself was a shell with a timeout on the
immediate child and output trimmed only after it finished.

These pin the replacement:

- A command is a diagnostic unless it is declared or bound as an assertion.
- Only an evaluated assertion settles a claim; a missing tool or a timeout is
  inconclusive.
- A settled recheck keeps the claim's subject, scope, branch and confidence.
- The run's output and its process tree are bounded.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import checks, lifecycle  # noqa: E402

PY = f'"{sys.executable}"'


def run(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, out.getvalue()


def git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=str(root),
        check=True,
        capture_output=True,
    )


def alive(pid: int) -> bool:
    """Is `pid` still running? A zombie (dead, not yet reaped by its new parent,
    which in a container is often a PID 1 that reaps slowly) does not count."""
    stat = Path(f"/proc/{pid}/stat")
    if stat.exists():
        try:
            return stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
        except (OSError, IndexError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


class ReplayCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def store(self, *, git_branch: str | None = None) -> Path:
        if git_branch:
            git(self.root, "init", "-q", "-b", "main")
            git(self.root, "config", "user.email", "t@t")
            git(self.root, "config", "user.name", "t")
            git(self.root, "commit", "-q", "--allow-empty", "-m", "base")
            git(self.root, "checkout", "-q", "-b", git_branch)
        run(["init", "--project", str(self.root), "--session-tracking", "full"])
        return self.root / crumb.MEMORY_DIRNAME

    def verification(self, mem: Path, *, status="open", evidence=(), **kwargs) -> str:
        res = crumb.verify(
            mem,
            self.root,
            "Quasar authentication bug",
            status=status,
            evidence=list(evidence),
            **kwargs,
        )
        self.assertTrue(res["ok"], res)
        return res["id"]

    def recheck(self, mem: Path, rid: str, **kwargs) -> dict:
        return lifecycle.recheck(mem, self.root, crumb.find_record_by_id(mem, rid), **kwargs)


class SettlementTests(ReplayCase):
    def test_noop_diagnostic_does_not_fix_claim(self):
        mem = self.store()
        rid = self.verification(mem, evidence=[{"type": "command", "ref": f'{PY} -c "pass"'}])
        res = self.recheck(mem, rid)
        self.assertTrue(res["ok"], res)
        self.assertFalse(res["settled"])
        self.assertIsNone(res["new_id"])
        self.assertEqual(res["runs"][0]["status"], checks.PASSED)
        self.assertEqual(res["runs"][0]["kind"], "diagnostic")
        rec = crumb.find_record_by_id(mem, rid)
        self.assertEqual((rec.meta["status"], rec.meta["outcome"]), ("active", "open"))
        self.assertEqual(len(crumb.load_records(mem, types=("verification",))), 1)

    def test_a_declared_assertion_settles_its_claim(self):
        mem = self.store()
        rid = self.verification(mem, evidence=[checks.assertion_item(f'{PY} -c "pass"')])
        res = self.recheck(mem, rid)
        self.assertTrue(res["settled"], res)
        self.assertEqual(res["outcome"], "fixed")
        new = crumb.find_record_by_id(mem, res["new_id"])
        self.assertEqual(new.meta["supersedes"], [rid])
        self.assertEqual(crumb.find_record_by_id(mem, rid).meta["status"], "superseded")

    def test_assertion_failure_differs_from_runner_unavailability(self):
        mem = self.store()
        failing = checks.assertion_item(f'{PY} -c "import sys; sys.exit(1)"')
        missing = checks.assertion_item("definitely-not-a-real-tool-4f1c --check")

        rid = self.verification(mem, status="fixed", evidence=[failing])
        res = self.recheck(mem, rid)
        self.assertEqual(res["runs"][0]["status"], checks.FAILED)
        self.assertEqual(res["outcome"], "regressed")  # it was recorded as fixed

        rid = self.verification(mem, status="open", evidence=[failing])
        self.assertEqual(self.recheck(mem, rid)["outcome"], "open")

        rid = self.verification(mem, status="open", evidence=[missing])
        res = self.recheck(mem, rid)
        self.assertEqual(res["runs"][0]["status"], checks.UNAVAILABLE)
        self.assertFalse(res["settled"])
        self.assertIn("inconclusive", res["reason"])
        self.assertEqual(crumb.find_record_by_id(mem, rid).meta["status"], "active")

    def test_a_timeout_is_inconclusive(self):
        mem = self.store()
        rid = self.verification(
            mem, evidence=[checks.assertion_item(f'{PY} -c "import time; time.sleep(30)"')]
        )
        res = self.recheck(mem, rid, timeout=0.5)
        self.assertEqual(res["runs"][0]["status"], checks.TIMEOUT)
        self.assertFalse(res["settled"])

    def test_an_unknown_assertion_spec_is_not_run(self):
        mem = self.store()
        sentinel = self.root / "ran"
        item = {"type": "assert", "ref": f"touch {sentinel}", "spec": "9"}
        rid = self.verification(mem, evidence=[item])
        res = self.recheck(mem, rid)
        self.assertEqual(res["runs"][0]["status"], checks.UNSUPPORTED)
        self.assertFalse(res["settled"])
        self.assertFalse(sentinel.exists())

    def test_diagnostics_beside_an_assertion_do_not_decide_it(self):
        mem = self.store()
        rid = self.verification(
            mem,
            evidence=[
                checks.assertion_item(f'{PY} -c "pass"'),
                {"type": "command", "ref": f'{PY} -c "import sys; sys.exit(3)"'},
            ],
        )
        res = self.recheck(mem, rid)
        self.assertEqual(res["outcome"], "fixed")
        self.assertEqual([r["kind"] for r in res["runs"]], ["assert", "diagnostic"])

    def test_bind_commands_is_explicit_and_recorded(self):
        mem = self.store()
        cmd = f'{PY} -c "pass"'
        rid = self.verification(mem, evidence=[{"type": "command", "ref": cmd}])
        res = self.recheck(mem, rid, bind_commands=True)
        self.assertEqual(res["outcome"], "fixed")
        new = crumb.find_record_by_id(mem, res["new_id"])
        self.assertIn(checks.assertion_item(cmd), new.meta["evidence"])

    def test_a_test_file_reference_is_never_executed(self):
        mem = self.store()
        script = self.root / "tests" / "test_x.py"
        script.parent.mkdir()
        sentinel = self.root / "ran"
        script.write_text(f"#!/bin/sh\ntouch {sentinel}\n")
        script.chmod(0o755)
        rid = self.verification(mem, evidence=[{"type": "test", "ref": "tests/test_x.py"}])
        targets, problems = lifecycle.recheck_targets(mem, [rid], self.root)
        self.assertEqual(targets, [])
        self.assertIn("test-file evidence is not run", problems[0])
        self.assertFalse(sentinel.exists())


class ScopeTests(ReplayCase):
    def test_recheck_preserves_branch_scope_across_checkout(self):
        mem = self.store(git_branch="feature/audit")
        rid = self.verification(
            mem,
            evidence=[checks.assertion_item(f'{PY} -c "pass"')],
            scope="branch",
            confidence="low",
        )
        res = self.recheck(mem, rid)
        self.assertTrue(res["settled"], res)
        new = crumb.find_record_by_id(mem, res["new_id"])
        self.assertEqual(
            (new.meta["scope"], new.meta["branch"], new.meta["confidence"], new.meta["subject"]),
            ("branch", "feature/audit", "low", "Quasar authentication bug"),
        )

        git(self.root, "checkout", "-q", "main")
        packet = crumb.build_resume_packet(mem, self.root)
        self.assertNotIn(res["new_id"], [v["id"] for v in packet["verifications"]])
        # A run from main would describe main, so the claim is not rechecked here.
        targets, problems = lifecycle.recheck_targets(mem, [res["new_id"]], self.root)
        self.assertEqual(targets, [])
        self.assertIn("scoped to branch feature/audit", problems[0])


class BoundsTests(ReplayCase):
    def test_output_and_descendant_processes_are_bounded(self):
        # Five megabytes of output are counted but not kept.
        loud = checks.run_check(
            f"{PY} -c \"import sys; sys.stdout.write('x' * 5_000_000)\"",
            self.root,
            window=4096,
        )
        self.assertEqual(loud.status, checks.PASSED)
        self.assertEqual(loud.output_bytes, 5_000_000)
        self.assertTrue(loud.truncated)
        self.assertLessEqual(sum(len(line) for line in loud.tail), 4096)

        if os.name != "posix":
            self.skipTest("process-group cleanup is exercised on POSIX here")
        # A child that outlives its parent is ended with the check, and does not
        # hold the check open until it finishes.
        pidfile = self.root / "child.pid"
        started = time.monotonic()
        res = checks.run_check(f"sleep 60 & echo $! > {pidfile}; exit 0", self.root)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(res.status, checks.PASSED)
        pid = int(pidfile.read_text().strip())
        deadline = time.monotonic() + 5
        while alive(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertFalse(alive(pid), "the background child survived its check")

    def test_a_timeout_ends_the_whole_tree(self):
        if os.name != "posix":
            self.skipTest("POSIX process groups")
        pidfile = self.root / "child.pid"
        # The parent outlives the timeout but not the child, so only a cleanup
        # of the whole group ends the child in time.
        res = checks.run_check(f"sleep 60 & echo $! > {pidfile}; sleep 5", self.root, timeout=0.5)
        self.assertEqual(res.status, checks.TIMEOUT)
        pid = int(pidfile.read_text().strip())
        time.sleep(0.2)
        self.assertFalse(alive(pid), "the background child survived the timeout")

    def test_a_detached_child_is_reported_not_waited_for(self):
        if os.name != "posix" or shutil.which("setsid") is None:
            self.skipTest("needs POSIX setsid")
        pidfile = self.root / "escaped.pid"
        started = time.monotonic()
        res = checks.run_check(
            f"setsid sh -c 'echo $$ > {pidfile}; sleep 30' & sleep 0.3", self.root
        )
        try:
            self.assertLess(time.monotonic() - started, 10)
            self.assertIn("left the group", res.detail or "")
        finally:
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(pidfile.read_text().strip()), 9)

    def test_secret_shaped_output_is_dropped(self):
        res = checks.run_check(f"{PY} -c \"print('key AKIAIOSFODNN7EXAMPLE')\"", self.root)
        self.assertEqual(res.tail, ["[line dropped: looked like a secret]"])

    def test_a_command_that_cannot_start_is_unavailable(self):
        res = checks.run_check("echo hi", self.root / "does-not-exist")
        self.assertEqual(res.status, checks.UNAVAILABLE)
        self.assertIn("could not start", res.detail)


class CliTests(ReplayCase):
    def test_the_preview_says_what_can_settle(self):
        mem = self.store()
        rid = self.verification(mem, evidence=[{"type": "command", "ref": "true"}])
        code, out = run(["verify", "--recheck", rid, "--yes", "--project", str(self.root)])
        self.assertEqual(code, 0, out)
        self.assertIn("[diagnostic]", out)
        self.assertIn("the claim cannot be settled by this run", out)
        self.assertIn("not settled", out)

    def test_verify_assert_declares_an_assertion(self):
        mem = self.store()
        code, out = run(
            [
                "verify", "Quasar login bug", "--status", "open", "--assert", "true",
                "--project", str(self.root), "--json",
            ]
        )  # fmt: skip
        self.assertEqual(code, 0, out)
        rec = crumb.find_record_by_id(mem, json.loads(out)["id"])
        self.assertEqual(rec.meta["evidence"], [checks.assertion_item("true")])
        code, out = run(
            ["verify", "--recheck", rec.meta["id"], "--yes", "--project", str(self.root), "--json"]
        )
        payload = json.loads(out)
        self.assertEqual(payload["items"][0]["outcome"], "fixed")
        self.assertEqual(payload["summary"]["settled"], 1)


if __name__ == "__main__":
    unittest.main()
