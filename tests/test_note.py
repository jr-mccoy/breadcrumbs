"""Tests for `crumb note question|trap|idea` and the `memory_note` MCP tool.

Closes the read/write asymmetry: open-questions / known-traps /
ideas were readable but had no writer.

Run with:  python -m pytest tests/
       or:  python tests/test_note.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import mcp_core  # noqa: E402


def init_store(tmp: str) -> Path:
    root = Path(tmp)
    crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


class NoteQuestionTests(unittest.TestCase):
    def test_question_is_written_and_parses_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            code, _ = run(
                [
                    "note",
                    "question",
                    "Should age signals gate compliance?",
                    "--project",
                    tmp,
                    "--why",
                    "blocks export",
                    "--needs",
                    "a decision",
                ]
            )
            self.assertEqual(code, 0)
            qs = crumb.load_open_questions(mem)
            self.assertTrue(any(q["question"] == "Should age signals gate compliance?" for q in qs))
            # placeholder replaced, validate clean
            self.assertNotIn("_No open questions yet._", (mem / "open-questions.md").read_text())
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    def test_two_questions_both_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(["note", "question", "First?", "--project", tmp])
            run(["note", "question", "Second?", "--project", tmp])
            qs = {q["question"] for q in crumb.load_open_questions(mem)}
            self.assertEqual(qs, {"First?", "Second?"})

    def test_refreshes_resume_packet(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(["note", "question", "Surfaces in packet?", "--project", tmp])
            packet = (mem / "generated" / "resume-packet.md").read_text()
            self.assertIn("Surfaces in packet?", packet)


class NoteTrapTests(unittest.TestCase):
    def test_trap_is_written_and_parses_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            code, _ = run(
                [
                    "note",
                    "trap",
                    "gradlew --stop corrupts R.jar lock",
                    "--project",
                    tmp,
                    "--slug",
                    "gradle-daemon",
                    "--area",
                    "build",
                ]
            )
            self.assertEqual(code, 0)
            traps = crumb.load_traps(mem)
            self.assertTrue(
                any(t["heading"].lower().startswith("trap_gradle-daemon") for t in traps)
            )
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    def test_slug_derived_when_omitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(
                ["note", "trap", "Flaky migration on rotate", "--project", tmp, "--json"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["ref"], "trap_flaky-migration-on-rotate")

    def test_derived_slug_shares_the_filename_budget(self):
        # An auto-derived slug is the whole trap text; unbounded, it turned
        # every downstream mention of the trap (resume packet, guard reasons)
        # into a paragraph-long id. Found dogfooding this repo's own store.
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            text = (
                "Never create a git tag or GitHub Release by hand because the "
                "release workflow owns both of them on the exact commit it builds "
                "and hand-tagging the wrong commit caused nearly every past failure"
            )
            code, out = run(["note", "trap", text, "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            ref = json.loads(out)["ref"]
            self.assertLessEqual(len(ref), len("trap_") + crumb.SLUG_MAX_CHARS, ref)
            # the full text survives as the summary even though the id is cut
            traps = crumb.load_traps(Path(tmp) / crumb.MEMORY_DIRNAME)
            self.assertTrue(any("nearly every past failure" in t["heading"] for t in traps))


class NoteIdeaTests(unittest.TestCase):
    def test_idea_creates_valid_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            code, out = run(
                [
                    "note",
                    "idea",
                    "cache resume packet across sessions",
                    "--project",
                    tmp,
                    "--set",
                    "Idea",
                    "memoize",
                    "--set",
                    "Motivation",
                    "speed",
                    "--json",
                ]
            )
            self.assertEqual(code, 0)
            payload = json.loads(out)
            self.assertTrue(payload["id"].startswith("idea_"))
            self.assertEqual(len(list((mem / "ideas").glob("*.md"))), 1)
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    def test_unknown_idea_section_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, _ = run(["note", "idea", "x", "--project", tmp, "--set", "Bogus", "y"])
            self.assertEqual(code, 2)


class NoteMisuseTests(unittest.TestCase):
    def test_bare_note_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, _ = run(["note", "--project", tmp])
            self.assertEqual(code, 2)

    def test_no_store_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(["note", "question", "x", "--project", tmp])
            self.assertEqual(code, 2)


class MemoryNoteToolTests(unittest.TestCase):
    def test_tool_note_writes_question(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            res = mcp_core.tool_note("question", "Tool-written?", fields={"why": "x"}, root=tmp)
            self.assertTrue(res["ok"])
            self.assertTrue(
                any(q["question"] == "Tool-written?" for q in crumb.load_open_questions(mem))
            )

    def test_tool_note_rejects_bad_kind(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            res = mcp_core.tool_note("bogus", "x", root=tmp)
            self.assertFalse(res["ok"])


class TrapLifecycleTests(unittest.TestCase):
    """`mark-status` on a trap.

    Traps live as `## trap_<slug>` blocks inside the aggregate known-traps.md
    while decisions/attempts/verifications are one file each, and `mark-status`
    resolved only the per-file types — so `note trap` printed an id, `search`
    listed it `[active]`, and `mark-status <that id>` answered "no record with
    id". No trap could ever be retired through the CLI: every trap ever written
    stayed active and kept firing in guard and search forever.
    """

    def _trap(self, tmp: str, text: str, slug: str, **flags) -> Path:
        mem = Path(tmp) / crumb.MEMORY_DIRNAME
        if not mem.is_dir():
            init_store(tmp)
        argv = ["note", "trap", text, "--project", tmp, "--slug", slug]
        for key, value in flags.items():
            argv += [f"--{key}", value]
        code, _ = run(argv)
        self.assertEqual(code, 0)
        return mem

    def test_the_id_note_prints_is_the_id_mark_status_takes(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(
                ["note", "trap", "Flex window ignored below API 26", "--project", tmp, "--json"]
            )
            self.assertEqual(code, 0)
            rid = json.loads(out)["ref"]
            mem = Path(tmp) / crumb.MEMORY_DIRNAME
            # the id search shows is the same one
            matches, _ = crumb.search(mem, Path(tmp), "flex window", include_ideas=True)
            self.assertIn(rid, [m["id"] for m in matches])

            code, out = run(["mark-status", rid, "stale", "--project", tmp, "--reason", "fixed"])
            self.assertEqual(code, 0, out)
            self.assertEqual(crumb.find_trap_by_id(mem, rid)["status"], "stale")

    def test_a_retired_trap_stops_being_advice(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._trap(
                tmp, "WorkManager flex window is not honored", "flex", area="app/work/Sync.kt"
            )
            root = Path(tmp)
            self.assertEqual(len(crumb.build_resume_packet(mem, root)["known_traps"]), 1)
            self.assertTrue(crumb._build_guard_prefilter(mem)["tokens"])

            run(["mark-status", "trap_flex", "stale", "--project", tmp, "--reason", "min-sdk 26"])

            # Gone from the packet and the hook pre-filter...
            self.assertEqual(crumb.build_resume_packet(mem, root)["known_traps"], [])
            self.assertEqual(crumb._build_guard_prefilter(mem), {"tokens": [], "paths": []})
            # ...and demoted out of the set that drives a guard verdict.
            result = crumb.guard(
                mem, root, "tune the WorkManager flex window", files=["app/work/Sync.kt"]
            )
            self.assertNotIn("trap_flex", [m["id"] for m in result["matches"]])
            self.assertIn("trap_flex", [m["id"] for m in result["history"]])

    def test_a_retired_trap_stays_findable_with_its_real_status(self):
        # Same posture as a superseded decision: retiring is not deleting.
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._trap(tmp, "gradlew --stop corrupts the R.jar lock", "gradle")
            run(["mark-status", "trap_gradle", "stale", "--project", tmp, "--reason", "gradle 8"])
            matches, _ = crumb.search(mem, Path(tmp), "gradlew", include_ideas=True)
            found = [m for m in matches if m["id"] == "trap_gradle"]
            self.assertEqual([m["status"] for m in found], ["stale"])

    def test_a_trap_can_come_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._trap(tmp, "Flaky rotate migration", "rotate")
            run(["mark-status", "trap_rotate", "stale", "--project", tmp, "--reason", "fixed"])
            code, _ = run(
                ["mark-status", "trap_rotate", "active", "--project", tmp, "--reason", "regressed"]
            )
            self.assertEqual(code, 0)
            self.assertEqual([t["id"] for t in crumb.active_traps(mem)], ["trap_rotate"])

    def test_pre_existing_traps_have_no_status_bullet_and_count_as_active(self):
        # Every trap in every store written before traps had a lifecycle.
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            path = mem / "known-traps.md"
            path.write_text(
                path.read_text(encoding="utf-8")
                + "\n## trap_legacy: Written before traps had a status\n"
                + "- Area / files: src/legacy.py\n\nSome loose prose.\n",
                encoding="utf-8",
            )
            self.assertEqual([t["id"] for t in crumb.active_traps(mem)], ["trap_legacy"])
            code, _ = run(
                [
                    "mark-status",
                    "trap_legacy",
                    "rejected",
                    "--project",
                    tmp,
                    "--reason",
                    "never reproduced",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(crumb.active_traps(mem), [])
            # the bullet joins the block's field list; the prose survives
            self.assertIn("Some loose prose.", path.read_text(encoding="utf-8"))

    def test_only_the_target_block_is_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._trap(tmp, "First trap", "one", area="a/one.py")
            self._trap(tmp, "Second trap", "two", area="b/two.py")
            path = mem / "known-traps.md"
            before = path.read_text(encoding="utf-8")
            run(["mark-status", "trap_one", "stale", "--project", tmp, "--reason", "done"])
            after = path.read_text(encoding="utf-8")

            # The template documents its own format inside an HTML comment, and
            # that comment contains a `## trap_<short-slug>:` example line — a
            # raw scan for the heading would edit the template instead.
            head = before.split("## trap_one", 1)[0]
            self.assertEqual(after.split("## trap_one", 1)[0], head)
            self.assertIn("<short-slug>", after)
            self.assertEqual(crumb.find_trap_by_id(mem, "trap_two")["status"], "active")
            self.assertIn("- Area / files: b/two.py", after)

    def test_lifecycle_bullets_never_reach_the_keyword_index(self):
        # `- Status: active` tokenizes to statu/activ. Indexing the raw body
        # would hand every trap two extra tokens and make any action mentioning
        # "status" trip the pre-filter — new alarm noise from the fix meant to
        # let traps be silenced.
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._trap(tmp, "Sync worker wedges", "sync")
            tokens = set(crumb._build_guard_prefilter(mem)["tokens"])
            self.assertFalse(tokens & {"statu", "activ", "status", "active"}, tokens)

    def test_superseded_needs_a_pointer(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._trap(tmp, "Old advice", "old")
            code, _ = run(
                ["mark-status", "trap_old", "superseded", "--project", tmp, "--reason", "replaced"]
            )
            self.assertEqual(code, 1)
            self.assertEqual(crumb.find_trap_by_id(mem, "trap_old")["status"], "active")
            code, _ = run(
                [
                    "mark-status",
                    "trap_old",
                    "superseded",
                    "--project",
                    tmp,
                    "--reason",
                    "replaced",
                    "--superseded-by",
                    "trap_new",
                ]
            )
            self.assertEqual(code, 0)
            trap = crumb.find_trap_by_id(mem, "trap_old")
            self.assertEqual(trap["status"], "superseded")
            self.assertIn("- Superseded by: trap_new", trap["body"])

    def test_reason_cannot_forge_trap_content(self):
        # Mirrors R24 on the record path: the reason is data, and a literal
        # `-->` would close the provenance comment and leak the rest as a trap.
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._trap(tmp, "Real trap", "real")
            code, _ = run(
                [
                    "mark-status",
                    "trap_real",
                    "stale",
                    "--project",
                    tmp,
                    "--reason",
                    "evil --> ## trap_fake: injected",
                ]
            )
            self.assertEqual(code, 0)
            self.assertNotIn("trap_fake", [t["id"] for t in crumb.load_traps(mem)])

    def test_unknown_id_says_trap_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(["mark-status", "trap_nope", "stale", "--project", tmp, "--json"])
            self.assertEqual(code, 1)
            self.assertIn("no record, trap or question", json.loads(out)["error"])

    def test_a_summary_only_trap_points_at_the_documented_template(self):
        # known-traps.md documents Area / Symptom / Why / Safe approach /
        # Verification at the top of the file, but the writer accepts a bare
        # summary, so the whole trap lands on the heading line.
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(["note", "trap", "Something bites here", "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            self.assertIn("--symptom", json.loads(out)["hint"])

            code, out = run(
                [
                    "note",
                    "trap",
                    "Something else bites",
                    "--project",
                    tmp,
                    "--slug",
                    "else",
                    "--symptom",
                    "it wedges",
                ]
            )
            self.assertEqual(code, 0)
            self.assertNotIn("--symptom", out)


class QuestionLifecycleTests(unittest.TestCase):
    """`mark-status` on an open question.

    The other half of the aggregate-file gap. Every *reader* already honored a
    question's `- Status:` bullet — the packet lists only `open` ones, guard
    gives only an `open` question the open-blocker floor — but the bullet was
    write-once at `note question` time. A question that got answered went on
    counting as a live blocker forever, exactly as a fixed trap went on firing.
    """

    def _ask(self, tmp: str, text: str, **flags) -> tuple[Path, str]:
        mem = Path(tmp) / crumb.MEMORY_DIRNAME
        if not mem.is_dir():
            init_store(tmp)
        argv = ["note", "question", text, "--project", tmp]
        for key, value in flags.items():
            argv += [f"--{key}", value]
        code, _ = run(argv)
        self.assertEqual(code, 0)
        return mem, crumb.question_item_id(text)

    def test_a_question_can_be_answered(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, qid = self._ask(tmp, "Should age signals gate compliance?", why="blocks export")
            root = Path(tmp)
            self.assertEqual(len(crumb.build_resume_packet(mem, root)["open_questions"]), 1)

            code, out = run(
                [
                    "mark-status",
                    qid,
                    "answered",
                    "--project",
                    tmp,
                    "--reason",
                    "see dec_20260816_gate-on-age",
                ]
            )
            self.assertEqual(code, 0, out)
            self.assertEqual(crumb.find_questions_by_id(mem, qid)[0]["status"], "answered")
            self.assertEqual(crumb.build_resume_packet(mem, root)["open_questions"], [])
            self.assertEqual(crumb.open_questions(mem), [])

    def test_an_answered_question_stops_being_an_open_blocker(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, qid = self._ask(tmp, "Should we shard the ledger table?")
            root = Path(tmp)
            live = crumb.guard(mem, root, "shard the ledger table")
            self.assertIn(qid, [m["id"] for m in live["matches"]])

            run(["mark-status", qid, "answered", "--project", tmp, "--reason", "yes, in Q3"])
            after = crumb.guard(mem, root, "shard the ledger table")
            self.assertNotIn(qid, [m["id"] for m in after["matches"]])
            self.assertIn(qid, [m["id"] for m in after["history"]])

    def test_an_answered_question_stays_findable(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, qid = self._ask(tmp, "Should we shard the ledger table?")
            run(["mark-status", qid, "closed", "--project", tmp, "--reason", "withdrawn"])
            matches, _ = crumb.search(mem, Path(tmp), "shard ledger", include_ideas=True)
            found = [m for m in matches if m["id"] == qid]
            self.assertEqual([m["status"] for m in found], ["closed"])

    def test_an_answered_question_stops_aging_into_a_warning(self):
        # compute_staleness nags about questions open past --stale-days. Before
        # this there was no way to make it stop short of hand-editing.
        with tempfile.TemporaryDirectory() as tmp:
            mem, qid = self._ask(tmp, "Is the migration reversible?")
            path = mem / "open-questions.md"
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    f"- Opened: {crumb.now_iso()[:10]}", "- Opened: 2020-01-01"
                ),
                encoding="utf-8",
            )
            aged = crumb.compute_staleness(
                Path(tmp), {}, [], [], crumb.load_open_questions(mem), crumb.STALE_AGE_DAYS
            )
            self.assertTrue(any("Is the migration reversible?" in w for w in aged))

            run(["mark-status", qid, "answered", "--project", tmp, "--reason", "yes"])
            quiet = crumb.compute_staleness(
                Path(tmp), {}, [], [], crumb.load_open_questions(mem), crumb.STALE_AGE_DAYS
            )
            self.assertFalse(any("Is the migration reversible?" in w for w in quiet))

    def test_a_question_can_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, qid = self._ask(tmp, "Do we still need the shim?")
            run(["mark-status", qid, "answered", "--project", tmp, "--reason", "no"])
            code, _ = run(["mark-status", qid, "open", "--project", tmp, "--reason", "it came up"])
            self.assertEqual(code, 0)
            self.assertEqual([q["id"] for q in crumb.open_questions(mem)], [qid])

    def test_record_and_question_vocabularies_do_not_cross(self):
        # A question is open/answered/closed, never superseded — forcing a
        # record word onto it would record the opposite of what happened.
        with tempfile.TemporaryDirectory() as tmp:
            mem, qid = self._ask(tmp, "Does the cache need eviction?")
            res = crumb.set_record_status(mem, qid, "superseded", "x")
            self.assertFalse(res["ok"])
            self.assertIn("invalid question status", res["error"])
            self.assertEqual(crumb.find_questions_by_id(mem, qid)[0]["status"], "open")

    def test_a_long_question_is_addressable_by_its_digest_id(self):
        # question_item_id appends a digest past 48 slug chars; mark-status has
        # to accept exactly the id search prints, digest and all.
        with tempfile.TemporaryDirectory() as tmp:
            text = (
                "Should we migrate the ledger to the new columnar store this quarter "
                "or wait for the row store rewrite?"
            )
            mem, qid = self._ask(tmp, text)
            self.assertNotEqual(qid, "q:" + crumb.slugify(text))
            code, _ = run(["mark-status", qid, "answered", "--project", tmp, "--reason", "wait"])
            self.assertEqual(code, 0)
            self.assertEqual(crumb.open_questions(mem), [])

    def test_only_the_target_block_is_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, first = self._ask(tmp, "First question?", why="it blocks the export")
            _, second = self._ask(tmp, "Second question?", needs="a decision")
            path = mem / "open-questions.md"
            before = path.read_text(encoding="utf-8")
            run(["mark-status", first, "answered", "--project", tmp, "--reason", "done"])
            after = path.read_text(encoding="utf-8")

            self.assertEqual(after.split("## Q: First", 1)[0], before.split("## Q: First", 1)[0])
            self.assertIn("- Needs: a decision", after)
            self.assertIn("- Why it matters: it blocks the export", after)
            self.assertEqual(crumb.find_questions_by_id(mem, second)[0]["status"], "open")

    def test_bookkeeping_bullets_never_reach_the_keyword_index(self):
        # `- Opened: 2026-08-16` and `- Status: open` are not what the question
        # is about; indexing them adds tokens that match nothing meaningful.
        with tempfile.TemporaryDirectory() as tmp:
            mem, _ = self._ask(tmp, "Does the ledger need sharding?")
            item = crumb._item_from_question(crumb.load_open_questions(mem)[0])
            self.assertFalse(item["specific"] & {"statu", "open", "activ"}, item["specific"])

    def test_reason_cannot_forge_question_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, qid = self._ask(tmp, "A real question?")
            code, _ = run(
                [
                    "mark-status",
                    qid,
                    "answered",
                    "--project",
                    tmp,
                    "--reason",
                    "evil --> ## Q: injected?",
                ]
            )
            self.assertEqual(code, 0)
            self.assertNotIn("injected?", [q["question"] for q in crumb.load_open_questions(mem)])

    def test_the_mcp_tool_reaches_questions_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, qid = self._ask(tmp, "Reachable over MCP?")
            res = mcp_core.tool_mark_status(qid, "answered", "yes", root=tmp)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["path"], "open-questions.md")
            self.assertEqual(crumb.find_questions_by_id(mem, qid)[0]["status"], "answered")


if __name__ == "__main__":
    unittest.main()
