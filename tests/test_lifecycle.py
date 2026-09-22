"""Tests for record lifecycle (Phase 3: WM-30 to WM-35).

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import lifecycle  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def run_err(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


def init_store(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


@contextlib.contextmanager
def days_later(days: int):
    """Move the one clock seam forward by `days`."""
    later = _cli._now() + timedelta(days=days)
    with mock.patch.object(_cli, "_now", return_value=later):
        yield later


def set_manifest(mem: Path, key: str, value: str) -> None:
    path = mem / "manifest.yml"
    path.write_text(path.read_text("utf-8") + f"{key}: {value}\n", encoding="utf-8")


def set_frontmatter(path: Path, key: str, value: str) -> None:
    meta, body = crumb.parse_frontmatter(path.read_text("utf-8"))
    meta[key] = value
    path.write_text(crumb.render_frontmatter(meta) + "\n" + body, encoding="utf-8")


def remember(tmp: str, title: str, *, file: str = "src/ledger.py", body: str | None = None) -> str:
    code, out = run(
        [
            "remember",
            "decision",
            "--project",
            tmp,
            "--title",
            title,
            "--set",
            "Decision",
            body or f"{title}.",
            "--evidence",
            "file",
            file,
            "--allow-duplicate",
            "--json",
        ]
    )
    assert code == 0, out
    return json.loads(out)["id"]


# --------------------------------------------------------------------------- #
# WM-30 typed time-to-live
# --------------------------------------------------------------------------- #


class TtlTests(unittest.TestCase):
    def test_a_settled_verification_expires_and_an_actionable_one_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            fixed = crumb.verify(mem, Path(tmp), "cache eviction works", status="fixed")
            opened = crumb.verify(mem, Path(tmp), "cache eviction leaks", status="regressed")
            self.assertIsNotNone(fixed["expires_at"])
            self.assertIsNone(opened["expires_at"])
            created = _cli._parse_iso(crumb.find_record_by_id(mem, fixed["id"]).meta["created_at"])
            expires = _cli._parse_iso(fixed["expires_at"])
            self.assertEqual((expires - created).days, lifecycle.TTL_DEFAULTS["verification"])

    def test_manifest_overrides_the_lifespan(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_manifest(mem, "ttl_verification_days", "10")
            set_manifest(mem, "ttl_question_days", "not-a-number")
            self.assertEqual(lifecycle.ttl_days(mem, "verification"), 10)
            self.assertEqual(lifecycle.ttl_days(mem, "question"), 45)
            fixed = crumb.verify(mem, Path(tmp), "cache eviction works", status="fixed")
            created = _cli._parse_iso(crumb.find_record_by_id(mem, fixed["id"]).meta["created_at"])
            self.assertEqual((_cli._parse_iso(fixed["expires_at"]) - created).days, 10)

    def test_the_jot_ttl_keeps_its_old_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_manifest(mem, "ttl_jot_days", "3")
            self.assertEqual(lifecycle.ttl_days(mem, "jot"), 3)

    def test_an_expired_verification_leaves_the_packet_and_is_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            vid = crumb.verify(mem, Path(tmp), "cache eviction works", status="fixed")["id"]
            listed = [v["id"] for v in crumb.build_resume_packet(mem, Path(tmp))["verifications"]]
            self.assertIn(vid, listed)
            with days_later(91):
                packet = crumb.build_resume_packet(mem, Path(tmp))
                self.assertNotIn(vid, [v["id"] for v in packet["verifications"]])
                self.assertEqual([r["id"] for r in lifecycle.expired_items(mem)], [vid])
                code, out = run(["expired", "--project", tmp, "--json"])
                self.assertEqual(code, 0)
                self.assertEqual([r["id"] for r in json.loads(out)["items"]], [vid])
            # Never deleted.
            self.assertIsNotNone(crumb.find_record_by_id(mem, vid))

    def test_an_expired_record_goes_to_guard_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = remember(tmp, "ledger rows are append only", file="src/ledger.py")
            path = crumb.find_record_by_id(mem, rid).path
            set_frontmatter(path, "expires_at", (_cli._now() + timedelta(days=5)).isoformat())
            action = "rewrite src/ledger.py to update rows in place"
            live = crumb.guard(mem, Path(tmp), action, files=["src/ledger.py"])
            self.assertIn(rid, [m["id"] for m in live["matches"]])
            with days_later(6):
                later = crumb.guard(mem, Path(tmp), action, files=["src/ledger.py"])
                self.assertNotIn(rid, [m["id"] for m in later["matches"]])
                self.assertIn(rid, [m["id"] for m in later["history"]])
                packet = crumb.build_resume_packet(mem, Path(tmp))
                self.assertNotIn(rid, [d["id"] for d in packet["active_decisions"]])
                self.assertTrue(any(f"{rid} expired on" in w for w in packet["warnings"]))

    def test_an_old_actionable_verification_asks_for_a_recheck(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            vid = crumb.verify(mem, Path(tmp), "cache eviction leaks", status="open")["id"]
            with days_later(89):
                warnings = crumb.build_resume_packet(mem, Path(tmp))["warnings"]
                self.assertFalse(any("recheck" in w for w in warnings))
            with days_later(91):
                packet = crumb.build_resume_packet(mem, Path(tmp))
                self.assertTrue(any(f"verification {vid}" in w for w in packet["warnings"]))
                # …and it is still listed: an open problem does not expire.
                self.assertIn(vid, [v["id"] for v in packet["verifications"]])

    def test_an_unconfirmed_trap_asks_for_a_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tid = crumb.note(mem, Path(tmp), "trap", "the daemon holds a lock")["id"]
            with days_later(181):
                warnings = crumb.build_resume_packet(mem, Path(tmp))["warnings"]
                self.assertTrue(any(f"trap {tid}" in w for w in warnings), warnings)
                _cli.set_trap_confirmed(mem, tid)
                warnings = crumb.build_resume_packet(mem, Path(tmp))["warnings"]
                self.assertFalse(any(f"trap {tid}" in w for w in warnings), warnings)

    def test_a_current_md_nobody_touched_asks_about_the_focus(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            warnings = crumb.build_resume_packet(mem, Path(tmp))["warnings"]
            self.assertFalse(any("current.md has not changed" in w for w in warnings))
            with days_later(15):
                warnings = crumb.build_resume_packet(mem, Path(tmp))["warnings"]
                self.assertTrue(any("current.md has not changed" in w for w in warnings))

    def test_questions_aging(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            crumb.note(mem, Path(tmp), "question", "Should we shard the ledger?")
            code, out = run(["questions", "--aging", "--project", tmp, "--json"])
            self.assertEqual(json.loads(out)["items"], [])
            with days_later(46):
                code, out = run(["questions", "--aging", "--project", tmp, "--json"])
                self.assertEqual(code, 0)
                items = json.loads(out)["items"]
                self.assertEqual(len(items), 1)
                self.assertTrue(items[0]["aging"])

    def test_decisions_never_expire_on_their_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            rid = remember(tmp, "ledger rows are append only")
            self.assertIsNone(crumb.find_record_by_id(mem, rid).meta.get("expires_at"))
            with days_later(3650):
                ids = [
                    d["id"] for d in crumb.build_resume_packet(mem, Path(tmp))["active_decisions"]
                ]
                self.assertIn(rid, ids)


# --------------------------------------------------------------------------- #
# WM-31 evidence-driven staleness
# --------------------------------------------------------------------------- #


class EvidenceStalenessTests(unittest.TestCase):
    def test_a_record_citing_a_deleted_file_warns(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            (Path(tmp) / "src").mkdir()
            (Path(tmp) / "src" / "ledger.py").write_text("x = 1\n")
            rid = remember(tmp, "ledger rows are append only", file="src/ledger.py:12")
            packet = crumb.build_resume_packet(mem, Path(tmp))
            self.assertFalse(any("cites" in w for w in packet["warnings"]))
            (Path(tmp) / "src" / "ledger.py").unlink()
            packet = crumb.build_resume_packet(mem, Path(tmp))
            self.assertTrue(any(f"{rid} cites src/ledger.py:12" in w for w in packet["warnings"]))
            findings = [
                f for f in crumb.run_audit(mem, Path(tmp)) if f["check"] == "evidence-missing-file"
            ]
            self.assertEqual([f["id"] for f in findings], [rid])

    def test_urls_globs_and_absolute_paths_are_not_checked(self):
        for ref in ("https://example.com/x", "src/*.py", "/etc/hosts", "~/notes.md"):
            with self.subTest(ref=ref):
                self.assertIsNone(lifecycle._evidence_path(ref))
        self.assertEqual(lifecycle._evidence_path("src/x.py:12-20"), "src/x.py")

    def test_the_packet_caps_the_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for i in range(8):
                remember(tmp, f"topic {i} gone file {i}", file=f"gone/file{i}.py")
            warnings = crumb.build_resume_packet(mem, Path(tmp))["warnings"]
            cites = [w for w in warnings if " cites " in w]
            self.assertEqual(len(cites), lifecycle.EVIDENCE_MISSING_MAX)
            self.assertTrue(any("(+3 more" in w for w in warnings))


class RecheckTests(unittest.TestCase):
    def _verified(self, tmp: str, command: str) -> tuple[Path, str]:
        mem = init_store(tmp)
        vid = crumb.verify(
            mem,
            Path(tmp),
            "the suite passes",
            status="fixed",
            evidence=[{"type": "command", "ref": command}],
        )["id"]
        return mem, vid

    def test_a_passing_command_records_fixed_and_supersedes(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, vid = self._verified(tmp, "true")
            code, out = run(["verify", "--recheck", vid, "--yes", "--project", tmp, "--json"])
            self.assertEqual(code, 0, out)
            res = json.loads(out)["items"][0]
            self.assertEqual(res["outcome"], "fixed")
            new = crumb.find_record_by_id(mem, res["new_id"])
            self.assertEqual(new.meta["method"], "runtime")
            self.assertEqual(new.meta["supersedes"], [vid])
            old = crumb.find_record_by_id(mem, vid)
            self.assertEqual(old.meta["status"], "superseded")
            self.assertEqual(old.meta["superseded_by"], res["new_id"])

    def test_a_failing_command_records_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, vid = self._verified(tmp, "echo broken >&2; false")
            code, out = run(["verify", "--recheck", vid, "--yes", "--project", tmp, "--json"])
            self.assertEqual(code, 0, out)
            res = json.loads(out)["items"][0]
            self.assertEqual(res["outcome"], "open")
            text = crumb.find_record_by_id(mem, res["new_id"]).path.read_text("utf-8")
            self.assertIn("exit 1", text)
            self.assertIn("broken", text)

    def test_without_yes_and_without_a_terminal_nothing_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / "ran"
            mem, vid = self._verified(tmp, f"touch {sentinel}")
            with mock.patch.object(_cli, "_interactive", return_value=False):
                code, _out, err = run_err(["verify", "--recheck", vid, "--project", tmp])
            self.assertEqual(code, 2)
            self.assertIn("--yes", err)
            self.assertFalse(sentinel.exists())
            self.assertEqual(crumb.find_record_by_id(mem, vid).meta["status"], "active")

    def test_all_takes_every_verification_with_a_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, vid = self._verified(tmp, "true")
            crumb.verify(mem, Path(tmp), "reviewed the diff by eye", status="fixed")
            code, out = run(["verify", "--all", "--yes", "--project", tmp, "--json"])
            self.assertEqual(code, 0, out)
            self.assertEqual([r["id"] for r in json.loads(out)["items"]], [vid])

    def test_a_status_is_still_required_for_a_plain_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, _out, err = run_err(["verify", "something", "--project", tmp])
            self.assertEqual(code, 2)
            self.assertIn("--status", err)


# --------------------------------------------------------------------------- #
# WM-32 near-duplicate detection on write
# --------------------------------------------------------------------------- #

DECISION = [
    "--set",
    "Decision",
    "Store ledger rows append-only in sqlite; compaction rewrites them nightly.",
    "--evidence",
    "file",
    "src/ledger.py",
]


class NearDuplicateTests(unittest.TestCase):
    def _decide(self, tmp: str, title: str, *extra: str) -> tuple[int, str, str]:
        return run_err(
            ["remember", "decision", "--project", tmp, "--title", title, *DECISION, *extra]
        )

    def test_the_same_decision_twice_is_refused_with_exit_3(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out, _ = self._decide(tmp, "Ledger rows are append-only", "--json")
            first = json.loads(out)["id"]
            code, _out, err = self._decide(tmp, "Ledger rows are append only in sqlite")
            self.assertEqual(code, 3)
            self.assertIn(first, err)
            self.assertIn("--supersedes", err)
            self.assertIn("--allow-duplicate", err)

    def test_supersedes_writes_and_retires_the_old_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            _, out, _ = self._decide(tmp, "Ledger rows are append-only", "--json")
            first = json.loads(out)["id"]
            code, out, _ = self._decide(
                tmp, "Ledger rows are append only in sqlite", "--supersedes", first, "--json"
            )
            self.assertEqual(code, 0, out)
            second = json.loads(out)["id"]
            self.assertEqual(crumb.find_record_by_id(mem, second).meta["supersedes"], [first])
            old = crumb.find_record_by_id(mem, first)
            self.assertEqual(
                (old.meta["status"], old.meta["superseded_by"]), ("superseded", second)
            )

    def test_supersedes_must_name_a_live_record_of_the_same_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tid = crumb.note(mem, Path(tmp), "trap", "the daemon holds a lock")["id"]
            code, _out, err = self._decide(tmp, "Something new entirely", "--supersedes", tid)
            self.assertEqual(code, 2)
            self.assertIn("not a decision", err)

    def test_allow_duplicate_writes_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            self._decide(tmp, "Ledger rows are append-only")
            code, _, _ = self._decide(tmp, "Ledger rows are append only", "--allow-duplicate")
            self.assertEqual(code, 0)
            self.assertEqual(len(crumb.active_decisions(mem)), 2)

    def test_different_topics_are_not_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            self._decide(tmp, "Ledger rows are append-only")
            code, _, err = run_err(
                [
                    "remember",
                    "decision",
                    "--project",
                    tmp,
                    "--title",
                    "The logo lives in the design repository",
                    "--set",
                    "Decision",
                    "Assets are exported as SVG from the design repository by the brand team.",
                    "--confidence",
                    "low",
                ]
            )
            self.assertEqual(code, 0, err)

    def test_a_reverified_subject_is_a_duplicate_until_superseded(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            argv = ["verify", "cache eviction under memory pressure", "--project", tmp]
            code, out, _ = run_err([*argv, "--status", "open", "--json"])
            first = json.loads(out)["id"]
            code, _out, err = run_err([*argv, "--status", "fixed"])
            self.assertEqual(code, 3, err)
            code, out, _ = run_err([*argv, "--status", "fixed", "--supersedes", first, "--json"])
            self.assertEqual(code, 0, out)
            self.assertEqual(crumb.find_record_by_id(mem, first).meta["status"], "superseded")

    def test_notes_and_jots_are_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            trap = [
                "--area",
                "src/daemon.py",
                "--why",
                "the daemon keeps the sqlite write lock between polling runs",
            ]
            code, _, _ = run_err(
                ["note", "trap", "daemon holds the sqlite lock", "--project", tmp, *trap]
            )
            self.assertEqual(code, 0)
            code, _, err = run_err(
                ["note", "trap", "the daemon holds a sqlite write lock", "--project", tmp, *trap]
            )
            self.assertEqual(code, 3, err)
            code, _, _ = run_err(["jot", "flaky test_x only fails under -n auto", "--project", tmp])
            self.assertEqual(code, 0)
            code, _, err = run_err(
                ["jot", "flaky test_x only fails under -n auto", "--project", tmp]
            )
            self.assertEqual(code, 3, err)
            self.assertNotIn("--supersedes", err)

    def test_the_mcp_writers_return_a_structured_refusal(self):
        from breadcrumbs import mcp_core

        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            payload = {
                "title": "Ledger rows are append-only",
                "sections": {"Decision": DECISION[2]},
                "evidence": [{"type": "file", "ref": "src/ledger.py"}],
            }
            first = mcp_core.tool_record("decision", payload, root=tmp)
            self.assertTrue(first["ok"], first)
            again = mcp_core.tool_record("decision", payload, root=tmp)
            self.assertFalse(again["ok"])
            self.assertEqual(again["error"], "near-duplicate")
            self.assertEqual(again["duplicates"][0]["id"], first["id"])
            ok = mcp_core.tool_record("decision", {**payload, "supersedes": first["id"]}, root=tmp)
            self.assertTrue(ok["ok"], ok)
            res = mcp_core.tool_jot("one observation about the parser depth", root=tmp)
            self.assertTrue(res["ok"])
            res = mcp_core.tool_jot("one observation about the parser depth", root=tmp)
            self.assertEqual(res["error"], "near-duplicate")

    def test_audit_lists_a_planted_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            self._decide(tmp, "Ledger rows are append-only")
            self._decide(tmp, "Ledger rows are append only", "--allow-duplicate")
            findings = [
                f for f in crumb.run_audit(mem, Path(tmp)) if f["check"] == "near-duplicates"
            ]
            self.assertEqual(len(findings), 1)

    def test_the_fixtures_hold_no_near_duplicates(self):
        for fixture in sorted((REPO_ROOT / "fixtures").glob("fixture-*")):
            with self.subTest(fixture=fixture.name):
                mem = fixture / crumb.MEMORY_DIRNAME
                self.assertEqual(lifecycle.near_duplicate_pairs(mem), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
