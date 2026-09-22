"""breadcrumbs — the inbox: short-term memory with no ceremony (WM-03).

Every durable write in this tool asks for a title, body sections, and evidence
or an explicit `--confidence low`. That is the right price for a decision and
the wrong price for "the flaky test is `test_x`; it only fails under `-n auto`".
Observations at that size were simply not written down, which is the discipline
tax that kills tools of this shape.

A **jot** is that observation: one line of text, a TTL, no evidence rule. It is
a candidate for memory, not memory — searchable, listed for the next session,
and either promoted into a real record or left to expire.

**Two inboxes, and the split is a privacy boundary, not a preference.**

- `inbox/` is committed. A human or agent chose to write this (`crumb jot`), or
  promoted it out of the private one.
- `private/inbox/` is gitignored. Everything written *automatically* lands here:
  a hook cannot know whether the prompt it just saw, or the transcript line it
  just mined, contains something the author would not publish. Machine-written
  content earns a commit by being promoted, never by default.

**The committed resume packet lists committed jots only.** A private jot in the
packet would make the packet differ between two checkouts of the same store
while `_inputs_hash` — which cannot read gitignored input without breaking the
same way — still called both fresh. That is precisely the cross-machine
ping-pong `_hashed_input_dirs` exists to prevent. Private jots reach an agent
through `crumb inbox`, and through the hooks that wrote them.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from breadcrumbs import cli

JOT_TYPE = "jot"
INBOX_DIRNAME = "inbox"
PRIVATE_INBOX_RELPATH = "private/inbox"

# How long a jot stays live before it stops being listed. Two weeks is the
# lifespan `current.md` already claims for short-term state, and a jot is
# shorter-lived than that file, not longer. Overridable per store with
# `jot_ttl_days` in manifest.yml.
JOT_TTL_DAYS = cli.JOT_TTL_DAYS_DEFAULT

# A jot is one observation. Past this it is a record that skipped the record
# contract, so the text is cut rather than the write refused — losing what the
# author already wrote is the one outcome worse than a truncated note.
JOT_MAX_CHARS = 600

# What a jot may be promoted into. Defined in `cli` so the argparse choices and
# this validation cannot drift apart. `session` is absent deliberately: a
# session record is a narrative of work that happened, not a durable claim, and
# nothing about a one-line note makes one.
PROMOTE_TARGETS = cli.INBOX_PROMOTE_TARGETS

_WS_RE = re.compile(r"\s+")


# --------------------------------------------------------------------------- #
# Locations
# --------------------------------------------------------------------------- #


def committed_inbox(memory_dir: Path) -> Path:
    return Path(memory_dir) / INBOX_DIRNAME


def private_inbox(memory_dir: Path) -> Path:
    return Path(memory_dir) / "private" / INBOX_DIRNAME


def inbox_dirs(memory_dir: Path) -> list[Path]:
    """Both inbox directories, committed first. Missing ones are included.

    Callers glob these, so a directory that does not exist simply yields nothing
    — a store that has not run `crumb migrate` has no jots rather than an error.
    """
    return [committed_inbox(memory_dir), private_inbox(memory_dir)]


def jot_ttl_days(memory_dir: Path) -> int:
    """The store's jot TTL (`ttl_jot_days`, or the older `jot_ttl_days`)."""
    from breadcrumbs import lifecycle

    return lifecycle.ttl_days(Path(memory_dir), "jot")


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def normalize_jot_text(text: str) -> tuple[str, bool]:
    """Collapse whitespace and cap the length. Returns (text, was_truncated)."""
    flat = _WS_RE.sub(" ", str(text or "")).strip()
    if len(flat) <= JOT_MAX_CHARS:
        return flat, False
    return flat[: JOT_MAX_CHARS - 1].rstrip() + "…", True


def write_jot(
    memory_dir: Path,
    project_root: Path,
    text: str,
    *,
    tags: list[str] | None = None,
    files: list[str] | None = None,
    local: bool = False,
    source: str = "agent",
    agent: str | None = None,
    host_session: str | None = None,
    fingerprint: str | None = None,
    evidence: list[dict] | None = None,
    title: str | None = None,
    scope: str | None = None,
) -> dict:
    """Write one jot. Same write + validate + revert gate as every other record.

    `scope` defaults by who is writing (WM-52): a jot a person or agent writes
    is about the project (`project`); one a hook writes — mined from this
    session's transcript, or a correction — is about the work on this branch
    (`branch`), and leaves the packet when another branch is checked out.

    `files` becomes `evidence: [{type: file, ref: …}]` rather than prose, so the
    guard's *declared file* signal reaches a jot exactly as it reaches a record.
    That is the difference between a note that can be found later and one that
    can only be found by remembering it exists. `evidence` adds refs of any
    other type (a mined candidate carries the command it ran).

    `title` separates what the jot is *called* from what it *says*. They are the
    same string for a typed jot, and different for a mined one, whose note holds
    a snippet of tool output that would make a useless heading.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root)
    flat, truncated = normalize_jot_text(text)
    if not flat:
        return {"ok": False, "error": "a jot needs some text"}

    target_dir = PRIVATE_INBOX_RELPATH if local else INBOX_DIRNAME
    (memory_dir / target_dir).mkdir(parents=True, exist_ok=True)

    created = cli.now_iso()
    expires = _expiry_from(created, jot_ttl_days(memory_dir))
    extra = {
        "source": source,
        "expires_at": expires,
        "host_session": host_session,
        "fingerprint": fingerprint,
    }
    heading, _ = normalize_jot_text(title) if title else (flat, False)
    refs = [{"type": "file", "ref": f} for f in (files or []) if f]
    for ref in evidence or []:
        if isinstance(ref, dict) and ref.get("ref") and ref not in refs:
            refs.append(ref)
    try:
        path, meta = cli.write_record(
            memory_dir,
            project_root,
            JOT_TYPE,
            heading or flat,
            {"Note": flat},
            tags=tags or [],
            evidence=refs,
            # A jot makes no claim it could support with evidence, and is exempt
            # from §16.9 for that reason; `low` is the honest confidence for an
            # unreviewed observation and keeps it from reading as a finding.
            confidence="low",
            privacy="local-private" if local else "repo-safe",
            agent=agent,
            scope=scope or ("project" if source in ("human", "agent") else "branch"),
            extra=extra,
            subdir=target_dir,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    fails = cli._validate_new_file(memory_dir, path)
    if fails:
        path.unlink()
        return {
            "ok": False,
            "error": "jot rejected by validate: " + "; ".join(f["message"] for f in fails),
        }
    cli.reindex_projections(memory_dir, project_root)
    result = {
        "ok": True,
        "kind": JOT_TYPE,
        "id": meta["id"],
        "path": str(path),
        "local": bool(local),
        "expires_at": expires,
        "source": source,
    }
    if truncated:
        result["hint"] = (
            f"text was longer than {JOT_MAX_CHARS} characters and was cut — "
            "a note this long is a record; write it with `crumb remember`"
        )
    return result


def _expiry_from(created_at: str, days: int) -> str | None:
    dt = cli._parse_iso(created_at)
    if dt is None:  # pragma: no cover - created_at is ours and always parseable
        return None
    return (dt + timedelta(days=days)).replace(microsecond=0).isoformat()


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #


def is_expired(rec: "cli.Record") -> bool:
    """Has this jot passed its `expires_at`? A jot with none never expires."""
    age = cli._age_days(rec.meta.get("expires_at"))
    return age is not None and age >= 0


def is_private(memory_dir: Path, rec: "cli.Record") -> bool:
    try:
        rec.path.relative_to(private_inbox(memory_dir))
    except ValueError:
        return False
    return True


def load_jots(
    memory_dir: Path,
    *,
    include_expired: bool = False,
    include_retired: bool = False,
    include_private: bool = True,
) -> list["cli.Record"]:
    """Jots, newest first.

    Default is the live set: active, unexpired, both inboxes. `include_retired`
    brings back promoted (`superseded`) and dropped (`rejected`) jots, which stay
    on disk as history exactly like every other retired record.
    """
    memory_dir = Path(memory_dir)
    out = []
    for rec in cli.load_records(memory_dir, types=(JOT_TYPE,)):
        if rec.error:
            continue
        if not include_private and is_private(memory_dir, rec):
            continue
        if not include_retired and (rec.meta.get("status") or "active") != "active":
            continue
        if not include_expired and is_expired(rec):
            continue
        out.append(rec)
    return cli._by_recency(out)


def jot_text(rec: "cli.Record") -> str:
    """The jot's note, with any audit-trail comment stripped.

    `set_record_status` appends its reason to the body as an HTML comment, which
    is how every retirement in this store records who changed what. For a record
    with prose sections that is invisible; for a jot, whose whole body is one
    line that gets printed verbatim in listings and in the packet, it would show
    up as trailing markup.
    """
    raw = rec.sections.get("Note") or rec.meta.get("title") or ""
    return _WS_RE.sub(" ", cli._HTML_COMMENT_RE.sub("", raw)).strip()


def jot_title(rec: "cli.Record") -> str:
    """The jot's headline: its frontmatter title, else its note."""
    title = str(rec.meta.get("title") or "").strip()
    return title or jot_text(rec)


def jot_rows(memory_dir: Path, **kwargs) -> list[dict]:
    """`load_jots` as plain dicts for `--json` and the human listing."""
    memory_dir = Path(memory_dir)
    rows = []
    for rec in load_jots(memory_dir, **kwargs):
        rows.append(
            {
                "id": rec.meta.get("id") or rec.stem,
                # `title` is the headline, `text` the body. They are the same
                # string for a jot somebody typed and different for a mined one,
                # whose body holds a snippet of tool output — so every listing
                # shows the title and leaves the detail to `crumb show`.
                "title": jot_title(rec),
                "text": jot_text(rec),
                "source": rec.meta.get("source") or "unknown",
                "status": rec.meta.get("status") or "active",
                "local": is_private(memory_dir, rec),
                "age_days": cli._age_days(rec.meta.get("created_at")),
                "expires_at": rec.meta.get("expires_at"),
                "expired": is_expired(rec),
                "tags": rec.meta.get("tags") or [],
                "scope": str(rec.meta.get("scope") or "project"),
                "branch": rec.meta.get("branch"),
                "path": str(rec.path),
            }
        )
    return rows


def find_jot(memory_dir: Path, jot_id: str) -> "cli.Record | None":
    jot_id = (jot_id or "").strip()
    for rec in cli.load_records(Path(memory_dir), types=(JOT_TYPE,)):
        if rec.error:
            continue
        if (rec.meta.get("id") or rec.stem) == jot_id:
            return rec
    return None


def packet_jots(memory_dir: Path) -> list[dict]:
    """The Inbox section of the resume packet: committed, live jots only.

    Private jots are excluded — see this module's docstring. This is the one
    reader where that matters, because its output is a committed file. A
    branch-scoped jot from another branch is excluded too (WM-52).
    """
    memory_dir = Path(memory_dir)
    current = cli.git_branch(memory_dir.parent)
    keep = {
        rec.meta.get("id") or rec.stem
        for rec in load_jots(memory_dir, include_private=False)
        if not cli.branch_scoped_elsewhere(rec.meta, current)
    }
    return [row for row in jot_rows(memory_dir, include_private=False) if row["id"] in keep]


# --------------------------------------------------------------------------- #
# Promotion / drop
# --------------------------------------------------------------------------- #


def promote_jot(
    memory_dir: Path,
    project_root: Path,
    jot_id: str,
    target: str,
    *,
    title: str | None = None,
    sections: dict[str, str] | None = None,
    evidence: list[dict] | None = None,
    tags: list[str] | None = None,
    confidence: str | None = None,
    fields: dict | None = None,
    status: str | None = None,
    method: str | None = None,
    agent: str | None = None,
) -> dict:
    """Turn a jot into a durable record, then supersede the jot.

    Promotion goes through the *existing* writer for the target type, so the
    evidence rule, the body vocabulary and the validate gate all apply exactly as
    they would to a record written by hand. A jot is a shortcut into memory, not
    a shortcut around its contract.

    The jot is marked `superseded` with `superseded_by` pointing at the new
    record rather than deleted: that is how every other retirement in this store
    works, and it leaves the trail from the one-line observation to the record it
    became. Promoting a *private* jot is what moves its content into committed
    memory; the jot file itself stays private.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root)
    if target not in PROMOTE_TARGETS:
        return {
            "ok": False,
            "error": f"unknown promote target {target!r}; use {', '.join(PROMOTE_TARGETS)}",
        }
    rec = find_jot(memory_dir, jot_id)
    if rec is None:
        return {"ok": False, "error": f"no jot with id {jot_id!r}"}
    if (rec.meta.get("status") or "active") != "active":
        return {
            "ok": False,
            "error": f"{jot_id} is already {rec.meta.get('status')}; only an active jot promotes",
        }

    new_title = (title or jot_title(rec)).strip()
    # The jot's own file evidence and tags carry over: they are what made it
    # findable, and a promotion that dropped them would produce a record the
    # guard can reach less well than the note it replaced.
    merged_evidence = list(rec.meta.get("evidence") or []) + list(evidence or [])
    merged_tags = sorted({*(rec.meta.get("tags") or []), *(tags or [])})

    if target in ("decision", "attempt", "idea"):
        result = _promote_to_record(
            memory_dir,
            project_root,
            target,
            new_title,
            sections or {},
            evidence=merged_evidence,
            tags=merged_tags,
            confidence=confidence,
            agent=agent,
        )
    elif target == "verification":
        result = cli.verify(
            memory_dir,
            project_root,
            new_title,
            status=status or "open",
            method=method,
            note=(sections or {}).get("Notes"),
            evidence=merged_evidence,
            tags=merged_tags,
            confidence=confidence,
            agent=agent,
        )
    else:  # trap | question
        result = cli.note(
            memory_dir,
            project_root,
            target,
            new_title,
            fields=fields or {},
            tags=merged_tags,
            agent=agent,
        )
    if not result.get("ok"):
        return result

    new_id = result.get("id") or result.get("ref")
    marked = cli.set_record_status(
        memory_dir,
        rec.meta.get("id") or rec.stem,
        "superseded",
        reason=f"promoted to {new_id}",
        superseded_by=new_id,
        agent=agent,
    )
    out = {
        "ok": True,
        "jot": rec.meta.get("id") or rec.stem,
        "promoted_to": new_id,
        "type": target,
        "path": result.get("path"),
    }
    if not marked.get("ok"):
        # The record exists and is valid; only the back-reference failed. Say so
        # rather than claiming a clean promotion — a jot left active will be
        # offered for promotion again.
        out["warning"] = (
            f"{new_id} was written, but the jot could not be marked superseded: "
            f"{marked.get('error')}"
        )
    cli.reindex_projections(memory_dir, project_root)
    return out


def _promote_to_record(
    memory_dir: Path,
    project_root: Path,
    rtype: str,
    title: str,
    sections: dict[str, str],
    *,
    evidence: list[dict],
    tags: list[str],
    confidence: str | None,
    agent: str | None,
) -> dict:
    """`remember`'s write path, reused: write, validate, revert on failure."""
    try:
        path, meta = cli.write_record(
            memory_dir,
            project_root,
            rtype,
            title,
            sections,
            tags=tags,
            evidence=evidence,
            confidence=confidence,
            agent=agent,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    fails = cli._validate_new_file(memory_dir, path)
    if fails:
        path.unlink()
        return {
            "ok": False,
            "error": (
                f"{rtype} rejected by validate: "
                + "; ".join(f["message"] for f in fails)
                + " — pass --evidence or --confidence low"
            ),
        }
    return {"ok": True, "id": meta["id"], "path": str(path), "type": rtype}


def drop_jot(
    memory_dir: Path,
    project_root: Path,
    jot_id: str,
    *,
    reason: str | None = None,
    agent: str | None = None,
) -> dict:
    """Retire a jot as noise. `rejected`, not deleted — `prune` deletes."""
    rec = find_jot(Path(memory_dir), jot_id)
    if rec is None:
        return {"ok": False, "error": f"no jot with id {jot_id!r}"}
    result = cli.set_record_status(
        Path(memory_dir),
        rec.meta.get("id") or rec.stem,
        "rejected",
        reason=reason or "dropped from the inbox as noise",
        agent=agent,
    )
    if result.get("ok"):
        cli.reindex_projections(Path(memory_dir), Path(project_root))
    return result


# --------------------------------------------------------------------------- #
# Retention
# --------------------------------------------------------------------------- #

# A jot is deleted only well after it stopped being listed. Expiry hides it;
# this deletes it. The gap exists so `crumb inbox --expired` can still show what
# was missed, and so a promotion trail survives long enough to be read.
PRUNE_JOTS_AFTER_DAYS = 30


def prune_jots(
    memory_dir: Path,
    project_root: Path,
    *,
    after_days: int = PRUNE_JOTS_AFTER_DAYS,
    dry_run: bool = False,
) -> dict:
    """Delete jots that are expired or retired and older than `after_days`.

    An active, unexpired jot is never deleted however old the store is — it is
    still waiting for somebody to promote or drop it, and deleting an unanswered
    question is not this command's call.
    """
    memory_dir = Path(memory_dir)
    deleted: list[str] = []
    total = 0
    for rec in cli.load_records(memory_dir, types=(JOT_TYPE,)):
        if rec.error:
            continue
        total += 1
        age = cli._age_days(rec.meta.get("created_at"))
        if age is None or age < after_days:
            continue
        retired = (rec.meta.get("status") or "active") != "active"
        if not (retired or is_expired(rec)):
            continue
        if not dry_run:
            rec.path.unlink()
        deleted.append(rec.meta.get("id") or rec.stem)
    if deleted and not dry_run:
        cli.reindex_projections(memory_dir, project_root)
    return {
        "jots": total,
        "kept": total - (0 if dry_run else len(deleted)),
        "deleted": deleted,
        "dry_run": dry_run,
        "after_days": after_days,
    }
