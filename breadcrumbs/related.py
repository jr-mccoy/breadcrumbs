"""breadcrumbs — related records, as a projection (WM-25).

Records that are about the same thing should point at each other. A decision
and the attempt that motivated it, a trap and the verification that proved it
fixed: a reader who finds one wants the others, and nothing linked them. This
computes "see also" for every live item at reindex time and writes it to
`generated/related.json`, which `crumb show` and `memory_show` read.

**The score is pure overlap, deliberately not `_score_item`.** The plan said to
reuse the guard's scorer, but that scorer decays by the current branch, the
clock and the commit distance — correct for a verdict about *this* checkout
*now*, and wrong for a committed file. Two developers' clones would compute
different relations for identical records, the file would churn on every
reindex, and drift detection would call each other's copy stale forever: the
exact ping-pong `_hashed_input_dirs` exists to prevent. What relates two records
is what they share, which does not depend on who is looking:

    declared file in common   6   (the same weight the guard gives a file)
    tag in common             4
    specific stem in common   1   (stems in over a third of the corpus excluded)

A pair relates when it scores at least `cli.GUARD_NOISE_FLOOR`, the same bar the
guard uses for "this counts at all". Each item keeps its top three.

The file is stamped with `inputs_hash`, so `validate` and `audit` detect it
going stale exactly as they detect the resume packet going stale.
"""

from __future__ import annotations

import json
from pathlib import Path

from breadcrumbs import cli

RELATED_FILENAME = "related.json"

# "See also" is a pointer, not a list: three is enough to follow a thread, and
# more is a wall nobody reads.
RELATED_MAX_PER_ITEM = 3

# The computation is quadratic in the corpus. Past this the projection says it
# skipped rather than making every reindex slow on a very large store.
RELATED_MAX_CORPUS = 2000

W_FILE = cli.GUARD_W_FILE
W_TAG = cli.GUARD_W_TAG
W_STEM = cli.GUARD_W_KEYWORD


def _live(item: dict) -> bool:
    """Only items that still apply relate: a superseded decision is history."""
    kind = item.get("kind")
    status = item.get("lifecycle") or item.get("status")
    if kind == "question":
        return status == "open"
    return status == "active"


def pair_score(a: dict, b: dict, ubiquitous: frozenset[str]) -> int:
    """How much two items share. Symmetric and machine-independent."""
    files = len(set(a.get("files") or ()) & set(b.get("files") or ()))
    tags = len(set(a.get("tag_stems") or {}) & set(b.get("tag_stems") or {}))
    stems = len((set(a.get("specific") or ()) & set(b.get("specific") or ())) - ubiquitous)
    return files * W_FILE + tags * W_TAG + stems * W_STEM


def compute_related(memory_dir: Path) -> dict:
    """`{"related": {id: [id, …]}, "skipped": reason|None}` for the live corpus."""
    items = [it for it in cli._candidate_items(Path(memory_dir), include_ideas=False) if _live(it)]
    if len(items) > RELATED_MAX_CORPUS:
        return {
            "related": {},
            "skipped": f"corpus of {len(items)} items exceeds {RELATED_MAX_CORPUS}",
        }
    ubiquitous = cli._ubiquitous_stems(items)
    scores: dict[str, list[tuple[int, str]]] = {it["id"]: [] for it in items}
    for i, a in enumerate(items):
        for b in items[i + 1 :]:
            score = pair_score(a, b, ubiquitous)
            if score < cli.GUARD_NOISE_FLOOR:
                continue
            scores[a["id"]].append((score, b["id"]))
            scores[b["id"]].append((score, a["id"]))
    related = {}
    for rid, pairs in scores.items():
        if not pairs:
            continue
        # Highest score first, then id — a tie must resolve the same way on
        # every machine or the committed file churns.
        pairs.sort(key=lambda p: (-p[0], p[1]))
        related[rid] = [other for _, other in pairs[:RELATED_MAX_PER_ITEM]]
    return {"related": dict(sorted(related.items())), "skipped": None}


def render_related(memory_dir: Path, project_root: Path) -> str:
    """The projection file's contents, stamped with the inputs it was built from."""
    doc = compute_related(memory_dir)
    doc = {
        "_generated": "GENERATED PROJECTION — do not edit. Rebuilt by `crumb reindex`.",
        "inputs_hash": cli._inputs_hash(Path(memory_dir), Path(project_root)),
        **doc,
    }
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def load_related(memory_dir: Path) -> dict[str, list[str]]:
    """The committed map, or `{}`. Never raises: "see also" is a convenience."""
    try:
        doc = json.loads((Path(memory_dir) / "generated" / RELATED_FILENAME).read_text("utf-8"))
    except Exception:
        return {}
    related = doc.get("related") if isinstance(doc, dict) else None
    return related if isinstance(related, dict) else {}
