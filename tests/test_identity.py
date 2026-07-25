"""Tests for filename-canonical record identity (Phase 2, plan §7).

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


class MF23CanonicalityTests(unittest.TestCase):
    """Canonicality used to be `(\\d{4})-(\\d{2})-(\\d{2})-(.+)` — shape only (review #5 Low).

    Writers always emit clean names; validate §16.4 exists for hand-created files,
    which is exactly where an id like `dec_99999999_My Slug!` — spaces and
    punctuation inside an exact-match key — came from.
    """

    def test_MF23_impossible_dates_are_not_canonical(self):
        for stem in (
            "9999-99-99-slug",
            "2026-13-01-slug",
            "2026-02-30-slug",
            "2026-00-10-slug",
            "2026-01-32-slug",
        ):
            with self.subTest(stem=stem):
                self.assertIsNone(crumb.derive_identity(stem, "decision"))

    def test_MF23_real_dates_including_leap_day_are_canonical(self):
        self.assertIsNotNone(crumb.derive_identity("2024-02-29-leap", "decision"))
        self.assertIsNone(crumb.derive_identity("2026-02-29-not-leap", "decision"))

    def test_MF23_slug_is_restricted_to_the_slugify_charset(self):
        for stem in (
            "2026-01-02-My Slug!",
            "2026-01-02-Weird_Slug",
            "2026-01-02-has.dot",
            "2026-01-02--leading",
            "2026-01-02-trailing-",
        ):
            with self.subTest(stem=stem):
                self.assertIsNone(crumb.derive_identity(stem, "decision"))

    def test_MF23_writer_produced_names_stay_canonical(self):
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

    def test_MF23_validate_names_the_rule_it_enforces(self):
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
