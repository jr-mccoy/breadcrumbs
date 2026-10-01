"""breadcrumbs — shorten a record's file name, and trim a long handoff log.

**`crumb rename <id> --slug <short>`** (DoWhat field report 2026-10-01, issue
5). Records written before the 60-character slug cap have names of 130-150
characters; on Windows a checkout path plus `.project-memory/<type>/` plus such
a name passes the 260-character limit, and `git add` and the migration backup
both failed. A record's id is derived from its filename, so renaming changes
the id. Everything that names the old id is updated: every other committed
store file that mentions it (links such as `superseded_by`, handoff and
current notes, indexes). The old id is kept in the record's `formerly:` list,
so `crumb show <old id>` and the other lookups still find it — commit messages
that cite it cannot be rewritten, and need not be.

**`crumb handoff trim --keep N`** (issue 1). `--next` adds an entry to the
handoff's Next Action and never removes one, so a long-lived handoff grows.
Trim moves all but the newest N entries, unchanged, to the top of a committed
history file beside the handoff. Nothing is deleted.
"""

from __future__ import annotations

import re
from pathlib import Path

from breadcrumbs import cli, path_policy

_SKIP_DIRS = ("private", "index", "generated")


def _store_text_files(memory_dir: Path):
    for path in sorted(Path(memory_dir).rglob("*.md")):
        rel = path.relative_to(memory_dir).parts
        if rel and rel[0] in _SKIP_DIRS:
            continue
        yield path


def rename_record(memory_dir: Path, root: Path, rid: str, slug: str) -> dict:
    """Rename record `rid` to `slug`. `{ok, from, to, path, updated, error}`."""
    from breadcrumbs import mutations as _mutations

    memory_dir = Path(memory_dir)
    rec = cli.find_record_by_id(memory_dir, rid)
    if rec is None or rec.error:
        return {"ok": False, "error": f"no record with id {rid!r}"}
    new_slug = cli.slugify(slug)
    if not new_slug or new_slug != slug.strip().lower():
        return {
            "ok": False,
            "error": f"slug must be lowercase words and hyphens, e.g. {new_slug!r}",
        }
    old_stem = rec.stem
    dated = re.match(r"^(\d{4}-\d{2}-\d{2})-", old_stem)
    new_stem = f"{dated.group(1)}-{new_slug}" if dated else new_slug
    ident = cli.derive_identity(new_stem, rec.rtype)
    if ident is None:
        return {"ok": False, "error": f"{new_stem!r} is not a valid {rec.rtype} file name"}
    new_id = ident[0]
    old_id = str(rec.meta.get("id") or (cli.derive_identity(old_stem, rec.rtype) or [rid])[0])
    if new_id == old_id:
        return {"ok": False, "error": "that is already its name"}
    if cli.find_record_by_id(memory_dir, new_id) is not None:
        return {"ok": False, "error": f"{new_id} already exists"}
    new_path = rec.path.with_name(new_stem + rec.path.suffix)
    word = re.compile(rf"(?<![\w-]){re.escape(old_id)}(?![\w-])")
    updated: list[str] = []
    with _mutations.transaction(memory_dir, "rename"):
        original = path_policy.read_text(rec.path)
        meta, body = cli.parse_frontmatter(original)
        meta["id"] = new_id
        formerly = [str(x) for x in (meta.get("formerly") or [])]
        if old_id not in formerly:
            formerly.append(old_id)
        meta["formerly"] = formerly
        meta["updated_at"] = cli.now_iso()
        cli.write_text_atomic(new_path, cli.render_frontmatter(meta) + "\n" + body.lstrip("\n"))
        rec.path.unlink()
        for path in _store_text_files(memory_dir):
            if path == new_path:
                continue
            text = path_policy.read_text(path)
            if word.search(text):
                cli.write_text_atomic(path, word.sub(new_id, text), expected=text)
                updated.append(path.relative_to(memory_dir).as_posix())
        fails = cli._validate_new_file(memory_dir, new_path)
        if fails:
            raise _mutations.MutationFailed(
                "the renamed record failed validation: " + "; ".join(f["message"] for f in fails)
            )
    cli.reindex_projections(memory_dir, root)
    return {
        "ok": True,
        "from": old_id,
        "to": new_id,
        "path": str(new_path),
        "updated": updated,
        "error": None,
    }


def long_record_paths(root: Path, memory_dir: Path, limit: int) -> list[tuple[str, int]]:
    """`(path from the project root, length)` for each store file over `limit`."""
    out = []
    for path in _store_text_files(memory_dir):
        rel = path.relative_to(Path(root)).as_posix()
        if len(rel) > limit:
            out.append((rel, len(rel)))
    return sorted(out, key=lambda x: -x[1])


# --------------------------------------------------------------------------- #
# crumb handoff trim
# --------------------------------------------------------------------------- #


def history_path(handoff: Path) -> Path:
    """`handoff-history.md` beside `handoff.md`; `<slug>.history.md` for a branch."""
    handoff = Path(handoff)
    if handoff.name == "handoff.md":
        return handoff.with_name("handoff-history.md")
    return handoff.with_name(handoff.stem + ".history.md")


def trim_handoff(memory_dir: Path, root: Path, keep: int) -> dict:
    """Move all but the newest `keep` Next Action entries to the history file."""
    from breadcrumbs import handoffs as _handoffs
    from breadcrumbs import mutations as _mutations

    memory_dir = Path(memory_dir)
    path = _handoffs.write_path(memory_dir, root, cli.git_branch(root))
    if not path.is_file():
        return {"ok": False, "error": f"no handoff at {path.relative_to(memory_dir).as_posix()}"}
    text = path_policy.read_text(path)
    spans = {h.strip(): (a, b) for a, b, h in cli._md_heading_spans(text)}
    if "Next Action" not in spans:
        return {"ok": False, "error": "the handoff has no Next Action section"}
    start, end = spans["Next Action"]
    section = text[start:end]
    head, _, content = section.partition("\n")
    blocks = _entry_blocks(content)
    if len(blocks) <= keep:
        return {"ok": True, "moved": 0, "kept": len(blocks), "history": None}
    kept, moved = blocks[:keep], blocks[keep:]
    new_section = head + "\n" + "\n\n".join(b.strip("\n") for b in kept).rstrip() + "\n\n"
    hist = history_path(path)
    rel = path.relative_to(memory_dir).as_posix()
    marker = "<!-- entries below, newest first -->"
    with _mutations.transaction(memory_dir, "handoff-trim"):
        prior = path_policy.read_text(hist) if hist.is_file() else ""
        if marker in prior:
            header, _, older = prior.partition(marker)
        else:
            header = (
                f"# Handoff history\n\n_Earlier Next Action entries moved here from `{rel}` by "
                "`crumb handoff trim`. `resume` does not read this file._\n\n"
            )
            older = ("\n" + prior) if prior.strip() else ""
        moved_text = "\n\n".join(b.strip("\n") for b in moved).rstrip()
        new_hist = header + marker + "\n" + moved_text + "\n" + older.rstrip("\n") + "\n"
        cli.write_text_atomic(hist, new_hist)
        cli.write_text_atomic(path, text[:start] + new_section + text[end:], expected=text)
    return {
        "ok": True,
        "moved": len(moved),
        "kept": len(kept),
        "history": hist.relative_to(memory_dir).as_posix(),
    }


def _entry_blocks(content: str) -> list[str]:
    """The Next Action section's entries with their header lines, newest first."""
    blocks: list[list[str]] = []
    for line in content.splitlines():
        if cli.NEXT_ENTRY_HEADER_RE.match(line) or not blocks:
            blocks.append([line])
        else:
            blocks[-1].append(line)
    return ["\n".join(b) for b in blocks if "\n".join(b).strip()]
