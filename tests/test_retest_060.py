"""The DoWhat retest of 0.6.0 (docs/reviews/2026-10-03-dowhat-0.6.0-retest-plan.md).

One class per item of the report. Each test failed at 60ff21b (0.6.0 plus the
health-review extraction) and passes after its fix.

Run with:  python -m unittest discover -s tests -p test_retest_060.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli  # noqa: E402
from breadcrumbs import git as _git  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path: Path, branch: str = "main") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    for key, value in (
        ("user.email", "t@t"),
        ("user.name", "t"),
        ("commit.gpgsign", "false"),
        # Git 2.47+ runs post-commit maintenance detached; keep the tree still.
        ("maintenance.auto", "false"),
        ("gc.auto", "0"),
    ):
        git(path, "config", key, value)
    (path / "f.txt").write_text("a\n")
    git(path, "add", "f.txt")
    git(path, "commit", "-qm", "initial")
    return path


def quiet(argv: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        return crumb.main(argv)


def commit_all(root: Path, message: str) -> None:
    git(root, "add", "-A")
    git(root, "commit", "-qm", message)


class GitSpy:
    """Counts every `git` process started while it is active, by argv."""

    def __init__(self):
        self.calls: list[list[str]] = []

    def __enter__(self):
        real = subprocess.Popen.__init__
        calls = self.calls

        def spy(popen, args, *a, **k):
            if (
                isinstance(args, (list, tuple))
                and args
                and Path(str(args[0])).name
                in (
                    "git",
                    "git.exe",
                )
            ):
                calls.append([str(x) for x in args[1:]])
            return real(popen, args, *a, **k)

        self._patch = mock.patch.object(subprocess.Popen, "__init__", spy)
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


def fire_guard(root: Path, tool: str, tool_input: dict, session: str = "S") -> tuple[dict, list]:
    """One `crumb hook guard` firing, with fresh per-process memos, as the host runs it."""
    _git._IS_REPO_CACHE.clear()
    cli._OP_MEMO.clear() if hasattr(cli, "_OP_MEMO") else None
    payload = {"cwd": str(root), "session_id": session, "tool_name": tool, "tool_input": tool_input}
    old = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    buf = io.StringIO()
    try:
        with GitSpy() as spy, contextlib.redirect_stdout(buf):
            crumb.main(["hook", "guard"])
    finally:
        sys.stdin = old
    return json.loads(buf.getvalue() or "{}"), spy.calls


def set_handoff(root: Path, branch: str, commit: str) -> None:
    path = root / ".project-memory" / "handoff.md"
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"_Branch: .*_", f"_Branch: {branch}_", text)
    text = re.sub(r"_Commit: .*_", f"_Commit: {commit}_", text)
    path.write_text(text, encoding="utf-8")


ATTEMPT = [
    "remember",
    "attempt",
    "--title",
    "Deleted app/build/test-results while a test task ran",
    "--set",
    "Do Not Retry Unless",
    "no Gradle daemon is running",
    "--evidence",
    "file",
    "app/build/test-results",
]
RM = {"command": "rm -rf app/build/test-results"}


# --------------------------------------------------------------------------- #
# Item 1: git processes on every guard firing
# --------------------------------------------------------------------------- #


class NoGitOnTheGuardHookTests(unittest.TestCase):
    """At a stable HEAD a full guard firing starts no `git` process, whatever
    branch the handoff and the matched records were written on."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_repo(Path(self._tmp.name) / "repo")
        quiet(["init", "--project", str(self.root)])
        quiet([*ATTEMPT, "--project", str(self.root)])
        commit_all(self.root, "store")
        for i in range(3):
            (self.root / f"w{i}.txt").write_text(f"{i}\n")
            commit_all(self.root, f"work {i}")

    def tearDown(self):
        self._tmp.cleanup()

    def _settled_firing(self) -> tuple[dict, list]:
        fire_guard(self.root, "Bash", RM)  # may build the per-HEAD caches
        return fire_guard(self.root, "Bash", RM)

    def test_a_handoff_from_another_branch_costs_no_git(self):
        # The handoff's commit is behind HEAD and its branch is a cloud
        # session's: 0.6.0 asked git for the distance (2 processes) and whether
        # handoff.md had reached HEAD (3 more) on every firing.
        set_handoff(
            self.root, "claude/cloud-session-x1", git(self.root, "rev-parse", "--short", "HEAD~2")
        )
        commit_all(self.root, "handoff")
        out, calls = self._settled_firing()
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(calls, [])

    def test_a_record_from_another_branch_costs_no_git(self):
        # Cloud sessions write records on claude/… branches that are merged
        # later; scoring asks whether each matched one has reached HEAD.
        rec = next((self.root / ".project-memory" / "attempts").glob("*.md"))
        rec.write_text(
            re.sub(r"(?m)^branch: .*$", "branch: claude/cloud-session-x1", rec.read_text("utf-8")),
            encoding="utf-8",
        )
        quiet(["reindex", "--project", str(self.root)])
        commit_all(self.root, "record from a cloud branch")
        out, calls = self._settled_firing()
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(calls, [])

    def test_reached_head_still_tells_committed_from_modified(self):
        # The cached answer must be the answer git gave.
        from breadcrumbs import scoring

        rec = next((self.root / ".project-memory" / "attempts").glob("*.md"))
        rec.write_text(
            re.sub(r"(?m)^branch: .*$", "branch: claude/cloud-session-x1", rec.read_text("utf-8")),
            encoding="utf-8",
        )
        quiet(["reindex", "--project", str(self.root)])
        commit_all(self.root, "record from a cloud branch")
        memory = self.root / ".project-memory"

        def mismatch() -> bool:
            result = scoring.guard(memory, self.root, RM["command"])
            return any(m.get("branch_mismatch") for m in result["matches"] + result["history"])

        self.assertFalse(mismatch())  # committed and clean: it reached HEAD
        # CRLF in the work tree is how a Windows checkout (`core.autocrlf`)
        # holds the same text: it has reached HEAD all the same.
        rec.write_bytes(rec.read_bytes().replace(b"\n", b"\r\n"))
        self.assertFalse(mismatch())
        rec.write_bytes(rec.read_bytes().replace(b"\r\n", b"\n") + b"\nedited\n")
        self.assertTrue(mismatch())  # modified: not what HEAD has

    def test_the_dowhat_clone_layout_needs_no_git(self):
        # Shallow, blob-filtered, worktreeConfig, leftover REBASE_HEAD and
        # ORIG_HEAD. The origin is then removed, so any fetch would fail.
        set_handoff(
            self.root, "claude/cloud-session-x1", git(self.root, "rev-parse", "--short", "HEAD~1")
        )
        commit_all(self.root, "handoff")
        git(self.root, "config", "uploadpack.allowFilter", "true")
        clone = Path(self._tmp.name) / "DoWhat"
        git(
            Path(self._tmp.name),
            "clone",
            "-q",
            "--depth",
            "3",
            "--filter=blob:limit=1048576",
            "--no-local",
            self.root.resolve().as_uri(),
            str(clone),
        )
        git(clone, "config", "extensions.worktreeConfig", "true")
        git(clone, "config", "--worktree", "core.sparseCheckout", "false")
        git(clone, "config", "maintenance.auto", "false")
        head = git(clone, "rev-parse", "HEAD")
        (clone / ".git" / "REBASE_HEAD").write_text(head + "\n")
        (clone / ".git" / "ORIG_HEAD").write_text(head + "\n")
        self.assertTrue((clone / ".git" / "shallow").is_file())
        shutil.rmtree(self.root)
        quiet(["reindex", "--project", str(clone)])
        fire_guard(clone, "Bash", RM)
        out, calls = fire_guard(clone, "Bash", RM)
        self.assertIn("hookSpecificOutput", out)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- #
# Item 2: start-up cost on the hook path
# --------------------------------------------------------------------------- #

# Each is a module tree the guard hook does not use on a firing that starts
# no git process. `dataclasses` alone pulls in inspect, ast, dis and tokenize
# (about 10 ms on Linux, several times that on Windows). `shutil` is not here:
# argparse imports it to read the terminal width.
HOOK_UNNEEDED = ("dataclasses", "inspect", "ast", "typing", "subprocess", "tempfile")


class HookImportTests(unittest.TestCase):
    def test_the_guard_hook_loads_only_what_it_uses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp) / "repo")
            quiet(["init", "--project", str(root)])
            quiet([*ATTEMPT, "--project", str(root)])
            commit_all(root, "store")
            fire_guard(root, "Bash", RM)  # builds the per-HEAD caches
            payload = json.dumps(
                {"cwd": str(root), "session_id": "S", "tool_name": "Bash", "tool_input": RM}
            )
            # A fresh interpreter, entered the way the console script enters.
            code = (
                "import sys, io, json, contextlib\n"
                f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
                "before = set(sys.modules)\n"
                "from breadcrumbs.cli import main\n"
                "sys.stdin = io.StringIO(sys.argv[1])\n"
                "with contextlib.redirect_stdout(io.StringIO()):\n"
                "    main(['hook', 'guard'])\n"
                "print(json.dumps(sorted(set(sys.modules) - before)))\n"
            )
            env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
            out = subprocess.run(
                [sys.executable, "-c", code, payload],
                capture_output=True,
                text=True,
                check=True,
                env=env,
                cwd=str(root),
            ).stdout
            loaded = set(json.loads(out.splitlines()[-1]))
            # What this interpreter's own argparse loads to build a parser is
            # not crumb's to avoid: on Python 3.14 that is dataclasses,
            # inspect and ast (argparse colours its help through _colorize).
            probe = (
                "import sys, json\n"
                "before = set(sys.modules)\n"
                "import argparse\n"
                "argparse.ArgumentParser().add_argument('--x')\n"
                "print(json.dumps(sorted(set(sys.modules) - before)))\n"
            )
            stdlib = set(
                json.loads(
                    subprocess.run(
                        [sys.executable, "-c", probe],
                        capture_output=True,
                        text=True,
                        check=True,
                        env=env,
                    ).stdout.splitlines()[-1]
                )
            )
            self.assertEqual(sorted((loaded - stdlib) & set(HOOK_UNNEEDED)), [])


# --------------------------------------------------------------------------- #
# Items 3-7: guard precision, on the android eval store (which holds the
# report's records) and on a copy padded until `results`, `tooling` and
# `migration` are common words, as they are in the 402-record DoWhat store.
# --------------------------------------------------------------------------- #


def _load_evals():
    # Under its own name: `run` alone would shadow evals/task_replays' module.
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "crumb_evals_run_retest_060", REPO_ROOT / "evals" / "run.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_evals = _load_evals()

from breadcrumbs import scoring  # noqa: E402
from breadcrumbs import shellcmd  # noqa: E402

ANDROID = REPO_ROOT / "evals" / "suites" / "android"
ID_429 = "att_20260912_retrying-gradle-against-maven-central-on-a-cold-web"
ID_FROM_CACHE = "att_20260918_deleting-test-results-to-force-an-independent-second-full"
ID_EOL = "att_20260919_hardcoded-a-guessed-post-edit-crlf-count-in-a-line-ending"
ID_REMOTE = "att_20260920_firebase-remoteconfig-get-output-writes-a-file-named"
ID_TODOS = "att_20260910_migrationv21tov22test-s-todos-inserts-named-5-of-the-10"
ID_PROSE_ONLY = "att_20260921_second-full-suite-run-came-back-from-cache"
ID_ROOM_TEST = "att_20260705_ran-the-room-migration-test-against-an-in-memory-database"

PADDING_WORDS = "results tooling migration version install python script output check".split()


def _padding(n: int = 40) -> str:
    out = []
    for i in range(n):
        a, b = PADDING_WORDS[i % 9], PADDING_WORDS[(i + 3) % 9]
        tag = ("tooling", "migration", "ci")[i % 3]
        out.append(
            f'@2026-08-{1 + i % 28:02d} remember decision --title "Module{i} {a} and {b} stay local"\n'
            f'  --set Decision "Module{i} keeps its {a} and {b} results beside the module."\n'
            f"  --evidence file mod{i}/Thing{i}.kt --tags {tag},mod{i} --allow-duplicate\n"
        )
    return "\n".join(out)


class _StoreCase(unittest.TestCase):
    padded = False
    extra = ""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        suite = Path(cls._tmp.name) / "suite"
        suite.mkdir()
        text = (ANDROID / "store.crumb").read_text("utf-8")
        if cls.padded:
            text += "\n" + _padding()
        text += cls.extra
        (suite / "store.crumb").write_text(text, "utf-8")
        cls.root = Path(cls._tmp.name) / "project"
        cls.memory = _evals.build_store(suite, cls.root)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def guard(self, action: str, files: list[str] | None = None) -> dict:
        return scoring.guard(self.memory, self.root, action, files=files)

    def stance(self, result: dict, rid: str) -> str | None:
        return next((m["stance"] for m in result["matches"] if m["id"] == rid), None)

    def cited(self, result: dict) -> set[str]:
        return {m["id"] for m in result["matches"]}


class GeneratedFilesAreMemoryTests(_StoreCase):
    """Item 3: a record citing a generated index points at memory."""

    def test_crumb_commands_do_not_pair_with_their_generated_files(self):
        for action in ("crumb migrate", "crumb reindex", "crumb note trap 'x' --slug y"):
            with self.subTest(action=action):
                self.assertNotIn(ID_429, self.cited(self.guard(action)))

    def test_the_429_attempt_is_still_found_when_the_action_is_about_it(self):
        result = self.guard("re-run ./gradlew assembleDebug against Maven Central after HTTP 429")
        self.assertIn(ID_429, self.cited(result))

    def test_a_trap_whose_area_is_a_generated_file_still_matches_its_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp) / "repo")
            quiet(["init", "--project", str(root)])
            quiet(
                [
                    "note",
                    "trap",
                    "known-traps.md is generated; a hand edit is lost on the next reindex",
                    "--slug",
                    "hand-edited-known-traps",
                    "--area",
                    ".project-memory/known-traps.md",
                    "--project",
                    str(root),
                ]
            )
            result = scoring.guard(
                root / ".project-memory",
                root,
                "edit .project-memory/known-traps.md: tidy",
                files=[".project-memory/known-traps.md"],
            )
            self.assertIn("trap_hand-edited-known-traps", {m["id"] for m in result["matches"]})


class NamedPathObjectsTests(_StoreCase):
    """Item 4: a path the action names and the record cites makes it topical."""

    padded = True
    extra = """
@2026-09-21 remember attempt --title "Second full-suite run came back FROM-CACHE"
  --set Tried "rm -rf app/build/test-results/ and ran the suite again"
  --set Do\\ Not\\ Retry\\ Unless "you also pass --rerun-tasks"
  --tags gradle --confidence low --allow-duplicate
"""

    def test_the_from_cache_attempt_objects_to_deleting_its_directory(self):
        result = self.guard("rm -rf app/build/test-results")
        self.assertEqual(self.stance(result, ID_FROM_CACHE), "blocking")

    def test_a_trailing_slash_is_the_same_path(self):
        from breadcrumbs import textmatch

        self.assertTrue(
            textmatch._norm_files(["app/build/test-results/"])
            & textmatch._norm_files(["app/build/test-results"])
        )

    def test_a_path_cited_only_in_prose_counts_too(self):
        # No file evidence: the path is in what it tried.
        result = self.guard("rm -rf app/build/test-results")
        self.assertEqual(self.stance(result, ID_PROSE_ONLY), "blocking")


class ObjectionsNeedTheActionTests(_StoreCase):
    """Item 5: a tag plus a few shared words is a match, not an objection."""

    TIMING = (
        "for i in 1 2 3; do time ~/.local/share/uv/tools/crumb-kit/Scripts/python.exe -c pass; "
        "time crumb --version; time bash -c 'exit 0'; done"
    )
    UV = 'uv tool install --force --refresh-package crumb-kit --python 3.13 "crumb-kit[mcp]>=0.6.0"'

    def test_the_tooling_attempts_do_not_object_to_unrelated_commands(self):
        for action in (self.TIMING, self.UV):
            with self.subTest(action=action[:30]):
                result = self.guard(action)
                for rid in (ID_EOL, ID_REMOTE):
                    self.assertNotEqual(self.stance(result, rid), "blocking")
                self.assertNotIn(result["verdict"], ("PAUSE", "ASK_HUMAN"))

    def test_a_room_builder_edit_shows_no_blocking_record(self):
        result = self.guard("add fallbackToDestructiveMigration() to the Room database builder")
        self.assertEqual([m["id"] for m in result["matches"] if m["stance"] == "blocking"], [])

    def test_objections_about_the_action_still_object(self):
        cases = {
            "./gradlew --stop": "att_20260720_ran-gradlew-stop-on-a-stoprequested-daemon-that-was-a-live",
            "rm -rf app/build/test-results": "att_20260709_deleted-app-build-test-results-to-clear-stale-reports",
            "retry the Gradle download from Maven Central on a cold web container": ID_429,
        }
        for action, rid in cases.items():
            with self.subTest(action=action):
                self.assertEqual(self.stance(self.guard(action), rid), "blocking")


class PaddedObjectionsTests(ObjectionsNeedTheActionTests):
    padded = True


class PackageInstallForceTests(unittest.TestCase):
    """N1: `--force` on a package install reinstalls; it destroys nothing."""

    def test_a_forced_install_is_not_destructive(self):
        for command in (
            'uv tool install --force --refresh-package crumb-kit "crumb-kit[mcp]>=0.6.0"',
            "pip install --force-reinstall crumb-kit",
            "npm install --force",
        ):
            with self.subTest(command=command):
                self.assertFalse(scoring._is_destructive(command, []))

    def test_force_elsewhere_still_is(self):
        for command in (
            "git push --force origin feature",
            "uv tool install x && git push --force origin feature",
            "git clean -fdx",
        ):
            with self.subTest(command=command):
                self.assertTrue(scoring._is_destructive(command, []))


class CrumbBehindAShellKeywordTests(unittest.TestCase):
    """Item 5b: `do crumb …`, `time crumb …` are crumb commands."""

    def test_keyword_and_prefix_forms_are_recognised(self):
        for command in (
            'while read a; do crumb guard "$a"; done',
            "time crumb --version",
            "if true; then crumb reindex; fi",
            "! crumb validate",
        ):
            with self.subTest(command=command):
                self.assertNotIn("crumb", shellcmd.without_crumb(command).split())

    def test_a_loop_body_is_still_read(self):
        self.assertEqual(
            shellcmd.high_impact("for b in x; do git push --force origin main; done"),
            "force-push to main",
        )


class TempFileDeletionTests(_StoreCase):
    """Item 6: deleting a scratch file is not a deletion."""

    REPORT = (
        'cp .project-memory/handoff.md "$TEMP/handoff.before" && crumb capture session '
        '--next "retest done" && diff "$TEMP/handoff.before" .project-memory/handoff.md; '
        'rm -f "$TEMP/handoff.before"'
    )

    def test_the_report_command_does_not_ask(self):
        self.assertNotEqual(self.guard(self.REPORT)["verdict"], "ASK_HUMAN")

    def test_scratch_deletions_are_routine(self):
        for command in (
            'rm -f "$TEMP/handoff.before"',
            "rm -f /tmp/out.json",
            'rm -f "${TMPDIR:-/tmp}/x"',
            'rm -f "%TEMP%\\x.txt"',
            "rm -rf $TMPDIR/scratch",
            "rm -f /c/Users/me/AppData/Local/Temp/x.txt",
            "cp a.txt backup.txt && diff a.txt backup.txt; rm -f backup.txt",
            "git diff > patch.txt; rm patch.txt",
        ):
            with self.subTest(command=command):
                self.assertNotIn("deletion", scoring.classify_action(command)[1])
                self.assertFalse(
                    scoring._is_destructive(command, scoring.classify_action(command)[1])
                )

    def test_real_deletions_still_count(self):
        for command in ("rm -f src/main.kt", "rm -rf src", "rm -f backup.txt", "rm -rf ~/tmp-not"):
            with self.subTest(command=command):
                self.assertIn("deletion", scoring.classify_action(command)[1])
        self.assertEqual(shellcmd.high_impact("rm -rf app/src"), "rm -rf app/src")


class HeredocDataTests(_StoreCase):
    """Item 7: a heredoc fed to `while read`, `cat >` or `python -` is data."""

    LOOP = (
        "while read a; do crumb guard \"$a\" --json | head -3; done <<'EOS'\n"
        "crumb migrate\ngit push --force origin main\n.project-memory/known-traps.md\nEOS"
    )

    def test_the_report_loop_does_not_ask(self):
        result = self.guard(self.LOOP)
        self.assertNotEqual(result["verdict"], "ASK_HUMAN")
        self.assertFalse(result["destructive"])

    def test_data_heredocs_are_not_destructive(self):
        for command in (
            "cat > notes.md <<'EOF'\nnever git push --force origin main\nEOF",
            "python - <<'PY'\nprint('rm -rf build')\nPY",
        ):
            with self.subTest(command=command[:20]):
                self.assertFalse(scoring._is_destructive(command, []))

    def test_a_heredoc_fed_to_a_shell_is_code(self):
        for command in (
            "bash <<'EOF'\ngit push --force origin main\nEOF",
            "ssh host <<EOF\nrm -rf /srv/app\nEOF",
            "psql prod <<'SQL'\nDROP TABLE users;\nSQL",
        ):
            with self.subTest(command=command[:20]):
                self.assertTrue(scoring._is_destructive(command, []))


# --------------------------------------------------------------------------- #
# Item 8: a 10.2 s Stop firing
# --------------------------------------------------------------------------- #


class StopFiringTimingsTests(unittest.TestCase):
    """A Stop firing logs where its time went, and doctor names the slowest."""

    def test_a_snapshot_firing_logs_mine_and_snapshot_time(self):
        from breadcrumbs import hooklog

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(Path(tmp) / "repo")
            quiet(["init", "--project", str(root)])
            commit_all(root, "store")
            (root / "work.txt").write_text("changed\n")
            transcript = Path(tmp) / "t.jsonl"
            transcript.write_text("")
            payload = {"cwd": str(root), "session_id": "S", "transcript_path": str(transcript)}
            old = sys.stdin
            sys.stdin = io.StringIO(json.dumps(payload))
            try:
                with contextlib.redirect_stdout(io.StringIO()):
                    crumb.main(["hook", "capture"])
            finally:
                sys.stdin = old
            memory = root / ".project-memory"
            last = hooklog.read_log(memory)[-1]
            self.assertEqual(last.get("snapshot"), "ok")
            self.assertIsInstance(last.get("mine_ms"), (int, float))
            self.assertIsInstance(last.get("snapshot_ms"), (int, float))
            summary = hooklog.summarize(hooklog.read_log(memory))
            slowest = summary["events"]["capture"]["slowest"]
            self.assertIn("snapshot_ms", slowest)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                crumb.main(["doctor", "--hook-log", "--project", str(root)])
            self.assertIn("slowest", out.getvalue())
            self.assertIn("snapshot", out.getvalue())
