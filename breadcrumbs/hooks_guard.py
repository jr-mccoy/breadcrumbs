"""breadcrumbs — the `PreToolUse` guard hook.

Fires before every tool call, so it is the hot path: a cheap pre-filter first
(the reindex-time trap index, read only when the current generation vouches
for it), and the full guard only when that pre-filter cannot clear the action;
`doctor --hook-log` reports a machine whose p50 is over `HOOK_GUARD_BUDGET_MS`.
It speaks only when a record is about the action, damps repeats within a
session, and never blocks a tool call by failing.

Moved out of `cli.py` (health review 2.1). `cli.cmd_hook` dispatches here.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from breadcrumbs import cli
from breadcrumbs import shellcmd as _shellcmd
from breadcrumbs.adapters import claude as _claude
from breadcrumbs import textmatch as _textmatch
from breadcrumbs import scoring as _scoring


def _prefilter_trap_hit(memory_dir: Path, action: str, files: list[str] | None) -> bool:
    """Does the action overlap the reindex-time trap-token index?

    One small generated-file read — no record walk — keeping the pre-filter's
    "cheap on the common path" promise while closing the near-miss class where a
    routine-looking command (`pytest -n auto`) matches a recorded trap that the
    keyword classifier and the destructive-op regex are both blind to.

    The index is used only when the current generation vouches for it
    (`projections.verified`). A missing, corrupt, replaced or out-of-date one —
    or one written before the manifest existed — is not evidence that the store
    holds no hazard (audit F11). Such an index counts as "possibly risky", so the
    caller runs the full guard against the records and a real trap is still
    found. Only a verified index can keep the hook quiet.
    """
    from breadcrumbs import hooklog as _hooklog
    from breadcrumbs import projections as _projections

    _textmatch.activate_store_aliases(memory_dir)
    raw = _projections.verified(memory_dir, Path(memory_dir).parent, cli.GUARD_PREFILTER_FILENAME)
    try:
        idx = json.loads(raw.decode("utf-8")) if raw is not None else None
    except ValueError:
        idx = None
    if not isinstance(idx, dict) or idx.get("format") != cli.GUARD_PREFILTER_FORMAT:
        _hooklog.note(prefilter="unverified")
        return True
    # The pre-filter leaves secret-shaped and opaque tokens out (item 9 of the
    # 0.5.0 retest), so an action holding one is checked in full.
    if cli._prefilter_opaque_action_token(action):
        return True
    # Each test mirrors one way `_score_item` lets a match through (see
    # `_build_guard_prefilter`), so this can only admit more than full guard
    # would surface, never less (audit WP11). Stems are re-stemmed at read time
    # under the store's aliases: `_stem` is idempotent.
    if _scoring._names_command(_shellcmd.match_tokens(action), idx.get("commands") or ()):
        return True
    q_specific = _textmatch._specific(action)
    sets = idx.get("token_sets")
    if isinstance(sets, list):
        for words in sets:
            if (
                len(q_specific & {_textmatch._stem(str(t)) for t in words})
                >= _scoring.GUARD_MIN_KEYWORD_OVERLAP
            ):
                return True
    else:
        idx_tokens = {_textmatch._stem(str(t)) for t in (idx.get("tokens") or ())}
        if len(q_specific & idx_tokens) >= _scoring.GUARD_MIN_KEYWORD_OVERLAP:
            return True
    if len(q_specific) == 1 and q_specific <= {
        _textmatch._stem(str(t)) for t in (idx.get("titles") or ())
    }:
        return True
    if q_specific & {_textmatch._stem(str(t)) for t in (idx.get("tags") or ())}:
        return True
    action_paths = _textmatch._norm_files(
        _textmatch._paths_from_text(action)
    ) | _textmatch._norm_files(files or [])
    index_paths = _textmatch._norm_files(idx.get("paths") or ())
    return bool(action_paths & index_paths)


def _prefilter_exact_hit(memory_dir: Path, action: str, files: list[str] | None) -> bool:
    """Does a verified pre-filter say a record names this exact command or a
    path it touches? True (run full guard) when the pre-filter is unverified."""
    from breadcrumbs import projections as _projections

    raw = _projections.verified(memory_dir, Path(memory_dir).parent, cli.GUARD_PREFILTER_FILENAME)
    try:
        idx = json.loads(raw.decode("utf-8")) if raw is not None else None
    except ValueError:
        idx = None
    if not isinstance(idx, dict) or idx.get("format") != cli.GUARD_PREFILTER_FORMAT:
        return True
    if _scoring._names_command(_shellcmd.match_tokens(action), idx.get("commands") or ()):
        return True
    action_paths = _textmatch._norm_files(
        _textmatch._paths_from_text(action)
    ) | _textmatch._norm_files(files or [])
    if action_paths & _textmatch._norm_files(idx.get("paths") or ()):
        return True
    # A path or command the pre-filter left out as opaque (item 9).
    return cli._prefilter_opaque_action_token(action)


# How much of an edit's new content, and of a subagent's launch prompt, feeds
# the guard; and which tools launch a subagent. The Claude Code adapter owns
# these (audit WP17); the names stay here as the compatibility surface.
_HOOK_CONTENT_SNIPPET_CHARS = _claude.CONTENT_SNIPPET_CHARS
SUBAGENT_TOOLS = _claude.SUBAGENT_TOOLS
_HOOK_SUBAGENT_PROMPT_CHARS = _claude.SUBAGENT_PROMPT_CHARS


def _hook_action_from_tool(tool: str, tool_input: dict) -> tuple[str, list[str] | None]:
    """Derive a guard action string + affected files from a PreToolUse payload.

    Normalized by the Claude Code adapter (`breadcrumbs.adapters.claude`),
    which declares every tool it guards. For file edits the action carries a
    bounded snippet of the *new* content (P0-3). An unknown tool yields no
    action.
    """
    action = _claude.normalize_tool(tool, tool_input, paths_from_text=_textmatch._paths_from_text)
    return action.text, action.files or None


# Advisory-dedupe state for the PreToolUse guard, keyed by host session. Lives
# in private/ (machine-local, gitignored) because it is per-checkout runtime
# state, not memory. Best-effort: a read or write failure must never block the
# hook, and losing the file only means one repeated advisory.
#
# The implementation moved to `breadcrumbs/hooks_common.py` when the
# `UserPromptSubmit` hook needed the same "have I already said this" question
# (WM-10). These names stay as the compatibility surface — they are what the
# existing tests and any external reader know this state by.
_HOOK_SEEN_FILENAME = "hook-guard-seen.json"
_HOOK_SEEN_MAX_SESSIONS = 8
_HOOK_SEEN_MAX_KEYS = 200


def _hook_damp_repeats(memory_dir: Path, session_id: str, result: dict) -> dict:
    """`result` without the advisory matches this session was already shown.

    A match stays when it objects to the action (blocking) or when the action
    itself names its file, the file a command writes, or its exact command:
    that is news about *this* action, not a repeat. The verdict is decided
    again from what is left (a high-impact action keeps ASK_HUMAN), so a
    firing whose every match was a repeat goes quiet. Never raises: without
    damping state the firing is left as it was.
    """
    try:
        from breadcrumbs import hooks_common as _hooks_common

        seen = _hooks_common.delivered_records(memory_dir, session_id, filename=_HOOK_SEEN_FILENAME)
    except Exception:  # pragma: no cover - damping is best-effort
        return result
    if not seen:
        return result

    def keep(m: dict) -> bool:
        if m["id"] not in seen:
            return True
        if (m.get("stance") or _scoring._match_stance(m.get("signals"))) == "blocking":
            return True
        return bool({"file", "writes-file", "command"} & set(m.get("signals") or ()))

    matches = result.get("matches") or []
    kept = [m for m in matches if keep(m)]
    if len(kept) == len(matches):
        return result
    verdict = _scoring._decide_verdict(
        kept, result.get("action_classes") or [], result.get("action", "")
    )
    # Never louder than guard said: its caps (read-only, a memory edit) hold.
    verdict = _scoring._min_verdict(verdict, result["verdict"])
    if result.get("high_impact"):
        verdict = "ASK_HUMAN"
    return {
        **result,
        "verdict": verdict,
        "matches": kept,
        "damped": [m["id"] for m in matches if not keep(m)],
    }


def _hook_guard_advisory_seen(memory_dir: Path, session_id: str, key: str) -> bool:
    """True if this advisory key already fired for this session; records it if not.

    Same records + same file ⇒ say nothing after the first time (P0-2b): a
    READ_FIRST that repeats verbatim on every edit trains the agent to ignore
    the one that matters. Only advisories dedupe — PAUSE/ASK_HUMAN always fire.
    """
    from breadcrumbs import hooks_common

    return hooks_common.advisory_seen(memory_dir, session_id, key, filename=_HOOK_SEEN_FILENAME)


# Permission modes in which the user has already told the harness not to
# interrupt them. `bypassPermissions` (`--dangerously-skip-permissions`) and
# `dontAsk` are explicit standing instructions; re-raising a prompt inside them
# overrides a choice the user made deliberately, and a memory tool has no
# standing to do that. `acceptEdits` is NOT here: it auto-accepts *edits* only,
# so a prompt on a destructive Bash command is still the normal flow there.
#
# The harness hands every hook the current mode in `permission_mode`, which is
# exactly what the field makes possible. Nothing read it before, so
# `crumb hook guard` reinstated approval prompts for whole sessions that had
# opted out of them — the one report we have of this ended in a `sed` wrapper
# stripping the decision keys back out of our JSON, deliberately built to
# survive `pip install -U`. That is a user routing around the tool's default
# because the default was wrong.
_HOOK_NONPROMPTING_MODES = frozenset({"bypassPermissions", "dontAsk"})

# Escape hatch for anyone who wants the advisory shape unconditionally, so the
# answer is an env var rather than a wrapper that rewrites our output.
_GUARD_ADVISORY_ENV = "CRUMB_GUARD_ADVISORY"


def _hook_may_prompt(payload: dict) -> bool:
    """May this hook escalate to a permission prompt at all?

    Two independent vetoes, both the user's: the session's permission mode, and
    an explicit `CRUMB_GUARD_ADVISORY=1`. A veto never suppresses the *warning* —
    the matched records still reach the agent as `additionalContext`. It
    suppresses only the interruption, which is the part the user opted out of.
    """
    if str(os.environ.get(_GUARD_ADVISORY_ENV, "")).strip().lower() in ("1", "true", "yes", "on"):
        return False
    mode = payload.get("permission_mode")
    return not (isinstance(mode, str) and mode in _HOOK_NONPROMPTING_MODES)


def _hook_surfacing_matches(result: dict) -> list[dict]:
    """The matches worth spending the agent's context on (G2).

    A match whose only signal is shared vocabulary — no file, no tag, no title
    hit, no explicit do-not-retry, no open blocker — is what a store produces for
    *any* action phrased in its own language. `crumb guard` still returns it as
    context, because a caller who asked explicitly should see what was
    considered; the hook fires on every tool call and pays for every word, so
    there it is dropped whenever anything better is available. An advisory the
    agent sees on every command is one it learns to skim, and then it skims the
    one that mattered.

    Empty when *every* match is keyword-only — the caller decides what to do
    with that; see `_hook_guard`.
    """
    return [
        m
        for m in result.get("matches", [])
        if _scoring.GUARD_SURFACING_SIGNALS & set(m.get("signals", ()))
    ]


# Matches the guard hook's reason names. Only these are emitted, so only these
# are counted as surfaced (audit F16).
_HOOK_GUARD_REASON_MATCHES = 3


def _hook_guard_reason(result: dict, matches: list[dict] | None = None) -> str:
    from breadcrumbs import safetext

    lines = [f"breadcrumbs guard: {result['verdict']} for this action."]
    for m in (result.get("matches", []) if matches is None else matches)[
        :_HOOK_GUARD_REASON_MATCHES
    ]:
        # One line per record, as data: a title cannot start a line of its
        # own or close the envelope the host wraps this in (audit F17).
        title = safetext.inline(m.get("title") or m.get("id") or "record", 200)
        why = safetext.inline(m.get("reason") or "", 200)
        lines.append(f"- {title}" + (f" ({why})" if why else ""))
    if result.get("compatibility"):
        lines.append(f"⚠ {result['compatibility']}")
    return "\n".join(lines)


# The guard hook's budget for its p50 on the common path (field report
# 2026-10-01, issue 6). `doctor --hook-log` says when a machine is over it.
HOOK_GUARD_BUDGET_MS = 300


def _outside_project(path: str, root: Path) -> bool:
    """Is `path` (as a tool call names it) outside the project root?"""
    try:
        p = Path(os.path.expanduser(str(path)))
        # Relative paths are the project's. An absolute path counts as outside
        # only when its directory really exists elsewhere — a path-shaped name
        # that is no directory on this machine (`/api/orders`) is not a claim
        # about the filesystem, so it is still matched.
        if not p.is_absolute() or not p.parent.is_dir():
            return False
        return not p.resolve().is_relative_to(Path(root).resolve())
    except (OSError, ValueError):
        return False


def _hook_guard(memory_dir: Path, root: Path, payload: dict) -> int:
    if not memory_dir.is_dir():
        print(json.dumps({}))
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        # A truthy non-dict tool_input crashed with a raw traceback where every
        # other malformed-payload path degrades to {}.
        tool_input = {}
    from breadcrumbs import hooklog as _hooklog

    _hooklog.note(tool=str(payload.get("tool_name") or "") or None)
    action, files = _hook_action_from_tool(payload.get("tool_name") or "", tool_input)
    if not action:
        print(json.dumps({}))
        return 0
    # An edit to a file outside the project (the agent's own memory folder, a
    # scratch file) is not this store's business: a project trap about
    # `handoff.md` fired on ~/.claude/…/memory/handoff.md (issue 7b).
    if files and all(_outside_project(f, root) for f in files):
        _hooklog.note(skipped="outside-project")
        print(json.dumps({}))
        return 0
    # Cost-aware pre-filter: pure-string classify + risk regex on the common
    # path, plus one read of the reindex-time trap-token index so
    # trap-shaped routine commands escalate too. Only a plausibly-risky action
    # escalates to full guard scoring.
    _primary, classes = _scoring.classify_action(action)
    # A read-only command (every segment) is guarded only for memory about
    # *it*: a trap naming the exact command, or a record about a path it
    # touches. Shared vocabulary alone cannot raise it past READ_FIRST, and
    # was the bulk of the field's "a warning on every command" (issue 7).
    if _scoring._is_read_only_action(action) and not _prefilter_exact_hit(
        memory_dir, action, files
    ):
        _hooklog.note(skipped="read-only")
        print(json.dumps({}))
        return 0
    risky = (
        classes != ["routine_edit"]
        or bool(_scoring._HOOK_RISK_RE.search(action))
        or bool(_shellcmd.high_impact(action))
        or _prefilter_trap_hit(
            memory_dir,
            action,
            list(files or []) + _shellcmd.crumb_writes(action, cli.MEMORY_DIRNAME),
        )
    )
    if not risky:
        _hooklog.note(skipped="prefilter")
        print(json.dumps({}))
        return 0
    from breadcrumbs import service as _service

    result = _service.guard(
        _service.Context(root, memory_dir, "hook"), action, files=files, staleness=False
    )
    verdict = result["verdict"]
    # Launching a subagent is not itself irreversible — the subagent's own tool
    # calls hit this same guard, where the blast radius actually is. So a launch
    # caps at READ_FIRST: the memory reaches the agent as context and no prompt
    # is raised. Asking twice for one piece of work is how a gate becomes noise.
    if (payload.get("tool_name") or "") in SUBAGENT_TOOLS and verdict not in (
        "PROCEED",
        "READ_FIRST",
    ):
        verdict = _scoring.GUARD_READ_ONLY_CEILING
        result = {**result, "verdict": verdict}
    session_id = str(payload.get("session_id") or "unknown")
    # Session damping (DoWhat retest of 0.5.0, item 5): an advisory record the
    # agent was already shown this session is not shown again, unless this
    # action names its file or command. Two records came back on most firings
    # of one session — `git status`, `cp`, a reindex, a README edit — with a
    # different verdict each time, which the per-target repeat filter below
    # never caught. A blocking record, and a high-impact action, always speak.
    if verdict != "PROCEED":
        result = _hook_damp_repeats(memory_dir, session_id, result)
        verdict = result["verdict"]
        if result.get("damped"):
            _hooklog.note(damped=len(result["damped"]))
    _hooklog.note(verdict=verdict)
    if verdict == "PROCEED":
        print(json.dumps({}))
        return 0
    # What the agent is actually shown. A keyword-only match rides along for free
    # today: `git status` drew two advisory lines, one of them a record that
    # shares nothing with it but the word "status". Where better matches exist,
    # the weak ones are dropped; where they are all there is, they are still
    # shown — a strong keyword-only match escalating through the score band is a
    # deliberate behaviour of this tool, not something to silence from here.
    shown = _hook_surfacing_matches(result) or result.get("matches", [])
    reason = _hook_guard_reason(result, shown)
    # Only what the reason names is emitted (audit F16): it lists the first
    # `_HOOK_GUARD_REASON_MATCHES`. Counted just before each non-empty output,
    # keyed by host session so WM-42 can ask "how many *sessions* did this
    # record reach" rather than "how many times did one session fire the hook".
    emitted = shown[:_HOOK_GUARD_REASON_MATCHES]
    _hooklog.note(candidates=len(result.get("matches", [])), matches=len(shown), emitted=0)

    def count_emitted() -> None:
        cli._record_guard_surfacings(
            memory_dir,
            emitted,
            "hook-guard",
            session_id=str(payload.get("session_id") or "") or None,
        )
        _hooklog.note(emitted=len(emitted))
        try:
            from breadcrumbs import hooks_common as _hooks_common

            _hooks_common.add_delivered_records(
                memory_dir, session_id, [m["id"] for m in emitted], filename=_HOOK_SEEN_FILENAME
            )
        except Exception:  # pragma: no cover - damping state is best-effort
            pass

    if verdict == "READ_FIRST":
        # Dedupe within the host session: the same records surfacing for the
        # same file is information exactly once (P0-2b/P0-3). Keyed on the
        # matched record ids + the file (or the action when no file), so a new
        # record or a different file speaks again; scoped to READ_FIRST so a
        # PAUSE/ASK_HUMAN is never swallowed.
        target = (files or [None])[0] or result["action"]
        key = f"{target}|" + ",".join(sorted(m["id"] for m in shown))
        try:
            if _hook_guard_advisory_seen(memory_dir, session_id, key):
                _hooklog.note(deduped=True)
                print(json.dumps({}))
                return 0
        except Exception:  # pragma: no cover - dedupe must never block the hook
            pass
        # `permissionDecision: "allow"` is not neutral — it *auto-approves* the
        # call, skipping the prompt the user would otherwise get, and its reason
        # is shown only to the user, never to the model. Emitting it on an
        # advisory verdict removed a safety gate and swallowed the warning: the
        # exact inverse of "memory informs, never decides". So
        # READ_FIRST takes no permission decision at all — the normal flow is
        # left untouched and the matched records reach the agent as context.
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": reason,
            }
        }
        count_emitted()
        print(json.dumps(out))
        return 0
    # PAUSE / ASK_HUMAN — hand the call to the human with the reason attached,
    # but only if prompting is ours to do at all.
    #
    # Note what is deliberately NOT a second condition here: blast radius.
    # Gating the prompt on `destructive` as well was tried and reverted, because
    # by the time a verdict reaches this branch it is already one of exactly two
    # things — a match whose stance is `blocking` (an attempt someone wrote with
    # an explicit *Do Not Retry Unless*), or a high-impact action class. The
    # first is an authored instruction to stop, not an inference from overlap,
    # and suppressing it would silence the one channel the schema gives an
    # author for saying "not this again". The second is blast radius already.
    # Danger belongs on the escalation side (`_decide_verdict`), where it can
    # *raise* a verdict, rather than here, where it could only ever suppress an
    # authored one.
    if _hook_may_prompt(payload):
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                # `ask`, never `deny`: memory informs; it never allows or denies
                # on its own. The human still makes the call.
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            }
        }
        count_emitted()
        print(json.dumps(out))
        return 0
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": reason,
        }
    }
    count_emitted()
    print(json.dumps(out))
    return 0
