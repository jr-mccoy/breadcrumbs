# `index/` — disposable search index (NEVER committed)

This is the reserved slot for a **disposable cache** — a SQLite FTS database or an
optional vector index — always gitignored except this README.

**Nothing writes here today.** `crumb search` is a deterministic scan over the
canonical records with no index behind it, and no build command ships. The
directory exists so that an index, if one is ever added, has a place that is
already excluded from git rather than one invented later.

Rules that apply if you (or a future version) put an index here:

- The index is never source of truth — a search hit must be confirmed by opening the
  canonical record it points to.
- Each index entry stores the source file path + hash and is invalidated on
  mismatch, so a stale index is detected rather than silently trusted.
- Deleting this directory is always safe.
