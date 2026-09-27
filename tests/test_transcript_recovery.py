"""Transcript mining is durable and incremental (audit F02; WP09).

The miner's cursor was a count of the *entries in an 8 MB tail*, stored as if
it were a position in the file. Once a transcript outgrew the tail, the count
stopped moving and nothing new was ever mined:

- a call whose result arrived a firing later was never joined to it;
- whatever the per-firing cap held back was gone as soon as the cursor moved;
- a crash between a jot and the cursor had no defined outcome.

These pin the replacement: a byte cursor with file identity, calls carried
between firings, a durable candidate backlog, and a ledger of acknowledged
events.

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
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from _jsonl import bash, edit, tool_result, tool_use, user_text  # noqa: E402
from _lockproc import held_by_another_process  # noqa: E402
from breadcrumbs import hooks_common as hc  # noqa: E402
from breadcrumbs import inbox as ibx  # noqa: E402
from breadcrumbs import transcript as tr  # noqa: E402


def append(path: Path, *entries: dict, raw: str = "") -> None:
    with path.open("a", encoding="utf-8") as fh:
        for entry in entries:
            fh.write(json.dumps(entry) + "\n")
        fh.write(raw)


def padded(text: str, pad: int) -> dict:
    entry = user_text(text)
    entry["padding"] = "x" * pad
    return entry


class RecoveryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        with contextlib.redirect_stdout(io.StringIO()):
            crumb.main(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME
        self.path = self.root / "transcript.jsonl"
        self.path.write_text("", encoding="utf-8")

    def ingest(self, session: str = "s1", **kwargs) -> dict:
        return tr.mine_transcript_into_jots(
            self.mem, self.root, str(self.path), session_id=session, **kwargs
        )

    def titles(self) -> list[str]:
        return sorted(ibx.jot_title(r) for r in ibx.load_jots(self.mem, include_retired=True))


class CursorTests(RecoveryCase):
    def test_sliding_tail_does_not_freeze_cursor(self):
        # 18 lines of ~500 KB: past the 8 MB a firing reads.
        append(self.path, *[padded(f"ordinary progress {i}", 500_000) for i in range(18)])
        self.assertGreater(self.path.stat().st_size, tr.DEFAULT_MAX_BYTES)
        first = self.ingest()
        for n in range(4):
            append(self.path, padded(f"No, keep retry budget number {n} during deploys.", 500_000))
            self.ingest()
        self.ingest()  # drain whatever the last window left
        found = [t for t in self.titles() if t.startswith("No, keep retry budget")]
        self.assertEqual(len(found), 4, found)  # each new event exactly once
        self.assertEqual(self.ingest()["written"], [])
        # (new in WP09) the first firing said how much it left for the next,
        # and the cursor now sits at the end of the file.
        self.assertGreater(first.get("unread_bytes", 0), 0)
        self.assertEqual(hc.miner_cursor(self.mem, "s1"), self.path.stat().st_size)

    def test_call_and_late_result_join_across_firings(self):
        append(self.path, tool_use("c1", "Bash", {"command": "python -m pytest tests/test_x.py"}))
        self.assertEqual(self.ingest()["written"], [])  # no result yet: nothing to say
        append(self.path, tool_result("c1", "FAILED tests/test_x.py::test_a", True))
        append(self.path, *edit("c2", "src/x.py"))
        self.ingest()
        append(self.path, tool_use("c3", "Bash", {"command": "python -m pytest tests/test_x.py"}))
        self.ingest()  # the pass has not arrived: still no "passed"
        self.assertFalse([t for t in self.titles() if "passed" in t], self.titles())
        append(self.path, tool_result("c3", "3 passed"))
        self.ingest()
        titles = self.titles()
        self.assertIn(
            "python -m pytest tests/test_x.py failed, then passed after 1 file(s) changed", titles
        )
        self.assertIn("python -m pytest tests/test_x.py passed", titles)
        # A call that never gets its result is never a success.
        append(self.path, tool_use("c4", "Bash", {"command": "npm test"}))
        self.ingest()
        self.assertNotIn("npm test passed", self.titles())

    def test_partial_line_rotation_and_restart_preserve_progress(self):
        line = json.dumps(user_text("No, do not squash the migration commits.")) + "\n"
        append(self.path, raw=line[:25])  # the harness is mid-write
        self.assertEqual(self.ingest()["written"], [])
        append(self.path, raw=line[25:])
        self.assertEqual(len(self.ingest()["written"]), 1)

        # A restart: a new process picks up from the saved cursor.
        append(self.path, user_text("Never force-push to the release branch."))
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]);"
            "from pathlib import Path; from breadcrumbs import transcript as tr;"
            "r = tr.mine_transcript_into_jots(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4],"
            " session_id='s1'); print(len(r['written']))"
        )
        out = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
                str(REPO_ROOT),
                str(self.mem),
                str(self.root),
                str(self.path),
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        self.assertEqual(out, "1")

        # Rotation: the same history in a new file, plus something new. Nothing
        # is written twice; the new event is mined.
        rotated = self.root / "rotated.jsonl"
        shutil.copy(self.path, rotated)
        with rotated.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(user_text("Stop editing generated files by hand.")) + "\n")
        os.replace(rotated, self.path)
        before = len(self.titles())
        report = self.ingest()
        self.assertEqual(len(report["written"]), 1)
        self.assertEqual(len(self.titles()), before + 1)

        # Truncation: a shorter file is a new file, read from the start.
        self.path.write_text(json.dumps(user_text("Don't rebase shared branches.")) + "\n")
        report = self.ingest()
        self.assertEqual(len(report["written"]), 1)
        titles = self.titles()
        self.assertEqual(len(titles), len(set(titles)), titles)
        self.assertEqual(report.get("reset"), "truncated")

    def test_crash_between_jot_and_cursor_is_idempotent(self):
        append(self.path, user_text("No, keep the old API alive for one release."))
        append(self.path, *bash("c1", "ruff check .", "All checks passed!"))
        # A real process, killed right after its first jot is written: the
        # state still lists that candidate in the backlog.
        code = (
            "import os, sys; sys.path.insert(0, sys.argv[1]);"
            "from pathlib import Path; from breadcrumbs import inbox, transcript as tr;"
            "real = inbox.write_jot\n"
            "def dying(*a, **k):\n"
            "    real(*a, **k); os._exit(9)\n"
            "inbox.write_jot = dying\n"
            "tr.mine_transcript_into_jots(Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4],"
            " session_id='s1')"
        )
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
                str(REPO_ROOT),
                str(self.mem),
                str(self.root),
                str(self.path),
            ],
            capture_output=True,
        )
        self.assertEqual(proc.returncode, 9)
        self.assertEqual(len(self.titles()), 1)
        report = self.ingest()
        self.assertEqual(len(report["written"]), 1)
        self.assertEqual(len(self.titles()), 2)
        self.assertEqual(self.ingest()["written"], [])
        self.assertEqual(len(self.titles()), 2)
        # (new in WP09) the dead process had saved both candidates to the
        # backlog first; the next firing recognised the written one.
        self.assertEqual((report["skipped"], report.get("backlog")), (1, 0))


class AccountingTests(RecoveryCase):
    def test_the_per_firing_cap_defers_instead_of_dropping(self):
        append(self.path, *[user_text(f"No, not approach {i}.") for i in range(4)])
        with mock.patch.object(tr, "MINER_MAX_JOTS_PER_FIRING", 2):
            first = self.ingest()
            second = self.ingest()
        self.assertEqual((len(first["written"]), first["backlog"]), (2, 2))
        self.assertEqual((len(second["written"]), second["backlog"]), (2, 0))
        self.assertEqual(len(self.titles()), 4)

    def test_doctor_reports_the_backlog(self):
        append(self.path, *[user_text(f"No, not approach {i}.") for i in range(3)])
        with mock.patch.object(tr, "MINER_MAX_JOTS_PER_FIRING", 1):
            self.ingest()
        row = next(c for c in crumb.doctor_report(self.root)["checks"] if c["check"] == "miner")
        self.assertIn("2 candidate(s) waiting to be written", row["detail"])

    def test_rule_caps_are_counted(self):
        append(self.path, *[user_text(f"No, not approach {i}.") for i in range(8)])
        report = self.ingest()
        self.assertEqual(len(report["written"]), tr.MAX_CORRECTIONS)
        self.assertEqual(report["policy_capped"], 8 - tr.MAX_CORRECTIONS)
        stats = hc.load_miner_state(self.mem, "s1")["stats"]
        self.assertEqual(stats["policy_capped"], 3)

    def test_lock_contention_consumes_nothing(self):
        append(self.path, user_text("No, keep the feature flag on."))
        with held_by_another_process(self.mem):
            report = self.ingest()
        self.assertTrue(report["locked"])
        self.assertEqual(hc.miner_cursor(self.mem, "s1"), 0)
        self.assertEqual(len(self.ingest()["written"]), 1)

    def test_a_failed_write_keeps_the_candidate(self):
        append(self.path, user_text("No, keep the feature flag on."))
        with mock.patch.object(ibx, "write_jot", side_effect=OSError("disk full")):
            report = self.ingest()
        self.assertEqual((report["written"], report["backlog"]), ([], 1))
        self.assertEqual(len(self.ingest()["written"]), 1)
        # A candidate that can never be written is dropped after a bounded
        # number of tries, and counted.
        append(self.path, user_text("No, not like that either."))
        with mock.patch.object(ibx, "write_jot", side_effect=OSError("disk full")):
            reports = [self.ingest() for _ in range(tr.MAX_BACKLOG_ATTEMPTS)]
        self.assertEqual(reports[-1]["dropped_backlog"], 1)
        self.assertEqual(reports[-1]["backlog"], 0)

    def test_an_oversize_line_is_skipped_and_counted(self):
        append(self.path, padded("filler", 50_000), user_text("No, pin the dependency."))
        report = tr.ingest(self.mem, self.root, str(self.path), session_id="s1", max_bytes=20_000)
        self.assertEqual(report["oversize_lines"], 1)
        report = tr.ingest(self.mem, self.root, str(self.path), session_id="s1", max_bytes=20_000)
        self.assertEqual(len(report["written"]), 1)

    def test_a_forked_session_does_not_duplicate_its_parent(self):
        append(
            self.path, user_text("No, keep the old API alive."), *bash("c1", "ruff check .", "ok")
        )
        self.assertEqual(len(self.ingest()["written"]), 2)
        fork = self.root / "fork.jsonl"
        shutil.copy(self.path, fork)
        with fork.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(user_text("Don't bump the major version.")) + "\n")
        report = tr.mine_transcript_into_jots(self.mem, self.root, str(fork), session_id="fork")
        self.assertEqual(len(report["written"]), 1)
        self.assertEqual(len(self.titles()), 3)

    def test_jots_from_before_the_upgrade_are_not_offered_again(self):
        # Written by the old miner (title fingerprint), then the new one reads
        # the session again from byte 0.
        append(
            self.path, user_text("No, keep the old API alive."), *bash("c1", "ruff check .", "ok")
        )
        old = [
            tr.Candidate(kind="correction", title="No, keep the old API alive.", note="x"),
            tr.Candidate(kind="verification", title="ruff check . passed", note="x"),
        ]
        for c in old:
            ibx.write_jot(
                self.mem,
                self.root,
                c.note,
                local=True,
                source="transcript",
                host_session="s1",
                fingerprint=c.fingerprint,  # no key: the old formula
                title=c.title,
            )
        self.assertEqual(self.ingest()["written"], [])
        self.assertEqual(len(self.titles()), 2)

    def test_carried_state_holds_no_secret(self):
        token = "AKIAIOSFODNN7EXAMPLE"
        append(
            self.path,
            tool_use("c1", "Bash", {"command": f"deploy --key {token}"}),
            tool_use("c2", "Bash", {"command": "make build"}),
            tool_result("c2", f"error: rejected key {token}", True),
        )
        self.ingest()
        state = hc.miner_state_path(self.mem, "s1").read_text(encoding="utf-8")
        self.assertNotIn(token, state)
        self.assertIn("make build", state)


if __name__ == "__main__":
    unittest.main()
