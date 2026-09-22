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

from pathlib import Path

from breadcrumbs import cli

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
INDEX_FORMAT = "1"

# The directories whose records the index may cover, by record type. Sessions
# are never in the search corpus; traps and questions live in aggregate files
# that are cheap to parse whole.
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

    It is only ever a *shortcut to yes*: a match means nothing moved since the
    index was built. A mismatch (an edit, or just a `git checkout` resetting
    mtimes) falls back to the real hash, which decides.
    """
    import hashlib

    memory_dir = Path(memory_dir)
    paths = [memory_dir / f for f in cli.CORE_FILES]
    paths += [memory_dir / "manifest.yml", memory_dir / cli.ALIASES_FILENAME]
    paths.append(Path(project_root) / ".gitignore")
    for dirname in cli.DIR_TYPES:
        paths.extend(sorted((memory_dir / dirname).glob("*.md")))
    h = hashlib.sha256()
    for p in paths:
        try:
            st = p.stat()
            h.update(f"{p}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
        except OSError:
            h.update(f"{p}\0-\n".encode())
    return h.hexdigest()[:16]


def _is_fresh(meta: dict, memory_dir: Path, project_root: Path) -> bool:
    if meta.get("format") != INDEX_FORMAT:
        return False
    if meta.get("stat_fingerprint") == _stat_fingerprint(memory_dir, project_root):
        return True
    return meta.get("inputs_hash") == cli._inputs_hash(memory_dir, project_root)


def _tokens_of(item: dict) -> list[tuple[str, str]]:
    """The (field, token) postings for one item: exactly what scoring compares."""
    out = [("s", s) for s in item.get("specific") or ()]
    out += [("t", s) for s in (item.get("tag_stems") or {})]
    out += [("f", f) for f in set(item.get("files") or ()) | set(item.get("mentioned_files") or ())]
    return out


def build_index(memory_dir: Path, project_root: Path, *, force: bool = False) -> dict:
    """(Re)build the index. Returns `{built, records, reason}`. Never raises."""
    memory_dir = Path(memory_dir)
    project_root = Path(project_root)
    if not available():
        return {"built": False, "records": 0, "reason": "sqlite3 unavailable"}
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
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        if tmp.exists():
            tmp.unlink()
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
                    ("inputs_hash", cli._inputs_hash(memory_dir, project_root)),
                    ("stat_fingerprint", _stat_fingerprint(memory_dir, project_root)),
                    ("format", INDEX_FORMAT),
                    ("dirs", ",".join(dirs)),
                ],
            )
            conn.commit()
        finally:
            conn.close()
        tmp.replace(path)
        return {"built": True, "records": len(rows), "reason": None}
    except Exception as exc:  # pragma: no cover - the index is a convenience
        return {"built": False, "records": 0, "reason": f"{type(exc).__name__}: {exc}"}


def index_status(memory_dir: Path, project_root: Path) -> dict:
    """`{state, records}` — absent | fresh | stale | unavailable | unreadable."""
    if not available():
        return {"state": "unavailable", "records": 0}
    path = index_path(memory_dir)
    if not path.is_file():
        return {"state": "absent", "records": 0}
    try:
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
) -> tuple[list[dict], frozenset[str]] | None:
    """The search corpus narrowed to possible matches, plus the ubiquitous stems.

    Returns None whenever the index cannot be trusted or cannot help — absent,
    stale, too small, unreadable, or a query with nothing to look up — and the
    caller falls back to the full scan. Every failure mode lands there.
    """
    memory_dir = Path(memory_dir)
    project_root = Path(project_root)
    if not available() or not (q_specific or q_files):
        return None
    path = index_path(memory_dir)
    if not path.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except Exception:
        return None
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        if not _is_fresh(meta, memory_dir, project_root):
            return None
        indexed_dirs = [d for d in (meta.get("dirs") or "").split(",") if d]
        spec = 1 if include_ideas else 0
        n_indexed = conn.execute(
            "SELECT COUNT(*) FROM records WHERE speculative = 0 OR ?", (spec,)
        ).fetchone()[0]
        if n_indexed < INDEX_MIN_CORPUS:
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
        return None
    finally:
        conn.close()

    # Parse only the records the index says could match.
    cli.activate_store_aliases(memory_dir)
    items: list[dict] = []
    rtype_by_dir = _CORPUS_DIRS
    for rel in hit_paths:
        p = memory_dir / rel
        rec = cli.Record.from_file(p, rtype_by_dir.get(Path(rel).parts[0], "decision"))
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
        for p in sorted((memory_dir / dirname).glob("*.md")):
            rec = cli.Record.from_file(p, rtype)
            if not rec.error:
                direct.append(cli._item_from_record(rec))
    for local_dir, rtype in cli.LOCAL_DIR_TYPES.items():
        if rtype not in wanted:
            continue
        for p in sorted((memory_dir / local_dir).glob("*.md")):
            rec = cli.Record.from_file(p, rtype)
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
