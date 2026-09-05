"""Tests for `--set` heading normalization (C1).

A wrong heading used to raise, and the raise aborted the *whole* call — every
other `--set` on the command line went with it. Content an agent has already
written is the most expensive thing in the system to reproduce, so the rule is:
match generously, park what cannot be matched, and say what happened.

Run with:  python -m unittest discover -s tests
       or:  python tests/test_sections.py
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import mcp_core  # noqa: E402


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


def init_store(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


class NormalizeSectionsTests(unittest.TestCase):
    def test_exact_headings_pass_through_unchanged(self):
        sections, notes = _cli.normalize_sections("decision", {"Context": "c", "Decision": "d"})
        self.assertEqual(sections, {"Context": "c", "Decision": "d"})
        self.assertEqual(notes, [])

    def test_case_space_and_punctuation_are_ignored(self):
        for spelling in ("Attempts / Failures", "attempts/failures", "ATTEMPTS  FAILURES"):
            sections, _ = _cli.normalize_sections("session", {spelling: "x"})
            self.assertEqual(list(sections), ["Attempts / Failures"], spelling)

    def test_obvious_synonyms_resolve(self):
        sections, notes = _cli.normalize_sections("session", {"Summary": "x"})
        self.assertEqual(sections, {"Work Completed": "x"})
        self.assertTrue(notes)

    def test_unmatched_heading_is_parked_with_its_original_name(self):
        sections, notes = _cli.normalize_sections(
            "session", [("Findings", "a"), ("Next Action", "b")]
        )
        self.assertEqual(sections["Next Action"], "b")
        self.assertIn("### Findings", sections[_cli.UNSORTED_SECTION])
        self.assertIn("a", sections[_cli.UNSORTED_SECTION])
        self.assertTrue(any("Findings" in n for n in notes))

    def test_several_unmatched_headings_all_survive(self):
        sections, _ = _cli.normalize_sections("idea", [("One", "1"), ("Two", "2")])
        parked = sections[_cli.UNSORTED_SECTION]
        self.assertIn("### One", parked)
        self.assertIn("### Two", parked)

    def test_normalization_is_idempotent(self):
        once, _ = _cli.normalize_sections("session", {"Summary": "x", "Bogus": "y"})
        twice, notes = _cli.normalize_sections("session", once)
        self.assertEqual(once, twice)
        self.assertEqual(notes, [])

    def test_parked_content_is_rendered_into_the_body(self):
        body = _cli.render_body(
            "session", {"Next Action": "n", _cli.UNSORTED_SECTION: "### X\n\nv"}
        )
        self.assertIn("## Next Action", body)
        self.assertIn(f"## {_cli.UNSORTED_SECTION}", body)
        # Never ahead of the vocabulary a reader is scanning for.
        self.assertLess(body.index("## Next Action"), body.index(f"## {_cli.UNSORTED_SECTION}"))


class CaptureSessionSetTests(unittest.TestCase):
    def test_one_bad_heading_does_not_discard_the_rest_of_the_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            code, out, err = run(
                [
                    "capture",
                    "session",
                    "--project",
                    tmp,
                    "--title",
                    "field review",
                    "--next",
                    "ship it",
                    "--set",
                    "Summary",
                    "eight hundred words",
                    "--set",
                    "Findings",
                    "six hundred words",
                ]
            )
            self.assertEqual(code, 0, out + err)
            body = next(iter((mem / "sessions").glob("*.md"))).read_text(encoding="utf-8")
            self.assertIn("eight hundred words", body)
            self.assertIn("six hundred words", body)
            self.assertIn(_cli.WARN_PREFIX, err)

    def test_warnings_are_on_stderr_not_in_json_stdout(self):
        import json

        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out, err = run(
                [
                    "capture",
                    "session",
                    "--project",
                    tmp,
                    "--json",
                    "--title",
                    "t",
                    "--next",
                    "n",
                    "--set",
                    "Nope",
                    "v",
                ]
            )
            self.assertEqual(code, 0, out + err)
            payload = json.loads(out)  # stdout stays a parseable document
            self.assertTrue(payload["warnings"])


class RecordWriterTests(unittest.TestCase):
    def test_the_mcp_record_tool_parks_instead_of_silently_dropping(self):
        """`render_body` walks the vocabulary, so an unknown heading used to vanish."""
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            result = mcp_core.tool_record(
                "decision",
                {
                    "title": "t",
                    "confidence": "low",
                    "sections": {"Decision": "kept", "Mystery": "would have been lost"},
                },
                root=tmp,
            )
            self.assertTrue(result.get("ok", True), result)
            body = (Path(tmp) / crumb.MEMORY_DIRNAME / result["path"]).read_text(encoding="utf-8")
            self.assertIn("kept", body)
            self.assertIn("would have been lost", body)
            self.assertIn("### Mystery", body)


if __name__ == "__main__":
    unittest.main()
