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

import hashlib
import re
from datetime import timedelta
from pathlib import Path

from breadcrumbs import cli, path_policy
from breadcrumbs import validation as _validation

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
    path_policy.mkdirs(memory_dir / target_dir)

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
    # A machine-local jot changes no shared view (audit WP15). The committed
    # packet, the guard pre-filter, related/conflicts and the search index are
    # all built from committed directories only, and the index's freshness is
    # the content hash of those. Local jots are read directly by every lookup
    # that includes them. So local capture does not pay for a publication.
    if not local:
        cli.reindex_projections(memory_dir, project_root)
    result = {
        "ok": True,
        "kind": JOT_TYPE,
        "id": meta["id"],
        "path": str(path),
        "local": bool(local),
        "expires_at": expires,
        "source": source,
        "scope": meta.get("scope") or "project",
    }
    if truncated:
        result["hint"] = (
            f"text was longer than {JOT_MAX_CHARS} characters and was cut — "
            "a note this long is a record; write it with `crumb remember`"
        )
    return result


def _expiry_from(created_at: str, days: int) -> str | None:
    dt = _validation.parse_timestamp(created_at)
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


# Where a jot's text lands in the record it becomes (audit F03). With no
# sections given, the note *is* the body, in the section the resume packet
# reads for that type (a decision's `Decision`) or, where the only packet
# section would claim a cause the note never stated (an attempt's `Why It
# Failed`), in the neutral one. With sections given, the note is kept as a
# provenance paragraph in `_SOURCE_SECTION` unless a section already quotes it.
_PRIMARY_SECTION = {"decision": "Decision", "attempt": "Result", "idea": "Idea"}
_SOURCE_SECTION = {"decision": "Context", "attempt": "Problem", "idea": "Motivation"}


def _source_line(jot_id: str, text: str) -> str:
    return f"From jot {jot_id}: {text}"


def _carry_text(rtype: str, sections: dict, jot_id: str, text: str) -> dict:
    """`sections` with the jot's text guaranteed to be in them."""
    sections, _notes = cli.normalize_sections(rtype, sections or {})
    filled = {k: v for k, v in sections.items() if str(v or "").strip()}
    if not filled:
        return {_PRIMARY_SECTION[rtype]: text}
    if any(text in str(v) for v in filled.values()):
        return filled
    key = _SOURCE_SECTION[rtype]
    line = _source_line(jot_id, text)
    filled[key] = f"{filled[key].rstrip()}\n\n{line}" if filled.get(key) else line
    return filled


def _carry_into(existing: str | None, jot_id: str, text: str) -> str:
    """A single notes field that keeps the jot's text (verification, trap, question)."""
    existing = (existing or "").strip()
    if not existing:
        return text
    if text in existing:
        return existing
    return f"{existing} {_source_line(jot_id, text)}"


def jot_digest(text: str) -> str:
    """The revision of a jot's note a promoted record was made from."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


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
    scope: str | None = None,
    allow_duplicate: bool = False,
    supersedes: str | None = None,
) -> dict:
    """Turn a jot into a durable record, then supersede the jot.

    Promotion goes through the *existing* writer for the target type, so the
    evidence rule, the body vocabulary, the near-duplicate gate and the validate
    gate all apply exactly as they would to a record written by hand. A jot is a
    shortcut into memory, not a shortcut around its contract.

    **It preserves meaning (audit F03).** The new record carries:

    - the jot's full note, as its body or as a provenance paragraph beside the
      sections the caller wrote;
    - its source, as `promoted_from` and `promoted_from_digest`;
    - its scope and confidence.

    Widening `branch` to `project`, or raising confidence, happens only when the
    caller asks for it (`scope=`, `confidence=`), and the result reports it.

    The jot is marked `superseded` with `superseded_by` pointing at the new
    record, and only after the new record is written and valid. It is never
    deleted: that is how every other retirement in this store works, and it
    leaves the trail from the one-line observation to the record it became.

    Promoting a *private* jot is what moves its content into committed memory.
    The result says so (`from_private`), and a note carrying a structured
    credential is refused rather than published. The jot file itself stays
    private.
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

    source_id = rec.meta.get("id") or rec.stem
    text = jot_text(rec)
    new_title = (title or jot_title(rec)).strip()
    private = is_private(memory_dir, rec)
    if private and cli.secret_pattern_hits(f"{text}\n{new_title}"):
        return {
            "ok": False,
            "error": f"{source_id} carries a credential-shaped string; promoting it would "
            "publish that into committed memory, so it stays private. Promote with "
            "--title and --set text that leaves the secret out, or drop the jot.",
        }
    jot_scope = str(rec.meta.get("scope") or "project")
    new_scope = scope or jot_scope
    new_confidence = confidence or str(rec.meta.get("confidence") or "low")
    provenance = {"promoted_from": source_id, "promoted_from_digest": jot_digest(text)}

    # The jot's own file evidence and tags carry over: they are what made it
    # findable, and a promotion that dropped them would produce a record the
    # guard can reach less well than the note it replaced.
    merged_evidence = list(rec.meta.get("evidence") or [])
    for ref in evidence or []:
        if ref not in merged_evidence:
            merged_evidence.append(ref)
    merged_tags = sorted({*(rec.meta.get("tags") or []), *(tags or [])})

    from breadcrumbs import mutations as _mutations

    # The target record, anything it supersedes, and the jot's retirement are
    # one change (audit F20): the jot is retired only if the rest held, and a
    # failure anywhere leaves the store as it was.
    try:
        with _mutations.transaction(memory_dir, "inbox-promote"):
            if target in ("decision", "attempt", "idea"):
                result = _promote_to_record(
                    memory_dir,
                    project_root,
                    target,
                    new_title,
                    _carry_text(target, sections or {}, source_id, text),
                    evidence=merged_evidence,
                    tags=merged_tags,
                    confidence=new_confidence,
                    scope=new_scope,
                    agent=agent,
                    extra=provenance,
                    allow_duplicate=allow_duplicate,
                    supersedes=supersedes,
                )
            elif target == "verification":
                result = cli.verify(
                    memory_dir,
                    project_root,
                    new_title,
                    status=status or "open",
                    method=method,
                    note=_carry_into((sections or {}).get("Notes"), source_id, text),
                    evidence=merged_evidence,
                    tags=merged_tags,
                    confidence=new_confidence,
                    agent=agent,
                    scope=new_scope,
                    extra=provenance,
                    dedupe=not allow_duplicate,
                    supersedes=supersedes,
                )
            else:  # trap | question
                fields = {k: v for k, v in (fields or {}).items() if v not in (None, "")}
                quoted = text == new_title or any(text in str(v) for v in fields.values())
                if not quoted:
                    fields["notes"] = _carry_into(fields.get("notes"), source_id, text)
                fields["meta"] = {"scope": new_scope, "confidence": new_confidence, **provenance}
                result = cli.note(
                    memory_dir,
                    project_root,
                    target,
                    new_title,
                    fields=fields,
                    tags=merged_tags,
                    agent=agent,
                    dedupe=not allow_duplicate,
                    supersedes=supersedes,
                )
            if not result.get("ok"):
                return result  # the jot stays live: nothing was promoted

            new_id = result.get("id") or result.get("ref")
            marked = cli.set_record_status(
                memory_dir,
                source_id,
                "superseded",
                reason=f"promoted to {new_id}",
                superseded_by=new_id,
                agent=agent,
            )
            if not marked.get("ok"):
                # A record written while its jot stays live would be offered for
                # promotion again and promoted twice: the whole promotion is undone.
                raise _mutations.MutationFailed(
                    f"{new_id} was written, but {source_id} could not be marked superseded: "
                    f"{marked.get('error')}"
                )
    except _mutations.MutationFailed as exc:
        return {"ok": False, "jot": source_id, "error": _mutations.describe(exc)}
    out = {
        "ok": True,
        "jot": source_id,
        "promoted_to": new_id,
        "type": target,
        "path": result.get("path"),
        "scope": new_scope,
        "confidence": new_confidence,
        "from_private": private,
        "scope_widened": jot_scope == "branch" and new_scope == "project",
    }
    for key in ("supersedes", "demoted"):
        if result.get(key):
            out[key] = result[key]
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
    scope: str | None,
    agent: str | None,
    extra: dict,
    allow_duplicate: bool,
    supersedes: str | None,
) -> dict:
    """`remember`'s write path, reused: duplicate gate, write, validate, revert on failure."""
    from breadcrumbs import lifecycle as _lifecycle

    problem = _lifecycle.check_supersedes(memory_dir, rtype, supersedes)
    if problem:
        return {"ok": False, "error": problem}
    if not supersedes and not allow_duplicate:
        dups = _lifecycle.find_near_duplicates(
            memory_dir,
            rtype,
            title,
            "\n".join(str(v) for v in sections.values()),
            files=[
                e["ref"]
                for e in evidence
                if isinstance(e, dict) and e.get("type") in ("file", "path")
            ],
            tags=tags or (),
        )
        if dups:
            return {
                "ok": False,
                "error": "near-duplicate",
                "duplicates": dups,
                "message": _lifecycle.duplicate_message(dups),
            }
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
            scope=scope,
            agent=agent,
            extra={**extra, "supersedes": [supersedes] if supersedes else None},
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
    out = {"ok": True, "id": meta["id"], "path": str(path), "type": rtype}
    if supersedes:
        results = _lifecycle.retire_all(memory_dir, [supersedes], meta["id"], agent=agent)
        out["supersedes"] = [supersedes]
        if _lifecycle.demoted_ids(results):
            out["demoted"] = _lifecycle.demoted_ids(results)
    return out


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


def prune_private_jots(memory_dir: Path, *, after_days: int = PRUNE_JOTS_AFTER_DAYS) -> int:
    """`prune_jots`, for machine-local jots only, run by the SessionStart hook.

    Same rule (expired or retired, and older than `after_days`), but nothing
    committed is touched and nothing is republished: a private jot is not an
    input to any committed projection. Returns how many were deleted.
    """
    memory_dir = Path(memory_dir)
    if not private_inbox(memory_dir).is_dir():
        return 0
    deleted = 0
    for rec in cli.load_records(memory_dir, types=(JOT_TYPE,)):
        if rec.error or not is_private(memory_dir, rec):
            continue
        age = cli._age_days(rec.meta.get("created_at"))
        if age is None or age < after_days:
            continue
        retired = (rec.meta.get("status") or "active") != "active"
        if retired or is_expired(rec):
            try:
                rec.path.unlink()
                deleted += 1
            except OSError:
                continue
    return deleted


# --------------------------------------------------------------------------- #
# Drafts: notes left by an agent that could not run the CLI
# --------------------------------------------------------------------------- #

DRAFTS_DIRNAME = "drafts"


def drafts_dir(memory_dir: Path) -> Path:
    """`inbox/drafts/`: where an agent without the CLI leaves free-form notes.

    `validate` and every reader ignore it (records are read one directory
    deep), so a note there can be any shape. Hand-written *records* were the
    other option, and in the field 133 of them failed validation and were
    dropped or misread (DoWhat field report 2026-10-01, issue 12).
    """
    return Path(memory_dir) / "inbox" / DRAFTS_DIRNAME


def import_drafts(memory_dir: Path, project_root: Path, *, agent: str | None = None) -> dict:
    """Turn each `inbox/drafts/*.md` into a jot. `{imported, kept, failed}`.

    A draft that fits in a jot is removed once its jot is written. A longer one
    is kept where it is (the jot cites it as file evidence), so nothing a
    person wrote is cut short.
    """
    import re

    memory_dir = Path(memory_dir)
    out: dict = {"imported": [], "kept": [], "failed": []}
    directory = drafts_dir(memory_dir)
    if not directory.is_dir():
        return out
    for path in sorted(directory.glob("*.md")):
        raw = path_policy.read_text(path)
        heading = re.search(r"(?m)^#\s+(.+?)\s*$", raw)
        body = re.sub(r"(?m)^#\s+.+$", "", raw).strip()
        title = (heading.group(1) if heading else "").strip() or None
        text = " ".join((body or title or "").split())
        if not text:
            continue
        rel = path.relative_to(memory_dir.parent).as_posix()
        long = len(text) > JOT_MAX_CHARS
        result = write_jot(
            memory_dir,
            project_root,
            text,
            title=title,
            agent=agent,
            source="draft",
            scope="project",
            files=[rel] if long else None,
        )
        if not result.get("ok"):
            out["failed"].append({"draft": rel, "error": result.get("error") or "rejected"})
            continue
        entry = {"draft": rel, "id": result.get("id")}
        if long:
            out["kept"].append(entry)
        else:
            path.unlink()
            out["imported"].append(entry)
    return out
