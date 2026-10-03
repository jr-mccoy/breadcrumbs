"""Decision staleness keyed on evidence, not elapsed time (health review 1.1).

17 of this store's 21 audit warnings were "active decision … is N days old with
no update — is this still true?", and the same lines filled the resume packet.
Audit now questions a decision when its evidence moved: a cited file rewritten
(WARN), changed (one INFO line), gone or contradicted (the lifecycle findings),
and only far past the age cutoff when nothing else says anything (INFO). The
packet carries no age line for a decision. evals/critical/cases.yml holds the
end-to-end cases (suite `staleness`); these pin the rules one at a time.

Run with:  python -m unittest discover -s tests -p test_decision_staleness.py
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import audit as _audit  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import packet as _packet  # noqa: E402

AS_OF = "2026-02-05"
STALENESS = {
    "decision-evidence-rewritten",
    "decision-evidence-changed",
    "decision-aged",
    "possible-contradiction",
    "near-duplicates",
    "evidence-missing-file",
}


def clock(date: str) -> datetime:
    return datetime.strptime(date, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)


class Project:
    """A git repository with a store, driven day by day."""

    def __init__(self, base: Path, sub: str = ""):
        self.repo = base / "repo"
        self.root = self.repo / sub if sub else self.repo
        self.root.mkdir(parents=True)
        self.git("2026-01-01", "init", "-q", "-b", "main")
        self.git("2026-01-01", "config", "user.email", "t@t")
        self.git("2026-01-01", "config", "user.name", "t")
        self.crumb("2026-01-01", "init", "--session-tracking", "full")
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def git(self, date: str, *args: str) -> str:
        stamp = clock(date).isoformat()
        env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
        return subprocess.run(
            ["git", *args], cwd=self.repo, env=env, check=True, capture_output=True, text=True
        ).stdout

    def crumb(self, date: str, *argv: str) -> str:
        out = io.StringIO()
        with mock.patch.object(_cli, "_now", return_value=clock(date)):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                code = crumb.main([*argv, "--project", str(self.root)])
        assert code == 0, out.getvalue()
        return out.getvalue()

    def lines(self, path: str, n: int, tag: str = "v1") -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("".join(f"line {i} {tag}\n" for i in range(1, n + 1)), encoding="utf-8")

    def commit(self, date: str, message: str = "work") -> None:
        self.git(date, "add", "-A")
        self.git(date, "commit", "-q", "-m", message)

    def decide(self, date: str, title: str, *evidence: str) -> str:
        args = ["remember", "decision", "--title", title, "--set", "Decision", title]
        for ref in evidence:
            args += ["--evidence", "file", ref]
        if not evidence:
            args += ["--evidence", "commit", "0000000"]
        self.crumb(date, *args, "--allow-duplicate")
        return next(
            r.meta["id"] for r in _cli.active_decisions(self.mem) if r.meta.get("title") == title
        )

    def audit(self, as_of: str = AS_OF) -> list[dict]:
        with mock.patch.object(_cli, "_now", return_value=clock(as_of)):
            return _audit.run_audit(self.mem, self.root)

    def questioned(self, as_of: str = AS_OF) -> dict[str, set[str]]:
        named: dict[str, set[str]] = {}
        for f in self.audit(as_of):
            if f["check"] in STALENESS:
                for rid in [f.get("id"), *(f.get("ids") or ())]:
                    if rid:
                        named.setdefault(rid, set()).add(f["check"])
        return named

    def packet_warnings(self, as_of: str = AS_OF) -> list[str]:
        with mock.patch.object(_cli, "_now", return_value=clock(as_of)):
            return _packet.build_resume_packet(self.mem, self.root)["warnings"]


class DecisionStalenessTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.p = Project(Path(self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_age_alone_is_neither_a_warning_nor_a_packet_line(self):
        # 66 days: past the 21-day cutoff, far from the decision-aged bar.
        self.p.lines("docs/logging.md", 20)
        self.p.commit("2025-12-01")
        rid = self.p.decide("2025-12-01", "Application logs are JSON lines", "docs/logging.md")
        self.p.commit("2025-12-01")
        self.assertNotIn(rid, self.p.questioned())
        self.assertFalse([w for w in self.p.packet_warnings() if rid in w])

    def test_a_rewritten_evidence_file_warns_however_young_the_decision(self):
        self.p.lines("src/payments.py", 40)
        self.p.commit("2026-02-01")
        rid = self.p.decide("2026-02-01", "Payments round half-even", "src/payments.py")
        self.p.lines("src/payments.py", 40, "v2")
        self.p.commit("2026-02-03", "rework payments")
        findings = [f for f in self.p.audit() if f.get("id") == rid]
        self.assertEqual([f["check"] for f in findings], ["decision-evidence-rewritten"])
        self.assertEqual(findings[0]["severity"], _audit.AUDIT_WARN)
        self.assertIn("src/payments.py", findings[0]["message"])

    def test_a_small_change_is_one_note_not_a_warning(self):
        self.p.lines("src/rates.toml", 30)
        self.p.commit("2026-01-05")
        rid = self.p.decide("2026-01-06", "Rates load once at startup", "src/rates.toml")
        with (self.p.root / "src/rates.toml").open("a", encoding="utf-8") as fh:
            fh.write("timeout = 5\n")
        self.p.commit("2026-01-20")
        self.assertEqual(self.p.questioned().get(rid), {"decision-evidence-changed"})
        (note,) = [f for f in self.p.audit() if f["check"] == "decision-evidence-changed"]
        self.assertEqual(note["severity"], _audit.AUDIT_INFO)

    def test_the_decisions_own_landing_does_not_count(self):
        # Written while the file was uncommitted, then committed: the commit
        # that follows lands the decision, it does not change it.
        self.p.lines("src/cache.py", 30)
        dirty = self.p.decide("2026-01-10", "Cache entries expire after an hour", "src/cache.py")
        self.p.commit("2026-01-10", "add the cache")
        # A tracked file edited before the decision and committed after it.
        self.p.lines("src/queue.py", 30)
        self.p.commit("2026-01-11")
        self.p.lines("src/queue.py", 30, "v2")
        edited = self.p.decide("2026-01-12", "The queue is FIFO", "src/queue.py")
        self.p.commit("2026-01-12", "rework the queue")
        named = self.p.questioned()
        self.assertNotIn(dirty, named)
        self.assertNotIn(edited, named)

    def test_a_vanished_file_is_reported_once_as_missing(self):
        self.p.lines("src/legacy.py", 20)
        self.p.commit("2026-01-05")
        rid = self.p.decide("2026-01-06", "The legacy export keeps its module", "src/legacy.py")
        (self.p.root / "src/legacy.py").unlink()
        self.p.commit("2026-01-20")
        self.assertEqual(self.p.questioned().get(rid), {"evidence-missing-file"})

    def test_a_very_old_unquestioned_decision_is_noted_once(self):
        rid = self.p.decide("2025-05-01", "All timestamps are UTC")
        self.p.commit("2025-05-01")
        aged = [f for f in self.p.audit() if f.get("id") == rid]
        self.assertEqual([f["check"] for f in aged], ["decision-aged"])
        self.assertEqual(aged[0]["severity"], _audit.AUDIT_INFO)
        self.assertFalse([w for w in self.p.packet_warnings() if rid in w])

    def test_a_decision_already_questioned_is_not_also_aged(self):
        self.p.lines("src/old.py", 40)
        self.p.commit("2025-05-01")
        rid = self.p.decide("2025-05-01", "Old module owns parsing", "src/old.py")
        self.p.lines("src/old.py", 40, "v2")
        self.p.commit("2026-01-20")
        self.assertEqual(self.p.questioned().get(rid), {"decision-evidence-rewritten"})

    def test_a_commit_this_clone_lacks_falls_back_to_time(self):
        self.p.lines("src/payments.py", 40)
        self.p.commit("2026-01-05")
        rid = self.p.decide("2026-01-06", "Payments round half-even", "src/payments.py")
        rec = _cli.find_record_by_id(self.p.mem, rid)
        text = rec.path.read_text(encoding="utf-8")
        rec.path.write_text(
            text.replace(f"commit: {rec.meta['commit']}", "commit: 1234567"), encoding="utf-8"
        )
        self.p.lines("src/payments.py", 40, "v2")
        self.p.commit("2026-01-20")
        self.assertEqual(self.p.questioned().get(rid), {"decision-evidence-rewritten"})

    def test_a_hub_file_does_not_count(self):
        # A file nearly every commit touches says nothing about one decision.
        self.p.lines("src/main.py", 40)
        self.p.lines("CHANGELOG.md", 5)
        self.p.commit("2026-01-01")
        rid = self.p.decide("2026-01-02", "main.py wires the app", "CHANGELOG.md")
        for i in range(_audit.AUDIT_EVIDENCE_HUB_MIN_COMMITS + 5):
            self.p.lines("CHANGELOG.md", 5, f"r{i}")
            self.p.commit("2026-01-03", f"release {i}")
        self.assertNotIn(rid, self.p.questioned())


class SubdirectoryProjectTests(unittest.TestCase):
    def test_a_project_below_the_repository_root_reads_its_own_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Project(Path(tmp), sub="app")
            p.lines("src/payments.py", 40)
            p.commit("2026-01-05")
            rid = p.decide("2026-01-06", "Payments round half-even", "src/payments.py")
            p.lines("src/payments.py", 40, "v2")
            p.commit("2026-01-20")
            self.assertEqual(p.questioned().get(rid), {"decision-evidence-rewritten"})


class NoGitTests(unittest.TestCase):
    def test_without_git_only_the_age_rule_applies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("x\n", encoding="utf-8")
            with mock.patch.object(_cli, "_now", return_value=clock("2025-05-01")):
                with contextlib.redirect_stdout(io.StringIO()):
                    crumb.main(["init", "--project", str(root)])
                    crumb.main(
                        [
                            "remember",
                            "decision",
                            "--project",
                            str(root),
                            "--title",
                            "A uses x",
                            "--set",
                            "Decision",
                            "x",
                            "--evidence",
                            "file",
                            "src/a.py",
                        ]
                    )
            mem = root / crumb.MEMORY_DIRNAME
            with mock.patch.object(_cli, "_now", return_value=clock(AS_OF)):
                checks = [f["check"] for f in _audit.run_audit(mem, root)]
            self.assertIn("decision-aged", checks)
            self.assertNotIn("decision-evidence-rewritten", checks)


if __name__ == "__main__":
    unittest.main()
