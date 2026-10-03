"""breadcrumbs — reading a shell command the way guard needs to.

Guard used to read a command as one string. That made three kinds of mistake
in the field (DoWhat field report, 2026-10-01, issues 7, 10 and 11):

- `cd app; grep -r x .` lost its read-only cap because of the `;`, while
  `find . | xargs rm -rf` kept it, because only the first word was checked and
  a single `|` was not looked at (N4 — a destructive command was capped *down*).
- Words inside quoted text and here-documents — a commit message, a
  `--next "cut the release"` — were read as what the command *does*, so
  `release` made a memory write an external side effect.
- crumb's own commands were judged like any other: `crumb migrate --dry-run`
  and `crumb reindex` were "migrations".

This module owns reading command text: `segments`/`words` parse a command
exactly, to decide what it does; `normalize_command` is a command's identity
across retries; `match_tokens` is the loose tokenizing guard retrieval matches
records with.

Everything here is stdlib string work with no store access, so the hook can
call it before it reads anything. It is conservative where it must be: a
command it cannot read (command substitution, a parse it does not understand)
is never called read-only.
"""

from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

from breadcrumbs.path_policy import to_posix

# ---- read-only verbs (moved here from cli.py; cli re-exports the names) ----- #

# Commands whose whole job is to report. Deliberately a short allowlist of the
# unambiguous ones: `tee` writes, and anything not named here is simply treated
# as capable of side effects, which is the safe default. `sed` and `awk` can
# write too, so they are not here: `_sed_read_only` and `_awk_read_only` read
# their arguments (DoWhat retest of 0.5.0, item 1: `sed -n '867p' f | grep x`
# got PAUSE).
READ_ONLY_COMMANDS = frozenset(
    """
    cat less more head tail nl wc tac rev
    ls dir tree stat file du df pwd realpath readlink basename dirname
    grep egrep fgrep rg ack ag find fd locate
    diff cmp comm md5sum sha1sum sha256sum
    which whereis type man whoami hostname uname date
    echo printf uniq cut column jq yq sort tr paste fold fmt expand unexpand
    od xxd hexdump strings
    ps top uptime id groups
    """.split()
)

# `git` spans the whole range, so it gets its own allowlist of subcommands.
READ_ONLY_GIT_SUBCOMMANDS = frozenset(
    """
    status log diff show blame describe shortlog rev-parse rev-list ls-files
    ls-tree ls-remote cat-file whatchanged grep reflog annotate count-objects var
    merge-base
    """.split()
)

# `git <sub>` forms that only list when given no positional argument (or only
# a listing flag): `git branch` lists, `git branch x` creates.
_GIT_LISTING_SUBCOMMANDS = {
    "branch": frozenset(
        "-a --all -r --remotes -v -vv --verbose -l --list --show-current --merged "
        "--no-merged --contains --no-contains --sort --format --color --no-color "
        "--column --no-column --points-at".split()
    ),
    "remote": frozenset("-v --verbose show get-url".split()),
    "tag": frozenset(
        "-l --list -n --sort --format --contains --no-contains --merged "
        "--no-merged --points-at --column --no-column".split()
    ),
    "stash": frozenset("list show".split()),
    "config": frozenset(
        "--get --get-all --get-regexp --list -l --show-origin --show-scope --name-only "
        "--global --local --system --file -f --null -z --type --bool --int --path".split()
    ),
}
# Listing flags above that take a value (`--sort=x` is one token; `--sort x` two).
_GIT_LISTING_VALUE_FLAGS = frozenset(
    "--contains --no-contains --merged --no-merged --points-at --sort --format --file -f "
    "--type".split()
)


def _git_listing(sub: str, args: list[str]) -> bool:
    """Is `git <sub> <args>` one of the listing forms in `_GIT_LISTING_SUBCOMMANDS`?"""
    allowed = _GIT_LISTING_SUBCOMMANDS.get(sub)
    if allowed is None:
        return False
    if sub == "config":
        # Reading config needs a reading flag; `git config user.name` reads too,
        # but `git config user.name x` writes, and the two differ only by count.
        flags = {a.split("=", 1)[0] for a in args if a.startswith("-")}
        return (
            bool(flags & {"--get", "--get-all", "--get-regexp", "--list", "-l"})
            and flags <= allowed
        )
    if sub == "stash":
        # A bare `git stash` is `git stash push`; only `list` and `show` read.
        return bool(args) and args[0] in allowed
    if sub == "remote" and args and not args[0].startswith("-"):
        # `git remote show origin`: the first word decides.
        return args[0] in allowed
    rest = list(args)
    while rest:
        a = rest.pop(0)
        if not a.startswith("-"):
            return False  # a name: create, delete or rename something
        if a.split("=", 1)[0] not in allowed:
            return False
        if a in _GIT_LISTING_VALUE_FLAGS and rest and "=" not in a:
            rest.pop(0)
    return True


# ---- sed and awk: reporting unless their script writes --------------------- #


def _sed_script_writes(script: str) -> bool | None:
    """Does a sed script write a file or run a command? None when unreadable.

    Walks the commands: addresses (`1`, `$`, `/re/`, `\\cREc`, ranges, `~`,
    `!`), then one command letter. `w`/`W` write a file, `e` runs a command,
    and an `s` command's `w`/`e` flags do the same. `a`/`i`/`c` and `r`/`R`
    take the rest of the line as text or a file to *read*.
    """
    i, n = 0, len(script)

    def skip_re(j: int, delim: str) -> int:
        j += 1
        while j < n and script[j] != delim:
            if script[j] == "\\":
                j += 1
            elif script[j] == "\n":
                return -1
            j += 1
        return j + 1 if j < n else -1

    while i < n:
        ch = script[i]
        if ch in " \t\n;{}":
            i += 1
            continue
        # Addresses.
        while i < n:
            ch = script[i]
            if ch.isdigit() or ch in "$,~+! \t":
                i += 1
            elif ch == "/":
                i = skip_re(i, "/")
                if i < 0:
                    return None
            elif ch == "\\" and i + 1 < n:
                i = skip_re(i + 1, script[i + 1])
                if i < 0:
                    return None
            else:
                break
            # A regex address may carry `I`/`M` modifiers.
            while i < n and script[i] in "IM" and i > 0 and script[i - 1] in "/":
                i += 1
        if i >= n:
            return False
        cmd = script[i]
        i += 1
        if cmd in "wWe":
            return True
        if cmd in "aicrRbtTvq:#lLQ":
            # Rest of the line is an argument (text, label, file to read).
            while i < n and script[i] != "\n":
                if cmd in "btTvqQlL" and script[i] in ";}":
                    break
                i += 1
            continue
        if cmd in "sy":
            if i >= n:
                return None
            delim = script[i]
            for _part in range(2):
                i = skip_re(i, delim) - 1
                if i < 0:
                    return None
            i += 1
            if cmd == "s":
                while i < n and script[i] not in ";}\n":
                    if script[i] in "we":
                        return True
                    i += 1
            continue
        if cmd in "=dDgGhHnNpPxzF{}":
            continue
        return None  # a command this reader does not know
    return False


def _sed_read_only(args: list[str]) -> bool:
    scripts: list[str] = []
    rest = list(args)
    explicit = False
    while rest:
        a = rest.pop(0)
        if a in ("--in-place",) or a.startswith("--in-place="):
            return False
        if a in ("-f", "--file") or a.startswith("--file="):
            return False  # a script file this cannot read
        if a in ("-e", "--expression"):
            if not rest:
                return False
            scripts.append(rest.pop(0))
            explicit = True
            continue
        if a.startswith("--expression="):
            scripts.append(a.split("=", 1)[1])
            explicit = True
            continue
        if a.startswith("--"):
            continue  # --quiet, --regexp-extended, --posix, --debug, ...
        if a.startswith("-") and len(a) > 1:
            letters = a[1:]
            if "i" in letters:
                return False  # -i, -i.bak, -ni
            if "f" in letters:
                return False
            if letters.endswith("e"):
                if not rest:
                    return False
                scripts.append(rest.pop(0))
                explicit = True
            continue
        if not explicit and not scripts:
            scripts.append(a)  # the first operand is the script
        # Later operands are input files.
    if not scripts:
        return False
    return all(_sed_script_writes(s) is False for s in scripts)


_AWK_WRITE_RE = re.compile(
    r"\bsystem\s*\(|\b(?:print|printf)\b[^;}\n]*(?:>|\|)|\|\s*getline|\|&|\bfflush\b"
)


def _awk_read_only(args: list[str]) -> bool:
    rest = list(args)
    program = None
    while rest:
        a = rest.pop(0)
        if a in ("-f", "--file", "-i", "--include", "-l", "--load", "-E", "--exec"):
            return False  # a program file, an extension, `-i inplace`
        if a.startswith(("-f", "--file=", "-i", "--include=", "--exec=")) and a != "-":
            return False
        if a in ("-F", "-v", "--field-separator", "--assign"):
            if rest:
                rest.pop(0)
            continue
        if a.startswith("-"):
            continue  # -F:, -vX=1, --posix, ...
        program = a
        break
    if program is None:
        return False
    return not _AWK_WRITE_RE.search(program)


# Flags that make an otherwise-reporting command act (`find . -delete`,
# `find . -exec rm {} +`, `sort -o out`). Matched as whole tokens.
READ_ONLY_DISQUALIFYING_ARGS = frozenset(
    "-delete -exec -execdir -ok -okdir -fprint -fls -fprintf -o --output".split()
)

# Segments that change nothing a reader cares about: moving around, no-ops.
NEUTRAL_VERBS = frozenset({"cd", "pushd", "popd", "true", ":", "set"})

# Redirection targets that discard or merge output rather than write a file.
NEUTRAL_REDIRECT_TARGETS = frozenset(
    {"/dev/null", "/dev/stdout", "/dev/stderr", "&1", "&2", "&-", "nul", "NUL", "$null"}
)

# xargs options that take a value, so the command it runs can be found.
_XARGS_VALUE_OPTS = frozenset({"-I", "-i", "-n", "-P", "-d", "-L", "-s", "-E", "-a"})


# ---- quoting, here-documents, segments -------------------------------------- #

_HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def strip_heredocs(command: str) -> str:
    """`command` with every here-document body removed (the `<<EOF` line stays).

    A heredoc body is data — a commit message, a file being written — and its
    `;`, `|` and words are not part of the command.
    """
    lines = (command or "").split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        terminators = [
            (m.group(2), m.group(0).startswith("<<-")) for m in _HEREDOC_RE.finditer(line)
        ]
        i += 1
        for word, dash in terminators:
            while i < len(lines):
                candidate = lines[i].lstrip("\t") if dash else lines[i]
                i += 1
                if candidate.strip() == word:
                    break
    return "\n".join(out)


def _scan(command: str):
    """Yield `(char, quoted)` for each character, tracking shell quoting."""
    quote = None
    escaped = False
    for ch in command:
        if escaped:
            escaped = False
            yield ch, True
            continue
        if ch == "\\" and quote != "'":
            escaped = True
            yield ch, quote is not None
            continue
        if quote:
            if ch == quote:
                quote = None
                yield ch, False
                continue
            yield ch, True
            continue
        if ch in ("'", '"'):
            quote = ch
            yield ch, False
            continue
        yield ch, False


def strip_quoted(command: str) -> str:
    """`command` with the contents of quoted strings removed (quotes kept).

    What a command *does* is in its words; what it *says* (a message, a
    `--next` note, a search string) is in its quotes.
    """
    return "".join(ch for ch, quoted in _scan(command or "") if not quoted)


def is_dynamic(command: str) -> bool:
    """Command substitution or process substitution outside single quotes:
    the command that will actually run cannot be read from the text."""
    text = command or ""
    quote = None
    prev = ""
    for ch in text:
        if quote == "'":
            if ch == "'":
                quote = None
            prev = ch
            continue
        if ch == "'" and quote is None:
            quote = "'"
        elif ch == '"':
            quote = None if quote == '"' else '"'
        elif ch == "`":
            return True
        elif ch == "(" and prev in ("$", "<", ">"):
            return True
        prev = ch
    return False


def segments(command: str) -> list[str] | None:
    """The simple commands in `command`, split on unquoted `;`, `&&`, `||`,
    `|`, `&` and newlines. None when the command is dynamic (see `is_dynamic`).
    Here-document bodies are dropped first."""
    text = strip_heredocs(command or "")
    if is_dynamic(text):
        return None
    out: list[str] = []
    buf: list[str] = []
    chars = list(_scan(text))
    i = 0
    while i < len(chars):
        ch, quoted = chars[i]
        if not quoted and ch in ";|&\n":
            # `>&`, `2>&1`, `&>`: a redirection, not a separator.
            prev = buf[-1] if buf else ""
            nxt = chars[i + 1][0] if i + 1 < len(chars) else ""
            if ch == "&" and (prev in (">", "<") or nxt == ">"):
                buf.append(ch)
                i += 1
                continue
            out.append("".join(buf))
            buf = []
            # Swallow the second char of `&&` / `||`.
            if i + 1 < len(chars) and chars[i + 1][0] == ch and ch in "&|":
                i += 1
            i += 1
            continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return [s.strip() for s in out if s.strip()]


_REDIRECT_RE = re.compile(r"(?<![<>&\w])(\d*|&)(>>?|>\|)\s*(&?[^\s;|&<>]*)")


def split_redirections(segment: str) -> tuple[str, list[str]]:
    """`(segment without output redirections, [targets])`, quote-aware."""
    masked = "".join(" " if quoted else ch for ch, quoted in _scan(segment))
    targets: list[str] = []
    pieces: list[str] = []
    last = 0
    for m in _REDIRECT_RE.finditer(masked):
        target = segment[m.start(3) : m.end(3)]
        targets.append(target.strip("'\""))
        pieces.append(segment[last : m.start()])
        last = m.end()
    pieces.append(segment[last:])
    return "".join(pieces), targets


# Words that come before a command without being it: shell keywords that open
# or continue a compound command, and prefixes that run the rest. Read as the
# command, `do crumb guard "$a"` in a loop was `do`, so crumb's own words were
# matched against the store and `do git push --force origin main` was not a
# force-push (DoWhat retest of 0.6.0, item 5b).
SHELL_KEYWORD_PREFIXES = frozenset(
    {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "(", "time", "nohup"}
)
# Words that close a compound command; a segment of only these runs nothing.
SHELL_CLOSERS = frozenset({"done", "fi", "esac", "}", ")"})


def words(segment: str) -> list[str]:
    """Shell words of one segment (output redirections removed), with leading
    `VAR=value` assignments, shell keywords (`do`, `then`, `if`, …) and the
    `time`/`nohup` prefixes dropped. Falls back to whitespace splitting."""
    body, _targets = split_redirections(segment)
    body = re.sub(r"(?<![\w-])\d*<\s*\S+", " ", body)  # input redirection
    try:
        toks = shlex.split(body, posix=True)
    except ValueError:
        toks = body.split()
    while toks:
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", toks[0]) or toks[0] in SHELL_KEYWORD_PREFIXES:
            if toks.pop(0) == "time" and toks[:1] == ["-p"]:
                toks.pop(0)
        elif toks[0].startswith(("(", "{")) and len(toks[0]) > 1:
            toks[0] = toks[0][1:]
        else:
            break
    if toks and all(t in SHELL_CLOSERS for t in toks):
        return []
    return toks


def verb_of(tokens: list[str]) -> str:
    return PurePosixPath(to_posix(tokens[0] if tokens else "")).name.lower()


# ---- crumb's own commands ------------------------------------------------- #

# What each crumb subcommand does, by effect. crumb knows its own commands; it
# must not guess at them from the words in their arguments.
CRUMB_READ_ONLY = frozenset(
    """
    resume search show guard validate schema audit scan-secrets doctor usage
    questions expired help version --version -V --help -h
    """.split()
)
CRUMB_MEMORY_WRITE = frozenset(
    """
    remember note verify mark-status retitle reindex recover capture jot inbox
    review prune traps policy consolidate promote demote rollup repair rename
    handoff
    """.split()
)

# Store files each memory-writing subcommand rewrites (issue 11: a trap keyed to
# handoff.md could not fire on `crumb capture session`, the command that wrote
# it). Store-relative; `crumb_writes` prefixes the store directory.
CRUMB_WRITES = {
    "capture": ("handoff.md", "handoffs/", "current.md", "sessions/"),
    "remember": ("decisions/", "attempts/"),
    "note": ("traps/", "questions/", "ideas/", "known-traps.md", "open-questions.md"),
    "verify": ("verifications/",),
    "jot": ("inbox/",),
    "migrate": ("manifest.yml", "known-traps.md", "open-questions.md", "traps/", "questions/"),
    "reindex": ("generated/", "known-traps.md", "open-questions.md"),
}


def crumb_invocation(tokens: list[str]) -> list[str] | None:
    """The arguments after `crumb` / `python crumb.py` / `python -m breadcrumbs`,
    or None when this is not a crumb command."""
    if not tokens:
        return None
    verb = verb_of(tokens)
    if verb in ("crumb", "crumb.exe"):
        return tokens[1:]
    if verb.startswith("python") or verb in ("py", "uv", "uvx"):
        rest = tokens[1:]
        if verb in ("uv",) and rest[:1] == ["run"]:
            rest = rest[1:]
            return crumb_invocation(rest)
        if verb == "uvx":
            return crumb_invocation(rest)
        while rest and rest[0].startswith("-") and rest[0] != "-m":
            rest = rest[1:]
        if rest[:2] == ["-m", "breadcrumbs"]:
            return rest[2:]
        if rest and PurePosixPath(to_posix(rest[0])).name == "crumb.py":
            return rest[1:]
    return None


def crumb_effect(args: list[str]) -> str:
    """`read_only`, `memory_write`, `migration` or `other` for crumb's arguments."""
    positional = [a for a in args if not a.startswith("-")]
    sub = positional[0] if positional else (args[0] if args else "help")
    flags = set(args)
    if sub in CRUMB_READ_ONLY or not args:
        return "read_only"
    if "--dry-run" in flags or ("-n" in flags and sub in ("migrate", "prune")):
        return "read_only"
    if sub == "migrate":
        return "migration"
    if sub == "inbox" and (len(positional) < 2 or positional[1] in ("list", "show")):
        return "read_only"
    if sub == "traps" and "--confirm" not in flags:
        return "read_only"
    if sub == "repair" and "--apply" not in flags:
        return "read_only"
    if sub == "policy" and (len(positional) < 2 or positional[1] in ("show",)):
        return "read_only"
    if sub == "mcp" and len(positional) > 1 and positional[1] == "doctor":
        return "read_only"
    if sub in CRUMB_MEMORY_WRITE:
        return "memory_write"
    return "other"


def crumb_commands(command: str) -> list[tuple[str, list[str]]]:
    """`[(effect, args)]` for every crumb invocation among the segments."""
    out = []
    for seg in segments(command) or []:
        args = crumb_invocation(words(seg))
        if args is not None:
            out.append((crumb_effect(args), args))
    return out


def crumb_writes(command: str, store_dirname: str = ".project-memory") -> list[str]:
    """Store paths the crumb commands in `command` write (issue 11)."""
    out: list[str] = []
    for effect, args in crumb_commands(command):
        positional = [a for a in args if not a.startswith("-")]
        sub = positional[0] if positional else ""
        if effect == "read_only":
            continue
        for rel in CRUMB_WRITES.get(sub, ()):
            path = f"{store_dirname}/{rel}"
            if path not in out:
                out.append(path)
    return out


# ---- read-only ------------------------------------------------------------- #


def _verb_read_only(tokens: list[str]) -> bool:
    if not tokens:
        return True
    verb = verb_of(tokens)
    if verb in NEUTRAL_VERBS:
        return True
    if READ_ONLY_DISQUALIFYING_ARGS & {t for t in tokens[1:]}:
        return False
    crumb = crumb_invocation(tokens)
    if crumb is not None:
        return crumb_effect(crumb) == "read_only"
    if verb == "git":
        rest = tokens[1:]
        # `git -C dir log`: skip global options and their values.
        while rest and rest[0].startswith("-"):
            opt = rest.pop(0)
            if opt in ("-C", "-c", "--git-dir", "--work-tree") and rest:
                rest.pop(0)
        if not rest:
            return False
        return rest[0] in READ_ONLY_GIT_SUBCOMMANDS or _git_listing(rest[0], rest[1:])
    if verb in ("sed", "gsed"):
        return _sed_read_only(tokens[1:])
    if verb in ("awk", "gawk", "mawk", "nawk"):
        return _awk_read_only(tokens[1:])
    if verb == "xargs":
        rest = tokens[1:]
        while rest and rest[0].startswith("-"):
            opt = rest.pop(0)
            if opt in _XARGS_VALUE_OPTS and rest:
                rest.pop(0)
        return bool(rest) and _verb_read_only(rest)
    return verb in READ_ONLY_COMMANDS


def is_read_only(command: str) -> bool:
    """True only when every part of `command` provably cannot change anything.

    Each segment of a compound command (`cd x && grep …`, `git log | head`) must
    be read-only on its own; output redirected anywhere but `/dev/null` (or
    merged into another stream) is a write; a pipe into `sh`, `tee`, `xargs rm`
    or `sed -i` is a write because those are not read-only verbs. A command
    this cannot read is treated as capable of side effects.
    """
    segs = segments(command)
    if not segs:
        return False
    for seg in segs:
        _body, targets = split_redirections(seg)
        if any(t not in NEUTRAL_REDIRECT_TARGETS for t in targets):
            return False
        if not _verb_read_only(words(seg)):
            return False
    return True


# ---- classification text --------------------------------------------------- #


def classification_text(command: str) -> str:
    """What the action classifier should read: the command's own words, with
    here-document bodies and quoted text removed (N11)."""
    return strip_quoted(strip_heredocs(command or ""))


def matching_text(command: str) -> str:
    """What retrieval should match against: here-document bodies removed (a
    5,000-character commit message matched 27-37 words of unrelated records)."""
    return strip_heredocs(command or "")


def without_crumb(command: str) -> str:
    """`matching_text(command)` with every crumb invocation left out.

    crumb's own words (`crumb`, `migrate`, `reindex`, `capture`, `session`)
    name crumb's operations, not the project's. Matched against the store they
    found every record tagged crumb, migration or memory (DoWhat retest of
    0.5.0, items 3 and 5). A crumb command meets memory through the files it
    writes (`crumb_writes`) and through records naming the exact command.
    """
    text = matching_text(command)
    segs = segments(command or "")
    if segs is None:
        return text
    kept = [seg for seg in segs if crumb_invocation(words(seg)) is None]
    if len(kept) == len(segs):
        return text
    return " ; ".join(kept)


# Code-shaped identifiers in written content: camelCase, PascalCase with two
# humps, snake_case, CONSTANT_CASE, and dotted calls. Prose has almost none.
_IDENTIFIER_RE = re.compile(
    r"\b(?:[a-z][a-z0-9]*[A-Z][A-Za-z0-9]*"
    r"|[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*"
    r"|[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+)\b"
)


def code_identifiers(content: str) -> list[str]:
    """The code identifiers in `content`, in order, without repeats."""
    seen: dict[str, None] = {}
    for m in _IDENTIFIER_RE.finditer(content or ""):
        seen.setdefault(m.group(0), None)
    return list(seen)


# ---- high-impact actions with no memory (operator decision D3) ------------ #

_DEFAULT_BRANCHES = frozenset({"main", "master", "trunk", "develop"})
_BUILD_DIR_NAMES = frozenset(
    """
    build dist out target node_modules .gradle __pycache__ .pytest_cache .mypy_cache
    .ruff_cache .tox .venv venv coverage htmlcov tmp temp .next .nuxt .cache
    test-results reports intermediates generated
    """.split()
)


def _force_push_to_default(tokens: list[str]) -> str | None:
    if verb_of(tokens) != "git" or "push" not in tokens:
        return None
    rest = tokens[tokens.index("push") + 1 :]
    force = any(
        t in ("--force", "-f") or (t.startswith("-") and not t.startswith("--") and "f" in t)
        for t in rest
    )
    refs = [t for t in rest if not t.startswith("-")]
    plus = [r for r in refs if r.startswith("+")]
    if not force and not plus:
        return None
    targets = {r.lstrip("+").split(":")[-1] for r in refs[1:]} if len(refs) > 1 else set()
    if targets & _DEFAULT_BRANCHES:
        return "force-push to " + "/".join(sorted(targets & _DEFAULT_BRANCHES))
    return None


def _rm_rf_outside_build(tokens: list[str]) -> str | None:
    if verb_of(tokens) == "xargs":
        # `… | xargs rm -rf`: the targets arrive on stdin, so nothing says they
        # are build output (N4: this used to be capped as read-only).
        rest = tokens[1:]
        while rest and rest[0].startswith("-"):
            opt = rest.pop(0)
            if opt in _XARGS_VALUE_OPTS and rest:
                rest.pop(0)
        inner = _rm_rf_outside_build(rest + ["<stdin>"])
        return "rm -rf on piped input" if inner else None
    if verb_of(tokens) != "rm":
        return None
    flags = "".join(
        t.lstrip("-") for t in tokens[1:] if t.startswith("-") and not t.startswith("--")
    )
    long_flags = {t for t in tokens[1:] if t.startswith("--")}
    recursive = "r" in flags or "R" in flags or "--recursive" in long_flags
    force = "f" in flags or "--force" in long_flags
    if not (recursive and force):
        return None
    targets = [t for t in tokens[1:] if not t.startswith("-")]
    for t in targets:
        parts = [p for p in to_posix(t).split("/") if p not in ("", ".")]
        if is_temp_path(t) or any(p in _BUILD_DIR_NAMES or p.endswith(".egg-info") for p in parts):
            continue
        return f"rm -rf {t}"
    return None


# ---- scratch files (DoWhat retest of 0.6.0, item 6) ------------------------ #
#
# `rm -f "$TEMP/handoff.before"`, at the end of a command that made that copy,
# asked a human: `rm` is a deletion, and a deletion turns any READ_FIRST into
# ASK_HUMAN. Deleting under the system temp directory, or a file the same
# command created, is cleanup.

_TEMP_ROOT_RE = re.compile(
    r"(?i)^(?:"
    r"\$\{?(?:TEMP|TMP|TMPDIR)(?::?[-=+?][^}]*)?\}?"  # $TEMP, ${TMPDIR:-/tmp}
    r"|%(?:TEMP|TMP)%"  # cmd.exe
    r"|\$env:(?:TEMP|TMP)"  # PowerShell
    r"|/tmp|/var/tmp|/private/tmp|/private/var/tmp"
    r"|[a-z]:[/\\]windows[/\\]temp"
    r")[/\\]+[^/\\]"
)
_APPDATA_TEMP_RE = re.compile(r"(?i)(?:^|[/\\])appdata[/\\]local[/\\]temp[/\\]+[^/\\]")


def is_temp_path(path: str) -> bool:
    """Is `path` something inside the system temp directory (never the directory itself)?"""
    p = str(path or "").strip().strip("\"'")
    if not p or ".." in re.split(r"[/\\]", p):
        return False
    return bool(_TEMP_ROOT_RE.match(p) or _APPDATA_TEMP_RE.search(p))


def _plain_path(path: str) -> str:
    p = to_posix(str(path or "").strip().strip("\"'"))
    while p.startswith("./"):
        p = p[2:]
    return p


def _created_by(tokens: list[str], segment: str) -> set[str]:
    """Files a segment creates: output redirects, `cp`/`mv`/`ln`/`install`
    destinations, and `touch`/`tee`/`mkdir` arguments."""
    _body, targets = split_redirections(segment)
    out = {t for t in targets if t not in NEUTRAL_REDIRECT_TARGETS}
    verb = verb_of(tokens)
    args = [t for t in tokens[1:] if not t.startswith("-")]
    if verb in ("cp", "mv", "ln", "install") and len(args) >= 2:
        out.add(args[-1])
    elif verb in ("touch", "tee", "mkdir"):
        out.update(args)
    return {_plain_path(t) for t in out if t}


def _rm_args(tokens: list[str]) -> tuple[list[str], bool] | None:
    """`(targets, recursive)` for an `rm`, else None."""
    if verb_of(tokens) != "rm":
        return None
    targets, recursive, options = [], False, True
    for t in tokens[1:]:
        if options and t == "--":
            options = False
        elif options and t.startswith("--"):
            recursive = recursive or t == "--recursive"
        elif options and t.startswith("-") and len(t) > 1:
            recursive = recursive or "r" in t or "R" in t
        else:
            targets.append(t)
    return targets, recursive


def scratch_deletions(segs: list[str]) -> list[bool]:
    """For each segment: does it only delete scratch files?

    Scratch is anything under the system temp directory, or a file an earlier
    segment of the same command created. A recursive delete counts only under
    temp: a directory the command made may hold more than it put there.
    """
    created: set[str] = set()
    out: list[bool] = []
    for seg in segs:
        toks = words(seg)
        rm = _rm_args(toks)
        scratch = False
        if rm is not None and rm[0]:
            targets, recursive = rm
            scratch = all(
                is_temp_path(t) or (not recursive and _plain_path(t) in created) for t in targets
            )
        out.append(scratch)
        created |= _created_by(toks, seg)
    return out


# ---- here-documents: data or code (DoWhat retest of 0.6.0, item 7) -------- #
#
# A heredoc fed to `while read`, `cat >`, `tee` or `python -` is data: its lines
# say what to do, they are not done here. One fed to a shell, a remote shell or
# a database client is run as commands.
HEREDOC_CODE_CONSUMERS = frozenset(
    """
    bash sh zsh ksh dash ash fish csh tcsh busybox ssh su sudo doas
    psql mysql mariadb sqlite3 mongo mongosh redis-cli cqlsh clickhouse-client
    """.split()
)


def _runs_code(line: str) -> bool:
    """Does the command on a heredoc's opening line run its input as commands?"""
    segs = segments(line)
    if segs is None:
        return True  # cannot tell: keep the body
    for seg in segs:
        for tok in words(seg):
            if PurePosixPath(to_posix(tok)).name.lower().removesuffix(".exe") in (
                HEREDOC_CODE_CONSUMERS
            ):
                return True
    return False


def _heredoc_lines(command: str):
    """Yield `(line, kind)`: `command`, or a heredoc body line that is `code` or `data`."""
    lines = (command or "").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        yield line, "command"
        terminators = [
            (m.group(2), m.group(0).startswith("<<-")) for m in _HEREDOC_RE.finditer(line)
        ]
        i += 1
        kind = "code" if terminators and _runs_code(line) else "data"
        for word, dash in terminators:
            while i < len(lines):
                candidate = lines[i].lstrip("\t") if dash else lines[i]
                done = candidate.strip() == word
                yield lines[i], "command" if done else kind
                i += 1
                if done:
                    break


def without_data_heredocs(command: str) -> str:
    """`command` with the bodies of data heredocs removed; code bodies stay."""
    return "\n".join(line for line, kind in _heredoc_lines(command) if kind != "data")


# Package managers whose `install` takes `--force` to mean "reinstall over the
# copy that is there" (found checking the 0.6.0 retest, N1): reversible, so not
# the `--force` the destructive check is about.
PACKAGE_MANAGERS = frozenset(
    """
    pip pip3 pipx uv uvx poetry pdm conda mamba npm pnpm yarn bun brew cargo gem
    go apt apt-get dnf yum choco winget scoop
    """.split()
)
_INSTALL_VERBS = frozenset({"install", "add", "upgrade", "update", "reinstall", "sync"})


def _package_install(tokens: list[str]) -> bool:
    """Is this segment a package manager installing something (`uv tool install …`)?"""
    if verb_of(tokens).removesuffix(".exe") not in PACKAGE_MANAGERS:
        return False
    positional = [t for t in tokens[1:4] if not t.startswith("-")]
    return bool(_INSTALL_VERBS & set(positional))


def destructive_text(command: str) -> str:
    """What the destructive-shape check reads: the command without data heredoc
    bodies, segments that only delete scratch files, and package installs (whose
    `--force` reinstalls). Quoted text stays: `bash -c "rm -rf x"` and
    `sqlite3 db "DROP TABLE t"` are code."""
    segs = segments(command or "")
    if segs is None:
        return without_data_heredocs(command)
    scratch = [
        cleanup or _package_install(words(seg))
        for seg, cleanup in zip(segs, scratch_deletions(segs))
    ]
    if not any(scratch):
        return without_data_heredocs(command)
    kept = [seg for seg, s in zip(segs, scratch) if not s]
    # `segments` dropped every heredoc body; the code ones still count.
    code = [line for line, kind in _heredoc_lines(command) if kind == "code"]
    return "\n".join([" ; ".join(kept), *code])


def high_impact(command: str) -> str | None:
    """Why `command` is high-impact whatever memory says, or None.

    A short, literal list (operator decision D3, 2026-10-01): a force-push to a
    default branch, a recursive forced delete outside build/cache directories,
    and a real (not `--dry-run`) `crumb migrate`. Guard gives these ASK_HUMAN
    even with no matching record, and says so instead of citing unrelated ones.
    """
    for seg in segments(command) or []:
        toks = words(seg)
        for check in (_force_push_to_default, _rm_rf_outside_build):
            reason = check(toks)
            if reason:
                return reason
        crumb = crumb_invocation(toks)
        if crumb is not None and crumb_effect(crumb) == "migration":
            return "crumb migrate rewrites the memory store"
    return None


# --------------------------------------------------------------------------- #
# Command identity and matching tokens
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


def match_tokens(text: str) -> list[str]:
    """A command as lowercase tokens for *matching*: `cd x &&` prefixes, pager
    tails and quotes folded, punctuation stripped.

    Not `words()`. `words()` is one segment's exact argv, for deciding what a
    command does; this is loose on purpose, because the other side of the
    match is often prose — a trap titled "gradlew --stop kills the daemon" —
    and both sides must fold the same way. Guard retrieval and the guard
    pre-filter match a trap's command heads against an action with it.
    """
    flat = normalize_command(str(text or ""))
    out = []
    for t in flat.split():
        # `./gradlew` is `gradlew`: stripping the dot alone left `/gradlew`, so a
        # trap titled "gradlew --stop …" never matched `./gradlew --stop`.
        t = t[2:] if t.startswith("./") else t
        t = t.strip("\"'`.,;:").lower()
        if t:
            out.append(t)
    return out
