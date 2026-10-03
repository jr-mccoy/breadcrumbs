"""breadcrumbs — search and guard: candidate items, scoring, verdicts.

Every record, trap and open question becomes a candidate item
(`_candidate_items`); `_score_item` scores one against a query by file, tag,
command, keyword and title signals, discounted by staleness and branch
mismatch; `search` ranks; `guard` classifies the action (its class and blast
radius), scores the store against it and decides a verdict — PROCEED,
READ_FIRST, PAUSE or ASK_HUMAN — that cites only records about the action.

Moved out of `cli.py` (health review 2.1). The shared tokens and stems are
`breadcrumbs.textmatch`; the `search` and `guard` commands and their human
rendering stay in `cli`.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from breadcrumbs import cli
from breadcrumbs import packet as _packet
from breadcrumbs import path_policy
from breadcrumbs import shellcmd as _shellcmd
from breadcrumbs import textmatch as _textmatch


# --------------------------------------------------------------------------- #
# search + guard — deterministic "don't repeat the expensive mistake"
# --------------------------------------------------------------------------- #
#
# This is the capability that separates a continuity engine from a scrapbook
# (§23): before you act, it warns you if a failed attempt or active decision says
# don't go that way. Two non-negotiables shape the whole layer:
#
#   1. NO EMBEDDINGS (§11). Matching is exact/keyword/tag/file-path/component
#      overlap over records already loaded in memory — deterministic, dependency
#      free, same input -> same output. SQLite FTS / vectors are a later,
#      disposable accelerator. Correct, not fast-at-scale.
#   2. MATCHED MEMORY IS DATA, NEVER INSTRUCTION (§15, §16 note, Fixture 7).
#      `guard` reads record text to *rank and cite* it; it never executes phrasing
#      found in memory. The "next safest action" is synthesized by this code from
#      match kinds — never lifted as an imperative from a record body. The only
#      memory text echoed back is structured evidence (e.g. a recorded verification
#      command) or a clearly-labeled excerpt presented as information.
#
# The anti-noise gate (§19b.8 / Fixture 3) lives in two deterministic rules: a
# stop-word filter strips generic words, and a pure-text match needs at least
# GUARD_MIN_KEYWORD_OVERLAP *specific* shared tokens (a single shared word never
# creates a warning unless it is a file-path or tag/component hit).

# ---- tunable thresholds (Task 8 / §22 Q2) ---------------------------------- #
# Exposed as named constants so guard aggressiveness can be tuned from dogfood
# feedback without rearchitecting. Chosen values + rationale recorded in
# phases/PHASE_5_search_and_guard.md ("Decisions resolved this phase").
GUARD_MAX_WARNINGS = 5  # §11.7 hard bound on ranked records shown
GUARD_NOISE_FLOOR = 3  # min score for a match to count at all (anti-noise)
GUARD_READ_FIRST_SCORE = 5  # score band: at/above -> at least READ_FIRST
GUARD_PAUSE_SCORE = 9  # score band: at/above -> at least PAUSE
GUARD_MIN_KEYWORD_OVERLAP = 2  # specific shared tokens for a pure-text match

# Ubiquity gate (0.1.10 field test, P0-2). In a store whose vocabulary overlaps
# the codebase, the tokens most records share carry no discriminating signal —
# package prefixes shed by cited file paths ("com", "kt", "java"), the project's
# own domain noun — yet two of them used to clear the keyword gate on every
# edit, so one trap fired on all 13 edits of a session. A stem present in more
# than GUARD_DF_UBIQUITY of the candidate corpus is ignored for keyword matching
# (zero weight, no gate credit), but only once the corpus is big enough for
# frequency to mean anything — below GUARD_DF_MIN_CORPUS items (every fixture,
# any young store) nothing is ubiquitous. File and tag matches are exempt: both
# are author-curated, deliberate signal.
GUARD_DF_UBIQUITY = 1 / 3
GUARD_DF_MIN_CORPUS = 8
# Rarity, a softer tier below ubiquity (DoWhat retest of 0.5.0, item 5). In a
# 400-record store full of migration and memory records, a `migration` tag or
# the word `memory` says little about *this* action, yet one shared tag plus one
# shared word made a record topical, and the same two records were cited on
# `git status`, `cp`, a reindex and a README edit. A tag or word carried by more
# than GUARD_DF_COMMON of the corpus is *common*: it scores half, and it cannot
# make a match topical on its own, so it cannot floor a verdict or make a
# do-not-retry line blocking. Unlike ubiquity this covers tags too: a tag on
# most records is author-curated, but it still names the whole store's topic.
# Below GUARD_DF_COMMON_MIN_CORPUS records nothing is common, and a stem must
# also be on more than GUARD_DF_COMMON_MIN_RECORDS records: in a 40-record
# store, four records sharing a tag is a topic, not the store's whole subject.
GUARD_DF_COMMON = 0.08
GUARD_DF_COMMON_MIN_CORPUS = 25
GUARD_DF_COMMON_MIN_RECORDS = 10

# scoring weights (§11.4 signals)
GUARD_W_FILE = 6  # per overlapping file path (strongest specific signal)
GUARD_W_TAG = 4  # per overlapping tag/component
# Per overlapping path the record only *mentions* in prose (G1). Below a tag and
# above a keyword: a prose mention is real evidence of topicality and is not the
# author saying "this record is about that file". It cannot open the candidate
# gate and it cannot floor a verdict; it can only add weight to a match that
# already qualified.
GUARD_W_MENTION = 2
GUARD_W_KEYWORD = 1  # per specific shared keyword
# Bonus per shared keyword that appears in the record's own *title*. A
# title names what the record is about; a body mention can be incidental. Scoring
# both at GUARD_W_KEYWORD made a decision whose title literally named the proposed
# action score like a passing reference — one stale-factor away from the noise
# floor. Additive: a title hit scores GUARD_W_KEYWORD + GUARD_W_TITLE.
GUARD_W_TITLE = 1
GUARD_W_STATUS_ACTIVE = 1
GUARD_W_CONFIDENCE_HIGH = 1
GUARD_W_REVIEWED = 1
GUARD_W_DO_NOT_RETRY = 4  # attempt carries an explicit "Do Not Retry Unless"
# A file the action writes without naming it (crumb's own commands, issue 11).
# Below a named file: the command is the sanctioned writer, so a trap about
# hand-editing that file should be seen, not take over the verdict.
GUARD_W_WRITES = 3
# Shared specific words that, on their own, make a do-not-retry attempt topical
# enough for its line to count ("logout no longer clears the session cookie"
# against an attempt whose result was "logout stopped clearing cookies").
GUARD_TOPICAL_KEYWORDS = 3
# Guard's keyword contribution stops here, so a longer command does not score
# higher for being longer (issue 7c). Plain search is uncapped.
GUARD_KEYWORD_CAP = 4
GUARD_W_OPEN_BLOCKER = 3  # overlaps an unresolved open question

# What a match must have, beyond shared vocabulary, to be surfaced as a warning
# rather than as history. `mention` is here and `keyword` is not: a prose-mined
# path is at least a claim about *this file*, where a shared stem is a claim
# about the language the project speaks. Deliberately not the same set as the
# specificity that lets a match raise a verdict ({file, tag}) — being worth
# showing and being worth escalating are different bars.
GUARD_SURFACING_SIGNALS = frozenset(
    {"file", "tag", "title", "mention", "do-not-retry", "open-blocker", "command", "writes-file"}
)

# recency / branch de-weighting (reuses the staleness signals above)
GUARD_BRANCH_MISMATCH_FACTOR = 0.8  # record written on another branch -> possibly stale
GUARD_STALE_AGE_FACTOR = 0.7  # record older than stale_days
GUARD_STALE_DIST_FACTOR = 0.7  # record written >= N commits behind HEAD
GUARD_STALE_DIST_COMMITS = 10

# Action classes that mean "a human should weigh in" when they collide with
# memory (§15 high-impact changes). Security/refactor are deliberately NOT here:
# they raise caution inside the normal bands but do not auto-escalate to ASK_HUMAN
# (a routine "rewrite auth middleware" should land on PAUSE/READ_FIRST, not ASK).
GUARD_HIGH_IMPACT_CLASSES = frozenset({"deletion", "migration", "external_side_effect"})

# Stance — does a matched record *oppose* the action, or merely *document* the
# area it touches? (0.1.11 field audit, F-1/F-2.) Retrieval overlap answers
# "is this record about the same thing"; it has never answered "does this record
# object", and the score band spent the difference. A trap that documented a
# hazard in ConversationDao.kt — including a `Safe approach:` prescribing the
# fix — scored file + title + 19 keywords and PAUSEd all five edits that
# implemented that prescribed fix. Documenting a hazard made the tool punish
# fixing it, which is the exact behavior the store exists to encourage.
#
# So relevance sets how loudly a record is surfaced, and stance sets how far it
# may raise the verdict:
#   blocking  — the record opposes *doing this*: an attempt carrying an explicit
#               "Do Not Retry Unless". Someone tried this and recorded why not to
#               again; that is the one thing the schema already states as opposition.
#   advisory  — everything else. A trap, decision, verification or open question
#               is knowledge about the area, not a prohibition on entering it.
#               It can demand a read; it cannot demand a stop.
# A high-impact action class still escalates past these ceilings below — that
# escalation is a property of the *action*'s blast radius, not of any record.
GUARD_BLOCKING_CEILING = "PAUSE"
GUARD_ADVISORY_CEILING = "READ_FIRST"

# ---- blast radius: the second axis (0.1.12 field report, issue 1) ---------- #
# Retrieval overlap and danger are different questions, and guard answered only
# the first. This regex already existed as `_HOOK_RISK_RE`, a *pre-filter* that
# decided whether an action was worth scoring and was then discarded — so the
# one danger signal in the codebase never reached a verdict or a prompt. It is
# now a first-class output (`guard()["destructive"]`).
#
# Deliberately literal: it names irreversible shell shapes, not vibes. Anything
# fuzzier belongs in the action classes, which are keyword-driven and already
# feed the ASK_HUMAN escalation.
_DESTRUCTIVE_OP_RE = re.compile(
    r"(?i)(--force\b|force-push|push\s+-f\b|reset\s+--hard|rm\s+-rf|git\s+clean|"
    r"--stop\b|drop\s+table|truncate\b|--no-verify|branch\s+-D\b)"
)

# Backwards-compatible alias: the pre-filter call site still reads as "is this
# worth scoring", which is a different question from "is this dangerous" even
# though one regex answers both today.
_HOOK_RISK_RE = _DESTRUCTIVE_OP_RE


def _is_destructive(action: str, classes: list[str]) -> bool:
    """Is this action hard to undo, independent of what memory says about it?

    True for a literal irreversible shell shape (`--force`, `rm -rf`, `reset
    --hard`, …) or a high-impact action class (deletion / migration / external
    side effect). Never consults the store: blast radius is a property of the
    action, and making it depend on how much of the repo the store cites is the
    conflation this exists to undo.
    """
    return bool(_DESTRUCTIVE_OP_RE.search(action or "")) or bool(
        GUARD_HIGH_IMPACT_CLASSES & set(classes or ())
    )


# ---- the other half of blast radius: an action that cannot do damage -------- #
#
# Retrieval overlap is symmetric, and that made the verdict scale *invert* in the
# 0.1.11 field test: `git status` — read-only, zero side effects — was the
# loudest command measured, at PAUSE with five matched records, while `npm test`,
# which executes arbitrary code, was silent at PROCEED. The mechanism is corpus
# frequency read as relevance: `git status` shares vocabulary with the many
# records that discuss git workflow, and an Android-heavy store shares nothing
# with `npm test`. No amount of scoring fixes that, because it is not a scoring
# question — it is that the command cannot do the thing being warned about.
#
# So classify the action first. A read-only verb caps at READ_FIRST however
# strong the overlap: memory is still worth surfacing (a trap about *reading*
# stale output is real), but it cannot rise to "stop and ask a human". PAUSE and
# ASK_HUMAN are reserved for actions that write, delete, push, deploy or execute.
GUARD_READ_ONLY_CEILING = "READ_FIRST"

# The read-only verb tables and the command reader live in `shellcmd` (field
# report 2026-10-01, issue 7 / N4); the names stay importable from here.
GUARD_READ_ONLY_COMMANDS = _shellcmd.READ_ONLY_COMMANDS
GUARD_READ_ONLY_GIT_SUBCOMMANDS = _shellcmd.READ_ONLY_GIT_SUBCOMMANDS
GUARD_READ_ONLY_DISQUALIFYING_ARGS = _shellcmd.READ_ONLY_DISQUALIFYING_ARGS


def _is_read_only_action(action: str) -> bool:
    """True only when the action provably cannot change anything (G2).

    Every segment of a compound command must be read-only on its own
    (`cd x && grep …` is; `find … | xargs rm -rf` is not), and output may only
    be redirected to `/dev/null` or another stream. An edit is never read-only.
    Conservative by construction: anything this cannot read is treated as
    capable of side effects, so a missed classification costs an unnecessary
    PAUSE, never a swallowed one.
    """
    text = (action or "").strip()
    if not text or _EDIT_ACTION_RE.match(text):
        return False
    return _shellcmd.is_read_only(text)


# What the Claude adapter (and `crumb guard --file`) builds for an edit:
# `edit <path>` or `edit <path>: <first characters of the new content>`.
_EDIT_ACTION_RE = re.compile(r"^(edit|delete a cell in) (\S+)(?::\s(.*))?$", re.S)


_VERDICTS = ("PROCEED", "READ_FIRST", "PAUSE", "ASK_HUMAN")
_VERDICT_RANK = {v: i for i, v in enumerate(_VERDICTS)}

# `crumb guard` exit codes, one per verdict (P0-1). Deliberately spaced so a
# script can threshold (`>= 15` = human involvement) and deliberately clear of
# 1 (crash), 2 (usage error), and 126+ (shell/OS conventions).
GUARD_VERDICT_EXIT_CODES = {"PROCEED": 0, "READ_FIRST": 10, "PAUSE": 15, "ASK_HUMAN": 20}


# Bullets in a trap block that hold the *remedy*, not the hazard. Mining file
# paths out of these is what made a trap fire on its own cure: a trap whose
# `Verification: ./gradlew test` and `Safe approach: wrap in
# withContext(Dispatchers.IO)` registered `./gradlew`, `gradlew` and
# `Dispatchers.IO` as tracked files scored GUARD_W_FILE (6, the strongest
# signal) against every gradle invocation in the repo — including
# `./gradlew --status`, a read-only status query. The file signal is exempt from
# the anti-noise ubiquity gate on the grounds that it is *author-curated*; text
# scraped out of a prescription is not curated, and it points at the fix rather
# than the fragile area. `Area / files:` is where a trap names its blast radius.
_TRAP_REMEDY_BULLET_RE = re.compile(
    r"(?im)^\s*[-*]\s*(safe\s*approach|verification|verify|fix|workaround)\s*:.*$"
)


# `- Area / files: app/src/Foo.kt, app/src/Bar.kt` — where a trap declares its
# blast radius. known-traps.md documents this five-field format at the top of the
# file, so it is a contract, not a convention.
_TRAP_AREA_BULLET_RE = re.compile(r"(?im)^\s*[-*]\s*area\s*(?:/\s*files)?\s*:(?P<value>.*)$")


def _trap_area_text(body: str) -> str:
    """Just the trap's `Area / files:` bullet(s) — the author's own declaration."""
    return "\n".join(m.group("value") for m in _TRAP_AREA_BULLET_RE.finditer(body or ""))


def _trap_hazard_text(body: str) -> str:
    """A trap block with its remedy bullets removed, for file-signal mining only.

    Keyword matching still sees the whole block — a remedy mentioning
    `Dispatchers.IO` is a legitimate weak text signal at GUARD_W_KEYWORD (1).
    Only the 6-point file signal is restricted to the hazard half.
    """
    return _TRAP_REMEDY_BULLET_RE.sub("", body or "")


# ---- action classifier (§11.2) --------------------------------------------- #


# Highest-severity class first; classify() returns that as the primary plus the
# full matched set. Keyword-driven and deterministic.
ACTION_CLASS_KEYWORDS: dict[str, frozenset[str]] = {
    "deletion": frozenset(
        {"delete", "remove", "drop", "rm", "purge", "teardown", "destroy", "wipe", "truncate"}
    ),
    "migration": frozenset(
        {"migrate", "migration", "backfill", "schema", "reindex", "datamigration"}
    ),
    "security_permission": frozenset(
        {
            "auth",
            "authentication",
            "authorization",
            "permission",
            "permissions",
            "credential",
            "credentials",
            "secret",
            "secrets",
            "token",
            "tokens",
            "oauth",
            "jwt",
            "rbac",
            "acl",
            "encrypt",
            "encryption",
            "scope",
            "scopes",
            "login",
            "session",
        }
    ),
    "external_side_effect": frozenset(
        {
            "deploy",
            "deployment",
            "publish",
            "release",
            "send",
            "email",
            "webhook",
            "production",
            "prod",
            "charge",
            "payment",
            "notify",
            "broadcast",
        }
    ),
    "dependency_tool": frozenset(
        {
            "dependency",
            "dependencies",
            "upgrade",
            "bump",
            "package",
            "npm",
            "pip",
            "library",
            "framework",
            "vendor",
            "sdk",
            "version",
        }
    ),
    "architecture": frozenset(
        {
            "architecture",
            "architectural",
            "pattern",
            "restructure",
            "rearchitect",
            "contract",
            "interface",
            "boundary",
            "layering",
            "decouple",
        }
    ),
    "broad_refactor": frozenset(
        {"refactor", "rewrite", "overhaul", "sweeping", "rename", "reorganize", "reorg", "port"}
    ),
}

_CLASS_SEVERITY = [
    "deletion",
    "migration",
    "security_permission",
    "external_side_effect",
    "dependency_tool",
    "architecture",
    "broad_refactor",
]


def classify_action(action: str) -> tuple[str, list[str]]:
    """Return (primary_class, sorted matched classes). 'routine_edit' if none hit.

    Reads what the action *does*, not what it *says* (field report 2026-10-01,
    issue 7 / N11): quoted text and here-document bodies are dropped, so a
    commit message or a `--next "cut the release"` note is not a release. An
    edit is classified by its path, not by the content being written. crumb's
    own commands are classified by the table in `shellcmd`, never by the words
    in their arguments: reading memory and writing memory are routine, and only
    a real `crumb migrate` is a migration.
    """
    edit = _EDIT_ACTION_RE.match((action or "").strip())
    effects: set[str] = set()
    if edit:
        text = f"{edit.group(1)} {edit.group(2)}"
    else:
        # Segment by segment (DoWhat retest of 0.5.0, item 2): a crumb command
        # counts by its effect, a read-only segment counts for nothing, and only
        # the rest is read for class words. Judging the whole command at once
        # made `crumb migrate --dry-run | sed -n '1,22p'` a migration, because
        # the `| sed` stopped it being "all crumb" and `migrate` was a word.
        segs = _shellcmd.segments(action or "")
        if segs is None:
            text = _shellcmd.classification_text(action or "")
        else:
            other: list[str] = []
            for seg in segs:
                args = _shellcmd.crumb_invocation(_shellcmd.words(seg))
                if args is not None:
                    effect = _shellcmd.crumb_effect(args)
                    effects.add(effect)
                    if effect == "other":
                        other.append(seg)
                    continue
                if _shellcmd.is_read_only(seg):
                    continue
                other.append(seg)
            text = _shellcmd.classification_text(" ; ".join(other))
    toks = _textmatch._tokenize(text)
    matched = {cls for cls, kws in ACTION_CLASS_KEYWORDS.items() if toks & kws}
    if "migration" in effects:
        matched.add("migration")
    if not matched:
        return "routine_edit", ["routine_edit"]
    primary = next(c for c in _CLASS_SEVERITY if c in matched)
    return primary, sorted(matched)


# ---- searchable corpus ----------------------------------------------------- #


def _attempt_has_do_not_retry(rec: cli.Record) -> bool:
    sec = rec.sections.get("Do Not Retry Unless", "")
    return bool(cli._first_line(sec))


_MD_HEADING_LINE_RE = re.compile(r"(?m)^#{1,6}\s.*$")


def _item_from_record(rec: cli.Record) -> dict:
    # Body-mined paths minus the ones that are really *commands*. A record whose
    # evidence is `--evidence command "./gradlew test"` or `--evidence test
    # "pytest tests/dao"` has that string in its body too, and `_paths_from_text`
    # cannot tell `pytest tests/dao` from a file reference — so the record scored
    # a 6-point file hit against every invocation of its own verification
    # command. Curated `--evidence file/path` refs are unaffected; this only
    # removes paths that the record itself already labelled as a command.
    cmd_paths = _textmatch._paths_from_text(" ".join(cli._evidence_refs(rec, ("command", "test"))))
    mined = _textmatch._paths_from_text(rec.body) - cmd_paths
    # Two tiers, not one (G1). `--evidence file …` is the author *declaring*
    # which files this record is about; a path mined out of its prose is a
    # mention, and the two were scored, displayed and reasoned about
    # identically. Declared paths keep the strongest signal guard has; mentions
    # get a weaker one and say so, so an agent reading `same file(s)` can still
    # trust it. A trap author knows which files their trap concerns — asking
    # beats any extractor.
    files = _textmatch._norm_files(set(cli._evidence_refs(rec, ("file", "path"))))
    mentioned = _textmatch._norm_files(mined) - files
    tags = {str(t).lower() for t in (rec.meta.get("tags") or [])}
    # Section headings are the template, not the record: "## Why It Failed /
    # Succeeded" made every attempt share `why` and `fail` with "why is my test
    # failing", and push the one relevant trap out (field report 2026-10-01,
    # issue 8).
    body_text = _MD_HEADING_LINE_RE.sub(" ", rec.body)
    text = " ".join([str(rec.meta.get("title") or ""), body_text, " ".join(tags)])
    # For verifications the interesting "status" is the *outcome* (open/fixed/…),
    # not the lifecycle status — so `search type:verification status:open` filters
    # on what the agent actually cares about. The lifecycle value is
    # kept alongside it: guard's liveness test needs both, and folding them into
    # one field is what silently excluded every verification from the verdict.
    lifecycle = str(rec.meta.get("status") or "active")
    status = (rec.meta.get("outcome") or "unknown") if rec.rtype == "verification" else lifecycle
    return {
        "id": rec.meta.get("id", rec.stem),
        "kind": rec.rtype,
        "status": status,
        "lifecycle": lifecycle,
        "title": rec.meta.get("title", "") or rec.stem,
        "tags": tags,
        # Stem -> original tag. Matching runs on stems (a "migrations" tag must
        # meet a "migration" query); display and `tag:` filters keep the raw tag.
        "tag_stems": {_textmatch._stem(t): t for t in tags},
        "files": files,
        "mentioned_files": mentioned,
        "specific": _textmatch._specific(text),
        # The title's own tokens, kept separate so `_score_item` can weight a
        # title hit above a body mention. The stem is the slug — same
        # words, so a filename hit counts as a title hit.
        "title_specific": _textmatch._specific(str(rec.meta.get("title") or rec.stem)),
        "branch": rec.meta.get("branch"),
        "record": rec,
        "do_not_retry": rec.rtype == "attempt" and _attempt_has_do_not_retry(rec),
        # An attempt titled "Ran gradlew --stop …" names a command just as a
        # trap's summary does (issue 8): the title head only, never the body.
        "command_heads": (
            _trap_command_heads(str(rec.meta.get("title") or ""), "")
            if rec.rtype == "attempt"
            else None
        ),
        "expired": cli.record_expired(rec.meta),
        "promoted": bool(rec.meta.get("promoted_to")),
        "scope": str(rec.meta.get("scope") or "project"),
    }


# ---- exact command hazards (audit F10) ------------------------------------- #
#
# A trap that names the very command about to run is the strongest evidence
# memory can give, and it used to score like one shared word: `npm test`
# against "npm test truncates the database" matched on the title alone (3 points)
# and came out PROCEED, while the pre-filter's two-specific-token rule let the
# hook skip the check entirely. The rule here is deliberately narrow:
#
# - a *head* is the command a trap names: the leading words of its summary, or
#   a backticked span anywhere in it;
# - the action names it when their longest common token prefix is at least two
#   tokens and covers the whole action, or stops at a flag (`npm test --watch`);
# - a match gets the `command` signal and, for a live trap, a READ_FIRST floor
#   (advisory: the reader is told, the permission flow is untouched).
#
# One shared word ("make sure …" against `make`) is never enough, and a hazard's
# documented remedy (`npm run test:unit`) does not share the prefix.

_BACKTICK_SPAN_RE = re.compile(r"`([^`\n]{2,160})`")
_COMMAND_MIN_TOKENS = 2


# A head is `[kind, *tokens]`. A `title` head is the leading words of a trap's
# summary, so the action need only match its start; a `span` head is a whole
# backticked command, so the action must contain all of it. The kind travels
# with the head (into the pre-filter too), never inferred from its position.
_HEAD_TITLE = "title"
_HEAD_SPAN = "span"
# A summary that opens with one of these describes running the command after it
# ("Running npm test truncates …").
_RUN_VERBS = ("run", "running", "runs", "ran", "calling", "executing")


def _trap_command_heads(heading: str, body: str) -> list[list[str]]:
    """The commands a trap names: its summary's head, then each backticked span."""
    summary = heading
    if heading.startswith("trap_") and ":" in heading:
        summary = heading.split(":", 1)[1]
    tokens = _shellcmd.match_tokens(summary)
    heads = [[_HEAD_TITLE, *tokens]]
    if tokens and tokens[0] in _RUN_VERBS:
        heads.append([_HEAD_TITLE, *tokens[1:]])
    # The hazard half only: a backticked command in the remedy ("use
    # `npm run test:unit`") is what to run instead, never the hazard.
    for span in _BACKTICK_SPAN_RE.findall(heading + "\n" + _trap_hazard_text(body or "")):
        tokens = _shellcmd.match_tokens(span)
        if len(tokens) >= _COMMAND_MIN_TOKENS:
            heads.append([_HEAD_SPAN, *tokens])
    return heads


def _names_command(action_tokens: list[str], heads) -> bool:
    """Does the action run a command one of these heads names? See above."""
    if len(action_tokens) < _COMMAND_MIN_TOKENS:
        return False
    for head in heads or ():
        if not head or head[0] not in (_HEAD_TITLE, _HEAD_SPAN):
            continue
        kind, tokens = head[0], head[1:]
        n = 0
        for a, b in zip(action_tokens, tokens):
            if a != b:
                break
            n += 1
        if n < _COMMAND_MIN_TOKENS:
            continue
        if kind == _HEAD_SPAN and n < len(tokens):
            continue  # a backticked command must be named whole
        if n == len(action_tokens) or action_tokens[n].startswith("-"):
            return True
    return False


def _item_from_trap(trap: dict) -> dict:
    heading, body = trap["heading"], trap.get("content", trap.get("body", ""))
    # Trap files carry tags since the field report's N1; a trap never scored
    # them, so a trap tagged `robolectric` lost to every attempt sharing it.
    tags = {str(t).lower() for t in (trap.get("tags") or [])}
    text = heading + "\n" + body + "\n" + " ".join(sorted(tags))
    return {
        "id": trap.get("id") or heading.split(":", 1)[0].strip() or "trap",
        "kind": "trap",
        # Was hardcoded "active", which is what made a retired trap keep scoring
        # in search and keep counting as live in guard's active/history split.
        "status": trap.get("status") or "active",
        "title": heading,
        "tags": tags,
        "tag_stems": {_textmatch._stem(t): t for t in tags},
        "files": _textmatch._norm_files(_textmatch._paths_from_text(_trap_area_text(body))),
        "mentioned_files": (
            _textmatch._norm_files(_textmatch._paths_from_text(_trap_hazard_text(body)))
            - _textmatch._norm_files(_textmatch._paths_from_text(_trap_area_text(body)))
        ),
        "specific": _textmatch._specific(text),
        "title_specific": _textmatch._specific(heading),
        "command_heads": _trap_command_heads(heading, body),
        "branch": None,
        "record": None,
        "do_not_retry": False,
        "promoted": bool(
            cli._BLOCK_PROMOTED_LINE_RE.search(trap.get("body") or "") or trap.get("promoted_to")
        ),
    }


QUESTION_SLUG_CHARS = 48


def question_item_id(question: str) -> str:
    """Search id for an open question: `q_<slug>`, disambiguated when truncated.

    Truncating the slug at 48 characters made two distinct questions share one id
    ("… to the new columnar store this quarter" / "… to the new row store next
    quarter" both slugify past the cut with the same prefix), and `search`'s
    by_id map kept only the last — which `guard`'s `_recommended_action` resolves
    through. A short digest of the *full* question restores
    uniqueness; ids for questions short enough not to be cut are unchanged.
    """
    slug = cli.slugify(question)
    if len(slug) <= QUESTION_SLUG_CHARS:
        return QUESTION_ID_PREFIX + slug
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:6]
    return f"{QUESTION_ID_PREFIX}{slug[:QUESTION_SLUG_CHARS].rstrip('-')}-{digest}"


# Question ids were `q:<slug>` through 0.2.x and are `q_<slug>` from Phase 2 on
# (WM-21/WM-22). The colon was the only id in the store that was not a valid
# filename or a clean URI path segment, and questions are about to become files
# and `memory://questions/{id}` resources. The old spelling is still accepted
# everywhere an id is *read* — it is in commit messages, decision records and
# people's shell history — and never printed.
QUESTION_ID_PREFIX = "q_"
_LEGACY_QUESTION_ID_PREFIX = "q:"


def normalize_question_id(rid: str) -> str:
    """`q:<slug>` -> `q_<slug>`; anything else unchanged."""
    rid = (rid or "").strip()
    if rid.lower().startswith(_LEGACY_QUESTION_ID_PREFIX):
        return QUESTION_ID_PREFIX + rid[len(_LEGACY_QUESTION_ID_PREFIX) :]
    return rid


def _item_from_question(q: dict) -> dict:
    body = q.get("content", q.get("body", ""))
    text = q["question"] + "\n" + body
    return {
        "id": q.get("id") or question_item_id(q["question"]),
        "kind": "question",
        "status": (q.get("status") or "open"),
        "title": q["question"],
        "tags": set(),
        # A question has no author-declared file field; everything it names is a
        # mention.
        "files": set(),
        "mentioned_files": _textmatch._norm_files(_textmatch._paths_from_text(body)),
        "specific": _textmatch._specific(text),
        "title_specific": _textmatch._specific(q["question"]),
        "branch": None,
        "record": None,
        "do_not_retry": False,
    }


# The corpus every ranked lookup draws from. Two corpora, not one — see
# `_candidate_items`.
JUDGING_ITEM_TYPES = ("decision", "attempt", "verification")
# Types a lookup should find but a verdict must never rest on. An idea is a
# proposal; a jot is an unconfirmed observation with a TTL. Neither has been
# through the evidence rule, and `_decide_verdict`'s score band is kind-agnostic,
# so either would otherwise gate a real edit on the strength of nobody having
# done the work yet.
SPECULATIVE_ITEM_TYPES = ("idea", "jot")


def _candidate_items(memory_dir: Path, *, include_ideas: bool = False) -> list[dict]:
    """Every searchable item: durable decision/attempt records + trap + question blocks.

    `include_ideas` is the **search-only corpus switch**. `crumb note idea` writes a
    real, validated record, but for most of this package's life nothing loaded it, so
    an idea could only be found by opening `ideas/`. The reason it stayed out is
    that `guard` is built on this same function: an idea is a *proposal*, deliberately
    exempt from the §16.9 evidence rule, and `_decide_verdict`'s score band is
    kind-agnostic — so a speculative note that happened to name the files being edited
    would have raised a real verdict on the strength of nobody having done the work.
    That is the one thing guard must never do.

    So the corpus forks by *who is asking*, not by record type:

    - **Lookup** (`crumb search`, the `memory_search` MCP tool) passes True. A human
      or agent asking "what do we know about X" wants the idea.
    - **Judging** (`guard`, the `PreToolUse` hook path, `resume --task`'s likely-file
      scoping) leaves it False. These turn matches into advice or into a packet, and
      speculation is not evidence.

    Jots ride the same switch as ideas, for the same reason: an unconfirmed
    one-line note that happens to name the file being edited must not raise a
    verdict. It is findable, and that is all it is.

    Sessions stay out of both: they are narrative, and under
    `session_tracking: distillate` a clone may not have them at all, so including
    them would make results depend on which checkout you ran in.
    """
    # Store aliases first: `search` stems the query right after this returns,
    # and both sides of every comparison must fold through the same table.
    _textmatch.activate_store_aliases(memory_dir)
    types = JUDGING_ITEM_TYPES + (SPECULATIVE_ITEM_TYPES if include_ideas else ())
    items: list[dict] = []
    for rec in cli.load_records(memory_dir, types=types):
        if rec.error:
            continue
        items.append(_item_from_record(rec))
    items.extend(_item_from_trap(t) for t in cli.load_traps(memory_dir))
    items.extend(_item_from_question(q) for q in cli.load_open_questions(memory_dir))
    return _disambiguate_item_ids(items)


def _disambiguate_item_ids(items: list[dict]) -> list[dict]:
    """Make every candidate id unique, appending `-2`, `-3`, … like `_unique_record_path`.

    Records are filename-canonical and validate §16.4 already rejects duplicate ids,
    but trap and question ids are derived from free text (a trap's id is the heading
    prefix, a question's a slug), so two blocks can still land on one id. `search`
    builds a by_id map that keeps only the last of a colliding pair, and guard
    resolves its next-safest-action through that map — so a collision silently
    substitutes one item's advice for another's.
    """
    seen: dict[str, int] = {}
    for item in items:
        base = item["id"]
        if base not in seen:
            seen[base] = 1
            continue
        seen[base] += 1
        item["id"] = f"{base}-{seen[base]}"
    return items


# ---- scoring (§11.4) ------------------------------------------------------- #


def _ubiquitous_stems(items: list[dict]) -> frozenset[str]:
    """Stems present in more than GUARD_DF_UBIQUITY of the corpus (see constants).

    Deterministic document frequency over the candidate items' own token bags —
    no external vocabulary, so the same store always yields the same set.
    """
    n = len(items)
    if n < GUARD_DF_MIN_CORPUS:
        return frozenset()
    df: dict[str, int] = {}
    for it in items:
        for s in it["specific"]:
            df[s] = df.get(s, 0) + 1
    cutoff = n * GUARD_DF_UBIQUITY
    return frozenset(s for s, c in df.items() if c > cutoff)


def _score_item(
    item: dict,
    q_specific: set[str],
    q_files: set[str],
    root: Path,
    cur_branch: str,
    stale_days: int,
    *,
    min_keyword: int,
    distances: cli.CommitDistanceIndex,
    ubiquitous: frozenset[str] = frozenset(),
    q_words: frozenset[str] = frozenset(),
    keyword_cap: int | None = None,
    q_writes: set[str] = frozenset(),
    do_not_retry_boost: bool = True,
    reached: "cli.HeadTree | None" = None,
    common: frozenset[str] = frozenset(),
    common_tags: frozenset[str] = frozenset(),
) -> dict | None:
    """Score one item against the query. None if it does not clear the candidate gate.

    `common` / `common_tags` are the query's stems that too many records carry
    as a word / as a tag to say much (`GUARD_DF_COMMON`): they score half and
    never make a match topical by themselves.
    """

    # _norm_files stores each file as both its full path and its bare basename,
    # so the intersection can hold both variants of one physical file. Count each
    # distinct full path once, plus any bare-basename match not already covered by
    # a matched full path. Keying on basename alone (the old approach) wrongly
    # collapsed genuinely-distinct files that share a name (src/a/x.ts, src/b/x.ts)
    # — undercounting the score and picking a hash-order-dependent survivor.
    def _overlap(candidate: set[str], against: set[str] = q_files) -> tuple[list[str], int]:
        raw = candidate & against
        full_paths = {f for f in raw if "/" in f}
        covered = {f.rsplit("/", 1)[-1] for f in full_paths}
        extra_bare = {f for f in raw if "/" not in f and f not in covered}
        return sorted(full_paths | extra_bare), len(full_paths) + len(extra_bare)

    matched_files, file_count = _overlap(item["files"])
    # Prose-mined paths, scored separately and never as "same file(s)".
    matched_mentions, mention_count = _overlap(item.get("mentioned_files", set()) - item["files"])
    # Files the action writes without naming them (crumb's own commands,
    # issue 11): weaker than a file the action names, and said differently.
    matched_writes, writes_count = _overlap(item["files"], q_writes) if q_writes else ([], 0)
    # Tag overlap is computed on stems; the display set carries the raw tags.
    tag_stems = item.get("tag_stems") or {t: t for t in item["tags"]}
    matched_tag_stems = set(tag_stems) & q_specific
    matched_tags = {tag_stems[s] for s in matched_tag_stems}
    # Ubiquitous stems (present in most of the corpus) are dropped before either
    # the gate or the weights see them — a token every record shares proves
    # nothing about *this* record.
    kw_overlap = (item["specific"] & q_specific) - ubiquitous
    kw_count = len(kw_overlap)
    # Title tokens are a subset of `specific` (the text bag includes the title),
    # so this can only re-weight an existing keyword hit, never create a match
    # the candidate gate below would have rejected.
    title_overlap = (item.get("title_specific", set()) & q_specific) - ubiquitous

    # Candidate gate (anti-noise, Fixture 3): a file or tag hit always qualifies;
    # a pure-text match needs >= min_keyword specific shared tokens.
    # A mention still opens the gate — `search --file src/auth/middleware.ts` has
    # no keywords to fall back on, and a record that names that file in its prose
    # is exactly what the caller asked for. What a mention no longer does is
    # claim to be the author's own file declaration: it scores lower, it reads as
    # `mentions:` rather than `same file(s):`, and it is not the specificity that
    # lets a match floor a verdict.
    # A query with fewer specific words than the floor (`npm test` is one:
    # "test" is generic) could never reach it, so no record could match it on
    # text at all: the field review's silent `npm test`. When the record's
    # *title* carries every specific word the query has, that is the same
    # evidence two shared words would be. Measured by the relevance evals (WM-61).
    # Every word of the query counts here, generic ones included, or `npm test`
    # would reduce to `npm` and match every record titled with npm.
    q_live = q_specific - ubiquitous
    short_query_title_hit = (
        bool(q_live)
        and len(q_live) < min_keyword
        and q_live <= title_overlap
        and q_words <= {_textmatch._stem(t) for t in _textmatch._tokenize(item.get("title") or "")}
    )
    if (
        not matched_files
        and not matched_mentions
        and not matched_tags
        and not matched_writes
        and kw_count < min_keyword
        and not short_query_title_hit
    ):
        return None

    signals: list[str] = []
    score = 0.0
    rare_tag_stems = matched_tag_stems - common_tags
    rare_kw = kw_overlap - common
    if matched_files:
        score += GUARD_W_FILE * file_count
        signals.append("file")
    if matched_mentions:
        score += GUARD_W_MENTION * mention_count
        signals.append("mention")
    if matched_tags:
        score += GUARD_W_TAG * len(rare_tag_stems)
        score += GUARD_W_TAG / 2 * (len(matched_tag_stems) - len(rare_tag_stems))
        # Only a rare tag is a surfacing signal; a tag half the store carries
        # is a topic, and on its own it is said as such (`common-tag`).
        signals.append("tag" if rare_tag_stems else "common-tag")
    if matched_writes:
        score += GUARD_W_WRITES * writes_count
        signals.append("writes-file")
    if kw_count:
        # Capped for guard: overlap grew with the command's length, so a long
        # commit message scored 39 against records it had nothing to do with
        # (issue 7c). Plain search keeps the uncapped count. A common word
        # counts half (item 5 of the 0.5.0 retest).
        weighted = len(rare_kw) + (kw_count - len(rare_kw)) / 2
        score += GUARD_W_KEYWORD * (min(weighted, keyword_cap) if keyword_cap else weighted)
        if kw_count >= min_keyword:
            signals.append("keyword")
    if title_overlap:
        score += GUARD_W_TITLE * len(title_overlap - common)
        score += GUARD_W_TITLE / 2 * len(title_overlap & common)
        if title_overlap - common:
            signals.append("title")

    rec = item.get("record")
    if item["status"] == "active":
        score += GUARD_W_STATUS_ACTIVE
    if rec is not None:
        if rec.meta.get("confidence") == "high":
            score += GUARD_W_CONFIDENCE_HIGH
        if rec.meta.get("review_status") == "reviewed":
            score += GUARD_W_REVIEWED
    # A do-not-retry line opposes *this* action only when the record is about
    # it: a file, the title, a tag plus a shared word, or a file the action
    # writes. Applied on any overlap, one shared tag lifted an unrelated
    # attempt to the PAUSE band and pushed the relevant record out (issue 8).
    # Words beyond the tags: a tag's own word is in the record's text too, so it
    # would otherwise count as the "shared word" that makes a tag hit topical.
    # Only rare evidence counts (item 5 of the 0.5.0 retest): a common tag
    # plus one common word is what a store says about everything. In a store
    # too small to have common words, these are the rules they always were.
    kw_beyond_tags = len(rare_kw - matched_tag_stems)
    topical = bool(
        matched_files
        or (title_overlap - matched_tag_stems - common)
        or matched_writes
        or (rare_tag_stems and kw_beyond_tags >= 1)
        or (len(matched_tag_stems) >= 2 and rare_tag_stems)
        or (matched_tag_stems and kw_beyond_tags >= 2)
        or kw_beyond_tags >= GUARD_TOPICAL_KEYWORDS
    )
    if item["do_not_retry"] and do_not_retry_boost and topical:
        score += GUARD_W_DO_NOT_RETRY
        signals.append("do-not-retry")
    if item["kind"] == "question" and item["status"] == "open":
        score += GUARD_W_OPEN_BLOCKER
        signals.append("open-blocker")

    # Recency + commit-distance de-weighting. The
    # pre-decay score is kept on the match: `search` needs it to tell "under the
    # noise floor on raw signal" (noise — drop) from "pushed under it by the
    # stale factors" (a real match — surface as history).
    undecayed = score
    factor = 1.0
    if rec is not None:
        age = cli._age_days(rec.meta.get("updated_at") or rec.meta.get("created_at"))
        if age is not None and age > stale_days:
            factor *= GUARD_STALE_AGE_FACTOR
        # Via the shared index, not a per-record `git_commit_distance`:
        # same answer, but the git calls stop scaling with the store's size.
        if distances.distance_reaches(rec.meta.get("commit")):
            factor *= GUARD_STALE_DIST_FACTOR

    # Branch match: a mismatch is surfaced (§15), not hidden — de-weight + flag.
    branch_mismatch = False
    rb = item.get("branch")
    if (
        rb
        and rb not in (cli.NO_GIT_BRANCH, None, "")
        and cur_branch not in (cli.NO_GIT_BRANCH, "HEAD")
        and rb != cur_branch
        # A record whose file has reached HEAD (merged, squashed, rebased) is
        # history here, not a risk — the same test resume uses (issue 9).
        and not (reached is not None and rec is not None and reached.contains(rec.path))
    ):
        branch_mismatch = True
        factor *= GUARD_BRANCH_MISMATCH_FACTOR
        signals.append("branch-mismatch")

    score = round(score * factor, 2)
    return {
        "id": item["id"],
        "kind": item["kind"],
        "status": item["status"],
        "lifecycle": item.get("lifecycle", item["status"]),
        "expired": bool(item.get("expired")),
        "promoted": bool(item.get("promoted")),
        "scope": item.get("scope") or "project",
        "title": item["title"],
        "score": score,
        "raw_score": round(undecayed, 2),
        "suppressed": False,  # set by `search` when decay pushed it under the floor
        "signals": signals,
        # Whether this record opposes the action or merely documents its area.
        # Exported so a caller can tell the two apart without re-deriving it from
        # `signals` — the 0.1.11 audit's F-2: the output gave a PAUSE-driving
        # record and a merely-topical one the same shape of evidence.
        "stance": _match_stance(signals),
        "matched_files": sorted(matched_files),
        "matched_mentions": sorted(matched_mentions),
        "matched_tags": sorted(matched_tags),
        "keyword_overlap": sorted(kw_overlap),
        "matched_writes": sorted(matched_writes),
        # Is there evidence beyond one shared topic? A tag alone (a `git` tag
        # against `git status`) says the record is about the same component,
        # not about this action; it no longer floors a verdict by itself.
        "topical": topical,
        "branch_mismatch": branch_mismatch,
        "reason": _match_reason(
            item["kind"],
            signals,
            matched_files,
            matched_tags,
            kw_count,
            matched_mentions,
            matched_writes,
        ),
    }


def _match_reason(
    kind, signals, matched_files, matched_tags, kw_count, matched_mentions=(), matched_writes=()
) -> str:
    """Human phrase for why a record matched. Derived facts only — never executed."""
    parts: list[str] = []
    if matched_files:
        shown = ", ".join(sorted(matched_files)[:3])
        parts.append(f"same file(s): {shown}")
    if matched_writes:
        parts.append(f"this command writes: {', '.join(sorted(matched_writes)[:3])}")
    if matched_mentions:
        # Deliberately a different phrase. `same file(s)` is a claim the author
        # made; this is one the extractor made, and telling them apart is what
        # keeps the first one worth reading.
        parts.append(f"mentions: {', '.join(sorted(matched_mentions)[:3])}")
    if matched_tags:
        parts.append(f"same component/tag: {', '.join(sorted(matched_tags))}")
    if kw_count and not matched_files and not matched_tags:
        parts.append(f"{kw_count} shared keyword(s)")
    elif kw_count:
        parts.append(f"+{kw_count} shared keyword(s)")
    if "title" in signals:
        parts.append("named in the record's title")
    if "do-not-retry" in signals:
        parts.append("has an explicit do-not-retry condition")
    if "open-blocker" in signals:
        parts.append("an unresolved open question touches this")
    if "branch-mismatch" in signals:
        parts.append("written on another branch (possibly stale)")
    return "; ".join(parts) if parts else "keyword overlap"


def _common_stems(df: dict) -> tuple[frozenset[str], frozenset[str]]:
    """(common words, common tags) among the query's stems (`GUARD_DF_COMMON`)."""
    n = int(df.get("n") or 0)
    if n < GUARD_DF_COMMON_MIN_CORPUS:
        return frozenset(), frozenset()
    cutoff = max(n * GUARD_DF_COMMON, GUARD_DF_COMMON_MIN_RECORDS)
    words = frozenset(s for s, c in (df.get("words") or {}).items() if c > cutoff)
    tags = frozenset(s for s, c in (df.get("tags") or {}).items() if c > cutoff)
    return words, tags


def search(
    memory_dir: Path,
    root: Path,
    query: str,
    *,
    files: list[str] | None = None,
    filters: dict | None = None,
    stale_days: int = cli.STALE_AGE_DAYS,
    min_keyword: int = 1,
    noise_floor: int = 1,
    include_ideas: bool = False,
    allow_full_scan: bool = True,
    info: dict | None = None,
    path_text: str | None = None,
    keyword_cap: int | None = None,
    writes: list[str] | None = None,
    do_not_retry_boost: bool = True,
    command_text: str | None = None,
) -> tuple[list[dict], dict[str, dict]]:
    """Deterministic search over the canonical records (§20.10).

    Guard's own knobs: `path_text` is where query paths are read from (default
    the query), `keyword_cap` bounds the keyword contribution so a longer
    command does not score higher for being long, `writes` are files the
    action writes without naming them (crumb's own commands, issue 11),
    `command_text` is the command matched against the commands records name
    (default the query), and `do_not_retry_boost=False` ranks by relevance
    alone (the prompt hook).

    Returns (matches sorted best-first, items_by_id). Matching signals: exact/
    keyword text, tag/component, and file path. No embeddings; same input ->
    same output. `filters` narrows the corpus by type/status/tag/file first.

    `include_ideas` selects the wider, lookup-only corpus — see `_candidate_items`.
    It defaults to False so a caller that forgets it gets guard's corpus, which is
    the safe side of the mistake.

    `info`, when given, is filled with how the lookup ran (audit WP10): `mode`
    (`indexed`, or `full_scan` with the index's `reason`), and `candidates`, the
    records scored. With `allow_full_scan=False` a lookup the index cannot
    serve returns nothing with `mode: "skipped"` instead of scanning, which is
    a bounded caller's choice; plain search always completes.
    """
    # Aliases before the query is stemmed: both sides of every comparison must
    # fold through the same table (WM-24).
    _textmatch.activate_store_aliases(memory_dir)
    filters = filters or {}
    q_specific = _textmatch._specific(query)
    q_words = frozenset(
        _textmatch._stem(t)
        for t in _textmatch._tokenize(query)
        if t not in _textmatch._FUNCTION_WORDS
    )
    q_files = _textmatch._norm_files(
        _textmatch._paths_from_text(query if path_text is None else path_text) | set(files or [])
    )
    q_writes = _textmatch._norm_files(writes or []) - q_files
    q_command = _shellcmd.match_tokens(query if command_text is None else command_text)
    # The search index narrows the corpus to records that could possibly match
    # (WM-23). It returns None whenever it cannot be trusted or cannot help, and
    # the full scan below is then exactly what it always was.
    from breadcrumbs import searchindex as _searchindex

    explain: dict = {}
    df: dict = {}
    narrowed = _searchindex.candidate_items(
        memory_dir,
        root,
        q_specific,
        q_files | q_writes,
        include_ideas=include_ideas,
        explain=explain,
        df_out=df,
    )
    info = info if info is not None else {}
    if narrowed is not None:
        items, ubiquitous = narrowed
        info.update(mode="indexed", reason=None)
    else:
        info.update(mode="full_scan", reason=explain.get("reason"))
        if not allow_full_scan:
            info.update(mode="skipped", candidates=0)
            return [], {}
        items = _candidate_items(memory_dir, include_ideas=include_ideas)
        ubiquitous = _ubiquitous_stems(items)
        df = {
            "n": len(items),
            "words": {q: sum(1 for it in items if q in it["specific"]) for q in q_specific},
            "tags": {
                q: sum(1 for it in items if q in (it.get("tag_stems") or ())) for q in q_specific
            },
        }
    common, common_tags = _common_stems(df)
    info["candidates"] = len(items)
    by_id = {it["id"]: it for it in items}
    cur_branch = cli.git_branch(root)
    # One commit-distance index for the whole pass — see the class.
    distances = cli.CommitDistanceIndex(root, GUARD_STALE_DIST_COMMITS)
    # Which record files have reached HEAD, built once per pass (issue 9): a
    # record committed here from a since-merged branch is history, not "written
    # on another branch", whatever its `branch:` field says.
    reached = cli._reached_head(root)

    matches: list[dict] = []
    for it in items:
        if not _passes_filters(it, filters):
            continue
        m = _score_item(
            it,
            q_specific,
            q_files,
            root,
            cur_branch,
            stale_days,
            min_keyword=min_keyword,
            distances=distances,
            ubiquitous=ubiquitous,
            q_words=q_words,
            keyword_cap=keyword_cap,
            q_writes=q_writes,
            do_not_retry_boost=do_not_retry_boost,
            reached=reached,
            common=common,
            common_tags=common_tags,
        )
        if it.get("command_heads") and _names_command(q_command, it["command_heads"]):
            m = _with_command_signal(m, it, do_not_retry_boost=do_not_retry_boost)
        if m is None:
            # Filter-only lookups (no scoring query) still surface the item.
            if filters and not q_specific and not q_files:
                m = {
                    "id": it["id"],
                    "kind": it["kind"],
                    "status": it["status"],
                    "lifecycle": it.get("lifecycle", it["status"]),
                    "expired": bool(it.get("expired")),
                    "promoted": bool(it.get("promoted")),
                    "title": it["title"],
                    "score": float(noise_floor),
                    "raw_score": float(noise_floor),
                    "suppressed": False,
                    "signals": ["filter"],
                    "matched_files": [],
                    "matched_tags": [],
                    "keyword_overlap": [],
                    "branch_mismatch": False,
                    "reason": "matched filter",
                }
            else:
                continue
        if m["score"] < noise_floor:
            # De-weighting must never erase (field test 2026-08-04). The
            # stale/branch factors compound to 0.39, which pushed real matches —
            # a decision whose title named the proposed action — under the floor
            # with no trace, so the store went quietest exactly where it was
            # oldest. A match under the floor on its *raw* signal is genuine
            # noise and still drops; one pushed under it by decay is kept,
            # marked, for guard to demote to history (mention-only).
            if m["raw_score"] < noise_floor:
                continue
            m["suppressed"] = True
            m["signals"].append("stale-suppressed")
            m["reason"] += "; de-weighted below the noise floor by age/branch"
        matches.append(m)

    matches.sort(key=lambda m: (-m["score"], m["id"]))
    return matches, by_id


def _with_command_signal(m: dict | None, item: dict, *, do_not_retry_boost: bool = True) -> dict:
    """Mark a match (or make one) for a record that names the action's command."""
    if m is None:
        m = {
            "id": item["id"],
            "kind": item["kind"],
            "status": item["status"],
            "lifecycle": item.get("lifecycle", item["status"]),
            "expired": bool(item.get("expired")),
            "promoted": bool(item.get("promoted")),
            "title": item["title"],
            "score": 0.0,
            "raw_score": 0.0,
            "suppressed": False,
            "signals": [],
            "matched_files": [],
            "matched_tags": [],
            "keyword_overlap": [],
            "branch_mismatch": False,
            "reason": "",
        }
    if "command" not in m["signals"]:
        m["signals"].append("command")
        m["reason"] = (m["reason"] + "; " if m["reason"] else "") + "names this exact command"
    # Naming the exact command is the most topical evidence there is, so an
    # attempt's do-not-retry line applies (issue 8: "Ran gradlew --stop on a
    # STOPREQUESTED daemon" was not in `./gradlew --stop`'s top three).
    if item.get("do_not_retry") and do_not_retry_boost and "do-not-retry" not in m["signals"]:
        m["signals"].append("do-not-retry")
        m["score"] = float(m["score"]) + GUARD_W_DO_NOT_RETRY
        m["raw_score"] = float(m["raw_score"]) + GUARD_W_DO_NOT_RETRY
        m["stance"] = _match_stance(m["signals"])
        if "do-not-retry condition" not in m["reason"]:
            m["reason"] += "; has an explicit do-not-retry condition"
    # As strong as READ_FIRST evidence: it ranks and surfaces like it.
    m["score"] = max(float(m["score"]), float(GUARD_READ_FIRST_SCORE))
    m["raw_score"] = max(float(m["raw_score"]), float(GUARD_READ_FIRST_SCORE))
    return m


def _passes_filters(item: dict, filters: dict) -> bool:
    t = filters.get("type")
    if t and item["kind"] != t:
        return False
    st = filters.get("status")
    if st and item["status"] != st:
        return False
    tag = filters.get("tag")
    if tag and tag.lower() not in item["tags"]:
        return False
    f = filters.get("file")
    # Declared *or* mentioned: `--file X` asks "which records concern X", and a
    # record that names X only in its prose is one of them (G1 splits the two
    # tiers for scoring and for what a match may claim, not for retrieval).
    if f and not (
        _textmatch._norm_files({f}) & (item["files"] | item.get("mentioned_files", set()))
    ):
        return False
    return True


# ---- guard verdict (§11.5–11.6) -------------------------------------------- #


def _match_stance(signals) -> str:
    """`blocking` if this match opposes the action, else `advisory` (see §11 stance).

    Derived, never authored: the only structural statement of opposition the
    schema has is an attempt's "Do Not Retry Unless" section, which
    `_attempt_has_do_not_retry` already turns into the `do-not-retry` signal. To
    make a record hard-stop an action, record it as
    `crumb remember attempt --do-not-retry "…"` — a trap *documents* a hazard,
    an attempt *forbids* a repeat.
    """
    return "blocking" if "do-not-retry" in set(signals or ()) else "advisory"


def _score_band(score: float) -> str:
    """The verdict a score alone argues for, before stance caps it."""
    if score >= GUARD_PAUSE_SCORE:
        return "PAUSE"
    if score >= GUARD_READ_FIRST_SCORE:
        return "READ_FIRST"
    return "PROCEED"


def _max_verdict(*verdicts: str) -> str:
    return max(verdicts, key=lambda v: _VERDICT_RANK[v])


def _min_verdict(*verdicts: str) -> str:
    return min(verdicts, key=lambda v: _VERDICT_RANK[v])


def _only_common_evidence(m: dict) -> bool:
    """A match carried only by common tags and words (`GUARD_DF_COMMON`)."""
    sig = set(m.get("signals") or ())
    return (
        "common-tag" in sig
        and not m.get("topical")
        and not ({"tag", "file", "mention", "writes-file", "command", "open-blocker"} & sig)
    )


def _decide_verdict(top: list[dict], matched_classes: list[str], action: str = "") -> str:
    """Pick one verdict from the ranked matches + action class. Deterministic.

    Per match: a kind/specificity floor and the score band both argue for a
    verdict, and the match's *stance* caps how far either may go. The verdict is
    the highest capped result across matches.

    The band used to be computed once from the single best score in the whole
    result set and OR-ed into the verdict — so any sufficiently *relevant*
    record raised the verdict whether or not it objected to anything, and one
    well-tagged trap on a busy file PAUSEd every edit to that file (F-1).
    """
    if not top:
        return "PROCEED"

    verdicts: list[str] = ["PROCEED"]
    for m in top:
        sig = set(m["signals"])
        # A tag counts as specific only with evidence beyond the tag itself
        # (`topical`; field report 2026-10-01, issue 7: every git-tagged
        # decision floored every git command at READ_FIRST). A file, or a file
        # the action writes, always does.
        specific = bool({"file", "writes-file"} & sig) or (
            bool({"tag", "common-tag"} & sig) and m.get("topical", True)
        )
        floor = "PROCEED"
        if "do-not-retry" in sig and specific:
            floor = "PAUSE"  # a failed attempt on these files/component
        elif m["kind"] == "decision" and specific:
            floor = "READ_FIRST"  # an active decision constrains this area
        elif m["kind"] == "trap" and "command" in sig:
            # The trap names the exact command (audit F10): advisory, READ_FIRST.
            floor = "READ_FIRST"
        elif m["kind"] == "trap" and specific:
            # Keyword-only trap matches used to floor READ_FIRST here, bypassing
            # the score bands — in a store whose vocabulary overlaps the codebase
            # that made one trap fire on every edit of a session (0.1.10 field
            # test, P0-2: 13 edits, 13 READ_FIRSTs, one relevant). A trap now
            # needs the same file/tag specificity as a decision to floor the
            # verdict; a strong keyword-only trap match can still escalate
            # through the score band like everything else.
            floor = "READ_FIRST"
        elif m["kind"] == "verification" and specific:
            floor = "READ_FIRST"  # an unsettled finding on these files/component
        elif "open-blocker" in sig:
            floor = "READ_FIRST"

        stance = m.get("stance") or _match_stance(m.get("signals"))
        ceiling = GUARD_BLOCKING_CEILING if stance == "blocking" else GUARD_ADVISORY_CEILING
        band = _score_band(m["score"])
        if _only_common_evidence(m):
            # Shared vocabulary the whole store speaks (DoWhat retest of 0.5.0,
            # item 5): it may be shown, but it cannot raise a verdict.
            band = "PROCEED"
        verdicts.append(_min_verdict(_max_verdict(floor, band), ceiling))

    verdict = _max_verdict(*verdicts)

    # ASK_HUMAN escalation: a high-impact *action* colliding with memory is a
    # human's call (§15). Security/refactor never auto-escalate (keeps Fixture 2
    # on PAUSE).
    #
    # This is the axis retrieval overlap cannot see, and it used to read only the
    # keyword-derived action classes — which know "delete", "migrate", "deploy"
    # but not the irreversible shell shapes. `git push --force origin main`
    # tokenizes to nothing high-impact, so a store that cited two docs escalated
    # `rm` of them to a prompt while a force-push over shared history stayed
    # advisory. `_is_destructive` folds in the literal irreversible forms, so
    # blast radius raises the verdict whatever vocabulary the action happens to
    # use. Still gated on an existing memory collision: guard reports on the
    # store, and an action nothing in memory touches is not guard's to judge.
    if (
        _is_destructive(action, matched_classes)
        and _VERDICT_RANK[verdict] >= _VERDICT_RANK["READ_FIRST"]
    ):
        verdict = "ASK_HUMAN"

    # Applied last, so nothing above can raise a reporting command past advisory.
    if _is_read_only_action(action):
        verdict = _min_verdict(verdict, GUARD_READ_ONLY_CEILING)
    return verdict


def _recommended_action(
    verdict: str, top: list[dict], by_id: dict, root: Path, *, high_impact: str | None = None
) -> str:
    """Synthesize the next safest action from match kinds (§11.6).

    Generated by this code from structure — never copied as an imperative out of a
    record body. Verification commands come from the structured `evidence` field.
    """
    ids = ", ".join(m["id"] for m in top[:3]) if top else ""
    cmds: list[str] = []
    for m in top:
        it = by_id.get(m["id"])
        rec = it.get("record") if it else None
        if rec is not None:
            cmds.extend(cli._evidence_refs(rec, ("command", "test")))
    cmds = cli._dedup(cmds)[:3]
    verify = f" Run the recorded verification command(s): {'; '.join(cmds)}." if cmds else ""

    if verdict == "ASK_HUMAN" and high_impact and not top:
        return (
            f"High-impact action ({high_impact}) and no project memory about it. "
            "Get a human to confirm before proceeding." + verify
        )
    if verdict == "ASK_HUMAN" and high_impact:
        return (
            f"High-impact action ({high_impact}). Read {ids}, then get a human to "
            "confirm before proceeding." + verify
        )
    if verdict == "ASK_HUMAN":
        return (
            f"This is a high-impact change that collides with recorded memory ({ids}). "
            "Get a human to review before proceeding." + verify
        )
    if verdict == "PAUSE":
        # Only a `blocking` match can reach PAUSE now, so this names what that
        # actually is. It used to say "a failed attempt *or active constraint*"
        # while firing on any topically-relevant record — including a trap whose
        # own prescribed fix was the action being blocked (F-1).
        return (
            f"Stop and read these records before acting: {ids}. They record an attempt "
            "that already failed here, with an explicit do-not-retry condition — check "
            "it still applies before repeating it. Prefer the smallest possible change "
            "over a rewrite." + verify
        )
    if verdict == "READ_FIRST":
        return (
            f"Read {ids} first — they constrain this area — then make a surgical change." + verify
        )
    # PROCEED says only that memory holds no applicable warning (audit F10). It
    # is not an authorization and not a safety check of the action itself.
    if top:
        return (
            "No applicable memory warning found (PROCEED is not an authorization or a "
            f"safety check). Weak overlap only; skim {ids} if unsure." + verify
        )
    return (
        "No applicable memory warning found (PROCEED is not an authorization or a "
        "safety check). Capture a new decision or attempt record if this turns into "
        "one worth remembering."
    )


def _direct_evidence(m: dict) -> bool:
    """Is a match about this action itself, not just its vocabulary?"""
    sig = set(m.get("signals") or ())
    return bool({"file", "writes-file", "command"} & sig) or (
        bool(m.get("topical")) and bool({"tag", "title"} & sig)
    )


def _is_memory_path(path: str, root: Path) -> bool:
    """Is `path` (as an edit names it) inside this project's memory store?"""
    norm = path_policy.to_posix(path or "")
    if norm.startswith(f"{cli.MEMORY_DIRNAME}/") or f"/{cli.MEMORY_DIRNAME}/" in f"/{norm}":
        try:
            target = Path(path)
            if target.is_absolute():
                return target.resolve().is_relative_to((Path(root) / cli.MEMORY_DIRNAME).resolve())
        except (OSError, ValueError):
            return False
        return True
    return False


def guard(
    memory_dir: Path,
    root: Path,
    action: str,
    *,
    files: list[str] | None = None,
    stale_days: int = cli.STALE_AGE_DAYS,
) -> dict:
    """Guard-before-action (§11): classify -> search -> score -> single verdict.

    Active records drive the verdict; superseded/rejected/stale records and
    resolved questions are demoted to history (mention-only, never 'active').
    Bounded to GUARD_MAX_WARNINGS ranked records. Matched text is data, not command.

    Ideas are **not** in this corpus (`include_ideas` stays False). An idea is a
    proposal exempt from the evidence rule; the score band below is kind-agnostic,
    so including them would let a speculative note that names the right files raise
    a real verdict. `crumb search` sees them; the verdict never does.
    """
    primary, classes = classify_action(action)
    # Match on the command, not on a here-document's body (issue 7c), and take
    # paths only from the command and the edited file — never from the content
    # being written (issue 10: `mentions: CLAUDE.md` came from prose).
    edit = _EDIT_ACTION_RE.match((action or "").strip())
    memory_edit = bool(edit) and _is_memory_path(edit.group(2), root)
    if edit:
        # An edit is about its file, not the prose it writes (DoWhat retest of
        # 0.5.0, item 4: a handoff note that said "migrated the schema" was
        # PAUSEd by a Room migration attempt). Code identifiers in the new
        # content still count; an edit inside the store is a memory write and
        # is matched on its path alone.
        path_text = f"{edit.group(1)} {edit.group(2)}"
        content = "" if memory_edit else (edit.group(3) or "")
        query = " ".join([path_text, *_shellcmd.code_identifiers(content)])
    else:
        path_text = _shellcmd.without_crumb(action)
        query = path_text
    matches, by_id = search(
        memory_dir,
        root,
        query,
        files=files,
        stale_days=stale_days,
        min_keyword=GUARD_MIN_KEYWORD_OVERLAP,
        noise_floor=GUARD_NOISE_FLOOR,
        include_ideas=False,
        path_text=path_text,
        keyword_cap=GUARD_KEYWORD_CAP,
        writes=_shellcmd.crumb_writes(action, cli.MEMORY_DIRNAME) if not edit else None,
        command_text=_shellcmd.matching_text(action) if not edit else path_text,
    )

    active, history = [], []
    for m in matches:
        # A match the stale/branch factors pushed under the noise floor is
        # mention-only: decay still de-weights the verdict, but the
        # record is named instead of silently dropped — "38 days old" is a
        # reason to re-verify a decision, not to forget it exists.
        if m.get("suppressed"):
            history.append(m)
            continue
        # A record is live when active; an open question is live too — it must be
        # able to drive the verdict (open-blocker floor). Resolved questions and
        # superseded/rejected/stale records fall through to history (mention-only).
        # A verification carries its *outcome* in `status` (never "active"), which
        # used to drop every one of them into history — a recorded "regressed" on
        # the exact files being touched could not raise the verdict.
        # It is live when the record itself is active and the outcome still needs
        # attention, mirroring `active_verifications`.
        # A record past its `expires_at` (WM-30) is history too: it aged out,
        # like a superseded one, and is named rather than allowed to drive.
        # WM-52: a branch-scoped record written on another branch is about
        # work that is not checked out here; it is history, not a live constraint.
        elsewhere = m.get("scope") == "branch" and m.get("branch_mismatch")
        live = (
            not m.get("expired")
            and not elsewhere
            and (
                m["status"] == "active"
                or (m["kind"] == "question" and m["status"] == "open")
                or (
                    m["kind"] == "verification"
                    and m.get("lifecycle", "active") == "active"
                    and m["status"] in cli.ACTIONABLE_VERIFICATION_OUTCOMES
                )
            )
        )
        (active if live else history).append(m)

    read_only = _is_read_only_action(action)
    # Operator decision D3 (2026-10-01): a short, literal list of high-impact
    # actions asks a human even when no record is about them. Without it, the
    # only thing that ever made `git push --force origin main` ASK_HUMAN was
    # unrelated records that happened to share the word "git".
    high_impact = _shellcmd.high_impact(action) if not edit else None
    if high_impact:
        # The verdict is the action's, so a record is cited only with direct
        # evidence that it is about *this* action: a file it names or writes,
        # the exact command, or a topical match. A real `crumb migrate` cited a
        # Gradle rate-limit attempt and a Room migration test (DoWhat retest of
        # 0.5.0, item 3); the rest is "no project memory about it".
        demoted = [m for m in active if not _direct_evidence(m)]
        active = [m for m in active if _direct_evidence(m)]
        history = history + demoted
    if read_only or memory_edit:
        # An action that changes nothing — or a memory write — cannot be what a
        # record objects to (item 6: `git status` showed a git attempt as
        # `[objects]`). The verdict was already capped; now the stance agrees.
        for m in active:
            m["stance"] = "advisory"
    top = active[:GUARD_MAX_WARNINGS]
    verdict = _decide_verdict(top, classes, action)
    if memory_edit:
        verdict = _min_verdict(verdict, GUARD_READ_ONLY_CEILING)
    if high_impact:
        verdict = "ASK_HUMAN"

    # Staleness is computed so a stale/wrong-branch handoff surfaces
    # in guard exactly as it does in resume (Fixture 4), regardless of verdict.
    # Lenient read: guard runs on the PreToolUse path and must not die on a bad
    # byte.
    from breadcrumbs import handoffs as _handoffs

    handoff_text, _problem, handoff_path = _handoffs.read_text(memory_dir, root)
    # `risks_only`: guard is called once per edit, and the full staleness view
    # repeated the same store-wide facts verbatim on every call (P0-4). Only
    # abnormal states — cold handoff, detached HEAD, branch mismatch — belong
    # on the per-action path; the rest lives in resume/doctor/audit.
    # The risks-only view reads no records (they feed only the full view), so
    # none are loaded for it: that re-read every decision on each firing (#6).
    staleness = _packet.compute_staleness(
        root,
        cli.parse_handoff_meta(handoff_text),
        [],
        [],
        [],
        stale_days,
        risks_only=True,
        memory_dir=memory_dir,
        handoff_path=handoff_path,
    )[:GUARD_MAX_WARNINGS]

    result = {
        "verdict": verdict,
        "action": action,
        "action_class": primary,
        "action_classes": classes,
        # Blast radius, scored independently of retrieval. Overlap answers "is a
        # record about this action"; it has never answered "how much damage does
        # this action do", and the two were conflated: a verdict driven entirely
        # by how much of the repo the store happens to cite decided whether the
        # human got interrupted. They are separate axes and are now reported as
        # such — `_hook_guard` gates the permission prompt on this one and the
        # surfaced context on the other.
        "destructive": _is_destructive(action, classes),
        # The other end of the same axis: an action that cannot change anything
        # caps at READ_FIRST however strong the retrieval overlap (G2). Reported
        # so a caller can see *why* a loud-looking match did not raise a verdict.
        "read_only": read_only,
        "matches": top,
        "history": history[:GUARD_MAX_WARNINGS],
        "staleness": staleness,
        # NOT `next_action` — that key is the resume packet's *recorded* Next
        # Action, and one name for two unrelated things read as one thing.
        "high_impact": high_impact,
        "recommended_action": _recommended_action(
            verdict, top, by_id, root, high_impact=high_impact
        ),
        "thresholds": {
            "noise_floor": GUARD_NOISE_FLOOR,
            "read_first_score": GUARD_READ_FIRST_SCORE,
            "pause_score": GUARD_PAUSE_SCORE,
            "min_keyword_overlap": GUARD_MIN_KEYWORD_OVERLAP,
            "max_warnings": GUARD_MAX_WARNINGS,
        },
    }
    # A store this build does not fully understand (audit WP21): the verdict
    # is still given, with the warning that it may misread the records.
    from breadcrumbs import compat as _compat

    note = _compat.warning(memory_dir)
    if note:
        result["compatibility"] = note
    return result
