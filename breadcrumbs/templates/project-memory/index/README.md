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

`guard-prefilter.json` lives here too: the token and path index the
`PreToolUse` guard hook reads before deciding whether a tool call needs a full
guard run. It is rebuilt on every write (and by `crumb reindex`), trusted only
while this machine's `generation.json` vouches for it, and never committed:
crumb-kit 0.5.0 and earlier kept it in `generated/`, where every rebuild was a
large diff that conflicted on merges. `commit-order.txt` caches HEAD's history,
and `head-tree.txt` the store's files at HEAD, so the hook need not ask git
either question on every call.
