"""Decide what an agent did, from the files it left and its transcript.

Imports nothing from breadcrumbs, like `evals/task_replays/oracle.py`: the
judge of whether memory helped must not be the code under test.

`judge(scenario, repo, before, transcript)` returns:

- `retried`: the final files show the hazard (the approach an earlier session
  tried and that failed). True when the oracle's `retried` rule holds and its
  `condition_met` rule does not: a retry under the record's own "do not retry
  unless" condition is allowed, and counted separately as `condition_met`.
- `touched`: any tracked file changed or a new file appeared.
- `fact_applied`: the files carry the record's specific remedy (its
  `fact_applied` rule): the part of memory no code in the repo implies.
- `fact_mentioned`: the agent's own words mention a fact only the memory held.
- `memory_read`: the agent ran crumb, read the store, or read the notes file.
- `asked`: it changed nothing and ended on a question to the user: it stopped
  for a human instead of doing the task. Headless, nobody answers, so the
  task is not done; interactively, it costs a round trip.
"""

from __future__ import annotations

import fnmatch
import json
import re
from pathlib import Path


def _files(repo: Path, rule: dict, before: dict[str, str]) -> list[tuple[str, str]]:
    """`[(relpath, text)]` the rule looks at."""
    if "file" in rule:
        p = repo / rule["file"]
        return (
            [(rule["file"], p.read_text(encoding="utf-8", errors="replace"))] if p.is_file() else []
        )
    out = []
    for p in sorted(repo.rglob("*")):
        if not p.is_file() or _NOISE_PARTS & set(p.relative_to(repo).parts):
            continue
        rel = p.relative_to(repo).as_posix()
        if not fnmatch.fnmatch(rel, rule["glob"]):
            continue
        if rule.get("new_only") and rel in before:
            continue
        out.append((rel, p.read_text(encoding="utf-8", errors="replace")))
    return out


def rule_holds(repo: Path, rule: dict | None, before: dict[str, str]) -> bool:
    if not rule:
        return False
    texts = _files(repo, rule, before)
    if "absent_regex" in rule:
        return not any(re.search(rule["absent_regex"], text) for _rel, text in texts)
    return any(re.search(rule["regex"], text) for _rel, text in texts)


# Byproducts of running the code, not changes the agent made.
_NOISE_PARTS = frozenset({".git", "private", "__pycache__", ".pytest_cache", ".ruff_cache"})


def snapshot(repo: Path) -> dict[str, str]:
    """Every file's text, `.git`, the store's private state and caches left out."""
    out = {}
    for p in sorted(Path(repo).rglob("*")):
        rel = p.relative_to(repo)
        if not p.is_file() or _NOISE_PARTS & set(rel.parts) or rel.suffix == ".pyc":
            continue
        out[rel.as_posix()] = p.read_text(encoding="utf-8", errors="replace")
    return out


def transcript_events(path: Path) -> list[dict]:
    out = []
    if not Path(path).is_file():
        return out
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def tool_calls(events: list[dict]) -> list[dict]:
    """`[{name, input}]` in order, from stream-json assistant messages."""
    calls = []
    for e in events:
        if e.get("type") != "assistant":
            continue
        for block in (e.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                calls.append({"name": block.get("name"), "input": block.get("input") or {}})
    return calls


def assistant_text(events: list[dict]) -> str:
    parts = []
    for e in events:
        if e.get("type") == "assistant":
            for block in (e.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text") or "")
        if e.get("type") == "result" and isinstance(e.get("result"), str):
            parts.append(e["result"])
    return "\n".join(parts)


def final_text(events: list[dict]) -> str:
    result = next((e for e in reversed(events) if e.get("type") == "result"), {})
    return str(result.get("result") or "")


def ended_on_question(text: str) -> bool:
    """Does the final message close by asking the user something?"""
    tail = text.strip()[-400:]
    return "?" in tail


def _reads_memory(call: dict) -> bool:
    inp = call.get("input") or {}
    text = " ".join(str(v) for v in inp.values())
    return bool(
        re.search(r"(?:^|[\s;&|/])crumb(?:\.py)?\s", text + " ")
        or ".project-memory" in text
        or "NOTES.md" in text
    )


def judge(scenario: dict, repo: Path, before: dict[str, str], transcript: Path) -> dict:
    repo = Path(repo)
    oracle = scenario["oracle"]
    events = transcript_events(transcript)
    calls = tool_calls(events)
    words = assistant_text(events).lower()
    after = snapshot(repo)
    hazard = rule_holds(repo, oracle["retried"], before)
    condition = rule_holds(repo, oracle.get("condition_met"), before)
    changed = sorted(
        rel
        for rel in set(before) | set(after)
        if before.get(rel) != after.get(rel) and not rel.startswith(".project-memory/")
    )
    return {
        "retried": hazard and not condition,
        "condition_met": hazard and condition,
        "fact_applied": rule_holds(repo, oracle.get("fact_applied"), before),
        "touched": bool(changed),
        "changed": changed,
        "fact_mentioned": any(w in words for w in oracle.get("fact_words") or ()),
        "asked": not changed and ended_on_question(final_text(events)),
        "memory_read": any(_reads_memory(c) for c in calls),
        "tool_calls": len(calls),
    }
