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

Migrations never touch `private/` or `index/`: both are machine-local and
disposable, so there is nothing there another checkout could disagree about.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable, NamedTuple

from breadcrumbs import cli

# Directories a backup skips: machine-local (`private/`) or disposable
# (`index/`). Also where the backups themselves live, so a second migration
# cannot recurse into the first one's copy.
_BACKUP_SKIP_DIRS = ("private", "index")


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
        committed.mkdir(parents=True, exist_ok=True)
        (committed / ".gitkeep").write_text("", encoding="utf-8")
        changed.append("created inbox/ (committed jots)")
    private = memory_dir / "private" / "inbox"
    if not private.is_dir():
        private.mkdir(parents=True, exist_ok=True)
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
        directory.mkdir(parents=True, exist_ok=True)
        changed.append("created handoffs/ (one handoff per non-default branch)")
    keep = directory / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
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


# --------------------------------------------------------------------------- #
# Backups
# --------------------------------------------------------------------------- #


def backup_store(memory_dir: Path) -> Path:
    """Copy the whole committed store under `private/migrations/<timestamp>/`.

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
    dest = memory_dir / "private" / "migrations" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for entry in sorted(memory_dir.iterdir()):
        if entry.name in _BACKUP_SKIP_DIRS:
            continue
        target = dest / entry.name
        if entry.is_dir():
            shutil.copytree(entry, target, dirs_exist_ok=True)
        elif entry.is_file():
            shutil.copy2(entry, target)
    return dest


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

    pending = pending_migrations(current)
    if not pending:
        return {
            "ok": True,
            "from": current,
            "to": current,
            "target": target,
            "steps": [],
            "backup": None,
            "error": None,
        }

    if dry_run:
        return {
            "ok": True,
            "from": current,
            "to": current,
            "target": target,
            "steps": [{"version": m.version, "summary": m.summary, "changed": []} for m in pending],
            "backup": None,
            "dry_run": True,
            "error": None,
        }

    backup = backup_store(memory_dir)
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
                "error": f"migration to schema_version {m.version} failed: {exc}",
            }
        set_manifest_version(memory_dir, m.version)
        at = m.version
        steps.append({"version": m.version, "summary": m.summary, "changed": changed})

    # The store's shape changed, so a projection built from the old shape is
    # suspect — but only refresh one that already exists. A migration that
    # *created* `generated/` would be inventing a committed artifact in a store
    # whose owner chose not to have one, which is a side effect no format
    # upgrade has any business causing. A store with no projection has nothing
    # to go stale. Best-effort either way: a projection that cannot be rebuilt
    # is `validate`'s finding, not a failed migration.
    if (memory_dir / "generated").is_dir():
        cli.reindex_projections(memory_dir, project_root)
    return {
        "ok": True,
        "from": current,
        "to": at,
        "target": target,
        "steps": steps,
        "backup": str(backup),
        "error": None,
    }
