"""Tests for the frontmatter parser and Record model.

Run with:  python -m pytest tests/
       or:  python tests/test_parser.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402


FULL = """---
id: dec_20260625_x
type: decision
slug: x
title: Use repo-local Markdown
status: active
created_at: 2026-06-25T14:30:00-05:00
dirty_files: []
supersedes: []
superseded_by: null
reviewed_by:
expires_at: ~
confidence: medium
tags:
  - memory
  - architecture
evidence:
  - type: commit
    ref: abc1234
  - type: command
    ref: npm test
---
## Context
hello world

## Decision
do the thing
"""


class ParserTests(unittest.TestCase):
    def test_roundtrips_full_schema(self):
        meta, body = crumb.parse_frontmatter(FULL)
        self.assertEqual(meta["type"], "decision")
        self.assertEqual(meta["title"], "Use repo-local Markdown")
        # ISO datetime preserved verbatim as a string (no tz math)
        self.assertEqual(meta["created_at"], "2026-06-25T14:30:00-05:00")
        # inline + block empty lists
        self.assertEqual(meta["dirty_files"], [])
        self.assertEqual(meta["supersedes"], [])
        # nulls (explicit, empty, and ~)
        self.assertIsNone(meta["superseded_by"])
        self.assertIsNone(meta["reviewed_by"])
        self.assertIsNone(meta["expires_at"])
        # block list of scalars
        self.assertEqual(meta["tags"], ["memory", "architecture"])
        # block list of maps (evidence)
        self.assertEqual(
            meta["evidence"],
            [
                {"type": "commit", "ref": "abc1234"},
                {"type": "command", "ref": "npm test"},
            ],
        )
        self.assertIn("## Context", body)

    def test_no_frontmatter_returns_body_verbatim(self):
        text = "# Just a heading\n\nno frontmatter here\n"
        meta, body = crumb.parse_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_unterminated_fence_is_malformed(self):
        with self.assertRaises(crumb.FrontmatterError):
            crumb.parse_frontmatter("---\nkey: val\nno closing fence\n")

    def test_top_level_indentation_is_malformed(self):
        with self.assertRaises(crumb.FrontmatterError):
            crumb.parse_frontmatter("---\n  oops: indented\n---\nbody\n")

    def test_quoted_value_with_hash_is_preserved(self):
        meta, _ = crumb.parse_frontmatter('---\nref: "#42"\n---\n')
        self.assertEqual(meta["ref"], "#42")

    def test_inline_comment_stripped_on_unquoted_scalar(self):
        meta, _ = crumb.parse_frontmatter("---\nstatus: active   # the default\n---\n")
        self.assertEqual(meta["status"], "active")


class RecordModelTests(unittest.TestCase):
    def test_sections_split_on_h2(self):
        _, body = crumb.parse_frontmatter(FULL)
        rec = crumb.Record(Path("decisions/2026-06-25-x.md"), "decision", {}, body)
        self.assertEqual(set(rec.sections), {"Context", "Decision"})
        self.assertEqual(rec.sections["Context"], "hello world")

    def test_from_file_captures_parse_error(self):
        bad = REPO_ROOT / "tests" / "data" / "decisions" / "2026-06-25-malformed.md"
        rec = crumb.Record.from_file(bad, "decision")
        self.assertIsNotNone(rec.error)
        self.assertEqual(rec.meta, {})

    def test_load_records_walks_type_dirs(self):
        # Build a tiny store from a fresh init + a couple of fixtures.
        import tempfile, shutil  # noqa: E401

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            mem = root / crumb.MEMORY_DIRNAME
            data = REPO_ROOT / "tests" / "data"
            shutil.copy(data / "decisions" / "2026-06-25-good-decision.md", mem / "decisions")
            shutil.copy(data / "sessions" / "2026-06-25-good-session.md", mem / "sessions")
            recs = crumb.load_records(mem)
            types = sorted(r.rtype for r in recs)
            self.assertEqual(types, ["decision", "session"])
            # type filtering
            only_dec = crumb.load_records(mem, types=("decision",))
            self.assertEqual([r.rtype for r in only_dec], ["decision"])


FENCED_BODY = """## Tried
Ran the check.

```md
## Next Action
this heading is inside a fenced block — it is content, not a section
```

## Result
converged
"""


class FenceAwareSectionsTests(unittest.TestCase):
    """`Record.sections` was a second, fence-blind splitter.

    The R4 fence fix landed in `split_md_ordered`/`split_md_sections` and never
    reached `Record.sections`, so the two disagreed about any body carrying a
    fenced `## ` line — which record bodies routinely do
    (`--set 'Commands / Verification' …`).
    """

    def _rec(self, body: str, rtype: str = "session") -> "crumb.Record":
        return crumb.Record(Path(f"{rtype}s/2026-01-02-x.md"), rtype, {}, body)

    def test_a_fenced_heading_is_not_a_section(self):
        rec = self._rec(FENCED_BODY)
        self.assertEqual(list(rec.sections), ["Tried", "Result"])

    def test_agrees_with_the_other_splitter(self):
        for body in (
            FENCED_BODY,
            "## A\n1\n\n## B\n2\n",
            "no headings at all\n",
            "## A\n~~~\n## B\n~~~\ntail\n",
        ):
            with self.subTest(body=body[:20]):
                self.assertEqual(self._rec(body).sections, crumb.split_md_sections(body))

    def test_content_after_a_fenced_heading_is_not_lost(self):
        rec = self._rec(FENCED_BODY)
        self.assertIn("Next Action", rec.sections["Tried"])
        self.assertEqual(rec.sections["Result"], "converged")

    def test_duplicate_headings_are_merged_not_last_wins(self):
        """The dict view must not silently drop a body."""
        rec = self._rec("## Notes\nfirst\n\n## Notes\nsecond\n")
        self.assertIn("first", rec.sections["Notes"])
        self.assertIn("second", rec.sections["Notes"])

    def test_validate_sees_no_next_action_in_a_fence(self):
        """§16.10 false-passed a session whose only "Next Action" was fenced."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            mem = root / crumb.MEMORY_DIRNAME
            src = REPO_ROOT / "tests" / "data" / "sessions" / "2026-06-25-good-session.md"
            dst = mem / "sessions" / "2026-06-25-fenced.md"
            shutil.copy(src, dst)
            meta, _ = crumb.parse_frontmatter(dst.read_text(encoding="utf-8"))
            # No convergence/done marker anywhere: the *only* "Next Action" heading
            # is the one inside the fence, which is exactly the false pass.
            body = (
                "## Tried\nRan the check.\n\n"
                "```md\n## Next Action\nfinish the migration\n```\n\n"
                "## Result\nstill investigating\n"
            )
            dst.write_text(crumb.render_frontmatter(meta) + "\n" + body, encoding="utf-8")
            rec = crumb.Record.from_file(dst, "session")
            self.assertNotIn("Next Action", rec.sections)
            fails = [
                f
                for f in crumb.run_validate(mem)
                if f["status"] == "fail" and "2026-06-25-fenced.md" in (f["path"] or "")
            ]
            self.assertTrue(
                any("next action" in f["message"].lower() for f in fails),
                f"expected a §16.10 finding, got {[f['message'] for f in fails]}",
            )


class CommentOnlyValueTests(unittest.TestCase):
    """`superseded_by: # none yet` parsed as the literal string "# none yet".

    `_strip_inline_comment` needs a space before the `#`, so a value that is
    *only* a comment survived as truthy garbage that satisfied validate §16.6's
    "a superseded record needs a superseded_by" check.
    """

    def test_comment_only_value_is_null(self):
        meta, _ = crumb.parse_frontmatter("---\nsuperseded_by: # none yet\n---\nbody\n")
        self.assertIsNone(meta["superseded_by"])

    def test_trailing_comments_still_strip(self):
        meta, _ = crumb.parse_frontmatter("---\nstatus: active # for now\n---\nbody\n")
        self.assertEqual(meta["status"], "active")

    def test_a_quoted_hash_is_still_a_value(self):
        meta, _ = crumb.parse_frontmatter("---\ntitle: \"#hashtag\"\nother: '#x'\n---\nb\n")
        self.assertEqual(meta["title"], "#hashtag")
        self.assertEqual(meta["other"], "#x")

    def test_superseded_without_a_target_fails_validate(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            mem = root / crumb.MEMORY_DIRNAME
            src = REPO_ROOT / "tests" / "data" / "decisions" / "2026-06-25-good-decision.md"
            dst = mem / "decisions" / "2026-06-25-comment-only.md"
            shutil.copy(src, dst)
            meta, body = crumb.parse_frontmatter(dst.read_text(encoding="utf-8"))
            meta["status"] = "superseded"
            text = crumb.render_frontmatter(meta) + "\n" + body
            text = text.replace(
                "status: superseded", "status: superseded\nsuperseded_by: # none yet"
            )
            dst.write_text(text, encoding="utf-8")
            fails = [
                f
                for f in crumb.run_validate(mem)
                if f["status"] == "fail" and "comment-only" in (f["path"] or "")
            ]
            self.assertTrue(
                any("superseded_by" in f["message"] for f in fails),
                f"expected a §16.6 finding, got {[f['message'] for f in fails]}",
            )


class GlobalFlagPositionTests(unittest.TestCase):
    """Global flags must work whether placed BEFORE or AFTER the subcommand.

    Regression test for issue #3. The parent-parser globals (--project, --json,
    --plain, --verbose) were silently dropped when placed before the subcommand
    because argparse's _SubParsersAction.__call__ parses the subcommand into a
    fresh namespace and copies the subparser's *defaults* back over values the
    top-level parser already set.
    """

    def _parse(self, argv):
        return crumb.build_parser().parse_args(argv)

    def test_project_honored_before_subcommand(self):
        args = self._parse(["--project", "/tmp/store", "validate"])
        self.assertEqual(args.project, "/tmp/store")

    def test_project_honored_after_subcommand(self):
        args = self._parse(["validate", "--project", "/tmp/store"])
        self.assertEqual(args.project, "/tmp/store")

    def test_project_honored_before_nested_subcommand(self):
        args = self._parse(["--project", "/tmp/store", "remember", "decision", "--title", "x"])
        self.assertEqual(args.project, "/tmp/store")

    def test_json_honored_before_subcommand(self):
        self.assertTrue(self._parse(["--json", "validate"]).json)

    def test_verbose_honored_before_subcommand(self):
        self.assertTrue(self._parse(["--verbose", "validate"]).verbose)

    def test_plain_honored_before_subcommand(self):
        self.assertTrue(self._parse(["--plain", "search", "x"]).plain)

    def test_defaults_present_when_flags_absent(self):
        args = self._parse(["validate"])
        self.assertIsNone(args.project)
        self.assertFalse(args.json)
        self.assertFalse(args.plain)
        self.assertFalse(args.verbose)

    def test_global_project_targets_store_from_unrelated_cwd(self):
        """The real-world bug: from a cwd that is not the project, a global
        --project must still resolve to the store (not fail on cwd)."""
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            saved = os.getcwd()
            with tempfile.TemporaryDirectory() as other:
                try:
                    os.chdir(other)
                    rc = crumb.main(["--project", str(root), "validate"])
                finally:
                    os.chdir(saved)
            self.assertEqual(rc, 0)


class StartupCostTests(unittest.TestCase):
    """Startup work that every invocation paid for and almost none of it used.

    `build_parser()` constructed all ~20 subparsers before argparse looked at
    argv, and it resolved `--version` eagerly — which imports `importlib.metadata`
    and, transitively, `email`/`zipfile`/`csv`/`socket`. Both costs landed on the
    `hook guard` pre-filter that fires on every tool call. Measured on Linux
    (min of 25 interleaved runs): `crumb hook guard` 85.9 ms -> 52.4 ms against a
    13.3 ms bare-interpreter floor.
    """

    def _in_subprocess(self, code: str) -> str:
        import subprocess

        out = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_requested_command_finds_the_subcommand(self):
        cases = {
            (): None,
            ("guard", "rm -rf /"): "guard",
            ("--json", "guard", "x"): "guard",
            # the value of a value-taking global flag is not the subcommand …
            ("--project", "guard", "validate"): "validate",
            # … including when argparse's long-option abbreviation is used
            ("--proj", "guard", "validate"): "validate",
            ("--project=guard", "validate"): "validate",
            # unknown token -> full parser, so "invalid choice" lists everything
            ("nosuchcommand",): None,
            ("--", "validate"): None,
            ("--help",): None,
        }
        for argv, expected in cases.items():
            with self.subTest(argv=argv):
                self.assertEqual(crumb.requested_command(list(argv)), expected)

    def test_only_builds_one_subparser_but_parses_it_identically(self):
        lean = crumb.build_parser("guard")
        full = crumb.build_parser()
        self.assertEqual(
            vars(lean.parse_args(["guard", "delete the auth module"])),
            vars(full.parse_args(["guard", "delete the auth module"])),
        )

    def test_full_parser_still_offers_every_command(self):
        """`only` is an optimisation — the registry stays the complete set."""
        full = crumb.build_parser()
        sub = next(
            a for a in full._subparsers._group_actions if hasattr(a, "choices")
        )  # the subparsers action
        self.assertEqual(list(sub.choices), list(crumb._SUBCOMMAND_BUILDERS))

    def test_version_is_not_resolved_while_building_the_parser(self):
        """The eager `--version` string pulled in importlib.metadata + email + zipfile."""
        seen = self._in_subprocess(
            "import sys, breadcrumbs.cli as c\n"
            "c.build_parser()\n"
            "print(','.join(m for m in ('importlib.metadata','email','zipfile','csv')"
            " if m in sys.modules) or 'none')"
        )
        self.assertEqual(seen, "none")

    def test_version_output_is_unchanged(self):
        out = self._in_subprocess("import breadcrumbs.cli as c; c.main(['--version'])")
        self.assertRegex(out, r"^breadcrumbs \d+\.\d+\.\d+.* \(record schema_version \d+\)$")

    def test_secret_and_poison_patterns_compile_on_first_use(self):
        """~3.5 ms of module body that only `audit`/`scan-secrets` ever need."""
        state = self._in_subprocess(
            "import breadcrumbs.cli as c\n"
            "lazy = [p for _n, p in c.SECRET_PATTERNS] + list(c.INSTRUCTION_LIKE_PATTERNS)\n"
            "print(any(p._compiled is not None for p in lazy))"
        )
        self.assertEqual(state, "False")
        # …and they behave exactly like the compiled patterns they replaced.
        self.assertTrue(
            any(p.search("AKIAIOSFODNN7EXAMPLE") for _n, p in crumb.SECRET_PATTERNS),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
