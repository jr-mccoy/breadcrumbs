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


class SupersedeGuardTests(unittest.TestCase):
    def test_an_already_superseded_verification_cannot_be_superseded_again(self):
        # It would overwrite `superseded_by` and orphan the first replacement.
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            first = crumb.verify(mem, Path(tmp), "cache eviction", status="open")["id"]
            second = crumb.verify(
                mem, Path(tmp), "cache eviction", status="fixed", supersedes=first
            )["id"]
            code, _out, err = run_err(
                [
                    "verify",
                    "cache eviction",
                    "--status",
                    "fixed",
                    "--supersedes",
                    first,
                    "--project",
                    tmp,
                ]
            )
            self.assertEqual(code, 2)
            self.assertIn("already superseded", err)
            self.assertEqual(crumb.find_record_by_id(mem, first).meta["superseded_by"], second)

    def test_a_bad_supersedes_is_usage_error_on_every_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            for argv in (
                ["note", "trap", "x y z", "--supersedes", "trap_nope"],
                ["verify", "x", "--status", "fixed", "--supersedes", "ver_20200101_nope"],
                [
                    "remember",
                    "decision",
                    "--title",
                    "x",
                    "--confidence",
                    "low",
                    "--supersedes",
                    "dec_20200101_nope",
                ],
            ):
                with self.subTest(cmd=argv[0]):
                    code, _out, _err = run_err([*argv, "--project", tmp])
                    self.assertEqual(code, 2)

    def test_recheck_of_a_retired_verification_names_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            ev = [{"type": "command", "ref": "true"}]
            first = crumb.verify(mem, Path(tmp), "suite passes", status="fixed", evidence=ev)["id"]
            crumb.verify(
                mem, Path(tmp), "suite passes", status="fixed", evidence=ev, supersedes=first
            )
            code, _out, err = run_err(["verify", "--recheck", first, "--yes", "--project", tmp])
            self.assertEqual(code, 1)
            self.assertIn("already superseded", err)

    def test_traps_stale_uses_the_store_ttl(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            tid = crumb.note(mem, Path(tmp), "trap", "the daemon holds a lock")["id"]
            _cli.set_trap_confirmed(mem, tid)
            set_manifest(mem, "ttl_trap_days", "5")
            with days_later(6):
                code, out = run(["traps", "--stale", "--project", tmp, "--json"])
                self.assertEqual([r["id"] for r in json.loads(out)["items"]], [tid])


# --------------------------------------------------------------------------- #
# WM-33 consolidation
# --------------------------------------------------------------------------- #


class ConsolidateTests(unittest.TestCase):
    def _pair(self, tmp: str) -> tuple[Path, str, str]:
        mem = init_store(tmp)
        a = remember(tmp, "Ledger rows are append-only", body=DECISION[2])
        with days_later(1):
            b = remember(
                tmp, "Ledger rows are append only in sqlite", body=DECISION[2] + " Always."
            )
        return mem, a, b

    def test_clusters_are_listed(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mem, a, b = self._pair(tmp)
            code, out = run(["consolidate", "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            clusters = json.loads(out)["items"]
            self.assertEqual([c["ids"] for c in clusters], [sorted([a, b])])

    def test_merge_writes_one_record_and_supersedes_the_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, a, b = self._pair(tmp)
            code, out = run(
                [
                    "consolidate",
                    "--merge",
                    a,
                    b,
                    "--title",
                    "Ledger rows are append-only in sqlite",
                    "--project",
                    tmp,
                    "--json",
                ]
            )
            self.assertEqual(code, 0, out)
            new_id = json.loads(out)["id"]
            new = crumb.find_record_by_id(mem, new_id)
            self.assertEqual(sorted(new.meta["supersedes"]), sorted([a, b]))
            self.assertIn(f"_(from {a})_", new.body)
            self.assertIn(f"_(from {b})_", new.body)
            self.assertLess(new.body.index(a), new.body.index(b), "oldest source first")
            self.assertEqual(new.meta["evidence"], [{"type": "file", "ref": "src/ledger.py"}])
            for old in (a, b):
                rec = crumb.find_record_by_id(mem, old)
                self.assertEqual(rec.meta["status"], "superseded")
                self.assertEqual(rec.meta["superseded_by"], new_id)
            g = crumb.guard(mem, Path(tmp), "rewrite src/ledger.py", files=["src/ledger.py"])
            live = [m["id"] for m in g["matches"]]
            self.assertIn(new_id, live)
            self.assertNotIn(a, live)
            self.assertNotIn(b, live)

    def test_mixed_types_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, a, _b = self._pair(tmp)
            vid = crumb.verify(mem, Path(tmp), "ledger rows checked", status="fixed")["id"]
            code, _out, err = run_err(
                ["consolidate", "--merge", a, vid, "--title", "x", "--project", tmp]
            )
            self.assertEqual(code, 2)
            self.assertIn("different types", err)

    def test_sessions_are_never_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            ids = []
            for i in range(2):
                path, meta = _cli.write_record(
                    mem, Path(tmp), "session", f"session {i}", {"Next Action": "ship"}
                )
                ids.append(meta["id"])
            code, _out, err = run_err(
                ["consolidate", "--merge", *ids, "--title", "x", "--project", tmp]
            )
            self.assertEqual(code, 2)
            self.assertIn("not sessions", err)


# --------------------------------------------------------------------------- #
# WM-34 contradiction detection
# --------------------------------------------------------------------------- #


def attempt(tmp: str, title: str, tried: str, file: str) -> str:
    code, out = run(
        [
            "remember",
            "attempt",
            "--project",
            tmp,
            "--title",
            title,
            "--problem",
            "builds hang on CI",
            "--tried",
            tried,
            "--result",
            "failed",
            "--why",
            "it killed the live test daemons",
            "--do-not-retry",
            "the daemon owner changes",
            "--evidence",
            "file",
            file,
            "--allow-duplicate",
            "--json",
        ]
    )
    assert code == 0, out
    return json.loads(out)["id"]


class ContradictionTests(unittest.TestCase):
    TRIED = "run gradlew --stop before every build to reset the gradle daemon"

    def test_a_later_decision_redoing_a_do_not_retry_attempt_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            aid = attempt(tmp, "Stopping the gradle daemon", self.TRIED, "app/build.gradle.kts")
            with days_later(3):
                did = remember(
                    tmp,
                    "Reset the gradle daemon before builds",
                    file="app/build.gradle.kts",
                    body="Run gradlew --stop before every build to reset the gradle daemon.",
                )
                found = lifecycle.find_contradictions(mem)
                self.assertEqual(
                    [(c["rule"], c["ids"]) for c in found],
                    [("retry-after-do-not-retry", [did, aid])],
                )
                warnings = crumb.build_resume_packet(mem, Path(tmp))["warnings"]
                self.assertTrue(
                    any(f"decision {did} may do what attempt {aid}" in w for w in warnings)
                )
                audit = [
                    f
                    for f in crumb.run_audit(mem, Path(tmp))
                    if f["check"] == "possible-contradiction"
                ]
                self.assertEqual(len(audit), 1)

    def test_a_retired_attempt_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            aid = attempt(tmp, "Stopping the gradle daemon", self.TRIED, "app/build.gradle.kts")
            run(["mark-status", aid, "stale", "--project", tmp, "--reason", "owner changed"])
            with days_later(3):
                remember(
                    tmp, "Reset the gradle daemon", file="app/build.gradle.kts", body=self.TRIED
                )
                self.assertEqual(lifecycle.find_contradictions(mem), [])

    def test_a_decision_written_before_the_attempt_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            remember(tmp, "Reset the gradle daemon", file="app/build.gradle.kts", body=self.TRIED)
            with days_later(3):
                attempt(tmp, "Stopping the gradle daemon", self.TRIED, "app/build.gradle.kts")
                self.assertEqual(lifecycle.find_contradictions(mem), [])

    def _overlapping(self, tmp: str, gap_days: int) -> Path:
        mem = init_store(tmp)
        remember(tmp, "Ledger rows are append-only", body=DECISION[2])
        with days_later(gap_days):
            remember(tmp, "Ledger rows are append only in sqlite", body=DECISION[2])
        return mem

    def test_overlapping_decisions_far_apart_are_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._overlapping(tmp, 10)
            rules = [c["rule"] for c in lifecycle.find_contradictions(mem)]
            self.assertEqual(rules, ["overlapping-decisions"])
            # One finding per pair: the contradiction, not also a near-duplicate.
            checks = [f["check"] for f in crumb.run_audit(mem, Path(tmp))]
            self.assertIn("possible-contradiction", checks)
            self.assertNotIn("near-duplicates", checks)

    def test_overlapping_decisions_close_together_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._overlapping(tmp, 2)
            self.assertEqual(lifecycle.find_contradictions(mem), [])

    def test_the_projection_is_written_at_reindex(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._overlapping(tmp, 10)
            crumb.main(["reindex", "--project", tmp])
            doc = json.loads((mem / "generated" / lifecycle.CONFLICTS_FILENAME).read_text("utf-8"))
            self.assertEqual(len(doc["conflicts"]), 1)
            self.assertEqual(doc["inputs_hash"], _cli._inputs_hash(mem, Path(tmp)))

    def test_the_fixtures_hold_no_contradictions(self):
        for fixture in sorted((REPO_ROOT / "fixtures").glob("fixture-*")):
            with self.subTest(fixture=fixture.name):
                self.assertEqual(lifecycle.find_contradictions(fixture / crumb.MEMORY_DIRNAME), [])


# --------------------------------------------------------------------------- #
# WM-35 session rollup
# --------------------------------------------------------------------------- #


class RollupTests(unittest.TestCase):
    def _sessions(self, tmp: str) -> tuple[Path, list[str], str]:
        mem = init_store(tmp)
        snapshots = []
        for day in range(10):
            with days_later(day):
                _path, meta = _cli.write_record(
                    mem,
                    Path(tmp),
                    "session",
                    f"snapshot {day}",
                    {
                        "Work Completed": f"worked on the parser, part {day}",
                        "Next Action": _cli.HOOK_SESSION_NEXT_ACTION,
                    },
                )
                snapshots.append(meta["id"])
        with days_later(4):
            _path, human = _cli.write_record(
                mem,
                Path(tmp),
                "session",
                "the parser rewrite",
                {"Work Completed": "rewrote the parser", "Next Action": "ship the parser"},
            )
        return mem, snapshots, human["id"]

    def _before(self, days: int) -> str:
        return (_cli._now() + timedelta(days=days)).date().isoformat()

    def test_snapshots_roll_into_one_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, snaps, human = self._sessions(tmp)
            code, out = run(
                ["rollup", "sessions", "--before", self._before(8), "--project", tmp, "--json"]
            )
            self.assertEqual(code, 0, out)
            res = json.loads(out)
            self.assertEqual(res["rolled_up"], 8)
            rolled = crumb.find_record_by_id(mem, res["id"])
            self.assertEqual(rolled.meta["supersedes"], snaps[:8])
            self.assertIn("rollup:", rolled.meta["title"])
            self.assertIn("part 0", rolled.body)
            self.assertIn("part 7", rolled.body)
            for sid in snaps[:8]:
                self.assertIsNone(crumb.find_record_by_id(mem, sid))
            # The newest snapshots and the human session are untouched.
            for sid in snaps[8:] + [human]:
                self.assertIsNotNone(crumb.find_record_by_id(mem, sid))

    def test_ten_snapshots_give_ten_supersedes(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, snaps, human = self._sessions(tmp)
            code, out = run(
                ["rollup", "sessions", "--before", self._before(11), "--project", tmp, "--json"]
            )
            res = json.loads(out)
            self.assertEqual(len(crumb.find_record_by_id(mem, res["id"]).meta["supersedes"]), 10)
            self.assertIsNotNone(crumb.find_record_by_id(mem, human))

    def test_dry_run_deletes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, snaps, _human = self._sessions(tmp)
            code, out = run(
                [
                    "rollup",
                    "sessions",
                    "--before",
                    self._before(8),
                    "--dry-run",
                    "--project",
                    tmp,
                    "--json",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["rolled_up"], 8)
            for sid in snaps:
                self.assertIsNotNone(crumb.find_record_by_id(mem, sid))

    def test_the_rollup_does_not_become_the_newest_session(self):
        # The Stop hook diffs from the newest session's commit and coalesces into
        # the newest snapshot; a rollup stamped "now" would hijack both.
        with tempfile.TemporaryDirectory() as tmp:
            mem, snaps, _human = self._sessions(tmp)
            run(["rollup", "sessions", "--before", self._before(8), "--project", tmp])
            self.assertEqual(_cli._newest_session_record(mem).meta["id"], snaps[-1])
            with days_later(10):
                code, _ = run(["capture", "session", "--fast", "--project", tmp, "--next", "go"])
            self.assertEqual(code, 0)

    def test_a_bad_date_is_usage_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, _, _ = run_err(["rollup", "sessions", "--before", "yesterday", "--project", tmp])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
