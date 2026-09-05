#!/usr/bin/env python3
"""crumb — Breadcrumbs CLI.

This module is the whole command surface — ``init``, ``validate``, ``schema``,
``remember``, ``verify``, ``mark-status``, ``note``, ``capture``, ``resume``,
``reindex``, ``search``, ``guard``, ``audit``, ``scan-secrets``, ``doctor``,
``mcp`` and the ``hook`` entry points — and the package entry point
(``breadcrumbs.cli``), exposed as the ``crumb`` console script. The ``crumb.py``
shim at the repo root re-exports it so source-checkout use
(``python crumb.py ...``) and the test suite keep working unchanged. Templates
ship as package data under ``breadcrumbs/templates/`` so ``init`` finds them
post-install without any repo-relative path.

Design constraints (see docs/):
- Standard library only.
- Deterministic by default.
- Memory is advisory; this tool only manages files, it never overrides
  current user instruction, code, tests, build output, or authoritative docs.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path, PurePosixPath

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

SCHEMA_VERSION = 1
MEMORY_DIRNAME = ".project-memory"

# Templates are package data: they live next to this module inside the
# `breadcrumbs` package, so this resolves correctly both from a source
# checkout and from an installed wheel (pipx/pip extract package data to real
# files in the venv). This is package-relative, never repo-relative — `init`
# finds the template tree wherever the package is installed.
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "project-memory"

# Dev/source-checkout fallback version. The installed distribution's version is
# authoritative (read from package metadata in get_version); this fallback is for
# source-tree runs where no metadata exists. It reads from the single source of
# truth — breadcrumbs/__init__.py `__version__` — so there is nothing to hand-sync.
# Imported lazily inside get_version() to avoid an import cycle: breadcrumbs/__init__
# imports this module, so `from breadcrumbs import __version__` at module load time
# could observe a partially-initialized package.

# Non-git fallback sentinels.
# Used everywhere git-derived fields cannot be populated.
NO_GIT_BRANCH = "(no-git)"
NO_GIT_COMMIT = "(no-git)"

# --------------------------------------------------------------------------- #
# Output safety (W1)
# --------------------------------------------------------------------------- #
#
# A Windows console defaults to cp1252, which cannot encode the ✓/✗ result
# markers. `print` then raised UnicodeEncodeError *mid-line*, so `validate` and
# `scan-secrets` printed their summary ("12 possible secret(s) found") and lost
# every per-item detail — the payload that says *which* twelve. The exit codes
# were right and the diagnosis was gone, which is the worst shape a failure can
# take: undiagnosable without knowing to re-run under PYTHONIOENCODING=utf-8.
#
# Two independent guards, because either alone still loses something:
#   * `reconfigure(errors="replace")` makes any stray non-ASCII (an em dash in a
#     record body, a path with an accent) degrade to `?` instead of raising. No
#     line is ever lost, whatever it holds.
#   * ASCII markers when the stream cannot encode the glyphs, so the common case
#     reads as `[x]` / `[ok]` rather than a row of `?`.
#
# A tool must never lose its diagnostic payload to a decorative glyph.
MARK_PASS = "✓"
MARK_FAIL = "✗"
_ASCII_MARK_PASS = "[ok]"
_ASCII_MARK_FAIL = "[x]"


def _stream_encodes(stream, text: str) -> bool:
    """Can `stream` encode `text` without loss? True for str-only sinks."""
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        # io.StringIO (and the test suite's capture buffers) hold `str`; there is
        # no encoding step to fail.
        return True
    try:
        text.encode(encoding, errors="strict")
    except (UnicodeEncodeError, LookupError):
        return False
    except Exception:  # pragma: no cover - a stream lying about its encoding
        return False
    return True


def configure_output(stream=None) -> None:
    """Make stdout total: never raise on encoding, and pick markers it can print.

    Called once from `main()`. Idempotent, and safe on any stream shape — a
    stream with no `reconfigure` (a pipe wrapper, a test buffer) just keeps the
    marker probe.
    """
    global MARK_PASS, MARK_FAIL
    stream = sys.stdout if stream is None else stream
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError, TypeError):  # pragma: no cover - stream-dependent
            pass
    if _stream_encodes(stream, MARK_PASS + MARK_FAIL):
        MARK_PASS, MARK_FAIL = "✓", "✗"
    else:
        MARK_PASS, MARK_FAIL = _ASCII_MARK_PASS, _ASCII_MARK_FAIL


# The first token of every error line (C2). Loud, greppable and machine-stable:
# agents pipe output through `head`/`tail` to bound its size, which scrolls an
# argparse usage block away and leaves the echoed prose behind, reading as
# success. A caller can now grep one fixed string to know a run failed even when
# it holds a truncated fragment of the output — and `$?` after a pipe is the
# pipe's status, not ours, so the text has to carry the fact by itself.
ERROR_PREFIX = "CRUMB-ERROR:"

# Same contract for the non-fatal half: input we accepted but changed.
WARN_PREFIX = "CRUMB-WARN:"

# Markers delimiting the block Breadcrumbs manages inside the project .gitignore.
# Anything between them is rewritten by `init`; everything else is preserved.
GITIGNORE_BEGIN = "# >>> breadcrumbs managed block (managed by `crumb init`) >>>"
GITIGNORE_END = "# <<< breadcrumbs managed block <<<"

VALID_SESSION_TRACKING = ("full", "distillate")

# Record vocabularies.
VALID_STATUS = (
    "active",
    "superseded",
    "stale",
    "disputed",
    "rejected",
    "quarantined",
)
VALID_PRIVACY = ("repo-safe", "local-private", "secret-prohibited")

# Open-question vocabulary. A question has its own lifecycle for the same reason
# a verification's `outcome` is not its `status`: the record words do not fit.
# The dominant way a question retires is that somebody *answered* it, and no
# lifecycle value says that — forcing `stale` onto an answered question would
# record the opposite of what happened. Only `open` is live; every reader
# already treats anything else as settled.
VALID_QUESTION_STATUS = (
    "open",
    "answered",  # resolved — the answer exists (name it in --reason)
    "closed",  # retired without an answer: withdrawn, obsolete, won't pursue
)
# What `mark-status` accepts on the command line. The id decides which
# vocabulary actually applies; the resolver rejects a mismatch by name.
MARK_STATUS_CHOICES = tuple(dict.fromkeys(VALID_STATUS + VALID_QUESTION_STATUS))

# Directory name -> record type.
DIR_TYPES = {
    "decisions": "decision",
    "attempts": "attempt",
    "sessions": "session",
    "ideas": "idea",
    "verifications": "verification",
}

# Record type -> id prefix.
TYPE_PREFIX = {
    "decision": "dec",
    "attempt": "att",
    "idea": "idea",
    "session": "ses",
    "trap": "trap",
    "question": "q",
    "verification": "ver",
}

# Verification outcome vocabulary. The record-level `status` stays the
# lifecycle value (active/superseded/…); the *finding about reality* lives in the
# `outcome` frontmatter field so it never collides with the lifecycle status.
VALID_VERIFICATION_OUTCOME = (
    "fixed",
    "open",
    "regressed",
    "not_applicable",
    "inconclusive",
)
# Outcomes that still need attention. `active_verifications` sorts these first,
# and guard treats a verification carrying one as live — the rest
# (fixed, not_applicable) are settled and only ever mentioned as history.
ACTIONABLE_VERIFICATION_OUTCOMES = ("open", "regressed", "inconclusive")
# Verification method vocabulary (how the subject was checked).
VALID_VERIFICATION_METHOD = ("static", "runtime", "test")

# Singleton core files that must exist.
CORE_FILES = ("current.md", "handoff.md", "open-questions.md", "known-traps.md")

# Frontmatter keys every durable directory record must carry.
# id/slug are derived from the filename (§7), so they are not required here.
REQUIRED_RECORD_KEYS = ("title", "status", "created_at", "privacy")


class _LazyPattern:
    """A `re.Pattern` stand-in that compiles the first time it is actually used.

    The secret-shape and instruction-like tables are the bulk of this module's
    top-level `re.compile` calls — ~3.5 ms of the ~7.5 ms module body —
    and only `audit`/`scan_secrets` ever touch them. Every other invocation,
    including the `hook guard` pre-filter that runs on every tool call, was
    paying for them. Attribute access proxies to the real pattern, so `.search`,
    `.finditer`, `.pattern` and friends behave exactly as before.
    """

    __slots__ = ("_spec", "_compiled")

    def __init__(self, pattern: str, flags: int = 0) -> None:
        self._spec = (pattern, flags)
        self._compiled: "re.Pattern[str] | None" = None

    @property
    def compiled(self) -> "re.Pattern[str]":
        if self._compiled is None:
            self._compiled = re.compile(*self._spec)
        return self._compiled

    def __getattr__(self, name: str):
        return getattr(self.compiled, name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<lazy re {self._spec[0]!r}>"


# Filename of a directory record: <YYYY-MM-DD>-<slug>.md
#
# The slug is restricted to the charset `slugify` emits — lowercase alphanumerics
# in `-`-joined runs. It used to be `(.+)`, which accepted `9999-99-99-My Slug!.md`
# and derived the id `dec_99999999_My Slug!`: spaces and punctuation inside an
# exact-match key. Writers always emit clean names; validate exists for the
# hand-created files where this matters.
RECORD_STEM_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)$")

# Marker every generated projection carries.
GENERATED_MARKER = "GENERATED PROJECTION"

# Session "Next Action or convergence" markers.
SESSION_DONE_MARKERS = ("converged", "session complete", "no next action", "done")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def write_text_atomic(path: Path, text: str) -> None:
    """Write text via tmp-file + rename in the destination directory.

    A plain `write_text` interrupted mid-write leaves a truncated record that
    validate then reports as corrupt; `os.replace` is atomic on
    the same filesystem, so readers see either the old file or the new one.
    """
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def read_text_lenient(path: Path) -> tuple[str, str | None]:
    """Read a memory file without ever raising: returns (text, problem).

    `problem` is None on a clean read; otherwise it is a human-readable reason —
    an OS error (text is then ""), or invalid UTF-8, in which case the text is
    still returned with the bad bytes replaced so the caller can do its job on
    what is readable. Callers decide whether that reason is a blocking finding, a
    warning, or noise; what none of them may do is die on it or silently skip it
    (one bad byte used to abort `audit` entirely and exempt a whole file from
    the secret scan).

    Callers are responsible for naming the offending path: `problem` is
    path-free so it can go in a finding that carries `path` separately.
    """
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return "", f"unreadable file: {exc}"
    try:
        return raw.decode("utf-8-sig"), None
    except UnicodeDecodeError as exc:
        return raw.decode("utf-8-sig", errors="replace"), (
            f"invalid UTF-8 at byte {exc.start} ({exc.reason}) — read with replacement "
            "characters, so anything derived from it is unreliable"
        )


def now_iso() -> str:
    """Local time, ISO-8601, timezone-aware (e.g. 2026-06-25T14:30:00-05:00)."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


# Memo for `is_git_repo`, keyed by (path, does `.git` exist there) so the answer is
# re-probed the moment that changes — `git init` after a negative probe re-keys the
# entry instead of returning a stale False. Five of one guard call's ten remaining
# subprocess spawns were this same question asked five times; a stat is
# ~1000x cheaper than a process, and much more so on Windows.
_IS_GIT_REPO_CACHE: dict[tuple[str, bool], bool] = {}


def is_git_repo(root: Path) -> bool:
    """True if `root` is inside a git work tree."""
    key = (str(root), (Path(root) / ".git").exists())
    cached = _IS_GIT_REPO_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
        answer = result.returncode == 0 and result.stdout.strip() == "true"
    except (FileNotFoundError, OSError):
        answer = False
    _IS_GIT_REPO_CACHE[key] = answer
    return answer


def derive_project_name(root: Path) -> str:
    """Project name = the resolved directory name of the project root."""
    name = root.name
    return name if name else "project"


def resolve_root(project_arg: str | None) -> Path:
    """Resolve the project root: --project overrides cwd."""
    return (Path(project_arg) if project_arg else Path.cwd()).resolve()


# --------------------------------------------------------------------------- #
# Manifest + .gitignore writers
# --------------------------------------------------------------------------- #


def manifest_content(
    project: str, created_at: str, session_tracking: str, commit_generated: bool
) -> str:
    """Render manifest.yml with the policies chosen at init time (§7)."""
    return (
        f"schema_version: {SCHEMA_VERSION}\n"
        f"created_at: {created_at}\n"
        f"project: {project}\n"
        f"# Tracking policy chosen during `crumb init` (see docs/record-schema.md):\n"
        f"session_tracking: {session_tracking}        # full | distillate\n"
        f"#   full       = commit dated session records under sessions/\n"
        f"#   distillate = sessions/ stays local; commit only promoted decisions/attempts\n"
        f"commit_generated_projections: {str(commit_generated).lower()}"
        f"   # commit generated/*.md summaries (indexes always ignored)\n"
        f"extraction_prompt: true   # Stop hook may ask the agent (once per new-commit\n"
        f"#   turn) to write decision/attempt records before ending; false = snapshot only\n"
    )


def gitignore_block(session_tracking: str, commit_generated: bool) -> str:
    """Build the managed .gitignore block matching the chosen policies (§5)."""
    lines: list[str] = [GITIGNORE_BEGIN]
    # private notes are never committed
    lines.append(f"{MEMORY_DIRNAME}/private/**")
    # disposable index is never committed (except its README)
    lines.append(f"{MEMORY_DIRNAME}/index/**")
    lines.append(f"!{MEMORY_DIRNAME}/index/README.md")
    # local/tmp generated projections are never committed
    lines.append(f"{MEMORY_DIRNAME}/generated/*.local.md")
    lines.append(f"{MEMORY_DIRNAME}/generated/*.tmp")
    if not commit_generated:
        # flip generated projections to local-only, but keep the explainer README.
        # *.json covers guard-prefilter.json, which is a projection like any other
        # (rebuilt on every write) and used to escape this policy entirely — the
        # user asked for local-only projections and got a tracked, churning one.
        lines.append(f"{MEMORY_DIRNAME}/generated/*.md")
        lines.append(f"{MEMORY_DIRNAME}/generated/*.json")
        lines.append(f"!{MEMORY_DIRNAME}/generated/README.md")
    if session_tracking == "distillate":
        # sessions stay local; only promoted decisions/attempts are committed
        lines.append(f"{MEMORY_DIRNAME}/sessions/")
    lines.append(GITIGNORE_END)
    return "\n".join(lines) + "\n"


def rewrite_managed_block(path: Path, begin: str, end: str, block: str | None) -> bool:
    """Insert, replace, or remove a fenced managed block in a text file.

    Idempotent. `block` (when given) must contain the `begin` and `end` marker
    lines; only the region between the markers is rewritten, so surrounding user
    content is preserved. Pass `block=None` (or "") to strip the managed block,
    leaving everything else intact. The comment style lives in the markers, so the
    same surgery works for `.gitignore` (`#`) and Markdown adapters (`<!-- -->`).

    Returns True iff the file's content actually changed — an already-current
    block is a no-op (no write, no mtime churn), and callers report it as such
    instead of claiming an update they did not make (P2-12).
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else ""

    if begin in existing and end in existing:
        head, _, rest = existing.partition(begin)
        _, _, tail = rest.partition(end)
        # tail starts right after the END marker; drop a leading newline if present
        tail = tail[1:] if tail.startswith("\n") else tail
        head = head.rstrip("\n")
        if not block:
            # Removal: stitch head and tail back together without the block.
            if head and tail.strip():
                new_content = head + "\n\n" + tail.lstrip("\n")
            elif head:
                new_content = head + "\n"
            else:
                new_content = tail.lstrip("\n")
        else:
            prefix = (head + "\n\n") if head else ""
            new_content = prefix + block + (tail if tail.strip() else "")
    else:
        if not block:
            return False  # nothing to remove
        sep = "" if (not existing or existing.endswith("\n")) else "\n"
        prefix = (existing + sep + "\n") if existing.strip() else ""
        new_content = prefix + block

    if path.exists() and new_content == existing:
        return False
    path.write_text(new_content, encoding="utf-8")
    return True


def write_gitignore(root: Path, block: str) -> None:
    """Insert/replace the breadcrumbs-managed block in the project .gitignore.

    Idempotent: re-running init rewrites only the managed block and leaves any
    user content intact. Thin wrapper over `rewrite_managed_block`.
    """
    rewrite_managed_block(root / ".gitignore", GITIGNORE_BEGIN, GITIGNORE_END, block)


def merge_json_file(path: Path, mutate) -> None:
    """Load a JSON object (or {} if absent/empty), apply `mutate` in place, write back.

    Used for `.mcp.json` and `.claude/settings.json`, which cannot carry comment
    markers. Sibling keys are preserved; output is 2-space-indented with a trailing
    newline. Raises ValueError on unparseable or non-object JSON rather than
    clobbering a file we do not understand.
    """
    if path.exists():
        text = path.read_text(encoding="utf-8")
        try:
            data = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError as exc:
            raise ValueError(f"cannot parse JSON at {path}: {exc}") from exc
    else:
        data = {}
    if not isinstance(data, dict):
        raise ValueError(f"expected a JSON object at {path}, found {type(data).__name__}")
    # Snapshot-compare so a semantic no-op never rewrites the file: a rewrite
    # reformats entries this tool does not own (P2-13), and "we changed nothing"
    # should leave no diff at all.
    before = json.dumps(data, sort_keys=True)
    mutate(data)
    if path.exists() and json.dumps(data, sort_keys=True) == before:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #


def copy_template_tree(dest: Path) -> None:
    """Copy templates/project-memory/** into dest."""
    if not TEMPLATE_DIR.is_dir():
        raise FileNotFoundError(
            f"template tree not found at {TEMPLATE_DIR}; is the package intact?"
        )
    shutil.copytree(TEMPLATE_DIR, dest, dirs_exist_ok=True)


def prompt_session_tracking(non_interactive_default: str = "full") -> str:
    """Ask the human for the session-tracking policy; default for non-tty."""
    # Same gate as every other prompt: both ends must be a terminal.
    if not _interactive():
        return non_interactive_default
    prompt = (
        "Session-tracking policy:\n"
        "  [full]       commit dated session records (good for solo multi-device)\n"
        "  [distillate] keep sessions/ local; commit only decisions/attempts (lean team repo)\n"
        "Choose [full/distillate] (default: full): "
    )
    try:
        answer = input(prompt).strip().lower()
    except EOFError:
        return non_interactive_default
    # Ctrl+C propagates: aborting the policy question must abort `init`, not
    # silently pick `full` and scaffold a store the user did not agree to.
    if answer in VALID_SESSION_TRACKING:
        return answer
    return non_interactive_default


def cmd_init(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME

    if not root.exists():
        _emit_error(args, f"project root does not exist: {root}")
        return 2

    if not root.is_dir():
        _emit_error(args, f"project root is not a directory: {root}")
        return 2

    # Integration flags are validated here, before *any* filesystem mutation —
    # before the scaffold swap, before .gitignore, before a single adapter edit.
    # Validating inside apply_integrations would still leave a half-initialized
    # project behind on a typo.
    problem = validate_integration_flags(args)
    if problem:
        _emit_error(args, problem)
        return 2

    # Standalone integration operations: they act on an existing project and never
    # scaffold, so they run before the "store already exists" guard below.
    if getattr(args, "remove_integrations", False):
        removed = remove_integrations(root)
        if args.json:
            _print_json(args, {"removed": removed, "items": removed})
        else:
            hooks = removed["hooks"]
            touched = removed["adapters"] or removed["mcp"] or hooks["removed"]
            print("Removed breadcrumbs integrations:" if touched else "No integrations to remove.")
            if removed["adapters"]:
                print(f"  adapter blocks: {', '.join(removed['adapters'])}")
            if removed["mcp"]:
                print("  .mcp.json: breadcrumbs server entry removed")
            if hooks["removed"]:
                print(f"  .claude/settings.json: {len(hooks['removed'])} crumb hook(s) removed")
            # Never let a partial uninstall read as a clean one. An
            # unmarked entry is left in place on purpose — say so, and say
            # how to finish, rather than deleting a hook we cannot prove is ours.
            if hooks["left"]:
                print(
                    f"  .claude/settings.json: {len(hooks['left'])} hook(s) LEFT IN PLACE — they "
                    f"look like crumb hooks but carry no `{HOOK_MARKER}` marker, so breadcrumbs "
                    "cannot prove it wrote them:"
                )
                for command in hooks["left"]:
                    print(f"      {command}")
                print(
                    "    Remove them by hand, or run `crumb init --with-hooks` to adopt them "
                    "(stamps the marker) and re-run this command."
                )
        return 0

    if getattr(args, "print_integrations", False):
        plan = resolve_integration_plan(root, args)
        if args.json:
            _print_json(args, {"would_apply": plan})
        else:
            print("Integrations that would be applied:")
            print(f"  adapter signpost -> {_fmt_adapter_targets(root, plan['adapters'])}")
            print(f"  MCP register     -> {'yes' if plan['mcp'] else 'no'}")
            print(f"  Claude hooks     -> {', '.join(plan['hooks']) or '(none)'}")
            note = _adapter_request_note(args, plan["adapters"])
            if note:
                print(f"  note: {note}")
        return 0

    if memory_dir.exists() and not args.force:
        # Integrations-only mode: wiring an agent into an
        # *existing* store must never require --force — --force replaces the
        # scaffold and destroys every record. When any integration flag is
        # given explicitly, apply just those and leave the store untouched.
        integrations_requested = any(
            getattr(args, k, None) is not None for k in ("adapter", "mcp", "hooks")
        )
        if integrations_requested:
            plan = resolve_integration_plan(root, args)
            applied = apply_integrations(root, plan)
            # P2-14: wiring an agent in is exactly when a fresh packet is needed
            # next; leaving the old one stale meant `doctor` could not go green
            # until a manual `crumb resume`.
            try_reindex_projections(memory_dir, root)
            if args.json:
                _print_json(args, {"store": "existing", "integrations": applied})
            else:
                print(f"{MEMORY_DIRNAME}/ already present — store left untouched.")
                print("Applied integrations:")
                print(f"  adapter signpost -> {_fmt_applied_adapters(applied) or '(none)'}")
                print(f"  MCP register     -> {_fmt_applied_mcp(applied)}")
                print(f"  Claude hooks     -> {', '.join(applied['hooks']) or '(none)'}")
                note = _adapter_request_note(args, applied["adapters"])
                if note:
                    print(f"  note: {note}")
            return 0
        _emit_error(
            args,
            f"{MEMORY_DIRNAME}/ already exists at {root}. "
            f"To wire integrations into it, pass --with-adapter/--with-mcp/--with-hooks "
            f"(no --force needed). --force replaces the scaffold and DELETES all "
            f"existing records.",
        )
        return 1

    # Resolve policies.
    if args.session_tracking:
        session_tracking = args.session_tracking
    else:
        session_tracking = prompt_session_tracking()
    commit_generated = not args.no_commit_generated

    # Non-git detection (notice only; gitignore is still written for later git init).
    git_present = is_git_repo(root)

    # Build the new scaffold in a staging dir and swap it in. An existing store
    # (--force) is destroyed only after the replacement is fully built, so a
    # missing template or a mid-build failure can never leave the project with a
    # half-written or deleted .project-memory/.
    project = derive_project_name(root)
    created_at = now_iso()
    staging = root / (MEMORY_DIRNAME + ".new")
    if staging.exists():
        shutil.rmtree(staging)
    try:
        copy_template_tree(staging)
        (staging / "manifest.yml").write_text(
            manifest_content(project, created_at, session_tracking, commit_generated),
            encoding="utf-8",
        )
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    if memory_dir.exists():
        shutil.rmtree(memory_dir)
    staging.rename(memory_dir)

    block = gitignore_block(session_tracking, commit_generated)
    write_gitignore(root, block)

    # Bootstrap agent integrations. Resolution prompts on a TTY when
    # unspecified and is a silent no-op non-interactively, so default `crumb init`
    # behavior is unchanged. Every edit is fenced/reversible (`--remove-integrations`).
    plan = resolve_integration_plan(root, args)
    applied = apply_integrations(root, plan)

    # Build the projections so `doctor` can be green immediately after init
    # (P2-14: it used to report the resume packet stale/absent until the first
    # manual `crumb resume`). Best-effort like every other reindex.
    try_reindex_projections(memory_dir, root)

    summary = {
        "created": str(memory_dir),
        "project": project,
        "created_at": created_at,
        "schema_version": SCHEMA_VERSION,
        "session_tracking": session_tracking,
        "commit_generated_projections": commit_generated,
        "gitignore": str(root / ".gitignore"),
        "git_repo": git_present,
        "integrations": applied,
    }
    note = _adapter_request_note(args, plan["adapters"])
    if note:
        summary["integration_note"] = note
    if not git_present:
        summary["git_notice"] = (
            f"no git repo detected; git-derived record fields will use sentinels "
            f"branch={NO_GIT_BRANCH!r}, commit={NO_GIT_COMMIT!r}, dirty_files=[]"
        )

    _emit_init_summary(args, summary)
    return 0


def _fmt_applied_adapters(applied: dict) -> str:
    """Render adapter targets with what actually happened to each (P2-12)."""
    states = applied.get("adapter_states") or {}
    return ", ".join(
        f"{name} ({states[name]})" if name in states else name
        for name in applied.get("adapters") or []
    )


def _fmt_applied_mcp(applied: dict) -> str:
    if not applied.get("mcp"):
        return "no"
    state = applied.get("mcp_state")
    return f"yes ({state})" if state else "yes"


def _emit_init_summary(args: argparse.Namespace, summary: dict) -> None:
    if args.json:
        _print_json(args, summary)
        return
    print(f"Initialized {summary['created']}")
    print(f"  project:                       {summary['project']}")
    print(f"  schema_version:                {summary['schema_version']}")
    print(f"  session_tracking:              {summary['session_tracking']}")
    print(f"  commit_generated_projections:  {summary['commit_generated_projections']}")
    print(f"  .gitignore:                    {summary['gitignore']}")
    integ = summary.get("integrations") or {}
    if integ.get("adapters") or integ.get("mcp") or integ.get("hooks"):
        print("  integrations:")
        if integ.get("adapters"):
            print(f"    adapter signpost:            {_fmt_applied_adapters(integ)}")
        if integ.get("mcp"):
            state = f" ({integ['mcp_state']})" if integ.get("mcp_state") else ""
            print(f"    MCP registered:              {integ['mcp']}{state}")
        if integ.get("hooks"):
            print(f"    Claude hooks:                {', '.join(integ['hooks'])}")
    else:
        print("\n" + FIRST_RUN_NUDGE)
    if summary.get("integration_note"):
        print(f"\nnote: {summary['integration_note']}")
    if not summary["git_repo"]:
        print(f"\nNotice: {summary['git_notice']}")
    if args.verbose:
        print("\nNext: `crumb resume` to load context; `crumb doctor` to check wiring.")


# Namespace attributes that name the sub-position of a command, outermost first.
# `crumb note trap --body ...` failed with a bare `crumb:` prefix, which does not
# say which of twenty subcommands rejected the flag.
_COMMAND_PATH_DESTS = (
    "command",
    "record_type",
    "note_kind",
    "capture_what",
    "mcp_what",
    "hook_event",
)


def command_label(args: argparse.Namespace) -> str:
    """`crumb note trap` — the fully-qualified subcommand that is speaking."""
    parts = ["crumb"]
    for dest in _COMMAND_PATH_DESTS:
        value = getattr(args, dest, None)
        if isinstance(value, str) and value:
            parts.append(value)
    return " ".join(parts)


# Keys under which commands already return their result list. `--json` grew one
# command at a time and every command invented its own name, so two commands
# doing the same shape of job — run N checks, report failures — disagreed on what
# to call the answer: `scan-secrets` returns `hits`, `validate` returns
# `findings`, `search` returns `matches`, `guard` a third shape again. Every
# consumer needed a per-subcommand adapter, and the failure mode is silent: a
# defensive `d.get("findings", [])` against `scan-secrets` reports zero problems
# rather than raising. `items` now aliases whichever of these a command emits, so
# one reader works everywhere; the original keys stay exactly where they were.
_JSON_ITEM_ALIASES = (
    "items",
    "findings",
    "hits",
    "matches",
    "checks",
    "records",
    "entries",
    "results",
)


def _print_json(
    args: argparse.Namespace,
    payload: dict,
    *,
    ok: bool | None = None,
    summary: dict | None = None,
) -> None:
    """Print one command's `--json` document inside the shared envelope (C4).

    Additive by construction: `ok`, `command`, `summary` and `items` are added or
    filled in, and every key the command already returned is preserved. `items`
    is always present — an empty list when the command has no item list — so a
    consumer can read it without knowing which command it is talking to.
    """
    payload = dict(payload)
    items = payload.get("items")
    if not isinstance(items, list):
        items = next(
            (payload[k] for k in _JSON_ITEM_ALIASES if isinstance(payload.get(k), list)), []
        )
    doc: dict = {
        "ok": payload.pop("ok", True) if ok is None else ok,
        "command": payload.pop("command", None) or command_label(args),
    }
    summary = summary if summary is not None else payload.pop("summary", None)
    if summary is not None:
        doc["summary"] = summary
    doc["items"] = items
    payload.pop("items", None)
    doc.update(payload)
    print(json.dumps(doc, indent=2))


def _emit_warning(args: argparse.Namespace, message: str) -> None:
    """A non-fatal note about input we accepted but changed (C1).

    stderr, and marked, for the same reason errors are: the command succeeded, so
    stdout carries the result and a caller parsing it must not find prose in it.
    """
    if not getattr(args, "json", False):
        print(f"{WARN_PREFIX} {command_label(args)}: {message}", file=sys.stderr)


def _emit_error(args: argparse.Namespace, message: str) -> None:
    if getattr(args, "json", False):
        print(
            json.dumps(
                {"ok": False, "command": command_label(args), "items": [], "error": message},
                indent=2,
            )
        )
    else:
        print(f"{ERROR_PREFIX} {command_label(args)}: {message}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Frontmatter parser (stdlib-only subset of YAML)
# --------------------------------------------------------------------------- #
#
# Supports exactly the shapes the record schema uses:
#   key: scalar          -> str
#   key: null  | key:    -> None
#   key: []              -> []   (inline empty list)
#   key:                 -> block list of scalars (`- item`) OR
#                           block list of maps (`- type: commit` / `  ref: ...`)
# ISO-8601 datetimes are preserved verbatim as strings (no tz math here).
#
# Schema convention vs published JSON Schema: resolved for now as
# *convention-in-code* — these deterministic checks ARE the schema. A published
# JSON Schema is deferred until the format stabilizes during dogfood.


class FrontmatterError(ValueError):
    """Raised when a record's frontmatter is malformed."""


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _has_tab_indent(line: str) -> bool:
    """True if the line's leading whitespace contains a tab.

    `_indent` counts only spaces, so a tab-indented line would otherwise read as
    un-indented and trip a misleading "expected 'key: value'" / "unexpected
    indentation" error. YAML forbids tabs for indentation, so we say so plainly.
    """
    return "\t" in line[: len(line) - len(line.lstrip())]


def _strip_inline_comment(val: str) -> str:
    """Drop a ` # ...` trailing comment from an unquoted scalar (YAML convention)."""
    if " #" in val:
        return val.split(" #", 1)[0].strip()
    return val


def _parse_scalar(val: str):
    """Parse a scalar frontmatter value into str / None / []."""
    val = val.strip()
    if val == "":
        return None
    if val[0] == "'":
        # Single-quoted scalar: a doubled `''` is an escaped quote (YAML), so a
        # value containing both quote kinds round-trips. Content
        # runs to the matching close; anything after it (e.g. a ` # comment`) is
        # ignored. An unterminated quote falls through to literal.
        buf: list[str] = []
        i = 1
        while i < len(val):
            if val[i] == "'":
                if i + 1 < len(val) and val[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                return "".join(buf)
            buf.append(val[i])
            i += 1
    elif val[0] == '"':
        # Double-quoted scalar: content up to the matching closing quote; a `#`
        # inside the quotes is preserved, anything after the close is ignored.
        end = val.find('"', 1)
        if end != -1:
            return val[1:end]
    val = _strip_inline_comment(val)
    if val.startswith("#"):
        # A comment-only value (`superseded_by: # none yet`). `_strip_inline_comment`
        # needs a space before the `#`, so this used to survive as the literal
        # string "# none yet" — truthy garbage that passed validate §16.6's
        # "superseded needs a superseded_by" check. YAML reads it as null; so do we.
        return None
    if val in ("null", "~"):
        return None
    if val == "[]":
        return []
    return val


def _is_map_item(after_dash: str) -> bool:
    """A list item is a map if it looks like `key: value` or `key:`.

    A quoted item is always a scalar, even if it contains `: ` — otherwise a
    tag like `"area: backend"` would be misread as a {key: value} map.
    """
    if after_dash[:1] in "\"'":
        return False
    return ": " in after_dash or after_dash.endswith(":")


def _parse_list(lines: list[str]) -> list:
    """Parse the child lines under a `key:` header into a list of scalars/maps."""
    items: list = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if _has_tab_indent(line):
            raise FrontmatterError(f"tabs are not allowed for indentation (use spaces): {line!r}")
        stripped = line.strip()
        if not stripped.startswith("-"):
            raise FrontmatterError(f"expected list item, got: {line!r}")
        after = stripped[1:].strip()
        if after and _is_map_item(after):
            item: dict = {}
            base_indent = _indent(line)
            key, _, raw_val = after.partition(":")
            item[key.strip()] = _parse_scalar(raw_val.strip())
            i += 1
            # Gather continuation lines (more indented than the dash, not a new item).
            while i < n:
                cont = lines[i]
                if not cont.strip():
                    i += 1
                    continue
                if cont.strip().startswith("-") or _indent(cont) <= base_indent:
                    break
                cstr = cont.strip()
                if ":" not in cstr:
                    raise FrontmatterError(f"expected 'key: value' in map item: {cont!r}")
                k, _, v = cstr.partition(":")
                item[k.strip()] = _parse_scalar(v.strip())
                i += 1
            items.append(item)
        else:
            items.append(_parse_scalar(after))
            i += 1
    return items


def _parse_mapping(lines: list[str]) -> dict:
    """Parse top-level frontmatter lines into a dict (flat, with list values)."""
    meta: dict = {}
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        if not raw.strip() or raw.lstrip().startswith("#"):
            i += 1
            continue
        if _has_tab_indent(raw):
            raise FrontmatterError(f"tabs are not allowed for indentation (use spaces): {raw!r}")
        if _indent(raw) != 0:
            raise FrontmatterError(f"unexpected indentation at top level: {raw!r}")
        stripped = raw.rstrip()
        if ":" not in stripped:
            raise FrontmatterError(f"expected 'key: value', got: {raw!r}")
        key, _, val = stripped.partition(":")
        key = key.strip()
        val = val.strip()
        if val == "":
            # Block list (or empty value): gather following indented lines.
            block: list[str] = []
            j = i + 1
            while j < n and (not lines[j].strip() or _indent(lines[j]) > 0):
                block.append(lines[j])
                j += 1
            non_blank = [b for b in block if b.strip() and not b.lstrip().startswith("#")]
            meta[key] = _parse_list(block) if non_blank else None
            i = j
        else:
            meta[key] = _parse_scalar(val)
            i += 1
    return meta


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a record into (frontmatter dict, body str).

    A document with no leading `---` fence has empty frontmatter and is returned
    verbatim as the body. An opened-but-unterminated fence is malformed.
    """
    if text.startswith("﻿"):
        # A UTF-8 BOM survives str.strip(), so it would mask the opening fence
        # and silently drop the whole frontmatter. Strip a single leading BOM.
        text = text[1:]
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    close = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            close = idx
            break
    if close is None:
        raise FrontmatterError("unterminated frontmatter (missing closing '---')")
    meta = _parse_mapping(lines[1:close])
    body = "\n".join(lines[close + 1 :])
    return meta, body


# --------------------------------------------------------------------------- #
# Record identity — filename-canonical
# --------------------------------------------------------------------------- #


def derive_identity(stem: str, rtype: str) -> tuple[str, str] | None:
    """From a record filename stem `<YYYY-MM-DD>-<slug>`, compute (id, slug).

    Returns None if the stem doesn't match the canonical pattern (caller flags it).
    The date must be a real calendar date: `2026-02-30` and `9999-99-99` are shaped
    like dates but name no day, and an id built from one sorts and reads as if it
    did.
    """
    m = RECORD_STEM_RE.match(stem)
    if not m:
        return None
    y, mo, d, slug = m.groups()
    try:
        date(int(y), int(mo), int(d))
    except ValueError:
        return None
    prefix = TYPE_PREFIX.get(rtype, rtype)
    rid = f"{prefix}_{y}{mo}{d}_{slug}"
    return rid, slug


# --------------------------------------------------------------------------- #
# Record model + loader
# --------------------------------------------------------------------------- #


class Record:
    """A loaded `.md` record: path, type, frontmatter, body, parse error (if any)."""

    def __init__(
        self,
        path: Path,
        rtype: str,
        meta: dict | None = None,
        body: str = "",
        error: str | None = None,
    ):
        self.path = Path(path)
        self.rtype = rtype
        self.meta = meta or {}
        self.body = body
        self.error = error

    @classmethod
    def from_file(cls, path: Path, rtype: str) -> "Record":
        # utf-8-sig transparently consumes a BOM. A decode failure or any OS
        # error (binary file, directory, broken symlink, permissions) is captured
        # as a Record error — never raised — so a single bad file can't crash the
        # walk that load_records()/validate run over the whole store.
        try:
            text = Path(path).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError) as exc:
            return cls(path, rtype, meta=None, body="", error=f"unreadable file: {exc}")
        try:
            meta, body = parse_frontmatter(text)
        except FrontmatterError as exc:
            return cls(path, rtype, meta=None, body="", error=str(exc))
        return cls(path, rtype, meta=meta, body=body)

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def sections(self) -> dict[str, str]:
        """Split the body into {heading: text} on `## ` headings (reused by resume/guard).

        Delegates to `split_md_sections` so there is exactly one splitter in the
        codebase. This used to be a second, fence-blind copy: a
        record body whose fenced code block contained `## Next Action` — routine
        for `--set 'Commands / Verification' …` — reported a section that does not
        exist, so validate §16.10 false-passed a session with no real Next Action,
        guard cited torn text, and content after the fake heading vanished.
        """
        return split_md_sections(self.body)


def load_records(memory_dir: Path, types: tuple[str, ...] | None = None) -> list[Record]:
    """Load every directory record under decisions/attempts/sessions/ideas.

    Parse errors are captured on the Record (`.error`), not raised, so `validate`
    can report them as findings. Singleton core files are NOT durable records and
    are intentionally excluded here.
    """
    records: list[Record] = []
    for dirname, rtype in DIR_TYPES.items():
        if types and rtype not in types:
            continue
        d = Path(memory_dir) / dirname
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            records.append(Record.from_file(p, rtype))
    return records


# --------------------------------------------------------------------------- #
# Field population helpers — derive + default halves
# --------------------------------------------------------------------------- #
# Every record writer reuses these; the prompted half (title/body) is collected
# separately.


def _git_out(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    if r.returncode != 0:
        return None
    # Trailing newline only. A whole-output strip() also ate the leading space of
    # the *first* line, which for `status --porcelain` is a status column — a
    # worktree-only modification is " M path", so the caller's line[3:] then
    # chopped three characters off the path. Every other caller
    # reads single-line output or regex-matches, so both forms suit them.
    return r.stdout.rstrip("\n")


def git_branch(root: Path) -> str:
    if not is_git_repo(root):
        return NO_GIT_BRANCH
    out = _git_out(root, "rev-parse", "--abbrev-ref", "HEAD")
    if out:
        return out
    # An unborn HEAD (fresh repo, no commits yet) fails rev-parse but still has
    # a real branch name — read it so records don't pair `branch: (no-git)` with
    # populated dirty_files.
    out = _git_out(root, "symbolic-ref", "--short", "HEAD")
    return out if out else NO_GIT_BRANCH


def git_commit(root: Path) -> str:
    if not is_git_repo(root):
        return NO_GIT_COMMIT
    out = _git_out(root, "rev-parse", "--short", "HEAD")
    return out if out else NO_GIT_COMMIT


# git C-style escapes used in quoted porcelain paths (paths with spaces/quotes/
# non-ASCII are emitted as "caf\303\251.txt"; octal escapes are raw UTF-8 bytes).
_GIT_PATH_ESCAPES = {
    "n": 0x0A,
    "t": 0x09,
    "r": 0x0D,
    '"': 0x22,
    "\\": 0x5C,
    "a": 0x07,
    "b": 0x08,
    "f": 0x0C,
    "v": 0x0B,
}


def _unquote_git_path(path: str) -> str:
    """Decode git's C-style quoted path form back to the real path.

    Unquoted paths pass through unchanged. Storing the quoted form verbatim
    persisted strings like '"caf\\303\\251.txt"' into frontmatter, which could
    then trip the R3 round-trip refusal on a later status change.
    """
    if not (len(path) >= 2 and path[0] == '"' and path[-1] == '"'):
        return path
    body = path[1:-1]
    out = bytearray()
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "\\" and i + 1 < len(body):
            nxt = body[i + 1]
            if nxt in _GIT_PATH_ESCAPES:
                out.append(_GIT_PATH_ESCAPES[nxt])
                i += 2
                continue
            if nxt in "01234567":
                val, j = 0, 0
                while j < 3 and i + 1 + j < len(body) and body[i + 1 + j] in "01234567":
                    val = val * 8 + int(body[i + 1 + j])
                    j += 1
                out.append(val)
                i += 1 + j
                continue
        out.extend(ch.encode("utf-8"))
        i += 1
    return out.decode("utf-8", errors="replace")


# A record's `dirty_files` is capped here. In the field store the *shortest*
# session record listed 32 paths and the longest 49; a list that long is not
# read, and the tail of it is not information. The count of what was dropped is.
DIRTY_FILES_MAX = 25
DIRTY_FILES_OVERFLOW = "… +{n} more"


def _cap_dirty_files(files: list[str]) -> list[str]:
    """Keep the first `DIRTY_FILES_MAX` paths; say how many were dropped."""
    if len(files) <= DIRTY_FILES_MAX:
        return files
    return files[:DIRTY_FILES_MAX] + [DIRTY_FILES_OVERFLOW.format(n=len(files) - DIRTY_FILES_MAX)]


def git_dirty_files(root: Path, *, include_memory: bool = True) -> list[str]:
    """Uncommitted paths, relative to the repo root.

    `include_memory=False` drops the memory store's own churn (R2). Every capture
    rewrites `.project-memory/` — a new session record, handoff.md, current.md,
    the projections — and in a shared tree it also sees every *other* session's
    uncommitted records. That made 76–79% of a session's `dirty_files` the tool
    measuring its own footprint and reporting it as the session's work: one
    session that touched three source files recorded 46 paths, 36 of them other
    sessions' memory records. Callers that are asking about the *store* (the
    staleness check, the Stop-hook dedupe) keep the default.
    """
    if not is_git_repo(root):
        return []
    out = _git_out(root, "status", "--porcelain")
    if not out:
        return []
    files: list[str] = []
    for line in out.splitlines():
        # porcelain: 2 status chars + space + path
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            # rename/copy entries are "R  old -> new"; record the destination.
            path = path.split(" -> ", 1)[1].strip()
        path = _unquote_git_path(path)
        if path:
            files.append(path)
    if not include_memory:
        files = list(_work_dirty_files(files))
    return files


def current_user() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


# Environment markers that identify the agent harness a command is running under.
# Ordered: the first marker whose variable is set (to anything non-empty)
# wins. Keep this cheap — it is consulted on every record write and must not
# import anything.
AGENT_ENV_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude-code", ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")),
    ("cursor", ("CURSOR_AGENT", "CURSOR_TRACE_ID")),
    ("codex", ("CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED")),
    ("gemini", ("GEMINI_CLI", "GEMINI_SANDBOX")),
    ("opencode", ("OPENCODE", "OPENCODE_BIN_PATH")),
    ("aider", ("AIDER_CHAT",)),
)

AGENT_UNKNOWN = "unknown"


def detect_agent(fallback: str = AGENT_UNKNOWN) -> str:
    """Best-effort author label for a record written without an explicit `--agent`.

    `human` used to be the default, so anything an agent wrote through the CLI
    without passing `--agent` was attributed to a person — while the MCP surface
    recorded the same write as `agent`. In a store whose `confidence` and
    `review_status` are trust signals, "a human stood behind this" is the one
    claim a missing flag must never manufacture.

    So: name the harness when the environment names it, and otherwise return
    `unknown`. That covers CI and every unrecognised agent runner too — none of
    them are evidence of a human, and neither is a bare shell. A person who wants
    the stronger claim asserts it with `--agent human`.

    `fallback` is for the surfaces that already know an agent is calling — the
    MCP tools and the hooks pass `"agent"`, so those writes name the harness when
    the environment names it and stay honest ("agent") when it doesn't.
    """
    for label, variables in AGENT_ENV_MARKERS:
        if any(os.environ.get(var) for var in variables):
            return label
    return fallback


def derive_fields(
    project_root: Path, agent: str | None = None, *, include_memory: bool = False
) -> dict:
    """Auto-derived frontmatter fields (clock + git + environment).

    `agent=None` means "nobody said" — resolved by `detect_agent()`, never to
    `human`. `include_memory` re-admits the memory store's own churn to
    `dirty_files`; the default excludes it (see `git_dirty_files`).
    """
    root = Path(project_root)
    now = now_iso()
    return {
        "created_at": now,
        "updated_at": now,
        "created_by": current_user(),
        "agent": agent or detect_agent(),
        "project": derive_project_name(root),
        "branch": git_branch(root),
        "commit": git_commit(root),
        "dirty_files": _cap_dirty_files(git_dirty_files(root, include_memory=include_memory)),
    }


def default_fields() -> dict:
    """Defaulted, overridable frontmatter fields (constants)."""
    return {
        "status": "active",
        "confidence": "medium",
        "privacy": "repo-safe",
        "review_status": "unreviewed",
        "scope": "project",
        "tags": [],
        "supersedes": [],
        "superseded_by": None,
        "expires_at": None,
        "reviewed_by": None,
    }


# --------------------------------------------------------------------------- #
# Manifest loader
# --------------------------------------------------------------------------- #


def load_manifest(memory_dir: Path) -> dict | None:
    """Parse the flat `key: value` manifest written by `init`. None if absent."""
    path = Path(memory_dir) / "manifest.yml"
    if not path.is_file():
        return None
    out: dict[str, str] = {}
    for line in read_text_lenient(path)[0].splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        val = val.strip()
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]  # unquote so `schema_version: "1"` compares as `1`
        else:
            # Strip an inline comment only at a whitespace boundary — a bare `#`
            # inside a value (e.g. `project: my#proj`) is content, not a comment.
            val = re.split(r"\s+#", val, maxsplit=1)[0].strip()
        out[key.strip()] = val
    return out


# --------------------------------------------------------------------------- #
# validate — fully deterministic; NO heuristic content scanning
# --------------------------------------------------------------------------- #


def _finding(check: str, status: str, path: str | None, message: str) -> dict:
    return {"check": check, "status": status, "path": path, "message": message}


def run_validate(memory_dir: Path) -> list[dict]:
    """Run the deterministic validation checks; return a list of findings.

    Every finding is {check, status: pass|fail, path, message}. Heuristic content
    scanning (secrets, instruction-like text) is intentionally absent — that lives
    in `audit`.
    """
    memory_dir = Path(memory_dir)
    findings: list[dict] = []

    # 16.1 — manifest exists + supported schema_version.
    manifest = load_manifest(memory_dir)
    if manifest is None:
        findings.append(_finding("manifest", "fail", "manifest.yml", "manifest.yml is missing"))
    else:
        sv = manifest.get("schema_version")
        if sv != str(SCHEMA_VERSION):
            findings.append(
                _finding(
                    "manifest",
                    "fail",
                    "manifest.yml",
                    f"unsupported schema_version {sv!r} (this build supports {SCHEMA_VERSION})",
                )
            )
        else:
            findings.append(_finding("manifest", "pass", "manifest.yml", f"schema_version {sv}"))

    # 16.2 — required core files exist, and are readable. An undecodable core
    # file used to pass silently here while aborting `audit` and `resume`
    # elsewhere — validate is the trust primitive, so it says so.
    for name in CORE_FILES:
        if not (memory_dir / name).is_file():
            findings.append(_finding("core-files", "fail", name, "required core file missing"))
            continue
        problem = read_text_lenient(memory_dir / name)[1]
        if problem:
            findings.append(_finding("core-files", "fail", name, problem))
        else:
            findings.append(_finding("core-files", "pass", name, "present"))

    # Load durable records once for the record-level checks (16.3–10).
    records = load_records(memory_dir)
    seen_ids: dict[str, str] = {}

    for rec in records:
        rel = str(rec.path.relative_to(memory_dir))

        # 16.3 — valid frontmatter (parses + required keys present).
        if rec.error:
            findings.append(
                _finding("frontmatter", "fail", rel, f"malformed frontmatter: {rec.error}")
            )
            continue
        missing = [k for k in REQUIRED_RECORD_KEYS if rec.meta.get(k) in (None, "")]
        if missing:
            findings.append(
                _finding("frontmatter", "fail", rel, f"missing required keys: {', '.join(missing)}")
            )
        else:
            findings.append(_finding("frontmatter", "pass", rel, "frontmatter valid"))

        # 16.4 — identity: filename canonical; id uniqueness + id/slug agreement.
        ident = derive_identity(rec.stem, rec.rtype)
        if ident is None:
            findings.append(
                _finding(
                    "identity",
                    "fail",
                    rel,
                    "filename does not match <YYYY-MM-DD>-<slug>.md with a real calendar "
                    "date and a lowercase [a-z0-9-] slug; id/slug underivable",
                )
            )
        else:
            rid, slug = ident
            is_duplicate = rid in seen_ids
            if is_duplicate:
                findings.append(
                    _finding(
                        "identity", "fail", rel, f"duplicate id {rid!r} (also {seen_ids[rid]})"
                    )
                )
            else:
                seen_ids[rid] = rel
            stored_id = rec.meta.get("id")
            stored_slug = rec.meta.get("slug")
            disagree = []
            if stored_id is not None and stored_id != rid:
                disagree.append(f"id frontmatter {stored_id!r} != derived {rid!r}")
            if stored_slug is not None and stored_slug != slug:
                disagree.append(f"slug frontmatter {stored_slug!r} != derived {slug!r}")
            stored_type = rec.meta.get("type")
            if stored_type is not None and stored_type != rec.rtype:
                disagree.append(f"type frontmatter {stored_type!r} != directory {rec.rtype!r}")
            if disagree:
                findings.append(_finding("identity", "fail", rel, "; ".join(disagree)))
            elif not is_duplicate:
                # A duplicate already produced a fail; don't also emit a redundant
                # identity pass that would inflate the passed count.
                findings.append(_finding("identity", "pass", rel, f"id {rid}"))

        # 16.5 — status in vocabulary.
        status = rec.meta.get("status")
        if status is not None and status not in VALID_STATUS:
            findings.append(
                _finding(
                    "status",
                    "fail",
                    rel,
                    f"invalid status {status!r} (allowed: {', '.join(VALID_STATUS)})",
                )
            )

        # 16.6 — superseded requires superseded_by.
        if status == "superseded" and rec.meta.get("superseded_by") in (None, "", []):
            findings.append(
                _finding("superseded", "fail", rel, "status superseded but superseded_by is empty")
            )

        # 16.7 / 16.8 — privacy placement and prohibition.
        privacy = rec.meta.get("privacy")
        if privacy is not None and privacy not in VALID_PRIVACY:
            # A typo'd value (e.g. "secret-prohibitted") must not silently slip
            # past the exact-match leak gate below — flag the out-of-vocab value.
            findings.append(
                _finding(
                    "privacy",
                    "fail",
                    rel,
                    f"invalid privacy {privacy!r} (allowed: {', '.join(VALID_PRIVACY)})",
                )
            )
        if privacy == "secret-prohibited":
            findings.append(
                _finding(
                    "privacy",
                    "fail",
                    rel,
                    "privacy: secret-prohibited must not be stored in memory",
                )
            )
        elif privacy == "local-private":
            # durable directory records are committed paths; local-private must be under private/.
            findings.append(
                _finding(
                    "privacy",
                    "fail",
                    rel,
                    "privacy: local-private record is under a committed path (must live under private/)",
                )
            )

        # 16.9 — decisions/attempts/verifications need evidence OR confidence: low.
        if rec.rtype in ("decision", "attempt", "verification"):
            evidence = rec.meta.get("evidence")
            has_evidence = bool(evidence) if evidence is not None else False
            if not has_evidence and rec.meta.get("confidence") != "low":
                findings.append(
                    _finding(
                        "evidence",
                        "fail",
                        rel,
                        f"{rec.rtype} has no evidence and confidence is not 'low'",
                    )
                )

        # 16.9b — verifications carry a subject and a valid outcome.
        if rec.rtype == "verification":
            subj = rec.meta.get("subject")
            # A non-string subject (e.g. a hand-edited YAML list) is a finding,
            # not a crash.
            if not (isinstance(subj, str) and subj.strip()):
                findings.append(
                    _finding(
                        "verification",
                        "fail",
                        rel,
                        "verification has no subject"
                        if subj in (None, "")
                        else f"verification subject must be a string, got {type(subj).__name__}",
                    )
                )
            outcome = rec.meta.get("outcome")
            if outcome not in VALID_VERIFICATION_OUTCOME:
                findings.append(
                    _finding(
                        "verification",
                        "fail",
                        rel,
                        f"invalid outcome {outcome!r} (allowed: {', '.join(VALID_VERIFICATION_OUTCOME)})",
                    )
                )
            method = rec.meta.get("method")
            if method not in (None, "") and method not in VALID_VERIFICATION_METHOD:
                findings.append(
                    _finding(
                        "verification",
                        "fail",
                        rel,
                        f"invalid method {method!r} (allowed: {', '.join(VALID_VERIFICATION_METHOD)})",
                    )
                )

        # 16.10 — session records need a Next Action (or convergence/done marker).
        if rec.rtype == "session":
            has_next = any(re.search(r"next action", h, re.I) for h in rec.sections)
            body_l = rec.body.lower()
            # Word-boundary match: a raw substring test let
            # "done" match "abandoned", false-passing the convergence check.
            has_done = any(
                re.search(rf"\b{re.escape(mark)}\b", body_l) for mark in SESSION_DONE_MARKERS
            )
            if not (has_next or has_done):
                findings.append(
                    _finding(
                        "session",
                        "fail",
                        rel,
                        "session record lacks a '## Next Action' or convergence/done marker",
                    )
                )

    # 16.11 — handoff has branch, commit, next action, stale conditions.
    handoff = memory_dir / "handoff.md"
    if handoff.is_file():
        try:
            htext = handoff.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # A finding, not a crash.
            findings.append(_finding("handoff", "fail", "handoff.md", f"unreadable file: {exc}"))
            htext = None
    else:
        htext = None
    if htext is not None:
        required = {
            "branch": re.search(r"branch\s*:", htext, re.I),
            "commit": re.search(r"commit\s*:", htext, re.I),
            "next action": re.search(r"##\s+next action", htext, re.I),
            "stale conditions": re.search(r"##\s+stale", htext, re.I),
        }
        missing_h = [name for name, hit in required.items() if not hit]
        if missing_h:
            findings.append(
                _finding("handoff", "fail", "handoff.md", f"missing: {', '.join(missing_h)}")
            )
        else:
            findings.append(
                _finding("handoff", "pass", "handoff.md", "branch/commit/next action/stale present")
            )

    # 16.12 — generated files are not treated as canonical (carry the projection marker).
    gen_dir = memory_dir / "generated"
    if gen_dir.is_dir():
        for p in sorted(gen_dir.glob("*.md")):
            if p.name == "README.md":
                continue
            rel = str(p.relative_to(memory_dir))
            try:
                head = "\n".join(p.read_text(encoding="utf-8").splitlines()[:5])
            except (OSError, UnicodeDecodeError) as exc:
                # A finding, not a crash.
                findings.append(_finding("generated", "fail", rel, f"unreadable file: {exc}"))
                continue
            if GENERATED_MARKER in head:
                findings.append(
                    _finding("generated", "pass", rel, "carries generated-projection marker")
                )
            else:
                findings.append(
                    _finding(
                        "generated",
                        "fail",
                        rel,
                        f"generated file lacks the '{GENERATED_MARKER}' marker",
                    )
                )

    # 16.12b — projection freshness: a generated projection stamped
    # with an inputs_hash that no longer matches the live canonical records is
    # stale. `validate` is the trust primitive, so it must not stay green while a
    # projection silently desyncs — that would *certify* drift. Unstamped/older
    # projections carry no hash and are skipped (handled by detect_packet_drift).
    for d in detect_packet_drift(memory_dir):
        findings.append(
            _finding(
                "freshness",
                "fail",
                d["path"],
                f"stale projection (built from inputs_hash {d['stamped']}; "
                f"live is {d['current']}). Run `crumb reindex`.",
            )
        )

    # 16.13 — adapter files are not loaded as canonical records. By construction the
    # loader walks only decisions/attempts/sessions/ideas, so project-root adapter
    # files (AGENTS.md/CLAUDE.md/etc.) are never treated as records. Recorded as pass.
    findings.append(
        _finding(
            "adapters", "pass", None, "adapter/signpost files are not loaded as canonical records"
        )
    )

    return findings


def cmd_validate(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(
            args,
            f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.",
        )
        return 2

    findings = run_validate(memory_dir)
    fails = [f for f in findings if f["status"] == "fail"]
    passes = [f for f in findings if f["status"] == "pass"]

    if args.json:
        _print_json(
            args,
            {"passed": len(passes), "failed": len(fails), "findings": findings},
            ok=not fails,
            summary={"passed": len(passes), "failed": len(fails)},
        )
        return 0 if not fails else 1

    if args.plain:
        for f in findings:
            loc = f["path"] or "-"
            print(f"{f['status'].upper()} {f['check']} {loc}: {f['message']}")
        return 0 if not fails else 1

    if fails:
        print(f"validate: {len(fails)} problem(s) found ({len(passes)} checks passed)\n")
        for f in fails:
            loc = f["path"] or "-"
            print(f"  {MARK_FAIL} [{f['check']}] {loc}: {f['message']}")
        if args.verbose:
            print("\nPassed checks:")
            for f in passes:
                loc = f["path"] or "-"
                print(f"  {MARK_PASS} [{f['check']}] {loc}: {f['message']}")
        return 1

    print(f"validate: OK — {len(passes)} checks passed, 0 problems.")
    if args.verbose:
        for f in passes:
            loc = f["path"] or "-"
            print(f"  {MARK_PASS} [{f['check']}] {loc}: {f['message']}")
    return 0


# --------------------------------------------------------------------------- #
# Capture half — record writer, `remember`, `capture session`
# --------------------------------------------------------------------------- #
#
# Design constraint: the capture budget. A routine
# `capture session` must take <90s of human effort; `--fast` ~15s. Everything not
# prompted is auto-derived (`derive_fields`) or defaulted (`default_fields`). No
# LLM is required on any path — git pre-fill + human edit is the MVP.

# Reverse of DIR_TYPES: record type -> directory.
TYPE_DIR = {v: k for k, v in DIR_TYPES.items()}

# §8 body section headings per record type (rendered in this order).
BODY_SECTIONS = {
    "decision": [
        "Context",
        "Options Considered",
        "Decision",
        "Rationale",
        "Consequences",
        "What Not To Retry",
        "Evidence",
        "Stale / Review Conditions",
    ],
    "attempt": [
        "Problem",
        "Tried",
        "Result",
        "Why It Failed / Succeeded",
        "Do Not Retry Unless",
        "Evidence",
        "Related Records",
    ],
    "session": [
        "Starting Context",
        "Work Completed",
        "Decisions Made",
        "Attempts / Failures",
        "Open Questions",
        "Files Touched",
        "Commands / Verification",
        "Next Action",
    ],
    # Ideas are speculative proposals. Kept lean so
    # `crumb note idea` stays low-friction; not subject to the §16.9 evidence rule.
    "idea": [
        "Idea",
        "Motivation",
        "Sketch",
        "Open Questions",
    ],
    # Verifications record a finding about reality — "I checked X; here is its
    # state". subject/outcome/method live in frontmatter (so search
    # and the resume packet can filter on them); the body carries the narrative.
    "verification": [
        "Subject",
        "Outcome",
        "Method",
        "Evidence",
        "Notes",
    ],
}

# Where content lands when its `--set` heading matches nothing in the record
# type's vocabulary (C1). A wrong heading used to abort the whole call — with it
# every *other* `--set` on the command line, which for an agent writing up a long
# session is a 1,500-word record it has to synthesise a second time, at the point
# in the session where it has least context left to do it with. Losing authored
# content to a typo is the worst trade available here: park it, name it, warn,
# and let a human or a later `--set` move it.
UNSORTED_SECTION = "Unsorted"


def _heading_key(heading: str) -> str:
    """Fold a heading to its comparison key: case, spacing and punctuation blind.

    Three of the session headings contain spaces and one contains a slash, which
    is a second, independent way to get the same call rejected — `Attempts /
    Failures` vs `Attempts/Failures` vs `attempts failures` are the same heading
    by any reading a caller has.
    """
    return re.sub(r"[^a-z0-9]+", " ", (heading or "").lower()).strip()


# Obvious synonyms, per record type. Deliberately short: a guess that lands
# content under the wrong heading is worse than parking it under `Unsorted`,
# where it is still there and still labelled. Only wordings that mean the
# canonical heading and nothing else belong here.
_SECTION_ALIASES: dict[str, dict[str, str]] = {
    "decision": {
        "summary": "Decision",
        "background": "Context",
        "why": "Rationale",
        "reasoning": "Rationale",
        "options": "Options Considered",
        "alternatives": "Options Considered",
        "tradeoffs": "Options Considered",
        "impact": "Consequences",
        "outcome": "Consequences",
    },
    "attempt": {
        "what i tried": "Tried",
        "approach": "Tried",
        "outcome": "Result",
        "why": "Why It Failed / Succeeded",
        "why it failed": "Why It Failed / Succeeded",
        "why it succeeded": "Why It Failed / Succeeded",
        "do not retry": "Do Not Retry Unless",
        "related": "Related Records",
    },
    "session": {
        "summary": "Work Completed",
        "work done": "Work Completed",
        "what happened": "Work Completed",
        "context": "Starting Context",
        "decisions": "Decisions Made",
        "attempts": "Attempts / Failures",
        "failures": "Attempts / Failures",
        "questions": "Open Questions",
        "blockers": "Open Questions",
        "files": "Files Touched",
        "files changed": "Files Touched",
        "commands": "Commands / Verification",
        "verification": "Commands / Verification",
        "next": "Next Action",
        "next steps": "Next Action",
    },
    "idea": {
        "summary": "Idea",
        "proposal": "Idea",
        "why": "Motivation",
        "rationale": "Motivation",
        "design": "Sketch",
        "questions": "Open Questions",
    },
    "verification": {
        "what": "Subject",
        "result": "Outcome",
        "how": "Method",
        "notes": "Notes",
    },
}


def canonical_heading(rtype: str, heading: str) -> str | None:
    """The canonical section `heading` names, or None if it names none."""
    key = _heading_key(heading)
    if not key:
        return None
    for canon in BODY_SECTIONS.get(rtype, ()):
        if _heading_key(canon) == key:
            return canon
    if key == _heading_key(UNSORTED_SECTION):
        return UNSORTED_SECTION
    return _SECTION_ALIASES.get(rtype, {}).get(key)


def normalize_sections(rtype: str, items) -> tuple[dict[str, str], list[str]]:
    """Canonicalize section headings without ever dropping content (C1).

    `items` is a mapping or an iterable of (heading, content) pairs. Returns the
    canonical `{heading: content}` plus human-readable notes about anything that
    was renamed or parked — the caller decides how loudly to say them.

    Content whose heading matches nothing is kept under `## Unsorted`, tagged
    with the heading the caller used, so the record holds everything that was
    written and a reader can see what it was called.
    """
    if hasattr(items, "items"):
        items = list(items.items())
    sections: dict[str, str] = {}
    parked: list[tuple[str, str]] = []
    notes: list[str] = []
    for heading, content in items or ():
        canon = canonical_heading(rtype, heading)
        if canon is None:
            parked.append((str(heading), content))
            notes.append(
                f"unknown section {heading!r} for {rtype}: kept under "
                f"`## {UNSORTED_SECTION}`. Valid: {', '.join(BODY_SECTIONS[rtype])} "
                f"(see `crumb schema {rtype}`)"
            )
            continue
        if canon != heading:
            notes.append(f"section {heading!r} matched {canon!r}")
        sections[canon] = content
    if parked:
        existing = (sections.get(UNSORTED_SECTION) or "").strip()
        blocks = [existing] if existing else []
        blocks += [f"### {h}\n\n{(c or '').strip()}" for h, c in parked]
        sections[UNSORTED_SECTION] = "\n\n".join(blocks)
    return sections, notes


# Named flags for the fixed attempt section vocabulary: expose the
# contract in `--help` so it is no longer discoverable only by rejection. Each maps a
# Namespace attribute (from `--problem`, `--do-not-retry`, …) to its canonical heading.
ATTEMPT_FLAG_SECTIONS = (
    ("problem", "Problem"),
    ("tried", "Tried"),
    ("result", "Result"),
    ("why", "Why It Failed / Succeeded"),
    ("do_not_retry", "Do Not Retry Unless"),
    ("related", "Related Records"),
)

# Frontmatter key order for rendered records (mirrors §7).
FRONTMATTER_ORDER = [
    "id",
    "type",
    "slug",
    "title",
    "status",
    "created_at",
    "updated_at",
    "created_by",
    "agent",
    "project",
    "scope",
    "branch",
    "commit",
    "dirty_files",
    # Harness session id, on machine snapshots only — the key that lets one
    # session's repeated Stop firings coalesce into one record (F-6).
    "host_session",
    "confidence",
    "privacy",
    "review_status",
    "reviewed_by",
    "supersedes",
    "superseded_by",
    "expires_at",
    "subject",
    "outcome",
    "method",
    "tags",
    "evidence",
]

_EMPTY_SECTION = "_(not recorded)_"


# ---- rendering ------------------------------------------------------------- #


def _needs_quote(s: str, in_list: bool = False) -> bool:
    if s == "":
        return True
    if s in ("null", "~", "[]", "true", "false"):
        return True
    if s != s.strip():
        return True
    if s[0] in "#\"'":
        return True
    if " #" in s:
        return True
    # In a block list, a `: ` or trailing `:` would make the parser read the
    # item as a {key: value} map instead of a scalar (see _is_map_item), so it
    # must be quoted. At the top level a colon in the value is harmless.
    if in_list and (": " in s or s.endswith(":")):
        return True
    return False


def _render_scalar(v, in_list: bool = False) -> str:
    """Render a scalar so it round-trips through `parse_frontmatter`."""
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    s = str(v)
    if "\n" in s or "\r" in s:
        # The frontmatter is a line-based YAML subset with no multi-line scalar
        # support: a newline would silently truncate the value and inject the
        # remainder as bogus keys. Reject it at the source instead of corrupting.
        raise ValueError("frontmatter values must be single-line (no newlines)")
    if _needs_quote(s, in_list=in_list):
        if '"' in s:
            # A double quote in the value forces the single-quoted form; interior
            # single quotes are escaped by doubling, which _parse_scalar reverses
            # (the old quote-flip silently truncated on re-read when a value
            # contained both quote kinds).
            return "'" + s.replace("'", "''") + "'"
        return f'"{s}"'
    return s


def _render_list_items(key: str, v: list) -> list[str]:
    """Render a block list under `key`, supporting the shapes the parser accepts.

    `_parse_list` produces scalars and one-level {key: scalar} maps for *any*
    key, so the renderer must handle both everywhere — not just scalars on
    generic keys and maps on `evidence` (the old asymmetry
    persisted Python `repr` strings for maps under generic keys and crashed on
    scalars under `evidence`). Deeper nesting is not representable in this
    frontmatter subset; fail closed rather than corrupt.
    """
    lines = [f"{key}:"]
    for item in v:
        if isinstance(item, dict):
            if not item:
                raise ValueError(f"frontmatter list under {key!r} contains an empty map")
            for idx, (k2, v2) in enumerate(item.items()):
                if isinstance(v2, (dict, list)):
                    raise ValueError(
                        f"frontmatter list under {key!r} nests a non-scalar value; "
                        "not representable in this frontmatter subset"
                    )
                prefix = "  - " if idx == 0 else "    "
                lines.append(f"{prefix}{k2}: {_render_scalar(v2)}")
        else:
            lines.append(f"  - {_render_scalar(item, in_list=True)}")
    return lines


def render_frontmatter(meta: dict) -> str:
    """Render a frontmatter dict into the YAML subset the parser accepts.

    Canonical keys are emitted in `FRONTMATTER_ORDER`; any non-canonical keys
    present on the record follow in insertion order, so a re-render (e.g. on a
    status change) never silently drops keys the writer didn't know about.
    """
    lines = ["---"]
    extra_keys = [k for k in meta if k not in FRONTMATTER_ORDER]
    for key in (*FRONTMATTER_ORDER, *extra_keys):
        if key not in meta:
            continue
        v = meta[key]
        if isinstance(v, list):
            if not v:
                lines.append(f"{key}: []")
            else:
                lines.extend(_render_list_items(key, v))
        else:
            lines.append(f"{key}: {_render_scalar(v)}")
    lines.append("---")
    return "\n".join(lines)


def render_body(rtype: str, sections: dict[str, str]) -> str:
    """Render the §8 body for `rtype` — provided sections only, canonical order.

    Unfilled sections are omitted, not stubbed (P2-10): the field test's best
    record had 4 of 7 sections reading `_(not recorded)_`, burying the one
    section that carried the value. `schema --template <type>` still shows a
    human the full skeleton; the stored record only says what was recorded.
    """
    out: list[str] = []
    # `Unsorted` is appended after the vocabulary, never inside it: it is where
    # content whose heading matched nothing lands (C1), and it must not displace
    # a canonical section a reader is scanning for.
    for heading in list(BODY_SECTIONS[rtype]) + [UNSORTED_SECTION]:
        content = (sections.get(heading) or "").strip()
        if not content or content == _EMPTY_SECTION:
            continue
        out.append(f"## {heading}")
        out.append(content)
        out.append("")
    if not out:
        # A record with no filled sections still needs a parseable body.
        out = [f"## {BODY_SECTIONS[rtype][0]}", _EMPTY_SECTION, ""]
    return "\n".join(out).rstrip() + "\n"


# ---- slug + identity ------------------------------------------------------- #


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s or "untitled"


# How much of a title a *filename* may carry. `slugify` itself stays
# uncapped — it also names traps and open questions, which are not files — so the
# cap lives here, where a path is built. A full-sentence title used to become a
# full-sentence filename: at ~240 characters `remember` failed outright with
# ENAMETOOLONG on Linux, and well before that `<repo>/.project-memory/<type>/` +
# the name pushed a Windows checkout past MAX_PATH (260), so `git clone` failed on
# a repo that had committed one. The record's `title` frontmatter carries the full
# text either way; the filename only has to be a readable, unique handle.
SLUG_MAX_CHARS = 60

# Closed-class words a truncated slug must not end on (P2-15). Deliberately
# tiny — nouns that double as function words in some titles ("test", "work")
# stay out so a meaningful tail is never eaten.
_SLUG_TRAILING_STOPWORDS = frozenset(
    "a an the and or but nor with no not of in on for to is are was were has have had by at from as".split()
)


def truncate_slug(slug: str, limit: int = SLUG_MAX_CHARS) -> str:
    """Cap `slug` at `limit` characters, preferring a whole-word cut.

    The result is still canonical for `RECORD_STEM_RE` (no leading/trailing or
    doubled `-`), so `derive_identity` reads it back unchanged. Cutting mid-word
    is allowed rather than dropping below half the budget — a slug of one very
    long word should still say something.
    """
    if limit <= 0 or len(slug) <= limit:
        return slug
    cut = slug[:limit]
    head, sep, _tail = cut.rpartition("-")
    if sep and len(head) >= limit // 2:
        cut = head
    cut = cut.rstrip("-") or slug[:limit].rstrip("-")
    # A truncated slug that ends on a function word ("…-is-nullable-with-no",
    # "…-15-minute-period-and") reads as corrupted (P2-15). Trim trailing
    # function words — only here, on the truncation path: an author's own short
    # title ("say-no") is never rewritten.
    parts = cut.split("-")
    while len(parts) > 1 and parts[-1] in _SLUG_TRAILING_STOPWORDS:
        parts.pop()
    return "-".join(parts)


# Types whose names are made unique by construction rather than by looking at
# the local tree (R3). `capture session` derives its disambiguating ordinal from
# the files it can *see*, so two agents working the same day in two checkouts
# each independently write `2026-09-04-session.md` (or `-session-3.md`, having
# each seen two of their own). Git catches it as an add/add conflict — the good
# outcome — but repair means rewriting the id, slug and title *inside* both
# files, not just renaming one, and a store like this repo's routinely has five
# concurrent sessions. Four hex characters of entropy cannot collide across
# actors who cannot see each other, which the ordinal never could.
UNIQUE_SUFFIX_TYPES = ("session",)
UNIQUE_SUFFIX_BYTES = 2  # -> 4 hex characters


def _unique_suffix() -> str:
    return hashlib.blake2s(os.urandom(16), digest_size=UNIQUE_SUFFIX_BYTES).hexdigest()


def _unique_record_path(
    directory: Path, date: str, slug: str, *, suffix: str | None = None
) -> tuple[Path, str]:
    """Pick a non-colliding `<date>-<slug>.md` (append -2, -3, … on same-day clash).

    The slug is capped at `SLUG_MAX_CHARS` *including* the collision suffix, so
    the disambiguated names stay inside the budget too. Truncation can make two
    long titles land on the same base — that is just another same-day clash, and
    the suffix already handles it.

    `suffix` (see `UNIQUE_SUFFIX_TYPES`) is appended before any of that: it makes
    the name unique against writers this process cannot see, where the ordinal
    only disambiguates against files already on disk here.
    """
    if suffix:
        slug = truncate_slug(slug, SLUG_MAX_CHARS - len(suffix) - 1) + "-" + suffix
    base = truncate_slug(slug)
    candidate = directory / f"{date}-{base}.md"
    if not candidate.exists():
        return candidate, base
    i = 2
    while True:
        suffix = f"-{i}"
        s2 = truncate_slug(slug, SLUG_MAX_CHARS - len(suffix)) + suffix
        candidate = directory / f"{date}-{s2}.md"
        if not candidate.exists():
            return candidate, s2
        i += 1


# ---- the writer ------------------------------------------------------------ #


def write_record(
    memory_dir: Path,
    project_root: Path,
    rtype: str,
    title: str,
    sections: dict[str, str],
    *,
    tags: list[str] | None = None,
    evidence: list[dict] | None = None,
    confidence: str | None = None,
    privacy: str | None = None,
    scope: str | None = None,
    status: str | None = None,
    agent: str | None = None,
    extra: dict | None = None,
    include_memory: bool = False,
) -> tuple[Path, dict]:
    """Assemble + write a durable record; return (path, frontmatter dict).

    Frontmatter is auto-derived (§7) + defaulted + the caller's prompted fields.
    `updated_at == created_at`. Identity is recomputed from the final filename so
    id/slug/filename always agree. `extra` carries type-specific frontmatter keys
    (e.g. a verification's subject/outcome/method) — rendered in
    canonical order when known to FRONTMATTER_ORDER, else appended.
    """
    # Normalize here as well as in the CLI's `--set` collector: `render_body`
    # walks the type's vocabulary, so a heading it does not recognize used to
    # vanish without a word for every writer that does not go through the CLI —
    # the MCP `memory_record` tool passes a raw `sections` mapping straight in.
    sections, _notes = normalize_sections(rtype, sections or {})
    derived = derive_fields(project_root, agent=agent, include_memory=include_memory)
    defaults = default_fields()
    date = derived["created_at"][:10]
    directory = Path(memory_dir) / TYPE_DIR[rtype]
    directory.mkdir(parents=True, exist_ok=True)
    path, slug = _unique_record_path(
        directory,
        date,
        slugify(title),
        suffix=_unique_suffix() if rtype in UNIQUE_SUFFIX_TYPES else None,
    )

    ident = derive_identity(path.stem, rtype)
    if ident is None:  # pragma: no cover - filename is constructed canonically
        raise ValueError(f"constructed filename is not canonical: {path.name}")
    rid, slug = ident

    meta: dict = {
        "id": rid,
        "type": rtype,
        "slug": slug,
        "title": title,
        "status": status or defaults["status"],
        "created_at": derived["created_at"],
        "updated_at": derived["created_at"],
        "created_by": derived["created_by"],
        "agent": derived["agent"],
        "project": derived["project"],
        "scope": scope or defaults["scope"],
        "branch": derived["branch"],
        "commit": derived["commit"],
        "dirty_files": derived["dirty_files"],
        "confidence": confidence or defaults["confidence"],
        "privacy": privacy or defaults["privacy"],
        "review_status": defaults["review_status"],
        "reviewed_by": defaults["reviewed_by"],
        "supersedes": defaults["supersedes"],
        "superseded_by": defaults["superseded_by"],
        "expires_at": defaults["expires_at"],
        "tags": tags or [],
        "evidence": evidence or [],
    }
    for k, v in (extra or {}).items():
        if v is not None:
            meta[k] = v
    text = render_frontmatter(meta) + "\n\n" + render_body(rtype, sections)
    write_text_atomic(path, text)
    return path, meta


def _validate_new_file(memory_dir: Path, path: Path) -> list[dict]:
    """Run the deterministic checks and return failures that touch `path`."""
    rel = str(Path(path).relative_to(memory_dir))
    return [f for f in run_validate(memory_dir) if f["status"] == "fail" and f["path"] == rel]


# ---- record lookup + status mutation (shared by MCP `memory_mark_status`) --- #


# ---- write-time guard reachability (F-4) ----------------------------------- #

# `audit` has long carried an `[unreachable]` check: a record with neither tags
# nor file references can only ever surface through generic keyword overlap, which
# the stale/branch decay factors readily push under the noise floor. It is the
# most precise diagnostic in the tool and it fires days too late — `audit` is
# discretionary, nobody runs it on the day they write the record, and that is the
# only moment fixing it is cheap. The 0.1.11 field audit (F-4) found four
# verification records in exactly this state: `validate` passes them, they look
# fine, and they simply never do their job.
#
# So run the same computation at write time. Non-fatal and non-blocking — the
# record is already written and valid; this only tells the author, while they are
# still around, that it will not be reachable.
REACHABILITY_HINT = (
    "no tags and no file evidence — `guard` can reach this record only through "
    "generic keyword overlap; add --tags or --evidence file <path> so it can "
    "drive a verdict"
)

BLOCK_REACHABILITY_HINT = (
    "no file or path reference — `guard` can reach this {kind} only through "
    "generic keyword overlap; name the file(s) it applies to so it can drive a verdict"
)


def _record_reachability_hint(path: Path, rtype: str) -> str | None:
    """`audit`'s [unreachable] check, run against a record just written.

    Deliberately re-derives from the file rather than from the caller's
    arguments: `_item_from_record` also mines file paths out of the *body*, so a
    verification whose note names `app/Foo.kt` is reachable and must not be
    nagged. Same function `audit` uses, so the two can never disagree.
    """
    rec = Record.from_file(path, rtype)
    if rec.error:
        return None  # unparseable is validate's finding, not this one's
    item = _item_from_record(rec)
    reachable = item["tags"] or item["files"] or item["mentioned_files"]
    return None if reachable else REACHABILITY_HINT


def _block_reachability_hint(body: str, kind: str) -> str | None:
    """The same check for trap/question blocks, which cannot carry tags.

    `_item_from_trap` / `_item_from_question` derive files only from paths in the
    block text, so a path reference is the single reachability lever these have.
    """
    return None if _paths_from_text(body) else BLOCK_REACHABILITY_HINT.format(kind=kind)


def find_record_by_id(memory_dir: Path, rid: str) -> "Record | None":
    """Return the durable Record whose id == `rid`, or None.

    Identity is filename-canonical (§7), so this matches the same id the CLI,
    search, guard and resume already use — no second identity scheme.
    """
    for rec in load_records(Path(memory_dir)):
        if rec.error:
            continue
        if rec.meta.get("id") == rid:
            return rec
        ident = derive_identity(rec.stem, rec.rtype)
        if ident and ident[0] == rid:
            return rec
    return None


def set_record_status(
    memory_dir: Path,
    rid: str,
    status: str,
    reason: str,
    *,
    agent: str | None = None,
    superseded_by: str | None = None,
) -> dict:
    """Change a durable record's `status`, gated by `validate` (§16.6).

    Reuses parse/render frontmatter + the same validate gate as `remember`, so
    there is one source of write-behavior. Returns a small result dict. The edit
    is reverted if it would leave the record invalid (e.g. `superseded` without
    `superseded_by`), and an error is returned instead. `superseded_by` points
    a superseding record when marking `superseded` — this is the supersede flow
    the docs reference.
    """
    memory_dir = Path(memory_dir)
    # Resolution comes before the status check, because which vocabulary applies
    # depends on what the id names: a question is `open`/`answered`/`closed`,
    # never `superseded`.
    rec = find_record_by_id(memory_dir, rid)
    if rec is None:
        # Traps and open questions are `## ` blocks inside aggregate files, not
        # one file per record, so neither ever resolved here — which left every
        # trap and every question permanently live, still scoring in `search`
        # and still driving `guard`, with no way to retire one but hand-editing
        # known-traps.md / open-questions.md.
        if find_trap_by_id(memory_dir, rid) is not None:
            return set_trap_status(
                memory_dir, rid, status, reason, agent=agent, superseded_by=superseded_by
            )
        found = find_questions_by_id(memory_dir, rid)
        if len(found) > 1:
            return {
                "ok": False,
                "error": f"id {rid!r} matches {len(found)} questions; they are slug-derived "
                "and these collide — rename one in open-questions.md to tell them apart",
            }
        if found:
            return set_question_status(
                memory_dir, rid, status, reason, agent=agent, superseded_by=superseded_by
            )
        return {"ok": False, "error": f"no record, trap or question with id {rid!r}"}

    if status not in VALID_STATUS:
        return {
            "ok": False,
            "error": f"invalid status {status!r}; valid: {', '.join(VALID_STATUS)}",
        }

    original = rec.path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(original)
    prev = meta.get("status")
    meta["status"] = status
    meta["updated_at"] = now_iso()
    if superseded_by:
        meta["superseded_by"] = superseded_by
    # The reason is recorded as a trailing, non-instruction comment (data, §15).
    # A literal `-->` inside the reason would terminate the comment early and
    # leak the remainder as content — neutralize it.
    reason = (reason or "").replace("-->", "-- >")
    author = agent or detect_agent()
    note = f"<!-- status: {prev} -> {status} ({reason}) by {author} at {meta['updated_at']} -->"
    try:
        rendered = render_frontmatter(meta)
    except ValueError as exc:
        return {"ok": False, "id": rid, "error": f"cannot re-render frontmatter: {exc}"}
    # Fail-closed round-trip check: the parser accepts a wider
    # grammar than the renderer can emit, so refuse to write a rendering the
    # parser would read back differently instead of silently corrupting the
    # record (and having validate certify the corruption).
    reparsed, _ = parse_frontmatter(rendered + "\n")
    if reparsed != meta:
        drifted = sorted(k for k in set(meta) | set(reparsed) if meta.get(k) != reparsed.get(k))
        return {
            "ok": False,
            "id": rid,
            "error": "status change refused: frontmatter would not survive a "
            f"re-render round-trip (field(s): {', '.join(drifted)}); "
            "fix the record by hand or simplify the offending value",
        }
    new_text = rendered + "\n" + body.rstrip("\n") + "\n\n" + note + "\n"
    write_text_atomic(rec.path, new_text)

    fails = _validate_new_file(memory_dir, rec.path)
    if fails:
        write_text_atomic(rec.path, original)  # revert
        return {
            "ok": False,
            "id": rid,
            "error": "status change rejected by validate: "
            + "; ".join(f["message"] for f in fails),
        }
    # Reindex-on-write: a status flip can drop a record from / add it
    # back to the active set, so the projections must follow.
    reindex_projections(memory_dir)
    return {"ok": True, "id": rid, "path": str(rec.path), "from": prev, "to": status}


def set_record_title(memory_dir: Path, rid: str, title: str, *, agent: str | None = None) -> dict:
    """Rewrite a record's `title` in place, gated by `validate` (R1).

    Repairs a corpus that was written before titles were derived: 280 of one
    field store's 310 sessions are titled `session`, and `search` ranks on
    title, so they are invisible to the tool that exists to find them.

    Identity — id, slug, filename — is deliberately NOT rewritten. Those are what
    every `supersedes`, `superseded_by` and evidence ref in the store points at,
    and a rename would break each of them silently while a reader looking at the
    old filename would see a record that no longer answers to it. The searchable
    field is the one that was empty of information, and it is the one this fixes;
    the id stays the durable handle it has always been.
    """
    memory_dir = Path(memory_dir)
    rec = find_record_by_id(memory_dir, rid)
    if rec is None:
        return {
            "ok": False,
            "error": f"no record with id {rid!r} (traps and questions "
            "have no separate title — edit their summary line in place)",
        }
    title = (title or "").strip()
    if not title:
        return {"ok": False, "id": rid, "error": "a title cannot be empty"}

    original = rec.path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(original)
    previous = meta.get("title")
    if previous == title:
        return {"ok": True, "id": rid, "path": str(rec.path), "from": previous, "to": title}
    meta["title"] = title
    meta["updated_at"] = now_iso()
    author = agent or detect_agent()
    note = f"<!-- title: {previous!r} -> {title!r} by {author} at {meta['updated_at']} -->"
    try:
        rendered = render_frontmatter(meta)
    except ValueError as exc:
        return {"ok": False, "id": rid, "error": f"cannot re-render frontmatter: {exc}"}
    reparsed, _ = parse_frontmatter(rendered + "\n")
    if reparsed != meta:
        return {
            "ok": False,
            "id": rid,
            "error": "retitle refused: frontmatter would not survive a re-render "
            "round-trip; simplify the title",
        }
    write_text_atomic(rec.path, rendered + "\n" + body.rstrip("\n") + "\n\n" + note + "\n")

    fails = _validate_new_file(memory_dir, rec.path)
    if fails:
        write_text_atomic(rec.path, original)  # revert
        return {
            "ok": False,
            "id": rid,
            "error": "retitle rejected by validate: " + "; ".join(f["message"] for f in fails),
        }
    reindex_projections(memory_dir)
    return {"ok": True, "id": rid, "path": str(rec.path), "from": previous, "to": title}


# ---- trap + question lifecycle (the aggregate-file half of `mark-status`) --- #


def find_trap_by_id(memory_dir: Path, rid: str) -> dict | None:
    """Return the trap block whose `trap_<slug>` id == `rid`, or None.

    Matches the id `note trap` prints and `search` lists, so the id a user is
    shown is the id `mark-status` takes.
    """
    wanted = (rid or "").strip().lower()
    if not wanted:
        return None
    for trap in load_traps(Path(memory_dir)):
        if trap["id"].lower() == wanted:
            return trap
    return None


def _apply_block_status(block: str, status: str, superseded_by: str | None, note: str) -> str:
    """Rewrite one `## ` block's lifecycle bullets, changing as little as possible.

    Only the `- Status:` bullet (inserted after the block's leading bullet run if
    absent), an optional `- Superseded by:` bullet, and an appended provenance
    comment differ from the input — the summary, the template fields and any
    hand-written prose survive byte for byte.
    """
    lines = block.splitlines(keepends=True)
    head = lines[0] if lines else ""
    if head and not head.endswith("\n"):
        head += "\n"
    rest = lines[1:]

    status_line = f"- Status: {status}\n"
    for i, line in enumerate(rest):
        if _BLOCK_STATUS_LINE_RE.match(line):
            rest[i] = status_line
            break
    else:
        # After the last bullet of the block's leading list, so lifecycle sits
        # with the other `- key: value` fields rather than below loose prose.
        insert = 0
        for i, line in enumerate(rest):
            if re.match(r"\s*-\s+\S", line):
                insert = i + 1
            elif line.strip():
                break
        rest.insert(insert, status_line)

    if superseded_by:
        sup_line = f"- Superseded by: {superseded_by}\n"
        for i, line in enumerate(rest):
            if _BLOCK_SUPERSEDED_LINE_RE.match(line):
                rest[i] = sup_line
                break
        else:
            rest.insert(rest.index(status_line) + 1, sup_line)

    body = "".join(rest)
    core = body.rstrip("\n")
    # The trailing newline run is the blank line separating this block from the
    # next heading — put it back after the note so blocks stay separated.
    tail = body[len(core) :] or "\n"
    return head + (core + "\n" if core else "") + note + tail


def _set_block_bullet(block: str, key: str, value: str) -> str:
    """Set `- <key>: <value>` inside one `## ` block, changing nothing else.

    Same placement rule as the status bullet: with the block's other
    `- key: value` fields, never below its prose.
    """
    pattern = re.compile(r"\s*-\s*" + re.escape(key) + r"\s*:", re.I)
    lines = block.splitlines(keepends=True)
    head, rest = (lines[0] if lines else ""), lines[1:]
    if head and not head.endswith("\n"):
        head += "\n"
    bullet = f"- {key}: {value}\n"
    for i, line in enumerate(rest):
        if pattern.match(line):
            rest[i] = bullet
            break
    else:
        insert = 0
        for i, line in enumerate(rest):
            if re.match(r"\s*-\s+\S", line):
                insert = i + 1
            elif line.strip():
                break
        rest.insert(insert, bullet)
    return head + "".join(rest)


def set_trap_confirmed(memory_dir: Path, rid: str, *, when: str | None = None) -> dict:
    """Stamp a trap's `- Last confirmed:` bullet with today's date (R6).

    Traps accumulate and nothing ages out: 77 active traps, 167 KB, loaded every
    session. Age alone cannot retire one — an old trap may be perfectly live —
    so the store needs the fact nobody was recording: when somebody last checked
    that this is still true. `crumb traps --stale` reads it back.
    """
    memory_dir = Path(memory_dir)
    trap = find_trap_by_id(memory_dir, rid)
    if trap is None:
        return {"ok": False, "error": f"no trap with id {rid!r}"}
    tid = trap["id"]
    path = memory_dir / "known-traps.md"
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "id": tid, "error": f"cannot read known-traps.md: {exc}"}
    span = next(
        (
            (start, end)
            for start, end, heading in _md_heading_spans(original)
            if heading.partition(":")[0].strip().lower() == tid.lower()
        ),
        None,
    )
    if span is None:  # pragma: no cover - defensive; find_trap_by_id just found it
        return {"ok": False, "id": tid, "error": f"could not locate the {tid} block to edit"}
    stamp = when or now_iso()[:10]
    start, end = span
    new_text = (
        original[:start]
        + _set_block_bullet(original[start:end], TRAP_CONFIRMED_KEY, stamp)
        + original[end:]
    )
    write_text_atomic(path, new_text)
    fails = _validate_new_file(memory_dir, path)
    if fails:
        write_text_atomic(path, original)  # revert
        return {
            "ok": False,
            "id": tid,
            "error": "confirm rejected by validate: " + "; ".join(f["message"] for f in fails),
        }
    reindex_projections(memory_dir)
    return {"ok": True, "id": tid, "path": str(path), "last_confirmed": stamp}


def set_trap_status(
    memory_dir: Path,
    rid: str,
    status: str,
    reason: str,
    *,
    agent: str | None = None,
    superseded_by: str | None = None,
) -> dict:
    """Change a trap's status by editing its block in known-traps.md in place.

    The aggregate-file counterpart to `set_record_status`, and reached through
    it, so the CLI and the `memory_mark_status` MCP tool both get this with no
    second entry point. Returns the same result shape as the record path.

    Fail-closed like `note()`: the file is reverted unless the edited block reads
    back with the requested status and leaves `validate` clean.
    """
    memory_dir = Path(memory_dir)
    if status not in VALID_STATUS:
        return {
            "ok": False,
            "error": f"invalid status {status!r}; valid: {', '.join(VALID_STATUS)}",
        }
    trap = find_trap_by_id(memory_dir, rid)
    if trap is None:
        return {"ok": False, "error": f"no trap with id {rid!r}"}
    tid, prev = trap["id"], trap["status"]
    # Same rule validate 16.6 puts on records: `superseded` must say by what.
    if status == "superseded" and not superseded_by:
        return {
            "ok": False,
            "id": tid,
            "error": "status superseded needs the replacing id (--superseded-by)",
        }

    path = memory_dir / "known-traps.md"
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "id": tid, "error": f"cannot read known-traps.md: {exc}"}

    span = next(
        (
            (start, end)
            for start, end, heading in _md_heading_spans(original)
            if heading.partition(":")[0].strip().lower() == tid.lower()
        ),
        None,
    )
    if span is None:  # pragma: no cover - defensive; load_traps just found it
        return {"ok": False, "id": tid, "error": f"could not locate the {tid} block to edit"}

    # The reason is data, not instruction (§15), and a literal `-->` inside it
    # would close the comment early and leak the remainder as trap content.
    reason = _sanitize_note_text(reason or "")
    author = agent or detect_agent()
    note_line = f"<!-- status: {prev} -> {status} ({reason}) by {author} at {now_iso()} -->"
    start, end = span
    new_text = (
        original[:start]
        + _apply_block_status(original[start:end], status, superseded_by, note_line)
        + original[end:]
    )
    write_text_atomic(path, new_text)

    after = find_trap_by_id(memory_dir, tid)
    if after is None or after["status"] != status:
        write_text_atomic(path, original)  # revert
        return {"ok": False, "id": tid, "error": "edited trap did not parse back; reverted"}
    fails = _validate_new_file(memory_dir, path)
    if fails:
        write_text_atomic(path, original)  # revert
        return {
            "ok": False,
            "id": tid,
            "error": "status change rejected by validate: "
            + "; ".join(f["message"] for f in fails),
        }
    # A retired trap drops out of the packet and the guard pre-filter, so the
    # projections have to follow the write, exactly as they do for records.
    reindex_projections(memory_dir)
    return {"ok": True, "id": tid, "path": str(path), "from": prev, "to": status}


def find_questions_by_id(memory_dir: Path, rid: str) -> list[dict]:
    """Every question block whose `q:<slug>` id == `rid` — normally zero or one.

    A list, not an Optional, because question ids are slug-derived: two questions
    can collide on one id (`question_item_id` only disambiguates the *truncated*
    ones), and `search`'s `-2` suffixes are positional, not stable enough to
    address a block by. The caller refuses an ambiguous edit rather than guessing
    which of two questions the user meant.
    """
    wanted = (rid or "").strip().lower()
    if not wanted:
        return []
    return [q for q in load_open_questions(Path(memory_dir)) if q["id"].lower() == wanted]


def set_question_status(
    memory_dir: Path,
    rid: str,
    status: str,
    reason: str,
    *,
    agent: str | None = None,
    superseded_by: str | None = None,
) -> dict:
    """Answer or close a `## Q:` block in open-questions.md, in place.

    The question half of the aggregate-file gap: every reader already honored a
    question's `- Status:` bullet (the packet lists only `open` ones, `guard`
    gives only an `open` question the open-blocker floor), but the bullet was
    write-once at `note question` time, so a question that got answered went on
    counting as a live blocker forever.

    Reached through `set_record_status`, so the CLI and `memory_mark_status` both
    get it with no second entry point. Same result shape as the record path.
    """
    memory_dir = Path(memory_dir)
    if status not in VALID_QUESTION_STATUS:
        return {
            "ok": False,
            "error": f"invalid question status {status!r}; valid: "
            + ", ".join(VALID_QUESTION_STATUS),
        }
    found = find_questions_by_id(memory_dir, rid)
    if not found:
        return {"ok": False, "error": f"no question with id {rid!r}"}
    if len(found) > 1:  # pragma: no cover - caller checks first
        return {"ok": False, "error": f"id {rid!r} matches {len(found)} questions"}
    question = found[0]
    qid, prev = question["id"], question["status"]

    path = memory_dir / "open-questions.md"
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "id": qid, "error": f"cannot read open-questions.md: {exc}"}

    span = next(
        (
            (start, end)
            for start, end, heading in _md_heading_spans(original)
            if heading.lower().startswith("q:")
            and question_item_id(heading[2:].strip()).lower() == qid.lower()
        ),
        None,
    )
    if span is None:  # pragma: no cover - defensive; the loader just found it
        return {"ok": False, "id": qid, "error": f"could not locate the {qid} block to edit"}

    # The reason is data, not instruction (§15); a literal `-->` inside it would
    # close the comment early and leak the remainder as question content.
    reason = _sanitize_note_text(reason or "")
    author = agent or detect_agent()
    note_line = f"<!-- status: {prev} -> {status} ({reason}) by {author} at {now_iso()} -->"
    start, end = span
    new_text = (
        original[:start]
        + _apply_block_status(original[start:end], status, superseded_by, note_line)
        + original[end:]
    )
    write_text_atomic(path, new_text)

    after = find_questions_by_id(memory_dir, qid)
    if len(after) != 1 or after[0]["status"] != status:
        write_text_atomic(path, original)  # revert
        return {"ok": False, "id": qid, "error": "edited question did not parse back; reverted"}
    fails = _validate_new_file(memory_dir, path)
    if fails:
        write_text_atomic(path, original)  # revert
        return {
            "ok": False,
            "id": qid,
            "error": "status change rejected by validate: "
            + "; ".join(f["message"] for f in fails),
        }
    # An answered question leaves the packet's Open Questions and stops raising
    # the open-blocker floor, so the projections follow the write.
    reindex_projections(memory_dir)
    return {"ok": True, "id": qid, "path": str(path), "from": prev, "to": status}


# ---- input helpers --------------------------------------------------------- #


def _interactive() -> bool:
    # Both ends must be a terminal. Agent harnesses exist where stdin
    # passes isatty() while every read hits EOF and stdout is a pipe; gating on
    # stdin alone sent `init` down the interactive branch there, where the MCP
    # consent prompt's yes-default turned "nobody answered" into a .mcp.json
    # write. stdout was correctly not a TTY in the observed harness.
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_line(question: str) -> str:
    """Read one answer, treating EOF as "no answer given" instead of a traceback.

    `_interactive()` keeps agents off the prompting path in the harnesses we know
    about, but it is a heuristic over two isatty() calls — when it guesses wrong
    the prompts must degrade to "unanswered", not kill the command halfway through
    with an `EOFError` after it has already printed its git summary.
    """
    try:
        return input(question).strip()
    except EOFError:
        return ""


def _split_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [t.strip() for t in raw.split(",") if t.strip()]


def _parse_evidence_pairs(pairs: list[list[str]] | None) -> list[dict]:
    out: list[dict] = []
    for pair in pairs or []:
        etype, ref = pair[0], pair[1]
        out.append({"type": etype, "ref": ref})
    return out


def _collect_set_sections(
    rtype: str, set_pairs: list[list[str]] | None
) -> tuple[dict[str, str], list[str]]:
    """`--set HEADING TEXT` pairs as canonical sections, plus any notes to print.

    Never raises on an unrecognized heading: see `normalize_sections`.
    """
    return normalize_sections(rtype, [(pair[0], pair[1]) for pair in set_pairs or []])


# ---- remember decision / attempt ------------------------------------------- #


def cmd_remember(args: argparse.Namespace) -> int:
    rtype = getattr(args, "record_type", None)
    if rtype not in ("decision", "attempt"):
        _emit_error(args, "specify a record type: `crumb remember decision|attempt`")
        return 2

    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    title = args.title
    sections, section_notes = _collect_set_sections(rtype, args.set)
    for note_text in section_notes:
        _emit_warning(args, note_text)
    # Named attempt flags (--problem/--tried/…) override any matching --set heading.
    for attr, heading in ATTEMPT_FLAG_SECTIONS:
        val = getattr(args, attr, None)
        if val is not None:
            sections[heading] = val
    evidence = _parse_evidence_pairs(args.evidence)
    tags = _split_tags(args.tags)
    confidence = args.confidence

    if title is None:
        if not _interactive():
            _emit_error(args, "non-interactive: --title is required")
            return 2
        title = input("Title: ").strip()
        for heading in BODY_SECTIONS[rtype]:
            if heading == "Evidence":
                continue  # handled below
            # `setdefault(h, input(...))` evaluated the prompt eagerly, so a heading
            # already supplied via --set was still asked for and the answer thrown
            # away.
            if heading not in sections:
                sections[heading] = input(f"{heading}: ").strip()

    if not title:
        _emit_error(args, "title must not be empty")
        return 2

    # Evidence-or-low-confidence (validate §16.9) — enforce up front with a clear path.
    if not evidence and confidence != "low":
        if _interactive():
            ans = input(
                "No evidence given. Enter an evidence ref as 'type:ref' "
                "(e.g. commit:abc1234), or leave blank to set confidence=low: "
            ).strip()
            if ans and ":" in ans:
                etype, _, ref = ans.partition(":")
                evidence = [{"type": etype.strip(), "ref": ref.strip()}]
            else:
                confidence = "low"
        else:
            _emit_error(
                args,
                f"a{'n' if rtype[0] in 'aeiou' else ''} {rtype} needs evidence "
                f"or low confidence (validate §16.9): "
                f"pass --evidence TYPE REF or --confidence low",
            )
            return 2

    try:
        path, meta = write_record(
            memory_dir,
            root,
            rtype,
            title,
            sections,
            tags=tags,
            evidence=evidence,
            confidence=confidence,
            privacy=args.privacy,
            scope=args.scope,
            status=args.status,
            agent=args.agent,
        )
    except ValueError as exc:
        # e.g. a newline in a frontmatter field — rendering refuses to corrupt.
        _emit_error(args, str(exc))
        return 2

    # Post-write validate gate (defense in depth — fail fast, don't leave a bad file).
    fails = _validate_new_file(memory_dir, path)
    if fails:
        path.unlink()
        _emit_error(args, "new record failed validation: " + "; ".join(f["message"] for f in fails))
        return 1

    # Reindex-on-write: keep generated/ in step with the new record.
    reindex_projections(memory_dir, root)

    summary = {
        "created": str(path),
        "id": meta["id"],
        "type": rtype,
        "slug": meta["slug"],
        "confidence": meta["confidence"],
    }
    # F-4: decisions and attempts are covered by audit's [unreachable] check too,
    # so they get the same warning at the same moment. `--confidence low` is a
    # documented way to write a decision with no evidence at all, which is exactly
    # the record that then cannot drive a verdict.
    hint = _record_reachability_hint(path, rtype)
    if hint:
        summary["hint"] = hint
    if section_notes:
        summary["warnings"] = section_notes
    if args.json:
        _print_json(args, summary)
    else:
        print(f"Recorded {rtype}: {meta['id']}")
        print(f"  file: {path}")
        if meta["confidence"] == "low" and not meta["evidence"]:
            print("  note: no evidence; confidence set to low.")
        if hint:
            print(f"  note: {hint}")
    return 0


# ---- schema introspection -------------------------------------------------- #


def record_schema() -> dict:
    """The full record-contract as data, so an agent reads it once.

    Pure projection of the existing contract constants — no memory dir required.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "record_types": {
            rtype: {"body_sections": list(sections)} for rtype, sections in BODY_SECTIONS.items()
        },
        "required_frontmatter_keys": list(REQUIRED_RECORD_KEYS),
        "derived_frontmatter_keys": ["id", "slug"],
        "vocabularies": {
            "status": list(VALID_STATUS),
            "privacy": list(VALID_PRIVACY),
            "confidence": ["low", "medium", "high"],
            "session_tracking": list(VALID_SESSION_TRACKING),
            "verification_outcome": list(VALID_VERIFICATION_OUTCOME),
            "verification_method": list(VALID_VERIFICATION_METHOD),
        },
        "rules": {
            "evidence_or_low_confidence": (
                "A decision, attempt, or verification needs at least one --evidence "
                "TYPE REF, or --confidence low (validate §16.9)."
            ),
        },
    }


def _record_template(rtype: str) -> str:
    """A copy-pasteable command skeleton for a record type."""
    if rtype == "verification":
        # Verifications are written with `crumb verify`, not `crumb remember`.
        return "\n".join(
            [
                "crumb verify 'WHAT WAS CHECKED (finding id / file / claim)' \\",
                "  --status fixed   # fixed|open|regressed|not_applicable|inconclusive \\",
                "  --method static  # static|runtime|test \\",
                "  --evidence file path/to/file.py:LINE \\",
                "  --note 'what the evidence shows'",
            ]
        )
    lines = [f"crumb remember {rtype} \\", "  --title 'SHORT IMPERATIVE TITLE' \\"]
    flag_for = {h: a for a, h in ATTEMPT_FLAG_SECTIONS}
    for heading in BODY_SECTIONS[rtype]:
        if heading == "Evidence":
            continue  # supplied via --evidence, not a body section
        if rtype == "attempt" and heading in flag_for:
            lines.append(f"  --{flag_for[heading].replace('_', '-')} 'TEXT' \\")
        else:
            lines.append(f"  --set '{heading}' 'TEXT' \\")
    lines.append("  --evidence commit SHA   # or: --confidence low")
    return "\n".join(lines)


def cmd_schema(args: argparse.Namespace) -> int:
    rtype = getattr(args, "schema_type", None)
    if rtype is not None and rtype not in BODY_SECTIONS:
        _emit_error(args, f"unknown record type {rtype!r}; valid: {', '.join(BODY_SECTIONS)}")
        return 2

    if getattr(args, "template", False):
        if rtype is None:
            _emit_error(args, f"--template needs a record type: {', '.join(BODY_SECTIONS)}")
            return 2
        print(_record_template(rtype))
        return 0

    schema = record_schema()
    if rtype is not None:
        schema = {
            "schema_version": schema["schema_version"],
            "record_types": {rtype: schema["record_types"][rtype]},
            "required_frontmatter_keys": schema["required_frontmatter_keys"],
            "derived_frontmatter_keys": schema["derived_frontmatter_keys"],
            "vocabularies": schema["vocabularies"],
            "rules": schema["rules"],
        }

    if args.json:
        _print_json(args, schema)
        return 0

    print(f"breadcrumbs record schema (schema_version {schema['schema_version']})")
    for rt, spec in schema["record_types"].items():
        print(f"\n{rt} — body sections (rendered in order):")
        for s in spec["body_sections"]:
            print(f"  - {s}")
    print("\nRequired frontmatter: " + ", ".join(schema["required_frontmatter_keys"]))
    print("Derived from filename: " + ", ".join(schema["derived_frontmatter_keys"]))
    print("\nVocabularies:")
    for name, vals in schema["vocabularies"].items():
        print(f"  {name + ':':12} " + ", ".join(vals))
    print("\nRule: " + schema["rules"]["evidence_or_low_confidence"])
    print("\nTip: `crumb schema --template <type>` prints a fill-in command skeleton.")
    return 0


# ---- note (question / trap / idea) ----------------------------------------- #

NOTE_KINDS = ("question", "trap", "idea")


# The exact placeholder lines the templates seed — anchored so a *user* line that
# merely resembles them (e.g. "_No fix for the flaky suite yet._") is never
# silently deleted on append.
_TEMPLATE_PLACEHOLDER_LINES = frozenset(
    {
        "_No open questions yet._",
        "_No known traps yet._",
    }
)


def _append_md_block(path: Path, block: str) -> None:
    """Append a `## ` block to a singleton markdown file (open-questions/known-traps).

    The templates seed a `_No … yet._` placeholder line; the first real block drops
    it, later blocks append after the existing content. Idempotency is the caller's
    concern (notes are additive by nature).
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    kept = [ln for ln in text.splitlines() if ln.strip() not in _TEMPLATE_PLACEHOLDER_LINES]
    head = "\n".join(kept).rstrip()
    write_text_atomic(path, (head + "\n\n" if head else "") + block.rstrip() + "\n")


def _sanitize_note_text(value) -> str:
    """Flatten note text/field values to one safe line.

    Notes render as headings and `- key: value` lines inside singleton files, so
    an embedded newline would forge structure (`\\n## …` injects a heading) and a
    literal `<!--` / `-->` pair across two blocks comment-joins everything between
    them out of every reader. Collapse whitespace and neutralize comment markers.
    """
    flat = " ".join(str(value).split())
    return flat.replace("<!--", "< !--").replace("-->", "-- >")


def _question_block(text: str, *, why=None, needs=None, status="open") -> str:
    lines = [f"## Q: {text}", f"- Opened: {now_iso()[:10]}"]
    if why:
        lines.append(f"- Why it matters: {why}")
    if needs:
        lines.append(f"- Needs: {needs}")
    lines.append(f"- Status: {status or 'open'}")
    return "\n".join(lines)


def _trap_block(
    summary: str,
    *,
    slug=None,
    area=None,
    symptom=None,
    why=None,
    safe=None,
    verify=None,
    status="active",
) -> str:
    slug = slug or slugify(summary)
    lines = [f"## trap_{slug}: {summary}"]
    if area:
        lines.append(f"- Area / files: {area}")
    if symptom:
        lines.append(f"- Symptom: {symptom}")
    if why:
        lines.append(f"- Why: {why}")
    if safe:
        lines.append(f"- Safe approach: {safe}")
    if verify:
        lines.append(f"- Verification: {verify}")
    # Written explicitly even though `active` is the parsed default: a trap is a
    # long-lived warning, and the bullet is what tells the human reading this
    # file that the trap has a lifecycle and can be retired.
    lines.append(f"- Status: {status or 'active'}")
    return "\n".join(lines)


# Machine-readable trap-token index consumed by the PreToolUse hook's cheap risk
# pre-filter. Lives under generated/ (rebuilt on every reindex,
# never canonical, skipped by the secret scan like the rest of generated/).
GUARD_PREFILTER_FILENAME = "guard-prefilter.json"


def _build_guard_prefilter(memory_dir: Path) -> dict:
    """Specific tokens + path tokens from traps and do-not-retry attempts.

    This is what lets `crumb hook guard` escalate a trap-shaped but
    routine-looking command (`pytest -n auto`) to full guard scoring without
    hardcoding any particular trap in a regex and without record I/O on the
    common hook path — the near-miss class that motivated hooks in the first place.
    """
    tokens: set[str] = set()
    paths: set[str] = set()
    for trap in active_traps(memory_dir):
        text = trap["heading"] + "\n" + trap["content"]
        tokens |= _specific(text)
        paths |= _paths_from_text(text)
    for rec in active_attempts(memory_dir):
        if _attempt_has_do_not_retry(rec):
            text = (
                (rec.meta.get("title") or "") + "\n" + rec.sections.get("Do Not Retry Unless", "")
            )
            tokens |= _specific(text)
            paths |= _paths_from_text(text)
            # Evidence file refs count as paths too. Scraping prose alone meant
            # `--evidence file src/billing.py` — the documented way to attach a
            # file — contributed nothing here, so an Edit to that exact file
            # sailed past the hook while `crumb guard "edit src/billing.py"`
            # said PAUSE. Full scoring already reads these (see _item_from_record);
            # the pre-filter must see the same files or it gates them out.
            paths |= set(_evidence_refs(rec, ("file", "path")))
    return {"tokens": sorted(tokens), "paths": sorted(paths)}


def try_reindex_projections(
    memory_dir: Path, project_root: Path | None = None
) -> tuple[bool, str | None]:
    """`reindex_projections` plus the reason it failed, for callers that report it.

    The bool-only form swallowed the exception, so `crumb reindex` could only say
    "Reindex failed" with no cause while projections silently stopped refreshing.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root) if project_root is not None else memory_dir.parent
    try:
        packet = build_resume_packet(memory_dir, project_root, stale_days=STALE_AGE_DAYS)
        gen = memory_dir / "generated"
        gen.mkdir(parents=True, exist_ok=True)
        write_text_atomic(gen / "resume-packet.md", render_packet_markdown(packet))
        # Guard pre-filter index: a token/path index over traps and
        # do-not-retry attempts, so the PreToolUse hook can spot trap-shaped
        # *routine* commands with one small-file read instead of walking records.
        write_text_atomic(
            gen / GUARD_PREFILTER_FILENAME,
            json.dumps(_build_guard_prefilter(memory_dir), indent=0, sort_keys=True) + "\n",
        )
        return True, None
    except Exception as exc:  # pragma: no cover - defensive; never block a write
        return False, f"{type(exc).__name__}: {exc}"


def reindex_projections(memory_dir: Path, project_root: Path | None = None) -> bool:
    """Rebuild the generated/ projections from the canonical records.

    Called after every canonical mutation (remember/note/verify/mark-status/
    capture session, and their MCP equivalents) so the static projections never
    silently desync from
    the records — the drift the review caught on the MCP write path. The live
    resume packet always recomputes; this keeps the *file* a consumer might trust
    (the committed snapshot, a human reading generated/) in step with it.

    Best-effort by default: a refresh failure must never fail the write that
    triggered it. `project_root` defaults to the store's parent (memory lives at
    <root>/.project-memory). Returns True iff a projection was written; use
    `try_reindex_projections` when the caller can report *why* it failed.
    """
    return try_reindex_projections(memory_dir, project_root)[0]


# Back-compat alias: the note() writer and tests referenced the original name.
_refresh_resume_packet = reindex_projections


def note(
    memory_dir: Path,
    project_root: Path,
    kind: str,
    text: str,
    *,
    fields: dict | None = None,
    tags: list[str] | None = None,
    agent: str | None = None,
) -> dict:
    """Write an open-question / known-trap / idea and refresh projections.

    Closes the read/write asymmetry: these were readable (MCP resources, resume,
    audit) but had no writer. question/trap append a parse-verified block to the
    singleton markdown file; idea goes through the same `write_record` + validate
    gate as `remember`. On any parse/validate failure the write is reverted.
    """
    fields = fields or {}
    text = text.strip()
    if not text:
        return {"ok": False, "error": "note text must not be empty"}
    if kind in ("question", "trap"):
        # question/trap render as single-line headings + `- key: value` lines in
        # a shared singleton file, so text and field values are flattened and
        # comment-marker-neutralized before they touch the file.
        text = _sanitize_note_text(text)
        fields = {
            k: (_sanitize_note_text(v) if isinstance(v, str) else v) for k, v in fields.items()
        }

    if kind == "question":
        path = memory_dir / "open-questions.md"
        # The CLI constrains `--status` through argparse; this is the same gate
        # for the MCP writer, which passes fields straight through. An
        # unrecognized status is not a harmless typo: every reader treats
        # anything but `open` as settled, so it would silently hide the question
        # from the packet, from guard and from the aged-question warning.
        qstatus = (fields.get("status") or "open").strip().lower()
        if qstatus not in VALID_QUESTION_STATUS:
            return {
                "ok": False,
                "error": f"invalid question status {fields.get('status')!r}; valid: "
                + ", ".join(VALID_QUESTION_STATUS),
            }
        fields = {**fields, "status": qstatus}
        if any(q["question"] == text for q in load_open_questions(memory_dir)):
            return {
                "ok": False,
                "error": f"question already recorded: {text!r} (reopen it with "
                "`crumb mark-status <id> open`)",
            }
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        _append_md_block(
            path,
            _question_block(
                text, why=fields.get("why"), needs=fields.get("needs"), status=fields.get("status")
            ),
        )
        if not any(q["question"] == text for q in load_open_questions(memory_dir)):
            write_text_atomic(path, before)  # revert
            return {"ok": False, "error": "appended question did not parse back; reverted"}
        # `ref` is the question itself (its identity in open-questions.md); `id`
        # is the handle `mark-status` and `search` take.
        result = {
            "ok": True,
            "kind": "question",
            "id": question_item_id(text),
            "ref": text,
            "path": str(path),
        }
        hint = _block_reachability_hint(
            "\n".join(str(fields.get(k) or "") for k in ("why", "needs")) + "\n" + text,
            "question",
        )
        if hint:
            result["hint"] = hint

    elif kind == "trap":
        path = memory_dir / "known-traps.md"
        # Same budget as record filenames: an auto-derived slug is the whole
        # trap text, and an unbounded one turns every downstream mention
        # (resume packet, guard reasons) into a paragraph-long id. Found by
        # dogfooding this repo's own store on day one. An explicit --slug is
        # the author's to spend as they like.
        slug = fields.get("slug") or truncate_slug(slugify(text))
        marker = f"trap_{slug}:".lower()
        # A duplicate heading would shadow the earlier block in every dict-based
        # reader, leaving its body unreachable — refuse instead.
        if any(b["heading"].lower().startswith(marker) for b in load_traps(memory_dir)):
            return {
                "ok": False,
                "error": f"trap trap_{slug} already exists; reopen it with "
                f"`crumb mark-status trap_{slug} active`, or pass a distinct "
                "slug (--slug / fields.slug) to record a separate trap",
            }
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        _append_md_block(
            path,
            _trap_block(
                text,
                slug=slug,
                area=fields.get("area"),
                symptom=fields.get("symptom"),
                why=fields.get("why"),
                safe=fields.get("safe"),
                verify=fields.get("verify"),
            ),
        )
        if not any(b["heading"].lower().startswith(marker) for b in load_traps(memory_dir)):
            write_text_atomic(path, before)  # revert
            return {"ok": False, "error": "appended trap did not parse back; reverted"}
        # `id` alongside `ref`: the id is what `mark-status`, `traps --confirm`
        # and `search` take, and a caller should not have to know that this one
        # command calls it something else (C4). They are the same string for a
        # trap — the printed id is the truncated slug that was stored, so
        # `mark-status <printed id>` resolves.
        result = {
            "ok": True,
            "kind": "trap",
            "id": f"trap_{slug}",
            "ref": f"trap_{slug}",
            "path": str(path),
        }
        # known-traps.md documents a five-field format at the top of the file,
        # but the writer accepts a bare summary, so the whole trap lands on the
        # heading line and the documented template goes unused. Say so at the
        # point of writing — a warning with no mechanism is what the next agent
        # cannot act on.
        if not any(fields.get(k) for k in ("area", "symptom", "why", "safe", "verify")):
            result["hint"] = (
                "summary line only — known-traps.md documents Area / Symptom / Why / "
                "Safe approach / Verification; pass --area/--symptom/--why/--safe/"
                "--verify so the next agent gets the mechanism, not just the warning"
            )
        else:
            # F-4. Only when the fuller hint above did not already fire: a
            # summary-only trap is unreachable *and* mechanism-less, and one
            # message naming the flags to fix both beats two overlapping ones.
            hint = _block_reachability_hint(
                "\n".join(
                    str(fields.get(k) or "") for k in ("area", "symptom", "why", "safe", "verify")
                )
                + "\n"
                + text,
                "trap",
            )
            if hint:
                result["hint"] = hint

    elif kind == "idea":
        sections = dict(fields.get("sections") or {})
        try:
            path, meta = write_record(
                memory_dir, project_root, "idea", text, sections, tags=tags, agent=agent
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}
        fails = _validate_new_file(memory_dir, path)
        if fails:
            path.unlink()  # revert
            return {
                "ok": False,
                "error": "idea rejected by validate: " + "; ".join(f["message"] for f in fails),
            }
        result = {"ok": True, "kind": "idea", "id": meta["id"], "path": str(path)}
        hint = _record_reachability_hint(path, "idea")
        if hint:
            result["hint"] = hint

    else:
        return {"ok": False, "error": f"unknown note kind {kind!r}; use {', '.join(NOTE_KINDS)}"}

    _refresh_resume_packet(memory_dir, project_root)
    return result


def cmd_note(args: argparse.Namespace) -> int:
    kind = getattr(args, "note_kind", None)
    if kind not in NOTE_KINDS:
        _emit_error(args, f"specify a note kind: `crumb note {'|'.join(NOTE_KINDS)}`")
        return 2

    # `remember` takes `--title` and `note` takes a positional, and an agent that
    # has just written a decision reaches for `--title` on the very next call.
    # The old failure was `unrecognized arguments: --title …` with an exit 2 —
    # correct, but it named no alternative, and a multi-line body pushed the
    # error prefix out of a truncated view. `--title` is now simply the same
    # argument by the other name.
    text = (getattr(args, "title", None) or getattr(args, "text", None) or "").strip()
    if getattr(args, "title", None) and getattr(args, "text", None):
        _emit_error(args, f"pass the {kind} summary once: either positionally or as --title")
        return 2
    if not text:
        _emit_error(
            args,
            f"a {kind} needs a one-line summary: "
            f'`crumb note {kind} "<summary>"` (or --title "<summary>")',
        )
        return 2

    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    fields: dict = {}
    tags: list[str] | None = None
    section_notes: list[str] = []
    if kind == "question":
        fields = {"why": args.why, "needs": args.needs, "status": args.status}
    elif kind == "trap":
        fields = {
            "slug": args.slug,
            "area": args.area,
            "symptom": args.symptom,
            "why": args.why,
            "safe": args.safe,
            "verify": args.verify,
        }
    else:  # idea
        idea_sections, section_notes = _collect_set_sections("idea", args.set)
        for note_text in section_notes:
            _emit_warning(args, note_text)
        fields = {"sections": idea_sections}
        tags = _split_tags(args.tags)

    result = note(
        memory_dir,
        root,
        kind,
        text,
        fields=fields,
        tags=tags,
        agent=getattr(args, "agent", None),
    )
    if not result.get("ok"):
        _emit_error(args, result.get("error", "note failed"))
        return 1

    if section_notes:
        result["warnings"] = section_notes
    if args.json:
        _print_json(args, result)
    else:
        print(f"Noted {kind}: {result.get('id') or result.get('ref')}")
        print(f"  file: {result['path']}")
        if result.get("hint"):
            print(f"  note: {result['hint']}")
    return 0


# ---- verify ---------------------------------------------------------------- #


def verify(
    memory_dir: Path,
    project_root: Path,
    subject: str,
    *,
    status: str,
    method: str | None = None,
    note: str | None = None,
    evidence: list[dict] | None = None,
    tags: list[str] | None = None,
    confidence: str | None = None,
    agent: str | None = None,
) -> dict:
    """Record a verification result — a finding about reality.

    The single most common agentic output ("I checked X; here is its state") had
    no home: it was mis-filed as a decision/attempt, polluting those categories.
    A verification is a first-class durable record whose `outcome` (fixed/open/
    regressed/not_applicable/inconclusive) and `subject`/`method` live in
    frontmatter so `search` and the resume packet can filter on them. It goes
    through the same write_record + validate gate as everything else; an invalid
    write is reverted.
    """
    subject = (subject or "").strip()
    if not subject:
        return {"ok": False, "error": "verification subject must not be empty"}
    if status not in VALID_VERIFICATION_OUTCOME:
        return {
            "ok": False,
            "error": f"invalid status {status!r}; valid: {', '.join(VALID_VERIFICATION_OUTCOME)}",
        }
    if method is not None and method not in VALID_VERIFICATION_METHOD:
        return {
            "ok": False,
            "error": f"invalid method {method!r}; valid: {', '.join(VALID_VERIFICATION_METHOD)}",
        }

    evidence = evidence or []
    # Evidence-or-low-confidence rule (validate §16.9) — a claim about reality with
    # no evidence is not high-confidence. Forced to low rather than failing.
    if not evidence and confidence != "low":
        confidence = "low"

    sections = {"Subject": subject, "Outcome": status}
    if method:
        sections["Method"] = method
    if note:
        sections["Notes"] = note

    try:
        path, meta = write_record(
            memory_dir,
            project_root,
            "verification",
            f"{subject} — {status}",
            sections,
            tags=tags,
            evidence=evidence,
            confidence=confidence,
            agent=agent,
            extra={"subject": subject, "outcome": status, "method": method},
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}

    fails = _validate_new_file(memory_dir, path)
    if fails:
        path.unlink()  # revert
        return {
            "ok": False,
            "error": "verification rejected by validate: " + "; ".join(f["message"] for f in fails),
        }

    reindex_projections(memory_dir, project_root)
    out = {
        "ok": True,
        "id": meta["id"],
        "subject": subject,
        "outcome": status,
        "method": method,
        "confidence": meta["confidence"],
        "path": str(path),
    }
    # F-4: verifications are the record type this bites hardest — the audit found
    # four unreachable ones in a single store — because `crumb verify "<claim>"
    # --status fixed` is a complete, valid call that carries neither tags nor
    # evidence.
    hint = _record_reachability_hint(path, "verification")
    if hint:
        out["hint"] = hint
    return out


def cmd_verify(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    subject = args.subject
    if subject is None:
        if not _interactive():
            _emit_error(args, "non-interactive: SUBJECT is required")
            return 2
        subject = input("Subject (finding id / file / claim checked): ").strip()

    result = verify(
        memory_dir,
        root,
        subject or "",
        status=args.status,
        method=args.method,
        note=args.note,
        evidence=_parse_evidence_pairs(args.evidence),
        tags=_split_tags(args.tags),
        confidence=args.confidence,
        agent=getattr(args, "agent", None),
    )
    if not result.get("ok"):
        _emit_error(args, result.get("error", "verify failed"))
        return 1

    if args.json:
        _print_json(args, result)
    else:
        print(f"Verified {result['subject']}: {result['outcome']}")
        print(f"  file: {result['path']}")
        if result["confidence"] == "low":
            print("  note: no evidence; confidence set to low.")
        if result.get("hint"):
            print(f"  note: {result['hint']}")
    return 0


# ---- mark-status ----------------------------------------------------------- #


# The always-on context a session starts with is dominated by known-traps.md:
# 167 KB and 77 active traps in the field store, growing monotonically because
# nothing ever ages out. Age alone must not retire a trap, so this reports rather
# than acts — it names the candidates and the one command that retires them.
TRAPS_STALE_DAYS_DEFAULT = 180


def trap_report(memory_dir: Path, *, stale_days: int | None = None, status: str | None = None):
    """Traps with their size and staleness, oldest confirmation first (R6)."""
    rows = []
    for trap in load_traps(memory_dir):
        if status and (trap.get("status") or "active") != status:
            continue
        confirmed = trap_last_confirmed(trap)
        age = _age_days(confirmed) if confirmed else None
        if stale_days is not None and (age is not None and age < stale_days):
            continue
        body = trap.get("content") or trap.get("body") or ""
        rows.append(
            {
                "id": trap["id"],
                "status": trap.get("status") or "active",
                "summary": trap.get("summary") or "",
                "last_confirmed": confirmed,
                "age_days": age,
                "approx_tokens": approx_tokens(trap["heading"] + "\n" + body),
            }
        )
    # Never-confirmed first (age None sorts highest), then oldest confirmation.
    rows.sort(key=lambda r: (r["age_days"] is not None, -(r["age_days"] or 0)))
    return rows


def cmd_traps(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    if args.confirm:
        result = set_trap_confirmed(memory_dir, args.confirm)
        if not result.get("ok"):
            _emit_error(args, result.get("error", "confirm failed"))
            return 1
        if args.json:
            _print_json(args, result)
        else:
            print(f"Confirmed {result['id']}: still true as of {result['last_confirmed']}")
            print(f"  file: {result['path']}")
        return 0

    stale_days = args.stale if args.stale is not None else None
    rows = trap_report(memory_dir, stale_days=stale_days, status=args.status)
    total = sum(r["approx_tokens"] for r in rows)
    if args.json:
        _print_json(
            args,
            {"traps": rows, "items": rows},
            summary={"count": len(rows), "approx_tokens": total},
        )
        return 0

    if not rows:
        scope = f" not confirmed in {stale_days} day(s)" if stale_days is not None else ""
        print(f"traps: none{scope}.")
        return 0
    header = f"traps: {len(rows)} trap(s), ~{total} tokens of always-on context"
    if stale_days is not None:
        header += f" (not confirmed in {stale_days} day(s))"
    print(header + "\n")
    for r in rows:
        when = r["last_confirmed"] or "never confirmed"
        age = f", {r['age_days']}d ago" if r["age_days"] is not None else ""
        print(f"  [{r['status']}] {r['id']} — {when}{age}, ~{r['approx_tokens']} tokens")
        if r["summary"]:
            print(f"      {r['summary']}")
    print(
        "\nStill true? `crumb traps --confirm <id>`. "
        'No longer? `crumb mark-status <id> resolved --reason "..."`.'
    )
    return 0


def cmd_retitle(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2
    result = set_record_title(memory_dir, args.record_id, args.title, agent=args.agent)
    if not result.get("ok"):
        _emit_error(args, result.get("error", "retitle failed"))
        return 1
    if args.json:
        _print_json(args, result)
    else:
        print(f"Retitled {result['id']}: {result['from']!r} -> {result['to']!r}")
        print(f"  file: {result['path']}")
        print(
            "  note: the id, slug and filename are unchanged — they are what "
            "other records reference."
        )
    return 0


def cmd_mark_status(args: argparse.Namespace) -> int:
    """CLI surface over `set_record_status` (already exposed via MCP).

    README/docs described marking records `disputed`/`stale`/`superseded`, but
    the only writer was the MCP tool — closing that gap gives the plain-file
    workflow the same lifecycle mutation.
    """
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    status = args.new_status or args.status_flag
    if not status:
        _emit_error(
            args,
            "a status is required: `crumb mark-status <ID> <STATUS>` or --status <STATUS>. "
            f"Records and traps: {', '.join(VALID_STATUS)}; "
            f"questions: {', '.join(VALID_QUESTION_STATUS)}",
        )
        return 2
    if args.new_status and args.status_flag and args.new_status != args.status_flag:
        _emit_error(
            args,
            f"conflicting status: {args.new_status!r} positionally and "
            f"{args.status_flag!r} via --status; pass one",
        )
        return 2

    result = set_record_status(
        memory_dir,
        args.record_id,
        status,
        args.reason or "",
        agent=getattr(args, "agent", None),
        superseded_by=args.superseded_by,
    )
    if not result.get("ok"):
        _emit_error(args, result.get("error", "status change failed"))
        return 1
    if args.json:
        _print_json(args, result)
    else:
        print(f"Marked {result['id']}: {result['from']} -> {result['to']}")
        print(f"  file: {result['path']}")
    return 0


# ---- capture session ------------------------------------------------------- #


def _newest_session_record(memory_dir: Path) -> Record | None:
    """The most recently created session record, or None if there are none."""
    recs = load_records(memory_dir, types=("session",))
    if not recs:
        return None
    recs = sorted(recs, key=lambda r: (_dt_sort_key(r.meta.get("created_at")), r.stem))
    return recs[-1]


def _last_session_commit(memory_dir: Path, exclude: Path | None = None) -> str | None:
    """Commit of the newest session record — the diff base for the next capture.

    `exclude` skips one record: when a capture *coalesces into* the newest
    snapshot (F-6), that snapshot is the record being rewritten, so using its own
    commit as the diff base would make the window empty and erase the work the
    earlier firings had already summarized. The previous session boundary is the
    honest base.
    """
    recs = load_records(memory_dir, types=("session",))
    if exclude is not None:
        exclude = Path(exclude).resolve()
        recs = [r for r in recs if r.path.resolve() != exclude]
    recs = sorted(recs, key=lambda r: (_dt_sort_key(r.meta.get("created_at")), r.stem))
    commit = recs[-1].meta.get("commit") if recs else None
    if commit in (None, "", NO_GIT_COMMIT):
        return None
    return commit


# ---- F-6: one machine snapshot per host session, not per Stop ---------------- #

# Claude Code's `Stop` fires at every turn boundary, so one working session
# produced three session records in the 0.1.11 field audit (2:39, 2:58, 3:16 for
# a session that began at 2:47) — and `audit` then flagged the resulting 101
# records as bloat. The tool was generating its own bloat warning.
#
# `_hook_capture_is_redundant` already suppresses a firing where *nothing* moved.
# The remaining case is the normal one: work moved, so a snapshot is warranted —
# but it is the *same session's* snapshot, and should replace the previous one
# rather than accumulate beside it. A machine snapshot is a disposable "where
# things stand" marker; there is no value in keeping five of them from one
# afternoon, and the stale `dirty_files` list on the older ones is actively
# misleading.
#
# Only machine snapshots coalesce. A record a human or agent authored through
# `crumb capture session` carries a real Next Action and narrative; it is never
# rewritten.
COALESCE_WINDOW_MINUTES = 90


def _is_machine_snapshot(rec: Record) -> bool:
    """True for a Stop-hook snapshot: placeholder Next Action, no narrative."""
    if rec.error or rec.rtype != "session":
        return False
    return _is_placeholder(rec.sections.get("Next Action", ""))


def _coalescible_snapshot(
    memory_dir: Path,
    root: Path,
    host_session: str | None,
    *,
    window_minutes: int = COALESCE_WINDOW_MINUTES,
) -> Record | None:
    """The machine snapshot this capture should overwrite, or None to write anew.

    Two ways to be "the same session", in order of confidence:
      1. Same host session id — exact, when the harness supplies one.
      2. Same branch, within `window_minutes` — the fallback for a payload with
         no session id. Deliberately not keyed on commit as well: a session that
         commits between two Stops is the *common* case, and refusing to coalesce
         across it would leave the audit's exact complaint unfixed.
    """
    rec = _newest_session_record(memory_dir)
    if rec is None or not _is_machine_snapshot(rec):
        return None

    recorded = rec.meta.get("host_session")
    if host_session and recorded:
        return rec if str(recorded) == str(host_session) else None
    if recorded and not host_session:
        # The snapshot knows which session it belongs to and this firing does
        # not — coalescing would risk folding two sessions together.
        return None

    if (rec.meta.get("branch") or "") != git_branch(root):
        return None
    stamped = _parse_iso(rec.meta.get("updated_at") or rec.meta.get("created_at"))
    if stamped is None:
        return None
    # Same naive-timestamp localization `_age_days` uses, so the subtraction is
    # always tz-aware; that helper is day-resolution and this needs minutes.
    if stamped.tzinfo is None:
        stamped = stamped.astimezone()
    delta = (datetime.now().astimezone() - stamped).total_seconds()
    return rec if 0 <= delta <= window_minutes * 60 else None


def _coalesce_into(
    rec: Record,
    sections: dict[str, str],
    root: Path,
    agent: str | None,
    *,
    include_memory: bool = False,
) -> Path:
    """Rewrite an existing machine snapshot in place with fresh git state.

    Identity is preserved — id, slug, filename, `created_at` and `created_by` all
    keep naming the moment the session's first snapshot was taken, which is the
    fact worth keeping. Only what has moved is updated.
    """
    meta = dict(rec.meta)
    derived = derive_fields(root, agent=agent, include_memory=include_memory)
    meta["updated_at"] = derived["created_at"]
    meta["branch"] = derived["branch"]
    meta["commit"] = derived["commit"]
    meta["dirty_files"] = derived["dirty_files"]
    text = render_frontmatter(meta) + "\n\n" + render_body("session", sections)
    write_text_atomic(rec.path, text)
    return rec.path


# git's canonical empty-tree object — diff base when the window reaches the root commit.
_GIT_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# How far back a git prefill will look, in commits. The diff base is the commit of
# the newest session record, which can be weeks old on a store that has been idle —
# and then one session record claims every commit since it (50 commits and
# "807 files changed, +90962/-14441" attributed to a single sitting). That is the
# *first* capture after any gap, which is exactly when someone is deciding whether
# to trust the tool. Past this cap the prefill falls back to the same bounded
# recent-history window it uses when there is no prior record at all, and says so.
GIT_PREFILL_MAX_COMMITS = 20


def _short_ref(ref: str | None) -> str:
    """Render a diff base for humans: short sha, or a name for the empty tree."""
    if not ref:
        return "(unknown)"
    if ref == _GIT_EMPTY_TREE:
        return "the empty tree (repo root)"
    return ref[:7] if re.fullmatch(r"[0-9a-f]{7,40}", ref) else ref


def _summarize_diffstat(shortstat: str | None) -> str:
    """Condense `git diff --shortstat` into one line: 'N files changed, +X/-Y'.

    Inlining the full per-file `--stat` bloats committed session records and can
    trip the secret scanner on path-shaped tokens; a counts-only
    summary avoids both while preserving the at-a-glance signal.
    """
    if not shortstat or not shortstat.strip():
        return "_(no file changes detected)_"
    files = ins = dels = 0
    m = re.search(r"(\d+)\s+files?\s+changed", shortstat)
    if m:
        files = int(m.group(1))
    m = re.search(r"(\d+)\s+insertions?\(\+\)", shortstat)
    if m:
        ins = int(m.group(1))
    m = re.search(r"(\d+)\s+deletions?\(-\)", shortstat)
    if m:
        dels = int(m.group(1))
    return f"{files} files changed, +{ins}/-{dels}"


def _git_prefill(root: Path, since: str | None, *, include_memory: bool = False) -> dict[str, str]:
    """Pre-fill Work Completed / Files Touched / Commands from git.

    With a prior-session `since` commit no more than `GIT_PREFILL_MAX_COMMITS`
    back, the window is `since..HEAD`. Otherwise — no prior record, an unreachable
    one, or one too far back to be one session's work — the window is the last
    `GIT_PREFILL_MAX_COMMITS` commits (Files Touched diffs from the parent of the
    oldest commit in that window, or the empty tree if that reaches the root).
    Either way the prefill states the window it used, so a big number can be read
    for what it is instead of taken as a claim about one sitting.
    """
    if not is_git_repo(root):
        return {
            "Work Completed": "_(no git history available)_",
            "Files Touched": "_(no git history available)_",
            "Commands / Verification": _EMPTY_SECTION,
        }
    # Validate the since-ref; if bad, fall back to recent history.
    recorded = since
    if since and _git_out(root, "rev-parse", "--verify", f"{since}^{{commit}}") is None:
        since = recorded = None

    # Cap the lookback. Dropping `since` here re-uses the bounded
    # recent-history window below rather than inventing a second one.
    ahead = 0
    if since:
        raw = _git_out(root, "rev-list", "--count", f"{since}..HEAD")
        ahead = int(raw) if (raw or "").strip().isdigit() else 0
        if ahead > GIT_PREFILL_MAX_COMMITS:
            since = None

    if since:
        log = _git_out(root, "log", "--oneline", "--no-decorate", f"{since}..HEAD")
        base: str | None = since
    else:
        log = _git_out(
            root, "log", "--oneline", "--no-decorate", "-n", str(GIT_PREFILL_MAX_COMMITS)
        )
        rev_list = _git_out(root, "rev-list", f"--max-count={GIT_PREFILL_MAX_COMMITS}", "HEAD")
        base = None
        if rev_list:
            oldest = rev_list.splitlines()[-1]
            parent = _git_out(root, "rev-parse", "--verify", f"{oldest}^")
            if parent:
                base = parent
            elif _git_out(root, "rev-parse", "--is-shallow-repository") == "true":
                # In a shallow clone the oldest visible commit is the shallow
                # boundary, not the root — diffing from the empty tree would
                # record the entire repo as "Files Touched".
                # Diff from the boundary commit instead: bounded, slightly
                # under-counting (its own changes are excluded) rather than
                # wildly over-counting.
                base = oldest
            else:
                base = _GIT_EMPTY_TREE

    shortstat = _git_out(root, "diff", "--shortstat", base, "HEAD") if base else None

    work = "\n".join(f"- {line}" for line in log.splitlines()) if log else "_(no new commits)_"

    # The diffstat describes the *commit range* only, so a session whose work is
    # still uncommitted recorded "no file changes detected" in the same record
    # whose `dirty_files` frontmatter listed 25 paths — a record contradicting
    # itself, read by the next agent as "that session did nothing". Name
    # the scope, and count the uncommitted files (count only: inlining the paths
    # is what §6.1 keeps out of committed records).
    dirty = git_dirty_files(root, include_memory=include_memory)
    files = _summarize_diffstat(shortstat)
    if base and shortstat and shortstat.strip():
        files = f"{files} (vs `{_short_ref(base)}`)"
    elif dirty:
        files = "_(no committed changes in this window)_"
    if dirty:
        files += f" — {len(dirty)} uncommitted file(s), see `dirty_files`"

    # Name the window in the record itself. A prefill is a machine's guess at what
    # a session did; without its diff base the counts read as a claim about this
    # sitting, which is how "807 files changed" ended up in a record for an
    # afternoon's work.
    if since:
        window = (
            f"_Prefill window: `{_short_ref(since)}`..HEAD — "
            f"{ahead} commit(s) since the last session record._"
        )
    elif recorded:
        window = (
            f"_Prefill window: last {GIT_PREFILL_MAX_COMMITS} commits "
            f"(`{_short_ref(base)}`..HEAD). The last session record is at "
            f"`{_short_ref(recorded)}`, {ahead} commits back — too far to attribute "
            "to one session, so the older commits are not counted here._"
        )
    else:
        window = (
            f"_Prefill window: last {GIT_PREFILL_MAX_COMMITS} commits "
            f"(`{_short_ref(base)}`..HEAD) — no prior session record to diff from._"
        )
    return {
        "Work Completed": f"{work}\n\n{window}",
        "Files Touched": files,
        "Commands / Verification": _EMPTY_SECTION,
    }


# A derived session title is capped here: long enough for a real clause, short
# enough that the filename it becomes stays readable.
SESSION_TITLE_MAX_CHARS = 72
SESSION_TITLE_FALLBACK = "session"

# `- 4f1c2ab fix: …` — the git prefill's own commit lines. The subject is the
# title; the sha is not.
_TITLE_SHA_PREFIX_RE = re.compile(r"^[0-9a-f]{7,40}\s+")


def _title_from_text(text: str) -> str:
    """A short human title from the first meaningful line of `text`, or ''."""
    for line in (text or "").splitlines():
        line = line.strip().lstrip("-*#").strip().strip("`")
        line = _TITLE_SHA_PREFIX_RE.sub("", line)
        if not line or _is_placeholder(line):
            continue
        # First sentence only — a Next Action is often a paragraph.
        line = re.split(r"(?<=[.!?])\s+", line, maxsplit=1)[0].strip().rstrip(".;:,")
        if not line:
            continue
        if len(line) > SESSION_TITLE_MAX_CHARS:
            cut = line[:SESSION_TITLE_MAX_CHARS].rsplit(" ", 1)[0]
            line = cut or line[:SESSION_TITLE_MAX_CHARS]
        return line
    return ""


def _derive_session_title(sections: dict[str, str], focus: str | None) -> str:
    """Name a session from what the caller already said about it (R1).

    `--title` was optional and fell back to the constant `session`, and an agent
    under context pressure skips optional flags: 90% of a 310-session field
    store was titled `session`, with the id, slug and filename carrying the same
    nothing. `crumb search` ranks on title, so those records were effectively
    invisible to the tool that exists to find them.

    Requiring `--title` would have prevented all of them, but the caller has
    already written the sentence we need — the Next Action is mandatory, and the
    focus and the work summary are usually there too. Deriving beats asking for
    the same fact twice.
    """
    candidates = [focus or "", sections.get("Next Action", "")]
    candidates += [sections.get(h, "") for h in BODY_SECTIONS["session"]]
    for text in candidates:
        title = _title_from_text(text)
        if title:
            return title
    return ""


def cmd_capture_session(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    manifest = load_manifest(memory_dir) or {}
    tracking = manifest.get("session_tracking", "full")

    # F-6: only a machine snapshot coalesces, and only into the *same* session's
    # previous snapshot. `--fast` is the Stop hook's path; an interactive or
    # `--set`-driven capture is authored content and always gets its own record.
    host_session = getattr(args, "host_session", None)
    coalesce = (
        _coalescible_snapshot(memory_dir, root, host_session)
        if (
            getattr(args, "fast", False)
            and not args.set
            and _is_placeholder(args.next_action or "")
        )
        else None
    )

    since = _last_session_commit(memory_dir, exclude=coalesce.path if coalesce else None)
    include_memory = bool(getattr(args, "include_memory", False))
    prefill = _git_prefill(root, since, include_memory=include_memory)

    # Manual section overrides.
    overrides, section_notes = _collect_set_sections("session", args.set)
    for note_text in section_notes:
        _emit_warning(args, note_text)

    sections: dict[str, str] = dict(prefill)
    sections.update(overrides)

    next_action = args.next_action

    if not args.fast:
        # Interactive narrative confirmation (only the parts not supplied).
        if _interactive():
            print("Captured from git:")
            print("  Work Completed:\n" + sections.get("Work Completed", ""))
            print("  Files Touched:\n" + sections.get("Files Touched", ""))
            for heading in (
                "Starting Context",
                "Decisions Made",
                "Attempts / Failures",
                "Open Questions",
            ):
                if heading not in overrides:
                    val = _prompt_line(f"{heading} (enter to skip): ")
                    if val:
                        sections[heading] = val
            if next_action is None:
                next_action = _prompt_line("Next Action (required): ")

    if next_action:
        sections["Next Action"] = next_action

    # Next Action is required for a valid session record (§16.10).
    if not (sections.get("Next Action") or "").strip():
        _emit_error(
            args,
            'a session needs a Next Action: pass --next "..." (required on --fast)',
        )
        return 2

    title = args.title or _derive_session_title(sections, args.focus) or SESSION_TITLE_FALLBACK
    if coalesce is not None:
        before = coalesce.path.read_text(encoding="utf-8")
        path = _coalesce_into(coalesce, sections, root, args.agent, include_memory=include_memory)
        meta = dict(coalesce.meta)
        fails = _validate_new_file(memory_dir, path)
        if fails:
            write_text_atomic(path, before)  # revert — never leave a broken snapshot
            _emit_error(
                args, "session update failed validation: " + "; ".join(f["message"] for f in fails)
            )
            return 1
    else:
        extra = {"host_session": host_session} if host_session else None
        path, meta = write_record(
            memory_dir,
            root,
            "session",
            title,
            sections,
            agent=args.agent,
            extra=extra,
            include_memory=include_memory,
        )

        fails = _validate_new_file(memory_dir, path)
        if fails:
            path.unlink()
            _emit_error(
                args, "new session failed validation: " + "; ".join(f["message"] for f in fails)
            )
            return 1

    # Refresh handoff + current.
    #
    # Current Focus is NOT defaulted to the Next Action text: doing so rendered
    # the packet's two headline fields as byte-identical ~1.4k-char duplicates
    # (0.1.10 field test, P1-6). An unset --focus keeps the previous Current
    # Focus (update_handoff/update_current retain the old value on empty),
    # which is also the honest reading of "the caller said nothing about focus".
    focus = args.focus or ""
    recently = sections.get("Work Completed", "")
    update_handoff(memory_dir, meta["branch"], meta["commit"], focus, sections["Next Action"])
    update_current(memory_dir, focus, recently)
    # Reindex-on-write: capture mutates three packet inputs (the
    # session record, handoff.md, current.md), so the projections must follow —
    # otherwise the documented session-end flow leaves `validate` failing on
    # freshness until the next resume/reindex.
    reindex_projections(memory_dir, root)

    summary = {
        "session": str(path),
        "id": meta["id"],
        "handoff": str(memory_dir / "handoff.md"),
        "current": str(memory_dir / "current.md"),
        "session_tracking": tracking,
        "fast": bool(args.fast),
        "since": since,
        "coalesced": coalesce is not None,
    }
    if section_notes:
        summary["warnings"] = section_notes
    if args.json:
        _print_json(args, summary)
    else:
        print(f"{'Updated' if coalesce is not None else 'Captured'} session: {meta['id']}")
        print(f"  file:    {path}")
        print("  handoff: updated")
        print("  current: updated")
        if tracking == "distillate":
            print("  note: session_tracking=distillate — sessions/ stays local (gitignored);")
            print("        promote durable items with `crumb remember` to commit them.")
    return 0


# ---- prune — session-snapshot retention (P1-9) ------------------------------ #

# The Stop hook writes a snapshot whenever the work moved, which is right for
# capture (an interrupted session with dirty files is exactly the handoff worth
# keeping) and wrong for retention: the 0.1.10 field-test store held 83 session
# files against 17 durable records, and `audit` could only complain about the
# bloat the tool itself created. Retention is a separate, explicit act.
PRUNE_SESSIONS_KEEP_DEFAULT = 20


def prune_sessions(
    memory_dir: Path,
    root: Path,
    *,
    keep: int = PRUNE_SESSIONS_KEEP_DEFAULT,
    dry_run: bool = False,
) -> dict:
    """Delete old *machine* session snapshots beyond the newest `keep` sessions.

    Only records whose Next Action is still the machine placeholder are
    candidates: a session someone gave a real Next Action (or any enriched
    section) is a deliberate handoff, and deleting human judgement is not this
    command's call. The newest `keep` sessions are never touched regardless —
    they anchor the Stop-hook dedupe and the extraction baseline.
    """
    keep = max(1, keep)
    recs = [r for r in load_records(memory_dir, types=("session",)) if not r.error]
    recs.sort(key=lambda r: r.path.name, reverse=True)
    candidates = [r for r in recs[keep:] if _is_placeholder(r.sections.get("Next Action") or "")]
    deleted = []
    for r in candidates:
        if not dry_run:
            r.path.unlink()
        deleted.append(r.meta.get("id", r.stem))
    if deleted and not dry_run:
        reindex_projections(memory_dir, root)
    return {
        "sessions": len(recs),
        "kept": len(recs) - (0 if dry_run else len(deleted)),
        "deleted": deleted,
        "dry_run": dry_run,
    }


def cmd_prune(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2
    res = prune_sessions(memory_dir, root, keep=args.keep, dry_run=args.dry_run)
    if args.json:
        _print_json(args, res)
        return 0
    verb = "would delete" if res["dry_run"] else "deleted"
    print(
        f"prune sessions: {res['sessions']} session record(s), "
        f"{verb} {len(res['deleted'])} machine snapshot(s)"
    )
    for rid in res["deleted"]:
        print(f"  - {rid}")
    if res["dry_run"] and res["deleted"]:
        print("Re-run without --dry-run to delete.")
    return 0


# ---- handoff.md / current.md updaters -------------------------------------- #

HANDOFF_SECTIONS = [
    "Current Focus",
    "Next Action",
    "Blockers / Open Questions",
    "Active Decisions To Respect",
    "Failed Attempts To Avoid",
    "Known Traps",
    "Likely Relevant Files",
    "Verification Commands",
    "Stale If",
]

CURRENT_SECTIONS = ["Current Focus", "Recently Changed", "Watch Out For"]


def split_md_ordered(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Fence-aware split into (preamble_lines, [(heading, content), …]) on `## `.

    Preserves everything `split_md_sections`'s dict view cannot: the lines before
    the first heading (preamble) and duplicate headings as separate entries.
    Fence-aware: a `## ` line inside a ``` / ~~~
    code fence is content, not a section boundary — otherwise a handoff whose
    Verification Commands section contains fenced expected output is torn apart
    on the next capture (unterminated fence, managed headings injected inside it).
    """
    preamble: list[str] = []
    ordered: list[tuple[str, str]] = []
    current: str | None = None
    buf: list[str] = []
    fence: str | None = None  # the opening fence marker, e.g. "```" or "~~~~"
    for line in text.splitlines():
        fm = re.match(r"^(`{3,}|~{3,})", line.lstrip())
        if fence is not None:
            # Inside a fence everything is content; only a closing fence of the
            # same character and at least the opening length ends it.
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
            (buf if current is not None else preamble).append(line)
            continue
        m = re.match(r"^##\s+(.*)$", line)
        if m:
            if current is not None:
                ordered.append((current, "\n".join(buf).strip()))
            current = m.group(1).strip()
            buf = []
            continue
        if fm:
            fence = fm.group(1)
        (buf if current is not None else preamble).append(line)
    if current is not None:
        ordered.append((current, "\n".join(buf).strip()))
    return preamble, ordered


def split_md_sections(text: str) -> dict[str, str]:
    """Split a plain-markdown file (no frontmatter) into {heading: content} on `## `.

    Fence-aware. Duplicate headings are merged (bodies joined)
    rather than last-wins, so no body silently disappears from the dict view.
    """
    sections: dict[str, str] = {}
    for heading, content in split_md_ordered(text)[1]:
        if heading in sections and content:
            existing = sections[heading]
            sections[heading] = (existing + "\n\n" + content).strip() if existing else content
        elif heading not in sections:
            sections[heading] = content
    return sections


# The Next Action the Stop-hook capture records when no human supplied one. The
# session record states it honestly, but it is a placeholder, not a handoff —
# `_is_placeholder` knows it so a machine capture can never overwrite a real
# Next Action / Current Focus in handoff.md or current.md.
HOOK_SESSION_NEXT_ACTION = "(session ended; see git log)"


def _is_placeholder(text: str) -> bool:
    """True for empty content, the `<...>` template stubs, or `_(...)_` notes.

    A `<...>` autolink URL (contains `://`) is real content, not a stub. The
    `_(...)_` italic form is what the capture prefill emits when there is nothing
    to report (e.g. `_(no new commits)_`) — treating it as a placeholder keeps it
    from clobbering a previously meaningful section. The Stop-hook's stand-in
    Next Action is placeholder text for the same reason.
    """
    t = text.strip()
    if not t:
        return True
    if t == HOOK_SESSION_NEXT_ACTION:
        return True
    if t.startswith("<") and t.endswith(">") and "://" not in t:
        return True
    if t.startswith("_(") and t.endswith(")_"):
        return True
    return False


# Preamble lines the updaters themselves (re)generate — everything else found
# before the first `## ` is user content and must survive a rewrite.
_MANAGED_PREAMBLE_RE = re.compile(
    r"^(#\s|_Last updated:|_Branch:|_Commit:|_What matters right now\.)"
)


def _user_preamble(preamble: list[str]) -> list[str]:
    """User-authored intro lines from a managed file's preamble (may be empty)."""
    kept = [ln for ln in preamble if ln.strip() and not _MANAGED_PREAMBLE_RE.match(ln)]
    return kept


def update_handoff(
    memory_dir: Path, branch: str, commit: str, focus: str, next_action: str
) -> None:
    path = Path(memory_dir) / "handoff.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    preamble, ordered = split_md_ordered(existing)
    sec = split_md_sections(existing)
    focus = "" if _is_placeholder(focus) else focus
    next_action = "" if _is_placeholder(next_action) else next_action
    sec["Current Focus"] = focus or sec.get("Current Focus", "")
    sec["Next Action"] = next_action or sec.get("Next Action", "")

    out = [
        "# Project Handoff",
        "",
        f"_Last updated: {now_iso()}_",
        f"_Branch: {branch}_",
        f"_Commit: {commit}_",
        "",
    ]
    intro = _user_preamble(preamble)
    if intro:
        out += intro + [""]
    for heading in HANDOFF_SECTIONS:
        out.append(f"## {heading}")
        content = sec.get(heading, "")
        out.append("" if _is_placeholder(content) else content)
        out.append("")
    # Preserve any user-added sections that aren't part of the managed layout
    # rather than silently dropping them on every capture. `sec` merges duplicate
    # headings, so no body is lost; `ordered` supplies first-seen order.
    emitted: set[str] = set(HANDOFF_SECTIONS)
    for heading, _content in ordered:
        content = sec.get(heading, "")
        if heading not in emitted and not _is_placeholder(content):
            out += [f"## {heading}", content, ""]
        emitted.add(heading)
    write_text_atomic(path, "\n".join(out).rstrip() + "\n")


def update_current(memory_dir: Path, focus: str, recently: str) -> None:
    path = Path(memory_dir) / "current.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    preamble, ordered = split_md_ordered(existing)
    sec = split_md_sections(existing)
    focus = "" if _is_placeholder(focus) else focus
    recently = "" if _is_placeholder(recently) else recently
    vals = {
        "Current Focus": focus or sec.get("Current Focus", ""),
        "Recently Changed": recently or sec.get("Recently Changed", ""),
        "Watch Out For": sec.get("Watch Out For", ""),
    }
    out = [
        "# Current State",
        "",
        "_What matters right now. Lifespan: days to ~2 weeks. Keep it short and true._",
        "",
    ]
    intro = _user_preamble(preamble)
    if intro:
        out += intro + [""]
    for heading in CURRENT_SECTIONS:
        out.append(f"## {heading}")
        content = vals[heading]
        out.append("" if _is_placeholder(content) else content)
        out.append("")
    # Preserve any user-added sections that aren't part of the managed layout.
    emitted = set(CURRENT_SECTIONS)
    for heading, _content in ordered:
        content = sec.get(heading, "")
        if heading not in emitted and not _is_placeholder(content):
            out += [f"## {heading}", content, ""]
        emitted.add(heading)
    write_text_atomic(path, "\n".join(out).rstrip() + "\n")


# --------------------------------------------------------------------------- #
# resume — bounded, paste-anywhere packet + computed staleness
# --------------------------------------------------------------------------- #
#
# `resume` turns captured memory into a bounded packet (§12) a human or agent can
# paste anywhere to reorient. Two design rules carry the most weight:
#   1. Bounded. Hard cap 5,000 tokens (chars/4 heuristic). Current/handoff/active
#      decisions outrank old session observations; sections are capped, then the
#      packet is trimmed lowest-priority-first until it fits. Never dump raw
#      transcripts (we summarize records; we never paste session bodies).
#   2. Staleness is COMPUTED, not just authored — age + commit-distance of the
#      handoff, aged-unresolved questions/decisions, branch mismatch, and
#      expired/low-confidence records (§12, §15). This is the "did the train of
#      thought go cold?" signal that a scrapbook cannot give you.
#
# The section accessors below (active_decisions / active_attempts / load_traps /
# load_open_questions / parse_handoff_meta) are the reusable surface `guard`
# ranks against — keep them deterministic and side-effect-free.

# Hard token ceiling for the packet (§12: "3,000 to 5,000 tokens").
TOKEN_BUDGET_MAX = 5000

# Default aged-unresolved threshold in days (§12; configurable via --stale-days).
STALE_AGE_DAYS = 21

# One wording for `--stale-days` everywhere it appears. The flag was described as an
# "aged-unresolved threshold" on resume/audit and a "recency de-weighting threshold"
# on guard — two names for one cutoff, and half the confusion that caused.
# It is always the same thing: the age at which a record stops counting as recent.
# Each command appends what it does with that fact.
STALE_DAYS_HELP = (
    f"age cutoff in days — a record older than this counts as aged (default: {STALE_AGE_DAYS})"
)

# Per-section item caps applied before budget trimming (keeps 100s of records bounded).
SECTION_CAPS = {
    "active_decisions": 15,
    "failed_attempts": 15,
    "known_traps": 12,
    "open_questions": 12,
    "likely_files": 20,
    "verification": 12,
    "verifications": 12,
    # Warnings are capped too: every aged decision/question emits
    # a warning, so a neglected store could blow the token bound through the one
    # section the trimmer never touched.
    "warnings": 20,
}

# Order in which sections give up items when the packet is over budget
# (first listed = trimmed first = least load-bearing). Project / Current Focus /
# Next Action are never trimmed; warnings are trimmed only after every
# substantive section is empty, so the hard token bound holds.
TRIM_ORDER = [
    "verification",
    "likely_files",
    "open_questions",
    "verifications",
    "known_traps",
    "failed_attempts",
    "active_decisions",
    "warnings",
]


def approx_tokens(text: str) -> int:
    """Cheap token estimate (chars/4, rounded up). Heuristic, not a real BPE count."""
    return (len(text) + 3) // 4


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 date or datetime; None if unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except (ValueError, TypeError):
        return None


def _age_days(value: str | None) -> int | None:
    """Whole days between `value` (ISO date/datetime) and now; None if unparseable.

    Positive means in the past. Naive timestamps are localized so the subtraction
    is always tz-aware.
    """
    dt = _parse_iso(value)
    if dt is None:
        return None
    now = datetime.now().astimezone()
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return (now - dt).days


def _dt_sort_key(value: str | None) -> float:
    """Chronologically comparable key for an ISO timestamp string.

    Lexicographic sort breaks on heterogeneous UTC offsets (`now_iso()` embeds
    the *local* offset, so DST or a machine move makes '2026-07-01T01:00+02:00'
    sort after '2026-07-01T00:30+00:00' despite being earlier). Unparseable or
    missing timestamps sort oldest.
    """
    dt = _parse_iso(value)
    if dt is None:
        return float("-inf")
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.timestamp()


def git_commit_distance(root: Path, commit: str | None) -> int | None:
    """Commits between `commit` and HEAD (`rev-list --count commit..HEAD`).

    None when there is no git, no recorded commit, or the commit is unknown to
    this checkout (e.g. a since-rebased sha) — callers degrade gracefully.
    """
    if not is_git_repo(root) or commit in (None, "", NO_GIT_COMMIT):
        return None
    if _git_out(root, "rev-parse", "--verify", f"{commit}^{{commit}}") is None:
        return None
    out = _git_out(root, "rev-list", "--count", f"{commit}..HEAD")
    try:
        return int(out) if out is not None else None
    except ValueError:
        return None


# How far back to index HEAD's ancestry in one pass. Beyond this a commit falls
# back to the exact per-commit query; a store with records older than this many
# commits pays one git call for each such distinct sha, which is the old cost.
_REVLIST_INDEX_CAP = 5000


class CommitDistanceIndex:
    """Commit-distance for a whole scoring pass, in one git call instead of N.

    `_score_item` called `git_commit_distance` per scored record, and that is three
    subprocess spawns each (`is_git_repo`, `rev-parse --verify`, `rev-list --count`).
    Guard therefore cost ~3 process spawns per record and got monotonically slower
    as the store grew — while the Stop hook adds a record per qualifying turn, so
    the tool degraded the hot path it had installed. Measured before this: 6.4
    ms/record on Linux in-process, ~17 ms/record on Windows; 87% of guard's runtime
    was `fork_exec` + `poll`, not record I/O.

    One `rev-list --topo-order` builds {sha: position}. Topo order shows no parent
    before all its children, so every commit *before* `sha` in the list is not an
    ancestor of `sha` and is therefore counted by `rev-list --count sha..HEAD`:
    **position is a guaranteed lower bound on the true distance.** That makes
    `position >= GUARD_STALE_DIST_COMMITS` a sound proof of `distance >= threshold`
    with no git call at all. Only a commit whose position is *under* the threshold —
    at most `GUARD_STALE_DIST_COMMITS` records, whatever the store's size — is
    ambiguous and falls through to the exact query. Verdicts are unchanged by
    construction, and the cost stops scaling with the record count.
    """

    def __init__(self, root: Path, threshold: int) -> None:
        self._root = root
        self._threshold = threshold
        self._pos: dict[str, int] | None = None
        self._by_len: dict[int, dict[str, int]] = {}
        self._exact: dict[str, int | None] = {}

    def _index(self) -> dict[str, int]:
        if self._pos is None:
            out = _git_out(
                self._root, "rev-list", "--topo-order", f"--max-count={_REVLIST_INDEX_CAP}", "HEAD"
            )
            self._pos = {sha: i for i, sha in enumerate((out or "").split())}
        return self._pos

    def _position(self, commit: str) -> int | None:
        """Position of a full-or-abbreviated sha in HEAD's topo-ordered ancestry."""
        full = self._index()
        if commit in full:
            return full[commit]
        # Records store `rev-parse --short` shas, so index by the length actually
        # seen. Nearest-HEAD wins an ambiguous prefix — git would refuse, and a
        # collision at abbreviation length is not a case worth a second git call.
        n = len(commit)
        if n >= 40:
            return None
        by_n = self._by_len.get(n)
        if by_n is None:
            by_n = {}
            for sha, pos in full.items():
                by_n.setdefault(sha[:n], pos)
            self._by_len[n] = by_n
        return by_n.get(commit)

    def distance_reaches(self, commit: str | None) -> bool:
        """Is `commit` at least `threshold` commits behind HEAD? (False when unknown.)"""
        if commit in (None, "", NO_GIT_COMMIT):
            return False
        pos = self._position(str(commit))
        if pos is not None and pos >= self._threshold:
            return True  # proven by the lower bound — no git call
        if commit not in self._exact:
            self._exact[str(commit)] = git_commit_distance(self._root, str(commit))
        dist = self._exact[str(commit)]
        return dist is not None and dist >= self._threshold


# ---- section accessors (reused by guard) ----------------------------------- #


def _by_recency(records: list[Record]) -> list[Record]:
    """Newest first, by updated_at then created_at then stem (parsed, not lexicographic)."""
    return sorted(
        records,
        key=lambda r: (
            _dt_sort_key(r.meta.get("updated_at")),
            _dt_sort_key(r.meta.get("created_at")),
            r.stem,
        ),
        reverse=True,
    )


def active_records(memory_dir: Path, rtype: str) -> list[Record]:
    """Parseable `rtype` records with status active (the live ones), newest first."""
    out = [
        r
        for r in load_records(memory_dir, types=(rtype,))
        if not r.error and (r.meta.get("status") or "active") == "active"
    ]
    return _by_recency(out)


def active_decisions(memory_dir: Path) -> list[Record]:
    return active_records(memory_dir, "decision")


def active_attempts(memory_dir: Path) -> list[Record]:
    return active_records(memory_dir, "attempt")


_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _strip_html_comments(text: str) -> str:
    """Drop `<!-- ... -->` regions so template example blocks never leak into a packet."""
    return _HTML_COMMENT_RE.sub("", text)


def _md_heading_spans(text: str) -> list[tuple[int, int, str]]:
    """`(start, end, heading)` for every real `## ` section, as offsets into `text`.

    The span runs from the heading line through the byte before the next heading,
    so a caller can splice one section and leave every other byte of the file
    untouched — which `_md_blocks` cannot offer, because it reads through a
    comment-stripped, whitespace-normalized copy.

    Comment- and fence-aware for the same reasons those readers are: the bundled
    known-traps.md documents its own format *inside* an HTML comment, so a naive
    scan would find the example `## trap_<short-slug>:` heading and edit the
    template instead of a trap.
    """
    comments = [(m.start(), m.end()) for m in _HTML_COMMENT_RE.finditer(text)]
    heads: list[list] = []
    fence: str | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        inert = any(a <= offset < b for a, b in comments)
        fm = re.match(r"^(`{3,}|~{3,})", line.lstrip())
        if inert:
            pass
        elif fence is not None:
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= len(fence):
                fence = None
        else:
            m = re.match(r"^##\s+(.*)$", line)
            if m:
                heads.append([offset, len(text), m.group(1).strip()])
            elif fm:
                fence = fm.group(1)
        offset += len(line)
    for i in range(len(heads) - 1):
        heads[i][1] = heads[i + 1][0]
    return [(a, b, h) for a, b, h in heads]


def _md_blocks(path: Path, head_predicate) -> list[dict]:
    """Split a plain-markdown file on `## ` and keep blocks whose heading matches.

    HTML-comment regions (the template's `<!-- format suggestion -->` examples) are
    stripped first so commented-out sample headings are never mistaken for records.
    """
    if not path.is_file():
        return []
    # Lenient: a bad byte in known-traps.md must not take down guard/resume/audit
    # with it. validate 16.2 reports the file itself.
    text = _strip_html_comments(read_text_lenient(path)[0])
    blocks: list[dict] = []
    for head, body in split_md_sections(text).items():
        if head_predicate(head):
            blocks.append({"heading": head, "body": body})
    return blocks


# Bookkeeping bullets a trap or question block carries alongside its content.
# They are read back as the block's status, and stripped from the text that
# feeds keyword matching — see `_block_content`.
_BLOCK_STATUS_LINE_RE = re.compile(r"\s*-\s*status\s*:\s*(.+)", re.I)
_BLOCK_SUPERSEDED_LINE_RE = re.compile(r"\s*-\s*superseded[ _]by\s*:\s*(.+)", re.I)
_BLOCK_OPENED_LINE_RE = re.compile(r"\s*-\s*opened\s*:\s*(.+)", re.I)
# When somebody last checked that a trap is still true (R6). Authored, not
# derived: age says a trap is old, and an old trap may be perfectly live — only
# a person or an agent re-checking it can say it still applies.
TRAP_CONFIRMED_KEY = "Last confirmed"
_BLOCK_CONFIRMED_LINE_RE = re.compile(r"\s*-\s*last[ _]confirmed\s*:\s*(.+)", re.I)
# The dated provenance comment `mark-status` appends: a fallback "last touched"
# for a trap nobody has confirmed explicitly.
_BLOCK_STAMP_RE = re.compile(r"at (\d{4}-\d{2}-\d{2})")


def trap_last_confirmed(trap: dict) -> str | None:
    """`YYYY-MM-DD` a trap was last confirmed or touched, or None if never."""
    body = (trap.get("body") or trap.get("content") or "") if trap else ""
    match = _BLOCK_CONFIRMED_LINE_RE.search(body)
    if match:
        return _strip_inline_comment(match.group(1)).strip()[:10] or None
    stamps = _BLOCK_STAMP_RE.findall(body)
    return max(stamps) if stamps else None


def _block_status(body: str, default: str) -> str:
    """A trap/question block's lifecycle status, or `default` if it has no bullet.

    Blocks written before traps had a status — every trap in every store that
    predates this — carry no bullet and keep meaning exactly what they meant.
    """
    for line in body.splitlines():
        m = _BLOCK_STATUS_LINE_RE.match(line)
        if m:
            return m.group(1).strip().lower() or default
    return default


def _block_content(body: str) -> str:
    """A trap/question body minus its bookkeeping bullets.

    Keyword matching and the guard pre-filter index must see the *warning*, not
    its bookkeeping: `- Status: active` tokenizes to `statu`/`activ`, so scoring
    the raw body would hand every trap in the store two extra tokens and make any
    action mentioning "status" trip the pre-filter — new alarm noise added by the
    very change meant to let traps be silenced. `- Opened: 2026-08-16` on a
    question is the same kind of nothing.
    """
    return "\n".join(
        ln
        for ln in body.splitlines()
        if not (
            _BLOCK_STATUS_LINE_RE.match(ln)
            or _BLOCK_SUPERSEDED_LINE_RE.match(ln)
            or _BLOCK_OPENED_LINE_RE.match(ln)
        )
    )


def load_traps(memory_dir: Path) -> list[dict]:
    """Trap blocks from known-traps.md (each `## trap_<slug>: <summary>`).

    Each block is returned with its `id` (the `trap_<slug>` heading prefix — the
    same id `note trap` prints and `search` lists), its one-line `summary`, and
    the lifecycle `status` from its `- Status:` bullet. `mark-status` writes that
    bullet; readers that only want traps which still apply use `active_traps`.
    """
    out: list[dict] = []
    for block in _md_blocks(
        Path(memory_dir) / "known-traps.md",
        lambda h: h.lower().startswith("trap"),
    ):
        ident, _, summary = block["heading"].partition(":")
        body = block.get("body") or ""
        out.append(
            {
                **block,
                "id": ident.strip() or "trap",
                "summary": summary.strip(),
                "status": _block_status(body, "active"),
                "content": _block_content(body),
            }
        )
    return out


def active_traps(memory_dir: Path) -> list[dict]:
    """Traps that still apply — what guard, the pre-filter and resume warn about.

    A retired trap stays in the file (and stays findable through `search`, like a
    superseded decision does) but stops being advice.
    """
    return [t for t in load_traps(memory_dir) if t["status"] == "active"]


def load_open_questions(memory_dir: Path) -> list[dict]:
    """Parse `## Q: <question>` blocks into {id, question, opened, status, body}.

    `id` is the `q:<slug>` id `search` lists and `mark-status` takes. The name is
    historical: this returns *all* questions with their status, open or not —
    every caller filters on `status == "open"` itself, or uses `open_questions`.
    """
    out: list[dict] = []
    for block in _md_blocks(
        Path(memory_dir) / "open-questions.md", lambda h: h.lower().startswith("q:")
    ):
        opened = None
        for line in block["body"].splitlines():
            m = _BLOCK_OPENED_LINE_RE.match(line)
            if m:
                opened = m.group(1).strip()
        question = block["heading"][2:].strip()
        out.append(
            {
                "id": question_item_id(question),
                "question": question,
                "opened": opened,
                "status": _block_status(block["body"], "open"),
                "content": _block_content(block["body"]),
                "body": block["body"],
            }
        )
    return out


def open_questions(memory_dir: Path) -> list[dict]:
    """Questions that are still open — the ones that count as live blockers.

    An answered/closed question stays in the file and stays findable through
    `search`, exactly as a retired trap or a superseded decision does.
    """
    return [q for q in load_open_questions(memory_dir) if q["status"] == "open"]


def parse_handoff_meta(text: str) -> dict:
    """Pull branch / commit / updated_at from the handoff header lines.

    Template placeholder values (`<branch>`, `<YYYY-MM-DDTHH:mm:ssZ>`, …) are
    treated as absent: a store that has never been captured must
    not warn "branch mismatch: handoff was written on '<branch>'" or "handoff
    timestamp is not parseable" on every resume/guard/audit until first capture.
    """
    meta: dict = {}
    for line in text.splitlines():
        for key, pattern in (
            ("updated_at", r"_Last updated:\s*(.+?)_\s*$"),
            ("branch", r"_Branch:\s*(.+?)_\s*$"),
            ("commit", r"_Commit:\s*(.+?)_\s*$"),
        ):
            m = re.match(pattern, line)
            if m:
                val = m.group(1).strip()
                if not _is_placeholder(val):
                    meta[key] = val
    return meta


# ---- one-line extractors --------------------------------------------------- #


def _first_line(text: str) -> str:
    """First meaningful line of a body section (skips bullets, stubs, blanks)."""
    for raw in (text or "").splitlines():
        s = raw.strip().lstrip("-*").strip()
        if s and s != _EMPTY_SECTION and not (s.startswith("_(") and s.endswith(")_")):
            return s
    return ""


def _decision_rationale(rec: Record) -> str:
    secs = rec.sections
    return (
        _first_line(secs.get("Rationale", ""))
        or _first_line(secs.get("Decision", ""))
        or (rec.meta.get("title") or rec.stem)
    )


def _attempt_do_not_retry(rec: Record) -> str:
    secs = rec.sections
    return (
        _first_line(secs.get("Do Not Retry Unless", ""))
        or _first_line(secs.get("Why It Failed / Succeeded", ""))
        or (rec.meta.get("title") or rec.stem)
    )


def _evidence_refs(rec: Record, types: tuple[str, ...]) -> list[str]:
    refs: list[str] = []
    for e in rec.meta.get("evidence") or []:
        if isinstance(e, dict) and e.get("type") in types and e.get("ref"):
            refs.append(str(e["ref"]))
    return refs


def _section_lines(handoff_sections: dict, heading: str) -> list[str]:
    content = handoff_sections.get(heading, "")
    if _is_placeholder(content):
        return []
    return [ln.strip().lstrip("-*").strip() for ln in content.splitlines() if ln.strip()]


# ---- staleness ------------------------------------------------------------- #


class HeadTree:
    """Which store files have *reached the current HEAD*: committed in HEAD's
    tree and byte-identical to the worktree copy. Lazy — no git call until asked.

    The branch-mismatch warnings (§15) exist because memory written on another
    branch may describe code this checkout does not have. A record file that is
    in HEAD's tree and unmodified has, by construction, reached this line of
    history — the branch its `branch:` names was merged, squashed, rebased or
    cherry-picked in — so the mismatch is a fact about how the record arrived,
    not a risk to act on. In a branch-per-session workflow (every PR branch is a
    new session) the old check printed a handoff mismatch plus a roll-call of
    every record ever written on *every* resume, guard call and audit: an alarm
    that is always on is one nobody reads, the same failure the guard floors
    were rebuilt to avoid.

    Judged on the **file**, never on the record's `commit:`. That field is HEAD
    at write time — where the *code* was — and a commit can be an ancestor of
    HEAD while the record written beside it sits uncommitted, or committed on a
    branch nobody merged. The file test is also what makes squash and rebase
    merges work: the file arrives whatever happened to the shas.

    Three git calls in total, once per staleness pass, whatever the store size:
    `rev-parse --show-prefix` (the project root may sit below the repo root;
    `ls-tree --full-name` and `status --porcelain` both print repo-root-relative
    paths), `ls-tree -r -z HEAD` (NUL-separated, so no C-quoting to undo), and
    the `status --porcelain` `git_dirty_files` already parses.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._loaded = False
        self._prefix = ""
        self._tracked: frozenset[str] = frozenset()
        self._dirty: frozenset[str] = frozenset()

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not is_git_repo(self._root):
            return
        prefix = _git_out(self._root, "rev-parse", "--show-prefix")
        if prefix is None:
            return
        self._prefix = prefix.strip().replace("\\", "/")
        # None on an unborn HEAD (repo with no commits yet): nothing has reached
        # a HEAD that does not exist, so every mismatch stays a mismatch.
        out = _git_out(
            self._root, "ls-tree", "-r", "-z", "--full-name", "--name-only", "HEAD", "--", "."
        )
        if out is None:
            return
        self._tracked = frozenset(p for p in out.split("\0") if p)
        self._dirty = frozenset(p.replace("\\", "/") for p in git_dirty_files(self._root))

    def contains(self, path: Path | None) -> bool:
        """Is `path` committed at HEAD with no worktree modification? (False when unknowable.)"""
        if path is None:
            return False
        self._load()
        if not self._tracked:
            return False
        try:
            rel = Path(path).resolve().relative_to(self._root.resolve()).as_posix()
        except (ValueError, OSError):
            return False
        full = self._prefix + rel
        return full in self._tracked and full not in self._dirty


def compute_staleness(
    root: Path,
    handoff_meta: dict,
    decisions: list[Record],
    attempts: list[Record],
    questions: list[dict],
    stale_days: int,
    *,
    risks_only: bool = False,
    memory_dir: Path | None = None,
) -> list[str]:
    """All computed staleness/risk warnings (§12, §15). Order: primary first.

    `risks_only` is the guard-context view (0.1.10 field test, P0-4): only
    warnings that flag an *abnormal* state — cold handoff, detached HEAD,
    handoff branch mismatch — are emitted. The full view additionally reports
    routine per-store facts (handoff age when fresh, aged records, low
    confidence, other-branch records); repeating those on every guard call was
    invariant noise, so they stay in resume/doctor/audit where they are read
    once per session, not once per edit.

    Branch mismatches are judged against what has *reached HEAD* (see
    `HeadTree`): a handoff or record whose file is committed at HEAD and clean
    in the worktree was written on a branch that has since landed here, and is
    not reported. `memory_dir` locates `handoff.md` for that test; without it
    the handoff mismatch is reported the old, unconditional way. Records carry
    their own path, so they never need it.
    """
    warnings: list[str] = []
    cur_branch = git_branch(root)
    detached = is_git_repo(root) and cur_branch == "HEAD"
    reached = HeadTree(root)
    handoff_path = Path(memory_dir) / "handoff.md" if memory_dir is not None else None

    # (5) Primary signal: handoff age + commit-distance ("train of thought cold").
    age = _age_days(handoff_meta.get("updated_at"))
    dist = git_commit_distance(root, handoff_meta.get("commit"))
    if age is not None or dist is not None:
        parts = []
        if age is not None:
            # A future timestamp (clock skew / edited-ahead date) yields a negative
            # age — don't render the nonsensical "-1 day(s) old".
            parts.append(
                "timestamped in the future (clock skew?)" if age < 0 else f"{age} day(s) old"
            )
        if dist is not None:
            parts.append(f"written {dist} commit(s) behind current HEAD")
        cold = (age is not None and age > stale_days) or (dist is not None and dist >= 10)
        if cold or not risks_only:
            warnings.append(("⚠ " if cold else "") + "handoff is " + ", ".join(parts) + ".")
    elif handoff_meta.get("updated_at") and not risks_only:
        warnings.append("handoff timestamp is not parseable; treat handoff age as unknown.")

    # (7) Branch mismatch (§15) — handoff first, then records, capped.
    if detached:
        warnings.append(
            f"git HEAD is detached at {git_commit(root)}; records may be stale "
            "relative to the current HEAD."
        )
    hb = handoff_meta.get("branch")
    if (
        hb
        and hb not in (NO_GIT_BRANCH, None, "")
        and not detached
        and cur_branch != NO_GIT_BRANCH
        and hb != cur_branch
        and not reached.contains(handoff_path)
    ):
        warnings.append(
            f"branch mismatch: handoff was written on '{hb}' but HEAD is on '{cur_branch}'."
        )
    if not detached and cur_branch != NO_GIT_BRANCH and not risks_only:
        mism = [
            f"{r.meta.get('id', r.stem)} (on '{r.meta.get('branch')}')"
            for r in (decisions + attempts)
            if r.meta.get("branch")
            and r.meta.get("branch") not in (NO_GIT_BRANCH, None, "")
            and r.meta.get("branch") != cur_branch
            and not reached.contains(r.path)
        ]
        if mism:
            shown = ", ".join(mism[:5])
            extra = f" (+{len(mism) - 5} more)" if len(mism) > 5 else ""
            warnings.append(
                f"{len(mism)} record(s) written on other branches than "
                f"'{cur_branch}': {shown}{extra}."
            )

    if risks_only:
        return warnings

    # (6) Aged-unresolved decisions + open questions.
    for r in decisions:
        a = _age_days(r.meta.get("updated_at") or r.meta.get("created_at"))
        if a is not None and a > stale_days:
            warnings.append(
                f"active decision {r.meta.get('id', r.stem)} is {a} days old with no "
                "update — is this still true?"
            )
    for q in questions:
        if (q.get("status") or "open") != "open":
            continue
        a = _age_days(q.get("opened"))
        if a is not None and a > stale_days:
            warnings.append(
                f'open question "{q["question"]}" has been open {a} days — '
                "did this ever get resolved?"
            )

    # (8) Expired + low-confidence records.
    for r in decisions + attempts:
        exp = r.meta.get("expires_at")
        if exp:
            a = _age_days(exp)
            if a is not None and a > 0:
                warnings.append(f"{r.meta.get('id', r.stem)} expired on {exp} ({a} days ago).")
        if r.meta.get("confidence") == "low":
            warnings.append(
                f"{r.meta.get('id', r.stem)} is low-confidence — verify before relying on it."
            )

    return warnings


# ---- packet assembly ------------------------------------------------------- #

# How many commit subjects the packet lists between the handoff's commit and
# HEAD (P1-5). Enough to falsify a stale work-list; small enough not to crowd
# the packet.
PACKET_COMMITS_SINCE_HANDOFF_MAX = 10


def _commits_since(root: Path, ref: str | None, limit: int) -> list[str]:
    """One-line subjects for `ref..HEAD`, newest first. [] when unknowable.

    A rewritten/shallow history (ref unknown to this clone) yields [] — the
    commit-distance staleness warning already covers that case; inventing a
    bogus range here would present guesses as history.
    """
    if not ref or not is_git_repo(root):
        return []
    cur = git_commit(root)
    if cur == NO_GIT_COMMIT or ref == cur:
        return []
    out = _git_out(root, "log", "--oneline", "--no-decorate", f"{ref}..HEAD")
    if out is None:
        return []
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines[:limit]


# Bounded so a store with many fixed verifications cannot flood the warnings
# section with drift guesses.
PACKET_DRIFT_CONFLICTS_MAX = 3

# Share of a fixed verification's subject stems the focus text must contain
# before the drift line fires (floor: two shared stems, or the whole subject
# when it is shorter). The first cut fired on *any* two shared stems, and on
# this tool's own store that was 4 of 9 fixed verifications, every one false:
# "crumb"+"open", "sect"+"sess" (a CHANGELOG *section* and a work *session*),
# and the bare "11" out of "0.1.11". Two words in common is what any two
# sentences about the same project share; most of the subject is a claim.
PACKET_DRIFT_SUBJECT_COVERAGE = 2 / 3


def _claim_stems(text: str) -> set[str]:
    """`_specific` minus digit-only stems: a version fragment is not a claim."""
    return {s for s in _specific(text) if not s.isdigit()}


def _focus_verification_conflicts(
    next_action: str, current_focus: str, verifications: list[Record]
) -> list[str]:
    """Warn when a **fixed** verification names what the focus still claims is owed.

    The P1-5 failure mode: the packet's Current Focus said two work items were
    outstanding while its own Verifications section recorded one of them as
    fixed — internally contradictory, and only a human noticed. This is the
    deterministic cross-check: token overlap between the focus claims and each
    fixed verification's subject (same stemming as guard/search), warn-only.

    The overlap must cover `PACKET_DRIFT_SUBJECT_COVERAGE` of the subject's
    stems, not merely reach two: the packet is read cold, so a drift line it
    prints is either the one contradiction the reader must resolve first, or
    the line that teaches them to skip the whole section. A missed paraphrase
    still has *Landed Since The Handoff Was Written* to fall back on.
    """
    claims = _claim_stems(f"{next_action} {current_focus}")
    if not claims:
        return []
    out: list[str] = []
    for r in verifications:
        if (r.meta.get("outcome") or "open") != "fixed":
            continue
        subject = r.meta.get("subject") or r.meta.get("title", "")
        subj = _claim_stems(subject)
        if not subj:
            continue
        need = max(min(2, len(subj)), math.ceil(len(subj) * PACKET_DRIFT_SUBJECT_COVERAGE))
        if len(subj & claims) >= need:
            rid = r.meta.get("id", r.stem)
            when = r.meta.get("updated_at") or r.meta.get("created_at") or ""
            when = f" on {when[:10]}" if when else ""
            out.append(
                f'possible drift: `{rid}` recorded "{subject}" as **fixed**{when}, '
                "but Current Focus / Next Action still claims that work — "
                "re-check before redoing it."
            )
            if len(out) >= PACKET_DRIFT_CONFLICTS_MAX:
                break
    return out


def _tracked_gitignored_dirs(project_root: Path, dirs: list[Path]) -> set[str]:
    """Of `dirs`, the ones a *committed* `.gitignore` excludes.

    Only patterns that live in a tracked-able `.gitignore` inside the worktree
    count. A machine-local exclude (`.git/info/exclude`, `core.excludesFile`)
    must not participate: `_inputs_hash` has to agree byte-for-byte across every
    clone, and folding one developer's personal excludes into it would recreate
    the very ping-pong this exists to stop.

    `git check-ignore -v` prints `<source>:<line>:<pattern>\\t<path>`; run from
    the project root, the source of a worktree `.gitignore` is a relative path,
    while both machine-local sources are absolute. That is the whole filter.
    """
    if not dirs or not is_git_repo(project_root):
        return set()
    rels = []
    for d in dirs:
        try:
            rels.append(d.resolve().relative_to(Path(project_root).resolve()).as_posix())
        except ValueError:  # pragma: no cover - store outside the project root
            return set()
    try:
        r = subprocess.run(
            ["git", "check-ignore", "-v", "--no-index", "--stdin"],
            cwd=str(project_root),
            input="\n".join(rels) + "\n",
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return set()
    if r.returncode not in (0, 1):  # 1 = nothing ignored; anything else is an error
        return set()
    out: set[str] = set()
    for line in r.stdout.splitlines():
        m = re.match(r"^(?P<source>.*):(?P<line>\d+):(?P<pattern>.*)\t(?P<path>.+)$", line)
        if not m:
            continue
        source, pattern = m.group("source"), m.group("pattern")
        # A negation (`!fixtures/**/…`) is reported as the deciding pattern too,
        # and it means the opposite of ignored.
        if pattern.startswith("!"):
            continue
        if not source or Path(source).is_absolute() or ".git/" in source.replace("\\", "/"):
            continue
        out.add(Path(m.group("path").strip()).name)
    return out


def _hashed_input_dirs(memory_dir: Path, project_root: Path, manifest: dict) -> list[str]:
    """The record directories `_inputs_hash` may read, per the store's own policy.

    A directory the store's policy keeps *local* is not a shared input: hashing it
    stamps the committed packet with a value no clone can reproduce, and the
    "stale projection — run `crumb reindex`" advice then ping-pongs between
    machines forever. `session_tracking: distillate` gitignores
    `sessions/`, and any record directory the committed `.gitignore` excludes is
    local for the same reason.
    """
    skipped = set()
    if (manifest.get("session_tracking") or "full") == "distillate":
        skipped.add("sessions")
    candidates = [Path(memory_dir) / d for d in DIR_TYPES if d not in skipped]
    skipped |= _tracked_gitignored_dirs(project_root, candidates)
    return sorted(d for d in DIR_TYPES if d not in skipped)


# --------------------------------------------------------------------------- #
# Projection freshness — three functions, one primitive
# --------------------------------------------------------------------------- #
# The fix list calls these "three competing notions of projection freshness". Two
# of them are complementary and the third is the primitive both are built on;
# writing that down here is a precondition for splitting this module, because the
# split will scatter them across files.
#
#   1. `_inputs_hash(memory_dir, root)` — the PRIMITIVE. A content hash over the
#      canonical inputs the store's own policy says are shared. It *defines* what
#      "unchanged" means. Stamped into every `generated/*.md` header when written.
#
#   2. `detect_packet_drift(memory_dir)` — "is the stamp stale?" Compares each
#      projection's stamped hash against a freshly computed one. Cheap: no packet
#      is rebuilt. Used by `validate` (§16.12 freshness, which FAILS) and `audit`.
#
#   3. `_packet_is_stale(memory_dir, root)` — "would a rebuild produce different
#      output?" Re-renders the packet and compares bytes, minus the lines that
#      vary by machine rather than by content. Expensive. Used only by `doctor`.
#
# They can legitimately disagree, in both directions, and neither answer is wrong:
#
#   * (2) fires and (3) does not — a record changed in a way the *bounded* packet
#     does not surface (an edit below the section cap, a record trimmed by
#     `TRIM_ORDER`). The projection is out of date with respect to its inputs even
#     though re-rendering yields the same bytes.
#   * (3) fires and (2) does not — the inputs are untouched but the *renderer*
#     changed, which no hash over inputs can see. This is what catches a packet
#     written by an older version of this package.
#
# Both directions were reproduced against a throwaway store and are pinned by
# `tests/test_audit.py::FreshnessComplementarityTests`.
#
# So: (2) is the gate (deterministic, cheap, and what CI enforces), and (3) is the
# advisory second opinion `doctor` gives a human. Collapsing them would lose one of
# the two classes above. Any split of this file must keep all three together, or
# keep this comment with whichever file gets `_inputs_hash`.


def _inputs_hash(memory_dir: Path, project_root: Path | None = None) -> str:
    """Short content hash of the canonical inputs (so audit can spot drift)."""
    memory_dir = Path(memory_dir)
    project_root = Path(project_root) if project_root is not None else memory_dir.parent
    manifest = load_manifest(memory_dir) or {}
    h = hashlib.sha256()
    # The policies that decide *what is shared* are part of the hash, so flipping
    # `session_tracking` invalidates every stamp exactly once instead of silently
    # changing the input set under a stamp that still looks current.
    dirs = _hashed_input_dirs(memory_dir, project_root, manifest)
    h.update(("policy:session_tracking=" + (manifest.get("session_tracking") or "full")).encode())
    h.update(b"\0")
    h.update(("policy:hashed_dirs=" + ",".join(dirs)).encode())
    h.update(b"\0")
    # manifest.yml is a packet input (project name, policies), so it is part of
    # the hash — otherwise the freshness check certifies a packet built from a
    # since-edited manifest.
    paths = [memory_dir / f for f in CORE_FILES]
    paths.append(memory_dir / "manifest.yml")
    for d in dirs:
        dd = memory_dir / d
        if dd.is_dir():
            paths.extend(sorted(dd.glob("*.md")))
    for p in sorted(set(paths)):
        if p.is_file():
            # Path *and* separators, not bare contents: record ids
            # are filename-derived, so a rename changes every id in the packet
            # while leaving a contents-only hash untouched — the freshness gate
            # then certifies a projection full of ids that no longer exist.
            rel = p.relative_to(memory_dir).as_posix()
            h.update(rel.encode())
            h.update(b"\0")
            h.update(p.read_bytes())
            h.update(b"\0")
    return h.hexdigest()[:12]


def build_resume_packet(
    memory_dir: Path,
    root: Path,
    *,
    stale_days: int = STALE_AGE_DAYS,
    fast: bool = False,
    task: str | None = None,
) -> dict:
    """Assemble the structured resume packet (the source of both MD and JSON output).

    When `task` is given (the "resume for THIS task" path) the packet
    is scoped to it: `requested_task` is echoed and `likely_files` is derived from
    the records that actually match the task instead of the store-global default
    that misdirects on off-domain work. With no task, behavior is unchanged.
    """
    memory_dir = Path(memory_dir)
    manifest = load_manifest(memory_dir) or {}

    # Lenient reads: one bad byte in handoff.md used to abort the
    # packet build, which took `resume`, `audit` and every reindex down with it —
    # projections silently stopped refreshing. The problem is surfaced as a packet
    # warning instead, naming the file.
    unreadable: list[str] = []
    current_text, problem = (
        read_text_lenient(memory_dir / "current.md")
        if (memory_dir / "current.md").is_file()
        else ("", None)
    )
    if problem:
        unreadable.append(f"current.md: {problem}")
    current_sections = split_md_sections(current_text)
    handoff_text, problem = (
        read_text_lenient(memory_dir / "handoff.md")
        if (memory_dir / "handoff.md").is_file()
        else ("", None)
    )
    if problem:
        unreadable.append(f"handoff.md: {problem}")
    handoff_sections = split_md_sections(handoff_text)
    handoff_meta = parse_handoff_meta(handoff_text)

    decisions = active_decisions(memory_dir)
    attempts = active_attempts(memory_dir)
    traps = active_traps(memory_dir)
    questions = load_open_questions(memory_dir)
    verifications = active_verifications(memory_dir)

    # Project snapshot (git is the live source; handoff metadata is advisory).
    dirty = git_dirty_files(root)
    project = {
        "name": manifest.get("project") or derive_project_name(root),
        # Project-relative, never the absolute host path. The packet
        # is a committed, shared artifact: an absolute path publishes the author's
        # local directory layout into the repo (the disclosure `mcp_core` already
        # forbids for error messages, issue #7), makes a byte-identical clone at
        # another path read as stale, and churns on every reindex when two
        # developers work at different paths.
        "path": ".",
        "branch": git_branch(root),
        "commit": git_commit(root),
        "dirty": len(dirty),
        "dirty_state": (f"{len(dirty)} uncommitted file(s)" if dirty else "clean"),
    }

    def _focus() -> str:
        cf = current_sections.get("Current Focus", "")
        if not _is_placeholder(cf):
            return cf.strip()
        hf = handoff_sections.get("Current Focus", "")
        return "" if _is_placeholder(hf) else hf.strip()

    next_action = handoff_sections.get("Next Action", "")
    next_action = "" if _is_placeholder(next_action) else next_action.strip()

    packet: dict = {
        "source": {
            "commit": git_commit(root),
            "inputs_hash": _inputs_hash(memory_dir, root),
            "generated_at": now_iso(),
        },
        "fast": bool(fast),
        # Two different numbers used to be one confusable word:
        # `stale_after_days` is the *threshold* the caller chose, while
        # `handoff_age_days`/`handoff_commit_distance` are the measured *age* and
        # distance the warnings are computed from. The ages used to exist only as
        # prose inside a warning string ("handoff is 6 day(s) old"), so a consumer
        # reading the packet had the threshold as data and the fact as English.
        # Both are None when unknown: an unparseable timestamp, or no git repo.
        "stale_after_days": stale_days,
        "handoff_age_days": _age_days(handoff_meta.get("updated_at")),
        "handoff_commit_distance": git_commit_distance(root, handoff_meta.get("commit")),
        "project": project,
        "current_focus": _focus(),
        "next_action": next_action,
        "active_decisions": [
            {
                "id": r.meta.get("id", r.stem),
                "title": r.meta.get("title", ""),
                "rationale": _decision_rationale(r),
            }
            for r in decisions
        ],
        "failed_attempts": [
            {
                "id": r.meta.get("id", r.stem),
                "title": r.meta.get("title", ""),
                "do_not_retry": _attempt_do_not_retry(r),
            }
            for r in attempts
        ],
        "known_traps": [t["heading"] for t in traps],
        "open_questions": [q["question"] for q in questions if q["status"] == "open"],
        "likely_files": [],
        "verification": [],
        "verifications": [
            {
                "id": r.meta.get("id", r.stem),
                "subject": (r.meta.get("subject") or r.meta.get("title", "")),
                "outcome": (r.meta.get("outcome") or "open"),
                "method": r.meta.get("method"),
            }
            for r in verifications
        ],
        "commits_since_handoff": _commits_since(
            root, handoff_meta.get("commit"), PACKET_COMMITS_SINCE_HANDOFF_MAX
        ),
        "warnings": (
            [f"⚠ {u}" for u in unreadable]
            + compute_staleness(
                root,
                handoff_meta,
                decisions,
                attempts,
                questions,
                stale_days,
                memory_dir=memory_dir,
            )
        ),
        "omitted": {},
        "omitted_reason": {},
    }
    # P1-5 cross-check: a fixed verification contradicting the focus claims is
    # the one staleness the age/distance numbers can never see.
    packet["warnings"] += _focus_verification_conflicts(
        packet["next_action"], packet["current_focus"], verifications
    )

    # Likely files: handoff section + file-type evidence refs (deduped, order-stable).
    files = _section_lines(handoff_sections, "Likely Relevant Files")
    for r in decisions + attempts:
        files.extend(_evidence_refs(r, ("file", "path")))
    packet["likely_files"] = _dedup(files)

    # Verification commands: handoff section + command-type evidence refs. (Distinct
    # from `verifications`, which are recorded *results*; this list is *how to check*.)
    verify_cmds = _section_lines(handoff_sections, "Verification Commands")
    for r in decisions + attempts:
        verify_cmds.extend(_evidence_refs(r, ("command", "test")))
    packet["verification"] = _dedup(verify_cmds)

    # Task scoping: when a task is named, replace the store-global
    # likely_files with files drawn from the records that actually match the task,
    # and label an empty result so the consumer knows the store is cold here rather
    # than trusting noise.
    if task:
        packet["requested_task"] = task
        scoped, note = _task_scoped_files(memory_dir, root, task, stale_days=stale_days)
        packet["likely_files"] = scoped
        if note:
            packet["likely_files_note"] = note

    _bound_packet(packet, fast=fast)
    return packet


def active_verifications(memory_dir: Path) -> list[Record]:
    """Active verification records, actionable outcome first.

    open/regressed/inconclusive (still need attention) sort ahead of
    not_applicable/fixed (resolved), each group newest-first via active_records.
    """
    order = {
        o: i for i, o in enumerate(ACTIONABLE_VERIFICATION_OUTCOMES + ("not_applicable", "fixed"))
    }
    recs = active_records(memory_dir, "verification")
    return sorted(recs, key=lambda r: order.get(r.meta.get("outcome") or "open", 99))


def _task_scoped_files(
    memory_dir: Path, root: Path, task: str, *, stale_days: int
) -> tuple[list[str], str | None]:
    """Files relevant to `task`, from records that match it.

    Reuses the deterministic `search` scoring rather than inventing a second
    relevance notion. Returns (files, note); note is set only when nothing matched.

    Ideas are excluded (the default corpus): this list goes into a packet that
    boots the next session, and a file path is only "likely" because someone did
    work there — not because someone proposed it.
    """
    matches, by_id = search(memory_dir, root, task, stale_days=stale_days, include_ideas=False)
    files: list[str] = []
    for m in matches:
        files.extend(m.get("matched_files") or [])
        item = by_id.get(m["id"]) or {}
        rec = item.get("record")
        if rec is not None:
            files.extend(_evidence_refs(rec, ("file", "path")))
    files = _dedup([f for f in files if f])
    if not files:
        return [], "no records match this task domain; starting cold"
    return files, None


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it and it not in seen:
            seen.add(it)
            out.append(it)
    return out


# Sections dropped wholesale by --fast (reduced reorientation view, §12).
_FAST_DROP = (
    "active_decisions",
    "failed_attempts",
    "known_traps",
    "open_questions",
    "likely_files",
    "verification",
    "verifications",
)


def _bound_packet(packet: dict, *, fast: bool) -> None:
    """Apply --fast pruning, per-section caps, then trim to the token budget."""
    if fast:
        for key in _FAST_DROP:
            packet[key] = []
        packet["omitted"] = {}
        packet["omitted_reason"] = {}

    # Per-section caps (record how many we hid, and why). Applied in --fast mode
    # too: warnings survive the fast prune and must stay bounded.
    for key, cap in SECTION_CAPS.items():
        if fast and key in _FAST_DROP:
            continue
        items = packet.get(key, [])
        if len(items) > cap:
            packet["omitted"][key] = packet["omitted"].get(key, 0) + (len(items) - cap)
            packet["omitted_reason"][key] = "the per-section cap"
            packet[key] = items[:cap]
    if fast:
        return

    # Budget trim, lowest-priority section first, until within the ceiling.
    while approx_tokens(render_packet_markdown(packet)) > TOKEN_BUDGET_MAX:
        for key in TRIM_ORDER:
            if packet.get(key):
                packet[key].pop()
                packet["omitted"][key] = packet["omitted"].get(key, 0) + 1
                # A key already capped is now also budget-trimmed — record both.
                prior = packet["omitted_reason"].get(key)
                packet["omitted_reason"][key] = (
                    "the per-section cap and token budget"
                    if prior == "the per-section cap"
                    else "the token budget"
                )
                break
        else:
            break  # nothing left to trim; emit slightly over rather than loop forever


# ---- rendering ------------------------------------------------------------- #


def _omitted_note(packet: dict, key: str) -> list[str]:
    n = packet.get("omitted", {}).get(key, 0)
    if not n:
        return []
    reason = packet.get("omitted_reason", {}).get(key, "the token budget")
    return [f"_(… {n} more omitted to stay within {reason})_"]


def render_packet_markdown(packet: dict) -> str:
    """Render the §12 packet. Source header keeps the GENERATED PROJECTION marker."""
    src = packet["source"]
    proj = packet["project"]
    out: list[str] = [
        f"<!-- {GENERATED_MARKER} — do not edit by hand. Rebuilt by `crumb resume`. -->",
        f"<!-- source_commit: {src['commit']} | inputs_hash: {src['inputs_hash']} "
        f"| generated_at: {src['generated_at']} -->",
        "",
        "# Resume Packet",
        "",
    ]
    if packet.get("requested_task"):
        out += [
            "## Requested Task",
            packet["requested_task"],
            "_(this is the task you asked to resume; the focus/next-action below are "
            "where the last session left off)_",
            "",
        ]
    # Stores written before 0.1.11 carry a Current Focus that is a verbatim copy
    # of the Next Action (capture used to default one to the other, P1-6);
    # collapse the duplicate at render time instead of spending ~1.4k chars
    # printing the same text twice.
    cf = packet["current_focus"]
    if cf and cf.strip() == (packet["next_action"] or "").strip():
        cf = "_(same as Next Action)_"
    out += [
        "## Project",
        f"**{proj['name']}** — `{proj['path']}`  ",
        f"branch `{proj['branch']}` · commit `{proj['commit']}` · {proj['dirty_state']}",
        "",
        "## Current Focus",
        cf or "_(not recorded — see current.md / handoff.md)_",
        "",
        "## Next Action",
        packet["next_action"] or "_(not recorded — set one with `crumb capture session --next`)_",
        "",
    ]

    # P1-5: the staleness numbers say how *old* the handoff is, never whether its
    # claims still hold. Listing what actually landed since it was written makes
    # the Current Focus / Next Action falsifiable by the reader — a fresh session
    # can check the list before redoing work the packet still says is owed.
    if packet.get("commits_since_handoff"):
        out += [
            "## Landed Since The Handoff Was Written",
            "_(check Current Focus / Next Action against these before redoing work)_",
        ]
        out += [f"- {c}" for c in packet["commits_since_handoff"]]
        out.append("")

    if not packet["fast"]:
        # The omitted-count disclosure is emitted in BOTH branches: budget-trimming
        # can empty a section entirely while still having hidden items, and the
        # "… N more omitted" note must not vanish when the list renders as none.
        out += ["## Active Decisions"]
        if packet["active_decisions"]:
            for d in packet["active_decisions"]:
                out.append(f"- `{d['id']}` — {d['rationale']}")
        else:
            out.append("_(none active)_")
        out += _omitted_note(packet, "active_decisions")
        out.append("")

        out += ["## Failed Attempts To Avoid"]
        if packet["failed_attempts"]:
            for a in packet["failed_attempts"]:
                out.append(f"- `{a['id']}` — do not retry: {a['do_not_retry']}")
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "failed_attempts")
        out.append("")

        out += ["## Known Traps"]
        if packet["known_traps"]:
            out += [f"- {t}" for t in packet["known_traps"]]
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "known_traps")
        out.append("")

        out += ["## Open Questions / Blockers"]
        if packet["open_questions"]:
            out += [f"- {q}" for q in packet["open_questions"]]
        else:
            out.append("_(none open)_")
        out += _omitted_note(packet, "open_questions")
        out.append("")

        out += ["## Likely Relevant Files"]
        if packet["likely_files"]:
            out += [f"- {f}" for f in packet["likely_files"]]
        elif packet.get("likely_files_note"):
            out.append(f"_({packet['likely_files_note']})_")
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "likely_files")
        out.append("")

        out += ["## Verifications"]
        if packet.get("verifications"):
            for v in packet["verifications"]:
                method = f" · {v['method']}" if v.get("method") else ""
                out.append(f"- `{v['id']}` — {v['subject']}: **{v['outcome']}**{method}")
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "verifications")
        out.append("")

        out += ["## Verification Commands"]
        if packet["verification"]:
            out += [f"- {c}" for c in packet["verification"]]
        else:
            out.append("_(none recorded)_")
        out += _omitted_note(packet, "verification")
        out.append("")

    out += ["## Stale / Risk Warnings"]
    # Name the threshold next to the ages it governs: every age below is measured,
    # this one number is the cutoff they are compared against.
    if packet.get("stale_after_days") is not None:
        out.append(
            f"_(ages below are measured; the cutoff is "
            f"{packet['stale_after_days']} days — set with `--stale-days`)_"
        )
    if packet["warnings"]:
        out += [f"- {w}" for w in packet["warnings"]]
    else:
        out.append("_(no computed staleness or risk signals)_")
    out += _omitted_note(packet, "warnings")
    out.append("")

    return "\n".join(out).rstrip() + "\n"


def cmd_resume(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    stale_days = args.stale_days if args.stale_days is not None else STALE_AGE_DAYS
    task = getattr(args, "task", None)
    packet = build_resume_packet(memory_dir, root, stale_days=stale_days, fast=args.fast, task=task)
    md = render_packet_markdown(packet)
    packet["approx_tokens"] = approx_tokens(md)

    # The full packet is the committed cloud-fallback artifact; --fast is a
    # print-only quick view and must not overwrite that artifact with a reduced one.
    # A task-scoped packet is a focused, ephemeral view, so it likewise does not
    # overwrite the canonical store-global snapshot.
    #
    # The store-global write goes through the same reindex every mutation uses:
    # writing only resume-packet.md left guard-prefilter.json unrebuilt — so
    # `crumb hook guard` stayed blind to a newly recorded trap —
    # while the fresh `inputs_hash` stamp made `audit` report zero packet drift,
    # hiding the staleness until the next mutation. It is also the only atomic
    # write path; the direct `write_text` here was the last torn-file risk.
    if not args.fast and not task:
        ok, problem = try_reindex_projections(memory_dir, root)
        if not ok:
            print(
                f"warning: generated projections not refreshed: {problem}",
                file=sys.stderr,
            )

    if args.json:
        _print_json(args, packet)
    else:
        print(md)
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    """Rebuild the generated/ projections from the canonical records.

    Mutations reindex automatically; this is the explicit refresh for after a batch
    of `--no-reindex` writes or a hand-edit, and the actionable target `validate`
    points at when it detects a stale projection.
    """
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    ok, problem = try_reindex_projections(memory_dir, root)
    summary = {"reindexed": ok, "path": str(memory_dir / "generated" / "resume-packet.md")}
    if problem:
        summary["error"] = problem
    if args.json:
        _print_json(args, summary)
    elif ok:
        print(f"Reindexed projections: {summary['path']}")
    else:
        # Naming the cause: "Reindex failed" alone left the user with a store
        # whose projections had silently stopped refreshing.
        print(f"Reindex failed (projections left unchanged): {problem}")
    return 0 if ok else 1


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
GUARD_W_OPEN_BLOCKER = 3  # overlaps an unresolved open question

# What a match must have, beyond shared vocabulary, to be surfaced as a warning
# rather than as history. `mention` is here and `keyword` is not: a prose-mined
# path is at least a claim about *this file*, where a shared stem is a claim
# about the language the project speaks. Deliberately not the same set as the
# specificity that lets a match raise a verdict ({file, tag}) — being worth
# showing and being worth escalating are different bars.
GUARD_SURFACING_SIGNALS = frozenset(
    {"file", "tag", "title", "mention", "do-not-retry", "open-blocker"}
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

# Commands whose whole job is to report. Deliberately a short allowlist of the
# unambiguous ones: `sed`, `awk` and `tee` can all write, and anything not named
# here is simply treated as capable of side effects, which is the safe default.
GUARD_READ_ONLY_COMMANDS = frozenset(
    """
    cat less more head tail nl wc
    ls dir tree stat file du df pwd realpath basename
    grep egrep fgrep rg ack ag find fd locate
    diff cmp md5sum sha1sum sha256sum
    which whereis type man whoami hostname uname date
    echo printf uniq cut column jq yq
    ps top uptime id groups
    """.split()
)

# Two near-misses, deliberately absent: `env` runs an arbitrary command as its
# argument, and `sort -o` writes a file. Neither reports for a living.

# `git` is both the most-used command in any store and the one whose subcommands
# span the whole range, so it gets its own allowlist rather than the verb alone.
GUARD_READ_ONLY_GIT_SUBCOMMANDS = frozenset(
    {
        "status",
        "log",
        "diff",
        "show",
        "blame",
        "describe",
        "shortlog",
        "rev-parse",
        "rev-list",
        "ls-files",
        "ls-tree",
        "ls-remote",
        "cat-file",
        "whatchanged",
        "grep",
        "reflog",
        "annotate",
        "count-objects",
        "var",
    }
)

# Flags that make an otherwise-reporting command act: `find . -delete` and
# `find . -exec rm {} +` are the ones that matter in practice. Matched as whole
# tokens, so an argument that merely contains one does not trip it.
GUARD_READ_ONLY_DISQUALIFYING_ARGS = frozenset(
    "-delete -exec -execdir -ok -okdir -fprint -fls -fprintf".split()
)

# Shell metacharacters that can turn a reporting command into a writing one
# (`cat x > y`, `ls && rm -rf .`, `` grep `rm -rf .` ``). Their presence forfeits
# the read-only claim outright: this cap only ever *lowers* a verdict, so the
# conservative reading is the correct one.
_SHELL_EFFECT_RE = re.compile(r"[>;&`]|\|\||\$\(")


def _is_read_only_action(action: str) -> bool:
    """True only when the action provably cannot change anything (G2).

    Conservative by construction: an action this cannot recognize is treated as
    capable of side effects, so a missed classification costs an unnecessary
    PAUSE, never a swallowed one.
    """
    text = (action or "").strip()
    if not text or _SHELL_EFFECT_RE.search(text):
        return False
    tokens = text.split()
    if GUARD_READ_ONLY_DISQUALIFYING_ARGS & {t.lower() for t in tokens[1:]}:
        return False
    verb = PurePosixPath(tokens[0].replace("\\", "/")).name.lower()
    if verb == "git":
        subcommands = [t for t in tokens[1:] if not t.startswith("-")]
        return bool(subcommands) and subcommands[0] in GUARD_READ_ONLY_GIT_SUBCOMMANDS
    return verb in GUARD_READ_ONLY_COMMANDS


_VERDICTS = ("PROCEED", "READ_FIRST", "PAUSE", "ASK_HUMAN")
_VERDICT_RANK = {v: i for i, v in enumerate(_VERDICTS)}

# `crumb guard` exit codes, one per verdict (P0-1). Deliberately spaced so a
# script can threshold (`>= 15` = human involvement) and deliberately clear of
# 1 (crash), 2 (usage error), and 126+ (shell/OS conventions).
GUARD_VERDICT_EXIT_CODES = {"PROCEED": 0, "READ_FIRST": 10, "PAUSE": 15, "ASK_HUMAN": 20}


# Generic words that carry no domain signal. A shared stop-word never counts
# toward keyword overlap (the core of the false-positive control, Fixture 3).
# Action-class verbs that DO carry signal (delete/remove/migrate/deploy/refactor/
# rewrite/upgrade…) are intentionally absent.
GUARD_STOPWORDS = frozenset(
    """
    the a an and or but to of in on for with at by from as is are be this that it
    its if then else so not no do does did we you i my our your their them they he
    she was were will would should can could may might must have has had about into
    over under out up down off than too very just also via per after before when
    while where which who what how here there all any some more most less few each
    add added adding update updated updating change changed changing fix fixed
    fixing new old make made making run running set get got use used using create
    created creating build built work working file files code project thing things
    stuff need needs want wants now today please let lets go going into onto
    src lib test tests spec specs index main app ts js tsx jsx py md json yml yaml
    txt cfg ini case feature support handle handling
    """.split()
)

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


def _stem(token: str) -> str:
    """Fold a token to its morphological stem (deterministic, idempotent)."""
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
    """File paths found in free text — candidates that pass `_is_path_token`."""
    return {m.group(0) for m in _FILE_TOKEN_RE.finditer(text or "") if _is_path_token(m.group(0))}


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
    """Return (primary_class, sorted matched classes). 'routine_edit' if none hit."""
    toks = _tokenize(action)
    matched = {cls for cls, kws in ACTION_CLASS_KEYWORDS.items() if toks & kws}
    if not matched:
        return "routine_edit", ["routine_edit"]
    primary = next(c for c in _CLASS_SEVERITY if c in matched)
    return primary, sorted(matched)


# ---- searchable corpus ----------------------------------------------------- #


def _attempt_has_do_not_retry(rec: Record) -> bool:
    sec = rec.sections.get("Do Not Retry Unless", "")
    return bool(_first_line(sec))


def _item_from_record(rec: Record) -> dict:
    # Body-mined paths minus the ones that are really *commands*. A record whose
    # evidence is `--evidence command "./gradlew test"` or `--evidence test
    # "pytest tests/dao"` has that string in its body too, and `_paths_from_text`
    # cannot tell `pytest tests/dao` from a file reference — so the record scored
    # a 6-point file hit against every invocation of its own verification
    # command. Curated `--evidence file/path` refs are unaffected; this only
    # removes paths that the record itself already labelled as a command.
    cmd_paths = _paths_from_text(" ".join(_evidence_refs(rec, ("command", "test"))))
    mined = _paths_from_text(rec.body) - cmd_paths
    # Two tiers, not one (G1). `--evidence file …` is the author *declaring*
    # which files this record is about; a path mined out of its prose is a
    # mention, and the two were scored, displayed and reasoned about
    # identically. Declared paths keep the strongest signal guard has; mentions
    # get a weaker one and say so, so an agent reading `same file(s)` can still
    # trust it. A trap author knows which files their trap concerns — asking
    # beats any extractor.
    files = _norm_files(set(_evidence_refs(rec, ("file", "path"))))
    mentioned = _norm_files(mined) - files
    tags = {str(t).lower() for t in (rec.meta.get("tags") or [])}
    text = " ".join([str(rec.meta.get("title") or ""), rec.body, " ".join(tags)])
    # For verifications the interesting "status" is the *outcome* (open/fixed/…),
    # not the lifecycle status — so `search type:verification status:open` filters
    # on what the agent actually cares about. The lifecycle value is
    # kept alongside it: guard's liveness test needs both, and folding them into
    # one field is what silently excluded every verification from the verdict.
    lifecycle = str(rec.meta.get("status") or "active")
    status = (rec.meta.get("outcome") or "open") if rec.rtype == "verification" else lifecycle
    return {
        "id": rec.meta.get("id", rec.stem),
        "kind": rec.rtype,
        "status": status,
        "lifecycle": lifecycle,
        "title": rec.meta.get("title", "") or rec.stem,
        "tags": tags,
        # Stem -> original tag. Matching runs on stems (a "migrations" tag must
        # meet a "migration" query); display and `tag:` filters keep the raw tag.
        "tag_stems": {_stem(t): t for t in tags},
        "files": files,
        "mentioned_files": mentioned,
        "specific": _specific(text),
        # The title's own tokens, kept separate so `_score_item` can weight a
        # title hit above a body mention. The stem is the slug — same
        # words, so a filename hit counts as a title hit.
        "title_specific": _specific(str(rec.meta.get("title") or rec.stem)),
        "branch": rec.meta.get("branch"),
        "record": rec,
        "do_not_retry": rec.rtype == "attempt" and _attempt_has_do_not_retry(rec),
    }


def _item_from_trap(trap: dict) -> dict:
    heading, body = trap["heading"], trap.get("content", trap.get("body", ""))
    text = heading + "\n" + body
    return {
        "id": trap.get("id") or heading.split(":", 1)[0].strip() or "trap",
        "kind": "trap",
        # Was hardcoded "active", which is what made a retired trap keep scoring
        # in search and keep counting as live in guard's active/history split.
        "status": trap.get("status") or "active",
        "title": heading,
        "tags": set(),
        "files": _norm_files(_paths_from_text(_trap_area_text(body))),
        "mentioned_files": (
            _norm_files(_paths_from_text(_trap_hazard_text(body)))
            - _norm_files(_paths_from_text(_trap_area_text(body)))
        ),
        "specific": _specific(text),
        "title_specific": _specific(heading),
        "branch": None,
        "record": None,
        "do_not_retry": False,
    }


QUESTION_SLUG_CHARS = 48


def question_item_id(question: str) -> str:
    """Search id for an open question: `q:<slug>`, disambiguated when truncated.

    Truncating the slug at 48 characters made two distinct questions share one id
    ("… to the new columnar store this quarter" / "… to the new row store next
    quarter" both slugify past the cut with the same prefix), and `search`'s
    by_id map kept only the last — which `guard`'s `_recommended_action` resolves
    through. A short digest of the *full* question restores
    uniqueness; ids for questions short enough not to be cut are unchanged.
    """
    slug = slugify(question)
    if len(slug) <= QUESTION_SLUG_CHARS:
        return "q:" + slug
    digest = hashlib.sha256(question.encode("utf-8")).hexdigest()[:6]
    return f"q:{slug[:QUESTION_SLUG_CHARS].rstrip('-')}-{digest}"


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
        "mentioned_files": _norm_files(_paths_from_text(body)),
        "specific": _specific(text),
        "title_specific": _specific(q["question"]),
        "branch": None,
        "record": None,
        "do_not_retry": False,
    }


# The corpus every ranked lookup draws from. Two corpora, not one — see
# `_candidate_items`.
JUDGING_ITEM_TYPES = ("decision", "attempt", "verification")
SPECULATIVE_ITEM_TYPES = ("idea",)


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

    Sessions stay out of both: they are narrative, and under
    `session_tracking: distillate` a clone may not have them at all, so including
    them would make results depend on which checkout you ran in.
    """
    types = JUDGING_ITEM_TYPES + (SPECULATIVE_ITEM_TYPES if include_ideas else ())
    items: list[dict] = []
    for rec in load_records(memory_dir, types=types):
        if rec.error:
            continue
        items.append(_item_from_record(rec))
    items.extend(_item_from_trap(t) for t in load_traps(memory_dir))
    items.extend(_item_from_question(q) for q in load_open_questions(memory_dir))
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
    distances: CommitDistanceIndex,
    ubiquitous: frozenset[str] = frozenset(),
) -> dict | None:
    """Score one item against the query. None if it does not clear the candidate gate."""

    # _norm_files stores each file as both its full path and its bare basename,
    # so the intersection can hold both variants of one physical file. Count each
    # distinct full path once, plus any bare-basename match not already covered by
    # a matched full path. Keying on basename alone (the old approach) wrongly
    # collapsed genuinely-distinct files that share a name (src/a/x.ts, src/b/x.ts)
    # — undercounting the score and picking a hash-order-dependent survivor.
    def _overlap(candidate: set[str]) -> tuple[list[str], int]:
        raw = candidate & q_files
        full_paths = {f for f in raw if "/" in f}
        covered = {f.rsplit("/", 1)[-1] for f in full_paths}
        extra_bare = {f for f in raw if "/" not in f and f not in covered}
        return sorted(full_paths | extra_bare), len(full_paths) + len(extra_bare)

    matched_files, file_count = _overlap(item["files"])
    # Prose-mined paths, scored separately and never as "same file(s)".
    matched_mentions, mention_count = _overlap(item.get("mentioned_files", set()) - item["files"])
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
    if not matched_files and not matched_mentions and not matched_tags and kw_count < min_keyword:
        return None

    signals: list[str] = []
    score = 0.0
    if matched_files:
        score += GUARD_W_FILE * file_count
        signals.append("file")
    if matched_mentions:
        score += GUARD_W_MENTION * mention_count
        signals.append("mention")
    if matched_tags:
        score += GUARD_W_TAG * len(matched_tag_stems)
        signals.append("tag")
    if kw_count:
        score += GUARD_W_KEYWORD * kw_count
        if kw_count >= min_keyword:
            signals.append("keyword")
    if title_overlap:
        score += GUARD_W_TITLE * len(title_overlap)
        signals.append("title")

    rec = item.get("record")
    if item["status"] == "active":
        score += GUARD_W_STATUS_ACTIVE
    if rec is not None:
        if rec.meta.get("confidence") == "high":
            score += GUARD_W_CONFIDENCE_HIGH
        if rec.meta.get("review_status") == "reviewed":
            score += GUARD_W_REVIEWED
    if item["do_not_retry"]:
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
        age = _age_days(rec.meta.get("updated_at") or rec.meta.get("created_at"))
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
        and rb not in (NO_GIT_BRANCH, None, "")
        and cur_branch not in (NO_GIT_BRANCH, "HEAD")
        and rb != cur_branch
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
        "branch_mismatch": branch_mismatch,
        "reason": _match_reason(
            item["kind"], signals, matched_files, matched_tags, kw_count, matched_mentions
        ),
    }


def _match_reason(kind, signals, matched_files, matched_tags, kw_count, matched_mentions=()) -> str:
    """Human phrase for why a record matched. Derived facts only — never executed."""
    parts: list[str] = []
    if matched_files:
        shown = ", ".join(sorted(matched_files)[:3])
        parts.append(f"same file(s): {shown}")
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


def search(
    memory_dir: Path,
    root: Path,
    query: str,
    *,
    files: list[str] | None = None,
    filters: dict | None = None,
    stale_days: int = STALE_AGE_DAYS,
    min_keyword: int = 1,
    noise_floor: int = 1,
    include_ideas: bool = False,
) -> tuple[list[dict], dict[str, dict]]:
    """Deterministic search over the canonical records (§20.10).

    Returns (matches sorted best-first, items_by_id). Matching signals: exact/
    keyword text, tag/component, and file path. No embeddings; same input ->
    same output. `filters` narrows the corpus by type/status/tag/file first.

    `include_ideas` selects the wider, lookup-only corpus — see `_candidate_items`.
    It defaults to False so a caller that forgets it gets guard's corpus, which is
    the safe side of the mistake.
    """
    items = _candidate_items(memory_dir, include_ideas=include_ideas)
    by_id = {it["id"]: it for it in items}
    filters = filters or {}
    q_specific = _specific(query)
    q_files = _norm_files(_paths_from_text(query) | set(files or []))
    cur_branch = git_branch(root)
    # One commit-distance index for the whole pass — see the class.
    distances = CommitDistanceIndex(root, GUARD_STALE_DIST_COMMITS)
    ubiquitous = _ubiquitous_stems(items)

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
        )
        if m is None:
            # Filter-only lookups (no scoring query) still surface the item.
            if filters and not q_specific and not q_files:
                m = {
                    "id": it["id"],
                    "kind": it["kind"],
                    "status": it["status"],
                    "lifecycle": it.get("lifecycle", it["status"]),
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
    if f and not (_norm_files({f}) & (item["files"] | item.get("mentioned_files", set()))):
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
        specific = bool({"file", "tag"} & sig)
        floor = "PROCEED"
        if "do-not-retry" in sig and specific:
            floor = "PAUSE"  # a failed attempt on these files/component
        elif m["kind"] == "decision" and specific:
            floor = "READ_FIRST"  # an active decision constrains this area
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
        verdicts.append(_min_verdict(_max_verdict(floor, _score_band(m["score"])), ceiling))

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


def _recommended_action(verdict: str, top: list[dict], by_id: dict, root: Path) -> str:
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
            cmds.extend(_evidence_refs(rec, ("command", "test")))
    cmds = _dedup(cmds)[:3]
    verify = f" Run the recorded verification command(s): {'; '.join(cmds)}." if cmds else ""

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
    if top:
        return (
            "Low-severity overlap only; likely unrelated. Proceed, but skim "
            f"{ids} if unsure." + verify
        )
    return (
        "No conflicting memory found. Proceed. Capture a new decision or attempt "
        "record if this turns into one worth remembering."
    )


def guard(
    memory_dir: Path,
    root: Path,
    action: str,
    *,
    files: list[str] | None = None,
    stale_days: int = STALE_AGE_DAYS,
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
    matches, by_id = search(
        memory_dir,
        root,
        action,
        files=files,
        stale_days=stale_days,
        min_keyword=GUARD_MIN_KEYWORD_OVERLAP,
        noise_floor=GUARD_NOISE_FLOOR,
        include_ideas=False,
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
        live = (
            m["status"] == "active"
            or (m["kind"] == "question" and m["status"] == "open")
            or (
                m["kind"] == "verification"
                and m.get("lifecycle", "active") == "active"
                and m["status"] in ACTIONABLE_VERIFICATION_OUTCOMES
            )
        )
        (active if live else history).append(m)

    top = active[:GUARD_MAX_WARNINGS]
    verdict = _decide_verdict(top, classes, action)

    # Staleness is computed so a stale/wrong-branch handoff surfaces
    # in guard exactly as it does in resume (Fixture 4), regardless of verdict.
    # Lenient read: guard runs on the PreToolUse path and must not die on a bad
    # byte.
    handoff_text = (
        read_text_lenient(memory_dir / "handoff.md")[0]
        if (memory_dir / "handoff.md").is_file()
        else ""
    )
    # `risks_only`: guard is called once per edit, and the full staleness view
    # repeated the same store-wide facts verbatim on every call (P0-4). Only
    # abnormal states — cold handoff, detached HEAD, branch mismatch — belong
    # on the per-action path; the rest lives in resume/doctor/audit.
    staleness = compute_staleness(
        root,
        parse_handoff_meta(handoff_text),
        active_decisions(memory_dir),
        active_attempts(memory_dir),
        load_open_questions(memory_dir),
        stale_days,
        risks_only=True,
        memory_dir=memory_dir,
    )[:GUARD_MAX_WARNINGS]

    return {
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
        "read_only": _is_read_only_action(action),
        "matches": top,
        "history": history[:GUARD_MAX_WARNINGS],
        "staleness": staleness,
        # NOT `next_action` — that key is the resume packet's *recorded* Next
        # Action, and one name for two unrelated things read as one thing.
        "recommended_action": _recommended_action(verdict, top, by_id, root),
        "thresholds": {
            "noise_floor": GUARD_NOISE_FLOOR,
            "read_first_score": GUARD_READ_FIRST_SCORE,
            "pause_score": GUARD_PAUSE_SCORE,
            "min_keyword_overlap": GUARD_MIN_KEYWORD_OVERLAP,
            "max_warnings": GUARD_MAX_WARNINGS,
        },
    }


# ---- rendering ------------------------------------------------------------- #


def render_guard_human(result: dict) -> str:
    """Render the §11 example shape (human format)."""
    out = [result["verdict"], "", f"Proposed action: {result['action']}"]
    cls = result["action_class"]
    if cls != "routine_edit":
        out.append(f"Action class: {cls}")
    out.append("")

    if result["matches"]:
        out.append("Relevant memory:")
        for i, m in enumerate(result["matches"], 1):
            # "objects" vs "context" is the stance, not the score: without it a
            # record that forbids this action and one that merely names the same
            # file read identically (F-2), so the caller could not tell which of
            # the two kinds of PAUSE they were looking at.
            stance = m.get("stance") or _match_stance(m.get("signals"))
            mark = "objects" if stance == "blocking" else "context"
            out.append(f"{i}. [{mark}] {m['id']} — {m['kind']}, {m['reason']}.")
    else:
        out.append("Relevant memory: none above the noise floor.")
    out.append("")

    if result["history"]:
        out.append("History (context only — not driving the verdict):")
        for m in result["history"]:
            out.append(f"- {m['id']} — {m['status']}; {m['reason']}.")
        out.append("")

    if result["staleness"]:
        out.append("Staleness / risk:")
        for w in result["staleness"]:
            out.append(f"- {w}")
        out.append("")

    out.append("Recommended next action:")
    out.append(result["recommended_action"])
    return "\n".join(out).rstrip() + "\n"


def render_search_human(matches: list[dict], query: str) -> str:
    if not matches:
        return f"search: no records matched {query!r}.\n"
    out = [f"search: {len(matches)} record(s) matched {query!r}", ""]
    for m in matches:
        out.append(
            f"- {m['id']} — {m['kind']} [{m['status']}] (score {m['score']}): {m['reason']}."
        )
    return "\n".join(out) + "\n"


# ---- command entry points -------------------------------------------------- #


def cmd_search(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    filters = {
        "type": args.type,
        "status": args.status,
        "tag": args.tag,
        "file": args.file,
    }
    filters = {k: v for k, v in filters.items() if v}
    stale_days = args.stale_days if args.stale_days is not None else STALE_AGE_DAYS
    query = args.query or ""
    # Lookup, not judging: ideas are in this corpus and out of guard's.
    #
    # Same keyword standard as guard (0.1.10 field test, P1-8): a pure-text match
    # needs GUARD_MIN_KEYWORD_OVERLAP shared specific tokens, relaxed to the
    # query's own specific-token count so a one-word lookup ("libsignal") still
    # works. Search can and should return zero — one generic shared token
    # ("version") is not a match.
    min_kw = max(1, min(GUARD_MIN_KEYWORD_OVERLAP, len(_specific(query)))) if query else 1
    matches, _ = search(
        memory_dir,
        root,
        query,
        filters=filters,
        stale_days=stale_days,
        min_keyword=min_kw,
        include_ideas=True,
    )

    if args.json:
        _print_json(args, {"query": query, "filters": filters, "matches": matches})
        return 0
    print(render_search_human(matches, query or "(filters only)"))
    return 0


def cmd_guard(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    action = (args.action or "").strip()
    if not action:
        _emit_error(
            args, 'guard needs a proposed action, e.g. guard "rewrite the auth middleware".'
        )
        return 2

    stale_days = args.stale_days if args.stale_days is not None else STALE_AGE_DAYS
    result = guard(memory_dir, root, action, files=args.files, stale_days=stale_days)

    if args.json:
        _print_json(args, result)
    else:
        print(render_guard_human(result))
    # Verdict-mapped exit codes (0.1.10 field test, P0-1) so callers can script
    # on the verdict ("block only on ASK_HUMAN") without parsing output. Spaced
    # and documented; 2 stays the usage-error code, and none of these can be
    # mistaken for a crash (1) or an unhandled error (255). The hook path
    # (`crumb hook guard`) is unaffected — hooks must exit 0.
    return GUARD_VERDICT_EXIT_CODES[result["verdict"]]


# --------------------------------------------------------------------------- #
# audit + scan-secrets — heuristic safety net
# --------------------------------------------------------------------------- #
#
# Design split: `validate` is deterministic and GATES; `audit`
# is heuristic and ADVISES. The one hard non-zero in audit is a secret leak — a
# token-like string in committed memory must block any "commit memory" workflow
# (§2.6, §15). Everything else — stale handoff, aged/expired/low-confidence
# records, branch mismatch, instruction-like text, generated-packet drift, bloat,
# and the validate-failing conditions re-surfaced for the health view — is a WARN
# (or INFO) and never flips the exit code on its own.
#
# Matched memory text is DATA, never instruction (§15, Fixture 7): the
# instruction-like heuristic only *flags* override phrasing for a human reviewer;
# audit never acts on it, exactly as `guard` ranks-but-never-executes record text.

# Severity ladder for audit findings.
AUDIT_FAIL = "fail"  # blocks (non-zero) — secrets only
AUDIT_WARN = "warn"  # flag for human review — never changes the exit code
AUDIT_INFO = "info"  # health/context note

# Directories under .project-memory/ the secret scan skips: private/ is gitignored
# local context, index/ is a disposable accelerator, generated/ holds derived
# projections rebuilt from canonical records (scanned for drift, not secrets).
_SECRET_SKIP_DIRS = {"private", "index", "generated"}

# Common secret SHAPES. Deliberately conservative: better to miss
# an exotic secret than to flag every git sha. The covered set is this tuple; the
# three deliberate gaps (bare hex only in a labeled context, path/CamelCase tokens
# allowlisted, URL credentials floored at 6 characters and placeholder-aware) are
# written up in `docs/security.md` §2 and pinned by `tests/test_secrets.py`.
SECRET_PATTERNS: tuple[tuple[str, "_LazyPattern"], ...] = (
    ("aws-access-key-id", _LazyPattern(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", _LazyPattern(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github-fine-grained-pat", _LazyPattern(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack-token", _LazyPattern(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", _LazyPattern(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    # sk-… covers both the legacy `sk-<base62>` and modern `sk-proj-<base62>`
    # OpenAI shapes (the hyphen in `proj-` broke the old alnum-only pattern).
    ("openai-style-key", _LazyPattern(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    # Stripe-style secret/restricted/publishable keys: sk_live_…, rk_test_…, etc.
    ("stripe-style-key", _LazyPattern(r"\b[srp]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("jwt", _LazyPattern(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("pem-private-key", _LazyPattern(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("bearer-token", _LazyPattern(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    (
        "secret-assignment",
        _LazyPattern(
            r"(?i)\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|"
            r"refresh[_-]?token|id[_-]?token|session[_-]?token|private[_-]?key|"
            r"signing[_-]?key|client[_-]?secret|password|passwd|pwd)\b"
            # allow a closing quote on the label so JSON keys ("private_key":)
            # match too — the scan now covers .json files
            r"['\"]?\s*[:=]\s*"
            r"['\"]?([A-Za-z0-9/+_\-]{16,})['\"]?"
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
        _LazyPattern(
            r"(?i)\b[a-z][a-z0-9+.\-]*://[^/\s:@]*:"
            r"(?!(?:password|passwd|pass|secret|token|changeme|placeholder|redacted|"
            r"example|user|username|test|xxx+|\*+)@)"
            r"(?![$%<{])"
            r"[^/\s:@]{6,}@"
        ),
    ),
    (
        "labeled-hex-secret",
        _LazyPattern(
            r"(?i)\b(?:token|authorization|x-[a-z0-9-]*-(?:key|token))\b\s*[:=]\s*"
            r"['\"]?[0-9a-fA-F]{32,}\b"
        ),
    ),
)

# Standalone high-entropy tokens (base64-ish). The charset excludes `_`/`-`, so
# record ids like `dec_20260605_markdown-source-of-truth` never form a long run,
# and the mixed-class + entropy floor below skips lowercase-only ids and hex shas.
_HIGH_ENTROPY_TOKEN = _LazyPattern(r"\b[A-Za-z0-9+/=]{32,}\b")

# Override-style phrasing audit flags for human review. A *flag*,
# never a gate — same content-as-data posture as guard (Fixture 7).
# A short run of qualifiers between the verb and its object, so natural phrasings
# ("ignore failing tests", "ignore all prior instructions", "skip the flaky
# suite's checks") are caught, not just the bare determiner forms.
_IL_QUALIFIERS = r"(?:(?:all|the|any|every|these|those|prior|previous|earlier|existing|above|failing|flaky|broken|remaining|other)\s+){0,3}"

INSTRUCTION_LIKE_PATTERNS: tuple["_LazyPattern", ...] = (
    _LazyPattern(
        r"(?i)\bignore\s+"
        + _IL_QUALIFIERS
        + r"(?:tests?|instructions?|previous|above|rules?|warnings?|memory|checks?|errors?|failures?)\b"
    ),
    _LazyPattern(
        r"(?i)\bskip\s+"
        + _IL_QUALIFIERS
        + r"(?:tests?|validation|verification|checks?|review|ci)\b"
    ),
    _LazyPattern(
        r"(?i)\bdisable\s+"
        + _IL_QUALIFIERS
        + r"(?:tests?|checks?|validation|guard|safety|linter?|ci)\b"
    ),
    # Imperative "never run X" only: an auxiliary right before it ("has never
    # run", "was never run") is a factual claim about history, not an
    # instruction — the field test's audit fired 7 warnings, all on sentences
    # like "E2E has never run in production" (P2-11). Python lookbehinds are
    # fixed-width, hence one per auxiliary.
    _LazyPattern(
        r"(?i)(?<!\bis\s)(?<!\bare\s)(?<!\bwas\s)(?<!\bhas\s)(?<!\bhad\s)"
        r"(?<!\bwere\s)(?<!\bbeen\s)(?<!\bhave\s)"
        r"\b(?:never|always)\s+run\b"
    ),
    _LazyPattern(r"(?i)\bdo\s+not\s+run\b"),
    _LazyPattern(r"(?i)\b(?:always|never)\s+(?:force[- ]?push|skip|disable|ignore|bypass)\b"),
    _LazyPattern(
        r"(?i)\bbypass\s+"
        + _IL_QUALIFIERS
        + r"(?:tests?|checks?|(?:code\s+)?review|validation|guard|ci)\b"
    ),
)

# Bloat thresholds (heuristic).
ADAPTER_FILENAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    ".clinerules",
    ".windsurfrules",
    ".github/copilot-instructions.md",
)
ADAPTER_BLOAT_CHARS = 4000  # signpost files should be small pointers, not copies
SESSIONS_GROWTH_NOTE = 50  # session count above which audit suggests promoting + pruning
# The always-on trap budget. Generous — a store of real traps is worth carrying —
# but bounded, because nothing else bounds it: the field store reached 167 KB and
# 77 active traps with no mechanism for anything to leave.
TRAPS_TOKEN_BUDGET = 8000


# ---- secret scan ----------------------------------------------------------- #


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
_PUSH_ID_SEGMENT_RE = _LazyPattern(r"^[A-Za-z0-9]{19,20}$")


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


# Text-file suffixes the secret scan covers. A `.yaml`/`.json`/`.txt` dropped
# under memory was previously never scanned.
_SECRET_SCAN_GLOBS = ("*.md", "*.yml", "*.yaml", "*.json", "*.txt")


def _iter_committed_memory_files(memory_dir: Path):
    """Yield committed-memory text files (skips private/index/generated subtrees)."""
    memory_dir = Path(memory_dir)
    paths: list[Path] = []
    for pattern in _SECRET_SCAN_GLOBS:
        paths.extend(memory_dir.rglob(pattern))
    for p in sorted(set(paths)):
        rel_parts = p.relative_to(memory_dir).parts
        if rel_parts and rel_parts[0] in _SECRET_SKIP_DIRS:
            continue
        yield p


CRUMBIGNORE_FILENAME = ".crumbignore"

# `high-entropy-string` is a heuristic with no structure behind it, and it gated
# every commit of the memory store. A project that has decided a given shape is
# not a secret should be able to say so once, rather than re-deciding it — and
# hand-overriding a gate on every commit is how a gate stops being read at all.
SECRET_WARNING_PATTERNS = frozenset({"high-entropy-string"})


def load_crumbignore(memory_dir: Path) -> list:
    """Patterns from `.project-memory/.crumbignore`, newest-wins order irrelevant.

    One pattern per line; `#` starts a comment. Each line is used as a regex, or
    as a literal substring if it does not compile. A hit whose *line text*
    matches any pattern is dropped by `scan_secrets` — the project has said, in a
    file its reviewers can see, that this shape is not a secret here.
    """
    path = Path(memory_dir) / CRUMBIGNORE_FILENAME
    if not path.is_file():
        return []
    text, _problem = read_text_lenient(path)
    patterns = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip() if not raw.lstrip().startswith("#") else ""
        if not line:
            continue
        try:
            patterns.append(re.compile(line))
        except re.error:
            patterns.append(re.compile(re.escape(line)))
    return patterns


def _secret_severity(pattern: str) -> str:
    """`warning` for the heuristics, `blocking` for shapes with real structure."""
    return AUDIT_WARN if pattern in SECRET_WARNING_PATTERNS else AUDIT_FAIL


def scan_secrets(memory_dir: Path) -> list[dict]:
    """Scan committed memory for secret-like strings.

    Each hit is {pattern, path, line} — the pattern NAME and location, never the
    matched value. Skips private/index/generated. This must run before any
    "commit memory" recommendation (§2.6, §15).

    A file that cannot be read cleanly yields a blocking `unscannable-file` hit
    rather than being skipped: silently exempting it made the whole "secrets are
    blocking" posture void for that file. Undecodable bytes are
    replaced and the readable remainder is still scanned, so a real secret next
    to a bad byte is still found.
    """
    findings: list[dict] = []
    seen: set[tuple[str, str, int]] = set()
    ignores = load_crumbignore(memory_dir)

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

    for p in _iter_committed_memory_files(memory_dir):
        rel = str(p.relative_to(memory_dir))
        text, problem = read_text_lenient(p)
        if problem:
            record("unscannable-file", rel, 0, detail=problem)
        for i, line in enumerate(text.splitlines(), 1):
            if any(pat.search(line) for pat in ignores):
                continue
            for name, pat in SECRET_PATTERNS:
                if pat.search(line):
                    record(name, rel, i)
            for m in _HIGH_ENTROPY_TOKEN.finditer(line):
                if _looks_high_entropy(m.group(0)):
                    record("high-entropy-string", rel, i)
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
    for rec in load_records(memory_dir):
        if not rec.error:
            targets.append(rec.path)

    seen: set[Path] = set()
    for p in targets:
        if p in seen or not p.is_file():
            continue
        seen.add(p)
        rel = str(p.relative_to(memory_dir))
        # Lenient: scan_secrets already reports the unreadable
        # file; this pass just must not abort audit on it.
        text = _strip_html_comments(read_text_lenient(p)[0])
        for i, line in enumerate(text.splitlines(), 1):
            for pat in INSTRUCTION_LIKE_PATTERNS:
                m = pat.search(line)
                if m:
                    findings.append({"path": rel, "line": i, "phrase": m.group(0).strip()})
                    break
    return findings


# ---- generated-packet drift ------------------------------------------------ #


def _stamped_inputs_hash(text: str) -> str | None:
    # Anchor to the generated source-header comment (written by render_packet_*
    # as `<!-- source_commit: … | inputs_hash: <hash> | … -->`) rather than the
    # whole file, so a stray `inputs_hash:` in copied body text isn't picked up.
    m = re.search(r"<!--\s*source_commit:.*?\binputs_hash:\s*([0-9a-f]+)", text)
    return m.group(1) if m else None


def detect_packet_drift(memory_dir: Path) -> list[dict]:
    """Flag committed generated projections whose stamped inputs_hash is stale.

    Compares each generated/*.md source-header `inputs_hash` against the current hash
    of the canonical inputs. Mismatch => a source record changed
    since the projection was built => regeneration needed. Hash-based, so it is
    robust to git checkouts not preserving mtimes.
    """
    memory_dir = Path(memory_dir)
    findings: list[dict] = []
    gen = memory_dir / "generated"
    if not gen.is_dir():
        return findings
    current = _inputs_hash(memory_dir)
    for p in sorted(gen.glob("*.md")):
        if p.name == "README.md":
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # undecodable projection — validate 16.12 reports it
        stamped = _stamped_inputs_hash(text)
        if stamped is None:
            continue  # an un-stamped projection (older format) — nothing to compare
        if stamped != current:
            findings.append(
                {"path": str(p.relative_to(memory_dir)), "stamped": stamped, "current": current}
            )
    return findings


# ---- bloat ----------------------------------------------------------------- #


def _audit_bloat(memory_dir: Path, root: Path) -> list[dict]:
    """Bloat heuristics: over-budget packet, adapter duplication,
    runaway sessions/ growth."""
    memory_dir = Path(memory_dir)
    findings: list[dict] = []

    # Packet over budget.
    pkt = memory_dir / "generated" / "resume-packet.md"
    if pkt.is_file():
        # Lenient throughout: audit is the gate command, so an
        # undecodable file must cost it one heuristic, not every finding it had.
        toks = approx_tokens(read_text_lenient(pkt)[0])
        if toks > TOKEN_BUDGET_MAX:
            findings.append(
                {
                    "kind": "packet-over-budget",
                    "path": "generated/resume-packet.md",
                    "message": f"resume packet ~{toks} tokens exceeds the {TOKEN_BUDGET_MAX}-token budget",
                }
            )

    # Adapter/signpost files duplicating canonical memory rather than pointing to it.
    canon: list[tuple[str, str]] = []
    for rec in load_records(memory_dir):
        if not rec.error and rec.body.strip():
            canon.append((str(rec.path.relative_to(memory_dir)), rec.body.strip()))
    for name in ADAPTER_FILENAMES:
        ap = Path(root) / name
        if not ap.is_file():
            continue
        text = read_text_lenient(ap)[0]
        dup = next((src for src, body in canon if len(body) >= 200 and body[:200] in text), None)
        if dup:
            findings.append(
                {
                    "kind": "adapter-duplication",
                    "path": name,
                    "message": (
                        f"adapter '{name}' copies memory record {dup} verbatim; "
                        "signpost files should point into memory, not duplicate it (§16.13)"
                    ),
                }
            )
            continue
        # Measure the managed block, not the host file. A repo's own
        # CLAUDE.md/AGENTS.md is legitimately large and is not ours to judge; what
        # §16.13 asks is that *our* signpost stay a small pointer. A file with no
        # managed block is not a signpost at all, so there is nothing to size —
        # `adapter-duplication` above still catches records copied into it.
        block = managed_block_text(text)
        if block is not None and len(block) > ADAPTER_BLOAT_CHARS:
            findings.append(
                {
                    "kind": "adapter-bloat",
                    "path": name,
                    "message": (
                        f"the breadcrumbs managed block in '{name}' is {len(block)} chars; "
                        "the signpost should be a small pointer into memory, not a large "
                        "copy (§16.13)"
                    ),
                }
            )

    # known-traps.md growth. Unlike the packet, nothing bounds this file: traps
    # are appended and never age out, and every session loads all of them. The
    # check names the report that makes retirement possible rather than asking
    # for a rollup command that does not exist.
    traps_path = memory_dir / "known-traps.md"
    if traps_path.is_file():
        traps = [t for t in load_traps(memory_dir) if (t.get("status") or "active") == "active"]
        toks = approx_tokens(read_text_lenient(traps_path)[0])
        if toks > TRAPS_TOKEN_BUDGET:
            findings.append(
                {
                    "kind": "traps-growth",
                    "path": "known-traps.md",
                    "message": (
                        f"{len(traps)} active trap(s), ~{toks} tokens of always-on context "
                        f"(budget {TRAPS_TOKEN_BUDGET}) — `crumb traps --stale` lists the "
                        "ones nobody has confirmed lately; retire one with "
                        "`crumb mark-status <id> stale`"
                    ),
                }
            )

    # sessions/ growth note. The advice is what a human can do today (promote the
    # durable parts, prune the rest); no rollup command exists, so telling users to
    # wait for one — as this note used to — is telling them to wait for nothing.
    sess = memory_dir / "sessions"
    n = len(list(sess.glob("*.md"))) if sess.is_dir() else 0
    if n > SESSIONS_GROWTH_NOTE:
        findings.append(
            {
                "kind": "sessions-growth",
                "path": "sessions/",
                "message": (
                    f"{n} session records — promote what still matters with `crumb "
                    "remember`, then `crumb prune sessions` to drop old machine "
                    "snapshots so the store stays navigable"
                ),
            }
        )
    return findings


# ---- audit core ------------------------------------------------------------ #

# validate-failing checks audit re-surfaces in its health view. These still gate
# `validate`; audit reports them so one pass shows the whole health picture (§19b.9).
_AUDIT_HEALTH_CHECKS = {"evidence", "status", "privacy", "superseded", "identity", "frontmatter"}


def _audit_finding(check: str, severity: str, path: str | None, message: str, **extra) -> dict:
    f = {"check": check, "severity": severity, "path": path, "message": message}
    f.update(extra)
    return f


def run_audit(memory_dir: Path, root: Path, *, stale_days: int = STALE_AGE_DAYS) -> list[dict]:
    """Heuristic health + safety audit.

    Returns findings tagged with a severity. Only `secret` is fail-severity (blocks);
    everything else advises. Policy-aware: reads tracking policy via the manifest /
    loaders rather than guessing (§7).
    """
    memory_dir = Path(memory_dir)
    findings: list[dict] = []

    # B. Secret scan — the only blocking check (§15, §17.6, Fixture 6).
    for s in scan_secrets(memory_dir):
        if s["pattern"] == "unscannable-file":
            # Blocking, like a secret: the scan could not certify this file, and
            # "we didn't look" must never read as "nothing there".
            findings.append(
                _audit_finding(
                    "secret",
                    AUDIT_FAIL,
                    s["path"],
                    f"{s.get('detail') or 'could not be read'} — the secret scan cannot "
                    "certify this file; fix it before committing memory",
                    pattern=s["pattern"],
                )
            )
            continue
        severity = s.get("severity", AUDIT_FAIL)
        remedy = (
            "must not be committed to memory; remove before any commit"
            if severity == AUDIT_FAIL
            else f"heuristic, not a structured credential shape — confirm, then add a "
            f"pattern to {MEMORY_DIRNAME}/{CRUMBIGNORE_FILENAME} if it is not a secret here"
        )
        findings.append(
            _audit_finding(
                "secret",
                severity,
                s["path"],
                f"possible secret ({s['pattern']}) at line {s['line']} — {remedy}",
                line=s["line"],
                pattern=s["pattern"],
            )
        )

    # A. Staleness / health (reuse compute_staleness): handoff age +
    # commit-distance, branch mismatch (incl. detached HEAD), aged-unresolved
    # questions/decisions, expired + low-confidence records.
    # Lenient read: audit is the gate command, so an undecodable
    # handoff must not abort it. scan_secrets above already emits the blocking
    # `unscannable-file` finding that names the file, so this read stays quiet.
    handoff_text = (
        read_text_lenient(memory_dir / "handoff.md")[0]
        if (memory_dir / "handoff.md").is_file()
        else ""
    )
    for w in compute_staleness(
        root,
        parse_handoff_meta(handoff_text),
        active_decisions(memory_dir),
        active_attempts(memory_dir),
        load_open_questions(memory_dir),
        stale_days,
        memory_dir=memory_dir,
    ):
        # The handoff age/distance line is emitted unconditionally; it is only a
        # *warning* when compute_staleness marked it cold (⚠). "handoff is 0
        # day(s) old, written 0 commit(s) behind" on a seconds-old store is
        # health context, not a problem.
        sev = AUDIT_INFO if (w.startswith("handoff is") and not w.startswith("⚠")) else AUDIT_WARN
        findings.append(_audit_finding("staleness", sev, "handoff.md", w))

    # A (cont). Re-surface the validate-failing health conditions for the health view
    # (missing evidence, invalid status, private-path violation, id/frontmatter
    # disagreement). These still FAIL `validate`; audit only reports them (§19b.9).
    for vf in run_validate(memory_dir):
        if vf["status"] == "fail" and vf["check"] in _AUDIT_HEALTH_CHECKS:
            findings.append(_audit_finding(vf["check"], AUDIT_WARN, vf["path"], vf["message"]))

    # C. Instruction-like text (flag only; never a gate — §16 note, Fixture 7).
    for il in scan_instruction_like(memory_dir):
        findings.append(
            _audit_finding(
                "instruction-like",
                AUDIT_WARN,
                il["path"],
                f'override-style phrasing "{il["phrase"]}" at line {il["line"]} — '
                "review (treated as data, never executed)",
                line=il["line"],
                phrase=il["phrase"],
            )
        )

    # D. Generated-packet drift (§15, §17.8, Fixture 8).
    for d in detect_packet_drift(memory_dir):
        findings.append(
            _audit_finding(
                "packet-drift",
                AUDIT_WARN,
                d["path"],
                f"generated projection is stale (stamped inputs_hash {d['stamped']} != "
                f"current {d['current']}) — regenerate with `crumb resume`",
                stamped=d["stamped"],
                current=d["current"],
            )
        )

    # E. Bloat (§16.13, §12).
    for b in _audit_bloat(memory_dir, root):
        sev = AUDIT_INFO if b["kind"] == "sessions-growth" else AUDIT_WARN
        findings.append(_audit_finding("bloat", sev, b["path"], b["message"], kind=b["kind"]))

    # F. Guard reachability (field test 2026-08-04). Guard's strong signals
    # are file and tag overlap; a record carrying neither can only surface through
    # generic keyword overlap, which the stale/branch factors readily push under
    # the noise floor. That is an authoring rule nothing stated: a prose-only
    # record is quietly on its way to unreachable, so say so while the author is
    # still around to add tags or file evidence.
    for rec in load_records(memory_dir, types=JUDGING_ITEM_TYPES):
        if rec.error or str(rec.meta.get("status") or "active") != "active":
            continue  # unparseable is its own finding; non-active never drives verdicts
        item = _item_from_record(rec)
        if item["tags"] or item["files"] or item["mentioned_files"]:
            continue
        findings.append(
            _audit_finding(
                "unreachable",
                AUDIT_WARN,
                str(rec.path.relative_to(memory_dir)),
                "no tags and no file references — guard can reach this record "
                "only through generic keyword overlap; add tags or file/path "
                "evidence so it can drive a verdict",
            )
        )

    return findings


# ---- rendering + command entry points -------------------------------------- #


def render_audit_human(findings: list[dict]) -> str:
    fails = [f for f in findings if f["severity"] == AUDIT_FAIL]
    warns = [f for f in findings if f["severity"] == AUDIT_WARN]
    infos = [f for f in findings if f["severity"] == AUDIT_INFO]
    if not findings:
        # No trailing newline: the sole caller prints this, which adds one.
        return "audit: OK — no problems, warnings, or notes."

    out: list[str] = [
        f"audit: {len(fails)} problem(s), {len(warns)} warning(s), {len(infos)} note(s).",
        "",
    ]
    if fails:
        out.append("Blocking (memory is NOT safe to commit until resolved):")
        for f in fails:
            out.append(f"  {MARK_FAIL} [{f['check']}] {f['path'] or '-'}: {f['message']}")
        out.append("")
    if warns:
        out.append("Warnings (review — these do not block):")
        for f in warns:
            out.append(f"  ⚠ [{f['check']}] {f['path'] or '-'}: {f['message']}")
        out.append("")
    if infos:
        out.append("Notes:")
        for f in infos:
            out.append(f"  • [{f['check']}] {f['path'] or '-'}: {f['message']}")
        out.append("")
    return "\n".join(out).rstrip()


def cmd_audit(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    stale_days = args.stale_days if args.stale_days is not None else STALE_AGE_DAYS
    findings = run_audit(memory_dir, root, stale_days=stale_days)
    fails = [f for f in findings if f["severity"] == AUDIT_FAIL]
    warns = [f for f in findings if f["severity"] == AUDIT_WARN]
    infos = [f for f in findings if f["severity"] == AUDIT_INFO]
    exit_code = 1 if fails else 0

    if args.json:
        _print_json(
            args,
            {
                "failed": len(fails),
                "warnings": len(warns),
                "info": len(infos),
                "findings": findings,
            },
            ok=not fails,
            summary={"passed": len(findings) - len(fails), "failed": len(fails)},
        )
        return exit_code

    if args.plain:
        for f in findings:
            print(f"{f['severity'].upper()} {f['check']} {f['path'] or '-'}: {f['message']}")
        return exit_code

    print(render_audit_human(findings))
    return exit_code


def cmd_scan_secrets(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    hits = scan_secrets(memory_dir)
    # Only a shape with real structure gates a commit (R5). An entropy heuristic
    # with no allowlist punishes exactly the records that are most useful — the
    # ones citing a concrete production path — and a gate that is hand-overridden
    # every time has stopped being a gate. Warnings are still printed, and still
    # counted; they just do not decide the exit code.
    blocking = [h for h in hits if h.get("severity", AUDIT_FAIL) == AUDIT_FAIL]
    warnings = [h for h in hits if h.get("severity", AUDIT_FAIL) != AUDIT_FAIL]
    if args.json:
        _print_json(
            args,
            {
                "count": len(hits),
                "blocking": len(blocking),
                "warnings": len(warnings),
                "hits": hits,
            },
            ok=not blocking,
            summary={"failed": len(blocking), "warnings": len(warnings)},
        )
        return 1 if blocking else 0

    if hits:
        unscannable = [h for h in blocking if h["pattern"] == "unscannable-file"]
        secrets = [h for h in blocking if h["pattern"] != "unscannable-file"]
        parts = ([f"{len(secrets)} possible secret(s)"] if secrets else []) + (
            [f"{len(unscannable)} unscannable file(s)"] if unscannable else []
        )
        if blocking:
            print(
                f"scan-secrets: {' and '.join(parts)} found — DO NOT commit memory until resolved\n"
            )
        else:
            print(f"scan-secrets: {len(warnings)} warning(s), nothing blocking\n")
        for h in hits:
            where = f"{h['path']}:{h['line']}" if h["line"] else h["path"]
            detail = f" — {h['detail']}" if h.get("detail") else ""
            mark = MARK_FAIL if h.get("severity", AUDIT_FAIL) == AUDIT_FAIL else "!"
            print(f"  {mark} [{h['pattern']}] {where}{detail}")
        if warnings:
            print(
                f"\nnote: {len(warnings)} warning(s) do not block. If a shape is not a "
                f"secret in this project, add a pattern to {MEMORY_DIRNAME}/"
                f"{CRUMBIGNORE_FILENAME} instead of overriding this every time."
            )
        return 1 if blocking else 0

    print("scan-secrets: OK — no secret-like strings in committed memory.")
    return 0


# --------------------------------------------------------------------------- #
# Integrations — bootstrapping the automaticity primitives
# --------------------------------------------------------------------------- #
#
# The package already ships every ingredient for automatic use (the fenced
# managed-block writer, the ADAPTER_FILENAMES list, the breadcrumbs-mcp server);
# this section assembles them behind explicit consent and makes each edit fenced
# and reversible. Default `crumb init` behavior is unchanged — integrations are
# opt-in (flags, or the first-run interactive picker).

MCP_SERVER_NAME = "breadcrumbs"


def mcp_server_entry(*, windows: bool | None = None) -> dict:
    """The `.mcp.json` entry for the breadcrumbs server (verified Claude Code shape).

    The server reads $BREADCRUMBS_PROJECT to locate the store; `${CLAUDE_PROJECT_DIR}`
    is exported by Claude Code, with a `.`-fallback for other launchers.

    **On Windows the module entry point is used instead of the console script**
    (0.1.11 field audit, F-7). `pip install --upgrade "crumb-kit[mcp]"` fails at
    the uninstall step with `OSError: [WinError 32]` on
    `Scripts\\breadcrumbs-mcp.exe` whenever any MCP server is running, and every
    live editor session holds that shim open — orphaned copies accumulate, so the
    upgrade fails against servers the user does not know are running. The shim is
    opened without `FILE_SHARE_DELETE`, so Windows blocks rename as well as
    delete and the usual self-updater rename-aside trick does not work either;
    the only route is to stop every server first.

    Launching via `<python> -m breadcrumbs mcp serve` makes the running server
    hold the *interpreter* open rather than a file pip needs to delete, so
    in-place upgrades stop failing. `python -m breadcrumbs mcp serve` was
    verified to speak stdio identically to the console script — same
    `initialize` handshake, same 10 tools / 6 resources / 6 prompts — before this
    was changed; the module path is `cmd_mcp`'s own `serve` branch, so there is
    no second server implementation to drift.

    POSIX keeps the console script: it has no such locking problem, and the
    script is shorter, PATH-relative and interpreter-agnostic.

    Note `sys.executable` is an absolute, machine-specific path, and `.mcp.json`
    is usually committed. That is the deliberate trade — a portable `"python"`
    would resolve through PATH to whichever interpreter comes first, which on the
    `--user` installs this bug afflicts is frequently not the one holding the
    package.
    """
    if windows is None:
        windows = os.name == "nt"
    command, args = ("breadcrumbs-mcp", [])
    if windows:
        command, args = (sys.executable, ["-m", "breadcrumbs", "mcp", "serve"])
    return {
        "type": "stdio",
        "command": command,
        "args": args,
        "env": {"BREADCRUMBS_PROJECT": "${CLAUDE_PROJECT_DIR:-.}"},
    }


def _splice_json_insert(text: str, parent_key: str, key: str, value: dict) -> str | None:
    """Insert `key: value` into the `parent_key` object by text splice.

    Preserves every other byte of the file — `merge_json_file`'s full
    re-serialization reformatted entries it does not own (P2-13: a `firebase`
    server's one-line args array came back multi-line). Returns the spliced
    text, or None when the anchor cannot be found; the caller MUST verify the
    result by re-parsing, which also defuses a false anchor match inside a
    string value (the reparse then disagrees with the expected data and the
    caller falls back to the full rewrite).
    """
    m = re.search(rf'"{re.escape(parent_key)}"\s*:\s*\{{', text)
    if m is None:
        return None
    line_start = text.rfind("\n", 0, m.start()) + 1
    parent_indent = re.match(r"[ \t]*", text[line_start:]).group(0)
    child_indent = parent_indent + "  "
    body = json.dumps(value, indent=2)
    lines = body.splitlines()
    rendered = lines[0] + "".join("\n" + child_indent + ln for ln in lines[1:])
    snippet = f'\n{child_indent}"{key}": {rendered},'
    return text[: m.end()] + snippet + text[m.end() :]


def register_mcp(root: Path) -> tuple[Path, bool]:
    """Add the breadcrumbs server to `.mcp.json`; other servers stay byte-identical.

    Returns (path, changed). Three tiers, safest-first: an already-current entry
    is a no-op; a fresh insert into an existing `mcpServers` object is a text
    splice (verified by re-parse) so unrelated entries keep their exact
    formatting; anything else falls back to the parse-validated full rewrite.
    """
    path = root / ".mcp.json"
    entry = mcp_server_entry()

    if path.exists():
        text = path.read_text(encoding="utf-8")
        try:
            data = json.loads(text) if text.strip() else {}
        except json.JSONDecodeError:
            data = None  # merge_json_file below raises the canonical error
        if isinstance(data, dict) and isinstance(data.get("mcpServers"), dict):
            servers = data["mcpServers"]
            if servers.get(MCP_SERVER_NAME) == entry:
                return path, False
            if MCP_SERVER_NAME not in servers:
                spliced = _splice_json_insert(text, "mcpServers", MCP_SERVER_NAME, entry)
                if spliced is not None:
                    expected = json.loads(json.dumps(data))
                    expected["mcpServers"][MCP_SERVER_NAME] = entry
                    try:
                        ok = json.loads(spliced) == expected
                    except json.JSONDecodeError:
                        ok = False
                    if ok:
                        path.write_text(spliced, encoding="utf-8")
                        return path, True

    def _mut(data: dict) -> None:
        servers = data.setdefault("mcpServers", {})
        servers[MCP_SERVER_NAME] = mcp_server_entry()

    merge_json_file(path, _mut)
    return path, True


def unregister_mcp(root: Path) -> bool:
    """Remove the breadcrumbs server from `.mcp.json`. True iff it was present."""
    path = root / ".mcp.json"
    if not path.exists():
        return False
    state = {"present": False}

    def _mut(data: dict) -> None:
        servers = data.get("mcpServers")
        if isinstance(servers, dict) and MCP_SERVER_NAME in servers:
            del servers[MCP_SERVER_NAME]
            state["present"] = True
            if not servers:
                data.pop("mcpServers", None)

    merge_json_file(path, _mut)
    return state["present"]


def _mcp_sdk_available() -> bool:
    """Whether the optional [mcp] extra is importable (lazy; never hard-fails)."""
    try:
        from breadcrumbs import mcp_server

        return mcp_server.sdk_available()
    except Exception:  # pragma: no cover - defensive
        return False


def cmd_mcp(args: argparse.Namespace) -> int:
    what = getattr(args, "mcp_what", None)
    if what == "serve":
        # `--project` must actually target the server at that project — it was
        # accepted and silently ignored, so reads AND writes went to cwd's store.
        # The server resolves $BREADCRUMBS_PROJECT.
        if getattr(args, "project", None):
            os.environ["BREADCRUMBS_PROJECT"] = str(resolve_root(args.project))
        # Lazy import keeps `crumb` stdlib-only; the server degrades with a clear
        # hint when the [mcp] extra is missing.
        from breadcrumbs import mcp_server

        return mcp_server.main([])

    if what == "register":
        root = resolve_root(args.project)
        path, changed = register_mcp(root)
        sdk = _mcp_sdk_available()
        summary = {
            "registered": str(path),
            "server": MCP_SERVER_NAME,
            "changed": changed,
            "sdk_available": sdk,
        }
        if args.json:
            _print_json(args, summary)
        else:
            state = "" if changed else " (already current)"
            print(f"Registered MCP server '{MCP_SERVER_NAME}' in {path}{state}")
            if not sdk:
                print("  note: the MCP SDK isn't installed — run: pip install 'crumb-kit[mcp]'")
            print(
                "  note: in Claude Code a committed .mcp.json server starts "
                "'⏸ Pending approval' until you approve it once — this is expected."
            )
            if os.name == "nt":
                print(
                    "  note: launching via this interpreter (-m breadcrumbs mcp serve) "
                    "rather than the\n"
                    "        breadcrumbs-mcp.exe shim, so `pip install --upgrade` is not "
                    "blocked by a\n"
                    "        running server (WinError 32)."
                )
        return 0

    if what == "doctor":
        root = resolve_root(args.project)
        sdk = _mcp_sdk_available()
        mcp_path = root / ".mcp.json"
        registered = False
        if mcp_path.is_file():
            try:
                registered = MCP_SERVER_NAME in (
                    json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers") or {}
                )
            except (json.JSONDecodeError, OSError):
                registered = False
        report = {"sdk_available": sdk, "registered": registered, "config": str(mcp_path)}
        if args.json:
            _print_json(args, report)
        else:
            print("crumb mcp doctor")
            print(
                f"  {MARK_PASS if sdk else MARK_FAIL} [mcp] extra: "
                + ("importable" if sdk else "not installed — run: pip install 'crumb-kit[mcp]'")
            )
            print(
                f"  {MARK_PASS if registered else MARK_FAIL} registration: "
                + (
                    f"'{MCP_SERVER_NAME}' in {mcp_path}"
                    if registered
                    else "not registered — run `crumb mcp register`"
                )
            )
        return 0 if (sdk and registered) else 1

    _emit_error(args, "specify: `crumb mcp serve`, `crumb mcp register`, or `crumb mcp doctor`")
    return 2


# ---- adapter signpost block ------------------------------------------------ #

# Markdown-comment markers for the adapter managed block (same fence mechanism as
# .gitignore, different comment syntax).
ADAPTER_BEGIN = (
    "<!-- >>> breadcrumbs managed block (managed by `crumb init`) "
    "— edit above/below, not inside >>> -->"
)
ADAPTER_END = "<!-- <<< breadcrumbs managed block <<< -->"


def managed_block_text(text: str) -> str | None:
    """The breadcrumbs-managed region of an adapter file, or None if absent.

    Every size check must measure *this*, never the host file. `CLAUDE.md`
    and `AGENTS.md` are the project's own agent-instruction files and are routinely
    tens of KB in a mature repo; measuring the whole file meant `doctor` reported
    the adapter row as bloated the moment the signpost was installed *correctly*,
    and never stopped. The size of a project's instruction file is not breadcrumbs'
    business — the size of the block breadcrumbs writes into it is.

    An unterminated block (someone hand-deleted the END marker) counts as ours
    through end-of-file: we can no longer tell where our region stops.
    """
    if ADAPTER_BEGIN not in text:
        return None
    _, _, rest = text.partition(ADAPTER_BEGIN)
    inner, sep, _ = rest.partition(ADAPTER_END)
    return ADAPTER_BEGIN + inner + (ADAPTER_END if sep else "")


def adapter_block() -> str:
    """The signpost injected into agent-guidance files: a small pointer, not a copy.

    Deliberately tiny (well under ADAPTER_BLOAT_CHARS) so the tool's own `audit`
    stays green — it practices what it preaches. Generic guidance text, never a
    record body, so it cannot trip audit's record-duplication check.
    """
    return (
        "\n".join(
            [
                ADAPTER_BEGIN,
                "## Project memory (breadcrumbs)",
                "",
                "This repo has a durable memory store under `.project-memory/`. Use it:",
                "",
                "- **Starting work / new session:** read the resume packet first —",
                "  `crumb resume` (or MCP resource `memory://resume-packet`).",
                "- **Before any risky or irreversible action** (deletes, force-push, schema",
                '  or build-system changes, rewrites): `crumb guard "<action>"` and honor a',
                "  `PAUSE` / `ASK_HUMAN` verdict.",
                "- **After a durable decision or a failed approach:**",
                "  `crumb remember decision|attempt …`.",
                "- **After checking whether something is still true / fixed:**",
                '  `crumb verify "<subject>" --status fixed|open|regressed|… --evidence …`.',
                "- **Leaving a note for the next agent:** `crumb note question|trap|idea …`",
                "  (for a trap, pass `--area/--symptom/--why/--safe/--verify` — a warning",
                "  with no mechanism is one the next agent learns to ignore).",
                "- **When a trap or decision no longer applies:**",
                '  `crumb mark-status <id> stale --reason "…"`, so it stops raising `guard`.',
                "- **When an open question gets answered:**",
                '  `crumb mark-status q:<slug> answered --reason "…"` (name the decision',
                "  that answered it), so it stops counting as a live blocker.",
                '- **Session end:** `crumb capture session --next "<what to do next>"`',
                '  (add `--set "Decisions Made" "…"` for narrative). Pass `--next`: the bare',
                "  form prompts for each section and cannot be answered without a terminal.",
                "  If the `Stop` hook is installed, a snapshot is already taken for you.",
                "",
                "Memory must never contain secrets; `crumb scan-secrets` gates commits.",
                ADAPTER_END,
            ]
        )
        + "\n"
    )


def present_adapters(root: Path) -> list[str]:
    """Adapter-guidance files that already exist (we never create new ones)."""
    return [name for name in ADAPTER_FILENAMES if (root / name).is_file()]


def write_adapter_block(root: Path, name: str) -> bool:
    """Insert/replace the signpost block in an agent-guidance file, creating it if absent.

    `.github/copilot-instructions.md` is the one adapter name that lives in a
    subdirectory, so creating it means creating `.github/` too. Returns True iff
    the file changed (an already-current block is a no-op).
    """
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return rewrite_managed_block(path, ADAPTER_BEGIN, ADAPTER_END, adapter_block())


def remove_adapter_block(root: Path, name: str) -> bool:
    """Strip our managed block from an adapter file. True iff it was present."""
    path = root / name
    if not path.exists():
        return False
    had = ADAPTER_BEGIN in path.read_text(encoding="utf-8")
    rewrite_managed_block(path, ADAPTER_BEGIN, ADAPTER_END, None)
    return had


# ---- Claude Code hooks ----------------------------------------------------- #

HOOK_EVENTS = ("session", "guard", "capture")
# breadcrumbs event -> (Claude Code event name, PreToolUse matcher or None)
_HOOK_SPECS: dict[str, tuple[str, str | None]] = {
    "session": ("SessionStart", None),
    "guard": ("PreToolUse", "Bash|Edit|Write|MultiEdit"),
    "capture": ("Stop", None),
}

# The key `init` stamps into each hook entry it owns, valued with the breadcrumbs
# event name. Identity must not live in the command text: a hook installed
# through any launcher — a wrapper script, a venv path, `python -m breadcrumbs` —
# was invisible to us, so `doctor` said "no hooks installed" while all three fired,
# `--remove-integrations` silently left them behind, and the next `init
# --with-hooks` appended a second copy that fired alongside the first. Installing
# through a wrapper has to stay a supported path: on some hosts it is the only
# way to reach the CLI at all.
HOOK_MARKER = "breadcrumbsHook"

# Where to look for the CLI, in order, before giving up. `command -v` answers for
# both a bare name (searched on $PATH) and a path (executable or not).
_HOOK_CRUMB_PATHS = (
    "crumb",
    '"${CLAUDE_PROJECT_DIR:-.}/.venv/bin/crumb"',
    '".venv/bin/crumb"',
    '"${CLAUDE_PROJECT_DIR:-.}/.venv/Scripts/crumb.exe"',
    '".venv/Scripts/crumb.exe"',
)
# Last resort: any interpreter that can import the package runs the same CLI. This
# is what rescues a Windows `pip install --user`, where the console script lands in
# %APPDATA%\Python\PythonXY\Scripts — on the Windows PATH, but not on the PATH a
# bash spawned from PowerShell inherits.
_HOOK_PYTHONS = ("python3", "python", "py")

# What a SessionStart hook says when it could not find the CLI. Emphatically not
# `{}`: an empty object is a valid "no opinion" for every event, so a
# breadcrumbs install that silently resolved to nothing would look healthy forever
# while loading no memory at all. Single quotes are impossible here — the JSON is
# carried inside a single-quoted shell word.
HOOK_INACTIVE_CONTEXT = (
    "Project memory (breadcrumbs) is INACTIVE this session: the crumb CLI was not "
    "found on PATH, in ./.venv, or via `python -m breadcrumbs`, so no resume packet "
    "was loaded. Read .project-memory/generated/resume-packet.md directly if it "
    "exists; `pip install crumb-kit` restores automatic loading."
)


def _hook_fallback_json(event: str) -> str:
    """The hook payload to print when the CLI cannot be found."""
    if event != "session":
        return "{}"  # PreToolUse/Stop: no opinion is the correct silent answer
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": HOOK_INACTIVE_CONTEXT,
            }
        }
    )


def hook_command(event: str) -> str:
    """The shell command `init --with-hooks` installs for one hook event.

    Not a bare `crumb hook <event>`. In a containerized session the CLI is
    installed into a project venv at SessionStart and exported through
    `CLAUDE_ENV_FILE`, which reaches later *tool* calls but not necessarily a
    sibling hook in the same batch; on Windows a bash spawned from PowerShell
    inherits a PATH without the `--user` Scripts directory. Both greet the user
    with `crumb: command not found`, silently, every session. So: try $PATH, then
    the usual venv layouts (POSIX and Windows), then any interpreter that can
    import the package — and if all of that fails, say so instead of exiting mute.

    POSIX `sh` syntax. A launcher of your own is a supported alternative: point the
    command at whatever you like and keep the `HOOK_MARKER` key on the entry, and
    `doctor` and `--remove-integrations` will still recognize it.

    Cost matters here — `PreToolUse` fires on every Bash/Edit/Write and is already
    dominated by interpreter startup. Resolution is shell builtins until something
    matches, the hit path is a single `exec`, and the interpreter fallback runs the
    module *once* (a separate `import breadcrumbs` probe would have doubled the
    startup cost for exactly the users who need that fallback).
    """
    fallback = _hook_fallback_json(event)
    parts = [
        "for c in " + " ".join(_HOOK_CRUMB_PATHS) + "; do "
        f'command -v "$c" >/dev/null 2>&1 && exec "$c" hook {event}; done',
        "for p in " + " ".join(_HOOK_PYTHONS) + "; do "
        'command -v "$p" >/dev/null 2>&1 || continue; '
        f'o=$("$p" -m breadcrumbs hook {event} 2>/dev/null) '
        "&& { printf '%s\\n' \"$o\"; exit 0; }; done",
        f"printf '%s\\n' '{fallback}'",
        "exit 0",
    ]
    return "; ".join(parts)


def _generated_hook_commands(event: str) -> set[str]:
    """Every command breadcrumbs has itself emitted for `event`.

    Re-running `init --with-hooks` upgrades one of these in place; anything else in
    the slot is the user's own launcher and is left exactly as they wrote it. When
    the emitted form changes, add the old one here rather than widening the match —
    guessing that a command "looks like ours" is how we would overwrite a wrapper
    someone wrote on purpose.
    """
    return {f"crumb hook {event}", hook_command(event)}


def _hook_command_event(command: object) -> str | None:
    """Best-effort read of an unmarked entry: does this command run a crumb hook?

    Only a fallback — `HOOK_MARKER` is the real answer. It exists for entries
    written before the marker and for launchers a user wired up by hand, which is
    the case that made `--remove-integrations` a lie.

    The event must appear as a whitespace-delimited *argument*, not merely
    somewhere in the text. `\\bsession\\b` also matches inside
    `.../crumb-hook-session-setup.sh`, because `-` is a word boundary — so a
    neighbouring script that happens to be named after a hook event was read as
    ours. Requiring an argument keeps every real launcher (`crumb hook session`,
    `./crumb-hook.sh session`) and drops the lookalikes.
    """
    text = str(command or "")
    if "crumb" not in text.lower():
        return None
    tokens = {t.strip("\"';,()`") for t in text.split()}
    return next((ev for ev in _HOOK_SPECS if ev in tokens), None)


def _hook_entry_event(hook: object) -> str | None:
    """Which breadcrumbs event a settings.json hook entry implements, if any."""
    if not isinstance(hook, dict):
        return None
    marked = hook.get(HOOK_MARKER)
    if isinstance(marked, str) and marked in _HOOK_SPECS:
        return marked
    return _hook_command_event(hook.get("command"))


def _group_entries(group: object) -> list[dict]:
    """The hook entries of one settings.json matcher group."""
    if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
        return []
    return [h for h in group["hooks"] if isinstance(h, dict)]


def install_claude_hooks(root: Path, events: list[str]) -> Path:
    """Merge SessionStart/PreToolUse/Stop hooks into .claude/settings.json.

    Appends to existing hook arrays (never clobbers other hooks) and is idempotent —
    re-running does not duplicate the breadcrumbs entries, whatever launcher those
    entries use. An entry already in the slot is adopted: it gets the marker so the
    rest of the tool can see it, and its command is rewritten only when breadcrumbs
    is the one that wrote it.
    """
    path = root / ".claude" / "settings.json"

    def _mut(data: dict) -> None:
        hooks = data.setdefault("hooks", {})
        for ev in events:
            cc_event, matcher = _HOOK_SPECS[ev]
            arr = hooks.setdefault(cc_event, [])
            existing = [h for g in arr for h in _group_entries(g) if _hook_entry_event(h) == ev]
            if existing:
                for h in existing:
                    if h.get("command") in _generated_hook_commands(ev):
                        h["command"] = hook_command(ev)
                    h[HOOK_MARKER] = ev
                continue
            entry: dict = {
                "hooks": [{"type": "command", "command": hook_command(ev), HOOK_MARKER: ev}]
            }
            if matcher:
                entry = {"matcher": matcher, **entry}
            arr.append(entry)

    merge_json_file(path, _mut)
    return path


def remove_claude_hooks(root: Path) -> dict:
    """Remove breadcrumbs' hook entries from .claude/settings.json.

    Returns `{"removed": [commands…], "left": [commands…]}` — JSON-serializable,
    because `--remove-integrations --json` reports it. Note it is always truthy;
    test `["removed"]`, not the dict.

    **The marker is authoritative here, and only here.** Detection may
    guess — over-reporting a hook as installed costs nothing — but deletion is
    irreversible, and `_hook_command_event` matches any command naming crumb plus
    an event word, so a `crumb-session-setup.sh` that was never ours would be
    matched and destroyed. Adoption is the safe direction: `init --with-hooks`
    stamps an entry it recognizes, and stamped entries are removable forever
    after. What is *not* acceptable is leaving a hook behind while reporting a
    clean uninstall — so anything recognized but unmarked
    is reported in `left` and the caller must say so out loud.

    Per *entry*, not per group: a group we share with someone else's hook keeps
    theirs and loses ours, and only a group left empty is dropped.
    """
    path = root / ".claude" / "settings.json"
    out: dict = {"removed": [], "left": []}
    if not path.exists():
        return out

    def _mut(data: dict) -> None:
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            return
        for cc_event in list(hooks):
            arr = hooks.get(cc_event)
            if not isinstance(arr, list):
                continue
            groups: list = []
            for group in arr:
                entries = _group_entries(group)
                kept = []
                for h in entries:
                    if isinstance(h.get(HOOK_MARKER), str) and h[HOOK_MARKER] in _HOOK_SPECS:
                        out["removed"].append(str(h.get("command", "")))
                        continue
                    if _hook_command_event(h.get("command")):
                        out["left"].append(str(h.get("command", "")))
                    kept.append(h)
                if len(kept) == len(entries):
                    groups.append(group)
                    continue
                if kept:
                    group["hooks"] = kept
                    groups.append(group)
            if groups:
                hooks[cc_event] = groups
            else:
                del hooks[cc_event]
        if not hooks:
            data.pop("hooks", None)

    merge_json_file(path, _mut)
    return out


# ---- integration plan: resolve flags / prompt, apply, remove, describe ----- #

FIRST_RUN_NUDGE = (
    "note: .project-memory/ is set up, but no agent integration was installed.\n"
    "      The store is only used if your agent is told to use it. Wire it up with\n"
    "      `crumb init --with-adapter --with-mcp` (and `--with-hooks`), or check\n"
    "      status anytime with `crumb doctor`."
)


def _resolve_tristate_list(value, all_items: list[str]) -> list[str] | None:
    """Map a --with-X[=a,b] / --no-X flag value to a concrete list, or None if unset.

    False -> [] (disabled); None -> None (undecided); "*" -> all_items; "a,b" -> [a,b].
    """
    if value is False:
        return []
    if value is None:
        return None
    if value == "*":
        return list(all_items)
    return [s.strip() for s in str(value).split(",") if s.strip()]


def _fmt_adapter_targets(root: Path, names: list[str]) -> str:
    """Render planned adapter targets, marking the ones that do not exist yet.

    `--print-integrations` used to print a bare filename for a file that was
    never going to be touched, so the dry run promised what the real run then
    silently skipped.
    """
    if not names:
        return "(none)"
    return ", ".join(n if (root / n).is_file() else f"{n} (will be created)" for n in names)


def _adapter_request_note(args: argparse.Namespace, adapters: list[str]) -> str | None:
    """Explain an adapter request that legitimately resolved to nothing.

    Bare `--with-adapter` on a project with no guidance file now falls back to
    creating `AGENTS.md` (the cross-agent standard), so the only way an
    explicit adapter request resolves empty is `--with-adapter=` with an empty
    list — still worth a note rather than a silent no-op, because `doctor`
    will report `✗ [adapter]` and the user should hear both facts together.
    """
    if adapters or getattr(args, "adapter", None) in (None, False):
        return None
    return (
        "the adapter list resolved to no files, so no signpost was written. "
        f"Name one to create it, e.g. `--with-adapter={ADAPTER_FILENAMES[0]}`."
    )


def _prompt_yes(question: str, default: bool) -> bool:
    """Ask a yes/no question. EOF declines; Ctrl+C aborts the command.

    Mapping `KeyboardInterrupt` to the default meant Ctrl+C at "Register the MCP
    server in .mcp.json?" (default yes) was recorded as consent and went on to edit
    `.mcp.json` — the one input that unambiguously means "stop".
    EOF is the same class: it means the shell *cannot* answer, not that it
    answered yes — under an agent harness whose stdin looks like a TTY but reads
    EOF, taking the yes-default was an unasked `.mcp.json` write. Only an explicit
    or defaulted *answer from a read that succeeded* counts as consent.
    """
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        ans = input(question + suffix).strip().lower()
    except EOFError:
        return False
    if not ans:
        return default
    return ans in ("y", "yes")


def validate_integration_flags(args: argparse.Namespace) -> str | None:
    """Error message if `--with-adapter`/`--with-hooks` name unknown values, else None.

    Must run before any filesystem mutation.
    Unvalidated, `--with-hooks=bogus` reached `_HOOK_SPECS[ev]` and escaped as a raw
    `KeyError` — *after* `init` had swapped in the scaffold and written
    `.gitignore`, leaving a store with no hooks that the command then refused to
    touch again. `--with-adapter=README.md` was worse: it injected the managed block
    into an arbitrary file, and `--remove-integrations` (which knows only
    `ADAPTER_FILENAMES`) reported "No integrations to remove." and left it there.
    """
    for flag, value, valid in (
        ("--with-hooks", getattr(args, "hooks", None), HOOK_EVENTS),
        ("--with-adapter", getattr(args, "adapter", None), ADAPTER_FILENAMES),
    ):
        requested = _resolve_tristate_list(value, list(valid)) or []
        unknown = [name for name in requested if name not in valid]
        if unknown:
            return (
                f"{flag}: unknown {'values' if len(unknown) > 1 else 'value'} "
                f"{', '.join(repr(u) for u in unknown)}. Valid: {', '.join(valid)} "
                f"(or the bare flag for all of them)."
            )
    return None


def resolve_integration_plan(root: Path, args: argparse.Namespace) -> dict:
    """Resolve which integrations to apply from flags, detection, and (TTY) prompts.

    Returns {"adapters": [...], "mcp": bool, "hooks": [...]}. On a TTY with an
    integration left unspecified, the user is asked once per integration (the
    first-run picker). Non-interactive + unspecified means "off".

    Raises ValueError on an unknown flag value. `cmd_init` checks the same thing up
    front (and exits 2), so this is the backstop for any other caller: no plan is
    ever resolved from values `apply_integrations` cannot honor.
    """
    problem = validate_integration_flags(args)
    if problem:
        raise ValueError(problem)
    detected = present_adapters(root)
    adapters = _resolve_tristate_list(getattr(args, "adapter", None), detected)
    # Bare `--with-adapter` on a project with no guidance file used to resolve
    # to a no-op (with a note recommending the flag spelling that would work).
    # But the flag IS the ask for a signpost, and `AGENTS.md` is the
    # cross-agent standard — so a green-field project gets that one file
    # created rather than nothing. Naming files explicitly still wins.
    if getattr(args, "adapter", None) == "*" and not adapters:
        adapters = [ADAPTER_FILENAMES[0]]
    hooks = _resolve_tristate_list(getattr(args, "hooks", None), list(HOOK_EVENTS))
    mcp = getattr(args, "mcp", None)  # True / False / None

    interactive = _interactive()
    undecided = adapters is None or mcp is None or hooks is None
    if interactive and undecided:
        print("Set up agent integrations so the store is actually used (each is reversible):")
        if adapters is None:
            if detected:
                adapters = (
                    detected
                    if _prompt_yes(f"  Inject the signpost block into {', '.join(detected)}?", True)
                    else []
                )
            else:
                adapters = (
                    [ADAPTER_FILENAMES[0]]
                    if _prompt_yes(
                        f"  No agent-guidance file found. Create {ADAPTER_FILENAMES[0]} "
                        "with the signpost?",
                        True,
                    )
                    else []
                )
        if mcp is None:
            mcp = _prompt_yes("  Register the MCP server in .mcp.json?", True)
        if hooks is None:
            hooks = (
                list(HOOK_EVENTS)
                if _prompt_yes("  Install Claude Code hooks (auto resume/guard/capture)?", False)
                else []
            )

    return {
        "adapters": adapters or [],
        "mcp": bool(mcp),
        "hooks": hooks or [],
    }


def apply_integrations(root: Path, plan: dict) -> dict:
    """Write the resolved integrations; return a summary of what was touched.

    A name reaches `plan["adapters"]` only two ways: detection (bare
    `--with-adapter` / the prompt, which list *existing* files only) or an
    explicit `--with-adapter=NAME`. So a name here that is not on disk was asked
    for by name, and the file is created. Guarding on `is_file()` made
    `--with-adapter=CLAUDE.md` a silent no-op in a repo without one, while
    `--print-integrations` had just promised the opposite and `doctor` went on
    recommending the command that could not help.
    """
    # `adapter_states`/`mcp_state` say what actually happened per target:
    # "updated" vs "already current". For a trust tool the distinction matters —
    # init used to print `adapter signpost -> CLAUDE.md` while CLAUDE.md was
    # byte-identical afterwards (P2-12), which reads as a lie in either direction.
    applied: dict = {"adapters": [], "adapter_states": {}, "mcp": None, "hooks": []}
    for name in plan["adapters"]:
        changed = write_adapter_block(root, name)
        applied["adapters"].append(name)
        applied["adapter_states"][name] = "updated" if changed else "already current"
    if plan["mcp"]:
        path, changed = register_mcp(root)
        applied["mcp"] = str(path)
        applied["mcp_state"] = "updated" if changed else "already current"
    if plan["hooks"]:
        install_claude_hooks(root, plan["hooks"])
        applied["hooks"] = list(plan["hooks"])
    return applied


# Files bigger than this are not scanned for a stray signpost block: the block is
# a few hundred bytes injected into a guidance file, and reading a repo's binaries
# or bundles to find one is not worth it.
ADAPTER_SCAN_MAX_BYTES = 1_000_000


def discover_adapter_blocks(root: Path) -> list[str]:
    """Every file carrying our managed signpost block, canonical or not.

    Removal used to iterate `ADAPTER_FILENAMES` alone, so a block injected into any
    other file — which `--with-adapter=<anything>` accepted before the flag was
    validated — was unreachable via the documented undo. The scan stays bounded: the
    canonical names plus the project root's own top-level files, skipping anything
    too large to plausibly be a guidance file.
    """
    names: list[str] = []
    seen: set[str] = set()
    candidates = [root / name for name in ADAPTER_FILENAMES]
    try:
        candidates += sorted(p for p in root.iterdir() if p.is_file())
    except OSError:
        pass
    for path in candidates:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:  # pragma: no cover - candidates are all under root
            continue
        if rel in seen or not path.is_file():
            continue
        seen.add(rel)
        try:
            if path.stat().st_size > ADAPTER_SCAN_MAX_BYTES:
                continue
        except OSError:
            continue
        # Lenient read: an undecodable file in the project root must
        # not take the whole removal down with it.
        text, _ = read_text_lenient(path)
        if ADAPTER_BEGIN in text:
            names.append(rel)
    return names


def remove_integrations(root: Path) -> dict:
    """Reverse every integration breadcrumbs added; leave all other content intact.

    `hooks` is `remove_claude_hooks`'s report, not a bool: hook entries that look
    like ours but carry no marker are deliberately left in place, and the caller
    has to surface them.
    """
    removed: dict = {"adapters": [], "mcp": False, "hooks": {"removed": [], "left": []}}
    for name in discover_adapter_blocks(root):
        if remove_adapter_block(root, name):
            removed["adapters"].append(name)
    removed["mcp"] = unregister_mcp(root)
    removed["hooks"] = remove_claude_hooks(root)
    return removed


# ---- crumb doctor ---------------------------------------------------------- #


def doctor_report(root: Path) -> dict:
    """Integration-health report: is memory actually wired up?"""
    memory_dir = root / MEMORY_DIRNAME
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    store = memory_dir.is_dir()
    add(
        "store",
        store,
        f"{MEMORY_DIRNAME}/ present" if store else f"no {MEMORY_DIRNAME}/ — run `crumb init`",
    )

    # Adapter blocks
    present = present_adapters(root)
    # One lenient read each: doctor used to read every adapter
    # twice and die on the first undecodable one, taking the whole report with it.
    adapter_text: dict[str, str] = {}
    unreadable: list[str] = []
    for n in present:
        adapter_text[n], problem = read_text_lenient(root / n)
        if problem:
            unreadable.append(f"{n} ({problem})")
    blocked = [n for n in present if ADAPTER_BEGIN in adapter_text[n]]
    # Size the managed block, not the host file. Measuring the file made a
    # correct install fail permanently in any repo whose CLAUDE.md is a real
    # instruction file — the check punished the very thing it asks for.
    bloated = [
        n for n in blocked if len(managed_block_text(adapter_text[n]) or "") > ADAPTER_BLOAT_CHARS
    ]
    add(
        "adapter",
        bool(blocked) and not bloated and not unreadable,
        (
            f"signpost in {', '.join(blocked)}"
            if blocked
            else (
                f"adapter files present ({', '.join(present)}) but no signpost block"
                if present
                # Naming the fix matters here: `crumb init --with-adapter` (what
                # the first-run nudge recommends) resolves to the *detected*
                # files, so in a project with none it cannot clear this check.
                else (
                    "no agent-guidance files detected — create one with "
                    f"`crumb init --with-adapter={ADAPTER_FILENAMES[0]}`"
                )
            )
        )
        + (f"; BLOATED: {', '.join(bloated)}" if bloated else "")
        + (f"; UNREADABLE: {', '.join(unreadable)}" if unreadable else ""),
    )

    # MCP registration + extra
    mcp_path = root / ".mcp.json"
    registered = False
    if mcp_path.is_file():
        try:
            registered = MCP_SERVER_NAME in (
                json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers") or {}
            )
        except (json.JSONDecodeError, OSError):
            registered = False
    sdk = _mcp_sdk_available()
    add(
        "mcp",
        registered,
        ".mcp.json registered" if registered else "not registered (`crumb mcp register`)",
    )
    add("mcp_extra", sdk, "[mcp] extra importable" if sdk else "optional [mcp] extra not installed")

    # Hooks
    hook_cmds = _installed_hook_commands(root)
    add(
        "hooks",
        bool(hook_cmds),
        f"{len(hook_cmds)} crumb hook(s) installed" if hook_cmds else "no hooks installed",
    )

    # Resume-packet staleness vs HEAD
    if store:
        packet = memory_dir / "generated" / "resume-packet.md"
        if packet.is_file():
            stale = _packet_is_stale(memory_dir, root)
            add(
                "resume_packet",
                not stale,
                "stale vs HEAD — run `crumb resume`" if stale else "fresh",
            )
        else:
            add("resume_packet", False, "not generated — run `crumb resume`")

    integrated = any(c["ok"] for c in checks if c["check"] in ("adapter", "mcp", "hooks"))
    return {"checks": checks, "integrated": integrated, "store": store}


def _installed_hook_commands(root: Path) -> list[str]:
    """The breadcrumbs hook commands present in .claude/settings.json.

    Recognized by `_hook_entry_event`, not by command text, so a hook run
    through a wrapper counts as installed — it *is* installed, and reporting "no
    hooks installed" while all three fire is worse than reporting nothing.
    """
    path = root / ".claude" / "settings.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    cmds: list[str] = []
    for arr in (data.get("hooks") or {}).values():
        if not isinstance(arr, list):
            continue
        for group in arr:
            for h in _group_entries(group):
                if _hook_entry_event(h):
                    cmds.append(str(h.get("command", "")))
    return cmds


def _packet_is_stale(memory_dir: Path, root: Path) -> bool:
    """Best-effort: True if the committed packet's inputs hash no longer matches."""
    try:
        packet = build_resume_packet(memory_dir, root)
        current = render_packet_markdown(packet)
        on_disk = (memory_dir / "generated" / "resume-packet.md").read_text(encoding="utf-8")
        return _strip_packet_volatile(current) != _strip_packet_volatile(on_disk)
    except Exception:  # pragma: no cover - defensive
        return False


# The rendered project line: `**<name>** — \`<path>\``. Machine-dependent for any
# packet written before the path went project-relative.
_PACKET_PROJECT_LINE_RE = re.compile(r"^\*\*.*\*\* — `.*`\s*$")


def _strip_packet_volatile(md: str) -> str:
    """Drop the lines that differ between machines rather than between contents.

    `generated_at:` so a pure-timestamp delta is not read as staleness, and the
    project line so a packet still carrying an absolute host path (written by an
    older version) does not read as stale on every other checkout.
    """
    return "\n".join(
        ln
        for ln in md.splitlines()
        if "generated_at:" not in ln and not _PACKET_PROJECT_LINE_RE.match(ln)
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    report = doctor_report(root)
    if args.json:
        _print_json(args, report)
    else:
        print("crumb doctor — integration health")
        for c in report["checks"]:
            mark = MARK_PASS if c["ok"] else MARK_FAIL
            print(f"  {mark} [{c['check']}] {c['detail']}")
        if report["store"] and not report["integrated"]:
            print("\n" + FIRST_RUN_NUDGE)
    # Non-zero when a store exists but nothing is wired up (the §5 finding, machine-checkable).
    return 0 if (report["integrated"] or not report["store"]) else 1


# ---- crumb hook session|guard|capture -------------------------------------- #


def _read_hook_stdin() -> dict:
    try:
        raw = sys.stdin.read()
    except OSError:
        return {}
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return {}
    # Valid JSON that isn't an object (a list, a string) is as useless to the
    # hook as malformed JSON — treat it the same.
    return payload if isinstance(payload, dict) else {}


def _hook_root(payload: dict) -> Path:
    return Path(payload.get("cwd") or os.environ.get("BREADCRUMBS_PROJECT") or Path.cwd()).resolve()


# Cheap risk patterns the keyword classifier misses (destructive shell/git ops).
# Used only to decide whether to escalate to full guard — a pure regex scan of a
# short string, no record I/O, so the common path stays well inside the hook budget.
# Store-specific trap shapes are NOT hardcoded here — they come from the
# generated/ trap-token index below.


def _prefilter_trap_hit(memory_dir: Path, action: str, files: list[str] | None) -> bool:
    """Does the action overlap the reindex-time trap-token index?

    One small generated-file read — no record walk — keeping the pre-filter's
    "cheap on the common path" promise while closing the near-miss class where a
    routine-looking command (`pytest -n auto`) matches a recorded trap that the
    keyword classifier and the destructive-op regex are both blind to. Absent or
    unreadable index ⇒ not risky (the index is rebuilt on every reindex).
    """
    p = memory_dir / "generated" / GUARD_PREFILTER_FILENAME
    try:
        idx = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(idx, dict):
        return False
    # Two specific shared tokens, mirroring the guard anti-noise floor — a single
    # generic word never escalates (§19b.8). Index tokens are re-stemmed at read
    # time: a prefilter written by an older version holds raw tokens, and _stem
    # is idempotent, so fresh and stale files compare identically.
    idx_tokens = {_stem(str(t)) for t in (idx.get("tokens") or ())}
    if len(_specific(action) & idx_tokens) >= GUARD_MIN_KEYWORD_OVERLAP:
        return True
    action_paths = _norm_files(_paths_from_text(action)) | _norm_files(files or [])
    index_paths = _norm_files(idx.get("paths") or ())
    return bool(action_paths & index_paths)


# How much of an edit's new content feeds the guard action string. Tokens are
# what matter, not prose, so a modest window is enough to let a content-level
# trap match ("flexTimeInterval", a banned API) while keeping the scoring pass
# cheap and the risk-regex scan bounded.
_HOOK_CONTENT_SNIPPET_CHARS = 400


def _hook_action_from_tool(tool: str, tool_input: dict) -> tuple[str, list[str] | None]:
    """Derive a guard action string + affected files from a PreToolUse payload.

    For file edits the action carries a bounded snippet of the *new* content
    (P0-3): with only `edit <path>` every edit of one file produced byte-identical
    guard output, and the store could never match on what the edit actually says —
    the exact signal a content-shaped trap needs.
    """
    if tool == "Bash":
        return (tool_input.get("command") or "").strip(), None
    if tool in ("Edit", "Write", "MultiEdit"):
        fp = tool_input.get("file_path") or tool_input.get("path") or ""
        if tool == "Write":
            new = tool_input.get("content") or ""
        elif tool == "MultiEdit":
            edits = tool_input.get("edits")
            parts = []
            if isinstance(edits, list):
                for e in edits:
                    if isinstance(e, dict) and e.get("new_string"):
                        parts.append(str(e["new_string"]))
            new = "\n".join(parts)
        else:
            new = tool_input.get("new_string") or ""
        snippet = " ".join(str(new).split())[:_HOOK_CONTENT_SNIPPET_CHARS]
        action = f"edit {fp}: {snippet}" if snippet else f"edit {fp}"
        return action.strip(), [fp] if fp else None
    return "", None


# Advisory-dedupe state for the PreToolUse guard, keyed by host session. Lives
# in private/ (machine-local, gitignored) because it is per-checkout runtime
# state, not memory. Best-effort: a read or write failure must never block the
# hook, and losing the file only means one repeated advisory.
_HOOK_SEEN_FILENAME = "hook-guard-seen.json"
_HOOK_SEEN_MAX_SESSIONS = 8
_HOOK_SEEN_MAX_KEYS = 200


def _hook_guard_advisory_seen(memory_dir: Path, session_id: str, key: str) -> bool:
    """True if this advisory key already fired for this session; records it if not.

    Same records + same file ⇒ say nothing after the first time (P0-2b): a
    READ_FIRST that repeats verbatim on every edit trains the agent to ignore
    the one that matters. Only advisories dedupe — PAUSE/ASK_HUMAN always fire.
    """
    path = memory_dir / "private" / _HOOK_SEEN_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    sessions = data.get("sessions")
    if not isinstance(sessions, dict):
        sessions = {}
    entry = sessions.get(session_id)
    if not isinstance(entry, dict) or not isinstance(entry.get("seen"), list):
        entry = {"seen": []}
    if key in entry["seen"]:
        return True
    entry["seen"] = (entry["seen"] + [key])[-_HOOK_SEEN_MAX_KEYS:]
    entry["updated_at"] = now_iso()
    sessions[session_id] = entry
    # Keep only the most recent sessions so the state file cannot grow unbounded.
    keep = sorted(sessions, key=lambda s: sessions[s].get("updated_at") or "", reverse=True)
    data = {"sessions": {s: sessions[s] for s in keep[:_HOOK_SEEN_MAX_SESSIONS]}}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomic(path, json.dumps(data, indent=0, sort_keys=True) + "\n")
    except Exception:  # pragma: no cover - dedupe state is best-effort
        pass
    return False


# Permission modes in which the user has already told the harness not to
# interrupt them. `bypassPermissions` (`--dangerously-skip-permissions`) and
# `dontAsk` are explicit standing instructions; re-raising a prompt inside them
# overrides a choice the user made deliberately, and a memory tool has no
# standing to do that. `acceptEdits` is NOT here: it auto-accepts *edits* only,
# so a prompt on a destructive Bash command is still the normal flow there.
#
# The harness hands every hook the current mode in `permission_mode`, which is
# exactly what the field makes possible. Nothing read it before, so
# `crumb hook guard` reinstated approval prompts for whole sessions that had
# opted out of them — the one report we have of this ended in a `sed` wrapper
# stripping the decision keys back out of our JSON, deliberately built to
# survive `pip install -U`. That is a user routing around the tool's default
# because the default was wrong.
_HOOK_NONPROMPTING_MODES = frozenset({"bypassPermissions", "dontAsk"})

# Escape hatch for anyone who wants the advisory shape unconditionally, so the
# answer is an env var rather than a wrapper that rewrites our output.
_GUARD_ADVISORY_ENV = "CRUMB_GUARD_ADVISORY"


def _hook_may_prompt(payload: dict) -> bool:
    """May this hook escalate to a permission prompt at all?

    Two independent vetoes, both the user's: the session's permission mode, and
    an explicit `CRUMB_GUARD_ADVISORY=1`. A veto never suppresses the *warning* —
    the matched records still reach the agent as `additionalContext`. It
    suppresses only the interruption, which is the part the user opted out of.
    """
    if str(os.environ.get(_GUARD_ADVISORY_ENV, "")).strip().lower() in ("1", "true", "yes", "on"):
        return False
    mode = payload.get("permission_mode")
    return not (isinstance(mode, str) and mode in _HOOK_NONPROMPTING_MODES)


def _hook_surfacing_matches(result: dict) -> list[dict]:
    """The matches worth spending the agent's context on (G2).

    A match whose only signal is shared vocabulary — no file, no tag, no title
    hit, no explicit do-not-retry, no open blocker — is what a store produces for
    *any* action phrased in its own language. `crumb guard` still returns it as
    context, because a caller who asked explicitly should see what was
    considered; the hook fires on every tool call and pays for every word, so
    there it is dropped whenever anything better is available. An advisory the
    agent sees on every command is one it learns to skim, and then it skims the
    one that mattered.

    Empty when *every* match is keyword-only — the caller decides what to do
    with that; see `_hook_guard`.
    """
    return [
        m for m in result.get("matches", []) if GUARD_SURFACING_SIGNALS & set(m.get("signals", ()))
    ]


def _hook_guard_reason(result: dict, matches: list[dict] | None = None) -> str:
    lines = [f"breadcrumbs guard: {result['verdict']} for this action."]
    for m in (result.get("matches", []) if matches is None else matches)[:3]:
        title = m.get("title") or m.get("id") or "record"
        why = m.get("reason") or ""
        lines.append(f"- {title}" + (f" ({why})" if why else ""))
    return "\n".join(lines)


def _hook_session(memory_dir: Path, root: Path) -> int:
    out: dict = {}
    if memory_dir.is_dir():
        try:
            packet = build_resume_packet(memory_dir, root)
            out = {
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": render_packet_markdown(packet),
                }
            }
        except Exception:  # pragma: no cover - never fail a session start on memory
            out = {}
    print(json.dumps(out))
    return 0


def _hook_guard(memory_dir: Path, root: Path, payload: dict) -> int:
    if not memory_dir.is_dir():
        print(json.dumps({}))
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        # A truthy non-dict tool_input crashed with a raw traceback where every
        # other malformed-payload path degrades to {}.
        tool_input = {}
    action, files = _hook_action_from_tool(payload.get("tool_name") or "", tool_input)
    if not action:
        print(json.dumps({}))
        return 0
    # Cost-aware pre-filter: pure-string classify + risk regex on the common
    # path, plus one read of the reindex-time trap-token index so
    # trap-shaped routine commands escalate too. Only a plausibly-risky action
    # escalates to full guard scoring.
    _primary, classes = classify_action(action)
    risky = (
        classes != ["routine_edit"]
        or bool(_HOOK_RISK_RE.search(action))
        or _prefilter_trap_hit(memory_dir, action, files)
    )
    if not risky:
        print(json.dumps({}))
        return 0
    result = guard(memory_dir, root, action, files=files)
    verdict = result["verdict"]
    if verdict == "PROCEED":
        print(json.dumps({}))
        return 0
    # What the agent is actually shown. A keyword-only match rides along for free
    # today: `git status` drew two advisory lines, one of them a record that
    # shares nothing with it but the word "status". Where better matches exist,
    # the weak ones are dropped; where they are all there is, they are still
    # shown — a strong keyword-only match escalating through the score band is a
    # deliberate behaviour of this tool, not something to silence from here.
    shown = _hook_surfacing_matches(result) or result.get("matches", [])
    reason = _hook_guard_reason(result, shown)
    if verdict == "READ_FIRST":
        # Dedupe within the host session: the same records surfacing for the
        # same file is information exactly once (P0-2b/P0-3). Keyed on the
        # matched record ids + the file (or the action when no file), so a new
        # record or a different file speaks again; scoped to READ_FIRST so a
        # PAUSE/ASK_HUMAN is never swallowed.
        target = (files or [None])[0] or result["action"]
        key = f"{target}|" + ",".join(sorted(m["id"] for m in shown))
        session_id = str(payload.get("session_id") or "unknown")
        try:
            if _hook_guard_advisory_seen(memory_dir, session_id, key):
                print(json.dumps({}))
                return 0
        except Exception:  # pragma: no cover - dedupe must never block the hook
            pass
        # `permissionDecision: "allow"` is not neutral — it *auto-approves* the
        # call, skipping the prompt the user would otherwise get, and its reason
        # is shown only to the user, never to the model. Emitting it on an
        # advisory verdict removed a safety gate and swallowed the warning: the
        # exact inverse of "memory informs, never decides". So
        # READ_FIRST takes no permission decision at all — the normal flow is
        # left untouched and the matched records reach the agent as context.
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": reason,
            }
        }
        print(json.dumps(out))
        return 0
    # PAUSE / ASK_HUMAN — hand the call to the human with the reason attached,
    # but only if prompting is ours to do at all.
    #
    # Note what is deliberately NOT a second condition here: blast radius.
    # Gating the prompt on `destructive` as well was tried and reverted, because
    # by the time a verdict reaches this branch it is already one of exactly two
    # things — a match whose stance is `blocking` (an attempt someone wrote with
    # an explicit *Do Not Retry Unless*), or a high-impact action class. The
    # first is an authored instruction to stop, not an inference from overlap,
    # and suppressing it would silence the one channel the schema gives an
    # author for saying "not this again". The second is blast radius already.
    # Danger belongs on the escalation side (`_decide_verdict`), where it can
    # *raise* a verdict, rather than here, where it could only ever suppress an
    # authored one.
    if _hook_may_prompt(payload):
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                # `ask`, never `deny`: memory informs; it never allows or denies
                # on its own. The human still makes the call.
                "permissionDecision": "ask",
                "permissionDecisionReason": reason,
            }
        }
        print(json.dumps(out))
        return 0
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": reason,
        }
    }
    print(json.dumps(out))
    return 0


def _work_dirty_files(files: list) -> tuple[str, ...]:
    """The dirty-file set with the memory store's own churn removed.

    Every capture rewrites the store (a new session record, handoff.md,
    current.md, the projections), so counting those paths as "work happened"
    would re-arm the Stop-hook dedupe on every firing.
    """
    return tuple(
        sorted(
            f
            for f in files
            if isinstance(f, str) and f.strip() and MEMORY_DIRNAME not in f.split("/")
        )
    )


def _hook_capture_is_redundant(memory_dir: Path, root: Path) -> bool:
    """True when nothing has moved since the newest session record.

    Claude Code's `Stop` fires every time the agent finishes responding — every
    turn, not once per session — so an unconditional capture floods `sessions/`
    with near-empty records. A firing earns a record only when the work moved:
    a different HEAD commit, or a different set of dirty working-tree files.
    """
    rec = _newest_session_record(memory_dir)
    if rec is None or rec.error:
        return False
    recorded = rec.meta.get("dirty_files")
    if not isinstance(recorded, list):
        return False
    if (rec.meta.get("commit") or "") != git_commit(root):
        return False
    return _work_dirty_files(recorded) == _work_dirty_files(git_dirty_files(root))


def _extraction_enabled(memory_dir: Path) -> bool:
    """Manifest kill switch for the Stop-hook extraction prompt (default on)."""
    manifest = load_manifest(memory_dir) or {}
    raw = str(manifest.get("extraction_prompt", "true")).strip().lower()
    return raw not in ("false", "no", "off", "0")


# The extraction prompt fires only when the ending turn produced new commits —
# a proportional trigger: chunky agent turns that landed real work get asked
# once; small interactive turns (edits with no commit) only get the silent
# snapshot. Bound mirrors the capture window's philosophy (never dump a wall).
EXTRACTION_MAX_COMMITS_SHOWN = 5


def _extraction_commits(memory_dir: Path, root: Path) -> list[str]:
    """One-line subjects for commits since the last session record.

    Empty means "do not prompt": nothing new, no git, or no prior session
    record — the first firing in a store takes the baseline snapshot silently
    instead of interrogating the agent about pre-existing history.
    """
    last = _last_session_commit(memory_dir)
    if not last:
        return []
    cur = git_commit(root)
    if cur == NO_GIT_COMMIT or cur == last:
        return []
    out = _git_out(root, "log", "--oneline", "--no-decorate", f"{last}..HEAD")
    if out is None:
        # `last` unknown to this clone (rebase / shallow fetch): HEAD still
        # moved, which is the signal — say so without a bogus range.
        return [f"(history rewritten; HEAD is now {_short_ref(cur)})"]
    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    return lines or [f"(HEAD moved to {_short_ref(cur)})"]


def _extraction_reason(commits: list[str]) -> str:
    """The block message: a concrete, one-shot instruction to persist memory.

    This is the agent-as-author moment — the request lands while the model
    still holds the session's "why", instead of relying on a standing signpost
    it read hundreds of turns ago. `capture session` is the last step, so
    completing the instruction is exactly what clears it (a re-firing Stop sees
    the fresh session record as redundant and stays silent).
    """
    shown = commits[:EXTRACTION_MAX_COMMITS_SHOWN]
    extra = len(commits) - len(shown)
    listing = "\n".join(f"  {c}" for c in shown)
    if extra > 0:
        listing += f"\n  … and {extra} more"
    # "landed", not "this turn produced": the range is HEAD-based, and the
    # workspace may be shared with other terminals/agents (P1-7) — attributing
    # someone else's commit to the agent would ask it to describe work it never
    # did. The instruction below scopes recording to the session's own work.
    return (
        f"breadcrumbs: {len(commits)} new commit(s) landed since the last recorded "
        f"session (this turn's work, or another actor's if the workspace is "
        f"shared):\n{listing}\n"
        "Before stopping, persist what the next session cannot rediscover — from "
        "this session's own work only; skip commits you did not make:\n"
        '1. A durable choice made here -> `crumb remember decision --title "…" '
        '--set Decision "…" --evidence commit <sha>`\n'
        '2. An approach tried that failed -> `crumb remember attempt --title "…" '
        '--result "…" --do-not-retry "…" --evidence commit <sha>`\n'
        '3. Something checked against reality -> `crumb verify "<subject>" '
        '--status fixed|open|regressed --evidence command "<cmd>"`\n'
        "4. A record this session contradicted -> `crumb mark-status <id> "
        'stale --reason "…"`\n'
        'Finish with `crumb capture session --next "<the next concrete action — cite '
        'a commit sha or file so the claim stays checkable>"`. '
        "Record durable facts only — routine work needs no records; if nothing "
        "durable happened, run just the final capture command."
    )


def _hook_capture_snapshot(root: Path, host_session: str | None = None) -> None:
    """The machine snapshot: the same --fast path the CLI uses (diff-stat already
    summarized). The Next Action is placeholder text (`_is_placeholder` knows
    it), so this capture cannot clobber a Next Action / Focus a human set.

    `host_session` is the harness's session id from the Stop payload. It is what
    lets the second and later firings of one session update the first firing's
    snapshot instead of stacking a new record beside it (F-6)."""
    ns = argparse.Namespace(
        project=str(root),
        json=True,
        plain=False,
        verbose=False,
        fast=True,
        next_action=HOOK_SESSION_NEXT_ACTION,
        title="session",
        set=None,
        focus=None,
        host_session=host_session,
        # A Stop-hook capture is always a machine write, so `agent` is the floor
        # here, not `unknown` — named harness when the env names one.
        agent=detect_agent(fallback="agent"),
        capture_what="session",
    )
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_capture_session(ns)
    except Exception:  # pragma: no cover - a capture failure must not block Stop
        pass


def _hook_capture(memory_dir: Path, root: Path, payload: dict) -> int:
    if not memory_dir.is_dir():
        print(json.dumps({}))
        return 0
    try:
        redundant = _hook_capture_is_redundant(memory_dir, root)
    except Exception:  # pragma: no cover - a dedupe failure must not block Stop
        redundant = False
    # A Stop firing that is itself the continuation of a blocked Stop already
    # had its extraction chance — never block twice (that is the loop). If the
    # agent captured, the fresh session record reads as redundant and we stay
    # silent; if it ignored the instruction, fall back to the machine snapshot
    # so the floor is never below plain snapshot behavior.
    host_session = str(payload.get("session_id") or "") or None
    if payload.get("stop_hook_active"):
        if not redundant:
            _hook_capture_snapshot(root, host_session)
        print(json.dumps({}))
        return 0
    if redundant:
        print(json.dumps({}))
        return 0
    if _extraction_enabled(memory_dir):
        commits = _extraction_commits(memory_dir, root)
        if commits:
            print(json.dumps({"decision": "block", "reason": _extraction_reason(commits)}))
            return 0
    _hook_capture_snapshot(root, host_session)
    print(json.dumps({}))
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    event = getattr(args, "hook_event", None)
    # Validate the event *before* reading stdin: `crumb hook` with
    # no subcommand used to block on a terminal until EOF and only then report the
    # usage error, which reads as a hang.
    if event not in HOOK_EVENTS:
        _emit_error(args, "specify: `crumb hook session|guard|capture`")
        return 2
    payload = _read_hook_stdin()
    root = _hook_root(payload)
    memory_dir = root / MEMORY_DIRNAME
    if event == "session":
        return _hook_session(memory_dir, root)
    if event == "guard":
        return _hook_guard(memory_dir, root, payload)
    return _hook_capture(memory_dir, root, payload)


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #


def get_version() -> str:
    """Resolve the distribution version.

    Installed (pipx/pip): authoritative version from package metadata.
    Source checkout (no metadata): the in-tree __version__ (single source).
    """

    def _fallback() -> str:
        from breadcrumbs import __version__

        return __version__

    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("crumb-kit")
        except PackageNotFoundError:
            return _fallback()
    except Exception:  # pragma: no cover - importlib.metadata always present on 3.8+
        return _fallback()


# Global flags live on a shared parent parser inherited by every subparser, so
# they can be passed either before or after the subcommand. The catch: argparse's
# subparser action (_SubParsersAction.__call__) parses the subcommand into a
# *fresh* namespace and copies its keys back over the parent namespace — which
# clobbers any global a user set before the subcommand (issue #3). Two-part fix:
#   1. The shared globals default to SUPPRESS, so an absent flag never lands in
#      the sub-namespace and therefore never overwrites the parent's value.
#   2. The top-level parser backfills the real defaults once, after parsing.
# Subparsers stay plain argparse.ArgumentParser (see add_subparsers below) so the
# backfill happens exactly once, at the top — never inside a sub-namespace that
# would then be copied back.
_GLOBAL_FLAG_DEFAULTS = {"project": None, "json": False, "plain": False, "verbose": False}


# One wording for every `--agent` flag. The default is deliberately *not* `human`:
# an omitted flag is an absence of evidence, so it resolves to the
# detected harness or to `unknown`, and a person asserts authorship explicitly.
_AGENT_FLAG_HELP = "{what} label (default: detected agent harness, else 'unknown')"


class _LazyVersionAction(argparse.Action):
    """`--version`, without charging every *other* command for it.

    argparse's built-in `version` action wants the finished string at parser
    construction time, so `build_parser()` called `get_version()` — which imports
    `importlib.metadata`, and with it `email`, `zipfile`, `csv`, `socket`,
    `typing`, … That was ~24 ms of a ~30 ms `build_parser()`, paid on every
    invocation including the `hook guard` pre-filter that fires on every tool
    call, for a flag almost nothing passes. Resolving the version inside
    `__call__` moves that cost to the one command that asked for it.
    """

    def __init__(
        self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None
    ):
        super().__init__(
            option_strings=option_strings, dest=dest, default=default, nargs=0, help=help
        )

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"breadcrumbs {get_version()} (record schema_version {SCHEMA_VERSION})")
        parser.exit()


class _CrumbParser(argparse.ArgumentParser):
    """An argparse parser whose usage errors lead with `CRUMB-ERROR:` (C2).

    argparse prints the usage block first and the reason last, so a caller that
    bounds output with `head` keeps the usage and drops the reason — and one that
    bounds it with `tail` keeps a line that ends in the author's own prose
    (`unrecognized arguments: --body some long text`), which reads like output,
    not like a rejection. Leading with the marker puts the fact that this failed
    on the first line either way, and `self.prog` names the exact subcommand.
    """

    def error(self, message: str):  # noqa: D102 - argparse contract
        self.exit(2, f"{ERROR_PREFIX} {self.prog}: {message}\n{self.format_usage()}")


class _BreadcrumbsParser(_CrumbParser):
    """Top-level parser that keeps global flags working in any position."""

    def parse_known_args(self, args=None, namespace=None):
        ns, argv = super().parse_known_args(args, namespace)
        for dest, default in _GLOBAL_FLAG_DEFAULTS.items():
            if not hasattr(ns, dest):
                setattr(ns, dest, default)
        return ns, argv

    def parse_args(self, args=None, namespace=None):
        """As argparse, but the leftover-argument error names the subcommand.

        argparse checks for unconsumed argv at the *top* level, so the stock
        message is prefixed `crumb:` however deep the rejected flag was — the
        caller is told a flag is unknown without being told which of twenty
        subcommands does not know it, and is then handed the top-level usage,
        which cannot list the flags the subcommand does accept.
        """
        ns, argv = self.parse_known_args(args, namespace)
        if argv:
            label = command_label(ns)
            self.exit(
                2,
                f"{ERROR_PREFIX} {label}: unrecognized arguments: {' '.join(argv)}\n"
                f"try `{label} --help` for the flags this subcommand accepts.\n",
            )
        return ns


# init
def _add_init(sub, global_parser: argparse.ArgumentParser) -> None:
    p_init = sub.add_parser(
        "init",
        parents=[global_parser],
        help="install the .project-memory/ layout into a project",
    )
    p_init.add_argument(
        "--session-tracking",
        choices=VALID_SESSION_TRACKING,
        help="session record policy (default: prompt, then 'full')",
    )
    p_init.add_argument(
        "--no-commit-generated",
        action="store_true",
        help="keep generated/*.md projections local (gitignored)",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing .project-memory/ scaffold",
    )
    # Integration flags. Tri-state: unset -> prompt on a TTY / off when
    # non-interactive; --with-* enables; --no-* disables. set_defaults keeps all three
    # at None so default `crumb init` is byte-identical to before.
    p_init.add_argument(
        "--with-adapter",
        dest="adapter",
        nargs="?",
        const="*",
        metavar="FILES",
        help="inject the signpost block into detected agent-guidance "
        "files (optional: comma-separated list)",
    )
    p_init.add_argument(
        "--no-adapter",
        dest="adapter",
        action="store_const",
        const=False,
        help="do not touch agent-guidance files",
    )
    p_init.add_argument(
        "--with-mcp",
        dest="mcp",
        action="store_const",
        const=True,
        help="register the MCP server in .mcp.json",
    )
    p_init.add_argument(
        "--no-mcp",
        dest="mcp",
        action="store_const",
        const=False,
        help="do not register the MCP server",
    )
    p_init.add_argument(
        "--with-hooks",
        dest="hooks",
        nargs="?",
        const="*",
        metavar="EVENTS",
        help="install Claude Code hooks (optional: comma list of session,guard,capture)",
    )
    p_init.add_argument(
        "--no-hooks", dest="hooks", action="store_const", const=False, help="do not install hooks"
    )
    p_init.add_argument(
        "--print-integrations",
        action="store_true",
        help="show which integrations would be applied, then exit",
    )
    p_init.add_argument(
        "--remove-integrations",
        action="store_true",
        help="reverse every breadcrumbs integration, then exit",
    )
    p_init.set_defaults(func=cmd_init, adapter=None, mcp=None, hooks=None)


# validate
def _add_validate(sub, global_parser: argparse.ArgumentParser) -> None:
    p_validate = sub.add_parser(
        "validate",
        parents=[global_parser],
        help="deterministically check the .project-memory/ store ",
    )
    p_validate.set_defaults(func=cmd_validate)


# remember decision | attempt
def _set_flag_help(rtype: str, verb: str = "set") -> str:
    """`--set` help that names the vocabulary (C1).

    The section list was reachable only through `crumb schema <type>` — which is
    excellent, and is not where anyone looks — or by being rejected. Both facts a
    caller needs (the headings, and where the full contract lives) go in the
    help text of the flag that takes them.
    """
    return (
        f"{verb} a body section (repeatable). HEADING is one of: "
        f"{', '.join(BODY_SECTIONS[rtype])}. Matching ignores case, spacing and "
        f"punctuation; anything else is kept under `## {UNSORTED_SECTION}` with a "
        f"warning. Full contract: `crumb schema {rtype}`"
    )


def _add_remember(sub, global_parser: argparse.ArgumentParser) -> None:
    p_remember = sub.add_parser(
        "remember",
        parents=[global_parser],
        help="record a durable decision or attempt",
    )
    p_remember.set_defaults(func=cmd_remember, record_type=None)
    rem_sub = p_remember.add_subparsers(dest="record_type", metavar="<type>")
    for rtype in ("decision", "attempt"):
        pr = rem_sub.add_parser(
            rtype,
            parents=[global_parser],
            help=f"record a durable {rtype}",
        )
        pr.add_argument("--title", help="record title (prompted if omitted in a TTY)")
        pr.add_argument(
            "--set",
            nargs=2,
            action="append",
            metavar=("HEADING", "TEXT"),
            help=_set_flag_help(rtype),
        )
        pr.add_argument(
            "--evidence",
            nargs=2,
            action="append",
            metavar=("TYPE", "REF"),
            help="add an evidence pointer, e.g. --evidence commit abc1234 (repeatable)",
        )
        pr.add_argument("--tags", help="comma-separated tags")
        pr.add_argument("--confidence", choices=("low", "medium", "high"))
        pr.add_argument("--privacy", choices=VALID_PRIVACY)
        pr.add_argument("--scope")
        pr.add_argument("--status", choices=VALID_STATUS)
        pr.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="record author"))
        if rtype == "attempt":
            # The fixed attempt vocabulary as named flags; each
            # overrides the matching --set heading.
            pr.add_argument("--problem", help="Problem section")
            pr.add_argument("--tried", help="Tried section")
            pr.add_argument("--result", help="Result section")
            pr.add_argument("--why", help="'Why It Failed / Succeeded' section")
            pr.add_argument(
                "--do-not-retry", dest="do_not_retry", help="'Do Not Retry Unless' section"
            )
            pr.add_argument("--related", help="'Related Records' section")
        pr.set_defaults(func=cmd_remember)


# schema introspection
def _add_schema(sub, global_parser: argparse.ArgumentParser) -> None:
    p_schema = sub.add_parser(
        "schema",
        parents=[global_parser],
        help="print the record schema contract (or a fill-in template)",
    )
    p_schema.add_argument(
        "schema_type",
        nargs="?",
        metavar="<type>",
        help="limit to one record type (decision|attempt|verification|session|idea)",
    )
    p_schema.add_argument(
        "--template",
        action="store_true",
        help="emit a copy-pasteable `crumb remember <type>` command skeleton",
    )
    p_schema.set_defaults(func=cmd_schema)


# note question|trap|idea
def _add_note(sub, global_parser: argparse.ArgumentParser) -> None:
    p_note = sub.add_parser(
        "note",
        parents=[global_parser],
        help="leave an open question, known trap, or idea for the next agent",
    )
    p_note.set_defaults(func=cmd_note, note_kind=None)
    note_sub = p_note.add_subparsers(dest="note_kind", metavar="<kind>")

    pq = note_sub.add_parser("question", parents=[global_parser], help="record an open question")
    pq.add_argument("text", nargs="?", help="the question, in one line")
    pq.add_argument("--title", help="the question (alias for the positional, as on `remember`)")
    pq.add_argument("--why", help="why it matters / what is blocked")
    pq.add_argument("--needs", help="human input | investigation | a decision")
    pq.add_argument(
        "--status",
        default="open",
        choices=VALID_QUESTION_STATUS,
        help="status (default: open); retire one later with `crumb mark-status <id> answered`",
    )
    pq.set_defaults(func=cmd_note)

    pt = note_sub.add_parser("trap", parents=[global_parser], help="record a reusable known trap")
    pt.add_argument("text", nargs="?", help="one-line trap summary")
    pt.add_argument("--title", help="trap summary (alias for the positional, as on `remember`)")
    pt.add_argument("--slug", help="short slug (derived from the summary if omitted)")
    pt.add_argument("--area", help="where this bites (files / area)")
    pt.add_argument("--symptom", help="what goes wrong")
    pt.add_argument("--why", help="the mechanism, not vibes")
    pt.add_argument("--safe", help="the safe approach to use instead")
    pt.add_argument("--verify", help="a command that proves it is OK")
    pt.set_defaults(func=cmd_note)

    pi = note_sub.add_parser("idea", parents=[global_parser], help="record a speculative idea")
    pi.add_argument("text", nargs="?", help="the idea title")
    pi.add_argument("--title", help="the idea title (alias for the positional, as on `remember`)")
    pi.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("HEADING", "TEXT"),
        help=_set_flag_help("idea"),
    )
    pi.add_argument("--tags", help="comma-separated tags")
    pi.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="note author"))
    pi.set_defaults(func=cmd_note)


# verify — record a verification result (a finding about reality)
def _add_verify(sub, global_parser: argparse.ArgumentParser) -> None:
    p_verify = sub.add_parser(
        "verify",
        parents=[global_parser],
        help="record a verification result (checked X; status fixed/open/regressed/…)",
    )
    p_verify.add_argument(
        "subject",
        nargs="?",
        default=None,
        metavar="SUBJECT",
        help="what was checked — a finding id, file, or claim (prompted if omitted in a TTY)",
    )
    p_verify.add_argument(
        "--status",
        required=True,
        choices=VALID_VERIFICATION_OUTCOME,
        help="the verification outcome",
    )
    p_verify.add_argument(
        "--method",
        choices=VALID_VERIFICATION_METHOD,
        help="how it was checked (static|runtime|test)",
    )
    p_verify.add_argument("--note", help="free-text notes / what the evidence shows")
    p_verify.add_argument(
        "--evidence",
        nargs=2,
        action="append",
        metavar=("TYPE", "REF"),
        help="add an evidence pointer, e.g. --evidence file path/to/file.py:170 (repeatable)",
    )
    p_verify.add_argument("--tags", help="comma-separated tags")
    p_verify.add_argument("--confidence", choices=("low", "medium", "high"))
    p_verify.add_argument(
        "--agent", default=None, help=_AGENT_FLAG_HELP.format(what="record author")
    )
    p_verify.set_defaults(func=cmd_verify)


# mark-status — record lifecycle mutation from the CLI
def _add_mark_status(sub, global_parser: argparse.ArgumentParser) -> None:
    p_mark = sub.add_parser(
        "mark-status",
        parents=[global_parser],
        help="change a record's, trap's or question's status, validate-gated",
    )
    p_mark.add_argument(
        "record_id",
        metavar="ID",
        help="record id (e.g. dec_20260510_markdown-source-of-truth), trap id "
        "(e.g. trap_hand-tagged-releases) or question id (e.g. q:should-we-shard) — "
        "retiring a trap or answering a question stops it raising guard",
    )
    # Positional STATUS, with `--status` accepted for the same value (C3). This
    # is the only place in the CLI where a vocabulary value is positional —
    # `crumb verify` takes the same words as `--status` — and that inconsistency
    # is the whole trap: `--status superseded` exited 2 with an argparse error
    # naming no subcommand. Accepting both costs nothing and removes the class.
    p_mark.add_argument(
        "new_status",
        metavar="STATUS",
        nargs="?",
        choices=MARK_STATUS_CHOICES,
        help=f"new status — records and traps: {', '.join(VALID_STATUS)}; "
        f"questions: {', '.join(VALID_QUESTION_STATUS)}",
    )
    p_mark.add_argument(
        "--status",
        dest="status_flag",
        default=None,
        choices=MARK_STATUS_CHOICES,
        help="the same value as the positional STATUS, spelled as `crumb verify` spells it",
    )
    p_mark.add_argument(
        "--reason", default="", help="why the status changed (recorded as a trailing comment)"
    )
    p_mark.add_argument(
        "--superseded-by",
        dest="superseded_by",
        default=None,
        metavar="ID",
        help="the replacing record's id (required by validate when marking superseded)",
    )
    p_mark.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="author"))
    p_mark.set_defaults(func=cmd_mark_status)


# traps — what the always-on context costs, and what can be retired
def _add_traps(sub, global_parser: argparse.ArgumentParser) -> None:
    p_traps = sub.add_parser(
        "traps",
        parents=[global_parser],
        help="list known traps with their staleness and context cost",
    )
    p_traps.add_argument(
        "--stale",
        nargs="?",
        type=int,
        const=TRAPS_STALE_DAYS_DEFAULT,
        default=None,
        metavar="DAYS",
        help=f"only traps not confirmed in DAYS (default {TRAPS_STALE_DAYS_DEFAULT}); "
        "never-confirmed traps always qualify",
    )
    p_traps.add_argument(
        "--status", choices=VALID_STATUS, default=None, help="only traps with this status"
    )
    p_traps.add_argument(
        "--confirm",
        metavar="ID",
        default=None,
        help=f"stamp a trap's `- {TRAP_CONFIRMED_KEY}:` bullet with today's date",
    )
    p_traps.set_defaults(func=cmd_traps)


# retitle — repair a record whose title carries no information
def _add_retitle(sub, global_parser: argparse.ArgumentParser) -> None:
    p_retitle = sub.add_parser(
        "retitle",
        parents=[global_parser],
        help="rewrite a record's title (id, slug and filename are left alone)",
    )
    p_retitle.add_argument(
        "record_id",
        metavar="ID",
        help="record id, e.g. ses_20260904_session-8",
    )
    p_retitle.add_argument("title", metavar="TITLE", help="the new title")
    p_retitle.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="author"))
    p_retitle.set_defaults(func=cmd_retitle)


# prune — explicit retention for machine session snapshots
def _add_prune(sub, global_parser: argparse.ArgumentParser) -> None:
    p_prune = sub.add_parser(
        "prune",
        parents=[global_parser],
        help="delete old machine session snapshots (keeps human handoffs + the newest N)",
    )
    p_prune.add_argument(
        "what",
        choices=("sessions",),
        help="what to prune (only `sessions` exists today)",
    )
    p_prune.add_argument(
        "--keep",
        type=int,
        default=PRUNE_SESSIONS_KEEP_DEFAULT,
        metavar="N",
        help=f"newest sessions never pruned (default: {PRUNE_SESSIONS_KEEP_DEFAULT})",
    )
    p_prune.add_argument(
        "--dry-run", action="store_true", help="list what would be deleted; delete nothing"
    )
    p_prune.set_defaults(func=cmd_prune)


# reindex — explicit projection refresh (mutations reindex automatically)
def _add_reindex(sub, global_parser: argparse.ArgumentParser) -> None:
    p_reindex = sub.add_parser(
        "reindex",
        parents=[global_parser],
        help="rebuild generated/ projections from the canonical records",
    )
    p_reindex.set_defaults(func=cmd_reindex)


# capture session
def _add_capture(sub, global_parser: argparse.ArgumentParser) -> None:
    p_capture = sub.add_parser(
        "capture",
        parents=[global_parser],
        help="capture a work session (git-prefilled); updates handoff + current",
    )
    p_capture.set_defaults(func=_capture_dispatch, capture_what=None)
    cap_sub = p_capture.add_subparsers(dest="capture_what", metavar="<what>")
    p_session = cap_sub.add_parser(
        "session",
        parents=[global_parser],
        help="record session end; auto-fills work/files/commands from git",
    )
    p_session.add_argument(
        "--fast", action="store_true", help="git snapshot + --next only; no prompts, no LLM"
    )
    p_session.add_argument(
        "--next", dest="next_action", help="the Next Action (required on --fast)"
    )
    p_session.add_argument("--title", help="session topic (default: 'session')")
    p_session.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("HEADING", "TEXT"),
        help=_set_flag_help("session", verb="override"),
    )
    p_session.add_argument(
        "--include-memory",
        dest="include_memory",
        action="store_true",
        help=f"keep {MEMORY_DIRNAME}/ paths in dirty_files (default: excluded — every "
        "capture rewrites the store, and in a shared tree it also sees other sessions')",
    )
    p_session.add_argument(
        "--focus", help="Current Focus for handoff/current (default: keep the previous focus)"
    )
    p_session.add_argument(
        "--agent", default=None, help=_AGENT_FLAG_HELP.format(what="session author")
    )
    p_session.set_defaults(func=cmd_capture_session)


# resume
def _add_resume(sub, global_parser: argparse.ArgumentParser) -> None:
    p_resume = sub.add_parser(
        "resume",
        parents=[global_parser],
        help="print a bounded resume packet with computed staleness",
    )
    p_resume.add_argument(
        "--fast",
        action="store_true",
        help="git snapshot + current focus + next action + staleness only (print-only)",
    )
    p_resume.add_argument(
        "--stale-days",
        type=int,
        default=None,
        metavar="N",
        help=f"{STALE_DAYS_HELP}; aged questions/decisions raise a staleness warning",
    )
    p_resume.add_argument(
        "--task",
        default=None,
        metavar="TEXT",
        help="resume FOR this task: scope likely-files to matching records; "
        "a task-scoped packet prints only and does not overwrite the committed snapshot",
    )
    p_resume.set_defaults(func=cmd_resume)


# search — deterministic exact/keyword/tag/file lookup
def _add_search(sub, global_parser: argparse.ArgumentParser) -> None:
    p_search = sub.add_parser(
        "search",
        parents=[global_parser],
        help="deterministic keyword/tag/file search over records (no embeddings)",
    )
    p_search.add_argument(
        "query", nargs="?", default="", help="search text (optional with filters)"
    )
    p_search.add_argument(
        "--type",
        choices=("decision", "attempt", "verification", "idea", "trap", "question"),
        help="narrow the corpus to one record type ('idea' is searchable but never "
        "reaches a guard verdict)",
    )
    p_search.add_argument(
        "--status",
        help="filter by record status (e.g. active, superseded; "
        "for verifications: the outcome, e.g. open/fixed)",
    )
    p_search.add_argument("--tag", help="filter by tag/component")
    p_search.add_argument("--file", help="filter by file path referenced in a record")
    p_search.add_argument(
        "--stale-days",
        type=int,
        default=None,
        metavar="N",
        help=f"{STALE_DAYS_HELP}; aged records score lower",
    )
    p_search.set_defaults(func=cmd_search)


# guard — guard-before-action: warn before repeating a mistake
def _add_guard(sub, global_parser: argparse.ArgumentParser) -> None:
    p_guard = sub.add_parser(
        "guard",
        parents=[global_parser],
        help="warn before an action that conflicts with memory (§11)",
    )
    p_guard.add_argument("action", help='the proposed action, e.g. "rewrite the auth middleware"')
    p_guard.add_argument(
        "--files",
        nargs="*",
        default=None,
        metavar="PATH",
        help="explicit file paths the action will touch (sharpens file-overlap scoring)",
    )
    p_guard.add_argument(
        "--stale-days",
        type=int,
        default=None,
        metavar="N",
        help=f"{STALE_DAYS_HELP}; aged records score lower",
    )
    p_guard.set_defaults(func=cmd_guard)


# audit — heuristic stale/unsafe/bloated detection (does NOT gate validate)
def _add_audit(sub, global_parser: argparse.ArgumentParser) -> None:
    p_audit = sub.add_parser(
        "audit",
        parents=[global_parser],
        help="heuristic health/safety audit: stale, unsafe (secrets), instruction-like, drift, bloat",
    )
    p_audit.add_argument(
        "--stale-days",
        type=int,
        default=None,
        metavar="N",
        help=f"{STALE_DAYS_HELP}; aged questions/decisions become warn findings",
    )
    p_audit.set_defaults(func=cmd_audit)


# scan-secrets — the secret sub-check as a standalone command
def _add_scan_secrets(sub, global_parser: argparse.ArgumentParser) -> None:
    p_scan = sub.add_parser(
        "scan-secrets",
        parents=[global_parser],
        help="scan committed memory for secret-like strings (run before committing memory)",
        description=(
            "Scan committed memory for secret-like strings. A structured credential "
            "shape (AWS key, PEM block, bearer token, …) exits non-zero; the "
            "high-entropy heuristic warns without blocking. Add one regex per line to "
            f"{MEMORY_DIRNAME}/{CRUMBIGNORE_FILENAME} to silence a shape this project "
            "has already decided is not a secret."
        ),
    )
    p_scan.set_defaults(func=cmd_scan_secrets)


# mcp serve|register — surface the optional MCP server from the CLI
def _add_mcp(sub, global_parser: argparse.ArgumentParser) -> None:
    p_mcp = sub.add_parser(
        "mcp",
        parents=[global_parser],
        help="run or register the optional breadcrumbs MCP server",
    )
    p_mcp.set_defaults(func=cmd_mcp, mcp_what=None)
    mcp_sub = p_mcp.add_subparsers(dest="mcp_what", metavar="<what>")
    p_mcp_serve = mcp_sub.add_parser(
        "serve",
        parents=[global_parser],
        help="run the MCP server over stdio (needs the [mcp] extra)",
    )
    p_mcp_serve.set_defaults(func=cmd_mcp, mcp_what="serve")
    p_mcp_register = mcp_sub.add_parser(
        "register",
        parents=[global_parser],
        help="add the breadcrumbs server to .mcp.json (preserves other servers)",
    )
    p_mcp_register.set_defaults(func=cmd_mcp, mcp_what="register")
    p_mcp_doctor = mcp_sub.add_parser(
        "doctor",
        parents=[global_parser],
        help="report MCP wiring: [mcp] extra, .mcp.json registration",
    )
    p_mcp_doctor.set_defaults(func=cmd_mcp, mcp_what="doctor")


# doctor — integration health
def _add_doctor(sub, global_parser: argparse.ArgumentParser) -> None:
    p_doctor = sub.add_parser(
        "doctor",
        parents=[global_parser],
        help="report whether memory is actually wired up (adapter/mcp/hooks/packet)",
    )
    p_doctor.set_defaults(func=cmd_doctor)


# hook session|guard|capture — harness translation layer
def _add_hook(sub, global_parser: argparse.ArgumentParser) -> None:
    p_hook = sub.add_parser(
        "hook",
        parents=[global_parser],
        help="Claude Code hook entry points (read stdin payload, emit hook JSON)",
    )
    p_hook.set_defaults(func=cmd_hook, hook_event=None)
    hook_sub = p_hook.add_subparsers(dest="hook_event", metavar="<event>")
    for ev, _help in (
        ("session", "SessionStart: emit the resume packet as additional context"),
        ("guard", "PreToolUse: cost-aware guard verdict for the proposed tool call"),
        ("capture", "Stop: snapshot a session record"),
    ):
        ph = hook_sub.add_parser(ev, parents=[global_parser], help=_help)
        ph.set_defaults(func=cmd_hook, hook_event=ev)


# Every subcommand's parser, built on demand. `build_parser()` used to
# construct all of these up front — ~5 ms before argparse had even looked at
# argv — on every invocation, including the `hook guard` pre-filter that fires
# on every tool call and usually returns `{}` without touching memory. `main()`
# now names the one command argv asks for and only that parser is built; the
# full set is still built for `--help`, for an unrecognised command (so the
# "invalid choice" message lists everything), and for any caller that wants the
# whole parser. Insertion order is the order `--help` lists them in.
_SUBCOMMAND_BUILDERS: dict[str, object] = {
    "init": _add_init,
    "validate": _add_validate,
    "remember": _add_remember,
    "schema": _add_schema,
    "note": _add_note,
    "verify": _add_verify,
    "mark-status": _add_mark_status,
    "retitle": _add_retitle,
    "traps": _add_traps,
    "prune": _add_prune,
    "reindex": _add_reindex,
    "capture": _add_capture,
    "resume": _add_resume,
    "search": _add_search,
    "guard": _add_guard,
    "audit": _add_audit,
    "scan-secrets": _add_scan_secrets,
    "mcp": _add_mcp,
    "doctor": _add_doctor,
    "hook": _add_hook,
}


def build_parser(only: str | None = None) -> argparse.ArgumentParser:
    """The `crumb` parser. `only` builds just that one subcommand's parser.

    `only` is an optimisation, never a behaviour change: pass a name from
    `_SUBCOMMAND_BUILDERS` and the returned parser handles exactly that command;
    pass nothing (every caller that needs help text, or an unknown command) and
    the full parser is built as before.
    """
    # Parent parser holds the global flags so every subcommand inherits them.
    # default=SUPPRESS is load-bearing — see _BreadcrumbsParser above.
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="machine-readable JSON output",
    )
    global_parser.add_argument(
        "--plain",
        action="store_true",
        default=argparse.SUPPRESS,
        help="plain-text output (no decoration)",
    )
    global_parser.add_argument(
        "--verbose", action="store_true", default=argparse.SUPPRESS, help="verbose output"
    )
    global_parser.add_argument(
        "--project", metavar="PATH", default=argparse.SUPPRESS, help="project root (default: cwd)"
    )

    parser = _BreadcrumbsParser(
        prog="crumb",
        description="Breadcrumbs — a repo-local ledger of durable project state you and your agents can follow back.",
        parents=[global_parser],
    )
    parser.add_argument(
        "--version",
        action=_LazyVersionAction,
        help="show version and record schema_version, then exit",
    )
    # Subparsers are _CrumbParser (not _BreadcrumbsParser) so the global backfill
    # runs only once, at the top level — never in a copied-back sub-namespace —
    # while every usage error still leads with the CRUMB-ERROR marker.
    sub = parser.add_subparsers(dest="command", metavar="<command>", parser_class=_CrumbParser)
    for name, add_subcommand in _SUBCOMMAND_BUILDERS.items():
        if only is None or name == only:
            add_subcommand(sub, global_parser)

    return parser


def _capture_dispatch(args: argparse.Namespace) -> int:
    """`crumb capture` with no subcommand -> guidance."""
    if getattr(args, "capture_what", None) is None:
        _emit_error(args, "specify what to capture: `crumb capture session`")
        return 2
    return cmd_capture_session(args)


# Global flags that take a separate value, so the argv pre-scan below doesn't
# mistake `--project guard` for the `guard` subcommand. Matched by prefix,
# because argparse accepts long-option abbreviations (`--proj guard …`).
_GLOBAL_VALUE_FLAGS = ("--project",)


def _consumes_next_token(token: str) -> bool:
    return any(flag.startswith(token) for flag in _GLOBAL_VALUE_FLAGS)


def requested_command(argv: list[str]) -> str | None:
    """The subcommand `argv` names, or None if it names none.

    A cheap pre-scan so `main()` can build one subparser instead of twenty. The
    subcommand is argparse's first positional, so this skips options (and the one
    global flag that takes a separate value) and returns the first bare token —
    but only if it is a name we know. An unknown token returns None, which builds
    the full parser, so argparse's "invalid choice" message still lists every
    command.
    """
    it = iter(argv)
    for token in it:
        if token == "--":
            # argparse already rejects `crumb -- <command>`; hand it the full
            # parser so that error still lists every choice.
            return None
        if token.startswith("-"):
            if _consumes_next_token(token):
                next(it, None)
            continue
        return token if token in _SUBCOMMAND_BUILDERS else None
    return None


def main(argv: list[str] | None = None) -> int:
    configure_output()
    parser = build_parser(requested_command(sys.argv[1:] if argv is None else list(argv)))
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except KeyboardInterrupt:
        # Ctrl+C at a prompt aborts the command. 130 is the shell
        # convention for SIGINT; the message goes to stderr so `--json` output is
        # never half a document followed by a traceback.
        print("\naborted.", file=sys.stderr)
        return 130
    except (OSError, ValueError) as exc:
        # Expected, user-facing failures (missing template/package, permissions,
        # unrepresentable values) surface as a clean error + nonzero exit rather
        # than a raw traceback. Programming errors still propagate.
        _emit_error(args, str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
