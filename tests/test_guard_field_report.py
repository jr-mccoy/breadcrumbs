"""Guard and prompt-hook fixes from the DoWhat field report on 0.4.0.

`docs/reviews/2026-10-01-dowhat-field-report-plan.md`, Release 2: a guard that
warned on 23 of 23 tool calls (issue 7), ranked unrelated do-not-retry attempts
above the relevant trap (issue 8), labelled merged records "possibly stale"
(issue 9), read `/dev/null` as a file (issue 10) and could not connect a crumb
command to the files it writes (issue 11). The Android eval suite and the
critical cases in `evals/` hold the field's own examples; these pin the
mechanisms.

Run with:  python -m unittest discover -s tests -p test_guard_field_report.py
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import shellcmd  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


def make_repo(tmp: str) -> Path:
    root = Path(tmp)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("a\n")
    git(root, "add", "f.txt")
    git(root, "commit", "-qm", "initial")
    return root


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def init_store(root: Path) -> Path:
    run(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def hook(event: str, payload: dict) -> dict:
    stdin = io.StringIO(json.dumps(payload))
    buf = io.StringIO()
    old = sys.stdin
    sys.stdin = stdin
    try:
        with contextlib.redirect_stdout(buf):
            crumb.main(["hook", event])
    finally:
        sys.stdin = old
    return json.loads(buf.getvalue() or "{}")


def attempt(root: Path, title: str, *, tags: str, dnr: str = "never", extra=()) -> None:
    run(
        [
            "remember",
            "attempt",
            "--project",
            str(root),
            "--title",
            title,
            "--set",
            "Problem",
            "p",
            "--set",
            "Tried",
            "t",
            "--set",
            "Result",
            "r",
            "--set",
            "Why It Failed / Succeeded",
            "w",
            "--set",
            "Do Not Retry Unless",
            dnr,
            "--tags",
            tags,
            "--confidence",
            "low",
            *extra,
        ]
    )


class ReadOnlyTests(unittest.TestCase):
    """Issue 7a / N4: each segment of a compound command is judged on its own."""

    READ_ONLY = [
        "cd /some/dir; grep foo file",
        "cd src && grep x f",
        "grep x f 2>/dev/null",
        "git log --oneline 2>&1 | head",
        "ls | xargs -n 1 grep foo",
        "git -C repo status",
        "crumb migrate --dry-run",
        "python crumb.py resume",
        "grep 'a|b' file",
    ]
    NOT_READ_ONLY = [
        "ls | xargs rm -rf",
        "find . -name x | xargs rm -rf",
        "cat x | sh",
        "ls | tee out",
        "grep a b | sed -i s/x/y/ f",
        "cat x > y",
        "grep `rm -rf .` x",
        "echo $(rm x)",
        "git commit -m 'x; rm -rf /'",
        "crumb migrate",
        "edit src/a.py: print(1)",
    ]

    def test_read_only(self):
        wrong = [c for c in self.READ_ONLY if not _cli._is_read_only_action(c)]
        self.assertEqual(wrong, [])

    def test_not_read_only(self):
        wrong = [c for c in self.NOT_READ_ONLY if _cli._is_read_only_action(c)]
        self.assertEqual(wrong, [])

    def test_a_piped_destructive_command_is_high_impact(self):
        self.assertTrue(shellcmd.high_impact("find app/src -name '*.orig' | xargs rm -rf"))
        self.assertIsNone(shellcmd.high_impact("rm -rf app/build/test-results"))
        self.assertIsNone(shellcmd.high_impact("git push -f origin feature"))
        self.assertTrue(shellcmd.high_impact("git push --force origin main"))


class ClassificationTests(unittest.TestCase):
    """Issue 7d / N11: crumb's own commands, and words inside quotes."""

    def test_quoted_text_is_not_what_a_command_does(self):
        self.assertEqual(
            _cli.classify_action('git commit -m "deploy the release to production"')[0],
            "routine_edit",
        )

    def test_crumb_commands_are_classified_by_effect(self):
        for cmd in (
            'crumb capture session --next "cut the release"',
            "crumb migrate --dry-run",
            "crumb reindex",
            'crumb verify "reindex works" --status fixed',
            "python crumb.py --version",
        ):
            with self.subTest(cmd):
                self.assertEqual(_cli.classify_action(cmd), ("routine_edit", ["routine_edit"]))
        self.assertEqual(_cli.classify_action("crumb migrate")[0], "migration")

    def test_an_edit_is_classified_by_its_path_not_its_content(self):
        self.assertEqual(
            _cli.classify_action("edit notes/todo.md: bump the schema version before release")[0],
            "routine_edit",
        )


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(self._tmp.name)
        self.mem = init_store(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def guard(self, action: str, files=None) -> dict:
        return crumb.guard(self.mem, self.root, action, files=files)


class RankingTests(StoreCase):
    """Issue 8."""

    def test_a_lone_shared_tag_does_not_make_a_do_not_retry_line_blocking(self):
        attempt(self.root, "Re-recorded the artwork screenshots", tags="robolectric")
        res = self.guard("fix robolectric test failing with KeyStore error")
        m = next(m for m in res["matches"] if "artwork" in m["id"])
        self.assertNotIn("do-not-retry", m["signals"])
        self.assertEqual(m["stance"], "advisory")
        self.assertNotIn(res["verdict"], ("PAUSE", "ASK_HUMAN"))

    def test_template_headings_are_not_shared_words(self):
        attempt(self.root, "Re-recorded the artwork screenshots", tags="screens")
        matches, _ = crumb.search(self.mem, self.root, "why is my zebra test failing")
        self.assertEqual([m["id"] for m in matches], [])

    def test_a_trap_scores_its_tags(self):
        run(
            [
                "note",
                "trap",
                "KeyStore init kills the test class",
                "--project",
                str(self.root),
                "--tags",
                "robolectric",
            ]
        )
        matches, _ = crumb.search(self.mem, self.root, "robolectric setup")
        self.assertIn("tag", matches[0]["signals"])

    def test_an_attempt_naming_the_command_gets_its_do_not_retry_line(self):
        attempt(
            self.root,
            "Ran gradlew --stop on a STOPREQUESTED daemon that was a LIVE build",
            tags="gradle",
            dnr="no other build is running",
        )
        res = self.guard("./gradlew --stop")
        self.assertEqual(res["verdict"], "ASK_HUMAN")
        self.assertIn("command", res["matches"][0]["signals"])
        self.assertIn("do-not-retry", res["matches"][0]["signals"])

    def test_a_long_command_does_not_score_higher_for_being_long(self):
        run(
            [
                "remember",
                "decision",
                "--project",
                str(self.root),
                "--title",
                "Cache invalidation uses versioned keys",
                "--set",
                "Decision",
                "Keys carry a version; invalidation bumps it.",
                "--confidence",
                "low",
            ]
        )
        short = self.guard("echo cache invalidation keys versioned")
        filler = " ".join(f"word{i}" for i in range(300))
        long = self.guard(f"echo cache invalidation keys versioned bump version {filler}")
        s = {m["id"]: m["score"] for m in short["matches"]}
        lg = {m["id"]: m["score"] for m in long["matches"]}
        for rid, score in lg.items():
            self.assertLessEqual(score, s.get(rid, 0) + _cli.GUARD_KEYWORD_CAP)

    def test_high_impact_with_no_memory_asks_and_cites_nothing(self):
        res = self.guard("git push --force origin main")
        self.assertEqual(res["verdict"], "ASK_HUMAN")
        self.assertEqual(res["high_impact"], "force-push to main")
        self.assertIn("no project memory", res["recommended_action"])


class PathTests(StoreCase):
    """Issue 10."""

    def test_dev_null_is_not_a_mention(self):
        run(
            [
                "remember",
                "decision",
                "--project",
                str(self.root),
                "--title",
                "Logs go to /dev/null in CI",
                "--set",
                "Decision",
                "Discard noisy logs.",
                "--confidence",
                "low",
            ]
        )
        res = self.guard("grep -r x app/build 2>/dev/null")
        for m in res["matches"] + res["history"]:
            self.assertNotIn("mention", m["signals"], m)


class WritesTests(StoreCase):
    """Issue 11: a trap keyed to handoff.md fires on the command that writes it."""

    def test_capture_matches_a_trap_about_handoff_md(self):
        run(
            [
                "note",
                "trap",
                "Hand-kept notes in the handoff get lost",
                "--project",
                str(self.root),
                "--area",
                ".project-memory/handoff.md",
            ]
        )
        res = self.guard('crumb capture session --next "ship it"')
        m = next((m for m in res["matches"] if m["kind"] == "trap"), None)
        self.assertIsNotNone(m, res)
        self.assertIn("writes-file", m["signals"])
        self.assertIn("this command writes: .project-memory/handoff.md", m["reason"])


class OutsideProjectTests(StoreCase):
    """Issue 7b: a write to the agent's own memory folder is not the store's business."""

    def test_an_edit_outside_the_project_is_silent(self):
        run(
            [
                "note",
                "trap",
                "Never hand-edit handoff.md",
                "--project",
                str(self.root),
                "--area",
                "handoff.md",
            ]
        )
        with tempfile.TemporaryDirectory() as elsewhere:
            target = Path(elsewhere) / "memory" / "handoff.md"
            target.parent.mkdir()
            out = hook(
                "guard",
                {
                    "cwd": str(self.root),
                    "tool_name": "Write",
                    "tool_input": {"file_path": str(target), "content": "release schema notes"},
                },
            )
        self.assertEqual(out, {})


class MergedBranchTests(unittest.TestCase):
    """Issue 9: a record merged from a cloud branch is history, not "possibly stale"."""

    def _land(self, root: Path, *, squash: bool) -> None:
        base = crumb.git_branch(root)
        git(root, "checkout", "-q", "-b", "claude/fix-auth-xyz")
        run(
            [
                "remember",
                "decision",
                "--project",
                str(root),
                "--title",
                "Auth tokens rotate hourly",
                "--set",
                "Decision",
                "Rotate auth tokens every hour.",
                "--confidence",
                "low",
                "--tags",
                "auth",
                "--scope",
                "branch",
            ]
        )
        git(root, "add", "-A")
        git(root, "commit", "-qm", "memory on the cloud branch")
        git(root, "checkout", "-q", base)
        if squash:
            git(root, "merge", "-q", "--squash", "claude/fix-auth-xyz")
            git(root, "commit", "-qm", "squash")
        else:
            git(root, "merge", "-q", "--no-ff", "-m", "merge", "claude/fix-auth-xyz")
        git(root, "branch", "-D", "claude/fix-auth-xyz")

    def test_merged_and_squashed_records_carry_no_branch_label(self):
        for squash in (False, True):
            with self.subTest(squash=squash), tempfile.TemporaryDirectory() as tmp:
                root = make_repo(tmp)
                mem = init_store(root)
                git(root, "add", "-A")
                git(root, "commit", "-qm", "store")
                self._land(root, squash=squash)
                res = crumb.guard(mem, root, "rotate the auth tokens")
                m = next(m for m in res["matches"] + res["history"] if "auth-tokens" in m["id"])
                self.assertFalse(m["branch_mismatch"], m)
                self.assertNotIn("another branch", m["reason"])
                # A branch-scoped record that reached HEAD is live, not history.
                self.assertIn(m["id"], [x["id"] for x in res["matches"]])

    def test_an_uncommitted_record_from_another_branch_is_still_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            run(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    "Auth tokens rotate hourly",
                    "--set",
                    "Decision",
                    "Rotate them.",
                    "--confidence",
                    "low",
                    "--tags",
                    "auth",
                ]
            )
            rec = next((mem / "decisions").glob("*.md"))
            rec.write_text(
                rec.read_text()
                .replace("branch: master", "branch: other")
                .replace("branch: main", "branch: other")
            )
            res = crumb.guard(mem, root, "rotate the auth tokens")
            m = next(m for m in res["matches"] + res["history"] if "auth-tokens" in m["id"])
            self.assertTrue(m["branch_mismatch"])


if __name__ == "__main__":
    unittest.main()


class SpeedTests(unittest.TestCase):
    """Issue 6: the guard hook took 5 s on Windows, mostly git spawns per record."""

    def _spawns(self, fn) -> int:
        import subprocess as sp
        from unittest import mock

        real = sp.Popen.__init__
        calls = []

        def counting(self_, *a, **k):
            calls.append(a[0] if a else k.get("args"))
            return real(self_, *a, **k)

        with mock.patch.object(sp.Popen, "__init__", counting):
            fn()
        return len(calls)

    def _store_with_side_branch_records(self, tmp: str, n: int) -> tuple[Path, Path]:
        root = make_repo(tmp)
        mem = init_store(root)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "store")
        base = crumb.git_branch(root)
        git(root, "checkout", "-q", "-b", "side")
        shas = []
        for i in range(n):
            (root / f"s{i}.txt").write_text("x\n")
            git(root, "add", f"s{i}.txt")
            git(root, "commit", "-qm", f"side {i}")
            shas.append(crumb.git_commit(root))
        git(root, "checkout", "-q", base)
        for i, sha in enumerate(shas):
            run(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    f"Billing retry rule {i}",
                    "--set",
                    "Decision",
                    "billing retry backoff",
                    "--evidence",
                    "file",
                    "src/billing/invoice.py",
                    "--confidence",
                    "low",
                ]
            )
            rec = sorted((mem / "decisions").glob("*.md"))[-1]
            text = rec.read_text()
            rec.write_text(text.replace(f"commit: {crumb.git_commit(root)}", f"commit: {sha}"))
        return root, mem

    def test_git_spawns_do_not_grow_with_unmerged_record_commits(self):
        counts = []
        for n in (3, 25):
            with tempfile.TemporaryDirectory() as tmp:
                root, mem = self._store_with_side_branch_records(tmp, n)
                counts.append(
                    self._spawns(
                        lambda: crumb.guard(
                            mem,
                            root,
                            "edit src/billing/invoice.py",
                            files=["src/billing/invoice.py"],
                        )
                    )
                )
        self.assertEqual(counts[0], counts[1], counts)
        self.assertLessEqual(counts[1], 12, counts)

    def test_a_read_only_command_is_skipped_by_the_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            run(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    "Cache keys are versioned",
                    "--set",
                    "Decision",
                    "cache keys versioned",
                    "--confidence",
                    "low",
                ]
            )
            run(["reindex", "--project", str(root)])
            out = hook(
                "guard",
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {
                        "command": "cd src && grep -rn 'cache keys' . 2>/dev/null | head"
                    },
                },
            )
            self.assertEqual(out, {})
            last = json.loads((mem / "private" / "hook-log.jsonl").read_text().splitlines()[-1])
            self.assertEqual(last.get("skipped"), "read-only")
