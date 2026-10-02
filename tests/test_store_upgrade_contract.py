"""The store upgrade and compatibility contract (audit WP21: F05, F18, F24).

`docs/compatibility.md` is the policy; these tests hold the code to it:

- an upgrade keeps every record's content, id, scope and unknown fields, and
  reports (never rewrites) legacy values;
- a migration backup is verified, an interrupted migration resumes against it,
  and `--restore` puts the store back exactly;
- a store this build does not fully understand is never written by it, and
  every read of it says so;
- the version tables in the document match what the package emits, and a
  schema change cannot ship without a minor version bump.

Run with:  python -m unittest discover -s tests -p "test_store_upgrade_contract.py"
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import crumb  # noqa: E402
import breadcrumbs  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import compat, hooks_common, lock, mcp_core, migrate, projections  # noqa: E402
from breadcrumbs import searchindex, usage  # noqa: E402
from _schema2 import downgrade_to_schema2  # noqa: E402

COMPAT_DOC = REPO_ROOT / "docs" / "compatibility.md"


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


def run_hook(event: str, payload: dict) -> dict:
    out = io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = crumb.main(["hook", event])
    finally:
        sys.stdin = saved
    assert code == 0, f"a hook must always exit 0, got {code}"
    text = out.getvalue().strip()
    return json.loads(text) if text else {}


def make_project(tmp: str) -> tuple[Path, Path]:
    root = Path(tmp)
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "f.txt").write_text("a\n")
    subprocess.run(["git", "add", "f.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True, capture_output=True)
    code, out, err = run(["init", "--project", str(root), "--session-tracking", "full"])
    assert code == 0, out + err
    return root, root / crumb.MEMORY_DIRNAME


def a_decision(root: Path, title: str, *extra: str) -> str:
    code, out, err = run(
        [
            "remember",
            "decision",
            "--project",
            str(root),
            "--title",
            title,
            "--set",
            "Decision",
            "recorded for the test",
            "--evidence",
            "file",
            "src/quasar.py",
            "--allow-duplicate",
            *extra,
            "--json",
        ]
    )
    assert code == 0, out + err
    return json.loads(out)["id"]


def add_frontmatter(path: Path, lines: str) -> None:
    """Insert raw frontmatter lines (unknown keys, legacy values) after `id:`."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^(id: .*)$", lambda m: m.group(1) + "\n" + lines, text, count=1)
    path.write_text(text, encoding="utf-8")


def set_frontmatter(path: Path, key: str, value: str) -> None:
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(rf"(?m)^{key}: .*$", f"{key}: {value}", text, count=1), encoding="utf-8")


def committed(mem: Path) -> dict[str, str]:
    return migrate.store_files(mem)


def all_ids(mem: Path) -> set[str]:
    ids = {r.meta.get("id") for r in _cli.load_records(mem) if not r.error}
    ids |= {t["id"] for t in _cli.load_traps(mem)}
    ids |= {q["id"] for q in _cli.load_open_questions(mem)}
    return {i for i in ids if i}


def doc_table(name: str) -> list[list[str]]:
    text = COMPAT_DOC.read_text(encoding="utf-8")
    block = text.split(f"<!-- compat:{name}:begin")[1].split(f"<!-- compat:{name}:end")[0]
    rows = [ln for ln in block.splitlines() if ln.startswith("| ") and not ln.startswith("|---")]
    return [[c.strip() for c in row.strip("|").split("|")] for row in rows[1:]]


class UpgradeContractTests(unittest.TestCase):
    def test_upgrade_preserves_content_ids_scope_and_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            branch_id = a_decision(root, "Branch scoped quasar routing rule", "--scope", "branch")
            legacy_id = a_decision(root, "Legacy free scoped quasar rule")
            plain_id = a_decision(root, "Plain quasar routing rule with unknown keys")
            downgrade_to_schema2(mem)
            for summary in ("Quasar trap one", "Quasar trap two"):
                res = crumb.note(mem, root, "trap", summary, fields={"why": "mechanism"})
                self.assertTrue(res["ok"], res)
            res = crumb.note(mem, root, "question", "Does quasar need a queue?", fields={})
            self.assertTrue(res["ok"], res)

            by_id = {r.meta["id"]: r.path for r in _cli.load_records(mem, types=("decision",))}
            # Unknown keys, a legacy free scope, and body text a writer must keep.
            add_frontmatter(by_id[plain_id], "x_team_owner: platform\nx_ticket: OPS-17")
            set_frontmatter(by_id[legacy_id], "scope", "all-machines")
            with open(by_id[plain_id], "a", encoding="utf-8") as fh:
                fh.write("\n## Notes\nKeep this exact line — ünïcode and `code` too.\n")
            before_ids = all_ids(mem)
            before_decisions = {p.name: p.read_bytes() for p in (mem / "decisions").glob("*.md")}
            before_traps = {t["id"]: t["summary"] for t in _cli.load_traps(mem)}

            # The preview says what will happen, and changes nothing.
            snapshot = committed(mem)
            code, out, err = run(["migrate", "--project", str(root), "--dry-run"])
            self.assertEqual(code, 0, out + err)
            self.assertIn("schema_version 3", out)
            self.assertIn("copied to", out)
            self.assertIn("scope-unsupported: 1", out)
            self.assertEqual(committed(mem), snapshot, "a dry run changed the store")

            code, out, err = run(["migrate", "--project", str(root), "--json"])
            self.assertEqual(code, 0, out + err)
            result = json.loads(out)
            self.assertEqual(result["to"], crumb.SCHEMA_VERSION)

            # Every id survives, and so does every trap and question.
            self.assertEqual(all_ids(mem), before_ids)
            self.assertEqual({t["id"]: t["summary"] for t in _cli.load_traps(mem)}, before_traps)
            # Decisions are untouched, byte for byte: unknown keys, the free
            # scope (reported, never rewritten) and the body.
            after_decisions = {p.name: p.read_bytes() for p in (mem / "decisions").glob("*.md")}
            self.assertEqual(after_decisions, before_decisions)
            meta = _cli.find_record_by_id(mem, legacy_id).meta
            self.assertEqual(meta["scope"], "all-machines")
            self.assertEqual(_cli.find_record_by_id(mem, branch_id).meta["scope"], "branch")

            # A writer run after the upgrade keeps unknown keys too.
            code, out, err = run(
                ["mark-status", plain_id, "stale", "--reason", "test", "--project", str(root)]
            )
            self.assertEqual(code, 0, out + err)
            text = by_id[plain_id].read_text(encoding="utf-8")
            self.assertIn("x_team_owner: platform", text)
            self.assertIn("x_ticket: OPS-17", text)
            self.assertIn("Keep this exact line — ünïcode and `code` too.", text)

    def test_interrupted_migration_is_resumable_and_backup_restores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            a_decision(root, "Quasar routing rule kept across a failed migration")
            downgrade_to_schema2(mem)
            crumb.note(mem, root, "trap", "Quasar interrupted trap", fields={"why": "x"})
            original = committed(mem)

            # The schema-3 step dies part-way (after writing some files).
            real_step = migrate.MIGRATIONS[1].apply

            def dies(memory_dir, project_root):
                real_step(memory_dir, project_root)
                raise RuntimeError("synthetic interruption")

            steps = [
                migrate.MIGRATIONS[0],
                migrate.MIGRATIONS[1]._replace(apply=dies),
                *migrate.MIGRATIONS[2:],
            ]
            with mock.patch.object(migrate, "MIGRATIONS", steps):
                code, out, err = run(["migrate", "--project", str(root), "--json"])
            failed = json.loads(out)
            self.assertEqual(code, 1)
            self.assertFalse(failed["ok"])
            self.assertEqual(
                migrate.store_schema_version(mem), 2, "stopped at the last completed version"
            )
            self.assertIn("re-run `crumb migrate` to resume", failed["error"])
            marker = migrate.in_progress(mem)
            self.assertIsNotNone(marker)
            backup = root / marker["backup"]
            self.assertEqual(migrate.verify_backup(backup), [])
            self.assertEqual(
                json.loads((backup / migrate.BACKUP_MANIFEST).read_text())["files"], original
            )

            # Restore: back to exactly the pre-migration store.
            code, out, err = run(["migrate", "--project", str(root), "--restore", "--dry-run"])
            self.assertEqual(code, 0, out + err)
            self.assertIn("file(s) differ", out)
            code, out, err = run(["migrate", "--project", str(root), "--restore"])
            self.assertEqual(code, 0, out + err)
            self.assertEqual(committed(mem), original)
            self.assertIsNone(migrate.in_progress(mem))
            self.assertEqual(migrate.store_schema_version(mem), 2)

            # Interrupt again, then resume: the re-run finishes against the
            # original backup, taking no new one.
            with mock.patch.object(migrate, "MIGRATIONS", steps):
                run(["migrate", "--project", str(root)])
            marker = migrate.in_progress(mem)
            backups_dir = mem / "private" / "migrations"
            backups_before = sorted(p for p in backups_dir.iterdir() if p.is_dir())
            code, out, err = run(["migrate", "--project", str(root), "--json"])
            resumed = json.loads(out)
            self.assertEqual(code, 0, out + err)
            self.assertTrue(resumed["ok"])
            self.assertEqual(resumed["resumed"]["backup"], marker["backup"])
            self.assertEqual(sorted(p for p in backups_dir.iterdir() if p.is_dir()), backups_before)
            self.assertIsNone(migrate.in_progress(mem))
            self.assertEqual(migrate.store_schema_version(mem), crumb.SCHEMA_VERSION)
            code, out, err = run(["validate", "--project", str(root)])
            self.assertEqual(code, 0, out + err)

            # A backup that does not verify is never restored.
            victim = next(p for p in (root / marker["backup"]).rglob("*.md"))
            victim.write_text("tampered\n", encoding="utf-8")
            result = migrate.restore(mem, root / marker["backup"])
            self.assertFalse(result["ok"])
            self.assertIn("does not verify", result["error"])

    def test_a_backup_that_does_not_verify_stops_the_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            downgrade_to_schema2(mem)
            original = committed(mem)
            with mock.patch.object(
                migrate, "verify_backup", return_value=["decisions/x.md differs"]
            ):
                result = migrate.migrate(mem, root)
            self.assertFalse(result["ok"])
            self.assertIn("Nothing was migrated", result["error"])
            self.assertEqual(committed(mem), original)
            self.assertEqual(migrate.store_schema_version(mem), 2)


class NewerStoreTests(unittest.TestCase):
    def test_old_reader_cannot_silently_misinterpret_new_authority_semantics(self):
        """A store written under semantics this build lacks: here, a newer
        schema (the shape WP14's review profiles will take) and, separately, a
        `requires:` feature. Nothing is written; every read says so."""
        for label, change in (
            (
                "newer schema",
                lambda mem: migrate.set_manifest_version(mem, crumb.SCHEMA_VERSION + 1),
            ),
            ("unknown feature", lambda mem: self._require(mem, "signed-reviews")),
        ):
            with self.subTest(label), tempfile.TemporaryDirectory() as tmp:
                root, mem = make_project(tmp)
                rid = a_decision(root, "Quasar routing uses the slow queue")
                run(["reindex", "--project", str(root)])
                change(mem)
                state = compat.check(mem)
                self.assertFalse(state.writable)
                with self.assertRaises(lock.IncompatibleStore):
                    with lock.store_lock(mem, timeout=0.1):
                        pass
                before = committed(mem)

                # Every writer refuses: CLI, MCP, hooks.
                for argv in (
                    [
                        "remember",
                        "decision",
                        "--title",
                        "An old-semantics write",
                        "--set",
                        "Decision",
                        "x",
                        "--evidence",
                        "file",
                        "a.py",
                    ],
                    ["note", "question", "Anything?"],
                    ["mark-status", rid, "stale", "--reason", "x"],
                    ["capture", "session", "--next", "n"],
                    ["reindex"],
                    ["jot", "a jot"],
                ):
                    code, out, err = run([*argv, "--project", str(root)])
                    self.assertEqual(code, 1, (argv, out, err))
                    self.assertIn("Upgrade crumb-kit", err, argv)
                tool = mcp_core.tool_record(
                    "decision",
                    {
                        "title": "MCP write",
                        "sections": {"Decision": "x"},
                        "evidence": [{"type": "file", "ref": "a.py"}],
                    },
                    root=root,
                )
                self.assertFalse(tool["ok"])
                self.assertIn("Upgrade crumb-kit", tool["error"])
                run_hook(
                    "prompt",
                    {"cwd": str(root), "session_id": "s", "prompt": "No, never use the slow queue"},
                )
                run_hook("capture", {"cwd": str(root), "session_id": "s", "transcript_path": ""})
                self.assertEqual(committed(mem), before, "something wrote to a newer store")

                # Reads work and say so.
                code, out, err = run(["resume", "--project", str(root)])
                self.assertEqual(code, 0)
                self.assertIn("Upgrade crumb-kit", out)
                self.assertIn(rid, out)
                code, out, err = run(
                    ["guard", "edit src/quasar.py", "--project", str(root), "--json"]
                )
                self.assertIn("Upgrade crumb-kit", json.loads(out)["compatibility"])
                code, out, err = run(["search", "quasar", "--project", str(root)])
                self.assertEqual(code, 0)
                self.assertIn("Upgrade crumb-kit", err)
                self.assertIn("Upgrade crumb-kit", mcp_core.resource_resume_packet(root))
                session = run_hook("session", {"cwd": str(root), "session_id": "s"})
                self.assertIn(
                    "Upgrade crumb-kit", session["hookSpecificOutput"]["additionalContext"]
                )
                code, out, err = run(["validate", "--project", str(root)])
                self.assertNotEqual(code, 0)

                # Repair is the one writer allowed: restore a verified backup.
                code, out, err = run(["migrate", "--project", str(root)])
                self.assertEqual(code, 1)

    def test_known_older_and_current_stores_stay_writable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            self.assertEqual(compat.check(mem).state, compat.CURRENT)
            downgrade_to_schema2(mem)
            self.assertEqual(compat.check(mem).state, compat.OLDER)
            self.assertTrue(compat.check(mem).writable)
            a_decision(root, "Written to an older store")
            with mock.patch.object(compat, "KNOWN_FEATURES", frozenset({"review-profiles"})):
                self._require(mem, "review-profiles")
                self.assertTrue(compat.check(mem).writable)
            self.assertEqual(compat.parse_features("[a, b]"), ("a", "b"))
            self.assertEqual(compat.parse_features("b a,  a"), ("a", "b"))

    def test_restore_repairs_a_store_this_build_cannot_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            downgrade_to_schema2(mem)
            code, out, err = run(["migrate", "--project", str(root)])
            self.assertEqual(code, 0, out + err)
            migrate.set_manifest_version(mem, crumb.SCHEMA_VERSION + 3)  # a newer build ran here
            self.assertFalse(compat.check(mem).writable)
            code, out, err = run(["migrate", "--project", str(root), "--restore"])
            self.assertEqual(code, 0, out + err)
            self.assertEqual(migrate.store_schema_version(mem), 2)
            self.assertTrue(compat.check(mem).writable)

    @staticmethod
    def _require(mem: Path, feature: str) -> None:
        manifest = mem / "manifest.yml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8") + f"requires: {feature}\n", encoding="utf-8"
        )


class VersionPolicyTests(unittest.TestCase):
    def test_documentation_matches_emitted_versions(self):
        """`docs/compatibility.md` §2 against the code and what it emits."""
        rows = {r[0].strip("`"): r[1] for r in doc_table("surfaces")}
        expected = {
            "package": "`__version__`",
            "schema_version": str(_cli.SCHEMA_VERSION),
            "requires": ", ".join(sorted(compat.KNOWN_FEATURES)) or "(none known)",
            "generation-manifest": str(projections.MANIFEST_FORMAT),
            "guard-prefilter": str(_cli.GUARD_PREFILTER_FORMAT),
            "search-index": str(searchindex.INDEX_FORMAT),
            "miner-state": str(hooks_common.MINER_STATE_VERSION),
            "usage-event": "1",
            "migration-backup": "1",
        }
        self.assertEqual(rows, expected)
        # What the package actually emits.
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            crumb.main(["--version"])
        out = out.getvalue()
        self.assertEqual(
            out.strip(),
            f"breadcrumbs {breadcrumbs.__version__} (record schema_version {_cli.SCHEMA_VERSION})",
        )
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            self.assertIn(
                f"schema_version: {_cli.SCHEMA_VERSION}\n", (mem / "manifest.yml").read_text()
            )
            run(["reindex", "--project", str(root)])
            gen = json.loads((mem / "index" / "generation.json").read_text())
            self.assertEqual(gen["format"], projections.MANIFEST_FORMAT)
            pre = json.loads(_cli.guard_prefilter_path(mem).read_text())
            self.assertEqual(pre["format"], _cli.GUARD_PREFILTER_FORMAT)
            usage.record_surfaced(mem, ["dec_x"], "resume")
            with mock.patch.object(usage, "fold", return_value=False):
                usage.record_surfaced(mem, ["dec_x"], "resume")
            event = next((mem / "private" / "usage-events").glob("*.json"))
            self.assertEqual(json.loads(event.read_text())["v"], 1)
            downgrade_to_schema2(mem)
            run(["migrate", "--project", str(root)])
            backup = sorted((mem / "private" / "migrations").iterdir())[-1]
            self.assertEqual(
                json.loads((backup / migrate.BACKUP_MANIFEST).read_text())["format"], 1
            )

    def test_a_schema_change_requires_a_minor_version_bump(self):
        """§1: `schema_version` never changes without the minor, and a release
        row records what shipped."""
        releases = [(r[0], int(r[1])) for r in doc_table("releases")]

        def key(v: str) -> tuple[int, ...]:
            return tuple(int(x) for x in v.split("."))

        self.assertEqual(releases, sorted(releases, key=lambda r: key(r[0])))
        for (prev_v, prev_s), (v, s) in zip(releases, releases[1:]):
            if s != prev_s:
                self.assertNotEqual(
                    key(v)[:2], key(prev_v)[:2], f"{v}: schema changed in a patch release"
                )
        # The CHANGELOG's released sections are exactly the table's rows.
        changelog = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        released = re.findall(r"(?m)^## \[(\d+\.\d+\.\d+)\]", changelog)
        self.assertEqual(sorted(released, key=key), [v for v, _ in releases])

        version, schema = breadcrumbs.__version__, _cli.SCHEMA_VERSION
        table = dict(releases)
        if version in table:
            # A released version: its schema is what shipped, so changing
            # SCHEMA_VERSION means bumping the version first.
            self.assertEqual(
                schema, table[version], f"SCHEMA_VERSION changed without a version bump ({version})"
            )
        else:
            last_v, last_s = releases[-1]
            self.assertGreater(key(version), key(last_v))
            if schema != last_s:
                self.assertNotEqual(
                    key(version)[:2], key(last_v)[:2], "a schema change needs a minor bump"
                )

    def test_backup_manifest_hashes_are_sha256_of_the_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = make_project(tmp)
            backup = migrate.backup_store(mem)
            files = json.loads((backup / migrate.BACKUP_MANIFEST).read_text())["files"]
            for rel, digest in files.items():
                self.assertEqual(hashlib.sha256((mem / rel).read_bytes()).hexdigest(), digest)
            self.assertNotIn("private", {Path(r).parts[0] for r in files})


if __name__ == "__main__":
    unittest.main()
