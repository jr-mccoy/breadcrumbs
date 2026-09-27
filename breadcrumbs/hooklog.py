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

Bounded to about `HOOK_LOG_MAX_LINES`, by rotation (audit WP12). When the
current file reaches half the bound it is renamed to `hook-log.1.jsonl`,
replacing the previous one, and readers read both. Every line is one append to
whichever file is current; nothing rewrites a file other processes append to,
so parallel hooks cannot drop each other's lines. A hook whose file was renamed
under it lands its line in `hook-log.1.jsonl`, which is still read. Rotation
takes `private/.hook-log.lock` without waiting, and re-checks the size once it
holds it, so two hooks never rotate the same file twice. Lines leave the log
only by retention: the oldest, a rotated file at a time. Best-effort
throughout: logging never fails, slows or changes a hook.
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
from breadcrumbs import path_policy

HOOK_LOG_FILENAME = "hook-log.jsonl"
HOOK_LOG_ROTATED_FILENAME = "hook-log.1.jsonl"
HOOK_LOG_LOCK_FILENAME = ".hook-log.lock"
HOOK_LOG_MAX_LINES = 5000
# Before audit WP12 the log was cut back to this many lines by rewriting it,
# which could drop lines a parallel hook appended meanwhile. Rotation replaced
# it; kept for importers.
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


def rotated_path(memory_dir: Path) -> Path:
    return Path(memory_dir) / "private" / HOOK_LOG_ROTATED_FILENAME


def _rotate_at() -> int:
    """Lines the current file may hold before it is rotated."""
    return max(1, HOOK_LOG_MAX_LINES // 2)


def append(memory_dir: Path, entry: dict) -> None:
    """Append one line, then rotate if the file holds half the bound. Never raises."""
    try:
        path = log_path(memory_dir)
        if not path.parent.is_dir():
            return  # no store here, or not one this hook should create
        line = json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n"
        # One write of the whole line to a file opened for appending, so the
        # line lands whole at the end whatever else is appending.
        # Never through a link (audit F17): the log is store content.
        fd = path_policy.open_file(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT)
        with os.fdopen(fd, "ab") as fh:
            fh.write(line.encode("utf-8"))
        if path.stat().st_size >= _rotate_at() * _MIN_LINE_BYTES:
            _rotate(memory_dir, path)
    except Exception:  # pragma: no cover - logging never breaks a hook
        pass


def _rotate(memory_dir: Path, path: Path) -> None:
    from breadcrumbs import lock as _lock

    with _lock.side_lock(path.parent / HOOK_LOG_LOCK_FILENAME, timeout=0.0) as state:
        if state == _lock.BUSY:
            return  # another hook is rotating; the next append looks again
        # Re-checked under the lock: whoever rotated first left a short file.
        if path_policy.read_bytes(path).count(b"\n") < _rotate_at():
            return
        os.replace(path, rotated_path(memory_dir))


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
    """Every parseable line, oldest first (the rotated file, then the current
    one). A bad line is skipped, not fatal."""
    text = ""
    for path in (rotated_path(memory_dir), log_path(memory_dir)):
        try:
            text += path_policy.read_text(path)
        except OSError:
            continue
        if text and not text.endswith("\n"):
            text += "\n"
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
