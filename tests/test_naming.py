"""Tests for session naming: derived titles (R1) and collision-proof ids (R3).

R1: `--title` was optional and fell back to the constant `session`, so 280 of a
310-session field store carried no information in their title, id, slug or
filename — and `search` ranks on title. R3: the disambiguating ordinal is
derived from the files this checkout can see, so two agents working the same
day each wrote `2026-09-04-session.md` and git met them as an add/add conflict.

Run with:  python -m unittest discover -s tests
       or:  python tests/test_naming.py
"""

from __future__ import annotations

import contextlib
import io
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def init_store(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


def only_session(mem: Path) -> _cli.Record:
    paths = sorted((mem / "sessions").glob("*.md"))
    assert len(paths) == 1, paths
    return _cli.Record.from_file(paths[0], "session")


class DerivedTitleTests(unittest.TestCase):
    def test_a_session_with_no_title_is_named_from_its_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            code, out = run(
                [
                    "capture",
                    "session",
                    "--project",
                    tmp,
                    "--next",
                    "Merge this branch, then release 0.1.13. Nothing else is pending.",
                ]
            )
            self.assertEqual(code, 0, out)
            rec = only_session(mem)
            self.assertEqual(rec.meta["title"], "Merge this branch, then release 0.1.13")
            self.assertNotEqual(rec.meta["title"], _cli.SESSION_TITLE_FALLBACK)

    def test_focus_wins_over_the_next_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(
                [
                    "capture",
                    "session",
                    "--project",
                    tmp,
                    "--next",
                    "do the thing",
                    "--focus",
                    "signal-to-noise in the staleness warnings",
                ]
            )
            self.assertEqual(
                only_session(mem).meta["title"], "signal-to-noise in the staleness warnings"
            )

    def test_an_explicit_title_is_never_overridden(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(
                [
                    "capture",
                    "session",
                    "--project",
                    tmp,
                    "--next",
                    "derive me",
                    "--title",
                    "chosen by hand",
                ]
            )
            self.assertEqual(only_session(mem).meta["title"], "chosen by hand")

    def test_a_derived_title_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(["capture", "session", "--project", tmp, "--next", "word " * 200])
            self.assertLessEqual(len(only_session(mem).meta["title"]), _cli.SESSION_TITLE_MAX_CHARS)

    def test_placeholder_text_never_becomes_a_title(self):
        self.assertEqual(_cli._title_from_text("_(not recorded)_"), "")
        self.assertEqual(_cli._title_from_text(""), "")

    def test_a_commit_line_is_titled_by_its_subject_not_its_sha(self):
        title = _cli._title_from_text("- 4f1c2ab fix: staleness warnings stop reporting memory")
        self.assertEqual(title, "fix: staleness warnings stop reporting memory")

    def test_a_snapshot_with_nothing_to_derive_from_still_writes(self):
        """The fallback must remain — a machine snapshot may say nothing at all."""
        self.assertEqual(_cli._derive_session_title({}, None), "")


class UniqueSessionIdTests(unittest.TestCase):
    def test_two_sessions_with_the_same_title_get_different_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for _ in range(2):
                run(["capture", "session", "--project", tmp, "--next", "n", "--title", "same"])
            paths = sorted((mem / "sessions").glob("*.md"))
            self.assertEqual(len(paths), 2)
            self.assertNotEqual(paths[0].name, paths[1].name)

    def test_the_suffix_does_not_depend_on_what_this_checkout_can_see(self):
        """The ordinal did — which is why two checkouts produced the same name."""
        seen = {_cli._unique_suffix() for _ in range(200)}
        self.assertGreater(len(seen), 150)
        for suffix in seen:
            self.assertRegex(suffix, r"^[0-9a-f]{4}$")

    def test_session_names_stay_inside_the_slug_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(["capture", "session", "--project", tmp, "--next", "n", "--title", "x" * 200])
            stem = next(iter((mem / "sessions").glob("*.md"))).stem
            slug = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
            self.assertLessEqual(len(slug), _cli.SLUG_MAX_CHARS)

    def test_durable_records_keep_their_readable_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            run(
                [
                    "remember",
                    "decision",
                    "--project",
                    tmp,
                    "--title",
                    "use markdown",
                    "--confidence",
                    "low",
                ]
            )
            name = next(iter((mem / "decisions").glob("*.md"))).name
            self.assertTrue(name.endswith("-use-markdown.md"), name)


class RetitleTests(unittest.TestCase):
    def _one_session(self, tmp: str) -> tuple[Path, str]:
        mem = init_store(tmp)
        run(["capture", "session", "--project", tmp, "--next", "n", "--title", "session"])
        rec = only_session(mem)
        return mem, rec.meta["id"]

    def test_retitle_rewrites_the_searchable_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, rid = self._one_session(tmp)
            code, out = run(["retitle", rid, "cloud functions coverage matrix", "--project", tmp])
            self.assertEqual(code, 0, out)
            self.assertEqual(only_session(mem).meta["title"], "cloud functions coverage matrix")

    def test_retitle_leaves_identity_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem, rid = self._one_session(tmp)
            before = only_session(mem).path.name
            run(["retitle", rid, "a new name", "--project", tmp])
            after = only_session(mem)
            self.assertEqual(after.path.name, before)
            self.assertEqual(after.meta["id"], rid)

    def test_retitle_of_an_unknown_id_fails_cleanly(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, _ = run(["retitle", "ses_20260101_nope", "x", "--project", tmp])
            self.assertEqual(code, 1)

    def test_retitle_refuses_an_empty_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mem, rid = self._one_session(tmp)
            code, _ = run(["retitle", rid, "   ", "--project", tmp])
            self.assertEqual(code, 1)


class MarkStatusFlagTests(unittest.TestCase):
    def _one_decision(self, tmp: str) -> str:
        init_store(tmp)
        run(
            [
                "remember",
                "decision",
                "--project",
                tmp,
                "--title",
                "d",
                "--confidence",
                "low",
            ]
        )
        mem = Path(tmp) / crumb.MEMORY_DIRNAME
        path = next(iter((mem / "decisions").glob("*.md")))
        return _cli.Record.from_file(path, "decision").meta["id"]

    def test_status_flag_is_accepted_like_the_positional(self):
        with tempfile.TemporaryDirectory() as tmp:
            rid = self._one_decision(tmp)
            code, out = run(["mark-status", rid, "--status", "stale", "--project", tmp])
            self.assertEqual(code, 0, out)
            self.assertIn("-> stale", out)

    def test_the_positional_still_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            rid = self._one_decision(tmp)
            code, out = run(["mark-status", rid, "stale", "--project", tmp])
            self.assertEqual(code, 0, out)

    def test_no_status_at_all_is_an_error_that_names_the_vocabulary(self):
        with tempfile.TemporaryDirectory() as tmp:
            rid = self._one_decision(tmp)
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = crumb.main(["mark-status", rid, "--project", tmp])
            self.assertEqual(code, 2)
            self.assertIn("stale", err.getvalue())

    def test_two_conflicting_statuses_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            rid = self._one_decision(tmp)
            code, _ = run(["mark-status", rid, "stale", "--status", "disputed", "--project", tmp])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
