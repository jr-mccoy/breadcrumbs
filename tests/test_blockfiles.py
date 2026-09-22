"""Tests for traps and questions as one file each (WM-22, schema 3).

Through schema 2 every trap was a `## trap_…` block in known-traps.md and every
question a `## Q:` block in open-questions.md: two files every writer appended
to, which two branches could not both touch without a merge conflict, and
which grew without bound (167 KB of traps in the field store). Schema 3 gives
each its own file and turns the two singletons into generated indexes.

What must hold:
- the migration keeps every id and every line, and is idempotent;
- the readers return the same traps and questions before and after, so guard,
  search and resume answer exactly as they did;
- a block somebody still hand-writes into a singleton is adopted into its own
  file, never lost — and one that clashes with an existing file is kept and
  reported, never merged by guesswork.

Run with:  python -m unittest discover -s tests
"""

from __future__ import annotations

import contextlib
import io
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from _schema2 import downgrade_to_schema2  # noqa: E402
from breadcrumbs import blockfiles, migrate  # noqa: E402

TRAPS = [
    ("gradle-stop", "gradlew --stop corrupts the build cache", "build.gradle"),
    ("tag-by-hand", "hand-tagging a release points the tag at the wrong commit", "RELEASING.md"),
    ("sqlite-lock", "the daemon holds the sqlite write lock", "src/daemon.py"),
    ("flex-window", "the flex window is ignored below API 26", "app/src/Work.kt"),
    ("utf8-bom", "a BOM in the manifest breaks the parser", "manifest.yml"),
]
QUESTIONS = [
    "Should the worker own its own schema migrations?",
    "Do we still need the Python 3.9 shim?",
    "Is the ledger compaction safe to run during business hours?",
]


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def schema2_store(tmp: str) -> tuple[Path, Path]:
    """A schema-2 store holding five trap blocks and three question blocks."""
    root = Path(tmp)
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    mem = downgrade_to_schema2(root / crumb.MEMORY_DIRNAME)
    for slug, summary, area in TRAPS:
        res = crumb.note(
            mem,
            root,
            "trap",
            summary,
            fields={
                "slug": slug,
                "area": area,
                "symptom": f"{summary} (symptom)",
                "why": "the mechanism",
                "safe": "do the safe thing",
                "verify": "python -m unittest",
            },
        )
        assert res["ok"], res
    for text in QUESTIONS:
        res = crumb.note(mem, root, "question", text, fields={"why": "it blocks work"})
        assert res["ok"], res
    return mem, root


def _trap_view(traps: list[dict]) -> dict:
    return {t["id"]: (t["summary"], t["status"], t["content"]) for t in traps}


def _question_view(questions: list[dict]) -> dict:
    return {q["id"]: (q["question"], q["status"], q["content"]) for q in questions}


class MigrationTests(unittest.TestCase):
    def test_the_schema2_store_really_holds_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, _ = schema2_store(tmp)
            self.assertFalse(blockfiles.uses_files(mem))
            text = (mem / "known-traps.md").read_text("utf-8")
            # (the template's format comment has a `## trap_<short-slug>` example)
            self.assertEqual(text.count("\n## trap_") - text.count("## trap_<"), len(TRAPS))
            self.assertFalse((mem / "traps").exists())

    def test_every_block_becomes_a_file_with_its_id_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, root = schema2_store(tmp)
            trap_ids = {t["id"] for t in crumb.load_traps(mem)}
            question_ids = {q["id"] for q in crumb.load_open_questions(mem)}
            res = migrate.migrate(mem, root)
            self.assertTrue(res["ok"], res)
            self.assertEqual(res["to"], 3)
            self.assertEqual(len(list((mem / "traps").glob("*.md"))), len(TRAPS))
            self.assertEqual(len(list((mem / "questions").glob("*.md"))), len(QUESTIONS))
            self.assertEqual({t["id"] for t in crumb.load_traps(mem)}, trap_ids)
            self.assertEqual({q["id"] for q in crumb.load_open_questions(mem)}, question_ids)
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertEqual(fails, [])

    def test_readers_return_the_same_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, root = schema2_store(tmp)
            run(["mark-status", "trap_utf8-bom", "stale", "--project", tmp, "--reason", "fixed"])
            traps = _trap_view(crumb.load_traps(mem))
            questions = _question_view(crumb.load_open_questions(mem))
            migrate.migrate(mem, root)
            self.assertEqual(_trap_view(crumb.load_traps(mem)), traps)
            self.assertEqual(_question_view(crumb.load_open_questions(mem)), questions)

    def test_a_summary_only_trap_migrates_without_gaining_content(self):
        # A trap with no sections renders as a `_(not recorded)_` stub so the
        # file parses; the stub must not come back out as a bullet, or the
        # migrated trap gains keywords ("record") its block never had.
        with tempfile.TemporaryDirectory() as tmp:
            mem, root = schema2_store(tmp)
            self.assertTrue(
                crumb.note(mem, root, "trap", "bare warning", fields={"slug": "bare"})["ok"]
            )
            before = _trap_view(crumb.load_traps(mem))["trap_bare"]
            migrate.migrate(mem, root)
            self.assertEqual(_trap_view(crumb.load_traps(mem))["trap_bare"], before)

    def test_guard_and_search_answer_the_same(self):
        actions = [
            "run gradlew --stop before the build",
            "git tag the release by hand",
            "edit src/daemon.py to take the sqlite lock",
            "rename a variable in the README",
        ]
        with tempfile.TemporaryDirectory() as tmp:
            mem, root = schema2_store(tmp)

            def snapshot():
                out = []
                for action in actions:
                    g = crumb.guard(mem, root, action)
                    out.append((g["verdict"], sorted(m["id"] for m in g["matches"])))
                for query in ("sqlite lock", "schema migrations worker", "release tag"):
                    matches, _ = crumb.search(mem, root, query, include_ideas=True)
                    out.append([(m["id"], m["score"], m["status"]) for m in matches])
                return out

            before = snapshot()
            migrate.migrate(mem, root)
            self.assertEqual(snapshot(), before)

    def test_the_singletons_become_indexes_listing_every_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, root = schema2_store(tmp)
            migrate.migrate(mem, root)
            index = (mem / "known-traps.md").read_text("utf-8")
            self.assertIn(blockfiles.INDEX_MARKER, index)
            self.assertNotIn("\n## trap_", index)
            for slug, _summary, _area in TRAPS:
                self.assertIn(f"`trap_{slug}`", index)
                self.assertIn(f"traps/{slug}.md", index)
            qindex = (mem / "open-questions.md").read_text("utf-8")
            self.assertEqual(qindex.count("\n- `q_"), len(QUESTIONS))

    def test_rerunning_the_step_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, root = schema2_store(tmp)
            migrate.migrate(mem, root)
            snap = {
                p: p.read_bytes() for p in sorted(mem.rglob("*.md")) if "private" not in p.parts
            }
            changed = migrate._m3_traps_and_questions_as_files(mem, root)
            self.assertFalse([c for c in changed if "->" in c], changed)
            after = {
                p: p.read_bytes() for p in sorted(mem.rglob("*.md")) if "private" not in p.parts
            }
            self.assertEqual(after, snap)

    def test_the_backup_holds_the_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, root = schema2_store(tmp)
            res = migrate.migrate(mem, root)
            backup = Path(res["backup"])
            self.assertIn("## trap_gradle-stop", (backup / "known-traps.md").read_text("utf-8"))

    def test_fixture_02_migrates_cleanly_and_guard_holds(self):
        # The committed fixtures are already at schema 3; this checks the
        # fixture's own guard contract still holds on the migrated shape.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "fx"
            shutil.copytree(REPO_ROOT / "fixtures" / "fixture-02-guard-true-positive", root)
            mem = root / crumb.MEMORY_DIRNAME
            self.assertEqual(migrate.store_schema_version(mem), crumb.SCHEMA_VERSION)
            fails = [f for f in crumb.run_validate(mem) if f["status"] == "fail"]
            self.assertEqual(fails, [])


class WritingAtSchema3Tests(unittest.TestCase):
    def test_note_trap_writes_a_file_and_the_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            mem = Path(tmp) / crumb.MEMORY_DIRNAME
            res = crumb.note(mem, Path(tmp), "trap", "the daemon holds a lock")
            self.assertTrue(res["ok"], res)
            path = mem / "traps" / "the-daemon-holds-a-lock.md"
            self.assertTrue(path.is_file())
            meta, _ = crumb.parse_frontmatter(path.read_text("utf-8"))
            self.assertEqual(meta["id"], "trap_the-daemon-holds-a-lock")
            self.assertEqual(meta["type"], "trap")
            self.assertIn(
                "`trap_the-daemon-holds-a-lock`", (mem / "known-traps.md").read_text("utf-8")
            )

    def test_a_duplicate_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            mem = Path(tmp) / crumb.MEMORY_DIRNAME
            self.assertTrue(crumb.note(mem, Path(tmp), "question", "Is it safe?")["ok"])
            res = crumb.note(mem, Path(tmp), "question", "Is it safe?")
            self.assertFalse(res["ok"])

    def test_two_traps_touch_two_files(self):
        # The point of the change: two branches adding a trap each touch
        # different files, so the only shared file is the generated index.
        with tempfile.TemporaryDirectory() as tmp:
            crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
            mem = Path(tmp) / crumb.MEMORY_DIRNAME
            crumb.note(mem, Path(tmp), "trap", "first trap")
            first = (mem / "traps" / "first-trap.md").read_bytes()
            crumb.note(mem, Path(tmp), "trap", "second trap")
            self.assertEqual((mem / "traps" / "first-trap.md").read_bytes(), first)

    def test_the_schema_template_names_note(self):
        code, out = run(["schema", "trap", "--template"])
        self.assertEqual(code, 0)
        self.assertIn("crumb note trap", out)
        code, out = run(["schema", "question", "--template"])
        self.assertEqual(code, 0)
        self.assertIn("crumb note question", out)


class AdoptionTests(unittest.TestCase):
    """A block hand-written into a schema-3 singleton — by a human, an older
    tool, or a merge from a branch that had not migrated yet."""

    BLOCK = (
        "\n## trap_hand-written: somebody typed this in\n"
        "- Area / files: src/x.py\n"
        "- Symptom: it breaks\n"
        "\nA line of loose prose.\n"
    )

    def _store(self, tmp: str) -> Path:
        crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
        return Path(tmp) / crumb.MEMORY_DIRNAME

    def test_readers_see_it_before_any_reindex(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store(tmp)
            path = mem / "known-traps.md"
            path.write_text(path.read_text("utf-8") + self.BLOCK, encoding="utf-8")
            self.assertIn("trap_hand-written", [t["id"] for t in crumb.load_traps(mem)])
            g = crumb.guard(mem, Path(tmp), "edit src/x.py")
            self.assertIn("trap_hand-written", [m["id"] for m in g["matches"]])

    def test_reindex_adopts_it_into_its_own_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store(tmp)
            path = mem / "known-traps.md"
            path.write_text(path.read_text("utf-8") + self.BLOCK, encoding="utf-8")
            crumb.main(["reindex", "--project", tmp])
            adopted = mem / "traps" / "hand-written.md"
            self.assertTrue(adopted.is_file())
            text = adopted.read_text("utf-8")
            self.assertIn("src/x.py", text)
            self.assertIn("A line of loose prose.", text)
            self.assertNotIn("\n## trap_hand-written", path.read_text("utf-8"))
            self.assertEqual([t["id"] for t in crumb.load_traps(mem)], ["trap_hand-written"])

    def test_a_conflicting_block_is_kept_and_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store(tmp)
            crumb.note(
                mem, Path(tmp), "trap", "somebody typed this in", fields={"slug": "hand-written"}
            )
            existing = (mem / "traps" / "hand-written.md").read_bytes()
            path = mem / "known-traps.md"
            path.write_text(path.read_text("utf-8") + self.BLOCK, encoding="utf-8")
            crumb.main(["reindex", "--project", tmp])
            # The file wins for reading, is never overwritten…
            self.assertEqual((mem / "traps" / "hand-written.md").read_bytes(), existing)
            # …and the block is kept below the index, not dropped.
            self.assertIn("A line of loose prose.", path.read_text("utf-8"))
            findings = [
                f for f in crumb.run_audit(mem, Path(tmp)) if f["check"] == "unadopted-block"
            ]
            self.assertEqual(len(findings), 1, findings)
            self.assertIn("trap_hand-written", findings[0]["message"])

    def test_an_identical_block_is_simply_absorbed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store(tmp)
            crumb.note(mem, Path(tmp), "question", "Is it safe?")
            qid = crumb.load_open_questions(mem)[0]["id"]
            question = crumb.find_questions_by_id(mem, qid)[0]
            before = Path(question["record_path"]).read_bytes()
            # Exactly what a schema-2 writer would have put in the block — the
            # shape a merge from an unmigrated branch brings in.
            block = f"\n## Q: Is it safe?\n{question['body']}\n"
            path = mem / "open-questions.md"
            path.write_text(path.read_text("utf-8") + block, encoding="utf-8")
            crumb.main(["reindex", "--project", tmp])
            after = Path(crumb.find_questions_by_id(mem, qid)[0]["record_path"]).read_bytes()
            self.assertEqual(after, before)
            self.assertNotIn("## Q: Is it safe?", path.read_text("utf-8"))
            self.assertEqual(len(crumb.load_open_questions(mem)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
