"""Multi-record mutations are all-or-nothing and recoverable (audit F20, WP06).

`remember --supersedes` wrote the new decision, then tried to retire the old one
and ignored the result: a failed retirement left two live decisions and exit 0.
Consolidation, promotion, rollup and automatic demotion had the same shape.
These pin the replacement:

- a failed step rolls the whole change back and the writer says so;
- a writer killed after any write leaves a journal that `crumb recover` rolls
  back exactly, or else the change had already committed completely;
- a rewrite refuses when the file changed since it was read;
- retrying after any of this yields one successor, never two.

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
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli, inbox, lifecycle, mcp_core, mutations, promote  # noqa: E402

FAILED_RETIREMENT = {"ok": False, "error": "synthetic retirement failure"}


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


# Runs a crumb command in a child that dies (no cleanup at all) right after its
# k-th file write.
_CRASH_AFTER = """
import os, sys
sys.path.insert(0, sys.argv[1])
from breadcrumbs import cli
limit, count = int(sys.argv[2]), [0]

def counted(real):
    def wrapper(*args, **kwargs):
        result = real(*args, **kwargs)
        count[0] += 1
        if count[0] == limit:
            os._exit(99)
        return result
    return wrapper

cli.write_text_atomic = counted(cli.write_text_atomic)
cli.rewrite_managed_block = counted(cli.rewrite_managed_block)
sys.exit(cli.main(sys.argv[3:]))
"""


class MutationCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def decision(self, title: str = "Route amber traffic through the queue") -> str:
        _path, meta = crumb.write_record(
            self.mem,
            self.root,
            "decision",
            title,
            {"Decision": f"{title}, always."},
            evidence=[{"type": "file", "ref": "src/queue.py"}],
        )
        return meta["id"]

    def live(self, rtype: str = "decision") -> list[str]:
        return sorted(
            r.meta["id"]
            for r in crumb.load_records(self.mem, types=(rtype,))
            if (r.meta.get("status") or "active") == "active"
        )

    def canonical(self) -> dict[str, bytes]:
        """Every file the store's operations may change, derived state excluded."""
        skip = {"generated", "index", "private"}
        out = {}
        for p in self.root.rglob("*"):
            rel = p.relative_to(self.root)
            if not p.is_file() or rel.parts[0] == ".git":
                continue
            if rel.parts[0] == crumb.MEMORY_DIRNAME and len(rel.parts) > 1 and rel.parts[1] in skip:
                continue
            out[rel.as_posix()] = p.read_bytes()
        return out

    def assert_clean(self):
        self.assertEqual(mutations.pending_operations(self.mem), [])
        fails = [f for f in crumb.run_validate(self.mem) if f["status"] == "fail"]
        self.assertEqual(fails, [])


class TruthfulFailureTests(MutationCase):
    def test_failed_retirement_is_not_success_with_two_live_decisions(self):
        old = self.decision()
        before = self.canonical()
        with mock.patch.object(cli, "set_record_status", return_value=FAILED_RETIREMENT):
            code, _out, err = run(
                [
                    "remember", "decision", "--project", str(self.root),
                    "--title", "Replace the amber queue policy",
                    "--set", "Decision", "Route amber traffic through the new queue.",
                    "--evidence", "file", "src/queue.py", "--supersedes", old,
                ]
            )  # fmt: skip
        self.assertEqual(code, 1)
        self.assertIn("synthetic retirement failure", err)
        self.assertIn("nothing was changed", err)
        self.assertEqual(self.live(), [old])
        self.assertEqual(self.canonical(), before)
        self.assert_clean()

    def test_every_replacing_writer_rolls_back(self):
        writers = {
            "mcp record": lambda old: mcp_core.tool_record(
                "decision",
                {
                    "title": "Replace the amber queue policy",
                    "sections": {"Decision": "Route amber traffic elsewhere."},
                    "evidence": [{"type": "file", "ref": "src/queue.py"}],
                    "supersedes": old,
                },
                root=self.root,
            ),
            "consolidate": lambda old: lifecycle.merge_records(
                self.mem,
                self.root,
                [old, self.decision("Route amber traffic twice")],
                title="Merged",
            ),
            "inbox promote": lambda old: inbox.promote_jot(
                self.mem,
                self.root,
                inbox.write_jot(self.mem, self.root, "use the amber queue for retries")["id"],
                "decision",
                supersedes=old,
            ),
        }
        for name, write in writers.items():
            with self.subTest(writer=name):
                old = self.decision(f"Route amber traffic via {name}")
                live_before = self.live()
                with mock.patch.object(cli, "set_record_status", return_value=FAILED_RETIREMENT):
                    res = write(old)
                self.assertFalse(res["ok"], res)
                self.assertIn("synthetic retirement failure", res["error"])
                # Anything the writer created before failing is gone again
                # (consolidate's second source was made by the test itself).
                self.assertLessEqual(set(self.live()) - set(live_before), {self._second(name)})
                self.assertIn(old, self.live())
                self.assertEqual(mutations.pending_operations(self.mem), [])

    def _second(self, name: str) -> str:
        return next((i for i in self.live() if "twice" in i and name == "consolidate"), "__none__")

    def test_a_failed_jot_retirement_undoes_the_promotion(self):
        jot = inbox.write_jot(self.mem, self.root, "prefer the amber queue for retries")["id"]
        real = cli.set_record_status

        def fail_for_the_jot(memory_dir, rid, *args, **kwargs):
            if rid == jot:
                return FAILED_RETIREMENT
            return real(memory_dir, rid, *args, **kwargs)

        with mock.patch.object(cli, "set_record_status", side_effect=fail_for_the_jot):
            res = inbox.promote_jot(self.mem, self.root, jot, "decision")
        self.assertFalse(res["ok"])
        self.assertEqual(self.live(), [])
        self.assertEqual(inbox.find_jot(self.mem, jot).meta["status"], "active")

    def test_demotion_failure_rolls_back_the_retirement(self):
        rid = self.decision()
        (self.root / "CLAUDE.md").write_text("# Guide\n")
        self.assertTrue(promote.promote(self.mem, self.root, rid, to="CLAUDE.md")["ok"])
        before = self.canonical()
        refused = {"ok": False, "code": 1, "error": "synthetic demotion failure"}
        with mock.patch.object(promote, "_demote", return_value=refused):
            res = crumb.set_record_status(self.mem, rid, "stale", "no longer true", agent="t")
        self.assertFalse(res["ok"])
        self.assertIn("synthetic demotion failure", res["error"])
        self.assertEqual(self.canonical(), before)  # still active, still promoted
        self.assertIn(rid, (self.root / "CLAUDE.md").read_text())

    def test_a_failed_projection_rebuild_is_visible(self):
        self.decision()
        with mock.patch("breadcrumbs.searchindex.build_index", side_effect=OSError("disk full")):
            ok, reason = cli.try_reindex_projections(self.mem, self.root)
        self.assertFalse(ok)
        checks = {c["check"]: c for c in cli.doctor_report(self.root)["checks"]}
        self.assertFalse(checks["projections"]["ok"])
        self.assertIn("disk full", checks["projections"]["detail"])
        self.assertTrue(cli.try_reindex_projections(self.mem, self.root)[0])
        checks = {c["check"]: c for c in cli.doctor_report(self.root)["checks"]}
        self.assertTrue(checks["projections"]["ok"])


class WindowsLineSeparatorTests(TruthfulFailureTests):
    """The same failures with Windows' line separator (audit WP17).

    Writers put "\r\n" on disk there, and the journal recorded the text before
    translation, so rollback took every file it had written for someone else's
    edit and left it: two live decisions again, on Windows only.
    """

    def setUp(self):
        patcher = mock.patch.object(os, "linesep", "\r\n")
        patcher.start()
        self.addCleanup(patcher.stop)
        super().setUp()


class RevisionTests(MutationCase):
    def test_expected_revision_prevents_lost_update(self):
        rid = self.decision()
        path = crumb.find_record_by_id(self.mem, rid).path
        real_render = cli.render_frontmatter

        def render_after_a_hand_edit(meta):
            # Another editor saves between this writer's read and its write.
            if "## Hand edit" not in path.read_text():
                path.write_text(path.read_text() + "\n## Hand edit\nKeep this.\n")
            return real_render(meta)

        with mock.patch.object(cli, "render_frontmatter", side_effect=render_after_a_hand_edit):
            res = crumb.set_record_status(self.mem, rid, "stale", "outdated", agent="t")
        self.assertFalse(res["ok"])
        self.assertIn("changed since it was read", res["error"])
        text = path.read_text()
        self.assertIn("Keep this.", text)  # the other edit survived
        self.assertIn("status: active", text)


class CrashRecoveryTests(MutationCase):
    def _crash_after(self, k: int, argv: list[str]) -> int:
        return subprocess.run(
            [sys.executable, "-c", _CRASH_AFTER, str(REPO_ROOT), str(k), *argv],
            capture_output=True,
            text=True,
        ).returncode

    def test_failure_after_each_participant_is_recoverable(self):
        # A replacement of a *promoted* decision: new record, old record's
        # retirement, the rule's removal from CLAUDE.md, the old record's
        # promotion fields, and projections.
        (self.root / "CLAUDE.md").write_text("# Guide\n")
        old = self.decision()
        self.assertTrue(promote.promote(self.mem, self.root, old, to="CLAUDE.md")["ok"])
        argv = [
            "remember", "decision", "--project", str(self.root),
            "--title", "Replace the amber queue policy",
            "--set", "Decision", "Route amber traffic through the new queue.",
            "--evidence", "file", "src/queue.py", "--supersedes", old,
        ]  # fmt: skip
        initial = self.canonical()
        crashes = 0
        for k in range(1, 60):
            code = self._crash_after(k, argv)
            if code != 99:
                self.assertEqual(code, 0)
                break  # the whole operation ran without reaching write k
            crashes += 1
            pending = mutations.pending_operations(self.mem)
            if pending:
                res = mutations.recover(self.mem, apply=True)
                self.assertTrue(all(op["rolled_back"] for op in res["operations"]), res)
                self.assertEqual(self.canonical(), initial, f"crash after write {k}")
            else:
                # Past the commit: the change is complete, only derived views lag.
                self.assertEqual(len(self.live()), 1, f"crash after write {k}")
                self.assertIn(old, self._superseded())
                cli.try_reindex_projections(self.mem, self.root)
                self._reset(initial)
            self.assertEqual(mutations.pending_operations(self.mem), [])
        self.assertGreater(crashes, 3, "the crash loop never interrupted anything")
        # The last, uninterrupted run is the one outcome: one live successor.
        live = self.live()
        self.assertEqual(len(live), 1)
        self.assertNotEqual(live, [old])
        self.assertNotIn(old, (self.root / "CLAUDE.md").read_text())
        self.assert_clean()

    def _superseded(self) -> list[str]:
        return [
            r.meta["id"]
            for r in crumb.load_records(self.mem, types=("decision",))
            if r.meta.get("status") == "superseded"
        ]

    def _reset(self, initial: dict[str, bytes]) -> None:
        """Put the committed crash case back, to try the next write number."""
        for rel in set(self.canonical()) - set(initial):
            (self.root / rel).unlink()
        for rel, data in initial.items():
            (self.root / rel).write_bytes(data)
        cli.try_reindex_projections(self.mem, self.root)

    def test_recover_leaves_a_later_edit_alone(self):
        old = self.decision()
        argv = ["mark-status", old, "stale", "--reason", "outdated", "--project", str(self.root)]
        self.assertEqual(self._crash_after(1, argv), 99)
        path = crumb.find_record_by_id(self.mem, old).path
        path.write_text(path.read_text() + "\nA person edited this afterwards.\n")
        res = mutations.recover(self.mem, apply=True)
        self.assertEqual(
            res["operations"][0]["conflicts"], [path.relative_to(self.root).as_posix()]
        )
        self.assertIn("A person edited this afterwards.", path.read_text())
        self.assertEqual(len(mutations.pending_operations(self.mem)), 1, "journal kept")
        code, out, _err = run(["recover", "--project", str(self.root), "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["summary"]["unresolved"], 1)

    def test_a_rolled_back_new_record_is_kept_not_erased(self):
        old = self.decision()
        argv = [
            "remember", "decision", "--project", str(self.root),
            "--title", "Replace the amber queue policy",
            "--set", "Decision", "A carefully worded replacement.",
            "--evidence", "file", "src/queue.py", "--supersedes", old,
        ]  # fmt: skip
        self.assertEqual(self._crash_after(1, argv), 99)  # the new record, then death
        res = mutations.recover(self.mem, apply=True)
        kept = res["operations"][0]["kept"]
        self.assertEqual(len(kept), 1)
        self.assertIn("A carefully worded replacement.", Path(kept[0]).read_text())
        self.assertEqual(self.live(), [old])


class RetryTests(MutationCase):
    def test_retry_does_not_duplicate_or_orphan_records(self):
        old = self.decision()
        argv = [
            "remember", "decision", "--project", str(self.root),
            "--title", "Replace the amber queue policy",
            "--set", "Decision", "Route amber traffic through the new queue.",
            "--evidence", "file", "src/queue.py", "--supersedes", old,
        ]  # fmt: skip
        with mock.patch.object(cli, "set_record_status", return_value=FAILED_RETIREMENT):
            self.assertEqual(run(argv)[0], 1)
        self.assertEqual(run(argv)[0], 0)
        records = crumb.load_records(self.mem, types=("decision",))
        self.assertEqual(len(records), 2)
        new = next(r for r in records if r.meta["id"] != old)
        self.assertEqual(new.meta["status"], "active")
        self.assertEqual(
            crumb.find_record_by_id(self.mem, old).meta["superseded_by"], new.meta["id"]
        )
        # Recovery with nothing to do is a no-op, however often it runs.
        for _ in range(2):
            self.assertEqual(mutations.recover(self.mem, apply=True)["operations"], [])
        self.assert_clean()


if __name__ == "__main__":
    unittest.main()
