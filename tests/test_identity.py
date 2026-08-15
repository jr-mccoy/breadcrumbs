"""Tests for filename-canonical record identity.

Run with:  python -m pytest tests/
       or:  python tests/test_identity.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402


class IdentityTests(unittest.TestCase):
    def test_decision_prefix(self):
        self.assertEqual(
            crumb.derive_identity("2026-06-25-repo-local-memory", "decision"),
            ("dec_20260625_repo-local-memory", "repo-local-memory"),
        )

    def test_all_type_prefixes(self):
        cases = {
            "decision": "dec",
            "attempt": "att",
            "idea": "idea",
            "session": "ses",
            "trap": "trap",
            "question": "q",
        }
        for rtype, prefix in cases.items():
            rid, slug = crumb.derive_identity("2026-01-02-thing", rtype)
            self.assertEqual(rid, f"{prefix}_20260102_thing")
            self.assertEqual(slug, "thing")

    def test_slug_keeps_internal_hyphens(self):
        rid, slug = crumb.derive_identity("2026-12-31-a-b-c", "attempt")
        self.assertEqual(slug, "a-b-c")
        self.assertEqual(rid, "att_20261231_a-b-c")

    def test_non_canonical_filename_returns_none(self):
        self.assertIsNone(crumb.derive_identity("not-a-dated-file", "decision"))
        self.assertIsNone(crumb.derive_identity("2026-6-5-bad-date", "decision"))


class CanonicalityTests(unittest.TestCase):
    """Canonicality used to be `(\\d{4})-(\\d{2})-(\\d{2})-(.+)` — shape only.

    Writers always emit clean names; validate §16.4 exists for hand-created files,
    which is exactly where an id like `dec_99999999_My Slug!` — spaces and
    punctuation inside an exact-match key — came from.
    """

    def test_impossible_dates_are_not_canonical(self):
        for stem in (
            "9999-99-99-slug",
            "2026-13-01-slug",
            "2026-02-30-slug",
            "2026-00-10-slug",
            "2026-01-32-slug",
        ):
            with self.subTest(stem=stem):
                self.assertIsNone(crumb.derive_identity(stem, "decision"))

    def test_real_dates_including_leap_day_are_canonical(self):
        self.assertIsNotNone(crumb.derive_identity("2024-02-29-leap", "decision"))
        self.assertIsNone(crumb.derive_identity("2026-02-29-not-leap", "decision"))

    def test_slug_is_restricted_to_the_slugify_charset(self):
        for stem in (
            "2026-01-02-My Slug!",
            "2026-01-02-Weird_Slug",
            "2026-01-02-has.dot",
            "2026-01-02--leading",
            "2026-01-02-trailing-",
        ):
            with self.subTest(stem=stem):
                self.assertIsNone(crumb.derive_identity(stem, "decision"))

    def test_writer_produced_names_stay_canonical(self):
        """Whatever `slugify` + `_unique_record_path` can emit must still parse."""
        for title in (
            "A Decision: with punctuation!",
            "  spaces  everywhere  ",
            "MiXeD CaSe 123",
            "—— nothing usable ——",
        ):
            slug = crumb.slugify(title)
            with self.subTest(title=title):
                self.assertIsNotNone(crumb.derive_identity(f"2026-01-02-{slug}", "decision"))
                # …including the same-day collision suffix.
                self.assertIsNotNone(crumb.derive_identity(f"2026-01-02-{slug}-2", "decision"))

    def test_validate_names_the_rule_it_enforces(self):
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            mem = root / crumb.MEMORY_DIRNAME
            good = REPO_ROOT / "tests" / "data" / "decisions" / "2026-06-25-good-decision.md"
            shutil.copy(good, mem / "decisions" / "9999-99-99-My Slug!.md")
            findings = crumb.run_validate(mem)
            ident = [f for f in findings if f["check"] == "identity" and f["status"] == "fail"]
            self.assertTrue(ident, "an impossible date must fail validate §16.4")
            self.assertIn("real calendar date", ident[0]["message"])


class SlugLengthTests(unittest.TestCase):
    """A sentence-length title must not become a sentence-length path.

    `slugify` had no cap, so the whole title landed in the filename: past ~240
    characters `remember` failed with ENAMETOOLONG on Linux, and long before that
    `<repo>/.project-memory/<type>/<name>` pushed a Windows checkout past
    MAX_PATH, so `git clone` failed on a repo that had committed one.
    """

    LONG_TITLE = (
        "Consider whether we should cache the parsed session index inside the "
        "auth middleware layer instead of recomputing it on every single request"
    )

    def test_generated_filename_is_capped(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            mem = root / crumb.MEMORY_DIRNAME
            code = crumb.main(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    self.LONG_TITLE,
                    "--confidence",
                    "low",
                ]
            )
            self.assertEqual(code, 0)
            path = next((mem / "decisions").glob("*.md"))
            slug = path.stem[len("2026-01-02-") :]
            self.assertLessEqual(len(slug), crumb.SLUG_MAX_CHARS)
            # The full text is not lost — it lives in `title`.
            meta, _ = crumb.parse_frontmatter(path.read_text(encoding="utf-8"))
            self.assertEqual(meta["title"], self.LONG_TITLE)
            self.assertIsNotNone(crumb.derive_identity(path.stem, "decision"))

    def test_a_title_too_long_for_the_filesystem_still_writes(self):
        """The pre-fix failure mode: ENAMETOOLONG straight out of `remember`."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            code = crumb.main(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    self.LONG_TITLE * 3,
                    "--confidence",
                    "low",
                ]
            )
            self.assertEqual(code, 0)

    def test_collision_suffixes_stay_inside_the_cap(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            mem = root / crumb.MEMORY_DIRNAME
            for _ in range(3):
                crumb.main(
                    [
                        "remember",
                        "decision",
                        "--project",
                        str(root),
                        "--title",
                        self.LONG_TITLE,
                        "--confidence",
                        "low",
                    ]
                )
            names = sorted(p.stem for p in (mem / "decisions").glob("*.md"))
            self.assertEqual(len(names), 3, names)
            for stem in names:
                slug = stem[len("2026-01-02-") :]
                self.assertLessEqual(len(slug), crumb.SLUG_MAX_CHARS, stem)
                self.assertIsNotNone(crumb.derive_identity(stem, "decision"), stem)
            self.assertTrue(any(s.endswith("-2") for s in names), names)
            self.assertTrue(any(s.endswith("-3") for s in names), names)

    def test_truncation_stays_canonical(self):
        for title in (
            self.LONG_TITLE,
            "a" * 200,
            "x-" * 100,
            "short",
            "—— nothing usable ——",
        ):
            slug = crumb.truncate_slug(crumb.slugify(title))
            with self.subTest(title=title[:24]):
                self.assertTrue(slug)
                self.assertLessEqual(len(slug), crumb.SLUG_MAX_CHARS)
                self.assertIsNotNone(crumb.derive_identity(f"2026-01-02-{slug}", "decision"))

    def test_records_already_on_disk_with_long_names_still_load(self):
        """The cap must not orphan anything a pre-cap version already wrote."""
        import shutil
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
            mem = root / crumb.MEMORY_DIRNAME
            good = REPO_ROOT / "tests" / "data" / "decisions" / "2026-06-25-good-decision.md"
            long_slug = "-".join(f"word{i}" for i in range(20))
            self.assertGreater(len(long_slug), crumb.SLUG_MAX_CHARS)
            legacy = mem / "decisions" / f"2026-06-25-{long_slug}.md"
            text = good.read_text(encoding="utf-8")
            meta, body = crumb.parse_frontmatter(text)
            rid, slug = crumb.derive_identity(legacy.stem, "decision")
            meta["id"], meta["slug"] = rid, slug
            legacy.write_text(crumb.render_frontmatter(meta) + "\n" + body, encoding="utf-8")
            shutil.copy(good, mem / "decisions" / good.name)

            loaded = {r.path.name: r for r in crumb.load_records(mem)}
            self.assertIn(legacy.name, loaded)
            self.assertEqual(loaded[legacy.name].meta["id"], rid)
            ident = [
                f
                for f in crumb.run_validate(mem)
                if f["check"] == "identity" and f["status"] == "fail"
            ]
            self.assertEqual(ident, [], "a long legacy name must still validate")


class SlugTailTests(unittest.TestCase):
    """P2-15 (0.1.10 field test): a truncated slug must not end on a function
    word ('…-is-nullable-with-no') — it reads as a corrupted id."""

    def test_truncated_slug_drops_trailing_function_words(self):
        slug = crumb.slugify(
            "the response payload is nullable with no fallback when the peer is offline"
        )
        cut = crumb.truncate_slug(slug, 40)
        self.assertFalse(
            cut.endswith(("-with", "-no", "-and", "-the", "-is", "-a")),
            cut,
        )

    def test_untruncated_slug_is_never_rewritten(self):
        # An author's own short title may legitimately end on a function word.
        self.assertEqual(crumb.truncate_slug("say-no"), "say-no")

    def test_result_stays_canonical(self):
        cut = crumb.truncate_slug(crumb.slugify("keep the flex window and the period and a"), 30)
        self.assertRegex(cut, r"^[a-z0-9]+(-[a-z0-9]+)*$")


if __name__ == "__main__":
    unittest.main(verbosity=2)
