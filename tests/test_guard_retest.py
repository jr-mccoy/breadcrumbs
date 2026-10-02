"""Guard fixes from the DoWhat retest of 0.5.0 (items 1-7).

`docs/reviews/2026-10-02-dowhat-retest-plan.md`. After the upgrade, 24 of 29
guard firings in one session added context, mostly citing records that had
nothing to do with the command:

- `sed -n` and `awk` pipelines were not read-only (item 1);
- `crumb migrate --dry-run | sed -n …` fell back to "migration" (item 2);
- high-impact actions still cited unrelated records (item 3);
- edits were scored on the prose being written (item 4);
- a few records sharing common tags turned up everywhere, and the hook's
  repeat filter did not stop them (item 5);
- a read-only command showed a record as `[objects]` (item 6).

The android eval suite holds the field's own commands; these pin the
mechanisms.

Run with:  python -m unittest discover -s tests -p test_guard_retest.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import shellcmd  # noqa: E402
from test_guard_field_report import StoreCase, attempt, hook, run  # noqa: E402


def write_decision(mem: Path, slug: str, title: str, tags: list[str], body: str = "") -> None:
    """A decision file written directly: a big store without one CLI call each."""
    tag_lines = "".join(f"  - {t}\n" for t in tags)
    (mem / "decisions" / f"2026-06-01-{slug}.md").write_text(
        "---\n"
        f"id: dec_20260601_{slug}\n"
        "type: decision\n"
        f"slug: {slug}\n"
        f"title: {title}\n"
        "status: active\n"
        # Recent, like the field's records: old ones are decayed below the
        # thresholds anyway, which would hide what this test is about.
        f"created_at: {_cli.now_iso()}\n"
        f"updated_at: {_cli.now_iso()}\n"
        "scope: project\n"
        "confidence: low\n"
        "tags:\n"
        f"{tag_lines}"
        "evidence: []\n"
        "---\n\n"
        f"## Decision\n{body or title}\n",
        encoding="utf-8",
    )


def migration_attempt(root: Path) -> None:
    """The retest's most-cited record: a do-not-retry attempt tagged with the
    store's commonest words."""
    attempt(
        root,
        "MigrationV21ToV22Test's todos inserts named 5 of the 10 required columns",
        tags="todo,migration,schema",
        dnr="the todos table gains defaults for every NOT NULL column",
    )


class SedAwkReadOnlyTests(unittest.TestCase):
    """Item 1: `sed` without -i / w / e, and `awk` without system() or a
    redirect, only report."""

    READ_ONLY = [
        "sed -n '1,22p' file",
        "sed -n '867p' file | grep -oiE 'migrat(e|ion)'",
        "crumb migrate --dry-run | sed -n '1,22p'",
        "git log --oneline | sed 's/^/  /'",
        "sed -e 's/a/b/g' -e '/x/d' f",
        "sed -E 's#/home/[^/]+#~#' f",
        "awk '{print $1}' f",
        "awk -F: '$3 > 1000 {print $1}' /etc/passwd",
        "git diff --stat | awk 'NR>1' | sort | uniq -c | sort -rn | head",
        "cut -d, -f2 f | tr a-z A-Z | wc -l",
        "diff a b",
        "tac f | rev",
        "git branch",
        "git branch -a",
        "git remote -v",
        "git stash list",
        "git tag -l",
        "git config --get user.name",
    ]
    NOT_READ_ONLY = [
        "sed -i 's/a/b/' f",
        "sed -i.bak 's/a/b/' f",
        "sed --in-place 's/a/b/' f",
        "sed -ni 's/a/b/p' f",
        "sed 's/a/b/w out.txt' f",
        "sed -n '1w out.txt' f",
        "sed 's/a/date/e' f",
        "sed -f script.sed f",
        "awk '{print > \"out\"}' f",
        "awk '{print $1 >> \"out\"}' f",
        "awk 'BEGIN{system(\"rm x\")}'",
        "awk '{print | \"sh\"}' f",
        "awk -i inplace '{print}' f",
        "awk -f prog.awk f",
        "git branch -D feature",
        "git branch new-branch",
        "git remote add origin x",
        "git stash",
        "git tag v1",
        "git config user.name x",
    ]

    def test_read_only(self):
        wrong = [c for c in self.READ_ONLY if not _cli._is_read_only_action(c)]
        self.assertEqual(wrong, [])

    def test_not_read_only(self):
        wrong = [c for c in self.NOT_READ_ONLY if _cli._is_read_only_action(c)]
        self.assertEqual(wrong, [])


class CrumbPipelineClassificationTests(unittest.TestCase):
    """Item 2: crumb's own commands keep their effect whatever is piped after."""

    def test_a_dry_run_piped_into_a_filter_is_not_a_migration(self):
        for cmd in (
            "crumb migrate --dry-run | sed -n '1,22p'",
            "crumb migrate --dry-run 2>&1 | head -40",
            "cd app && crumb resume | grep Next",
        ):
            with self.subTest(cmd):
                self.assertEqual(_cli.classify_action(cmd)[0], "routine_edit")

    def test_a_real_migrate_is_still_a_migration_in_a_pipeline(self):
        self.assertEqual(_cli.classify_action("crumb migrate | tee log.txt")[0], "migration")

    def test_a_non_crumb_writer_in_the_pipeline_is_still_read(self):
        self.assertEqual(
            _cli.classify_action("crumb resume && rm -rf build")[0],
            "deletion",
        )


class HighImpactCitesOnlyItsOwnMemoryTests(StoreCase):
    """Item 3: a high-impact verdict cites only records about the action."""

    def setUp(self):
        super().setUp()
        attempt(
            self.root,
            "Retrying Gradle against Maven Central on a cold web container hit HTTP 429",
            tags="gradle,ci",
            dnr="the container has a warm Gradle cache",
        )
        attempt(
            self.root,
            "Ran the Room migration test against an in-memory database",
            tags="room,migration",
            dnr="Room supports in-memory migration testing",
        )
        run(
            [
                "note",
                "trap",
                "A git merge conflict inside .project-memory is resolved by keeping both sides",
                "--project",
                str(self.root),
                "--tags",
                "git,merge",
            ]
        )

    def test_a_real_migrate_cites_no_unrelated_record(self):
        res = self.guard("crumb migrate")
        self.assertEqual(res["verdict"], "ASK_HUMAN")
        self.assertEqual(res["high_impact"], "crumb migrate rewrites the memory store")
        self.assertEqual([m["id"] for m in res["matches"]], [])
        self.assertIn("no project memory about it", res["recommended_action"])

    def test_a_force_push_cites_no_unrelated_git_record(self):
        res = self.guard("git push --force origin main")
        self.assertEqual(res["verdict"], "ASK_HUMAN")
        self.assertEqual([m["id"] for m in res["matches"]], [])

    def test_a_record_about_the_target_is_still_cited(self):
        attempt(
            self.root,
            "Deleted app/build/test-results to clear stale reports",
            tags="gradle",
            dnr="no Gradle daemon is running",
            extra=["--evidence", "file", "app/build/test-results"],
        )
        res = self.guard("rm -rf app/src/main")
        self.assertEqual(res["verdict"], "ASK_HUMAN")
        self.assertEqual([m["id"] for m in res["matches"]], [])
        res = self.guard("rm -rf app/build/test-results")
        self.assertIn("deleted-app-build-test-results", res["matches"][0]["id"])


class EditsAreScoredOnTheirPathTests(StoreCase):
    """Item 4: the words an edit writes are not the action."""

    def setUp(self):
        super().setUp()
        migration_attempt(self.root)

    def _assert_quiet_about_the_attempt(self, action: str, files: list[str]) -> None:
        res = self.guard(action, files=files)
        self.assertNotIn(res["verdict"], ("PAUSE", "ASK_HUMAN"), res["matches"])
        self.assertFalse(any("migrationv21" in m["id"] for m in res["matches"]), res["matches"])

    def test_a_memory_note_about_a_migration_is_not_paused(self):
        self._assert_quiet_about_the_attempt(
            "edit .project-memory/handoff.md: Migrated the store from schema 1 to 4; "
            "the migration kept every todo trap.",
            [".project-memory/handoff.md"],
        )

    def test_a_script_whose_comment_says_migrated_is_not_paused(self):
        self._assert_quiet_about_the_attempt(
            "edit tools/run.sh: # migrated the schema; todo: re-run the migration",
            ["tools/run.sh"],
        )

    def test_an_edit_inside_the_store_is_at_most_read_first(self):
        attempt(
            self.root,
            "Hand-edited handoff.md during a capture",
            tags="handoff",
            dnr="capture is not running",
            extra=["--evidence", "file", ".project-memory/handoff.md"],
        )
        res = self.guard("edit .project-memory/handoff.md: x", files=[".project-memory/handoff.md"])
        self.assertEqual(res["verdict"], "READ_FIRST")
        self.assertTrue(all(m["stance"] == "advisory" for m in res["matches"]))

    def test_code_identifiers_in_the_new_content_still_count(self):
        self.assertEqual(
            shellcmd.code_identifiers(
                "val helper = MigrationTestHelper(Room.inMemoryDatabaseBuilder(ctx)) // migrated"
            ),
            ["MigrationTestHelper", "inMemoryDatabaseBuilder"],
        )


class CommonWordsTests(StoreCase):
    """Item 5: in a store full of migration and memory records, those words
    say little about an action."""

    def setUp(self):
        super().setUp()
        mem = self.mem
        for i in range(24):
            tags = ["migration", "schema"] if i % 2 == 0 else [f"area{i}"]
            write_decision(mem, f"choice-{i}", f"Choice number {i} about component {i}", tags)
        write_decision(
            mem,
            "merges-conflict-on-memory-files",
            "Merging main conflicts on three .project-memory files; regenerate the generated one",
            ["crumb", "git", "memory"],
        )
        for i in range(12):
            write_decision(mem, f"git-{i}", f"Git habit {i}", ["git", "memory"])
        migration_attempt(self.root)
        run(["reindex", "--project", str(self.root)])

    def test_a_common_tag_and_a_common_word_do_not_make_a_record_topical(self):
        res = self.guard("echo migration schema notes > notes.txt")
        att = [m for m in res["matches"] if "migrationv21" in m["id"]]
        for m in att:
            self.assertFalse(m["topical"], m)
            self.assertEqual(m["stance"], "advisory")
        self.assertNotIn(res["verdict"], ("PAUSE", "ASK_HUMAN"))

    def test_routine_commands_do_not_cite_the_merge_decision(self):
        for action in ("git status", "cp a.txt b.txt", "edit README.md: notes on memory and git"):
            with self.subTest(action):
                res = self.guard(action, files=["README.md"] if action.startswith("edit") else None)
                # git and memory are on most of this store: sharing them is not a
                # reason to stop (0.5.0 said READ_FIRST to git status and to the
                # README edit on the strength of the git tag alone).
                self.assertEqual(res["verdict"], "PROCEED", res["matches"])
                cited = [
                    m["id"] for m in res["matches"] if m["score"] >= _cli.GUARD_READ_FIRST_SCORE
                ]
                self.assertNotIn("dec_20260601_merges-conflict-on-memory-files", cited)


class ReadOnlyNeverObjectsTests(StoreCase):
    """Item 6: a command that changes nothing cannot be what a record objects to."""

    def test_git_status_shows_a_topical_git_attempt_as_context(self):
        attempt(
            self.root,
            "Hunk-filtering discipline applied to the kt file lost the unrelated hunks",
            tags="git",
            dnr="the unrelated hunks are saved to a patch first",
            extra=["--set", "Tried", "git status, then git add -p and git reset --hard"],
        )
        res = self.guard("git status")
        self.assertEqual(res["verdict"], "READ_FIRST")
        self.assertTrue(res["matches"])
        self.assertTrue(all(m["stance"] == "advisory" for m in res["matches"]))
        self.assertNotIn("[objects]", _cli.render_guard_human(res))


class SessionDampingTests(StoreCase):
    """Item 5 / F: the hook shows an advisory record once per session."""

    def setUp(self):
        super().setUp()
        run(
            [
                "remember",
                "decision",
                "--project",
                str(self.root),
                "--title",
                "Deploy scripts read the release channel from the environment",
                "--set",
                "Decision",
                "The deploy scripts read CHANNEL; nothing hard-codes a channel.",
                "--tags",
                "deploy,release",
                "--confidence",
                "low",
            ]
        )

    def _fire(self, command: str, session: str) -> dict:
        return hook(
            "guard",
            {
                "cwd": str(self.root),
                "session_id": session,
                "tool_name": "Bash",
                "tool_input": {"command": command},
            },
        )

    def test_the_same_advisory_record_is_delivered_once_per_session(self):
        commands = [
            "./scripts/deploy.sh release staging",
            "./scripts/deploy.sh release production --dry",
            "bash scripts/deploy.sh release canary",
        ]
        spoke = [bool(self._fire(c, "S1")) for c in commands]
        self.assertEqual(spoke, [True, False, False])
        # Another session is told again.
        self.assertTrue(self._fire(commands[1], "S2"))

    def test_a_blocking_record_is_never_damped(self):
        attempt(
            self.root,
            "Ran the deploy script for release against production on a Friday",
            tags="deploy,release",
            dnr="a second person is on call",
        )
        outs = [self._fire(f"./scripts/deploy.sh release production {i}", "S3") for i in range(3)]
        for out in outs:
            self.assertIn("hookSpecificOutput", out)


if __name__ == "__main__":
    unittest.main()
