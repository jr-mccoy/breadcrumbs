"""breadcrumbs — one line per hook firing (WM-62).

The field test (`docs/field-test.md`) asks what the hooks actually cost and do
in a real session: how often each fires, how long it takes, how often it spends
the agent's context, how often the Stop hook asks for an extraction turn, how
often a writer skipped because a parallel session held the store lock. Usage
telemetry (`usage.py`) answers "which records were shown"; this answers "what
did each hook do".

`private/hook-log.jsonl`, gitignored like everything under `private/`. One JSON
object per firing: `{event, at, ms, outcome}` plus the session id and whatever
the handler noted (guard's verdict and tool name, how many records the prompt
hook matched, how many jots a transcript mine wrote).

**Never the content.** No prompt, command, file path or transcript text is
logged, only counts and verdicts, so the log can be shared to report a field
test without review.

`outcome` is read off the JSON the hook printed, so it describes what the host
received: `silent` (`{}`), `context` (additionalContext injected), `ask` (a
permission prompt), `block` (the Stop hook's extraction turn), or `locked` (a
writing hook skipped because another writer held the store).

Bounded to `HOOK_LOG_MAX_LINES`. When it grows past that it is cut back to
`HOOK_LOG_TRIM_TO`, so a busy session does not rewrite the file on every tool
call. Best-effort throughout: logging never fails, slows or changes a hook.
Two hooks trimming at the same moment can drop a few lines, which is acceptable
for a log that only counts.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable

HOOK_LOG_FILENAME = "hook-log.jsonl"
HOOK_LOG_MAX_LINES = 5000
HOOK_LOG_TRIM_TO = 4000
# A line is at least this long, so a file under MAX_LINES * this cannot be over
# the bound and needs no counting.
_MIN_LINE_BYTES = 48

# Detail the running handler adds to its own line. One hook runs per process,
# and `run_logged` clears it around each run.
_notes: dict = {}


def log_path(memory_dir: Path) -> Path:
    return Path(memory_dir) / "private" / HOOK_LOG_FILENAME


def note(**fields) -> None:
    """Add detail to the current hook's log line (a verdict, a count)."""
    _notes.update({k: v for k, v in fields.items() if v is not None})


def outcome_of(output: str) -> str:
    """What the host received, from the JSON a hook printed."""
    try:
        doc = json.loads(output.strip() or "{}")
    except ValueError:
        return "unparsed"
    if not isinstance(doc, dict) or not doc:
        return "silent"
    if doc.get("decision") == "block":
        return "block"
    specific = doc.get("hookSpecificOutput") or {}
    if isinstance(specific, dict):
        if specific.get("permissionDecision") == "ask":
            return "ask"
        if specific.get("additionalContext"):
            return "context"
    return "other"


def append(memory_dir: Path, entry: dict) -> None:
    """Append one line, then trim if the log is over its bound. Never raises."""
    try:
        path = log_path(memory_dir)
        if not path.parent.is_dir():
            return  # no store here, or not one this hook should create
        line = json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
        if path.stat().st_size > HOOK_LOG_MAX_LINES * _MIN_LINE_BYTES:
            _trim(path)
    except Exception:  # pragma: no cover - logging never breaks a hook
        pass


def _trim(path: Path) -> None:
    raw = path.read_bytes()
    if raw.count(b"\n") <= HOOK_LOG_MAX_LINES:
        return
    keep = raw.splitlines(keepends=True)[-HOOK_LOG_TRIM_TO:]
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(b"".join(keep))
    os.replace(tmp, path)


def run_logged(
    event: str, memory_dir: Path, payload: dict, handler: Callable[[], int], now_iso
) -> int:
    """Run a hook handler, pass its output through untouched, and log one line.

    The handler's stdout is captured so its outcome can be read, then written
    out exactly as printed, even when the handler raises.
    """
    _notes.clear()
    buf = io.StringIO()
    started = time.perf_counter()
    try:
        with contextlib.redirect_stdout(buf):
            code = handler()
    finally:
        sys.stdout.write(buf.getvalue())
        sys.stdout.flush()
    ms = round((time.perf_counter() - started) * 1000, 1)
    try:
        entry = {
            "event": event,
            "at": now_iso(),
            "ms": ms,
            "outcome": _notes.pop("outcome", None) or outcome_of(buf.getvalue()),
        }
        session = payload.get("session_id") if isinstance(payload, dict) else None
        if session:
            entry["session"] = str(session)
        entry.update(_notes)
        append(memory_dir, entry)
    except Exception:  # pragma: no cover
        pass
    finally:
        _notes.clear()
    return code


def read_log(memory_dir: Path) -> list[dict]:
    """Every parseable line, oldest first. A bad line is skipped, not fatal."""
    try:
        text = log_path(memory_dir).read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("event"):
            out.append(entry)
    return out


_BASE_KEYS = frozenset({"event", "at", "ms", "outcome", "session", "verdict"})


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1))))
    return ordered[index]


def summarize(entries: list[dict]) -> dict:
    """What `crumb doctor --hook-log` prints: per-event counts, outcomes, timings."""
    events: dict[str, dict] = {}
    sessions: set[str] = set()
    for e in entries:
        ev = events.setdefault(
            e["event"], {"count": 0, "outcomes": {}, "ms": [], "verdicts": {}, "counts": {}}
        )
        ev["count"] += 1
        outcome = str(e.get("outcome") or "unknown")
        ev["outcomes"][outcome] = ev["outcomes"].get(outcome, 0) + 1
        if isinstance(e.get("ms"), (int, float)):
            ev["ms"].append(float(e["ms"]))
        if e.get("verdict"):
            v = str(e["verdict"])
            ev["verdicts"][v] = ev["verdicts"].get(v, 0) + 1
        # Handler detail: numbers are summed (`mined`, `matches`, `offered`),
        # flags are counted (`snapshot`, `deduped`, `correction`), and a
        # string detail is tallied by value (`skipped: prefilter`).
        for key, val in e.items():
            if key in _BASE_KEYS:
                continue
            if isinstance(val, bool):
                if val:
                    ev["counts"][key] = ev["counts"].get(key, 0) + 1
            elif isinstance(val, int):
                ev["counts"][key] = ev["counts"].get(key, 0) + val
            elif isinstance(val, str) and key != "tool":
                name = f"{key}: {val}"
                ev["counts"][name] = ev["counts"].get(name, 0) + 1
        if e.get("session"):
            sessions.add(str(e["session"]))
    report = {}
    for name, ev in sorted(events.items()):
        ms = ev.pop("ms")
        ev["ms_p50"] = _percentile(ms, 50)
        ev["ms_p95"] = _percentile(ms, 95)
        ev["ms_max"] = max(ms) if ms else None
        spoke = sum(n for o, n in ev["outcomes"].items() if o in ("context", "ask", "block"))
        ev["spoke_rate"] = round(spoke / ev["count"], 3) if ev["count"] else None
        if not ev["verdicts"]:
            ev.pop("verdicts")
        report[name] = ev
    stamps = [str(e["at"]) for e in entries if e.get("at")]
    return {
        "entries": len(entries),
        "first_at": min(stamps) if stamps else None,
        "last_at": max(stamps) if stamps else None,
        "sessions": len(sessions),
        "events": report,
        "locked": sum(1 for e in entries if e.get("outcome") == "locked"),
    }
