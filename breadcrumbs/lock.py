"""breadcrumbs — one writer at a time per store (WM-51).

Hooks from parallel sessions in one checkout write the same store: two Stop
hooks capture at once, a prompt hook jots while another session reindexes. Each
file write is already atomic (`write_text_atomic` renames a temp file into
place), so a *torn* file cannot happen; what can happen is a lost update — two
read-modify-write sequences (a handoff rewrite, an index regeneration)
interleaving so that one silently undoes the other.

`store_lock(memory_dir)` serialises writers:

- **Across processes**, with a lock file `private/.write-lock` created with
  `O_CREAT | O_EXCL` — atomic on every filesystem the store lives on — holding
  the owner's pid, host and the time. The holder touches it every
  `HEARTBEAT_SECONDS`, so a long writer (a migration backup, a search-index
  build) keeps it; a lock not touched for `STALE_SECONDS`, or whose pid is gone
  on this host (POSIX), is broken — a writer that crashed must not wedge the
  store. Breaking is rename-then-verify, so two waiters that both judged the
  same lock stale cannot also remove the fresh lock one of them just took.
- **Across threads**, with an in-process lock per store.
- **Re-entrant** within one thread: a command that takes the lock and then
  calls a writer that takes it again (every writer reindexes) does not
  deadlock on itself.

Callers pick the wait: the CLI waits `CLI_TIMEOUT` and then fails with exit 1,
hooks wait `HOOK_TIMEOUT` and then skip their write silently — a hook never
blocks the host it runs in.
"""

from __future__ import annotations

import contextlib
import os
import threading
import time
from pathlib import Path

LOCK_RELPATH = ("private", ".write-lock")
STALE_SECONDS = 60.0
HEARTBEAT_SECONDS = 15.0
CLI_TIMEOUT = 2.0
HOOK_TIMEOUT = 0.5
MCP_TIMEOUT = 2.0
_POLL_SECONDS = 0.02


class StoreLocked(Exception):
    """Another writer holds the store past the caller's timeout."""

    def __init__(self, pid: int | None, *, who: str | None = None):
        self.pid = pid
        who = who or (f"pid {pid}" if pid else "another writer")
        super().__init__(f"store is locked by {who}; try again, or remove a stale lock")


_registry_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}
_held = threading.local()


def lock_path(memory_dir: Path) -> Path:
    return Path(memory_dir).joinpath(*LOCK_RELPATH)


def _host() -> str:
    import socket

    try:
        return socket.gethostname() or "?"
    except OSError:  # pragma: no cover
        return "?"


def _read_owner(path: Path) -> tuple[int | None, float | None, str | None]:
    """`(pid, written_at, host)`; any part None when unreadable."""
    try:
        raw = path.read_text(encoding="utf-8").split()
    except OSError:
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
    # CTRL_C_EVENT), so there the age rule alone decides.
    if os.name != "posix":
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _is_stale(path: Path) -> bool:
    pid, stamp, host = _read_owner(path)
    try:
        # The holder's heartbeat touches the file, so its mtime is the freshest
        # sign of life; the stamp inside is when it was taken.
        touched = max(path.stat().st_mtime, stamp or 0.0)
    except OSError:
        return True
    if time.time() - touched > STALE_SECONDS:
        return True
    # A pid is only meaningful on the host that wrote it: a store on a shared
    # filesystem can hold another machine's lock.
    if host not in (None, _host()):
        return False
    return pid is not None and pid != os.getpid() and not _pid_alive(pid)


def _break_stale(path: Path) -> None:
    """Remove a stale lock without ever removing a fresh one.

    Two waiters can both judge the same lock stale. Rename it aside, then check
    that what was moved is the lock that was judged; if the other waiter had
    already replaced it with a fresh lock, put that one back.
    """
    judged = _read_owner(path)
    tomb = path.with_name(f"{path.name}.stale.{os.getpid()}.{threading.get_ident()}")
    try:
        os.replace(str(path), str(tomb))
    except FileNotFoundError:
        return
    if _read_owner(tomb) != judged:
        try:
            os.link(str(tomb), str(path))
        except OSError:
            pass  # slot already retaken; the moved lock's owner will find it gone
    with contextlib.suppress(FileNotFoundError):
        tomb.unlink()


def _acquire_file(path: Path, deadline: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if _is_stale(path):
                _break_stale(path)
                continue
            if time.monotonic() >= deadline:
                raise StoreLocked(_read_owner(path)[0]) from None
            time.sleep(_POLL_SECONDS)
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{os.getpid()} {time.time():.3f} {_host()}\n")
        return


def _release_file(path: Path) -> None:
    pid, _stamp, host = _read_owner(path)
    if pid in (None, os.getpid()) and host in (None, _host()):
        with contextlib.suppress(FileNotFoundError):
            path.unlink()


def _heartbeat(path: Path, stop: threading.Event) -> None:
    while not stop.wait(HEARTBEAT_SECONDS):
        with contextlib.suppress(OSError):
            os.utime(str(path))


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
        path = lock_path(memory_dir)
        _acquire_file(path, deadline)
        depth[key] = 1
        stop = threading.Event()
        beat = threading.Thread(target=_heartbeat, args=(path, stop), daemon=True)
        beat.start()
        try:
            yield
        finally:
            stop.set()
            depth[key] = 0
            _release_file(path)
    finally:
        thread_lock.release()


def holds_lock(memory_dir: Path) -> bool:
    """Does this thread currently hold the store's lock?"""
    depth = getattr(_held, "depth", None) or {}
    return bool(depth.get(str(Path(memory_dir).resolve())))
