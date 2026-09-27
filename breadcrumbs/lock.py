"""breadcrumbs — one writer at a time per store (WM-51; audit WP05).

Hooks from parallel sessions in one checkout write the same store: two Stop
hooks capture at once, a prompt hook jots while another session reindexes. Each
file write is already atomic (`write_text_atomic` renames a temp file into
place), so a *torn* file cannot happen; what can happen is a lost update — two
read-modify-write sequences (a handoff rewrite, an index regeneration)
interleaving so that one silently undoes the other.

`store_lock(memory_dir)` serialises writers:

- **Across processes**, with an operating-system lock on `private/.store.lock`:
  `flock` on POSIX, `msvcrt.locking` on Windows. The kernel holds it, so it is
  released when its holder exits however that happens. There is no heartbeat,
  no age limit and no "stale" rule: a live writer is never judged dead because a
  clock jumped or a process was suspended, and a crashed one never wedges the
  store (audit F08). The file itself is permanent and never unlinked, so no
  waiter can ever lock a different inode than the holder. It carries the
  holder's pid, host and start time for error messages only; nothing decides
  anything from them.
- **Across threads**, with an in-process lock per store.
- **Re-entrant** within one thread: a command that takes the lock and then
  calls a writer that takes it again (every writer reindexes) does not
  deadlock on itself.

**Supported filesystems.** OS locks are exact on a local filesystem. On a
network or sync-managed filesystem they may be emulated or absent; there,
failing to take the lock is reported (`LockUnsupported`) rather than skipped.
Two machines sharing one store through git are a different, supported design:
each has its own checkout and its own lock.

**Older versions.** crumb-kit 0.3.0 and earlier used an exclusive-create file,
`private/.write-lock`, with a heartbeat. While such a file is fresh and its
writer alive, this version waits for it too. It never removes one, and an older
version does not see this version's lock.

Callers pick the wait: the CLI waits `CLI_TIMEOUT` and then fails with exit 1,
hooks wait `HOOK_TIMEOUT` and then skip their write silently — a hook never
blocks the host it runs in.
"""

from __future__ import annotations

import contextlib
import errno
import os
import threading
import time
from pathlib import Path
from breadcrumbs import path_policy

LOCK_RELPATH = ("private", ".store.lock")
LEGACY_LOCK_RELPATH = ("private", ".write-lock")
# How fresh a legacy (0.3.0-and-earlier) lock must be for this version to wait
# on it: its writer touched it every 15 seconds while alive.
LEGACY_FRESH_SECONDS = 60.0
CLI_TIMEOUT = 2.0
HOOK_TIMEOUT = 0.5
MCP_TIMEOUT = 2.0
_POLL_SECONDS = 0.02

if os.name == "posix":
    import fcntl
else:  # pragma: no cover - Windows
    import msvcrt

# errno values that mean "somebody else holds it", as opposed to "this
# filesystem cannot lock".
_BUSY = {errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES, errno.EDEADLK}


class StoreLocked(Exception):
    """Another writer holds the store past the caller's timeout."""

    def __init__(self, pid: int | None, *, who: str | None = None, message: str | None = None):
        self.pid = pid
        who = who or (f"pid {pid}" if pid else "another writer")
        super().__init__(message or f"store is locked by {who}; try again shortly")


class LockUnsupported(StoreLocked):
    """The store's filesystem refused an OS lock; writes are not coordinated there."""

    def __init__(self, path: Path, exc: OSError):
        super().__init__(
            None,
            message=f"cannot take a write lock on {path} ({exc.strerror or exc}); the store "
            "must be on a local filesystem for concurrent writers to be safe",
        )


_registry_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}
_held = threading.local()


def lock_path(memory_dir: Path) -> Path:
    return Path(memory_dir).joinpath(*LOCK_RELPATH)


def legacy_lock_path(memory_dir: Path) -> Path:
    return Path(memory_dir).joinpath(*LEGACY_LOCK_RELPATH)


def _host() -> str:
    import socket

    try:
        return socket.gethostname() or "?"
    except OSError:  # pragma: no cover
        return "?"


def _read_owner(path: Path) -> tuple[int | None, float | None, str | None]:
    """`(pid, written_at, host)` from a lock file; any part None when unreadable."""
    try:
        raw = path_policy.read_text(path).split()
    except (OSError, UnicodeDecodeError):
        return None, None, None
    try:
        pid = int(raw[0])
    except (ValueError, IndexError):
        pid = None
    try:
        stamp = float(raw[1])
    except (ValueError, IndexError):
        stamp = None
    host = raw[2] if len(raw) > 2 else None
    return pid, stamp, host


def _pid_alive(pid: int) -> bool:
    # Only on POSIX: on Windows `os.kill(pid, 0)` is not a probe (signal 0 is
    # CTRL_C_EVENT), so there a fresh legacy lock is simply waited on.
    if os.name != "posix":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _legacy_holder(memory_dir: Path) -> int | None:
    """The pid of a live 0.3.0-era writer holding `private/.write-lock`, if any.

    Waited on, never broken: this version has no business removing another
    version's lock. A file its writer stopped touching long ago (the writer
    crashed) is ignored rather than deleted.
    """
    path = legacy_lock_path(memory_dir)
    try:
        age = time.time() - path.stat().st_mtime
    except OSError:
        return None
    if age > LEGACY_FRESH_SECONDS:
        return None
    pid, _stamp, host = _read_owner(path)
    if pid is None or pid == os.getpid():
        return None
    if host not in (None, _host()):
        return pid  # another machine's live-looking lock: its pid cannot be probed here
    return pid if _pid_alive(pid) else None


def _try_os_lock(fh) -> bool:
    """One non-blocking attempt. True when taken, False when somebody holds it."""
    try:
        if os.name == "posix":
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:  # pragma: no cover - Windows
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        return True
    except OSError as exc:
        if exc.errno in _BUSY:
            return False
        raise


def _os_unlock(fh) -> None:
    with contextlib.suppress(OSError):
        if os.name == "posix":
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        else:  # pragma: no cover - Windows
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)


def _acquire_file(memory_dir: Path, deadline: float):
    """Take the OS lock (waiting until `deadline`); return the open handle."""
    path = lock_path(memory_dir)
    # "a+b" creates the file if needed and never truncates another holder's
    # owner line on open. The file is never unlinked (see the module docstring).
    # Opened under the store's path policy (audit F17): a lock file that is a
    # link would have this process write its pid wherever the link points.
    try:
        path_policy.mkdirs(path.parent)
        fh = _open_lock_file(path)
    except path_policy.Refused as exc:
        raise StoreLocked(None, message=str(exc)) from None
    try:
        while True:
            try:
                taken = _try_os_lock(fh)
            except OSError as exc:
                raise LockUnsupported(path, exc) from exc
            if taken:
                legacy = _legacy_holder(memory_dir)
                if legacy is None:
                    break
                _os_unlock(fh)  # an older version is writing: wait for it too
                owner = legacy
            else:
                owner = _read_owner(path)[0]
            if time.monotonic() >= deadline:
                raise StoreLocked(owner)
            time.sleep(_POLL_SECONDS)
        # Who holds it, for the next waiter's error message.
        with contextlib.suppress(OSError):
            fh.seek(0)
            fh.truncate()
            fh.write(f"{os.getpid()} {time.time():.3f} {_host()}\n".encode())
            fh.flush()
        return fh
    except BaseException:
        fh.close()
        raise


def _open_lock_file(path: Path):
    """`open(path, "a+b")`, never through a link (audit F17)."""
    fd = path_policy.open_file(path, os.O_RDWR | os.O_CREAT | os.O_APPEND)
    return os.fdopen(fd, "a+b")


def _release_file(fh) -> None:
    # Clear the owner line first, so a waiter never blames a process that has
    # already let go; then drop the OS lock. The file stays.
    with contextlib.suppress(OSError):
        fh.seek(0)
        fh.truncate()
        fh.flush()
    _os_unlock(fh)
    with contextlib.suppress(OSError):
        fh.close()


def lock_owner(memory_dir: Path) -> int | None:
    """The pid recorded by the current holder, for messages. Not a lock test."""
    return _read_owner(lock_path(memory_dir))[0]


@contextlib.contextmanager
def store_lock(memory_dir: Path, timeout: float = CLI_TIMEOUT):
    """Hold the store's write lock for the `with` body. Raises `StoreLocked`."""
    key = str(Path(memory_dir).resolve())
    depth: dict = getattr(_held, "depth", None) or {}
    _held.depth = depth
    if depth.get(key):
        depth[key] += 1
        try:
            yield
        finally:
            depth[key] -= 1
        return

    with _registry_guard:
        thread_lock = _thread_locks.setdefault(key, threading.Lock())
    deadline = time.monotonic() + max(0.0, timeout)
    if not thread_lock.acquire(timeout=max(0.0, timeout)):
        raise StoreLocked(None, who="another thread of this process")
    try:
        fh = _acquire_file(Path(memory_dir), deadline)
        depth[key] = 1
        try:
            yield
        finally:
            depth[key] = 0
            _release_file(fh)
    finally:
        thread_lock.release()


def holds_lock(memory_dir: Path) -> bool:
    """Does this thread currently hold the store's lock?"""
    depth = getattr(_held, "depth", None) or {}
    return bool(depth.get(str(Path(memory_dir).resolve())))


# --------------------------------------------------------------------------- #
# Side locks: machine-local state that is not the store (audit WP12)
# --------------------------------------------------------------------------- #
#
# Hook state, usage telemetry and the hook log live under `private/` and are
# never records, so they do not take the store lock: a parallel session's
# capture must not cost a guard call its dedupe, and a busy hook must not delay
# a writer. Each has a lock file of its own, held for the few reads and writes
# of one update.

HELD = "held"
BUSY = "busy"
UNSUPPORTED = "unsupported"

# How long a hook waits for a side lock. An update holds one for well under a
# millisecond; this only has to outlast a burst of parallel hooks.
SIDE_TIMEOUT = 0.25


@contextlib.contextmanager
def side_lock(path: Path, timeout: float = SIDE_TIMEOUT):
    """Hold an OS lock on `path` for the `with` body, waiting up to `timeout`.

    Yields `HELD`, `BUSY` (somebody held it past `timeout`) or `UNSUPPORTED`
    (the filesystem cannot lock, or the file cannot be opened). It never
    raises for either: the caller decides whether to skip its update (and
    say so) or go ahead uncoordinated. The file is never unlinked.
    """
    try:
        path = Path(path)
        path_policy.mkdirs(path.parent)
        fh = _open_lock_file(path)
    except OSError:
        yield UNSUPPORTED
        return
    try:
        deadline = time.monotonic() + max(0.0, timeout)
        state = BUSY
        while True:
            try:
                if _try_os_lock(fh):
                    state = HELD
                    break
            except OSError:
                state = UNSUPPORTED
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(_POLL_SECONDS / 4)
        try:
            yield state
        finally:
            if state == HELD:
                _os_unlock(fh)
    finally:
        with contextlib.suppress(OSError):
            fh.close()
