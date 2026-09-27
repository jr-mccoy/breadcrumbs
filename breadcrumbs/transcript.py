"""breadcrumbs — deterministic transcript mining (WM-14).

Turn a Claude Code transcript into a bounded list of memory *candidates* with no
LLM and no network: commands that failed and then passed after an edit, test
commands that passed, files edited over and over, and the moments a user said
"no, not that". Each candidate becomes a machine-local jot the agent can promote
into a real record, or leave to expire.

**Why deterministic.** Everything else in this tool has the property that the
same input gives the same output, and that is what makes `validate`, the
fixtures and the guard's precision work testable at all. A miner that asked a
model what was interesting would be unreproducible, would cost a round trip at
the exact moment the session is ending, and could not run in `PreCompact`, where
nothing can talk to the model. Four narrow rules that are usually right beat one
broad rule that cannot be checked.

**Candidates are not memory.** Nothing here writes a decision, an attempt or a
trap. It writes jots — `confidence: low`, a TTL, no evidence rule, never the
basis of a guard verdict — into `private/inbox/`, which is gitignored. Promotion
is a separate, human- or agent-initiated act that runs the real writer. A miner
that wrote durable records directly would be putting a regex's opinion into the
store's permanent history.

**Never raise.** Every entry point is called from a hook. A malformed line, a
truncated file, a missing field, a transcript that is not JSONL at all: all of
it degrades to "nothing to mine".
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from breadcrumbs import cli

# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #

# A long session's transcript is megabytes of tool output. Only the tail can
# matter to a hook firing now, and reading the whole thing would blow the hook's
# time budget on a file whose front half was already mined firings ago.
DEFAULT_MAX_BYTES = 8_000_000

# The tools whose calls are read. Anything else (reads, searches, web fetches)
# says nothing about what changed.
EDIT_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit")
BASH_TOOL = "Bash"

# How much of a tool result is kept for display. The outcome is classified from
# the whole result first: a failure printed after the cutoff is still a failure.
RESULT_SNIPPET_CHARS = 400

# What happened to a tool call, as far as the transcript can show (audit F01).
# Only SUCCESS may be worded as "passed". A call whose result never arrived is
# UNKNOWN, not a success that happened to print nothing.
SUCCESS = "success"
FAILURE = "failure"
INTERRUPTED = "interrupted"  # started, then stopped by the user or the harness
NOT_RUN = "not_run"  # refused before it ran: blocked by a hook, rejected by the user
UNKNOWN = "unknown"  # no result in the transcript (yet), or one that settles nothing
OUTCOMES = (SUCCESS, FAILURE, INTERRUPTED, NOT_RUN, UNKNOWN)


def read_transcript(path: str | Path, *, max_bytes: int = DEFAULT_MAX_BYTES) -> list[dict]:
    """Parse a JSONL transcript, reading at most the last `max_bytes`.

    A partial first line (the tail read landed mid-record) is discarded rather
    than guessed at. Malformed lines are skipped individually, so one truncated
    write in the middle of a 20k-line file costs that line and nothing else.
    Returns `[]` for anything unreadable.
    """
    try:
        p = Path(path)
        size = p.stat().st_size
        with p.open("rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
                fh.readline()  # discard the partial line the seek landed inside
            raw = fh.read()
    except Exception:
        return []
    out: list[dict] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


# --------------------------------------------------------------------------- #
# Tool-call pairing
# --------------------------------------------------------------------------- #


@dataclass
class ToolCall:
    """One tool invocation, and what the transcript shows came back for it.

    `result_received` says whether a `tool_result` answered the call at all;
    `outcome` is one of `OUTCOMES`. `result_text` is a bounded display excerpt,
    cut after the outcome was decided from the full result.
    """

    name: str
    input: dict
    result_text: str
    index: int
    timestamp: str | None = None
    result_received: bool = False
    outcome: str = UNKNOWN

    @property
    def is_error(self) -> bool:
        """The call ran and failed. Interrupted, refused and unanswered calls did not."""
        return self.outcome == FAILURE


def _content_blocks(entry: dict) -> list:
    message = entry.get("message")
    if not isinstance(message, dict):
        return []
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def _result_text(block: dict) -> str:
    """Flatten a tool_result's content, which may be a string or text blocks."""
    content = block.get("content")
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            elif isinstance(part, str):
                parts.append(part)
        text = "\n".join(parts)
    else:
        text = ""
    return text


# What counts as a failing Bash result when the harness did not set `is_error`.
# Deliberately a short list of unambiguous failure shapes: a false positive here
# invents a "failed then fixed" attempt that never happened, which is a lie in
# the store, while a false negative costs one candidate nobody was promised.
# Tunable — widen it only with a fixture that proves the new shape is real.
_BASH_FAILURE_RE = re.compile(
    r"(?i)\b(traceback|error:|failed|exit code [1-9]|command not found|"
    r"FAIL(ED)?\b|AssertionError|npm ERR!)"
)

# A count of zero is a success report, not a failure: "15 passed, 0 failed",
# "test result: ok. 3 passed; 0 failed", "failures: 0", "no errors". These are
# removed before the failure test, so the words in them cannot trip it.
_ZERO_FAILURE_RE = re.compile(
    r"(?i)(\b(0|no|zero)\s+(tests?\s+)?(failed|failures?|errors?)\b"
    r"|\b(failed|failures?|errors?)\s*[:=]\s*0\b)"
)


def _failure_match(text: str) -> re.Match | None:
    """The first unambiguous failure in the *whole* output, zero counts excepted."""
    return _BASH_FAILURE_RE.search(_ZERO_FAILURE_RE.sub(" ", text or ""))


def _looks_failed(text: str) -> bool:
    return _failure_match(text) is not None


# How the harness says a call never ran or was stopped. `<tool_use_error>` is
# the harness refusing the call (a hook blocked it, the input was invalid); the
# two phrases are what Claude Code writes when the user rejects or interrupts a
# tool. None of these is the command failing, and none may read as it passing.
# Anchored: each is the whole result when the harness writes it, and a `cat` of
# a file that merely quotes one (this module's tests do) must not match.
_NOT_RUN_RE = re.compile(
    r"^\s*(<tool_use_error>|The user doesn't want to proceed with this tool use)", re.I
)
_INTERRUPTED_RE = re.compile(r"^\s*\[Request interrupted by user")

# Commands whose *output* is a verdict: test runners, linters, type checkers and
# builds. A failure in their output is a failure. Any other command's output
# may be data — a `cat` or `grep` of source that contains "error:" has not
# failed — so failure words there make the outcome UNKNOWN, not FAILURE.
_BUILD_CMD_RE = re.compile(
    r"(?i)^((npm|yarn|pnpm) (run )?(build|test|lint|check|typecheck)\b|make\b|"
    r"cargo (build|check|clippy|test)\b|go (build|vet|test)\b|python -m (build|mypy|ruff)\b)"
)


def _output_is_a_verdict(command: str) -> bool:
    cmd = normalize_command(command)
    return bool(_TEST_CMD_RE.match(cmd) or _BUILD_CMD_RE.match(cmd))


def _excerpt(flat: str, at: int | None) -> str:
    """A bounded display excerpt, keeping the failure in view when it is late."""
    if len(flat) <= RESULT_SNIPPET_CHARS:
        return flat
    if at is None or at < RESULT_SNIPPET_CHARS - 80:
        return flat[:RESULT_SNIPPET_CHARS]
    start = max(0, at - 80)
    return "… " + flat[start : start + RESULT_SNIPPET_CHARS - 2]


def classify_result(
    name: str,
    text: str,
    flagged: bool,
    structured: dict | None = None,
    command: str = "",
) -> tuple[str, str]:
    """(outcome, excerpt) for a call whose result arrived.

    Structured signals first: the harness's interrupt flag and `is_error` (which
    Claude Code sets for a non-zero exit, writing `Exit code N` first). Then the
    full Bash output, because a pipeline such as `pytest | tail` exits with
    `tail`'s status and a clean exit proves nothing about what it piped:

    - a test, lint or build run whose output reports a failure *failed*;
    - any other command whose output reads like a failure is UNKNOWN — a `grep`
      that found the word "error:" has not failed, but `python x.py | tail`
      printing a traceback has not passed either;
    - otherwise it succeeded.

    An edit whose new content says "failed" has not failed, so no other tool
    gets the textual test. The excerpt is cut last, around the failure when
    there is one.
    """
    flat = " ".join(str(text or "").split())
    structured = structured if isinstance(structured, dict) else {}
    if _NOT_RUN_RE.search(flat):
        return NOT_RUN, _excerpt(flat, None)
    if structured.get("interrupted") is True or _INTERRUPTED_RE.search(flat):
        return INTERRUPTED, _excerpt(flat, None)
    match = _failure_match(flat) if name == BASH_TOOL else None
    at = match.start() if match else None
    if flagged:
        return FAILURE, _excerpt(flat, at)
    if match:
        return (FAILURE if _output_is_a_verdict(command) else UNKNOWN), _excerpt(flat, at)
    return SUCCESS, _excerpt(flat, None)


def pair_tool_calls(entries: list[dict]) -> list[ToolCall]:
    """Match each `tool_use` block to the `tool_result` that answers it.

    Results arrive in a later entry and reference the call by `tool_use_id`, so
    a single forward pass collects the calls and a second resolves them. A call
    with no result (the session ended mid-tool, or the result lands in a later
    firing) is kept with `result_received=False` and outcome UNKNOWN: that it
    was *attempted* is still a fact, but nothing about how it ended is.
    """
    calls: dict[str, ToolCall] = {}
    order: list[str] = []
    results: dict[str, tuple[str, bool, dict | None]] = {}

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        ts = entry.get("timestamp") if isinstance(entry.get("timestamp"), str) else None
        blocks = [b for b in _content_blocks(entry) if isinstance(b, dict)]
        # `toolUseResult` sits on the entry, not the block, so it can only be
        # attributed when the entry answers exactly one call.
        n_results = sum(1 for b in blocks if b.get("type") == "tool_result")
        structured = entry.get("toolUseResult") if n_results == 1 else None
        for block in blocks:
            btype = block.get("type")
            if btype == "tool_use":
                call_id = str(block.get("id") or f"_pos{index}")
                name = str(block.get("name") or "")
                payload = block.get("input")
                calls[call_id] = ToolCall(
                    name=name,
                    input=payload if isinstance(payload, dict) else {},
                    result_text="",
                    index=index,
                    timestamp=ts,
                )
                order.append(call_id)
            elif btype == "tool_result":
                call_id = str(block.get("tool_use_id") or "")
                if not call_id:
                    continue
                results[call_id] = (
                    _result_text(block),
                    bool(block.get("is_error")),
                    structured if isinstance(structured, dict) else None,
                )

    out: list[ToolCall] = []
    for call_id in order:
        call = calls[call_id]
        if call_id in results:
            text, flagged, structured = results[call_id]
            call.result_received = True
            call.outcome, call.result_text = classify_result(
                call.name, text, flagged, structured, str(call.input.get("command") or "")
            )
        out.append(call)
    return out


# --------------------------------------------------------------------------- #
# Command identity
# --------------------------------------------------------------------------- #

_CD_PREFIX_RE = re.compile(r"^\s*cd\s+[^\s;&|]+\s*&&\s*")
_REDIRECT_TAIL_RE = re.compile(r"\s*2>&1\s*$")
_PAGER_TAIL_RE = re.compile(r"\s*\|\s*(head|tail)\b[^|]*$")

COMMAND_MAX_CHARS = 200


def normalize_command(command: str) -> str:
    """The identity of a command across retries.

    An agent that reruns a failing test rarely retypes it identically: it adds a
    `cd`, pipes through `head`, drops `2>&1`. Without folding those away, "the
    same command passed later" never matches and rule 1 never fires.
    """
    text = " ".join(str(command or "").split())
    for _ in range(3):  # a couple of `cd x && cd y &&` layers
        stripped = _CD_PREFIX_RE.sub("", text)
        if stripped == text:
            break
        text = stripped
    prev = None
    while prev != text:
        prev = text
        text = _PAGER_TAIL_RE.sub("", text)
        text = _REDIRECT_TAIL_RE.sub("", text)
        text = text.strip()
    return text[:COMMAND_MAX_CHARS]


def _edited_path(call: ToolCall) -> str | None:
    """The file a call edited — only when the edit is known to have happened.

    A refused, interrupted or failed edit ("string not found") changed nothing,
    and one with no result may not have either.
    """
    if call.name not in EDIT_TOOLS or call.outcome != SUCCESS:
        return None
    value = call.input.get("file_path") or call.input.get("path") or call.input.get("notebook_path")
    return str(value) if value else None


# --------------------------------------------------------------------------- #
# Candidates
# --------------------------------------------------------------------------- #

TITLE_MAX_CHARS = 120
NOTE_MAX_CHARS = 600

# Per-rule caps. A session that ran forty test commands has not produced forty
# things worth remembering, and an inbox nobody can read is an inbox nobody
# triages.
MAX_ATTEMPTS = 5
MAX_VERIFICATIONS = 5
MAX_CHURN = 3
MAX_CORRECTIONS = 5

# Edits to one file before repetition is itself the signal.
CHURN_MIN_EDITS = 4

# Test/lint commands whose success is worth recording as a verification: the
# command an agent would want to rerun to check the same thing later.
_TEST_CMD_RE = re.compile(
    r"(?i)^(python -m (unittest|pytest)|pytest|npm test|npm run (test|lint)|yarn test|"
    r"cargo test|go test|make (test|check)|ruff (check|format)|mypy|tsc\b|"
    r"gradlew? test|mvn test)"
)

# The opening of a correction. Anchored at the start: "don't" in the middle of a
# sentence is ordinary prose, while a message that *begins* "no, don't" is the
# user overriding what just happened. That moment is the highest-value thing in
# a session and the one the tool currently loses entirely.
CORRECTION_RE = re.compile(
    r"(?i)^\s*(no[,.! ]|don'?t\b|do not\b|stop\b|not that\b|that'?s (wrong|not)\b|"
    r"instead[, ]|never\b|wrong\b|undo\b|revert\b|actually[, ])"
)

# Above this a message is a specification, not a correction.
CORRECTION_MAX_CHARS = 500


@dataclass
class Candidate:
    """One mined observation, before anybody has confirmed it."""

    kind: str  # attempt | verification | trap | correction
    title: str
    note: str
    files: list[str] = field(default_factory=list)
    command: str | None = None
    evidence: list[dict] = field(default_factory=list)
    confidence: str = "low"

    @property
    def fingerprint(self) -> str:
        """Content identity, so the same candidate is never written twice.

        Kind and title only: the note carries a snippet of tool output that can
        differ between runs of the same failure, and a fingerprint that moved
        with it would defeat the deduplication it exists for.
        """
        return hashlib.sha1(f"{self.kind}\0{self.title}".encode()).hexdigest()[:16]


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def redact_secrets(text: str) -> str | None:
    """`text` back, or None when it carries a structured credential.

    Drop, never mask. A masked secret still proves one was there and where, and
    the miner's whole input is tool output and user prose — the two places a
    credential is most likely to appear by accident. The high-entropy heuristic
    is deliberately *not* consulted: it is warn-only for `scan-secrets` because
    it has no structure behind it, and using it here would silently drop
    candidates that merely cite a build hash.
    """
    return None if cli.secret_pattern_hits(str(text or "")) else text


# --------------------------------------------------------------------------- #
# The rules
# --------------------------------------------------------------------------- #


def _mine_attempts(calls: list[ToolCall]) -> list[Candidate]:
    """Rule 1 — a command failed, files changed, the same command passed.

    This is the shape of nearly every real debugging loop, and the resulting
    attempt record is the single most useful thing a future session can be told
    about this one. It is worded as the sequence the transcript shows, not as a
    cause: the edits came between the failure and the pass, and whether they
    were the fix is for whoever promotes the candidate to say.

    Both ends must be observed outcomes. An interrupted or refused run did not
    fail, and a run whose result never arrived did not pass.
    """
    out: list[Candidate] = []
    seen: set[str] = set()
    for i, failure in enumerate(calls):
        if failure.name != BASH_TOOL or failure.outcome != FAILURE:
            continue
        command = normalize_command(failure.input.get("command", ""))
        if not command or command in seen:
            continue
        edited: list[str] = []
        for later in calls[i + 1 :]:
            path = _edited_path(later)
            if path and path not in edited:
                edited.append(path)
                continue
            if later.name != BASH_TOOL or later.outcome != SUCCESS:
                continue
            if normalize_command(later.input.get("command", "")) != command:
                continue
            if not edited:
                break  # it passed on a retry with no edit: flaky, not fixed
            seen.add(command)
            shown = edited[:3]
            note = _clip(
                f"{failure.result_text} Passed on a later run, after edits to: "
                f"{', '.join(shown)} (not shown to be the fix).",
                NOTE_MAX_CHARS,
            )
            out.append(
                Candidate(
                    kind="attempt",
                    title=_clip(
                        f"{command} failed, then passed after {len(edited)} file(s) changed",
                        TITLE_MAX_CHARS,
                    ),
                    note=note,
                    files=list(edited),
                    command=command,
                    evidence=[{"type": "command", "ref": command}]
                    + [{"type": "file", "ref": f} for f in shown],
                )
            )
            break
        if len(out) >= MAX_ATTEMPTS:
            break
    return out


def _mine_verifications(calls: list[ToolCall]) -> list[Candidate]:
    """Rule 2 — a test or lint command that passed.

    Recorded because `resume` builds *Verification Commands* out of exactly this
    and a session that discovers the right command to check something should not
    make the next one rediscover it.
    """
    out: list[Candidate] = []
    seen: set[str] = set()
    for call in calls:
        # "Passed" needs a result that arrived, was not flagged, and printed no
        # failure. Anything short of that — no result, interrupted, refused —
        # is not evidence the command passes.
        if call.name != BASH_TOOL or call.outcome != SUCCESS:
            continue
        command = normalize_command(call.input.get("command", ""))
        if not command or command in seen or not _TEST_CMD_RE.match(command):
            continue
        seen.add(command)
        out.append(
            Candidate(
                kind="verification",
                title=_clip(f"{command} passed", TITLE_MAX_CHARS),
                note=_clip(
                    "Exited without a reported error and printed no failure in this "
                    f"session. {call.result_text}",
                    NOTE_MAX_CHARS,
                ),
                command=command,
                evidence=[{"type": "command", "ref": command}],
            )
        )
        if len(out) >= MAX_VERIFICATIONS:
            break
    return out


def _mine_churn(calls: list[ToolCall]) -> list[Candidate]:
    """Rule 3 — one file edited over and over.

    The weakest of the four, and worded as a question rather than a finding:
    repetition can mean a fragile area, a missing test, or simply a big feature
    landing in one file. It is offered so somebody who knows which can say.
    """
    counts: dict[str, int] = {}
    for call in calls:
        path = _edited_path(call)
        if path:
            counts[path] = counts.get(path, 0) + 1
    hot = sorted(
        ((p, n) for p, n in counts.items() if n >= CHURN_MIN_EDITS),
        key=lambda pair: (-pair[1], pair[0]),
    )
    return [
        Candidate(
            kind="trap",
            title=_clip(f"{path} was edited {n} times this session", TITLE_MAX_CHARS),
            note=(
                "Repeated edits suggest a fragile area or a missing test; "
                "confirm before recording a trap."
            ),
            files=[path],
            evidence=[{"type": "file", "ref": path}],
        )
        for path, n in hot[:MAX_CHURN]
    ]


def _user_text(entry: dict) -> str:
    """A user entry's own words, excluding tool results.

    A `tool_result` is delivered in a user-role message, so without this filter
    every command that printed "Error: ..." would read as the user saying "no".
    """
    if entry.get("type") != "user":
        return ""
    parts = []
    for block in _content_blocks(entry):
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            return ""  # a results-carrying turn is not the user talking
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return " ".join(" ".join(parts).split())


def _mine_corrections(entries: list[dict]) -> list[Candidate]:
    """Rule 4 — the user overriding what the agent just did.

    The highest-value moment in a session by a distance, and the one nothing in
    this tool captured before: "no, not like that" is a durable constraint that
    the agent would otherwise re-violate in the next session.
    """
    out: list[Candidate] = []
    for entry in entries:
        text = _user_text(entry)
        if not text or len(text) > CORRECTION_MAX_CHARS or not CORRECTION_RE.match(text):
            continue
        out.append(
            Candidate(
                kind="correction",
                title=_clip(text, TITLE_MAX_CHARS),
                note=_clip(text, NOTE_MAX_CHARS),
            )
        )
        if len(out) >= MAX_CORRECTIONS:
            break
    return out


def mine(entries: list[dict], *, since_index: int = 0) -> tuple[list[Candidate], int]:
    """Candidates from `entries[since_index:]`, plus how many entries were read.

    The second value is what the caller stores as its cursor, so the next firing
    starts where this one stopped instead of re-mining a transcript that only
    grows.
    """
    total = len(entries)
    window = entries[max(0, since_index) :]
    if not window:
        return [], total
    calls = pair_tool_calls(window)
    candidates = (
        _mine_attempts(calls)
        + _mine_verifications(calls)
        + _mine_churn(calls)
        + _mine_corrections(window)
    )
    return candidates, total


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #

# The most jots one firing may add. A single compaction or Stop should never
# bury the inbox; what it cannot fit, the next firing can.
MINER_MAX_JOTS_PER_FIRING = 10


def write_candidates(
    memory_dir: Path,
    project_root: Path,
    candidates: list[Candidate],
    *,
    session_id: str,
    source: str = "transcript",
    extra_tags: list[str] | None = None,
) -> dict:
    """Write candidates as machine-local jots. Returns a small report.

    Three filters, in order: redaction drops anything carrying a structured
    credential, the fingerprint drops anything this session already wrote, and
    the per-firing cap drops the rest. `{"written": [ids], "skipped": n,
    "dropped_for_secrets": n}`.

    **Always `local=True`.** This is the automatic-writer path, and a hook
    cannot know whether the tool output or user prose it just read is
    publishable. Promotion is what moves content into the committed store.
    """
    from breadcrumbs import inbox as _inbox

    memory_dir = Path(memory_dir)
    project_root = Path(project_root)
    known = _session_fingerprints(memory_dir, session_id)
    report = {"written": [], "skipped": 0, "dropped_for_secrets": 0}

    for candidate in candidates:
        if len(report["written"]) >= MINER_MAX_JOTS_PER_FIRING:
            report["skipped"] += 1
            continue
        title = redact_secrets(candidate.title)
        note = redact_secrets(candidate.note)
        if title is None or note is None:
            report["dropped_for_secrets"] += 1
            continue
        fingerprint = candidate.fingerprint
        if fingerprint in known:
            report["skipped"] += 1
            continue
        result = _inbox.write_jot(
            memory_dir,
            project_root,
            note or title,
            tags=sorted({"mined", candidate.kind, *(extra_tags or [])}),
            files=candidate.files,
            local=True,
            source=source,
            agent=cli.detect_agent(fallback="agent"),
            host_session=session_id,
            fingerprint=fingerprint,
            evidence=candidate.evidence,
            title=title,
        )
        if result.get("ok"):
            known.add(fingerprint)
            report["written"].append(result["id"])
        else:
            report["skipped"] += 1
    return report


def _session_fingerprints(memory_dir: Path, session_id: str) -> set[str]:
    """Fingerprints already written for this session.

    Scoped to the session on purpose: the same failure recurring in a *later*
    session is news again, and deduplicating across all time would hide a
    regression the store should surface.
    """
    from breadcrumbs import inbox as _inbox

    out: set[str] = set()
    for rec in _inbox.load_jots(memory_dir, include_expired=True, include_retired=True):
        if rec.meta.get("host_session") != session_id:
            continue
        fingerprint = rec.meta.get("fingerprint")
        if isinstance(fingerprint, str) and fingerprint:
            out.add(fingerprint)
    return out


def mine_transcript_into_jots(
    memory_dir: Path,
    project_root: Path,
    transcript_path: str | None,
    *,
    session_id: str,
    use_cursor: bool = True,
    extra_tags: list[str] | None = None,
) -> dict:
    """Read, mine and write in one call — what every hook actually wants.

    Best-effort throughout: any failure returns an empty report rather than
    propagating into the hook. `use_cursor=False` mines the whole file, which is
    what a finished subagent transcript needs (it is never read again).
    """
    empty = {"written": [], "skipped": 0, "dropped_for_secrets": 0}
    if not transcript_path:
        return empty
    try:
        entries = read_transcript(transcript_path)
        if not entries:
            return empty
        from breadcrumbs import hooks_common

        since = hooks_common.miner_cursor(memory_dir, session_id) if use_cursor else 0
        candidates, read_to = mine(entries, since_index=since)
        report = write_candidates(
            memory_dir,
            project_root,
            candidates,
            session_id=session_id,
            extra_tags=extra_tags,
        )
        if use_cursor:
            hooks_common.set_miner_cursor(memory_dir, session_id, read_to)
        return report
    except Exception:  # pragma: no cover - mining never breaks its hook
        return empty
