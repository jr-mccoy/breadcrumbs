"""breadcrumbs — what the store may read and write on disk (audit F17, WP13).

**The threat.** Memory files are repository content. Whoever can commit to the
repository (or write the checkout) can replace `current.md`, a record, or a
whole directory of the store with a symbolic link, and a process that reads
"its own memory" then reads whatever the link names, with the reader's
permissions, and hands it to an MCP client or an agent's context. The same
link on a directory redirects writes. Before this module, `memory://current`
served a file outside the project that way.

**The policy: nothing inside the store is a link.**

- **The store** is the `.project-memory` directory of a project, and every path
  under it. The store directory itself, every directory under it, and every
  file read or written in it must be a real directory or file, not a symbolic
  link, and on Windows not a junction or other reparse point. An internal link
  (one pointing elsewhere in the store) is refused too: the simplest rule to
  audit is "no links at all", and nothing in the tool creates one.
- **`..` never appears** in a store path.
- **The project root** is authorized by the person who runs the command (the
  working directory or `--project`). It is resolved once, links and all, and
  never re-derived from anything inside the store.
- **Project files the tool writes** (`CLAUDE.md`, `AGENTS.md`, `.gitignore`,
  `.mcp.json`, `.claude/settings.json`) may be links, as long as each resolves
  inside the project: `AGENTS.md -> CLAUDE.md` is a common, legitimate layout.
  One that resolves outside is refused.
- **Refusal fails closed** with `Refused`, a `PermissionError` whose message
  names the store- or project-relative path and the rule, never the link's
  target, the target's bytes, or an absolute host path.

**How it is enforced.** On POSIX, a store path is opened one component at a
time from the store directory, each with `O_NOFOLLOW` (and `O_DIRECTORY` for the
directories), relative to the previous component's descriptor. A link swapped
in at any point makes the open fail rather than follow it, so there is no
window between a check and a use. Writes create their temporary file and rename
it into place through the same directory descriptor. Where that is not
available (Windows), each component is checked with `lstat` first, and a link
swapped in between the check and the use is not caught: that residual race is
documented, not claimed closed.

Paths outside any store (transcripts named by the host, git, the package's own
templates) are read as before. This module has no dependency on the rest of
the package.
"""

from __future__ import annotations

import contextlib
import errno
import os
import stat
from pathlib import Path

STORE_DIRNAME = ".project-memory"

LINK = "is a symbolic link or junction; nothing inside the store may be a link"
LINKED_DIR = (
    "is under a symbolic link or junction; the store's directories must be real directories"
)
TRAVERSAL = "contains '..'; store paths may not leave the store"
NOT_REGULAR = "is not a regular file"
OUTSIDE = "resolves outside the project (a symbolic link or junction points elsewhere)"

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_DIRECTORY = getattr(os, "O_DIRECTORY", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)

# The descriptor-relative path: every call it needs, with no-follow opens.
FD_RELATIVE = bool(
    os.name == "posix"
    and _NOFOLLOW
    and _DIRECTORY
    and os.open in os.supports_dir_fd
    and os.rename in os.supports_dir_fd
    and os.mkdir in os.supports_dir_fd
    and os.unlink in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)


class Refused(PermissionError):
    """A store or project path the policy does not allow. The message is safe to
    show anyone: a relative path and the rule, nothing from the link's target."""

    def __init__(self, shown: str, why: str):
        self.shown = shown
        self.why = why
        super().__init__(errno.EACCES, f"{shown} {why}")

    def __str__(self) -> str:
        return f"refused: {self.shown} {self.why}"


# --------------------------------------------------------------------------- #
# Which paths are store paths
# --------------------------------------------------------------------------- #


_EXTENDED_PREFIX = "\\\\?\\"


def extended_path(path, *, windows: bool | None = None) -> str:
    r"""`path` as a string the OS accepts past MAX_PATH (260 characters).

    On Windows that is the `\\?\` extended-length form of the absolute path
    (`\\?\UNC\server\share\…` for a UNC path), which the file APIs honour
    whether or not the LongPathsEnabled policy is on. Elsewhere it is just
    `str(path)`. Pure string work, so it is testable on any OS (`windows=`).
    Field report 2026-10-01, issue 5: a migration backup under
    `private/migrations/<stamp>/` went past 260 characters on Windows.
    """
    import ntpath

    windows = (os.name == "nt") if windows is None else windows
    text = os.fspath(path)
    if not windows or text.startswith(_EXTENDED_PREFIX):
        return text
    if not ntpath.isabs(text):
        text = ntpath.join(os.getcwd(), text)
    text = ntpath.normpath(text.replace("/", "\\"))
    if text.startswith("\\\\"):
        return _EXTENDED_PREFIX + "UNC\\" + text[2:]
    return _EXTENDED_PREFIX + text


def plain_path(path) -> str:
    """Undo `extended_path`, for showing a path to a person."""
    text = os.fspath(path)
    if text.startswith(_EXTENDED_PREFIX + "UNC\\"):
        return "\\\\" + text[len(_EXTENDED_PREFIX) + 4 :]
    if text.startswith(_EXTENDED_PREFIX):
        return text[len(_EXTENDED_PREFIX) :]
    return text


def describe_copy_error(exc: BaseException, base=None, *, limit: int = 10) -> str:
    r"""A person-readable account of a failed copy.

    `shutil.Error` carries a list of `(src, dst, why)` tuples and its `str()` is
    the raw list (field report: `CRUMB-ERROR: crumb migrate: [('C:\…', …)]`).
    This names up to `limit` files — relative to `base` when given — and why.
    """
    import shutil

    rows = exc.args[0] if isinstance(exc, shutil.Error) and exc.args else None
    if not isinstance(rows, list):
        return str(exc)

    def short(p: str) -> str:
        p = plain_path(p)
        if base is not None:
            for root in (os.fspath(base), plain_path(extended_path(base))):
                if p.startswith(root):
                    return p[len(root) :].lstrip("\\/").replace("\\", "/") or p
        return p

    lines = []
    for row in rows[:limit]:
        if isinstance(row, (tuple, list)) and len(row) == 3:
            src, _dst, why = row
            lines.append(f"{short(str(src))} ({why})")
        else:
            lines.append(str(row))
    more = f"; and {len(rows) - limit} more" if len(rows) > limit else ""
    return f"{len(rows)} file(s) could not be copied: " + "; ".join(lines) + more


def split_store(path) -> tuple[Path, tuple[str, ...]] | None:
    """`(store_dir, parts_under_it)` for a path inside a store, else None.

    The *first* `.project-memory` component is the store, so a directory of
    that name nested inside a store cannot shorten the checked chain.
    """
    parts = Path(path).parts
    try:
        i = parts.index(STORE_DIRNAME)
    except ValueError:
        return None
    return Path(*parts[: i + 1]), tuple(parts[i + 1 :])


def is_store_path(path) -> bool:
    return split_store(path) is not None


def shown(path) -> str:
    """How a path appears in a diagnostic: store-relative, else the bare name."""
    split = split_store(path)
    if split is None:
        return Path(path).name
    return "/".join((STORE_DIRNAME, *split[1]))


def _is_link(st: os.stat_result) -> bool:
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def check(path) -> None:
    """Raise `Refused` if a store path is (or is under) a link, or uses `..`.

    Components that do not exist yet end the check: nothing there can be
    followed. A path outside any store passes. On POSIX the reads and writes
    below do not rely on this check (they refuse links as they open); it is
    what the Windows path and `validate` use.
    """
    split = split_store(path)
    if split is None:
        return
    store, rel = split
    if ".." in rel:
        raise Refused(shown(path), TRAVERSAL)
    chain = [store]
    for part in rel:
        chain.append(chain[-1] / part)
    for i, p in enumerate(chain):
        try:
            st = os.lstat(p)
        except OSError:
            return
        if _is_link(st):
            raise Refused(shown(path), LINK if i == len(chain) - 1 else LINKED_DIR)


# --------------------------------------------------------------------------- #
# Descriptor-relative opens (POSIX)
# --------------------------------------------------------------------------- #


def _translate(exc: OSError, path) -> OSError:
    """Turn a no-follow failure into `Refused`; keep any other error, with the
    path it concerned rather than a single component."""
    try:
        check(path)
    except Refused as refused:
        return refused
    if exc.errno in (errno.ELOOP, getattr(errno, "EMLINK", -1)):
        return Refused(shown(path), LINK)
    return type(exc)(exc.errno, exc.strerror, str(path))


def _open_dir(store: Path, parts: tuple[str, ...], *, create: bool = False) -> int:
    """A descriptor for `store/parts`, opened with no link followed anywhere.

    With `create`, missing directories are made on the way (as
    `mkdir(parents=True)` would), each inside the descriptor it was checked
    through.
    """
    flags = os.O_RDONLY | _DIRECTORY | _NOFOLLOW | _CLOEXEC
    if create:
        with contextlib.suppress(FileExistsError):
            os.mkdir(store)
    fd = os.open(store, flags)
    try:
        for part in parts:
            if create:
                with contextlib.suppress(FileExistsError):
                    os.mkdir(part, dir_fd=fd)
            nfd = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = nfd
    except BaseException:
        os.close(fd)
        raise
    return fd


def _leaf(path) -> tuple[Path, tuple[str, ...]] | None:
    split = split_store(path)
    if split is None:
        return None
    store, rel = split
    if ".." in rel:
        raise Refused(shown(path), TRAVERSAL)
    return store, rel


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


def read_bytes(path) -> bytes:
    """The file's bytes. A store path is read under the policy."""
    split = _leaf(path)
    if split is None or not split[1]:
        return Path(path).read_bytes()
    store, rel = split
    if not FD_RELATIVE:
        check(path)
        return Path(path).read_bytes()
    try:
        dfd = _open_dir(store, rel[:-1])
        try:
            fd = os.open(rel[-1], os.O_RDONLY | _NOFOLLOW | _NONBLOCK | _CLOEXEC, dir_fd=dfd)
        finally:
            os.close(dfd)
    except OSError as exc:
        raise _translate(exc, path) from None
    with os.fdopen(fd, "rb") as fh:
        mode = os.fstat(fh.fileno()).st_mode
        if stat.S_ISDIR(mode):
            raise IsADirectoryError(errno.EISDIR, "Is a directory", str(path))
        if not stat.S_ISREG(mode):
            raise Refused(shown(path), NOT_REGULAR)
        return fh.read()


def read_text(path, encoding: str = "utf-8", errors: str = "strict") -> str:
    """`Path.read_text` under the policy, newline translation included."""
    return decode(read_bytes(path), encoding, errors)


def decode(data: bytes, encoding: str = "utf-8", errors: str = "strict") -> str:
    """Bytes to text exactly as `Path.read_text` would: universal newlines, so
    `\r\n` and a lone `\r` both become `\n`."""
    text = data.decode(encoding, errors)
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text


def read_dir(path, suffix: str) -> list[tuple[Path, bytes | OSError]]:
    """Every `*<suffix>` file in a directory, read under the policy, in one pass.

    What `sorted(Path(path).glob("*" + suffix))` followed by a read of each
    would give (hidden names excluded, as `glob` excludes them), with each
    file's bytes or the error reading it. The directory is opened once, so a
    store of a thousand records costs one walk, not a thousand. A directory
    that is a link, or under one, raises `Refused`.
    """
    split = _leaf(path)
    if split is None or not FD_RELATIVE:
        check(path)
        return [(p, _read_or_error(p)) for p in sorted(Path(path).glob("*" + suffix))]
    store, rel = split
    try:
        dfd = _open_dir(store, rel)
    except OSError as exc:
        raise _translate(exc, path) from None
    try:
        names = sorted(n for n in os.listdir(dfd) if n.endswith(suffix) and not n.startswith("."))
        return [(Path(path) / n, _read_at(dfd, n, Path(path) / n)) for n in names]
    finally:
        os.close(dfd)


def read_files(paths) -> dict[Path, bytes | OSError]:
    """Each path's bytes, or the error reading it, under the policy.

    Paths are grouped by directory and each directory is opened once. For a
    caller holding a list of records to parse (search index hits).
    """
    out: dict[Path, bytes | OSError] = {}
    groups: dict[Path, list[Path]] = {}
    for p in map(Path, paths):
        groups.setdefault(p.parent, []).append(p)
    for parent, members in groups.items():
        split = _leaf(parent) if FD_RELATIVE else None
        if split is None:
            for p in members:
                out[p] = _read_or_error(p)
            continue
        try:
            dfd = _open_dir(*split)
        except OSError as exc:
            for p in members:
                out[p] = _translate(exc, p)
            continue
        try:
            for p in members:
                out[p] = (
                    Refused(shown(p), TRAVERSAL) if p.name == ".." else _read_at(dfd, p.name, p)
                )
        finally:
            os.close(dfd)
    return out


def _read_or_error(p: Path) -> bytes | OSError:
    try:
        return read_bytes(p)
    except OSError as exc:
        return exc


def _read_at(dfd: int, name: str, p: Path) -> bytes | OSError:
    """One file in an open directory, no link followed; the bytes or the error."""
    try:
        fd = os.open(name, os.O_RDONLY | _NOFOLLOW | _NONBLOCK | _CLOEXEC, dir_fd=dfd)
    except OSError as exc:
        return _translate(exc, p)
    with os.fdopen(fd, "rb") as fh:
        mode = os.fstat(fh.fileno()).st_mode
        if stat.S_ISDIR(mode):
            return IsADirectoryError(errno.EISDIR, "Is a directory", str(p))
        if not stat.S_ISREG(mode):
            return Refused(shown(p), NOT_REGULAR)
        return fh.read()


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


def mkdirs(path) -> None:
    """`Path(path).mkdir(parents=True, exist_ok=True)`, never through a link."""
    split = _leaf(path)
    if split is None:
        Path(path).mkdir(parents=True, exist_ok=True)
        return
    store, rel = split
    if not FD_RELATIVE:
        check(path)
        Path(path).mkdir(parents=True, exist_ok=True)
        return
    # Above the store is the project, which the caller chose.
    store.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.close(_open_dir(store, rel, create=True))
    except OSError as exc:
        raise _translate(exc, path) from None


def write_atomic(path, data: bytes) -> None:
    """Write via a temporary file renamed into place, in the same directory.

    Readers see the old file or the new one. A store path is written through
    a descriptor for its directory, opened with no link followed, and a link
    at the leaf is refused rather than replaced. The file is created `0600`,
    as `tempfile.mkstemp` did before this.
    """
    split = _leaf(path)
    if split is None or not split[1] or not FD_RELATIVE:
        if split is not None:
            check(path)
        _plain_atomic(Path(path), data)
        return
    store, rel = split
    leaf = rel[-1]
    try:
        dfd = _open_dir(store, rel[:-1])
    except OSError as exc:
        raise _translate(exc, path) from None
    try:
        try:
            st = os.stat(leaf, dir_fd=dfd, follow_symlinks=False)
        except FileNotFoundError:
            st = None
        if st is not None and _is_link(st):
            raise Refused(shown(path), LINK)
        tmp = f".{leaf}.{os.urandom(6).hex()}.tmp"
        fd = os.open(
            tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _NOFOLLOW | _CLOEXEC, 0o600, dir_fd=dfd
        )
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
            os.rename(tmp, leaf, src_dir_fd=dfd, dst_dir_fd=dfd)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp, dir_fd=dfd)
            raise
    finally:
        os.close(dfd)


def _plain_atomic(path: Path, data: bytes) -> None:
    import tempfile

    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def open_file(path, flags: int, mode: int = 0o666):
    """A raw descriptor for `path` opened with `flags`, never through a link.

    For the files kept open or appended to rather than replaced: lock files
    and the hook log. The caller wraps it (`os.fdopen`).
    """
    split = _leaf(path)
    if split is None or not split[1] or not FD_RELATIVE:
        if split is not None:
            check(path)
        return os.open(path, flags | _CLOEXEC, mode)
    store, rel = split
    try:
        dfd = _open_dir(store, rel[:-1])
        try:
            return os.open(rel[-1], flags | _NOFOLLOW | _CLOEXEC, mode, dir_fd=dfd)
        finally:
            os.close(dfd)
    except OSError as exc:
        raise _translate(exc, path) from None


# --------------------------------------------------------------------------- #
# Enumeration and audit
# --------------------------------------------------------------------------- #


def list_dir(path, pattern: str = "*") -> list[Path]:
    """`sorted(Path(path).glob(pattern))` for a directory that is not a link or
    under one. Entries that are links are listed; reading one is refused."""
    check(path)
    return sorted(Path(path).glob(pattern))


def find_links(memory_dir) -> list[str]:
    """Every link in the store, as store-relative POSIX paths. Never follows one."""
    memory_dir = Path(memory_dir)
    out: list[str] = []
    try:
        if _is_link(os.lstat(memory_dir)):
            return ["."]
    except OSError:
        return out
    for dirpath, dirnames, filenames in os.walk(memory_dir, followlinks=False):
        for name in sorted(dirnames + filenames):
            p = Path(dirpath) / name
            try:
                if _is_link(os.lstat(p)):
                    out.append(p.relative_to(memory_dir).as_posix())
            except OSError:
                continue
        # os.walk does not descend into a linked directory; a junction on
        # Windows may be walked, so prune it explicitly.
        dirnames[:] = [d for d in dirnames if not _safe_is_link(Path(dirpath) / d)]
    return sorted(out)


def _safe_is_link(p: Path) -> bool:
    try:
        return _is_link(os.lstat(p))
    except OSError:
        return True


# --------------------------------------------------------------------------- #
# Project files the tool writes
# --------------------------------------------------------------------------- #


def check_project_target(path, root) -> None:
    """Raise `Refused` unless `path` stays inside the project `root`.

    Links are allowed when they resolve inside the project; `..` is not; a
    target inside the store is held to the store's rule.
    """
    root = Path(root)
    p = Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        rel = p.relative_to(root)
    except ValueError:
        raise Refused(p.name, OUTSIDE) from None
    if ".." in rel.parts:
        raise Refused(rel.as_posix(), TRAVERSAL)
    root_r = root.resolve()
    resolved = p.resolve()
    if resolved != root_r and root_r not in resolved.parents:
        raise Refused(rel.as_posix(), OUTSIDE)
    check(p)
