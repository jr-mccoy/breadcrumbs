"""breadcrumbs — the shared matching vocabulary: tokens, stems and paths.

Search, guard, the packet's task relevance, the guard pre-filter and the
search index all compare text the same way, so they share one tokenizer
(`_tokenize`), one stemmer (`_stem`, folding each store's aliases through
`store_aliases`), one stop-word list and one reading of path-shaped tokens
(`_paths_from_text`, `_norm_files`). Both sides of every comparison must fold
through these, or a record and a query that say the same thing never meet.

The alias table is per-thread state, scoped by `store_aliases(memory_dir)`.

Moved out of `cli.py` (health review 2.1).
"""

from __future__ import annotations

import contextlib
import functools
import re
import threading
from pathlib import Path

from breadcrumbs import cli


# Generic words that carry no domain signal. A shared stop-word never counts
# toward keyword overlap (the core of the false-positive control, Fixture 3).
# Action-class verbs that DO carry signal (delete/remove/migrate/deploy/refactor/
# rewrite/upgrade…) are intentionally absent.
# English function words: never evidence of anything. Split out of
# GUARD_STOPWORDS because the short-query title rule (`_score_item`) must keep
# the generic *development* words ("test" in `npm test`) that the keyword
# overlap ignores.
_FUNCTION_WORDS = frozenset(
    """
    the a an and or but to of in on for with at by from as is are be this that it
    its if then else so not no do does did we you i my our your their them they he
    she was were will would should can could may might must have has had about into
    over under out up down off than too very just also via per after before when
    while where which who what how here there all any some more most less few each
    """.split()
)

GUARD_STOPWORDS = _FUNCTION_WORDS | frozenset(
    """
    add added adding update updated updating change changed changing fix fixed
    fixing new old make made making run running set get got use used using create
    created creating build built work working file files code project thing things
    stuff need needs want wants now today please let lets go going into onto
    src lib test tests spec specs index main app ts js tsx jsx py md json yml yaml
    txt cfg ini case feature support handle handling
    why fail fails failed failing failure error errors broken wrong issue issues
    problem problems
    """.split()
)
# The last line above (field report 2026-10-01, issue 8): the words a question
# about *any* failure uses. "why is my robolectric test failing" shared `why`
# and `fail` with every attempt record, which is what let five unrelated
# attempts outrank the one trap about the actual error.

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
# Candidate path tokens in free text. This regex only *finds* things shaped like
# a path; `_is_path_token` decides whether each one is one. Keeping the two
# separate is the point — the old code treated the regex's own output as the
# answer, and a regex reading "contains a dot or a slash" says yes to most of a
# paragraph of technical prose (G1).
_FILE_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_][\w./\-]*\.[A-Za-z0-9]+|[A-Za-z0-9_./\-]+/[A-Za-z0-9_./\-]+"
)

# Extensions that make a dotted token a filename rather than an attribute access.
# Not exhaustive and not meant to be: an unknown extension with no slash simply
# does not qualify, which is the safe direction — an over-broad file signal is
# the strongest wrong answer guard can give (GUARD_W_FILE is its heaviest
# weight), and a missed one costs a keyword match instead.
GUARD_PATH_EXTENSIONS = frozenset(
    """
    py pyi pyx ipynb md markdown mdx rst txt adoc
    json yml yaml toml ini cfg conf properties env lock sum mod
    js jsx mjs cjs ts tsx vue svelte astro css scss sass less html htm
    java kt kts gradle groovy scala clj cljs
    go rs rb php swift m mm c h cc cpp hpp cs fs fsx dart zig nim ex exs erl
    sh bash zsh fish ps1 bat cmd mk cmake
    sql graphql gql proto tf tfvars tfstate hcl
    xml plist pro csv tsv svg png jpg jpeg gif ico webp pdf
    r jl lua pl pm rake gemspec podspec xcconfig entitlements
    """.split()
)

# `0.47`, `8.13.2`, `v0.1.5` — a version, not a path, however many dots it has.
_VERSION_TOKEN_RE = re.compile(r"^v?\d+(\.\d+)+$")


_SYSTEM_PATH_RE = re.compile(r"^(?:\.\./|~)?/?(?:dev|proc|sys)/")
# Slash-joined words that read as prose, not as a directory and a file.
_PROSE_SLASH_PAIRS = frozenset(
    """
    and/or either/or read/write yes/no input/output stdin/stdout stdout/stderr
    ci/cd on/off true/false client/server i/o r/w pass/fail before/after he/she
    his/her s/he am/pm win/loss success/failure open/close start/stop get/set
    push/pull load/store encode/decode request/response send/receive
    """.split()
)


def _is_path_token(token: str) -> bool:
    """Is `token` really a file path, as opposed to prose that looks like one?

    The prefilter of a 310-session field store held 439 "paths", of which 89
    existed: the rest were version numbers (`8.13.2`), units (`10.dp`, `AM/PM`,
    `0xDD/255`), CLI flag lists (`--title/--set`) and Python attribute access
    (`json.load`, `io.open`). That mattered because `same file(s)` is guard's
    single strongest relevance signal, so a command that merely read a JSON file
    drew a PAUSE from a screenshot-testing trap on the strength of `json.load`.
    An agent that learns "same file(s) is noise" has lost the only precise signal
    guard has, and will miss the true positive when it arrives.

    The test is structural, not lexical: a known file extension, or a real path
    shape. Deliberately *not* "does it exist on disk" — a record citing a file
    that was since deleted or renamed is often exactly the trap worth raising,
    and a store must mean the same thing in every checkout that reads it.
    """
    token = (token or "").strip()
    if len(token) < 2 or token.startswith("-") or _VERSION_TOKEN_RE.match(token):
        return False
    # Device files and pseudo-filesystems are not project files: `2>/dev/null`
    # produced "mentions: null" (field report 2026-10-01, issue 10).
    if _SYSTEM_PATH_RE.match(token):
        return False
    if token.lower() in _PROSE_SLASH_PAIRS:
        return False  # `and/or`, `read/write`, `ci/cd`
    if token.startswith("./") and "/" not in token[2:] and "." not in token[2:]:
        # `./gradlew` is a command being run, not a file the action is about;
        # as a path it gave every record mentioning `./gradlew assembleDebug`
        # a mention signal against `./gradlew --stop` (issue 8).
        return False
    basename = token.rsplit("/", 1)[-1]
    extension = basename.rsplit(".", 1)[-1].lower() if "." in basename else ""
    if extension and extension in GUARD_PATH_EXTENSIONS:
        return True
    if "/" not in token:
        # `json.load`, `f.get`, `tests.test`, `10.dp` — a dot alone proves nothing.
        return False
    segments = [seg for seg in token.split("/") if seg not in ("", ".", "..")]
    if not segments:
        return False
    if not any(c.islower() for c in token):
        return False  # `AM/PM`, `TODO/FIXME`
    for seg in segments:
        if seg.isdigit() or _VERSION_TOKEN_RE.match(seg):
            return False  # `10/15`, `362/LF`, `0xDD/255`, `v0.1.5/v0.1.6`
    return True


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens (alnum + underscore), single chars dropped."""
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) > 1}


# Morphology folding for guard/search matching. Exact-token intersection missed
# the main case the tool exists for: a *different* session phrases the same
# intent differently ("reconciliation" vs the recorded "reconciler",
# "batching" vs "batched"), and the record stayed invisible. This is a small
# deterministic suffix-stripper, not Porter: every rule is a plain strip (or the
# ies/ied→y rewrite), applied longest-first to a fixpoint so the whole
# morphological family lands on one stem. The fixpoint also makes stemming
# idempotent, which is what lets `_prefilter_trap_hit` re-stem tokens read from
# an older on-disk prefilter without diverging from freshly-written ones.
# Matching runs on stems on BOTH sides (query and record), so a miss is always
# symmetric; `keyword_overlap` in --json output therefore contains stems.
_STEM_REPLACEMENTS = (("ies", "y"), ("ied", "y"))
_STEM_SUFFIXES = tuple(
    sorted(
        (
            "ations",
            "ements",
            "ments",
            "ances",
            "ences",
            "ities",
            "ation",
            "ement",
            "ating",
            "ance",
            "ence",
            "ancy",
            "ency",
            "ings",
            "ated",
            "ates",
            "ment",
            "ions",
            "ing",
            "ate",
            "ity",
            "ion",
            "ers",
            "ors",
            "ed",
            "er",
            "or",
            "es",
            "ly",
            "s",
            "e",
            "i",
        ),
        key=len,
        reverse=True,
    )
)
_STEM_MIN_RESIDUE = 3

# Ubiquitous dev abbreviations the stemmer cannot derive. Keys are stems (post
# suffix-strip), values are the short form people actually type. Deliberately
# tiny: every entry here is a curated equivalence, not a synonym engine.
GUARD_STEM_ALIASES = {
    "authentic": "auth",
    "authoriz": "auth",
    "configur": "config",
    "repository": "repo",
    "databas": "db",
}


# ---- store-local aliases (WM-24) ------------------------------------------- #
#
# `GUARD_STEM_ALIASES` is five entries, and it is the tool's vocabulary, not the
# project's. Every codebase has its own: a service nickname, a module and its
# acronym, the two names a team uses for one thing. `.project-memory/aliases.txt`
# lets a store add those without a code change — one group per line, words that
# fold to the first word's stem:
#
#     auth authn authz login
#     billing invoicing ledger
#
# It is committed (a teammate's clone must stem the same way, or the same query
# returns different results on two machines) and folded into `_inputs_hash`
# (it changes what the guard prefilter contains).
#
# `_stem` is a pure function called from everywhere, with no store in scope, so
# the table is state that the store-scoped entry points *activate*
# (`_candidate_items`, the prefilter builder and reader). Activation is keyed on
# the file's path, mtime and size, so it is one `stat` when nothing changed — and
# a store with no file resets the table.
#
# The table is per thread (audit WP16): an MCP server answering two stores from
# worker threads, or two service contexts, never sees the other's aliases.
# `store_aliases(memory_dir)` scopes an activation and restores the previous
# table afterwards.
ALIASES_FILENAME = "aliases.txt"
_ALIASES = threading.local()


def active_store_aliases() -> dict[str, str]:
    """The alias table `_stem` applies in this thread (empty when none)."""
    return getattr(_ALIASES, "table", None) or {}


def parse_store_aliases(text: str) -> tuple[dict[str, str], list[dict]]:
    """Alias groups -> `{member_stem: canonical_stem}`, plus per-line problems.

    Problems are reported, never raised: a malformed alias file must degrade to
    "fewer aliases", not to a search that crashes. A word already claimed by an
    earlier group keeps its first meaning — deterministic, and it means adding a
    line can never silently change what an older line did.
    """
    mapping: dict[str, str] = {}
    problems: list[dict] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        words = [w for w in _TOKEN_RE.findall(line.lower()) if len(w) > 1]
        if len(words) < 2:
            problems.append({"line": lineno, "problem": "a group needs at least two words"})
            continue
        canonical = _base_stem(words[0])
        mapping.setdefault(canonical, canonical)
        for word in words[1:]:
            stem = _base_stem(word)
            if stem in mapping and mapping[stem] != canonical:
                problems.append(
                    {"line": lineno, "problem": f"{word!r} is already in an earlier group"}
                )
                continue
            mapping[stem] = canonical
    # Resolve chains to a fixpoint so `_stem` stays idempotent: the guard
    # prefilter re-stems tokens it wrote earlier, and `stem(stem(x)) != stem(x)`
    # would make a fresh index and a stale one disagree.
    for key in list(mapping):
        seen = {key}
        target = mapping[key]
        while target in mapping and mapping[target] != target and target not in seen:
            seen.add(target)
            target = mapping[target]
        mapping[key] = target
    return {k: v for k, v in mapping.items() if k != v}, problems


def activate_store_aliases(memory_dir: Path) -> None:
    """Make `_stem` use this store's aliases in this thread. Cheap when nothing changed."""
    path = Path(memory_dir) / ALIASES_FILENAME
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        key = None
    if key == getattr(_ALIASES, "key", None) and hasattr(_ALIASES, "table"):
        return
    _ALIASES.key = key
    if key is None:
        _ALIASES.table = {}
        return
    try:
        _ALIASES.table = parse_store_aliases(cli.read_text_lenient(path)[0])[0]
    except Exception:  # pragma: no cover - aliases must never break a search
        _ALIASES.table = {}


@contextlib.contextmanager
def store_aliases(memory_dir: Path):
    """Activate `memory_dir`'s aliases for the block, then restore the previous table."""
    saved = (getattr(_ALIASES, "table", None), getattr(_ALIASES, "key", None))
    activate_store_aliases(memory_dir)
    try:
        yield
    finally:
        _ALIASES.table, _ALIASES.key = saved


def _stem(token: str) -> str:
    """Fold a token to its stem, then apply the active store's aliases."""
    stem = _base_stem(token)
    table = getattr(_ALIASES, "table", None)
    return table.get(stem, stem) if table else stem


@functools.lru_cache(maxsize=65536)
def _base_stem(token: str) -> str:
    """Fold a token to its morphological stem (deterministic, idempotent).

    A pure function of the token and module constants, so memoizing it is
    exact; a 1,000-record publication stemmed the same words 84,000 times
    (audit WP15). Store aliases are applied after it, in `_stem`.
    """
    word = token
    for _ in range(4):  # fixpoint: families collapse in <=4 strips
        if word.isdigit():
            break
        # Alias keys terminate the loop: they are already canonical family
        # names, and letting the strip rules keep going would walk past them
        # ("databas" -> "databa", missing the db alias entirely).
        if word in GUARD_STEM_ALIASES:
            break
        changed = False
        for suf, repl in _STEM_REPLACEMENTS:
            if word.endswith(suf) and len(word) - len(suf) >= _STEM_MIN_RESIDUE:
                word = word[: -len(suf)] + repl
                changed = True
                break
        if not changed:
            for suf in _STEM_SUFFIXES:
                if not word.endswith(suf) or len(word) - len(suf) < _STEM_MIN_RESIDUE:
                    continue
                # never strip the second s of an "ss" ending (class, address)
                if suf == "s" and word.endswith("ss"):
                    continue
                word = word[: -len(suf)]
                changed = True
                break
        if not changed:
            break
    return GUARD_STEM_ALIASES.get(word, word)


# Stopwords are filtered on stems so inflections a raw list misses ("changes"
# when the list has "change changed changing") drop out too.
_GUARD_STOPWORD_STEMS = frozenset(GUARD_STOPWORDS | {_stem(w) for w in GUARD_STOPWORDS})


def _specific(text: str) -> set[str]:
    """Meaningful stems only: tokenized words, stemmed, minus stop-word stems."""
    out = set()
    for t in _tokenize(text):
        s = _stem(t)
        if len(s) > 1 and s not in _GUARD_STOPWORD_STEMS and t not in GUARD_STOPWORDS:
            out.add(s)
    return out


def _paths_from_text(text: str) -> set[str]:
    """File paths found in free text — candidates that pass `_is_path_token`.

    A token that is part of a URL (`https://host/a`) is not a path: its last
    segment used to become a file name of its own (issue 10).
    """
    text = text or ""
    out = set()
    for m in _FILE_TOKEN_RE.finditer(text):
        token = m.group(0)
        before = text[max(0, m.start() - 3) : m.start()]
        if before.endswith(":") or before.endswith(":/") or token.startswith("//"):
            continue
        if _is_path_token(token):
            out.add(token)
    return out


def _norm_files(paths) -> set[str]:
    """Normalize a set of paths to {full path, basename} for overlap matching."""
    out: set[str] = set()
    for p in paths or ():
        p = str(p).strip().strip("`").strip().rstrip(".,;:")
        if not p:
            continue
        out.add(p)
        base = p.rsplit("/", 1)[-1]
        if base:
            # A trailing-slash directory path ("src/auth/") has an empty
            # basename; adding "" would make every directory path overlap.
            out.add(base)
    return out
