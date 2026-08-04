"""Tests for `crumb search` — deterministic exact/keyword/tag/file lookup (Phase 5).

Run with:  python -m pytest tests/
       or:  python -m unittest discover -s tests
       or:  python tests/test_search.py

Search is the permissive lookup layer (min_keyword=1); `guard` is the cautious
gate built on top of it (tested in test_guard.py). No embeddings — every result
is an exact text / tag / file-path / component overlap, and the same input always
produces the same output.
"""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402

FIXTURES = REPO_ROOT / "fixtures"


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def copy_fixture(name: str, dest_parent: str) -> Path:
    """Copy a committed fixture's .project-memory into a NON-git tmp dir.

    A plain copy yields the (no-git) sentinels, so assertions are about content,
    not this repo's branch/commit (mirrors test_resume.copy_fixture)."""
    dest = Path(dest_parent)
    shutil.copytree(FIXTURES / name / ".project-memory", dest / crumb.MEMORY_DIRNAME)
    return dest


class SearchSignalTests(unittest.TestCase):
    """A match must come from a real signal: text, tag, or file path."""

    def test_keyword_match_returns_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-02-guard-true-positive", tmp)
            code, out = run(["search", "auth middleware", "--project", str(root), "--json"])
            self.assertEqual(code, 0)
            ids = {m["id"] for m in json.loads(out)["matches"]}
            self.assertIn("att_20260612_auth-middleware-rewrite", ids)

    def test_tag_filter_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-02-guard-true-positive", tmp)
            code, out = run(["search", "--tag", "session", "--project", str(root), "--json"])
            self.assertEqual(code, 0)
            ids = {m["id"] for m in json.loads(out)["matches"]}
            self.assertIn("dec_20260610_session-parser-contract", ids)
            self.assertNotIn("att_20260612_auth-middleware-rewrite", ids)

    def test_file_path_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-02-guard-true-positive", tmp)
            code, out = run(["search", "src/auth/middleware.ts", "--project", str(root), "--json"])
            self.assertEqual(code, 0)
            matches = json.loads(out)["matches"]
            top = matches[0]
            self.assertEqual(top["id"], "att_20260612_auth-middleware-rewrite")
            self.assertIn("file", top["signals"])

    def test_type_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-02-guard-true-positive", tmp)
            _, out = run(["search", "auth", "--type", "attempt", "--project", str(root), "--json"])
            kinds = {m["kind"] for m in json.loads(out)["matches"]}
            self.assertEqual(kinds, {"attempt"})

    def test_unrelated_query_returns_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-02-guard-true-positive", tmp)
            _, out = run(["search", "kubernetes helm chart", "--project", str(root), "--json"])
            self.assertEqual(json.loads(out)["matches"], [])

    def test_superseded_records_are_searchable(self):
        """Search is a lookup; it finds superseded records too (guard demotes them)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-05-superseded-decision", tmp)
            _, out = run(["search", "auth token", "--project", str(root), "--json"])
            by_id = {m["id"]: m for m in json.loads(out)["matches"]}
            self.assertIn("dec_20260501_auth-token-in-url", by_id)
            self.assertEqual(by_id["dec_20260501_auth-token-in-url"]["status"], "superseded")


class DeterminismTests(unittest.TestCase):
    def test_same_input_same_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-02-guard-true-positive", tmp)
            _, a = run(["search", "auth session", "--project", str(root), "--json"])
            _, b = run(["search", "auth session", "--project", str(root), "--json"])
            self.assertEqual(a, b)


class HumanOutputTests(unittest.TestCase):
    def test_human_output_lists_ids_and_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-02-guard-true-positive", tmp)
            _, out = run(["search", "auth middleware", "--project", str(root)])
            self.assertIn("att_20260612_auth-middleware-rewrite", out)
            self.assertIn("score", out)

    def test_no_memory_errors_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(["search", "anything", "--project", tmp])
            self.assertEqual(code, 2)


# --------------------------------------------------------------------------- #
# MF-18 — candidate ids must be unique (audit #6 N6)
# --------------------------------------------------------------------------- #
Q_COLUMNAR = "Should we migrate the reporting pipeline to the new columnar store this quarter"
Q_ROW = "Should we migrate the reporting pipeline to the new row store next quarter"


class QuestionIdCollisionTests(unittest.TestCase):
    """Question ids were `q:` + the first 48 characters of the slug.

    Two distinct questions sharing that prefix collapsed to one id, and `search`'s
    by_id map kept only the last — which `guard`'s `_recommended_action` resolves
    through, so one question's advice was silently served for another's.
    """

    def _store_with_questions(self, tmp: str, questions) -> Path:
        root = Path(tmp)
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
        mem = root / crumb.MEMORY_DIRNAME
        for q in questions:
            crumb.note(mem, root, "question", q, fields={}, tags=[], agent="test")
        return mem

    def test_MF18_colliding_prefixes_get_distinct_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store_with_questions(tmp, (Q_COLUMNAR, Q_ROW))
            ids = [i["id"] for i in crumb._candidate_items(mem) if i["kind"] == "question"]
            self.assertEqual(len(ids), 2)
            self.assertEqual(len(set(ids)), 2, ids)

    def test_MF18_search_by_id_map_keeps_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._store_with_questions(tmp, (Q_COLUMNAR, Q_ROW))
            _, out = run(["search", "columnar store quarter", "--project", str(root), "--json"])
            payload = json.loads(out)
            ids = [m["id"] for m in payload["matches"]]
            titles = {m["title"] for m in payload["matches"]}
            self.assertEqual(len(ids), len(set(ids)), ids)
            self.assertIn(Q_COLUMNAR, titles)
            self.assertIn(Q_ROW, titles)

    def test_MF18_short_question_ids_are_unchanged(self):
        """Only truncated slugs get a digest; existing short ids must not churn."""
        short = "Should the worker own its own schema migrations"
        self.assertEqual(crumb.question_item_id(short), "q:" + crumb.slugify(short))
        self.assertLessEqual(len(crumb.slugify(short)), crumb.QUESTION_SLUG_CHARS)

    def test_MF18_ids_are_deterministic(self):
        self.assertEqual(crumb.question_item_id(Q_ROW), crumb.question_item_id(Q_ROW))

    def test_MF18_residual_collisions_are_still_disambiguated(self):
        """The backstop: identical ids from any source get -2, -3, … suffixes."""
        items = [{"id": "trap_x"}, {"id": "trap_x"}, {"id": "trap_x"}, {"id": "trap_y"}]
        out = [i["id"] for i in crumb._disambiguate_item_ids(items)]
        self.assertEqual(out, ["trap_x", "trap_x-2", "trap_x-3", "trap_y"])


IDEA_ID = "idea_20260620_cache-parsed-sessions-in-the-auth-middleware"


class SearchableIdeasTests(unittest.TestCase):
    """MF-57 / O1 — `ideas/` joins the lookup corpus, and only the lookup corpus.

    `crumb note idea` has always written a real, validated record that nothing
    loaded, so an idea could be found only by opening the directory. Fixture 12 is
    the control: a store whose *only* record is an untried hunch naming the file
    an action would touch.
    """

    def test_idea_is_found_by_keyword(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-12-speculative-idea", tmp)
            code, out = run(["search", "auth middleware cache", "--project", str(root), "--json"])
            self.assertEqual(code, 0)
            matches = json.loads(out)["matches"]
            self.assertEqual([m["id"] for m in matches], [IDEA_ID])
            self.assertEqual(matches[0]["kind"], "idea")

    def test_type_idea_filter_is_offered_and_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-12-speculative-idea", tmp)
            code, out = run(["search", "--type", "idea", "--project", str(root), "--json"])
            self.assertEqual(code, 0)
            self.assertEqual([m["id"] for m in json.loads(out)["matches"]], [IDEA_ID])

    def test_idea_is_found_by_the_file_it_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = copy_fixture("fixture-12-speculative-idea", tmp)
            code, out = run(
                ["search", "--file", "src/auth/middleware.ts", "--project", str(root), "--json"]
            )
            self.assertEqual(code, 0)
            self.assertIn(IDEA_ID, [m["id"] for m in json.loads(out)["matches"]])

    def test_corpus_switch_defaults_to_the_narrow_one(self):
        """A caller that forgets the flag gets guard's corpus — the safe mistake."""
        mem = FIXTURES / "fixture-12-speculative-idea" / ".project-memory"
        narrow = {i["id"] for i in crumb._candidate_items(mem)}
        wide = {i["id"] for i in crumb._candidate_items(mem, include_ideas=True)}
        self.assertNotIn(IDEA_ID, narrow)
        self.assertEqual(wide - narrow, {IDEA_ID})

    def test_sessions_stay_out_of_both_corpora(self):
        """Only `ideas/` moved. Sessions are absent from a distillate clone, so
        including them would make results depend on which checkout you ran in."""
        mem = FIXTURES / "fixture-10-many-sessions" / ".project-memory"
        self.assertTrue((mem / "sessions").is_dir())
        for kwargs in ({}, {"include_ideas": True}):
            kinds = {i["kind"] for i in crumb._candidate_items(mem, **kwargs)}
            self.assertNotIn("session", kinds)


if __name__ == "__main__":
    unittest.main(verbosity=2)
