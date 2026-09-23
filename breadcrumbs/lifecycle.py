"""breadcrumbs — record lifecycle: decay, duplicates, consolidation, conflict (Phase 3).

Phases 0 to 2 made memory easy to write and easy to find. This module is about
the other half: memory that stops being true. Nothing here deletes a record
except `rollup_sessions`, which only folds machine snapshots into one record.
Everything else hides, warns or asks — a record that aged out goes to guard's
history, a near-duplicate is refused with the id it duplicates, a
contradiction is a question in the packet — because deciding that a claim is
wrong is the author's job, not a heuristic's.

**Time-to-live (WM-30).** Every type has a lifespan, overridable per store with
flat `ttl_<type>_days` keys in `manifest.yml` (flat because `load_manifest`
parses flat `key: value`). What reaching it means differs by type:

| type | default | reached |
|---|---|---|
| jot | 14 | `expires_at` is set at write; hidden from packet and inbox |
| verification | 90 | settled outcomes (`fixed`, `not_applicable`) get `expires_at` and go to history; actionable ones never expire, the packet asks for a recheck |
| trap | 180 | since last confirmed (or written); the packet asks for a confirmation |
| question | 45 | still open; `crumb questions --aging` lists it |
| current | 14 | since `current.md` last changed; the packet asks whether the focus is still true |

Decisions and attempts have no lifespan. A decision is true until something
supersedes it, and an attempt records something that happened.

**The clock** is `cli._now()`. Tests move it by patching that one function.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from breadcrumbs import cli

# --------------------------------------------------------------------------- #
# WM-30: time-to-live
# --------------------------------------------------------------------------- #

TTL_DEFAULTS = {
    "jot": cli.JOT_TTL_DAYS_DEFAULT,
    "question": 45,
    "verification": 90,
    "trap": 180,
    "current": 14,
}

# Outcomes that are settled: the check is done and the answer was "fine" or
# "does not apply". These are the verifications that silently go stale, so they
# are the ones that expire. An actionable outcome (open, regressed,
# inconclusive) never expires: it is a problem somebody still has to look at.
SETTLED_VERIFICATION_OUTCOMES = ("fixed", "not_applicable")

# Packet warnings per lifecycle kind. Each is a nudge, not a list: the full
# picture is one command away (`crumb expired`, `crumb traps --stale`, …).
PACKET_LIFECYCLE_MAX = 3


def ttl_days(memory_dir: Path, kind: str) -> int:
    """The store's lifespan for `kind`, from `ttl_<kind>_days` or the default.

    `jot_ttl_days` (the Phase 0 key) still works for jots; the new spelling wins
    when both are set. Anything unparseable or non-positive falls back to the
    default rather than disabling decay.
    """
    manifest = cli.load_manifest(Path(memory_dir)) or {}
    default = TTL_DEFAULTS[kind]
    keys = [f"ttl_{kind}_days"] + (["jot_ttl_days"] if kind == "jot" else [])
    for key in keys:
        raw = manifest.get(key)
        if raw is None:
            continue
        try:
            value = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return default


is_expired = cli.record_expired


def verification_expiry(memory_dir: Path, outcome: str, created_at: str) -> str | None:
    """`expires_at` for a new verification: settled outcomes only."""
    if outcome not in SETTLED_VERIFICATION_OUTCOMES:
        return None
    dt = cli._parse_iso(created_at)
    if dt is None:  # pragma: no cover - created_at is ours and always parseable
        return None
    days = ttl_days(memory_dir, "verification")
    return (dt + timedelta(days=days)).replace(microsecond=0).isoformat()


def expired_items(memory_dir: Path) -> list[dict]:
    """Every still-`active` record whose `expires_at` has passed, oldest expiry first.

    Machine-local jots are included — this is a local listing, never a
    committed one. A record somebody already retired is not "expired", it is
    retired, and is left out.
    """
    from breadcrumbs import inbox as _inbox

    memory_dir = Path(memory_dir)
    out = []
    records = list(cli.load_records(memory_dir))
    loaded = {r.path for r in records}
    for directory in _inbox.inbox_dirs(memory_dir):
        for path in sorted(directory.glob("*.md")):
            if path not in loaded:
                records.append(cli.Record.from_file(path, "jot"))
    for rec in records:
        if rec.error:
            continue
        if (rec.meta.get("status") or "active") != "active" or not is_expired(rec.meta):
            continue
        out.append(
            {
                "id": rec.meta.get("id", rec.stem),
                "kind": rec.rtype,
                "title": rec.meta.get("title") or rec.stem,
                "expires_at": rec.meta.get("expires_at"),
                "days_ago": cli._age_days(rec.meta.get("expires_at")),
                "path": str(rec.path.relative_to(memory_dir)),
            }
        )
    out.sort(key=lambda r: (cli._dt_sort_key(r["expires_at"]), r["id"]))
    return out


def aging_questions(memory_dir: Path, *, days: int | None = None) -> list[dict]:
    """Open questions older than the question TTL (or `days`), oldest first."""
    memory_dir = Path(memory_dir)
    limit = ttl_days(memory_dir, "question") if days is None else days
    rows = []
    for q in cli.load_open_questions(memory_dir):
        if (q.get("status") or "open") != "open":
            continue
        age = cli._age_days(q.get("opened"))
        rows.append(
            {
                "id": q["id"],
                "question": q["question"],
                "opened": q.get("opened"),
                "age_days": age,
                "aging": age is not None and age > limit,
            }
        )
    rows.sort(key=lambda r: (r["age_days"] is None, -(r["age_days"] or 0), r["id"]))
    return rows


def _current_md_age(memory_dir: Path, root: Path) -> int | None:
    """Days since `current.md` last changed: git's view first, the file's mtime else.

    A checkout rewrites every mtime, so on a fresh clone mtime says "today" for
    a file nobody has touched in a month. The last commit that changed the file
    is the honest answer; an uncommitted edit means it changed today.
    """
    path = Path(memory_dir) / "current.md"
    if not path.is_file():
        return None
    root = Path(root)
    if cli.is_git_repo(root):
        try:
            rel = path.resolve().relative_to(root.resolve())
        except ValueError:
            rel = None
        if rel is not None:
            dirty = cli._git_out(root, "status", "--porcelain", "--", str(rel))
            if dirty:
                return 0
            stamp = cli._git_out(root, "log", "-1", "--format=%cI", "--", str(rel))
            if stamp:
                return cli._age_days(stamp.strip())
    mtime = datetime.fromtimestamp(path.stat().st_mtime).astimezone()
    return cli._age_days(mtime.isoformat())


def lifecycle_warnings(
    memory_dir: Path,
    root: Path,
    *,
    verifications: list,
    traps: list[dict],
) -> list[str]:
    """The packet's lifespan nudges: old actionable verifications, unconfirmed
    traps, a `current.md` nobody has touched. Each kind capped separately."""
    memory_dir = Path(memory_dir)
    warnings: list[str] = []

    ver_ttl = ttl_days(memory_dir, "verification")
    old = []
    for rec in verifications:
        if (rec.meta.get("outcome") or "open") in SETTLED_VERIFICATION_OUTCOMES:
            continue
        age = cli._age_days(rec.meta.get("updated_at") or rec.meta.get("created_at"))
        if age is not None and age >= ver_ttl:
            old.append((age, rec.meta.get("id", rec.stem)))
    old.sort(reverse=True)
    for age, rid in old[:PACKET_LIFECYCLE_MAX]:
        warnings.append(
            f"verification {rid} is {age} days old; recheck it (`crumb verify --recheck {rid}`)."
        )

    trap_ttl = ttl_days(memory_dir, "trap")
    unconfirmed = []
    for trap in traps:
        if (trap.get("status") or "active") != "active":
            continue
        stamp = cli.trap_last_confirmed(trap) or _trap_written_at(trap)
        age = cli._age_days(stamp) if stamp else None
        if age is not None and age >= trap_ttl:
            unconfirmed.append((age, trap["id"]))
    unconfirmed.sort(reverse=True)
    for age, tid in unconfirmed[:PACKET_LIFECYCLE_MAX]:
        warnings.append(
            f"trap {tid} has not been confirmed in {age} days — still true? "
            f"(`crumb traps --confirm {tid}`, or retire it with `crumb mark-status {tid} stale`)."
        )

    cur_age = _current_md_age(memory_dir, root)
    cur_ttl = ttl_days(memory_dir, "current")
    if cur_age is not None and cur_age >= cur_ttl:
        warnings.append(
            f"current.md has not changed in {cur_age} days; is Current Focus still true?"
        )
    return warnings


def _trap_written_at(trap: dict) -> str | None:
    """When a trap file was written (a block has no date, so None)."""
    path = trap.get("record_path")
    if not path:
        return None
    rec = cli.Record.from_file(Path(path), "trap")
    return None if rec.error else rec.meta.get("created_at")


# --------------------------------------------------------------------------- #
# WM-31: evidence-driven staleness
# --------------------------------------------------------------------------- #

# Packet and audit both cap this: a store whose code moved under it can cite a
# hundred vanished files, and the first few are the signal.
EVIDENCE_MISSING_MAX = 5

# A recheck runs a command a record names. Five minutes is generous for a test
# suite and short enough that a hung command does not hang the CLI forever.
RECHECK_TIMEOUT_SECONDS = 300
RECHECK_OUTPUT_LINES = 3


def _evidence_path(ref: str) -> str | None:
    """The path part of a file evidence ref, or None when it is not a local path.

    `src/x.py:170` → `src/x.py`. Globs, URLs and absolute paths are skipped:
    none of them can be checked against this checkout, and a warning that can
    never be cleared is noise.
    """
    ref = str(ref or "").strip()
    if not ref or "://" in ref or any(c in ref for c in "*?["):
        return None
    path = ref
    head, sep, tail = ref.rpartition(":")
    if sep and head and tail.replace("-", "").isdigit():
        path = head
    if Path(path).is_absolute() or path.startswith("~"):
        return None
    return path


def missing_evidence_files(root: Path, records: list) -> list[tuple[str, str]]:
    """`(record id, ref)` for every cited file that is neither on disk nor in HEAD.

    On disk *or* in HEAD, not "in HEAD" alone: a file the author just created is
    not committed yet and is plainly not missing. What this catches is a file
    that was deleted or renamed after the record cited it — the record may
    describe code that no longer exists. Guard scoring is untouched: the decision
    that rejected existence-on-disk as a scoring signal
    (`dec_20260905_path-extraction-is-structural-and-a-mined-path`) stands; a
    warning is a different consumer.
    """
    root = Path(root)
    head = cli.HeadTree(root)
    out: list[tuple[str, str]] = []
    for rec in records:
        if rec.error:
            continue
        for ref in cli._evidence_refs(rec, ("file", "path")):
            path = _evidence_path(ref)
            if path is None:
                continue
            if (root / path).exists() or head.contains(root / path):
                continue
            out.append((rec.meta.get("id", rec.stem), ref))
    return out


def missing_evidence_warnings(root: Path, records: list) -> list[str]:
    missing = missing_evidence_files(root, records)
    lines = [
        f"{rid} cites {ref}, which is not in HEAD — verify the record still applies."
        for rid, ref in missing[:EVIDENCE_MISSING_MAX]
    ]
    if len(missing) > EVIDENCE_MISSING_MAX:
        lines.append(
            f"(+{len(missing) - EVIDENCE_MISSING_MAX} more cited file(s) missing — `crumb audit`)"
        )
    return lines


def recheck_targets(memory_dir: Path, ids: list[str] | None) -> tuple[list, list[str]]:
    """Verifications to recheck and the ids that could not be used, with why.

    `ids` None means every active verification that names a command. A named id
    that is not a verification, or has no command evidence, is reported rather
    than silently skipped — the user asked for that one.
    """
    memory_dir = Path(memory_dir)
    problems: list[str] = []
    if ids is None:
        recs = [
            r
            for r in cli.active_records(memory_dir, "verification")
            if cli._evidence_refs(r, ("command", "test"))
        ]
        return recs, problems
    recs = []
    for rid in ids:
        rec = cli.find_record_by_id(memory_dir, rid)
        if rec is None or rec.error or rec.rtype != "verification":
            problems.append(f"{rid}: no verification with that id")
            continue
        if (rec.meta.get("status") or "active") != "active":
            problems.append(
                f"{rid}: already {rec.meta.get('status')} — recheck the record that replaced it"
            )
            continue
        if not cli._evidence_refs(rec, ("command", "test")):
            problems.append(f"{rid}: names no command evidence to rerun")
            continue
        recs.append(rec)
    return recs, problems


def run_command(command: str, root: Path) -> dict:
    """Run one recorded command in the project root. Never raises."""
    import subprocess

    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=RECHECK_TIMEOUT_SECONDS,
        )
        code, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        code = None
        output = f"timed out after {RECHECK_TIMEOUT_SECONDS}s\n" + str(exc.output or "")
    except OSError as exc:
        code, output = None, f"could not run: {exc}"
    lines = [ln for ln in output.splitlines() if ln.strip()][-RECHECK_OUTPUT_LINES:]
    from breadcrumbs.transcript import redact_secrets

    tail = [
        ln if redact_secrets(ln) is not None else "[line dropped: looked like a secret]"
        for ln in lines
    ]
    return {"command": command, "exit_code": code, "tail": tail}


def recheck(memory_dir: Path, root: Path, rec, *, agent: str | None = None) -> dict:
    """Rerun `rec`'s commands and record the result as a new verification.

    The new record has the same subject, `method: runtime`, outcome `fixed` when
    every command exited 0 and `open` otherwise, the commands as evidence, and a
    note with each exit code and the last lines of output. The old record is
    superseded by it: the new one is the current answer, the old one history.
    """
    commands = cli._evidence_refs(rec, ("command", "test"))
    runs = [run_command(c, root) for c in commands]
    ok = all(r["exit_code"] == 0 for r in runs)
    note_lines = []
    for r in runs:
        code = "no exit code" if r["exit_code"] is None else f"exit {r['exit_code']}"
        note_lines.append(f"`{r['command']}` — {code}")
        note_lines.extend(f"    {ln}" for ln in r["tail"])
    old_id = rec.meta.get("id", rec.stem)
    note_lines.append(f"Recheck of {old_id}.")
    subject = rec.meta.get("subject") or rec.meta.get("title") or old_id
    result = cli.verify(
        memory_dir,
        root,
        str(subject),
        status="fixed" if ok else "open",
        method="runtime",
        note="\n".join(note_lines),
        evidence=[
            e
            for e in (rec.meta.get("evidence") or [])
            if isinstance(e, dict) and e.get("type") in ("command", "test")
        ],
        tags=[str(t) for t in (rec.meta.get("tags") or [])],
        agent=agent,
        supersedes=old_id,
    )
    if not result.get("ok"):
        return {"ok": False, "id": old_id, "error": result.get("error"), "runs": runs}
    return {
        "ok": True,
        "id": old_id,
        "new_id": result["id"],
        "outcome": result["outcome"],
        "runs": runs,
    }


# --------------------------------------------------------------------------- #
# WM-32: near-duplicate detection
# --------------------------------------------------------------------------- #

# Similarity is Jaccard over the specific stems of title + body (the vocabulary
# search scores on), plus a bonus per shared declared file and per shared tag,
# capped at 1.0. At 0.6 two records say substantially the same thing; below it
# they merely share a topic, which is what `related.json` is for.
DUP_THRESHOLD = 0.6
# A jot is cheap and a repeated observation is itself a signal, so the gate is
# much higher: only a near-verbatim repeat is refused.
JOT_DUP_THRESHOLD = 0.9
# Jaccard on a handful of words is noise: "Something bites here" and "Something
# else bites" share one stem out of three. A pair must share at least this many
# specific stems before a ratio means anything.
DUP_MIN_SHARED = 3
DUP_FILE_BONUS = 0.15
DUP_TAG_BONUS = 0.1
# The bonuses together never add more than this. Two records about the same
# four files are related, not duplicates — `related.json` already says so — and
# uncapped, four shared files alone cleared the threshold at 0.24 text overlap
# on this repo's own store. Capped, the text must carry at least 0.4.
DUP_BONUS_MAX = 0.2
DUP_MAX = 3
# The audit's retrospective sweep is pairwise; past this many items of one type
# it names the cost instead of paying it.
DUP_SWEEP_MAX_ITEMS = 2000
AUDIT_DUP_PAIRS_MAX = 10

# Types the gate and the sweep cover. Sessions are narratives of work that
# happened — two alike are two days of alike work, not a duplicate claim.
DEDUP_TYPES = ("decision", "attempt", "verification", "idea", "trap", "question", "jot")


def similarity(a: dict, b: dict) -> float:
    """How much two candidates (see `_candidate`) say the same thing, 0..1."""
    sa, sb = a["specific"], b["specific"]
    shared = sa & sb
    if len(shared) < DUP_MIN_SHARED and sa != sb:
        return 0.0
    union = sa | sb
    base = len(shared) / len(union) if union else 0.0
    bonus = DUP_FILE_BONUS * len(a["files"] & b["files"]) + DUP_TAG_BONUS * len(
        a["tags"] & b["tags"]
    )
    return round(min(1.0, base + min(bonus, DUP_BONUS_MAX)), 2)


def _candidate(rid: str, kind: str, title: str, text: str, files, tags) -> dict:
    tags = {str(t).lower() for t in (tags or ())}
    return {
        "id": rid,
        "kind": kind,
        "title": title,
        "specific": cli._specific(f"{title}\n{text}\n{' '.join(sorted(tags))}"),
        "files": cli._norm_files(set(files or ())),
        "tags": tags,
    }


def candidate_from_record(rec) -> dict:
    # Section *content* only: every record of a type carries the same headings
    # (`## Subject`, `## Outcome`, …), and counting them as shared words makes
    # every pair look alike and dilutes the ones that really are.
    return _candidate(
        rec.meta.get("id", rec.stem),
        rec.rtype,
        str(rec.meta.get("title") or rec.stem),
        "\n".join(cli._strip_html_comments(str(v)) for v in rec.sections.values()),
        cli._evidence_refs(rec, ("file", "path")),
        rec.meta.get("tags") or [],
    )


def live_candidates(memory_dir: Path, rtype: str) -> list[dict]:
    """Every live item of `rtype`, as a duplicate candidate.

    Live means what the packet and guard would still act on: active, not
    expired, not scoped to another branch (WM-52); for questions, open. Retired
    items are history — duplicating one is how you bring a retired claim back,
    which is allowed — and a record about another branch is not this branch's
    to supersede.
    """
    memory_dir = Path(memory_dir)
    current = cli.git_branch(memory_dir.parent)
    if rtype == "trap":
        return [
            _candidate(
                t["id"],
                "trap",
                t.get("summary") or t["heading"],
                t.get("content") or "",
                cli._item_from_trap(t)["files"],
                (),
            )
            for t in cli.active_traps(memory_dir)
        ]
    if rtype == "question":
        return [
            _candidate(q["id"], "question", q["question"], q.get("content") or "", (), ())
            for q in cli.load_open_questions(memory_dir)
            if (q.get("status") or "open") == "open"
        ]
    if rtype == "jot":
        from breadcrumbs import inbox as _inbox

        return [
            candidate_from_record(r)
            for r in _inbox.load_jots(memory_dir)
            if not cli.branch_scoped_elsewhere(r.meta, current)
        ]
    return [
        candidate_from_record(r)
        for r in cli.active_records(memory_dir, rtype)
        if not cli.record_expired(r.meta) and not cli.branch_scoped_elsewhere(r.meta, current)
    ]


def find_near_duplicates(
    memory_dir: Path,
    rtype: str,
    title: str,
    text: str = "",
    *,
    files=(),
    tags=(),
    threshold: float | None = None,
) -> list[dict]:
    """Live items of `rtype` that the new one would duplicate, most similar first."""
    if rtype not in DEDUP_TYPES:
        return []
    if threshold is None:
        threshold = JOT_DUP_THRESHOLD if rtype == "jot" else DUP_THRESHOLD
    new = _candidate("", rtype, title, text, files, tags)
    if not new["specific"]:
        return []
    hits = []
    for cand in live_candidates(memory_dir, rtype):
        score = similarity(new, cand)
        if score >= threshold:
            hits.append({"id": cand["id"], "title": cand["title"], "similarity": score})
    hits.sort(key=lambda h: (-h["similarity"], h["id"]))
    return hits[:DUP_MAX]


def duplicate_message(duplicates: list[dict], *, allow_supersede: bool = True) -> str:
    """The one-line refusal every CLI writer prints (exit 3)."""
    top = duplicates[0]
    msg = f"looks like {top['id']} ({top['similarity']:.2f} similar)"
    if len(duplicates) > 1:
        msg += " and " + ", ".join(d["id"] for d in duplicates[1:])
    if allow_supersede:
        return (
            f"{msg} — pass --supersedes {top['id']} to replace it, "
            "or --allow-duplicate to write anyway"
        )
    return f"{msg} — pass --allow-duplicate to write it anyway"


def check_supersedes(memory_dir: Path, rtype: str, old_id: str | None) -> str | None:
    """Why `old_id` cannot be superseded by a new `rtype`, or None when it can."""
    if not old_id:
        return None
    item = cli.find_item(Path(memory_dir), old_id)
    if item is None:
        return f"--supersedes {old_id}: no record with that id"
    if item["kind"] != rtype:
        return f"--supersedes {old_id}: that is a {item['kind']}, not a {rtype}"
    # `find_item` reports the lifecycle status for every kind (a verification's
    # outcome lives in `outcome`), so one check covers all: superseding an
    # already-retired record would overwrite its `superseded_by` and orphan the
    # record that replaced it first.
    live = ("open",) if rtype == "question" else ("active",)
    if (item.get("status") or "") not in live:
        return f"--supersedes {old_id}: already {item['status']}"
    return None


def mark_superseded(
    memory_dir: Path, old_ids: list[str], new_id: str, *, agent: str | None = None
) -> list[dict]:
    """Retire each of `old_ids` in favour of `new_id`. Returns each result."""
    results = []
    for old in old_ids:
        item = cli.find_item(Path(memory_dir), old)
        if item is None:
            results.append({"ok": False, "id": old, "error": "not found"})
            continue
        # A question's vocabulary has no `superseded`; `closed` is its word for
        # "no longer the live one", and the pointer still records why.
        status = "closed" if item["kind"] == "question" else "superseded"
        results.append(
            cli.set_record_status(
                Path(memory_dir),
                item["id"],
                status,
                f"superseded by {new_id}",
                agent=agent,
                superseded_by=new_id,
            )
        )
    return results


def demoted_ids(results: list[dict]) -> list[str]:
    """Ids among `mark_superseded` results whose promoted rule was also removed."""
    return [r["id"] for r in results if r.get("ok") and r.get("demoted")]


def near_duplicate_pairs(memory_dir: Path) -> list[dict]:
    """The retrospective sweep: live same-type pairs over the threshold.

    `[{kind, a, b, similarity}]`, most similar first. The write-time gate only
    sees new writes; this is how a store that predates it finds what it already
    holds.
    """
    pairs = []
    for rtype in DEDUP_TYPES:
        cands = live_candidates(memory_dir, rtype)
        if len(cands) > DUP_SWEEP_MAX_ITEMS:
            continue
        threshold = JOT_DUP_THRESHOLD if rtype == "jot" else DUP_THRESHOLD
        for i, a in enumerate(cands):
            for b in cands[i + 1 :]:
                score = similarity(a, b)
                if score >= threshold:
                    x, y = sorted((a["id"], b["id"]))
                    pairs.append({"kind": rtype, "a": x, "b": y, "similarity": score})
    pairs.sort(key=lambda p: (-p["similarity"], p["a"], p["b"]))
    return pairs


# --------------------------------------------------------------------------- #
# Audit findings (WM-31, WM-32, WM-34)
# --------------------------------------------------------------------------- #

AUDIT_EVIDENCE_MISSING_MAX = 20


def audit_findings(memory_dir: Path, root: Path) -> list[dict]:
    """The lifecycle half of `crumb audit`. Every finding is `AUDIT_WARN`."""
    memory_dir = Path(memory_dir)
    findings: list[dict] = []
    live = []
    for rtype in ("decision", "attempt", "verification"):
        live += [r for r in cli.active_records(memory_dir, rtype) if not cli.record_expired(r.meta)]
    missing = missing_evidence_files(root, live)
    for rid, ref in missing[:AUDIT_EVIDENCE_MISSING_MAX]:
        findings.append(
            cli._audit_finding(
                "evidence-missing-file",
                cli.AUDIT_WARN,
                None,
                f"{rid} cites {ref}, which is not in HEAD — verify the record still applies",
                id=rid,
                ref=ref,
            )
        )
    conflicts = find_contradictions(memory_dir)
    for c in conflicts[:AUDIT_CONFLICTS_MAX]:
        findings.append(
            cli._audit_finding(
                "possible-contradiction",
                cli.AUDIT_WARN,
                None,
                c["message"],
                ids=c["ids"],
                rule=c["rule"],
            )
        )
    # A pair already raised as a possible contradiction is not raised again
    # as a near-duplicate: one finding per pair, the more specific one.
    raised = {tuple(sorted(c["ids"])) for c in conflicts}
    pairs = [p for p in near_duplicate_pairs(memory_dir) if (p["a"], p["b"]) not in raised]
    for pair in pairs[:AUDIT_DUP_PAIRS_MAX]:
        findings.append(
            cli._audit_finding(
                "near-duplicates",
                cli.AUDIT_WARN,
                None,
                f"{pair['kind']}s {pair['a']} and {pair['b']} are {pair['similarity']:.2f} "
                "similar — supersede one (`crumb mark-status <id> superseded --superseded-by "
                "<id>`) or merge them (`crumb consolidate`)",
                ids=[pair["a"], pair["b"]],
                similarity=pair["similarity"],
            )
        )
    return findings


# --------------------------------------------------------------------------- #
# WM-33: consolidation
# --------------------------------------------------------------------------- #

# Types `consolidate --merge` writes. Sessions are narratives of work and are
# never merged; traps, questions and jots have their own writers and their own
# retirement (`mark-status`, `inbox promote`), and a merged trap would need the
# block writer's shape at schema 2.
MERGEABLE_TYPES = ("decision", "attempt", "verification", "idea")
_CONFIDENCE_ORDER = {"low": 0, "medium": 1, "high": 2}


def duplicate_clusters(memory_dir: Path, rtype: str | None = None) -> list[dict]:
    """Connected components of the near-duplicate pair graph, biggest first.

    `[{kind, ids, titles{id: title}, pairs[{a, b, similarity}]}]`.
    """
    pairs = [p for p in near_duplicate_pairs(memory_dir) if rtype in (None, p["kind"])]
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.setdefault(x, x) != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for p in pairs:
        parent[find(p["a"])] = find(p["b"])
    groups: dict[str, list[str]] = {}
    for x in parent:
        groups.setdefault(find(x), []).append(x)
    titles: dict[str, str] = {}
    for kind in {p["kind"] for p in pairs}:
        for cand in live_candidates(memory_dir, kind):
            titles[cand["id"]] = cand["title"]
    clusters = []
    for members in groups.values():
        ids = sorted(members)
        kind = next(p["kind"] for p in pairs if p["a"] in ids)
        clusters.append(
            {
                "kind": kind,
                "ids": ids,
                "titles": {i: titles.get(i, "") for i in ids},
                "pairs": [p for p in pairs if p["a"] in ids],
            }
        )
    clusters.sort(key=lambda c: (-len(c["ids"]), c["ids"]))
    return clusters


def merge_records(
    memory_dir: Path,
    root: Path,
    ids: list[str],
    *,
    title: str,
    sections: dict[str, str] | None = None,
    agent: str | None = None,
) -> dict:
    """Write one record that replaces `ids`, then supersede every source.

    Each section is the sources' non-empty text for that heading, oldest first,
    each paragraph prefixed `_(from <id>)_`; `sections` overrides a heading
    outright. Evidence and tags are the unions, confidence the lowest, and
    `supersedes` lists every source. Nothing is merged automatically: this runs
    only when someone names the ids, and it prints a reminder that the merged
    body is a starting point to edit.
    """
    memory_dir = Path(memory_dir)
    ids = list(dict.fromkeys(i.strip() for i in ids if i and i.strip()))
    if len(ids) < 2:
        return {"ok": False, "code": 2, "error": "--merge needs at least two ids"}
    if not (title or "").strip():
        return {"ok": False, "code": 2, "error": "--merge needs --title for the merged record"}
    recs = []
    for rid in ids:
        rec = cli.find_record_by_id(memory_dir, rid)
        if rec is None or rec.error:
            return {"ok": False, "code": 2, "error": f"{rid}: no record with that id"}
        recs.append(rec)
    kinds = {r.rtype for r in recs}
    if len(kinds) > 1:
        return {
            "ok": False,
            "code": 2,
            "error": f"cannot merge different types ({', '.join(sorted(kinds))})",
        }
    rtype = recs[0].rtype
    if rtype not in MERGEABLE_TYPES:
        return {
            "ok": False,
            "code": 2,
            "error": f"consolidate merges {', '.join(MERGEABLE_TYPES)}; not {rtype}s",
        }
    retired = [r.meta.get("id") for r in recs if (r.meta.get("status") or "active") != "active"]
    if retired:
        return {"ok": False, "code": 2, "error": f"already retired: {', '.join(retired)}"}

    recs.sort(key=lambda r: (cli._dt_sort_key(r.meta.get("created_at")), r.stem))
    merged: dict[str, str] = {}
    for heading in cli.BODY_SECTIONS[rtype]:
        parts = []
        for rec in recs:
            text = cli._strip_html_comments(rec.sections.get(heading, "")).strip()
            if text and not cli._is_placeholder(text):
                parts.append(f"_(from {rec.meta.get('id')})_ {text}")
        if parts:
            merged[heading] = "\n\n".join(parts)
    merged.update({k: v for k, v in (sections or {}).items() if v is not None})

    evidence, seen = [], set()
    for rec in recs:
        for e in rec.meta.get("evidence") or []:
            key = (e.get("type"), e.get("ref")) if isinstance(e, dict) else None
            if key and key not in seen:
                seen.add(key)
                evidence.append({"type": key[0], "ref": key[1]})
    tags = sorted({str(t) for rec in recs for t in (rec.meta.get("tags") or [])})
    confidence = min(
        (str(r.meta.get("confidence") or "medium") for r in recs),
        key=lambda c: _CONFIDENCE_ORDER.get(c, 1),
    )
    extra: dict = {"supersedes": [r.meta.get("id") for r in recs]}
    if rtype == "verification":
        newest = recs[-1]
        extra.update(
            {
                "subject": title.strip(),
                "outcome": newest.meta.get("outcome") or "open",
                "method": newest.meta.get("method"),
            }
        )
    try:
        path, meta = cli.write_record(
            memory_dir,
            root,
            rtype,
            title.strip(),
            merged,
            tags=tags,
            evidence=evidence,
            confidence=confidence,
            agent=agent,
            extra=extra,
        )
    except ValueError as exc:
        return {"ok": False, "code": 1, "error": str(exc)}
    fails = cli._validate_new_file(memory_dir, path)
    if fails:
        path.unlink()
        return {
            "ok": False,
            "code": 1,
            "error": "merged record rejected by validate: "
            + "; ".join(f["message"] for f in fails),
        }
    results = mark_superseded(memory_dir, [r.meta.get("id") for r in recs], meta["id"], agent=agent)
    cli.reindex_projections(memory_dir, root)
    return {
        "ok": True,
        "id": meta["id"],
        "type": rtype,
        "path": str(path),
        "supersedes": extra["supersedes"],
        "retired": [r.get("id") for r in results if r.get("ok")],
        "demoted": demoted_ids(results),
    }


# --------------------------------------------------------------------------- #
# WM-34: contradiction detection
# --------------------------------------------------------------------------- #

CONFLICTS_FILENAME = "conflicts.json"
PACKET_CONFLICTS_MAX = 3
AUDIT_CONFLICTS_MAX = 10
# Rule 1: an attempt said "do not retry unless …", and a later decision does
# something close to what it tried.
CONFLICT_RETRY_SIMILARITY = 0.5
# Rule 2: two live decisions this alike, written this far apart, with neither
# superseding the other — the later one may have quietly replaced the earlier.
CONFLICT_DECISION_SIMILARITY = 0.7
CONFLICT_DECISION_MIN_GAP_DAYS = 7


def _section_candidate(rec, heading: str) -> dict:
    return _candidate(
        rec.meta.get("id", rec.stem),
        rec.rtype,
        "",
        cli._strip_html_comments(rec.sections.get(heading, "")),
        cli._evidence_refs(rec, ("file", "path")),
        (),
    )


def _supersede_linked(a, b) -> bool:
    aid, bid = a.meta.get("id"), b.meta.get("id")
    return bid in (a.meta.get("supersedes") or []) or aid in (b.meta.get("supersedes") or [])


def find_contradictions(memory_dir: Path) -> list[dict]:
    """Records that may argue with each other. Two overlap heuristics, worded as questions.

    `[{rule, ids, message, similarity}]`. Deterministic and machine-independent
    — it reads created dates, never "now" — so the committed `conflicts.json`
    does not churn between checkouts.
    """
    memory_dir = Path(memory_dir)
    decisions = [
        r for r in cli.active_records(memory_dir, "decision") if not cli.record_expired(r.meta)
    ]
    attempts = [
        r
        for r in cli.active_records(memory_dir, "attempt")
        if not cli.record_expired(r.meta) and cli._attempt_has_do_not_retry(r)
    ]
    out: list[dict] = []

    for att in attempts:
        tried = _section_candidate(att, "Tried")
        att_at = cli._dt_sort_key(att.meta.get("created_at"))
        for dec in decisions:
            if cli._dt_sort_key(dec.meta.get("created_at")) <= att_at:
                continue
            chose = _section_candidate(dec, "Decision")
            shared_file = bool(tried["files"] & chose["files"])
            union = tried["specific"] | chose["specific"]
            text_sim = (
                round(len(tried["specific"] & chose["specific"]) / len(union), 2) if union else 0.0
            )
            if text_sim < CONFLICT_RETRY_SIMILARITY and not shared_file:
                continue
            did, aid = dec.meta.get("id"), att.meta.get("id")
            out.append(
                {
                    "rule": "retry-after-do-not-retry",
                    "ids": [did, aid],
                    "similarity": text_sim,
                    "message": (
                        f"decision {did} may do what attempt {aid} says not to retry — "
                        "confirm the retry condition was met, or mark one stale"
                    ),
                }
            )

    cands = {candidate_from_record(r)["id"]: candidate_from_record(r) for r in decisions}
    for i, a in enumerate(decisions):
        for b in decisions[i + 1 :]:
            if _supersede_linked(a, b):
                continue
            gap = abs(
                cli._dt_sort_key(a.meta.get("created_at"))
                - cli._dt_sort_key(b.meta.get("created_at"))
            )
            if gap <= CONFLICT_DECISION_MIN_GAP_DAYS * 86400:
                continue
            sim = similarity(cands[a.meta.get("id")], cands[b.meta.get("id")])
            if sim < CONFLICT_DECISION_SIMILARITY:
                continue
            x, y = sorted((a.meta.get("id"), b.meta.get("id")))
            out.append(
                {
                    "rule": "overlapping-decisions",
                    "ids": [x, y],
                    "similarity": sim,
                    "message": (
                        f"decisions {x} and {y} overlap heavily — supersede one or "
                        "consolidate (`crumb consolidate`)"
                    ),
                }
            )
    out.sort(key=lambda c: (c["rule"], -c["similarity"], c["ids"]))
    return out


def render_conflicts(memory_dir: Path, root: Path) -> str:
    """`generated/conflicts.json`, stamped like `related.json`."""
    import json

    doc = {
        "_generated": "GENERATED PROJECTION — do not edit. Rebuilt by `crumb reindex`.",
        "inputs_hash": cli._inputs_hash(Path(memory_dir), Path(root)),
        "conflicts": find_contradictions(memory_dir),
    }
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def conflict_warnings(memory_dir: Path) -> list[str]:
    found = find_contradictions(memory_dir)
    lines = [c["message"] + "." for c in found[:PACKET_CONFLICTS_MAX]]
    if len(found) > PACKET_CONFLICTS_MAX:
        lines.append(
            f"(+{len(found) - PACKET_CONFLICTS_MAX} more possible contradiction(s) — `crumb audit`)"
        )
    return lines


# --------------------------------------------------------------------------- #
# WM-35: session rollup
# --------------------------------------------------------------------------- #


def rollup_candidates(memory_dir: Path, before: str) -> list:
    """Machine-snapshot sessions created before `before` (YYYY-MM-DD), oldest first.

    A session a person or agent wrote — one with a real Next Action — is never
    a candidate: it is the narrative somebody chose to leave, not a snapshot.
    """
    cutoff = cli._dt_sort_key(before)
    recs = [
        r
        for r in cli.load_records(Path(memory_dir), types=("session",))
        if not r.error
        and cli._is_machine_snapshot(r)
        and not (r.meta.get("title") or "").startswith("rollup:")
        and cli._dt_sort_key(r.meta.get("created_at")) < cutoff
    ]
    recs.sort(key=lambda r: (cli._dt_sort_key(r.meta.get("created_at")), r.stem))
    return recs


def rollup_sessions(
    memory_dir: Path,
    root: Path,
    before: str,
    *,
    dry_run: bool = False,
    agent: str | None = None,
) -> dict:
    """Fold old machine snapshots into one session record, then delete them."""
    memory_dir = Path(memory_dir)
    if cli._parse_iso(before) is None:
        return {"ok": False, "code": 2, "error": f"--before {before!r} is not a YYYY-MM-DD date"}
    recs = rollup_candidates(memory_dir, before)
    ids = [r.meta.get("id", r.stem) for r in recs]
    if len(recs) < 2:
        return {"ok": True, "rolled_up": 0, "ids": ids, "dry_run": dry_run, "id": None}
    first = str(recs[0].meta.get("created_at") or "")[:10]
    last = str(recs[-1].meta.get("created_at") or "")[:10]
    title = f"rollup: {first}..{last} ({len(recs)} sessions)"
    if dry_run:
        return {"ok": True, "rolled_up": len(recs), "ids": ids, "dry_run": True, "title": title}
    lines = []
    for rec in recs:
        date = str(rec.meta.get("created_at") or "")[:10]
        work = cli._strip_html_comments(rec.sections.get("Work Completed", "")).strip()
        if work and not cli._is_placeholder(work):
            flat = " ".join(work.split())
            lines.append(f"- {date}: {flat}")
    sections = {
        "Work Completed": "\n".join(lines) or "_(no work recorded in the rolled-up snapshots)_",
        "Next Action": "(rolled up)",
    }
    # The rollup stands where its sources stood: dated, and pinned to the commit,
    # of the last snapshot it replaces. Stamped "now" it would become the newest
    # session record, and the Stop hook diffs from the newest session's commit —
    # every commit made since the last kept snapshot would silently fall out of
    # the next capture.
    newest = recs[-1].meta
    pinned = {k: newest.get(k) for k in ("created_at", "updated_at", "branch", "commit")}
    pinned["dirty_files"] = []
    path, meta = cli.write_record(
        memory_dir,
        root,
        "session",
        title,
        sections,
        agent=agent,
        extra={"supersedes": ids, **{k: v for k, v in pinned.items() if v is not None}},
    )
    fails = cli._validate_new_file(memory_dir, path)
    if fails:
        path.unlink()
        return {
            "ok": False,
            "code": 1,
            "error": "rollup record rejected by validate: "
            + "; ".join(f["message"] for f in fails),
        }
    for rec in recs:
        rec.path.unlink()
    cli.reindex_projections(memory_dir, root)
    return {
        "ok": True,
        "rolled_up": len(recs),
        "ids": ids,
        "dry_run": False,
        "id": meta["id"],
        "path": str(path),
    }
