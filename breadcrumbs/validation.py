"""The record contract: shape and integrity checks shared by every writer and reader.

`validate` is the trust primitive, and every writer (CLI, MCP, hooks, inbox
promotion, lifecycle commands) runs it after writing and reverts on failure. The
per-record checks it ran used to establish presence, not shape: any non-empty
`evidence` satisfied the evidence rule, `confidence: certainly` and
`expires_at: tomorrow` passed, and a `superseded_by` naming a record that does not
exist retired the record in favour of nothing (audit F05).

This module owns those checks. It is pure and imports nothing from the package,
so the CLI, the MCP core and the packet builder can all call it without a cycle
and without paying for the CLI at import time.

Two levels:

- `record_issues(meta, rtype, rid)` — one record's fields, in isolation.
- `store_issues(entries)` — links between records: a `superseded_by` must name a
  record in the store, and a replacement chain must not loop.

An issue is `{"code", "field", "message"}`. Codes are stable identifiers a caller
may branch on; messages are for people and may change. These checks establish
that a record is well formed. They do not establish that its claim is true: a
well-formed evidence pointer is a pointer, not a proof.

What is deliberately *not* checked:

- `supersedes` targets. It is a historical back-link, and `crumb rollup sessions`
  deletes the snapshots it folds, so a rollup's `supersedes` names ids that are
  gone by design. Only the forward link, `superseded_by`, must resolve.
- Unknown frontmatter keys. They are preserved on every rewrite and are not an
  error; a newer writer's field must survive an older reader.
"""

from __future__ import annotations

import re
from datetime import datetime

VALID_CONFIDENCE = ("low", "medium", "high")
VALID_REVIEW_STATUS = ("unreviewed", "reviewed", "needs-review")
# What a writer may set. A legacy record with other text is *read* as `project`
# (docs/record-schema.md §4) and reported by `validate`; it is never rewritten.
RECORD_SCOPES = ("project", "branch")

TIMESTAMP_FIELDS = ("created_at", "updated_at", "expires_at", "last_confirmed", "promoted_at")

# The ISO-8601 subset this project writes and reads on every supported Python.
# `datetime.fromisoformat` accepts far more on 3.11+ than on 3.9/3.10 (and no `Z`
# before 3.11), so parsing alone would make `validate` pass a store on one
# interpreter and fail it on another.
_TIMESTAMP_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}"
    r"(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{3}|\.\d{6})?)?(?:Z|[+-]\d{2}:\d{2})?)?$"
)

# Stable issue codes.
CONFIDENCE_INVALID = "confidence-invalid"
REVIEW_STATUS_INVALID = "review-status-invalid"
SCOPE_UNSUPPORTED = "scope-unsupported"
EVIDENCE_MALFORMED = "evidence-malformed"
TIMESTAMP_INVALID = "timestamp-invalid"
SUPERSEDED_BY_MALFORMED = "superseded-by-malformed"
SUPERSESSION_SELF = "supersession-self"
SUPERSEDED_BY_MISSING = "superseded-by-missing"
SUPERSESSION_CYCLE = "supersession-cycle"


def _issue(code: str, field: str, message: str) -> dict:
    return {"code": code, "field": field, "message": message}


def parse_timestamp(value) -> datetime | None:
    """A timestamp in the supported subset, parsed; None when it is not one."""
    if not isinstance(value, str) or not _TIMESTAMP_RE.match(value.strip()):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:  # shaped like a date, names no day (2026-02-30)
        return None


def _blank(value) -> bool:
    return value in (None, "", [])


def well_formed_evidence(evidence) -> list[dict]:
    """The evidence items that are pointers: a mapping with a non-empty type and ref."""
    if not isinstance(evidence, list):
        return []
    return [e for e in evidence if _evidence_item_problem(e) is None]


def _evidence_item_problem(item) -> str | None:
    if not isinstance(item, dict):
        return f"is a {type(item).__name__}, not a {{type, ref}} mapping"
    for key in ("type", "ref"):
        val = item.get(key)
        if not (isinstance(val, str) and val.strip()):
            return f"has no {key}"
    return None


def record_issues(meta: dict, rtype: str, rid: str | None = None) -> list[dict]:
    """Shape problems in one record's frontmatter. Empty when it is well formed.

    Only fields that are present are checked; which keys are *required* is
    `validate`'s existing rule. `rid` enables the self-link check.
    """
    issues: list[dict] = []

    confidence = meta.get("confidence")
    if confidence is not None and confidence not in VALID_CONFIDENCE:
        issues.append(
            _issue(
                CONFIDENCE_INVALID,
                "confidence",
                f"invalid confidence {confidence!r} (allowed: {', '.join(VALID_CONFIDENCE)})",
            )
        )

    review = meta.get("review_status")
    if review is not None and review not in VALID_REVIEW_STATUS:
        issues.append(
            _issue(
                REVIEW_STATUS_INVALID,
                "review_status",
                f"invalid review_status {review!r} (allowed: {', '.join(VALID_REVIEW_STATUS)})",
            )
        )

    scope = meta.get("scope")
    if scope is not None and scope not in RECORD_SCOPES:
        issues.append(
            _issue(
                SCOPE_UNSUPPORTED,
                "scope",
                f"unsupported scope {scope!r}: it is read as 'project', which may be wider "
                f"than the author meant — set scope to {' or '.join(RECORD_SCOPES)} explicitly",
            )
        )

    evidence = meta.get("evidence")
    if not _blank(evidence):
        if not isinstance(evidence, list):
            issues.append(
                _issue(
                    EVIDENCE_MALFORMED,
                    "evidence",
                    f"evidence is a {type(evidence).__name__}, not a list of {{type, ref}} items",
                )
            )
        else:
            for n, item in enumerate(evidence, 1):
                problem = _evidence_item_problem(item)
                if problem:
                    issues.append(
                        _issue(EVIDENCE_MALFORMED, "evidence", f"evidence item {n} {problem}")
                    )

    for field in TIMESTAMP_FIELDS:
        value = meta.get(field)
        if not _blank(value) and parse_timestamp(value) is None:
            issues.append(
                _issue(
                    TIMESTAMP_INVALID,
                    field,
                    f"{field} {value!r} is not an ISO-8601 date or datetime",
                )
            )

    superseded_by = meta.get("superseded_by")
    if not _blank(superseded_by):
        if not isinstance(superseded_by, str):
            issues.append(
                _issue(
                    SUPERSEDED_BY_MALFORMED,
                    "superseded_by",
                    f"superseded_by must be one record id, got a {type(superseded_by).__name__}",
                )
            )
        elif rid and superseded_by.strip() == rid:
            issues.append(
                _issue(SUPERSESSION_SELF, "superseded_by", "record is superseded by itself")
            )

    supersedes = meta.get("supersedes")
    if rid and isinstance(supersedes, list) and rid in supersedes:
        issues.append(_issue(SUPERSESSION_SELF, "supersedes", "record supersedes itself"))

    return issues


def store_issues(entries: list[tuple[str, str | None, dict]]) -> dict[str, list[dict]]:
    """Link problems across a store, keyed by the path of the record holding the link.

    `entries` is `(path, rid, meta)` for every record in the store; `rid` is the
    filename-derived id (None when underivable) and `meta` may be empty for a
    record whose frontmatter did not parse — it still exists as a link target.
    """
    ids = {rid for _path, rid, _meta in entries if rid}
    forward: dict[str, str] = {}
    path_of: dict[str, str] = {}
    out: dict[str, list[dict]] = {}

    for path, rid, meta in entries:
        target = meta.get("superseded_by")
        if not isinstance(target, str) or not target.strip():
            continue
        target = target.strip()
        if rid and target == rid:
            continue  # record_issues reports the self-link
        if target not in ids:
            out.setdefault(path, []).append(
                _issue(
                    SUPERSEDED_BY_MISSING,
                    "superseded_by",
                    f"superseded_by {target!r} names no record in this store",
                )
            )
        elif rid:
            forward[rid] = target
            path_of[rid] = path

    # A replacement chain that returns to where it started retires every record
    # on the loop in favour of another retired one: nothing on it is live.
    on_cycle: set[str] = set()
    done: set[str] = set()
    for start in forward:
        if start in done:
            continue
        chain: list[str] = []
        seen: dict[str, int] = {}
        node: str | None = start
        while node in forward and node not in done and node not in seen:
            seen[node] = len(chain)
            chain.append(node)
            node = forward[node]
        if node in seen:
            on_cycle.update(chain[seen[node] :])
        done.update(chain)
    for rid in sorted(on_cycle):
        loop = [rid]
        nxt = forward[rid]
        while nxt != rid:
            loop.append(nxt)
            nxt = forward[nxt]
        out.setdefault(path_of[rid], []).append(
            _issue(
                SUPERSESSION_CYCLE,
                "superseded_by",
                "supersession cycle: " + " -> ".join(loop + [rid]),
            )
        )
    return out
