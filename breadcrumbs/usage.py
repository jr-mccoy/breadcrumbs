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

**Surfaced means shown, not read.** A record counts when it reached an agent or
a human: the resume packet was printed or injected, a guard verdict cited it, a
hook spent context on it. It deliberately does *not* count when
`build_resume_packet` runs as part of a reindex (every write triggers one, which
would make the counts measure writes), nor on a `search` (a lookup is the caller
already knowing what they want), nor on an MCP resource read.

Every function here is best-effort: telemetry must never fail a command, block a
hook, or lose a write. A missing, corrupt or unwritable file means "no data".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from breadcrumbs import cli

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


def usage_path(memory_dir: Path) -> Path:
    return Path(memory_dir) / "private" / USAGE_FILENAME


def load_usage(memory_dir: Path) -> dict:
    """The usage document, or an empty one. Never raises.

    `started_at` is when counting began on this machine (WM-60): decay must know
    how much history "never surfaced" is measured over. Files written before it
    existed have none, and `coverage_start` falls back to their evidence.
    """
    try:
        data = json.loads(usage_path(memory_dir).read_text(encoding="utf-8"))
    except Exception:
        return {"records": {}}
    if not isinstance(data, dict):
        return {"records": {}}
    records = data.get("records")
    if not isinstance(records, dict):
        return {"records": {}}
    out: dict = {"records": records}
    if isinstance(data.get("started_at"), str):
        out["started_at"] = data["started_at"]
    return out


def record_surfaced(
    memory_dir: Path,
    ids: Iterable[str],
    source: str,
    *,
    session_id: str | None = None,
) -> None:
    """Count one surfacing of each id. Best-effort; swallows every failure.

    Keyed by record **id**, not path: an id survives `crumb retitle` and any file
    move, and it is what every other surface in the tool already names a record
    by.
    """
    try:
        ids = [str(i) for i in ids if i]
        if not ids:
            return
        data = load_usage(memory_dir)
        records = data["records"]
        now = cli.now_iso()
        # Read before this write touches any timestamp: a file from before
        # `started_at` existed keeps the history it can prove.
        started = data.get("started_at") or _oldest_surfacing(records) or now
        for rid in ids:
            entry = records.get(rid)
            if not isinstance(entry, dict):
                entry = {}
            by = entry.get("by")
            if not isinstance(by, dict):
                by = {}
            by[source] = int(by.get(source, 0) or 0) + 1
            sessions = entry.get("sessions")
            if not isinstance(sessions, list):
                sessions = []
            if session_id and session_id not in sessions:
                sessions = (sessions + [session_id])[-USAGE_MAX_SESSIONS_PER_RECORD:]
            records[rid] = {
                "surfaced": int(entry.get("surfaced", 0) or 0) + 1,
                "last_surfaced_at": now,
                "by": by,
                "sessions": sessions,
            }
        if len(records) > USAGE_MAX_RECORDS:
            # Drop the least recently surfaced. An id with no timestamp sorts
            # oldest, which is the right answer for a hand-edited file.
            keep = sorted(
                records,
                key=lambda r: str(records[r].get("last_surfaced_at") or ""),
                reverse=True,
            )[:USAGE_MAX_RECORDS]
            records = {r: records[r] for r in keep}
        path = usage_path(memory_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        doc = {"records": records, "started_at": started}
        cli.write_text_atomic(path, json.dumps(doc, indent=0, sort_keys=True) + "\n")
    except Exception:  # pragma: no cover - telemetry never breaks its caller
        pass


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
    wanted = types or cli.JUDGING_ITEM_TYPES
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
DECAY_DAYS = cli.DECAY_DAYS_DEFAULT
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
        meta, _ = cli.parse_frontmatter(Path(path).read_text(encoding="utf-8"))
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
