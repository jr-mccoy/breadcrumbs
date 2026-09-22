"""breadcrumbs — the `PreCompact` and `SubagentStop` hooks (WM-11, WM-13).

Two events, one shape: something is about to destroy context, so mine what is
there into machine-local jots and get out of the way. Neither can speak to the
model, and neither blocks.

**PreCompact** is the biggest memory-loss event in a long session — the whole
conversation is about to be replaced by a summary. The hook cannot inject
anything (its stdout goes to the debug log), so it does the only useful
deterministic thing: mines the transcript, and leaves a marker so the
`SessionStart` that fires afterwards with `source: compact` can say what was
salvaged. That handoff, not this hook's output, is how the mined candidates
reach the model.

**SubagentStop** fires when a subagent finishes. Its findings — a command it got
working, a test it proved passes — currently vanish with it, because the parent
only ever sees the subagent's final message. Mining its transcript keeps them.

Neither hook blocks, though `SubagentStop` supports it exactly like `Stop`.
Holding a subagent to make it write records is a prompt-fatigue question that
needs the field test `open-questions.md` already asks for; `subagent_extraction`
in `manifest.yml` is reserved for that work and does nothing yet.
"""

from __future__ import annotations

from pathlib import Path

from breadcrumbs import cli, hooks_common, transcript

# Reserved manifest key for the deferred "hold the subagent" behaviour (WM-13).
# Read here so the name is claimed and a store can set it before the behaviour
# exists, rather than having the key mean something different later.
SUBAGENT_EXTRACTION_KEY = "subagent_extraction"


def subagent_extraction_enabled(memory_dir: Path) -> bool:
    """Whether a finished subagent may be held for an extraction turn.

    Defaults to **False**, which is the opposite of `extraction_prompt`'s
    default: the parent's Stop hook already asks once per unit of work, and
    adding a second prompt per subagent is precisely the fatigue the open
    question is about. Nothing consults this yet.
    """
    manifest = cli.load_manifest(memory_dir) or {}
    raw = str(manifest.get(SUBAGENT_EXTRACTION_KEY, "false")).strip().lower()
    return raw in ("true", "yes", "on", "1")


def hook_compact(memory_dir: Path, root: Path, payload: dict) -> dict:
    """`PreCompact` — salvage what the compaction is about to discard."""
    if not memory_dir.is_dir():
        return {}
    session_id = hooks_common.session_id_of(payload)
    report = transcript.mine_transcript_into_jots(
        memory_dir,
        root,
        payload.get("transcript_path"),
        session_id=session_id,
        use_cursor=True,
    )
    # The marker is written even when nothing was mined. "The context was
    # compacted and nothing survived" is exactly what the post-compaction
    # SessionStart needs to say; an absent marker would read as "no compaction
    # happened", which is a different and wrong thing.
    hooks_common.record_compaction(
        memory_dir,
        session_id,
        trigger=str(payload.get("trigger") or "") or None,
        commit=cli.git_commit(root),
        jots=report["written"],
    )
    return {}


def hook_subagent(memory_dir: Path, root: Path, payload: dict) -> dict:
    """`SubagentStop` — keep what the subagent found.

    The transcript is the *subagent's* and it is finished, so there is no cursor
    to keep: mine the whole thing once. Its `agent_type` rides along as a tag so
    a later review can see which kinds of subagent produce candidates worth
    promoting and which produce noise.
    """
    if not memory_dir.is_dir():
        return {}
    agent_type = str(payload.get("agent_type") or "").strip()
    extra_tags = ["subagent"]
    if agent_type:
        extra_tags.append(f"agent:{agent_type}")
    transcript.mine_transcript_into_jots(
        memory_dir,
        root,
        payload.get("transcript_path"),
        # Keyed by the parent session so the Stop hook's "what did this session
        # produce" query finds them: the subagent's own id dies with it, and a
        # candidate nobody can retrieve is a candidate nobody promotes.
        session_id=hooks_common.session_id_of(payload),
        use_cursor=False,
        extra_tags=extra_tags,
    )
    return {}
