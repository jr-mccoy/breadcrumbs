"""breadcrumbs — one handoff per branch (WM-50, schema 4).

`handoff.md` is the store's "what the next session should do first". It was a
singleton, so two agents on two branches overwrote each other's next action,
and a feature branch's handoff ("finish the migration on this branch") was the
first thing a session on `main` read.

From schema 4 a capture on a branch that is not the repository's default branch
writes `handoffs/<branch-slug>.md` instead — same sections, same metadata lines —
and leaves `handoff.md` to the default branch. A resume reads its own branch's
handoff when there is one and falls back to `handoff.md`, and says which.
`current.md` stays a singleton: it is the project's focus, not a branch's.

Readers switch on the manifest version, as every schema step does; a store at
schema 3 keeps writing `handoff.md` from every branch, exactly as before.
"""

from __future__ import annotations

from pathlib import Path

from breadcrumbs import cli

HANDOFFS_SCHEMA = 4
HANDOFFS_DIR = "handoffs"
# `crumb prune handoffs` removes a branch handoff only when its branch is gone
# *and* it has not been touched in this long: a branch deleted this morning may
# be recreated this afternoon, and its handoff is exactly what that session wants.
PRUNE_MIN_AGE_DAYS = 30


def uses_branch_handoffs(memory_dir: Path) -> bool:
    manifest = cli.load_manifest(Path(memory_dir)) or {}
    try:
        return int(str(manifest.get("schema_version", "1")).strip()) >= HANDOFFS_SCHEMA
    except ValueError:
        return False


def default_branch(root: Path) -> str | None:
    """The repository's default branch, or None when every branch counts as default.

    `origin/HEAD` when the clone knows it; otherwise `main`, then `master`, if
    such a local branch exists. None — no git, or neither exists — means there
    is no branch to tell apart from the others, so everything goes to
    `handoff.md` as it always did.
    """
    root = Path(root)
    if not cli.is_git_repo(root):
        return None
    ref = cli._git_out(root, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    if ref and ref.strip().startswith("refs/remotes/origin/"):
        return ref.strip()[len("refs/remotes/origin/") :]
    for name in ("main", "master"):
        if cli._git_out(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}") is not None:
            return name
    return None


def branch_slug(branch: str) -> str:
    """The handoff file stem for `branch`: its slug, plus a short hash when the
    slug is not the branch name itself.

    `slugify` is lossy — `feature/parser-rewrite` and `feature-parser-rewrite`,
    or `Fix` and `fix`, fold to one slug — and two branches sharing a handoff
    file is the overwrite WM-50 exists to stop. A branch whose name already is
    its slug keeps the plain, readable name.
    """
    import hashlib

    slug = cli.truncate_slug(cli.slugify(branch))
    if slug == branch:
        return slug
    return f"{slug}-{hashlib.sha1(branch.encode('utf-8')).hexdigest()[:6]}"


def _is_feature_branch(root: Path, branch: str | None) -> bool:
    if not branch or branch in (cli.NO_GIT_BRANCH, "HEAD"):
        return False
    default = default_branch(root)
    return default is not None and branch != default


def branch_handoff_path(memory_dir: Path, branch: str) -> Path:
    return Path(memory_dir) / HANDOFFS_DIR / f"{branch_slug(branch)}.md"


def write_path(memory_dir: Path, root: Path, branch: str | None) -> Path:
    """Where a capture on `branch` writes its handoff."""
    memory_dir = Path(memory_dir)
    if uses_branch_handoffs(memory_dir) and _is_feature_branch(root, branch):
        return branch_handoff_path(memory_dir, branch)
    return memory_dir / "handoff.md"


def read_path(memory_dir: Path, root: Path) -> tuple[Path, str]:
    """The handoff a resume on the current branch reads, and how to say so.

    `(path, label)` — label is `handoffs/<slug>.md`, `handoff.md`, or
    `handoff.md (no branch handoff)` on a feature branch that has not captured
    yet.
    """
    memory_dir = Path(memory_dir)
    single = memory_dir / "handoff.md"
    if not uses_branch_handoffs(memory_dir):
        return single, "handoff.md"
    branch = cli.git_branch(root)
    if not _is_feature_branch(root, branch):
        return single, "handoff.md"
    own = branch_handoff_path(memory_dir, branch)
    if own.is_file():
        return own, f"{HANDOFFS_DIR}/{own.name}"
    return single, "handoff.md (no branch handoff)"


def read_text(memory_dir: Path, root: Path) -> tuple[str, str | None, Path]:
    """`(text, problem, path)` of the handoff this branch reads; lenient."""
    path, _label = read_path(memory_dir, root)
    if not path.is_file():
        return "", None, path
    text, problem = cli.read_text_lenient(path)
    return text, problem, path


def seed_text(memory_dir: Path, path: Path) -> str:
    """What a handoff update starts from: the file itself, or — for a branch's
    first handoff — `handoff.md`'s Current Focus and nothing else.

    A new branch is usually cut from the default branch mid-thought; starting
    empty would drop the focus the session just read. Nothing more carries
    over: copying `handoff.md`'s Next Action under this branch's fresh date,
    branch and commit lines would pass off another branch's stale instruction
    as this one's, and hide it from the age and branch-mismatch checks.
    """
    if path.is_file():
        return path.read_text(encoding="utf-8")
    single = Path(memory_dir) / "handoff.md"
    if path == single or not single.is_file():
        return single.read_text(encoding="utf-8") if single.is_file() else ""
    focus = cli.split_md_sections(single.read_text(encoding="utf-8")).get("Current Focus", "")
    return f"## Current Focus\n{focus}\n" if not cli._is_placeholder(focus) else ""


# --------------------------------------------------------------------------- #
# crumb prune handoffs
# --------------------------------------------------------------------------- #


def live_branch_slugs(root: Path) -> set[str] | None:
    """Slugs of every local branch and every `origin/` branch; None without git."""
    root = Path(root)
    if not cli.is_git_repo(root):
        return None
    names: set[str] = set()
    local = cli._git_out(root, "for-each-ref", "--format=%(refname:short)", "refs/heads")
    remote = cli._git_out(root, "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
    for line in (local or "").splitlines():
        if line.strip():
            names.add(line.strip())
    for line in (remote or "").splitlines():
        name = line.strip()
        if name.startswith("origin/"):
            name = name[len("origin/") :]
        if name and name != "HEAD" and name != "origin":
            names.add(name)
    return {branch_slug(n) for n in names}


def orphan_handoffs(memory_dir: Path, root: Path) -> list[dict]:
    """Branch handoffs whose branch is gone and which are older than the floor."""
    directory = Path(memory_dir) / HANDOFFS_DIR
    live = live_branch_slugs(root)
    if live is None or not directory.is_dir():
        return []
    out = []
    for path in sorted(directory.glob("*.md")):
        if path.stem in live:
            continue
        meta = cli.parse_handoff_meta(cli.read_text_lenient(path)[0])
        age = cli._age_days(meta.get("updated_at"))
        if age is None or age < PRUNE_MIN_AGE_DAYS:
            continue
        out.append(
            {
                "path": f"{HANDOFFS_DIR}/{path.name}",
                "branch": meta.get("branch"),
                "age_days": age,
            }
        )
    return out


def prune_handoffs(memory_dir: Path, root: Path, *, dry_run: bool = False) -> dict:
    orphans = orphan_handoffs(memory_dir, root)
    if not dry_run:
        for o in orphans:
            (Path(memory_dir) / o["path"]).unlink(missing_ok=True)
        if orphans:
            cli.reindex_projections(Path(memory_dir), Path(root))
    return {"ok": True, "pruned": orphans, "dry_run": dry_run}
