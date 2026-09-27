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
| `session-state.json` | `UserPromptSubmit` | `SessionStart` after a compaction | the latest substantive task, and apart from it the latest lookup: what it selected and emitted, and for which prompt (audit WP12) |
| `compaction-marker.json` | `PreCompact` | `SessionStart` after a compaction | when the context was destroyed and what was salvaged |
| `extraction-asked.json` | `Stop` | itself | jot ids already offered for promotion |

**Every function here is best-effort.** A hook that cannot read its own state
must behave as though the state were empty; a hook that cannot write it loses at
most one deduplication. Neither may ever raise: a hook that fails takes the
user's tool call or turn with it.

**Updates are locked per file (audit WP12).** The shared files are rewritten
whole, so two sessions updating one at the same moment could each drop the
other's entry. `update_state` takes the file's side lock for its read and write;
if another process holds it past `lock.SIDE_TIMEOUT`, the update is skipped and
`state_dropped` noted in the hook log.
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


def update_state(memory_dir: Path, filename: str, session_id: str, mutate) -> dict | None:
    """Read-modify-write one session's entry under the file's side lock.

    Every session's hooks share these files, so two unlocked updates could
    each rewrite the file from what they read and drop the other's entry
    (audit F16). `mutate(entry)` gets this session's entry (`{}` if none) and
    returns the new one, or `None` to leave the file alone.

    Returns the entry written, or `None` when nothing was: `mutate` declined,
    or another process held the lock past `lock.SIDE_TIMEOUT`, in which case
    the update is skipped and `state_dropped` is noted in the hook log rather
    than waited on. A filesystem that cannot lock is written uncoordinated, as
    before this existed. Never raises.
    """
    from breadcrumbs import hooklog, lock as _lock

    try:
        path = private_path(memory_dir, "." + filename + ".lock")
        with _lock.side_lock(path) as state:
            if state == _lock.BUSY:
                hooklog.note(state_dropped=filename)
                return None
            sessions = read_state(memory_dir, filename)
            entry = sessions.get(session_id)
            entry = dict(entry) if isinstance(entry, dict) else {}
            new = mutate(entry)
            if new is None:
                return None
            new["updated_at"] = cli.now_iso()
            sessions[session_id] = new
            write_state(memory_dir, filename, sessions, current=session_id)
            return new
    except Exception:  # pragma: no cover - hook state is best-effort
        return None


# --------------------------------------------------------------------------- #
# "Have I already said this?"
# --------------------------------------------------------------------------- #


def advisory_seen(
    memory_dir: Path, session_id: str, key: str, *, filename: str | None = None
) -> bool:
    """True if `key` already fired for this session; records it if not.

    Same records, same target ⇒ say nothing after the first time. An advisory
    that repeats verbatim on every tool call is one the agent learns to skim,
    and then it skims the one that mattered. If the key cannot be recorded
    (the state file is busy), the advisory speaks: a failure costs one
    deduplication, never a warning.
    """
    seen = []

    def mutate(entry: dict):
        keys = entry.get("seen") if isinstance(entry.get("seen"), list) else []
        if key in keys:
            seen.append(True)
            return None
        return {**entry, "seen": (keys + [key])[-MAX_KEYS_PER_SESSION:]}

    update_state(memory_dir, filename or GUARD_SEEN_FILENAME, session_id, mutate)
    return bool(seen)


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


def task_ref(prompt: str) -> str:
    """A short digest naming one prompt, so retrieval state can say which task
    it belongs to without keeping a second copy of the text."""
    text = " ".join(str(prompt or "").split())
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def record_task(
    memory_dir: Path, session_id: str, prompt: str, *, retain_text: bool = True
) -> dict | None:
    """The session's latest substantive task: its text, when and where it came from.

    Written for every prompt the prompt hook treats as work, *before* the
    lookup, so a task that matches nothing still replaces the one before it
    (audit F15). Acknowledgements and slash commands never reach here, so "ok"
    does not overwrite what the session is doing.

    The text is local state, not a record and never an instruction: at most
    `SESSION_PROMPT_CHARS`, withheld if it carries a credential, and not kept
    at all when the manifest says `retain_prompt_text: false` (then only the
    digest and time are). Retrieval state from an earlier task is left as it
    was, and stays labelled as belonging to that task.
    """
    from breadcrumbs import transcript as _transcript

    text = " ".join(str(prompt or "").split())[:SESSION_PROMPT_CHARS]
    task = {"ref": task_ref(prompt), "at": cli.now_iso(), "source": "prompt"}
    if not retain_text:
        task["withheld"] = "policy"
    elif _transcript.redact_secrets(text) is None:
        task["withheld"] = "credential"
    else:
        task["text"] = text

    def mutate(entry: dict) -> dict:
        new = {k: v for k, v in entry.items() if k not in ("last_prompt", "matched", "at")}
        new["task"] = task
        return new

    return update_state(memory_dir, SESSION_STATE_FILENAME, session_id, mutate)


def record_retrieval(
    memory_dir: Path,
    session_id: str,
    prompt: str,
    *,
    mode: str,
    selected: list[str],
    emitted: list[str],
) -> dict | None:
    """What the latest lookup found for the prompt `prompt`, kept apart from the task.

    `selected` is what memory matched (after the current-records rule and the
    cap); `emitted` is what the hook actually printed (after budget trimming
    and deduplication), which is the only part counted as surfaced. The query
    text is not stored again: `for_task` is its digest.
    """
    retrieval = {
        "for_task": task_ref(prompt),
        "at": cli.now_iso(),
        "mode": mode,
        "selected": list(selected or []),
        "emitted": list(emitted or []),
    }

    def mutate(entry: dict) -> dict:
        return {**entry, "retrieval": retrieval}

    return update_state(memory_dir, SESSION_STATE_FILENAME, session_id, mutate)


def record_prompt_state(
    memory_dir: Path, session_id: str, prompt: str, matched_ids: list[str]
) -> None:
    """The pre-WP12 single call, kept for importers: the task and its lookup."""
    record_task(memory_dir, session_id, prompt)
    record_retrieval(
        memory_dir, session_id, prompt, mode="unknown", selected=matched_ids, emitted=matched_ids
    )


def prompt_state(memory_dir: Path, session_id: str) -> dict:
    """This session's prompt state, with the two views compaction reads.

    - `last_prompt`: the latest substantive task's text (absent if it was not
      retained).
    - `matched`: what memory matched for *that* task, or `[]` when the latest
      lookup was for an earlier one or matched nothing.

    The raw `task` and `retrieval` entries are returned as well. A file from
    before audit WP12 (with `last_prompt` and `matched` only) is read as it
    was written.
    """
    entry = read_state(memory_dir, SESSION_STATE_FILENAME).get(session_id)
    if not isinstance(entry, dict):
        return {}
    if not isinstance(entry.get("task"), dict):
        return entry
    task = entry["task"]
    retrieval = entry.get("retrieval") if isinstance(entry.get("retrieval"), dict) else {}
    current = retrieval.get("for_task") == task.get("ref")
    out = dict(entry)
    if task.get("text"):
        out["last_prompt"] = task["text"]
    out["at"] = task.get("at")
    out["matched"] = list(retrieval.get("selected") or []) if current else []
    return out


def record_compaction(
    memory_dir: Path, session_id: str, *, trigger: str | None, commit: str, jots: list[str]
) -> None:
    marker = {
        "at": cli.now_iso(),
        "trigger": trigger or "unknown",
        "commit": commit,
        "jots": list(jots or []),
    }
    update_state(memory_dir, COMPACTION_MARKER_FILENAME, session_id, lambda _entry: dict(marker))


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

    def mutate(entry: dict) -> dict:
        prior = entry.get("jots") if isinstance(entry.get("jots"), list) else []
        known = {str(j) for j in prior} | {str(j) for j in jot_ids or []}
        return {"jots": sorted(known)[-MAX_KEYS_PER_SESSION:]}

    update_state(memory_dir, EXTRACTION_ASKED_FILENAME, session_id, mutate)
