"""Tests for `crumb hook session|guard|capture`.

These drive the hook translators by feeding a JSON payload on stdin and asserting
the emitted JSON matches the verified Claude Code contract.

Run with:  python -m pytest tests/
       or:  python tests/test_hooks.py
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402  (patch target: `_hook_guard` resolves `guard` here)
from breadcrumbs import git as _git  # noqa: E402
from breadcrumbs import hooks_stop  # noqa: E402
from breadcrumbs import hooks_guard  # noqa: E402
from breadcrumbs import scoring as _scoring  # noqa: E402


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


def dirty(root: Path) -> list[str]:
    """`git status --porcelain` lines: what a Stop firing left uncommitted."""
    r = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(root), capture_output=True, text=True, check=True
    )
    return [ln for ln in r.stdout.splitlines() if ln.strip()]


def make_repo(tmp: str) -> Path:
    root = Path(tmp)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
    # Git 2.47+ runs its post-commit auto-maintenance detached; a lock file it
    # left in `.git` failed this file's temp-directory cleanup on CI
    # ("Directory not empty: '.git'"). These repositories never need it.
    git(root, "config", "maintenance.auto", "false")
    git(root, "config", "gc.auto", "0")
    (root / "f.txt").write_text("a\n")
    git(root, "add", "f.txt")
    git(root, "commit", "-qm", "init")
    return root


def run_hook(event: str, payload: dict) -> dict:
    """Invoke `crumb hook <event>` in-process with `payload` on stdin; parse stdout."""
    out = io.StringIO()
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(out):
            code = crumb.main(["hook", event])
    finally:
        sys.stdin = saved_stdin
    assert code == 0, code
    text = out.getvalue().strip()
    return json.loads(text) if text else {}


def init_store(root: Path) -> Path:
    crumb.main(["init", "--project", str(root), "--session-tracking", "full"])
    return root / crumb.MEMORY_DIRNAME


class HookSessionTests(unittest.TestCase):
    def test_emits_resume_packet_as_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            out = run_hook("session", {"cwd": str(root), "hook_event_name": "SessionStart"})
            hso = out["hookSpecificOutput"]
            self.assertEqual(hso["hookEventName"], "SessionStart")
            self.assertIn("additionalContext", hso)
            self.assertTrue(hso["additionalContext"].strip())

    def test_no_store_emits_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_hook("session", {"cwd": tmp})
            self.assertEqual(out, {})


class HookGuardTests(unittest.TestCase):
    def test_routine_action_is_silent_allow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "ls -la"},
                },
            )
            self.assertEqual(out, {})

    def test_risky_action_escalates_with_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            crumb.main(["note", "trap", "force-push to main loses history", "--project", str(root)])
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "git push --force origin main"},
                },
            )
            hso = out["hookSpecificOutput"]
            self.assertEqual(hso["hookEventName"], "PreToolUse")
            # memory informs; it never allows or denies on its own, so whichever
            # band this lands in, the reason reaches someone.
            self.assertNotIn(hso.get("permissionDecision"), ("allow", "deny"))
            reason = hso.get("permissionDecisionReason") or hso.get("additionalContext") or ""
            self.assertIn("guard", reason.lower())

    def test_high_impact_deletion_asks_human(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            # a decision touching the schema makes a deletion of it high-impact
            crumb.main(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    "users table schema is canonical",
                    "--set",
                    "Decision",
                    "keep users schema",
                    "--confidence",
                    "low",
                    "--tags",
                    "schema,database",
                ]
            )
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "tool_name": "Bash",
                    "tool_input": {"command": "drop table users schema"},
                },
            )
            # deletion is a high-impact class; with a memory hit this escalates to ask
            if "hookSpecificOutput" in out:
                self.assertNotIn(
                    out["hookSpecificOutput"].get("permissionDecision"), ("allow", "deny")
                )

    def test_verdict_to_permission_decision_mapping(self):
        """All four verdicts map the same way: never `allow`, never `deny`.

        `permissionDecision: "allow"` auto-approves the call and hides the reason
        from the model — the inverse of "memory informs, never decides". PROCEED
        stays silent, READ_FIRST informs via additionalContext with no decision,
        PAUSE/ASK_HUMAN ask.
        """
        expected = {
            "PROCEED": (None, None),
            "READ_FIRST": (None, "additionalContext"),
            "PAUSE": ("ask", "permissionDecisionReason"),
            "ASK_HUMAN": ("ask", "permissionDecisionReason"),
        }
        self.assertEqual(set(expected), set(_scoring._VERDICTS))
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            payload = {
                "cwd": str(root),
                "tool_name": "Bash",
                "tool_input": {"command": "git push --force origin main"},
            }
            real_guard = _scoring.guard
            for verdict, (decision, reason_key) in expected.items():
                with self.subTest(verdict=verdict):

                    def fake_guard(*a, _v=verdict, **kw):
                        result = real_guard(*a, **kw)
                        result["verdict"] = _v
                        return result

                    _scoring.guard = fake_guard
                    try:
                        out = run_hook("guard", payload)
                    finally:
                        _scoring.guard = real_guard
                    if decision is None and reason_key is None:
                        self.assertEqual(out, {})
                        continue
                    hso = out["hookSpecificOutput"]
                    self.assertEqual(hso["hookEventName"], "PreToolUse")
                    self.assertEqual(hso.get("permissionDecision"), decision)
                    self.assertIn(verdict, hso[reason_key])


class HookCaptureTests(unittest.TestCase):
    def test_writes_session_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            out = run_hook("capture", {"cwd": str(root), "stop_reason": "end_turn"})
            self.assertEqual(out, {})
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 1)
            # the written record must validate clean (diff-stat summarized, no bloat)
            self.assertEqual([f for f in crumb.run_validate(mem) if f["status"] == "fail"], [])

    def test_repeat_firings_write_one_record_and_keep_next_action(self):
        """`Stop` fires every turn, not once per session.

        Three consecutive firings against one store must leave exactly one
        session record, and must not overwrite a Next Action a human set.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            crumb.main(
                [
                    "capture",
                    "session",
                    "--project",
                    str(root),
                    "--fast",
                    "--next",
                    "wire the parser into the CLI",
                ]
            )
            before = sorted(p.name for p in (mem / "sessions").glob("*.md"))

            for _ in range(3):
                self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})

            self.assertEqual(sorted(p.name for p in (mem / "sessions").glob("*.md")), before)
            handoff = crumb.split_md_sections((mem / "handoff.md").read_text())
            self.assertEqual(
                crumb.split_next_entries(handoff["Next Action"]), ["wire the parser into the CLI"]
            )

    def test_new_work_since_the_last_record_is_captured(self):
        """The dedupe guard must not swallow a firing after real work."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 1)
            # a second firing with nothing changed adds nothing …
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 1)
            # … but a new commit is new work: the firing becomes the extraction
            # prompt, and the loop-guarded re-firing takes the snapshot.
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "more work")
            out = run_hook("capture", {"cwd": str(root)})
            self.assertEqual(out.get("decision"), "block", out)
            run_hook("capture", {"cwd": str(root), "stop_hook_active": True})

            # F-6: "captured" means the record reflects the work, not that a new
            # file appeared. These firings are all one host session, so they
            # coalesce into one record that keeps moving forward.
            def newest(mem):
                files = sorted((mem / "sessions").glob("*.md"))
                self.assertEqual(len(files), 1, [f.name for f in files])
                return crumb.Record.from_file(files[0], "session").meta

            self.assertEqual(newest(mem)["commit"], _git.short_head(root))
            # an uncommitted edit outside the store is new work too, but not
            # commit-shaped — snapshot only, no prompt.
            (root / "h.txt").write_text("c\n")
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            self.assertIn("h.txt", newest(mem).get("dirty_files") or [])

    def test_stop_hook_active_never_blocks_and_falls_back_to_snapshot(self):
        # A continuation of a blocked Stop must never be blocked again (that is
        # the loop); if the agent ignored the instruction, the machine snapshot
        # is the floor.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            out = run_hook("capture", {"cwd": str(root), "stop_hook_active": True})
            self.assertEqual(out, {})
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 1)

    def test_committing_the_snapshot_is_not_new_work(self):
        """Committing the store must not earn another snapshot (0.6.0).

        The snapshot records HEAD; committing the snapshot moves HEAD; the next
        Stop saw "work moved", rewrote the snapshot with the new sha, and left
        the store dirty again — which the agent committed again, forever.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            sid = {"cwd": str(root), "session_id": "s1"}
            git(root, "add", "-A")
            git(root, "commit", "-qm", "store")
            run_hook("session", {**sid, "hook_event_name": "SessionStart"})
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "work")
            self.assertEqual(run_hook("capture", sid).get("decision"), "block")
            run_hook("capture", {**sid, "stop_hook_active": True})
            self.assertTrue(dirty(root), "the continuation's snapshot dirties the store")
            git(root, "add", "-A")
            git(root, "commit", "-qm", "Project memory: snapshot")
            for _ in range(3):
                self.assertEqual(run_hook("capture", sid), {})
                self.assertEqual(dirty(root), [], "a memory-only commit re-snapshotted")
            self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 1)
            # Real work after the memory commits is still new work.
            (root / "h.txt").write_text("c\n")
            git(root, "add", "h.txt")
            git(root, "commit", "-qm", "more work")
            self.assertEqual(run_hook("capture", sid).get("decision"), "block")

    def test_the_agents_own_capture_is_the_capture(self):
        """The extraction turn ends with `capture session`; the agent commits
        it. The continuation used to stack a machine snapshot beside that
        authored record because the commit moved HEAD."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            sid = {"cwd": str(root), "session_id": "s1"}
            git(root, "add", "-A")
            git(root, "commit", "-qm", "store")
            run_hook("session", {**sid, "hook_event_name": "SessionStart"})
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "work")
            self.assertEqual(run_hook("capture", sid).get("decision"), "block")
            code = crumb.main(
                ["capture", "session", "--project", str(root), "--next", "ship g.txt"]
            )
            self.assertEqual(code, 0)
            git(root, "add", "-A")
            git(root, "commit", "-qm", "Project memory: session capture")
            self.assertEqual(run_hook("capture", {**sid, "stop_hook_active": True}), {})
            self.assertEqual(dirty(root), [])
            files = list((mem / "sessions").glob("*.md"))
            self.assertEqual(len(files), 1, [f.name for f in files])
            self.assertEqual(run_hook("capture", sid), {})
            self.assertEqual(dirty(root), [])

    def test_no_store_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run_hook("capture", {"cwd": tmp})
            self.assertEqual(out, {})


class ExtractionTurnTests(unittest.TestCase):
    """The Stop-hook extraction turn: when the ending turn produced new commits,
    the hook blocks ONCE with an instruction to persist durable memory while the
    agent still holds the session's context. This is the agent-as-author moment;
    everything here pins its lifecycle: proportional trigger, self-clearing via
    `capture session`, the stop_hook_active loop guard, and the manifest kill
    switch.
    """

    def _store_with_baseline(self, tmp: str) -> tuple[Path, Path]:
        root = make_repo(tmp)
        mem = init_store(root)
        # first firing takes the baseline snapshot silently — install day must
        # not interrogate the agent about pre-existing history
        self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
        self.assertEqual(len(list((mem / "sessions").glob("*.md"))), 1)
        return root, mem

    def _commit(self, root: Path, name: str, msg: str) -> None:
        (root / name).write_text("x\n")
        git(root, "add", name)
        git(root, "commit", "-qm", msg)

    def _snapshot(self, mem: Path) -> dict:
        """The single machine snapshot's frontmatter (F-6: firings coalesce)."""
        files = sorted((mem / "sessions").glob("*.md"))
        assert len(files) == 1, [f.name for f in files]
        return crumb.Record.from_file(files[0], "session").meta

    def test_new_commits_block_once_with_a_concrete_instruction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._store_with_baseline(tmp)
            self._commit(root, "g.txt", "wire the reconciler")
            out = run_hook("capture", {"cwd": str(root)})
            self.assertEqual(out.get("decision"), "block", out)
            reason = out.get("reason", "")
            # the instruction names the work and the commands that clear it
            self.assertIn("wire the reconciler", reason)
            self.assertIn("crumb remember", reason)
            self.assertIn("crumb capture session --next", reason)

    def test_capture_clears_the_prompt(self):
        # Completing the instruction IS the reset: after `capture session`,
        # a re-firing Stop sees the fresh record as redundant and stays silent.
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_baseline(tmp)
            self._commit(root, "g.txt", "more work")
            self.assertEqual(run_hook("capture", {"cwd": str(root)}).get("decision"), "block")
            crumb.main(
                ["capture", "session", "--project", str(root), "--fast", "--next", "ship it"]
            )
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            handoff = crumb.split_md_sections((mem / "handoff.md").read_text())
            self.assertEqual(crumb.split_next_entries(handoff["Next Action"])[0], "ship it")

    def test_dirty_files_without_commits_snapshot_silently(self):
        # Proportionality: an edit-only turn never earns an interrogation.
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_baseline(tmp)
            (root / "notes.txt").write_text("scratch\n")
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            # F-6: the snapshot is taken, but into the same session's existing
            # record — one working session must not leave a trail of records.
            self.assertIn("notes.txt", self._snapshot(mem).get("dirty_files") or [])

    def test_manifest_kill_switch_disables_the_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, mem = self._store_with_baseline(tmp)
            manifest = mem / "manifest.yml"
            manifest.write_text(
                manifest.read_text().replace("extraction_prompt: true", "extraction_prompt: false")
            )
            self._commit(root, "g.txt", "more work")
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            # Snapshot taken with no prompt, coalesced into the same record (F-6):
            # it now points at the new HEAD.
            self.assertEqual(self._snapshot(mem)["commit"], _git.short_head(root))

    def test_commit_listing_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = self._store_with_baseline(tmp)
            for i in range(8):
                self._commit(root, f"f{i}.txt", f"commit number {i}")
            reason = run_hook("capture", {"cwd": str(root)}).get("reason", "")
            self.assertIn("8 new commit(s)", reason)
            self.assertIn("… and 3 more", reason)

    def test_non_git_project_never_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_store(root)
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})
            self.assertEqual(run_hook("capture", {"cwd": str(root)}), {})


class HookUsageTests(unittest.TestCase):
    """`crumb hook` with no subcommand read stdin before validating the event.

    From a terminal that blocks until EOF, so the usage error a user is waiting
    for looks like a hang instead.
    """

    def test_missing_subcommand_never_reads_stdin(self):
        def explode():
            raise AssertionError("stdin was read before the event was validated")

        err = io.StringIO()
        with (
            mock.patch.object(_cli, "_read_hook_stdin", side_effect=explode),
            contextlib.redirect_stderr(err),
        ):
            code = crumb.main(["hook"])
        self.assertEqual(code, 2)
        self.assertIn("session|guard|capture", err.getvalue())

    def test_does_not_block_on_a_terminal(self):
        """End to end: a real process with a tty-less pipe that never sends EOF."""
        proc = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "crumb.py"), "hook"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            _, stderr = proc.communicate(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover - the bug being fixed
            proc.kill()
            self.fail("`crumb hook` blocked on stdin instead of reporting usage")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("session|guard|capture", stderr)

    def test_valid_events_still_read_their_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            self.assertIsInstance(run_hook("session", {"cwd": str(root)}), dict)


class PrefilterEvidencePathTests(unittest.TestCase):
    """The hook pre-filter must see the files a do-not-retry attempt names via
    `--evidence file` — the documented way to attach a file. Scraping prose
    alone left `crumb guard "edit src/billing.py"` saying PAUSE while the hook
    on the identical Edit stayed silent (the field-test defect this class pins).
    """

    def _attempt_with_file_evidence(self, root: Path) -> None:
        crumb.main(
            [
                "remember",
                "attempt",
                "--project",
                str(root),
                "--title",
                "Batched the billing reconciler writes",
                "--tried",
                "batched writes",
                "--result",
                "double-charged customers in staging",
                "--do-not-retry",
                "an idempotency key exists",
                "--evidence",
                "file",
                "src/billing.py",
                "--tags",
                "billing",
            ]
        )

    def test_prefilter_index_carries_evidence_file_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            self._attempt_with_file_evidence(root)
            idx = json.loads(_cli.guard_prefilter_path(mem).read_text(encoding="utf-8"))
            self.assertIn("src/billing.py", idx["paths"], idx)

    def test_edit_of_an_evidenced_file_escalates_in_the_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            self._attempt_with_file_evidence(root)
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "src/billing.py"},
                },
            )
            hso = out.get("hookSpecificOutput") or {}
            self.assertTrue(
                hso.get("permissionDecisionReason") or hso.get("additionalContext"),
                f"hook stayed silent on the exact file the attempt evidences: {out}",
            )

    def test_stale_raw_token_prefilter_still_matches_stemmed_actions(self):
        # A prefilter written before the stemmer holds raw tokens; the reader
        # re-stems them, so an inflected action still trips the index.
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            pre = _cli.guard_prefilter_path(mem)
            pre.write_text(
                json.dumps({"tokens": ["reconciler", "batched"], "paths": []}),
                encoding="utf-8",
            )
            self.assertTrue(
                hooks_guard._prefilter_trap_hit(mem, "batching the reconciliation writes", None)
            )


class HookEditContentTests(unittest.TestCase):
    """P0-3 (0.1.10 field test): the guard action for a file edit carries a
    bounded snippet of the new content, so different edits of one file stop
    producing byte-identical guard input and content-shaped traps can match."""

    def test_edit_action_carries_bounded_snippet(self):
        long_new = "val req = PeriodicWorkRequest(flexTimeInterval = 5)\n" * 50
        action, files = hooks_guard._hook_action_from_tool(
            "Edit", {"file_path": "a/b.kt", "new_string": long_new}
        )
        self.assertTrue(action.startswith("edit a/b.kt: val req = PeriodicWorkRequest"))
        self.assertLessEqual(
            len(action), len("edit a/b.kt: ") + hooks_guard._HOOK_CONTENT_SNIPPET_CHARS
        )
        self.assertEqual(files, ["a/b.kt"])

    def test_edit_without_content_keeps_the_old_shape(self):
        action, files = hooks_guard._hook_action_from_tool("Edit", {"file_path": "a/b.kt"})
        self.assertEqual(action, "edit a/b.kt")
        self.assertEqual(files, ["a/b.kt"])

    def test_multiedit_and_write_content_is_seen(self):
        action, _ = hooks_guard._hook_action_from_tool(
            "MultiEdit",
            {"file_path": "x.py", "edits": [{"new_string": "alpha"}, {"new_string": "beta"}]},
        )
        self.assertIn("alpha", action)
        self.assertIn("beta", action)
        action, _ = hooks_guard._hook_action_from_tool(
            "Write", {"file_path": "x.py", "content": "gamma delta"}
        )
        self.assertIn("gamma delta", action)


class HookAdvisoryDedupeTests(unittest.TestCase):
    """P0-2b (0.1.10 field test): the same records surfacing for the same file
    is information exactly once per host session. Advisories only — PAUSE and
    ASK_HUMAN always fire."""

    def _store_with_file_trap(self, tmp: str) -> Path:
        root = make_repo(tmp)
        init_store(root)
        kt = root / crumb.MEMORY_DIRNAME / "known-traps.md"
        kt.write_text(
            kt.read_text(encoding="utf-8")
            + "\n## trap_accrual-shim: accrual shim must wrap ledger mutations\n"
            "- Area / files: src/billing.py\n",
            encoding="utf-8",
        )
        # Rebuild the guard prefilter so the hook's cheap path sees the trap.
        crumb.main(["reindex", "--project", str(root)])
        return root

    def _edit_payload(self, root: Path, session_id: str) -> dict:
        return {
            "cwd": str(root),
            "session_id": session_id,
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/billing.py"},
        }

    def test_read_first_fires_once_per_session_per_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._store_with_file_trap(tmp)
            first = run_hook("guard", self._edit_payload(root, "s1"))
            hso = first.get("hookSpecificOutput") or {}
            self.assertTrue(hso.get("additionalContext"), first)
            second = run_hook("guard", self._edit_payload(root, "s1"))
            self.assertEqual(second, {}, "identical advisory must not repeat in-session")

    def test_a_new_session_hears_the_advisory_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._store_with_file_trap(tmp)
            run_hook("guard", self._edit_payload(root, "s1"))
            other = run_hook("guard", self._edit_payload(root, "s2"))
            hso = other.get("hookSpecificOutput") or {}
            self.assertTrue(hso.get("additionalContext"), other)

    def test_pause_is_never_deduplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            crumb.main(
                [
                    "remember",
                    "attempt",
                    "--project",
                    str(root),
                    "--title",
                    "Batched the billing reconciler writes",
                    "--tried",
                    "batched writes",
                    "--result",
                    "double-charged customers in staging",
                    "--do-not-retry",
                    "an idempotency key exists",
                    "--evidence",
                    "file",
                    "src/billing.py",
                ]
            )
            payload = {
                "cwd": str(root),
                "session_id": "s1",
                "tool_name": "Edit",
                "tool_input": {"file_path": "src/billing.py"},
            }
            for attempt in range(2):
                out = run_hook("guard", payload)
                hso = out.get("hookSpecificOutput") or {}
                self.assertEqual(hso.get("permissionDecision"), "ask", (attempt, out))

    def test_dedupe_state_lives_in_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._store_with_file_trap(tmp)
            run_hook("guard", self._edit_payload(root, "s1"))
            state = root / crumb.MEMORY_DIRNAME / "private" / hooks_guard._HOOK_SEEN_FILENAME
            self.assertTrue(state.is_file(), "advisory state must be machine-local")


# --------------------------------------------------------------------------- #
# F-6 (0.1.11 field audit) — one machine snapshot per session, not per Stop
# --------------------------------------------------------------------------- #
class SnapshotCoalescingTests(unittest.TestCase):
    """Claude Code's `Stop` fires at every turn boundary, not once per session.

    The field audit's store took snapshots at 2:39, 2:58 and 3:16 for a session
    that began at 2:47 — one working session, three session records — and
    `audit` then flagged the resulting 101 records as bloat. The tool was
    generating its own bloat warning, and the older snapshots carried
    `dirty_files` lists that were stale by the time the next one was written.

    A machine snapshot is a disposable "where things stand" marker, so a later
    firing of the same session replaces it rather than stacking beside it.
    Records a human or agent authored are never touched.
    """

    def _sessions(self, mem: Path) -> list[Path]:
        return sorted((mem / "sessions").glob("*.md"))

    def _meta(self, path: Path) -> dict:
        return crumb.Record.from_file(path, "session").meta

    def test_one_session_of_repeated_firings_leaves_one_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            sid = {"cwd": str(root), "session_id": "sess-abc"}
            run_hook("capture", sid)
            first = self._sessions(mem)
            self.assertEqual(len(first), 1)

            # Three more turns that each move the work — the audit's shape.
            for n in range(3):
                (root / f"w{n}.txt").write_text("x\n")
                run_hook("capture", {**sid, "stop_hook_active": True})

            self.assertEqual([p.name for p in self._sessions(mem)], [first[0].name])
            meta = self._meta(first[0])
            self.assertIn("w2.txt", meta.get("dirty_files") or [])
            self.assertEqual(meta.get("host_session"), "sess-abc")

    def test_coalescing_keeps_the_first_firings_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            sid = {"cwd": str(root), "session_id": "sess-abc"}
            run_hook("capture", sid)
            before = self._meta(self._sessions(mem)[0])

            (root / "later.txt").write_text("x\n")
            run_hook("capture", {**sid, "stop_hook_active": True})
            after = self._meta(self._sessions(mem)[0])

            # created_at names when the session's first snapshot was taken —
            # that is the fact worth keeping — while updated_at moves.
            self.assertEqual(after["id"], before["id"])
            self.assertEqual(after["created_at"], before["created_at"])
            self.assertIn("later.txt", after.get("dirty_files") or [])

    def test_a_different_host_session_starts_its_own_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            run_hook("capture", {"cwd": str(root), "session_id": "sess-one"})
            (root / "w.txt").write_text("x\n")
            run_hook("capture", {"cwd": str(root), "session_id": "sess-two"})
            self.assertEqual(len(self._sessions(mem)), 2)
            self.assertEqual(
                sorted(self._meta(p).get("host_session") for p in self._sessions(mem)),
                ["sess-one", "sess-two"],
            )

    def test_an_authored_capture_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            run_hook("capture", {"cwd": str(root), "session_id": "sess-abc"})

            # A real capture with a real Next Action is authored content.
            code = crumb.main(
                [
                    "capture",
                    "session",
                    "--project",
                    str(root),
                    "--fast",
                    "--next",
                    "ship the reconciler fix",
                ]
            )
            self.assertEqual(code, 0)
            self.assertEqual(len(self._sessions(mem)), 2)

            authored = next(
                f
                for f in self._sessions(mem)
                if "ship the reconciler fix" in f.read_text(encoding="utf-8")
            )
            frozen = authored.read_text(encoding="utf-8")

            # A later Stop firing must not rewrite that authored record: the
            # newest record is no longer a machine snapshot, so the firing
            # starts a fresh one instead of coalescing.
            (root / "w.txt").write_text("x\n")
            run_hook("capture", {"cwd": str(root), "session_id": "sess-abc"})
            self.assertEqual(authored.read_text(encoding="utf-8"), frozen)
            self.assertIn("ship the reconciler fix", frozen)
            self.assertEqual(len(self._sessions(mem)), 3)

    def test_a_snapshot_outside_the_window_is_not_coalesced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            # No session id in the payload -> the branch + time-window fallback.
            run_hook("capture", {"cwd": str(root)})
            old = self._sessions(mem)[0]
            text = old.read_text(encoding="utf-8")
            stale = (
                (
                    datetime.now().astimezone()
                    - timedelta(minutes=crumb.COALESCE_WINDOW_MINUTES + 30)
                )
                .replace(microsecond=0)
                .isoformat()
            )
            old.write_text(
                re.sub(r"^updated_at: .*$", f"updated_at: {stale}", text, flags=re.M),
                encoding="utf-8",
            )

            (root / "w.txt").write_text("x\n")
            run_hook("capture", {"cwd": str(root)})
            self.assertEqual(len(self._sessions(mem)), 2, "a cold snapshot is a separate session")

    def test_the_store_stops_growing_two_records_a_day(self):
        # The bloat arithmetic from the audit: 101 records over ~50 days is
        # "one or more per stop", not "one per session".
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            sid = {"cwd": str(root), "session_id": "sess-long"}
            for n in range(12):
                (root / f"turn{n}.txt").write_text("x\n")
                run_hook("capture", {**sid, "stop_hook_active": True})
            self.assertEqual(len(self._sessions(mem)), 1, self._sessions(mem))


if __name__ == "__main__":
    unittest.main()


class HookGuardPermissionModeTests(unittest.TestCase):
    """The hook must never reinstate a prompt the user opted out of.

    `crumb hook guard` used to emit `permissionDecision: "ask"` on every
    PAUSE/ASK_HUMAN regardless of the session's permission mode, so a session
    run under `bypassPermissions` got approval prompts back — a decision the
    tool has no standing to make. The warning is still delivered; only the
    interruption is withheld.
    """

    def _blocking_store(self, tmp: str) -> Path:
        root = make_repo(tmp)
        init_store(root)
        crumb.main(
            [
                "remember",
                "attempt",
                "--project",
                str(root),
                "--title",
                "Batched the billing reconciler writes",
                "--problem",
                "slow reconciliation",
                "--tried",
                "batching",
                "--result",
                "double-charged customers in staging",
                "--do-not-retry",
                "an idempotency key exists",
                "--evidence",
                "file",
                "src/billing.py",
            ]
        )
        return root

    def _payload(self, root: Path, mode: str | None, session_id: str = "s1") -> dict:
        p = {
            "cwd": str(root),
            "session_id": session_id,
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/billing.py"},
        }
        if mode is not None:
            p["permission_mode"] = mode
        return p

    def test_default_mode_still_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._blocking_store(tmp)
            hso = run_hook("guard", self._payload(root, "default")).get("hookSpecificOutput") or {}
            self.assertEqual(hso.get("permissionDecision"), "ask")

    def test_missing_permission_mode_still_prompts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._blocking_store(tmp)
            hso = run_hook("guard", self._payload(root, None)).get("hookSpecificOutput") or {}
            self.assertEqual(hso.get("permissionDecision"), "ask")

    def test_non_prompting_modes_downgrade_to_context(self):
        for mode in ("bypassPermissions", "dontAsk"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                root = self._blocking_store(tmp)
                out = run_hook("guard", self._payload(root, mode))
                hso = out.get("hookSpecificOutput") or {}
                self.assertIsNone(hso.get("permissionDecision"), out)
                self.assertIsNone(hso.get("permissionDecisionReason"), out)
                # The warning itself must survive — this is a downgrade, not a drop.
                self.assertIn("guard", hso.get("additionalContext", ""), out)

    def test_accept_edits_still_prompts(self):
        # acceptEdits auto-accepts edits only; it is not a blanket "never ask".
        with tempfile.TemporaryDirectory() as tmp:
            root = self._blocking_store(tmp)
            hso = (
                run_hook("guard", self._payload(root, "acceptEdits")).get("hookSpecificOutput")
                or {}
            )
            self.assertEqual(hso.get("permissionDecision"), "ask")

    def test_advisory_env_var_downgrades_in_any_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self._blocking_store(tmp)
            with mock.patch.dict("os.environ", {"CRUMB_GUARD_ADVISORY": "1"}):
                out = run_hook("guard", self._payload(root, "default"))
            hso = out.get("hookSpecificOutput") or {}
            self.assertIsNone(hso.get("permissionDecision"), out)
            self.assertIn("guard", hso.get("additionalContext", ""), out)


class SessionCursorTests(unittest.TestCase):
    """Field report 2026-10-01, issues 2-3: the Stop hook asked about commits
    other sessions made (counted from the newest session record in the store),
    and could ask again every turn when its fallback snapshot did not land."""

    def _commit(self, root: Path, name: str, msg: str, path: str | None = None) -> None:
        target = root / (path or name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"{msg}\n")
        git(root, "add", str(target.relative_to(root)))
        git(root, "commit", "-qm", msg)

    def _start(self, root: Path, sid: str) -> None:
        run_hook("session", {"cwd": str(root), "session_id": sid})

    def test_other_sessions_commits_are_not_this_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            crumb.main(["capture", "session", "--project", str(root), "--fast", "--next", "x"])
            for i in range(7):
                self._commit(root, f"o{i}.txt", f"other session work {i}")
            self._start(root, "NEW")
            self.assertEqual(run_hook("capture", {"cwd": str(root), "session_id": "NEW"}), {})

    def test_this_sessions_commit_is_asked_about_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            self._start(root, "S")
            self._commit(root, "mine.txt", "my own work")
            out = run_hook("capture", {"cwd": str(root), "session_id": "S"})
            self.assertEqual(out.get("decision"), "block", out)
            self.assertIn("my own work", out["reason"])
            self.assertIn("1 new commit(s)", out["reason"])

    def test_a_memory_only_commit_is_not_new_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            self._start(root, "S")
            self._commit(root, "x", "chore: commit memory", path=".project-memory/decisions/x.md")
            self.assertEqual(run_hook("capture", {"cwd": str(root), "session_id": "S"}), {})

    def test_a_backward_checkout_is_not_a_new_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            self._commit(root, "a.txt", "a")
            self._start(root, "S")
            git(root, "checkout", "-q", "HEAD~1")
            self.assertEqual(run_hook("capture", {"cwd": str(root), "session_id": "S"}), {})

    def test_a_failed_snapshot_never_re_asks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            self._start(root, "S")
            self._commit(root, "w.txt", "work")
            payload = {"cwd": str(root), "session_id": "S"}
            with unittest.mock.patch.object(_cli, "cmd_capture_session", side_effect=OSError("x")):
                self.assertEqual(run_hook("capture", payload).get("decision"), "block")
                self.assertEqual(run_hook("capture", {**payload, "stop_hook_active": True}), {})
                self.assertEqual(run_hook("capture", payload), {})
            with unittest.mock.patch.object(_cli, "cmd_capture_session", return_value=2):
                self.assertEqual(run_hook("capture", payload), {})

    def test_a_failed_snapshot_is_logged_as_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            (root / "dirty.txt").write_text("x\n")
            with unittest.mock.patch.object(
                _cli, "cmd_capture_session", side_effect=OSError("disk full")
            ):
                run_hook("capture", {"cwd": str(root), "session_id": "S"})
            log = (mem / "private" / "hook-log.jsonl").read_text().splitlines()
            last = json.loads(log[-1])
            self.assertEqual(last.get("snapshot"), "failed")
            self.assertIn("disk full", last.get("snapshot_error", ""))

    def test_a_future_dated_record_does_not_cause_a_nag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            crumb.main(["capture", "session", "--project", str(root), "--fast", "--next", "x"])
            rec = next((mem / "sessions").glob("*.md"))
            rec.write_text(rec.read_text().replace("created_at: 2026", "created_at: 2027", 1))
            self._start(root, "S")
            self._commit(root, "w.txt", "work")
            payload = {"cwd": str(root), "session_id": "S"}
            self.assertEqual(run_hook("capture", payload).get("decision"), "block")
            run_hook("capture", {**payload, "stop_hook_active": True})
            self.assertEqual(run_hook("capture", payload), {})
            self.assertEqual(run_hook("capture", payload), {})

    def test_many_dirty_files_are_redundant_on_the_second_firing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            for i in range(40):
                (root / f"d{i}.txt").write_text("x\n")
            run_hook("capture", {"cwd": str(root), "session_id": "S"})
            self.assertTrue(hooks_stop._hook_capture_is_redundant(mem, root))

    def test_session_start_records_the_head_once(self):
        from breadcrumbs import hooks_common

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            self._start(root, "S")
            first = hooks_common.session_baseline(mem, "S")["head"]
            self._commit(root, "w.txt", "work")
            self._start(root, "S")  # a resumed session keeps its start
            self.assertEqual(hooks_common.session_baseline(mem, "S")["head"], first)

    def _clone_pair(self, tmp: str) -> tuple[Path, Path]:
        """A local checkout with a store and a 'cloud' clone of the same origin."""
        base = Path(tmp)
        git(base, "init", "-q", "--bare", "-b", "main", "origin.git")
        local = base / "local"
        git(base, "clone", "-q", "origin.git", str(local))
        for repo in (local,):
            git(repo, "config", "user.email", "l@l")
            git(repo, "config", "user.name", "local")
        self._commit(local, "a.txt", "initial")
        init_store(local)
        git(local, "add", "-A")
        git(local, "commit", "-qm", "store")
        git(local, "push", "-q", "origin", "main")
        cloud = base / "cloud"
        git(base, "clone", "-q", "origin.git", str(cloud))
        git(cloud, "config", "user.email", "c@c")
        git(cloud, "config", "user.name", "cloud")
        return local, cloud

    def test_a_pulled_commit_made_during_the_session_is_not_this_sessions(self):
        # DoWhat retest of 0.5.0, F1: a cloud session commits while the local
        # session runs; the local `git pull` brings it in after the session's
        # start, so the author-time filter alone counted it as this session's.
        with tempfile.TemporaryDirectory() as tmp:
            local, cloud = self._clone_pair(tmp)
            self._start(local, "S")
            self._commit(cloud, "cloud.txt", "cloud session work")
            git(cloud, "push", "-q", "origin", "main")
            git(local, "pull", "-q", "--ff-only", "origin", "main")
            payload = {"cwd": str(local), "session_id": "S"}
            self.assertEqual(run_hook("capture", payload), {})
            # This session's own commit is still asked about, once.
            self._commit(local, "mine.txt", "my own work")
            out = run_hook("capture", payload)
            self.assertEqual(out.get("decision"), "block", out)
            self.assertIn("my own work", out["reason"])
            self.assertNotIn("cloud session work", out["reason"])
            self.assertIn("1 new commit(s)", out["reason"])
            run_hook("capture", {**payload, "stop_hook_active": True})
            self.assertEqual(run_hook("capture", payload), {})

    def test_a_merged_pull_and_a_rebased_pull_count_only_local_commits(self):
        with tempfile.TemporaryDirectory() as tmp:
            local, cloud = self._clone_pair(tmp)
            self._start(local, "S")
            self._commit(local, "mine.txt", "my own work")
            self._commit(cloud, "cloud.txt", "cloud session work")
            git(cloud, "push", "-q", "origin", "main")
            git(local, "pull", "-q", "--rebase", "origin", "main")
            out = run_hook("capture", {"cwd": str(local), "session_id": "S"})
            self.assertEqual(out.get("decision"), "block", out)
            self.assertIn("my own work", out["reason"])
            self.assertNotIn("cloud session work", out["reason"])

    def test_short_shas_of_different_lengths_are_the_same_commit(self):
        self.assertTrue(_git.same_commit("abc1234", "abc1234de"))
        self.assertFalse(_git.same_commit("abc1234", "abc1235"))
        self.assertFalse(_git.same_commit("abc", "abcdef0"))


class StopLifecycleTests(unittest.TestCase):
    """The Stop hook's lifecycle gaps closed in 0.6.0."""

    @staticmethod
    def _sessions(mem: Path) -> list[Path]:
        return sorted((mem / "sessions").glob("*.md"))

    @staticmethod
    def _commit_at(root: Path, msg: str, when: int, *, amend: bool = False) -> None:
        env = {
            **__import__("os").environ,
            "GIT_AUTHOR_DATE": f"@{when} +0000",
            "GIT_COMMITTER_DATE": f"@{when} +0000",
        }
        args = (
            ["git", "commit", "-q", "--amend", "--no-edit"]
            if amend
            else ["git", "commit", "-qm", msg]
        )
        subprocess.run(args, cwd=str(root), check=True, capture_output=True, env=env)

    def _started(self, root: Path, sid: dict) -> Path:
        mem = init_store(root)
        git(root, "add", "-A")
        git(root, "commit", "-qm", "store")
        run_hook("session", {**sid, "hook_event_name": "SessionStart"})
        return mem

    def test_a_redundant_firing_runs_no_commit_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            sid = {"cwd": str(root), "session_id": "s1"}
            run_hook("capture", sid)  # first firing: the snapshot
            with mock.patch.object(hooks_stop, "_session_commits", side_effect=AssertionError):
                self.assertEqual(run_hook("capture", sid), {})
            # No SessionStart ran, so the redundant firing gave the session a start.
            from breadcrumbs import hooks_common

            self.assertTrue(hooks_common.session_baseline(mem, "s1").get("head"))

    def test_an_id_less_payload_is_keyed_by_its_transcript(self):
        from breadcrumbs import hooks_common

        a = hooks_common.session_id_of({"transcript_path": "/t/a.jsonl"})
        b = hooks_common.session_id_of({"transcript_path": "/t/b.jsonl"})
        self.assertNotEqual(a, b)
        self.assertEqual(a, hooks_common.session_id_of({"transcript_path": "/t/a.jsonl"}))
        self.assertEqual(hooks_common.session_id_of({}), hooks_common.UNKNOWN_SESSION)
        self.assertEqual(hooks_common.session_id_of({"session_id": "x"}), "x")

    def test_each_start_of_the_shared_bucket_is_a_new_session(self):
        from breadcrumbs import hooks_common

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            key = hooks_common.UNKNOWN_SESSION
            run_hook("session", {"cwd": str(root), "hook_event_name": "SessionStart"})
            first = hooks_common.session_baseline(mem, key)
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "between sessions")
            run_hook("session", {"cwd": str(root), "hook_event_name": "SessionStart"})
            second = hooks_common.session_baseline(mem, key)
            self.assertNotEqual(first["head"], second["head"])
            self.assertEqual(second["head"], _git.head(root))

    def test_an_amend_of_an_asked_commit_is_not_asked_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            sid = {"cwd": str(root), "session_id": "s1"}
            self._started(root, sid)
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "work")
            self.assertEqual(run_hook("capture", sid).get("decision"), "block")
            run_hook("capture", {**sid, "stop_hook_active": True})
            (root / "g.txt").write_text("b2\n")
            git(root, "add", "g.txt")
            self._commit_at(root, "", int(__import__("time").time()) - 3600, amend=True)
            self.assertNotEqual(run_hook("capture", sid).get("decision"), "block")

    def test_work_rewritten_after_the_ask_is_still_asked_about(self):
        """Before 0.6.0 any rewrite re-baselined silently and the work was lost."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            sid = {"cwd": str(root), "session_id": "s1"}
            self._started(root, sid)
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "work")
            self.assertEqual(run_hook("capture", sid).get("decision"), "block")
            run_hook("capture", {**sid, "stop_hook_active": True})
            later = int(__import__("time").time()) + 120
            (root / "h.txt").write_text("c\n")
            git(root, "add", "h.txt")
            self._commit_at(root, "new work", later)
            # Rewritten before the next Stop: the baseline is no ancestor now.
            git(root, "reset", "-q", "--soft", "HEAD~2")
            self._commit_at(root, "squashed", later + 1)
            out = run_hook("capture", sid)
            self.assertEqual(out.get("decision"), "block", out)
            self.assertIn("squashed", out["reason"])

    def test_a_code_and_memory_commit_answering_the_ask_is_the_answer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            sid = {"cwd": str(root), "session_id": "s1"}
            mem = self._started(root, sid)
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "work")
            self.assertEqual(run_hook("capture", sid).get("decision"), "block")
            # The agent commits the code it had not committed yet together with
            # its capture, in the extraction turn.
            (root / "h.txt").write_text("c\n")
            crumb.main(["capture", "session", "--project", str(root), "--next", "ship h.txt"])
            git(root, "add", "-A")
            git(root, "commit", "-qm", "finish h.txt and record the session")
            self.assertEqual(run_hook("capture", {**sid, "stop_hook_active": True}), {})
            self.assertEqual(dirty(root), [], "no machine snapshot beside the agent's capture")
            self.assertEqual(len(self._sessions(mem)), 1)
            self.assertEqual(run_hook("capture", sid), {}, "not asked about again")
            self.assertEqual(dirty(root), [])

    def test_a_subagent_finding_alone_does_not_earn_the_ask(self):
        from breadcrumbs import inbox

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            sid = {"cwd": str(root), "session_id": "s1"}
            kw = {"local": True, "source": "transcript", "host_session": "s1"}
            inbox.write_jot(
                mem, root, "pytest -x failed, then passed", tags=["attempt", "subagent"], **kw
            )
            self.assertEqual(run_hook("capture", sid), {})
            # The session's own failed-then-fixed command still earns it.
            inbox.write_jot(mem, root, "make build failed, then passed", tags=["attempt"], **kw)
            (root / "g.txt").write_text("b\n")  # new work, so the firing is not redundant
            out = run_hook("capture", sid)
            self.assertEqual(out.get("decision"), "block", out)

    def test_parallel_sessions_each_keep_one_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            for n in range(3):
                for s in ("s1", "s2"):
                    (root / f"{s}-{n}.txt").write_text("x\n")
                    run_hook("capture", {"cwd": str(root), "session_id": s})
            self.assertEqual(len(self._sessions(mem)), 2, self._sessions(mem))
            # Nothing moved: whichever session fires, the tree is described.
            self.assertEqual(run_hook("capture", {"cwd": str(root), "session_id": "s1"}), {})
            before = [p.read_bytes() for p in self._sessions(mem)]
            run_hook("capture", {"cwd": str(root), "session_id": "s2"})
            self.assertEqual([p.read_bytes() for p in self._sessions(mem)], before)

    def test_session_start_prunes_old_expired_private_jots(self):
        from breadcrumbs import inbox

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            old = "2026-01-01T00:00:00+00:00"
            private = inbox.write_jot(mem, root, "old local note", local=True)
            committed = inbox.write_jot(mem, root, "old shared note")
            for made in (private, committed):
                path = Path(made["path"])
                text = path.read_text(encoding="utf-8")
                text = re.sub(r"(?m)^created_at: .*$", f"created_at: {old}", text)
                text = re.sub(
                    r"(?m)^expires_at: .*$", "expires_at: 2026-01-15T00:00:00+00:00", text
                )
                path.write_text(text, encoding="utf-8")
            run_hook(
                "session", {"cwd": str(root), "session_id": "s1", "hook_event_name": "SessionStart"}
            )
            self.assertFalse(Path(private["path"]).exists(), "expired private jot pruned")
            self.assertTrue(Path(committed["path"]).exists(), "a committed jot is never touched")

    def test_the_commit_cursor_outlives_eight_newer_sessions(self):
        from breadcrumbs import hooks_common

        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            hooks_common.set_session_baseline(mem, "long", "a" * 40)
            for n in range(20):
                hooks_common.set_session_baseline(mem, f"other{n}", "b" * 40)
            self.assertEqual(hooks_common.session_baseline(mem, "long").get("head"), "a" * 40)


class StopReviewFindingsTests(unittest.TestCase):
    """Defects the 0.6.0 review found in the first cut of the Stop fixes."""

    @staticmethod
    def _sessions(mem: Path) -> list[Path]:
        return sorted((mem / "sessions").glob("*.md"))

    def test_a_coalesced_snapshot_keeps_the_work_it_summarized(self):
        """Coalescing into this session's own snapshot while another session's
        is newer used the newer one as the diff base and erased earlier work."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            stamps = iter(
                [
                    "2026-10-02T10:00:00+00:00",
                    "2026-10-02T10:05:00+00:00",
                    "2026-10-02T10:10:00+00:00",
                ]
            )

            def commit(name: str) -> None:
                (root / name).write_text(name)
                git(root, "add", name)
                git(root, "commit", "-qm", name)

            def snapshot(sid: str) -> None:
                with mock.patch.object(_cli, "now_iso", return_value=next(stamps)):
                    self.assertEqual(hooks_stop._hook_capture_snapshot(root, sid), "ok")

            commit("a0")
            snapshot("A")
            commit("a1")
            snapshot("B")
            commit("a2")
            snapshot("A")
            own = next(
                crumb.Record.from_file(p, "session")
                for p in self._sessions(mem)
                if crumb.Record.from_file(p, "session").meta.get("host_session") == "A"
            )
            work = own.sections.get("Work Completed", "")
            for subject in ("a1", "a2"):
                self.assertIn(subject, work)

    def test_an_old_ask_does_not_cover_a_later_continuation(self):
        """`stop_hook_active` is true after any Stop hook blocked; an old ask
        plus an old capture used to cover every later continuation's commits."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            git(root, "add", "-A")
            git(root, "commit", "-qm", "store")
            sid = {"cwd": str(root), "session_id": "s1"}
            run_hook("session", {**sid, "hook_event_name": "SessionStart"})
            (root / "g.txt").write_text("b\n")
            git(root, "add", "g.txt")
            git(root, "commit", "-qm", "first work")
            self.assertEqual(run_hook("capture", sid).get("decision"), "block")
            crumb.main(["capture", "session", "--project", str(root), "--next", "ship g.txt"])
            git(root, "add", "-A")
            git(root, "commit", "-qm", "memory")
            self.assertEqual(run_hook("capture", {**sid, "stop_hook_active": True}), {})
            (root / "h.txt").write_text("c\n")
            git(root, "add", "h.txt")
            git(root, "commit", "-qm", "second work")
            # Another hook blocks this Stop; ours must not read the old capture
            # as an answer covering "second work".
            run_hook("capture", {**sid, "stop_hook_active": True})
            (root / "i.txt").write_text("d\n")  # the next turn's work moves the tree
            out = run_hook("capture", sid)
            self.assertEqual(out.get("decision"), "block", out)
            self.assertIn("second work", out["reason"])
