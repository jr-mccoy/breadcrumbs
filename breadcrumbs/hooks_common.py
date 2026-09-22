"""breadcrumbs — state shared by the hook handlers (Phase 1).

Every hook that remembers something between firings keeps it here, in
`private/`: machine-local runtime state, never committed, never a record. A
hook's memory of what it already said is not project memory — it is a detail of
this checkout on this machine, and committing it would make two developers'
sessions interfere.

Four things live in this shape, all keyed by the harness `session_id` and all
bounded to the most recent `_MAX_SESSIONS` sessions so no file grows without
limit:

| File | Written by | Read by | Holds |
|---|---|---|---|
| `hook-guard-seen.json` | `PreToolUse` guard, `UserPromptSubmit` | themselves | advisory keys already shown, so a repeat says nothing |
| `miner-cursor.json` | `PreCompact`, `Stop` | themselves | how much of the transcript has already been mined |
| `session-state.json` | `UserPromptSubmit` | `SessionStart` after a compaction | the last prompt and what memory was surfaced for it |
| `compaction-marker.json` | `PreCompact` | `SessionStart` after a compaction | when the context was destroyed and what was salvaged |
| `extraction-asked.json` | `Stop` | itself | jot ids already offered for promotion |

**Every function here is best-effort.** A hook that cannot read its own state
must behave as though the state were empty; a hook that cannot write it loses at
most one deduplication. Neither may ever raise: a hook that fails takes the
user's tool call or turn with it.
"""

from __future__ import annotations

import json
from pathlib import Path

from breadcrumbs import cli

# Per-session state files, all under `private/`.
GUARD_SEEN_FILENAME = "hook-guard-seen.json"
MINER_CURSOR_FILENAME = "miner-cursor.json"
SESSION_STATE_FILENAME = "session-state.json"
COMPACTION_MARKER_FILENAME = "compaction-marker.json"
EXTRACTION_ASKED_FILENAME = "extraction-asked.json"

# How many sessions of history each file keeps. Eight is well past the number a
# person has open at once and small enough that the files stay a single read.
MAX_SESSIONS = 8

# Cap on the keys one session may accumulate in a list-valued entry.
MAX_KEYS_PER_SESSION = 200

UNKNOWN_SESSION = "unknown"


def private_path(memory_dir: Path, filename: str) -> Path:
    return Path(memory_dir) / "private" / filename


def read_state(memory_dir: Path, filename: str) -> dict:
    """The `{session_id: entry}` map in `filename`, or `{}`. Never raises."""
    try:
        data = json.loads(private_path(memory_dir, filename).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    sessions = data.get("sessions")
    return sessions if isinstance(sessions, dict) else {}


def write_state(memory_dir: Path, filename: str, sessions: dict) -> None:
    """Replace the map, keeping only the most recently updated sessions.

    Best-effort: a failure here costs one deduplication, never a hook.
    """
    try:
        keep = sorted(
            sessions,
            key=lambda s: str((sessions.get(s) or {}).get("updated_at") or ""),
            reverse=True,
        )[:MAX_SESSIONS]
        path = private_path(memory_dir, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        cli.write_text_atomic(
            path,
            json.dumps({"sessions": {s: sessions[s] for s in keep}}, indent=0, sort_keys=True)
            + "\n",
        )
    except Exception:  # pragma: no cover - hook state is best-effort
        pass


def session_id_of(payload: dict) -> str:
    """The harness session id, or a stable stand-in.

    A missing id must not make every firing look like a new session — that would
    turn every dedupe into a no-op — so one bucket absorbs them all.
    """
    return str(payload.get("session_id") or "").strip() or UNKNOWN_SESSION


# --------------------------------------------------------------------------- #
# "Have I already said this?"
# --------------------------------------------------------------------------- #


def advisory_seen(
    memory_dir: Path, session_id: str, key: str, *, filename: str | None = None
) -> bool:
    """True if `key` already fired for this session; records it if not.

    Same records, same target ⇒ say nothing after the first time. An advisory
    that repeats verbatim on every tool call is one the agent learns to skim,
    and then it skims the one that mattered.
    """
    filename = filename or GUARD_SEEN_FILENAME
    sessions = read_state(memory_dir, filename)
    entry = sessions.get(session_id)
    if not isinstance(entry, dict) or not isinstance(entry.get("seen"), list):
        entry = {"seen": []}
    if key in entry["seen"]:
        return True
    entry["seen"] = (entry["seen"] + [key])[-MAX_KEYS_PER_SESSION:]
    entry["updated_at"] = cli.now_iso()
    sessions[session_id] = entry
    write_state(memory_dir, filename, sessions)
    return False


# --------------------------------------------------------------------------- #
# The miner cursor
# --------------------------------------------------------------------------- #


def miner_cursor(memory_dir: Path, session_id: str) -> int:
    """How many transcript entries of this session have already been mined."""
    entry = read_state(memory_dir, MINER_CURSOR_FILENAME).get(session_id)
    if not isinstance(entry, dict):
        return 0
    try:
        return max(0, int(entry.get("index", 0)))
    except (TypeError, ValueError):
        return 0


def set_miner_cursor(memory_dir: Path, session_id: str, index: int) -> None:
    """Advance the cursor past the entries actually read.

    Never moves backwards: the transcript is append-only, and a shorter read
    (the tail-only path for a very large file) must not cause the next firing to
    re-mine everything it already saw.
    """
    sessions = read_state(memory_dir, MINER_CURSOR_FILENAME)
    current = miner_cursor(memory_dir, session_id)
    sessions[session_id] = {
        "index": max(current, int(index)),
        "updated_at": cli.now_iso(),
    }
    write_state(memory_dir, MINER_CURSOR_FILENAME, sessions)


# --------------------------------------------------------------------------- #
# Session state (what the prompt hook saw) and the compaction marker
# --------------------------------------------------------------------------- #

# How much of the prompt is kept. Enough to recognise the task after a
# compaction; not enough to be a transcript.
SESSION_PROMPT_CHARS = 300


def record_prompt_state(
    memory_dir: Path, session_id: str, prompt: str, matched_ids: list[str]
) -> None:
    sessions = read_state(memory_dir, SESSION_STATE_FILENAME)
    sessions[session_id] = {
        "last_prompt": " ".join(str(prompt or "").split())[:SESSION_PROMPT_CHARS],
        "matched": list(matched_ids or []),
        "at": cli.now_iso(),
        "updated_at": cli.now_iso(),
    }
    write_state(memory_dir, SESSION_STATE_FILENAME, sessions)


def prompt_state(memory_dir: Path, session_id: str) -> dict:
    entry = read_state(memory_dir, SESSION_STATE_FILENAME).get(session_id)
    return entry if isinstance(entry, dict) else {}


def record_compaction(
    memory_dir: Path, session_id: str, *, trigger: str | None, commit: str, jots: list[str]
) -> None:
    sessions = read_state(memory_dir, COMPACTION_MARKER_FILENAME)
    sessions[session_id] = {
        "at": cli.now_iso(),
        "updated_at": cli.now_iso(),
        "trigger": trigger or "unknown",
        "commit": commit,
        "jots": list(jots or []),
    }
    write_state(memory_dir, COMPACTION_MARKER_FILENAME, sessions)


def compaction_marker(memory_dir: Path, session_id: str) -> dict:
    entry = read_state(memory_dir, COMPACTION_MARKER_FILENAME).get(session_id)
    return entry if isinstance(entry, dict) else {}


# --------------------------------------------------------------------------- #
# Which jots the Stop hook has already offered
# --------------------------------------------------------------------------- #


def extraction_asked(memory_dir: Path, session_id: str) -> set[str]:
    entry = read_state(memory_dir, EXTRACTION_ASKED_FILENAME).get(session_id)
    if not isinstance(entry, dict) or not isinstance(entry.get("jots"), list):
        return set()
    return {str(j) for j in entry["jots"]}


def record_extraction_asked(memory_dir: Path, session_id: str, jot_ids: list[str]) -> None:
    """Remember that these jots were offered, so a later turn does not re-ask.

    An agent that declined to promote a candidate has answered; asking again
    every turn until it expires is the fatigue this tool exists to avoid.
    """
    sessions = read_state(memory_dir, EXTRACTION_ASKED_FILENAME)
    known = extraction_asked(memory_dir, session_id) | {str(j) for j in jot_ids or []}
    sessions[session_id] = {
        "jots": sorted(known)[-MAX_KEYS_PER_SESSION:],
        "updated_at": cli.now_iso(),
    }
    write_state(memory_dir, EXTRACTION_ASKED_FILENAME, sessions)
