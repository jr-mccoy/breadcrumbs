"""Builders for synthetic Claude Code transcripts, shared by the hook tests.

Not a test module — `unittest discover` ignores it, and importing it from two
test files loads it once. `tests/test_transcript.py` pins the *shape* these
produce against the format the miner documents; everything else just needs a
transcript that exercises a rule.
"""

from __future__ import annotations

import json
from pathlib import Path


def user_text(text: str) -> dict:
    """A user turn carrying the user's own words."""
    return {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]},
    }


def tool_use(call_id: str, name: str, payload: dict) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": call_id, "name": name, "input": payload}],
        },
    }


def tool_result(call_id: str, text: str, is_error: bool = False) -> dict:
    """A tool result, which the harness delivers inside a *user*-role message."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": call_id,
                    "content": text,
                    "is_error": is_error,
                }
            ],
        },
    }


def bash(call_id: str, command: str, result: str, is_error: bool = False) -> list[dict]:
    return [tool_use(call_id, "Bash", {"command": command}), tool_result(call_id, result, is_error)]


def edit(call_id: str, path: str, new: str = "x = 1") -> list[dict]:
    return [
        tool_use(call_id, "Edit", {"file_path": path, "new_string": new}),
        tool_result(call_id, "ok"),
    ]


def write_transcript(directory: Path, entries: list[dict], name: str = "transcript.jsonl") -> Path:
    path = Path(directory) / name
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


# The canonical debugging loop: a command fails, a file changes, it passes.
FIXED_TRANSCRIPT = (
    bash("c1", "python -m pytest tests/test_parser.py", "FAILED - AssertionError")
    + edit("c2", "src/parser.py")
    + bash("c3", "python -m pytest tests/test_parser.py", "2 passed")
)
