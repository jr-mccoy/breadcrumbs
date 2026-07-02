#!/usr/bin/env python3
"""crumb — Breadcrumbs CLI.

Phase 1 surface: the `init` command plus the global argparse skeleton that
later phases (validate, remember, capture, resume, guard, audit) bolt onto.

Phase 7 (packaging): this is the package entry point (``breadcrumbs.cli``),
exposed as the ``crumb`` console script. The ``crumb.py`` shim at the
repo root re-exports it so source-checkout use (``python crumb.py ...``)
and the test suite keep working unchanged. Templates ship as package data under
``breadcrumbs/templates/`` so ``init`` finds them post-install without any
repo-relative path.

Design constraints (see docs/ and the build plan):
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
from datetime import datetime
from pathlib import Path

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
# authoritative (read from package metadata in get_version); keep this in sync
# with `version` in pyproject.toml for source-tree runs where no metadata exists.
_FALLBACK_VERSION = "0.1.6"

# Non-git fallback sentinels (build plan §22 Q5, resolved this phase).
# Used everywhere git-derived fields cannot be populated.
NO_GIT_BRANCH = "(no-git)"
NO_GIT_COMMIT = "(no-git)"

# Markers delimiting the block Breadcrumbs manages inside the project .gitignore.
# Anything between them is rewritten by `init`; everything else is preserved.
GITIGNORE_BEGIN = "# >>> breadcrumbs managed block (managed by `crumb init`) >>>"
GITIGNORE_END = "# <<< breadcrumbs managed block <<<"

VALID_SESSION_TRACKING = ("full", "distillate")

# Record vocabularies (plan §7).
VALID_STATUS = (
    "active",
    "superseded",
    "stale",
    "disputed",
    "rejected",
    "quarantined",
)
VALID_PRIVACY = ("repo-safe", "local-private", "secret-prohibited")

# Directory name -> record type (plan §6 taxonomy).
DIR_TYPES = {
    "decisions": "decision",
    "attempts": "attempt",
    "sessions": "session",
    "ideas": "idea",
    "verifications": "verification",
}

# Record type -> id prefix (plan §7 "Record identity").
TYPE_PREFIX = {
    "decision": "dec",
    "attempt": "att",
    "idea": "idea",
    "session": "ses",
    "trap": "trap",
    "question": "q",
    "verification": "ver",
}

# Verification outcome vocabulary (review F1). The record-level `status` stays the
# lifecycle value (active/superseded/…); the *finding about reality* lives in the
# `outcome` frontmatter field so it never collides with the lifecycle status.
VALID_VERIFICATION_OUTCOME = (
    "fixed",
    "open",
    "regressed",
    "not_applicable",
    "inconclusive",
)
# Verification method vocabulary (how the subject was checked).
VALID_VERIFICATION_METHOD = ("static", "runtime", "test")

# Singleton core files that must exist (plan §16.2).
CORE_FILES = ("current.md", "handoff.md", "open-questions.md", "known-traps.md")

# Frontmatter keys every durable directory record must carry (plan §16.3).
# id/slug are derived from the filename (§7), so they are not required here.
REQUIRED_RECORD_KEYS = ("title", "status", "created_at", "privacy")

# Filename of a directory record: <YYYY-MM-DD>-<slug>.md
RECORD_STEM_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)$")

# Marker every generated projection carries (plan §3, §16.12).
GENERATED_MARKER = "GENERATED PROJECTION"

# Session "Next Action or convergence" markers (plan §16.10).
SESSION_DONE_MARKERS = ("converged", "session complete", "no next action", "done")


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def write_text_atomic(path: Path, text: str) -> None:
    """Write text via tmp-file + rename in the destination directory.

    A plain `write_text` interrupted mid-write leaves a truncated record that
    validate then reports as corrupt (review #3 R24); `os.replace` is atomic on
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


def now_iso() -> str:
    """Local time, ISO-8601, timezone-aware (e.g. 2026-06-25T14:30:00-05:00)."""
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def is_git_repo(root: Path) -> bool:
    """True if `root` is inside a git work tree."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


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
        # flip generated projections to local-only, but keep the explainer README
        lines.append(f"{MEMORY_DIRNAME}/generated/*.md")
        lines.append(f"!{MEMORY_DIRNAME}/generated/README.md")
    if session_tracking == "distillate":
        # sessions stay local; only promoted decisions/attempts are committed
        lines.append(f"{MEMORY_DIRNAME}/sessions/")
    lines.append(GITIGNORE_END)
    return "\n".join(lines) + "\n"


def rewrite_managed_block(
    path: Path, begin: str, end: str, block: str | None
) -> None:
    """Insert, replace, or remove a fenced managed block in a text file.

    Idempotent. `block` (when given) must contain the `begin` and `end` marker
    lines; only the region between the markers is rewritten, so surrounding user
    content is preserved. Pass `block=None` (or "") to strip the managed block,
    leaving everything else intact. The comment style lives in the markers, so the
    same surgery works for `.gitignore` (`#`) and Markdown adapters (`<!-- -->`).
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
            return  # nothing to remove
        sep = "" if (not existing or existing.endswith("\n")) else "\n"
        prefix = (existing + sep + "\n") if existing.strip() else ""
        new_content = prefix + block

    path.write_text(new_content, encoding="utf-8")


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
        raise ValueError(
            f"expected a JSON object at {path}, found {type(data).__name__}"
        )
    mutate(data)
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
    if not sys.stdin.isatty():
        return non_interactive_default
    prompt = (
        "Session-tracking policy:\n"
        "  [full]       commit dated session records (good for solo multi-device)\n"
        "  [distillate] keep sessions/ local; commit only decisions/attempts (lean team repo)\n"
        "Choose [full/distillate] (default: full): "
    )
    try:
        answer = input(prompt).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return non_interactive_default
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

    # Standalone integration operations: they act on an existing project and never
    # scaffold, so they run before the "store already exists" guard below.
    if getattr(args, "remove_integrations", False):
        removed = remove_integrations(root)
        if args.json:
            print(json.dumps({"removed": removed}, indent=2))
        else:
            touched = removed["adapters"] or removed["mcp"] or removed["hooks"]
            print("Removed breadcrumbs integrations:" if touched else "No integrations to remove.")
            if removed["adapters"]:
                print(f"  adapter blocks: {', '.join(removed['adapters'])}")
            if removed["mcp"]:
                print("  .mcp.json: breadcrumbs server entry removed")
            if removed["hooks"]:
                print("  .claude/settings.json: crumb hooks removed")
        return 0

    if getattr(args, "print_integrations", False):
        plan = resolve_integration_plan(root, args)
        if args.json:
            print(json.dumps({"would_apply": plan}, indent=2))
        else:
            print("Integrations that would be applied:")
            print(f"  adapter signpost -> {', '.join(plan['adapters']) or '(none)'}")
            print(f"  MCP register     -> {'yes' if plan['mcp'] else 'no'}")
            print(f"  Claude hooks     -> {', '.join(plan['hooks']) or '(none)'}")
        return 0

    if memory_dir.exists() and not args.force:
        # Integrations-only mode (review #3 R2): wiring an agent into an
        # *existing* store must never require --force — --force replaces the
        # scaffold and destroys every record. When any integration flag is
        # given explicitly, apply just those and leave the store untouched.
        integrations_requested = any(
            getattr(args, k, None) is not None for k in ("adapter", "mcp", "hooks")
        )
        if integrations_requested:
            plan = resolve_integration_plan(root, args)
            applied = apply_integrations(root, plan)
            if args.json:
                print(json.dumps({"store": "existing", "integrations": applied}, indent=2))
            else:
                print(f"{MEMORY_DIRNAME}/ already present — store left untouched.")
                print("Applied integrations:")
                print(f"  adapter signpost -> {', '.join(applied['adapters']) or '(none)'}")
                print(f"  MCP register     -> {'yes' if applied['mcp'] else 'no'}")
                print(f"  Claude hooks     -> {', '.join(applied['hooks']) or '(none)'}")
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

    # Bootstrap agent integrations (review §5/§7). Resolution prompts on a TTY when
    # unspecified and is a silent no-op non-interactively, so default `crumb init`
    # behavior is unchanged. Every edit is fenced/reversible (`--remove-integrations`).
    plan = resolve_integration_plan(root, args)
    applied = apply_integrations(root, plan)

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
    if not git_present:
        summary["git_notice"] = (
            f"no git repo detected; git-derived record fields will use sentinels "
            f"branch={NO_GIT_BRANCH!r}, commit={NO_GIT_COMMIT!r}, dirty_files=[]"
        )

    _emit_init_summary(args, summary)
    return 0


def _emit_init_summary(args: argparse.Namespace, summary: dict) -> None:
    if args.json:
        print(json.dumps(summary, indent=2))
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
            print(f"    adapter signpost:            {', '.join(integ['adapters'])}")
        if integ.get("mcp"):
            print(f"    MCP registered:              {integ['mcp']}")
        if integ.get("hooks"):
            print(f"    Claude hooks:                {', '.join(integ['hooks'])}")
    else:
        print("\n" + FIRST_RUN_NUDGE)
    if not summary["git_repo"]:
        print(f"\nNotice: {summary['git_notice']}")
    if args.verbose:
        print("\nNext: `crumb resume` to load context; `crumb doctor` to check wiring.")


def _emit_error(args: argparse.Namespace, message: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps({"error": message}, indent=2))
    else:
        print(f"error: {message}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Frontmatter parser (stdlib-only subset of YAML, plan §7 / §18 Phase 1)
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
# Schema convention vs published JSON Schema (plan §22 Q1): resolved for now as
# *convention-in-code* — these deterministic checks ARE the schema. A published
# JSON Schema is deferred until the format stabilizes during dogfood.


class FrontmatterError(ValueError):
    """Raised when a record's frontmatter is malformed (plan §16.3)."""


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
        # value containing both quote kinds round-trips (review #3 R3). Content
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
            raise FrontmatterError(
                f"tabs are not allowed for indentation (use spaces): {line!r}"
            )
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
            raise FrontmatterError(
                f"tabs are not allowed for indentation (use spaces): {raw!r}"
            )
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
    body = "\n".join(lines[close + 1:])
    return meta, body


# --------------------------------------------------------------------------- #
# Record identity (plan §7 "Record identity") — filename-canonical
# --------------------------------------------------------------------------- #

def derive_identity(stem: str, rtype: str) -> tuple[str, str] | None:
    """From a record filename stem `<YYYY-MM-DD>-<slug>`, compute (id, slug).

    Returns None if the stem doesn't match the canonical pattern (caller flags it).
    """
    m = RECORD_STEM_RE.match(stem)
    if not m:
        return None
    y, mo, d, slug = m.groups()
    prefix = TYPE_PREFIX.get(rtype, rtype)
    rid = f"{prefix}_{y}{mo}{d}_{slug}"
    return rid, slug


# --------------------------------------------------------------------------- #
# Record model + loader (plan §6, §20.5)
# --------------------------------------------------------------------------- #

_SECTION_RE = re.compile(r"^##\s+(.*)$")


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
        """Split the body into {heading: text} on `## ` headings (reused by resume/guard)."""
        out: dict[str, str] = {}
        current: str | None = None
        buf: list[str] = []
        for line in self.body.splitlines():
            m = _SECTION_RE.match(line)
            if m:
                if current is not None:
                    out[current] = "\n".join(buf).strip()
                current = m.group(1).strip()
                buf = []
            elif current is not None:
                buf.append(line)
        if current is not None:
            out[current] = "\n".join(buf).strip()
        return out


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
# Field population helpers (plan §7 table) — derive + default halves
# --------------------------------------------------------------------------- #
# Phase 3's writers reuse these; Phase 3 adds the prompted half (title/body).

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
    return r.stdout.strip()


def git_branch(root: Path) -> str:
    if not is_git_repo(root):
        return NO_GIT_BRANCH
    out = _git_out(root, "rev-parse", "--abbrev-ref", "HEAD")
    if out:
        return out
    # An unborn HEAD (fresh repo, no commits yet) fails rev-parse but still has
    # a real branch name — read it so records don't pair `branch: (no-git)` with
    # populated dirty_files (review #3 R24).
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
    "n": 0x0A, "t": 0x09, "r": 0x0D, '"': 0x22, "\\": 0x5C,
    "a": 0x07, "b": 0x08, "f": 0x0C, "v": 0x0B,
}


def _unquote_git_path(path: str) -> str:
    """Decode git's C-style quoted path form back to the real path (review #3 R21).

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


def git_dirty_files(root: Path) -> list[str]:
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
    return files


def current_user() -> str:
    return os.environ.get("USER") or os.environ.get("USERNAME") or "unknown"


def derive_fields(project_root: Path, agent: str = "human") -> dict:
    """Auto-derived frontmatter fields (clock + git + environment, plan §7)."""
    root = Path(project_root)
    now = now_iso()
    return {
        "created_at": now,
        "updated_at": now,
        "created_by": current_user(),
        "agent": agent,
        "project": derive_project_name(root),
        "branch": git_branch(root),
        "commit": git_commit(root),
        "dirty_files": git_dirty_files(root),
    }


def default_fields() -> dict:
    """Defaulted, overridable frontmatter fields (constants, plan §7)."""
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
# Manifest loader (reads what Phase 1 wrote)
# --------------------------------------------------------------------------- #

def load_manifest(memory_dir: Path) -> dict | None:
    """Parse the flat `key: value` manifest written by `init`. None if absent."""
    path = Path(memory_dir) / "manifest.yml"
    if not path.is_file():
        return None
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, _, val = stripped.partition(":")
        val = val.strip()
        if len(val) >= 2 and val[0] in "\"'" and val[-1] == val[0]:
            val = val[1:-1]  # unquote so `schema_version: "1"` compares as `1`
        else:
            # Strip an inline comment only at a whitespace boundary — a bare `#`
            # inside a value (e.g. `project: my#proj`) is content, not a comment
            # (review #3 R24).
            val = re.split(r"\s+#", val, 1)[0].strip()
        out[key.strip()] = val
    return out


# --------------------------------------------------------------------------- #
# validate (plan §16.1–14) — fully deterministic; NO heuristic content scanning
# --------------------------------------------------------------------------- #

def _finding(check: str, status: str, path: str | None, message: str) -> dict:
    return {"check": check, "status": status, "path": path, "message": message}


def run_validate(memory_dir: Path) -> list[dict]:
    """Run the deterministic validation checks; return a list of findings.

    Every finding is {check, status: pass|fail, path, message}. Heuristic content
    scanning (secrets, instruction-like text) is intentionally absent — that lives
    in `audit` (plan §16.14 note).
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

    # 16.2 — required core files exist.
    for name in CORE_FILES:
        if (memory_dir / name).is_file():
            findings.append(_finding("core-files", "pass", name, "present"))
        else:
            findings.append(_finding("core-files", "fail", name, "required core file missing"))

    # Load durable records once for the record-level checks (16.3–10).
    records = load_records(memory_dir)
    seen_ids: dict[str, str] = {}

    for rec in records:
        rel = str(rec.path.relative_to(memory_dir))

        # 16.3 — valid frontmatter (parses + required keys present).
        if rec.error:
            findings.append(_finding("frontmatter", "fail", rel, f"malformed frontmatter: {rec.error}"))
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
                    "filename does not match <YYYY-MM-DD>-<slug>.md; id/slug underivable",
                )
            )
        else:
            rid, slug = ident
            is_duplicate = rid in seen_ids
            if is_duplicate:
                findings.append(
                    _finding("identity", "fail", rel, f"duplicate id {rid!r} (also {seen_ids[rid]})")
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
                _finding("status", "fail", rel, f"invalid status {status!r} (allowed: {', '.join(VALID_STATUS)})")
            )

        # 16.6 — superseded requires superseded_by.
        if status == "superseded" and rec.meta.get("superseded_by") in (None, "", []):
            findings.append(_finding("superseded", "fail", rel, "status superseded but superseded_by is empty"))

        # 16.7 / 16.8 — privacy placement and prohibition.
        privacy = rec.meta.get("privacy")
        if privacy is not None and privacy not in VALID_PRIVACY:
            # A typo'd value (e.g. "secret-prohibitted") must not silently slip
            # past the exact-match leak gate below — flag the out-of-vocab value.
            findings.append(
                _finding("privacy", "fail", rel,
                         f"invalid privacy {privacy!r} (allowed: {', '.join(VALID_PRIVACY)})")
            )
        if privacy == "secret-prohibited":
            findings.append(
                _finding("privacy", "fail", rel, "privacy: secret-prohibited must not be stored in memory")
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

        # 16.9b — verifications carry a subject and a valid outcome (review F1).
        if rec.rtype == "verification":
            subj = rec.meta.get("subject")
            # A non-string subject (e.g. a hand-edited YAML list) is a finding,
            # not a crash (review #3 R16).
            if not (isinstance(subj, str) and subj.strip()):
                findings.append(
                    _finding("verification", "fail", rel,
                             "verification has no subject"
                             if subj in (None, "")
                             else f"verification subject must be a string, got {type(subj).__name__}")
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
            # Word-boundary match (review #3 R17): a raw substring test let
            # "done" match "abandoned", false-passing the convergence check.
            has_done = any(
                re.search(rf"\b{re.escape(mark)}\b", body_l)
                for mark in SESSION_DONE_MARKERS
            )
            if not (has_next or has_done):
                findings.append(
                    _finding("session", "fail", rel, "session record lacks a '## Next Action' or convergence/done marker")
                )

    # 16.11 — handoff has branch, commit, next action, stale conditions.
    handoff = memory_dir / "handoff.md"
    if handoff.is_file():
        try:
            htext = handoff.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            # A finding, not a crash (review #3 R16).
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
            findings.append(_finding("handoff", "fail", "handoff.md", f"missing: {', '.join(missing_h)}"))
        else:
            findings.append(_finding("handoff", "pass", "handoff.md", "branch/commit/next action/stale present"))

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
                # A finding, not a crash (review #3 R16).
                findings.append(_finding("generated", "fail", rel, f"unreadable file: {exc}"))
                continue
            if GENERATED_MARKER in head:
                findings.append(_finding("generated", "pass", rel, "carries generated-projection marker"))
            else:
                findings.append(
                    _finding("generated", "fail", rel, f"generated file lacks the '{GENERATED_MARKER}' marker")
                )

    # 16.12b — projection freshness (review F3): a generated projection stamped
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
        _finding("adapters", "pass", None, "adapter/signpost files are not loaded as canonical records")
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
        print(
            json.dumps(
                {
                    "ok": not fails,
                    "passed": len(passes),
                    "failed": len(fails),
                    "findings": findings,
                },
                indent=2,
            )
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
            print(f"  ✗ [{f['check']}] {loc}: {f['message']}")
        if args.verbose:
            print("\nPassed checks:")
            for f in passes:
                loc = f["path"] or "-"
                print(f"  ✓ [{f['check']}] {loc}: {f['message']}")
        return 1

    print(f"validate: OK — {len(passes)} checks passed, 0 problems.")
    if args.verbose:
        for f in passes:
            loc = f["path"] or "-"
            print(f"  ✓ [{f['check']}] {loc}: {f['message']}")
    return 0


# --------------------------------------------------------------------------- #
# Capture half — record writer, `remember`, `capture session` (Phase 3)
# --------------------------------------------------------------------------- #
#
# Design constraint: the capture budget (plan §2.7/§7/§23). A routine
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
    # Ideas are speculative proposals (review §6.6 write-surface). Kept lean so
    # `crumb note idea` stays low-friction; not subject to the §16.9 evidence rule.
    "idea": [
        "Idea",
        "Motivation",
        "Sketch",
        "Open Questions",
    ],
    # Verifications record a finding about reality — "I checked X; here is its
    # state" (review F1). subject/outcome/method live in frontmatter (so search
    # and the resume packet can filter on them); the body carries the narrative.
    "verification": [
        "Subject",
        "Outcome",
        "Method",
        "Evidence",
        "Notes",
    ],
}

# Named flags for the fixed attempt section vocabulary (review §6.2/§8): expose the
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
            # (review #3 R3 — the old quote-flip silently truncated on re-read
            # when a value contained both quote kinds).
            return "'" + s.replace("'", "''") + "'"
        return f'"{s}"'
    return s


def _render_list_items(key: str, v: list) -> list[str]:
    """Render a block list under `key`, supporting the shapes the parser accepts.

    `_parse_list` produces scalars and one-level {key: scalar} maps for *any*
    key, so the renderer must handle both everywhere — not just scalars on
    generic keys and maps on `evidence` (review #3 R3: the old asymmetry
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
    """Render the §8 body for `rtype`, filling provided sections; stub the rest."""
    out: list[str] = []
    for heading in BODY_SECTIONS[rtype]:
        out.append(f"## {heading}")
        content = (sections.get(heading) or "").strip()
        out.append(content if content else _EMPTY_SECTION)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


# ---- slug + identity ------------------------------------------------------- #

def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    s = re.sub(r"-{2,}", "-", s)
    return s or "untitled"


def _unique_record_path(directory: Path, date: str, slug: str) -> tuple[Path, str]:
    """Pick a non-colliding `<date>-<slug>.md` (append -2, -3, … on same-day clash)."""
    candidate = directory / f"{date}-{slug}.md"
    if not candidate.exists():
        return candidate, slug
    i = 2
    while True:
        s2 = f"{slug}-{i}"
        candidate = directory / f"{date}-{s2}.md"
        if not candidate.exists():
            return candidate, s2
        i += 1


# ---- the writer ------------------------------------------------------------ #

def _canonical_heading(rtype: str, heading: str) -> str:
    for canon in BODY_SECTIONS[rtype]:
        if canon.lower() == heading.lower():
            return canon
    raise ValueError(
        f"unknown section {heading!r} for {rtype}; valid: {', '.join(BODY_SECTIONS[rtype])}"
    )


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
    agent: str = "human",
    extra: dict | None = None,
) -> tuple[Path, dict]:
    """Assemble + write a durable record; return (path, frontmatter dict).

    Frontmatter is auto-derived (§7) + defaulted + the caller's prompted fields.
    `updated_at == created_at`. Identity is recomputed from the final filename so
    id/slug/filename always agree. `extra` carries type-specific frontmatter keys
    (e.g. a verification's subject/outcome/method, review F1) — rendered in
    canonical order when known to FRONTMATTER_ORDER, else appended.
    """
    derived = derive_fields(project_root, agent=agent)
    defaults = default_fields()
    date = derived["created_at"][:10]
    directory = Path(memory_dir) / TYPE_DIR[rtype]
    directory.mkdir(parents=True, exist_ok=True)
    path, slug = _unique_record_path(directory, date, slugify(title))

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
    return [
        f for f in run_validate(memory_dir) if f["status"] == "fail" and f["path"] == rel
    ]


# ---- record lookup + status mutation (shared by MCP `memory_mark_status`) --- #

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
    agent: str = "human",
    superseded_by: str | None = None,
) -> dict:
    """Change a durable record's `status`, gated by `validate` (§16.6).

    Reuses parse/render frontmatter + the same validate gate as `remember`, so
    there is one source of write-behavior. Returns a small result dict. The edit
    is reverted if it would leave the record invalid (e.g. `superseded` without
    `superseded_by`), and an error is returned instead. `superseded_by` points
    a superseding record when marking `superseded` (review #3 R25 — this is the
    supersede flow the docs reference).
    """
    memory_dir = Path(memory_dir)
    if status not in VALID_STATUS:
        return {"ok": False, "error": f"invalid status {status!r}; valid: {', '.join(VALID_STATUS)}"}

    rec = find_record_by_id(memory_dir, rid)
    if rec is None:
        return {"ok": False, "error": f"no record with id {rid!r}"}

    original = rec.path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(original)
    prev = meta.get("status")
    meta["status"] = status
    meta["updated_at"] = now_iso()
    if superseded_by:
        meta["superseded_by"] = superseded_by
    # The reason is recorded as a trailing, non-instruction comment (data, §15).
    # A literal `-->` inside the reason would terminate the comment early and
    # leak the remainder as content (review #3 R24) — neutralize it.
    reason = (reason or "").replace("-->", "-- >")
    note = f"<!-- status: {prev} -> {status} ({reason}) by {agent} at {meta['updated_at']} -->"
    try:
        rendered = render_frontmatter(meta)
    except ValueError as exc:
        return {"ok": False, "id": rid, "error": f"cannot re-render frontmatter: {exc}"}
    # Fail-closed round-trip check (review #3 R3): the parser accepts a wider
    # grammar than the renderer can emit, so refuse to write a rendering the
    # parser would read back differently instead of silently corrupting the
    # record (and having validate certify the corruption).
    reparsed, _ = parse_frontmatter(rendered + "\n")
    if reparsed != meta:
        drifted = sorted(
            k for k in set(meta) | set(reparsed) if meta.get(k) != reparsed.get(k)
        )
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
    # Reindex-on-write (review F2): a status flip can drop a record from / add it
    # back to the active set, so the projections must follow.
    reindex_projections(memory_dir)
    return {"ok": True, "id": rid, "path": str(rec.path), "from": prev, "to": status}


# ---- input helpers --------------------------------------------------------- #

def _interactive() -> bool:
    return sys.stdin.isatty()


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


def _collect_set_sections(rtype: str, set_pairs: list[list[str]] | None) -> dict[str, str]:
    sections: dict[str, str] = {}
    for pair in set_pairs or []:
        heading = _canonical_heading(rtype, pair[0])
        sections[heading] = pair[1]
    return sections


# ---- remember decision / attempt ------------------------------------------ #

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
    try:
        sections = _collect_set_sections(rtype, args.set)
    except ValueError as exc:
        _emit_error(args, str(exc))
        return 2
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
            sections.setdefault(heading, input(f"{heading}: ").strip())

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
                f"a {rtype} needs evidence or low confidence (validate §16.9): "
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

    # Reindex-on-write (review F2): keep generated/ in step with the new record.
    reindex_projections(memory_dir, root)

    summary = {
        "created": str(path),
        "id": meta["id"],
        "type": rtype,
        "slug": meta["slug"],
        "confidence": meta["confidence"],
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Recorded {rtype}: {meta['id']}")
        print(f"  file: {path}")
        if meta["confidence"] == "low" and not meta["evidence"]:
            print("  note: no evidence; confidence set to low.")
    return 0


# ---- schema introspection (review §6.2/§8) --------------------------------- #

def record_schema() -> dict:
    """The full record-contract as data, so an agent reads it once (review §6.2).

    Pure projection of the existing contract constants — no memory dir required.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "record_types": {
            rtype: {"body_sections": list(sections)}
            for rtype, sections in BODY_SECTIONS.items()
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
        return "\n".join([
            "crumb verify 'WHAT WAS CHECKED (finding id / file / claim)' \\",
            "  --status fixed   # fixed|open|regressed|not_applicable|inconclusive \\",
            "  --method static  # static|runtime|test \\",
            "  --evidence file path/to/file.py:LINE \\",
            "  --note 'what the evidence shows'",
        ])
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
        print(json.dumps(schema, indent=2))
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
        print(f"  {name+':':12} " + ", ".join(vals))
    print("\nRule: " + schema["rules"]["evidence_or_low_confidence"])
    print("\nTip: `crumb schema --template <type>` prints a fill-in command skeleton.")
    return 0


# ---- note (question / trap / idea) — review §6.6 write-surface ------------- #

NOTE_KINDS = ("question", "trap", "idea")


# The exact placeholder lines the templates seed — anchored so a *user* line that
# merely resembles them (e.g. "_No fix for the flaky suite yet._") is never
# silently deleted on append (review #3 R22).
_TEMPLATE_PLACEHOLDER_LINES = frozenset({
    "_No open questions yet._",
    "_No known traps yet._",
})


def _append_md_block(path: Path, block: str) -> None:
    """Append a `## ` block to a singleton markdown file (open-questions/known-traps).

    The templates seed a `_No … yet._` placeholder line; the first real block drops
    it, later blocks append after the existing content. Idempotency is the caller's
    concern (notes are additive by nature).
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    kept = [
        ln for ln in text.splitlines() if ln.strip() not in _TEMPLATE_PLACEHOLDER_LINES
    ]
    head = "\n".join(kept).rstrip()
    write_text_atomic(path, (head + "\n\n" if head else "") + block.rstrip() + "\n")


def _sanitize_note_text(value) -> str:
    """Flatten note text/field values to one safe line (review #3 R22).

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


def _trap_block(summary: str, *, slug=None, area=None, symptom=None, why=None,
                safe=None, verify=None) -> str:
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
    return "\n".join(lines)


# Machine-readable trap-token index consumed by the PreToolUse hook's cheap risk
# pre-filter (review #3 R9). Lives under generated/ (rebuilt on every reindex,
# never canonical, skipped by the secret scan like the rest of generated/).
GUARD_PREFILTER_FILENAME = "guard-prefilter.json"


def _build_guard_prefilter(memory_dir: Path) -> dict:
    """Specific tokens + path tokens from traps and do-not-retry attempts.

    This is what lets `crumb hook guard` escalate a trap-shaped but
    routine-looking command (`pytest -n auto`) to full guard scoring without
    hardcoding any particular trap in a regex and without record I/O on the
    common hook path — the near-miss class that motivated hooks in review #1.
    """
    tokens: set[str] = set()
    paths: set[str] = set()
    for trap in load_traps(memory_dir):
        text = trap["heading"] + "\n" + (trap.get("body") or "")
        tokens |= _specific(text)
        paths |= _paths_from_text(text)
    for rec in active_attempts(memory_dir):
        if _attempt_has_do_not_retry(rec):
            text = (rec.meta.get("title") or "") + "\n" + rec.sections.get(
                "Do Not Retry Unless", ""
            )
            tokens |= _specific(text)
            paths |= _paths_from_text(text)
    return {"tokens": sorted(tokens), "paths": sorted(paths)}


def reindex_projections(memory_dir: Path, project_root: Path | None = None) -> bool:
    """Rebuild the generated/ projections from the canonical records (review F2).

    Called after every canonical mutation (remember/note/verify/mark-status/
    capture session, and their MCP equivalents) so the static projections never
    silently desync from
    the records — the drift the review caught on the MCP write path. The live
    resume packet always recomputes; this keeps the *file* a consumer might trust
    (the committed snapshot, a human reading generated/) in step with it.

    Best-effort by default: a refresh failure must never fail the write that
    triggered it. `project_root` defaults to the store's parent (memory lives at
    <root>/.project-memory). Returns True iff a projection was written.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root) if project_root is not None else memory_dir.parent
    try:
        packet = build_resume_packet(memory_dir, project_root, stale_days=STALE_AGE_DAYS)
        gen = memory_dir / "generated"
        gen.mkdir(parents=True, exist_ok=True)
        write_text_atomic(gen / "resume-packet.md", render_packet_markdown(packet))
        # Guard pre-filter index (review #3 R9): a token/path index over traps and
        # do-not-retry attempts, so the PreToolUse hook can spot trap-shaped
        # *routine* commands with one small-file read instead of walking records.
        write_text_atomic(
            gen / GUARD_PREFILTER_FILENAME,
            json.dumps(_build_guard_prefilter(memory_dir), indent=0, sort_keys=True) + "\n",
        )
        return True
    except Exception:  # pragma: no cover - defensive; never block a write on a projection
        return False


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
    agent: str = "human",
) -> dict:
    """Write an open-question / known-trap / idea and refresh projections (review §6.6).

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
        # comment-marker-neutralized before they touch the file (review #3 R22).
        text = _sanitize_note_text(text)
        fields = {
            k: (_sanitize_note_text(v) if isinstance(v, str) else v)
            for k, v in fields.items()
        }

    if kind == "question":
        path = memory_dir / "open-questions.md"
        if any(q["question"] == text for q in load_open_questions(memory_dir)):
            return {"ok": False, "error": f"question already recorded: {text!r}"}
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        _append_md_block(
            path,
            _question_block(text, why=fields.get("why"), needs=fields.get("needs"),
                            status=fields.get("status")),
        )
        if not any(q["question"] == text for q in load_open_questions(memory_dir)):
            write_text_atomic(path, before)  # revert
            return {"ok": False, "error": "appended question did not parse back; reverted"}
        result = {"ok": True, "kind": "question", "ref": text, "path": str(path)}

    elif kind == "trap":
        path = memory_dir / "known-traps.md"
        slug = fields.get("slug") or slugify(text)
        marker = f"trap_{slug}:".lower()
        # A duplicate heading would shadow the earlier block in every dict-based
        # reader, leaving its body unreachable (review #3 R22) — refuse instead.
        if any(b["heading"].lower().startswith(marker) for b in load_traps(memory_dir)):
            return {
                "ok": False,
                "error": f"trap trap_{slug} already exists; pass a distinct slug "
                "(--slug / fields.slug) to record a separate trap",
            }
        before = path.read_text(encoding="utf-8") if path.exists() else ""
        _append_md_block(
            path,
            _trap_block(text, slug=slug, area=fields.get("area"),
                        symptom=fields.get("symptom"), why=fields.get("why"),
                        safe=fields.get("safe"), verify=fields.get("verify")),
        )
        if not any(b["heading"].lower().startswith(marker) for b in load_traps(memory_dir)):
            write_text_atomic(path, before)  # revert
            return {"ok": False, "error": "appended trap did not parse back; reverted"}
        result = {"ok": True, "kind": "trap", "ref": f"trap_{slug}", "path": str(path)}

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

    else:
        return {"ok": False, "error": f"unknown note kind {kind!r}; use {', '.join(NOTE_KINDS)}"}

    _refresh_resume_packet(memory_dir, project_root)
    return result


def cmd_note(args: argparse.Namespace) -> int:
    kind = getattr(args, "note_kind", None)
    if kind not in NOTE_KINDS:
        _emit_error(args, f"specify a note kind: `crumb note {'|'.join(NOTE_KINDS)}`")
        return 2

    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    fields: dict = {}
    tags: list[str] | None = None
    if kind == "question":
        fields = {"why": args.why, "needs": args.needs, "status": args.status}
    elif kind == "trap":
        fields = {
            "slug": args.slug, "area": args.area, "symptom": args.symptom,
            "why": args.why, "safe": args.safe, "verify": args.verify,
        }
    else:  # idea
        try:
            fields = {"sections": _collect_set_sections("idea", args.set)}
        except ValueError as exc:
            _emit_error(args, str(exc))
            return 2
        tags = _split_tags(args.tags)

    result = note(memory_dir, root, kind, args.text or "", fields=fields, tags=tags,
                  agent=getattr(args, "agent", "human"))
    if not result.get("ok"):
        _emit_error(args, result.get("error", "note failed"))
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Noted {kind}: {result.get('id') or result.get('ref')}")
        print(f"  file: {result['path']}")
    return 0


# ---- verify (review F1) ---------------------------------------------------- #

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
    agent: str = "human",
) -> dict:
    """Record a verification result — a finding about reality (review F1).

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
            "error": "verification rejected by validate: "
            + "; ".join(f["message"] for f in fails),
        }

    reindex_projections(memory_dir, project_root)
    return {
        "ok": True,
        "id": meta["id"],
        "subject": subject,
        "outcome": status,
        "method": method,
        "confidence": meta["confidence"],
        "path": str(path),
    }


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
        agent=getattr(args, "agent", "human"),
    )
    if not result.get("ok"):
        _emit_error(args, result.get("error", "verify failed"))
        return 1

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Verified {result['subject']}: {result['outcome']}")
        print(f"  file: {result['path']}")
        if result["confidence"] == "low":
            print("  note: no evidence; confidence set to low.")
    return 0


# ---- mark-status (review #3 R25) ------------------------------------------- #

def cmd_mark_status(args: argparse.Namespace) -> int:
    """CLI surface over `set_record_status` (already exposed via MCP).

    README/docs described marking records `disputed`/`stale`/`superseded`, but
    the only writer was the MCP tool — closing that gap gives the plain-file
    workflow the same lifecycle mutation (review #3 R25).
    """
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    result = set_record_status(
        memory_dir,
        args.record_id,
        args.new_status,
        args.reason or "",
        agent=getattr(args, "agent", "human"),
        superseded_by=args.superseded_by,
    )
    if not result.get("ok"):
        _emit_error(args, result.get("error", "status change failed"))
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Marked {result['id']}: {result['from']} -> {result['to']}")
        print(f"  file: {result['path']}")
    return 0


# ---- capture session ------------------------------------------------------- #

def _last_session_commit(memory_dir: Path) -> str | None:
    recs = load_records(memory_dir, types=("session",))
    if not recs:
        return None
    recs = sorted(recs, key=lambda r: (_dt_sort_key(r.meta.get("created_at")), r.stem))
    commit = recs[-1].meta.get("commit")
    if commit in (None, "", NO_GIT_COMMIT):
        return None
    return commit


# git's canonical empty-tree object — diff base when the window reaches the root commit.
_GIT_EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


def _summarize_diffstat(shortstat: str | None) -> str:
    """Condense `git diff --shortstat` into one line: 'N files changed, +X/-Y'.

    Inlining the full per-file `--stat` bloats committed session records and can
    trip the secret scanner on path-shaped tokens (review §6.1); a counts-only
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


def _git_prefill(root: Path, since: str | None) -> dict[str, str]:
    """Pre-fill Work Completed / Files Touched / Commands from git (plan §8).

    With a prior-session `since` commit, the window is `since..HEAD`. Without one,
    the window is the last 20 commits (Files Touched diffs from the parent of the
    oldest commit in that window, or the empty tree if that reaches the root).
    """
    if not is_git_repo(root):
        return {
            "Work Completed": "_(no git history available)_",
            "Files Touched": "_(no git history available)_",
            "Commands / Verification": _EMPTY_SECTION,
        }
    # Validate the since-ref; if bad, fall back to recent history.
    if since and _git_out(root, "rev-parse", "--verify", f"{since}^{{commit}}") is None:
        since = None

    if since:
        log = _git_out(root, "log", "--oneline", "--no-decorate", f"{since}..HEAD")
        base: str | None = since
    else:
        log = _git_out(root, "log", "--oneline", "--no-decorate", "-n", "20")
        rev_list = _git_out(root, "rev-list", "--max-count=20", "HEAD")
        base = None
        if rev_list:
            oldest = rev_list.splitlines()[-1]
            parent = _git_out(root, "rev-parse", "--verify", f"{oldest}^")
            if parent:
                base = parent
            elif _git_out(root, "rev-parse", "--is-shallow-repository") == "true":
                # In a shallow clone the oldest visible commit is the shallow
                # boundary, not the root — diffing from the empty tree would
                # record the entire repo as "Files Touched" (review #3 R15).
                # Diff from the boundary commit instead: bounded, slightly
                # under-counting (its own changes are excluded) rather than
                # wildly over-counting.
                base = oldest
            else:
                base = _GIT_EMPTY_TREE

    shortstat = _git_out(root, "diff", "--shortstat", base, "HEAD") if base else None

    work = "\n".join(f"- {line}" for line in log.splitlines()) if log else "_(no new commits)_"
    files = _summarize_diffstat(shortstat)
    return {
        "Work Completed": work,
        "Files Touched": files,
        "Commands / Verification": _EMPTY_SECTION,
    }


def cmd_capture_session(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    manifest = load_manifest(memory_dir) or {}
    tracking = manifest.get("session_tracking", "full")

    since = _last_session_commit(memory_dir)
    prefill = _git_prefill(root, since)

    # Manual section overrides.
    try:
        overrides = _collect_set_sections("session", args.set)
    except ValueError as exc:
        _emit_error(args, str(exc))
        return 2

    sections: dict[str, str] = dict(prefill)
    sections.update(overrides)

    next_action = args.next_action

    if not args.fast:
        # Interactive narrative confirmation (only the parts not supplied).
        if _interactive():
            print("Captured from git:")
            print("  Work Completed:\n" + sections.get("Work Completed", ""))
            print("  Files Touched:\n" + sections.get("Files Touched", ""))
            for heading in ("Starting Context", "Decisions Made", "Attempts / Failures", "Open Questions"):
                if heading not in overrides:
                    val = input(f"{heading} (enter to skip): ").strip()
                    if val:
                        sections[heading] = val
            if next_action is None:
                next_action = input("Next Action (required): ").strip()

    if next_action:
        sections["Next Action"] = next_action

    # Next Action is required for a valid session record (§16.10).
    if not (sections.get("Next Action") or "").strip():
        _emit_error(
            args,
            "a session needs a Next Action: pass --next \"...\" (required on --fast)",
        )
        return 2

    title = args.title or "session"
    path, meta = write_record(memory_dir, root, "session", title, sections, agent=args.agent)

    fails = _validate_new_file(memory_dir, path)
    if fails:
        path.unlink()
        _emit_error(args, "new session failed validation: " + "; ".join(f["message"] for f in fails))
        return 1

    # Refresh handoff + current (plan §8, §10).
    focus = args.focus or sections.get("Next Action", "")
    recently = sections.get("Work Completed", "")
    update_handoff(memory_dir, meta["branch"], meta["commit"], focus, sections["Next Action"])
    update_current(memory_dir, focus, recently)
    # Reindex-on-write (review #3 R1): capture mutates three packet inputs (the
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
    }
    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print(f"Captured session: {meta['id']}")
        print(f"  file:    {path}")
        print(f"  handoff: updated")
        print(f"  current: updated")
        if tracking == "distillate":
            print("  note: session_tracking=distillate — sessions/ stays local (gitignored);")
            print("        promote durable items with `crumb remember` to commit them.")
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
    the first heading (preamble) and duplicate headings as separate entries
    (review #3 R14). Fence-aware (review #3 R4): a `## ` line inside a ``` / ~~~
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

    Fence-aware (review #3 R4). Duplicate headings are merged (bodies joined)
    rather than last-wins, so no body silently disappears from the dict view
    (review #3 R14).
    """
    sections: dict[str, str] = {}
    for heading, content in split_md_ordered(text)[1]:
        if heading in sections and content:
            existing = sections[heading]
            sections[heading] = (existing + "\n\n" + content).strip() if existing else content
        elif heading not in sections:
            sections[heading] = content
    return sections


def _is_placeholder(text: str) -> bool:
    """True for empty content, the `<...>` template stubs, or `_(...)_` notes.

    A `<...>` autolink URL (contains `://`) is real content, not a stub. The
    `_(...)_` italic form is what the capture prefill emits when there is nothing
    to report (e.g. `_(no new commits)_`) — treating it as a placeholder keeps it
    from clobbering a previously meaningful section.
    """
    t = text.strip()
    if not t:
        return True
    if t.startswith("<") and t.endswith(">") and "://" not in t:
        return True
    if t.startswith("_(") and t.endswith(")_"):
        return True
    return False


# Preamble lines the updaters themselves (re)generate — everything else found
# before the first `## ` is user content and must survive a rewrite (review #3 R14).
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
# resume — bounded, paste-anywhere packet + computed staleness (Phase 4)
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
# load_open_questions / parse_handoff_meta) are the reusable surface Phase 5's
# `guard` ranks against — keep them deterministic and side-effect-free.

# Hard token ceiling for the packet (§12: "3,000 to 5,000 tokens").
TOKEN_BUDGET_MAX = 5000

# Default aged-unresolved threshold in days (§12; configurable via --stale-days).
STALE_AGE_DAYS = 21

# Per-section item caps applied before budget trimming (keeps 100s of records bounded).
SECTION_CAPS = {
    "active_decisions": 15,
    "failed_attempts": 15,
    "known_traps": 12,
    "open_questions": 12,
    "likely_files": 20,
    "verification": 12,
    "verifications": 12,
    # Warnings are capped too (review #3 R8): every aged decision/question emits
    # a warning, so a neglected store could blow the token bound through the one
    # section the trimmer never touched.
    "warnings": 20,
}

# Order in which sections give up items when the packet is over budget
# (first listed = trimmed first = least load-bearing). Project / Current Focus /
# Next Action are never trimmed; warnings are trimmed only after every
# substantive section is empty, so the hard token bound holds (review #3 R8).
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
    """Chronologically comparable key for an ISO timestamp string (review #3 R23).

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


# ---- section accessors (reused by Phase 5 guard) --------------------------- #

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


def _strip_html_comments(text: str) -> str:
    """Drop `<!-- ... -->` regions so template example blocks never leak into a packet."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _md_blocks(path: Path, head_predicate) -> list[dict]:
    """Split a plain-markdown file on `## ` and keep blocks whose heading matches.

    HTML-comment regions (the template's `<!-- format suggestion -->` examples) are
    stripped first so commented-out sample headings are never mistaken for records.
    """
    if not path.is_file():
        return []
    text = _strip_html_comments(path.read_text(encoding="utf-8"))
    blocks: list[dict] = []
    for head, body in split_md_sections(text).items():
        if head_predicate(head):
            blocks.append({"heading": head, "body": body})
    return blocks


def load_traps(memory_dir: Path) -> list[dict]:
    """Trap blocks from known-traps.md (each `## trap_<slug>: <summary>`)."""
    return _md_blocks(
        Path(memory_dir) / "known-traps.md",
        lambda h: h.lower().startswith("trap"),
    )


def load_open_questions(memory_dir: Path) -> list[dict]:
    """Parse `## Q: <question>` blocks into {question, opened, status, body}."""
    out: list[dict] = []
    for block in _md_blocks(
        Path(memory_dir) / "open-questions.md", lambda h: h.lower().startswith("q:")
    ):
        opened = status = None
        for line in block["body"].splitlines():
            m = re.match(r"\s*-\s*opened\s*:\s*(.+)", line, re.I)
            if m:
                opened = m.group(1).strip()
            m = re.match(r"\s*-\s*status\s*:\s*(.+)", line, re.I)
            if m:
                status = m.group(1).strip().lower()
        out.append(
            {
                "question": block["heading"][2:].strip(),
                "opened": opened,
                "status": status or "open",
                "body": block["body"],
            }
        )
    return out


def parse_handoff_meta(text: str) -> dict:
    """Pull branch / commit / updated_at from the handoff header lines.

    Template placeholder values (`<branch>`, `<YYYY-MM-DDTHH:mm:ssZ>`, …) are
    treated as absent (review #3 R19): a store that has never been captured must
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

def compute_staleness(
    root: Path,
    handoff_meta: dict,
    decisions: list[Record],
    attempts: list[Record],
    questions: list[dict],
    stale_days: int,
) -> list[str]:
    """All computed staleness/risk warnings (§12, §15). Order: primary first."""
    warnings: list[str] = []
    cur_branch = git_branch(root)
    detached = is_git_repo(root) and cur_branch == "HEAD"

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
        warnings.append(("⚠ " if cold else "") + "handoff is " + ", ".join(parts) + ".")
    elif handoff_meta.get("updated_at"):
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
    ):
        warnings.append(
            f"branch mismatch: handoff was written on '{hb}' but HEAD is on '{cur_branch}'."
        )
    if not detached and cur_branch != NO_GIT_BRANCH:
        mism = [
            f"{r.meta.get('id', r.stem)} (on '{r.meta.get('branch')}')"
            for r in (decisions + attempts)
            if r.meta.get("branch")
            and r.meta.get("branch") not in (NO_GIT_BRANCH, None, "")
            and r.meta.get("branch") != cur_branch
        ]
        if mism:
            shown = ", ".join(mism[:5])
            extra = f" (+{len(mism) - 5} more)" if len(mism) > 5 else ""
            warnings.append(
                f"{len(mism)} record(s) written on other branches than "
                f"'{cur_branch}': {shown}{extra}."
            )

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
                warnings.append(
                    f"{r.meta.get('id', r.stem)} expired on {exp} ({a} days ago)."
                )
        if r.meta.get("confidence") == "low":
            warnings.append(
                f"{r.meta.get('id', r.stem)} is low-confidence — verify before relying on it."
            )

    return warnings


# ---- packet assembly ------------------------------------------------------- #

def _inputs_hash(memory_dir: Path) -> str:
    """Short content hash of the canonical inputs (so audit/Phase 6 can spot drift)."""
    h = hashlib.sha256()
    # manifest.yml is a packet input (project name, policies), so it is part of
    # the hash — otherwise the freshness check certifies a packet built from a
    # since-edited manifest (review #3 R7).
    paths = [Path(memory_dir) / f for f in CORE_FILES]
    paths.append(Path(memory_dir) / "manifest.yml")
    for d in DIR_TYPES:
        dd = Path(memory_dir) / d
        if dd.is_dir():
            paths.extend(sorted(dd.glob("*.md")))
    for p in sorted(set(paths)):
        if p.is_file():
            h.update(p.read_bytes())
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

    When `task` is given (the "resume for THIS task" path, review F4/F6) the packet
    is scoped to it: `requested_task` is echoed and `likely_files` is derived from
    the records that actually match the task instead of the store-global default
    that misdirects on off-domain work. With no task, behavior is unchanged.
    """
    memory_dir = Path(memory_dir)
    manifest = load_manifest(memory_dir) or {}

    current_sections = split_md_sections(
        (memory_dir / "current.md").read_text(encoding="utf-8")
    ) if (memory_dir / "current.md").is_file() else {}
    handoff_text = (
        (memory_dir / "handoff.md").read_text(encoding="utf-8")
        if (memory_dir / "handoff.md").is_file()
        else ""
    )
    handoff_sections = split_md_sections(handoff_text)
    handoff_meta = parse_handoff_meta(handoff_text)

    decisions = active_decisions(memory_dir)
    attempts = active_attempts(memory_dir)
    traps = load_traps(memory_dir)
    questions = load_open_questions(memory_dir)
    verifications = active_verifications(memory_dir)

    # Project snapshot (git is the live source; handoff metadata is advisory).
    dirty = git_dirty_files(root)
    project = {
        "name": manifest.get("project") or derive_project_name(root),
        "path": str(root),
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
            "inputs_hash": _inputs_hash(memory_dir),
            "generated_at": now_iso(),
        },
        "fast": bool(fast),
        "stale_days": stale_days,
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
        "open_questions": [q["question"] for q in questions if (q.get("status") or "open") == "open"],
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
        "warnings": compute_staleness(root, handoff_meta, decisions, attempts, questions, stale_days),
        "omitted": {},
        "omitted_reason": {},
    }

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

    # Task scoping (review F4/F6): when a task is named, replace the store-global
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
    """Active verification records, actionable outcome first (review F1).

    open/regressed/inconclusive (still need attention) sort ahead of
    not_applicable/fixed (resolved), each group newest-first via active_records.
    """
    order = {o: i for i, o in enumerate(
        ("open", "regressed", "inconclusive", "not_applicable", "fixed")
    )}
    recs = active_records(memory_dir, "verification")
    return sorted(recs, key=lambda r: order.get(r.meta.get("outcome") or "open", 99))


def _task_scoped_files(
    memory_dir: Path, root: Path, task: str, *, stale_days: int
) -> tuple[list[str], str | None]:
    """Files relevant to `task`, from records that match it (review F4).

    Reuses the deterministic `search` scoring rather than inventing a second
    relevance notion. Returns (files, note); note is set only when nothing matched.
    """
    matches, by_id = search(memory_dir, root, task, stale_days=stale_days)
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
_FAST_DROP = ("active_decisions", "failed_attempts", "known_traps", "open_questions", "likely_files", "verification", "verifications")


def _bound_packet(packet: dict, *, fast: bool) -> None:
    """Apply --fast pruning, per-section caps, then trim to the token budget."""
    if fast:
        for key in _FAST_DROP:
            packet[key] = []
        packet["omitted"] = {}
        packet["omitted_reason"] = {}

    # Per-section caps (record how many we hid, and why). Applied in --fast mode
    # too: warnings survive the fast prune and must stay bounded (review #3 R8).
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
    out += [
        "## Project",
        f"**{proj['name']}** — `{proj['path']}`  ",
        f"branch `{proj['branch']}` · commit `{proj['commit']}` · {proj['dirty_state']}",
        "",
        "## Current Focus",
        packet["current_focus"] or "_(not recorded — see current.md / handoff.md)_",
        "",
        "## Next Action",
        packet["next_action"] or "_(not recorded — set one with `crumb capture session --next`)_",
        "",
    ]

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
    packet = build_resume_packet(
        memory_dir, root, stale_days=stale_days, fast=args.fast, task=task
    )
    md = render_packet_markdown(packet)
    packet["approx_tokens"] = approx_tokens(md)

    # The full packet is the committed cloud-fallback artifact; --fast is a
    # print-only quick view and must not overwrite that artifact with a reduced one.
    # A task-scoped packet is a focused, ephemeral view, so it likewise does not
    # overwrite the canonical store-global snapshot.
    if not args.fast and not task:
        gen = memory_dir / "generated"
        gen.mkdir(parents=True, exist_ok=True)
        (gen / "resume-packet.md").write_text(md, encoding="utf-8")

    if args.json:
        print(json.dumps(packet, indent=2))
    else:
        print(md)
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    """Rebuild the generated/ projections from the canonical records (review F2).

    Mutations reindex automatically; this is the explicit refresh for after a batch
    of `--no-reindex` writes or a hand-edit, and the actionable target `validate`
    points at when it detects a stale projection (review F3).
    """
    root = resolve_root(args.project)
    memory_dir = root / MEMORY_DIRNAME
    if not memory_dir.is_dir():
        _emit_error(args, f"no {MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return 2

    ok = reindex_projections(memory_dir, root)
    summary = {"reindexed": ok, "path": str(memory_dir / "generated" / "resume-packet.md")}
    if args.json:
        print(json.dumps(summary, indent=2))
    elif ok:
        print(f"Reindexed projections: {summary['path']}")
    else:
        print("Reindex failed (projections left unchanged).")
    return 0 if ok else 1


# --------------------------------------------------------------------------- #
# search + guard — deterministic "don't repeat the expensive mistake" (Phase 5)
# --------------------------------------------------------------------------- #
#
# This is the capability that separates a continuity engine from a scrapbook
# (§23): before you act, it warns you if a failed attempt or active decision says
# don't go that way. Two non-negotiables shape the whole layer:
#
#   1. NO EMBEDDINGS (§11). Matching is exact/keyword/tag/file-path/component
#      overlap over records already loaded in memory — deterministic, dependency
#      free, same input -> same output. SQLite FTS / vectors are Phase 10. Correct,
#      not fast-at-scale.
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

GUARD_MAX_WARNINGS = 5            # §11.7 hard bound on ranked records shown
GUARD_NOISE_FLOOR = 3            # min score for a match to count at all (anti-noise)
GUARD_READ_FIRST_SCORE = 5      # score band: at/above -> at least READ_FIRST
GUARD_PAUSE_SCORE = 9           # score band: at/above -> at least PAUSE
GUARD_MIN_KEYWORD_OVERLAP = 2   # specific shared tokens for a pure-text match

# scoring weights (§11.4 signals)
GUARD_W_FILE = 6                # per overlapping file path (strongest specific signal)
GUARD_W_TAG = 4                 # per overlapping tag/component
GUARD_W_KEYWORD = 1            # per specific shared keyword
GUARD_W_STATUS_ACTIVE = 1
GUARD_W_CONFIDENCE_HIGH = 1
GUARD_W_REVIEWED = 1
GUARD_W_DO_NOT_RETRY = 4       # attempt carries an explicit "Do Not Retry Unless"
GUARD_W_OPEN_BLOCKER = 3       # overlaps an unresolved open question

# recency / branch de-weighting (reuse Phase 4 staleness signals)
GUARD_BRANCH_MISMATCH_FACTOR = 0.8   # record written on another branch -> possibly stale
GUARD_STALE_AGE_FACTOR = 0.7         # record older than stale_days
GUARD_STALE_DIST_FACTOR = 0.7        # record written >= N commits behind HEAD
GUARD_STALE_DIST_COMMITS = 10

# Action classes that mean "a human should weigh in" when they collide with
# memory (§15 high-impact changes). Security/refactor are deliberately NOT here:
# they raise caution inside the normal bands but do not auto-escalate to ASK_HUMAN
# (a routine "rewrite auth middleware" should land on PAUSE/READ_FIRST, not ASK).
GUARD_HIGH_IMPACT_CLASSES = frozenset({"deletion", "migration", "external_side_effect"})

_VERDICTS = ("PROCEED", "READ_FIRST", "PAUSE", "ASK_HUMAN")
_VERDICT_RANK = {v: i for i, v in enumerate(_VERDICTS)}


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
# A token that looks like a file path: has a directory separator or a dotted ext.
_FILE_TOKEN_RE = re.compile(
    r"[A-Za-z0-9_][\w./\-]*\.[A-Za-z0-9]+|[A-Za-z0-9_./\-]+/[A-Za-z0-9_./\-]+"
)


def _tokenize(text: str) -> set[str]:
    """Lowercase word tokens (alnum + underscore), single chars dropped."""
    return {t for t in _TOKEN_RE.findall((text or "").lower()) if len(t) > 1}


def _specific(text: str) -> set[str]:
    """Meaningful tokens only: word tokens minus the generic stop-words."""
    return _tokenize(text) - GUARD_STOPWORDS


def _paths_from_text(text: str) -> set[str]:
    """Path-like tokens (contain `/` or a dotted extension) found in free text."""
    out: set[str] = set()
    for m in _FILE_TOKEN_RE.finditer(text or ""):
        out.add(m.group(0))
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


# ---- action classifier (§11.2) -------------------------------------------- #

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
            "auth", "authentication", "authorization", "permission", "permissions",
            "credential", "credentials", "secret", "secrets", "token", "tokens",
            "oauth", "jwt", "rbac", "acl", "encrypt", "encryption", "scope", "scopes",
            "login", "session",
        }
    ),
    "external_side_effect": frozenset(
        {
            "deploy", "deployment", "publish", "release", "send", "email", "webhook",
            "production", "prod", "charge", "payment", "notify", "broadcast",
        }
    ),
    "dependency_tool": frozenset(
        {
            "dependency", "dependencies", "upgrade", "bump", "package", "npm", "pip",
            "library", "framework", "vendor", "sdk", "version",
        }
    ),
    "architecture": frozenset(
        {
            "architecture", "architectural", "pattern", "restructure", "rearchitect",
            "contract", "interface", "boundary", "layering", "decouple",
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
    files = _norm_files(set(_evidence_refs(rec, ("file", "path"))) | _paths_from_text(rec.body))
    tags = {str(t).lower() for t in (rec.meta.get("tags") or [])}
    text = " ".join(
        [str(rec.meta.get("title") or ""), rec.body, " ".join(tags)]
    )
    # For verifications the interesting "status" is the *outcome* (open/fixed/…),
    # not the lifecycle status — so `search type:verification status:open` filters
    # on what the agent actually cares about (review F1).
    status = (
        (rec.meta.get("outcome") or "open")
        if rec.rtype == "verification"
        else (rec.meta.get("status") or "active")
    )
    return {
        "id": rec.meta.get("id", rec.stem),
        "kind": rec.rtype,
        "status": status,
        "title": rec.meta.get("title", "") or rec.stem,
        "tags": tags,
        "files": files,
        "specific": _specific(text),
        "branch": rec.meta.get("branch"),
        "record": rec,
        "do_not_retry": rec.rtype == "attempt" and _attempt_has_do_not_retry(rec),
    }


def _item_from_trap(trap: dict) -> dict:
    heading, body = trap["heading"], trap.get("body", "")
    text = heading + "\n" + body
    return {
        "id": heading.split(":", 1)[0].strip() or "trap",
        "kind": "trap",
        "status": "active",
        "title": heading,
        "tags": set(),
        "files": _norm_files(_paths_from_text(body)),
        "specific": _specific(text),
        "branch": None,
        "record": None,
        "do_not_retry": False,
    }


def _item_from_question(q: dict) -> dict:
    text = q["question"] + "\n" + q.get("body", "")
    return {
        "id": "q:" + slugify(q["question"])[:48],
        "kind": "question",
        "status": (q.get("status") or "open"),
        "title": q["question"],
        "tags": set(),
        "files": _norm_files(_paths_from_text(q.get("body", ""))),
        "specific": _specific(text),
        "branch": None,
        "record": None,
        "do_not_retry": False,
    }


def _candidate_items(memory_dir: Path) -> list[dict]:
    """Every searchable item: durable decision/attempt records + trap + question blocks."""
    items: list[dict] = []
    for rec in load_records(memory_dir, types=("decision", "attempt", "verification")):
        if rec.error:
            continue
        items.append(_item_from_record(rec))
    items.extend(_item_from_trap(t) for t in load_traps(memory_dir))
    items.extend(_item_from_question(q) for q in load_open_questions(memory_dir))
    return items


# ---- scoring (§11.4) ------------------------------------------------------- #

def _score_item(
    item: dict,
    q_specific: set[str],
    q_files: set[str],
    root: Path,
    cur_branch: str,
    stale_days: int,
    *,
    min_keyword: int,
) -> dict | None:
    """Score one item against the query. None if it does not clear the candidate gate."""
    # _norm_files stores each file as both its full path and its bare basename,
    # so the intersection can hold both variants of one physical file. Count each
    # distinct full path once, plus any bare-basename match not already covered by
    # a matched full path. Keying on basename alone (the old approach) wrongly
    # collapsed genuinely-distinct files that share a name (src/a/x.ts, src/b/x.ts)
    # — undercounting the score and picking a hash-order-dependent survivor.
    raw_files = item["files"] & q_files
    full_paths = {f for f in raw_files if "/" in f}
    covered = {f.rsplit("/", 1)[-1] for f in full_paths}
    extra_bare = {f for f in raw_files if "/" not in f and f not in covered}
    matched_files = sorted(full_paths | extra_bare)
    file_count = len(full_paths) + len(extra_bare)
    matched_tags = item["tags"] & q_specific
    kw_overlap = item["specific"] & q_specific
    kw_count = len(kw_overlap)

    # Candidate gate (anti-noise, Fixture 3): a file or tag hit always qualifies;
    # a pure-text match needs >= min_keyword specific shared tokens.
    if not matched_files and not matched_tags and kw_count < min_keyword:
        return None

    signals: list[str] = []
    score = 0.0
    if matched_files:
        score += GUARD_W_FILE * file_count
        signals.append("file")
    if matched_tags:
        score += GUARD_W_TAG * len(matched_tags)
        signals.append("tag")
    if kw_count:
        score += GUARD_W_KEYWORD * kw_count
        if kw_count >= min_keyword:
            signals.append("keyword")

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

    # Recency + commit-distance de-weighting (reuse Phase 4 signals).
    factor = 1.0
    if rec is not None:
        age = _age_days(rec.meta.get("updated_at") or rec.meta.get("created_at"))
        if age is not None and age > stale_days:
            factor *= GUARD_STALE_AGE_FACTOR
        dist = git_commit_distance(root, rec.meta.get("commit"))
        if dist is not None and dist >= GUARD_STALE_DIST_COMMITS:
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
        "title": item["title"],
        "score": score,
        "signals": signals,
        "matched_files": sorted(matched_files),
        "matched_tags": sorted(matched_tags),
        "keyword_overlap": sorted(kw_overlap),
        "branch_mismatch": branch_mismatch,
        "reason": _match_reason(item["kind"], signals, matched_files, matched_tags, kw_count),
    }


def _match_reason(kind, signals, matched_files, matched_tags, kw_count) -> str:
    """Human phrase for why a record matched. Derived facts only — never executed."""
    parts: list[str] = []
    if matched_files:
        shown = ", ".join(sorted(matched_files)[:3])
        parts.append(f"same file(s): {shown}")
    if matched_tags:
        parts.append(f"same component/tag: {', '.join(sorted(matched_tags))}")
    if kw_count and not matched_files and not matched_tags:
        parts.append(f"{kw_count} shared keyword(s)")
    elif kw_count:
        parts.append(f"+{kw_count} shared keyword(s)")
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
) -> tuple[list[dict], dict[str, dict]]:
    """Deterministic search over the canonical records (§20.10).

    Returns (matches sorted best-first, items_by_id). Matching signals: exact/
    keyword text, tag/component, and file path. No embeddings; same input ->
    same output. `filters` narrows the corpus by type/status/tag/file first.
    """
    items = _candidate_items(memory_dir)
    by_id = {it["id"]: it for it in items}
    filters = filters or {}
    q_specific = _specific(query)
    q_files = _norm_files(_paths_from_text(query) | set(files or []))
    cur_branch = git_branch(root)

    matches: list[dict] = []
    for it in items:
        if not _passes_filters(it, filters):
            continue
        m = _score_item(
            it, q_specific, q_files, root, cur_branch, stale_days, min_keyword=min_keyword
        )
        if m is None:
            # Filter-only lookups (no scoring query) still surface the item.
            if filters and not q_specific and not q_files:
                m = {
                    "id": it["id"], "kind": it["kind"], "status": it["status"],
                    "title": it["title"], "score": float(noise_floor), "signals": ["filter"],
                    "matched_files": [], "matched_tags": [], "keyword_overlap": [],
                    "branch_mismatch": False, "reason": "matched filter",
                }
            else:
                continue
        if m["score"] < noise_floor:
            continue
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
    if f and not (_norm_files({f}) & item["files"]):
        return False
    return True


# ---- guard verdict (§11.5–11.6) -------------------------------------------- #

def _decide_verdict(top: list[dict], matched_classes: list[str]) -> str:
    """Pick one verdict from the ranked matches + action class. Deterministic."""
    if not top:
        return "PROCEED"

    floors: list[str] = ["PROCEED"]
    for m in top:
        sig = set(m["signals"])
        specific = bool({"file", "tag"} & sig)
        if "do-not-retry" in sig and specific:
            floors.append("PAUSE")          # a failed attempt on these files/component
        elif m["kind"] == "decision" and specific:
            floors.append("READ_FIRST")     # an active decision constrains this area
        elif m["kind"] == "trap" and (specific or "keyword" in sig):
            floors.append("READ_FIRST")
        elif "open-blocker" in sig:
            floors.append("READ_FIRST")

    best = max(m["score"] for m in top)
    band = "PROCEED"
    if best >= GUARD_PAUSE_SCORE:
        band = "PAUSE"
    elif best >= GUARD_READ_FIRST_SCORE:
        band = "READ_FIRST"
    floors.append(band)

    verdict = max(floors, key=lambda v: _VERDICT_RANK[v])

    # ASK_HUMAN escalation: a high-impact class colliding with memory is a human's
    # call (§15). Security/refactor never auto-escalate (keeps Fixture 2 on PAUSE).
    high_impact = GUARD_HIGH_IMPACT_CLASSES & set(matched_classes)
    if high_impact and _VERDICT_RANK[verdict] >= _VERDICT_RANK["READ_FIRST"]:
        verdict = "ASK_HUMAN"
    return verdict


def _next_safest_action(verdict: str, top: list[dict], by_id: dict, root: Path) -> str:
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
        return (
            f"Stop and read these records before acting: {ids}. They include a failed "
            "attempt or active constraint on this exact area. Prefer the smallest "
            "possible change over a rewrite." + verify
        )
    if verdict == "READ_FIRST":
        return (
            f"Read {ids} first — they constrain this area — then make a surgical change."
            + verify
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
    )

    active, history = [], []
    for m in matches:
        # A record is live when active; an open question is live too — it must be
        # able to drive the verdict (open-blocker floor). Resolved questions and
        # superseded/rejected/stale records fall through to history (mention-only).
        live = m["status"] == "active" or (
            m["kind"] == "question" and m["status"] == "open"
        )
        (active if live else history).append(m)

    top = active[:GUARD_MAX_WARNINGS]
    verdict = _decide_verdict(top, classes)

    # Staleness is computed (reuse Phase 4) so a stale/wrong-branch handoff surfaces
    # in guard exactly as it does in resume (Fixture 4), regardless of verdict.
    handoff_text = (
        (memory_dir / "handoff.md").read_text(encoding="utf-8")
        if (memory_dir / "handoff.md").is_file()
        else ""
    )
    staleness = compute_staleness(
        root,
        parse_handoff_meta(handoff_text),
        active_decisions(memory_dir),
        active_attempts(memory_dir),
        load_open_questions(memory_dir),
        stale_days,
    )[:GUARD_MAX_WARNINGS]

    return {
        "verdict": verdict,
        "action": action,
        "action_class": primary,
        "action_classes": classes,
        "matches": top,
        "history": history[:GUARD_MAX_WARNINGS],
        "staleness": staleness,
        "next_action": _next_safest_action(verdict, top, by_id, root),
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
            out.append(f"{i}. {m['id']} — {m['kind']}, {m['reason']}.")
    else:
        out.append("Relevant memory: none above the noise floor.")
    out.append("")

    if result["history"]:
        out.append("History (not active — context only):")
        for m in result["history"]:
            out.append(f"- {m['id']} — {m['status']}; {m['reason']}.")
        out.append("")

    if result["staleness"]:
        out.append("Staleness / risk:")
        for w in result["staleness"]:
            out.append(f"- {w}")
        out.append("")

    out.append("Recommended next action:")
    out.append(result["next_action"])
    return "\n".join(out).rstrip() + "\n"


def render_search_human(matches: list[dict], query: str) -> str:
    if not matches:
        return f"search: no records matched {query!r}.\n"
    out = [f"search: {len(matches)} record(s) matched {query!r}", ""]
    for m in matches:
        out.append(f"- {m['id']} — {m['kind']} [{m['status']}] (score {m['score']}): {m['reason']}.")
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
    matches, _ = search(memory_dir, root, query, filters=filters, stale_days=stale_days)

    if args.json:
        print(json.dumps({"query": query, "filters": filters, "matches": matches}, indent=2))
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
        _emit_error(args, 'guard needs a proposed action, e.g. guard "rewrite the auth middleware".')
        return 2

    stale_days = args.stale_days if args.stale_days is not None else STALE_AGE_DAYS
    result = guard(memory_dir, root, action, files=args.files, stale_days=stale_days)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(render_guard_human(result))
    return 0


# --------------------------------------------------------------------------- #
# audit + scan-secrets — heuristic safety net (Phase 6; plan §10/§15/§16 note/§17)
# --------------------------------------------------------------------------- #
#
# Design split (plan §16.14 note): `validate` is deterministic and GATES; `audit`
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

# Common secret SHAPES (plan §15, §17.6). Deliberately conservative: better to miss
# an exotic secret than to flag every git sha. Coverage / known gaps are recorded in
# the Phase 6 doc ("Decisions resolved this phase").
SECRET_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("github-fine-grained-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    # sk-… covers both the legacy `sk-<base62>` and modern `sk-proj-<base62>`
    # OpenAI shapes (the hyphen in `proj-` broke the old alnum-only pattern).
    ("openai-style-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    # Stripe-style secret/restricted/publishable keys: sk_live_…, rk_test_…, etc.
    ("stripe-style-key", re.compile(r"\b[srp]k_(?:live|test)_[A-Za-z0-9]{16,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("pem-private-key", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}")),
    (
        "secret-assignment",
        re.compile(
            r"(?i)\b(?:api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|"
            r"refresh[_-]?token|id[_-]?token|session[_-]?token|private[_-]?key|"
            r"signing[_-]?key|client[_-]?secret|password|passwd|pwd)\b"
            # allow a closing quote on the label so JSON keys ("private_key":)
            # match too — the scan now covers .json files (review #3 R26)
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
    (
        "labeled-hex-secret",
        re.compile(
            r"(?i)\b(?:token|authorization|x-[a-z0-9-]*-(?:key|token))\b\s*[:=]\s*"
            r"['\"]?[0-9a-fA-F]{32,}\b"
        ),
    ),
)

# Standalone high-entropy tokens (base64-ish). The charset excludes `_`/`-`, so
# record ids like `dec_20260605_markdown-source-of-truth` never form a long run,
# and the mixed-class + entropy floor below skips lowercase-only ids and hex shas.
_HIGH_ENTROPY_TOKEN = re.compile(r"\b[A-Za-z0-9+/=]{32,}\b")

# Override-style phrasing audit flags for human review (plan §16 note). A *flag*,
# never a gate — same content-as-data posture as guard (Fixture 7).
# A short run of qualifiers between the verb and its object, so natural phrasings
# ("ignore failing tests", "ignore all prior instructions", "skip the flaky
# suite's checks") are caught, not just the bare determiner forms (review #3 R26).
_IL_QUALIFIERS = r"(?:(?:all|the|any|every|these|those|prior|previous|earlier|existing|above|failing|flaky|broken|remaining|other)\s+){0,3}"

INSTRUCTION_LIKE_PATTERNS: tuple["re.Pattern[str]", ...] = (
    re.compile(
        r"(?i)\bignore\s+" + _IL_QUALIFIERS +
        r"(?:tests?|instructions?|previous|above|rules?|warnings?|memory|checks?|errors?|failures?)\b"
    ),
    re.compile(
        r"(?i)\bskip\s+" + _IL_QUALIFIERS +
        r"(?:tests?|validation|verification|checks?|review|ci)\b"
    ),
    re.compile(
        r"(?i)\bdisable\s+" + _IL_QUALIFIERS +
        r"(?:tests?|checks?|validation|guard|safety|linter?|ci)\b"
    ),
    re.compile(r"(?i)\b(?:never|always)\s+run\b"),
    re.compile(r"(?i)\bdo\s+not\s+run\b"),
    re.compile(r"(?i)\b(?:always|never)\s+(?:force[- ]?push|skip|disable|ignore|bypass)\b"),
    re.compile(
        r"(?i)\bbypass\s+" + _IL_QUALIFIERS +
        r"(?:tests?|checks?|(?:code\s+)?review|validation|guard|ci)\b"
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
SESSIONS_GROWTH_NOTE = 50    # forward-ref §22 Q7 / Phase 10 rollup


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
    covered = sum(
        len(w) for w in _WORD_RE.findall(seg) if any(c in "aeiouAEIOU" for c in w)
    )
    return covered >= 6 and covered * 2 >= len(seg)


def _looks_like_path_or_identifier(tok: str) -> bool:
    """True for path- or dotted-identifier-shaped tokens that only *look* random.

    Long CamelCase identifiers like ``DatabaseMigrationHelperV2Factory`` and paths
    like ``app/src/MigrationV14ToV15Test`` clear the mixed-class + entropy bar yet
    are obviously not secrets (review §6.4). The discriminator is deliberately narrow
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
        elif len(seg) >= 12:
            return False  # a long, word-free segment is a blob, not a path component
    return has_word


def _looks_high_entropy(tok: str) -> bool:
    """True only for mixed-class, genuinely-random-looking tokens.

    Requires lower + upper + digit (so hex shas and lowercase ids never qualify) and
    a real entropy floor. Conservative by design — misses some secrets, flags ~no ids.
    Path- and identifier-shaped tokens are allowlisted (review §6.4) without lowering
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
# under memory was previously never scanned (review #3 R26).
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


def scan_secrets(memory_dir: Path) -> list[dict]:
    """Scan committed memory for secret-like strings (plan §15, §17.6).

    Each hit is {pattern, path, line} — the pattern NAME and location, never the
    matched value. Skips private/index/generated. This must run before any
    "commit memory" recommendation (§2.6, §15).
    """
    findings: list[dict] = []
    seen: set[tuple[str, str, int]] = set()
    for p in _iter_committed_memory_files(memory_dir):
        rel = str(p.relative_to(memory_dir))
        try:
            lines = p.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, 1):
            for name, pat in SECRET_PATTERNS:
                if pat.search(line):
                    key = (name, rel, i)
                    if key not in seen:
                        seen.add(key)
                        findings.append({"pattern": name, "path": rel, "line": i})
            for m in _HIGH_ENTROPY_TOKEN.finditer(line):
                if _looks_high_entropy(m.group(0)):
                    key = ("high-entropy-string", rel, i)
                    if key not in seen:
                        seen.add(key)
                        findings.append({"pattern": "high-entropy-string", "path": rel, "line": i})
    return findings


# ---- instruction-like heuristic -------------------------------------------- #

def scan_instruction_like(memory_dir: Path) -> list[dict]:
    """Lexical scan of known-traps.md + durable record bodies for override phrasing.

    Flag-only (warn). Never gates `validate` and never instructs `guard` — the same
    content-as-data posture as Fixture 7 (plan §16 note).
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
        text = _strip_html_comments(p.read_text(encoding="utf-8"))
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
    of the canonical inputs (plan §15, §17.8). Mismatch => a source record changed
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
            continue  # undecodable projection — validate 16.12 reports it (review #3 R16)
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
    """Bloat heuristics (plan §16.13, §12): over-budget packet, adapter duplication,
    runaway sessions/ growth."""
    memory_dir = Path(memory_dir)
    findings: list[dict] = []

    # Packet over budget.
    pkt = memory_dir / "generated" / "resume-packet.md"
    if pkt.is_file():
        toks = approx_tokens(pkt.read_text(encoding="utf-8"))
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
        text = ap.read_text(encoding="utf-8", errors="replace")
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
        elif len(text) > ADAPTER_BLOAT_CHARS:
            findings.append(
                {
                    "kind": "adapter-bloat",
                    "path": name,
                    "message": (
                        f"adapter '{name}' is {len(text)} chars; signpost files should be small "
                        "pointers into memory, not large copies (§16.13)"
                    ),
                }
            )

    # sessions/ growth note (forward-ref §22 Q7 / Phase 10 rollup).
    sess = memory_dir / "sessions"
    n = len(list(sess.glob("*.md"))) if sess.is_dir() else 0
    if n > SESSIONS_GROWTH_NOTE:
        findings.append(
            {
                "kind": "sessions-growth",
                "path": "sessions/",
                "message": (
                    f"{n} session records — consider a periodic rollup so the store stays "
                    "navigable (forward-ref Phase 10)"
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
    """Heuristic health + safety audit (plan §10, §15, §16 note).

    Returns findings tagged with a severity. Only `secret` is fail-severity (blocks);
    everything else advises. Policy-aware: reads tracking policy via the manifest /
    loaders rather than guessing (§7).
    """
    memory_dir = Path(memory_dir)
    findings: list[dict] = []

    # B. Secret scan — the only blocking check (§15, §17.6, Fixture 6).
    for s in scan_secrets(memory_dir):
        findings.append(
            _audit_finding(
                "secret",
                AUDIT_FAIL,
                s["path"],
                f"possible secret ({s['pattern']}) at line {s['line']} — "
                "must not be committed to memory; remove before any commit",
                line=s["line"],
                pattern=s["pattern"],
            )
        )

    # A. Staleness / health (reuse Phase 4 compute_staleness): handoff age +
    # commit-distance, branch mismatch (incl. detached HEAD), aged-unresolved
    # questions/decisions, expired + low-confidence records.
    handoff_text = (
        (memory_dir / "handoff.md").read_text(encoding="utf-8")
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
    ):
        # The handoff age/distance line is emitted unconditionally; it is only a
        # *warning* when compute_staleness marked it cold (⚠). "handoff is 0
        # day(s) old, written 0 commit(s) behind" on a seconds-old store is
        # health context, not a problem (review #3 R20).
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
            out.append(f"  ✗ [{f['check']}] {f['path'] or '-'}: {f['message']}")
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
        print(
            json.dumps(
                {
                    "ok": not fails,
                    "failed": len(fails),
                    "warnings": len(warns),
                    "info": len(infos),
                    "findings": findings,
                },
                indent=2,
            )
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
    if args.json:
        print(json.dumps({"ok": not hits, "count": len(hits), "hits": hits}, indent=2))
        return 1 if hits else 0

    if hits:
        print(
            f"scan-secrets: {len(hits)} possible secret(s) found — "
            "DO NOT commit memory until resolved\n"
        )
        for h in hits:
            print(f"  ✗ [{h['pattern']}] {h['path']}:{h['line']}")
        return 1

    print("scan-secrets: OK — no secret-like strings in committed memory.")
    return 0


# --------------------------------------------------------------------------- #
# Integrations — bootstrapping the automaticity primitives (review §5/§7)
# --------------------------------------------------------------------------- #
#
# The package already ships every ingredient for automatic use (the fenced
# managed-block writer, the ADAPTER_FILENAMES list, the breadcrumbs-mcp server);
# this section assembles them behind explicit consent and makes each edit fenced
# and reversible. Default `crumb init` behavior is unchanged — integrations are
# opt-in (flags, or the first-run interactive picker).

MCP_SERVER_NAME = "breadcrumbs"


def mcp_server_entry() -> dict:
    """The `.mcp.json` entry for the breadcrumbs server (verified Claude Code shape).

    The server reads $BREADCRUMBS_PROJECT to locate the store; `${CLAUDE_PROJECT_DIR}`
    is exported by Claude Code, with a `.`-fallback for other launchers.
    """
    return {
        "type": "stdio",
        "command": "breadcrumbs-mcp",
        "args": [],
        "env": {"BREADCRUMBS_PROJECT": "${CLAUDE_PROJECT_DIR:-.}"},
    }


def register_mcp(root: Path) -> Path:
    """Merge the breadcrumbs server into `.mcp.json`, preserving any other servers."""
    path = root / ".mcp.json"

    def _mut(data: dict) -> None:
        servers = data.setdefault("mcpServers", {})
        servers[MCP_SERVER_NAME] = mcp_server_entry()

    merge_json_file(path, _mut)
    return path


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
        # accepted and silently ignored, so reads AND writes went to cwd's store
        # (review #3 R12). The server resolves $BREADCRUMBS_PROJECT.
        if getattr(args, "project", None):
            os.environ["BREADCRUMBS_PROJECT"] = str(resolve_root(args.project))
        # Lazy import keeps `crumb` stdlib-only; the server degrades with a clear
        # hint when the [mcp] extra is missing.
        from breadcrumbs import mcp_server

        return mcp_server.main([])

    if what == "register":
        root = resolve_root(args.project)
        path = register_mcp(root)
        sdk = _mcp_sdk_available()
        summary = {"registered": str(path), "server": MCP_SERVER_NAME, "sdk_available": sdk}
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"Registered MCP server '{MCP_SERVER_NAME}' in {path}")
            if not sdk:
                print("  note: the MCP SDK isn't installed — run: pip install 'crumb-kit[mcp]'")
            print("  note: in Claude Code a committed .mcp.json server starts "
                  "'⏸ Pending approval' until you approve it once — this is expected.")
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
            print(json.dumps(report, indent=2))
        else:
            print("crumb mcp doctor")
            print(f"  {'✓' if sdk else '✗'} [mcp] extra: "
                  + ("importable" if sdk else "not installed — run: pip install 'crumb-kit[mcp]'"))
            print(f"  {'✓' if registered else '✗'} registration: "
                  + (f"'{MCP_SERVER_NAME}' in {mcp_path}" if registered
                     else "not registered — run `crumb mcp register`"))
        return 0 if (sdk and registered) else 1

    _emit_error(args, "specify: `crumb mcp serve`, `crumb mcp register`, or `crumb mcp doctor`")
    return 2


# ---- adapter signpost block (review §7.1) ---------------------------------- #

# Markdown-comment markers for the adapter managed block (same fence mechanism as
# .gitignore, different comment syntax).
ADAPTER_BEGIN = (
    "<!-- >>> breadcrumbs managed block (managed by `crumb init`) "
    "— edit above/below, not inside >>> -->"
)
ADAPTER_END = "<!-- <<< breadcrumbs managed block <<< -->"


def adapter_block() -> str:
    """The signpost injected into agent-guidance files: a small pointer, not a copy.

    Deliberately tiny (well under ADAPTER_BLOAT_CHARS) so the tool's own `audit`
    stays green — it practices what it preaches. Generic guidance text, never a
    record body, so it cannot trip audit's record-duplication check.
    """
    return "\n".join([
        ADAPTER_BEGIN,
        "## Project memory (breadcrumbs)",
        "",
        "This repo has a durable memory store under `.project-memory/`. Use it:",
        "",
        "- **Starting work / new session:** read the resume packet first —",
        "  `crumb resume` (or MCP resource `memory://resume-packet`).",
        "- **Before any risky or irreversible action** (deletes, force-push, schema",
        "  or build-system changes, rewrites): `crumb guard \"<action>\"` and honor a",
        "  `PAUSE` / `ASK_HUMAN` verdict.",
        "- **After a durable decision or a failed approach:**",
        "  `crumb remember decision|attempt …`.",
        "- **After checking whether something is still true / fixed:**",
        "  `crumb verify \"<subject>\" --status fixed|open|regressed|… --evidence …`.",
        "- **Leaving a note for the next agent:** `crumb note question|trap|idea …`.",
        "- **Session end:** `crumb capture session`.",
        "",
        "Memory must never contain secrets; `crumb scan-secrets` gates commits.",
        ADAPTER_END,
    ]) + "\n"


def present_adapters(root: Path) -> list[str]:
    """Adapter-guidance files that already exist (we never create new ones)."""
    return [name for name in ADAPTER_FILENAMES if (root / name).is_file()]


def write_adapter_block(root: Path, name: str) -> None:
    rewrite_managed_block(root / name, ADAPTER_BEGIN, ADAPTER_END, adapter_block())


def remove_adapter_block(root: Path, name: str) -> bool:
    """Strip our managed block from an adapter file. True iff it was present."""
    path = root / name
    if not path.exists():
        return False
    had = ADAPTER_BEGIN in path.read_text(encoding="utf-8")
    rewrite_managed_block(path, ADAPTER_BEGIN, ADAPTER_END, None)
    return had


# ---- Claude Code hooks (review §7.3 / Appendix A.6) ------------------------ #

HOOK_EVENTS = ("session", "guard", "capture")
# breadcrumbs event -> (Claude Code event name, PreToolUse matcher or None, command)
_HOOK_SPECS: dict[str, tuple[str, str | None, str]] = {
    "session": ("SessionStart", None, "crumb hook session"),
    "guard": ("PreToolUse", "Bash|Edit|Write|MultiEdit", "crumb hook guard"),
    "capture": ("Stop", None, "crumb hook capture"),
}


def _group_has_command(group: object, command: str) -> bool:
    return isinstance(group, dict) and any(
        isinstance(h, dict) and h.get("command") == command
        for h in group.get("hooks", [])
    )


def _group_is_breadcrumbs(group: object) -> bool:
    return isinstance(group, dict) and any(
        isinstance(h, dict) and str(h.get("command", "")).startswith("crumb hook")
        for h in group.get("hooks", [])
    )


def install_claude_hooks(root: Path, events: list[str]) -> Path:
    """Merge SessionStart/PreToolUse/Stop hooks into .claude/settings.json.

    Appends to existing hook arrays (never clobbers other hooks) and is idempotent —
    re-running does not duplicate the breadcrumbs entries.
    """
    path = root / ".claude" / "settings.json"

    def _mut(data: dict) -> None:
        hooks = data.setdefault("hooks", {})
        for ev in events:
            cc_event, matcher, command = _HOOK_SPECS[ev]
            arr = hooks.setdefault(cc_event, [])
            if any(_group_has_command(g, command) for g in arr):
                continue  # idempotent
            entry: dict = {"hooks": [{"type": "command", "command": command}]}
            if matcher:
                entry = {"matcher": matcher, **entry}
            arr.append(entry)

    merge_json_file(path, _mut)
    return path


def remove_claude_hooks(root: Path) -> bool:
    """Remove only the `crumb hook …` entries from .claude/settings.json. True iff any."""
    path = root / ".claude" / "settings.json"
    if not path.exists():
        return False
    state = {"removed": False}

    def _mut(data: dict) -> None:
        hooks = data.get("hooks")
        if not isinstance(hooks, dict):
            return
        for cc_event in list(hooks):
            arr = hooks.get(cc_event)
            if not isinstance(arr, list):
                continue
            kept = [g for g in arr if not _group_is_breadcrumbs(g)]
            if len(kept) != len(arr):
                state["removed"] = True
            if kept:
                hooks[cc_event] = kept
            else:
                del hooks[cc_event]
        if not hooks:
            data.pop("hooks", None)

    merge_json_file(path, _mut)
    return state["removed"]


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


def _prompt_yes(question: str, default: bool) -> bool:
    suffix = " [Y/n] " if default else " [y/N] "
    try:
        ans = input(question + suffix).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return default
    if not ans:
        return default
    return ans in ("y", "yes")


def resolve_integration_plan(root: Path, args: argparse.Namespace) -> dict:
    """Resolve which integrations to apply from flags, detection, and (TTY) prompts.

    Returns {"adapters": [...], "mcp": bool, "hooks": [...]}. On a TTY with an
    integration left unspecified, the user is asked once per integration (the
    first-run picker). Non-interactive + unspecified means "off".
    """
    detected = present_adapters(root)
    adapters = _resolve_tristate_list(getattr(args, "adapter", None), detected)
    hooks = _resolve_tristate_list(getattr(args, "hooks", None), list(HOOK_EVENTS))
    mcp = getattr(args, "mcp", None)  # True / False / None

    interactive = _interactive()
    undecided = adapters is None or mcp is None or hooks is None
    if interactive and undecided:
        print("Set up agent integrations so the store is actually used (each is reversible):")
        if adapters is None:
            if detected:
                adapters = detected if _prompt_yes(
                    f"  Inject the signpost block into {', '.join(detected)}?", True
                ) else []
            else:
                adapters = []  # nothing to point at; don't create files
        if mcp is None:
            mcp = _prompt_yes("  Register the MCP server in .mcp.json?", True)
        if hooks is None:
            hooks = list(HOOK_EVENTS) if _prompt_yes(
                "  Install Claude Code hooks (auto resume/guard/capture)?", False
            ) else []

    return {
        "adapters": adapters or [],
        "mcp": bool(mcp),
        "hooks": hooks or [],
    }


def apply_integrations(root: Path, plan: dict) -> dict:
    """Write the resolved integrations; return a summary of what was touched."""
    applied: dict = {"adapters": [], "mcp": None, "hooks": []}
    for name in plan["adapters"]:
        if (root / name).is_file():
            write_adapter_block(root, name)
            applied["adapters"].append(name)
    if plan["mcp"]:
        applied["mcp"] = str(register_mcp(root))
    if plan["hooks"]:
        install_claude_hooks(root, plan["hooks"])
        applied["hooks"] = list(plan["hooks"])
    return applied


def remove_integrations(root: Path) -> dict:
    """Reverse every integration breadcrumbs added; leave all other content intact."""
    removed: dict = {"adapters": [], "mcp": False, "hooks": False}
    for name in ADAPTER_FILENAMES:
        if remove_adapter_block(root, name):
            removed["adapters"].append(name)
    removed["mcp"] = unregister_mcp(root)
    removed["hooks"] = remove_claude_hooks(root)
    return removed


# ---- crumb doctor (review §A.7) -------------------------------------------- #

def doctor_report(root: Path) -> dict:
    """Integration-health report: is memory actually wired up?"""
    memory_dir = root / MEMORY_DIRNAME
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"check": name, "ok": ok, "detail": detail})

    store = memory_dir.is_dir()
    add("store", store, f"{MEMORY_DIRNAME}/ present" if store else f"no {MEMORY_DIRNAME}/ — run `crumb init`")

    # Adapter blocks
    present = present_adapters(root)
    blocked = [n for n in present if ADAPTER_BEGIN in (root / n).read_text(encoding="utf-8")]
    bloated = [
        n for n in blocked if len((root / n).read_text(encoding="utf-8")) > ADAPTER_BLOAT_CHARS
    ]
    add(
        "adapter",
        bool(blocked) and not bloated,
        (f"signpost in {', '.join(blocked)}" if blocked else
         (f"adapter files present ({', '.join(present)}) but no signpost block" if present
          else "no agent-guidance files detected")) + (f"; BLOATED: {', '.join(bloated)}" if bloated else ""),
    )

    # MCP registration + extra
    mcp_path = root / ".mcp.json"
    registered = False
    if mcp_path.is_file():
        try:
            registered = MCP_SERVER_NAME in (json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers") or {})
        except (json.JSONDecodeError, OSError):
            registered = False
    sdk = _mcp_sdk_available()
    add("mcp", registered, ".mcp.json registered" if registered else "not registered (`crumb mcp register`)")
    add("mcp_extra", sdk, "[mcp] extra importable" if sdk else "optional [mcp] extra not installed")

    # Hooks
    hook_cmds = _installed_hook_commands(root)
    add("hooks", bool(hook_cmds), f"{len(hook_cmds)} crumb hook(s) installed" if hook_cmds else "no hooks installed")

    # Resume-packet staleness vs HEAD
    if store:
        packet = memory_dir / "generated" / "resume-packet.md"
        if packet.is_file():
            stale = _packet_is_stale(memory_dir, root)
            add("resume_packet", not stale, "stale vs HEAD — run `crumb resume`" if stale else "fresh")
        else:
            add("resume_packet", False, "not generated — run `crumb resume`")

    integrated = any(c["ok"] for c in checks if c["check"] in ("adapter", "mcp", "hooks"))
    return {"checks": checks, "integrated": integrated, "store": store}


def _installed_hook_commands(root: Path) -> list[str]:
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
            if isinstance(group, dict):
                for h in group.get("hooks", []):
                    c = isinstance(h, dict) and str(h.get("command", ""))
                    if c and c.startswith("crumb hook"):
                        cmds.append(c)
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


def _strip_packet_volatile(md: str) -> str:
    """Drop the generated_at line so a pure-timestamp delta is not read as staleness."""
    return "\n".join(
        ln for ln in md.splitlines() if "generated_at:" not in ln
    )


def cmd_doctor(args: argparse.Namespace) -> int:
    root = resolve_root(args.project)
    report = doctor_report(root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("crumb doctor — integration health")
        for c in report["checks"]:
            mark = "✓" if c["ok"] else "✗"
            print(f"  {mark} [{c['check']}] {c['detail']}")
        if report["store"] and not report["integrated"]:
            print("\n" + FIRST_RUN_NUDGE)
    # Non-zero when a store exists but nothing is wired up (the §5 finding, machine-checkable).
    return 0 if (report["integrated"] or not report["store"]) else 1


# ---- crumb hook session|guard|capture (review §A.6) ------------------------ #

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
    # hook as malformed JSON — treat it the same (review #3 R13).
    return payload if isinstance(payload, dict) else {}


def _hook_root(payload: dict) -> Path:
    return Path(
        payload.get("cwd") or os.environ.get("BREADCRUMBS_PROJECT") or Path.cwd()
    ).resolve()


# Cheap risk patterns the keyword classifier misses (destructive shell/git ops).
# Used only to decide whether to escalate to full guard — a pure regex scan of a
# short string, no record I/O, so the common path stays well inside the hook budget.
# Store-specific trap shapes are NOT hardcoded here — they come from the
# generated/ trap-token index below (review #3 R9).
_HOOK_RISK_RE = re.compile(
    r"(?i)(--force\b|force-push|push\s+-f\b|reset\s+--hard|rm\s+-rf|git\s+clean|"
    r"--stop\b|drop\s+table|truncate\b|--no-verify|branch\s+-D\b)"
)


def _prefilter_trap_hit(memory_dir: Path, action: str, files: list[str] | None) -> bool:
    """Does the action overlap the reindex-time trap-token index? (review #3 R9)

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
    # generic word never escalates (§19b.8).
    if len(_specific(action) & set(idx.get("tokens") or ())) >= GUARD_MIN_KEYWORD_OVERLAP:
        return True
    action_paths = _norm_files(_paths_from_text(action)) | _norm_files(files or [])
    index_paths = _norm_files(idx.get("paths") or ())
    return bool(action_paths & index_paths)


def _hook_action_from_tool(tool: str, tool_input: dict) -> tuple[str, list[str] | None]:
    """Derive a guard action string + affected files from a PreToolUse payload."""
    if tool == "Bash":
        return (tool_input.get("command") or "").strip(), None
    if tool in ("Edit", "Write", "MultiEdit"):
        fp = tool_input.get("file_path") or tool_input.get("path") or ""
        return (f"edit {fp}".strip(), [fp] if fp else None)
    return "", None


def _hook_guard_reason(result: dict) -> str:
    lines = [f"breadcrumbs guard: {result['verdict']} for this action."]
    for m in result.get("matches", [])[:3]:
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
        # other malformed-payload path degrades to {} (review #3 R13).
        tool_input = {}
    action, files = _hook_action_from_tool(payload.get("tool_name") or "", tool_input)
    if not action:
        print(json.dumps({}))
        return 0
    # Cost-aware pre-filter: pure-string classify + risk regex on the common
    # path, plus one read of the reindex-time trap-token index (review #3 R9) so
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
    decision = "ask" if verdict == "ASK_HUMAN" else "allow"
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,  # memory informs; it never denies on its own
            "permissionDecisionReason": _hook_guard_reason(result),
        }
    }
    print(json.dumps(out))
    return 0


def _hook_capture(memory_dir: Path, root: Path, payload: dict) -> int:
    if not memory_dir.is_dir():
        print(json.dumps({}))
        return 0
    # Reuse the same --fast snapshot path the CLI uses (diff-stat already summarized).
    ns = argparse.Namespace(
        project=str(root), json=True, plain=False, verbose=False, fast=True,
        next_action="(session ended; see git log)", title="session", set=None,
        focus=None, agent="agent", capture_what="session",
    )
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_capture_session(ns)
    except Exception:  # pragma: no cover - a capture failure must not block Stop
        pass
    print(json.dumps({}))
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    event = getattr(args, "hook_event", None)
    payload = _read_hook_stdin()
    root = _hook_root(payload)
    memory_dir = root / MEMORY_DIRNAME
    if event == "session":
        return _hook_session(memory_dir, root)
    if event == "guard":
        return _hook_guard(memory_dir, root, payload)
    if event == "capture":
        return _hook_capture(memory_dir, root, payload)
    _emit_error(args, "specify: `crumb hook session|guard|capture`")
    return 2


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #

def get_version() -> str:
    """Resolve the distribution version.

    Installed (pipx/pip): authoritative version from package metadata.
    Source checkout (no metadata): the in-tree _FALLBACK_VERSION.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("crumb-kit")
        except PackageNotFoundError:
            return _FALLBACK_VERSION
    except Exception:  # pragma: no cover - importlib.metadata always present on 3.8+
        return _FALLBACK_VERSION


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


class _BreadcrumbsParser(argparse.ArgumentParser):
    """Top-level parser that keeps global flags working in any position."""

    def parse_known_args(self, args=None, namespace=None):
        ns, argv = super().parse_known_args(args, namespace)
        for dest, default in _GLOBAL_FLAG_DEFAULTS.items():
            if not hasattr(ns, dest):
                setattr(ns, dest, default)
        return ns, argv


def build_parser() -> argparse.ArgumentParser:
    # Parent parser holds the global flags so every subcommand inherits them.
    # default=SUPPRESS is load-bearing — see _BreadcrumbsParser above.
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                               help="machine-readable JSON output")
    global_parser.add_argument("--plain", action="store_true", default=argparse.SUPPRESS,
                               help="plain-text output (no decoration)")
    global_parser.add_argument("--verbose", action="store_true", default=argparse.SUPPRESS,
                               help="verbose output")
    global_parser.add_argument("--project", metavar="PATH", default=argparse.SUPPRESS,
                               help="project root (default: cwd)")

    parser = _BreadcrumbsParser(
        prog="crumb",
        description="Breadcrumbs — a repo-local ledger of durable project state you and your agents can follow back.",
        parents=[global_parser],
    )
    parser.add_argument(
        "--version",
        action="version",
        version=(
            f"breadcrumbs {get_version()} "
            f"(record schema_version {SCHEMA_VERSION})"
        ),
        help="show version and record schema_version, then exit",
    )
    # Subparsers are plain ArgumentParsers (not _BreadcrumbsParser) so the global
    # backfill runs only once, at the top level — never in a copied-back sub-namespace.
    sub = parser.add_subparsers(dest="command", metavar="<command>",
                                parser_class=argparse.ArgumentParser)

    # init
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
    # Integration flags (review §7). Tri-state: unset -> prompt on a TTY / off when
    # non-interactive; --with-* enables; --no-* disables. set_defaults keeps all three
    # at None so default `crumb init` is byte-identical to before.
    p_init.add_argument("--with-adapter", dest="adapter", nargs="?", const="*",
                        metavar="FILES",
                        help="inject the signpost block into detected agent-guidance "
                             "files (optional: comma-separated list)")
    p_init.add_argument("--no-adapter", dest="adapter", action="store_const", const=False,
                        help="do not touch agent-guidance files")
    p_init.add_argument("--with-mcp", dest="mcp", action="store_const", const=True,
                        help="register the MCP server in .mcp.json")
    p_init.add_argument("--no-mcp", dest="mcp", action="store_const", const=False,
                        help="do not register the MCP server")
    p_init.add_argument("--with-hooks", dest="hooks", nargs="?", const="*",
                        metavar="EVENTS",
                        help="install Claude Code hooks (optional: comma list of "
                             "session,guard,capture)")
    p_init.add_argument("--no-hooks", dest="hooks", action="store_const", const=False,
                        help="do not install hooks")
    p_init.add_argument("--print-integrations", action="store_true",
                        help="show which integrations would be applied, then exit")
    p_init.add_argument("--remove-integrations", action="store_true",
                        help="reverse every breadcrumbs integration, then exit")
    p_init.set_defaults(func=cmd_init, adapter=None, mcp=None, hooks=None)

    # validate (Phase 2)
    p_validate = sub.add_parser(
        "validate",
        parents=[global_parser],
        help="deterministically check the .project-memory/ store (plan §16)",
    )
    p_validate.set_defaults(func=cmd_validate)

    # remember decision | attempt (Phase 3)
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
            help="set a body section, e.g. --set Context 'why this came up' (repeatable)",
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
        pr.add_argument("--agent", default="human", help="record author label (default: human)")
        if rtype == "attempt":
            # The fixed attempt vocabulary as named flags (review §6.2/§8); each
            # overrides the matching --set heading.
            pr.add_argument("--problem", help="Problem section")
            pr.add_argument("--tried", help="Tried section")
            pr.add_argument("--result", help="Result section")
            pr.add_argument("--why", help="'Why It Failed / Succeeded' section")
            pr.add_argument("--do-not-retry", dest="do_not_retry",
                            help="'Do Not Retry Unless' section")
            pr.add_argument("--related", help="'Related Records' section")
        pr.set_defaults(func=cmd_remember)

    # schema introspection (review §6.2/§8)
    p_schema = sub.add_parser(
        "schema",
        parents=[global_parser],
        help="print the record schema contract (or a fill-in template)",
    )
    p_schema.add_argument(
        "schema_type", nargs="?", metavar="<type>",
        help="limit to one record type (decision|attempt|verification|session|idea)",
    )
    p_schema.add_argument(
        "--template", action="store_true",
        help="emit a copy-pasteable `crumb remember <type>` command skeleton",
    )
    p_schema.set_defaults(func=cmd_schema)

    # note question|trap|idea (review §6.6 write-surface)
    p_note = sub.add_parser(
        "note",
        parents=[global_parser],
        help="leave an open question, known trap, or idea for the next agent",
    )
    p_note.set_defaults(func=cmd_note, note_kind=None)
    note_sub = p_note.add_subparsers(dest="note_kind", metavar="<kind>")

    pq = note_sub.add_parser("question", parents=[global_parser],
                             help="record an open question")
    pq.add_argument("text", help="the question, in one line")
    pq.add_argument("--why", help="why it matters / what is blocked")
    pq.add_argument("--needs", help="human input | investigation | a decision")
    pq.add_argument("--status", default="open", help="status (default: open)")
    pq.set_defaults(func=cmd_note)

    pt = note_sub.add_parser("trap", parents=[global_parser],
                             help="record a reusable known trap")
    pt.add_argument("text", help="one-line trap summary")
    pt.add_argument("--slug", help="short slug (derived from the summary if omitted)")
    pt.add_argument("--area", help="where this bites (files / area)")
    pt.add_argument("--symptom", help="what goes wrong")
    pt.add_argument("--why", help="the mechanism, not vibes")
    pt.add_argument("--safe", help="the safe approach to use instead")
    pt.add_argument("--verify", help="a command that proves it is OK")
    pt.set_defaults(func=cmd_note)

    pi = note_sub.add_parser("idea", parents=[global_parser],
                             help="record a speculative idea")
    pi.add_argument("text", help="the idea title")
    pi.add_argument("--set", nargs=2, action="append", metavar=("HEADING", "TEXT"),
                    help="set an idea body section (repeatable)")
    pi.add_argument("--tags", help="comma-separated tags")
    pi.add_argument("--agent", default="human", help="note author label (default: human)")
    pi.set_defaults(func=cmd_note)

    # verify (review F1) — record a verification result (a finding about reality)
    p_verify = sub.add_parser(
        "verify",
        parents=[global_parser],
        help="record a verification result (checked X; status fixed/open/regressed/…)",
    )
    p_verify.add_argument(
        "subject", nargs="?", default=None,
        metavar="SUBJECT",
        help="what was checked — a finding id, file, or claim (prompted if omitted in a TTY)",
    )
    p_verify.add_argument(
        "--status", required=True, choices=VALID_VERIFICATION_OUTCOME,
        help="the verification outcome",
    )
    p_verify.add_argument(
        "--method", choices=VALID_VERIFICATION_METHOD,
        help="how it was checked (static|runtime|test)",
    )
    p_verify.add_argument("--note", help="free-text notes / what the evidence shows")
    p_verify.add_argument(
        "--evidence", nargs=2, action="append", metavar=("TYPE", "REF"),
        help="add an evidence pointer, e.g. --evidence file path/to/file.py:170 (repeatable)",
    )
    p_verify.add_argument("--tags", help="comma-separated tags")
    p_verify.add_argument("--confidence", choices=("low", "medium", "high"))
    p_verify.add_argument("--agent", default="human", help="record author label (default: human)")
    p_verify.set_defaults(func=cmd_verify)

    # mark-status (review #3 R25) — record lifecycle mutation from the CLI
    p_mark = sub.add_parser(
        "mark-status",
        parents=[global_parser],
        help="change a record's status (stale/disputed/superseded/…), validate-gated",
    )
    p_mark.add_argument("record_id", metavar="ID", help="record id, e.g. dec_20260510_markdown-source-of-truth")
    p_mark.add_argument("new_status", metavar="STATUS", choices=VALID_STATUS,
                        help=f"new status ({', '.join(VALID_STATUS)})")
    p_mark.add_argument("--reason", default="",
                        help="why the status changed (recorded as a trailing comment)")
    p_mark.add_argument("--superseded-by", dest="superseded_by", default=None, metavar="ID",
                        help="the replacing record's id (required by validate when "
                             "marking superseded)")
    p_mark.add_argument("--agent", default="human", help="author label (default: human)")
    p_mark.set_defaults(func=cmd_mark_status)

    # reindex (review F2) — explicit projection refresh (mutations reindex automatically)
    p_reindex = sub.add_parser(
        "reindex",
        parents=[global_parser],
        help="rebuild generated/ projections from the canonical records",
    )
    p_reindex.set_defaults(func=cmd_reindex)

    # capture session (Phase 3)
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
    p_session.add_argument("--fast", action="store_true", help="git snapshot + --next only; no prompts, no LLM")
    p_session.add_argument("--next", dest="next_action", help="the Next Action (required on --fast)")
    p_session.add_argument("--title", help="session topic (default: 'session')")
    p_session.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("HEADING", "TEXT"),
        help="override a session body section (repeatable)",
    )
    p_session.add_argument("--focus", help="Current Focus for handoff/current (default: Next Action)")
    p_session.add_argument("--agent", default="human", help="session author label (default: human)")
    p_session.set_defaults(func=cmd_capture_session)

    # resume (Phase 4)
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
        help=f"aged-unresolved threshold in days (default: {STALE_AGE_DAYS})",
    )
    p_resume.add_argument(
        "--task",
        default=None,
        metavar="TEXT",
        help="resume FOR this task: scope likely-files to matching records (review F4); "
             "a task-scoped packet prints only and does not overwrite the committed snapshot",
    )
    p_resume.set_defaults(func=cmd_resume)

    # search (Phase 5) — deterministic exact/keyword/tag/file lookup
    p_search = sub.add_parser(
        "search",
        parents=[global_parser],
        help="deterministic keyword/tag/file search over records (no embeddings)",
    )
    p_search.add_argument("query", nargs="?", default="", help="search text (optional with filters)")
    p_search.add_argument("--type", choices=("decision", "attempt", "verification", "trap", "question"))
    p_search.add_argument("--status", help="filter by record status (e.g. active, superseded; "
                                            "for verifications: the outcome, e.g. open/fixed)")
    p_search.add_argument("--tag", help="filter by tag/component")
    p_search.add_argument("--file", help="filter by file path referenced in a record")
    p_search.add_argument("--stale-days", type=int, default=None, metavar="N")
    p_search.set_defaults(func=cmd_search)

    # guard (Phase 5) — guard-before-action: warn before repeating a mistake
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
        help=f"recency de-weighting threshold in days (default: {STALE_AGE_DAYS})",
    )
    p_guard.set_defaults(func=cmd_guard)

    # audit (Phase 6) — heuristic stale/unsafe/bloated detection (does NOT gate validate)
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
        help=f"aged-unresolved threshold in days (default: {STALE_AGE_DAYS})",
    )
    p_audit.set_defaults(func=cmd_audit)

    # scan-secrets (Phase 6) — the secret sub-check as a standalone command
    p_scan = sub.add_parser(
        "scan-secrets",
        parents=[global_parser],
        help="scan committed memory for secret-like strings (run before committing memory)",
    )
    p_scan.set_defaults(func=cmd_scan_secrets)

    # mcp serve|register — surface the optional MCP server from the CLI (review §6.3)
    p_mcp = sub.add_parser(
        "mcp",
        parents=[global_parser],
        help="run or register the optional breadcrumbs MCP server",
    )
    p_mcp.set_defaults(func=cmd_mcp, mcp_what=None)
    mcp_sub = p_mcp.add_subparsers(dest="mcp_what", metavar="<what>")
    p_mcp_serve = mcp_sub.add_parser(
        "serve", parents=[global_parser],
        help="run the MCP server over stdio (needs the [mcp] extra)",
    )
    p_mcp_serve.set_defaults(func=cmd_mcp, mcp_what="serve")
    p_mcp_register = mcp_sub.add_parser(
        "register", parents=[global_parser],
        help="add the breadcrumbs server to .mcp.json (preserves other servers)",
    )
    p_mcp_register.set_defaults(func=cmd_mcp, mcp_what="register")
    p_mcp_doctor = mcp_sub.add_parser(
        "doctor", parents=[global_parser],
        help="report MCP wiring: [mcp] extra, .mcp.json registration",
    )
    p_mcp_doctor.set_defaults(func=cmd_mcp, mcp_what="doctor")

    # doctor — integration health (review §A.7)
    p_doctor = sub.add_parser(
        "doctor",
        parents=[global_parser],
        help="report whether memory is actually wired up (adapter/mcp/hooks/packet)",
    )
    p_doctor.set_defaults(func=cmd_doctor)

    # hook session|guard|capture — harness translation layer (review §A.6)
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

    return parser


def _capture_dispatch(args: argparse.Namespace) -> int:
    """`crumb capture` with no subcommand -> guidance."""
    if getattr(args, "capture_what", None) is None:
        _emit_error(args, "specify what to capture: `crumb capture session`")
        return 2
    return cmd_capture_session(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 0
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        # Expected, user-facing failures (missing template/package, permissions,
        # unrepresentable values) surface as a clean error + nonzero exit rather
        # than a raw traceback. Programming errors still propagate.
        _emit_error(args, str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
