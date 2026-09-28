"""Latest intent and emission accounting (audit WP12: F15, F16).

- **F15.** The prompt hook saved the task only when memory matched it, so a
  later task that matched nothing left the older one in place, and compaction
  restored the older task.
- **F16.** Usage counted records that were never delivered: the guard hook
  counted before its dedupe exit, and the prompt hook counted every selected id
  before budget trimming dropped some. Counts were a read-modify-write of one
  shared file, so parallel hooks lost each other's increments.

Run with:  python -m unittest discover -s tests -p "test_emission_accounting.py"
"""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import hooklog, hooks_common, hooks_prompt, usage  # noqa: E402
from _jsonl import FIXED_TRANSCRIPT, write_transcript  # noqa: E402


def run(argv: list[str]) -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, buf.getvalue()


def run_hook(event: str, payload: dict) -> dict:
    """`crumb hook <event>` in-process, through the real dispatcher and hook log."""
    out = io.StringIO()
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(out):
            code = crumb.main(["hook", event])
    finally:
        sys.stdin = saved
    assert code == 0, f"a hook must always exit 0, got {code}"
    text = out.getvalue().strip()
    return json.loads(text) if text else {}


def make_repo(tmp: str) -> Path:
    root = Path(tmp)
    for args in (
        ["init", "-q"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    (root / "f.txt").write_text("a\n")
    subprocess.run(["git", "add", "f.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True, capture_output=True)
    return root


def init_store(root: Path) -> Path:
    code, out = run(["init", "--project", str(root), "--session-tracking", "full"])
    assert code == 0, out
    return root / crumb.MEMORY_DIRNAME


def a_decision(root: Path, title: str, *, file: str, tags: str = "routing") -> str:
    code, out = run(
        [
            "remember",
            "decision",
            "--project",
            str(root),
            "--title",
            title,
            "--set",
            "Decision",
            "recorded for the test",
            "--evidence",
            "file",
            file,
            "--tags",
            tags,
            "--allow-duplicate",
            "--json",
        ]
    )
    assert code == 0, out
    return json.loads(out)["id"]


def surfaced(mem: Path, rid: str) -> int:
    entry = usage.load_usage(mem)["records"].get(rid) or {}
    return int(entry.get("surfaced", 0))


def context_of(out: dict) -> str:
    spec = out.get("hookSpecificOutput") or {}
    return spec.get("additionalContext") or spec.get("permissionDecisionReason") or ""


def compacted_preamble(root: Path, session: str) -> str:
    path = write_transcript(root, FIXED_TRANSCRIPT)
    run_hook("compact", {"cwd": str(root), "session_id": session, "transcript_path": str(path)})
    out = run_hook("session", {"cwd": str(root), "session_id": session, "source": "compact"})
    text = context_of(out)
    return text.split("# Resume Packet", 1)[0]


TASK_A = "refactor the amber quasar routing policy in src/quasar.py"
TASK_B = "design the calendar week view with drag to reschedule"


class LatestIntentTests(unittest.TestCase):
    def test_unmatched_new_task_replaces_old_matched_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            rid = a_decision(root, "Amber quasar routing uses the slow queue", file="src/quasar.py")

            def prompt(text: str) -> dict:
                return run_hook("prompt", {"cwd": str(root), "session_id": "s1", "prompt": text})

            # Task A matches memory.
            self.assertIn(rid, context_of(prompt(TASK_A)))
            state = hooks_common.prompt_state(mem, "s1")
            self.assertEqual(state["last_prompt"], TASK_A)
            self.assertEqual(state["matched"], [rid])

            # Task B matches nothing, and still replaces A as the latest task.
            self.assertEqual(prompt(TASK_B), {})
            state = hooks_common.prompt_state(mem, "s1")
            self.assertEqual(state["last_prompt"], TASK_B)
            self.assertEqual(state["matched"], [], "A's hits are not B's")
            # The retrieval state is kept apart, still labelled with A's task.
            self.assertEqual(state["retrieval"]["for_task"], hooks_common.task_ref(TASK_B))
            self.assertEqual(state["retrieval"]["selected"], [])

            # An acknowledgement and a slash command are not new tasks.
            prompt("ok")
            prompt("/compact")
            self.assertEqual(hooks_common.prompt_state(mem, "s1")["last_prompt"], TASK_B)

            preamble = compacted_preamble(root, "s1")
            self.assertIn(f"Latest task before compaction (the user's words): {TASK_B}", preamble)
            self.assertIn("Memory matched nothing for it.", preamble)
            self.assertNotIn("quasar", preamble)
            self.assertNotIn(rid, preamble)

            # A short, meaningful prompt is a task (audit F10) and replaces B.
            prompt("ruff")
            prompt("thanks")
            preamble = compacted_preamble(root, "s1")
            self.assertIn("Latest task before compaction (the user's words): ruff", preamble)
            self.assertNotIn(TASK_B, preamble)

            # The rebuilt packet after the compaction is ordered for the latest
            # task, not the last task that happened to match memory.
            with mock.patch.object(
                _cli, "build_resume_packet", wraps=_cli.build_resume_packet
            ) as b:
                run_hook("session", {"cwd": str(root), "session_id": "s1", "source": "compact"})
            self.assertEqual(b.call_args.kwargs["task"], "ruff")

    def test_task_text_follows_the_privacy_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            a_decision(root, "Amber quasar routing uses the slow queue", file="src/quasar.py")
            state_file = hooks_common.private_path(mem, hooks_common.SESSION_STATE_FILENAME)

            # A credential in the prompt: the task is recorded, its text is not.
            secret = "deploy with AKIAIOSFODNN7EXAMPLE to the calendar bucket"
            run_hook("prompt", {"cwd": str(root), "session_id": "s1", "prompt": secret})
            self.assertNotIn("AKIA", state_file.read_text(encoding="utf-8"))
            state = hooks_common.prompt_state(mem, "s1")
            self.assertEqual(state["task"]["withheld"], "credential")
            self.assertNotIn("last_prompt", state)
            preamble = compacted_preamble(root, "s1")
            self.assertIn("not retained (it contained a credential)", preamble)

            # The manifest can switch retention off: digest and time only.
            manifest = mem / "manifest.yml"
            manifest.write_text(
                manifest.read_text(encoding="utf-8") + "retain_prompt_text: false\n",
                encoding="utf-8",
            )
            run_hook("prompt", {"cwd": str(root), "session_id": "s2", "prompt": TASK_A})
            self.assertNotIn("routing policy", state_file.read_text(encoding="utf-8"))
            state = hooks_common.prompt_state(mem, "s2")
            self.assertEqual(state["task"]["withheld"], "policy")
            self.assertEqual(state["task"]["ref"], hooks_common.task_ref(TASK_A))
            self.assertIn("retain_prompt_text is false", compacted_preamble(root, "s2"))

    def test_a_state_file_from_before_wp12_still_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            hooks_common.write_state(
                mem,
                hooks_common.SESSION_STATE_FILENAME,
                {"s1": {"last_prompt": "old task", "matched": ["dec_x"], "updated_at": "x"}},
            )
            state = hooks_common.prompt_state(mem, "s1")
            self.assertEqual((state["last_prompt"], state["matched"]), ("old task", ["dec_x"]))
            # The next prompt writes the new shape and drops the old keys.
            run_hook("prompt", {"cwd": str(root), "session_id": "s1", "prompt": TASK_B})
            raw = hooks_common.read_state(mem, hooks_common.SESSION_STATE_FILENAME)["s1"]
            self.assertNotIn("matched", raw)
            self.assertEqual(hooks_common.prompt_state(mem, "s1")["last_prompt"], TASK_B)


class EmissionTests(unittest.TestCase):
    def test_deduped_guard_does_not_increment_surfaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            rid = a_decision(root, "Amber quasar routing uses the slow queue", file="src/quasar.py")
            payload = {
                "cwd": str(root),
                "session_id": "counts",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "src/quasar.py",
                    "new_string": "refactor amber quasar routing policy",
                },
            }
            first = run_hook("guard", payload)
            second = run_hook("guard", payload)
            self.assertIn("slow queue", context_of(first))
            self.assertEqual(second, {}, "the repeat is deduplicated")
            self.assertEqual(surfaced(mem, rid), 1, "one emission, one count (audit F16)")

            # The log says which firing emitted and which was deduped.
            guard_lines = [e for e in hooklog.read_log(mem) if e["event"] == "guard"]
            self.assertEqual([e.get("emitted") for e in guard_lines], [1, 0])
            self.assertTrue(guard_lines[1].get("deduped"))

            # Another session is another emission.
            run_hook("guard", {**payload, "session_id": "other"})
            self.assertEqual(surfaced(mem, rid), 2)

            # The prompt hook: the same records again in one session are said
            # once and counted once.
            p = {"cwd": str(root), "session_id": "counts", "prompt": TASK_A}
            self.assertIn(rid, context_of(run_hook("prompt", p)))
            self.assertEqual(run_hook("prompt", {**p, "prompt": TASK_A + " again"}), {})
            self.assertEqual(usage.load_usage(mem)["records"][rid]["by"].get("prompt"), 1)

            # Silent and empty outcomes count nothing.
            before = surfaced(mem, rid)
            run_hook("guard", {**payload, "tool_name": "Bash", "tool_input": {"command": "ls"}})
            run_hook("prompt", {**p, "prompt": TASK_B})
            run_hook("prompt", {**p, "prompt": "ok"})
            self.assertEqual(surfaced(mem, rid), before)

    def test_trimmed_ids_are_not_counted_as_emitted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            ids = [
                a_decision(
                    root,
                    f"Amber quasar routing rule {word} for the slow queue",
                    file="src/quasar.py",
                )
                for word in ("alpha", "bravo", "charlie", "delta", "echo")
            ]

            # The prompt hook, with a budget that fits two lines of five.
            fits_two = None
            for budget in range(50, 800):
                with mock.patch.object(hooks_prompt, "PROMPT_HOOK_TOKEN_BUDGET", budget):
                    matches = hooks_prompt.retrieve(mem, root, TASK_A)
                    if len(hooks_prompt.render_emitted(matches)[1]) == 2:
                        fits_two = budget
                        break
            self.assertIsNotNone(fits_two)
            self.assertEqual(len(matches), 5, "all five are selected")
            with mock.patch.object(hooks_prompt, "PROMPT_HOOK_TOKEN_BUDGET", fits_two):
                out = run_hook("prompt", {"cwd": str(root), "session_id": "p", "prompt": TASK_A})
            text = context_of(out)
            shown = [i for i in ids if i in text]
            self.assertEqual(len(shown), 2)
            counted = {
                i
                for i in ids
                if usage.load_usage(mem)["records"].get(i, {}).get("by", {}).get("prompt")
            }
            self.assertEqual(counted, set(shown), "only the rendered ids are counted")
            state = hooks_common.prompt_state(mem, "p")
            self.assertEqual(len(state["retrieval"]["selected"]), 5)
            self.assertEqual(sorted(state["retrieval"]["emitted"]), sorted(shown))
            line = [e for e in hooklog.read_log(mem) if e["event"] == "prompt"][-1]
            self.assertEqual((line["matches"], line["emitted"], line["trimmed"]), (5, 2, 3))

            # Over budget entirely: nothing is printed and nothing is counted.
            with mock.patch.object(hooks_prompt, "PROMPT_HOOK_TOKEN_BUDGET", 5):
                out = run_hook("prompt", {"cwd": str(root), "session_id": "q", "prompt": TASK_A})
            self.assertEqual(out, {})
            self.assertEqual(
                sum(
                    usage.load_usage(mem)["records"].get(i, {}).get("by", {}).get("prompt", 0)
                    for i in ids
                ),
                2,
            )

            # The guard hook names three matches; only those three are counted.
            out = run_hook(
                "guard",
                {
                    "cwd": str(root),
                    "session_id": "g",
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "src/quasar.py", "new_string": "x"},
                },
            )
            reason = context_of(out)
            named = [i for i in ids if _cli.find_record_by_id(mem, i).meta["title"] in reason]
            self.assertEqual(len(named), 3, reason)
            by_hook = {
                i
                for i in ids
                if usage.load_usage(mem)["records"].get(i, {}).get("by", {}).get("hook-guard")
            }
            self.assertEqual(by_hook, set(named))

            # A trimmed resume packet counts what it printed, not what it computed.
            code, printed = run(["resume", "--project", str(root), "--budget", "900"])
            self.assertEqual(code, 0, printed)
            by_resume = {
                i
                for i in ids
                if usage.load_usage(mem)["records"].get(i, {}).get("by", {}).get("resume")
            }
            self.assertTrue(by_resume)
            self.assertEqual(by_resume, {i for i in ids if i in printed})


WORKER = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    sys.path.insert(0, {repo!r})
    from breadcrumbs import hooklog, hooks_common, usage

    mem, worker, go = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    hooklog.HOOK_LOG_MAX_LINES = {max_lines}
    hooklog._MIN_LINE_BYTES = 1
    while not go.exists():
        time.sleep(0.001)
    acked = {{}}
    for i in range({calls}):
        ids = ["dec_shared", f"dec_w{{worker}}"]
        n = usage.record_surfaced(mem, ids, "hook-guard", session_id=f"s{{worker}}")
        for rid in ids[:n]:
            acked[rid] = acked.get(rid, 0) + 1
        hooklog.append(mem, {{"event": "guard", "worker": worker, "n": i}})
        hooks_common.record_task(mem, f"s{{worker}}", f"task {{i}} of worker {{worker}}")
    print(acked)
    """
)


class ConcurrencyTests(unittest.TestCase):
    def test_parallel_telemetry_does_not_silently_lose_acknowledged_events(self):
        workers, calls = 6, 30
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            go = Path(tmp) / "go"
            # One rotation of the hook log over the run, and the retained window
            # (both files) holds every line written.
            max_lines = workers * calls + 20
            script = WORKER.format(repo=str(REPO_ROOT), max_lines=max_lines, calls=calls)
            procs = [
                subprocess.Popen(
                    [sys.executable, "-c", script, str(mem), str(w), str(go)],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                for w in range(workers)
            ]
            time.sleep(0.3)
            go.write_text("go")
            acked: dict[str, int] = {}
            for proc in procs:
                out, err = proc.communicate(timeout=120)
                self.assertEqual(proc.returncode, 0, err)
                for rid, n in eval(out.strip()).items():  # noqa: S307 - our own worker's dict
                    acked[rid] = acked.get(rid, 0) + n

            # Usage: every acknowledged increment is counted, none twice.
            records = usage.load_usage(mem)["records"]
            self.assertEqual(acked.get("dec_shared"), workers * calls, "nothing was dropped")
            for rid, n in acked.items():
                self.assertEqual(records[rid]["surfaced"], n, rid)
            self.assertEqual(len(records["dec_shared"]["sessions"]), workers)
            # ...and still exactly once after everything is folded.
            self.assertTrue(usage.fold(mem, timeout=5))
            acc = usage.accounting(mem)
            self.assertEqual(acc["pending_events"], 0)
            self.assertEqual(acc["events_folded"], workers * calls)
            self.assertEqual(acc["unreadable_events"], 0)
            self.assertEqual(
                usage.load_usage(mem)["records"]["dec_shared"]["surfaced"], workers * calls
            )
            self.assertEqual(list(usage.events_dir(mem).glob("*.json")), [])

            # The hook log: every line from every worker, across a rotation.
            with mock.patch.object(hooklog, "HOOK_LOG_MAX_LINES", max_lines):
                entries = [e for e in hooklog.read_log(mem) if "worker" in e]
            self.assertTrue(hooklog.rotated_path(mem).exists(), "the run rotated the log")
            seen = {(e["worker"], e["n"]) for e in entries}
            self.assertEqual(len(entries), workers * calls)
            self.assertEqual(seen, {(w, i) for w in range(workers) for i in range(calls)})

            # Session state: no session's entry was lost to another's rewrite.
            sessions = hooks_common.read_state(mem, hooks_common.SESSION_STATE_FILENAME)
            for w in range(workers):
                self.assertEqual(
                    sessions[f"s{w}"]["task"]["text"], f"task {calls - 1} of worker {w}"
                )

    def test_a_fold_that_dies_after_writing_does_not_count_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            mem = init_store(make_repo(tmp))
            with mock.patch.object(usage, "fold", return_value=False):
                for _ in range(3):
                    usage.record_surfaced(mem, ["dec_x"], "resume")
            self.assertEqual(usage.accounting(mem)["pending_events"], 3)
            self.assertEqual(surfaced(mem, "dec_x"), 3, "pending events are counted")
            # The fold writes its counts, then "dies" before deleting the events.
            with mock.patch.object(Path, "unlink", side_effect=OSError("killed")):
                self.assertTrue(usage.fold(mem))
            self.assertEqual(len(list(usage.events_dir(mem).glob("*.json"))), 3)
            self.assertEqual(surfaced(mem, "dec_x"), 3)
            self.assertTrue(usage.fold(mem))
            self.assertEqual(surfaced(mem, "dec_x"), 3)
            self.assertEqual(list(usage.events_dir(mem).glob("*.json")), [])

    def test_dropped_emissions_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            # A full backlog that cannot be folded: the emission is refused, and
            # the refusal is in the hook log, not silent.
            with (
                mock.patch.object(usage, "USAGE_MAX_PENDING_EVENTS", 2),
                mock.patch.object(usage, "fold", return_value=False),
            ):
                self.assertEqual(usage.record_surfaced(mem, ["dec_x"], "resume"), 1)
                self.assertEqual(usage.record_surfaced(mem, ["dec_x"], "resume"), 1)
                hooklog._notes.clear()
                self.assertEqual(usage.record_surfaced(mem, ["dec_x"], "resume"), 0)
                self.assertEqual(hooklog._notes.get("usage_dropped"), 1)
            hooklog._notes.clear()
            self.assertEqual(surfaced(mem, "dec_x"), 2)
            # `crumb usage` states the accounting model and what is unfolded.
            code, out = run(["usage", "--project", str(root), "--json"])
            self.assertEqual(code, 0, out)
            acc = json.loads(out)["accounting"]
            self.assertEqual(acc["pending_events"], 2)
            self.assertIn("not that it was read or that it helped", acc["model"])
            code, out = run(["usage", "--project", str(root)])
            self.assertIn("2 event(s) not yet folded (already counted)", out)

    def test_counts_never_decide_anything_on_their_own(self):
        """Frequency is a suggestion, never authority (audit F16): the decay and
        promotion reports built on these counts print commands for a person and
        change nothing."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_repo(tmp)
            mem = init_store(root)
            rid = a_decision(root, "Amber quasar routing uses the slow queue", file="src/quasar.py")
            for i in range(50):
                usage.record_surfaced(mem, [rid], "hook-guard", session_id=f"s{i}")
            before = {p: p.read_bytes() for p in (mem / "decisions").rglob("*.md")}
            for argv in (
                ["usage", "--project", str(root), "--decay", "0"],
                ["usage", "--project", str(root), "--never"],
                ["audit", "--project", str(root)],
            ):
                run(argv)
            after = {p: p.read_bytes() for p in (mem / "decisions").rglob("*.md")}
            self.assertEqual(before, after)
            for name in ("CLAUDE.md", "AGENTS.md"):
                self.assertFalse((root / name).exists())


if __name__ == "__main__":
    unittest.main()
