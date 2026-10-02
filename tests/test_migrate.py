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
            # The first run on a current store sets the writer floor (DoWhat
            # retest of 0.5.0, item 14); after that there is nothing to do.
            mig.migrate(mem, Path(tmp))
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
            run(["migrate", "--project", tmp])  # sets the writer floor once
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


class LegacyBlockTests(unittest.TestCase):
    """Field report 2026-10-01, issue 4 / N2: a dry run said "would apply 3
    step(s)", then step 3 failed on hand-written trap statuses; a duplicate trap
    id was silently dropped."""

    def _store(self, tmp: str, traps: str = "", questions: str = "") -> Path:
        sys.path.insert(0, str(REPO_ROOT / "tests"))
        from _schema2 import downgrade_to_schema2

        mem = downgrade_to_schema2(init_store(tmp))
        if traps:
            with open(mem / "known-traps.md", "a", encoding="utf-8") as fh:
                fh.write("\n" + traps)
        if questions:
            with open(mem / "open-questions.md", "a", encoding="utf-8") as fh:
                fh.write("\n" + questions)
        return mem

    FIELD_TRAPS = (
        "## trap_fixed-one: an old trap someone fixed\n- Why: w\n- Status: fixed\n\n"
        "## trap_resolved-one: another\n- Why: w\n"
        "- Status: resolved 2026-09-18 — we rewrote the loader in PR 41\n"
    )

    def test_field_statuses_are_mapped_and_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store(tmp, self.FIELD_TRAPS)
            preview = mig.migrate(mem, Path(tmp), dry_run=True)
            self.assertTrue(preview["ok"], preview["error"])
            lines = [ln for st in preview["steps"] for ln in st["changed"]]
            self.assertTrue(any("trap_fixed-one" in ln and "-> stale" in ln for ln in lines))
            self.assertTrue(any("known-traps.md:" in ln for ln in lines))
            self.assertEqual(mig.store_schema_version(mem), 2)  # preview changed nothing
            result = mig.migrate(mem, Path(tmp))
            self.assertTrue(result["ok"], result["error"])
            body = (mem / "traps" / "resolved-one.md").read_text(encoding="utf-8")
            self.assertIn("status: stale", body)
            self.assertIn(
                "Original status: resolved 2026-09-18 — we rewrote the loader in PR 41", body
            )
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    BAD_INPUTS = {
        "superseded-without-successor": "## trap_a: a\n- Status: superseded\n",
        "bad-last-confirmed": "## trap_b: b\n- Last confirmed: last tuesday\n",
        "dangling-successor": "## trap_c: c\n- Status: superseded\n- Superseded by: dec_nope\n",
        "unknown-word": "## trap_d: d\n- Status: wip-ish\n",
    }

    def test_preview_and_real_run_agree(self):
        for name, block in self.BAD_INPUTS.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                mem = self._store(tmp, block)
                preview = mig.migrate(mem, Path(tmp), dry_run=True)
                real = mig.migrate(mem, Path(tmp))
                self.assertEqual(preview["ok"], real["ok"], (preview["error"], real["error"]))
                self.assertTrue(real["ok"], real["error"])

    def test_question_status_maps_to_answered(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store(tmp, questions="## Q: is it done?\n- Status: resolved by dec_x\n")
            result = mig.migrate(mem, Path(tmp))
            self.assertTrue(result["ok"], result["error"])
            q = crumb.load_open_questions(mem)[0]
            self.assertEqual(q["status"], "answered")

    def test_duplicate_trap_id_is_never_dropped(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store(
                tmp,
                "## trap_dup: first\n- Why: FIRST BODY\n\n## trap_dup: second\n- Why: SECOND BODY\n",
            )
            result = mig.migrate(mem, Path(tmp))
            self.assertTrue(result["ok"], result["error"])
            committed = "".join(
                p.read_text(encoding="utf-8") for p in mem.rglob("*.md") if "private" not in p.parts
            )
            self.assertIn("FIRST BODY", committed)
            self.assertIn("SECOND BODY", committed)

    def test_a_blocker_is_named_and_the_preview_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = self._store(tmp, "## trap_ok: fine\n- Why: w\n")
            boom = mig.Migration(
                3,
                "boom",
                lambda m, r: (_ for _ in ()).throw(RuntimeError("trap_x (known-traps.md:9): boom")),
            )
            with mock.patch.object(mig, "MIGRATIONS", [mig.MIGRATIONS[0], boom, mig.MIGRATIONS[2]]):
                preview = mig.migrate(mem, Path(tmp), dry_run=True)
            self.assertFalse(preview["ok"])
            self.assertIn("known-traps.md:9", preview["error"])
            self.assertIn("schema_version 3", preview["error"])
            self.assertEqual(mig.store_schema_version(mem), 2)

    def test_every_failure_is_listed(self):
        # The step used to show the first five, so a store with many bad blocks
        # meant fix five, re-run, repeat (N12).
        with tempfile.TemporaryDirectory() as tmp:
            blocks = "".join(f"## trap_t{i}: t{i}\n- Why: w\n\n" for i in range(12))
            mem = self._store(tmp, blocks)
            from breadcrumbs import blockfiles

            fails = [
                {"status": "fail", "path": f"traps/t{i}.md", "message": "bad"} for i in range(12)
            ]
            with mock.patch.object(_cli, "run_validate", return_value=fails):
                with self.assertRaises(RuntimeError) as ctx:
                    blockfiles.adopt_blocks(mem, Path(tmp))
            self.assertIn("traps/t11.md", str(ctx.exception))
            self.assertIn("12 trap/question file(s)", str(ctx.exception))


class LongPathTests(unittest.TestCase):
    """Field report 2026-10-01, issue 5: the backup copy went past Windows'
    MAX_PATH and the error printed was shutil.Error's raw list of tuples."""

    def test_extended_path_forms(self):
        from breadcrumbs import path_policy as pp

        self.assertEqual(pp.extended_path(r"C:\a\b\..\c.md", windows=True), "\\\\?\\C:\\a\\c.md")
        self.assertEqual(
            pp.extended_path(r"\\srv\share\x", windows=True), "\\\\?\\UNC\\srv\\share\\x"
        )
        self.assertEqual(pp.extended_path("\\\\?\\C:\\x", windows=True), "\\\\?\\C:\\x")
        self.assertEqual(pp.plain_path(pp.extended_path(r"C:\a\c.md", windows=True)), r"C:\a\c.md")
        self.assertEqual(pp.extended_path("/tmp/x", windows=False), "/tmp/x")

    def test_a_failed_backup_copy_is_readable_and_leaves_nothing(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, 3)
            err = shutil.Error(
                [
                    (
                        str(mem / "decisions" / "x.md"),
                        "dst",
                        "[WinError 3] The system cannot find the path specified",
                    )
                ]
            )
            with mock.patch.object(mig.shutil, "copytree", side_effect=err):
                result = mig.migrate(mem, Path(tmp))
            self.assertFalse(result["ok"])
            self.assertIn("decisions/x.md", result["error"])
            self.assertIn("WinError 3", result["error"])
            self.assertIn("Nothing was migrated", result["error"])
            self.assertNotIn("[('", result["error"])
            backups = mem / "private" / "migrations"
            leftover = [p for p in backups.iterdir()] if backups.is_dir() else []
            self.assertEqual(leftover, [])
            self.assertEqual(mig.store_schema_version(mem), 3)

    def test_cli_never_prints_the_raw_tuple_list(self):
        import shutil

        with tempfile.TemporaryDirectory() as tmp:
            init_store(tmp)
            err = shutil.Error([("/x/.project-memory/a.md", "/y", "File name too long")])
            stderr = io.StringIO()
            with (
                mock.patch.object(_cli, "cmd_validate", side_effect=err),
                contextlib.redirect_stderr(stderr),
            ):
                code, _ = run(["validate", "--project", tmp])
            self.assertEqual(code, 1)
            self.assertNotIn("[('", stderr.getvalue())
            self.assertIn("a.md (File name too long)", stderr.getvalue())

    def test_restore_that_cannot_copy_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            set_version(mem, 3)
            self.assertTrue(mig.migrate(mem, Path(tmp))["ok"])
            before = mig.store_files(mem)
            with mock.patch.object(mig, "_copytree", side_effect=OSError("disk full")):
                result = mig.restore(mem)
            self.assertFalse(result["ok"])
            self.assertIn("nothing was changed", result["error"])
            self.assertEqual(mig.store_files(mem), before)
            leftover = [p.name for p in (mem / "private" / "migrations").iterdir()]
            self.assertFalse(any(n.startswith(".restoring") for n in leftover), leftover)
