"""Tests for `crumb migrate` and the schema-version gate (WM-01).

The machinery that makes a store-format change safe to ship: ordered idempotent
steps, a manifest written after each one, a backup before any of them, and a
`validate` finding that names the right remedy in each direction.

Run with:  python -m pytest tests/
       or:  python tests/test_migrate.py
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
from breadcrumbs import cli as _cli  # noqa: E402  (patch target: migrate reads SCHEMA_VERSION here)
from breadcrumbs import migrate as mig  # noqa: E402


def init_store(tmp: str) -> Path:
    root = Path(tmp)
    with contextlib.redirect_stdout(io.StringIO()):
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = crumb.main(argv)
    return code, buf.getvalue()


def set_version(mem: Path, version) -> None:
    text = (mem / "manifest.yml").read_text(encoding="utf-8")
    lines = [
        f"schema_version: {version}" if ln.startswith("schema_version:") else ln
        for ln in text.splitlines()
    ]
    (mem / "manifest.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")


class VersionReadWriteTests(unittest.TestCase):
    def test_fresh_store_is_at_the_current_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            self.assertEqual(mig.store_schema_version(mem), crumb.SCHEMA_VERSION)

    def test_missing_schema_version_reads_as_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            text = (mem / "manifest.yml").read_text(encoding="utf-8")
            kept = [ln for ln in text.splitlines() if not ln.startswith("schema_version:")]
            (mem / "manifest.yml").write_text("\n".join(kept) + "\n", encoding="utf-8")
            self.assertEqual(mig.store_schema_version(mem), 1)

    def test_no_manifest_reads_as_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            (mem / "manifest.yml").unlink()
            self.assertIsNone(mig.store_schema_version(mem))

    def test_set_version_preserves_every_other_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            before = (mem / "manifest.yml").read_text(encoding="utf-8").splitlines()
            mig.set_manifest_version(mem, 7)
            after = (mem / "manifest.yml").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(before), len(after))
            self.assertIn("schema_version: 7", after)
            # Every non-version line — the comments `init` wrote, and any key a
            # newer build added that this one does not know about — survives.
            self.assertEqual(
                [ln for ln in before if not ln.startswith("schema_version:")],
                [ln for ln in after if not ln.startswith("schema_version:")],
            )


class MigrationDriverTests(unittest.TestCase):
    def test_nothing_to_do_is_a_clean_no_op(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            before = (mem / "manifest.yml").read_bytes()
            res = mig.migrate(mem, Path(tmp))
            self.assertTrue(res["ok"])
            self.assertEqual(res["from"], res["to"])
            self.assertEqual(res["steps"], [])
            self.assertIsNone(res["backup"])
            self.assertEqual((mem / "manifest.yml").read_bytes(), before)

    def test_steps_apply_in_order_and_the_manifest_lands_at_the_target(self):
        order = []

        def step_a(mem, root):
            order.append("a")
            return ["did a"]

        def step_b(mem, root):
            order.append("b")
            # The previous step's version is already committed when this runs.
            self.assertEqual(mig.store_schema_version(mem), 8)
            return ["did b"]

        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, 7)
            fake = [mig.Migration(8, "step a", step_a), mig.Migration(9, "step b", step_b)]
            with (
                mock.patch.object(mig, "MIGRATIONS", fake),
                mock.patch.object(_cli, "SCHEMA_VERSION", 9),
            ):
                res = mig.migrate(mem, Path(tmp))
            self.assertTrue(res["ok"], res)
            self.assertEqual(order, ["a", "b"])
            self.assertEqual(res["from"], 7)
            self.assertEqual(res["to"], 9)
            self.assertEqual([s["version"] for s in res["steps"]], [8, 9])
            self.assertEqual(mig.store_schema_version(mem), 9)

    def test_a_failing_step_halts_at_the_last_completed_version(self):
        def step_a(mem, root):
            return ["did a"]

        def step_b(mem, root):
            raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, 7)
            fake = [mig.Migration(8, "step a", step_a), mig.Migration(9, "step b", step_b)]
            with (
                mock.patch.object(mig, "MIGRATIONS", fake),
                mock.patch.object(_cli, "SCHEMA_VERSION", 9),
            ):
                res = mig.migrate(mem, Path(tmp))
            self.assertFalse(res["ok"])
            self.assertIn("boom", res["error"])
            # The store is at 8, not 7 and not 9: step a really did happen and
            # step b really did not.
            self.assertEqual(res["to"], 8)
            self.assertEqual(mig.store_schema_version(mem), 8)

    def test_backup_holds_the_pre_migration_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            (mem / "current.md").write_text("# Current State\n\nbefore\n", encoding="utf-8")
            set_version(mem, 7)

            def step(mem_, root_):
                (mem_ / "current.md").write_text("# Current State\n\nafter\n", encoding="utf-8")
                return ["rewrote current.md"]

            with (
                mock.patch.object(mig, "MIGRATIONS", [mig.Migration(8, "rewrite", step)]),
                mock.patch.object(_cli, "SCHEMA_VERSION", 8),
            ):
                res = mig.migrate(mem, Path(tmp))
            self.assertTrue(res["ok"], res)
            backup = Path(res["backup"])
            self.assertIn("before", (backup / "current.md").read_text(encoding="utf-8"))
            self.assertIn("after", (mem / "current.md").read_text(encoding="utf-8"))
            # The backup lives under private/, which is never committed.
            self.assertEqual(backup.relative_to(mem).parts[0], "private")

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, crumb.SCHEMA_VERSION - 1)
            before = (mem / "manifest.yml").read_bytes()
            res = mig.migrate(mem, Path(tmp), dry_run=True)
            self.assertTrue(res["ok"])
            self.assertTrue(res["steps"])
            self.assertIsNone(res["backup"])
            self.assertEqual((mem / "manifest.yml").read_bytes(), before)
            self.assertFalse((mem / "private" / "migrations").exists())

    def test_a_newer_store_is_refused_not_downgraded(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, crumb.SCHEMA_VERSION + 5)
            res = mig.migrate(mem, Path(tmp))
            self.assertFalse(res["ok"])
            self.assertIn("Upgrade crumb-kit", res["error"])
            self.assertEqual(mig.store_schema_version(mem), crumb.SCHEMA_VERSION + 5)

    def test_migration_does_not_invent_a_generated_directory(self):
        """A format upgrade must not create a committed artifact the store lacks.

        Several fixtures deliberately ship no `generated/`; a migration that
        wrote one would change what those stores are.
        """
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for p in (mem / "generated").glob("*"):
                p.unlink()
            (mem / "generated").rmdir()
            set_version(mem, 1)
            res = mig.migrate(mem, Path(tmp))
            self.assertTrue(res["ok"], res)
            self.assertFalse((mem / "generated").exists())


class InboxMigrationTests(unittest.TestCase):
    def test_schema_two_creates_both_inboxes_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for d in ("inbox", "private/inbox"):
                for p in (mem / d).glob("*"):
                    p.unlink()
                (mem / d).rmdir()
            set_version(mem, 1)

            res = mig.migrate(mem, Path(tmp))
            self.assertTrue(res["ok"], res)
            self.assertTrue((mem / "inbox").is_dir())
            self.assertTrue((mem / "inbox" / ".gitkeep").is_file())
            self.assertTrue((mem / "private" / "inbox").is_dir())
            self.assertEqual(len(res["steps"][0]["changed"]), 2)

            # Re-running the step directly is a no-op: it reports no changes and
            # does not disturb what is already there.
            again = mig._m2_inbox_directories(mem, Path(tmp))
            self.assertEqual(again, [])

    def test_readers_tolerate_a_store_that_never_migrated(self):
        """An un-migrated store has no inbox and must still work everywhere."""
        from breadcrumbs import inbox as ibx

        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            for d in ("inbox", "private/inbox"):
                for p in (mem / d).glob("*"):
                    p.unlink()
                (mem / d).rmdir()
            self.assertEqual(ibx.load_jots(mem), [])
            self.assertEqual(ibx.packet_jots(mem), [])
            packet = crumb.build_resume_packet(mem, Path(tmp))
            self.assertEqual(packet["inbox"], [])
            self.assertNotIn("## Inbox", crumb.render_packet_markdown(packet))


class ValidateSchemaGateTests(unittest.TestCase):
    def _schema_findings(self, mem: Path) -> list[dict]:
        return [f for f in crumb.run_validate(mem) if f["check"] == "schema-version"]

    def test_older_store_is_told_to_migrate(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, 1)
            fails = [f for f in self._schema_findings(mem) if f["status"] == "fail"]
            self.assertEqual(len(fails), 1)
            self.assertIn("`crumb migrate`", fails[0]["message"])

    def test_newer_store_is_told_to_upgrade_the_tool(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, 99)
            fails = [f for f in self._schema_findings(mem) if f["status"] == "fail"]
            self.assertEqual(len(fails), 1)
            self.assertIn("upgrade crumb-kit", fails[0]["message"])

    def test_unreadable_version_is_a_finding_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, "banana")
            fails = [f for f in self._schema_findings(mem) if f["status"] == "fail"]
            self.assertEqual(len(fails), 1)
            self.assertIn("unreadable", fails[0]["message"])

    def test_current_store_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            self.assertEqual([f["status"] for f in self._schema_findings(mem)], ["pass"])


class MigrateCommandTests(unittest.TestCase):
    def test_command_reports_nothing_to_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            code, out = run(["migrate", "--project", tmp])
            self.assertEqual(code, 0)
            self.assertIn("nothing to do", out)

    def test_command_migrates_and_json_envelope_is_well_formed(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, 1)
            code, out = run(["migrate", "--project", tmp, "--json"])
            self.assertEqual(code, 0)
            doc = json.loads(out)
            self.assertTrue(doc["ok"])
            self.assertEqual(doc["command"], "crumb migrate")
            self.assertEqual(doc["to"], crumb.SCHEMA_VERSION)
            self.assertTrue(doc["items"])

    def test_command_exits_one_on_a_newer_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, 99)
            code, _ = run(["migrate", "--project", tmp])
            self.assertEqual(code, 1)

    def test_command_needs_a_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _ = run(["migrate", "--project", tmp])
            self.assertEqual(code, 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
