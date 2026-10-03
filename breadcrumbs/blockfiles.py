"""breadcrumbs — traps and questions as one file per record (WM-22).

Through schema 2 every trap is a `## trap_<slug>:` block in `known-traps.md` and
every question a `## Q:` block in `open-questions.md`. That shape reached 167 KB
and 77 active traps in one field store, parsed in full on every hook firing,
with every edit a splice into a file other writers were also splicing. Decisions
and verifications were already one file each; this makes traps and questions the
same.

**Nothing downstream changes.** At schema 3 `cli.load_traps` and
`cli.load_open_questions` return exactly the dict shapes they always returned —
`body` is rendered in the same bullet format the block writer used — so the
packet, the guard, the prefilter, `crumb traps`, audit and every scorer read
traps and questions through the code they already had. Search and guard results
are identical before and after migration by construction, and
`tests/test_blockfiles.py` pins that.

**Ids do not change.** Files are named by slug alone (`traps/<slug>.md`,
`questions/<slug>.md`), and the id is prefix + slug: `trap_<slug>` as before,
`q_<slug>` for questions (the `q:` spelling is still accepted on input). Ids are
cited in decision records, commit messages and people's notes; a migration that
changed them would break every one of those references.

**The singleton files stay, as generated indexes.** A cloud agent with no CLI
reads `known-traps.md` and `open-questions.md` directly (README, "Plain-file
fallback"). They become one line per record, pointing at the file, rebuilt on
every reindex — a projection, no longer a source.
"""

from __future__ import annotations

import re
from pathlib import Path

from breadcrumbs import cli
from breadcrumbs import path_policy
from breadcrumbs import scoring as _scoring
from breadcrumbs import validate as _validate

FILES_SCHEMA = 3
TRAP_DIR = "traps"
QUESTION_DIR = "questions"

# The block bullets, in the order the block writer emits them, mapped to the
# section each becomes. Order matters: `render_trap_body` reproduces exactly the
# text `cli._trap_block` would have written, which is what keeps every reader's
# view of a trap identical across the migration.
TRAP_BULLETS = (
    ("Area / files", "Area / files"),
    ("Symptom", "Symptom"),
    ("Why", "Why"),
    ("Safe approach", "Safe approach"),
    ("Verification", "Verification"),
)
QUESTION_BULLETS = (
    ("Why it matters", "Why it matters"),
    ("Needs", "Needs"),
)

# Bullets that are bookkeeping rather than content: they become frontmatter.
_META_BULLETS = {
    "status": "status",
    "superseded by": "superseded_by",
    "superseded_by": "superseded_by",
    "last confirmed": "last_confirmed",
    "last_confirmed": "last_confirmed",
    "promoted to": "promoted_to",
    "promoted_to": "promoted_to",
    "opened": "opened",
}

_BULLET_RE = re.compile(r"^\s*-\s*([^:]+?)\s*:\s*(.*)$")


# --------------------------------------------------------------------------- #
# Which shape is this store?
# --------------------------------------------------------------------------- #


def uses_files(memory_dir: Path) -> bool:
    """True from schema 3 on. Decided by the manifest, never by what is on disk.

    A `traps/` directory existing is not proof of anything — a half-finished
    migration, or a user's own folder of that name — whereas the manifest
    version is written only after a migration step completes.
    """
    manifest = cli.load_manifest(Path(memory_dir)) or {}
    try:
        return int(str(manifest.get("schema_version", "1")).strip()) >= FILES_SCHEMA
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Reading: records -> the legacy dict shapes
# --------------------------------------------------------------------------- #


def _flat(text: str) -> str:
    """A section's content as one bullet line, with provenance comments removed.

    `render_body` stubs a record with no filled section as `_(not recorded)_`
    so it still parses; that stub is not content, and emitting it as a bullet
    would give a migrated empty trap keywords its block never had.
    """
    flat = " ".join(cli._strip_html_comments(text or "").split())
    return "" if flat == cli._EMPTY_SECTION else flat


def render_trap_body(rec: "cli.Record") -> str:
    """The bullet block a trap file stands for — what `_trap_block` would write."""
    sections = rec.sections
    lines = []
    for heading, section in TRAP_BULLETS:
        value = _flat(sections.get(section, ""))
        if value:
            lines.append(f"- {heading}: {value}")
    if rec.meta.get("last_confirmed"):
        lines.append(f"- {cli.TRAP_CONFIRMED_KEY}: {rec.meta['last_confirmed']}")
    if rec.meta.get("promoted_to"):
        lines.append(f"- Promoted to: {rec.meta['promoted_to']}")
    if rec.meta.get("superseded_by"):
        lines.append(f"- Superseded by: {rec.meta['superseded_by']}")
    lines.append(f"- Status: {rec.meta.get('status') or 'active'}")
    notes = cli._strip_html_comments(sections.get("Notes", "")).strip()
    if notes:
        lines.append(notes)
    return "\n".join(lines)


def render_question_body(rec: "cli.Record") -> str:
    sections = rec.sections
    lines = [f"- Opened: {str(rec.meta.get('created_at') or '')[:10]}"]
    for heading, section in QUESTION_BULLETS:
        value = _flat(sections.get(section, ""))
        if value:
            lines.append(f"- {heading}: {value}")
    if rec.meta.get("superseded_by"):
        lines.append(f"- Superseded by: {rec.meta['superseded_by']}")
    lines.append(f"- Status: {rec.meta.get('status') or 'open'}")
    notes = cli._strip_html_comments(sections.get("Notes", "")).strip()
    if notes:
        lines.append(notes)
    return "\n".join(lines)


def load_trap_files(memory_dir: Path) -> list[dict]:
    """Trap files as the dicts `cli.load_traps` has always returned."""
    out = []
    for rec in cli.load_records(Path(memory_dir), types=("trap",)):
        if rec.error:
            continue
        tid = rec.meta.get("id") or cli.UNDATED_ID_PREFIX["trap"] + rec.stem
        summary = str(rec.meta.get("title") or "").strip()
        body = render_trap_body(rec)
        out.append(
            {
                "heading": f"{tid}: {summary}",
                "body": body,
                "id": tid,
                "summary": summary,
                "status": (rec.meta.get("status") or "active").lower(),
                "content": cli._block_content(body),
                "record_path": rec.path,
                "tags": _tags_of(rec),
            }
        )
    return out


def _tags_of(rec) -> list[str]:
    tags = rec.meta.get("tags") or []
    return [str(t) for t in tags] if isinstance(tags, list) else []


def load_question_files(memory_dir: Path) -> list[dict]:
    """Question files as the dicts `cli.load_open_questions` has always returned."""
    out = []
    for rec in cli.load_records(Path(memory_dir), types=("question",)):
        if rec.error:
            continue
        qid = rec.meta.get("id") or cli.UNDATED_ID_PREFIX["question"] + rec.stem
        body = render_question_body(rec)
        out.append(
            {
                "id": qid,
                "question": str(rec.meta.get("title") or "").strip(),
                "opened": str(rec.meta.get("created_at") or "")[:10] or None,
                "status": (rec.meta.get("status") or "open").lower(),
                "content": cli._block_content(body),
                "body": body,
                "record_path": rec.path,
                "tags": _tags_of(rec),
            }
        )
    return out


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #


def _write(
    memory_dir: Path,
    project_root: Path,
    rtype: str,
    stem: str,
    title: str,
    sections: dict[str, str],
    *,
    status: str,
    agent: str | None,
    created_at: str | None = None,
    extra: dict | None = None,
    validate: bool = True,
) -> dict:
    """Write one trap/question file through the same validate gate as any record.

    `validate=False` is for the migration only, which writes every trap in the
    store and then validates once: a full `run_validate` per file is quadratic
    in the store size, and a 77-trap store is exactly the one being migrated.
    """
    memory_dir = Path(memory_dir)
    directory = memory_dir / cli.TYPE_DIR[rtype]
    path_policy.mkdirs(directory)
    path = directory / f"{stem}.md"
    if path.exists():
        return {"ok": False, "error": f"{cli.UNDATED_ID_PREFIX[rtype]}{stem} already exists"}
    ident = cli.derive_identity(stem, rtype)
    if ident is None:
        return {
            "ok": False,
            "error": f"{stem!r} is not a usable id (lowercase letters, digits, - and _)",
        }
    rid, slug = ident
    derived = cli.derive_fields(project_root, agent=agent)
    defaults = cli.default_fields()
    when = created_at or derived["created_at"]
    meta = {
        "id": rid,
        "type": rtype,
        "slug": slug,
        "title": title,
        "status": status,
        "created_at": when,
        "updated_at": derived["created_at"],
        "created_by": derived["created_by"],
        "agent": derived["agent"],
        "project": derived["project"],
        "scope": defaults["scope"],
        "branch": derived["branch"],
        "commit": derived["commit"],
        "dirty_files": derived["dirty_files"],
        "confidence": defaults["confidence"],
        "privacy": defaults["privacy"],
        "review_status": cli._admission_review_status(memory_dir, rtype),
        "reviewed_by": defaults["reviewed_by"],
        "supersedes": defaults["supersedes"],
        "superseded_by": defaults["superseded_by"],
        "expires_at": defaults["expires_at"],
        "tags": [],
        "evidence": [],
    }
    for key, value in (extra or {}).items():
        if value not in (None, ""):
            meta[key] = value
    try:
        text = cli.render_frontmatter(meta) + "\n\n" + cli.render_body(rtype, sections)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    cli.write_text_atomic(path, text)
    if validate:
        fails = cli._validate_new_file(memory_dir, path)
        if fails:
            path.unlink()
            return {
                "ok": False,
                "error": f"{rtype} rejected by validate: " + "; ".join(f["message"] for f in fails),
            }
    return {"ok": True, "id": rid, "path": str(path)}


def trap_stem(slug: str) -> str:
    """A trap file's stem from a slug or a `trap_<slug>` id."""
    s = (slug or "").strip().lower()
    prefix = cli.UNDATED_ID_PREFIX["trap"]
    return s[len(prefix) :] if s.startswith(prefix) else s


def question_stem(qid: str) -> str:
    """A question file's stem from its `q_<slug>` id."""
    qid = _scoring.normalize_question_id(qid).lower()
    prefix = cli.UNDATED_ID_PREFIX["question"]
    return qid[len(prefix) :] if qid.startswith(prefix) else qid


def write_trap(
    memory_dir: Path,
    project_root: Path,
    summary: str,
    *,
    slug: str,
    area=None,
    symptom=None,
    why=None,
    safe=None,
    verify=None,
    notes=None,
    status: str = "active",
    agent: str | None = None,
    created_at: str | None = None,
    last_confirmed: str | None = None,
    promoted_to: str | None = None,
    superseded_by: str | None = None,
    validate: bool = True,
    meta_extra: dict | None = None,
) -> dict:
    """Write one trap file. `meta_extra` sets further frontmatter (scope,
    confidence, promotion provenance); a None value leaves the default."""
    sections = {
        "Area / files": area or "",
        "Symptom": symptom or "",
        "Why": why or "",
        "Safe approach": safe or "",
        "Verification": verify or "",
        "Notes": notes or "",
    }
    return _write(
        memory_dir,
        project_root,
        "trap",
        trap_stem(slug),
        summary,
        sections,
        status=status or "active",
        agent=agent,
        created_at=created_at,
        extra={
            **(meta_extra or {}),
            "last_confirmed": last_confirmed,
            "superseded_by": superseded_by,
            "promoted_to": promoted_to,
        },
        validate=validate,
    )


def write_question(
    memory_dir: Path,
    project_root: Path,
    text: str,
    *,
    why=None,
    needs=None,
    notes=None,
    status: str = "open",
    agent: str | None = None,
    created_at: str | None = None,
    superseded_by: str | None = None,
    validate: bool = True,
    meta_extra: dict | None = None,
) -> dict:
    """Write one question file. `meta_extra` as on `write_trap`."""
    sections = {
        "Question": text,
        "Why it matters": why or "",
        "Needs": needs or "",
        "Notes": notes or "",
    }
    return _write(
        memory_dir,
        project_root,
        "question",
        question_stem(_scoring.question_item_id(text)),
        text,
        sections,
        status=status or "open",
        agent=agent,
        created_at=created_at,
        extra={**(meta_extra or {}), "superseded_by": superseded_by},
        validate=validate,
    )


def set_last_confirmed(memory_dir: Path, rid: str, stamp: str) -> dict:
    """Stamp a trap file's `last_confirmed`, validate-gated and reverted on failure."""
    memory_dir = Path(memory_dir)
    rec = cli.find_record_by_id(memory_dir, rid)
    if rec is None or rec.rtype != "trap" or rec.error:
        return {"ok": False, "error": f"no trap with id {rid!r}"}
    original = path_policy.read_text(rec.path)
    meta, body = cli.parse_frontmatter(original)
    meta["last_confirmed"] = stamp
    meta["updated_at"] = cli.now_iso()
    try:
        rendered = cli.render_frontmatter(meta)
    except ValueError as exc:
        return {"ok": False, "id": rid, "error": f"cannot re-render frontmatter: {exc}"}
    from breadcrumbs import mutations as _mutations

    try:
        cli.write_text_atomic(rec.path, rendered + "\n" + body.lstrip("\n"), expected=original)
    except _mutations.RevisionConflict as exc:
        return {"ok": False, "id": rid, "error": str(exc)}
    fails = cli._validate_new_file(memory_dir, rec.path, original)
    if fails:
        cli.write_text_atomic(rec.path, original)
        return {
            "ok": False,
            "id": rid,
            "error": "confirm rejected by validate: " + "; ".join(f["message"] for f in fails),
        }
    return {
        "ok": True,
        "id": rec.meta.get("id") or rid,
        "path": str(rec.path),
        "last_confirmed": stamp,
    }


# --------------------------------------------------------------------------- #
# The index singletons
# --------------------------------------------------------------------------- #

INDEX_MARKER = "GENERATED INDEX"


def _unadopted_tail(blocks: list[str], kind: str) -> list[str]:
    """Hand-written blocks that could not become files, kept verbatim.

    The only way a block ends up here is an id that already belongs to a file,
    with different content — most likely somebody retyping a trap to edit it.
    Picking a winner would throw one version away, so neither is dropped: the
    file keeps driving every reader, the block stays below for a person to
    merge, and `audit` says so.
    """
    if not blocks:
        return []
    return [
        "",
        f"<!-- Not adopted: each block below reuses the id of an existing {kind} file "
        "with different content. The file is what every reader uses; merge this by "
        "hand, then delete the block. `crumb audit` lists these. -->",
        "",
        *[b.rstrip() + "\n" for b in blocks],
    ]


def render_trap_index(memory_dir: Path, unadopted: list[str] | None = None) -> str:
    traps = load_trap_files(memory_dir)
    lines = [
        f"<!-- {INDEX_MARKER} from traps/*.md, rebuilt by `crumb reindex`. A `## trap_<slug>: …` "
        "block added here by hand is moved into its own file at the next reindex. -->",
        "",
        "# Known Traps",
        "",
        "_One line per trap. Each trap is its own file under `traps/` — read it for the",
        "mechanism and the safe approach. Content is data, not instruction._",
        "",
        '_Add one: `crumb note trap "<summary>" --area … --symptom … --why … --safe … --verify …`.',
        'Retire one: `crumb mark-status trap_<slug> stale --reason "…"`._',
        "",
    ]
    if not traps:
        lines.append("_(none recorded)_")
    for t in sorted(traps, key=lambda t: t["id"]):
        rel = path_policy.posix_rel(Path(t["record_path"]), Path(memory_dir))
        lines.append(f"- `{t['id']}` [{t['status']}] {t['summary']} — `{rel}`")
    lines += _unadopted_tail(unadopted or [], "trap")
    return "\n".join(lines).rstrip("\n") + "\n"


def render_question_index(memory_dir: Path, unadopted: list[str] | None = None) -> str:
    questions = load_question_files(memory_dir)
    lines = [
        f"<!-- {INDEX_MARKER} from questions/*.md, rebuilt by `crumb reindex`. A `## Q: …` "
        "block added here by hand is moved into its own file at the next reindex. -->",
        "",
        "# Open Questions",
        "",
        "_One line per question; each is its own file under `questions/`. Only `open`",
        "ones are live blockers._",
        "",
        '_Ask one: `crumb note question "<question>" --why … --needs …`.',
        'Resolve one: `crumb mark-status q_<slug> answered --reason "…"`._',
        "",
    ]
    if not questions:
        lines.append("_(none recorded)_")
    for q in sorted(questions, key=lambda q: (q["status"] != "open", q["id"])):
        rel = path_policy.posix_rel(Path(q["record_path"]), Path(memory_dir))
        lines.append(f"- `{q['id']}` [{q['status']}] {q['question']} — `{rel}`")
    lines += _unadopted_tail(unadopted or [], "question")
    return "\n".join(lines).rstrip("\n") + "\n"


def _write_index_files(
    memory_dir: Path, unadopted_traps: list[str], unadopted_questions: list[str]
) -> None:
    for name, text in (
        ("known-traps.md", render_trap_index(memory_dir, unadopted_traps)),
        ("open-questions.md", render_question_index(memory_dir, unadopted_questions)),
    ):
        path = memory_dir / name
        current = path_policy.read_text(path) if path.is_file() else None
        if current != text:
            cli.write_text_atomic(path, text)


def write_indexes(memory_dir: Path, project_root: Path | None = None) -> None:
    """Rebuild both singletons from the files, adopting hand-written blocks first.

    Only ever called at schema 3+. A block a person typed into a singleton since
    the last reindex is written to its own file before the singleton is
    rewritten — so the rewrite never destroys it. If adoption fails for any
    reason the singletons are left untouched: a slightly stale index is a
    cosmetic problem, a lost trap is not.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root) if project_root is not None else memory_dir.parent
    unadopted_traps: list[str] = []
    unadopted_questions: list[str] = []
    if cli._load_trap_blocks(memory_dir) or cli._load_question_blocks(memory_dir):
        try:
            result = adopt_blocks(memory_dir, project_root, agent="adopted")
        except Exception as exc:  # noqa: BLE001 - reported, and the singletons kept
            # Silence here left a hand-added block unadopted with no word why
            # (field report 2026-10-01, N10). The block stays where it is.
            import sys

            print(
                f"CRUMB-WARN: a hand-written trap/question block could not be moved "
                f"into its own file, so known-traps.md / open-questions.md were left "
                f"as they are: {exc}",
                file=sys.stderr,
            )
            return
        unadopted_traps = result["unadopted_traps"]
        unadopted_questions = result["unadopted_questions"]
    _write_index_files(memory_dir, unadopted_traps, unadopted_questions)


def unadopted_blocks(memory_dir: Path) -> list[str]:
    """Ids of hand-written blocks still in a singleton at schema 3 (for `audit`)."""
    memory_dir = Path(memory_dir)
    if not uses_files(memory_dir):
        return []
    return [t["id"] for t in cli._load_trap_blocks(memory_dir)] + [
        q["id"] for q in cli._load_question_blocks(memory_dir)
    ]


# --------------------------------------------------------------------------- #
# Migration: blocks -> files
# --------------------------------------------------------------------------- #


def _parse_block(raw_body: str) -> tuple[dict[str, str], dict[str, str], list[str]]:
    """Split a block body into (content bullets, bookkeeping bullets, other lines).

    Nothing is dropped: a line that is neither a known content bullet nor a
    bookkeeping bullet — free prose, an unknown bullet, a provenance comment —
    lands in the third list and becomes the file's `Notes` section.
    """
    content: dict[str, str] = {}
    meta: dict[str, str] = {}
    other: list[str] = []
    known = {h.lower(): h for h, _ in TRAP_BULLETS + QUESTION_BULLETS}
    for line in raw_body.splitlines():
        m = _BULLET_RE.match(line)
        key = m.group(1).strip().lower() if m else None
        if key in _META_BULLETS:
            meta[_META_BULLETS[key]] = cli._strip_inline_comment(m.group(2)).strip()
        elif key in known and known[key] not in content:
            content[known[key]] = m.group(2).strip()
        elif line.strip():
            other.append(line.rstrip())
    return content, meta, other


def _raw_blocks(path: Path, matches) -> dict[str, str]:
    """Raw blocks — heading line included, comments included — keyed by id."""
    if not path.is_file():
        return {}
    text = cli.read_text_lenient(path)[0]
    out: dict[str, str] = {}
    for start, end, heading in cli._md_heading_spans(text):
        rid = matches(heading)
        if rid and rid not in out:
            out[rid] = text[start:end]
    return out


def _body_of(raw_block: str) -> str:
    return raw_block.split("\n", 1)[1] if "\n" in raw_block else ""


def _same(a: str, b: str) -> bool:
    """Equal once comments and whitespace are ignored."""
    return " ".join(cli._strip_html_comments(a).split()) == " ".join(
        cli._strip_html_comments(b).split()
    )


# Status words a hand-kept block used for "this no longer applies". Readers
# already treated any status but `active` / `open` as settled, so mapping them
# keeps what every reader did; the original wording is kept in Notes
# (field report 2026-10-01, issue 4).
_ANSWERED_WORDS = ("resolved", "fixed", "done", "answered", "solved", "complete", "completed")


def _legacy_fixes(
    kind: str, meta: dict[str, str], fallback_status: str, known_ids: set[str]
) -> tuple[dict[str, str | None], list[str], list[str]]:
    """Map block values a file may not hold onto ones it may.

    Returns `(values, note_lines, described)`: the status / superseded_by /
    last_confirmed to write, the lines that keep each original in the file's
    Notes, and one short description per change for the migration's report.
    Nothing is dropped: every value replaced is kept, verbatim, in Notes.
    """
    from breadcrumbs import validation as _validation

    raw_status = (meta.get("status") or fallback_status or "").strip()
    status = raw_status.lower() or ("active" if kind == "trap" else "open")
    superseded_by = (meta.get("superseded_by") or "").strip() or None
    last_confirmed = (meta.get("last_confirmed") or "").strip() or None
    notes: list[str] = []
    described: list[str] = []
    valid = cli.VALID_STATUS if kind == "trap" else cli.VALID_QUESTION_STATUS
    if status not in valid:
        if kind == "trap":
            new = "stale"
        else:
            first = re.split(r"[^a-z]+", status, maxsplit=1)[0]
            new = "answered" if first in _ANSWERED_WORDS else "closed"
        notes.append(f"- Original status: {raw_status}")
        described.append(f"status {raw_status[:60]!r} -> {new}")
        status = new
    if superseded_by and superseded_by.lower() not in known_ids:
        notes.append(f"- Original superseded by: {superseded_by} (names no record in this store)")
        described.append(f"superseded_by {superseded_by!r} names no record; link kept in Notes")
        superseded_by = None
    if status == "superseded" and not superseded_by:
        new = "stale" if kind == "trap" else "closed"
        if "- Original status:" not in "\n".join(notes):
            notes.append(f"- Original status: {raw_status} (no successor named)")
        described.append(f"status superseded with no successor -> {new}")
        status = new
    if last_confirmed and _validation.parse_timestamp(last_confirmed) is None:
        notes.append(f"- Original last confirmed: {last_confirmed}")
        described.append(f"last_confirmed {last_confirmed!r} is not a date; kept in Notes")
        last_confirmed = None
    values = {"status": status, "superseded_by": superseded_by, "last_confirmed": last_confirmed}
    return values, notes, described


def _block_lines(path: Path) -> dict[str, int]:
    """`{heading: 1-based line}` of each `## ` block in `path` (first occurrence)."""
    if not path.is_file():
        return {}
    text = cli.read_text_lenient(path)[0]
    out: dict[str, int] = {}
    for start, _end, heading in cli._md_heading_spans(text):
        out.setdefault(heading.strip(), text.count("\n", 0, start) + 1)
    return out


def _known_ids(memory_dir: Path) -> set[str]:
    """Every id a migrated block may link to: records, trap and question blocks."""
    ids = {
        str(r.meta.get("id") or r.stem).lower()
        for r in cli.load_records(Path(memory_dir))
        if not r.error
    }
    ids |= {t["id"].lower() for t in cli._load_trap_blocks(memory_dir)}
    ids |= {q["id"].lower() for q in cli._load_question_blocks(memory_dir)}
    return ids


def adopt_blocks(memory_dir: Path, project_root: Path, *, agent: str = "migration") -> dict:
    """Write a file for every trap/question block that does not have one yet.

    Shared by the schema-3 migration (every block) and by reindex at schema 3
    (a block somebody typed into a singleton since). Returns `{changed,
    unadopted_traps, unadopted_questions}`; the last two are the raw text of
    blocks whose id already belongs to a file with *different* content — kept
    so the caller can leave them in place rather than drop them. A block
    identical to its file (a migration re-run after a crash) is simply done.

    Raises, having removed every file it wrote, if those files fail validation:
    the store is then exactly as it was before the call.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root)
    changed: list[str] = []
    new_paths: list[Path] = []
    unadopted_traps: list[str] = []
    unadopted_questions: list[str] = []
    existing_traps = {t["id"].lower(): t for t in load_trap_files(memory_dir)}
    existing_questions = {q["id"].lower(): q for q in load_question_files(memory_dir)}

    known_ids = _known_ids(memory_dir)
    mapped: list[str] = []
    trap_lines = _block_lines(memory_dir / "known-traps.md")
    trap_raw = _raw_blocks(
        memory_dir / "known-traps.md",
        lambda h: h.partition(":")[0].strip().lower() if h.lower().startswith("trap") else None,
    )
    trap_raw_by_heading = _raw_blocks(memory_dir / "known-traps.md", lambda h: h.strip())
    adopted_here: set[str] = set()
    for trap in cli._load_trap_blocks(memory_dir):
        tid = trap["id"].lower()
        raw = trap_raw_by_heading.get(trap["heading"].strip()) or trap_raw.get(tid, "")
        where = f"known-traps.md:{trap_lines.get(trap['heading'].strip(), '?')}"
        if tid in adopted_here:
            # A second block with an id this run already wrote (N2): writing it
            # failed "already exists" and was dropped silently. Keep it verbatim
            # below the index, the same as any block that collides with a file.
            unadopted_traps.append(raw or f"## {trap['heading']}\n{trap.get('body') or ''}")
            changed.append(f"trap {tid} ({where}) reuses an id; kept below the index to merge")
            continue
        if tid in existing_traps:
            if not _same(existing_traps[tid]["body"], trap.get("body") or ""):
                unadopted_traps.append(raw or f"## {trap['heading']}\n{trap.get('body') or ''}")
            continue
        stem = trap_stem(tid)
        if not cli.UNDATED_STEM_RE.match(stem):
            stem = cli.slugify(stem) or "trap"
        content, meta, other = _parse_block(_body_of(raw) if raw else trap.get("body") or "")
        values, extra_notes, described = _legacy_fixes("trap", meta, trap["status"], known_ids)
        mapped += [f"trap {tid} ({where}): {d}" for d in described]
        result = write_trap(
            memory_dir,
            project_root,
            trap["summary"] or tid,
            slug=stem,
            area=content.get("Area / files"),
            symptom=content.get("Symptom"),
            why=content.get("Why"),
            safe=content.get("Safe approach"),
            verify=content.get("Verification"),
            notes="\n".join(other + extra_notes),
            status=values["status"],
            agent=agent,
            last_confirmed=values["last_confirmed"],
            promoted_to=meta.get("promoted_to"),
            superseded_by=values["superseded_by"],
            validate=False,
        )
        adopted_here.add(tid)
        if result.get("ok"):
            new_paths.append(Path(result["path"]))
            new_id = result["id"]
            # Lookups ignore case, so `trap_Foo` still finds `trap_foo`; say so
            # anyway, because the printed id is what people will copy next.
            original = trap["id"]
            if new_id == original:
                note = ""
            elif new_id == tid:
                note = f" (id was {original!r}; ids are lowercase now, lookups ignore case)"
            else:
                note = f" (id was {original!r}, not a usable filename)"
            changed.append(f"trap {new_id} -> traps/{stem}.md{note}")
        elif "already exists" not in result.get("error", ""):
            raise RuntimeError(f"trap {tid} ({where}): {result.get('error')}")

    question_raw = _raw_blocks(
        memory_dir / "open-questions.md",
        lambda h: _scoring.question_item_id(h[2:].strip()) if h.lower().startswith("q:") else None,
    )
    question_lines = _block_lines(memory_dir / "open-questions.md")
    question_raw_by_heading = _raw_blocks(memory_dir / "open-questions.md", lambda h: h.strip())
    for q in cli._load_question_blocks(memory_dir):
        heading = f"Q: {q['question']}"
        raw = question_raw_by_heading.get(heading) or question_raw.get(q["id"], "")
        where = f"open-questions.md:{question_lines.get(heading, '?')}"
        if q["id"].lower() in adopted_here:
            unadopted_questions.append(raw or f"## Q: {q['question']}\n{q.get('body') or ''}")
            changed.append(f"question {q['id']} ({where}) reuses an id; kept below the index")
            continue
        if q["id"].lower() in existing_questions:
            if not _same(existing_questions[q["id"].lower()]["body"], q.get("body") or ""):
                unadopted_questions.append(raw or f"## Q: {q['question']}\n{q.get('body') or ''}")
            continue
        content, meta, other = _parse_block(_body_of(raw) if raw else q.get("body") or "")
        opened = meta.get("opened") or q.get("opened")
        created = (
            f"{opened}T00:00:00+00:00"
            if opened and re.match(r"^\d{4}-\d{2}-\d{2}$", opened)
            else None
        )
        values, extra_notes, described = _legacy_fixes("question", meta, q["status"], known_ids)
        mapped += [f"question {q['id']} ({where}): {d}" for d in described]
        result = write_question(
            memory_dir,
            project_root,
            q["question"],
            why=content.get("Why it matters"),
            needs=content.get("Needs"),
            notes="\n".join(other + extra_notes),
            status=values["status"],
            agent=agent,
            created_at=created,
            superseded_by=values["superseded_by"],
            validate=False,
        )
        adopted_here.add(q["id"].lower())
        if result.get("ok"):
            new_paths.append(Path(result["path"]))
            changed.append(f"question {result['id']} -> questions/{question_stem(result['id'])}.md")
        elif "already exists" not in result.get("error", ""):
            raise RuntimeError(f"question {q['id']} ({where}): {result.get('error')}")

    if new_paths:
        # One validate pass over everything just written. A failure removes
        # those files and raises: the singletons have not been rewritten, so the
        # store still reads exactly as it did.
        written = {path_policy.posix_rel(p, memory_dir) for p in new_paths}
        fails = [
            f
            for f in _validate.run_validate(memory_dir)
            if f["status"] == "fail" and f["path"] in written
        ]
        if fails:
            for p in new_paths:
                if p.exists():
                    p.unlink()
            raise RuntimeError(
                f"{len(fails)} trap/question file(s) failed validation: "
                + "; ".join(f"{f['path']}: {f['message']}" for f in fails)
            )
    return {
        "changed": changed + mapped,
        "mapped": mapped,
        "unadopted_traps": unadopted_traps,
        "unadopted_questions": unadopted_questions,
    }


def migrate_blocks_to_files(memory_dir: Path, project_root: Path) -> list[str]:
    """Migration step 3 — see `migrate._m3_traps_and_questions_as_files`."""
    memory_dir = Path(memory_dir)
    result = adopt_blocks(memory_dir, project_root, agent="migration")
    changed = list(result["changed"])
    for dirname in (TRAP_DIR, QUESTION_DIR):
        d = memory_dir / dirname
        if not d.is_dir():
            path_policy.mkdirs(d)
            changed.append(f"created {dirname}/")
        keep = d / ".gitkeep"
        if not keep.exists():
            cli.write_text_atomic(keep, "")
    _write_index_files(memory_dir, result["unadopted_traps"], result["unadopted_questions"])
    changed.append("rewrote known-traps.md and open-questions.md as generated indexes")
    return changed
