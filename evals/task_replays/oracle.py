"""The task oracle for the continuity replays (audit WP19).

Deliberately independent of breadcrumbs: it imports nothing from the package
and judges only text, so the same oracle scores every baseline and can be
rerun on a saved `results.json` without the code that produced it.

A scenario's oracle has two lists of token groups:

- `must_deliver`: facts session 2 needs. A group is delivered when every one
  of its tokens appears, case-insensitively, in the text handed to session 2.
- `pointer`: the title of the record that holds those facts. Delivered means
  session 2 was told where the facts are, one lookup away.
- `stale_as_current`: guidance that is no longer true on this branch or since
  a later decision. It counts only when it appears in text presented as
  current, so a caller passes only that text (the packet's "active" sections,
  a note file, a guard warning). A superseded line shown as history is the
  caller's to leave out.
"""

from __future__ import annotations


def _has(text: str, group: list[str]) -> bool:
    low = text.lower()
    return all(token.lower() in low for token in group)


def judge(oracle: dict, delivered: dict[str, str]) -> dict:
    """`delivered`: moment -> text handed over at that moment (`start`,
    `prompt`, `action`). Returns what was delivered when, and whether stale
    guidance was presented as current."""
    must = oracle.get("must_deliver") or []
    pointer = oracle.get("pointer") or []
    stale = oracle.get("stale_as_current") or []
    start = (delivered.get("start") or "") + "\n" + (delivered.get("prompt") or "")
    action = delivered.get("action") or ""
    everything = start + "\n" + action
    return {
        "by_start": all(_has(start, g) for g in must),
        "at_action": all(_has(action, g) for g in must),
        "by_action": all(_has(everything, g) for g in must),
        "pointer_by_start": all(_has(start, g) for g in pointer),
        "pointer_at_action": all(_has(action, g) for g in pointer),
        "groups_delivered": sum(1 for g in must if _has(everything, g)),
        "groups_total": len(must),
        "stale_presented": any(_has(everything, g) for g in stale),
    }
