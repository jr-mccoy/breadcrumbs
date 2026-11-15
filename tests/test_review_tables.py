"""Regressions for the §3 tables of docs/reviews/2026-11-13-system-review.md.

Each test names its row (R3, W4, H1, …) and fails on the code the review read.

Run with:  python -m unittest discover -s tests -p test_review_tables.py
"""

from __future__ import annotations

import contextlib
import errno
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import hooks_stop  # noqa: E402
from breadcrumbs import lock as _lock  # noqa: E402
from breadcrumbs import transcript as _transcript  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
    ).stdout


def make_repo(tmp: str) -> Path:
    root = Path(tmp)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    git(root, "config", "maintenance.auto", "false")
    git(root, "config", "gc.auto", "0")
    (root / "f.txt").write_text("a\n")
    git(root, "add", "f.txt")
    git(root, "commit", "-qm", "init")
    return root


def init_store(root: Path) -> Path:
    with contextlib.redirect_stdout(io.StringIO()):
        crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


def run(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = crumb.main(argv)
    return code, out.getvalue(), err.getvalue()


def run_hook_bytes(event: str, data: bytes, encoding: str = "utf-8") -> tuple[int, dict]:
    """`crumb hook <event>` in-process, stdin a text stream over `data`
    decoded as `encoding` would be by default (the locale of the pipe)."""
    saved = sys.stdin
    sys.stdin = io.TextIOWrapper(io.BytesIO(data), encoding=encoding)
    try:
        code, out, _err = run(["hook", event])
    finally:
        sys.stdin = saved
    text = out.strip()
    return code, (json.loads(text) if text else {})


def remember(root: Path, *extra: str) -> tuple[int, str, str]:
    return run(
        [
            "remember",
            "decision",
            "--project",
            str(root),
            "--title",
            "Cache rates per publication date",
            "--set",
            "Rationale",
            "The upstream publishes once a day.",
            "--confidence",
            "low",
            *extra,
        ]
    )


class ReadPathTests(unittest.TestCase):
    def test_r3_a_directory_named_like_a_record_is_a_finding_not_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            (mem / "decisions" / "x.md").mkdir()
            code, out, err = run(["validate", "--project", str(root)])
            self.assertEqual(code, 1)
            self.assertNotIn("Errno 21] Is a directory: 3", out + err)
            self.assertIn("decisions/x.md", out)
            code, out, err = run(["resume", "--fast", "--project", str(root)])
            self.assertEqual(code, 0, err)

    def test_r9_a_closed_pipe_is_not_a_crumb_error(self):
        class Closed(io.StringIO):
            def write(self, s):
                raise BrokenPipeError(errno.EPIPE, "Broken pipe")

            def flush(self):
                raise BrokenPipeError(errno.EPIPE, "Broken pipe")

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            for argv in (["resume"], ["--json", "resume"]):
                with self.subTest(argv=argv):
                    err = io.StringIO()
                    with (
                        mock.patch.object(sys, "stdout", Closed()),
                        contextlib.redirect_stderr(err),
                    ):
                        code = crumb.main([*argv, "--project", str(root)])
                    self.assertEqual(code, 141)
                    self.assertNotIn(_cli.ERROR_PREFIX, err.getvalue())
                    self.assertNotIn("Traceback", err.getvalue())

    @unittest.skipUnless(sys.platform.startswith("linux"), "F_SETPIPE_SZ is Linux-only")
    def test_r9_piped_to_head(self):
        import fcntl

        r, w = os.pipe()
        fcntl.fcntl(w, 1031, 4096)  # F_SETPIPE_SZ: smaller than the output
        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "crumb.py"), "--json", "search", "guard"],
            cwd=str(REPO_ROOT),
            stdout=w,
            stderr=subprocess.PIPE,
        )
        os.close(w)
        os.read(r, 10)
        os.close(r)
        err = proc.stderr.read().decode()
        proc.stderr.close()
        self.assertIn(proc.wait(), (0, 141))
        self.assertEqual(err, "")


class ReadPathOrderTests(unittest.TestCase):
    def test_r1_traps_and_questions_are_newest_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            # Written zebra, yak, xylophone: newest is alphabetically last.
            for i, name in enumerate(("zebra crossing", "yak shaving", "xylophone tuning")):
                run(["note", "trap", f"{name} breaks the build", "--project", str(root)])
                run(["note", "question", f"Should {name} stay?", "--project", str(root)])
                for kind in ("traps", "questions"):
                    for f in (mem / kind).glob("*.md"):
                        text = f.read_text(encoding="utf-8")
                        if name.split()[0] in f.name and "2026-01-0" not in text:
                            stamp = f"2026-01-0{3 - i}T00:00:00+00:00"
                            text = re.sub(
                                r"(?m)^(created_at|updated_at): .*$", rf"\1: '{stamp}'", text
                            )
                            f.write_text(text, encoding="utf-8")
            code, out, _err = run(["--json", "resume", "--project", str(root)])
            packet = json.loads(out)
            self.assertEqual(packet["ordering"], "recency")
            traps = [t.split(":", 1)[0] for t in packet["known_traps"]]
            # zebra was stamped newest, xylophone oldest.
            self.assertTrue(traps[0].startswith("trap_zebra"), traps)
            self.assertTrue(traps[-1].startswith("trap_xylophone"), traps)
            self.assertIn("zebra", packet["open_questions"][0])

    def test_r10_a_retitled_question_keeps_its_id(self):
        from breadcrumbs import packet as _packet

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            run(["note", "question", "Should the cache be per region?", "--project", str(root)])
            qfile = next((mem / "questions").glob("*.md"))
            qid = qfile.stem if qfile.stem.startswith("q_") else "q_" + qfile.stem
            run(["retitle", qid, "Is a per-region cache worth it?", "--project", str(root)])
            packet = _packet.build_resume_packet(mem, root)
            entry = packet["open_questions"][0]
            self.assertEqual(str(entry), "Is a per-region cache worth it?")
            self.assertEqual(_packet._question_id(entry), qid)
            self.assertEqual(_packet._entry_source("open_questions", entry), f"crumb show {qid}")

    def test_r2_a_branch_handoff_is_read_with_no_default_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git(root, "init", "-q", "-b", "feature-x")
            git(root, "config", "user.email", "t@t")
            git(root, "config", "user.name", "t")
            (root / "f.txt").write_text("a\n")
            git(root, "add", "f.txt")
            git(root, "commit", "-qm", "init")
            mem = init_store(root)
            handoff = mem / "handoffs" / "feature-x.md"
            handoff.parent.mkdir(exist_ok=True)
            text = (mem / "handoff.md").read_text(encoding="utf-8")
            handoff.write_text(
                text.replace(
                    "## Next Action\n", "## Next Action\nFinish the feature-x parser.\n", 1
                ),
                encoding="utf-8",
            )
            code, out, _err = run(["resume", "--project", str(root)])
            self.assertIn("Finish the feature-x parser.", out)
            self.assertIn("handoffs/feature-x.md", out)

    def test_r4_same_file_means_the_same_path(self):
        from breadcrumbs import textmatch

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            run(
                [
                    "remember", "attempt", "--project", str(root),
                    "--title", "Lazy imports in the package init",
                    "--set", "Tried", "Moved imports into pkg_a/__init__.py",
                    "--set", "Result", "Circular import at startup",
                    "--evidence", "file", "pkg_a/__init__.py",
                ]
            )  # fmt: skip

            def verdict(action):
                return json.loads(run(["--json", "guard", action, "--project", str(root)])[1])

            other = verdict("edit pkg_b/__init__.py")
            self.assertNotIn("same file", json.dumps(other))
            for action in (
                "edit pkg_a/__init__.py",
                "edit ./pkg_a/__init__.py",
                f"edit {root}/pkg_a/__init__.py",
            ):
                with self.subTest(action=action):
                    self.assertIn("same file", json.dumps(verdict(action)))
            self.assertIn("src/a.py", textmatch._norm_files({"./src/a.py"}))

    def test_r5_lists_come_back_when_the_protected_fields_shrink(self):
        import random

        rng = random.Random(1)
        words = "alpha beta gamma delta zeta theta kappa sigma cache index shard queue".split()
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            for i in range(20):
                remember_args = [
                    "remember", "decision", "--project", str(root),
                    "--title", " ".join(rng.sample(words, 6)) + f" {i}",
                    "--set", "Rationale", " ".join(rng.choice(words) for _ in range(60)),
                    "--confidence", "low", "--allow-duplicate",
                ]  # fmt: skip
                run(remember_args)
            long = "Сосредоточиться на миграции кэша и индексов. " * 100
            for name, heading in (
                ("current.md", "## Current Focus"),
                ("handoff.md", "## Next Action"),
            ):
                path = mem / name
                text = path.read_text(encoding="utf-8")
                path.write_text(
                    text.replace(heading + "\n", f"{heading}\n{long}\n", 1), encoding="utf-8"
                )
            code, out, _err = run(["--json", "resume", "--project", str(root)])
            packet = json.loads(out)
            self.assertLess(len(packet["current_focus"]), len(long))  # they shrank
            self.assertGreater(len(packet["active_decisions"]), 0)
            self.assertGreater(packet["budget"]["used"], packet["budget"]["limit"] * 0.8)

    def test_r8_a_shallow_clone_says_it_cannot_measure(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "src").mkdir()
            src = make_repo(str(Path(tmp) / "src"))
            init_store(src)
            run(["capture", "session", "--next", "Finish the parser", "--project", str(src)])
            git(src, "add", "-A")
            git(src, "commit", "-qm", "memory")
            for i in range(3):
                (src / "f.txt").write_text(f"{i}\n")
                git(src, "commit", "-qam", f"c{i}")
            clone = Path(tmp) / "clone"
            git(Path(tmp), "clone", "-q", "--depth", "1", src.as_uri(), str(clone))
            code, out, _err = run(["resume", "--project", str(clone)])
            self.assertIn("shallow clone", out)
            code, out, _err = run(["resume", "--project", str(src)])
            self.assertIn("commit(s) behind", out)
            self.assertNotIn("shallow clone", out)


class RetrievalTests(unittest.TestCase):
    def _store(self, tmp: str) -> Path:
        root = make_repo(tmp)
        init_store(root)
        for title, body in (
            ("Rebuild the projection on every write", "The projection was stale."),
            ("Release 0.6.0 pins the hook matcher", "Pinned in 0.6.0."),
            ("Кэш индексов сбрасывается при миграции", "Сбросить кэш вручную."),
            ("数据库迁移需要停机", "迁移期间停止写入。"),
        ):
            run(
                [
                    "remember", "decision", "--project", str(root), "--title", title,
                    "--set", "Rationale", body, "--confidence", "low", "--allow-duplicate",
                ]
            )  # fmt: skip
        return root

    def search(self, root: Path, query: str) -> list[str]:
        out = json.loads(run(["--json", "search", query, "--project", str(root)])[1])
        return [m.get("title", "") for m in out.get("matches", out.get("items", []))]

    def test_r6_a_word_sharing_a_stopwords_stem_is_searchable(self):
        from breadcrumbs import textmatch

        with tempfile.TemporaryDirectory() as tmp:
            root = self._store(tmp)
            self.assertTrue(any("projection" in t for t in self.search(root, "projection")))
        for word in ("projection", "note", "handler", "worker", "indexing"):
            self.assertFalse(textmatch._is_stopword(word), word)
        for word in ("changes", "fixed", "running", "the", "index"):
            self.assertTrue(textmatch._is_stopword(word), word)

    def test_r7_versions_and_non_ascii_text_are_searchable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._store(tmp)
            self.assertTrue(any("0.6.0" in t for t in self.search(root, "0.6.0")))
            self.assertTrue(any("Кэш" in t for t in self.search(root, "кэш индексов")))
            self.assertTrue(any("迁移" in t for t in self.search(root, "迁移")))

    def test_w2_a_long_token_is_linear(self):
        from breadcrumbs import textmatch

        text = "see " + "a" * 200_000 + ". and src/app/main.py"
        started = time.perf_counter()
        self.assertEqual(textmatch._paths_from_text(text), {"src/app/main.py"})
        self.assertLess(time.perf_counter() - started, 1.0)


class WritePathTests(unittest.TestCase):
    def test_w4_local_private_is_refused_before_anything_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            code, _out, err = remember(root, "--privacy", "local-private")
            self.assertNotEqual(code, 0)
            self.assertIn("jot --local", err)
            self.assertEqual(list((mem / "decisions").glob("*.md")), [])
            self.assertEqual(remember(root)[0], 0)

    def test_w5_a_read_only_store_still_resumes_and_writers_say_why(self):
        def read_only(path):
            raise OSError(errno.EROFS, "Read-only file system", str(path))

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            with mock.patch.object(_lock, "_open_lock_file", read_only):
                code, out, err = run(["resume", "--project", str(root)])
                self.assertEqual(code, 0, err)
                self.assertIn("Resume Packet", out)
                code, _out, err = remember(root)
                self.assertEqual(code, 1)
                self.assertIn("read-only", err)
                self.assertNotIn("Traceback", err)
                payload = json.dumps({"cwd": str(root), "session_id": "s", "prompt": "hi"})
                for event in ("session", "prompt", "capture"):
                    with self.subTest(event=event):
                        self.assertEqual(run_hook_bytes(event, payload.encode())[0], 0)

    def test_w7_an_interrupted_writes_temp_file_is_ignored_reported_and_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            self.assertEqual(remember(root)[0], 0)
            record = next((mem / "decisions").glob("*.md"))
            orphan = record.with_name(f".{record.name}.0123456789ab.tmp")
            orphan.write_bytes(record.read_bytes())
            fresh = record.with_name(f".{record.name}.ba9876543210.tmp")
            fresh.write_bytes(b"in progress")
            old = time.time() - 600
            os.utime(orphan, (old, old))

            # Not committable.
            git(root, "check-ignore", "-q", str(orphan))
            # Reported; one young enough to be a live write is not.
            code, out, _err = run(["validate", "--project", str(root)])
            self.assertEqual(code, 1)
            self.assertIn("[temp-files]", out)
            self.assertIn(orphan.name, out)
            self.assertNotIn(fresh.name, out)
            code, out, _err = run(["recover", "--project", str(root)])
            self.assertIn(orphan.name, out)
            self.assertTrue(orphan.exists())
            # Removed.
            run(["recover", "--apply", "--project", str(root)])
            self.assertFalse(orphan.exists())
            self.assertTrue(fresh.exists())
            fresh.unlink()
            self.assertEqual(run(["validate", "--project", str(root)])[0], 0)


class HookTests(unittest.TestCase):
    def test_h1_the_payload_is_utf8_whatever_the_locale(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "projét-Á"
            project.mkdir()
            root = make_repo(str(project))
            init_store(root)
            payload = json.dumps({"cwd": str(root), "prompt": "Á fix it"}, ensure_ascii=False)
            # cp1252 is a Windows pipe's default; the host writes UTF-8.
            code, out = run_hook_bytes("session", payload.encode("utf-8"), encoding="cp1252")
            self.assertEqual(code, 0)
            self.assertIn("additionalContext", out.get("hookSpecificOutput", {}))
            code, _out = run_hook_bytes("prompt", payload.encode("utf-8"), encoding="cp1252")
            self.assertEqual(code, 0)

    def test_h5_hostile_payloads_exit_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            (mem / "index").mkdir(exist_ok=True)
            (mem / "index" / "commit-order.txt").write_bytes(b"\xff\xfe garbage \x00\n")
            head = git(root, "rev-parse", "HEAD").strip()
            payloads = [
                '{"cwd": %s, "prompt": "x \\ud800 y", "session_id": "s"}' % json.dumps(str(root)),
                '{"cwd": %s, "n": %s}' % (json.dumps(str(root)), "9" * 5000),
                '{"cwd": %s, "prompt": "hi"}' % json.dumps(str(root) + "\u0000x"),
                '{"cwd": 5, "prompt": "hi"}',
            ]
            for event in ("session", "prompt", "guard", "capture", "compact", "subagent"):
                for raw in payloads:
                    with self.subTest(event=event, payload=raw[:40]):
                        code, _out = run_hook_bytes(event, raw.encode())
                        self.assertEqual(code, 0)
            # A cache that names HEAD but holds junk is a miss, not a history.
            (mem / "index" / "commit-order.txt").write_text(f"{head} 5000\nnot-a-sha\n")
            self.assertEqual(_cli._cached_commit_order(root)[0], head)

    def test_h7_a_tilde_transcript_path_is_expanded(self):
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as home:
            root = make_repo(tmp)
            mem = init_store(root)
            (Path(home) / "t.jsonl").write_text("")
            with mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}):
                report = _transcript.mine_transcript_into_jots(
                    mem, root, "~/t.jsonl", session_id="s"
                )
                self.assertFalse(report["missing"], report)
                report = _transcript.mine_transcript_into_jots(
                    mem, root, "~/absent.jsonl", session_id="s"
                )
                self.assertTrue(report["missing"])

    def test_h8_the_hook_log_records_no_path(self):
        status = (
            "failed: PermissionError: [Errno 13] Permission denied: "
            "'/home/someone/proj/.project-memory/sessions/a.md'"
        )
        kind = hooks_stop._error_kind(status)
        self.assertIn("Permission denied", kind)
        self.assertNotIn("/home", kind)
        self.assertNotIn("sessions/a.md", hooks_stop._error_kind("failed: exit 1: sessions/a.md"))
        self.assertEqual(hooks_stop._error_kind("failed: OSError: disk full"), "OSError: disk full")

    def test_h8_a_settings_file_of_the_wrong_shape_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            settings = root / ".claude" / "settings.json"
            settings.parent.mkdir()
            for text in ('{"hooks": []}', '{"hooks": {"PreToolUse": {"x": 1}}}', "[1]"):
                with self.subTest(settings=text):
                    settings.write_text(text)
                    code, _out, err = run(
                        ["init", "--with-hooks=session,guard", "--project", str(root)]
                    )
                    self.assertNotIn("Traceback", err)
                    self.assertEqual(settings.read_text(), text)  # nothing written
                    code, _out, err = run(["doctor", "--project", str(root)])
                    self.assertNotIn("Traceback", err)


if __name__ == "__main__":
    unittest.main(verbosity=2)
