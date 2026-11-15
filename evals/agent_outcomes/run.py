"""Agent-outcome eval: does memory stop an agent repeating a failed approach?

Review 2026-11-13, §5.1 (the v2 design's E2, run against v1 as it is). The
continuity replays (`evals/task_replays/`) measure what memory *delivers*;
this runs a real agent and measures what it *does*.

For each scenario in `scenarios.json` (a small repo, a task, and an approach
an earlier session tried and that failed), under each condition:

- `none`: no memory. `CLAUDE.md` says only "see README".
- `notes`: a hand-kept notes list in `CLAUDE.md`, which Claude Code loads at
  start: the failed approach as one line, beside five unrelated notes.
- `crumb-instructions`: a breadcrumbs store holding the same facts as
  records, and the `CLAUDE.md` signpost `crumb init --with-adapter` writes.
  No hooks: the agent has to choose to run `crumb`.
- `crumb-hooks`: the same plus `crumb init --with-hooks`: the resume packet
  at session start, guard warnings before tool calls.

it builds a fresh repo, runs `claude -p` headless in it, and judges the final
files with `oracle.py`. The agent runs isolated: an empty `HOME`, project
settings only, no MCP servers, `bypassPermissions` (so a guard warning reaches
the agent as context, the way it does in a permissive session, rather than
becoming a headless denial).

    python evals/agent_outcomes/run.py --dry-run          # build the repos only
    python evals/agent_outcomes/run.py --repeats 3 --jobs 4 --out results.json

Each run costs model usage; `--dry-run` and the offline tests cost nothing.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent


def _load_oracle():
    """`oracle.py` beside this file, under its own module name: the task-replay
    harness has an `oracle` module too, and a bare `import oracle` got
    whichever was imported first."""
    spec = importlib.util.spec_from_file_location("agent_outcomes_oracle", HERE / "oracle.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


oracle = _load_oracle()

CONDITIONS = ("none", "notes", "crumb-instructions", "crumb-hooks")
BASE_CLAUDE_MD = "# Project\n\nSee README.md for what this is and how to run it.\n"


def load_scenarios(path: Path = HERE / "scenarios.json") -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def crumb_bin(workdir: Path) -> Path:
    """A directory holding a `crumb` that runs this checkout's code."""
    bin_dir = Path(workdir) / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "crumb"
    script.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{REPO_ROOT / "crumb.py"}" "$@"\n', encoding="utf-8"
    )
    script.chmod(0o755)
    return bin_dir


def _crumb(repo: Path, bin_dir: Path, *args: str) -> None:
    subprocess.run(
        [str(bin_dir / "crumb"), "--project", str(repo), *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def build(
    scenario: dict, distractors: list[dict], condition: str, repo: Path, bin_dir: Path
) -> None:
    """A fresh repo for one run: the project, committed, then its memory, committed."""
    if repo.exists():
        shutil.rmtree(repo)
    repo.mkdir(parents=True)
    for rel, text in scenario["files"].items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "eval@example.invalid")
    _git(repo, "config", "user.name", "eval")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "project")

    claude_md = BASE_CLAUDE_MD
    if condition == "notes":
        lines = [f"- {scenario['hazard']['note']}"] + [f"- {d['note']}" for d in distractors]
        claude_md += "\n## Project notes (kept by hand, newest first)\n\n" + "\n".join(lines) + "\n"
    (repo / "CLAUDE.md").write_text(claude_md, encoding="utf-8")

    if condition.startswith("crumb"):
        flags = ["--with-adapter"] + (["--with-hooks"] if condition == "crumb-hooks" else [])
        _crumb(repo, bin_dir, "init", *flags)
        for d in distractors:
            _crumb(
                repo, bin_dir, "remember", "decision", "--title", d["title"],
                "--set", "Decision", d["decision"], "--set", "Rationale", d["note"],
                "--evidence", "file", "README.md",
            )  # fmt: skip
        h = scenario["hazard"]
        args = [
            "remember", "attempt", "--title", h["title"], "--problem", h["problem"],
            "--tried", h["tried"], "--result", h["result"], "--why", h["why"],
            "--do-not-retry", h["do_not_retry"], "--tags", ",".join(h["tags"]),
        ]  # fmt: skip
        for f in h["files"]:
            args += ["--evidence", "file", f]
        _crumb(repo, bin_dir, *args)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "memory")


def delivered_at_start(repo: Path, condition: str, bin_dir: Path) -> int:
    """Characters of memory in the agent's context before its first action."""
    if condition == "notes":
        text = (repo / "CLAUDE.md").read_text(encoding="utf-8")
        return len(text) - len(BASE_CLAUDE_MD)
    if condition != "crumb-hooks":
        return 0
    payload = json.dumps({"cwd": str(repo), "session_id": "measure", "source": "startup"})
    out = subprocess.run(
        [str(bin_dir / "crumb"), "hook", "session"],
        cwd=repo,
        input=payload,
        capture_output=True,
        text=True,
    ).stdout
    try:
        return len(json.loads(out)["hookSpecificOutput"]["additionalContext"])
    except (ValueError, KeyError):
        return 0


def hook_counts(repo: Path) -> dict:
    """What the hooks did during the run, from the store's hook log."""
    log = repo / ".project-memory" / "private" / "hook-log.jsonl"
    counts = {"session_context": 0, "guard_warnings": 0, "guard_asks": 0}
    if not log.is_file():
        return counts
    for line in log.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("session") == "measure":
            continue
        if d.get("event") == "session" and d.get("outcome") == "context":
            counts["session_context"] += 1
        elif d.get("event") == "guard" and d.get("outcome") == "context":
            counts["guard_warnings"] += 1
        elif d.get("event") == "guard" and d.get("outcome") == "ask":
            counts["guard_asks"] += 1
    return counts


def run_one(job: dict) -> dict:
    scenario, condition, rep = job["scenario"], job["condition"], job["rep"]
    run_dir = Path(job["out_dir"]) / f"{scenario['id']}--{condition}--{rep}"
    repo, home = run_dir / "repo", run_dir / "home"
    if home.exists():
        shutil.rmtree(home)
    home.mkdir(parents=True)
    bin_dir = Path(job["bin_dir"])
    build(scenario, job["distractors"], condition, repo, bin_dir)
    delivered = delivered_at_start(repo, condition, bin_dir)
    before = oracle.snapshot(repo)
    row = {
        "scenario": scenario["id"],
        "condition": condition,
        "rep": rep,
        "model": job["model"],
        "delivered_chars_at_start": delivered,
    }
    if job["dry_run"]:
        return row
    transcript = run_dir / "transcript.jsonl"
    env = dict(
        os.environ, HOME=str(home), PATH=f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"
    )
    for key in ("CLAUDE_PROJECT_DIR", "BREADCRUMBS_PROJECT"):
        env.pop(key, None)
    cmd = [
        job["claude"], "-p", scenario["task"], "--model", job["model"],
        "--setting-sources", "project", "--strict-mcp-config",
        "--permission-mode", "bypassPermissions",
        "--output-format", "stream-json", "--verbose",
        "--max-turns", str(job["max_turns"]), "--no-session-persistence",
    ]  # fmt: skip
    started = time.time()
    with transcript.open("w", encoding="utf-8") as out, (run_dir / "stderr.txt").open("w") as err:
        try:
            subprocess.run(cmd, cwd=repo, env=env, stdout=out, stderr=err, timeout=job["timeout"])
            row["timed_out"] = False
        except subprocess.TimeoutExpired:
            row["timed_out"] = True
    row["wall_s"] = round(time.time() - started, 1)
    result = next(
        (e for e in reversed(oracle.transcript_events(transcript)) if e.get("type") == "result"),
        {},
    )
    row.update(
        {
            "status": result.get("subtype"),
            "turns": result.get("num_turns"),
            "cost_usd": result.get("total_cost_usd"),
            **oracle.judge(scenario, repo, before, transcript),
            **hook_counts(repo),
        }
    )
    return row


def summarize(rows: list[dict]) -> list[dict]:
    """One line per condition (and per scenario), as counts over runs."""
    out = []
    keys = sorted({(r["scenario"], r["condition"]) for r in rows}) + sorted(
        {("ALL", r["condition"]) for r in rows}
    )
    for scenario, condition in keys:
        sel = [
            r for r in rows
            if r["condition"] == condition and (scenario == "ALL" or r["scenario"] == scenario)
        ]  # fmt: skip
        done = [r for r in sel if "retried" in r]
        out.append(
            {
                "scenario": scenario,
                "condition": condition,
                "runs": len(done),
                "retried": sum(r["retried"] for r in done),
                "condition_met": sum(r["condition_met"] for r in done),
                "fact_applied": sum(r["fact_applied"] for r in done),
                "done": sum(r["touched"] for r in done),
                "asked": sum(r.get("asked", False) for r in done),
                "fact_mentioned": sum(r["fact_mentioned"] for r in done),
                "memory_read": sum(r["memory_read"] for r in done),
                "delivered_chars_at_start": round(
                    sum(r["delivered_chars_at_start"] for r in sel) / max(len(sel), 1)
                ),
                "cost_usd": round(sum(r.get("cost_usd") or 0 for r in done), 2),
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", default="claude-sonnet-5-5")
    ap.add_argument("--repeats", type=int, default=2)
    ap.add_argument("--conditions", default=",".join(CONDITIONS))
    ap.add_argument("--scenarios", default="", help="comma-separated ids (default: all)")
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--max-turns", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=900, help="seconds per run")
    ap.add_argument("--workdir", default="", help="where repos and transcripts go")
    ap.add_argument("--out", default="", help="write rows and summary as JSON here")
    ap.add_argument("--dry-run", action="store_true", help="build the repos; run no agent")
    ap.add_argument("--claude", default=shutil.which("claude") or "claude")
    args = ap.parse_args(argv)

    data = load_scenarios()
    wanted = {s for s in args.scenarios.split(",") if s}
    scenarios = [s for s in data["scenarios"] if not wanted or s["id"] in wanted]
    conditions = [c for c in args.conditions.split(",") if c]
    unknown = set(conditions) - set(CONDITIONS)
    if unknown:
        ap.error(f"unknown condition(s): {', '.join(sorted(unknown))}")
    workdir = Path(args.workdir or Path.cwd() / "agent-outcomes-work").resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    bin_dir = crumb_bin(workdir)
    jobs = [
        {
            "scenario": s,
            "condition": c,
            "rep": rep,
            "distractors": data["distractors"],
            "out_dir": str(workdir / "runs"),
            "bin_dir": str(bin_dir),
            "model": args.model,
            "max_turns": args.max_turns,
            "timeout": args.timeout,
            "dry_run": args.dry_run,
            "claude": args.claude,
        }  # fmt: skip
        for rep in range(1, args.repeats + 1)
        for s in scenarios
        for c in conditions
    ]
    rows = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        for row in pool.map(run_one, jobs):
            rows.append(row)
            print(json.dumps({k: row.get(k) for k in (
                "scenario", "condition", "rep", "retried", "condition_met", "fact_applied",
                "fact_mentioned", "memory_read", "status", "cost_usd",
            )}), flush=True)  # fmt: skip
    summary = summarize(rows)
    report = {
        "model": args.model,
        "scenarios_version": data["version"],
        "rows": rows,
        "summary": summary,
    }
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for line in summary:
        print(json.dumps(line))
    return 0


if __name__ == "__main__":
    sys.exit(main())
