"""The application layer (audit WP16): one set of operations behind the CLI,
MCP and hooks, with the transports at the edges.

- `test_refactor_preserves_ids_scores_and_wire_contracts` replays one scripted
  session through every transport and compares the serialized outputs with a
  golden captured from the code before the extraction
  (`fixtures/application_parity.json`; regenerate only on purpose, with
  `python tests/test_application_parity.py --write-golden`).
- The other tests hold the structure: the service imports without the
  argument parser, the three channels share one admission decision, and two
  store contexts share no alias or policy state.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli as _cli  # noqa: E402
from breadcrumbs import mcp_core  # noqa: E402

GOLDEN = Path(__file__).resolve().parent / "fixtures" / "application_parity.json"
CLOCK = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT", "CODEX_HOME")


def _run(argv: list[str], stdin: str | None = None) -> tuple[int, str]:
    out = io.StringIO()
    saved = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            try:
                code = crumb.main(argv)
            except SystemExit as exc:
                code = exc.code
    finally:
        sys.stdin = saved
    return code, out.getvalue()


def _json(text: str):
    return json.loads(text) if text.strip() else None


def normalize(value, root: Path):
    """Strip what differs between runs and machines: the temp root, commit
    hashes, and wall-clock durations. Everything else must match exactly."""
    text = json.dumps(value, sort_keys=True)
    # Longest spelling first: macOS `/private/var/…` contains `/var/…`, and a
    # set's order left `/private<ROOT>` behind. Forms as JSON escapes them
    # (Windows backslashes), then the rest of a rooted path made POSIX.
    forms = {json.dumps(str(p))[1:-1] for p in (root, root.resolve())}
    for form in sorted(forms, key=len, reverse=True):
        text = text.replace(form, "<ROOT>")
    text = re.sub(
        r'<ROOT>((?:\\\\[^"\\]*)+)', lambda m: "<ROOT>" + m.group(1).replace("\\\\", "/"), text
    )
    text = re.sub(r"\b[0-9a-f]{40}\b", "<SHA>", text)
    text = re.sub(r'("(?:source_commit|commit|head)": ")[0-9a-f]{7,40}"', r'\1<SHA>"', text)
    text = re.sub(r'("(?:elapsed_ms|ms|seconds|duration_ms)": )[0-9.]+', r"\g<1>0", text)
    return json.loads(text)


def scenario(root: Path) -> dict:
    """One scripted session through the CLI, MCP and hook transports."""
    out: dict = {}
    # The scenario's git ignores the machine's global and system config: a
    # global `commit.gpgsign` (or a default branch name) changes the commit
    # hash, which records carry and every inputs hash covers.
    git_env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    for args in (
        ["init", "-q"],
        ["symbolic-ref", "HEAD", "refs/heads/main"],
        ["config", "user.email", "t@t"],
        ["config", "user.name", "t"],
    ):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=git_env)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "i"],
        cwd=root,
        check=True,
        env={
            **git_env,
            "GIT_AUTHOR_DATE": "2026-09-20T12:00:00Z",
            "GIT_COMMITTER_DATE": "2026-09-20T12:00:00Z",
        },
    )
    p = ["--project", str(root)]
    out["init"] = _run(["init", *p, "--session-tracking", "full"])[0]
    writes = [
        [
            "remember",
            "decision",
            "--title",
            "Cache TTL is five minutes for the pricing API",
            "--set",
            "Decision",
            "pricing responses are cached for 300 seconds",
            "--set",
            "Why",
            "upstream rate limits",
            "--evidence",
            "file",
            "src/pricing/cache.py",
            "--tags",
            "pricing,cache",
        ],
        [
            "remember",
            "decision",
            "--title",
            "Retries use exponential backoff with jitter",
            "--set",
            "Decision",
            "retry the billing webhook with backoff and jitter",
            "--evidence",
            "file",
            "src/billing/webhook.py",
            "--tags",
            "billing,retry",
        ],
        [
            "remember",
            "attempt",
            "--title",
            "Tried an in-memory cache for pricing",
            "--problem",
            "pricing API is slow",
            "--tried",
            "an in-process LRU cache for pricing",
            "--result",
            "stale prices across workers",
            "--do-not-retry",
            "the pricing workers share one process",
            "--evidence",
            "file",
            "src/pricing/cache.py",
            "--tags",
            "pricing,cache",
        ],
    ]
    out["cli_remember"] = []
    for argv in writes:
        code, text = _run([*argv, *p, "--json"])
        out["cli_remember"].append([code, _json(text)])
    code, text = _run(
        [
            "remember",
            "decision",
            "--title",
            "Cache TTL is five minutes for the pricing API",
            "--set",
            "Decision",
            "pricing responses are cached for 300 seconds",
            "--evidence",
            "file",
            "src/pricing/cache.py",
            *p,
            "--json",
        ]
    )
    out["cli_remember_duplicate"] = [code, _json(text)]
    code, text = _run(["remember", "decision", "--title", "No evidence decision", *p, "--json"])
    out["cli_remember_no_evidence"] = [code, _json(text)]
    code, text = _run(
        [
            "note",
            "trap",
            "Pricing cache keys must include currency",
            "--area",
            "src/pricing",
            "--symptom",
            "wrong currency served",
            "--why",
            "key omits currency",
            "--safe",
            "include currency in the key",
            *p,
            "--json",
        ]
    )
    out["cli_note_trap"] = [code, _json(text)]
    code, text = _run(
        [
            "jot",
            "the billing webhook sometimes double-fires",
            "--file",
            "src/billing/webhook.py",
            *p,
            "--json",
        ]
    )
    out["cli_jot"] = [code, _json(text)]

    payload = {
        "title": "Queue workers drain before deploy",
        "sections": {"Decision": "drain the queue first"},
        "evidence": [{"type": "file", "ref": "src/queue/worker.py"}],
        "tags": ["queue"],
    }
    out["mcp_record"] = mcp_core.tool_record("decision", payload, root=root)
    out["mcp_record_human"] = mcp_core.tool_record(
        "decision", {**payload, "title": "Other", "agent": "human"}, root=root
    )
    out["mcp_record_no_evidence_confidence"] = mcp_core.tool_record(
        "decision", {"title": "Stated without evidence", "confidence": "high"}, root=root
    )
    out["mcp_record_duplicate"] = mcp_core.tool_record("decision", payload, root=root)
    out["mcp_jot"] = mcp_core.tool_jot("pricing cache warmed at deploy", root=root)

    code, text = _run(["search", "pricing cache", *p, "--json"])
    out["cli_search"] = [code, _json(text)]
    out["mcp_search"] = mcp_core.tool_search("pricing cache", root=root)
    code, text = _run(
        ["guard", "change the pricing cache ttl", "--files", "src/pricing/cache.py", *p, "--json"]
    )
    out["cli_guard"] = [code, _json(text)]
    out["mcp_guard"] = mcp_core.tool_guard_before_action(
        "change the pricing cache ttl", files=["src/pricing/cache.py"], root=root
    )
    hook_env = {"cwd": str(root), "session_id": "s-parity"}
    code, text = _run(
        ["hook", "guard"],
        stdin=json.dumps(
            {
                **hook_env,
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": str(root / "src/pricing/cache.py"),
                    "new_string": "TTL = 60",
                },
            }
        ),
    )
    out["hook_guard"] = [code, _json(text)]
    code, text = _run(
        ["hook", "prompt"], stdin=json.dumps({**hook_env, "prompt": "change the pricing cache ttl"})
    )
    out["hook_prompt"] = [code, _json(text)]
    code, text = _run(["resume", *p, "--json", "--task", "pricing cache"])
    out["cli_resume"] = [code, _json(text)]
    out["mcp_resume"] = mcp_core.tool_build_resume_packet(task="pricing cache", root=root)
    mem = root / crumb.MEMORY_DIRNAME
    for name in ("related.json", "conflicts.json"):
        out[f"generated_{name}"] = json.loads(
            (mem / "generated" / name).read_text(encoding="utf-8")
        )
    out["record_ids"] = sorted(
        p.stem for p in mem.rglob("*.md") if p.parent.name in ("decisions", "attempts", "traps")
    )
    return out


def run_scenario() -> dict:
    # The author a record names comes from $USER; pin it (and drop USERNAME) so
    # the records, and every inputs hash over them, are machine-independent.
    env = {k: v for k, v in os.environ.items() if k not in AGENT_MARKERS and k != "USERNAME"}
    env["USER"] = "parity"
    suffixes = (f"{n:04x}" for n in range(1, 1 << 16))
    with (
        tempfile.TemporaryDirectory() as tmp,
        mock.patch.dict(os.environ, env, clear=True),
        mock.patch.object(_cli, "_now", lambda: CLOCK),
        mock.patch.object(_cli, "_unique_suffix", lambda: next(suffixes)),
    ):
        # A fixed directory name: the project name appears in the packet.
        root = Path(tmp) / "parity-project"
        root.mkdir()
        return normalize(scenario(root), root)


class ParityTests(unittest.TestCase):
    maxDiff = None

    def test_refactor_preserves_ids_scores_and_wire_contracts(self):
        golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        actual = run_scenario()
        self.assertEqual(sorted(actual), sorted(golden))
        for key in golden:
            with self.subTest(key):
                self.assertEqual(actual[key], golden[key])

    def test_scenario_is_deterministic(self):
        """Two runs agree, so a parity failure is a behavior change, not noise."""
        self.assertEqual(run_scenario(), run_scenario())


def make_store(parent: Path, name: str) -> Path:
    root = parent / name
    root.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "i"], cwd=root, check=True)
    _run(["init", "--project", str(root), "--session-tracking", "full"])
    return root


def _clean_env() -> dict:
    return {k: v for k, v in os.environ.items() if k not in AGENT_MARKERS}


class StructureTests(unittest.TestCase):
    def test_service_import_does_not_import_cli_parser(self):
        """The application layer imports and runs without the argument parser,
        and without printing (F21's completion test)."""
        probe = r"""
import contextlib, io, json, subprocess, sys, tempfile
from pathlib import Path
from breadcrumbs import service
loaded = {m for m in ("breadcrumbs.cli_parser", "argparse") if m in sys.modules}
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".project-memory").mkdir()
    for d in ("decisions", "attempts", "sessions", "traps", "questions", "ideas", "inbox", "handoffs"):
        (root / ".project-memory" / d).mkdir()
    ctx = service.open_context(root, agent="probe")
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            service.search(ctx, "anything")
            service.guard(ctx, "edit the cache")
        except service.ServiceError:
            pass
    loaded |= {m for m in ("breadcrumbs.cli_parser",) if m in sys.modules}
print(json.dumps({"loaded": sorted(loaded), "stdout": out.getvalue()}))
"""
        p = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=_clean_env(),
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual(result["loaded"], [], "the service import pulled in the parser")
        self.assertEqual(result["stdout"], "")
        # And the CLI still builds its parser on demand.
        self.assertIsNotNone(_cli.build_parser("guard"))

    def test_cli_mcp_and_hook_admission_parity(self):
        """One admission decision, whichever transport the write arrives by.

        For every policy and payload: what `service.admit` / `review_status_for`
        decide for a channel is what the transport for that channel does, and
        each transport reaches that decision through the service.
        """
        from breadcrumbs import admission, service

        policies = [
            ("solo", "write"),
            ("solo", "propose"),
            ("team", "propose"),
            ("team", "read-only"),
        ]
        payloads = {
            "plain": {},
            "agent-human": {"agent": "human"},
            "reviewed": {"review_status": "reviewed"},
            "reviewed-by": {"reviewed_by": "alice"},
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, _clean_env(), clear=True),
        ):
            n = 0
            for profile, mode in policies:
                root = make_store(Path(tmp), f"{profile}-{mode}")
                mem = root / crumb.MEMORY_DIRNAME
                admission.set_policy(mem, profile, mode)
                for label, extra in payloads.items():
                    for chan in ("cli", "mcp", "hook"):
                        n += 1
                        case = f"{profile}/{mode} {label} via {chan}"
                        ctx = service.Context(root, mem, chan, None, "agent")
                        try:
                            service.admit(ctx, extra)
                            expected_refused = False
                        except service.ServiceError:
                            expected_refused = True
                        base = {
                            "title": f"Parity decision {n} about the {chan} {label} lane",
                            "sections": {"Decision": f"lane {n} {label} {chan}"},
                            "evidence": [{"type": "file", "ref": f"src/lane{n}.py"}],
                            "allow_duplicate": True,
                        }
                        with mock.patch.object(service, "admit", wraps=service.admit) as spy:
                            if chan == "mcp":
                                res = mcp_core.tool_record("decision", {**base, **extra}, root=root)
                                refused = res.get("refused_by") == "policy"
                                rid = res.get("id")
                            elif chan == "cli":
                                if set(extra) - {"agent"}:
                                    continue  # the CLI has no flag that sets review fields
                                argv = [
                                    "remember",
                                    "decision",
                                    "--title",
                                    base["title"],
                                    "--set",
                                    "Decision",
                                    base["sections"]["Decision"],
                                    "--evidence",
                                    "file",
                                    f"src/lane{n}.py",
                                    "--allow-duplicate",
                                    "--project",
                                    str(root),
                                    "--json",
                                ]
                                if extra.get("agent"):
                                    argv += ["--agent", extra["agent"]]
                                code, text = _run(argv)
                                refused = code != 0
                                rid = (_json(text) or {}).get("id")
                            else:
                                # The hook transport: a write inside the context `crumb hook` sets.
                                try:
                                    with service.active(ctx):
                                        rid = service.record(ctx, "decision", {**base, **extra})[
                                            "id"
                                        ]
                                    refused = False
                                except service.ServiceError as exc:
                                    refused, rid = exc.kind == "refused", None
                            self.assertTrue(spy.called, f"{case}: did not go through service.admit")
                        self.assertEqual(refused, expected_refused, case)
                        if not refused:
                            rec = _cli.find_record_by_id(mem, rid)
                            self.assertEqual(
                                rec.meta.get("review_status"),
                                service.review_status_for(ctx, "decision"),
                                case,
                            )
                # The CLI inside an agent session is an agent's write too.
                with mock.patch.dict(os.environ, {"CLAUDECODE": "1"}):
                    ctx = service.Context(root, mem, "cli")
                    code, text = _run(
                        [
                            "remember",
                            "decision",
                            "--title",
                            f"Agent shell lane {profile} {mode}",
                            "--set",
                            "Decision",
                            "x",
                            "--evidence",
                            "file",
                            "src/shell.py",
                            "--allow-duplicate",
                            "--project",
                            str(root),
                            "--json",
                        ]
                    )
                    self.assertEqual(code, 0, text)
                    rec = _cli.find_record_by_id(mem, _json(text)["id"])
                    expected = "needs-review" if profile == "team" else "unreviewed"
                    self.assertEqual(
                        rec.meta.get("review_status"), service.review_status_for(ctx, "decision")
                    )
                    self.assertEqual(
                        rec.meta.get("review_status"), expected, f"{profile}/{mode} agent CLI"
                    )

    def test_two_store_contexts_do_not_share_alias_or_policy_state(self):
        """Aliases, policy and clock belong to a context, not to the process."""
        import threading

        from breadcrumbs import admission, service

        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(os.environ, _clean_env(), clear=True),
        ):
            root_a = make_store(Path(tmp), "a")
            root_b = make_store(Path(tmp), "b")
            mem_a, mem_b = root_a / crumb.MEMORY_DIRNAME, root_b / crumb.MEMORY_DIRNAME
            (mem_a / "aliases.txt").write_text("billing payments\n", encoding="utf-8")
            admission.set_policy(mem_a, "team")
            for root in (root_a, root_b):
                _run(
                    [
                        "note",
                        "trap",
                        "Billing webhook retries double charge",
                        "--area",
                        "src/billing",
                        "--symptom",
                        "double charge",
                        "--why",
                        "retries",
                        "--safe",
                        "idempotency key",
                        "--project",
                        str(root),
                    ]
                )
            ctx_a = service.Context(root_a, mem_a, "mcp", lambda: CLOCK)
            ctx_b = service.Context(root_b, mem_b, "mcp")
            stem = _cli._base_stem
            results: dict = {}
            barrier = threading.Barrier(2)

            def worker(name, ctx):
                with service.active(ctx):
                    barrier.wait()  # both contexts active at once, in two threads
                    matches, _ = service.search(ctx, "payments")
                    results[name] = {
                        "payments": _cli._stem("payments"),
                        "found": [m["id"] for m in matches],
                        "review": service.review_status_for(ctx, "decision"),
                        "now": _cli.now_iso(),
                    }
                    barrier.wait()

            threads = [
                threading.Thread(target=worker, args=a) for a in (("a", ctx_a), ("b", ctx_b))
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            trap = "trap_billing-webhook-retries-double-charge"
            self.assertEqual(results["a"]["payments"], stem("billing"))
            self.assertEqual(results["b"]["payments"], stem("payments"))
            self.assertIn(trap, results["a"]["found"])
            self.assertNotIn(trap, results["b"]["found"])
            self.assertEqual(results["a"]["review"], "needs-review")  # team
            self.assertEqual(results["b"]["review"], "unreviewed")  # solo, MCP write
            self.assertEqual(results["a"]["now"], "2026-09-20T12:00:00+00:00")
            self.assertNotEqual(results["b"]["now"], "2026-09-20T12:00:00+00:00")

            # Nested in one thread: the inner context's aliases, then the outer's again.
            with service.active(ctx_a):
                self.assertEqual(_cli._stem("payments"), stem("billing"))
                with service.active(ctx_b):
                    self.assertEqual(_cli._stem("payments"), stem("payments"))
                self.assertEqual(_cli._stem("payments"), stem("billing"))
            self.assertEqual(_cli.active_store_aliases(), {})


if __name__ == "__main__":
    if "--write-golden" in sys.argv:
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(
            json.dumps(run_scenario(), indent=1, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"wrote {GOLDEN}")
    else:
        unittest.main()
