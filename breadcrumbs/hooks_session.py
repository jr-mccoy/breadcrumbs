"""breadcrumbs — the `SessionStart` hook.

Records the HEAD the session starts from (the Stop hook counts this session's
commits from it) and injects the resume packet. After a compaction it also
says what was in flight when the context was destroyed: the mined candidates
the `PreCompact` hook salvaged.

Moved out of `cli.py` (health review 2.1). `cli.cmd_hook` dispatches here.
"""

from __future__ import annotations

import json
from pathlib import Path

from breadcrumbs import cli
from breadcrumbs import git as _git
from breadcrumbs import hooks_stop as _hooks_stop
from breadcrumbs import packet as _packet


# Lines of mined candidates the post-compaction preamble may list. The rest are
# still in the inbox; `crumb inbox` is one command away.
_COMPACT_PREAMBLE_MAX_JOTS = 10

# Headroom the preamble may add on top of the packet's own budget. A compaction
# has just freed the entire context window, so this is the cheapest context in
# the session and the most valuable — but it is still bounded.
_COMPACT_PREAMBLE_TOKENS = 1000


def _compaction_preamble(memory_dir: Path, session_id: str) -> str:
    """What was in flight when the context was destroyed, for the model that lost it.

    After a compaction the model holds a summary and has no memory of the
    records it was shown or the task it was on. `PreCompact` cannot tell it
    anything — that hook's output never reaches the model — so it left the facts
    in `private/` and this is where they are read back.

    Empty when there is no marker for this session, which is the normal case:
    every other `source` value means no compaction happened.
    """
    from breadcrumbs import hooks_common, safetext

    marker = hooks_common.compaction_marker(memory_dir, session_id)
    if not marker:
        return ""
    lines = [
        "breadcrumbs: context was compacted. What follows is what was in flight "
        "before it; the full resume packet comes after.",
        "",
    ]
    state = hooks_common.prompt_state(memory_dir, session_id)
    # The latest substantive task, whether or not memory matched it (audit
    # F15): acknowledgements and slash commands do not replace it. What memory
    # matched is listed only when it was matched for *that* task; an earlier
    # task's hits are not passed off as this one's.
    task = state.get("task") if isinstance(state.get("task"), dict) else {}
    if state.get("last_prompt"):
        lines.append(
            "Latest task before compaction (the user's words): "
            + safetext.inline(state["last_prompt"], hooks_common.SESSION_PROMPT_CHARS + 40)
        )
    elif task.get("withheld"):
        why = (
            "retain_prompt_text is false"
            if task["withheld"] == "policy"
            else "it contained a credential"
        )
        lines.append(f"Latest task before compaction: not retained ({why}).")
    if state.get("matched"):
        lines.append(
            "Records memory matched for it: " + ", ".join(f"`{i}`" for i in state["matched"])
        )
    elif task and state.get("last_prompt"):
        lines.append("Memory matched nothing for it.")
    # Everything this session has waiting, not only what the last firing mined.
    # A compaction that found nothing new — because the Stop hook already mined
    # the same range — would otherwise report "nothing salvaged" while the
    # inbox holds a dozen candidates this very session produced. What the model
    # needs here is what it can act on, not which firing wrote it.
    rows = _hooks_stop._session_jot_rows(memory_dir, session_id)
    if rows:
        shown = rows[:_COMPACT_PREAMBLE_MAX_JOTS]
        lines += [
            "",
            "Mined from this session so far (unconfirmed — promote with "
            "`crumb inbox promote <id> <type>`, or drop with `crumb inbox drop <id>`):",
        ]
        lines += [
            f"- `{r['id']}` [{r.get('kind', 'note')}] {safetext.inline(r['text'], 300)}"
            for r in shown
        ]
        if len(rows) > len(shown):
            lines.append(f"- … and {len(rows) - len(shown)} more in `crumb inbox`")
    else:
        lines.append("Nothing durable was mined from the transcript before compaction.")
    text = "\n".join(lines)
    # Trim the mined list first: the last prompt is the cheapest, most useful
    # line here, and dropping it to keep candidates would be backwards.
    while (
        _packet.approx_tokens(text) > _COMPACT_PREAMBLE_TOKENS
        and lines
        and lines[-1].startswith("- ")
    ):
        lines.pop()
        text = "\n".join(lines)
    return text + "\n\n"


def _record_session_start(memory_dir: Path, root: Path, payload: dict) -> None:
    """Remember the HEAD this session starts from — the Stop hook counts this
    session's commits from it (field report 2026-10-01, issue 2). A resumed or
    compacted session keeps its original start. Never raises."""
    try:
        from breadcrumbs import hooks_common

        head = _git.head(root)
        if head:
            key = hooks_common.session_id_of(payload)
            hooks_common.set_session_baseline(
                memory_dir,
                key,
                head,
                keep_existing=True,
                # A payload with no session id and no transcript cannot say
                # which session it is, so each start is a new one: keeping the
                # first-ever start counted every commit since as this session's.
                restart=key == hooks_common.UNKNOWN_SESSION,
            )
    except Exception:  # pragma: no cover - a SessionStart hook must never fail
        pass
    # Machine-local jots past their expiry: nothing else deletes them, and every
    # Stop firing loads the whole inbox (0.6.0). Never touches a committed jot.
    try:
        from breadcrumbs import inbox as _inbox

        _inbox.prune_private_jots(memory_dir)
    except Exception:  # pragma: no cover - best-effort
        pass
    # A `git pull` or checkout since the last crumb write leaves the guard
    # pre-filter unverified, and then every tool call pays a full guard run
    # until something writes (field report 2026-10-01, issue 6: "prefilter:
    # unverified" on most firings). Republish once here, where one slow firing
    # per session is affordable; skip if another writer holds the lock.
    try:
        from breadcrumbs import lock as _lock
        from breadcrumbs import projections as _projections

        if _projections.verified(memory_dir, root, cli.GUARD_PREFILTER_FILENAME) is None:
            cli.try_reindex_projections(memory_dir, root, lock_timeout=_lock.HOOK_TIMEOUT)
    except Exception:  # pragma: no cover - best-effort
        pass


def _hook_session(memory_dir: Path, root: Path, payload: dict | None = None) -> int:
    out: dict = {}
    payload = payload or {}
    if memory_dir.is_dir():
        _record_session_start(memory_dir, root, payload)
        try:
            # `source` says why this SessionStart fired. Absent on older harness
            # versions, which is `startup` for every practical purpose.
            compacted = str(payload.get("source") or "startup") == "compact"
            task = None
            if compacted:
                from breadcrumbs import hooks_common

                session_id = hooks_common.session_id_of(payload)
                # The latest substantive task before the compaction is the best
                # statement of what this session is doing, so the rebuilt packet
                # is ordered by relevance to it (WM-20) rather than by recency.
                # It is the latest task whether or not memory matched it (audit
                # F15), and absent when its text was not retained.
                task = hooks_common.prompt_state(memory_dir, session_id).get("last_prompt")
            # This hook is Claude Code's, which loads the project's CLAUDE.md
            # itself. A promoted record whose rule is in that file right now is
            # already in the session's context, so only those are left out
            # (audit F13); everything else stays, rule text included.
            from breadcrumbs import promote as _promote

            packet = _packet.build_resume_packet(
                memory_dir,
                root,
                task=task or None,
                loaded_rules=_promote.loaded_rules(root, ("CLAUDE.md",)),
                loaded_rules_from=("CLAUDE.md",),
            )
            context = _packet.render_packet_markdown(packet)
            if compacted:
                context = _compaction_preamble(memory_dir, session_id) + context
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": context,
                }
            }
            # The packet is about to be injected into a session: this is the
            # single most load-bearing surfacing the tool performs. The ids are
            # read off the packet after its budget trimming, and the promoted
            # records left out for CLAUDE.md are not in it.
            _packet._record_packet_surfacings(
                memory_dir, packet, session_id=str(payload.get("session_id") or "") or None
            )
        except Exception:  # pragma: no cover - never fail a session start on memory
            out = {}
    print(json.dumps(out))
    return 0
