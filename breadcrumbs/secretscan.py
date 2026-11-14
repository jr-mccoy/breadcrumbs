"""breadcrumbs — secret and instruction-like text in committed memory.

`scan_secrets` looks for credential-shaped strings (named patterns plus a
high-entropy heuristic that leaves paths and identifiers alone) in the files a
store commits, minus `.crumbignore`; a hit blocks a memory commit.
`scan_instruction_like` flags text that reads like an instruction to an agent
("ignore all previous…") for a person to review; nothing acts on it.

Moved out of `cli.py` (health review 2.1). `crumb scan-secrets`, `crumb audit`
and MCP call `scan_secrets`; the transcript miner and the inbox check text with
`secret_pattern_hits` before keeping it. The patterns compile on first use
(`cli._LazyPattern`), which keeps them off the hook's startup path.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from breadcrumbs import cli
from breadcrumbs import path_policy
from breadcrumbs import audit as _audit


# Directories under .project-memory/ the secret scan skips: private/ is gitignored
# local context and index/ a gitignored, disposable accelerator. generated/ is
# scanned (DoWhat retest of 0.5.0, item 9): it is committed, and its projections
# copy record text, so a secret there would be published like any other.
_SECRET_SKIP_DIRS = {"private", "index"}
# Files under a skipped directory that the store's .gitignore still commits.
_SECRET_SCAN_KEEP = {("index", "README.md")}

# Common secret SHAPES. Deliberately conservative: better to miss
# an exotic secret than to flag every git sha. The covered set is this tuple; the
# three deliberate gaps (bare hex only in a labeled context, path/CamelCase tokens
# allowlisted, URL credentials floored at 6 characters and placeholder-aware) are
# written up in `docs/security.md` §2 and pinned by `tests/test_secrets.py`.
# A credential label: one of these words, alone or inside an environment-
# variable name (`DB_PASSWORD`, `GITHUB_TOKEN`, `SECRET_KEY_BASE`). A word
# boundary before the label missed every `PREFIX_` form, because `_` is a word
# character (review 2026-11-13, §2.3). Case-insensitive, and only the label is.
_SECRET_LABEL = (
    r"(?<![A-Za-z0-9])(?i:(?:[a-z0-9]+_)*"
    r"(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?key|access[_-]?token|auth[_-]?token|"
    r"refresh[_-]?token|id[_-]?token|session[_-]?token|private[_-]?key|"
    r"signing[_-]?key|client[_-]?secret|password|passwd|pwd|token)"
    r"(?:_[a-z0-9]+)*)"
)
# The value after it. Unquoted: 16+ characters of a key alphabet, with a letter
# and either a digit or both cases, so a phrase (`token: approx_tokens_per_x`,
# `private_key: config/keys/deploy_private.pem`) or a number is not a secret.
# Quoted: 12+ non-space characters with a letter and a digit, punctuation
# allowed (`"P@ssw0rd!2024"`).
_KEY_CHAR = r"[A-Za-z0-9/+_\-]"
_SECRET_VALUE = (
    r"(?:"
    rf"(?=[^\s'\"]*[A-Za-z])(?=[^\s'\"]*[0-9]|{_KEY_CHAR}*[a-z]{_KEY_CHAR}*[A-Z]|"
    rf"{_KEY_CHAR}*[A-Z]{_KEY_CHAR}*[a-z]){_KEY_CHAR}{{16,}}"
    r"|(['\"])(?=[^'\"\s]*[A-Za-z])(?=[^'\"\s]*[0-9])[^'\"\s]{12,}\1"
    r")"
)

SECRET_PATTERNS: tuple[tuple[str, "cli._LazyPattern"], ...] = (
    # AKIA long-term, ASIA temporary (STS) access key ids.
    ("aws-access-key-id", cli._LazyPattern(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    # The 40-character secret beside it has no prefix; its label is the shape.
    (
        "aws-secret-access-key",
        cli._LazyPattern(
            r"(?i:aws_?secret_?access_?key)['\"]?\s*[:=]\s*['\"]?"
            r"[A-Za-z0-9/+]{40}(?![A-Za-z0-9/+])"
        ),
    ),
    ("gitlab-token", cli._LazyPattern(r"\bglpat-[A-Za-z0-9_\-]{20,}")),
    ("npm-token", cli._LazyPattern(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("huggingface-token", cli._LazyPattern(r"\bhf_[A-Za-z0-9]{30,}\b")),
    ("webhook-signing-secret", cli._LazyPattern(r"\bwhsec_[A-Za-z0-9+/=]{24,}")),
    ("github-token", cli._LazyPattern(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github-fine-grained-pat", cli._LazyPattern(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack-token", cli._LazyPattern(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", cli._LazyPattern(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    # sk-… covers both the legacy `sk-<base62>` and modern `sk-proj-<base62>`
    # OpenAI shapes (the hyphen in `proj-` broke the old alnum-only pattern).
    ("openai-style-key", cli._LazyPattern(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    # Stripe-style secret/restricted/publishable keys: sk_live_…, rk_test_…, etc.
    ("stripe-style-key", cli._LazyPattern(r"\b[srp]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("jwt", cli._LazyPattern(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("pem-private-key", cli._LazyPattern(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("bearer-token", cli._LazyPattern(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    (
        "secret-assignment",
        cli._LazyPattern(
            _SECRET_LABEL
            # allow a closing quote on the label so JSON keys ("private_key":)
            # match too — the scan now covers .json files
            + r"['\"]?\s*[:=]\s*"
            + _SECRET_VALUE
        ),
    ),
    # A bare lowercase-hex token is shape-identical to the SHA-1/256 digests
    # (commit refs, evidence refs, inputs_hash) that fill project memory, so the
    # standalone high-entropy heuristic deliberately can't flag it (see
    # `_looks_high_entropy`). We close the leak only in a *labeled* credential
    # context, where a standalone sha is unlikely — covering the labels the
    # `secret-assignment` keyword list above misses: bare `token:`,
    # `Authorization:` (no "Bearer", so `bearer-token` skips it), and
    # `X-…-Key:` / `X-…-Token:` HTTP headers. No label ⇒ still no flag.
    # Credentials embedded in a connection string — `postgres://app:pw@host/db`,
    # `mongodb+srv://…`, `redis://:pw@…`, `https://user:token@host/repo.git`. The
    # keyword list above cannot see these: the password follows a bare `:` inside
    # a URL, with no `password=` label anywhere. Conservative on purpose:
    # a username with no password (`https://user@host`) is not a secret and does
    # not match; `$VAR` / `${VAR}` / `%VAR%` / `<placeholder>` interpolations and
    # the obvious doc placeholders are excluded; and the 6-character floor drops
    # well-known defaults like amqp's `guest:guest`.
    (
        "url-embedded-credentials",
        cli._LazyPattern(
            r"(?i)\b[a-z][a-z0-9+.\-]*://[^/\s:@]*:"
            r"(?!(?:password|passwd|pass|secret|token|changeme|placeholder|redacted|"
            r"example|user|username|test|xxx+|\*+)@)"
            r"(?![$%<{])"
            r"[^/\s:@]{6,}@"
        ),
    ),
    (
        "labeled-hex-secret",
        cli._LazyPattern(
            r"(?i)\b(?:token|authorization|x-[a-z0-9-]*-(?:key|token))\b\s*[:=]\s*"
            r"['\"]?[0-9a-fA-F]{32,}\b"
        ),
    ),
)

# Standalone high-entropy tokens (base64-ish). The charset excludes `_`/`-`, so
# record ids like `dec_20260605_markdown-source-of-truth` never form a long run,
# and the mixed-class + entropy floor below skips lowercase-only ids and hex shas.
_HIGH_ENTROPY_TOKEN = cli._LazyPattern(r"\b[A-Za-z0-9+/=]{32,}\b")

# Override-style phrasing audit flags for human review. A *flag*,
# never a gate — same content-as-data posture as guard (Fixture 7).
# A short run of qualifiers between the verb and its object, so natural phrasings
# ("ignore failing tests", "ignore all prior instructions", "skip the flaky
# suite's checks") are caught, not just the bare determiner forms.
_IL_QUALIFIERS = r"(?:(?:all|the|any|every|these|those|prior|previous|earlier|existing|above|failing|flaky|broken|remaining|other)\s+){0,3}"

INSTRUCTION_LIKE_PATTERNS: tuple["cli._LazyPattern", ...] = (
    cli._LazyPattern(
        r"(?i)\bignore\s+"
        + _IL_QUALIFIERS
        + r"(?:tests?|instructions?|previous|above|rules?|warnings?|memory|checks?|errors?|failures?)\b"
    ),
    cli._LazyPattern(
        r"(?i)\bskip\s+"
        + _IL_QUALIFIERS
        + r"(?:tests?|validation|verification|checks?|review|ci)\b"
    ),
    cli._LazyPattern(
        r"(?i)\bdisable\s+"
        + _IL_QUALIFIERS
        + r"(?:tests?|checks?|validation|guard|safety|linter?|ci)\b"
    ),
    # Imperative "never run X" only: an auxiliary right before it ("has never
    # run", "was never run") is a factual claim about history, not an
    # instruction — the field test's audit fired 7 warnings, all on sentences
    # like "E2E has never run in production" (P2-11). Python lookbehinds are
    # fixed-width, hence one per auxiliary.
    cli._LazyPattern(
        r"(?i)(?<!\bis\s)(?<!\bare\s)(?<!\bwas\s)(?<!\bhas\s)(?<!\bhad\s)"
        r"(?<!\bwere\s)(?<!\bbeen\s)(?<!\bhave\s)"
        r"\b(?:never|always)\s+run\b"
    ),
    cli._LazyPattern(r"(?i)\bdo\s+not\s+run\b"),
    cli._LazyPattern(r"(?i)\b(?:always|never)\s+(?:force[- ]?push|skip|disable|ignore|bypass)\b"),
    cli._LazyPattern(
        r"(?i)\bbypass\s+"
        + _IL_QUALIFIERS
        + r"(?:tests?|checks?|(?:code\s+)?review|validation|guard|ci)\b"
    ),
)


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: dict[str, int] = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


# A path/identifier segment: a run of letters and digits with no separators.
_IDENT_SEGMENT = re.compile(r"^[A-Za-z0-9]+$")
# A pronounceable "word": a letter followed by 3+ lowercase letters (e.g. the
# CamelCase subwords Migration/Database/Test). Random base64 yields at most a stray
# short run, never enough to cover half the segment.
_WORD_RE = re.compile(r"[A-Za-z][a-z]{3,}")


def _segment_is_wordy(seg: str) -> bool:
    """True if CamelCase words cover most of the segment (identifier, not a blob).

    Requires vowel-bearing words to span ≥half the segment (and ≥6 chars), so a real
    identifier (Database/Migration/Helper…) qualifies while a random base64 run with
    an incidental 4-letter sequence does not.
    """
    covered = sum(len(w) for w in _WORD_RE.findall(seg) if any(c in "aeiouAEIOU" for c in w))
    return covered >= 6 and covered * 2 >= len(seg)


# A Firebase Realtime Database push id: 20 characters of base64url, timestamp-
# prefixed and therefore lexicographically sortable — a public, structurally
# recognizable document key, which is exactly what a real secret is not. Split on
# `-`, the leading dash goes with the separator, so both lengths are accepted.
# These are the ids that appear in a record citing a concrete production path,
# which is to say in the most useful records a store has (R5).
_PUSH_ID_SEGMENT_RE = cli._LazyPattern(r"^[A-Za-z0-9]{19,20}$")


def _is_push_id_segment(seg: str) -> bool:
    return bool(_PUSH_ID_SEGMENT_RE.match(seg))


def _looks_like_path_or_identifier(tok: str) -> bool:
    """True for path- or dotted-identifier-shaped tokens that only *look* random.

    Long CamelCase identifiers like ``DatabaseMigrationHelperV2Factory`` and paths
    like ``app/src/MigrationV14ToV15Test`` clear the mixed-class + entropy bar yet
    are obviously not secrets. The discriminator is deliberately narrow
    so it cannot launder a real secret: base64 padding/charset (`+`, `=`) disqualifies
    outright; every segment must be alphanumeric; and any segment long enough to be a
    blob (≥12 chars) must read as CamelCase words, with at least one wordy segment
    overall. A bare random run has no words and stays flagged.
    """
    if "+" in tok or "=" in tok:
        return False  # base64-specific characters never occur in paths/identifiers
    segments = [s for s in re.split(r"[/._-]", tok) if s]
    if not segments:
        return False
    has_word = False
    for seg in segments:
        if not _IDENT_SEGMENT.match(seg):
            return False
        if _segment_is_wordy(seg):
            has_word = True
        elif len(seg) >= 12 and not _is_push_id_segment(seg):
            return False  # a long, word-free segment is a blob, not a path component
    return has_word


def _looks_high_entropy(tok: str) -> bool:
    """True only for mixed-class, genuinely-random-looking tokens.

    Requires lower + upper + digit (so hex shas and lowercase ids never qualify) and
    a real entropy floor. Conservative by design — misses some secrets, flags ~no ids.
    Path- and identifier-shaped tokens are allowlisted without lowering
    the entropy floor, so real secrets are unaffected.

    A bare lowercase-hex token (a 32–64 char hex API key) is intentionally NOT
    caught here: it is indistinguishable from the git shas / inputs_hash digests
    that fill memory. Such tokens are flagged only in a labeled credential
    context by the `labeled-hex-secret` pattern above (issue #5).
    """
    if not (
        any(c.islower() for c in tok)
        and any(c.isupper() for c in tok)
        and any(c.isdigit() for c in tok)
    ):
        return False
    if _looks_like_path_or_identifier(tok):
        return False
    return _shannon_entropy(tok) >= 3.5


def _iter_committed_memory_files(memory_dir: Path):
    """Yield every file the store commits: all of it but private/ and index/,
    and index/README.md, which the store's .gitignore keeps.

    Chosen by place, not by extension. A list of text suffixes missed what git
    commits all the same: `note.MD`, a `.log`, a `.jsonl`, a name with no
    suffix, the `.tmp` copy an interrupted write leaves (review 2026-11-13,
    §2.3). A link is yielded too, so the read refuses it as unscannable.
    """
    memory_dir = Path(memory_dir)
    for p in sorted(memory_dir.rglob("*")):
        rel_parts = p.relative_to(memory_dir).parts
        if (
            rel_parts
            and rel_parts[0] in _SECRET_SKIP_DIRS
            and tuple(rel_parts) not in _SECRET_SCAN_KEEP
        ):
            continue
        if p.is_symlink() or p.is_file():
            yield p


CRUMBIGNORE_FILENAME = ".crumbignore"

# `high-entropy-string` is a heuristic with no structure behind it, and it gated
# every commit of the memory store. A project that has decided a given shape is
# not a secret should be able to say so once, rather than re-deciding it — and
# hand-overriding a gate on every commit is how a gate stops being read at all.
SECRET_WARNING_PATTERNS = frozenset({"high-entropy-string", "crumbignore-pattern"})


def load_crumbignore(memory_dir: Path) -> list:
    """Patterns from `.project-memory/.crumbignore` (see `crumbignore_rules`)."""
    return crumbignore_rules(memory_dir)[0]


def crumbignore_rules(memory_dir: Path) -> tuple[list, list[dict]]:
    """`(patterns, problems)` from `.project-memory/.crumbignore`.

    One pattern per line; a line *starting* with `#` is a comment. Each line is
    used as a regex, or as a literal substring if it does not compile. A hit
    whose *line text* matches any pattern is dropped by `scan_secrets` — the
    project has said, in a file its reviewers can see, that this shape is not a
    secret here.

    `#` used to start a comment anywhere, so `C# sample fixtures` became the
    pattern `C` and exempted every line with a capital C. And a pattern that
    matches the empty string (`FIXTURE|`) matches every line, which switched
    the scan off while it still printed OK. Such a pattern is not used; it is
    returned in `problems` as `{line, detail}` (review 2026-11-13, §2.3).
    """
    path = Path(memory_dir) / CRUMBIGNORE_FILENAME
    if not path.is_file():
        return [], []
    text, _problem = cli.read_text_lenient(path)
    patterns, problems = [], []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            pat = re.compile(line)
        except re.error:
            pat = re.compile(re.escape(line))
        if pat.search(""):
            problems.append(
                {
                    "line": n,
                    "detail": "this pattern matches every line, so it is not used; "
                    "make it name what it exempts",
                }
            )
            continue
        patterns.append(pat)
    return patterns, problems


def _secret_severity(pattern: str) -> str:
    """`warning` for the heuristics, `blocking` for shapes with real structure."""
    return _audit.AUDIT_WARN if pattern in SECRET_WARNING_PATTERNS else _audit.AUDIT_FAIL


def secret_pattern_hits(text: str, *, blocking_only: bool = True) -> list[str]:
    """Names of the secret shapes `text` matches — never the matched value.

    Factored out of `scan_secrets` so a caller that holds a string rather than a
    file can use the same table. The transcript miner is that caller: everything
    it reads is tool output and user prose, which is exactly where a credential
    turns up by accident, and a second private copy of these patterns would
    drift from this one the first time either moved.

    `blocking_only` (the default) consults only the structured shapes. The
    high-entropy heuristic is deliberately excluded: `scan-secrets` downgraded it
    to a warning because it has no structure behind it and punished the records
    that cite a concrete production path, and a caller using this to decide
    whether to *drop* content needs the stricter, better-evidenced half.
    """
    out = []
    for name, pat in SECRET_PATTERNS:
        if blocking_only and _secret_severity(name) != _audit.AUDIT_FAIL:
            continue
        if pat.search(text or ""):
            out.append(name)
    return out


def scan_secrets(memory_dir: Path, *, stats: dict | None = None) -> list[dict]:
    """Scan committed memory for secret-like strings.

    Each hit is {pattern, path, line} — the pattern NAME and location, never the
    matched value. Skips private/ and index/. This must run before any
    "commit memory" recommendation (§2.6, §15).

    A file that cannot be read cleanly yields a blocking `unscannable-file` hit
    rather than being skipped: silently exempting it made the whole "secrets are
    blocking" posture void for that file. Undecodable bytes are
    replaced and the readable remainder is still scanned, so a real secret next
    to a bad byte is still found. A file holding NUL bytes (a binary, a UTF-16
    file) is unscannable as text, and blocking for the same reason.

    `stats`, when given, receives `suppressed`: lines with a hit that
    `.crumbignore` exempted. A `.crumbignore` pattern that matches every line
    is a `crumbignore-pattern` warning, and is not used.
    """
    findings: list[dict] = []
    seen: set[tuple[str, str, int]] = set()
    ignores, ignore_problems = crumbignore_rules(memory_dir)
    suppressed = 0

    def record(pattern: str, rel: str, i: int, **extra) -> None:
        key = (pattern, rel, i)
        if key in seen:
            return
        seen.add(key)
        findings.append(
            {
                "pattern": pattern,
                "path": rel,
                "line": i,
                "severity": _secret_severity(pattern),
                **extra,
            }
        )

    for problem in ignore_problems:
        record(
            "crumbignore-pattern",
            CRUMBIGNORE_FILENAME,
            problem["line"],
            detail=problem["detail"],
        )
    for p in _iter_committed_memory_files(memory_dir):
        rel = path_policy.posix_rel(p, memory_dir)
        text, problem = cli.read_text_lenient(p)
        if problem:
            record("unscannable-file", rel, 0, detail=problem)
        if "\x00" in text:
            record(
                "unscannable-file",
                rel,
                0,
                detail="binary content (NUL bytes); it cannot be scanned as text",
            )
        for i, line in enumerate(text.splitlines(), 1):
            hits = [name for name, pat in SECRET_PATTERNS if pat.search(line)]
            if any(_looks_high_entropy(m.group(0)) for m in _HIGH_ENTROPY_TOKEN.finditer(line)):
                hits.append("high-entropy-string")
            if not hits:
                continue
            if any(pat.search(line) for pat in ignores):
                suppressed += 1
                continue
            for name in hits:
                record(name, rel, i)
    if stats is not None:
        stats["suppressed"] = suppressed
    return findings


# ---- hidden characters ----------------------------------------------------- #


def scan_hidden_characters(memory_dir: Path) -> list[dict]:
    """Records holding characters a reader does not see: format characters
    such as Unicode tags, blank fillers, smuggling runs of variation
    selectors, and line breaks other than a newline.

    Every view escapes them (`safetext`), but the file still holds them and a
    diff does not show them, so a person should look (review 2026-11-13,
    §2.7). One finding per file: `{path, lines, count}`. Flag only.
    """
    from breadcrumbs import safetext

    memory_dir = Path(memory_dir)
    targets: list[Path] = []
    kt = memory_dir / "known-traps.md"
    if kt.is_file():
        targets.append(kt)
    targets += [rec.path for rec in cli.load_records(memory_dir) if not rec.error]
    findings: list[dict] = []
    for p in dict.fromkeys(targets):
        if not p.is_file():
            continue
        text = cli.read_text_lenient(p)[0]
        lines, count = [], 0
        for i, line in enumerate(text.split("\n"), 1):
            n = safetext.hidden_count(line.rstrip("\r"))
            if n:
                lines.append(i)
                count += n
        if count:
            findings.append(
                {"path": path_policy.posix_rel(p, memory_dir), "lines": lines, "count": count}
            )
    return findings


# ---- instruction-like heuristic -------------------------------------------- #


def scan_instruction_like(memory_dir: Path) -> list[dict]:
    """Lexical scan of known-traps.md + durable record bodies for override phrasing.

    Flag-only (warn). Never gates `validate` and never instructs `guard` — the same
    content-as-data posture as Fixture 7.
    """
    memory_dir = Path(memory_dir)
    findings: list[dict] = []
    targets: list[Path] = []
    kt = memory_dir / "known-traps.md"
    if kt.is_file():
        targets.append(kt)
    for rec in cli.load_records(memory_dir):
        if not rec.error:
            targets.append(rec.path)

    seen: set[Path] = set()
    for p in targets:
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        rel = path_policy.posix_rel(p, memory_dir)
        # Lenient: scan_secrets already reports the unreadable
        # file; this pass just must not abort audit on it.
        text = cli._strip_html_comments(cli.read_text_lenient(p)[0])
        for i, line in enumerate(text.splitlines(), 1):
            for pat in INSTRUCTION_LIKE_PATTERNS:
                m = pat.search(line)
                if m:
                    findings.append({"path": rel, "line": i, "phrase": m.group(0).strip()})
                    break
    return findings
