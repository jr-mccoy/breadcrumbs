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
from breadcrumbs import path_policy

RELATED_FILENAME = "related.json"

# "See also" is a pointer, not a list: three is enough to follow a thread, and
# more is a wall nobody reads.
RELATED_MAX_PER_ITEM = 3

# Before audit WP15 the computation compared every pair, and past this many
# items it skipped the whole projection. Pairs now come from shared features
# (postings), so there is no corpus cutoff. Kept for importers.
RELATED_MAX_CORPUS = 2000

# The most candidate pairs one build scores. A feature shared by most of the
# store (a tag on every record) makes nearly every pair a candidate; past this
# budget the most widely shared features stop generating pairs, and the
# projection says which, in `degraded`. Nothing is dropped silently.
RELATED_PAIR_BUDGET = 3_000_000

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


def _features(item: dict, ubiquitous: frozenset[str]) -> set[tuple[str, str]]:
    """What a pair must share to score at all (`pair_score` > 0)."""
    feats = {("f", f) for f in item.get("files") or ()}
    feats |= {("t", t) for t in item.get("tag_stems") or {}}
    feats |= {("s", s) for s in item.get("specific") or () if s not in ubiquitous}
    return feats


def compute_related(memory_dir: Path) -> dict:
    """`{"related": {id: [id, …]}, "skipped": None, "degraded"?: {...}}` for the live corpus.

    Exactly what comparing every pair gives (`_compute_related_full`), because
    a pair that shares no file, tag stem or non-ubiquitous stem scores 0 and
    is never kept (`GUARD_NOISE_FLOOR` is positive). So only pairs sharing
    one are scored, found from the feature postings (audit WP15). Past
    `RELATED_PAIR_BUDGET` candidate pairs, the most widely shared features
    stop generating pairs, and `degraded` names how many and why.
    """
    assert cli.GUARD_NOISE_FLOOR > 0, "a zero-score pair would have to be kept"
    items = [it for it in cli._candidate_items(Path(memory_dir), include_ideas=False) if _live(it)]
    ubiquitous = cli._ubiquitous_stems(items)
    postings: dict[tuple[str, str], list[int]] = {}
    for i, it in enumerate(items):
        for feat in _features(it, ubiquitous):
            postings.setdefault(feat, []).append(i)
    # Largest postings last, so the budget drops the most widely shared first.
    ordered = sorted(postings.items(), key=lambda kv: (len(kv[1]), kv[0]))
    budget, used, dropped = RELATED_PAIR_BUDGET, 0, []
    # Per item, the postings it generates pairs from: pairs are enumerated one
    # item at a time, so memory stays linear in the store, not in the pairs.
    usable: list[list[list[int]]] = [[] for _ in items]
    for feat, members in ordered:
        n = len(members) * (len(members) - 1) // 2
        if used + n > budget:
            dropped.append((feat, len(members)))
            continue
        used += n
        for i in members:
            usable[i].append(members)
    # `pair_score`'s three sets, built once per item rather than once per pair.
    prepared = [
        (
            frozenset(it.get("files") or ()),
            frozenset(it.get("tag_stems") or {}),
            frozenset(it.get("specific") or ()) - ubiquitous,
        )
        for it in items
    ]
    scores: dict[str, list[tuple[int, str]]] = {it["id"]: [] for it in items}
    for i, lists in enumerate(usable):
        near: set[int] = set()
        for members in lists:
            near.update(j for j in members if j > i)
        fa, ta, sa = prepared[i]
        for j in near:
            fb, tb, sb = prepared[j]
            score = len(fa & fb) * W_FILE + len(ta & tb) * W_TAG + len(sa & sb) * W_STEM
            if score < cli.GUARD_NOISE_FLOOR:
                continue
            a, b = items[i], items[j]
            scores[a["id"]].append((score, b["id"]))
            scores[b["id"]].append((score, a["id"]))
    related = {}
    for rid, found in scores.items():
        if not found:
            continue
        # Highest score first, then id — a tie must resolve the same way on
        # every machine or the committed file churns.
        found.sort(key=lambda p: (-p[0], p[1]))
        related[rid] = [other for _, other in found[:RELATED_MAX_PER_ITEM]]
    doc: dict = {"related": dict(sorted(related.items())), "skipped": None}
    if dropped:
        doc["degraded"] = {
            "reason": f"more than {RELATED_PAIR_BUDGET} candidate pairs; the most widely shared "
            "features stopped generating pairs",
            "dropped_features": len(dropped),
            "largest_dropped_posting": max(n for _, n in dropped),
        }
    return doc


def _compute_related_full(memory_dir: Path) -> dict:
    """The pairwise reference implementation of `compute_related` (below a
    corpus of `RELATED_MAX_CORPUS`), kept as the oracle for
    `tests/test_incremental_equivalence.py`."""
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


def render_related(memory_dir: Path, project_root: Path, *, inputs_hash: str | None = None) -> str:
    """The projection file's contents, stamped with the inputs it was built from.

    `inputs_hash` is the snapshot digest a publication verified (audit F07);
    computing it here, after the records were read, could stamp content the map
    never saw.
    """
    doc = compute_related(memory_dir)
    doc = {
        "_generated": "GENERATED PROJECTION — do not edit. Rebuilt by `crumb reindex`.",
        "inputs_hash": inputs_hash or cli._inputs_hash(Path(memory_dir), Path(project_root)),
        **doc,
    }
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def load_degraded(memory_dir: Path) -> dict | None:
    """The committed map's `degraded` report, or None (complete, or unreadable)."""
    try:
        doc = json.loads(path_policy.read_text(Path(memory_dir) / "generated" / RELATED_FILENAME))
    except Exception:
        return None
    degraded = doc.get("degraded") if isinstance(doc, dict) else None
    return degraded if isinstance(degraded, dict) else None


def load_related(memory_dir: Path) -> dict[str, list[str]]:
    """The committed map, or `{}`. Never raises: "see also" is a convenience."""
    try:
        doc = json.loads(path_policy.read_text(Path(memory_dir) / "generated" / RELATED_FILENAME))
    except Exception:
        return {}
    related = doc.get("related") if isinstance(doc, dict) else None
    return related if isinstance(related, dict) else {}
