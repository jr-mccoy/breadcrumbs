"""breadcrumbs — record usage telemetry (WM-02).

Which records actually get *shown* to somebody. Nothing recorded this before, so
every question that depends on it had no answer: which records earn their place
in the packet, which are never reached and should decay, which have proven
durable enough to promote into the long-term instruction file.

**Local-only, by design.** The counts live in `private/usage.json`, which is
gitignored. Three alternatives were rejected:

- *Counters in record frontmatter* — every guard call would rewrite records,
  churn `_inputs_hash`, and make "records are authored facts" false.
- *A committed counter file* — it would conflict on every merge, in every repo,
  forever.
- *No telemetry* — the decay, ranking and promotion work downstream of this has
  no signal at all without it.

A shared signal may still be worth the merge cost later; that is an open
decision in `docs/roadmap-working-memory.md` §3, to be made with data from this.

**Surfaced means emitted, not read.** A record counts when its id was in output
that reached an agent or a human: the resume packet was printed or injected, a
guard verdict cited it, a hook spent context on it. It is counted after
deduplication and budget trimming (audit F16): a repeat the hook stayed silent
on, or a line trimmed to fit, was retrieved and selected but never emitted, and
does not count. A count is not evidence that a record was read or that it
helped, and nothing here acts on one: decay and promotion print commands for a
person. It deliberately does *not* count when
`build_resume_packet` runs as part of a reindex (every write triggers one, which
would make the counts measure writes), nor on a `search` (a lookup is the caller
already knowing what they want), nor on an MCP resource read.

**Contention (audit WP12).** Each emission is one event file in
`private/usage-events/`, created by an atomic rename. Nothing read-modify-writes
a shared file on the emitting path, so parallel hooks cannot lose each other's
counts. `fold` adds pending events to `usage.json` under `.usage.lock`, exactly
once, and readers count what is still pending. What is approximate is stated in
`accounting`: the 2000-record cap evicts, an unreadable event file is dropped,
and an emission that cannot be written is noted `usage_dropped` in the hook log.

Every function here is best-effort: telemetry must never fail a command, block a
hook, or lose a write. A missing, corrupt or unwritable file means "no data".
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import time
from pathlib import Path
from typing import Iterable

from breadcrumbs import cli
from breadcrumbs import path_policy
from breadcrumbs import scoring as _scoring
from breadcrumbs import audit as _audit

USAGE_FILENAME = "usage.json"

# Ids kept before the least-recently-surfaced are dropped. A store with more
# distinct records than this is well past the point where the oldest counts
# matter, and the file has to stay small enough to read on every guard call.
USAGE_MAX_RECORDS = 2000

# Distinct session ids remembered per record. WM-42 asks "how many *sessions*
# surfaced this", which a raw count cannot answer: one session that fires the
# guard forty times is not forty pieces of evidence.
USAGE_MAX_SESSIONS_PER_RECORD = 20

# The recognized `source` values. Not enforced — an unknown source is recorded
# as given rather than dropped, because losing data to a typo is worse than a
# stray key — but these are what the reports and later phases look for.
USAGE_SOURCES = ("resume", "guard", "hook-guard", "prompt")

# Where emissions wait to be folded into `usage.json` (audit F16): one small
# file per emission, so parallel hooks never rewrite each other's counts.
USAGE_EVENTS_DIRNAME = "usage-events"
USAGE_LOCK_FILENAME = ".usage.lock"
# Past this many unfolded events (a fold held off that long means something is
# wrong), a new emission is dropped and the drop noted, rather than letting
# the directory grow without bound.
USAGE_MAX_PENDING_EVENTS = 2000
# More ids than any one surface emits; a runaway caller cannot write a huge event.
USAGE_MAX_IDS_PER_EVENT = 200

# What a count means, printed with the counts (`crumb usage`).
ACCOUNTING_MODEL = (
    "surfaced = the record's id was in output a host received (a resume packet, a "
    "guard verdict, a hook's context or prompt), counted after deduplication and "
    "budget trimming. Retrieved or selected-but-trimmed records are not counted. A "
    "count says the record was shown, not that it was read or that it helped."
)


def usage_path(memory_dir: Path) -> Path:
    return Path(memory_dir) / "private" / USAGE_FILENAME


def events_dir(memory_dir: Path) -> Path:
    return Path(memory_dir) / "private" / USAGE_EVENTS_DIRNAME


def _lock_path(memory_dir: Path) -> Path:
    return Path(memory_dir) / "private" / USAGE_LOCK_FILENAME


def _read_snapshot(memory_dir: Path) -> dict:
    """`usage.json` as written by the last fold, normalised. Never raises."""
    try:
        data = json.loads(path_policy.read_text(usage_path(memory_dir)))
    except Exception:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("records"), dict):
        return {"records": {}, "folded_last": [], "accounting": {}}
    out: dict = {"records": data["records"]}
    if isinstance(data.get("started_at"), str):
        out["started_at"] = data["started_at"]
    folded = data.get("folded_last")
    out["folded_last"] = [str(n) for n in folded] if isinstance(folded, list) else []
    acc = data.get("accounting")
    out["accounting"] = dict(acc) if isinstance(acc, dict) else {}
    return out


def _pending_names(memory_dir: Path) -> list[str]:
    """Event files written and not yet folded, oldest first. Temp files excluded."""
    try:
        names = os.listdir(events_dir(memory_dir))
    except OSError:
        return []
    return sorted(n for n in names if n.endswith(".json") and not n.startswith("."))


def _read_event(memory_dir: Path, name: str):
    """An event dict, `None` if the file is gone (folded meanwhile), or
    `False` if it cannot be used."""
    try:
        data = json.loads(path_policy.read_text(events_dir(memory_dir) / name))
    except FileNotFoundError:
        return None
    except Exception:
        return False
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("ids"), list)
        or not isinstance(data.get("source"), str)
    ):
        return False
    return data


def _apply(records: dict, event: dict) -> None:
    """Add one emission to the per-record counts, in place."""
    at = str(event.get("at") or "")
    source = str(event["source"])
    session_id = event.get("session")
    for rid in event["ids"]:
        if not rid:
            continue
        rid = str(rid)
        entry = records.get(rid)
        if not isinstance(entry, dict):
            entry = {}
        by = entry.get("by")
        by = dict(by) if isinstance(by, dict) else {}
        by[source] = int(by.get(source, 0) or 0) + 1
        sessions = entry.get("sessions")
        sessions = list(sessions) if isinstance(sessions, list) else []
        if session_id and session_id not in sessions:
            sessions = (sessions + [session_id])[-USAGE_MAX_SESSIONS_PER_RECORD:]
        last = str(entry.get("last_surfaced_at") or "")
        records[rid] = {
            "surfaced": int(entry.get("surfaced", 0) or 0) + 1,
            "last_surfaced_at": max(last, at) or None,
            "by": by,
            "sessions": sessions,
        }


def load_usage(memory_dir: Path) -> dict:
    """The usage document, or an empty one. Never raises.

    The last fold's counts plus every event still waiting to be folded, so a
    reader never misses an acknowledged emission because a fold has not run
    yet (audit F16).

    `started_at` is when counting began on this machine (WM-60): decay must know
    how much history "never surfaced" is measured over. Files written before it
    existed have none, and `coverage_start` falls back to their evidence.
    """
    try:
        # Listed before the snapshot is read: a fold that lands in between has
        # already counted and removed what it folded, and a listed file that
        # is gone by the time it is read is skipped.
        pending = _pending_names(memory_dir)
        snap = _read_snapshot(memory_dir)
        records = snap["records"]
        folded = set(snap["folded_last"])
        copied = False
        for name in pending:
            if name in folded:
                continue
            event = _read_event(memory_dir, name)
            if not event:
                continue
            if not copied:
                records = {k: dict(v) if isinstance(v, dict) else v for k, v in records.items()}
                copied = True
            _apply(records, event)
        out: dict = {"records": records}
        if snap.get("started_at"):
            out["started_at"] = snap["started_at"]
        elif copied:
            out["started_at"] = _oldest_surfacing(records)
        return out
    except Exception:  # pragma: no cover - telemetry never breaks its caller
        return {"records": {}}


def accounting(memory_dir: Path) -> dict:
    """How complete the counts are: what `crumb usage` reports beside them.

    - `pending_events`: acknowledged emissions not yet folded (they are
      counted; a fold is only waiting for its lock).
    - `unreadable_events`: event files a fold could not parse, removed
      uncounted.
    - `evicted_records`: ids dropped by the `USAGE_MAX_RECORDS` cap.
    - `events_folded`: emissions folded into `usage.json` since the file began.

    An emission that could not be written at all is not here: nothing durable
    was made. The hook that tried notes `usage_dropped` in its hook-log line
    (`crumb doctor --hook-log`).
    """
    snap = _read_snapshot(memory_dir)
    folded = set(snap["folded_last"])
    acc = snap["accounting"]
    return {
        "model": ACCOUNTING_MODEL,
        "pending_events": sum(1 for n in _pending_names(memory_dir) if n not in folded),
        "events_folded": int(acc.get("events_folded", 0) or 0),
        "unreadable_events": int(acc.get("unreadable_events", 0) or 0),
        "evicted_records": int(acc.get("evicted_records", 0) or 0),
    }


def record_surfaced(
    memory_dir: Path,
    ids: Iterable[str],
    source: str,
    *,
    session_id: str | None = None,
) -> int:
    """Count one emission of each id. Returns how many ids were acknowledged.

    Call it only with the ids of output a host actually received (audit F16):
    after deduplication, after budget trimming, never for a candidate that was
    retrieved and then dropped.

    Acknowledged means durable: the emission is one event file, created by an
    atomic rename, and every reader counts it from then on. Parallel writers
    never read-modify-write a shared file, so none can lose another's
    increment. Folding into `usage.json` is housekeeping under a lock of its
    own; when another process holds it the event simply waits, still counted.

    Returns 0, and notes `usage_dropped` for the hook log, when the event could
    not be written or the pending backlog is at `USAGE_MAX_PENDING_EVENTS`.
    Never raises: telemetry must not fail its caller.

    Keyed by record **id**, not path: an id survives `crumb retitle` and any file
    move, and it is what every other surface in the tool already names a record
    by.
    """
    try:
        unique: list[str] = []
        for i in ids:
            if i and str(i) not in unique:
                unique.append(str(i))
        if not unique:
            return 0
        unique = unique[:USAGE_MAX_IDS_PER_EVENT]
        if len(_pending_names(memory_dir)) >= USAGE_MAX_PENDING_EVENTS:
            fold(memory_dir)
            if len(_pending_names(memory_dir)) >= USAGE_MAX_PENDING_EVENTS:
                _note_dropped(len(unique))
                return 0
        event = {"at": cli.now_iso(), "ids": unique, "source": str(source), "v": 1}
        if session_id:
            event["session"] = str(session_id)
        folder = events_dir(memory_dir)
        path_policy.mkdirs(folder)
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        name = (
            f"{stamp}-{time.monotonic_ns() % 10**9:09d}-{os.getpid()}-{secrets.token_hex(4)}.json"
        )
        cli.write_text_atomic(folder / name, json.dumps(event, sort_keys=True) + "\n")
    except Exception:
        _note_dropped(1)
        return 0
    fold(memory_dir)
    return len(unique)


def _note_dropped(n: int) -> None:
    try:
        from breadcrumbs import hooklog

        hooklog.note(usage_dropped=n)
    except Exception:  # pragma: no cover
        pass


def fold(memory_dir: Path, *, timeout: float = 0.0) -> bool:
    """Fold pending events into `usage.json`, exactly once. Never raises.

    Under `private/.usage.lock`, one folder at a time. `folded_last` names the
    events the last fold counted; it is written in the same atomic replace as
    the counts, and those files are removed before the next fold forgets them,
    so a fold that dies between writing and deleting cannot count an event
    twice. Returns True when a fold ran.
    """
    from breadcrumbs import lock as _lock

    try:
        with _lock.side_lock(_lock_path(memory_dir), timeout=timeout) as state:
            if state != _lock.HELD:
                return False  # the events wait; they are already counted
            snap = _read_snapshot(memory_dir)
            folder = events_dir(memory_dir)
            for name in snap["folded_last"]:
                with contextlib.suppress(OSError):
                    (folder / name).unlink()
            folded_last = set(snap["folded_last"])
            names = [n for n in _pending_names(memory_dir) if n not in folded_last]
            if not names:
                return True
            # Read before this fold's timestamps count: a file from before
            # `started_at` existed keeps the history it can prove.
            prior_start = snap.get("started_at") or _oldest_surfacing(snap["records"])
            records = snap["records"]
            acc = snap["accounting"]
            applied: list[str] = []
            first_at = None
            for name in names:
                event = _read_event(memory_dir, name)
                if event is None:
                    continue
                applied.append(name)
                if event is False:
                    acc["unreadable_events"] = int(acc.get("unreadable_events", 0) or 0) + 1
                    continue
                _apply(records, event)
                acc["events_folded"] = int(acc.get("events_folded", 0) or 0) + 1
                at = str(event.get("at") or "")
                if at and (first_at is None or at < first_at):
                    first_at = at
            started = prior_start or first_at or cli.now_iso()
            if len(records) > USAGE_MAX_RECORDS:
                # Drop the least recently surfaced. An id with no timestamp
                # sorts oldest, which is the right answer for a hand-edited file.
                keep = sorted(
                    records,
                    key=lambda r: str((records[r] or {}).get("last_surfaced_at") or ""),
                    reverse=True,
                )[:USAGE_MAX_RECORDS]
                acc["evicted_records"] = int(acc.get("evicted_records", 0) or 0) + (
                    len(records) - len(keep)
                )
                records = {r: records[r] for r in keep}
            doc = {
                "accounting": acc,
                "folded_last": applied,
                "records": records,
                "started_at": started,
            }
            path = usage_path(memory_dir)
            path_policy.mkdirs(path.parent)
            cli.write_text_atomic(path, json.dumps(doc, indent=0, sort_keys=True) + "\n")
            for name in applied:
                with contextlib.suppress(OSError):
                    (folder / name).unlink()
            return True
    except Exception:  # pragma: no cover - telemetry never breaks its caller
        return False


def usage_rows(memory_dir: Path, *, by_sessions: bool = False) -> list[dict]:
    """One row per record with usage data, most-surfaced first.

    `by_sessions` sorts by distinct sessions instead (WM-60): forty guard calls
    in one session are one piece of evidence, five sessions are five. Only the
    last `USAGE_MAX_SESSIONS_PER_RECORD` are kept, so a row at the cap reads as
    "at least" that many (`sessions_capped`).
    """
    records = load_usage(memory_dir)["records"]
    rows = []
    for rid, entry in records.items():
        if not isinstance(entry, dict):
            continue
        by = entry.get("by") if isinstance(entry.get("by"), dict) else {}
        sessions = entry.get("sessions") if isinstance(entry.get("sessions"), list) else []
        rows.append(
            {
                "id": rid,
                "surfaced": int(entry.get("surfaced", 0) or 0),
                "last_surfaced_at": entry.get("last_surfaced_at"),
                "by": by,
                "sessions": len(sessions),
                "sessions_capped": len(sessions) >= USAGE_MAX_SESSIONS_PER_RECORD,
            }
        )
    if by_sessions:
        rows.sort(key=lambda r: (-r["sessions"], -r["surfaced"], r["id"]))
    else:
        rows.sort(key=lambda r: (-r["surfaced"], r["id"]))
    return rows


def never_surfaced(memory_dir: Path, *, types: tuple[str, ...] | None = None) -> list[dict]:
    """Active items with no usage entry at all, oldest first.

    Covers the same corpus `guard` judges against (decisions, attempts,
    verifications, traps) plus whatever `types` narrows to — the records that are
    *meant* to be reached. An idea or a jot has no such obligation.
    """
    seen = set(load_usage(memory_dir)["records"])
    out: list[dict] = []
    wanted = types or _scoring.JUDGING_ITEM_TYPES
    for rec in cli.load_records(memory_dir, types=wanted):
        if rec.error or (rec.meta.get("status") or "active") != "active":
            continue
        rid = rec.meta.get("id") or rec.stem
        if rid in seen:
            continue
        out.append(
            {
                "id": rid,
                "type": rec.rtype,
                "title": rec.meta.get("title", ""),
                "created_at": rec.meta.get("created_at"),
                "age_days": cli._age_days(rec.meta.get("created_at")),
            }
        )
    if "trap" in (types or ()) or types is None:
        for trap in cli.active_traps(memory_dir):
            if trap["id"] in seen:
                continue
            out.append(
                {
                    "id": trap["id"],
                    "type": "trap",
                    "title": trap.get("summary") or trap.get("heading", ""),
                    "created_at": None,
                    "age_days": None,
                }
            )
    out.sort(key=lambda r: (r["age_days"] is None, -(r["age_days"] or 0), r["id"]))
    return out


def has_usage_data(memory_dir: Path) -> bool:
    """Is there any history at all?

    `audit` must not report "never surfaced" on a fresh clone, where *nothing*
    has been surfaced yet and the finding would be true of every record and
    useful about none.
    """
    return bool(load_usage(memory_dir)["records"])


# --------------------------------------------------------------------------- #
# WM-60: decay
# --------------------------------------------------------------------------- #

# A record with no surfacing in this many days of usage history, and at least
# this old itself, is a decay candidate.
DECAY_DAYS = _audit.DECAY_DAYS_DEFAULT
# What decays. Verifications and questions already have TTLs (WM-30); an idea or
# a jot is not meant to be reached.
DECAY_TYPES = ("decision", "attempt", "trap")
DECAY_REASON = "not surfaced in {days} days"


def coverage_start(memory_dir: Path) -> str | None:
    """When usage counting began here, as an ISO timestamp, or None if never.

    Files from before `started_at` existed fall back to the oldest
    `last_surfaced_at`. Counting began no later than that, so this can only
    *under*-state the history, and decay errs toward suggesting nothing.
    """
    data = load_usage(memory_dir)
    return data.get("started_at") or _oldest_surfacing(data["records"])


def _oldest_surfacing(records: dict) -> str | None:
    stamps = [
        str(e.get("last_surfaced_at"))
        for e in records.values()
        if isinstance(e, dict) and e.get("last_surfaced_at")
    ]
    return min(stamps) if stamps else None


def _trap_age_days(trap: dict) -> int | None:
    """A trap's age: its file's `updated_at`/`created_at`, else unknown."""
    path = trap.get("record_path")
    if not path:
        return None
    try:
        meta, _ = cli.parse_frontmatter(path_policy.read_text(Path(path)))
    except Exception:
        return None
    return cli._age_days(meta.get("updated_at") or meta.get("created_at"))


def decay_candidates(memory_dir: Path, *, days: int = DECAY_DAYS) -> dict:
    """Active decisions, attempts and traps nothing has surfaced for `days` (WM-60).

    A candidate is at least `days` old (by `updated_at`, so an edit resets
    it) and has no surfacing in the last `days`, and the usage history covers
    at least `days`. With less history nothing is a candidate: a store that has
    counted for a week cannot say what went unused for six months.

    Never retires anything. Each candidate carries the `mark-status` command a
    person can run. Left out: promoted records (the packet stops showing them
    on purpose, so they are never surfaced), records past their TTL (already
    out of the packet), and traps confirmed within `days` (`crumb traps
    --confirm` is someone saying it still holds).
    """
    from breadcrumbs import promote as _promote

    memory_dir = Path(memory_dir)
    start = coverage_start(memory_dir)
    coverage = cli._age_days(start) if start else None
    result = {
        "days": days,
        "coverage_start": start,
        "coverage_days": coverage,
        "enough_history": coverage is not None and coverage >= days,
        "candidates": [],
    }
    if not result["enough_history"]:
        return result
    records = load_usage(memory_dir)["records"]

    def unused(rid: str) -> tuple[bool, dict]:
        entry = records.get(rid) if isinstance(records.get(rid), dict) else {}
        last = entry.get("last_surfaced_at")
        since = cli._age_days(last) if last else None
        return (not last or (since is not None and since >= days)), entry

    reason = DECAY_REASON.format(days=days)
    out: list[dict] = []
    for rec in cli.load_records(memory_dir, types=("decision", "attempt")):
        if rec.error or (rec.meta.get("status") or "active") != "active":
            continue
        if _promote.is_promoted_record(rec) or cli.record_expired(rec.meta):
            continue
        age = cli._age_days(rec.meta.get("updated_at") or rec.meta.get("created_at"))
        rid = rec.meta.get("id") or rec.stem
        ok, entry = unused(rid)
        if age is None or age < days or not ok:
            continue
        out.append(_candidate(rid, rec.rtype, rec.meta.get("title", ""), age, entry, reason))
    for trap in cli.active_traps(memory_dir):
        if _promote.is_promoted_trap(trap):
            continue
        confirmed = cli.trap_last_confirmed(trap)
        confirmed_age = cli._age_days(confirmed) if confirmed else None
        if confirmed_age is not None and confirmed_age < days:
            continue
        age = _trap_age_days(trap)
        ok, entry = unused(trap["id"])
        if age is None or age < days or not ok:
            continue
        title = trap.get("summary") or trap.get("heading", "")
        out.append(_candidate(trap["id"], "trap", title, age, entry, reason))
    out.sort(key=lambda r: (-r["age_days"], r["id"]))
    result["candidates"] = out
    return result


def _candidate(rid: str, rtype: str, title: str, age: int, entry: dict, reason: str) -> dict:
    return {
        "id": rid,
        "type": rtype,
        "title": title,
        "age_days": age,
        "surfaced": int(entry.get("surfaced", 0) or 0),
        "last_surfaced_at": entry.get("last_surfaced_at"),
        "command": f'crumb mark-status {rid} stale --reason "{reason}"',
    }
