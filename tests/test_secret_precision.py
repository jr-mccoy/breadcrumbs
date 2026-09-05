"""Tests for secret-scan precision (R5) and dirty_files noise (R2).

R5 — every hit in the field store was `high-entropy-string`, and every one was a
Firebase push id quoted inside a production path. `scan-secrets` exits non-zero,
so those records blocked the memory commit and the gate was hand-overridden
every time; an entropy heuristic with no allowlist punishes exactly the records
that cite a concrete path, which are the most useful ones a store has.

R2 — 76-79% of a session record's `dirty_files` was the memory store's own
churn: the tool measuring its own footprint and reporting it as the session's
work.

Run with:  python -m unittest discover -s tests
       or:  python tests/test_secret_precision.py
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
from breadcrumbs import mcp_core  # noqa: E402

FIXTURES = REPO_ROOT / "fixtures"

PUSH_ID_LINE = (
    "confirm families/-OzbgqHUlYJcY3tHofJE/conversations/family_-OzbgqHUlYJcY3tHofJE now exists\n"
)
REAL_BLOB_LINE = "leaked dGhpc2lzYVJlYWxseUxvbmdSYW5kb21CbG9iMTIzNDU2Nzg5MA==\n"


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def init_store(tmp: str) -> Path:
    crumb.main(["init", "--project", tmp, "--session-tracking", "full"])
    return Path(tmp) / crumb.MEMORY_DIRNAME


def write_trap(mem: Path, text: str) -> None:
    with (mem / "known-traps.md").open("a", encoding="utf-8") as fh:
        fh.write("\n## trap_x: a trap\n\n- Area / files: app/x.py\n- Symptom: " + text)


class PushIdTests(unittest.TestCase):
    def test_a_push_id_in_a_path_is_not_a_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            write_trap(mem, PUSH_ID_LINE)
            self.assertEqual(_cli.scan_secrets(mem), [])

    def test_a_real_random_blob_is_still_caught(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            write_trap(mem, REAL_BLOB_LINE)
            patterns = {h["pattern"] for h in _cli.scan_secrets(mem)}
            self.assertIn("high-entropy-string", patterns)

    def test_the_canonical_leak_fixture_still_fails(self):
        code, out = run(["scan-secrets", "--project", str(FIXTURES / "fixture-06-secret-leak")])
        self.assertEqual(code, 1, out)


class SeverityTests(unittest.TestCase):
    def test_a_bare_entropy_hit_warns_without_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            write_trap(mem, REAL_BLOB_LINE)
            code, out = run(["scan-secrets", "--project", tmp])
            self.assertEqual(code, 0, out)
            self.assertIn("warning", out)
            self.assertIn("high-entropy-string", out)

    def test_a_structured_credential_still_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            write_trap(mem, "the key AKIAIOSFODNN7EXAMPLE leaked\n")
            code, out = run(["scan-secrets", "--project", tmp])
            self.assertEqual(code, 1, out)

    def test_json_separates_blocking_from_warnings(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            write_trap(mem, REAL_BLOB_LINE)
            code, out = run(["scan-secrets", "--project", tmp, "--json"])
            payload = json.loads(out)
            self.assertEqual(code, 0)
            self.assertIs(payload["ok"], True)
            self.assertEqual(payload["blocking"], 0)
            self.assertEqual(payload["warnings"], 1)

    def test_the_mcp_tool_agrees_with_the_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            write_trap(mem, REAL_BLOB_LINE)
            result = mcp_core.tool_scan_secrets(root=tmp)
            self.assertIs(result["ok"], True)
            self.assertIs(result["clean"], False)
            self.assertEqual(result["blocking"], 0)


class CrumbignoreTests(unittest.TestCase):
    def test_a_project_can_retire_a_false_positive_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            write_trap(mem, REAL_BLOB_LINE)
            self.assertTrue(_cli.scan_secrets(mem))
            (mem / _cli.CRUMBIGNORE_FILENAME).write_text(
                "# base64 in this trap is a fixture, not a credential\nleaked dGhpc2lz\n",
                encoding="utf-8",
            )
            self.assertEqual(_cli.scan_secrets(mem), [])

    def test_an_uncompilable_pattern_is_taken_literally(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            (mem / _cli.CRUMBIGNORE_FILENAME).write_text("a[b\n", encoding="utf-8")
            patterns = _cli.load_crumbignore(mem)
            self.assertEqual(len(patterns), 1)
            self.assertTrue(patterns[0].search("xxa[bxx"))

    def test_no_crumbignore_is_not_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(tmp)
            self.assertEqual(_cli.load_crumbignore(mem), [])


class DirtyFilesTests(unittest.TestCase):
    def _repo(self, tmp: str) -> Path:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "src.py").write_text("x = 1\n", encoding="utf-8")
        init_store(tmp)
        return root

    def test_a_session_record_does_not_count_the_stores_own_churn(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            run(["capture", "session", "--project", tmp, "--next", "n", "--title", "t"])
            rec = next(iter((root / crumb.MEMORY_DIRNAME / "sessions").glob("*.md")))
            dirty = _cli.Record.from_file(rec, "session").meta["dirty_files"]
            self.assertTrue(any("src.py" in f for f in dirty), dirty)
            self.assertFalse(any(crumb.MEMORY_DIRNAME in f for f in dirty), dirty)

    def test_include_memory_puts_it_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            run(
                [
                    "capture",
                    "session",
                    "--project",
                    tmp,
                    "--next",
                    "n",
                    "--title",
                    "t",
                    "--include-memory",
                ]
            )
            rec = next(iter((root / crumb.MEMORY_DIRNAME / "sessions").glob("*.md")))
            dirty = _cli.Record.from_file(rec, "session").meta["dirty_files"]
            self.assertTrue(any(crumb.MEMORY_DIRNAME in f for f in dirty), dirty)

    def test_the_staleness_check_still_sees_memory_files(self):
        """`git_dirty_files` defaults to including them — HeadTree depends on it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = self._repo(tmp)
            everything = _cli.git_dirty_files(root)
            self.assertTrue(any(crumb.MEMORY_DIRNAME in f for f in everything), everything)

    def test_the_list_is_capped_and_says_how_many_were_dropped(self):
        files = [f"src/file{i}.py" for i in range(60)]
        capped = _cli._cap_dirty_files(files)
        self.assertEqual(len(capped), _cli.DIRTY_FILES_MAX + 1)
        self.assertIn("35 more", capped[-1])

    def test_a_short_list_is_untouched(self):
        files = ["a.py", "b.py"]
        self.assertEqual(_cli._cap_dirty_files(files), files)


if __name__ == "__main__":
    unittest.main()
