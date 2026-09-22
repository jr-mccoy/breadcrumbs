# CLI Specification

The CLI binary is `crumb` (installed via `pipx`/`pip`; from a source checkout the
equivalent is `python crumb.py <command>`, a shim over `breadcrumbs.cli`). Every
command supports the global flags below; capture/resume additionally support
`--fast`. New subcommands are added without changing established flag semantics.

---

## Global flags

Every command accepts:

```text
--json            machine-readable JSON output
--plain           plain-text output (no decoration)
--verbose         verbose output
--project <path>  project root (default: cwd)
--fast            capture/resume only: git-only, no prompts or LLM narrative
```

`crumb --version` (top level, not a subcommand) prints the package version and the
record `schema_version` — two independent numbers, see `README.md`.

`--stale-days N` is accepted by `resume`, `search`, `guard` and `audit`. It is one
cutoff with one meaning everywhere — *a record older than N days counts as aged*
(default: 21). What each command does with that differs: `resume`/`audit` raise a
warning on aged questions and decisions, `search`/`guard` score aged records lower.

Default output is human-readable Markdown / plain text.

**Exit codes shared across commands:** `0` success, `1` the command failed
(`CRUMB-ERROR: …` on stderr), `2` usage error or no `.project-memory/` store, `3`
a writer (`remember`, `note`, `verify`, `jot`) refused a **near-duplicate** of a
live record — see [Near-duplicate gate](#near-duplicate-gate-built-wm-32).
`guard` maps its verdicts to `0`/`10`/`15`/`20` instead (see `guard`).

---

## Command table

| Command | Reads | Writes | Purpose | Phase |
|---|---|---|---|---|
| `init` | project root | `.project-memory/`, `manifest.yml`, `.gitignore` edits | Install memory layout; record session + generated-projection policy in `manifest.yml`. | **1 (built)** |
| `validate` | all canonical files | validation output | Enforce schema and invariants (deterministic). Includes a projection-freshness check: fails on a `generated/` projection (`*.md`, or a `*.json` carrying a top-level `inputs_hash` such as `related.json` and `conflicts.json`) whose stamped `inputs_hash` no longer matches the live records. | **2 (built)** |
| `remember decision` | git state, user input | decision record | Capture a durable choice. Refuses a near-duplicate of a live decision (exit 3) unless `--supersedes ID` or `--allow-duplicate`. | **3 (built)** |
| `remember attempt` | git state, user input | attempt record | Capture a tried path and its outcome. Same near-duplicate gate as `remember decision`. | **3 (built)** |
| `verify <subject>` | git state, user input | verification record | Record a verification result (a finding about reality): `--status fixed\|open\|regressed\|not_applicable\|inconclusive`, `--method static\|runtime\|test`. A settled outcome (`fixed`, `not_applicable`) gets an `expires_at` (`ttl_verification_days`, default 90). Near-duplicate gate as on `remember` (`--supersedes ID`, `--allow-duplicate`). `--recheck ID` (repeatable) or `--all`, with `--yes`, reruns recorded command evidence instead — see `verify --recheck` below; `--status` is required only when not rechecking (exit 2 without it). Reindexes on write. | **built** |
| `reindex` | all canonical files | `generated/` projections, the trap/question indexes (schema 3), `index/search.sqlite` | Rebuild the generated projections from the records (mutations reindex automatically). `--search-index` builds the search index even below its size threshold — see `reindex` below. | **built** |
| `capture session` | git state (log, status, diff --shortstat) | session record, handoff, current | Record session end; git-prefill body sections (Files Touched is a counts-only summary) over a bounded window (`since..HEAD`, capped at 20 commits) that the record names. `--fast` = git-only snapshot + one-line next action; `--next` + `--set` runs unattended without dropping narrative. | **3 (built)** |
| `schema [<type>]` | (none) | record contract | Print body sections / vocab / rules from source constants. `--template <type>` emits a `remember` skeleton (a `verify` one for `verification`, a `crumb note …` one for `trap` and `question`). | **built** |
| `note question\|trap\|idea` | user input, git state | a question / trap / idea record | Write-surface for the three kinds with no `remember` type; refreshes the resume packet. At schema 3 a trap is written to `traps/<slug>.md` and a question to `questions/<slug>.md`, through the same validate gate as any record; on a schema-2 store they are still blocks appended to `known-traps.md` / `open-questions.md`. Near-duplicate gate as on `remember` (`--supersedes ID`, `--allow-duplicate`); an exact repeat (same question text, same trap slug) keeps its own exit-1 "reopen it" error. | **built** |
| `show <id>` | one record, trap, question or jot | the full text (read-only) | Print the body behind a one-line mention. Takes any id the tool prints — `dec_`/`att_`/`ver_`/`idea_`/`ses_`/`jot_`, `trap_…`, `q_…` (legacy `q:…` accepted) — and adds a `See also:` line from `generated/related.json`. Exit 1 with `CRUMB-ERROR` on an unknown id. See `show` below. | **built (WM-21)** |
| `jot "<text>"` | user input, git state | a jot under `inbox/` or `private/inbox/` | The short-term tier: one observation, a TTL (`ttl_jot_days`, or the older `jot_ttl_days`; default 14), and **no evidence rule**. `--file PATH` becomes file evidence so the note can be found again; `--local` writes to `private/inbox/`, which is never committed and is where every automatic writer must put things. A jot is searchable and never reaches a `guard` verdict. A near-verbatim repeat of a live jot (similarity ≥ 0.9) is refused with exit 3 unless `--allow-duplicate` (no `--supersedes` on a jot). | **built (WM-03)** |
| `inbox [--all] [--expired]` | `inbox/`, `private/inbox/` | listing (read-only) | Triage queue: live jots newest first, with id, age and source. | **built (WM-03)** |
| `inbox promote <id> <type>` | one jot | a decision / attempt / verification / trap / question / idea, + the jot | Turn a jot into a durable record **through that type's normal writer**, so the evidence rule and the validate gate apply exactly as they would to a record written by hand. The jot's file evidence and tags carry over; the jot is marked `superseded` with `superseded_by`, never deleted. | **built (WM-03)** |
| `inbox drop <id>` | one jot | status change | Retire a jot as noise (`rejected`). Kept as history; `prune jots` deletes. | **built (WM-03)** |
| `migrate [--dry-run]` | `manifest.yml`, the store | store format + `manifest.yml` | Bring the store's on-disk format up to this build's `schema_version`. Steps are ordered and idempotent, the manifest is written after each one (so a failure halts at the last completed version), and the whole store is copied to `private/migrations/<timestamp>/` first. `validate` fails with `run \`crumb migrate\`` on an older store and `upgrade crumb-kit` on a newer one. See `migrate` below for the steps. | **built (WM-01)** |
| `usage [--never] [--top N]` | `private/usage.json` | report (read-only) | Which records actually get **shown** — a packet printed or injected, a guard verdict, a hook advisory. Counts are local to the machine and never committed. `--never` lists active records nothing has ever reached. | **built (WM-02)** |
| `resume` | current, handoff, records, git state | generated resume packet | Print a bounded resume packet (≤5k tokens) with computed staleness. `--fast` = git snapshot + focus + next action + staleness (print-only). `--task TEXT` scopes `likely_files` to matching records and orders every list section by relevance to the task (print-only). | **4 (built)** |
| `search [<query>]` | decisions, attempts, verifications, ideas, jots, traps, open questions | search output (read-only — `search` writes nothing) | Deterministic keyword/tag/file lookup over the records; the permissive layer `guard` builds on. Keyword and tag matching folds morphological variants — query and record tokens are stemmed by a small deterministic suffix-stripper (plus a tiny curated alias table: auth/config/db/repo, and the store's own `aliases.txt`), so "reconciliation" meets a record that says "reconciler"; `keyword_overlap` in `--json` output therefore contains stems. `--explain` prints the stems the query became. | **5 (built)** |
| `guard "<action>"` | decisions, attempts, traps, questions, unsettled verifications, handoff (**not** ideas) | a verdict + the matches behind it (read-only — `guard` writes nothing) | Warn before a repeated mistake (deterministic ranking). Exits with the verdict-mapped code — see `guard` section. | **5 (built)** |
| `audit` | all memory + adapters | health report | Find stale / unsafe / bloated memory (incl. secret + instruction-like heuristics). Heuristic — does NOT gate `validate`. | **6 (built)** |
| `scan-secrets` | committed memory | secret report | Scan committed memory for secret-like strings; non-zero on a hit. Run before committing memory. | **6 (built)** |
| `mark-status <id> <status>` | one record, **one trap, or one open question** | status + `updated_at` (+ optional `superseded_by`) | Record lifecycle mutation (stale/disputed/superseded/…), validate-gated and reverted on failure; `--superseded-by ID` is the supersede flow. Reindexes on write. A `trap_<slug>` or `q_<slug>` id (legacy `q:<slug>` accepted) resolves too. At schema 3 each is its own file, so its frontmatter `status` is edited like any record's; on a schema-2 store — or for a block somebody typed into a singleton since the last reindex — the block's `- Status:` bullet is edited in place (every other byte preserved). Retiring a trap drops it from the resume packet and the hook pre-filter and stops it driving a `guard` verdict; answering a question drops it from the packet, from `guard`'s open-blocker floor and from the aged-unresolved staleness warning. Both stay findable in `search` under their real status. Questions carry their own vocabulary (`open`/`answered`/`closed`) because the record words do not fit — the id decides which vocabulary applies, and a mismatch is rejected by name. A block with no `- Status:` bullet counts as `active` (trap) / `open` (question). | **built** |
| `prune sessions` | `sessions/` | deletions + reindex | Delete old **machine** session snapshots (placeholder Next Action) beyond the newest `--keep N` (default 20). Human handoffs are never candidates; `--dry-run` lists. The Stop hook creates snapshots eagerly (an interrupted session is a handoff worth keeping) — retention is this separate, explicit act. | **built** |
| `rollup sessions --before YYYY-MM-DD` | `sessions/` | one session record, deletions + reindex | Fold the machine snapshots created before the date (at least two) into one session record that supersedes them, then delete them. Human/agent sessions are never touched; `--dry-run` lists. See `rollup sessions` below. | **built (WM-35)** |
| `prune jots` | `inbox/`, `private/inbox/` | deletions + reindex | Delete jots that are expired or retired **and** older than 30 days. An active, unexpired jot is never deleted however old the store is: it is still waiting for somebody to promote or drop it. `--dry-run` lists. | **built (WM-03)** |
| `expired` | all records, both inboxes | listing (read-only) | Active records past their `expires_at`, oldest expiry first, machine-local jots included. See `expired` below. | **built (WM-30)** |
| `questions [--aging]` | open questions | listing (read-only) | Open questions with their age, oldest first; `--aging` keeps those open longer than `ttl_question_days` (default 45). | **built (WM-30)** |
| `consolidate [--type T]` | live records | listing (read-only) | Clusters of near-duplicate live records (connected components of the near-duplicate pairs). | **built (WM-33)** |
| `consolidate --merge ID ID… --title "…"` | the named records | one merged record + status changes + reindex | Write one decision / attempt / verification / idea from the sources and mark every source `superseded`. See `consolidate` below. | **built (WM-33)** |
| `doctor` | adapters, `.mcp.json`, hooks, packet, `index/search.sqlite` | integration-health report | Is memory wired up? Exit 1 if a store exists but no integration is active. A `search_index` row reports the search index as fresh / stale / unreadable / unavailable (no `sqlite3` module) / not built (fine below the 200-record threshold, flagged above it); none of these changes the exit code. | **built** |
| `mcp serve\|register\|doctor` | `.mcp.json` | running server / registration / health | Run the MCP server, merge its `.mcp.json` entry, or report MCP wiring (`[mcp]` extra + registration). | **built** |
| `hook session\|guard\|capture\|prompt\|compact\|subagent` | hook stdin payload | hook JSON on stdout (+ mined jots) | Claude Code hook translators (`init --with-hooks` installs them, as a `sh` resolver that falls back through `./.venv` and `python -m breadcrumbs` and reports memory inactive if none resolve). Installed entries are identified by a `breadcrumbsHook` key, not by command text, so a custom launcher stays visible to `doctor` and `--remove-integrations`. Removal keys on that marker alone: an unmarked entry that merely looks like a crumb hook is reported and left in place, never deleted (adopt it with `init --with-hooks` to make it removable). Re-running `init --with-hooks` also brings an entry **we own** up to the current matcher, which is how an existing install picked up `Task\|Agent` on the guard. The event is validated before stdin is read, so a bare `crumb hook` reports usage (exit 2) instead of blocking on a terminal. **Every event exits 0 and prints JSON**, whatever the payload. See the per-event table below. | **built** |

### Hook events

| breadcrumbs event | Claude Code event | Matcher | Does |
|---|---|---|---|
| `session` | `SessionStart` | — | Emits the resume packet as `additionalContext`. With `source: compact` it prepends what was in flight before the compaction: the last prompt, the records surfaced for it, and the mined candidates waiting in the inbox — and builds the packet with that last prompt as its task, so the sections are ordered by relevance to it (see `resume --task`). |
| `guard` | `PreToolUse` | `Bash\|Edit\|Write\|MultiEdit\|Task\|Agent` | Cost-aware guard verdict. A subagent launch (`Task`/`Agent`) is scored on its launch prompt and **capped at `READ_FIRST`**: the launch is not itself irreversible, and the subagent's own calls hit this same hook. |
| `capture` | `Stop` | — | Mines the transcript (always, as a side effect), then snapshots a session record or holds the stop once for the extraction turn. The extraction instruction includes one line saying a write refused with exit 3 is a near-duplicate, answered with `--supersedes <id>` or `--allow-duplicate`. |
| `prompt` | `UserPromptSubmit` | — | Injects up to 5 records relevant to this prompt (≤800 approx tokens), deduped per session, with a footer pointing at `crumb show <id>` (or `memory://records/{id}`) for the full text. Captures a correction to `private/inbox/`. **Never blocks** — that would erase the prompt. |
| `compact` | `PreCompact` | — | Mines the transcript and writes a marker for the next `SessionStart`. Emits nothing: this event's stdout never reaches the model. |
| `subagent` | `SubagentStop` | — | Mines the finished subagent's transcript, tagged `subagent` and `agent:<type>`. Does not hold the subagent. |

**What the miner writes.** Four deterministic rules over the transcript — a
command that failed and passed after an edit (`attempt`), a test command that
passed (`verification`), a file edited four or more times (`trap`), and a user
message that opens like a correction. Candidates become jots in
`private/inbox/`, never the committed store, after a secret scan that drops
rather than masks. Bounded at 10 per firing and deduped by fingerprint within a
session. A cursor in `private/miner-cursor.json` stops a later firing re-mining
what an earlier one already read.

### Integration flags on `init`

```text
init --with-adapter[=CLAUDE.md,…] / --no-adapter   # signpost block in detected guidance files
init --with-mcp / --no-mcp                          # merge .mcp.json entry
init --with-hooks[=session,guard,capture] / --no-hooks
init --print-integrations                           # dry run
init --remove-integrations                          # reverse everything
```

On a TTY with none specified, `init` asks once per integration; non-interactive +
unspecified writes nothing (plus a one-line nudge). Every edit is fenced and
reversible.

Both lists are validated **before any filesystem mutation** — `--with-hooks` against
`session|guard|capture`, `--with-adapter` against the known guidance filenames —
and a typo exits 2 naming the valid values, with nothing written. `init` never
injects the signpost into a file outside that list, because `--remove-integrations`
would not know to look there. (For stores already in that state, removal scans the
project root for stray managed blocks and reverses them too.)

Ctrl+C at any `init` prompt aborts with exit 130 and writes nothing further; EOF
(piped input) still takes the prompt's default.

**Reporting matches reality.** Each adapter/MCP target is reported as
`(updated)` or `(already current)` — `init` never claims to have written a file
it left byte-identical (`--json` carries `adapter_states` / `mcp_state`).
Registering the MCP server leaves other `.mcp.json` entries byte-for-byte
untouched (a fresh insert is a re-parse-verified text splice, an already-current
entry is a no-op; only a degenerate file falls back to a full rewrite), and
`init` finishes by building the `generated/` projections so `doctor` can be
green immediately.

**A note on the hook marker.** Installed hook entries carry a `breadcrumbsHook`
key *inside* Claude Code's `.claude/settings.json` hook objects. That is a
foreign key in another product's schema, relying on Claude Code ignoring
unknown keys (which it documents and does). It is deliberate: identity in the
command text broke under wrapper scripts, venv paths, and `python -m
breadcrumbs` launchers — `doctor` saw "no hooks" while all three fired, and
removal left ghosts. If Claude Code ever rejects unknown keys, reinstalling
hooks (`init --with-hooks`) is the migration path; the marker's name is
namespaced enough to make a collision implausible.

### Later commands (post-MVP)

**None of these exist**, and none is scheduled. They are recorded here as the shape
a later version might take, not as work in progress:

```text
supersede <old-id> <new-id>   # sugar over `mark-status --superseded-by` / a writer's `--supersedes` (both built)
dashboard | recent | where-was-i
```

---

## `init` (built)

```bash
crumb init
crumb init --session-tracking <full|distillate>
crumb init --no-commit-generated
crumb init --project <path>
crumb init --force
```

Behavior:

- Refuses to clobber an existing `.project-memory/` unless `--force` (which
  replaces the scaffold and deletes all existing records). With any
  `--with-adapter`/`--with-mcp`/`--with-hooks` flag, an existing store is left
  untouched and just those integrations are applied (no `--force` needed).
- Copies the bundled `breadcrumbs/templates/project-memory/` tree (shipped as
  package data, resolved package-relative) into the target's `.project-memory/`.
- Auto-derives `project` (root dir name), `created_at` (ISO-8601 w/ tz), and sets
  `schema_version` to this build's `SCHEMA_VERSION` (currently `3`).
- **Session-tracking policy:** `--session-tracking <full|distillate>`, else prompt;
  non-interactive default is `full`. Recorded in `manifest.yml`.
- **Generated-projection policy:** default `commit_generated_projections: true`;
  `--no-commit-generated` flips it. Recorded in `manifest.yml`.
- Writes a managed `.gitignore` block matching the policies. `index/**` is always
  ignored (except `index/README.md`); `private/**` is always ignored;
  `--no-commit-generated` ignores `generated/*.md` (keeping the README);
  `distillate` ignores `sessions/`.
- **Non-git fallback:** detects whether the project is a git repo; if not, prints a
  notice that git-derived record fields will use the sentinels documented in
  [`record-schema.md`](record-schema.md) §7 (`branch: (no-git)`,
  `commit: (no-git)`, `dirty_files: []`).
- `--json` emits a machine summary of what was created and the chosen policies.

---

## `resume` (built)

```bash
crumb resume                  # full bounded packet; writes generated/resume-packet.md
crumb resume --fast           # reduced reorientation view (print-only)
crumb resume --json           # structured packet (sections + warnings + source header)
crumb resume --stale-days N   # age cutoff in days (default: 21)
crumb resume --task TEXT      # resume FOR this task: scope likely-files, order by relevance (print-only)
```

Behavior:

- Assembles the §12 packet from `current.md`, `handoff.md`, active `decisions/`,
  active `attempts/`, the traps and open questions (`traps/` and `questions/` at
  schema 3, the `known-traps.md` / `open-questions.md` blocks before), and live
  git state.
- **`--task` orders by relevance, and hides nothing.** With a task, one
  `search` over the corpus (ideas excluded) scores every record against it, and
  each list section — active decisions, failed attempts, verifications, known
  traps, open questions — is reordered: the newest `RECENCY_FLOOR` (3) entries
  keep their place first, then the entries the task scores against, best first,
  then the rest in recency order. Caps and the token budget apply afterwards, so
  what relevance changes is which entries survive a trim. The packet carries
  `ordering: "relevance"` (`"recency"` otherwise, including a task that matched
  nothing), and the rendered packet says so under the Project line:
  `_(sections ordered by relevance to: <task>; the 3 newest in each stay first)_`.
  `--task` also scopes `likely_files` to the matching records, labelling an empty
  result `starting cold`.
- **Bounding:** per-section caps, then a hard **5,000-token** ceiling (chars/4
  heuristic). Current/handoff/active-decisions outrank old session observations;
  lower-priority sections are trimmed first and an omission note is shown. Raw
  transcripts are never included.
- **Computed staleness** (not just authored): handoff **age + commit-distance**,
  **aged-unresolved** questions/decisions (> `--stale-days`), **branch mismatch**
  (incl. detached HEAD), and **expired**/**low-confidence** records.
- **Expired records leave the lists (WM-30).** A decision, attempt or
  verification past its `expires_at` keeps `status: active` and stays on disk
  and in `search`, but is dropped from the packet's list sections (the "expired
  on …" staleness line still names an expired decision or attempt). `crumb
  expired` lists them.
- **Lifecycle warnings (WM-30, WM-31, WM-34)**, each kind capped separately:
  - an actionable verification (`open`, `regressed`, `inconclusive`) whose
    `updated_at` (else `created_at`) is at least `ttl_verification_days` (90)
    old — `verification <id> is N days old; recheck it (\`crumb verify --recheck
    <id>\`).` (up to 3);
  - an active trap not confirmed — or, for a trap file never confirmed, not
    written — within `ttl_trap_days` (180), pointing at `crumb traps --confirm`
    and `crumb mark-status <id> stale` (up to 3);
  - `current.md` unchanged for `ttl_current_days` (14). The age is taken from
    the last git commit that touched the file (`0` when it has uncommitted
    changes), or from its mtime when the store is not in git — a checkout
    rewrites every mtime, so on a fresh clone mtime would say "today";
  - a listed decision, attempt or verification citing `file`/`path` evidence
    that is neither on disk nor in HEAD — `<id> cites <ref>, which is not in
    HEAD — verify the record still applies.` (up to 5, then `(+N more …)`).
    A `:line` suffix is stripped first; URLs, globs, absolute and `~` paths are
    skipped. `guard` scoring does not use this;
  - a possible contradiction from `generated/conflicts.json`'s rules (see
    `reindex`), worded as a question (up to 3, then `(+N more …)`).
- **A branch mismatch is only reported for memory that has not reached HEAD.**
  The handoff and every record carry the branch they were written on; the
  warning exists because that branch may describe code this checkout does not
  have. A file that is committed in HEAD's tree and unmodified in the worktree
  has arrived here — merged, squash-merged, rebased or cherry-picked, the sha
  history does not matter — so its `branch:` is provenance, not risk, and it
  is not reported. In a branch-per-session workflow the old check printed a
  handoff mismatch plus a roll-call of every record ever written, on every
  resume, guard call and audit. An uncommitted or locally modified file from
  another branch still warns, as does everything when there is no HEAD to
  judge against.
- **The focus claims are falsifiable (0.1.11, P1-5).** Age and distance say how
  *old* the handoff is, never whether its claims still hold — the field test's
  packet told a fresh session to redo two items that had already landed. Two
  checks close that gap: the packet lists the commit subjects landed since the
  handoff was written (`commits_since_handoff`, bounded, rendered as *Landed
  Since The Handoff Was Written*) so the reader can check the work-list against
  history; and a **fixed** verification whose subject the Current Focus /
  Next Action text mostly restates (two-thirds of the subject's stems, at
  least two; digit-only tokens such as the `11` in `0.1.11` never count) adds a
  warn-only `possible drift:` line. The first cut fired on *any* two shared
  stems and, on this tool's own store, flagged four of nine fixed
  verifications, all falsely — a drift line is either the first thing the
  reader resolves or the line that teaches them to skip the section. Citing a
  commit sha or file in `--next` (the extraction prompt now asks for one) keeps
  the claim checkable.
- **Current Focus never mirrors Next Action.** `capture session` no longer
  defaults an unset `--focus` to the Next Action text, and packets from stores
  written before 0.1.11 render the verbatim duplicate as
  `_(same as Next Action)_` instead of printing ~1.4k chars twice (P1-6).
- **The threshold and the ages are separate, separately named fields.** `--json`
  carries `stale_after_days` (the cutoff in force) alongside `handoff_age_days` and
  `handoff_commit_distance` (what was measured; `null` when the timestamp is
  unparseable or there is no git repo), and the rendered packet names the cutoff
  above the warnings. One number is a policy, the others are facts — a distinction
  the old single `stale_days` field hid.
- **`next_action` here is recorded state, not advice.** The packet's
  `next_action` is the `## Next Action` a session handoff left behind — `""` when
  nobody set one. `guard --json` has no `next_action`: its synthesized advice is
  **`recommended_action`**, and it is always a non-empty string. The two were one
  name until 0.1.9, which made an unset handoff look like a broken guard.
- The **committed** projection is always written with the default cutoff, not the
  one a given invocation passed: a shared artifact must not change because one
  developer preferred `--stale-days 7`. `--stale-days` affects what *you* see.
- **Source header:** every packet carries `source_commit` / `inputs_hash` /
  `generated_at` (carrying the `GENERATED PROJECTION` marker so `validate` accepts
  it and `audit` can later detect drift).
- **Project path is project-relative** (`.`) in both the rendered packet and
  `--json`: the packet is a committed, shared artifact, so it never carries the
  author's absolute host path.
- Refreshes the store-global projections through the same reindex every mutation
  uses — `generated/resume-packet.md` (the committed cloud-fallback artifact under
  the default policy), `generated/guard-prefilter.json`,
  `generated/related.json` and `generated/conflicts.json`, each written
  atomically (see `reindex`). `--fast`
  and `--task` are **print-only** and never overwrite them.
- Exit codes: `0` on success, `2` when no `.project-memory/` store is present.

---

## `show` (built)

```bash
crumb show dec_20260625_repo-local-memory-source-of-truth   # full text + "See also:"
crumb show trap_gradlew-stop                                 # a trap
crumb show q_should-age-signals-gate-compliance --json       # a question, structured
```

The other half of the one-line-per-record packet and hook injection: fetch the
body when a line looks relevant.

- Resolves any id the tool prints: a directory record (`dec_`, `att_`, `ver_`,
  `idea_`, `ses_`, `jot_` — committed or machine-local), a trap (`trap_…`) or a
  question (`q_…`; the legacy `q:…` spelling is accepted). Records are tried
  first, then traps, then questions — the order `mark-status` uses. One resolver,
  `cli.find_item`, backs `show`, the `memory://…/{id}` resources and
  `memory_show`, so they cannot disagree about what an id names.
- Prints the whole file (frontmatter and body). A trap or question still stored
  as a block (schema 2, or hand-written into a singleton since the last reindex)
  prints as that block.
- Adds `See also: …` from `generated/related.json` when the item has related
  records (see `reindex`).
- `--json`: `{id, kind, status, path, text, related}` (`items` aliases
  `related`); `path` is absolute, as elsewhere on the CLI.
- An ambiguous question id (two slug-derived ids colliding) resolves to nothing
  rather than to one of the two.
- Exit codes: `0` found, `1` unknown id (`CRUMB-ERROR: crumb show: …`), `2` no
  store.

---

## `reindex` (built)

```bash
crumb reindex                  # rebuild every projection
crumb reindex --search-index   # ...and build index/search.sqlite regardless of store size
```

Every mutation runs the same reindex; this command runs it on demand. In order:

1. **At schema 3, the trap and question indexes.** `known-traps.md` and
   `open-questions.md` are rewritten as one line per record pointing at its file.
   A `## trap_…` / `## Q:` block somebody typed into either file since the last
   reindex is first *adopted* into its own file. A block whose id already
   belongs to a file with different content is not adopted: it is kept verbatim
   below the index under a `Not adopted` comment, the file keeps driving every
   reader, and `audit` reports it (`unadopted-block`). If adoption fails, both
   files are left untouched.
2. `generated/resume-packet.md` and `generated/guard-prefilter.json`.
3. **`generated/related.json`** — up to three related ids for every live item
   (active; for questions, `open`). A pair is scored by what the two share, and
   nothing else: shared declared files ×6, shared tag stems ×4, shared specific
   stems ×1 (minus ubiquitous stems — the same gate as `search`, computed over
   the live items), kept when the
   score reaches `GUARD_NOISE_FLOOR`; ties break by id. It deliberately does not
   reuse the guard's scorer, which decays by branch, clock and commit distance —
   two clones would compute different relations for identical records. Stamped
   with `inputs_hash`, so `validate` and `audit` detect it going stale. Above
   2000 items the map is empty and `skipped` names the reason.
4. **`generated/conflicts.json`** (WM-34) — pairs of live records that may
   argue with each other, `{_generated, inputs_hash, conflicts: [{rule, ids,
   similarity, message}]}`. Two rules:
   - `retry-after-do-not-retry` — an active attempt with a *Do Not Retry
     Unless* section, and an active decision created after it whose *Decision*
     section is at least 0.5 Jaccard-similar to the attempt's *Tried* section
     (over specific stems), or that shares a declared file with it;
   - `overlapping-decisions` — two active decisions at least 0.7 similar (the
     near-duplicate measure, see below), created more than 7 days apart,
     neither listing the other in `supersedes`.

   Expired records take no part. It reads `created_at`, never the clock, so
   every clone computes the same file. Stamped with `inputs_hash`, so
   `validate` and `audit` detect it going stale, like `related.json`.
5. **`index/search.sqlite`** — the disposable search index (see `search`). Built
   only when the indexable corpus (decisions, attempts, verifications, ideas and
   committed jots, in directories the freshness hash covers) holds at least
   `INDEX_MIN_CORPUS` (200) records; below that, a leftover index is deleted.
   `--search-index` builds it whatever the size, but `search` still consults an
   index only past the threshold, and the next ordinary reindex of a small store
   deletes it again. A build failure is swallowed: no index only means the full
   scan.

`--json` adds a `search_index` object (`{built, records, reason}`) when
`--search-index` is passed.

---

## `migrate` (built)

```bash
crumb migrate --dry-run   # list the steps that would run; change nothing
crumb migrate             # back the store up, then apply them in order
```

| Step | Change |
|---|---|
| 2 | Create `inbox/` and `private/inbox/` (the jot tier). |
| 3 | Move traps and questions to one file each; `known-traps.md` and `open-questions.md` become generated indexes. |

**Step 3** writes every `## trap_…` block to `traps/<slug>.md` and every `## Q:`
block to `questions/<slug>.md`, keeping the id (lowercased; a trap slug that is
still not a usable filename is slugified, and the step's output names that
change) and every line of the block: content bullets become sections, bookkeeping bullets
(`Status`, `Last confirmed`, `Superseded by`, `Opened`) become frontmatter, and
anything else — free prose, provenance comments — becomes the `Notes` section.
It then rewrites both singletons as indexes. The written files are validated
once; on failure they are removed and the step raises, leaving the store at
schema 2 exactly as it was. Re-running it is a no-op apart from rewriting the
indexes: an existing file is never overwritten.

Readers switch on the manifest's `schema_version`, never on what is on disk, so
a schema-2 store keeps reading and writing blocks until it is migrated.

---

## `search` (built)

```bash
crumb search "auth middleware"      # keyword search over the records
crumb search --tag auth             # filter by tag/component
crumb search --file src/auth/x.ts   # filter by referenced file path
crumb search --type verification --status open    # filter-only lookup (no query)
crumb search "session" --type decision --json
crumb search "login flow" --explain                # show the stems the query became
```

```text
--type {decision,attempt,verification,idea,trap,question,jot}
--status <value>     record status; for a verification, its outcome (open, fixed, …)
--tag <value>        tag / component
--file <path>        a file path referenced by the record
--explain            print the query's stems (and whether aliases.txt is active)
--stale-days N       age cutoff in days (default: 21) — aged records score lower
```

Behavior:

- **Deterministic and dependency-free.** Exact/keyword text, tag/component and file
  path; no embeddings. Same input → same output, with or without the search
  index below.
- The **corpus** is decisions, attempts, verifications, **ideas**, jots, known
  traps and open questions. `sessions/` is deliberately out: sessions are narrative, and a
  `session_tracking: distillate` clone may not have them at all, so including them
  would make results depend on which checkout you ran in.
- **`ideas/` is searchable here and invisible to `guard`.** That asymmetry is the
  point, not an oversight. An idea is a proposal — exempt from the §16.9 evidence
  rule — and `guard`'s score band does not care what kind of record it is scoring,
  so a speculative note naming the right files would otherwise gate a real edit on
  the strength of nobody having done the work. `crumb search --type idea` finds it;
  a `guard` verdict never sees it. Fixture 12 is the control.
- A query with no filters ranks by overlap; filters with no query list every
  matching record instead of returning nothing.
- **Search can return zero, and that is an answer.** A pure-text match needs the
  same shared-keyword floor as `guard` (`GUARD_MIN_KEYWORD_OVERLAP`, relaxed to
  the query's own specific-token count so a one-word lookup like "libsignal"
  still works). Before 0.1.11 a single generic shared token ("version") counted
  as a match, which made weak queries return confident noise.
- **Ubiquity gate (shared with `guard`).** Once the corpus holds at least
  `GUARD_DF_MIN_CORPUS` items, a stem present in more than `GUARD_DF_UBIQUITY`
  of them (package prefixes shed by cited paths, the project's own domain noun)
  carries zero keyword weight and no gate credit. File and tag matches are
  exempt — both are author-curated signal.
- **Store aliases.** `.project-memory/aliases.txt` (committed) adds the
  project's own synonyms to the stemmer: one group per line, whitespace-separated
  words, all folding to the first word's stem (`auth authn authz login`). `#`
  starts a comment; blank lines are ignored; a word already claimed by an
  earlier group keeps its first meaning, and chains resolve to a fixpoint. The
  table applies wherever stems are compared — `search`, `guard` and the hook
  pre-filter — and the file is part of `inputs_hash`, so editing it makes the
  projections stale until the next reindex. A malformed line (fewer than two
  words, or a word already in an earlier group) is skipped and reported by
  `audit` as `aliases`.
- **`--explain`** prints `query stems: …` before the results, plus
  `store aliases active: N (aliases.txt)` when the file maps any words, so a
  synonym that missed can be traced to how the two words stem. With `--json` it
  adds `query_stems`.
- **The search index narrows, it never ranks.** Past `INDEX_MIN_CORPUS` (200)
  indexed records, reindex builds `index/search.sqlite`: a plain SQLite inverted
  index (not FTS5, whose tokenizer splits on `_`, `/`, `.` and `-` and so would
  not store the tokens scoring compares) of each record's specific stems, tag
  stems and files. `search` uses it to pick the records that share at least one
  of those with the query, parses only those, and scores them exactly as the
  full scan would; ubiquity for the query's stems comes from the index's
  document frequencies. Matches and scores are identical with and without it.
  Traps, questions, machine-local jots and any directory the freshness hash does
  not cover are always parsed directly. The index is machine-local, gitignored
  and disposable, stamped with the inputs it was built from (a cheap stat
  fingerprint first, `inputs_hash` when that differs); a stale, absent or
  unreadable index — or a Python without `sqlite3` — is never used, and search
  falls back to the full scan.
- **Expired records are still found.** A record past its `expires_at` keeps
  its status and is searched like any other; the human line marks it
  (`[active, expired]`, or `[fixed, expired]` for a verification, whose
  bracket shows the outcome) and every `--json` match carries an `expired`
  boolean.
- `guard` is this same engine with a verdict on top plus a noise floor,
  so a `search` hit is the permissive case of a `guard` match.
- Exit codes: `0` on success (including zero matches), `2` when no
  `.project-memory/` store is present.

---

## `guard` (built)

```bash
crumb guard "<proposed action>" [--files F ...] [--json] [--stale-days N]
```

The judging layer on top of `search`: classify the action, rank the overlapping
records, emit one deterministic verdict (`PROCEED` / `READ_FIRST` / `PAUSE` /
`ASK_HUMAN`) plus the matches behind it.

Behavior (deltas from `search` — everything there applies here too):

- **Verdict floors need author-curated specificity.** A matched decision,
  unsettled verification, or trap floors the verdict at `READ_FIRST` (a
  do-not-retry attempt at `PAUSE`) only when the match carries a **file or tag**
  signal. A keyword-only match — however the tokens overlap — can escalate only
  through the score bands (`GUARD_READ_FIRST_SCORE` / `GUARD_PAUSE_SCORE`).
  Until 0.1.11 a keyword-only *trap* match floored `READ_FIRST` unconditionally;
  in a store whose vocabulary overlaps the codebase that made one trap fire on
  every edit of a session (the 0.1.10 field test's 13-for-13).
- **Staleness on the guard path is risks-only.** Only abnormal states — cold
  handoff (`⚠`), detached HEAD, handoff branch mismatch — ride along with a
  verdict. The routine store facts (fresh handoff age, aged records, low
  confidence, other-branch record lists) are read once per session in
  `resume`/`doctor`/`audit`, not once per edit.
- **An expired record is history.** A match past its `expires_at` is listed
  under `history` (context only), like a superseded one, and never drives the
  verdict.
- **Exit codes are verdict-mapped** so callers can script on the verdict
  without parsing output: `PROCEED` = 0, `READ_FIRST` = 10, `PAUSE` = 15,
  `ASK_HUMAN` = 20 (`>= 15` means a human belongs in the loop); `2` = usage
  error / no store. Deliberately clear of 1, 2, and the shell's 126+ range.
  The hook translator (`crumb hook guard`) always exits 0 — hook protocols
  treat nonzero as a hook failure.

The `PreToolUse` hook path adds two behaviors of its own:

- **Edits carry content.** The guard action for an `Edit`/`Write`/`MultiEdit`
  is `edit <path>: <bounded snippet of the new content>`, so successive edits
  of one file stop producing byte-identical guard input and a content-shaped
  trap ("this API is banned") can actually match.
- **Advisories dedupe per host session.** A `READ_FIRST` for the same file and
  the same matched records fires once per session (state in
  `private/hook-guard-seen.json`, machine-local, bounded); a new record, a
  different file, or a new session speaks again. `PAUSE`/`ASK_HUMAN` are never
  deduplicated.

---

## `audit` (built)

```bash
crumb audit                  # human health report
crumb audit --json           # structured findings (check/severity/path/message)
crumb audit --plain          # one line per finding
crumb audit --stale-days N   # age cutoff in days (default: 21)
```

`audit` is the **heuristic** safety net that `validate`'s determinism intentionally
excludes (see the determinism note). It never gates `validate`; it advises. Findings
carry a severity:

- **fail** — blocks (non-zero exit). The *only* fail-severity check is a **secret
  leak**: a token-like string in committed memory (see `scan-secrets`). This must be
  resolved before any "commit memory" workflow.
- **warn** — flag for human review; never changes the exit code. Covers: stale
  handoff (age + commit-distance), branch mismatch (incl. detached HEAD),
  aged-unresolved questions/decisions, expired + low-confidence records,
  **instruction-like text** (override phrasing such as "ignore the tests" — flagged,
  never executed: matched memory is data, not command), **generated-packet drift**
  (a committed projection — `generated/*.md`, `related.json` or `conflicts.json` — whose stamped
  `inputs_hash` no longer matches the canonical inputs → regenerate), bloat
  (adapter files duplicating memory; over-budget packet), the validate-failing
  health conditions re-surfaced for one health view (missing evidence, invalid
  status, private-path violation, id/frontmatter disagreement),
  **`unadopted-block`** (at schema 3, a hand-written trap/question block in a
  singleton whose id already has a file with different content — merge it into
  the file by hand, then delete the block), **`aliases`** (a malformed line in
  `aliases.txt`, which is ignored), and three lifecycle checks over live
  (active, unexpired) records:
  - **`evidence-missing-file`** — a decision, attempt or verification cites
    `file`/`path` evidence that is neither on disk nor in HEAD (same rules as
    the packet warning in `resume`; up to 20 findings);
  - **`possible-contradiction`** — a pair from the two `conflicts.json` rules
    (see `reindex`; up to 10);
  - **`near-duplicates`** — two live records of the same type at or above the
    near-duplicate threshold (0.6; 0.9 for jots), with the commands to
    supersede one or merge them (up to 10 pairs). A pair already reported as a
    possible contradiction is not reported again here. A type with more than
    2000 live items is not swept.
- **info** — context note (e.g. `sessions/` growth → the note names `crumb
  rollup sessions --before YYYY-MM-DD`, and `crumb prune sessions`).

Exit codes: `1` when any **fail** finding is present (a secret), else `0`; `2` when no
`.project-memory/` store is present.

---

## `scan-secrets` (built)

```bash
crumb scan-secrets           # human report; non-zero on any hit
crumb scan-secrets --json    # {ok, count, hits:[{pattern, path, line}]}
```

The secret sub-check of `audit`, exposed standalone so it can run as a pre-commit /
pre-push gate before memory is committed (§2.6, §15). Scans committed memory only —
`private/`, `index/`, and `generated/` are skipped. Reports the matched pattern
**name** and location, never the secret value. Coverage is deliberately conservative
(AWS/GitHub/Slack/Google/OpenAI-style keys, JWTs, PEM private-key headers, bearer
tokens, `secret/token/password=`-style assignments, and mixed-class high-entropy
blobs). The covered set is `SECRET_PATTERNS` in `breadcrumbs/cli.py`, and the
false-positive controls (git SHAs, record ids, path- and CamelCase-shaped tokens)
are pinned by `tests/test_secrets.py`; known gaps are listed in
[`security.md`](security.md) §2. Exit codes: `1` on any hit, `0` when clean, `2`
when no store is present.

---

## Near-duplicate gate (built, WM-32)

```bash
crumb remember decision --title "…" … --supersedes dec_…   # replace that record
crumb note trap "…" --allow-duplicate                      # write both
crumb jot "…" --allow-duplicate                            # jots take no --supersedes
```

`remember`, `note question|trap|idea`, `verify` and `jot` refuse a new record
that nearly repeats a **live** record of the same type — active and unexpired;
for a question, `open`. The refusal is exit **3** with

```text
CRUMB-ERROR: crumb remember decision: looks like <id> (0.71 similar) — pass --supersedes <id> to replace it, or --allow-duplicate to write anyway
```

(a jot's says only `--allow-duplicate`). Up to three matches are named, most
similar first. Under `--json` the refusal is `{ok: false, command, error:
"near-duplicate", message, duplicates: [{id, title, similarity}], items}`
(`items` aliases `duplicates`).

- **Similarity** is Jaccard over the specific stems (the vocabulary `search`
  scores on) of the title plus the section content (plus tags) — `0` unless the
  two share at least 3 stems or have identical stem sets — plus 0.15 per
  shared declared file and 0.1 per shared tag, that bonus capped at 0.2; the
  total capped at 1.0. The threshold is 0.6 (0.9 for jots — a repeated
  observation is itself a signal, so only a near-verbatim repeat is refused).
  Sessions are never compared.
- **`--supersedes ID`** names a live record of the same type that the new one
  replaces, and skips the similarity check. The new record gets `supersedes:
  [ID]` (decisions, attempts, verifications, ideas — trap and question files do
  not carry the key), and the old one is marked `superseded` with
  `superseded_by`; a question is marked `closed` with `superseded_by`, because
  the question vocabulary has no `superseded`. An id that is unknown, of
  another type, or already retired is refused before anything is written, with
  exit 2 (a usage error) on every writer.
- **`--allow-duplicate`** writes the record anyway.
- An **exact repeat** — the same question text, the same trap slug — keeps its
  existing exit-1 error (`… reopen it with \`crumb mark-status <id> open\``).
- Internal writers (`inbox promote`, migrations, the transcript miner) are not
  gated. The MCP writers are: see [`mcp-spec.md`](mcp-spec.md).

Records that predate the gate are found by `audit` (`near-duplicates`) and
grouped by `consolidate`.

---

## `verify --recheck` (built, WM-31)

```bash
crumb verify --recheck ver_20260801_unit-suite-open          # asks y/N per record
crumb verify --recheck ver_… --recheck ver_… --yes           # runs without asking
crumb verify --all --yes                                     # every active verification with a command
```

Reruns the `command`/`test` evidence a verification recorded and writes the
result as a **new** verification. Each record's commands are printed first;
without `--yes`, a terminal is asked `run these? [y/N]` per record, and with no
terminal the command exits 2 having run nothing. There is no MCP equivalent, on
purpose: running commands taken from the store is a human-confirmed, CLI-only
act.

- Each command runs with `shell=True` in the project root, with a 300-second
  timeout.
- The new verification has the same subject, `method: runtime`, outcome `fixed`
  when every command exited 0 and `open` otherwise, the commands as `command`
  evidence, and a `Notes` section with each command's exit code and its last 3
  non-empty output lines — a line that looks like a secret is replaced by
  `[line dropped: looked like a secret]`. The old record is marked `superseded`
  by it. The near-duplicate gate does not apply.
- `--all` takes every active verification that names a command. A named id that
  is not a verification or has no command evidence is reported with a
  `CRUMB-WARN` line and skipped.
- Exit codes: `0` all recorded (a declined record counts as skipped, not
  failed), `1` nothing to recheck or a new record could not be written, `2` no
  store or no terminal without `--yes`. `--json` returns `{rechecked: [{ok, id,
  new_id, outcome, runs: [{command, exit_code, tail}]}], summary: {rechecked,
  fixed, open, skipped}}`.

---

## `expired` and `questions` (built, WM-30)

```bash
crumb expired [--json]              # active records past expires_at
crumb questions [--aging] [--json]  # open questions with their age
```

Every type has a lifespan, set per store with `ttl_<type>_days` keys in
`manifest.yml` (see [`record-schema.md`](record-schema.md) §3): jots 14 days,
questions 45, verifications 90, traps 180, `current.md` 14. What reaching it
does differs by type: a jot or a settled verification carries an `expires_at`;
an actionable verification, a trap and `current.md` raise packet warnings (see
`resume`); a question shows up under `questions --aging`. Decisions and attempts
have no lifespan. Every age is measured through one clock, `cli._now()`.

- **`expired`** lists every record whose `status` is still `active` and whose
  `expires_at` has passed, oldest expiry first — including machine-local jots,
  since it is a local listing. Expiry is decay, not retirement: the record stays
  on disk and in `search`, and leaves the packet's lists and `guard`'s live set.
  Still true? Record it again. No longer true? `crumb mark-status <id> stale`.
  `--json`: `{expired: [{id, kind, title, expires_at, days_ago, path}]}`.
- **`questions`** lists open questions, oldest first, marking those open longer
  than `ttl_question_days` as `AGING`; `--aging` keeps only those. `--json`:
  `{questions: [{id, question, opened, age_days, aging}], ttl_days}`.
- Both are read-only. Exit codes: `0`, or `2` when no store is present.

---

## `consolidate` (built, WM-33)

```bash
crumb consolidate [--type decision] [--json]         # list clusters
crumb consolidate --merge dec_… dec_… --title "…" [--set Rationale "…"] [--agent …]
```

Without `--merge`, lists clusters of near-duplicates: connected components of
the pairs `audit`'s `near-duplicates` check finds, biggest first, with each
pair's similarity (`--json`: `{clusters: [{kind, ids, titles, pairs}]}`).
Nothing is merged automatically.

`--merge` writes one record that replaces the named ones:

- Only decisions, attempts, verifications and ideas, all of one type. Mixed
  types, any other type, an unknown id, or a source that is already retired →
  exit 2; fewer than two ids or no `--title` → exit 2.
- Each body section is every source's non-empty text for that heading, in
  created order, each prefixed `_(from <id>)_`. `--set HEADING TEXT`
  (repeatable) replaces a heading outright.
- Evidence and tags are the unions, `confidence` the lowest, and `supersedes`
  lists every source. For verifications, `subject` is the title and
  `outcome`/`method` come from the newest source.
- The record passes the validate gate (exit 1 and nothing kept if it fails);
  every source is then marked `superseded` with `superseded_by`, and the
  projections are rebuilt. The output reminds you that the merged body is a
  starting point to edit.

---

## `rollup sessions` (built, WM-35)

```bash
crumb rollup sessions --before 2026-09-01 --dry-run   # list what would be folded
crumb rollup sessions --before 2026-09-01             # fold and delete
```

Folds the **machine snapshots** (sessions whose Next Action is the Stop hook's
placeholder) created before the date into one session record, then deletes
them. A session with a real Next Action — written by a person or an agent — is
never a candidate, and neither is an earlier rollup. Fewer than two candidates
is a no-op.

- The record is titled `rollup: <first date>..<last date> (<N> sessions)`; its
  *Work Completed* has one `- <date>: <text>` line per source, its *Next
  Action* is `(rolled up)`, and `supersedes` lists the source ids.
- It is dated and pinned — `created_at`, `updated_at`, `branch`, `commit` — to
  the last snapshot it replaces. Stamped "now" it would become the newest
  session record, which the Stop hook diffs from, and the commits since the last
  kept snapshot would drop out of the next capture.
- Exit codes: `0` (including nothing to roll up), `1` the record failed
  validation (nothing deleted), `2` a `--before` that is not a `YYYY-MM-DD`
  date, or no store. `--json`: `{rolled_up, ids, dry_run, id, path}` (`title`
  instead of `id`/`path` on a dry run).

---

## `--fast` semantics

For `capture` and `resume` (Phases 3–4): skip all prompts and any LLM narrative and
operate from git state only. `capture --fast` writes a git-only snapshot plus a
one-line next action (~15-second path for a tired human). `resume --fast` prints the
git snapshot, current focus, next action, and computed staleness warnings only —
skipping the fuller record summaries.

---

## Determinism note

`validate` is fully deterministic. Heuristics (secret scan, instruction-like text
detection) live in `audit`, never in `validate`. See
[`security.md`](security.md).
