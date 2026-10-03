"""breadcrumbs — the resume packet: what an agent reads first.

`build_resume_packet` assembles the packet from the store (handoff, active
decisions, failed attempts, traps, open questions, verifications, the inbox,
what landed since the handoff and computed staleness warnings), ordered by
relevance to the task when one is given. `_bound_packet` trims it to a token
budget in the final serialized view, section by section in `TRIM_ORDER`, and
`render_packet_markdown` / `packet_json_text` render it.

Moved out of `cli.py` (health review 2.1). `crumb resume`, `crumb reindex`,
the SessionStart hook and MCP's `memory_build_resume_packet` call it. The
freshness primitive (`cli._inputs_hash`) stays in `cli` with the publication
that stamps it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from breadcrumbs import cli
from breadcrumbs import git as _git
from breadcrumbs import textmatch as _textmatch
from breadcrumbs import scoring as _scoring
from breadcrumbs import validate as _validate


# Hard token ceiling for the packet (§12: "3,000 to 5,000 tokens"). Since audit
# WP08 it bounds the *final serialized view* — every heading, warning, protected
# section and wrapper of the Markdown or JSON a consumer receives — in the unit
# `approx_tokens` measures (see TOKEN_ESTIMATOR).
TOKEN_BUDGET_MAX = 5000

# The `--fast` view's own ceiling: a reorientation glance, not a briefing.
FAST_TOKEN_BUDGET = 1500

# The smallest budget each view can honour: its own framing (headings, the
# source header, one omission note per section) with every field reduced to a
# pointer. A smaller request is raised to this and the packet says so
# (`budget.requested`); `crumb resume --budget` refuses it outright. Each is
# at least 30% above the floor measured for a worst-case store (non-ASCII names,
# task and fields, every section overfull, every field reduced to its pointer):
# markdown 375, markdown-fast 282, json 528, json-fast 504.
# tests/test_packet_delivery.py holds every view to its limit.
PACKET_MIN_BUDGET = {
    "markdown": 500,
    "markdown-fast": 400,
    "json": 700,
    "json-fast": 700,
}


# Per-section item caps applied before budget trimming (keeps 100s of records bounded).
SECTION_CAPS = {
    "active_decisions": 15,
    "failed_attempts": 15,
    "known_traps": 12,
    "open_questions": 12,
    "likely_files": 20,
    "verification": 12,
    "verifications": 12,
    # Lower than the durable sections on purpose: the inbox is a triage queue,
    # and a packet that spends more context on unsorted notes than on decisions
    # has inverted what it is for.
    "inbox": 10,
    # Warnings are capped too: every aged decision/question emits
    # a warning, so a neglected store could blow the token bound through the one
    # section the trimmer never touched.
    "warnings": 20,
}

# Order in which sections give up items when the packet is over budget
# (first listed = trimmed first = least load-bearing). Project / Current Focus /
# Next Action are never trimmed; warnings are trimmed only after every
# substantive section is empty, so the hard token bound holds.
TRIM_ORDER = [
    "verification",
    # Trimmed early: an unpromoted jot is the least load-bearing thing in the
    # packet by construction — it is a candidate nobody has confirmed.
    "inbox",
    "likely_files",
    "open_questions",
    "verifications",
    "known_traps",
    "failed_attempts",
    "active_decisions",
    # What landed since the handoff makes the focus falsifiable; it goes after
    # every record section, and before the warnings.
    "commits_since_handoff",
    "warnings",
]

# Free-text caps (audit F14). No single field may take the packet over: past its
# cap a field becomes a marked excerpt with a pointer to the full text. The
# canonical files are never changed.
PROTECTED_EXCERPT_CHARS = 2000  # Current Focus, Next Action
TASK_EXCERPT_CHARS = 500  # Requested Task
ITEM_EXCERPT_CHARS = 300  # one entry of any list section, one warning
NAME_EXCERPT_CHARS = 120  # project name, branch, handoff path
# Still over budget once every list is empty: the protected fields shrink
# through these caps, down to a bare pointer.
_PROTECTED_SHRINK = (1000, 500, 250, 120, 0)

# How `approx_tokens` counts, named wherever a budget is reported (audit F14).
TOKEN_ESTIMATOR = "approx-tokens/2"
TOKEN_ESTIMATOR_RULE = (
    "ceil(ASCII chars / 4) + 1 per non-ASCII char — a heuristic, not a model tokenizer"
)


def approx_tokens(text: str) -> int:
    """Cheap token estimate: ASCII chars/4 (rounded up), plus one per other char.

    Plain chars/4 badly undercounts text outside ASCII: a CJK character or an
    emoji is usually one or more tokens by itself, not a quarter of one. This
    is still a heuristic, not any model's tokenizer; budgets reported in this
    unit say so (TOKEN_ESTIMATOR). For ASCII text it equals the old chars/4.
    """
    ascii_chars = len(text.encode("ascii", "ignore"))
    return (ascii_chars + 3) // 4 + (len(text) - ascii_chars)


def _decision_rationale(rec: cli.Record) -> str:
    secs = rec.sections
    return (
        cli._first_line(secs.get("Rationale", ""))
        or cli._first_line(secs.get("Decision", ""))
        or (rec.meta.get("title") or rec.stem)
    )


def _attempt_do_not_retry(rec: cli.Record) -> str:
    secs = rec.sections
    return (
        cli._first_line(secs.get("Do Not Retry Unless", ""))
        or cli._first_line(secs.get("Why It Failed / Succeeded", ""))
        or (rec.meta.get("title") or rec.stem)
    )


def _section_lines(handoff_sections: dict, heading: str) -> list[str]:
    content = handoff_sections.get(heading, "")
    if cli._is_placeholder(content):
        return []
    return [ln.strip().lstrip("-*").strip() for ln in content.splitlines() if ln.strip()]


def compute_staleness(
    root: Path,
    handoff_meta: dict,
    decisions: list[cli.Record],
    attempts: list[cli.Record],
    questions: list[dict],
    stale_days: int,
    *,
    risks_only: bool = False,
    memory_dir: Path | None = None,
    handoff_path: Path | None = None,
) -> list[str]:
    """All computed staleness/risk warnings (§12, §15). Order: primary first.

    `risks_only` is the guard-context view (0.1.10 field test, P0-4): only
    warnings that flag an *abnormal* state — cold handoff, detached HEAD,
    handoff branch mismatch — are emitted. The full view additionally reports
    routine per-store facts (handoff age when fresh, aged open questions, low
    confidence, other-branch records); repeating those on every guard call was
    invariant noise, so they stay in resume/doctor/audit where they are read
    once per session, not once per edit.

    Branch mismatches are judged against what has *reached HEAD* (see
    `HeadTree`): a handoff or record whose file is committed at HEAD and clean
    in the worktree was written on a branch that has since landed here, and is
    not reported. `memory_dir` locates `handoff.md` for that test; without it
    the handoff mismatch is reported the old, unconditional way. Records carry
    their own path, so they never need it.
    """
    warnings: list[str] = []
    cur_branch = cli.git_branch(root)
    detached = _git.is_repo(root) and cur_branch == "HEAD"
    reached = cli.HeadTree(root)
    if handoff_path is None and memory_dir is not None:
        handoff_path = Path(memory_dir) / "handoff.md"

    # (5) Primary signal: handoff age + commit-distance ("train of thought cold").
    age = cli._age_days(handoff_meta.get("updated_at"))
    dist = cli.git_commit_distance(root, handoff_meta.get("commit"))
    if age is not None or dist is not None:
        parts = []
        if age is not None:
            # A future timestamp (clock skew / edited-ahead date) yields a negative
            # age — don't render the nonsensical "-1 day(s) old".
            parts.append(
                "timestamped in the future (clock skew?)" if age < 0 else f"{age} day(s) old"
            )
        if dist is not None:
            parts.append(f"written {dist} commit(s) behind current HEAD")
        cold = (age is not None and age > stale_days) or (dist is not None and dist >= 10)
        if cold or not risks_only:
            warnings.append(("⚠ " if cold else "") + "handoff is " + ", ".join(parts) + ".")
    elif handoff_meta.get("updated_at") and not risks_only:
        warnings.append("handoff timestamp is not parseable; treat handoff age as unknown.")

    # (7) Branch mismatch (§15) — handoff first, then records, capped.
    if detached:
        warnings.append(
            f"git HEAD is detached at {_git.short_head(root)}; records may be stale "
            "relative to the current HEAD."
        )
    hb = handoff_meta.get("branch")
    if (
        hb
        and hb not in (cli.NO_GIT_BRANCH, None, "")
        and not detached
        and cur_branch != cli.NO_GIT_BRANCH
        and hb != cur_branch
        and not reached.contains(handoff_path)
    ):
        warnings.append(
            f"branch mismatch: handoff was written on '{hb}' but HEAD is on '{cur_branch}'."
        )
    if not detached and cur_branch != cli.NO_GIT_BRANCH and not risks_only:
        mism = [
            f"{r.meta.get('id', r.stem)} (on '{r.meta.get('branch')}')"
            for r in (decisions + attempts)
            if r.meta.get("branch")
            and r.meta.get("branch") not in (cli.NO_GIT_BRANCH, None, "")
            and r.meta.get("branch") != cur_branch
            and not reached.contains(r.path)
        ]
        if mism:
            shown = ", ".join(mism[:5])
            extra = f" (+{len(mism) - 5} more)" if len(mism) > 5 else ""
            warnings.append(
                f"{len(mism)} record(s) written on other branches than "
                f"'{cur_branch}': {shown}{extra}."
            )

    if risks_only:
        return warnings

    # (6) Aged-unresolved open questions. A decision's age alone is not a
    # warning: one that stays unchanged for a month is the normal case, and
    # the line was most of every packet's and audit's warnings (health review
    # 1.1). `crumb audit` keys decision staleness on its evidence instead
    # (`audit.decision_staleness_findings`).
    for q in questions:
        if (q.get("status") or "open") != "open":
            continue
        a = cli._age_days(q.get("opened"))
        if a is not None and a > stale_days:
            warnings.append(
                f'open question "{q["question"]}" has been open {a} days — '
                "did this ever get resolved?"
            )

    # (8) Expired + low-confidence records.
    for r in decisions + attempts:
        exp = r.meta.get("expires_at")
        if exp and cli.record_expired(r.meta):
            a = cli._age_days(exp)
            warnings.append(f"{r.meta.get('id', r.stem)} expired on {exp} ({a} days ago).")
        if r.meta.get("confidence") == "low":
            warnings.append(
                f"{r.meta.get('id', r.stem)} is low-confidence — verify before relying on it."
            )

    return warnings


# ---- packet assembly ------------------------------------------------------- #

# How many commit subjects the packet lists between the handoff's commit and
# HEAD (P1-5). Enough to falsify a stale work-list; small enough not to crowd
# the packet.
PACKET_COMMITS_SINCE_HANDOFF_MAX = 10


def _commits_since(root: Path, ref: str | None, limit: int) -> list[str]:
    """One-line subjects for `ref..HEAD`, newest first. [] when unknowable.

    A rewritten/shallow history (ref unknown to this clone) yields [] — the
    commit-distance staleness warning already covers that case; inventing a
    bogus range here would present guesses as history.
    """
    if not ref or not _git.is_repo(root):
        return []
    cur = _git.head(root)
    if cur is None or _git.same_commit(ref, cur):
        return []
    # Commits that touch only the memory store are the handoff and its
    # projections being committed, not work that landed (0.6.0).
    out = _git.run(
        root,
        "log",
        "--oneline",
        "--no-decorate",
        f"{ref}..HEAD",
        "--",
        ".",
        f":(exclude){cli.MEMORY_DIRNAME}",
    )
    if out is None:
        return []
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[:limit]


# Bounded so a store with many fixed verifications cannot flood the warnings
# section with drift guesses.
PACKET_DRIFT_CONFLICTS_MAX = 3

# Share of a fixed verification's subject stems the focus text must contain
# before the drift line fires (floor: two shared stems, or the whole subject
# when it is shorter). The first cut fired on *any* two shared stems, and on
# this tool's own store that was 4 of 9 fixed verifications, every one false:
# "crumb"+"open", "sect"+"sess" (a CHANGELOG *section* and a work *session*),
# and the bare "11" out of "0.1.11". Two words in common is what any two
# sentences about the same project share; most of the subject is a claim.
PACKET_DRIFT_SUBJECT_COVERAGE = 2 / 3


def _claim_stems(text: str) -> set[str]:
    """`_specific` minus digit-only stems: a version fragment is not a claim."""
    return {s for s in _textmatch._specific(text) if not s.isdigit()}


def _focus_verification_conflicts(
    next_action: str, current_focus: str, verifications: list[cli.Record]
) -> list[str]:
    """Warn when a **fixed** verification names what the focus still claims is owed.

    The P1-5 failure mode: the packet's Current Focus said two work items were
    outstanding while its own Verifications section recorded one of them as
    fixed — internally contradictory, and only a human noticed. This is the
    deterministic cross-check: token overlap between the focus claims and each
    fixed verification's subject (same stemming as guard/search), warn-only.

    The overlap must cover `PACKET_DRIFT_SUBJECT_COVERAGE` of the subject's
    stems, not merely reach two: the packet is read cold, so a drift line it
    prints is either the one contradiction the reader must resolve first, or
    the line that teaches them to skip the whole section. A missed paraphrase
    still has *Landed Since The Handoff Was Written* to fall back on.
    """
    claims = _claim_stems(f"{next_action} {current_focus}")
    if not claims:
        return []
    out: list[str] = []
    for r in verifications:
        if (r.meta.get("outcome") or "open") != "fixed":
            continue
        subject = r.meta.get("subject") or r.meta.get("title", "")
        subj = _claim_stems(subject)
        if not subj:
            continue
        need = max(min(2, len(subj)), math.ceil(len(subj) * PACKET_DRIFT_SUBJECT_COVERAGE))
        if len(subj & claims) >= need:
            rid = r.meta.get("id", r.stem)
            when = r.meta.get("updated_at") or r.meta.get("created_at") or ""
            when = f" on {when[:10]}" if when else ""
            out.append(
                f'possible drift: `{rid}` recorded "{subject}" as **fixed**{when}, '
                "but Current Focus / Next Action still claims that work — "
                "re-check before redoing it."
            )
            if len(out) >= PACKET_DRIFT_CONFLICTS_MAX:
                break
    return out


# How much of a jot's text the packet spends. A jot is capped at
# JOT_MAX_CHARS; the packet shows the opening of it and the id to fetch the
# rest, because ten full jots would outweigh every decision in the section above.
PACKET_JOT_CHARS = 120


def _packet_record_ids(packet: dict) -> list[str]:
    """Every record id the rendered packet actually names.

    Read from the packet *after* capping and budget trimming, so a record that
    was computed and then dropped is not counted as surfaced — it was not.
    """
    ids: list[str] = []
    for key in ("active_decisions", "failed_attempts", "verifications", "inbox"):
        ids += [
            item["id"] for item in packet.get(key, []) if isinstance(item, dict) and item.get("id")
        ]
    # Traps render as their heading (`trap_<slug>: summary`), which is how the
    # id is spelled in that file; take the id half.
    ids += [str(t).split(":", 1)[0].strip() for t in packet.get("known_traps", [])]
    return [i for i in ids if i]


def _record_packet_surfacings(
    memory_dir: Path, packet: dict, source: str = "resume", session_id: str | None = None
) -> None:
    """Best-effort usage counts for a packet that was just shown to somebody."""
    from breadcrumbs import usage as _usage

    _usage.record_surfaced(memory_dir, _packet_record_ids(packet), source, session_id=session_id)


def _packet_inbox(memory_dir: Path) -> list[dict]:
    """Live committed jots for the packet's Inbox section.

    Imported here rather than at module scope: `breadcrumbs.inbox` imports this
    module, so a top-level import would be a cycle.
    """
    from breadcrumbs import inbox as _inbox

    out = []
    for row in _inbox.packet_jots(memory_dir):
        text = row["title"]
        if len(text) > PACKET_JOT_CHARS:
            text = text[: PACKET_JOT_CHARS - 1].rstrip() + "…"
        out.append(
            {
                "id": row["id"],
                "text": text,
                "source": row["source"],
                "age_days": row["age_days"],
            }
        )
    return out


def build_resume_packet(
    memory_dir: Path,
    root: Path,
    *,
    stale_days: int = cli.STALE_AGE_DAYS,
    fast: bool = False,
    task: str | None = None,
    view: str = "markdown",
    budget: int | None = None,
    render=None,
    loaded_rules: dict[str, str] | None = None,
    loaded_rules_from: tuple[str, ...] | None = None,
) -> dict:
    """Assemble the structured resume packet (the source of both MD and JSON output).

    When `task` is given (the "resume for THIS task" path) the packet
    is scoped to it: `requested_task` is echoed and `likely_files` is derived from
    the records that actually match the task instead of the store-global default
    that misdirects on off-domain work. With no task, behavior is unchanged.

    Its `inputs_hash` stamp is the snapshot it was built from, verified
    unchanged across the build, or `unstable` with a warning (audit F07; see
    `breadcrumbs/snapshots.py`).

    Audit WP08. `view` ("markdown" or "json") and `budget` say which serialized
    view the packet is bounded for; `render` is that view's exact text, when the
    caller wraps it (default: `render_packet_markdown` / `packet_json_text`).
    The packet is portable unless `loaded_rules` (`promote.loaded_rules`) says
    which standing rules its consumer has loaded, from `loaded_rules_from`;
    only those promoted records are left out.
    """
    from breadcrumbs import snapshots as _snapshots

    options = {
        "stale_days": stale_days,
        "fast": fast,
        "task": task,
        "view": view,
        "budget": budget,
        "render": render,
        "loaded_rules": loaded_rules,
        "loaded_rules_from": loaded_rules_from,
    }
    packet, digest = _snapshots.stable_build(
        memory_dir,
        root,
        lambda h: _build_resume_packet_once(memory_dir, root, inputs_hash=h, **options),
    )
    if digest is None:
        # Built once more, stamped and warned as unstable before it is bounded,
        # so the warning counts against the budget like any other line.
        packet = _build_resume_packet_once(
            memory_dir,
            root,
            inputs_hash=_snapshots.UNSTABLE,
            lead_warnings=[_snapshots.UNSTABLE_WARNING],
            **options,
        )
    return packet


def _build_resume_packet_once(
    memory_dir: Path,
    root: Path,
    *,
    stale_days: int = cli.STALE_AGE_DAYS,
    fast: bool = False,
    task: str | None = None,
    inputs_hash: str,
    view: str = "markdown",
    budget: int | None = None,
    render=None,
    loaded_rules: dict[str, str] | None = None,
    loaded_rules_from: tuple[str, ...] | None = None,
    lead_warnings: list[str] | None = None,
) -> dict:
    """One build of the packet, stamped with the digest the caller verifies."""
    memory_dir = Path(memory_dir)
    manifest = cli.load_manifest(memory_dir) or {}

    # Lenient reads: one bad byte in handoff.md used to abort the
    # packet build, which took `resume`, `audit` and every reindex down with it —
    # projections silently stopped refreshing. The problem is surfaced as a packet
    # warning instead, naming the file.
    unreadable: list[str] = []
    current_text, problem = (
        cli.read_text_lenient(memory_dir / "current.md")
        if (memory_dir / "current.md").is_file()
        else ("", None)
    )
    if problem:
        unreadable.append(f"current.md: {problem}")
    current_sections = cli.split_md_sections(current_text)
    # WM-50: this branch's own handoff when it has one, else handoff.md.
    from breadcrumbs import handoffs as _handoffs

    handoff_path, handoff_label = _handoffs.read_path(memory_dir, root)
    handoff_text, problem = (
        cli.read_text_lenient(handoff_path) if handoff_path.is_file() else ("", None)
    )
    if problem:
        unreadable.append(f"{handoff_label}: {problem}")
    handoff_sections = cli.split_md_sections(handoff_text)
    handoff_meta = cli.parse_handoff_meta(handoff_text)

    decisions = cli.active_decisions(memory_dir)
    attempts = cli.active_attempts(memory_dir)
    traps = cli.active_traps(memory_dir)
    questions = cli.load_open_questions(memory_dir)
    verifications = active_verifications(memory_dir)
    # WM-30: a record past its `expires_at` leaves the lists (it is still on
    # disk, still searchable, and `crumb expired` names it). The staleness
    # warnings below still see every active record, so "X expired on …" is said.
    listed_decisions = [r for r in decisions if not cli.record_expired(r.meta)]
    listed_attempts = [r for r in attempts if not cli.record_expired(r.meta)]
    listed_verifications = [r for r in verifications if not cli.record_expired(r.meta)]
    # WM-52: branch-scoped records from another branch leave the lists too.
    current_branch = cli.git_branch(root)
    listed_decisions = [
        r for r in listed_decisions if not cli.branch_scoped_elsewhere(r.meta, current_branch)
    ]
    listed_attempts = [
        r for r in listed_attempts if not cli.branch_scoped_elsewhere(r.meta, current_branch)
    ]
    listed_verifications = [
        r for r in listed_verifications if not cli.branch_scoped_elsewhere(r.meta, current_branch)
    ]
    # WM-40 / audit F13: a promoted record is a standing rule in an instruction
    # file. The packet is portable by default: it keeps the record, and carries
    # the rule in force, because its reader may not load that file (another
    # harness, a read-only clone) or the file may no longer hold the rule. Only a
    # consumer that has verifiably loaded the rule (`loaded_rules`, read from
    # the files it loads, at the moment it loads them) gets the record elided,
    # so the same rule is not spent twice in its context. Guard, search and the
    # warnings see every promoted record either way.
    from breadcrumbs import promote as _promote

    rule_files = _promote.rules_in_files(root)
    rules: dict[str, dict] = {}

    def _standing(rid: str, target: str | None) -> dict:
        if rid not in rules:
            text, in_file = _promote.effective_rule(memory_dir, rid, target, rule_files)
            rules[rid] = {"promoted_to": target, "rule": text, "rule_in_file": in_file}
        return rules[rid]

    def _elided(rid: str, promoted: bool) -> bool:
        return promoted and loaded_rules is not None and rid in loaded_rules

    promoted_counts = {"active_decisions": 0, "failed_attempts": 0, "known_traps": 0}
    listed_decisions_all = listed_decisions
    listed_attempts_all = listed_attempts
    for key, recs in (("active_decisions", listed_decisions), ("failed_attempts", listed_attempts)):
        for r in recs:
            rid = r.meta.get("id", r.stem)
            if _promote.is_promoted_record(r):
                _standing(rid, str(r.meta["promoted_to"]))
                promoted_counts[key] += _elided(rid, True)
    for t in traps:
        if _promote.is_promoted_trap(t):
            _standing(t["id"], _promote.promoted_to(t))
            promoted_counts["known_traps"] += _elided(t["id"], True)
    listed_decisions = [
        r
        for r in listed_decisions
        if not _elided(r.meta.get("id", r.stem), _promote.is_promoted_record(r))
    ]
    listed_attempts = [
        r
        for r in listed_attempts
        if not _elided(r.meta.get("id", r.stem), _promote.is_promoted_record(r))
    ]
    listed_traps = [t for t in traps if not _elided(t["id"], _promote.is_promoted_trap(t))]

    def _trap_line(t: dict) -> str:
        rule = rules.get(t["id"])
        if not rule or not rule["rule"]:
            return t["heading"]
        return f"{t['id']}: {_standing_label(rule)} {rule['rule']}"

    # Project snapshot (git is the live source; handoff metadata is advisory).
    dirty = cli.git_dirty_files(root)
    project = {
        "name": manifest.get("project") or cli.derive_project_name(root),
        # Project-relative, never the absolute host path. The packet
        # is a committed, shared artifact: an absolute path publishes the author's
        # local directory layout into the repo (the disclosure `mcp_core` already
        # forbids for error messages, issue #7), makes a byte-identical clone at
        # another path read as stale, and churns on every reindex when two
        # developers work at different paths.
        "path": ".",
        "branch": cli.git_branch(root),
        "commit": _git.short_head(root),
        "dirty": len(dirty),
        "dirty_state": (f"{len(dirty)} uncommitted file(s)" if dirty else "clean"),
        "handoff": handoff_label,
    }

    def _focus() -> tuple[str, str]:
        cf = current_sections.get("Current Focus", "")
        if not cli._is_placeholder(cf):
            return cf.strip(), "current.md → Current Focus"
        hf = handoff_sections.get("Current Focus", "")
        return ("" if cli._is_placeholder(hf) else hf.strip()), f"{handoff_label} → Current Focus"

    focus, focus_source = _focus()

    next_action = handoff_sections.get("Next Action", "")
    next_action = "" if cli._is_placeholder(next_action) else next_action.strip()
    # The Next Action is a log, newest first: the packet carries the newest
    # entry and says how many earlier ones the handoff holds (issue 1).
    next_entries = cli.split_next_entries(next_action)
    next_action_earlier = max(len(next_entries) - 1, 0)
    if next_entries:
        next_action = next_entries[0]

    packet: dict = {
        "source": {
            "commit": _git.short_head(root),
            "inputs_hash": inputs_hash,
            "generated_at": cli.now_iso(),
        },
        "fast": bool(fast),
        # Two different numbers used to be one confusable word:
        # `stale_after_days` is the *threshold* the caller chose, while
        # `handoff_age_days`/`handoff_commit_distance` are the measured *age* and
        # distance the warnings are computed from. The ages used to exist only as
        # prose inside a warning string ("handoff is 6 day(s) old"), so a consumer
        # reading the packet had the threshold as data and the fact as English.
        # Both are None when unknown: an unparseable timestamp, or no git repo.
        "stale_after_days": stale_days,
        "handoff_age_days": cli._age_days(handoff_meta.get("updated_at")),
        "handoff_commit_distance": cli.git_commit_distance(root, handoff_meta.get("commit")),
        "project": project,
        "current_focus": focus,
        "next_action": next_action,
        "next_action_earlier": next_action_earlier,
        "active_decisions": [
            {
                "id": r.meta.get("id", r.stem),
                "title": r.meta.get("title", ""),
                "rationale": _decision_rationale(r),
                **rules.get(r.meta.get("id", r.stem), {}),
            }
            for r in listed_decisions
        ],
        "failed_attempts": [
            {
                "id": r.meta.get("id", r.stem),
                "title": r.meta.get("title", ""),
                "do_not_retry": _attempt_do_not_retry(r),
                **rules.get(r.meta.get("id", r.stem), {}),
            }
            for r in listed_attempts
        ],
        "known_traps": [_trap_line(t) for t in listed_traps],
        # Standing rules this packet left out because its consumer has loaded
        # them (only ever non-empty for such a consumer; see `rules`).
        "promoted": {k: v for k, v in promoted_counts.items() if v},
        "rules": (
            {"mode": "portable"}
            if loaded_rules is None
            else {
                "mode": "elided-when-loaded",
                "loaded_from": list(loaded_rules_from or ()),
                "elided": sum(promoted_counts.values()),
            }
        ),
        "open_questions": [q["question"] for q in questions if q["status"] == "open"],
        # Committed jots only. A machine-local jot in this list would make the
        # committed packet differ between two checkouts of one store while
        # `_inputs_hash` — which cannot read gitignored input without the same
        # problem — still called both fresh. See `breadcrumbs/inbox.py`.
        "inbox": _packet_inbox(memory_dir),
        "likely_files": [],
        "verification": [],
        "verifications": [
            {
                "id": r.meta.get("id", r.stem),
                "subject": (r.meta.get("subject") or r.meta.get("title", "")),
                # A verification with no outcome is not "open" — nobody said so.
                # Showing it as open inverted a hand-written "Fixed." (N3).
                "outcome": (r.meta.get("outcome") or "unknown"),
                "method": r.meta.get("method"),
            }
            for r in listed_verifications
        ],
        "commits_since_handoff": _commits_since(
            root, handoff_meta.get("commit"), PACKET_COMMITS_SINCE_HANDOFF_MAX
        ),
        "warnings": (
            list(lead_warnings or [])
            + [f"⚠ {u}" for u in unreadable]
            + _validate.record_contract_warnings(memory_dir)
            + compute_staleness(
                root,
                handoff_meta,
                decisions,
                attempts,
                questions,
                stale_days,
                memory_dir=memory_dir,
                handoff_path=handoff_path,
            )
        ),
        "omitted": {},
        "omitted_reason": {},
    }
    # P1-5 cross-check: a fixed verification contradicting the focus claims is
    # the one staleness the age/distance numbers can never see.
    packet["warnings"] += _focus_verification_conflicts(
        packet["next_action"], packet["current_focus"], verifications
    )
    from breadcrumbs import lifecycle as _lifecycle

    packet["warnings"] += _lifecycle.lifecycle_warnings(
        memory_dir, root, verifications=listed_verifications, traps=traps
    )
    # WM-31: a record citing a file that is gone may describe code that is gone.
    # Promoted records too: a standing rule citing a deleted file is exactly the
    # one that must be rechecked.
    packet["warnings"] += _lifecycle.missing_evidence_warnings(
        root, listed_decisions_all + listed_attempts_all + listed_verifications
    )
    # WM-34: memory that argues with itself, worded as a question.
    packet["warnings"] += _lifecycle.conflict_warnings(memory_dir)
    # Its own field, never trimmed: a store written by a newer crumb-kit is
    # read, but its records may mean something this build does not know
    # (audit WP21).
    from breadcrumbs import compat as _compat

    compat_note = _compat.warning(memory_dir)
    if compat_note:
        packet["compatibility"] = compat_note

    # Likely files: handoff section + file-type evidence refs (deduped, order-stable).
    files = _section_lines(handoff_sections, "Likely Relevant Files")
    for r in decisions + attempts:
        files.extend(cli._evidence_refs(r, ("file", "path")))
    packet["likely_files"] = cli._dedup(files)

    # Verification commands: handoff section + command-type evidence refs. (Distinct
    # from `verifications`, which are recorded *results*; this list is *how to check*.)
    verify_cmds = _section_lines(handoff_sections, "Verification Commands")
    for r in decisions + attempts:
        verify_cmds.extend(cli._evidence_refs(r, ("command", "test")))
    packet["verification"] = cli._dedup(verify_cmds)

    # Task scoping: when a task is named, replace the store-global
    # likely_files with files drawn from the records that actually match the task,
    # and label an empty result so the consumer knows the store is cold here rather
    # than trusting noise.
    packet["ordering"] = "recency"
    if task:
        packet["requested_task"] = task
        scoped, note = _task_scoped_files(memory_dir, root, task, stale_days=stale_days)
        packet["likely_files"] = scoped
        if note:
            packet["likely_files_note"] = note
        _order_by_relevance(packet, memory_dir, root, task, stale_days=stale_days)

    _bound_packet(
        packet,
        fast=fast,
        view=view,
        budget=budget,
        render=render,
        sources={
            "current_focus": focus_source,
            "next_action": f"{handoff_label} → Next Action",
            "requested_task": "the task you passed",
        },
    )
    return packet


# How many of the newest items in each section keep their place when a packet
# is ordered by relevance. Without a floor, a record written ten minutes ago that
# happens to share no words with the task would sink below a year-old one that
# does — and "what just changed" is the one thing a resuming reader cannot
# afford to miss, whatever they are about to work on.
RECENCY_FLOOR = 3

# The packet's list sections and how to get a search id out of each entry. Two
# of them hold strings rather than dicts: a trap is rendered as its heading
# (`trap_<slug>: summary`) and a question as its text.
_RELEVANCE_SECTIONS: dict[str, "object"] = {
    "active_decisions": lambda e: e["id"],
    "failed_attempts": lambda e: e["id"],
    "verifications": lambda e: e["id"],
    "known_traps": lambda e: str(e).split(":", 1)[0].strip(),
    "open_questions": lambda e: _scoring.question_item_id(str(e)),
}


def task_relevance_scores(
    memory_dir: Path, root: Path, task: str, *, stale_days: int = cli.STALE_AGE_DAYS
) -> dict[str, float]:
    """`{record_id: score}` for `task`: what a task-ordered packet sorts by.

    Deliberately loose (one shared word is enough): it only orders, it never
    hides. The relevance evals (`evals/run.py`) rank the packet by this too, so
    the packet and its measurement cannot drift apart.
    """
    matches, _ = _scoring.search(
        memory_dir, root, task, include_ideas=False, min_keyword=1, stale_days=stale_days
    )
    return {m["id"]: float(m.get("score") or 0) for m in matches}


def _order_by_relevance(
    packet: dict, memory_dir: Path, root: Path, task: str, *, stale_days: int
) -> None:
    """Reorder every list section by relevance to `task`, in place (WM-20).

    Ordering only — nothing is hidden. The newest `RECENCY_FLOOR` entries stay
    first, then everything the task scores against, best first, then the rest
    in their original order. Caps and the token budget apply afterwards exactly
    as before, so what relevance changes is *which* entries survive a trim: the
    ones about the task instead of whichever happened to be newest.

    One `search` over the whole corpus, reused for every section, so the cost is
    the same as `--task`'s likely-file scoping already paid.
    """
    scores = task_relevance_scores(memory_dir, root, task, stale_days=stale_days)
    if not scores:
        return
    for key, id_of in _RELEVANCE_SECTIONS.items():
        entries = packet.get(key) or []
        head, rest = entries[:RECENCY_FLOOR], entries[RECENCY_FLOOR:]
        scored = [e for e in rest if scores.get(id_of(e), 0) > 0]
        unscored = [e for e in rest if scores.get(id_of(e), 0) <= 0]
        # sort() is stable, so equal scores keep their recency order.
        scored.sort(key=lambda e: -scores[id_of(e)])
        packet[key] = head + scored + unscored
    packet["ordering"] = "relevance"


def active_verifications(memory_dir: Path) -> list[cli.Record]:
    """Active verification records, actionable outcome first.

    open/regressed/inconclusive (still need attention) sort ahead of
    not_applicable/fixed (resolved), each group newest-first via active_records.
    """
    order = {
        o: i
        for i, o in enumerate(cli.ACTIONABLE_VERIFICATION_OUTCOMES + ("not_applicable", "fixed"))
    }
    recs = cli.active_records(memory_dir, "verification")
    return sorted(recs, key=lambda r: order.get(r.meta.get("outcome") or "open", 99))


def _task_scoped_files(
    memory_dir: Path, root: Path, task: str, *, stale_days: int
) -> tuple[list[str], str | None]:
    """Files relevant to `task`, from records that match it.

    Reuses the deterministic `search` scoring rather than inventing a second
    relevance notion. Returns (files, note); note is set only when nothing matched.

    Ideas are excluded (the default corpus): this list goes into a packet that
    boots the next session, and a file path is only "likely" because someone did
    work there — not because someone proposed it.
    """
    matches, by_id = _scoring.search(
        memory_dir, root, task, stale_days=stale_days, include_ideas=False
    )
    files: list[str] = []
    for m in matches:
        files.extend(m.get("matched_files") or [])
        item = by_id.get(m["id"]) or {}
        rec = item.get("record")
        if rec is not None:
            files.extend(cli._evidence_refs(rec, ("file", "path")))
    files = cli._dedup([f for f in files if f])
    if not files:
        return [], "no records match this task domain; starting cold"
    return files, None


# Sections dropped wholesale by --fast (reduced reorientation view, §12).
_FAST_DROP = (
    "active_decisions",
    "failed_attempts",
    "known_traps",
    "open_questions",
    "likely_files",
    "verification",
    "verifications",
    "inbox",
)


def _excerpt(text: str, limit: int, source: str | None = None) -> tuple[str, bool]:
    """`(text, excerpted)`: `text` cut to `limit` chars, visibly, with a pointer.

    The mark says how much is shown and where the whole is, so a shortened
    field can never be mistaken for the full one. At `limit` 0 only the pointer
    is left.
    """
    text = text or ""
    if len(text) <= limit:
        return text, False
    where = f"; full text: {source}" if source else ""
    shown = text[:limit].rstrip() if limit > 0 else ""
    if shown:
        return f"{shown}… [excerpt: {len(shown)} of {len(text)} chars{where}]", True
    return f"[omitted: {len(text)} chars{where}]", True


def _entry_source(section: str, entry) -> str | None:
    if isinstance(entry, dict) and entry.get("id"):
        return f"crumb show {entry['id']}"
    if section == "known_traps":
        return f"crumb show {str(entry).split(':', 1)[0].strip()}"
    if section == "open_questions":
        return f"crumb show {_scoring.question_item_id(str(entry))}"
    return None


# The text fields of each list section's entries (dict entries) that can grow
# without limit; string entries are excerpted whole.
_ENTRY_TEXT_FIELDS = {
    "active_decisions": ("title", "rationale", "rule"),
    "failed_attempts": ("title", "do_not_retry", "rule"),
    "verifications": ("subject",),
    "inbox": ("text",),
}


def _excerpt_entries(packet: dict) -> None:
    """Cap every list entry and warning at ITEM_EXCERPT_CHARS (audit F14)."""
    excerpted = packet.setdefault("excerpted", {})
    for key in [*SECTION_CAPS, "commits_since_handoff"]:
        entries = packet.get(key) or []
        out = []
        for entry in entries:
            source = _entry_source(key, entry)
            hit = False
            if isinstance(entry, dict):
                entry = dict(entry)
                for field in _ENTRY_TEXT_FIELDS.get(key, ()):
                    if isinstance(entry.get(field), str):
                        entry[field], cut = _excerpt(entry[field], ITEM_EXCERPT_CHARS, source)
                        hit = hit or cut
            elif isinstance(entry, str):
                entry, hit = _excerpt(entry, ITEM_EXCERPT_CHARS, source)
            if hit:
                excerpted[key] = excerpted.get(key, 0) + 1
            out.append(entry)
        if key in packet:
            packet[key] = out


# Project names shrink with the protected fields, but never below this.
_NAME_FLOOR_CHARS = 40


def _excerpt_protected(packet: dict, originals: dict, sources: dict, cap: int) -> None:
    """Set the protected fields from their full text at `cap` chars each."""
    excerpted = packet.setdefault("excerpted", {})
    same = originals["current_focus"] and (
        originals["current_focus"].strip() == originals["next_action"].strip()
    )
    proj = packet.get("project") or {}
    name_cap = min(NAME_EXCERPT_CHARS, max(cap, _NAME_FLOOR_CHARS))
    for field in ("name", "branch", "handoff"):
        full = originals.get(f"project.{field}")
        if isinstance(full, str):
            proj[field], cut = _excerpt(full, name_cap)
            if cut:
                excerpted[f"project.{field}"] = {"shown_chars": name_cap, "total_chars": len(full)}
    for field, limit in (
        ("next_action", cap),
        ("current_focus", cap),
        ("requested_task", min(cap, TASK_EXCERPT_CHARS)),
    ):
        if originals.get(field) is None:
            continue
        if field == "current_focus" and same:
            # Rendered as "same as Next Action": keep the two strings equal.
            packet[field] = packet["next_action"]
            continue
        packet[field], cut = _excerpt(originals[field], limit, sources.get(field))
        if cut:
            excerpted[field] = {
                "shown_chars": min(limit, len(originals[field])),
                "total_chars": len(originals[field]),
                "source": sources.get(field),
            }
        else:
            excerpted.pop(field, None)


def packet_json_text(packet: dict) -> str:
    """The JSON view as the MCP tool and library callers serialize it."""
    return json.dumps(packet, indent=2)


def _bound_packet(
    packet: dict,
    *,
    fast: bool,
    view: str = "markdown",
    budget: int | None = None,
    render=None,
    sources: dict | None = None,
) -> None:
    """Fit the packet into its view's budget, measured on the final text (audit F14).

    In order: --fast pruning; per-entry and per-field excerpts; per-section caps;
    list trimming (TRIM_ORDER); then the protected fields shrink to pointers.
    Every step removes something, so it terminates. Everything left out or
    shortened is disclosed (`omitted`, `excerpted`, the inline marks), and
    `budget` names the view, the unit, the estimator, the limit and what the
    view actually used.
    """
    if view not in ("markdown", "json"):
        raise ValueError(f"unknown packet view: {view!r}")
    view_name = f"{view}-fast" if fast else view
    requested = budget
    if requested is None:
        requested = FAST_TOKEN_BUDGET if fast else TOKEN_BUDGET_MAX
    limit = max(int(requested), PACKET_MIN_BUDGET[view_name])
    if render is None:
        render = render_packet_markdown if view == "markdown" else packet_json_text

    def measure() -> int:
        return approx_tokens(render(packet))

    packet["budget"] = {
        "view": view_name,
        "unit": "approx_tokens",
        "estimator": TOKEN_ESTIMATOR,
        "estimator_rule": TOKEN_ESTIMATOR_RULE,
        "limit": limit,
        # Placeholders at least as wide as the final values, so the text
        # measured below is never shorter than the text emitted.
        "used": limit,
        "within": False,
    }
    if limit != requested:
        packet["budget"]["requested"] = int(requested)

    if fast:
        for key in _FAST_DROP:
            packet[key] = []
        packet["omitted"] = {}
        packet["omitted_reason"] = {}

    sources = sources or {}
    originals = {
        "current_focus": packet.get("current_focus") or "",
        "next_action": packet.get("next_action") or "",
        "requested_task": packet.get("requested_task"),
        **{f"project.{k}": v for k, v in (packet.get("project") or {}).items()},
    }
    _excerpt_entries(packet)
    _excerpt_protected(packet, originals, sources, PROTECTED_EXCERPT_CHARS)

    # Per-section caps (record how many we hid, and why). Applied in --fast mode
    # too: warnings survive the fast prune and must stay bounded.
    for key, cap in SECTION_CAPS.items():
        if fast and key in _FAST_DROP:
            continue
        items = packet.get(key, [])
        if len(items) > cap:
            packet["omitted"][key] = packet["omitted"].get(key, 0) + (len(items) - cap)
            packet["omitted_reason"][key] = "the per-section cap"
            packet[key] = items[:cap]

    # Budget trim, lowest-priority section first, until within the ceiling.
    while measure() > limit:
        for key in TRIM_ORDER:
            if packet.get(key):
                packet[key].pop()
                packet["omitted"][key] = packet["omitted"].get(key, 0) + 1
                # A key already capped is now also budget-trimmed — record both.
                prior = packet["omitted_reason"].get(key)
                packet["omitted_reason"][key] = (
                    "the per-section cap and token budget"
                    if prior == "the per-section cap"
                    else "the token budget"
                )
                break
        else:
            break

    # Every list is empty and it is still over: the protected fields give way,
    # as marked excerpts and finally bare pointers.
    for cap in _PROTECTED_SHRINK:
        if measure() <= limit:
            break
        _excerpt_protected(packet, originals, sources, cap)

    if not packet["excerpted"]:
        packet.pop("excerpted")
    used = measure()
    packet["budget"]["used"] = used
    packet["budget"]["within"] = used <= limit


# ---- rendering ------------------------------------------------------------- #


def _standing_label(rule: dict) -> str:
    """How a promoted entry introduces its rule, saying where the rule lives."""
    target = rule.get("promoted_to") or "the instruction file"
    if rule.get("rule_in_file"):
        return f"standing rule in {target}:"
    return f"standing rule (promoted to {target}, not found there):"


def _omitted_note(packet: dict, key: str) -> list[str]:
    out = []
    n = packet.get("omitted", {}).get(key, 0)
    if n:
        reason = packet.get("omitted_reason", {}).get(key, "the token budget")
        out.append(f"_(… {n} more omitted to stay within {reason})_")
    promoted = (packet.get("promoted") or {}).get(key, 0)
    if promoted:
        loaded = ", ".join((packet.get("rules") or {}).get("loaded_from") or []) or (
            "the instruction file"
        )
        out.append(
            f"_({promoted} standing rule(s) left out — already loaded from {loaded} "
            'this session, under "Project rules promoted from memory")_'
        )
    return out


def _view_header(packet: dict) -> str | None:
    """The line that says which view this is, its budget and its rule mode."""
    budget = packet.get("budget")
    if not budget:
        return None
    rules = packet.get("rules") or {}
    if rules.get("mode") == "elided-when-loaded":
        mode = f"rules: elided when loaded from {', '.join(rules.get('loaded_from') or [])}"
    else:
        mode = "rules: portable"
    asked = f", raised from {budget['requested']}" if "requested" in budget else ""
    return (
        f"<!-- view: {budget['view']} | budget: {budget['used']}/{budget['limit']} "
        f"{budget['unit']}{asked} ({budget['estimator']}: {budget['estimator_rule']}) "
        f"| {mode} -->"
    )


def render_packet_markdown(packet: dict) -> str:
    """Render the §12 packet. Source header keeps the GENERATED PROJECTION marker."""
    src = packet["source"]
    proj = packet["project"]
    out: list[str] = [
        f"<!-- {cli.GENERATED_MARKER} — do not edit by hand. Rebuilt by `crumb resume`. -->",
        f"<!-- source_commit: {src['commit']} | inputs_hash: {src['inputs_hash']} "
        f"| generated_at: {src['generated_at']} -->",
    ]
    header = _view_header(packet)
    if header:
        out.append(header)
    out += [
        "",
        "# Resume Packet",
        "",
    ]
    if packet.get("compatibility"):
        out += [f"> ⚠ {packet['compatibility']}", ""]
    if packet.get("requested_task"):
        out += [
            "## Requested Task",
            packet["requested_task"],
            "_(this is the task you asked to resume; the focus/next-action below are "
            "where the last session left off)_",
            "",
        ]
    # Stores written before 0.1.11 carry a Current Focus that is a verbatim copy
    # of the Next Action (capture used to default one to the other, P1-6);
    # collapse the duplicate at render time instead of spending ~1.4k chars
    # printing the same text twice.
    cf = packet["current_focus"]
    if cf and cf.strip() == (packet["next_action"] or "").strip():
        cf = "_(same as Next Action)_"
    out += [
        "## Project",
        f"**{proj['name']}** — `{proj['path']}`  ",
        f"branch `{proj['branch']}` · commit `{proj['commit']}` · {proj['dirty_state']}"
        + (f" · handoff: {proj['handoff']}" if proj.get("handoff") else ""),
    ]
    # Say which order the reader is looking at. A relevance-ordered list read as
    # if it were newest-first would suggest a year-old decision is the latest.
    # The task itself is printed once, under Requested Task, not again here.
    if packet.get("ordering") == "relevance" and packet.get("requested_task"):
        out.append(
            f"_(sections ordered by relevance to the Requested Task above; "
            f"the {RECENCY_FLOOR} newest in each stay first)_"
        )
    out += [
        "",
        "## Current Focus",
        cf or "_(not recorded — see current.md / handoff.md)_",
        "",
        "## Next Action",
        packet["next_action"] or "_(not recorded — set one with `crumb capture session --next`)_",
        "",
    ]
    if packet.get("next_action_earlier"):
        n = packet["next_action_earlier"]
        where = (packet.get("project") or {}).get("handoff") or "the handoff"
        out[-1:-1] = ["", f"_({n} earlier entr{'y' if n == 1 else 'ies'} in {where})_"]

    # P1-5: the staleness numbers say how *old* the handoff is, never whether its
    # claims still hold. Listing what actually landed since it was written makes
    # the Current Focus / Next Action falsifiable by the reader — a fresh session
    # can check the list before redoing work the packet still says is owed.
    if packet.get("commits_since_handoff"):
        out += [
            "## Landed Since The Handoff Was Written",
            "_(check Current Focus / Next Action against these before redoing work)_",
        ]
        out += [f"- {c}" for c in packet["commits_since_handoff"]]
        out.append("")

    if not packet["fast"]:
        # The omitted-count disclosure is emitted in BOTH branches: budget-trimming
        # can empty a section entirely while still having hidden items, and the
        # "… N more omitted" note must not vanish when the list renders as none.
        out += ["## Active Decisions"]
        if packet["active_decisions"]:
            for d in packet["active_decisions"]:
                if d.get("rule"):
                    out.append(f"- `{d['id']}` — {_standing_label(d)} {d['rule']}")
                else:
                    out.append(f"- `{d['id']}` — {d['rationale']}")
        else:
            out.append("_(none active)_")
        out += _omitted_note(packet, "active_decisions")
        out.append("")

        out += ["## Failed Attempts To Avoid"]
        if packet["failed_attempts"]:
            for a in packet["failed_attempts"]:
                if a.get("rule"):
                    out.append(f"- `{a['id']}` — {_standing_label(a)} {a['rule']}")
                else:
                    out.append(f"- `{a['id']}` — do not retry: {a['do_not_retry']}")
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "failed_attempts")
        out.append("")

        out += ["## Known Traps"]
        if packet["known_traps"]:
            out += [f"- {t}" for t in packet["known_traps"]]
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "known_traps")
        out.append("")

        out += ["## Open Questions / Blockers"]
        if packet["open_questions"]:
            out += [f"- {q}" for q in packet["open_questions"]]
        else:
            out.append("_(none open)_")
        out += _omitted_note(packet, "open_questions")
        out.append("")

        # Only when there is something in it. An empty Inbox heading in every
        # packet is a line of context spent saying nothing, and most stores will
        # never use the tier at all.
        if packet.get("inbox"):
            out += ["## Inbox (unsorted, expires)"]
            out.append(
                "_(candidates, not findings — promote with `crumb inbox promote <id> "
                "<type>` or drop with `crumb inbox drop <id>`)_"
            )
            for j in packet["inbox"]:
                age = f"{j['age_days']}d" if j["age_days"] is not None else "new"
                out.append(f"- `{j['id']}` ({age}, {j['source']}) {j['text']}")
            out += _omitted_note(packet, "inbox")
            out.append("")

        out += ["## Likely Relevant Files"]
        if packet["likely_files"]:
            out += [f"- {f}" for f in packet["likely_files"]]
        elif packet.get("likely_files_note"):
            out.append(f"_({packet['likely_files_note']})_")
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "likely_files")
        out.append("")

        out += ["## Verifications"]
        if packet.get("verifications"):
            for v in packet["verifications"]:
                method = f" · {v['method']}" if v.get("method") else ""
                out.append(f"- `{v['id']}` — {v['subject']}: **{v['outcome']}**{method}")
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "verifications")
        out.append("")

        out += ["## Verification Commands"]
        if packet["verification"]:
            out += [f"- {c}" for c in packet["verification"]]
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "verification")
        out.append("")

    out += ["## Stale / Risk Warnings"]
    # Name the threshold next to the ages it governs: every age below is measured,
    # this one number is the cutoff they are compared against.
    if packet.get("stale_after_days") is not None:
        out.append(
            f"_(ages below are measured; the cutoff is "
            f"{packet['stale_after_days']} days — set with `--stale-days`)_"
        )
    if packet["warnings"]:
        out += [f"- {w}" for w in packet["warnings"]]
    else:
        out.append("_(no computed staleness or risk signals)_")
    out += _omitted_note(packet, "warnings")
    out.append("")

    # Record text rendered as data (audit F17): control and invisible
    # characters escaped, framing tags neutralized. Clean text is unchanged.
    from breadcrumbs import safetext

    return safetext.block("\n".join(out).rstrip() + "\n")
