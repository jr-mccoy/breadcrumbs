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
    for form in {str(root), str(root.resolve())}:
        text = text.replace(form, "<ROOT>")
    text = re.sub(r"\b[0-9a-f]{40}\b", "<SHA>", text)
    text = re.sub(r'("(?:source_commit|commit|head)": ")[0-9a-f]{7,40}"', r'\1<SHA>"', text)
    text = re.sub(r'("(?:elapsed_ms|ms|seconds|duration_ms)": )[0-9.]+', r"\g<1>0", text)
    return json.loads(text)


def scenario(root: Path) -> dict:
    """One scripted session through the CLI, MCP and hook transports."""
    out: dict = {}
    for args in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "--allow-empty", "-m", "i"],
        cwd=root,
        check=True,
        env={**os.environ, "GIT_AUTHOR_DATE": "2026-09-20T12:00:00Z", "GIT_COMMITTER_DATE": "2026-09-20T12:00:00Z"},
    )
    p = ["--project", str(root)]
    out["init"] = _run(["init", *p, "--session-tracking", "full"])[0]
    writes = [
        ["remember", "decision", "--title", "Cache TTL is five minutes for the pricing API",
         "--set", "Decision", "pricing responses are cached for 300 seconds",
         "--set", "Why", "upstream rate limits", "--evidence", "file", "src/pricing/cache.py",
         "--tags", "pricing,cache"],
        ["remember", "decision", "--title", "Retries use exponential backoff with jitter",
         "--set", "Decision", "retry the billing webhook with backoff and jitter",
         "--evidence", "file", "src/billing/webhook.py", "--tags", "billing,retry"],
        ["remember", "attempt", "--title", "Tried an in-memory cache for pricing",
         "--problem", "pricing API is slow", "--tried", "an in-process LRU cache for pricing",
         "--result", "stale prices across workers",
         "--do-not-retry", "the pricing workers share one process",
         "--evidence", "file", "src/pricing/cache.py", "--tags", "pricing,cache"],
    ]
    out["cli_remember"] = []
    for argv in writes:
        code, text = _run([*argv, *p, "--json"])
        out["cli_remember"].append([code, _json(text)])
    code, text = _run(["remember", "decision", "--title", "Cache TTL is five minutes for the pricing API",
                       "--set", "Decision", "pricing responses are cached for 300 seconds",
                       "--evidence", "file", "src/pricing/cache.py", *p, "--json"])
    out["cli_remember_duplicate"] = [code, _json(text)]
    code, text = _run(["remember", "decision", "--title", "No evidence decision", *p, "--json"])
    out["cli_remember_no_evidence"] = [code, _json(text)]
    code, text = _run(["note", "trap", "Pricing cache keys must include currency", "--area", "src/pricing",
                       "--symptom", "wrong currency served", "--why", "key omits currency",
                       "--safe", "include currency in the key", *p, "--json"])
    out["cli_note_trap"] = [code, _json(text)]
    code, text = _run(["jot", "the billing webhook sometimes double-fires", "--file", "src/billing/webhook.py",
                       *p, "--json"])
    out["cli_jot"] = [code, _json(text)]

    payload = {"title": "Queue workers drain before deploy", "sections": {"Decision": "drain the queue first"},
               "evidence": [{"type": "file", "ref": "src/queue/worker.py"}], "tags": ["queue"]}
    out["mcp_record"] = mcp_core.tool_record("decision", payload, root=root)
    out["mcp_record_human"] = mcp_core.tool_record("decision", {**payload, "title": "Other", "agent": "human"}, root=root)
    out["mcp_record_no_evidence_confidence"] = mcp_core.tool_record(
        "decision", {"title": "Stated without evidence", "confidence": "high"}, root=root
    )
    out["mcp_record_duplicate"] = mcp_core.tool_record("decision", payload, root=root)
    out["mcp_jot"] = mcp_core.tool_jot("pricing cache warmed at deploy", root=root)

    code, text = _run(["search", "pricing cache", *p, "--json"])
    out["cli_search"] = [code, _json(text)]
    out["mcp_search"] = mcp_core.tool_search("pricing cache", root=root)
    code, text = _run(["guard", "change the pricing cache ttl", "--files", "src/pricing/cache.py", *p, "--json"])
    out["cli_guard"] = [code, _json(text)]
    out["mcp_guard"] = mcp_core.tool_guard_before_action(
        "change the pricing cache ttl", files=["src/pricing/cache.py"], root=root
    )
    hook_env = {"cwd": str(root), "session_id": "s-parity"}
    code, text = _run(["hook", "guard"], stdin=json.dumps({**hook_env, "tool_name": "Edit",
                      "tool_input": {"file_path": str(root / "src/pricing/cache.py"), "new_string": "TTL = 60"}}))
    out["hook_guard"] = [code, _json(text)]
    code, text = _run(["hook", "prompt"], stdin=json.dumps({**hook_env, "prompt": "change the pricing cache ttl"}))
    out["hook_prompt"] = [code, _json(text)]
    code, text = _run(["resume", *p, "--json", "--task", "pricing cache"])
    out["cli_resume"] = [code, _json(text)]
    out["mcp_resume"] = mcp_core.tool_build_resume_packet(task="pricing cache", root=root)
    mem = root / crumb.MEMORY_DIRNAME
    for name in ("related.json", "conflicts.json"):
        out[f"generated_{name}"] = json.loads((mem / "generated" / name).read_text(encoding="utf-8"))
    out["record_ids"] = sorted(p.stem for p in mem.rglob("*.md") if p.parent.name in ("decisions", "attempts", "traps"))
    return out


def run_scenario() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in AGENT_MARKERS}
    suffixes = (f"{n:04x}" for n in range(1, 1 << 16))
    with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
        os.environ, env, clear=True
    ), mock.patch.object(_cli, "_now", lambda: CLOCK), mock.patch.object(
        _cli, "_unique_suffix", lambda: next(suffixes)
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


if __name__ == "__main__":
    if "--write-golden" in sys.argv:
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(run_scenario(), indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {GOLDEN}")
    else:
        unittest.main()
