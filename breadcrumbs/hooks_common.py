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
| `miner/<session>.json` | `PreCompact`, `Stop`, `SubagentStop` | themselves | the transcript byte cursor, calls awaiting results, the candidate backlog (audit WP09) |
| `miner/acked.json` | the same | the same | transcript events already turned into jots, across sessions |
| `session-state.json` | `UserPromptSubmit` | `SessionStart` after a compaction | the last prompt and what memory was surfaced for it |
| `compaction-marker.json` | `PreCompact` | `SessionStart` after a compaction | when the context was destroyed and what was salvaged |
| `extraction-asked.json` | `Stop` | itself | jot ids already offered for promotion |

**Every function here is best-effort.** A hook that cannot read its own state
must behave as though the state were empty; a hook that cannot write it loses at
most one deduplication. Neither may ever raise: a hook that fails takes the
user's tool call or turn with it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from breadcrumbs import cli

# Per-session state files, all under `private/`.
GUARD_SEEN_FILENAME = "hook-guard-seen.json"
# The entry-count cursor before audit WP09. Never read now; left on disk.
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


def write_state(
    memory_dir: Path, filename: str, sessions: dict, current: str | None = None
) -> None:
    """Replace the map, keeping only the most recently updated sessions.

    `current`, the session being written, is always kept. `updated_at` has
    one-second resolution, and on a tie the sort kept dict order, so a new
    session written in the same second as eight others was the one dropped,
    and its dedupe record was lost at once. The delivery evals (audit WP18)
    found it.

    Best-effort: a failure here costs one deduplication, never a hook.
    """
    try:
        others = sorted(
            (s for s in sessions if s != current),
            key=lambda s: str((sessions.get(s) or {}).get("updated_at") or ""),
            reverse=True,
        )
        keep = ([current] if current in sessions else []) + others
        keep = keep[:MAX_SESSIONS]
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
    write_state(memory_dir, filename, sessions, current=session_id)
    return False


# --------------------------------------------------------------------------- #
# The miner's state (audit F02, WP09)
# --------------------------------------------------------------------------- #
#
# The old cursor counted *entries* of an 8 MB tail and stored the count as if it
# were a position in the file. Once the file outgrew the tail, the count stopped
# moving and new entries were never mined. `miner-cursor.json` is no longer
# read; its successor is one file per session, so two sessions' hooks never
# rewrite each other's state, written under the store lock by
# `transcript.ingest`.

MINER_DIRNAME = "miner"
MINER_ACKED_FILENAME = "acked.json"
MINER_STATE_VERSION = 2
# Session files kept (most recently updated first). A session pruned from here
# starts again at byte 0; the acknowledged-event ledger keeps that from
# writing anything twice.
MINER_MAX_SESSIONS = 32
# Event ids remembered as acknowledged, newest kept.
MINER_MAX_ACKED = 5000


def _miner_dir(memory_dir: Path) -> Path:
    return Path(memory_dir) / "private" / MINER_DIRNAME


def miner_state_path(memory_dir: Path, session_id: str) -> Path:
    digest = hashlib.sha1(str(session_id).encode("utf-8")).hexdigest()[:16]
    return _miner_dir(memory_dir) / f"{digest}.json"


def load_miner_state(memory_dir: Path, session_id: str) -> dict:
    """This session's miner state, or a fresh one. Never raises."""
    fresh = {"version": MINER_STATE_VERSION, "session": session_id, "offset": 0}
    try:
        data = json.loads(miner_state_path(memory_dir, session_id).read_text(encoding="utf-8"))
    except Exception:
        return fresh
    if not isinstance(data, dict) or data.get("version") != MINER_STATE_VERSION:
        return fresh
    return data


def save_miner_state(memory_dir: Path, session_id: str, state: dict) -> None:
    """Write this session's state atomically. Raises on failure: the caller must
    know whether its progress is durable before it acts on it."""
    path = miner_state_path(memory_dir, session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {**state, "version": MINER_STATE_VERSION, "session": session_id}
    state["updated_at"] = cli.now_iso()
    cli.write_text_atomic(path, json.dumps(state, sort_keys=True) + "\n")
    _prune_miner_states(memory_dir)


def _prune_miner_states(memory_dir: Path) -> None:
    try:
        files = [p for p in _miner_dir(memory_dir).glob("*.json") if p.name != MINER_ACKED_FILENAME]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for old in files[MINER_MAX_SESSIONS:]:
            old.unlink()
    except OSError:  # pragma: no cover - pruning is housekeeping
        pass


def miner_states(memory_dir: Path) -> list[dict]:
    """Every session's miner state, for `doctor`. Never raises."""
    out = []
    try:
        paths = sorted(_miner_dir(memory_dir).glob("*.json"))
    except OSError:
        return out
    for p in paths:
        if p.name == MINER_ACKED_FILENAME:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and data.get("version") == MINER_STATE_VERSION:
            out.append(data)
    return out


def load_acked(memory_dir: Path) -> list[str]:
    try:
        data = json.loads((_miner_dir(memory_dir) / MINER_ACKED_FILENAME).read_text("utf-8"))
    except Exception:
        return []
    events = data.get("events") if isinstance(data, dict) else None
    return [str(e) for e in events] if isinstance(events, list) else []


def save_acked(memory_dir: Path, events: list[str]) -> None:
    path = _miner_dir(memory_dir) / MINER_ACKED_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text_atomic(
        path, json.dumps({"events": events[-MINER_MAX_ACKED:]}, sort_keys=True) + "\n"
    )


def miner_cursor(memory_dir: Path, session_id: str) -> int:
    """How many bytes of this session's transcript have been consumed."""
    try:
        return max(0, int(load_miner_state(memory_dir, session_id).get("offset") or 0))
    except (TypeError, ValueError):
        return 0


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
    write_state(memory_dir, SESSION_STATE_FILENAME, sessions, current=session_id)


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
    write_state(memory_dir, COMPACTION_MARKER_FILENAME, sessions, current=session_id)


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
    write_state(memory_dir, EXTRACTION_ASKED_FILENAME, sessions, current=session_id)
