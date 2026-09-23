# `private/` — local-only memory (NEVER committed)

Everything under `private/` is gitignored by `crumb init` and must never be
committed. Use it for `privacy: local-private` notes — personal or sensitive local
context that should not travel in the shared repo.

Rules:

- **`local-private`** records may live here (or in an external private store).
- **`secret-prohibited`** content (secrets, credentials, customer PII) must **not**
  be stored in project memory at all — not even here. `validate` fails on
  `secret-prohibited` records and `audit` scans for token-like strings.

The tool also keeps machine-local telemetry here. Both files are safe to delete;
the counts start again.

- `usage.json` — which records were shown (packet, guard, hooks), and since when
  (`crumb usage`, `crumb usage --decay`).
- `hook-log.jsonl` — one line per hook firing: event, duration, outcome and
  counts, never content (`crumb doctor --hook-log`; see `docs/field-test.md`).

Because this directory is gitignored, a fresh clone will not contain it; that is
intentional. Each machine keeps its own private notes.
