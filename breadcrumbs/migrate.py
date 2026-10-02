"""breadcrumbs — store-format migrations (WM-01).

`SCHEMA_VERSION` in `cli.py` is the on-disk record format version. Through 0.2.0
it had never moved, and there was no machinery to move it: every store-format
change would have been a breaking change for every store already on disk. This
module is that machinery.

**The contract.**

- A migration numbered `n` upgrades a store at `schema_version n-1` to `n`. They
  run in order, one at a time, and each writes the manifest before the next
  starts — so a failure halfway leaves the store at the last version that
  actually completed, never at a version whose step did not finish.
- **Migrations are idempotent.** Re-running a completed step must be a no-op.
  The version in the manifest is the gate, but a step that re-runs (a crash
  between the step and the manifest write, a hand-edited manifest) must not
  corrupt anything.
- **Readers tolerate both shapes for one major version.** A migration that
  changes where data lives ships alongside readers that accept the old location,
  so a store that has not migrated yet still works. Say so in the step's
  docstring, and name the readers.
- **Nothing is deleted without a backup.** See `backup_store`.

**Operator guarantees (audit WP21).**

- **Preview.** `--dry-run` lists the steps, what the backup will hold, and
  the legacy metadata migration will *not* touch (`legacy_report`): invalid
  values are reported for a person to fix, never rewritten automatically.
- **A verified backup.** The backup carries `backup-manifest.json` (a SHA-256
  per file), and it is re-read and checked against the store before any step
  runs. A backup that does not verify stops the migration.
- **Interruption.** `private/migrations/in-progress.json` names the backup and
  the steps done. A migration that stopped (a crash, a failed step) resumes on
  the next `crumb migrate` from the last completed version, against the same
  pre-migration backup.
- **Restore.** `crumb migrate --restore [BACKUP]` checks the backup against its
  manifest, puts the committed store back exactly as it was, and checks the
  result. `--dry-run` with it lists what would change.
- **Stable ids, kept content.** No step renames a record, and every step keeps
  frontmatter keys it does not know.

Migrations never touch `private/` or `index/`: both are machine-local and
disposable, so there is nothing there another checkout could disagree about.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Callable, NamedTuple

from breadcrumbs import cli, path_policy

# Directories a backup skips: machine-local (`private/`) or disposable
# (`index/`). Also where the backups themselves live, so a second migration
# cannot recurse into the first one's copy.
_BACKUP_SKIP_DIRS = ("private", "index")

# In a backup directory: every file's SHA-256, written after the copy, so the
# backup can be verified before a migration relies on it and before a restore.
BACKUP_MANIFEST = "backup-manifest.json"
BACKUPS_RELPATH = ("private", "migrations")
IN_PROGRESS_RELPATH = ("private", "migrations", "in-progress.json")


class BackupUnverified(Exception):
    """A backup that does not match what it claims to hold."""


class BackupFailed(BackupUnverified):
    """A backup that could not be written at all (a path too long, a full disk).

    The partial copy is removed before this is raised, so a failed attempt
    leaves nothing behind under `private/migrations/`."""


class Migration(NamedTuple):
    """One ordered, idempotent step from `version - 1` to `version`.

    `summary` is what `--dry-run` prints, so it says what the step will do in the
    imperative, not what it did. `apply` returns the lines describing what it
    actually changed — empty when there was nothing to do, which is the normal
    result of re-running a completed step.
    """

    version: int
    summary: str
    apply: Callable[[Path, Path], list[str]]


# --------------------------------------------------------------------------- #
# The steps
# --------------------------------------------------------------------------- #


def _m2_inbox_directories(memory_dir: Path, project_root: Path) -> list[str]:
    """schema 2 — add `inbox/` and `private/inbox/` (WM-03, the jot tier).

    Creating directories only: no record moves, nothing rewritten. Readers
    (`breadcrumbs.inbox.inbox_dirs`, `cli.load_records`) already treat a missing
    inbox directory as "no jots", so a store that never migrates keeps working
    and simply has nowhere to put a jot.
    """
    changed: list[str] = []
    committed = memory_dir / "inbox"
    if not committed.is_dir():
        path_policy.mkdirs(committed)
        cli.write_text_atomic(committed / ".gitkeep", "")
        changed.append("created inbox/ (committed jots)")
    private = memory_dir / "private" / "inbox"
    if not private.is_dir():
        path_policy.mkdirs(private)
        changed.append("created private/inbox/ (machine-local jots)")
    return changed


def _m3_traps_and_questions_as_files(memory_dir: Path, project_root: Path) -> list[str]:
    """schema 3 — one file per trap and per question (WM-22).

    Every `## trap_…` block in known-traps.md becomes `traps/<slug>.md` and every
    `## Q:` block in open-questions.md becomes `questions/<slug>.md`. Ids are
    kept exactly: they are cited in decision records and commit messages. Every
    line of every block is kept too — content bullets become sections,
    bookkeeping bullets become frontmatter, and anything else (free prose,
    status-change provenance comments) becomes the file's `Notes` section.

    The two singletons are then rewritten as generated one-line-per-record
    indexes, so a cloud agent reading them without the CLI still finds every
    trap and question. Readers switch on the manifest version, not on what is
    on disk, so a store stopped halfway still reads its blocks.

    Idempotent: an existing file is never overwritten, and on a store with no
    blocks left (already migrated) the step only rewrites the indexes. If the
    written files fail validation, they are removed and the step raises, leaving
    the store at schema 2 exactly as it was.
    """
    from breadcrumbs import blockfiles

    return blockfiles.migrate_blocks_to_files(memory_dir, project_root)


def _m4_branch_handoffs(memory_dir: Path, project_root: Path) -> list[str]:
    """schema 4 — add `handoffs/` for one handoff per branch (WM-50).

    Creates the directory only. `handoff.md` is untouched: it stays the default
    branch's handoff, and a branch handoff is written the first time a session
    captures on a feature branch. Readers (`breadcrumbs.handoffs`) fall back to
    `handoff.md` whenever a branch has no file of its own, so a store that never
    migrates keeps its single handoff.
    """
    changed: list[str] = []
    directory = memory_dir / "handoffs"
    if not directory.is_dir():
        path_policy.mkdirs(directory)
        changed.append("created handoffs/ (one handoff per non-default branch)")
    keep = directory / ".gitkeep"
    if not keep.exists():
        cli.write_text_atomic(keep, "")
    return changed


MIGRATIONS: list[Migration] = [
    Migration(2, "add inbox/ and private/inbox/ for the jot tier", _m2_inbox_directories),
    Migration(
        3,
        "move traps and questions to one file each; known-traps.md and "
        "open-questions.md become generated indexes",
        _m3_traps_and_questions_as_files,
    ),
    Migration(4, "add handoffs/ for one handoff per branch", _m4_branch_handoffs),
]


# --------------------------------------------------------------------------- #
# Version reading + writing
# --------------------------------------------------------------------------- #


def store_schema_version(memory_dir: Path) -> int | None:
    """The store's `schema_version`, or None when there is no readable manifest.

    A manifest with no `schema_version` key reads as 1: that is what every store
    written before the key could be absent actually is, and guessing higher would
    skip a migration that store needs.
    """
    manifest = cli.load_manifest(Path(memory_dir))
    if manifest is None:
        return None
    raw = str(manifest.get("schema_version", "1")).strip()
    try:
        return int(raw)
    except ValueError:
        return None


def set_manifest_version(memory_dir: Path, version: int) -> None:
    """Rewrite the manifest's `schema_version:` line in place, atomically.

    Line-level rewrite rather than a re-render: `manifest.yml` carries the
    explanatory comments `init` wrote and any key a later version added, and
    re-rendering it from `manifest_content` would drop everything this build does
    not know about. A manifest with no `schema_version` line gets one prepended,
    because that is where `manifest_content` puts it.
    """
    path = Path(memory_dir) / "manifest.yml"
    text = cli.read_text_lenient(path)[0] if path.is_file() else ""
    lines = text.splitlines()
    out: list[str] = []
    replaced = False
    for line in lines:
        if not replaced and line.strip().split(":", 1)[0].strip() == "schema_version":
            out.append(f"schema_version: {version}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.insert(0, f"schema_version: {version}")
    cli.write_text_atomic(path, "\n".join(out).rstrip("\n") + "\n")


def set_manifest_field(memory_dir: Path, key: str, value: str, comment: str = "") -> None:
    """Set one top-level `key: value` line in manifest.yml, keeping every other
    line (comments, keys this build does not know). A missing key is appended,
    after `comment` when one is given."""
    path = Path(memory_dir) / "manifest.yml"
    text = cli.read_text_lenient(path)[0] if path.is_file() else ""
    out: list[str] = []
    replaced = False
    for line in text.splitlines():
        if (
            not replaced
            and not line.startswith((" ", "\t", "#"))
            and line.split(":", 1)[0].strip() == key
        ):
            out.append(f"{key}: {value}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if comment:
            out.append(f"# {comment}")
        out.append(f"{key}: {value}")
    cli.write_text_atomic(path, "\n".join(out).rstrip("\n") + "\n")


# --------------------------------------------------------------------------- #
# Store maintenance: template files and the minimum writer version
# --------------------------------------------------------------------------- #

# Files `crumb init` copies from the template tree that explain the store.
TEMPLATE_FILES = ("README.md", "generated/README.md", "index/README.md", "private/README.md")
# The scaffold 0.1.7 and earlier made, which nothing has read since.
LEGACY_REFS = "evidence/refs.yml"


def _template_hash(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def maintenance(memory_dir: Path, *, dry_run: bool) -> dict:
    """Bring a store's template files and writer floor up to this build.

    `{changes, warnings}`; nothing is written when `dry_run`. Runs after a
    migration and on a store that is already current (DoWhat retest of 0.5.0,
    items 12 and 14):

    - a template file (`TEMPLATE_FILES`) still byte-identical to a version
      crumb-kit shipped is replaced by the current one; an edited one is kept,
      with a warning. After the DoWhat migration the store README still said
      traps live in `known-traps.md`, by then a generated index.
    - `evidence/refs.yml` is removed when it is the untouched scaffold, and
      named when someone added to it.
    - `min_crumb_version` is raised to `compat.MIN_SAFE_WRITER` (never
      lowered) and `requires:` gains `min-crumb-version`, so builds that
      predate the field refuse to write too (decision D14).
    """
    from breadcrumbs import compat, template_history

    memory_dir = Path(memory_dir)
    changes: list[str] = []
    warnings: list[str] = []
    for rel in TEMPLATE_FILES:
        target = memory_dir / rel
        template = cli.TEMPLATE_DIR / rel
        if not (target.is_file() and template.is_file()):
            continue
        try:
            current = path_policy.read_bytes(target)
        except OSError as exc:
            warnings.append(f"{rel}: not checked ({exc})")
            continue
        new = template.read_bytes()
        have = _template_hash(current)
        if have == _template_hash(new):
            continue
        if have in template_history.SHIPPED.get(rel, frozenset()):
            changes.append(
                f"{rel}: replaced with the current template (it was an unedited older one)"
            )
            if not dry_run:
                cli.write_text_atomic(target, new.decode("utf-8"))
        else:
            warnings.append(
                f"{rel}: kept as it is: it was edited, so it may describe the store as it used "
                f"to be. Compare it with the current template ({template.as_posix()})."
            )
    refs = memory_dir / LEGACY_REFS
    if refs.is_file():
        try:
            unchanged = _template_hash(path_policy.read_bytes(refs)) in (
                template_history.SHIPPED.get(LEGACY_REFS, frozenset())
            )
        except OSError:
            unchanged = False
        if unchanged:
            changes.append(
                f"{LEGACY_REFS}: removed (the unedited 0.1.x scaffold; nothing reads it)"
            )
            if not dry_run:
                refs.unlink()
                with contextlib.suppress(OSError):
                    refs.parent.rmdir()
        else:
            warnings.append(
                f"{LEGACY_REFS}: kept: someone added to it, but nothing has read it since 0.1.7. "
                "Cite what matters with `--evidence` on the records it concerns, then delete it."
            )
    manifest = cli.load_manifest(memory_dir) or {}
    raw_min = manifest.get(compat.MIN_VERSION_KEY)
    floor = compat.parse_version(compat.MIN_SAFE_WRITER)
    have_min = compat.parse_version(raw_min) if raw_min not in (None, "") else None
    if raw_min not in (None, "") and have_min is None:
        warnings.append(
            f"manifest.yml: {compat.MIN_VERSION_KEY} {raw_min!r} is unreadable; left as it is"
        )
    elif have_min is None or have_min < floor:
        changes.append(
            f"manifest.yml: {compat.MIN_VERSION_KEY}: {compat.MIN_SAFE_WRITER} (older crumb-kit "
            "builds refuse to write this store)"
        )
        if not dry_run:
            set_manifest_field(
                memory_dir,
                compat.MIN_VERSION_KEY,
                compat.MIN_SAFE_WRITER,
                "Oldest crumb-kit allowed to write this store (set by `crumb migrate`; "
                "docs/compatibility.md section 4).",
            )
    features = compat.parse_features(manifest.get(compat.REQUIRES_KEY))
    if compat.MIN_VERSION_FEATURE not in features:
        wanted = sorted({*features, compat.MIN_VERSION_FEATURE})
        changes.append(
            f"manifest.yml: requires: {', '.join(wanted)} (so 0.4.x and 0.5.0, which predate "
            f"{compat.MIN_VERSION_KEY}, refuse to write too)"
        )
        if not dry_run:
            set_manifest_field(memory_dir, compat.REQUIRES_KEY, ", ".join(wanted))
    return {"changes": changes, "warnings": warnings}


# --------------------------------------------------------------------------- #
# Backups
# --------------------------------------------------------------------------- #


def backup_store(memory_dir: Path) -> Path:
    """Copy the whole committed store under `private/migrations/<timestamp>/`,
    then verify the copy (audit WP21). Raises `BackupUnverified` if it differs.

    **The whole store, not the files a step declares it will touch.** A step that
    under-declares its paths is a silent data-loss bug that only shows up on
    somebody else's store, and the thing being copied is a few hundred kilobytes
    of markdown. The cost of over-copying is a directory nobody reads; the cost
    of under-copying is unrecoverable.

    It lands under `private/`, which is gitignored, so a backup is never
    committed and never leaks a local-private record into a shared history.
    """
    memory_dir = Path(memory_dir)
    stamp = cli.now_iso().replace(":", "").replace("-", "")[:15]
    dest = memory_dir.joinpath(*BACKUPS_RELPATH) / stamp
    n = 1
    while dest.exists():  # two migrations in one second each get their own
        n += 1
        dest = memory_dir.joinpath(*BACKUPS_RELPATH) / f"{stamp}-{n}"
    path_policy.mkdirs(dest)
    try:
        for entry in sorted(memory_dir.iterdir()):
            if entry.name in _BACKUP_SKIP_DIRS:
                continue
            target = dest / entry.name
            # Links are copied as links, never followed (audit F17); the driver
            # refuses a store with any, so this is the second line.
            if entry.is_symlink():
                continue
            if entry.is_dir():
                _copytree(entry, target)
            elif entry.is_file():
                _copy2(entry, target)
    except OSError as exc:  # shutil.Error is an OSError
        _discard(dest)
        raise BackupFailed(
            f"the backup could not be written to {_rel(dest, memory_dir)}: "
            + path_policy.describe_copy_error(exc, memory_dir)
        ) from None
    source = store_files(memory_dir)
    doc = {
        "format": 1,
        "created_at": cli.now_iso(),
        "schema_version": store_schema_version(memory_dir),
        "files": source,
    }
    cli.write_text_atomic(dest / BACKUP_MANIFEST, json.dumps(doc, indent=1, sort_keys=True) + "\n")
    problems = verify_backup(dest)
    if problems:
        raise BackupUnverified(
            f"the backup at {_rel(dest, memory_dir)} does not match the store: "
            + "; ".join(problems[:5])
        )
    return dest


def store_files(directory: Path) -> dict[str, str]:
    """`{relative path: sha256}` for every file of a committed store (or of a
    backup of one), skipping `private/`, `index/` and the backup manifest.
    Links are never followed or listed."""
    directory = Path(directory)
    # Walked through the extended-length form on Windows, so a deep store or
    # backup is hashed rather than reported missing (issue 5); elsewhere this
    # is the plain path and files are read under the store's link policy.
    top = path_policy.extended_path(directory)
    windows = top != os.fspath(directory)
    out: dict[str, str] = {}
    for dirpath, dirnames, filenames in os.walk(top, followlinks=False):
        rel_parts = [p for p in dirpath[len(top) :].replace("\\", "/").split("/") if p]
        if not rel_parts:
            dirnames[:] = [d for d in dirnames if d not in _BACKUP_SKIP_DIRS]
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for name in filenames:
            full = os.path.join(dirpath, name)
            rel = "/".join([*rel_parts, name])
            if os.path.islink(full) or rel == BACKUP_MANIFEST:
                continue
            if windows:
                with open(full, "rb") as fh:
                    data = fh.read()
            else:
                data = path_policy.read_bytes(Path(full))
            out[rel] = hashlib.sha256(data).hexdigest()
    return dict(sorted(out.items()))


def verify_backup(backup: Path) -> list[str]:
    """What is wrong with a backup, or `[]`: every file its manifest lists is
    present with that hash, and nothing else is there."""
    backup = Path(backup)
    try:
        expected = json.loads(path_policy.read_text(backup / BACKUP_MANIFEST))["files"]
    except Exception:
        expected = None
    if not isinstance(expected, dict):
        return [f"{BACKUP_MANIFEST} is missing or unreadable (made by crumb-kit 0.3.1 or earlier?)"]
    actual = store_files(backup)
    problems = [f"{rel} is missing" for rel in expected if rel not in actual]
    problems += [
        f"{rel} differs" for rel in expected if rel in actual and actual[rel] != expected[rel]
    ]
    problems += [f"{rel} is not in the manifest" for rel in actual if rel not in expected]
    return problems


def _copytree(src: Path, dst: Path) -> None:
    shutil.copytree(
        path_policy.extended_path(src),
        path_policy.extended_path(dst),
        symlinks=True,
        dirs_exist_ok=True,
    )


def _copy2(src: Path, dst: Path) -> None:
    shutil.copy2(
        path_policy.extended_path(src), path_policy.extended_path(dst), follow_symlinks=False
    )


def _discard(path: Path) -> None:
    shutil.rmtree(path_policy.extended_path(path), ignore_errors=True)


def _rel(path: Path, memory_dir: Path) -> str:
    try:
        return Path(path).relative_to(Path(memory_dir).parent).as_posix()
    except ValueError:
        return Path(path).name


def _in_progress_path(memory_dir: Path) -> Path:
    return Path(memory_dir).joinpath(*IN_PROGRESS_RELPATH)


def in_progress(memory_dir: Path) -> dict | None:
    """The marker of a migration that started and did not finish, or None."""
    try:
        doc = json.loads(path_policy.read_text(_in_progress_path(memory_dir)))
    except Exception:
        return None
    return doc if isinstance(doc, dict) and doc.get("backup") else None


def _write_in_progress(memory_dir: Path, doc: dict) -> None:
    path = _in_progress_path(memory_dir)
    path_policy.mkdirs(path.parent)
    cli.write_text_atomic(path, json.dumps(doc, indent=1, sort_keys=True) + "\n")


def _clear_in_progress(memory_dir: Path) -> None:
    try:
        _in_progress_path(memory_dir).unlink()
    except FileNotFoundError:
        pass


def latest_backup(memory_dir: Path) -> Path | None:
    """The interrupted migration's backup, else the newest verified-format one."""
    marker = in_progress(memory_dir)
    if marker:
        return Path(memory_dir).parent / marker["backup"]
    root = Path(memory_dir).joinpath(*BACKUPS_RELPATH)
    if not root.is_dir():
        return None
    candidates = sorted(p for p in root.iterdir() if (p / BACKUP_MANIFEST).is_file())
    return candidates[-1] if candidates else None


def restore(memory_dir: Path, backup: Path | None = None, *, dry_run: bool = False) -> dict:
    """Put the committed store back exactly as `backup` holds it (audit WP21).

    Returns `{ok, backup, changed, schema_version, error}`. `changed` lists the
    store-relative files that differ (added, removed or altered by the restore).
    The backup is verified against its manifest first, and the store against
    the manifest afterwards; `private/` and `index/` are never touched.
    """
    memory_dir = Path(memory_dir)
    backup = Path(backup) if backup is not None else latest_backup(memory_dir)
    base = {"ok": False, "backup": None, "changed": [], "schema_version": None, "error": None}
    if backup is None or not backup.is_dir():
        return {**base, "error": "no migration backup found under private/migrations/"}
    if not backup.is_absolute():
        backup = (Path.cwd() / backup).resolve()
    shown = _rel(backup, memory_dir)
    problems = verify_backup(backup)
    if problems:
        return {
            **base,
            "backup": shown,
            "error": f"the backup at {shown} does not verify: " + "; ".join(problems[:5]),
        }
    saved = json.loads(path_policy.read_text(backup / BACKUP_MANIFEST))["files"]
    current = store_files(memory_dir)
    changed = sorted(r for r in set(current) | set(saved) if current.get(r) != saved.get(r))
    if dry_run:
        return {**base, "ok": True, "backup": shown, "changed": changed, "dry_run": True}
    links = path_policy.find_links(memory_dir)
    if links:
        return {
            **base,
            "backup": shown,
            "error": "the store contains links: " + ", ".join(links[:10]),
        }
    # Copy the backup next to the store first, and only then swap it in: the
    # store used to be emptied before the copy, so a copy that failed part-way
    # (a long path, a full disk) left it half gone (field report 2026-10-01, N9).
    stamp = cli.now_iso().replace(":", "").replace("-", "")[:15]
    staging = memory_dir.joinpath(*BACKUPS_RELPATH) / f".restoring-{stamp}"
    _discard(staging)
    path_policy.mkdirs(staging)
    try:
        for entry in sorted(backup.iterdir()):
            if entry.name == BACKUP_MANIFEST:
                continue
            if entry.is_dir():
                _copytree(entry, staging / entry.name)
            else:
                _copy2(entry, staging / entry.name)
    except OSError as exc:
        _discard(staging)
        return {
            **base,
            "backup": shown,
            "changed": changed,
            "error": "the backup could not be copied back, so nothing was changed: "
            + path_policy.describe_copy_error(exc, backup),
        }
    for entry in sorted(memory_dir.iterdir()):
        if entry.name in _BACKUP_SKIP_DIRS:
            continue
        if entry.is_dir():
            shutil.rmtree(path_policy.extended_path(entry))
        else:
            entry.unlink()
    for entry in sorted(staging.iterdir()):
        os.replace(
            path_policy.extended_path(entry), path_policy.extended_path(memory_dir / entry.name)
        )
    _discard(staging)
    after = store_files(memory_dir)
    if after != saved:
        bad = sorted(r for r in set(after) | set(saved) if after.get(r) != saved.get(r))
        return {
            **base,
            "backup": shown,
            "changed": changed,
            "error": "the restored store does not match the backup: " + ", ".join(bad[:10]),
        }
    _clear_in_progress(memory_dir)
    return {
        **base,
        "ok": True,
        "backup": shown,
        "changed": changed,
        "schema_version": store_schema_version(memory_dir),
    }


def simulate(memory_dir: Path, pending: list[Migration]) -> tuple[list[dict], dict | None]:
    """Run `pending` against a scratch copy of the store; nothing real is touched.

    Returns `(steps, blocker)`: each step's `{version, summary, changed}` as the
    real run would report it, and `{version, error}` for the first step that
    would fail (None when every step would succeed). The copy is made with the
    same rules as the backup — committed store only, no `private/` or `index/`
    — so the steps see exactly what they will see for real.
    """
    import tempfile

    memory_dir = Path(memory_dir)
    steps: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="crumb-migrate-") as td:
        scratch_root = Path(td)
        copy = scratch_root / memory_dir.name
        path_policy.mkdirs(copy)
        try:
            for entry in sorted(memory_dir.iterdir()):
                if entry.name in _BACKUP_SKIP_DIRS or entry.is_symlink():
                    continue
                if entry.is_dir():
                    _copytree(entry, copy / entry.name)
                elif entry.is_file():
                    _copy2(entry, copy / entry.name)
        except OSError as exc:
            reason = path_policy.describe_copy_error(exc, memory_dir)
            return steps, {
                "version": pending[0].version,
                "error": f"the store could not be copied for the preview: {reason}",
            }
        for m in pending:
            try:
                changed = m.apply(copy, scratch_root)
            except Exception as exc:  # noqa: BLE001 - reported as the blocker
                steps.append({"version": m.version, "summary": m.summary, "changed": []})
                return steps, {"version": m.version, "error": str(exc)}
            set_manifest_version(copy, m.version)
            steps.append({"version": m.version, "summary": m.summary, "changed": changed})
    return steps, None


def legacy_findings(memory_dir: Path) -> tuple[dict, list[str]]:
    """`legacy_report`'s counts plus one `path: message` line per finding, so a
    preview names each record a person has to fix, not just how many."""
    counts: dict[str, int] = {}
    items: list[str] = []
    for finding in cli.run_validate(Path(memory_dir)):
        if finding.get("status") != "fail":
            continue
        code = finding.get("code") or finding.get("check")
        if code in ("schema-version", "manifest"):
            continue
        counts[code] = counts.get(code, 0) + 1
        items.append(f"{finding.get('path') or '(store)'}: {finding.get('message')}")
    return dict(sorted(counts.items())), items


def legacy_report(memory_dir: Path) -> dict:
    """What a migration leaves as it is, for a person to decide (audit WP21).

    `{code: count}` of record-contract findings (`record-schema.md` §4): free
    scopes, invalid confidence, malformed evidence, dangling `superseded_by`,
    and the rest. A migration never rewrites these: guessing what a free
    `scope` meant, or raising a confidence, would be inventing facts. Unknown
    frontmatter keys are not listed; they are kept by every step and writer.
    """
    counts: dict[str, int] = {}
    for finding in cli.run_validate(Path(memory_dir)):
        if finding.get("status") != "fail":
            continue
        code = finding.get("code") or finding.get("check")
        if code in ("schema-version", "manifest"):
            continue
        counts[code] = counts.get(code, 0) + 1
    return dict(sorted(counts.items()))


# --------------------------------------------------------------------------- #
# The driver
# --------------------------------------------------------------------------- #


def pending_migrations(current: int) -> list[Migration]:
    """Steps between `current` and this build's `SCHEMA_VERSION`, in order."""
    return sorted(
        (m for m in MIGRATIONS if current < m.version <= cli.SCHEMA_VERSION),
        key=lambda m: m.version,
    )


def migrate(memory_dir: Path, project_root: Path, *, dry_run: bool = False) -> dict:
    """Bring a store up to this build's `SCHEMA_VERSION`.

    Returns `{ok, from, to, target, steps, backup, error}`. `to` is the version
    the store is actually at when this returns — on a failed step that is the
    last version whose migration completed, never the target.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root)
    target = cli.SCHEMA_VERSION
    current = store_schema_version(memory_dir)

    if current is None:
        return {
            "ok": False,
            "from": None,
            "to": None,
            "target": target,
            "steps": [],
            "backup": None,
            "error": "manifest.yml is missing or has an unreadable schema_version",
        }
    if current > target:
        return {
            "ok": False,
            "from": current,
            "to": current,
            "target": target,
            "steps": [],
            "backup": None,
            "error": (
                f"store is schema_version {current}; this build understands {target}. "
                "Upgrade crumb-kit — a newer store must not be downgraded."
            ),
        }

    from breadcrumbs import compat as _compat

    compatibility = _compat.check(memory_dir)
    if not compatibility.writable:
        return {
            "ok": False,
            "from": current,
            "to": current,
            "target": target,
            "steps": [],
            "backup": None,
            "error": f"{compatibility.message} Nothing was changed.",
        }

    pending = pending_migrations(current)
    if not pending:
        # A migration that finished its last step but stopped before clearing
        # its marker is complete; the marker would only mislead the next run.
        if not dry_run:
            _clear_in_progress(memory_dir)
        maint = maintenance(memory_dir, dry_run=dry_run)
        if maint["changes"] and not dry_run and (memory_dir / "generated").is_dir():
            cli.reindex_projections(memory_dir, project_root, force=True)
        return {
            "ok": True,
            "from": current,
            "to": current,
            "target": target,
            "steps": [],
            "backup": None,
            "error": None,
            "dry_run": dry_run,
            "maintenance": maint,
        }

    # A migration reads and rewrites the whole store: with a link inside it,
    # the backup would copy what the link points at and a step could write
    # through it (audit F17). Refuse before anything is touched.
    links = path_policy.find_links(memory_dir)
    if links:
        return {
            "ok": False,
            "from": current,
            "to": current,
            "target": target,
            "steps": [],
            "backup": None,
            "error": (
                "the store contains symbolic links or junctions, which it may not: "
                + ", ".join(links[:10])
                + (f" (and {len(links) - 10} more)" if len(links) > 10 else "")
                + ". Replace each with the file or directory itself, then re-run."
            ),
        }

    marker = in_progress(memory_dir)
    if dry_run:
        # The preview runs the real steps on a scratch copy, so it can only say
        # "would apply" when applying would succeed (field report 2026-10-01,
        # issue 4: a dry run passed, then step 3 failed on two trap statuses).
        steps, blocker = simulate(memory_dir, pending)
        legacy, legacy_items = legacy_findings(memory_dir)
        return {
            "ok": blocker is None,
            "from": current,
            "to": current,
            "target": target,
            "steps": steps,
            "backup": None,
            "dry_run": True,
            # What the backup will hold, and what migration leaves for a person.
            "backup_files": len(store_files(memory_dir)),
            "maintenance": maintenance(memory_dir, dry_run=True),
            "legacy": legacy,
            "legacy_items": legacy_items,
            "resumes": marker,
            "error": (
                None
                if blocker is None
                else f"the migration would stop at schema_version {blocker['version']}: "
                f"{blocker['error']}. Nothing was changed."
            ),
        }

    # A migration that stopped part-way resumes against the backup it took
    # before its first step, so `--restore` still returns to the original
    # store. A new migration takes (and verifies) a new backup.
    resumed = None
    if marker and not verify_backup(project_root / marker["backup"]):
        backup = project_root / marker["backup"]
        resumed = marker
    else:
        try:
            backup = backup_store(memory_dir)
        except BackupUnverified as exc:
            return {
                "ok": False,
                "from": current,
                "to": current,
                "target": target,
                "steps": [],
                "backup": None,
                "error": f"{exc}. Nothing was migrated.",
            }
        marker = {
            "backup": _rel(backup, memory_dir),
            "from": current,
            "target": target,
            "started_at": cli.now_iso(),
        }
    _write_in_progress(memory_dir, {**marker, "at": current})
    steps: list[dict] = []
    at = current
    for m in pending:
        try:
            changed = m.apply(memory_dir, project_root)
        except Exception as exc:  # noqa: BLE001 - a step failure is a reported result
            return {
                "ok": False,
                "from": current,
                "to": at,
                "target": target,
                "steps": steps,
                "backup": str(backup),
                "resumed": resumed,
                "error": (
                    f"migration to schema_version {m.version} failed: {exc}. The store is "
                    f"at schema_version {at}; re-run `crumb migrate` to resume, or "
                    "`crumb migrate --restore` to return to the backup."
                ),
            }
        set_manifest_version(memory_dir, m.version)
        at = m.version
        _write_in_progress(memory_dir, {**marker, "at": at})
        steps.append({"version": m.version, "summary": m.summary, "changed": changed})
    _clear_in_progress(memory_dir)
    maint = maintenance(memory_dir, dry_run=False)

    # The store's shape changed, so a projection built from the old shape is
    # suspect — but only refresh one that already exists. A migration that
    # *created* `generated/` would be inventing a committed artifact in a store
    # whose owner chose not to have one, which is a side effect no format
    # upgrade has any business causing. A store with no projection has nothing
    # to go stale. Best-effort either way: a projection that cannot be rebuilt
    # is `validate`'s finding, not a failed migration.
    if (memory_dir / "generated").is_dir():
        cli.reindex_projections(memory_dir, project_root, force=True)
    return {
        "ok": True,
        "from": current,
        "to": at,
        "target": target,
        "steps": steps,
        "backup": str(backup),
        "resumed": resumed,
        "error": None,
        "maintenance": maint,
    }
