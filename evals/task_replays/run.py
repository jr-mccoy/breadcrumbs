"""Controlled two-session continuity replays (audit WP19, finding F26).

For each scenario in `scenarios.json` and each host repository, session 1 is
replayed three ways, and what session 2 is handed is scored by `oracle.py`:

- `none`: no memory. Session 2 gets the repository and its git log, and
  nothing is delivered to it.
- `notes`: a hand-kept `NOTES.md`. Session 1 appends the line a diligent
  person would write; session 2's harness loads the file at start, as it
  loads `CLAUDE.md`/`AGENTS.md`. It is also reloaded after a compaction.
- `breadcrumbs`: session 1 records with `crumb`. Session 2 gets:
  - under Claude Code, the `SessionStart` packet, the `UserPromptSubmit`
    injection and the `PreToolUse` guard warning at its first action;
  - under an MCP client, `memory_build_resume_packet` at start and
    `memory_guard_before_action` at the action. Those are calls the agent must
    make, and the results say so.

What is measured (see `docs/benchmarks/continuity-results.md`):
- whether the scenario's facts were handed over by session start and at the
  action;
- whether stale guidance was presented as current;
- the tokens handed over;
- capture and maintenance cost: commands run, bytes of memory written, and
  prose authored.

This measures delivery, not agent behavior. No model is run.

Hosts: `fresh`, an empty repository; and `this-repo`, a local clone of this
repository with its real store of past records competing for attention.

    python evals/task_replays/run.py [--json OUT] [--hosts fresh this-repo]

Deterministic: no randomness and no model, so a rerun gives the same results
(ids carry the run's date). `results.json` records every delivered text's
digest and, for breadcrumbs, the id and content hash of each record that
surfaced, so a reader can inspect the exact revision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

import oracle  # noqa: E402

CRUMB = [sys.executable, str(ROOT / "crumb.py")]
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")
BASELINES = ("none", "notes", "breadcrumbs")


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in AGENT_MARKERS}
    # The replay's git ignores the machine's config (signing, default branch).
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "USER": "replay"})
    # No background maintenance: newer git (2.47+) detaches `git maintenance
    # run --auto` after a commit, and a detached run still writing into
    # .git/objects made the temporary repo's cleanup fail ("Directory not
    # empty") on CI's git 2.55.
    env.update(
        {
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "maintenance.auto",
            "GIT_CONFIG_VALUE_0": "false",
            "GIT_CONFIG_KEY_1": "gc.auto",
            "GIT_CONFIG_VALUE_1": "0",
        }
    )
    return env


ENV = _env()


def tokens(text: str) -> int:
    """The package's approx-tokens heuristic: ceil(ASCII/4) + 1 per non-ASCII char."""
    ascii_chars = sum(1 for c in text if ord(c) < 128)
    return -(-ascii_chars // 4) + (len(text) - ascii_chars)


def git(root: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, env=ENV)
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def crumb(root: Path, *args: str, stdin: str | None = None) -> tuple[int, str]:
    p = subprocess.run(
        [*CRUMB, *args], cwd=root, input=stdin, capture_output=True, text=True, env=ENV
    )
    return p.returncode, p.stdout


class Cost:
    def __init__(self):
        self.commands = 0
        self.prose_chars = 0


def make_host(kind: str, tmp: Path, scenario: dict) -> Path:
    root = tmp / "repo"
    if kind == "fresh":
        root.mkdir()
        git(root, "init", "-q")
    else:  # this-repo: the real history and store, a local clone
        subprocess.run(
            ["git", "clone", "-q", "--no-hardlinks", str(ROOT), str(root)],
            check=True,
            capture_output=True,
            env=ENV,
        )
    git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    git(root, "config", "user.email", "replay@example.invalid")
    git(root, "config", "user.name", "replay")
    for rel, text in scenario.get("files", {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", "scenario files")
    return root


def _noise(i: int) -> dict:
    words = ["ledger", "tenant", "quota", "export", "webhook", "invoice", "shard", "replica"]
    a, b = words[i % len(words)], words[(i * 3 + 1) % len(words)]
    return {
        "title": f"Unrelated note {i}: {a} handling for the {b} service",
        "decision": f"keep the {a} path for {b} as it is (item {i})",
        "why": "housekeeping",
        "files": [f"src/other/{a}_{i}.py"],
        "tags": [a],
        "markdown": f"- Unrelated note {i}: keep the {a} path for {b}.",
    }


def replay_session1(baseline: str, root: Path, scenario: dict, cost: Cost) -> dict:
    """Session 1, as `baseline` records it. Returns state session 2 needs."""
    committed = scenario.get("memory_committed", True)
    notes = root / "NOTES.md"
    ids: list[str] = []
    state: dict = {"compacted": False}
    if baseline == "breadcrumbs" and not (root / ".project-memory").is_dir():
        crumb(root, "init", "--session-tracking", "full")
        cost.commands += 1
    state["setup_bytes"] = memory_bytes(baseline, root)
    for step in scenario["session1"]:
        event = step["event"]
        if event == "branch":
            if step["name"] == "main":
                git(root, "checkout", "-q", "main")
            else:
                git(root, "checkout", "-q", "-b", step["name"])
            continue
        if event == "compaction":
            state["compacted"] = True
            if baseline == "breadcrumbs":
                crumb(
                    root,
                    "hook",
                    "compact",
                    stdin=json.dumps({"cwd": str(root), "session_id": "s1", "trigger": "auto"}),
                )
            continue
        items = [_noise(i) for i in range(step["count"])] if event == "noise" else [step]
        for item in items:
            prose = " ".join(
                str(item.get(k) or "")
                for k in ("title", "decision", "why", "problem", "tried", "result", "do_not_retry")
            )
            cost.prose_chars += len(prose)
            if baseline == "notes":
                with notes.open("a", encoding="utf-8") as fh:
                    fh.write(item["markdown"] + "\n")
            elif baseline == "breadcrumbs":
                ids.append(
                    _record(root, event if event != "noise" else "decision", item, ids, cost)
                )
            if committed:
                git(root, "add", "-A")
            git(root, "commit", "-q", "--allow-empty", "-m", item.get("commit") or item["title"])
    state["ids"] = ids
    return state


def _record(root: Path, event: str, item: dict, ids: list[str], cost: Cost) -> str:
    args = ["--title", item["title"], "--json", "--allow-duplicate"]
    for f in item.get("files") or []:
        args += ["--evidence", "file", f]
    if item.get("tags"):
        args += ["--tags", ",".join(item["tags"])]
    if item.get("scope"):
        args += ["--scope", item["scope"]]
    if item.get("supersedes_previous") and ids:
        args += ["--supersedes", ids[-1]]
    if event == "attempt":
        args = [
            "remember",
            "attempt",
            "--problem",
            item["problem"],
            "--tried",
            item["tried"],
            "--result",
            item["result"],
            "--do-not-retry",
            item["do_not_retry"],
            *args,
        ]
    else:
        args = [
            "remember",
            "decision",
            "--set",
            "Decision",
            item["decision"],
            "--set",
            "Rationale",
            item["why"],
            *args,
        ]
    code, out = crumb(root, *args)
    cost.commands += 1
    if code != 0:
        raise RuntimeError(f"crumb {' '.join(args[:2])} failed ({code}): {out}")
    return json.loads(out)["id"]


def _hook_text(out: str) -> str:
    try:
        spec = json.loads(out).get("hookSpecificOutput") or {}
    except ValueError:
        return ""
    return str(spec.get("additionalContext") or spec.get("permissionDecisionReason") or "")


def _action_payload(action: dict, root: Path) -> dict:
    if action["tool"] == "Bash":
        return {"tool_name": "Bash", "tool_input": {"command": action["command"]}}
    return {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(root / action["file"]),
            "old_string": "",
            "new_string": action["new"],
        },
    }


def replay_session2(baseline: str, root: Path, scenario: dict, state: dict) -> dict:
    s2 = scenario["session2"]
    harness = scenario.get("harness", "claude-code")
    delivered = {"start": "", "prompt": "", "action": ""}
    if baseline == "notes":
        notes = root / "NOTES.md"
        delivered["start"] = notes.read_text(encoding="utf-8") if notes.exists() else ""
    elif baseline == "breadcrumbs":
        if harness == "mcp":
            probe = (
                "import json,sys; sys.path.insert(0, sys.argv[1]); from breadcrumbs import mcp_core;"
                "r=sys.argv[2]; a=json.loads(sys.argv[3]);"
                "p=mcp_core.tool_build_resume_packet(task=a['prompt'], root=r);"
                "g=mcp_core.tool_guard_before_action(a['action'], files=a.get('files'), root=r);"
                "print(json.dumps({'start': json.dumps(p), 'action': json.dumps(g)}))"
            )
            action = s2["action"]
            text = action.get("command") or f"edit {action.get('file')}: {action.get('new')}"
            arg = {
                "prompt": s2["prompt"],
                "action": text,
                "files": [action["file"]] if action.get("file") else None,
            }
            p = subprocess.run(
                [sys.executable, "-c", probe, str(ROOT), str(root), json.dumps(arg)],
                capture_output=True,
                text=True,
                env=ENV,
            )
            out = json.loads(p.stdout.strip().splitlines()[-1])
            delivered["start"], delivered["action"] = out["start"], out["action"]
        else:
            base = {"cwd": str(root), "session_id": "s2"}
            source = "compact" if state.get("compacted") else "startup"
            _, out = crumb(root, "hook", "session", stdin=json.dumps({**base, "source": source}))
            delivered["start"] = _hook_text(out)
            _, out = crumb(
                root, "hook", "prompt", stdin=json.dumps({**base, "prompt": s2["prompt"]})
            )
            delivered["prompt"] = _hook_text(out)
            payload = {**base, **_action_payload(s2["action"], root)}
            _, out = crumb(root, "hook", "guard", stdin=json.dumps(payload))
            delivered["action"] = _hook_text(out)
    return delivered


def memory_bytes(baseline: str, root: Path) -> int:
    if baseline == "notes":
        p = root / "NOTES.md"
        return p.stat().st_size if p.exists() else 0
    if baseline == "breadcrumbs":
        mem = root / ".project-memory"
        return sum(p.stat().st_size for p in mem.rglob("*") if p.is_file()) if mem.is_dir() else 0
    return 0


def surfaced(root: Path, texts: list[str]) -> list[dict]:
    """Record ids in the delivered text, with each record file's content hash."""
    mem = root / ".project-memory"
    ids = sorted(
        set(re.findall(r"\b(?:dec|att|ver|trap|q|jot|idea)_[a-z0-9_\-]+", " ".join(texts)))
    )
    out = []
    for rid in ids:
        stem = (
            rid.split("_", 2)[-1]
            if rid.startswith(("dec_", "att_", "ver_", "jot_"))
            else rid.split("_", 1)[-1]
        )
        matches = [p for p in mem.rglob("*.md") if p.stem.endswith(stem)] if mem.is_dir() else []
        digest = hashlib.sha256(matches[0].read_bytes()).hexdigest()[:12] if matches else None
        out.append(
            {
                "id": rid,
                "file": matches[0].relative_to(root).as_posix() if matches else None,
                "sha256": digest,
            }
        )
    return out


def run(hosts: list[str]) -> dict:
    scenarios = json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))
    rows = []
    for scenario in scenarios["scenarios"]:
        for host in hosts:
            for baseline in BASELINES:
                with tempfile.TemporaryDirectory() as tmp:
                    root = make_host(host, Path(tmp), scenario)
                    before = memory_bytes(baseline, root)
                    cost = Cost()
                    state = replay_session1(baseline, root, scenario, cost)
                    # Store setup (a new store's scaffolding) apart from what the events wrote.
                    setup = state["setup_bytes"] - before
                    written = memory_bytes(baseline, root) - state["setup_bytes"]
                    delivered = replay_session2(baseline, root, scenario, state)
                    verdict = oracle.judge(scenario["oracle"], delivered)
                    texts = list(delivered.values())
                    rows.append(
                        {
                            "scenario": scenario["id"],
                            "kind": scenario["kind"],
                            "host": host,
                            "baseline": baseline,
                            "harness": scenario.get("harness", "claude-code"),
                            **verdict,
                            "tokens_delivered": sum(tokens(t) for t in texts),
                            "tokens_by_moment": {k: tokens(v) for k, v in delivered.items()},
                            "capture_commands": cost.commands,
                            "memory_bytes_written": written,
                            "setup_bytes": setup,
                            "prose_chars": cost.prose_chars,
                            "delivered_sha256": {
                                k: hashlib.sha256(v.encode()).hexdigest()[:12]
                                for k, v in delivered.items()
                            },
                            "surfaced": surfaced(root, texts) if baseline == "breadcrumbs" else [],
                            "git_log_mentions_fact": any(
                                oracle._has(git(root, "log", "--all", "--format=%s %b"), g)
                                for g in scenario["oracle"].get("must_deliver") or []
                            ),
                        }
                    )
    return {"scenarios_version": scenarios["version"], "hosts": hosts, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--hosts", nargs="+", default=["fresh", "this-repo"], choices=["fresh", "this-repo"]
    )
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    result = run(args.hosts)
    text = json.dumps(result, indent=1, sort_keys=True)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(
        f"{'scenario':18} {'host':10} {'baseline':12} facts@start facts@action ptr@start ptr@action stale tokens cmds bytes"
    )
    for r in result["rows"]:
        print(
            f"{r['scenario']:18} {r['host']:10} {r['baseline']:12} "
            f"{'yes' if r['by_start'] else 'no':11} {'yes' if r['at_action'] else 'no':12} "
            f"{'yes' if r['pointer_by_start'] else 'no':9} {'yes' if r['pointer_at_action'] else 'no':10} "
            f"{'YES' if r['stale_presented'] else 'no':5} {r['tokens_delivered']:6} "
            f"{r['capture_commands']:4} {r['memory_bytes_written']:6}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
