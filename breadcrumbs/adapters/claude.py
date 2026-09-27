"""The Claude Code adapter (audit WP17, finding F22).

Claude Code sends a hook a JSON payload. For `PreToolUse` it names the tool
(`tool_name`) and passes its input (`tool_input`). This module is the one
place those payloads become a guard action, and it declares, per tool, what
breadcrumbs does with it:

- **guarded**: normalized to an action (and the files it touches), matched by
  the installed `PreToolUse` hook, and covered by
  `tests/test_adapter_contracts.py`;
- **ignored**: a tool that cannot change the project (reads, searches, web
  fetches). The hook is not installed for it, and a payload naming it yields
  no action.

A tool name in neither list is unknown. It yields no action, and
`normalize_tool` reports it as `unsupported` rather than guessing from its
input's shape, which is how `PowerShell` used to pass through as an empty
action.

The field names are Claude Code's documented tool inputs. `CONTRACT_VERSION`
changes when this mapping changes, and the matcher `crumb init --with-hooks`
installs is built from `GUARDED_TOOLS`, so the two cannot drift apart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

HOST = "claude-code"
CONTRACT_VERSION = 2  # 1: Bash|Edit|Write|MultiEdit|Task|Agent; 2: + PowerShell, NotebookEdit

# How much of an edit's new content the guard sees, and of a subagent's prompt.
CONTENT_SNIPPET_CHARS = 400
SUBAGENT_PROMPT_CHARS = 1200

SHELL_TOOLS = ("Bash", "PowerShell")
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
# The subagent tool has carried both names across harness versions; matching a
# name that does not exist costs nothing.
SUBAGENT_TOOLS = ("Task", "Agent")
GUARDED_TOOLS = SHELL_TOOLS + EDIT_TOOLS + SUBAGENT_TOOLS
IGNORED_TOOLS = (
    "Read",
    "Glob",
    "Grep",
    "LS",
    "WebFetch",
    "WebSearch",
    "TodoWrite",
    "NotebookRead",
    "BashOutput",
    "KillShell",
    "ExitPlanMode",
)

# The `PreToolUse` matcher `crumb init --with-hooks` installs.
GUARD_MATCHER = "|".join(GUARDED_TOOLS)

# Which Claude Code hook events breadcrumbs installs, and what each is for.
HOOK_EVENTS = {
    "SessionStart": "resume packet injected at session start",
    "UserPromptSubmit": "prompt retrieval; corrections captured as local jots",
    "PreToolUse": "guard advisories for " + GUARD_MATCHER,
    "Stop": "session capture and the extraction turn",
    "PreCompact": "compaction marker and re-injection",
    "SubagentStop": "subagent extraction prompt",
}


@dataclass(frozen=True)
class Action:
    """What a tool call proposes to do, in the guard's terms."""

    tool: str
    kind: str  # shell | edit | subagent | none
    text: str = ""
    files: list[str] = field(default_factory=list)
    supported: bool = True  # False: a tool name this adapter does not know


def _snippet(text: object, limit: int) -> str:
    return " ".join(str(text or "").split())[:limit]


def normalize_tool(tool: str, tool_input: dict, *, paths_from_text=None) -> Action:
    """Normalize one `PreToolUse` payload's tool call.

    `paths_from_text` extracts file paths from free text (the CLI passes its
    own). It is used for a subagent's prompt.
    """
    tool = str(tool or "")
    tool_input = tool_input if isinstance(tool_input, dict) else {}
    if tool in SHELL_TOOLS:
        return Action(tool, "shell", str(tool_input.get("command") or "").strip())
    if tool in EDIT_TOOLS:
        if tool == "NotebookEdit":
            path = tool_input.get("notebook_path") or ""
            mode = str(tool_input.get("edit_mode") or "replace")
            new = "" if mode == "delete" else tool_input.get("new_source") or ""
            verb = "delete a cell in" if mode == "delete" else "edit"
        else:
            path = tool_input.get("file_path") or tool_input.get("path") or ""
            verb = "edit"
            if tool == "Write":
                new = tool_input.get("content") or ""
            elif tool == "MultiEdit":
                edits = tool_input.get("edits")
                parts = []
                if isinstance(edits, list):
                    for e in edits:
                        if isinstance(e, dict) and e.get("new_string"):
                            parts.append(str(e["new_string"]))
                new = "\n".join(parts)
            else:
                new = tool_input.get("new_string") or ""
        snippet = _snippet(new, CONTENT_SNIPPET_CHARS)
        text = f"{verb} {path}: {snippet}" if snippet else f"{verb} {path}"
        return Action(tool, "edit", text.strip(), [str(path)] if path else [])
    if tool in SUBAGENT_TOOLS:
        # A subagent starts cold: its launch prompt is the best description of
        # the action a session produces. Paths it names are mined like prose.
        prompt = tool_input.get("prompt") or tool_input.get("description") or ""
        text = _snippet(prompt, SUBAGENT_PROMPT_CHARS)
        files = sorted(paths_from_text(text)) if paths_from_text else []
        return Action(tool, "subagent", text.strip(), files)
    return Action(tool, "none", supported=tool in IGNORED_TOOLS)


def capabilities() -> dict:
    """The versioned declaration `docs/compatibility-matrix.md` publishes."""
    return {
        "host": HOST,
        "contract_version": CONTRACT_VERSION,
        "hook_events": dict(HOOK_EVENTS),
        "guarded_tools": list(GUARDED_TOOLS),
        "ignored_tools": list(IGNORED_TOOLS),
        "guard_matcher": GUARD_MATCHER,
    }
