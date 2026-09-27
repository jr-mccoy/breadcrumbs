"""breadcrumbs — record text rendered as data (audit F17, WP13).

Record files are repository content, and their text is handed to agents: in a
hook's `additionalContext`, the resume packet, a guard reason, an MCP resource
or tool result. The JSON around each of those is produced by `json.dumps` (or
the MCP SDK), so no record text can break the serialization itself. What text
*can* do is impersonate framing inside the payload a model reads:

- **Line breaks in a one-line field.** A title carrying a newline (or U+2028,
  or a bare carriage return) starts a line of its own, which can pose as the
  tool's header or verdict ("breadcrumbs guard: PROCEED …").
- **Control characters.** ANSI escapes rewrite a terminal; NUL and friends
  confuse readers; a carriage return overprints the line before it.
- **Invisible formatting.** Bidirectional overrides and zero-width characters
  make what is displayed differ from what is read.
- **Framing tags.** A closing tag, or an opening tag named like a harness
  envelope (`</system-reminder>`, `<function_results>`), can pose as the end of
  the tool's output and the start of something the harness said.

The source file is never changed. Only what is rendered from it is:

- `inline(value, limit)` for a field that must stay on one line: every line
  break and tab becomes a space, whitespace collapses, control and invisible
  characters become visible escapes (`\\x1b`, `\\u202e`), framing tags lose
  their `<` (`&lt;/system-reminder>`), and the result is cut to `limit`.
- `block(text, limit)` for multi-line text: newlines stay (`\\r\\n` becomes
  `\\n`; any other break, such as a bare `\\r` or U+2028, is shown as an
  escape rather than starting a line), everything else as `inline`, cut to
  `limit` with a note saying how much was left out.

Ordinary text, including Unicode letters, emoji, `<id>` placeholders and
Markdown, passes through unchanged.
"""

from __future__ import annotations

import re

# Characters that end a line somewhere: in a terminal, a Markdown renderer, a
# JSON/JS consumer, or a model's tokenizer.
_BREAKS = "\r\x0b\x0c\x1c\x1d\x1e\x85  "

# Zero-width and bidirectional formatting characters.
_INVISIBLE = frozenset("؜᠎​‌‍‎‏‪‫‬‭‮⁠⁡⁢⁣⁤⁦⁧⁨⁩﻿")

# Tag names that frame tool output, prompts or roles in the harnesses this tool
# runs under. An opening tag with one of these names is neutralized; any
# closing tag is.
_FRAMING = frozenset(
    {
        "system",
        "system-reminder",
        "function_calls",
        "function_results",
        "function",
        "functions",
        "result",
        "results",
        "output",
        "error",
        "tool_use",
        "tool_result",
        "tool",
        "invoke",
        "parameter",
        "instructions",
        "human",
        "assistant",
        "user",
        "document",
        "documents",
        "document_content",
        "source",
        "context",
        "untrusted_external_data",
        "pasted_content",
        "additionalcontext",
        "hookspecificoutput",
    }
)

_TAG = re.compile(r"<(/?)\s*([A-Za-z][\w:.-]*)")


def _escape(ch: str) -> str:
    code = ord(ch)
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"


def _clean_char(ch: str) -> str:
    code = ord(ch)
    if code < 0x20 and ch not in "\n\t":
        return _escape(ch)
    if 0x7F <= code <= 0x9F or ch in _INVISIBLE:
        return _escape(ch)
    return ch


def _neutralize_tags(text: str) -> str:
    def sub(m: re.Match) -> str:
        closing, name = m.group(1), m.group(2).lower()
        if closing or name in _FRAMING or name.startswith("antml"):
            return "&lt;" + m.group(0)[1:]
        return m.group(0)

    return _TAG.sub(sub, text)


def _clip(text: str, limit: int | None) -> str:
    if limit is None or len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def inline(value, limit: int | None = None) -> str:
    """`value` as one safe line of data (see the module docstring)."""
    text = str(value if value is not None else "")
    for br in _BREAKS + "\n\t":
        if br in text:
            text = text.replace(br, " ")
    text = "".join(_clean_char(ch) for ch in text)
    text = re.sub(r" {2,}", " ", text).strip()
    return _clip(_neutralize_tags(text), limit)


def block(text, limit: int | None = None) -> str:
    """`text` as safe multi-line data (see the module docstring)."""
    text = str(text if text is not None else "")
    text = text.replace("\r\n", "\n")
    # Only a real newline starts a line. Every other break (a bare carriage
    # return, U+2028, a form feed) is shown as an escape rather than turned
    # into a line nobody wrote.
    text = "".join(_escape(ch) if ch in _BREAKS else _clean_char(ch) for ch in text)
    text = _neutralize_tags(text)
    if limit is not None and len(text) > limit:
        left = len(text) - limit
        text = text[:limit] + f"\n… [{left} more characters not shown]"
    return text


def tree(value, limit: int | None = None):
    """Every string in a JSON-shaped value through `block`. Keys are kept."""
    if isinstance(value, str):
        return block(value, limit)
    if isinstance(value, dict):
        return {k: tree(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [tree(v, limit) for v in value]
    if isinstance(value, tuple):
        return tuple(tree(v, limit) for v in value)
    return value
