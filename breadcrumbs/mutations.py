"""Multi-record mutations that either happen completely or not at all (audit F20).

Replacing a decision is several writes: the new record, the old one's retirement
(`superseded_by`), perhaps the removal of its promoted rule from `CLAUDE.md`, and
the projections. Each write is atomic; the sequence was not. A retirement that
failed left two live decisions while `remember --supersedes` exited 0.

`transaction()` makes such a sequence one unit:

- **Before-images.** The first time the sequence writes or deletes a tracked
  file (a record, a trap or question file, a singleton, an adapter file), its
  prior bytes — or its absence — are saved to a write-ahead journal under
  `private/operations/<id>/`, together with a digest of what is about to be
  written. `generated/`, `index/` and `private/` are derived or local state and
  are not tracked; they are rebuilt instead.
- **Commit** removes the journal. **Failure** — an exception, or a step whose
  result the caller checked and found wanting (`fail()`) — restores every
  tracked file to its before-image, rebuilds the projections, and re-raises.
  The caller reports a failure in which nothing changed.
- **A crash** (the process killed mid-sequence) leaves the journal behind.
  `recover()` (`crumb recover`) rolls it back with the same rule, restoring a
  file only when it still holds either its before-image or a state this
  operation wrote. Anything else was changed by someone since, and is reported
  and left for a person rather than overwritten. A file the operation created
  and the rollback removes is kept under `private/recovered/<id>/`, so rolling
  back never erases what was authored.

`write_text_atomic(path, text, expected=…)` is the other half: a rewrite of a
record the writer read earlier refuses (`RevisionConflict`) when the file no
longer holds what was read, instead of silently discarding the other edit.

Transactions run under the store write lock. They take it themselves when the
caller does not hold it, and a nested `transaction()` joins the outer one.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import secrets
import shutil
import threading
import time
from pathlib import Path
from breadcrumbs import path_policy

OPERATIONS_RELPATH = ("private", "operations")
RECOVERED_RELPATH = ("private", "recovered")
# Store subdirectories whose files are derived or machine-local, never tracked.
_UNTRACKED_DIRS = ("generated", "index", "private")

_current = threading.local()


class MutationFailed(Exception):
    """A multi-record change did not complete. `unresolved` is true when rolling
    it back did not fully succeed either, and the journal was kept for `recover`."""

    def __init__(self, message: str, *, op_id: str | None = None, unresolved: bool = False):
        self.op_id = op_id
        self.unresolved = unresolved
        if unresolved:
            message += (
                f" — and it could not be fully rolled back; operation {op_id} is recorded "
                "as unresolved: run `crumb recover`"
            )
        super().__init__(message)


class RevisionConflict(Exception):
    """A file changed between the moment a writer read it and its rewrite."""

    def __init__(self, path: Path):
        self.path = Path(path)
        super().__init__(
            f"{self.path.name} changed since it was read (another editor?); "
            "nothing was written — re-run the command"
        )


def _digest(data: bytes | None) -> str:
    return "absent" if data is None else hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes | None:
    try:
        return path_policy.read_bytes(Path(path))
    except FileNotFoundError:
        return None


def _raw_write(path: Path, data: bytes) -> None:
    """An atomic write that bypasses tracking (the journal's own files, and a
    rollback's restores). Never through a link (audit F17)."""
    path_policy.mkdirs(path.parent)
    path_policy.write_atomic(path, data)


class Transaction:
    def __init__(self, memory_dir: Path, kind: str):
        self.memory_dir = Path(memory_dir).resolve()
        self.root = self.memory_dir.parent
        self.kind = kind
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
        self.op_id = f"{stamp}-{kind}-{secrets.token_hex(3)}"
        self.dir = self.memory_dir.joinpath(*OPERATIONS_RELPATH) / self.op_id
        self.entries: dict[str, dict] = {}  # relpath -> entry
        self.doomed = False

    # ---- journal ---------------------------------------------------------- #

    def _manifest(self) -> dict:
        return {
            "id": self.op_id,
            "kind": self.kind,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pid": os.getpid(),
            "files": list(self.entries.values()),
        }

    def _save(self) -> None:
        _raw_write(self.dir / "manifest.json", json.dumps(self._manifest(), indent=2).encode())

    def tracks(self, path: Path) -> bool:
        try:
            rel = Path(path).resolve().relative_to(self.root)
        except ValueError:
            return False
        parts = rel.parts
        if parts and parts[0] == self.memory_dir.name:
            return not (len(parts) > 1 and parts[1] in _UNTRACKED_DIRS)
        return True  # a project file the store writes: an adapter, .gitignore

    def before_change(self, path: Path, intended: bytes | None) -> None:
        """Journal `path`'s before-image (first touch) and the state about to be written."""
        path = Path(path)
        if not self.tracks(path):
            return
        rel = path.resolve().relative_to(self.root).as_posix()
        entry = self.entries.get(rel)
        if entry is None:
            before = _read(path)
            n = len(self.entries)
            entry = {
                "path": rel,
                "before": None if before is None else f"before/{n}",
                "before_digest": _digest(before),
                "written": [],
            }
            if before is not None:
                _raw_write(self.dir / entry["before"], before)
            self.entries[rel] = entry
        entry["written"].append(_digest(intended))
        self._save()  # write-ahead: the journal knows before the file changes

    # ---- outcome ---------------------------------------------------------- #

    def fail(self, message: str) -> None:
        """A step the caller checked did not succeed: abort the whole operation."""
        raise MutationFailed(message, op_id=self.op_id)

    def rollback(self) -> list[str]:
        """Restore every tracked file; return the paths that could not be restored."""
        conflicts, _kept = _roll_back(self.root, self.dir, list(self.entries.values()), keep=False)
        return conflicts

    def discard_journal(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)


def _roll_back(root: Path, op_dir: Path, entries: list[dict], *, keep: bool):
    """Restore `entries` newest first. Returns (unrestorable paths, kept copies)."""
    conflicts: list[str] = []
    kept: list[str] = []
    for entry in reversed(entries):
        path = root / entry["path"]
        current = _read(path)
        allowed = {entry["before_digest"], *entry["written"]}
        if _digest(current) not in allowed:
            conflicts.append(entry["path"])  # changed by someone else since: leave it
            continue
        if _digest(current) == entry["before_digest"]:
            continue
        try:
            if entry["before"] is None:
                if keep and current is not None:
                    copy = op_dir.parent.parent / "recovered" / op_dir.name / entry["path"]
                    _raw_write(copy, current)
                    kept.append(str(copy))
                with contextlib.suppress(FileNotFoundError):
                    path.unlink()
            else:
                _raw_write(path, path_policy.read_bytes(op_dir / entry["before"]))
        except OSError:
            conflicts.append(entry["path"])
    return conflicts, kept


def describe(exc: MutationFailed) -> str:
    """The user-facing line for a failed operation."""
    return str(exc) if exc.unresolved else f"{exc}; nothing was changed"


def current(memory_dir: Path | None = None) -> Transaction | None:
    tx = getattr(_current, "tx", None)
    if tx is None:
        return None
    if memory_dir is not None and Path(memory_dir).resolve() != tx.memory_dir:
        return None
    return tx


def before_write(path: Path, text: str | bytes | None) -> None:
    """Hook for every store writer: journal `path` if a transaction is open."""
    tx = getattr(_current, "tx", None)
    if tx is not None:
        data = text.encode("utf-8") if isinstance(text, str) else text
        tx.before_change(Path(path), data)


def delete(path: Path) -> None:
    """Remove a file, inside the open transaction when there is one."""
    before_write(path, None)
    Path(path).unlink()


@contextlib.contextmanager
def transaction(memory_dir: Path, kind: str, *, lock_timeout: float | None = None):
    """Run the body as one all-or-nothing store mutation. See the module docstring."""
    from breadcrumbs import cli
    from breadcrumbs import lock as _lock

    outer = getattr(_current, "tx", None)
    if outer is not None:
        # Nested: part of the enclosing operation. A failure here dooms the
        # whole operation even if a caller in between turns it into a return
        # value, so a partial inner change can never be committed.
        try:
            yield outer
        except BaseException:
            outer.doomed = True
            raise
        return
    memory_dir = Path(memory_dir)
    wait = _lock.CLI_TIMEOUT if lock_timeout is None else lock_timeout
    with _lock.store_lock(memory_dir, timeout=wait):
        tx = Transaction(memory_dir, kind)
        path_policy.mkdirs(tx.dir)
        tx._save()
        _current.tx = tx
        try:
            yield tx
        except BaseException as exc:
            _current.tx = None
            conflicts = tx.rollback()
            with contextlib.suppress(Exception):
                cli.reindex_projections(memory_dir)
            if conflicts:
                raise MutationFailed(
                    f"{exc}; could not restore {', '.join(conflicts)}",
                    op_id=tx.op_id,
                    unresolved=True,
                ) from exc
            tx.discard_journal()
            raise
        else:
            _current.tx = None
            if tx.doomed:
                conflicts = tx.rollback()
                with contextlib.suppress(Exception):
                    cli.reindex_projections(memory_dir)
                if not conflicts:
                    tx.discard_journal()
                raise MutationFailed(
                    "a step of this change failed"
                    + (f"; could not restore {', '.join(conflicts)}" if conflicts else ""),
                    op_id=tx.op_id,
                    unresolved=bool(conflicts),
                )
            tx.discard_journal()
        finally:
            _current.tx = None


# --------------------------------------------------------------------------- #
# Recovery (`crumb recover`, `crumb doctor`)
# --------------------------------------------------------------------------- #


def pending_operations(memory_dir: Path) -> list[dict]:
    """Journals left by operations that never finished, oldest first."""
    base = Path(memory_dir).joinpath(*OPERATIONS_RELPATH)
    out = []
    for manifest in sorted(base.glob("*/manifest.json")):
        try:
            data = json.loads(path_policy.read_text(manifest))
        except (OSError, ValueError):
            data = {"id": manifest.parent.name, "kind": "?", "files": [], "corrupt": True}
        data["dir"] = str(manifest.parent)
        out.append(data)
    return out


def recover(memory_dir: Path, *, apply: bool = False) -> dict:
    """Roll back every unfinished operation (`apply`), or describe what would happen.

    Takes the store lock: an operation's journal is only abandoned when no
    writer holds the lock, because every transaction runs under it.
    """
    from breadcrumbs import cli
    from breadcrumbs import lock as _lock

    memory_dir = Path(memory_dir)
    root = memory_dir.resolve().parent
    report = []
    with _lock.store_lock(memory_dir):
        for op in pending_operations(memory_dir):
            files = op.get("files", [])
            plan = []
            for entry in files:
                current = _digest(_read(root / entry["path"]))
                if current == entry["before_digest"]:
                    action = "unchanged"
                elif current in entry["written"]:
                    action = "remove" if entry["before"] is None else "restore"
                else:
                    action = "conflict"
                plan.append({"path": entry["path"], "action": action})
            row = {"id": op.get("id"), "kind": op.get("kind"), "files": plan}
            if op.get("corrupt"):
                row["error"] = "journal unreadable; inspect it by hand"
            elif apply:
                conflicts, kept = _roll_back(root, Path(op["dir"]), files, keep=True)
                row["rolled_back"] = not conflicts
                row["conflicts"] = conflicts
                row["kept"] = kept
                if not conflicts:
                    shutil.rmtree(op["dir"], ignore_errors=True)
            report.append(row)
        if apply and report:
            cli.reindex_projections(memory_dir)
    return {"operations": report, "applied": apply}
