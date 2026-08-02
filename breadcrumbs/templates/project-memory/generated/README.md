# `generated/` — rebuildable projections (NOT source of truth)

Everything in this directory is a **projection** rebuilt from the canonical records
elsewhere in `.project-memory/`. Never edit these by hand and never treat them as
authoritative — if a projection disagrees with the canonical records, the records
win and the projection should be regenerated.

| File | Built by | What it is |
|---|---|---|
| `resume-packet.md` | `crumb resume` / `crumb reindex` | Bounded boot summary (≤ 5k tokens) for pasting into any agent. |
| `guard-prefilter.json` | `crumb resume` / `crumb reindex` | Token + path index over known traps and do-not-retry attempts, so the `PreToolUse` hook can spot a trap-shaped command with one small read instead of walking every record. |

Every projection here is rebuilt on every canonical write (and by `crumb reindex`),
so none of them is ever hand-maintained.

Each Markdown projection carries a source timestamp/commit/hash header so staleness
is visible. By default these files are committed (so a read-only cloud agent gets a
pre-built catch-up file); set `commit_generated_projections: false` at `init` to keep
them local instead — that setting covers `*.json` here as well as `*.md`.
`*.local.md` and `*.tmp` here are always gitignored.

SQLite and vector indexes never live here — they live in `index/`, which is always
gitignored.
