"""Delivery reaches the agent (review 2026-11-13, §6 item 3).

- **The host's character cap.** Claude Code shows the model a 2,000-character
  preview of any hook text over 10,000 characters. The SessionStart packet is
  trimmed by meaning to fit, and every hook's text is capped as a backstop.
- **One root resolver.** The CLI walks up from its working directory to the
  nearest store, and the hooks walk up from the payload's `cwd`, then fall
  back to `$CLAUDE_PROJECT_DIR`. Neither crosses into an enclosing repository.
- **Merged branch handoffs.** A branch's handoff merged after `handoff.md` was
  written is shown above the older Next Action, labelled with its branch.

Run with:  python -m unittest discover -s tests -p test_delivery_reach.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import handoffs, hooks_common, packet  # noqa: E402


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(root), check=True, capture_output=True, text=True
    ).stdout


def run(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, out.getvalue()


def hook(event: str, payload: dict, env: dict | None = None) -> dict:
    """Fire `crumb hook <event>` in-process with `payload` on stdin."""
    out = io.StringIO()
    with (
        mock.patch.object(sys, "stdin", io.StringIO(json.dumps(payload))),
        mock.patch.dict(os.environ, env or {}),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(io.StringIO()),
    ):
        code = crumb.main(["hook", event])
    assert code == 0
    return json.loads(out.getvalue())


def repo_with_store(root: Path) -> Path:
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    (root / "f.txt").write_text("a\n")
    git(root, "add", "f.txt")
    git(root, "commit", "-qm", "initial")
    run(["init", "--project", str(root), "--session-tracking", "full"])
    git(root, "add", "-A")
    git(root, "commit", "-qm", "store")
    return root / crumb.MEMORY_DIRNAME


def at(day: int):
    """Patch the clock to 2026-11-<day> 12:00 UTC."""
    when = datetime(2026, 11, day, 12, 0, tzinfo=timezone.utc)
    return mock.patch.object(_cli, "_now", return_value=when)


class Store(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.mem = repo_with_store(self.root)


# --------------------------------------------------------------------------- #
# The host's character cap
# --------------------------------------------------------------------------- #


class HostCharsTests(unittest.TestCase):
    def test_counts_utf16_code_units(self):
        self.assertEqual(hooks_common.host_chars("abc"), 3)
        self.assertEqual(hooks_common.host_chars("é"), 1)
        self.assertEqual(hooks_common.host_chars("🙂"), 2)  # outside the BMP

    def test_fit_context_keeps_short_text(self):
        self.assertEqual(hooks_common.fit_context("short\ntext"), "short\ntext")

    def test_fit_context_cuts_at_a_line_and_says_so(self):
        text = "\n".join(f"line {i} " + "x" * 80 for i in range(400))
        cut = hooks_common.fit_context(text, 2000)
        self.assertLessEqual(hooks_common.host_chars(cut), 2000)
        self.assertTrue(cut.endswith(hooks_common.CONTEXT_TRIMMED_NOTE))
        body = cut[: -len(hooks_common.CONTEXT_TRIMMED_NOTE)].rstrip("\n")
        self.assertTrue(all(ln.startswith("line ") for ln in body.splitlines()))

    def test_fit_context_cuts_one_long_line(self):
        cut = hooks_common.fit_context("🙂" * 5000, 1000)
        self.assertLessEqual(hooks_common.host_chars(cut), 1000)

    def test_the_budget_is_under_the_host_cap(self):
        self.assertLess(hooks_common.CONTEXT_CHAR_BUDGET, hooks_common.HOST_CONTEXT_CHARS)


class SessionStartCapTests(Store):
    """On this repository's own store the packet was 12,317 characters."""

    def _fill(self, n: int = 40) -> None:
        for i in range(n):
            crumb.write_record(
                self.mem,
                self.root,
                "decision",
                f"Decision number {i} about the queue layout",
                {
                    "Decision": f"Route traffic through queue {i}. " + "Detail. " * 30,
                    "Rationale": f"Rationale {i}: " + "measured and agreed " * 14,
                },
                evidence=[{"type": "file", "ref": f"src/queue_{i}.py"}],
            )
        for i in range(12):
            run(
                [
                    "note", "trap", f"Trap {i}: the cache layer forgets writes " + "when " * 40,
                    "--why", "because " * 20, "--project", str(self.root), "--allow-duplicate",
                ]
            )  # fmt: skip
            run(
                [
                    "note", "question", f"Question {i}: should the cache layer " + "keep " * 40 + "?",
                    "--project", str(self.root), "--allow-duplicate",
                ]
            )  # fmt: skip

    def _context(self, **payload) -> str:
        out = hook(
            "session",
            {"cwd": str(self.root), "session_id": "s1", "source": "startup", **payload},
        )
        return out["hookSpecificOutput"]["additionalContext"]

    def test_a_full_store_fits_and_says_what_was_cut(self):
        self._fill()
        unbounded = packet.render_packet_markdown(packet.build_resume_packet(self.mem, self.root))
        self.assertGreater(len(unbounded), hooks_common.HOST_CONTEXT_CHARS, "fixture too small")
        text = self._context()
        self.assertLessEqual(hooks_common.host_chars(text), hooks_common.CONTEXT_CHAR_BUDGET)
        self.assertIn(hooks_common.CONTEXT_LIMIT_REASON.removeprefix("the "), text)
        self.assertTrue(text.rstrip().endswith(hooks_common.CONTEXT_TRIMMED_NOTE))
        # Trimmed by meaning, in TRIM_ORDER: decisions and traps survive.
        self.assertIn("## Active Decisions", text)
        self.assertIn("trap_", text)

    def test_the_budget_line_reports_characters(self):
        self._fill(5)
        p = packet.build_resume_packet(self.mem, self.root, char_limit=9000)
        self.assertEqual(p["budget"]["char_limit"], 9000)
        self.assertLessEqual(p["budget"]["chars"], 9000)
        self.assertTrue(p["budget"]["within"])
        self.assertIn("| chars: ", packet.render_packet_markdown(p))

    def test_without_a_char_limit_nothing_changes(self):
        self._fill(5)
        p = packet.build_resume_packet(self.mem, self.root)
        self.assertNotIn("char_limit", p["budget"])

    def test_a_small_store_is_not_trimmed(self):
        text = self._context()
        self.assertNotIn(hooks_common.CONTEXT_TRIMMED_NOTE, text)

    def test_the_compaction_preamble_counts_against_the_cap(self):
        self._fill()
        with mock.patch.object(
            sys.modules["breadcrumbs.hooks_session"],
            "_compaction_preamble",
            return_value="breadcrumbs: context was compacted.\n" + "p" * 3000 + "\n\n",
        ):
            text = self._context(source="compact")
        self.assertTrue(text.startswith("breadcrumbs: context was compacted."))
        self.assertLessEqual(hooks_common.host_chars(text), hooks_common.CONTEXT_CHAR_BUDGET)


# --------------------------------------------------------------------------- #
# One root resolver
# --------------------------------------------------------------------------- #


class FindStoreRootTests(Store):
    def test_walks_up_from_a_subdirectory(self):
        deep = self.root / "src" / "pkg"
        deep.mkdir(parents=True)
        self.assertEqual(_cli.find_store_root(deep), self.root)
        self.assertEqual(_cli.find_store_root(self.root), self.root)

    def test_stops_at_a_nested_repository(self):
        nested = self.root / "vendor" / "lib"
        nested.mkdir(parents=True)
        git(nested, "init", "-q")
        self.assertIsNone(_cli.find_store_root(nested / "."))
        (nested / "sub").mkdir()
        self.assertIsNone(_cli.find_store_root(nested / "sub"))

    def test_a_missing_subdirectory_still_belongs_to_the_project(self):
        """A payload `cwd` the agent has since deleted is still the project's."""
        self.assertEqual(_cli.find_store_root(self.root / "nope" / "deeper"), self.root)


class ResolveRootTests(Store):
    def test_the_cli_finds_the_store_from_a_subdirectory(self):
        deep = self.root / "src"
        deep.mkdir()
        with mock.patch.object(Path, "cwd", return_value=deep):
            self.assertEqual(_cli.resolve_root(None), self.root)
            code, out = run(["guard", "edit src/app.py", "--json"])
        self.assertIn(code, (0, 10, 15, 20), out)
        self.assertTrue(json.loads(out)["ok"])

    def test_project_is_taken_exactly(self):
        deep = self.root / "src"
        deep.mkdir()
        self.assertEqual(_cli.resolve_root(str(deep)), deep)

    def test_init_from_a_subdirectory_does_not_nest_a_store(self):
        deep = self.root / "src"
        deep.mkdir()
        with mock.patch.object(Path, "cwd", return_value=deep):
            code, _out = run(["init"])
        self.assertNotEqual(code, 0)  # the project already has one
        self.assertFalse((deep / crumb.MEMORY_DIRNAME).exists())


class HookRootTests(Store):
    GUARD = {
        "session_id": "s1",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "git push --force origin main"},
    }

    def _clean_env(self) -> dict:
        return {"CLAUDE_PROJECT_DIR": "", "BREADCRUMBS_PROJECT": ""}

    def test_a_subdirectory_cwd_still_guards(self):
        """It returned {} for every action once the agent had run `cd`."""
        deep = self.root / "config" / "deep"
        deep.mkdir(parents=True)
        out = hook("guard", {**self.GUARD, "cwd": str(deep)}, self._clean_env())
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_falls_back_to_the_session_project(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            env = {**self._clean_env(), "CLAUDE_PROJECT_DIR": str(self.root)}
            out = hook("guard", {**self.GUARD, "cwd": elsewhere}, env)
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "ask")

    def test_no_store_anywhere_is_silent(self):
        with tempfile.TemporaryDirectory() as elsewhere:
            out = hook("guard", {**self.GUARD, "cwd": elsewhere}, self._clean_env())
        self.assertEqual(out, {})

    def test_a_worktree_store_beats_the_session_project(self):
        """Inside a linked worktree, `cwd` is the worktree: its store is the
        branch being worked on, not the main checkout's."""
        with tempfile.TemporaryDirectory() as other:
            other_mem = repo_with_store(Path(other))
            env = {**self._clean_env(), "CLAUDE_PROJECT_DIR": str(self.root)}
            with mock.patch.dict(os.environ, env):
                found = _cli._hook_root({"cwd": other})
            self.assertEqual(found, other_mem.parent.resolve())

    def test_a_non_string_cwd_does_not_crash(self):
        for cwd in (5, ["x"], {"a": 1}, "a\0b"):
            with self.subTest(cwd=cwd):
                root = _cli._hook_root({"cwd": cwd})
                self.assertIsInstance(root, Path)


# --------------------------------------------------------------------------- #
# Merged branch handoffs
# --------------------------------------------------------------------------- #


class MergedHandoffTests(Store):
    def _capture(self, day: int, next_action: str) -> None:
        with at(day):
            code, out = run(
                ["capture", "session", "--project", str(self.root), "--fast", "--next", next_action]
            )
        self.assertEqual(code, 0, out)
        git(self.root, "add", "-A")
        git(self.root, "commit", "-qm", f"capture {day}")

    def _merge_feature(self, branch: str, day: int, next_action: str) -> None:
        git(self.root, "checkout", "-q", "-b", branch)
        self._capture(day, next_action)
        git(self.root, "checkout", "-q", "main")
        git(self.root, "merge", "-q", "--no-ff", "-m", f"merge {branch}", branch)

    def _resume(self) -> tuple[str, dict]:
        with at(20):
            md = packet.render_packet_markdown(packet.build_resume_packet(self.mem, self.root))
            js = packet.build_resume_packet(self.mem, self.root, view="json")
        return md, js

    def test_a_merged_branch_s_newer_next_action_is_shown_first(self):
        self._capture(1, "MAIN: ship release 1.0")
        self._merge_feature("feature/parser", 5, "FEATURE: release 1.1 with the new parser")
        md, js = self._resume()
        self.assertIn("## Newer Next Action From Merged Branches", md)
        self.assertLess(md.index("FEATURE: release 1.1"), md.index("MAIN: ship release 1.0"))
        self.assertIn("**From `feature/parser`**", md)
        (entry,) = js["merged_handoffs"]
        self.assertEqual(entry["branch"], "feature/parser")
        self.assertTrue(entry["path"].startswith("handoffs/feature-parser-"))
        self.assertEqual(js["next_action"], "MAIN: ship release 1.0")

    def test_an_older_branch_handoff_is_not_shown(self):
        self._merge_feature("feature/old", 1, "FEATURE: an old instruction")
        self._capture(5, "MAIN: the newer main-line instruction")
        md, js = self._resume()
        self.assertEqual(js.get("merged_handoffs", []), [])
        self.assertNotIn("Merged Branches", md)

    def test_newest_first_and_capped(self):
        self._capture(1, "MAIN: base")
        for i, day in enumerate((3, 4, 5, 6)):
            self._merge_feature(f"feature/b{i}", day, f"FEATURE {i}")
        md, js = self._resume()
        self.assertEqual(
            [e["next_action"] for e in js["merged_handoffs"]],
            ["FEATURE 3", "FEATURE 2", "FEATURE 1"],
        )
        self.assertEqual(js["omitted"]["merged_handoffs"], 1)
        self.assertIn("1 more omitted", md)

    def test_a_branch_does_not_see_its_own_handoff_as_merged(self):
        self._capture(1, "MAIN: base")
        git(self.root, "checkout", "-q", "-b", "feature/own")
        self._capture(5, "OWN: this branch's instruction")
        md, js = self._resume()
        self.assertEqual(js.get("merged_handoffs", []), [])
        self.assertEqual(js["next_action"], "OWN: this branch's instruction")

    def test_a_trim_history_file_is_not_a_handoff(self):
        self._capture(1, "MAIN: base")
        self._merge_feature("feature/h", 5, "FEATURE: kept")
        (path,) = [
            p for p in (self.mem / "handoffs").glob("feature-h*.md") if ".history" not in p.name
        ]
        history = path.with_name(path.stem + ".history.md")
        history.write_text(path.read_text("utf-8").replace("FEATURE: kept", "HISTORY: old"))
        found = handoffs.newer_merged(self.mem, self.root, self.mem / "handoff.md")
        self.assertEqual([e["next_action"] for e in found], ["FEATURE: kept"])

    def test_a_schema_3_store_has_no_merged_handoffs(self):
        with mock.patch.object(handoffs, "uses_branch_handoffs", return_value=False):
            self.assertEqual(
                handoffs.newer_merged(self.mem, self.root, self.mem / "handoff.md"), []
            )

    def test_a_long_next_action_is_excerpted_with_a_pointer(self):
        self._capture(1, "MAIN: base")
        self._merge_feature("feature/long", 5, "FEATURE " + "word " * 400)
        md, js = self._resume()
        text = js["merged_handoffs"][0]["next_action"]
        self.assertIn("[excerpt:", text)
        self.assertIn("handoffs/feature-long-", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
