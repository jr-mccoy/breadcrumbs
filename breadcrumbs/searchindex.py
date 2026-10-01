"""breadcrumbs — a disposable inverted index that narrows `search` (WM-23).

`search` parses every record in the store and scores every one of them against
the query. That is fine to a few hundred records and gets slow past that, and
the slow part is the parse: YAML frontmatter, section splitting, tokenizing and
stemming a file that will score zero. This index answers one question before any
of that happens — *which records could possibly match?* — so only those get
parsed.

**It narrows; it never ranks.** Scoring is untouched and still runs on the
parsed records. The guarantee, pinned by `tests/test_searchindex.py`, is that the
set of matches (and every score in it) is identical with and without the index.
It holds by construction:

- A record can only clear `_score_item`'s gate by sharing a specific stem, a tag
  stem or a file token with the query. The index stores exactly those tokens,
  exactly as `_item_from_record` computes them, and returns every record that
  shares at least one. Nothing that could score is left out.
- The one corpus-wide input to scoring is the *ubiquity* filter: a stem in more
  than a third of the corpus scores zero. Narrowing the corpus would change
  those frequencies, so the index also stores them. Scoring only ever consults
  ubiquity for stems the query contains, so only those are computed.

**Why not SQLite FTS5**, which the plan named. FTS5's tokenizer re-splits on
`_`, `/`, `.` and `-`, so `src/auth/session.py` and `parse_config` would not be
the tokens scoring compares — equivalence would need a custom tokenizer, and FTS
buys nothing this needs (no prefix, phrase or rank queries). A posting table with
a B-tree index stores tokens verbatim and works on any SQLite, including builds
without FTS5 compiled in.

**Disposable and never trusted stale.** It lives at `index/search.sqlite`, which
is gitignored and exists only on this machine. It is stamped with the
`_inputs_hash` it was built from and used only when that still matches, so an
edit made without a reindex falls back to the full scan rather than silently
missing a record. Only directories the hash covers are indexed; anything else in
the corpus (machine-local jots, a record directory the committed `.gitignore`
excludes) is always parsed directly, because a change there would not show up
as staleness.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from breadcrumbs import cli, path_policy

try:  # sqlite3 is stdlib, but some minimal builds ship without it
    import sqlite3
except ImportError:  # pragma: no cover - depends on the interpreter build
    sqlite3 = None  # type: ignore[assignment]

INDEX_FILENAME = "search.sqlite"

# Below this many indexed records the full scan is already fast, and a store
# that small would otherwise grow an index/ file for no benefit. The index is
# neither built nor consulted until a store is past it.
INDEX_MIN_CORPUS = 200

# Bumped when the table layout or what goes into it changes, so an index built
# by an older version is rebuilt rather than misread.
# 2: stamped with the verified snapshot digest, fresh only by content hash
# (audit F07, F12).
INDEX_FORMAT = "2"

# The directories whose records the index may cover, by record type. Sessions
# are never in the search corpus. Traps and questions are few (tens, not
# hundreds) and may still be blocks in a schema-2 store, so `candidate_items`
# always loads them directly instead of indexing them.
_CORPUS_DIRS = {
    "decisions": "decision",
    "attempts": "attempt",
    "verifications": "verification",
    "ideas": "idea",
    "inbox": "jot",
}


def available() -> bool:
    return sqlite3 is not None


def index_path(memory_dir: Path) -> Path:
    return Path(memory_dir) / "index" / INDEX_FILENAME


def _indexable_dirs(memory_dir: Path, project_root: Path) -> list[str]:
    """Corpus directories the freshness hash covers — the only ones safe to index."""
    manifest = cli.load_manifest(memory_dir) or {}
    hashed = set(cli._hashed_input_dirs(memory_dir, project_root, manifest))
    return sorted(d for d in _CORPUS_DIRS if d in hashed)


def _stat_fingerprint(memory_dir: Path, project_root: Path) -> str:
    """A cheap "has anything changed" signature: paths, sizes and mtimes.

    `_inputs_hash` reads and hashes every record's bytes and asks git which
    directories are ignored. That is the right cost for `validate`, and it was
    40% of an indexed search. This stats the same files instead — plus every
    record directory and the repo `.gitignore`, a deliberate superset, so any
    change the real hash would see also changes this.

    Since audit WP07 it is *not* part of the index's freshness, which is the
    content hash alone. It serves the generation manifest's cheap "has anything
    moved since publication" test (`projections.verified`), where a false
    "moved" costs only the slow path.

    Each file is named relative to the store, never by its absolute path: one
    directory has several spellings (macOS `/var` and `/private/var`, a Windows
    8.3 short name), and a publisher and a reader that spelled it differently
    never matched, so the hook always took the slow path there (audit WP17).
    """
    import hashlib

    memory_dir = Path(memory_dir)
    named = [(f, memory_dir / f) for f in cli.CORE_FILES]
    named += [(n, memory_dir / n) for n in ("manifest.yml", cli.ALIASES_FILENAME)]
    named.append(("<root>/.gitignore", Path(project_root) / ".gitignore"))
    for dirname in cli.DIR_TYPES:
        named.extend(
            (f"{dirname}/{p.name}", p) for p in sorted((memory_dir / dirname).glob("*.md"))
        )
    h = hashlib.sha256()
    for name, p in named:
        try:
            st = p.stat()
            h.update(f"{name}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
        except OSError:
            h.update(f"{name}\0-\n".encode())
    return h.hexdigest()[:16]


def _is_fresh(meta: dict, memory_dir: Path, project_root: Path) -> bool:
    """Strict freshness: the index was built from exactly the current inputs.

    A path/size/mtime match used to return "fresh" before any content was
    compared, so a same-size edit with a restored mtime left indexed search
    missing a word the full scan found (audit F12). Indexed search promises the
    full scan's results, so only the content hash decides. It costs ~17 ms at
    1000 records.
    """
    if meta.get("format") != INDEX_FORMAT:
        return False
    # The guard and prompt hooks run on every tool call and prompt, where the
    # content hash (every record read, plus a `git check-ignore` spawn) was a
    # large share of the firing (field report 2026-10-01, issue 6). There, an
    # unchanged path/size/mtime signature taken before the build is accepted.
    # A same-size edit that also restores the mtime (F12) can make one hook
    # firing use the previous index; the next write republishes it. Every
    # other caller keeps the strict content hash.
    from breadcrumbs import admission

    if admission.current_channel() == "hook" and meta.get("stat_fingerprint"):
        if meta["stat_fingerprint"] == _stat_fingerprint(memory_dir, project_root):
            return True
    return meta.get("inputs_hash") == cli._inputs_hash(memory_dir, project_root)


def _tokens_of(item: dict) -> list[tuple[str, str]]:
    """The (field, token) postings for one item: exactly what scoring compares."""
    out = [("s", s) for s in item.get("specific") or ()]
    out += [("t", s) for s in (item.get("tag_stems") or {})]
    out += [("f", f) for f in set(item.get("files") or ()) | set(item.get("mentioned_files") or ())]
    return out


def build_index(
    memory_dir: Path,
    project_root: Path,
    *,
    force: bool = False,
    inputs_hash: str | None = None,
    publish: bool = True,
) -> dict:
    """(Re)build the index. Returns `{built, records, reason}`. Never raises.

    The index is stamped with the snapshot it was built from (audit F07).
    `inputs_hash` is that digest when a publication verifies the snapshot
    itself. Otherwise this build verifies its own: it hashes before reading and
    again after, and publishes nothing if they differ. `publish=False` leaves
    the built file in place for the caller (`"staged"`): `publish_index()` puts
    it live, and `discard_index()` removes it.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root)
    if not available():
        return {"built": False, "records": 0, "reason": "sqlite3 unavailable"}
    own_snapshot = inputs_hash is None
    # Taken before anything is read: a file that moves during the build then
    # mismatches, and the hook takes the slow path, never a stale fast one.
    fingerprint = _stat_fingerprint(memory_dir, project_root)
    if own_snapshot:
        inputs_hash = cli._inputs_hash(memory_dir, project_root)
    try:
        cli.activate_store_aliases(memory_dir)
        dirs = _indexable_dirs(memory_dir, project_root)
        rows = []
        for dirname in dirs:
            rtype = _CORPUS_DIRS[dirname]
            for path in sorted((memory_dir / dirname).glob("*.md")):
                rec = cli.Record.from_file(path, rtype)
                if rec.error:
                    continue
                rows.append((path, rtype, cli._item_from_record(rec)))
        if len(rows) < INDEX_MIN_CORPUS and not force:
            # Small store: remove any index left from when it was bigger, so a
            # stale file can never be mistaken for a live one.
            path = index_path(memory_dir)
            if path.exists():
                path.unlink()
            return {"built": False, "records": len(rows), "reason": "below threshold"}

        path = index_path(memory_dir)
        path_policy.mkdirs(path.parent)
        # SQLite opens by name and follows links; the directory is checked
        # above, and a link at the published name is refused (audit F17).
        path_policy.check(path)
        # A temp file of its own (audit F06): with one fixed `.tmp` name, two
        # builders would write into the same file and publish each other's work.
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".index.", suffix=".tmp")
        os.close(fd)
        tmp = Path(tmp_name)
        conn = sqlite3.connect(str(tmp))
        try:
            conn.executescript(
                """
                CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE records(
                    rid INTEGER PRIMARY KEY, path TEXT, rtype TEXT, speculative INTEGER
                );
                CREATE TABLE postings(field TEXT, token TEXT, rid INTEGER);
                """
            )
            speculative = set(cli.SPECULATIVE_ITEM_TYPES)
            for rid, (rpath, rtype, item) in enumerate(rows):
                conn.execute(
                    "INSERT INTO records VALUES (?, ?, ?, ?)",
                    (
                        rid,
                        rpath.relative_to(memory_dir).as_posix(),
                        rtype,
                        int(rtype in speculative),
                    ),
                )
                conn.executemany(
                    "INSERT INTO postings VALUES (?, ?, ?)",
                    [(field, token, rid) for field, token in _tokens_of(item)],
                )
            conn.execute("CREATE INDEX postings_lookup ON postings(field, token)")
            conn.executemany(
                "INSERT INTO meta VALUES (?, ?)",
                [
                    ("inputs_hash", inputs_hash),
                    ("format", INDEX_FORMAT),
                    ("dirs", ",".join(dirs)),
                    ("stat_fingerprint", fingerprint),
                ],
            )
            conn.commit()
        except BaseException:
            conn.close()
            tmp.unlink(missing_ok=True)
            raise
        conn.close()
        if own_snapshot and cli._inputs_hash(memory_dir, project_root) != inputs_hash:
            tmp.unlink(missing_ok=True)
            return {
                "built": False,
                "records": len(rows),
                "reason": "the store changed during the build",
            }
        if not publish:
            return {"built": True, "records": len(rows), "reason": None, "staged": str(tmp)}
        tmp.replace(path)
        return {"built": True, "records": len(rows), "reason": None}
    except Exception as exc:  # pragma: no cover - the index is a convenience
        return {"built": False, "records": 0, "reason": f"{type(exc).__name__}: {exc}"}


def publish_index(memory_dir: Path, staged: str | None) -> None:
    """Put a staged index (from `build_index(publish=False)`) live."""
    if staged:
        Path(staged).replace(index_path(memory_dir))


def discard_index(staged: str | None) -> None:
    if staged:
        Path(staged).unlink(missing_ok=True)


def index_status(memory_dir: Path, project_root: Path) -> dict:
    """`{state, records}` — absent | fresh | stale | unavailable | unreadable."""
    if not available():
        return {"state": "unavailable", "records": 0}
    path = index_path(memory_dir)
    if not path.is_file():
        return {"state": "absent", "records": 0}
    try:
        path_policy.check(path)  # a linked index is unreadable, never followed
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
            records = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return {"state": "unreadable", "records": 0}
    fresh = _is_fresh(meta, Path(memory_dir), Path(project_root))
    return {"state": "fresh" if fresh else "stale", "records": records}


def candidate_items(
    memory_dir: Path,
    project_root: Path,
    q_specific: set[str],
    q_files: set[str],
    *,
    include_ideas: bool,
    explain: dict | None = None,
) -> tuple[list[dict], frozenset[str]] | None:
    """The search corpus narrowed to possible matches, plus the ubiquitous stems.

    Returns None whenever the index cannot be trusted or cannot help — absent,
    stale, too small, unreadable, or a query with nothing to look up — and the
    caller falls back to the full scan. Every failure mode lands there, and
    `explain["reason"]` says which (audit WP10), so the caller can report it.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root)
    explain = explain if explain is not None else {}
    if not available():
        explain["reason"] = "sqlite3 is unavailable"
        return None
    if not (q_specific or q_files):
        explain["reason"] = "the query has nothing the index holds"
        return None
    path = index_path(memory_dir)
    if not path.is_file():
        explain["reason"] = "no search index"
        return None
    try:
        path_policy.check(path)  # a linked index is unreadable, never followed
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except Exception:
        explain["reason"] = "the search index is unreadable"
        return None
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        if not _is_fresh(meta, memory_dir, project_root):
            explain["reason"] = "the search index is stale"
            return None
        indexed_dirs = [d for d in (meta.get("dirs") or "").split(",") if d]
        spec = 1 if include_ideas else 0
        n_indexed = conn.execute(
            "SELECT COUNT(*) FROM records WHERE speculative = 0 OR ?", (spec,)
        ).fetchone()[0]
        if n_indexed < INDEX_MIN_CORPUS:
            explain["reason"] = f"the store is under {INDEX_MIN_CORPUS} indexed records"
            return None

        stems = sorted(q_specific)
        files = sorted(q_files)
        clauses, params = [], []
        if stems:
            marks = ",".join("?" * len(stems))
            clauses.append(f"(p.field IN ('s', 't') AND p.token IN ({marks}))")
            params += stems
        if files:
            marks = ",".join("?" * len(files))
            clauses.append(f"(p.field = 'f' AND p.token IN ({marks}))")
            params += files
        hit_paths = [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT r.path FROM postings p JOIN records r ON r.rid = p.rid "
                f"WHERE ({' OR '.join(clauses)}) AND (r.speculative = 0 OR ?) ORDER BY r.path",
                (*params, spec),
            )
        ]
        df_indexed: dict[str, int] = {}
        if stems:
            marks = ",".join("?" * len(stems))
            for token, count in conn.execute(
                "SELECT p.token, COUNT(DISTINCT p.rid) FROM postings p JOIN records r "
                f"ON r.rid = p.rid WHERE p.field = 's' AND p.token IN ({marks}) "
                "AND (r.speculative = 0 OR ?) GROUP BY p.token",
                (*stems, spec),
            ):
                df_indexed[token] = count
    except Exception:
        explain["reason"] = "the search index is unreadable"
        return None
    finally:
        conn.close()

    # Parse only the records the index says could match.
    cli.activate_store_aliases(memory_dir)
    items: list[dict] = []
    rtype_by_dir = _CORPUS_DIRS
    # One directory walk per directory, not per hit, under the path policy.
    blobs = path_policy.read_files(memory_dir / rel for rel in hit_paths)
    for rel in hit_paths:
        p = memory_dir / rel
        rtype = rtype_by_dir.get(Path(rel).parts[0], "decision")
        rec = cli.Record.from_bytes(p, rtype, blobs[p])
        if not rec.error:
            items.append(cli._item_from_record(rec))

    # Everything the index does not cover is parsed directly, and counted toward
    # the corpus exactly as the full scan would count it.
    direct: list[dict] = []
    wanted = set(cli.JUDGING_ITEM_TYPES) | (
        set(cli.SPECULATIVE_ITEM_TYPES) if include_ideas else set()
    )
    for dirname, rtype in _CORPUS_DIRS.items():
        if dirname in indexed_dirs or rtype not in wanted:
            continue
        for rec in cli.records_in(memory_dir / dirname, rtype):
            if not rec.error:
                direct.append(cli._item_from_record(rec))
    for local_dir, rtype in cli.LOCAL_DIR_TYPES.items():
        if rtype not in wanted:
            continue
        for rec in cli.records_in(memory_dir / local_dir, rtype):
            if not rec.error:
                direct.append(cli._item_from_record(rec))
    direct += [cli._item_from_trap(t) for t in cli.load_traps(memory_dir)]
    direct += [cli._item_from_question(q) for q in cli.load_open_questions(memory_dir)]

    # Ubiquity, for the only stems scoring will ask about: the query's own.
    n = n_indexed + len(direct)
    ubiquitous: set[str] = set()
    if n >= cli.GUARD_DF_MIN_CORPUS:
        cutoff = n * cli.GUARD_DF_UBIQUITY
        for stem in stems:
            df = df_indexed.get(stem, 0) + sum(1 for it in direct if stem in it["specific"])
            if df > cutoff:
                ubiquitous.add(stem)

    return cli._disambiguate_item_ids(items + direct), frozenset(ubiquitous)
