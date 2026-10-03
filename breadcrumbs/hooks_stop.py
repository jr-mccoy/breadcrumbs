"""breadcrumbs — the `Stop` hook: the session snapshot and the extraction ask.

Claude Code fires `Stop` every time the agent finishes a turn. A firing does
one of three things:

- **nothing**, when no work moved since the newest session record (the same
  HEAD, apart from commits that touch only the memory store, and the same
  dirty files);
- **asks once**, when the turn landed commits this session made (or mined
  enough candidates): it blocks with an instruction to capture, and records
  the HEAD it asked at so the same commits are never asked about twice;
- **snapshots**, otherwise: a machine-written session record of where the
  work stands, coalesced into this session's own snapshot when it can be.

Moved out of `cli.py` (health review 2.1). `cli.cmd_hook` dispatches here.
"""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from breadcrumbs import cli
from breadcrumbs import git as _git


def _hook_capture_is_redundant(memory_dir: Path, root: Path) -> bool:
    """True when nothing has moved since the newest session record.

    Claude Code's `Stop` fires every time the agent finishes responding — every
    turn, not once per session — so an unconditional capture floods `sessions/`
    with near-empty records. A firing earns a record only when the work moved:
    a different HEAD commit, or a different set of dirty working-tree files.
    """
    rec = cli._newest_session_record(memory_dir)
    if rec is None or rec.error:
        return False
    recorded = rec.meta.get("dirty_files")
    if not isinstance(recorded, list):
        return False
    head = _git.head(root) or cli.NO_GIT_COMMIT
    if not _git.same_commit(rec.meta.get("commit") or "", head):
        # HEAD moved — but a commit that touches only the memory store (the
        # agent committing the previous snapshot, or its own capture) is not
        # work. Re-snapshotting on it rewrote the record with the sha of the
        # commit that committed it, which left the store dirty again, which
        # the agent committed again: the tree could never settle (0.6.0).
        if _work_commits_between(root, rec.meta.get("commit") or "", head):
            return False
    # The record holds the capped list (`derive_fields`), so compare with the
    # live list capped the same way: comparing a capped list with an uncapped
    # one made every firing with more than DIRTY_FILES_MAX dirty files look
    # like new work, and re-snapshot every turn (field report 2026-10-01, N5).
    live = cli._cap_dirty_files(cli.git_dirty_files(root, include_memory=False))
    return cli._work_dirty_files(recorded) == cli._work_dirty_files(live)


def _work_commits_between(root: Path, base: str, head: str) -> bool:
    """True when `base..head` holds a commit touching anything outside the
    memory store — the same filter `_session_commits` applies. A base this
    clone cannot resolve (rebase, shallow fetch) counts as work: there is no
    honest way to say nothing moved."""
    if not base or not head or cli.NO_GIT_COMMIT in (base, head):
        return True
    out = _git.run(
        root, "log", "--format=%H", f"{base}..{head}", "--", ".", f":(exclude){cli.MEMORY_DIRNAME}"
    )
    return out is None or bool(out.strip())


def _extraction_enabled(memory_dir: Path) -> bool:
    """Manifest kill switch for the Stop-hook extraction prompt (default on)."""
    manifest = cli.load_manifest(memory_dir) or {}
    raw = str(manifest.get("extraction_prompt", "true")).strip().lower()
    return raw not in ("false", "no", "off", "0")


# The extraction prompt fires only when the ending turn produced new commits —
# a proportional trigger: chunky agent turns that landed real work get asked
# once; small interactive turns (edits with no commit) only get the silent
# snapshot. Bound mirrors the capture window's philosophy (never dump a wall).
EXTRACTION_MAX_COMMITS_SHOWN = 5


# A commit authored this long before the session started is not the session's
# work (a fast-forward `git pull` of other people's commits); the margin
# absorbs clock skew between the commit's machine and this one.
EXTRACTION_AUTHOR_MARGIN_SECONDS = 120


def _session_commits(memory_dir: Path, root: Path, session_id: str) -> list[str]:
    """One-line subjects of the commits this session made since it was last asked.

    Counted from the HEAD the session started on (SessionStart records it), not
    from the newest session record in the store, which may be another session's
    or another machine's from days ago (field report 2026-10-01, issue 2).

    - No baseline yet (SessionStart not installed, or a session that predates
      it): this firing records one and asks nothing.
    - HEAD is not a descendant of the baseline (an amend, a rebase, a
      `pull --rebase`): count from where the two histories meet, keeping only
      commits authored after the last ask (an amend or a rebase keeps the
      author time, so a rewritten copy of a commit already asked about is not
      asked about again). Before 0.6.0 this re-baselined silently, and the
      rewritten work was never asked about. No common history at all (a
      checkout of an unrelated branch, a reset to a gone commit): re-baseline.
    - Commits that touch only the memory store, and commits authored before
      the session started (pulled history), are not the session's work.

    The caller advances the baseline to HEAD once it has asked, so the same
    commits are never asked about twice, whatever the agent then does (issue 3).
    """
    from breadcrumbs import hooks_common

    if not _git.is_repo(root):
        return []
    head = _git.head(root)
    if not head:
        return []
    entry = hooks_common.session_baseline(memory_dir, session_id)
    base = entry.get("head")
    if not base:
        hooks_common.set_session_baseline(memory_dir, session_id, head)
        return []
    if base == head:
        return []
    asked = None  # set only when history was rewritten under the baseline
    rewritten = False
    if _git.run(root, "merge-base", "--is-ancestor", base, head) is None:
        fork = (_git.run(root, "merge-base", base, head) or "").strip()
        if not fork:
            hooks_common.set_session_baseline(memory_dir, session_id, head)
            return []
        base, rewritten = fork, True
        asked = _epoch(entry.get("asked_at"))
    out = _git.run(
        root,
        "log",
        "--no-decorate",
        "--format=%at %H %h %s",
        f"{base}..{head}",
        "--",
        ".",
        f":(exclude){cli.MEMORY_DIRNAME}",
    )
    started = _epoch(entry.get("started_at"))
    made_here = _commits_made_here(root) if out else None
    lines: list[str] = []
    for line in (out or "").splitlines():
        stamp, _, rest = line.strip().partition(" ")
        full, _, rest = rest.partition(" ")
        if not rest:
            continue
        if started is not None and stamp.isdigit():
            if int(stamp) < started - EXTRACTION_AUTHOR_MARGIN_SECONDS:
                continue
        # Local commits on a local clock: no skew margin. A commit authored at
        # or before the ask is one the ask already covered.
        if asked is not None and stamp.isdigit() and int(stamp) <= asked:
            continue
        if made_here is not None and full not in made_here:
            continue
        lines.append(rest)
    if not lines and rewritten:
        # Nothing new on the rewritten history: count from it from now on.
        hooks_common.set_session_baseline(memory_dir, session_id, head)
    return lines


# Reflog actions that create a commit in this checkout. Everything else that
# moves HEAD (`pull: Fast-forward`, `merge`, `reset`, `checkout`, `clone`)
# brings in commits someone else made.
_LOCAL_COMMIT_ACTIONS = ("commit", "cherry-pick", "revert", "rebase", "am")


_REFLOG_SCAN = 2000


def _commits_made_here(root: Path) -> set[str] | None:
    """Full shas HEAD's reflog says were created in this checkout, or None
    when there is no reflog to ask (then every commit in range counts).

    A `git pull` of a commit a cloud session made *after* this session started
    passed the author-time filter, and the Stop hook asked about it as this
    session's work (DoWhat retest of 0.5.0, F1). The reflog tells the two apart:
    a local commit is logged as `commit: …`, a pulled one arrives by `pull:`.
    """
    out = _git.run(root, "reflog", "show", f"-n{_REFLOG_SCAN}", "--format=%H%x09%gs", "HEAD")
    if not out:
        return None
    made: set[str] = set()
    for line in out.splitlines():
        sha, _, action = line.partition("\t")
        verb = action.strip().lower()
        if "(start)" in verb or "(abort)" in verb:
            continue  # a rebase's start checks out the upstream: not made here
        if verb.startswith(_LOCAL_COMMIT_ACTIONS) or (
            verb.startswith("pull") and "--rebase" in verb and "(pick)" in verb
        ):
            made.add(sha.strip())
    return made


def _epoch(stamp) -> int | None:
    from breadcrumbs import validation as _validation

    when = _validation.parse_timestamp(stamp) if stamp else None
    return int(when.timestamp()) if when is not None else None


# Mined candidates the extraction prompt lists. Six is enough to cover a busy
# session's real findings; beyond that the prompt stops being a request and
# becomes a backlog.
EXTRACTION_MAX_JOTS_SHOWN = 6


# Mined candidates that, on their own, earn an extraction turn even with no
# commits. One failed-then-fixed command is a real finding; three notes of any
# kind means the session produced enough to be worth a minute.
EXTRACTION_MIN_ATTEMPT_JOTS = 1


EXTRACTION_MIN_SESSION_JOTS = 3


def _extraction_reason(commits: list[str], session_jots: list[dict] | None = None) -> str:
    """The block message: a concrete, one-shot instruction to persist memory.

    This is the agent-as-author moment — the request lands while the model
    still holds the session's "why", instead of relying on a standing signpost
    it read hundreds of turns ago. `capture session` is the last step, so
    completing the instruction is exactly what clears it (a re-firing Stop sees
    the fresh session record as redundant and stays silent).

    When the miner found candidates, they are listed with their ids. That turns
    the request from "compose a record about what just happened" — expensive,
    at the moment the model has least context left — into "promote this one, drop
    that one", which is a judgement it can still make cheaply and well.
    """
    parts: list[str] = []
    if commits:
        shown = commits[:EXTRACTION_MAX_COMMITS_SHOWN]
        extra = len(commits) - len(shown)
        listing = "\n".join(f"  {c}" for c in shown)
        if extra > 0:
            listing += f"\n  … and {extra} more"
        # "landed", not "this turn produced": the range is HEAD-based, and the
        # workspace may be shared with other terminals/agents (P1-7) —
        # attributing someone else's commit to the agent would ask it to
        # describe work it never did. The instruction below scopes recording to
        # the session's own work.
        parts.append(
            f"breadcrumbs: {len(commits)} new commit(s) since this session started "
            f"(or since it was last asked) — this session's work, or another actor's "
            f"if the workspace is shared:\n{listing}"
        )
    else:
        parts.append(
            "breadcrumbs: this session produced findings worth keeping, though no commits landed."
        )

    jots = list(session_jots or [])[:EXTRACTION_MAX_JOTS_SHOWN]
    if jots:
        rows = "\n".join(f"  {j['id']} [{j.get('kind', 'note')}] {j['text']}" for j in jots)
        parts.append(
            "Candidates mined from this session (unconfirmed; each is a private jot):\n"
            f"{rows}\n"
            "Promote what is durable:  `crumb inbox promote <jot id> "
            "attempt|verification|trap --evidence commit <sha>`\n"
            "Drop what is noise:       `crumb inbox drop <jot id>`"
        )

    parts.append(
        "Before stopping, persist what the next session cannot rediscover — from "
        "this session's own work only; skip commits you did not make:\n"
        '1. A durable choice made here -> `crumb remember decision --title "…" '
        '--set Decision "…" --evidence commit <sha>`\n'
        '2. An approach tried that failed -> `crumb remember attempt --title "…" '
        '--result "…" --do-not-retry "…" --evidence commit <sha>`\n'
        '3. Something checked against reality -> `crumb verify "<subject>" '
        '--status fixed|open|regressed --evidence command "<cmd>"`\n'
        "4. A record this session contradicted -> `crumb mark-status <id> "
        'stale --reason "…"`\n'
        "A write refused with exit 3 is a near-duplicate: pass `--supersedes <id>` "
        "to replace that record, or `--allow-duplicate` to keep both.\n"
        'Finish with `crumb capture session --next "<the next concrete action — cite '
        'a commit sha or file so the claim stays checkable>"`; it adds an entry above '
        "the handoff's earlier ones and replaces nothing. "
        "Record durable facts only — routine work needs no records; if nothing "
        "durable happened, run just the final capture command. You will not be "
        "asked about these commits again."
    )
    return "\n".join(parts)


def _session_jot_rows(memory_dir: Path, session_id: str) -> list[dict]:
    """Live machine-local jots this session produced, newest first.

    What the extraction prompt offers for promotion. Scoped by `host_session`
    so one terminal never asks an agent to triage another's findings.
    """
    try:
        from breadcrumbs import inbox as _inbox

        rows = []
        for rec in _inbox.load_jots(memory_dir):
            if rec.meta.get("host_session") != session_id:
                continue
            tags = rec.meta.get("tags") or []
            kind = next(
                (t for t in tags if t in ("attempt", "verification", "trap", "correction")), "note"
            )
            rows.append(
                {
                    "id": rec.meta.get("id") or rec.stem,
                    "text": _inbox.jot_title(rec)[:140],
                    "kind": kind,
                    "tags": tags,
                }
            )
        return rows
    except Exception:  # pragma: no cover - the prompt degrades to commits-only
        return []


def _hook_capture_snapshot(root: Path, host_session: str | None = None) -> str:
    """The machine snapshot: the same --fast path the CLI uses (diff-stat already
    summarized). The Next Action is placeholder text (`_is_placeholder` knows
    it), so this capture cannot clobber a Next Action / Focus a human set.

    `host_session` is the harness's session id from the Stop payload. It is what
    lets the second and later firings of one session update the first firing's
    snapshot instead of stacking a new record beside it (F-6).

    Returns `"ok"` or `"failed: <why>"` for the hook log. It used to swallow
    every failure, so a snapshot that never landed looked like one that did
    (field report 2026-10-01, issue 3)."""
    import argparse

    ns = argparse.Namespace(
        project=str(root),
        json=True,
        plain=False,
        verbose=False,
        fast=True,
        next_action=cli.HOOK_SESSION_NEXT_ACTION,
        title="session",
        set=None,
        focus=None,
        host_session=host_session,
        # A Stop-hook capture is always a machine write, so `agent` is the floor
        # here, not `unknown` — named harness when the env names one.
        agent=cli.detect_agent(fallback="agent"),
        capture_what="session",
    )
    err = io.StringIO()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = cli.cmd_capture_session(ns)
    except Exception as exc:  # a capture failure must not block Stop — but it is logged
        return f"failed: {type(exc).__name__}: {exc}"[:200]
    if code != 0:
        detail = " ".join(err.getvalue().split())
        return f"failed: exit {code}" + (f": {detail}" if detail else "")[:200]
    return "ok"


def _hook_capture(memory_dir: Path, root: Path, payload: dict) -> int:
    if not memory_dir.is_dir():
        print(json.dumps({}))
        return 0
    return _hook_capture_inner(memory_dir, root, payload)


def _answered_since_ask(memory_dir: Path, session_key: str) -> bool:
    """Did the agent write its own session capture after this session's ask?

    The extraction turn ends with `crumb capture session --next …`; that record
    is authored (a real Next Action), created after `asked_at`, and carries no
    other session's id. Only while the ask is open: the continuation right
    after it closes it (`hooks_common.close_ask`).
    """
    from breadcrumbs import hooks_common

    entry = hooks_common.session_baseline(memory_dir, session_key)
    asked = _epoch(entry.get("asked_at"))
    if asked is None or not entry.get("ask_pending"):
        return False
    for rec in cli.load_records(memory_dir, types=("session",)):
        if rec.error or cli._is_machine_snapshot(rec):
            continue
        owner = rec.meta.get("host_session")
        if owner and str(owner) != session_key:
            continue
        made = _epoch(rec.meta.get("created_at"))
        if made is not None and made >= asked:
            return True
    return False


def _live_work_dirty(root: Path) -> list[str]:
    return cli._work_dirty_files(
        cli._cap_dirty_files(cli.git_dirty_files(root, include_memory=False))
    )


def _same_as_settled(memory_dir: Path, root: Path, session_key: str) -> bool:
    """Is the tree still the one the agent's answer to the ask left?

    Its capture recorded the tree *before* it committed (code it had not
    committed at the ask, committed with the records), so to the session-record
    comparison that commit looked like new work, and the next Stop stacked a
    machine snapshot beside the agent's record (0.6.0).
    """
    from breadcrumbs import hooks_common

    settled = hooks_common.session_baseline(memory_dir, session_key).get("settled")
    if not isinstance(settled, dict) or not settled.get("head"):
        return False
    head = _git.head(root)
    if not head:
        return False
    if head != settled["head"] and _work_commits_between(root, settled["head"], head):
        return False
    return cli._work_dirty_files(settled.get("dirty") or []) == _live_work_dirty(root)


def _hook_capture_inner(memory_dir: Path, root: Path, payload: dict) -> int:
    from breadcrumbs import hooks_common
    from breadcrumbs import transcript as _transcript

    session_key = hooks_common.session_id_of(payload)
    # Mine first, unconditionally: it is a side effect, not a decision. Even a
    # firing that will stay silent — a continuation, a redundant snapshot, a
    # store with the prompt switched off — should still salvage what the
    # transcript shows, because nothing else will read it again.
    from breadcrumbs import hooklog as _hooklog

    mined = _transcript.mine_transcript_into_jots(
        memory_dir,
        root,
        payload.get("transcript_path"),
        session_id=session_key,
        use_cursor=True,
    )
    _transcript.note_report(mined)
    try:
        redundant = _hook_capture_is_redundant(memory_dir, root)
    except Exception:  # pragma: no cover - a dedupe failure must not block Stop
        redundant = False
    # The key snapshots coalesce on: the harness id, or the transcript-derived
    # stand-in; never the shared id-less bucket, which would fold sessions.
    host_session = session_key if session_key != hooks_common.UNKNOWN_SESSION else None
    # A Stop firing that is itself the continuation of a blocked Stop already
    # had its extraction chance — never block twice (that is the loop).
    if payload.get("stop_hook_active"):
        if _answered_since_ask(memory_dir, session_key):
            # The agent captured. Whatever it committed in that turn — code it
            # had not committed before the ask, committed with its records — is
            # what its capture describes: count from here, and no machine
            # snapshot beside the record it wrote (0.6.0).
            head = _git.head(root)
            if head:
                hooks_common.set_session_baseline(memory_dir, session_key, head)
                hooks_common.set_settled(memory_dir, session_key, head, _live_work_dirty(root))
            _hooklog.note(answered=True)
        elif not redundant:
            # It ignored the instruction (or another hook blocked this Stop):
            # the machine snapshot is the floor.
            _note_snapshot(_hook_capture_snapshot(root, host_session))
            hooks_common.set_settled(memory_dir, session_key, None, None)
        hooks_common.close_ask(memory_dir, session_key)
        print(json.dumps({}))
        return 0
    if not redundant:
        try:
            redundant = _same_as_settled(memory_dir, root, session_key)
        except Exception:  # pragma: no cover - a dedupe failure must not block Stop
            redundant = False
    if redundant:
        # Nothing moved, so there is nothing to count or ask: no git log, no
        # reflog scan (0.6.0). Only make sure the session has a start.
        hooks_common.ensure_session_baseline(memory_dir, session_key, root)
        _hooklog.note(redundant=True)
        print(json.dumps({}))
        return 0
    try:
        commits = _session_commits(memory_dir, root, session_key)
    except Exception:  # pragma: no cover - the prompt degrades to jots-only
        commits = []
    if _extraction_enabled(memory_dir):
        # Candidates this session produced that have not already been offered.
        # Re-offering a jot the agent declined, every turn until it expires, is
        # exactly the fatigue that makes an agent start ignoring the prompt.
        asked = hooks_common.extraction_asked(memory_dir, session_key)
        jots = [j for j in _session_jot_rows(memory_dir, session_key) if j["id"] not in asked]
        # A subagent's findings are listed when the turn is asked about, but
        # never earn the ask on their own: one "attempt" line from a search
        # subagent blocked the parent's Stop with "this session produced
        # findings" (0.6.0).
        own = [j for j in jots if "subagent" not in (j.get("tags") or [])]
        attempts = [j for j in own if "attempt" in (j.get("tags") or [])]
        earned = (
            bool(commits)
            or len(attempts) >= EXTRACTION_MIN_ATTEMPT_JOTS
            or len(own) >= EXTRACTION_MIN_SESSION_JOTS
        )
        if earned:
            hooks_common.record_extraction_asked(
                memory_dir, session_key, [j["id"] for j in jots[:EXTRACTION_MAX_JOTS_SHOWN]]
            )
            # Asked once: these commits are never asked about again, whether
            # or not the agent's capture (or the continuation's snapshot)
            # then lands. Without this a failed snapshot re-asked every turn.
            # `asked_at` dates the ask (see `set_session_baseline`).
            head = _git.head(root)
            if head:
                hooks_common.set_session_baseline(memory_dir, session_key, head, asked=True)
            _hooklog.note(offered=len(jots[:EXTRACTION_MAX_JOTS_SHOWN]), commits=len(commits))
            print(json.dumps({"decision": "block", "reason": _extraction_reason(commits, jots)}))
            return 0
    _note_snapshot(_hook_capture_snapshot(root, host_session))
    # The tree moved past the answer; the snapshot describes it from now on.
    hooks_common.set_settled(memory_dir, session_key, None, None)
    print(json.dumps({}))
    return 0


def _note_snapshot(status: str) -> None:
    """Log a Stop-hook snapshot as `ok` or `failed` (with why) — never claim one
    that did not land."""
    from breadcrumbs import hooklog as _hooklog

    if status == "ok":
        _hooklog.note(snapshot="ok")
    else:
        _hooklog.note(snapshot="failed", snapshot_error=status.removeprefix("failed: "))
