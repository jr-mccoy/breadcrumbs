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
    return _parse_lines(raw)[0]


def _parse_lines(raw: bytes) -> tuple[list[dict], int]:
    """`(entries, malformed)` from JSONL bytes.

    Split on the byte `\n` only: a JSON string may legally hold U+2028 or a
    form feed, which `str.splitlines` would break the record on.
    """
    out: list[dict] = []
    malformed = 0
    for chunk in raw.split(b"\n"):
        line = chunk.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            malformed += 1
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out, malformed


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
    # The harness's `tool_use` id: what joins a result to its call across
    # firings, and what a mined candidate cites as the event it came from.
    call_id: str = ""

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


def pair_tool_calls(entries: list[dict], carried: list[ToolCall] | None = None) -> list[ToolCall]:
    """Match each `tool_use` block to the `tool_result` that answers it.

    Results arrive in a later entry and reference the call by `tool_use_id`, so
    a single forward pass collects the calls and a second resolves them. A call
    with no result (the session ended mid-tool, or the result lands in a later
    firing) is kept with `result_received=False` and outcome UNKNOWN: that it
    was *attempted* is still a fact, but nothing about how it ended is.

    `carried` are calls from earlier firings (audit F02): they come first, in
    their order, and a result in `entries` resolves a carried call that was
    still waiting for one.
    """
    calls: dict[str, ToolCall] = {}
    order: list[str] = []
    for call in carried or []:
        key = call.call_id or f"_carried{len(order)}"
        if key not in calls:
            calls[key] = call
            order.append(key)
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
                if call_id not in calls:
                    order.append(call_id)
                calls[call_id] = ToolCall(
                    name=name,
                    input=payload if isinstance(payload, dict) else {},
                    result_text="",
                    index=index,
                    timestamp=ts,
                    call_id=call_id,
                )
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
        if call_id in results and not call.result_received:
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
    # What makes two sightings the same candidate, when the title can drift
    # between firings (a churn count that grows, an attempt whose edit list
    # was cut): the file, the command, the failing call. Default: the title.
    key: str | None = None
    # The transcript events it came from: tool_use ids, or a user entry's id.
    # Acknowledged events are never mined into a jot again, in any session, so
    # a replayed or forked transcript cannot duplicate them (audit F02).
    events: list[str] = field(default_factory=list)

    @property
    def fingerprint(self) -> str:
        """Content identity, so the same candidate is never written twice.

        Kind and key (the title unless the rule names something steadier): the
        note carries a snippet of tool output that can differ between runs of
        the same failure, and a fingerprint that moved with it would defeat the
        deduplication it exists for.
        """
        ident = self.key if self.key is not None else self.title
        return hashlib.sha1(f"{self.kind}\0{ident}".encode()).hexdigest()[:16]

    @property
    def title_fingerprint(self) -> str:
        """The fingerprint before audit WP09 (kind and title), which jots
        written by older versions carry. Checked too, so re-mining a session
        after an upgrade does not offer them again."""
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


def _mine_attempts(calls: list[ToolCall], limit: int | None = MAX_ATTEMPTS) -> list[Candidate]:
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
                    key=f"{command}\0{failure.call_id}",
                    events=[e for e in (failure.call_id, later.call_id) if e],
                )
            )
            break
        if limit is not None and len(out) >= limit:
            break
    return out


def _mine_verifications(
    calls: list[ToolCall], limit: int | None = MAX_VERIFICATIONS
) -> list[Candidate]:
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
                key=command,
                events=[call.call_id] if call.call_id else [],
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out


def _mine_churn(calls: list[ToolCall], limit: int | None = MAX_CHURN) -> list[Candidate]:
    """Rule 3 — one file edited over and over.

    The weakest of the four, and worded as a question rather than a finding:
    repetition can mean a fragile area, a missing test, or simply a big feature
    landing in one file. It is offered so somebody who knows which can say.
    """
    counts: dict[str, int] = {}
    edits: dict[str, list[str]] = {}
    for call in calls:
        path = _edited_path(call)
        if path:
            counts[path] = counts.get(path, 0) + 1
            if call.call_id:
                edits.setdefault(path, []).append(call.call_id)
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
            # One candidate per file per session, however the count grows.
            key=path,
            events=edits.get(path, []),
        )
        for path, n in (hot if limit is None else hot[:limit])
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


def _entry_event(entry: dict, text: str) -> str:
    """A user entry's identity: its `uuid`, else its timestamp and words."""
    uid = entry.get("uuid")
    if isinstance(uid, str) and uid:
        return uid
    stamp = entry.get("timestamp") if isinstance(entry.get("timestamp"), str) else ""
    return "entry:" + hashlib.sha1(f"{stamp}\0{text}".encode()).hexdigest()[:16]


def _mine_corrections(entries: list[dict], limit: int | None = MAX_CORRECTIONS) -> list[Candidate]:
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
        event = _entry_event(entry, text)
        out.append(
            Candidate(
                kind="correction",
                title=_clip(text, TITLE_MAX_CHARS),
                note=_clip(text, NOTE_MAX_CHARS),
                key=event,
                events=[event],
            )
        )
        if limit is not None and len(out) >= limit:
            break
    return out


# Each rule's cap: how many of its candidates one window may yield. What a cap
# holds back is a deliberate policy drop, and it is counted (`capped`), never
# silent (audit F02).
_RULES = (
    ("attempt", _mine_attempts, MAX_ATTEMPTS, "calls"),
    ("verification", _mine_verifications, MAX_VERIFICATIONS, "calls"),
    ("trap", _mine_churn, MAX_CHURN, "calls"),
    ("correction", _mine_corrections, MAX_CORRECTIONS, "entries"),
)


@dataclass
class Window:
    """What one mining pass saw: its candidates, what the caps held back, its calls."""

    candidates: list[Candidate]
    capped: int
    calls: list[ToolCall]


def mine_window(
    entries: list[dict],
    carried: list[ToolCall] | None = None,
    *,
    seen=None,
) -> Window:
    """Candidates from `entries`, joined with the calls `carried` from earlier firings.

    `seen(candidate)` says a candidate was already acknowledged. Those are
    removed *before* the caps apply, so re-detections of what earlier firings
    wrote never crowd out something new.
    """
    calls = pair_tool_calls(entries, carried)
    candidates: list[Candidate] = []
    capped = 0
    for _kind, rule, cap, source in _RULES:
        found = rule(calls if source == "calls" else entries, None)
        if seen is not None:
            found = [c for c in found if not seen(c)]
        candidates += found[:cap]
        capped += max(0, len(found) - cap)
    return Window(candidates, capped, calls)


def mine(entries: list[dict], *, since_index: int = 0) -> tuple[list[Candidate], int]:
    """Candidates from `entries[since_index:]`, plus how many entries were read.

    A pure function over one list, for tests and for callers that hold a whole
    transcript. The hooks use `ingest`, which keeps a byte cursor and the
    calls still waiting for a result between firings.
    """
    total = len(entries)
    window = entries[max(0, since_index) :]
    if not window:
        return [], total
    return mine_window(window).candidates, total


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


# --------------------------------------------------------------------------- #
# Durable incremental ingestion (audit F02, WP09)
# --------------------------------------------------------------------------- #
#
# The hooks used to re-read an 8 MB tail every firing and keep, as a cursor, how
# many *entries* of that tail had been mined. Past 8 MB the tail slides, the
# count stops meaning anything, and new entries were never mined again. A
# call's result arriving a firing later was never joined to it, and whatever
# the per-firing cap held back was gone once the cursor moved.
#
# Now, per session (`hooks_common.load_miner_state`):
#
# - **The cursor is a byte offset** at a line boundary, with digests of the
#   file's first bytes and of the bytes just before the offset. A file that no
#   longer matches (truncated, replaced, rewritten) is read again from byte 0.
#   A trailing partial line is left for the next firing.
# - **Bash and edit calls are carried** between firings, bounded: every call
#   still waiting for its result, and the most recent resolved ones. A late
#   result joins its call, and the attempt rule sees a failure, edits and a
#   pass that came in different firings. A carried command or output holding a
#   credential is blanked first.
# - **Candidates go to a backlog before any jot is written**, and the cursor
#   and backlog are saved first. A candidate leaves the backlog only once it
#   is written, refused for a counted reason (duplicate, validation, secret),
#   or dropped after repeated write failures (counted). What the per-firing
#   cap holds back waits for the next firing.
# - **Acknowledged events are remembered** (`hooks_common.load_acked`): a
#   candidate whose transcript events were already acknowledged, in this
#   session or another, is not proposed again. A crash between a jot and the
#   state write, a replayed transcript, or a forked session therefore cannot
#   write the same thing twice.
#
# The whole pass runs under the store lock (WP05). If another writer holds it,
# nothing is consumed and the next firing reads the same bytes.

# The most transcript bytes one firing reads past its cursor. What lies beyond
# waits for the next firing, and the report says how much (`unread_bytes`).
MAX_BYTES_PER_FIRING = DEFAULT_MAX_BYTES
# A finished transcript (a subagent's) is mined in one go: at most this much of
# its tail, with the rest disclosed as `skipped_bytes`.
ONE_SHOT_MAX_BYTES = 4 * DEFAULT_MAX_BYTES
# How the cursor recognises its file.
IDENTITY_HEAD_BYTES = 4096
IDENTITY_ANCHOR_BYTES = 256
# Bash and edit calls carried between firings.
MAX_CARRIED_CALLS = 200
# Candidates waiting to be written. Past this, new ones are dropped and counted.
MAX_BACKLOG = 50
# Failed write attempts before a candidate is dropped (counted).
MAX_BACKLOG_ATTEMPTS = 5
# How far an over-long line's skip scan reads at a time.
_SCAN_BLOCK = 1 << 20

_CARRIED_TOOLS = (BASH_TOOL, *EDIT_TOOLS)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:32]


def _event_key(event: str) -> str:
    return hashlib.sha1(str(event).encode("utf-8")).hexdigest()[:16]


def _carry(call: ToolCall) -> dict | None:
    """A call as the miner keeps it between firings: bounded, and never a secret."""
    if call.name not in _CARRIED_TOOLS:
        return None
    if call.name == BASH_TOOL:
        command = normalize_command(call.input.get("command", ""))
        inp = {"command": command if redact_secrets(command) is not None else ""}
    else:
        path = (
            call.input.get("file_path") or call.input.get("path") or call.input.get("notebook_path")
        )
        inp = {"file_path": str(path)[:COMMAND_MAX_CHARS]} if path else {}
    text = call.result_text if call.outcome == FAILURE else ""
    if redact_secrets(text) is None:
        text = ""
    return {
        "id": call.call_id,
        "name": call.name,
        "input": inp,
        "text": text,
        "received": call.result_received,
        "outcome": call.outcome,
        "ts": call.timestamp,
    }


def _uncarry(row) -> ToolCall | None:
    try:
        return ToolCall(
            name=str(row["name"]),
            input=dict(row.get("input") or {}),
            result_text=str(row.get("text") or ""),
            index=-1,
            timestamp=row.get("ts") if isinstance(row.get("ts"), str) else None,
            result_received=bool(row.get("received")),
            outcome=str(row.get("outcome") or UNKNOWN),
            call_id=str(row.get("id") or ""),
        )
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _carry_forward(calls: list[ToolCall], stats: dict) -> list[dict]:
    """Every call still waiting for a result, then the newest resolved ones."""
    rows = [r for r in (_carry(c) for c in calls) if r]
    pending = [i for i, r in enumerate(rows) if not r["received"]]
    resolved = [i for i, r in enumerate(rows) if r["received"]]
    if len(pending) > MAX_CARRIED_CALLS:
        evicted = len(pending) - MAX_CARRIED_CALLS
        stats["evicted_pending"] = stats.get("evicted_pending", 0) + evicted
        pending = pending[evicted:]
    room = MAX_CARRIED_CALLS - len(pending)
    keep = set(pending) | set(resolved[-room:] if room > 0 else [])
    return [r for i, r in enumerate(rows) if i in keep]


def _read_new(path: Path, state: dict, max_bytes: int, report: dict) -> tuple[list[dict], dict]:
    """The complete lines past the cursor, and the state that records reading them."""
    size = path.stat().st_size
    offset = int(state.get("offset") or 0)
    ident = state.get("identity") if isinstance(state.get("identity"), dict) else {}
    with path.open("rb") as fh:
        if offset:
            reason = None
            if size < offset:
                reason = "truncated"
            else:
                fh.seek(0)
                head = fh.read(int(ident.get("head_len") or 0))
                anchor_at = max(0, offset - IDENTITY_ANCHOR_BYTES)
                fh.seek(anchor_at)
                anchor = fh.read(offset - anchor_at)
                if _digest(head) != ident.get("head") or _digest(anchor) != ident.get("anchor"):
                    reason = "replaced"
            if reason:
                report["reset"] = reason
                offset = 0
        fh.seek(offset)
        chunk = fh.read(max_bytes)
        cut = chunk.rfind(b"\n")
        if cut >= 0:
            consumed = cut + 1
        elif len(chunk) >= max_bytes:
            # One line longer than a whole firing's read. It cannot be parsed
            # within budget, so it is skipped, and counted, once it has ended.
            consumed = len(chunk)
            while True:
                block = fh.read(_SCAN_BLOCK)
                if not block:
                    consumed = 0  # still being written: wait for its end
                    break
                nl = block.find(b"\n")
                if nl >= 0:
                    consumed += nl + 1
                    report["oversize_lines"] += 1
                    break
                consumed += len(block)
            chunk = b""
        else:
            consumed = 0  # a partial last line: the rest is still to come
        data = chunk[:consumed]
        new_offset = offset + consumed
        head_len = min(IDENTITY_HEAD_BYTES, new_offset)
        fh.seek(0)
        head = fh.read(head_len)
        anchor_at = max(0, new_offset - IDENTITY_ANCHOR_BYTES)
        fh.seek(anchor_at)
        anchor = fh.read(new_offset - anchor_at)
    entries, malformed = _parse_lines(data)
    report["malformed_lines"] += malformed
    report["consumed_bytes"] = consumed
    report["unread_bytes"] = max(0, size - new_offset)
    return entries, {
        "offset": new_offset,
        "identity": {"head": _digest(head), "head_len": head_len, "anchor": _digest(anchor)},
    }


def _empty_report() -> dict:
    return {
        "written": [],
        "skipped": 0,
        "dropped_for_secrets": 0,
        "policy_capped": 0,
        "dropped_backlog": 0,
        "backlog": 0,
        "consumed_bytes": 0,
        "unread_bytes": 0,
        "skipped_bytes": 0,
        "oversize_lines": 0,
        "malformed_lines": 0,
        "reset": None,
        "locked": False,
        "error": None,
    }


def ingest(
    memory_dir: Path,
    project_root: Path,
    transcript_path: str | None,
    *,
    session_id: str,
    extra_tags: list[str] | None = None,
    one_shot: bool = False,
    max_bytes: int = MAX_BYTES_PER_FIRING,
) -> dict:
    """Mine what is new in a transcript into jots, durably. Never raises.

    `one_shot` mines a finished transcript whole (a subagent's), without a
    cursor; its candidates still go through this session's backlog. The report
    keeps `written` / `skipped` / `dropped_for_secrets` and adds what was held
    back or left: `policy_capped`, `backlog`, `dropped_backlog`, `unread_bytes`,
    `skipped_bytes`, `oversize_lines`, `malformed_lines`, `reset` and `locked`.
    """
    from breadcrumbs import lock as _lock

    report = _empty_report()
    if not transcript_path:
        return report
    memory_dir = Path(memory_dir)
    try:
        with _lock.store_lock(memory_dir, timeout=_lock.HOOK_TIMEOUT):
            _ingest_locked(
                memory_dir,
                Path(project_root),
                Path(transcript_path),
                session_id=session_id,
                extra_tags=extra_tags,
                one_shot=one_shot,
                max_bytes=max_bytes,
                report=report,
            )
    except _lock.StoreLocked as exc:
        report["locked"] = True
        report["error"] = str(exc)
    except Exception as exc:  # pragma: no cover - mining never breaks its hook
        report["error"] = f"{type(exc).__name__}: {exc}"
    return report


def _ingest_locked(
    memory_dir: Path,
    project_root: Path,
    path: Path,
    *,
    session_id: str,
    extra_tags: list[str] | None,
    one_shot: bool,
    max_bytes: int,
    report: dict,
) -> None:
    from breadcrumbs import hooks_common

    state = hooks_common.load_miner_state(memory_dir, session_id)
    stats = dict(state.get("stats") or {})
    acked = hooks_common.load_acked(memory_dir)
    acked_set = set(acked)
    known = _session_fingerprints(memory_dir, session_id)
    backlog = [b for b in state.get("backlog") or [] if isinstance(b, dict)]
    queued = {b.get("fingerprint") for b in backlog}

    def ack(events) -> None:
        for event in events or []:
            key = _event_key(event)
            if key not in acked_set:
                acked_set.add(key)
                acked.append(key)

    def seen(c: Candidate) -> bool:
        if c.fingerprint in known or c.fingerprint in queued or c.title_fingerprint in known:
            return True
        return bool(c.events) and all(_event_key(e) in acked_set for e in c.events)

    # 1. Read what is new, and mine it with the calls carried from before.
    progress: dict = {}
    entries: list[dict] = []
    carried: list[ToolCall] = []
    if path.is_file():
        if one_shot:
            size = path.stat().st_size
            report["skipped_bytes"] = max(0, size - ONE_SHOT_MAX_BYTES)
            entries = read_transcript(path, max_bytes=ONE_SHOT_MAX_BYTES)
        else:
            entries, progress = _read_new(path, state, max_bytes, report)
            carried = [c for c in (_uncarry(r) for r in state.get("calls") or []) if c]
    window = mine_window(entries, carried, seen=seen)
    report["policy_capped"] = window.capped

    # 2. Queue the candidates. Secrets are refused here, before anything
    #    is stored, and the refusal is an acknowledgment.
    for c in window.candidates:
        title, note = redact_secrets(c.title), redact_secrets(c.note)
        if title is None or note is None:
            report["dropped_for_secrets"] += 1
            ack(c.events)
            continue
        if len(backlog) >= MAX_BACKLOG:
            report["dropped_backlog"] += 1
            ack(c.events)
            continue
        backlog.append(
            {
                "fingerprint": c.fingerprint,
                "kind": c.kind,
                "title": title,
                "note": note,
                "files": list(c.files),
                "evidence": list(c.evidence),
                "events": list(c.events),
                "tags": sorted({"mined", c.kind, *(extra_tags or [])}),
                "attempts": 0,
            }
        )
        queued.add(c.fingerprint)

    # 3. Durable before acting: the cursor, the carried calls and the backlog.
    #    If this write fails, nothing below runs and the next firing re-reads.
    for key in ("policy_capped", "dropped_for_secrets", "oversize_lines", "malformed_lines"):
        stats[key] = stats.get(key, 0) + report[key]
    if report["reset"]:
        stats["resets"] = stats.get("resets", 0) + 1
    if not one_shot and path.is_file():
        state.update(progress)
        state["path"] = str(path)
        state["calls"] = _carry_forward(window.calls, stats)
        state["unread_bytes"] = report["unread_bytes"]
    state["backlog"] = backlog
    state["stats"] = stats
    hooks_common.save_miner_state(memory_dir, session_id, state)
    hooks_common.save_acked(memory_dir, acked)

    # 4. Write jots from the backlog, oldest first, up to the per-firing cap.
    _flush_backlog(memory_dir, project_root, session_id, backlog, known, ack, stats, report)
    state["backlog"] = backlog
    state["stats"] = stats
    hooks_common.save_miner_state(memory_dir, session_id, state)
    hooks_common.save_acked(memory_dir, acked)
    report["backlog"] = len(backlog)


def _flush_backlog(
    memory_dir: Path,
    project_root: Path,
    session_id: str,
    backlog: list[dict],
    known: set[str],
    ack,
    stats: dict,
    report: dict,
) -> None:
    from breadcrumbs import inbox as _inbox

    remaining: list[dict] = []
    stop = False
    for item in backlog:
        if stop or len(report["written"]) >= MINER_MAX_JOTS_PER_FIRING:
            remaining.append(item)
            continue
        fingerprint = item.get("fingerprint")
        if fingerprint in known:
            # Written by an earlier firing that stopped before it saved.
            report["skipped"] += 1
            ack(item.get("events"))
            continue
        try:
            result = _inbox.write_jot(
                memory_dir,
                project_root,
                item.get("note") or item.get("title") or "",
                tags=item.get("tags") or ["mined"],
                files=item.get("files") or [],
                local=True,
                source="transcript",
                agent=cli.detect_agent(fallback="agent"),
                host_session=session_id,
                fingerprint=fingerprint,
                evidence=item.get("evidence") or [],
                title=item.get("title"),
            )
        except Exception:
            # Not the candidate's fault (disk, permissions): keep it, try again
            # next firing, and stop writing for this one.
            item["attempts"] = int(item.get("attempts") or 0) + 1
            if item["attempts"] >= MAX_BACKLOG_ATTEMPTS:
                report["dropped_backlog"] += 1
                ack(item.get("events"))
            else:
                remaining.append(item)
            stop = True
            continue
        if result.get("ok"):
            known.add(fingerprint)
            report["written"].append(result["id"])
        else:
            report["skipped"] += 1  # refused by validate: final, and counted
        ack(item.get("events"))
    stats["dropped_backlog"] = stats.get("dropped_backlog", 0) + report["dropped_backlog"]
    backlog[:] = remaining


def note_report(report: dict) -> None:
    """What a hook's log line says about one ingestion."""
    from breadcrumbs import hooklog

    hooklog.note(
        mined=len(report.get("written") or []),
        miner_backlog=report.get("backlog") or None,
        miner_unread_bytes=report.get("unread_bytes") or None,
        miner_capped=report.get("policy_capped") or None,
        miner_dropped=report.get("dropped_backlog") or None,
        miner_reset=report.get("reset"),
        miner_locked=True if report.get("locked") else None,
    )


def mine_transcript_into_jots(
    memory_dir: Path,
    project_root: Path,
    transcript_path: str | None,
    *,
    session_id: str,
    use_cursor: bool = True,
    extra_tags: list[str] | None = None,
) -> dict:
    """What every hook wants: `ingest`, incrementally (`use_cursor`) or once whole."""
    return ingest(
        memory_dir,
        project_root,
        transcript_path,
        session_id=session_id,
        extra_tags=extra_tags,
        one_shot=not use_cursor,
    )
