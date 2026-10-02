"""breadcrumbs — assisted repair of records that break the record contract.

The DoWhat field report (2026-10-01, issue 12) found 133 `validate` failures,
most of them records written by hand while the CLI was unavailable:
verifications with no frontmatter, a free `scope` like `breadcrumbs`, statuses
such as `fixed`. Readers either dropped those records or misread them (N3), and
nothing helped a person fix them.

`crumb repair` fills in what can be known honestly and asks for what cannot:

- **Derived** (no guessing): the id, type and slug from the filename; the
  title from the `# ` heading or the slug; `created_at` from the filename date;
  `created_by`, `branch` and `commit` from the commit that added the file;
  `status: active`; `privacy: repo-safe` (it is a committed file); a
  verification's `subject` from its title.
- **Mapped**, keeping the original: a status outside the vocabulary
  (`fixed`, `resolved …`, `done` → `stale`; for a question `answered` or
  `closed`), and a free scope (→ `project`, which is how every reader already
  read it). The original value is kept in `repaired_from`.
- **Never invented**: a verification's `outcome`, and evidence. Repair sets
  `confidence: low` on a record with no evidence (the honest state), proposes
  file paths it found in the body, and lists each outcome a person must give,
  with the exact command (`--set <id>.outcome=fixed`).

Nothing is written without `--apply`. With it, every rewrite goes through the
store's mutation journal and the validate gate: a rewrite that would introduce
a failure is not made.
"""

from __future__ import annotations

import re
from pathlib import Path

from breadcrumbs import cli, path_policy
from breadcrumbs import validation as _validation

# Status words people use for "this no longer applies"; the same reading as the
# migration's block mapping (blockfiles._legacy_fixes).
_ANSWERED_WORDS = ("resolved", "fixed", "done", "answered", "solved", "complete", "completed")

_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")
_H1_RE = re.compile(r"(?m)^#\s+(.+?)\s*$")


def _mapped_status(rtype: str, raw: str) -> str:
    if rtype == "question":
        first = re.split(r"[^a-z]+", raw.lower(), maxsplit=1)[0]
        return "answered" if first in _ANSWERED_WORDS else "closed"
    return "stale"


def _adding_commit(root: Path, path: Path) -> dict:
    """`{author, commit, date}` of the commit that added `path`, or `{}`."""
    if not cli.is_git_repo(root):
        return {}
    out = cli._git_out(
        root,
        "log",
        "--diff-filter=A",
        "--format=%an%x00%h%x00%aI",
        "-n",
        "1",
        "--",
        str(path),
    )
    if not out:
        return {}
    parts = out.splitlines()[-1].split("\0")
    if len(parts) != 3:
        return {}
    return {"author": parts[0], "commit": parts[1], "date": parts[2]}


# Trailing characters prose leaves on a path: "see Asia/Tokyo." or "(app/x.kt)".
_TRAILING_PUNCT = ".,;:!?)]}'\"`"


def _head_files(root: Path) -> frozenset[str]:
    """Every path in HEAD's tree (one git call per repair run)."""
    return cli.op_memo(
        ("repair_head_files", str(root)),
        lambda: frozenset(
            (
                cli._git_out(root, "ls-tree", "-r", "--name-only", "--full-tree", "HEAD") or ""
            ).splitlines()
        ),
    )


def citable_paths(root: Path, candidates) -> list[str]:
    """The candidates that are files this project has: in the working tree or
    in HEAD, relative to the project root.

    A path-*shaped* word is not evidence (DoWhat retest of 0.5.0, item 10):
    repair suggested `Asia/Tokyo.`, `APPDATA/npm`, `/home/user/android-sdk`,
    part of a database push key and an API route. Guard keeps the structural
    test on purpose (a record may name a file since deleted); a *suggestion*
    to cite a file should only name one that is there.
    """
    root = Path(root)
    out: set[str] = set()
    head: frozenset[str] | None = None
    for raw in candidates:
        p = str(raw).strip().rstrip(_TRAILING_PUNCT).replace("\\", "/")
        if not p or p.startswith(("/", "~")) or ":" in p or ".." in p.split("/"):
            continue  # absolute, a drive, or outside the project
        p = p[2:] if p.startswith("./") else p
        try:
            on_disk = (root / p).exists()
        except OSError:
            on_disk = False
        if not on_disk:
            if head is None:
                head = _head_files(root) if cli.is_git_repo(root) else frozenset()
            if p.rstrip("/") not in head and not any(
                f.startswith(p.rstrip("/") + "/") for f in head
            ):
                continue
        out.add(p)
    return sorted(out)


def plan_record(rec: "cli.Record", memory_dir: Path, root: Path, sets: dict) -> dict | None:
    """What repair would change in one record: `{path, id, changes, meta,
    needs, proposals}`, or None when it needs nothing."""
    if rec.error:
        return None
    meta = dict(rec.meta or {})
    rtype = rec.rtype
    ident = cli.derive_identity(rec.stem, rtype)
    rid = (meta.get("id") or (ident[0] if ident else None)) or rec.stem
    changes: list[str] = []
    repaired: list[str] = list(meta.get("repaired_from") or [])
    needs: list[str] = []
    proposals: list[str] = []
    added = None

    def adding() -> dict:
        nonlocal added
        if added is None:
            added = _adding_commit(root, rec.path)
        return added

    hand_written = not rec.meta
    if hand_written:
        changes.append("add frontmatter (the file had none)")
    if not meta.get("title"):
        m = _H1_RE.search(rec.body or "")
        meta["title"] = (
            m.group(1).strip() if m else (ident[1] if ident else rec.stem).replace("-", " ").strip()
        )
        changes.append(f"title: {meta['title']!r} (from the heading or filename)")
    if not meta.get("id") and ident:
        meta["id"] = ident[0]
    if not meta.get("created_at"):
        # The filename's date is the author's; the adding commit may be weeks
        # later (records kept by hand while the CLI was unavailable).
        dm = _DATE_RE.match(rec.path.name)
        stamp = (
            f"{dm.group(1)}-{dm.group(2)}-{dm.group(3)}T00:00:00+00:00" if dm else None
        ) or adding().get("date")
        if stamp:
            meta["created_at"] = stamp
            changes.append(f"created_at: {stamp}")
        else:
            needs.append(f"{rid}: no date in the filename or git history (set created_at)")
    if not meta.get("updated_at") and meta.get("created_at"):
        meta["updated_at"] = meta["created_at"]
    if hand_written:
        info = adding()
        meta.setdefault("created_by", info.get("author") or "unknown")
        meta.setdefault("agent", "unknown")
        if info.get("commit"):
            meta.setdefault("commit", info["commit"])
        meta.setdefault("tags", [])
        meta.setdefault("evidence", [])
    vocab = cli.VALID_QUESTION_STATUS if rtype == "question" else cli.VALID_STATUS
    status = meta.get("status")
    if status in (None, ""):
        meta["status"] = "open" if rtype == "question" else "active"
        changes.append(f"status: {meta['status']}")
    elif str(status) not in vocab:
        new = _mapped_status(rtype, str(status))
        repaired.append(f"status: {status}")
        meta["status"] = new
        changes.append(f"status {str(status)[:60]!r} -> {new} (original kept in repaired_from)")
    if meta.get("status") == "superseded" and not meta.get("superseded_by"):
        repaired.append("status: superseded (no successor named)")
        meta["status"] = "stale" if rtype != "question" else "closed"
        changes.append(f"status superseded with no successor -> {meta['status']}")
    if not meta.get("privacy"):
        meta["privacy"] = "repo-safe"
        changes.append("privacy: repo-safe (a committed file)")
    scope = meta.get("scope")
    if scope not in (None, "") and str(scope) not in _validation.RECORD_SCOPES:
        repaired.append(f"scope: {scope}")
        meta["scope"] = "project"
        changes.append(f"scope {scope!r} -> project (how readers already read it)")
    elif scope in (None, "") and hand_written:
        meta["scope"] = "project"
    if rtype == "verification":
        if meta.get("subject") in (None, ""):
            meta["subject"] = meta.get("title")
            changes.append("subject: the title")
        wanted = sets.get((str(rid), "outcome")) or sets.get((rec.stem, "outcome"))
        if wanted:
            if wanted not in cli.VALID_VERIFICATION_OUTCOME:
                needs.append(
                    f"{rid}: outcome {wanted!r} is not one of "
                    + ", ".join(cli.VALID_VERIFICATION_OUTCOME)
                )
            elif meta.get("outcome") != wanted:
                meta["outcome"] = wanted
                changes.append(f"outcome: {wanted} (given with --set)")
        elif meta.get("outcome") not in cli.VALID_VERIFICATION_OUTCOME:
            needs.append(
                f"{rid}: what was the outcome? — `crumb repair --apply --set "
                f"{rid}.outcome=fixed|open|regressed|not_applicable|inconclusive`"
            )
    if (
        not meta.get("evidence")
        and meta.get("confidence") not in ("low",)
        and rtype
        in (
            "decision",
            "attempt",
            "verification",
        )
    ):
        meta["confidence"] = "low"
        changes.append("confidence: low (no evidence recorded)")
        found = citable_paths(root, cli._paths_from_text(rec.body or ""))[:3]
        if found:
            proposals.append(
                f"{rid}: evidence it could cite: "
                + ", ".join(f"`--evidence file {p}`" for p in found)
            )
    if repaired != list(rec.meta.get("repaired_from") or []):
        meta["repaired_from"] = repaired
    if not changes and not needs:
        return None
    return {
        "path": rec.path,
        "rel": rec.path.relative_to(memory_dir).as_posix(),
        "id": str(rid),
        "changes": changes,
        "meta": meta,
        "needs": needs,
        "proposals": proposals,
    }


def plan(memory_dir: Path, root: Path, sets: dict | None = None) -> list[dict]:
    """Every record repair would touch, in path order."""
    sets = sets or {}
    out = []
    for dirname, rtype in cli.DIR_TYPES.items():
        if dirname in ("inbox", "sessions"):
            continue  # machine-written; a jot expires, a session is a log
        for rec in cli.records_in(Path(memory_dir) / dirname, rtype):
            p = plan_record(rec, Path(memory_dir), Path(root), sets)
            if p is not None:
                out.append(p)
    return sorted(out, key=lambda p: p["rel"])


def apply(memory_dir: Path, root: Path, planned: list[dict]) -> dict:
    """Write the planned frontmatter. `{written, skipped}`; a rewrite that would
    introduce a validate failure is reverted and listed under `skipped`."""
    from breadcrumbs import mutations as _mutations

    written, skipped = [], []
    with _mutations.transaction(memory_dir, "repair"):
        for p in planned:
            if not p["changes"]:
                continue
            path = Path(p["path"])
            before = path_policy.read_text(path)
            body = cli.parse_frontmatter(before)[1] if before.lstrip().startswith("---") else before
            text = cli.render_frontmatter(p["meta"]) + "\n" + body.lstrip("\n")
            cli.write_text_atomic(path, text, expected=before)
            fails = cli._validate_new_file(memory_dir, path, before)
            if fails:
                cli.write_text_atomic(path, before)
                skipped.append({"id": p["id"], "reason": "; ".join(f["message"] for f in fails)})
            else:
                written.append(p["id"])
    if written:
        cli.reindex_projections(memory_dir, root)
    return {"written": written, "skipped": skipped}


def parse_sets(pairs: list[str] | None) -> dict:
    """`["ver_x.outcome=fixed"]` -> `{("ver_x", "outcome"): "fixed"}`."""
    out = {}
    for raw in pairs or []:
        key, _, value = str(raw).partition("=")
        rid, _, field = key.rpartition(".")
        if rid and field and value:
            out[(rid.strip(), field.strip())] = value.strip()
    return out
