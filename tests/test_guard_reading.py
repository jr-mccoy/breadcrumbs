"""Guard reads a shell command the way the shell does (review 2026-11-13,
§6 item 5: §2.4, §2.8 and §5.3).

- **Here-documents.** `<<<` and a quoted `<<` were read as here-documents, and
  every later line, real commands included, became data.
- **Redirects.** `cat /dev/null>file` (no space) was read-only.
- **Writers called read-only.** `sort -o`, `uniq in out`, `yq -i`, `fd -X`,
  `rg --pre`, `git reflog expire`, `git -c`, `--output=`, sed `w` after a label.
- **Wrappers.** `sudo`, `env`, `timeout`, `bash -c`, a code heredoc and `$(…)`
  hid the command from the always-ask floor.
- **The floor's spellings.** `--force-with-lease`, `refs/heads/main`, deleting
  `main`, `rm -rf build/../src`, `rm -rf /tmp`, `$tmp/…`, `crumb --project .
  migrate`.
- **`edit X: …` from a Bash tool** skipped the floor as if it were a file edit.
- **A `crumb <sub>` trap** could not fire on that command.
- **Index parity.** With the search index built, an attempt naming the exact
  command was never loaded.

The property tests at the end say what the case lists only sample: rewriting a
command the way an agent does (a wrapper, a second line, a missing space) never
makes it look safer.

Run with:  python -m unittest discover -s tests -p test_guard_reading.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import scoring, searchindex, shellcmd  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, out.getvalue()


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


class HereDocumentTests(unittest.TestCase):
    def test_a_here_string_is_not_a_here_document(self):
        cmd = "cat <<< hello\nrm -rf src"
        self.assertIn("rm -rf src", shellcmd.strip_heredocs(cmd))
        self.assertEqual(shellcmd.segments(cmd), ["cat <<< hello", "rm -rf src"])
        self.assertFalse(shellcmd.is_read_only(cmd))
        self.assertEqual(shellcmd.high_impact(cmd), "rm -rf src")

    def test_a_quoted_operator_is_not_a_here_document(self):
        for first in ('grep -c "a << b" notes.txt', "python3 -c 'print(1 << n)'"):
            cmd = first + "\ngit push --force origin main"
            with self.subTest(first=first):
                self.assertEqual(shellcmd.high_impact(cmd), "force-push to main")

    def test_a_real_here_document_is_still_data(self):
        cmd = "cat > notes.md <<'EOF'\nrm -rf src\ngit push --force origin main\nEOF\necho done"
        self.assertEqual(shellcmd.strip_heredocs(cmd), "cat > notes.md <<'EOF'\necho done")
        self.assertIsNone(shellcmd.high_impact(cmd))

    def test_a_here_document_a_shell_runs_is_code(self):
        self.assertEqual(shellcmd.high_impact("bash <<EOF\nrm -rf src\nEOF"), "rm -rf src")

    def test_quotes_inside_a_body_do_not_leak(self):
        cmd = "cat <<EOF\ndon't stop\nEOF\nrm -rf src"
        self.assertEqual(shellcmd.high_impact(cmd), "rm -rf src")


class RedirectTests(unittest.TestCase):
    def test_no_space_before_the_operator_is_still_a_write(self):
        for cmd in ("cat /dev/null>src/main.py", "echo $HOME>f", "cat a.txt>b.txt", "cat a>>b"):
            with self.subTest(cmd=cmd):
                self.assertFalse(shellcmd.is_read_only(cmd))
                self.assertTrue(shellcmd.split_redirections(cmd)[1])

    def test_a_digit_in_a_word_is_not_a_descriptor(self):
        body, targets = shellcmd.split_redirections("echo a2>err")
        self.assertEqual((body.strip(), targets), ("echo a2", ["err"]))

    def test_discarding_output_is_still_read_only(self):
        for cmd in ("cat x 2>/dev/null", "grep -r x . 2>&1 | head", "git log >/dev/null 2>&1"):
            with self.subTest(cmd=cmd):
                self.assertTrue(shellcmd.is_read_only(cmd))


class ReadOnlyTests(unittest.TestCase):
    WRITERS = (
        "sort --output=important.txt x",
        "sort -oimportant.txt x",
        "sort -o out x",
        "yq -i '.version = 2' config.yml",
        "yq --inplace '.a = 1' f.yml",
        "fd -e log -X rm -rf",
        "fd . -x rm {}",
        "fd --exec rm",
        "git reflog expire --expire=now --all",
        "git reflog delete HEAD@{1}",
        "git diff --output=x.patch",
        "git log --output x.txt",
        "git -c core.pager=evil log",
        "find . -fprint0 out",
        "uniq in out",
        "xxd -r dump bin",
        "rg --pre ./decode x",
        "rg --pre=./decode x",
        "tree -o out.txt",
        "date -s 2020-01-01",
        "sed ':a;N;$!ba;w out.txt' in.txt",
        "sed --in-pl 's/a/b/' f.txt",
        "echo \\'$(git push --force origin main)\\'",
        "command rm -rf src",
    )
    READERS = (
        "sort x",
        "sort -k2 -t, x",
        "uniq x",
        "yq .a f.yml",
        "fd -e py",
        "git reflog",
        "git reflog show",
        "git log --oneline -5",
        "git diff HEAD~1",
        "xxd file",
        "rg -n todo src",
        "tree -L 2",
        "date",
        "sed -n '1,5p' f",
        "command -v rm",
        "cat <<< hello",
        "sudo cat /var/log/syslog",
        "env | grep PATH",
    )

    def test_writers_are_not_read_only(self):
        for cmd in self.WRITERS:
            with self.subTest(cmd=cmd):
                self.assertFalse(shellcmd.is_read_only(cmd))

    def test_readers_still_are(self):
        for cmd in self.READERS:
            with self.subTest(cmd=cmd):
                self.assertTrue(shellcmd.is_read_only(cmd))


class WrapperTests(unittest.TestCase):
    def test_wrappers_are_unwrapped(self):
        cases = {
            "sudo rm -rf src": ["rm", "-rf", "src"],
            "sudo -u bob -E rm -rf src": ["rm", "-rf", "src"],
            "env FOO=1 rm -rf src": ["rm", "-rf", "src"],
            "env -i -u HOME PATH=/bin rm -rf src": ["rm", "-rf", "src"],
            "env -S 'rm -rf src'": ["rm", "-rf", "src"],
            "timeout 10 rm -rf src": ["rm", "-rf", "src"],
            "timeout -s KILL 10s rm -rf src": ["rm", "-rf", "src"],
            "nice -n 5 rm -rf src": ["rm", "-rf", "src"],
            "command rm -rf src": ["rm", "-rf", "src"],
            "sudo env FOO=1 nice rm -rf src": ["rm", "-rf", "src"],
            "stdbuf -oL rm -rf src": ["rm", "-rf", "src"],
        }
        for cmd, expected in cases.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(shellcmd.words(cmd), expected)

    def test_a_bare_wrapper_is_itself(self):
        self.assertEqual(shellcmd.words("env"), ["env"])
        self.assertEqual(shellcmd.words("sudo -l"), ["sudo", "-l"])
        self.assertEqual(shellcmd.words("command -v rm"), ["command", "-v", "rm"])

    def test_the_floor_sees_through_them(self):
        for cmd in (
            "sudo rm -rf src",
            "env FOO=1 rm -rf src",
            "bash -c 'rm -rf src'",
            "sh -lc 'git push --force origin main'",
            "timeout 30 git push -f origin main",
            "eval 'rm -rf src'",
            "rm -rf src $(echo x)",
            "echo \\'$(git push --force origin main)\\'",
            "sudo crumb migrate",
            "find . | xargs --max-args 1 rm -rf",
        ):
            with self.subTest(cmd=cmd):
                self.assertIsNotNone(shellcmd.high_impact(cmd))


class FloorSpellingTests(unittest.TestCase):
    ASK = {
        "git push --force-with-lease origin main": "force-push to main",
        "git push --force-with-lease=main:abc origin main": "force-push to main",
        "git push --force-if-includes --force origin main": "force-push to main",
        "git push -f origin refs/heads/main": "force-push to main",
        "git push origin +refs/heads/main": "force-push to main",
        "git push origin HEAD:main --force": "force-push to main",
        "git -C repo push --force origin main": "force-push to main",
        "git push -o ci.skip --force origin main": "force-push to main",
        "git push --delete origin main": "push deleting main",
        "git push origin :main": "push deleting main",
        "git push origin --delete refs/heads/master": "push deleting master",
        "crumb --project . migrate": "crumb migrate rewrites the memory store",
        "python crumb.py --project /x migrate": "crumb migrate rewrites the memory store",
        "rm -rf build/../src": "rm -rf build/../src",
        "rm -rf ./dist/../..": "rm -rf ./dist/../..",
        "rm -rf /tmp/../etc": "rm -rf /tmp/../etc",
        "rm -rf /tmp": "rm -rf /tmp",
        "rm -rf ~/reports": "rm -rf ~/reports",
        "rm -rf /home/me/project/build": "rm -rf /home/me/project/build",
        "tmp=$HOME/work; rm -rf $tmp/src": "rm -rf $tmp/src",
    }
    PROCEED = (
        "rm -rf build",
        "rm -rf ./dist node_modules",
        "rm -rf target/debug",
        "rm -rf /tmp/scratch-1",
        'rm -rf "$TMPDIR/foo"',
        "rm -rf $TMP/x",
        "git push --force origin feature-x",
        "git push origin main",
        "git push --force-with-lease origin my-branch",
        "git push origin --delete old-feature",
        "crumb migrate --dry-run",
        "crumb --project . resume",
    )

    def test_each_spelling_asks(self):
        for cmd, why in self.ASK.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(shellcmd.high_impact(cmd), why)

    def test_ordinary_forms_do_not(self):
        for cmd in self.PROCEED:
            with self.subTest(cmd=cmd):
                self.assertIsNone(shellcmd.high_impact(cmd))

    def test_crumb_effect_skips_the_project_value(self):
        self.assertEqual(shellcmd.crumb_effect(["--project", ".", "migrate"]), "migration")
        self.assertEqual(shellcmd.crumb_effect(["--project=.", "resume"]), "read_only")
        self.assertEqual(
            shellcmd.crumb_effect(["--json", "--project", "x", "search", "q"]), "read_only"
        )


# --------------------------------------------------------------------------- #
# Guard, end to end
# --------------------------------------------------------------------------- #


class Store(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        run(["init", "--project", str(self.root)])
        self.mem = self.root / crumb.MEMORY_DIRNAME

    def verdict(self, action: str, **kw) -> dict:
        return scoring.guard(self.mem, self.root, action, staleness=False, **kw)


class ShellEditTests(Store):
    def test_a_shell_command_shaped_like_an_edit_still_asks(self):
        action = "edit notes: ; rm -rf src"
        self.assertEqual(self.verdict(action, shell=True)["verdict"], "ASK_HUMAN")

    def test_the_hook_passes_shell_for_bash(self):
        payload = {
            "cwd": str(self.root),
            "session_id": "s1",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "edit notes: ; rm -rf src"},
        }
        out = io.StringIO()
        with (
            mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
            mock.patch.dict(os.environ, {"CLAUDE_PROJECT_DIR": "", "BREADCRUMBS_PROJECT": ""}),
            contextlib.redirect_stdout(out),
        ):
            crumb.main(["hook", "guard"])
        self.assertEqual(
            json.loads(out.getvalue())["hookSpecificOutput"]["permissionDecision"], "ask"
        )

    def test_a_file_edit_is_still_an_edit(self):
        self.assertIsNone(self.verdict("edit notes.md: rm -rf src is in the README")["high_impact"])


class CrumbSubcommandTrapTests(Store):
    def setUp(self):
        super().setUp()
        run(
            [
                "note", "trap", "crumb rename deletes the record it renames",
                "--why", "w", "--project", str(self.root),
            ]
        )  # fmt: skip

    def test_the_trap_fires_on_its_command(self):
        for action in (
            "crumb rename dec_x --slug y",
            "python crumb.py rename dec_x --slug short",
            "crumb --project . rename dec_x --slug y",
        ):
            with self.subTest(action=action):
                res = self.verdict(action)
                self.assertNotEqual(res["verdict"], "PROCEED", action)
                ids = [m["id"] for m in res.get("matches", [])]
                self.assertIn("trap_crumb-rename-deletes-the-record-it-renames", ids)

    def test_another_subcommand_does_not(self):
        res = self.verdict("crumb remember decision --title x --set Decision y")
        ids = [m["id"] for m in res.get("matches", [])]
        self.assertNotIn("trap_crumb-rename-deletes-the-record-it-renames", ids)


class IndexParityTests(Store):
    """`make build --jobs 4`: `make` and `build` are stopwords, so the only stem
    is `job`, and the index never returned the attempt naming the command."""

    def setUp(self):
        super().setUp()
        for i in range(searchindex.INDEX_MIN_CORPUS + 5):
            crumb.write_record(
                self.mem,
                self.root,
                "decision",
                f"Filler decision {i} about subsystem {i}",
                {"Decision": f"filler {i}"},
                confidence="low",
            )
        code, _ = run(
            [
                "remember", "attempt", "--project", str(self.root),
                "--title", "make build wipes the fixture directory",
                "--problem", "p", "--tried", "t", "--result", "r", "--why", "w",
                "--do-not-retry", "unless the clean dependency is removed",
                "--evidence", "file", "Makefile",
            ]
        )  # fmt: skip
        self.assertEqual(code, 0)
        run(["reindex", "--search-index", "--project", str(self.root)])

    def test_indexed_and_full_scan_agree(self):
        info: dict = {}
        scoring.search(self.mem, self.root, "make build --jobs 4", info=info)
        self.assertEqual(info.get("mode"), "indexed", info)
        indexed = self.verdict("make build --jobs 4")
        (self.mem / "index" / "search.sqlite").unlink()
        full = self.verdict("make build --jobs 4")
        self.assertEqual(full["verdict"], "READ_FIRST", full)
        self.assertEqual(indexed["verdict"], full["verdict"])
        self.assertEqual([m["id"] for m in indexed["matches"]], [m["id"] for m in full["matches"]])


# --------------------------------------------------------------------------- #
# Properties
# --------------------------------------------------------------------------- #

# What an agent does to a command without changing what it does.
REWRITES = {
    "sudo": lambda c: "sudo " + c,
    "env": lambda c: "env CI=1 " + c,
    "timeout": lambda c: "timeout 60 " + c,
    "nohup": lambda c: "nohup " + c,
    "command": lambda c: "command " + c,
    "bash -c": lambda c: "bash -c " + shlex.quote(c),
    "cd prefix": lambda c: "cd sub && " + c,
    "trailing true": lambda c: c + "; true",
    "second line": lambda c: c + "\necho done",
    "here-string first": lambda c: "cat <<< hello\n" + c,
    "quoted << first": lambda c: 'grep -c "a << b" notes.txt\n' + c,
    "heredoc first": lambda c: "cat > n.md <<'EOF'\nx\nEOF\n" + c,
}

HIGH_IMPACT = (
    "rm -rf src",
    "rm -rf ../shared",
    "git push --force origin main",
    "git push -f origin master",
    "git push origin +main",
    "git push --delete origin main",
    "crumb migrate",
)

NOT_READ_ONLY = (
    "rm notes.txt",
    "sed -i s/a/b/ f",
    "git commit -m x",
    "cat a > b",
    "sort -o out x",
    "npm install",
    "find . -delete",
)


class PropertyTests(unittest.TestCase):
    def test_a_rewrite_never_hides_a_high_impact_action(self):
        for cmd in HIGH_IMPACT:
            for name, rewrite in REWRITES.items():
                with self.subTest(cmd=cmd, rewrite=name):
                    self.assertIsNotNone(shellcmd.high_impact(rewrite(cmd)), rewrite(cmd))

    def test_a_rewrite_never_makes_a_writer_read_only(self):
        for cmd in NOT_READ_ONLY:
            for name, rewrite in REWRITES.items():
                with self.subTest(cmd=cmd, rewrite=name):
                    self.assertFalse(shellcmd.is_read_only(rewrite(cmd)), rewrite(cmd))

    def test_removing_the_space_before_a_redirect_changes_nothing(self):
        for cmd in ("cat a > b", "echo x >> log", "printf y > out.txt"):
            tight = cmd.replace(" > ", ">").replace(" >> ", ">>")
            with self.subTest(cmd=tight):
                self.assertEqual(
                    shellcmd.split_redirections(cmd)[1], shellcmd.split_redirections(tight)[1]
                )
                self.assertFalse(shellcmd.is_read_only(tight))

    def test_a_rewrite_never_lowers_a_guard_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            run(["init", "--project", tmp])
            mem = root / crumb.MEMORY_DIRNAME
            run(
                [
                    "remember", "attempt", "--project", tmp,
                    "--title", "Editing deploy config in place broke the rollout",
                    "--problem", "p", "--tried", "sed on config/deploy.yml",
                    "--result", "outage", "--why", "w",
                    "--do-not-retry", "the schema validator passes",
                    "--evidence", "file", "config/deploy.yml",
                ]
            )  # fmt: skip
            rank = scoring._VERDICT_RANK
            for cmd in (
                "sed -i 's/1/2/' config/deploy.yml",
                "cat /dev/null > config/deploy.yml",
                *HIGH_IMPACT,
            ):
                base = scoring.guard(mem, root, cmd, staleness=False)["verdict"]
                for name, rewrite in REWRITES.items():
                    if name == "cd prefix":
                        continue  # a relative path names another file from sub/
                    got = scoring.guard(mem, root, rewrite(cmd), staleness=False)["verdict"]
                    with self.subTest(cmd=cmd, rewrite=name):
                        self.assertGreaterEqual(
                            rank[got], rank[base], f"{rewrite(cmd)!r}: {got} < {base}"
                        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
