"""breadcrumbs — read a few git refs from disk instead of starting `git`.

The guard hook runs before every tool call. Each `git` process costs ~1 ms on
Linux and 50-80 ms with Git for Windows, and a full guard firing started five
of them just to learn the branch, HEAD and the default branch (DoWhat retest
of 0.5.0, item 7: p50 764 ms on Windows). Those answers are a few small files:

- `HEAD` names the branch (`ref: refs/heads/main`) or a detached sha;
- a branch is a loose file under `refs/` or a line in `packed-refs`;
- `refs/remotes/origin/HEAD` is a symbolic ref, always a loose file.

Every function returns None when it cannot answer for certain, and the caller
then asks `git` exactly as before. Unusual layouts are left to git: a reftable
ref store, `GIT_DIR`/`GIT_WORK_TREE`/`GIT_COMMON_DIR` in the environment, or
anything unreadable. Linked worktrees (`.git` is a file pointing at
`gitdir:`, with a `commondir`) are read the way git reads them.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_SHA_RE = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")
_ENV_OVERRIDES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES")


def _read(path: Path) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="strict") as fh:
            return fh.read()
    except (OSError, UnicodeDecodeError):
        return None


def git_dir(root: Path) -> Path | None:
    """The `.git` directory for the work tree containing `root`, or None."""
    if any(os.environ.get(k) for k in _ENV_OVERRIDES):
        return None
    try:
        here = Path(root).resolve()
    except OSError:
        return None
    for d in (here, *here.parents):
        dot = d / ".git"
        if dot.is_dir():
            return dot if (dot / "HEAD").is_file() else None
        if dot.is_file():
            text = _read(dot)
            if not text or not text.startswith("gitdir:"):
                return None
            target = Path(text[len("gitdir:") :].strip())
            if not target.is_absolute():
                target = d / target
            return target if (target / "HEAD").is_file() else None
    return None


def work_tree(root: Path) -> Path | None:
    """The top of the work tree containing `root` (where its `.git` is), or None.

    None whenever git might put it elsewhere: an environment override, or a
    `core.worktree` setting (in `config` or `config.worktree`). The caller then
    asks git (`rev-parse --show-prefix`).
    """
    if any(os.environ.get(k) for k in _ENV_OVERRIDES):
        return None
    gd = git_dir(root)
    if gd is None or not _supported(gd):
        return None
    for name in ("config", "config.worktree"):
        for base in {gd, _common_dir(gd)}:
            if re.search(r"(?im)^\s*worktree\s*=", _read(base / name) or ""):
                return None
    try:
        here = Path(root).resolve()
    except OSError:
        return None
    for d in (here, *here.parents):
        if (d / ".git").exists():
            return d
    return None


def _common_dir(gd: Path) -> Path:
    text = _read(gd / "commondir")
    if text and text.strip():
        common = Path(text.strip())
        return common if common.is_absolute() else (gd / common)
    return gd


def _supported(gd: Path) -> bool:
    common = _common_dir(gd)
    if (common / "reftable").exists():
        return False
    config = _read(common / "config") or ""
    return "refstorage" not in config.lower()


def _resolve(gd: Path, ref: str, depth: int = 0) -> str | None:
    """The sha `ref` (e.g. `refs/heads/main`) points at, or None."""
    if depth > 5 or not ref.startswith("refs/") or ".." in ref:
        return None
    common = _common_dir(gd)
    for base in (gd, common) if ref.startswith(("refs/bisect", "refs/worktree")) else (common,):
        text = _read(base / ref)
        if text is not None:
            text = text.strip()
            if text.startswith("ref:"):
                return _resolve(gd, text[4:].strip(), depth + 1)
            return text if _SHA_RE.match(text) else None
    packed = _read(common / "packed-refs")
    if packed:
        for line in packed.splitlines():
            if not line or line[0] in "#^":
                continue
            sha, _, name = line.partition(" ")
            if name.strip() == ref and _SHA_RE.match(sha):
                return sha
    return None


def _head(root: Path) -> tuple[Path, str] | None:
    gd = git_dir(root)
    if gd is None or not _supported(gd):
        return None
    text = _read(gd / "HEAD")
    if text is None:
        return None
    return gd, text.strip()


def branch(root: Path) -> str | None:
    """The checked-out branch's short name, `HEAD` when detached, or None."""
    found = _head(root)
    if found is None:
        return None
    _gd, head = found
    if head.startswith("ref: refs/heads/"):
        return head[len("ref: refs/heads/") :] or None
    if _SHA_RE.match(head):
        return "HEAD"
    return None


def head_sha(root: Path) -> str | None:
    """HEAD's full sha, or None (unborn branch, or not readable here)."""
    found = _head(root)
    if found is None:
        return None
    gd, head = found
    if head.startswith("ref:"):
        return _resolve(gd, head[4:].strip())
    return head if _SHA_RE.match(head) else None


def has_ref(root: Path, ref: str) -> bool | None:
    """Does `ref` exist? None when this cannot tell."""
    found = _head(root)
    if found is None:
        return None
    return _resolve(found[0], ref) is not None


def symbolic_target(root: Path, ref: str) -> str | None:
    """What a symbolic ref such as `refs/remotes/origin/HEAD` points at.

    None both when it is absent and when it cannot be read; the caller asks
    git when it needs to tell the two apart (`has_ref` says which).
    """
    found = _head(root)
    if found is None:
        return None
    text = _read(_common_dir(found[0]) / ref)
    if text and text.strip().startswith("ref:"):
        return text.strip()[4:].strip()
    return None
