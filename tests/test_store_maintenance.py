"""Migration and doctor fixes from the DoWhat retest of 0.5.0 (items 12-14).

- Item 12: `migrate` left the store's old template README (which said traps
  live in `known-traps.md`, by then a generated index) and the 0.1.x
  `evidence/refs.yml` that nothing reads.
- Item 13: `doctor` pointed a current store's validation failures at
  `crumb migrate`, which has nothing to fix there.
- Item 14: nothing could stop an older crumb-kit writing a store whose newer
  meaning it would damage (a 0.4.x capture replaces the Next Action log that
  0.5.0 keeps). Decision D14: `min_crumb_version`, set by migrate, with
  `requires: min-crumb-version` so builds that predate it refuse too.

Run with:  python -m unittest discover -s tests -p test_store_maintenance.py
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import compat  # noqa: E402
from breadcrumbs import migrate as mig  # noqa: E402

DATA = Path(__file__).resolve().parent / "data"
OLD_README = DATA / "template-README-0.2.0.md"
OLD_REFS = DATA / "scaffold-refs-0.1.7.yml"


def run(argv: list[str]) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue() + err.getvalue()


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        run(["init", "--project", str(self.root), "--session-tracking", "full"])
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def tearDown(self):
        self._tmp.cleanup()

    def remember(self) -> int:
        code, _out = run(
            [
                "remember",
                "decision",
                "--project",
                str(self.root),
                "--title",
                "Use the porpoise queue",
                "--set",
                "Decision",
                "Jobs go through the porpoise queue.",
                "--confidence",
                "low",
            ]
        )
        return code


def _lf(data: bytes) -> bytes:
    """A store file's text with line endings folded: stores write the platform's
    separator, and a Windows checkout holds the template with CRLF."""
    return data.replace(b"\r\n", b"\n")


class TemplateRefreshTests(Case):
    """Item 12."""

    def test_an_unedited_old_readme_is_replaced(self):
        (self.mem / "README.md").write_bytes(OLD_README.read_bytes())
        code, out = run(["migrate", "--project", str(self.root)])
        self.assertEqual(code, 0, out)
        self.assertEqual(
            _lf((self.mem / "README.md").read_bytes()),
            _lf((_cli.TEMPLATE_DIR / "README.md").read_bytes()),
        )
        self.assertIn("README.md: replaced", out)

    def test_a_crlf_template_on_windows_is_not_doubled(self):
        # A source checkout on Windows holds the template with CRLF, and every
        # store write uses the platform's separator: the README came out with
        # \r\r\n (the native-full Windows job, after the 0.6.1 merge).
        import os
        import shutil

        templates = Path(self._tmp.name) / "templates"
        shutil.copytree(_cli.TEMPLATE_DIR, templates)
        readme = templates / "README.md"
        readme.write_bytes(_lf(readme.read_bytes()).replace(b"\n", b"\r\n"))
        (self.mem / "README.md").write_bytes(OLD_README.read_bytes())
        with (
            mock.patch.object(_cli, "TEMPLATE_DIR", templates),
            mock.patch.object(os, "linesep", "\r\n"),
        ):
            code, out = run(["migrate", "--project", str(self.root)])
        self.assertEqual(code, 0, out)
        data = (self.mem / "README.md").read_bytes()
        self.assertNotIn(b"\r\r\n", data)
        self.assertEqual(_lf(data), _lf(readme.read_bytes()))

    def test_an_edited_readme_is_kept_with_a_warning(self):
        edited = OLD_README.read_text(encoding="utf-8") + "\nOur own note about the store.\n"
        (self.mem / "README.md").write_text(edited, encoding="utf-8")
        code, out = run(["migrate", "--project", str(self.root)])
        self.assertEqual(code, 0, out)
        self.assertEqual((self.mem / "README.md").read_text(encoding="utf-8"), edited)
        self.assertIn("warning: README.md: kept", out)

    def test_the_unedited_refs_scaffold_is_removed_and_an_edited_one_kept(self):
        refs = self.mem / "evidence" / "refs.yml"
        refs.parent.mkdir()
        refs.write_bytes(OLD_REFS.read_bytes())
        run(["migrate", "--project", str(self.root)])
        self.assertFalse(refs.exists())
        self.assertFalse(refs.parent.exists())
        refs.parent.mkdir()
        refs.write_text("refs:\n  - id: ref_npm_test\n    type: command\n    ref: npm test\n")
        code, out = run(["migrate", "--project", str(self.root)])
        self.assertTrue(refs.exists())
        self.assertIn("evidence/refs.yml: kept", out)

    def test_the_dry_run_lists_it_and_changes_nothing(self):
        (self.mem / "README.md").write_bytes(OLD_README.read_bytes())
        before = (self.mem / "manifest.yml").read_bytes()
        code, out = run(["migrate", "--dry-run", "--project", str(self.root)])
        self.assertEqual(code, 0, out)
        self.assertIn("README.md: replaced", out)
        self.assertEqual((self.mem / "README.md").read_bytes(), OLD_README.read_bytes())
        self.assertEqual((self.mem / "manifest.yml").read_bytes(), before)

    def test_an_older_store_is_refreshed_by_its_migration(self):
        _cli_migrate_store = self.mem / "manifest.yml"
        text = _cli_migrate_store.read_text(encoding="utf-8")
        _cli_migrate_store.write_text(
            text.replace("schema_version: 4", "schema_version: 3"), encoding="utf-8"
        )
        (self.mem / "README.md").write_bytes(OLD_README.read_bytes())
        res = mig.migrate(self.mem, self.root)
        self.assertTrue(res["ok"], res)
        self.assertEqual(
            _lf((self.mem / "README.md").read_bytes()),
            _lf((_cli.TEMPLATE_DIR / "README.md").read_bytes()),
        )


class DoctorRecordsLineTests(Case):
    """Item 13."""

    def _bad_record(self) -> None:
        (self.mem / "decisions" / "2026-09-20-hand-written.md").write_text(
            "# Hand-written decision\n\nWe chose the porpoise queue.\n", encoding="utf-8"
        )

    def test_a_current_store_points_at_repair(self):
        self._bad_record()
        _code, out = run(["doctor", "--project", str(self.root)])
        line = next(ln for ln in out.splitlines() if "validation failure" in ln)
        self.assertIn("crumb repair", line)
        self.assertNotIn("crumb migrate", line)

    def test_an_older_store_still_points_at_migrate(self):
        self._bad_record()
        manifest = self.mem / "manifest.yml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace("schema_version: 4", "schema_version: 3"),
            encoding="utf-8",
        )
        _code, out = run(["doctor", "--project", str(self.root)])
        line = next(ln for ln in out.splitlines() if "validation failure" in ln)
        self.assertIn("crumb migrate", line)


class MinimumWriterTests(Case):
    """Item 14, decision D14."""

    def _set_floor(self, value: str) -> None:
        mig.set_manifest_field(self.mem, compat.MIN_VERSION_KEY, value)

    def test_a_store_needing_a_newer_build_refuses_writes_and_says_why(self):
        self._set_floor("99.0")
        code, out = run(
            [
                "remember",
                "decision",
                "--project",
                str(self.root),
                "--title",
                "Use the porpoise queue",
                "--set",
                "Decision",
                "x",
                "--confidence",
                "low",
            ]
        )
        self.assertEqual(code, 1, out)
        self.assertIn("needs crumb-kit 99.0 or newer", out)
        self.assertFalse(list((self.mem / "decisions").glob("*.md")))
        # Reads still work, with the warning.
        code, out = run(["resume", "--project", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("99.0", out)

    def test_a_store_at_this_builds_floor_is_written(self):
        self._set_floor("0.5.0")
        self.assertEqual(self.remember(), 0)

    def test_migrate_sets_the_floor_and_the_bridge(self):
        run(["migrate", "--project", str(self.root)])
        manifest = _cli.load_manifest(self.mem)
        self.assertEqual(str(manifest[compat.MIN_VERSION_KEY]), compat.MIN_SAFE_WRITER)
        self.assertIn("min-crumb-version", compat.parse_features(manifest["requires"]))
        # It never lowers a floor set by hand.
        self._set_floor("0.7.1")
        with mock.patch.object(_cli, "get_version", return_value="0.8.0"):
            run(["migrate", "--project", str(self.root)])
        self.assertEqual(str(_cli.load_manifest(self.mem)[compat.MIN_VERSION_KEY]), "0.7.1")

    def test_a_build_that_predates_the_field_refuses_through_requires(self):
        run(["migrate", "--project", str(self.root)])
        old_features = compat.KNOWN_FEATURES - {"min-crumb-version"}
        with mock.patch.object(compat, "KNOWN_FEATURES", old_features):
            self.assertFalse(compat.check(self.mem).writable)
            self.assertNotEqual(self.remember(), 0)
        self.assertEqual(self.remember(), 0)

    def test_doctor_shows_the_floor(self):
        run(["migrate", "--project", str(self.root)])
        _code, out = run(["doctor", "--project", str(self.root), "--json"])
        checks = {c["check"]: c for c in json.loads(out)["checks"]}
        self.assertIn("min_writer", checks)
        self.assertIn(compat.MIN_SAFE_WRITER, checks["min_writer"]["detail"])

    def test_migrate_refuses_a_store_it_may_not_write(self):
        self._set_floor("99.0")
        before = (self.mem / "manifest.yml").read_bytes()
        code, out = run(["migrate", "--project", str(self.root)])
        self.assertEqual(code, 1)
        self.assertEqual((self.mem / "manifest.yml").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
