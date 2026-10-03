"""The same store behaves the same on every platform (audit WP17).

The native macOS and Windows jobs ran the full suite for the first time and
found defects that Linux could not show. Each is pinned here in a form Linux
*can* run, so the gating jobs hold them:

- a directory has several spellings (macOS `/var` and `/private/var`, a
  Windows 8.3 short name), and the generation's stat fingerprint named files by
  absolute path, so a hook reading through the other spelling never trusted the
  prefilter;
- Windows writes CRLF, and git's autocrlf checks a store out with CRLF; the
  inputs hash, the generation's file digests and the lenient reader all treated
  line endings as content;
- `cmd.exe` exits 1, not 9009, when it cannot find a program, so a missing
  runner read as a failed assertion;
- `configure_output` probed the *current* markers, so a second call after an
  ASCII choice switched back to glyphs a cp1252 console cannot print.
"""

from __future__ import annotations

import ast
import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crumb  # noqa: E402
from breadcrumbs import checks, projections, searchindex  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402


def _run(argv):
    with (
        contextlib.redirect_stdout(io.StringIO()) as out,
        contextlib.redirect_stderr(io.StringIO()),
    ):
        code = crumb.main(argv)
    return code, out.getvalue()


def _store(root: Path) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    _run(["init", "--project", str(root), "--session-tracking", "full"])
    mem = root / crumb.MEMORY_DIRNAME
    crumb.write_record(
        mem,
        root,
        "attempt",
        "Batched the billing reconciler writes",
        {"Tried": "batched writes", "Do Not Retry Unless": "an idempotency key exists"},
        evidence=[{"type": "file", "ref": "src/billing.py"}],
    )
    _cli.try_reindex_projections(mem, root)
    return mem


def _flip_line_endings(directory: Path) -> int:
    """Rewrite every Markdown file with the other line ending (as a checkout on
    the other platform would); return how many changed."""
    changed = 0
    for p in directory.rglob("*.md"):
        data = p.read_bytes()
        lf = data.replace(b"\r\n", b"\n")
        flipped = lf if lf != data else lf.replace(b"\n", b"\r\n")
        if flipped != data:
            p.write_bytes(flipped)
            changed += 1
    return changed


class PathSpellingTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, "symlink"), "needs symlinks")
    def test_a_generation_is_trusted_through_another_spelling_of_its_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real"
            real.mkdir()
            try:
                os.symlink(real, Path(tmp) / "alias", target_is_directory=True)
            except OSError as exc:  # pragma: no cover - Windows without the privilege
                self.skipTest(f"cannot create a symlink: {exc}")
            mem = _store(real)
            alias = Path(tmp) / "alias"
            name = crumb.GUARD_PREFILTER_FILENAME
            self.assertIsNotNone(projections.verified(mem, real, name))
            self.assertEqual(
                searchindex._stat_fingerprint(mem, real),
                searchindex._stat_fingerprint(alias / crumb.MEMORY_DIRNAME, alias),
            )
            self.assertIsNotNone(
                projections.verified(alias / crumb.MEMORY_DIRNAME, alias, name),
                "the prefilter was never trusted through the other spelling",
            )


class LineEndingTests(unittest.TestCase):
    def test_the_inputs_hash_ignores_line_endings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mem = _store(root)
            before = _cli._inputs_hash(mem, root)
            self.assertGreater(_flip_line_endings(mem), 0)
            self.assertEqual(_cli._inputs_hash(mem, root), before)
            # ...and a real edit still moves it.
            handoff = mem / "handoff.md"
            handoff.write_bytes(handoff.read_bytes() + b"edited\r\n")
            self.assertNotEqual(_cli._inputs_hash(mem, root), before)

    def test_a_crlf_checkout_keeps_its_generation_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mem = _store(root)
            # A committed projection: the guard pre-filter is machine-local
            # (index/) since 0.6.0, so a checkout never rewrites its endings.
            name = "related.json"
            generated = mem / "generated" / name
            generated.write_bytes(
                generated.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            )
            # Rewriting moved its mtime but not the canonical inputs.
            self.assertIsNotNone(projections.verified(mem, root, name))
            generated.write_bytes(b'{"paths": [], "tokens": []}\r\n')
            self.assertIsNone(projections.verified(mem, root, name), "other content")

    def test_audit_sees_a_crlf_adapter_copying_a_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _run(["init", "--project", str(root), "--session-tracking", "full"])
            mem = root / crumb.MEMORY_DIRNAME
            rec_path, _ = crumb.write_record(
                mem,
                root,
                "decision",
                "keep memory in plain files",
                {
                    "Decision": "plain markdown is canonical",
                    "Rationale": "a read-only agent can read it without any tooling, "
                    "a human can review it in any diff view, and no database or index "
                    "has to exist for the memory to survive a checkout on a new machine",
                },
                tags=["memory"],
                evidence=[{"type": "commit", "ref": "abc1234"}],
            )
            body = Path(rec_path).read_text(encoding="utf-8")
            (root / "CLAUDE.md").write_bytes(
                ("# signpost\n\n" + body).replace("\n", "\r\n").encode("utf-8")
            )
            kinds = {f.get("kind") for f in crumb.run_audit(mem, root) if f["check"] == "bloat"}
            self.assertIn("adapter-duplication", kinds)


class CmdUnavailableTests(unittest.TestCase):
    def test_the_program_a_command_line_starts_with(self):
        cases = {
            "definitely-not-a-real-tool --check": "definitely-not-a-real-tool",
            '"C:\\Program Files\\x\\tool.exe" -v': "C:\\Program Files\\x\\tool.exe",
            "@echo off": "echo",
            "foo&&bar": "foo",
            "  pytest -q": "pytest",
        }
        for command, word in cases.items():
            with self.subTest(command=command):
                self.assertEqual(checks._first_word(command), word)

    def test_a_missing_program_is_told_from_a_failing_one(self):
        here = Path.cwd()
        self.assertTrue(checks._cmd_cannot_find("definitely-not-a-real-tool-4f1c --check", here))
        self.assertFalse(
            checks._cmd_cannot_find(f'"{sys.executable}" -c "raise SystemExit(1)"', here)
        )
        # An internal command has no file, and cmd.exe still runs it.
        self.assertFalse(checks._cmd_cannot_find("echo hi && exit /b 1", here))
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "build.cmd").write_text("exit /b 1\n")
            self.assertFalse(checks._cmd_cannot_find("build.cmd", Path(tmp)))


class RelativePathRenderingTests(unittest.TestCase):
    def test_no_store_relative_path_is_rendered_with_os_separators(self):
        """`str(p.relative_to(x))` is backslashed on Windows. Findings, JSON
        and the write gates compare these strings, so one native rendering
        against POSIX ones silently matched nothing there: the gate that
        refuses an invalid write let it through (CI run 247). Linux cannot
        show the difference, so the pattern itself is refused."""
        offenders = []
        for path in sorted((ROOT / "breadcrumbs").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "str"
                    and node.args
                    and isinstance(node.args[0], ast.Call)
                    and isinstance(node.args[0].func, ast.Attribute)
                    and node.args[0].func.attr == "relative_to"
                ):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
                if (  # the same rendering inside an f-string
                    isinstance(node, ast.FormattedValue)
                    and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr == "relative_to"
                ):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
        self.assertEqual(offenders, [], "use path_policy.posix_rel() for a store-relative path")

    def test_posix_conversion_is_path_policys(self):
        """`x.relative_to(y).as_posix()` and `.replace("\\", "/")` were open-coded
        some 30 times across 12 modules (deferred health review 2.2). One spelling,
        `path_policy.posix_rel` / `path_policy.to_posix`, keeps the store-relative
        POSIX rule in one place."""
        offenders = []
        for path in sorted((ROOT / "breadcrumbs").rglob("*.py")):
            if path.name == "path_policy.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                    continue
                inner = node.func.value
                if (
                    node.func.attr == "as_posix"
                    and isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "relative_to"
                ):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
                if (
                    node.func.attr == "replace"
                    and len(node.args) == 2
                    and all(isinstance(a, ast.Constant) for a in node.args)
                    and [a.value for a in node.args] == ["\\", "/"]
                ):
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
        self.assertEqual(offenders, [], "use path_policy.posix_rel() / path_policy.to_posix()")


class ConsoleMarkerTests(unittest.TestCase):
    def test_a_second_configuration_keeps_ascii_markers_on_cp1252(self):
        saved = (_cli.MARK_PASS, _cli.MARK_FAIL)
        self.addCleanup(lambda: setattr(_cli, "MARK_PASS", saved[0]))
        self.addCleanup(lambda: setattr(_cli, "MARK_FAIL", saved[1]))
        for _ in range(2):
            stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
            _cli.configure_output(stream)
            self.assertEqual((_cli.MARK_PASS, _cli.MARK_FAIL), ("[ok]", "[x]"))
            stream.detach()
        _cli.configure_output(io.TextIOWrapper(io.BytesIO(), encoding="utf-8"))
        self.assertEqual(_cli.MARK_FAIL, "✗")


if __name__ == "__main__":
    unittest.main()
