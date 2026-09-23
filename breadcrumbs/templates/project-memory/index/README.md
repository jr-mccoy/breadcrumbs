# `index/` — disposable search index (NEVER committed)

A **disposable cache**, always gitignored except this README.

`crumb reindex` builds `search.sqlite` here once the store has 200 or more
searchable records (`crumb reindex --search-index` forces one on a smaller
store). It is an inverted index of the same stems, tags and files `crumb search`
scores on, and it only narrows which records get scored: search returns exactly
the same results with or without it.

- It is never source of truth. A hit is always scored on the canonical record.
- It records a fingerprint of the files it was built from. A stale, missing or
  unreadable index is never used; search falls back to a full scan and
  `crumb doctor` says so.
- Deleting this directory is always safe.
