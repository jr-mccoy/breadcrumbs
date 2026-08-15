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


if __name__ == "__main__":
    unittest.main()
