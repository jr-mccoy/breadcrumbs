"""breadcrumbs — the one owner of git state.

Every git question the package asks goes through here. Before this module the
answers came two ways: `cli._git_out` started `git`, while `gitrefs` read
`.git` from disk, and five other modules called the private `cli._git_out`.
`cli.git_commit` returned a short sha from a subprocess and `gitrefs.head_sha` a
full one, and comparing the two by string was field-report item N8 (a phantom
"HEAD moved" block whenever `core.abbrev` differed).

The rules:

- **Full shas for identity.** `head()` is HEAD's full sha; compare commits with
  it, or with `same_commit()` when one side is a stored short sha.
- **Short shas for display and for the record's `commit` field** (`short_head()`),
  which is a stored format and stays as git abbreviates it.
- **Disk first, `git` second.** `gitrefs` answers what it can from `.git`
  without a process (each costs 50-80 ms with Git for Windows); anything it
  cannot answer for certain is asked of `git` exactly as before.

This module imports nothing from the rest of the package except `gitrefs`, so
any module can use it without an import cycle through `cli`.
"""

from __future__ import annotations

import time
from pathlib import Path

from breadcrumbs import gitrefs

# What a record's `branch` / `commit` field holds outside a git work tree.
NO_BRANCH = "(no-git)"
NO_COMMIT = "(no-git)"

# git processes started by this process, for the hook log's `git` count: on
# Windows each costs tens of milliseconds, and a count says at once whether a
# slow firing was git or Python (field report 2026-10-01, issue 6).
CALLS = [0]
# ...and the milliseconds they took, for the hook log's `git_ms` (item 7 of the
# 0.5.0 retest: the next Windows measurement should say where the time went).
MS = [0.0]


def run(root: Path, *args: str) -> str | None:
    """`git <args>`'s stdout in `root`, trailing newline trimmed; None on failure."""
    import subprocess  # here, not at the top: most guard firings start no git (item 2)

    CALLS[0] += 1
    started = time.perf_counter()
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
    finally:
        MS[0] += (time.perf_counter() - started) * 1000
    if r.returncode != 0:
        return None
    # Trailing newline only. A whole-output strip() also ate the leading space of
    # the *first* line, which for `status --porcelain` is a status column — a
    # worktree-only modification is " M path", so the caller's line[3:] then
    # chopped three characters off the path. Every other caller
    # reads single-line output or regex-matches, so both forms suit them.
    return r.stdout.rstrip("\n")


def check_ignore(root: Path, rels: list[str]) -> list[tuple[str, str, str]] | None:
    """`(source, pattern, path)` for each of `rels` an ignore rule matches.

    Every rule git knows counts here, machine-local excludes included; the
    caller filters by `source`. None when git cannot answer.
    """
    import subprocess

    CALLS[0] += 1
    started = time.perf_counter()
    # `-z`: NUL-separated bytes both ways. Text-mode stdin sent each path with
    # "\r\n" on Windows, git read `ideas\r`, and nothing ever matched there
    # (audit WP17); `-z` also leaves unusual names unquoted.
    try:
        r = subprocess.run(
            ["git", "check-ignore", "-v", "-z", "--no-index", "--stdin"],
            cwd=str(root),
            input=b"".join(rel.encode("utf-8") + b"\0" for rel in rels),
            capture_output=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return None
    finally:
        MS[0] += (time.perf_counter() - started) * 1000
    if r.returncode not in (0, 1):  # 1 = nothing ignored; anything else is an error
        return None
    fields = r.stdout.decode("utf-8", errors="replace").split("\0")
    # Each match is four fields: source, line number, pattern, path.
    return [
        (source, pattern, path)
        for source, _line, pattern, path in (
            fields[i : i + 4] for i in range(0, len(fields) - 3, 4)
        )
    ]


# Memo for `is_repo`, keyed by (path, does `.git` exist there) so the answer is
# re-probed the moment that changes — `git init` after a negative probe re-keys the
# entry instead of returning a stale False. Five of one guard call's ten remaining
# subprocess spawns were this same question asked five times; a stat is
# ~1000x cheaper than a process, and much more so on Windows.
_IS_REPO_CACHE: dict[tuple[str, bool], bool] = {}


def is_repo(root: Path) -> bool:
    """True if `root` is inside a git work tree."""
    key = (str(root), (Path(root) / ".git").exists())
    cached = _IS_REPO_CACHE.get(key)
    if cached is not None:
        return cached
    # A `.git` found by walking up answers without a process (DoWhat retest of
    # 0.5.0, item 7); anything unusual still asks git.
    if gitrefs.git_dir(Path(root)) is not None:
        _IS_REPO_CACHE[key] = True
        return True
    answer = run(root, "rev-parse", "--is-inside-work-tree") == "true"
    _IS_REPO_CACHE[key] = answer
    return answer


def work_tree(root: Path) -> Path | None:
    """The top of the work tree holding `root`, read from `.git` without a
    process; None when only git can say (see `gitrefs.work_tree`)."""
    return gitrefs.work_tree(Path(root))


def branch(root: Path) -> str:
    """The checked-out branch, `HEAD` when detached, or `NO_BRANCH`."""
    if not is_repo(root):
        return NO_BRANCH
    fast = gitrefs.branch(root)
    if fast:
        return fast
    out = run(root, "rev-parse", "--abbrev-ref", "HEAD")
    if out:
        return out
    # An unborn HEAD (fresh repo, no commits yet) fails rev-parse but still has
    # a real branch name — read it so records don't pair `branch: (no-git)` with
    # populated dirty_files.
    out = run(root, "symbolic-ref", "--short", "HEAD")
    return out if out else NO_BRANCH


def head(root: Path, *, spawn: bool = True) -> str | None:
    """HEAD's full sha, or None (no git, or an unborn branch).

    `spawn=False` reads `.git` only and returns None where that cannot answer,
    for a caller that must not start a process.
    """
    fast = gitrefs.head_sha(root)
    if fast or not spawn:
        return fast
    if not is_repo(root):
        return None
    out = run(root, "rev-parse", "--verify", "--quiet", "HEAD")
    return out.strip() if out and out.strip() else None


def short_head(root: Path) -> str:
    """HEAD abbreviated the way this repo's git abbreviates it, or `NO_COMMIT`.

    This is the value a record's `commit` field stores. Its length depends on
    `core.abbrev` and the object count, so compare it with `same_commit()`.
    """
    if not is_repo(root):
        return NO_COMMIT
    out = run(root, "rev-parse", "--short", "HEAD")
    return out if out else NO_COMMIT


def same_commit(a: str, b: str) -> bool:
    """Two commit ids name the same commit, whatever their abbreviation length.

    Short shas are compared as strings across machines, where `core.abbrev` or
    a grown object count can make one longer than the other (N8)."""
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b or NO_COMMIT in (a, b):
        return a == b
    n = min(len(a), len(b))
    return n >= 7 and a[:n] == b[:n]


def default_branch(root: Path) -> str | None:
    """`origin/HEAD`'s branch, else a local `main` or `master`; None when neither."""
    if not is_repo(root):
        return None
    # Read from .git when it can be (no `git` process on the guard path; DoWhat
    # retest of 0.5.0, item 7); `git` answers whatever that cannot.
    readable = gitrefs.has_ref(root, "refs/heads/main") is not None
    if readable:
        ref = gitrefs.symbolic_target(root, "refs/remotes/origin/HEAD")
    else:
        ref = run(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if ref and ref.strip().startswith("refs/remotes/origin/"):
        return ref.strip()[len("refs/remotes/origin/") :]
    for name in ("main", "master"):
        if readable:
            if gitrefs.has_ref(root, f"refs/heads/{name}"):
                return name
        elif run(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}") is not None:
            return name
    return None


def branch_names(root: Path) -> set[str] | None:
    """Every local branch and every `origin/` branch (without `origin/`); None without git."""
    if not is_repo(root):
        return None
    names: set[str] = set()
    local = run(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    remote = run(root, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
    for line in (local or "").splitlines():
        if line.strip():
            names.add(line.strip())
    for line in (remote or "").splitlines():
        name = line.strip()
        if name.startswith("origin/"):
            name = name[len("origin/") :]
        if name and name != "HEAD" and name != "origin":
            names.add(name)
    return names


# git C-style escapes used in quoted porcelain paths (paths with spaces/quotes/
# non-ASCII are emitted as "caf\303\251.txt"; octal escapes are raw UTF-8 bytes).
_PATH_ESCAPES = {
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


def unquote_path(path: str) -> str:
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
            if nxt in _PATH_ESCAPES:
                out.append(_PATH_ESCAPES[nxt])
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


def status_paths(root: Path) -> list[str]:
    """Every uncommitted path `git status` reports, relative to the repo root."""
    if not is_repo(root):
        return []
    out = run(root, "status", "--porcelain")
    if not out:
        return []
    files: list[str] = []
    for line in out.splitlines():
        # porcelain: 2 status chars + space + path
        path = line[3:].strip() if len(line) > 3 else line.strip()
        if " -> " in path:
            # rename/copy entries are "R  old -> new"; record the destination.
            path = path.split(" -> ", 1)[1].strip()
        path = unquote_path(path)
        if path:
            files.append(path)
    return files
