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
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402  (patch target: `_hook_guard` resolves `guard` here)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True, text=True)


def make_repo(tmp: str) -> Path:
    root = Path(tmp)
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@t")
    git(root, "config", "user.name", "t")
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
        self.assertEqual(set(expected), set(_cli._VERDICTS))
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            init_store(root)
            payload = {
                "cwd": str(root),
                "tool_name": "Bash",
                "tool_input": {"command": "git push --force origin main"},
            }
            real_guard = _cli.guard
            for verdict, (decision, reason_key) in expected.items():
                with self.subTest(verdict=verdict):

                    def fake_guard(*a, _v=verdict, **kw):
                        result = real_guard(*a, **kw)
                        result["verdict"] = _v
                        return result

                    _cli.guard = fake_guard
                    try:
                        out = run_hook("guard", payload)
                    finally:
                        _cli.guard = real_guard
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
            self.assertEqual(handoff["Next Action"].strip(), "wire the parser into the CLI")

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

            self.assertEqual(newest(mem)["commit"], crumb.git_commit(root))
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
            self.assertEqual(handoff["Next Action"].strip(), "ship it")

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
            self.assertEqual(self._snapshot(mem)["commit"], crumb.git_commit(root))

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
            idx = json.loads(
                (mem / "generated" / _cli.GUARD_PREFILTER_FILENAME).read_text(encoding="utf-8")
            )
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
            pre = mem / "generated" / _cli.GUARD_PREFILTER_FILENAME
            pre.write_text(
                json.dumps({"tokens": ["reconciler", "batched"], "paths": []}),
                encoding="utf-8",
            )
            self.assertTrue(
                _cli._prefilter_trap_hit(mem, "batching the reconciliation writes", None)
            )


class HookEditContentTests(unittest.TestCase):
    """P0-3 (0.1.10 field test): the guard action for a file edit carries a
    bounded snippet of the new content, so different edits of one file stop
    producing byte-identical guard input and content-shaped traps can match."""

    def test_edit_action_carries_bounded_snippet(self):
        long_new = "val req = PeriodicWorkRequest(flexTimeInterval = 5)\n" * 50
        action, files = _cli._hook_action_from_tool(
            "Edit", {"file_path": "a/b.kt", "new_string": long_new}
        )
        self.assertTrue(action.startswith("edit a/b.kt: val req = PeriodicWorkRequest"))
        self.assertLessEqual(len(action), len("edit a/b.kt: ") + _cli._HOOK_CONTENT_SNIPPET_CHARS)
        self.assertEqual(files, ["a/b.kt"])

    def test_edit_without_content_keeps_the_old_shape(self):
        action, files = _cli._hook_action_from_tool("Edit", {"file_path": "a/b.kt"})
        self.assertEqual(action, "edit a/b.kt")
        self.assertEqual(files, ["a/b.kt"])

    def test_multiedit_and_write_content_is_seen(self):
        action, _ = _cli._hook_action_from_tool(
            "MultiEdit",
            {"file_path": "x.py", "edits": [{"new_string": "alpha"}, {"new_string": "beta"}]},
        )
        self.assertIn("alpha", action)
        self.assertIn("beta", action)
        action, _ = _cli._hook_action_from_tool(
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
            state = root / crumb.MEMORY_DIRNAME / "private" / _cli._HOOK_SEEN_FILENAME
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
