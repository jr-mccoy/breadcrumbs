"""Purpose-specific retrieval, with an honest account of how it ran (audit WP10).

The `UserPromptSubmit` hook used to decide what to look up with three shortcuts,
each of which made memory disappear:

- **A corpus cap (F09).** It loaded and counted every candidate record, then
  returned nothing above 500, retired records included. One live decision
  beside 500 retired ones was never injected, at the store size where the
  search index exists to help.
- **A length gate (F10).** Any prompt under 12 characters was treated as an
  acknowledgement. `quasar`, `npm test` and `ruff` are meaningful prompts that
  short, and they were never answered.
- **A proxy for "is there content" (F11).** The existence of the guard
  pre-filter file stood in for "this store has records".

Replacements:

- **Acknowledgements are a vocabulary.** `is_acknowledgment` accepts a prompt
  made only of words like "ok", "yes please", "go on" or "thanks", or of
  nothing but punctuation and emoji. Anything else is looked up, however short.
- **No pre-count.** `prompt_lookup` asks `cli.search` directly. It narrows
  through the search index when the index is current. When it is not, it scans
  the store in full, up to `PROMPT_FULL_SCAN_MAX` records.
- **Past that bound it does not guess.** It reports `mode: "skipped"`, and the
  hook says so once per session instead of staying silent.
- **Eligibility comes before the cap.** Current advice only (`eligible`):
  superseded, rejected, stale or quarantined records, answered questions,
  expired records and other branches' branch-scoped records are left out
  *before* the five-match budget, so history never takes a slot.
- **A cheap corpus summary.** `corpus_summary` reads the record count from a
  verified generation manifest (WP07), and otherwise counts files. It stands in
  for the pre-filter's existence.

Full `crumb search` stays exact: it has no scan bound, and reports its own mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from breadcrumbs import cli

# ---- acknowledgements (F10) ------------------------------------------------ #

# Words that carry no task on their own. A prompt made only of these (at most
# ACK_MAX_WORDS of them) is an acknowledgement, and nothing is looked up.
ACK_WORDS = frozenset(
    {
        "ok", "okay", "k", "kk", "yes", "y", "yeah", "yep", "yup", "sure", "no", "nope",
        "thanks", "thank", "you", "thx", "ty", "cheers", "great", "good", "nice", "cool",
        "perfect", "awesome", "lgtm", "sgtm", "right", "correct", "agreed", "fine",
        "please", "pls", "go", "on", "ahead", "continue", "proceed", "next", "do", "it",
        "that", "done", "sounds", "keep", "going", "again", "hi", "hello", "hey",
        "alright", "got", "ack", "approved", "carry", "resume",
    }
)  # fmt: skip
ACK_MAX_WORDS = 4
_NON_WORD_RE = re.compile(r"[^\w\s']+", re.UNICODE)


def is_acknowledgment(prompt: str) -> bool:
    """True for "ok", "yes please", "go on", "thanks!", "👍": nothing to look up."""
    words = _NON_WORD_RE.sub(" ", str(prompt or "").lower()).split()
    if not words:
        return True  # punctuation and emoji only
    return len(words) <= ACK_MAX_WORDS and all(w.strip("'") in ACK_WORDS for w in words)


# ---- the corpus (F11) ------------------------------------------------------ #

# The record directories the prompt corpus reads (ideas are lookup-only), and
# the singletons that hold trap and question blocks before schema 3.
_CORPUS_DIRS = ("decisions", "attempts", "verifications", "inbox", "traps", "questions")
_BLOCK_FILES = {"known-traps.md": "## trap_", "open-questions.md": "## Q:"}


def count_records(memory_dir: Path) -> int:
    """Records the prompt corpus could hold, counted without parsing any."""
    memory_dir = Path(memory_dir)
    total = 0
    for name in (*_CORPUS_DIRS, "private/inbox"):
        d = memory_dir / name
        if d.is_dir():
            total += sum(1 for p in d.glob("*.md") if p.name != "README.md")
    for name, marker in _BLOCK_FILES.items():
        try:
            text = (memory_dir / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        total += sum(1 for line in text.splitlines() if line.startswith(marker))
    return total


def corpus_summary(memory_dir: Path, root: Path) -> dict:
    """`{records, source}`: from the verified generation manifest, else counted."""
    from breadcrumbs import projections as _projections

    doc = _projections.load_manifest(memory_dir)
    corpus = (doc or {}).get("corpus")
    if (
        isinstance(corpus, dict)
        and isinstance(corpus.get("records"), int)
        and _projections.generation_current(memory_dir, root)
    ):
        return {"records": corpus["records"], "source": "manifest"}
    return {"records": count_records(memory_dir), "source": "count"}


# ---- purpose-specific eligibility ------------------------------------------ #


def eligible(match: dict, purpose: str = "prompt") -> bool:
    """May this match be offered as current advice for `purpose`?

    `search` offers everything (it is a lookup, history included). The prompt
    hook offers what is still something to act on; see the module docstring.
    """
    if purpose == "search":
        return True
    # WM-52: a branch-scoped record written on another branch is not about the
    # work checked out here — the packet and guard's live set leave it out too.
    if match.get("scope") == "branch" and match.get("branch_mismatch"):
        return False
    if match.get("expired"):
        return False
    if match.get("kind") == "verification":
        return match.get("lifecycle", "active") == "active"
    if match.get("kind") == "question":
        return match.get("status") == "open"
    return (match.get("status") or "active") == "active"


# ---- the prompt lookup (F09) ----------------------------------------------- #

# The largest store the prompt hook will scan in full when the search index
# cannot be used. A full scan is ~0.3 s per 1,000 records; the hook runs on
# every prompt. Past this, it reports `skipped` rather than stall the prompt.
PROMPT_FULL_SCAN_MAX = 2000


@dataclass
class Lookup:
    """What a lookup found, and how: so a consumer can tell a complete lookup
    from a limited one."""

    matches: list[dict] = field(default_factory=list)
    # indexed | full_scan | skipped | empty
    mode: str = "empty"
    # False when records that could have matched were not considered.
    complete: bool = True
    reason: str | None = None
    records: int = 0
    candidates: int = 0

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "complete": self.complete,
            "reason": self.reason,
            "records": self.records,
            "candidates": self.candidates,
        }


def prompt_lookup(memory_dir: Path, root: Path, prompt: str, *, limit: int = 5) -> Lookup:
    """The current records worth a prompt's context, best first, and how they were found."""
    summary = corpus_summary(memory_dir, root)
    records = summary["records"]
    if records == 0:
        return Lookup(mode="empty", reason="the store has no records", records=0)
    info: dict = {}
    matches, _ = cli.search(
        memory_dir,
        root,
        prompt,
        min_keyword=cli.GUARD_MIN_KEYWORD_OVERLAP,
        noise_floor=cli.GUARD_NOISE_FLOOR,
        include_ideas=False,
        allow_full_scan=records <= PROMPT_FULL_SCAN_MAX,
        info=info,
    )
    if info.get("mode") == "skipped":
        return Lookup(
            mode="skipped",
            complete=False,
            reason=f"{info.get('reason') or 'no usable search index'}; a full scan of "
            f"{records} records exceeds the prompt hook's budget ({PROMPT_FULL_SCAN_MAX})",
            records=records,
        )
    kept = [
        m
        for m in matches
        if (cli.GUARD_SURFACING_SIGNALS & set(m.get("signals", ())))
        or m.get("score", 0) >= cli.GUARD_READ_FIRST_SCORE
    ]
    kept = [m for m in kept if eligible(m, "prompt")]
    return Lookup(
        matches=kept[:limit],
        mode=info.get("mode") or "full_scan",
        complete=True,
        reason=info.get("reason"),
        records=records,
        candidates=int(info.get("candidates") or 0),
    )
