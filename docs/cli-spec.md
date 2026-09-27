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
(`CRUMB-ERROR: …` on stderr) — including a writing command that could not take
the store's write lock within 2 seconds, see
[Store write lock](#store-write-lock-built-wm-51) — `2` usage error or no `.project-memory/` store, `3`
a writer (`remember`, `note`, `verify`, `jot`) refused a **near-duplicate** of a
live record — see [Near-duplicate gate](#near-duplicate-gate-built-wm-32).
`guard` maps its verdicts to `0`/`10`/`15`/`20` instead (see `guard`).

---

## Command table

| Command | Reads | Writes | Purpose | Phase |
|---|---|---|---|---|
| `init` | project root | `.project-memory/`, `manifest.yml`, `.gitignore` edits | Install memory layout; record session + generated-projection policy in `manifest.yml`. | **1 (built)** |
| `validate` | all canonical files | validation output | Enforce schema and invariants (deterministic). Includes a projection-freshness check: fails on a `generated/` projection (`*.md`, or a `*.json` carrying a top-level `inputs_hash`: `related.json`, `conflicts.json` and, since audit WP07, `guard-prefilter.json`; the stamp `unstable` is always stale) whose stamped `inputs_hash` no longer matches the live records. Also checks the record contract (`record-schema.md` §4): field vocabularies, evidence shape, timestamps, scope, and `superseded_by` links (a missing target, a self-link or a cycle). Reports every symbolic link or junction inside the store as `path-link` (audit WP13; nothing there may be one, and readers refuse them). Every finding carries a stable `code`, and `--json` includes it. | **2 (built)** |
| `remember decision` | git state, user input | decision record | Capture a durable choice. Refuses a near-duplicate of a live decision (exit 3) unless `--supersedes ID` or `--allow-duplicate`. | **3 (built)** |
| `remember attempt` | git state, user input | attempt record | Capture a tried path and its outcome. Same near-duplicate gate as `remember decision`. | **3 (built)** |
| `verify <subject>` | git state, user input | verification record | Record a verification result (a finding about reality): `--status fixed\|open\|regressed\|not_applicable\|inconclusive`, `--method static\|runtime\|test`. A settled outcome (`fixed`, `not_applicable`) gets an `expires_at` (`ttl_verification_days`, default 90). Near-duplicate gate as on `remember` (`--supersedes ID`, `--allow-duplicate`). `--assert CMD` (repeatable) declares an assertion, the only kind of check a recheck may settle the claim with. `--recheck ID` (repeatable) or `--all`, with `--yes`, reruns a verification's checks instead — see `verify --recheck` below; `--status` is required only when not rechecking (exit 2 without it). `--scope branch` makes the result apply only while the current branch is checked out (default `project`; see [Branch scope](#branch-scope-built-wm-52)). Reindexes on write. | **built** |
| `recover [--apply]` | `private/operations/` | the files an unfinished operation touched | List, or with `--apply` roll back, the multi-record operations a writer that stopped midway left unfinished. Exit 1 while any remain unfinished. See [Multi-record operations](#multi-record-operations-and-recover-built-audit-wp06). | **built (audit WP06)** |
| `reindex` | all canonical files | `generated/` projections, the trap/question indexes (schema 3), `index/search.sqlite` | Rebuild the generated projections from the records (mutations reindex automatically). `--search-index` builds the search index even below its size threshold — see `reindex` below. | **built** |
| `capture session` | git state (log, status, diff --shortstat) | session record, handoff, current | Record session end; git-prefill body sections (Files Touched is a counts-only summary) over a bounded window (`since..HEAD`, capped at 20 commits) that the record names. `--fast` = git-only snapshot + one-line next action; `--next` + `--set` runs unattended without dropping narrative. At schema 4, on a branch that is not the default branch, the handoff written is `handoffs/<branch-slug>.md` instead of `handoff.md` — see [Branch handoffs](#branch-handoffs-built-wm-50). | **3 (built)** |
| `schema [<type>]` | (none) | record contract | Print body sections / vocab / rules from source constants. `--template <type>` emits a `remember` skeleton (a `verify` one for `verification`, a `crumb note …` one for `trap` and `question`). | **built** |
| `note question\|trap\|idea` | user input, git state | a question / trap / idea record | Write-surface for the three kinds with no `remember` type; refreshes the resume packet. At schema 3 a trap is written to `traps/<slug>.md` and a question to `questions/<slug>.md`, through the same validate gate as any record; on a schema-2 store they are still blocks appended to `known-traps.md` / `open-questions.md`. Near-duplicate gate as on `remember` (`--supersedes ID`, `--allow-duplicate`); an exact repeat (same question text, same trap slug) keeps its own exit-1 "reopen it" error. | **built** |
| `show <id>` | one record, trap, question or jot | the full text (read-only) | Print the body behind a one-line mention. Takes any id the tool prints — `dec_`/`att_`/`ver_`/`idea_`/`ses_`/`jot_`, `trap_…`, `q_…` (legacy `q:…` accepted) — and adds a `See also:` line from `generated/related.json`. Exit 1 with `CRUMB-ERROR` on an unknown id. See `show` below. | **built (WM-21)** |
| `jot "<text>"` | user input, git state | a jot under `inbox/` or `private/inbox/` | The short-term tier: one observation, a TTL (`ttl_jot_days`, or the older `jot_ttl_days`; default 14), and **no evidence rule**. `--file PATH` becomes file evidence so the note can be found again; `--local` writes to `private/inbox/`, which is never committed and is where every automatic writer must put things. A jot is searchable and never reaches a `guard` verdict. A near-verbatim repeat of a live jot (similarity ≥ 0.9) is refused with exit 3 unless `--allow-duplicate` (no `--supersedes` on a jot). `--scope branch` makes it apply only while the current branch is checked out (default `project`; jots the hooks write default to `branch`). | **built (WM-03)** |
| `inbox [--all] [--expired]` | `inbox/`, `private/inbox/` | listing (read-only) | Triage queue: live jots newest first, with id, age and source. `--json` rows also carry `scope` and `branch`. | **built (WM-03)** |
| `inbox promote <id> <type>` | one jot | a decision / attempt / verification / trap / question / idea, + the jot | Turn a jot into a durable record **through that type's normal writer**, so the evidence rule, the near-duplicate gate (`--allow-duplicate`, `--supersedes ID`, exit 3) and the validate gate apply exactly as they would to a record written by hand. The promotion preserves meaning (audit F03). The jot's note becomes the body (a decision's `Decision`, an attempt's `Result`, an idea's `Idea`, a verification's, trap's or question's `Notes`); when `--set` or the trap flags supply other text, the note is kept as a `From jot <id>: …` paragraph. The record also takes the jot's scope and confidence, `promoted_from` and `promoted_from_digest`, and its file evidence and tags. `--scope project` widens a branch jot and `--confidence` raises it. The output names the scope and confidence written, and says when a private jot's text is now committed; a private jot carrying a credential-shaped string is refused. The jot is marked `superseded` with `superseded_by` only after the record is written, and never deleted. | **built (WM-03)** |
| `inbox drop <id>` | one jot | status change | Retire a jot as noise (`rejected`). Kept as history; `prune jots` deletes. | **built (WM-03)** |
| `migrate [--dry-run] [--restore [BACKUP]]` | `manifest.yml`, the store | store format + `manifest.yml` | Bring the store's on-disk format up to this build's `schema_version`. Steps are ordered and idempotent, the manifest is written after each one (so a failure halts at the last completed version), and the whole store is copied to `private/migrations/<timestamp>/` first, with `backup-manifest.json`, and verified before any step (audit WP21). `--dry-run` also reports the backup size and the legacy values migration leaves for a person. An interrupted migration (`private/migrations/in-progress.json`) resumes on the next run against its original backup. `--restore` puts the committed store back as a verified backup holds it (default: the interrupted migration's, else the newest), checks the result, and is the one write allowed on a store this build cannot otherwise write; with `--dry-run` it lists the files that would change. See [`compatibility.md`](compatibility.md). A store containing a symbolic link or junction is refused before anything is copied, and the backup never follows one (audit WP13). `validate` fails with `run \`crumb migrate\`` on an older store and `upgrade crumb-kit` on a newer one. See `migrate` below for the steps. | **built (WM-01)** |
| `review <id> [--reviewer NAME]` | the record | `review_status: reviewed`, `reviewed_by`, `reviewed_at`, `reviewed_hash` | Stamp a decision, attempt, verification or trap as reviewed by a person (audit WP14). The stamp covers the record's claim: an edit makes it stale. The reviewer defaults to git's `user.email`, else the OS user. Under the team profile it is refused inside an agent session (friction, not enforcement: see `security.md` §4.2). | **built (WP14)** |
| `policy [show \| set solo\|team [--mcp-mode write\|propose\|read-only]]` | `manifest.yml` | `review_profile`, `mcp_mode`, `requires` | Show or set the store's review policy (`security.md` §4). `team` makes agent-written guidance a proposal, keeps high-impact MCP status changes for a person, requires a valid review for `promote`, and declares `requires: review-profiles`. Setting it is refused inside an agent session. | **built (WP14)** |
| `usage [--never \| --sessions \| --decay [DAYS]] [--top N]` | `private/usage.json` | report (read-only) | Which records actually get **shown** — a packet printed or injected, a guard verdict, a hook advisory. Counts are local to the machine and never committed. `--never` lists active records nothing has ever reached; `--sessions` orders by distinct sessions instead of raw count; `--decay` lists old records nothing has surfaced lately, with the `mark-status … stale` command for each (it never runs them). The three are mutually exclusive. See [`usage`](#usage-built-wm-02-wm-60). | **built (WM-02, WM-60)** |
| `resume` | current, handoff, records, git state | generated resume packet | Print a bounded resume packet (≤5k tokens) with computed staleness. `--fast` = git snapshot + focus + next action + staleness (print-only). `--task TEXT` scopes `likely_files` to matching records and orders every list section by relevance to the task (print-only). | **4 (built)** |
| `search [<query>]` | decisions, attempts, verifications, ideas, jots, traps, open questions | search output (read-only — `search` writes nothing) | Deterministic keyword/tag/file lookup over the records; the permissive layer `guard` builds on. Keyword and tag matching folds morphological variants — query and record tokens are stemmed by a small deterministic suffix-stripper (plus a tiny curated alias table: auth/config/db/repo, and the store's own `aliases.txt`), so "reconciliation" meets a record that says "reconciler"; `keyword_overlap` in `--json` output therefore contains stems. `--explain` prints the stems the query became. | **5 (built)** |
| `guard "<action>"` | decisions, attempts, traps, questions, unsettled verifications, handoff (**not** ideas) | a verdict + the matches behind it (read-only — `guard` writes nothing) | Warn before a repeated mistake (deterministic ranking). Exits with the verdict-mapped code — see `guard` section. | **5 (built)** |
| `audit` | all memory + adapters | health report | Find stale / unsafe / bloated memory (incl. secret + instruction-like heuristics). Heuristic — does NOT gate `validate`. | **6 (built)** |
| `scan-secrets` | committed memory | secret report | Scan committed memory for secret-like strings; non-zero on a hit. Run before committing memory. | **6 (built)** |
| `mark-status <id> <status>` | one record, **one trap, or one open question** | status + `updated_at` (+ optional `superseded_by`) | Record lifecycle mutation (stale/disputed/superseded/…), validate-gated and reverted on failure; `--superseded-by ID` is the supersede flow. Reindexes on write. A `trap_<slug>` or `q_<slug>` id (legacy `q:<slug>` accepted) resolves too. At schema 3 each is its own file, so its frontmatter `status` is edited like any record's; on a schema-2 store — or for a block somebody typed into a singleton since the last reindex — the block's `- Status:` bullet is edited in place (every other byte preserved). Retiring a trap drops it from the resume packet and the hook pre-filter and stops it driving a `guard` verdict; answering a question drops it from the packet, from `guard`'s open-blocker floor and from the aged-unresolved staleness warning. Both stay findable in `search` under their real status. Questions carry their own vocabulary (`open`/`answered`/`closed`) because the record words do not fit — the id decides which vocabulary applies, and a mismatch is rejected by name. A block with no `- Status:` bullet counts as `active` (trap) / `open` (question). Marking a promoted decision, attempt or trap `superseded`, `stale`, `rejected`, `disputed` or `quarantined` also demotes it (see `promote` and `demote`); the output adds `also demoted: …` and `--json` a `demoted` object. | **built** |
| `prune sessions` | `sessions/` | deletions + reindex | Delete old **machine** session snapshots (placeholder Next Action) beyond the newest `--keep N` (default 20). Human handoffs are never candidates; `--dry-run` lists. The Stop hook creates snapshots eagerly (an interrupted session is a handoff worth keeping) — retention is this separate, explicit act. | **built** |
| `rollup sessions --before YYYY-MM-DD` | `sessions/` | one session record, deletions + reindex | Fold the machine snapshots created before the date (at least two) into one session record that supersedes them, then delete them. Human/agent sessions are never touched; `--dry-run` lists. See `rollup sessions` below. | **built (WM-35)** |
| `prune jots` | `inbox/`, `private/inbox/` | deletions + reindex | Delete jots that are expired or retired **and** older than 30 days. An active, unexpired jot is never deleted however old the store is: it is still waiting for somebody to promote or drop it. `--dry-run` lists. | **built (WM-03)** |
| `prune handoffs` | `handoffs/`, local and `origin` branches | deletions + reindex | Delete branch handoffs whose branch exists neither locally nor on `origin` **and** whose `_Last updated_` is at least 30 days old. `--dry-run` lists. See [Branch handoffs](#branch-handoffs-built-wm-50). | **built (WM-50)** |
| `expired` | all records, both inboxes | listing (read-only) | Active records past their `expires_at`, oldest expiry first, machine-local jots included. See `expired` below. | **built (WM-30)** |
| `questions [--aging]` | open questions | listing (read-only) | Open questions with their age, oldest first; `--aging` keeps those open longer than `ttl_question_days` (default 45). | **built (WM-30)** |
| `consolidate [--type T]` | live records | listing (read-only) | Clusters of near-duplicate live records (connected components of the near-duplicate pairs). | **built (WM-33)** |
| `consolidate --merge ID ID… --title "…"` | the named records | one merged record + status changes + reindex | Write one decision / attempt / verification / idea from the sources and mark every source `superseded`. See `consolidate` below. | **built (WM-33)** |
| `promote <id> [--to CLAUDE.md\|AGENTS.md] [--rule "…"]` | one decision, attempt or trap | one rule line in the instruction file's promoted-rules block + `promoted_to`/`promoted_at` on the record + reindex | Make an active record a standing rule in the long-term tier. Never creates the instruction file. See `promote` and `demote` below. | **built (WM-40)** |
| `demote <id> [--reason "…"]` | `CLAUDE.md`, `AGENTS.md`, the record | the rule line removed + promotion fields cleared + reindex | Take a promoted rule back out; the record is otherwise unchanged. | **built (WM-41)** |
| `doctor` | adapters, `.mcp.json`, hooks, packet, `index/search.sqlite` (`--hook-log`: `private/hook-log.jsonl`) | integration-health report | Is memory wired up? Exit 1 if a store exists but no integration is active. A `search_index` row reports the search index as fresh / stale / unreadable / unavailable (no `sqlite3` module) / not built (fine below the 200-record threshold, flagged above it); none of these changes the exit code. An `operations` row fails while a multi-record operation is unfinished (`crumb recover`), and a `projections` row fails when the last projection rebuild raised (`crumb reindex`); neither changes the exit code. A `promoted_rules` row (`CLAUDE.md: 3 rule(s), 612 chars`), present only when a promoted-rules block has rules, says what the long-term tier costs every session; it does not change the exit code either. `--hook-log` instead summarises `private/hook-log.jsonl` per hook (exit 0; 2 with no store) — see [Hook log](#hook-log-built-wm-62). | **built** |
| `mcp serve\|register\|doctor` | `.mcp.json` | running server / registration / health | Run the MCP server, merge its `.mcp.json` entry, or report MCP wiring (`[mcp]` extra + registration). | **built** |
| `hook session\|guard\|capture\|prompt\|compact\|subagent` | hook stdin payload | hook JSON on stdout (+ mined jots, one `private/hook-log.jsonl` line) | Claude Code hook translators (`init --with-hooks` installs them, as a `sh` resolver that falls back through `./.venv` and `python -m breadcrumbs` and reports memory inactive if none resolve; a candidate that is found but fails — say an older crumb-kit on PATH that predates the event — is skipped like a missing one, and the launcher itself always exits 0, because Claude Code reads exit 2 from `UserPromptSubmit`/`PreToolUse` as "block"). An event this version does not know (installed by a newer `init`) prints `{}` and exits 0 rather than a usage error. Installed entries are identified by a `breadcrumbsHook` key, not by command text, so a custom launcher stays visible to `doctor` and `--remove-integrations`. Removal keys on that marker alone: an unmarked entry that merely looks like a crumb hook is reported and left in place, never deleted (adopt it with `init --with-hooks` to make it removable). Re-running `init --with-hooks` also brings an entry **we own** up to the current matcher, which is how an existing install picked up `Task\|Agent`, and then `PowerShell\|NotebookEdit` (audit WP17), on the guard. The event is validated before stdin is read, so a bare `crumb hook` reports usage (exit 2) instead of blocking on a terminal. **Every event exits 0 and prints JSON**, whatever the payload. See the per-event table below. | **built** |

### Hook events

| breadcrumbs event | Claude Code event | Matcher | Does |
|---|---|---|---|
| `session` | `SessionStart` | — | Emits the resume packet as `additionalContext`. With `source: compact` it prepends what was in flight before the compaction: the latest task (the last prompt that was not an acknowledgement or a slash command, whether or not memory matched it; audit WP12), the records memory matched for *that* task, or "matched nothing", and the mined candidates waiting in the inbox. It builds the packet with that task as its task, so the sections are ordered by relevance to it (see `resume --task`). When the task's text was not kept (`retain_prompt_text: false`, or it carried a credential) it says so and orders by recency. |
| `guard` | `PreToolUse` | `Bash\|PowerShell\|Edit\|Write\|MultiEdit\|NotebookEdit\|Task\|Agent` (from `adapters.claude.GUARDED_TOOLS`, audit WP17) | Cost-aware guard verdict. A shell command (`Bash`, `PowerShell`) is scored as typed; an edit (`Edit`, `Write`, `MultiEdit`, `NotebookEdit`) on its path and a snippet of the new content (a notebook cell deletion as `delete a cell in <path>`). A tool the adapter does not know yields no action. A subagent launch (`Task`/`Agent`) is scored on its launch prompt and **capped at `READ_FIRST`**: the launch is not itself irreversible, and the subagent's own calls hit this same hook. |
| `capture` | `Stop` | — | Mines the transcript (always, as a side effect), then snapshots a session record or holds the stop once for the extraction turn. The extraction instruction includes one line saying a write refused with exit 3 is a near-duplicate, answered with `--supersedes <id>` or `--allow-duplicate`. |
| `prompt` | `UserPromptSubmit` | — | Injects up to 5 records relevant to this prompt (≤800 approx tokens), deduped per session, looked up for **any prompt that is not an acknowledgement** (audit WP10: a vocabulary such as "ok", "yes please", "go on", "thanks" or emoji alone, not a length — `npm test` and `quasar` are looked up) with **no record-count cutoff** (it used to return nothing above 500 records), with a footer pointing at `crumb show <id>` (or `memory://records/{id}`) for the full text. Injects **current records only**: superseded, rejected, stale, disputed and quarantined records, answered and closed questions, records past their `expires_at`, and branch-scoped records written on another branch stay out. A verification stays in while its own lifecycle status is `active`, whatever its outcome. Captures a correction to `private/inbox/`. Records the prompt as the session's latest task **before** the lookup (audit WP12), and the lookup's selected and emitted ids apart from it; acknowledgements and slash commands leave the task alone. The dedupe key and the usage count are the ids left after budget trimming. **Never blocks** — that would erase the prompt. |
| `compact` | `PreCompact` | — | Mines the transcript and writes a marker for the next `SessionStart`. Emits nothing: this event's stdout never reaches the model. |
| `subagent` | `SubagentStop` | — | Mines the finished subagent's transcript, tagged `subagent` and `agent:<type>`. Does not hold the subagent. |

**How the prompt hook looks up** (audit WP10, `breadcrumbs/retrieval.py`).

- **Acknowledgements.** A prompt made only of acknowledgement words (at most
  four), or only of punctuation and emoji, is not looked up. Every other
  prompt is, however short. Before, anything under 12 characters was skipped.
- **No pre-count.** It uses the search index when that is current. Otherwise
  it scans the store in full, up to `PROMPT_FULL_SCAN_MAX` (2,000) records.
  Before, it loaded every record to count them and returned nothing above 500,
  retired ones included.
- **Past that bound it says so.** With no usable index, it injects a one-line
  notice once per session ("memory was not searched for this prompt — … Run
  `crumb reindex`"), rather than staying silent as if nothing were relevant.
- **Current records only, chosen before the five-match cap**, so history never
  takes a slot.
- **The hook log records how it looked:** `retrieval` is `indexed`,
  `full_scan`, `skipped` or `acknowledgment`.
- **Whether the store has anything** comes from the verified generation
  manifest's record count, or a file count. It used to be the guard
  pre-filter file's existence.

**What the miner writes.** Four deterministic rules over the transcript — a
command that failed, then passed after an edit (`attempt`), a test command that
passed (`verification`), a file edited four or more times (`trap`), and a user
message that opens like a correction.

Each tool call is classified before any rule runs:
- **`success`** — the result arrived, was not flagged as an error, and printed
  no failure.
- **`failure`** — the harness flagged the result (Claude Code does this for a
  non-zero exit), or a test, lint or build command prints an unambiguous
  failure anywhere in its output. A zero count such as `0 failed` or
  `errors: 0` is not a failure. The output is read because a pipeline such as
  `pytest | tail` exits with `tail`'s status.
- **`interrupted`** — the user or harness stopped the call.
- **`not_run`** — the call was refused before it ran: a `<tool_use_error>`, or
  a rejected tool use.
- **`unknown`** — no result is in the transcript, or an unflagged result from
  any other command reads like a failure. A `grep` that found the word
  "error:" has not failed, and `python x.py | tail` printing a traceback has
  not passed.

Only `success` is worded as "passed", and only `failure` opens an attempt. An
edit counts only when it succeeded. The attempt names the sequence ("failed,
then passed after N file(s) changed"), not a cause. The 400-character excerpt
in a candidate is cut after classification, around the failure when it comes
late. Candidates become jots in `private/inbox/`, never the committed store,
after a secret scan that drops rather than masks.

**Mining is incremental and durable** (audit WP09). Each session has its state
in `private/miner/<session>.json`, written under the store lock.

- **A byte cursor.** Each firing reads only the complete lines past the cursor,
  at most 8 MB. Whatever is beyond waits for the next firing and is reported
  (`unread_bytes`). Before WP09 the cursor counted entries of a moving 8 MB
  tail: once a transcript outgrew it, nothing new was ever mined.
  - A trailing partial line is left until it is finished.
  - A single line longer than a whole read is skipped once it ends, and
    counted (`oversize_lines`).
  - The file is recognised by digests of its first bytes and of the bytes just
    before the cursor. A transcript that was truncated, replaced or rewritten
    is read again from the start (`reset`); what was already written is not
    written twice.
- **Calls carry over.** A Bash or edit call still waiting for its result, and
  the 200 most recent resolved ones, are kept between firings. A result that
  arrives later joins its call, and a failure, edits and a pass in different
  firings still make one attempt. A carried command or output that holds a
  credential is blanked before it is saved.
- **Nothing is dropped silently.**
  - Candidates go to a backlog, and the cursor and backlog are saved, before
    any jot is written.
  - At most 10 jots are written per firing. The rest wait in the backlog
    (at most 50; beyond that, new ones are dropped and counted).
  - A candidate leaves the backlog only once its jot is written, refused (a
    duplicate, a validation failure, a secret: counted), or dropped after five
    failed writes (counted).
  - What a rule's own cap holds back is counted too (`policy_capped`).
  - The hook log and `crumb doctor`'s `miner` row show the backlog, the unread
    bytes, the capped and the dropped.
- **Nothing is written twice.** A candidate's fingerprint is stable (the
  command, the file, the failing call, the user entry), and the transcript
  events behind every acknowledged candidate are remembered across sessions
  in `private/miner/acked.json`. So none of these writes a jot twice:
  - a crash between a jot and the state write;
  - a replayed transcript;
  - a forked session that copies its parent's history.

  `private/miner-cursor.json` from older versions is no longer read.

**The writing events share the store.** `capture`, `compact` and `subagent`
run under the store's write lock (see
[Store write lock](#store-write-lock-built-wm-51)). If another writer holds it
for more than 0.5 seconds, the event prints `{}`, exits 0 and does nothing —
that firing's snapshot or mined candidates are skipped rather than the host
being blocked. `prompt` takes the lock only around its correction jot, with
the same 0.5-second wait; on contention the correction is skipped and the
records are still injected. `session` and `guard` never take the lock.

**Every firing is logged.** Each event appends one line to
`private/hook-log.jsonl`: the event, the time, how long it took and what the
host received (`silent`, `context`, `ask`, `block`, or `locked` when a writing
event skipped on the lock). No prompt, command, path or transcript text is
logged. The hook's output reaches the host unchanged. `crumb doctor --hook-log`
summarises the file — see [Hook log](#hook-log-built-wm-62).

### Integration flags on `init`

```text
init --with-adapter[=CLAUDE.md,…] / --no-adapter   # signpost block in detected guidance files
init --with-mcp / --no-mcp                          # merge .mcp.json entry
init --with-hooks[=session,guard,capture,prompt,compact,subagent] / --no-hooks
init --print-integrations                           # dry run
init --remove-integrations                          # reverse everything
```

On a TTY with none specified, `init` asks once per integration; non-interactive +
unspecified writes nothing (plus a one-line nudge). Every edit is fenced and
reversible.

`--remove-integrations` removes the signpost block only. The promoted-rules
block that `crumb promote` writes into the same files (see `promote` and
`demote`) is left in place: those rules are the project's instructions now, and
`crumb demote` is how one comes out.

Both lists are validated **before any filesystem mutation** — `--with-hooks` against
the six events (`session|guard|capture|prompt|compact|subagent`; bare
`--with-hooks` installs all of them), `--with-adapter` against the known guidance filenames —
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
  `schema_version` to this build's `SCHEMA_VERSION` (currently `4`). The tree
  includes `handoffs/` (with a `.gitkeep`), where branch handoffs go.
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

- Assembles the §12 packet from `current.md`, the handoff, active `decisions/`,
  active `attempts/`, the traps and open questions (`traps/` and `questions/` at
  schema 3, the `known-traps.md` / `open-questions.md` blocks before), and live
  git state.
- **The handoff is this branch's (WM-50).** At schema 4, on a branch other than
  the default branch, the packet reads `handoffs/<branch-slug>.md` when it
  exists and `handoff.md` otherwise, and the Project line ends with which one:
  `· handoff: handoffs/<slug>.md`, `· handoff: handoff.md`, or `· handoff:
  handoff.md (no branch handoff)` on a feature branch that has not captured yet.
  `--json` carries the same label as `project.handoff`. The handoff age,
  commit-distance and branch-mismatch warnings are computed from the file that
  was read. See [Branch handoffs](#branch-handoffs-built-wm-50).
- **`--task` orders by relevance, and hides nothing.** With a task, one
  `search` over the corpus (ideas excluded) scores every record against it, and
  each list section — active decisions, failed attempts, verifications, known
  traps, open questions — is reordered: the newest `RECENCY_FLOOR` (3) entries
  keep their place first, then the entries the task scores against, best first,
  then the rest in recency order. Caps and the token budget apply afterwards, so
  what relevance changes is which entries survive a trim. The packet carries
  `ordering: "relevance"` (`"recency"` otherwise, including a task that matched
  nothing), and the rendered packet says so under the Project line:
  `_(sections ordered by relevance to the Requested Task above; the 3 newest in
  each stay first)_`. The task itself is printed once, under *Requested Task*.
  `--task` also scopes `likely_files` to the matching records, labelling an empty
  result `starting cold`.
- **Bounding: the view you receive is within its budget** (audit WP08). The
  budget is measured on the final text of the view, including headings,
  warnings, the protected sections and the envelope, not on the lists alone.
  Raw transcripts are never included.

  | View | Measured on | Default budget | Smallest |
  |---|---|---|---|
  | `markdown` (`resume`, the committed packet, the `SessionStart` hook, `memory://resume-packet`) | the rendered Markdown | 5,000 | 500 |
  | `markdown-fast` (`resume --fast`) | the rendered Markdown | 1,500 | 400 |
  | `json` (`resume --json`, MCP `memory_build_resume_packet`) | the exact JSON document printed or returned, envelope included | 5,000 | 700 |
  | `json-fast` (`resume --fast --json`) | the same | 1,500 | 700 |

  - **The unit is named.** Budgets are in `approx_tokens`, estimator
    `approx-tokens/2`: ASCII chars / 4, rounded up, plus one per non-ASCII
    character. It is a heuristic, not any model's tokenizer, and the packet says
    so. For ASCII text it equals the old chars/4. Before WP08, a CJK or emoji
    character counted a quarter.
  - **`--budget TOKENS`** bounds the printed view instead; it never changes the
    committed packet. A value below the view's smallest budget exits 2. A
    library caller asking for less gets the smallest, with
    `budget.requested` saying what was asked.
  - **How a view is fitted:**
    1. Every list entry and warning is capped at 300 characters, and Current
       Focus and Next Action at 2,000 (Requested Task at 500). A longer field
       becomes a marked excerpt with a pointer to the whole:
       `… [excerpt: 2000 of 31499 chars; full text: handoff.md → Next Action]`.
       Entries point at `crumb show <id>`.
    2. The per-section caps apply.
    3. The lists are trimmed in `TRIM_ORDER` (least load-bearing first, the
       commits since the handoff and then the warnings last), each with its
       `… N more omitted` note.
    4. If the view is still over, Current Focus, Next Action, Requested Task
       and the project names shrink (1,000, 500, 250, 120 characters), down to
       a bare pointer: `[omitted: 45000 chars; full text: current.md → Current Focus]`.

    The canonical files are never shortened.
  - **The packet identifies itself.** The Markdown carries a second header line,
    `<!-- view: markdown | budget: <used>/<limit> approx_tokens (approx-tokens/2: …) | rules: portable -->`.
    `--json` carries `budget: {view, unit, estimator, estimator_rule, limit,
    used, within, requested?}` and `excerpted` (per section, a count; per
    protected field, `{shown_chars, total_chars, source}`). `approx_tokens` is
    the emitted view's size, equal to `budget.used`. Before WP08 it was always
    the Markdown's.
  - Before WP08, a long Current Focus or Next Action was never trimmed: a
    28,500-character focus produced a packet of 7,333 estimated tokens
    under a "5,000-token" ceiling.
- **Computed staleness** (not just authored): handoff **age + commit-distance**,
  **aged-unresolved** questions/decisions (> `--stale-days`), **branch mismatch**
  (incl. detached HEAD), and **expired**/**low-confidence** records.
- **Expired records leave the lists (WM-30).** A decision, attempt or
  verification past its `expires_at` keeps `status: active` and stays on disk
  and in `search`, but is dropped from the packet's list sections (the "expired
  on …" staleness line still names an expired decision or attempt). `crumb
  expired` lists them.
- **Promoted records stay, as their rules, unless the reader has loaded them**
  (WM-40, audit WP08). A decision, attempt or trap promoted to `CLAUDE.md` /
  `AGENTS.md` is a standing rule. The packet does not know that its reader
  loads that file: it may be another harness, a read-only clone, or the file
  may have lost the rule.
  - **Portable packets keep the record** and show the rule in force. These are
    `resume` in every form, the committed packet, and the MCP packet and
    resource.
    - Markdown: `` - `<id>` — standing rule in CLAUDE.md: <rule> ``.
    - If the file or the bullet is gone: `standing rule (promoted to CLAUDE.md,
      not found there):`, with the rule rendered from the record.
    - `--json` entries gain `promoted_to`, `rule` and `rule_in_file`. A trap
      entry reads `<trap id>: standing rule in CLAUDE.md: <rule>`.
    - The rule in force is the bullet in the file, even one edited by hand,
      because that is what the file's readers have.
  - **Only the `SessionStart` hook leaves any out.** It serves Claude Code,
    which loads the project's `CLAUDE.md`. It leaves out exactly the promoted
    records whose bullet is in that file at session start (a rule promoted to
    `AGENTS.md` stays). Each such section ends with `_(N standing rule(s) left
    out — already loaded from CLAUDE.md this session, …)_`.
  - `packet.promoted` counts what was left out
    (`{active_decisions, failed_attempts, known_traps}`, non-zero only), so it
    is `{}` in every portable packet. `packet.rules` is `{mode: "portable"}` or
    `{mode: "elided-when-loaded", loaded_from, elided}`.
  - Before WP08, every packet left promoted records out on the strength of
    `promoted_to` alone. A missing `CLAUDE.md` then hid a live decision from
    everyone.
  - The missing-evidence warning below still checks promoted decisions and
    attempts.
- **Branch-scoped records from another branch leave the lists (WM-52).** A
  decision, attempt, verification or committed jot with `scope: branch` whose
  `branch` is not the current branch is left out of *Active Decisions*,
  *Failed Attempts To Avoid*, *Verifications* and the *Inbox*. See
  [Branch scope](#branch-scope-built-wm-52).
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
- **Waits at most 0.5 seconds for the write lock** (audit WP05). A session must
  not fail to start because another session is capturing. If the lock is busy,
  `resume` prints the packet it built but publishes nothing (see
  [Store write lock](#store-write-lock-built-wm-51)).
- **The stamp is the snapshot the packet was built from** (audit WP07). If the
  store kept changing across three builds, the packet is stamped
  `inputs_hash: unstable` and says so in its warnings (see
  [Coherent projections](#coherent-projections-built-audit-wp07)).
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
   with `inputs_hash`, so `validate` and `audit` detect it going stale. Only
   pairs that share a file, a tag stem or a non-ubiquitous stem are scored
   (the rest score 0), so there is no corpus cutoff (it used to be 2000 items,
   audit WP15). Past `RELATED_PAIR_BUDGET` (3,000,000) candidate pairs, the
   most widely shared features stop generating pairs and the file says so in
   `degraded` (`reason`, `dropped_features`, `largest_dropped_posting`).
   `skipped` is always `null`.
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

All of these are one **generation**, built from one snapshot of the store and
published together, with the manifest `index/generation.json` written last (see
[Coherent projections](#coherent-projections-built-audit-wp07)). The packet,
pre-filter, related map and conflict list all carry that snapshot's
`inputs_hash`.

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
| 4 | Create `handoffs/` (with a `.gitkeep`) for one handoff per branch. |

**Step 3** writes every `## trap_…` block to `traps/<slug>.md` and every `## Q:`
block to `questions/<slug>.md`, keeping the id (lowercased; a trap slug that is
still not a usable filename is slugified, and the step's output names that
change) and every line of the block: content bullets become sections, bookkeeping bullets
(`Status`, `Last confirmed`, `Promoted to`, `Superseded by`, `Opened`) become frontmatter, and
anything else — free prose, provenance comments — becomes the `Notes` section.
It then rewrites both singletons as indexes. The written files are validated
once; on failure they are removed and the step raises, leaving the store at
schema 2 exactly as it was. Re-running it is a no-op apart from rewriting the
indexes: an existing file is never overwritten.

**Step 4** only creates the directory. `handoff.md` is left as it is and stays
the default branch's handoff; a branch handoff is written the first time a
session captures on another branch.

Readers switch on the manifest's `schema_version`, never on what is on disk, so
a schema-2 store keeps reading and writing blocks until it is migrated, and a
schema-3 store keeps one `handoff.md` for every branch.

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
  and disposable, stamped with the `inputs_hash` of the snapshot it was built
  from. It is **fresh only when that content hash still matches** (audit WP07).
  - There is no path/size/mtime shortcut: a same-size edit with a restored mtime
    used to leave the index "fresh" and missing the new words.
  - Hashing the store costs about 3.5 ms at 200 records and 17 ms at 1,000.
  - An index from an older format (`index_format` below `2`) is stale.

  A stale, absent or unreadable index — or a Python without `sqlite3` — is
  never used, and search falls back to the full scan.
- **A lookup says how it ran** (audit WP10). `--json` carries
  `lookup: {mode, reason, candidates}` and `--explain` prints it: `indexed`, or
  `full_scan` with the reason the index could not serve (`no search index`,
  `the search index is stale`, `the search index is unreadable`, `the store is
  under 200 indexed records`, …). `crumb search` always completes.
- **Expired records are still found.** A record past its `expires_at` keeps
  its status and is searched like any other; the human line marks it
  (`[active, expired]`, or `[fixed, expired]` for a verification, whose
  bracket shows the outcome) and every `--json` match carries an `expired`
  boolean.
- **Promoted records are marked.** A decision, attempt or trap promoted to the
  instruction file reads `[active, promoted]` on the human line, and every
  `--json` match carries a `promoted` boolean.
- **Branch-scoped records are always found.** A `scope: branch` record written
  on another branch is searched like any other (the human line adds `written on
  another branch (possibly stale)`, as for any record from another branch), and
  every `--json` match carries `scope` (`project` or `branch`).
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
- **A short action can still match on its title.** `guard` does not relax the
  two-keyword floor the way `search` does, so an action with fewer specific
  words than the floor (`npm test`: "test" is a generic word) could never match
  a record on text. Such an action passes the gate for a record whose **title**
  holds every word of the action, generic words included and English function
  words aside: `npm test` matches a trap titled "npm test …", but not every
  record that mentions npm. The match is keyword-only, so it escalates only
  through the score bands. The prompt hook uses the same gate. Found by the
  relevance evals (`evals/`, WM-61).
- **A trap that names the exact command is READ_FIRST** (audit WP10, F10).
  Before, `npm test` against a trap titled "npm test truncates the database"
  matched on the title alone, scored 3 and came out `PROCEED`. The rule is
  narrow:
  - **A trap names a command** with the leading words of its summary (after a
    leading "run"/"running", as in "Running make deploy pushes to prod"), or
    with a backticked span in its hazard text. Each named command records
    which it is: a summary head matches from its start, and a backticked span
    must be named whole (audit WP11). A backticked command in the trap's
    remedy, such as "use `npm run test:unit`", is what to run *instead*, and
    never counts.
  - **The action matches** when their common leading tokens number at least
    two and cover the whole action, or stop at a flag: `npm test` and
    `npm test --watch` match; `npm run test:unit`, `npm install`, `pytest -q`
    and `make` do not.
  - **A match carries the `command` signal**, scores at least
    `GUARD_READ_FIRST_SCORE`, and floors a live trap at `READ_FIRST`, the
    advisory ceiling. The reader is told; the permission flow is untouched.
- **`PROCEED` means "no applicable memory warning found".** It is not an
  authorization and not a safety check of the action. The recommended action
  says so.
- **Staleness on the guard path is risks-only.** Only abnormal states — cold
  handoff (`⚠`), detached HEAD, handoff branch mismatch — ride along with a
  verdict. The routine store facts (fresh handoff age, aged records, low
  confidence, other-branch record lists) are read once per session in
  `resume`/`doctor`/`audit`, not once per edit.
- **An expired record is history.** A match past its `expires_at` is listed
  under `history` (context only), like a superseded one, and never drives the
  verdict.
- **A promoted record is scored at full weight.** Promotion takes a record out
  of the packet's lists only; `guard` matches and scores it like any other
  active record.
- **A branch-scoped record from another branch is history.** A `scope: branch`
  match whose `branch` differs from the current one (the match's
  `branch_mismatch`) is listed under `history` and never drives the verdict. A
  project-scoped record from another branch is still live, de-weighted as
  before.
- **The handoff read is this branch's**, chosen as in `resume` (see
  [Branch handoffs](#branch-handoffs-built-wm-50)); the handoff warnings are
  computed from it.
- `guard` does not take the store's write lock and never waits on a writer.
- **Exit codes are verdict-mapped** so callers can script on the verdict
  without parsing output: `PROCEED` = 0, `READ_FIRST` = 10, `PAUSE` = 15,
  `ASK_HUMAN` = 20 (`>= 15` means a human belongs in the loop); `2` = usage
  error / no store. Deliberately clear of 1, 2, and the shell's 126+ range.
  The hook translator (`crumb hook guard`) always exits 0 — hook protocols
  treat nonzero as a hook failure.
- **`--exit-zero`** (audit WP11) exits 0 whatever the verdict, for a caller that
  cannot take a non-zero status (a CI step under `set -e`). It is opt-in and
  changes the status only: the verdict is still printed and in `--json`, and
  the default mapping is unchanged.

The `PreToolUse` hook path adds three behaviors of its own:

- **The pre-filter is trusted only when verified** (audit WP07). The hook reads
  `generated/guard-prefilter.json` to decide whether a routine-looking call
  needs the full guard at all. It relies on that file only when the current
  generation manifest vouches for it (see
  [Coherent projections](#coherent-projections-built-audit-wp07)).
  - A missing, corrupt or replaced pre-filter, one from a publication that was
    not stable, or one older than the records now on disk is **not** evidence
    that no hazard exists. The hook runs the full guard against the records
    instead, and the hook log notes `prefilter: "unverified"`.
  - That costs time, not coverage: in the recorded run, 39 ms instead of
    2.6 ms per call at 200 records, and 92 ms instead of 8.2 ms at 1,000.
  - A verified pre-filter that finds nothing keeps the call silent as before
    (`skipped: "prefilter"`).
  - **It never filters out a named command** (audit WP10). The pre-filter lists
    the commands live traps name, and an action that names one goes to the full
    guard, however routine it looks.
  - **It is a strict superset of what full guard surfaces** (audit WP11, format
    `3`). Before, it covered traps and do-not-retry attempts only, so an edit to
    a file only a *decision* declares could draw `READ_FIRST` from
    `crumb guard` and silence from the hook. On the eval stores this happened
    to 27 of 193 warnings.
    - It now holds, from every record that could drive a verdict (live
      decisions, attempts, verifications, traps, open questions), everything
      `_score_item` can match on: specific stems (`tokens`), title stems
      (`titles`), tag stems (`tags`), declared and mentioned files (`paths`)
      and named commands (`commands`).
    - An action passes when it shares two stems with `tokens`, is a single
      stem found in `titles`, shares a tag or a path, or names a command.
    - It may admit an action full guard then passes over, which costs one
      full guard run. It cannot drop one full guard would warn about.
      `tests/test_guard_delivery.py` checks this against full guard on every
      eval suite.
    - A pre-filter of another format is treated as unverified.
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
  handoff (age + commit-distance, measured on the handoff this branch reads —
  see `resume`; the finding's path is that file), branch mismatch (incl. detached HEAD),
  aged-unresolved questions/decisions, expired + low-confidence records,
  **instruction-like text** (override phrasing such as "ignore the tests" — flagged,
  never executed: matched memory is data, not command), **generated-packet drift**
  (a committed projection — `generated/*.md`, `related.json` or `conflicts.json` — whose stamped
  `inputs_hash` no longer matches the canonical inputs → regenerate), bloat
  (adapter files duplicating memory, judged with the promoted-rules block
  removed, since its rules mirror records on purpose; over-budget packet), the validate-failing
  health conditions re-surfaced for one health view (missing evidence, invalid
  status, private-path violation, id/frontmatter disagreement),
  **`unadopted-block`** (at schema 3, a hand-written trap/question block in a
  singleton whose id already has a file with different content — merge it into
  the file by hand, then delete the block), **`aliases`** (a malformed line in
  `aliases.txt`, which is ignored), and four lifecycle checks over live
  (active, unexpired) records:
  - **`evidence-missing-file`** — a decision, attempt or verification cites
    `file`/`path` evidence that is neither on disk nor in HEAD (same rules as
    the packet warning in `resume`; up to 20 findings);
  - **`possible-contradiction`** — a pair from the two `conflicts.json` rules
    (see `reindex`; up to 10);
  - **`near-duplicates`** — two live records of the same type at or above the
    near-duplicate threshold (0.6; 0.9 for jots), with the commands to
    supersede one or merge them (up to 10 pairs). A pair already reported as a
    possible contradiction is not reported again here. Every type is swept at
    any size (before audit WP15, a type with more than 2000 live items was
    skipped without a word);
  - **`related-degraded`** — the committed `generated/related.json` carries a
    `degraded` report: the pair budget stopped its most widely shared
    features, so "see also" is incomplete (see `reindex`).

  and two checks on the promoted-rules block in `CLAUDE.md`/`AGENTS.md` (see
  `promote` and `demote`):
  - **`promoted-bloat`** — the block (markers included) is over
    `ADAPTER_BLOAT_CHARS` (4000). Measured on its own, separately from the
    signpost block;
  - **`demote-candidate`** — a rule that names no `source:` record, whose
    source record no longer exists, or whose source is no longer `active`. The
    message names `crumb demote <id>`; a rule with no source has no id to
    demote and is removed by hand.
- **info** — context note (e.g. `sessions/` growth → the note names `crumb
  rollup sessions --before YYYY-MM-DD`, and `crumb prune sessions`), and:
  - **`promoted-drift`** — a promoted rule differs from what `crumb promote`
    would write for its record now: the line was edited by hand, or the record
    was retitled or its rationale changed. A stored `--rule` override counts as
    the expected text. The hint is `crumb promote <id>`, which re-renders it;
  - **`promote-candidate`** — an active decision or attempt, not `confidence:
    low` and not promoted, at least 60 days old and surfaced in at least 5
    distinct sessions according to `private/usage.json`. The message names
    `crumb promote <id>`. The session count is machine-local, so two clones can
    disagree;
  - **`decay-candidate`** — what `crumb usage --decay` lists with its default
    window of 180 days (see [`usage`](#usage-built-wm-02-wm-60)): an active
    decision, attempt or trap at least 180 days old that nothing has surfaced
    in 180 days. The message carries the `crumb mark-status <id> stale
    --reason "not surfaced in 180 days"` command; nothing is changed. Up to 10
    (`AUDIT_DECAY_MAX`), and none until this machine has 180 days of usage
    history;
  - **`never-surfaced`** — an active record at least 90 days old with no entry
    in `private/usage.json` (up to 10). A record already reported as a
    `decay-candidate` is not reported again here. Both checks run only when
    `usage.json` holds some history.

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
that nearly repeats a **live** record of the same type — active, unexpired and
not scoped to another branch (see [Branch scope](#branch-scope-built-wm-52));
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
- `inbox promote` is gated like `remember` (audit F03). Other internal writers
  (migrations, the transcript miner) are not gated. The MCP writers are: see [`mcp-spec.md`](mcp-spec.md).

Records that predate the gate are found by `audit` (`near-duplicates`) and
grouped by `consolidate`.

---

## `verify --recheck` (built, WM-31; replay contract: audit WP04)

```bash
crumb verify "login rejects expired tokens" --status open \
  --assert "pytest tests/test_auth.py::test_expired_token"   # declare an assertion
crumb verify --recheck ver_20260801_login-bug                 # asks y/N per record
crumb verify --recheck ver_… --recheck ver_… --yes            # runs without asking
crumb verify --recheck ver_… --bind-commands --yes            # treat its commands as assertions
crumb verify --all --yes                                      # every active verification with a check
```

Reruns a verification's checks. Only an **assertion** can change the claim.
Each record's commands are printed first, marked `[assert]` or `[diagnostic]`.
Without `--yes`, a terminal is asked `run these? [y/N]` per record; with no
terminal the command exits 2 having run nothing. There is no MCP equivalent, on
purpose: running commands taken from the store is a human-confirmed, CLI-only
act.

**What runs, and what it may claim** (`breadcrumbs/checks.py`):

- **Assertion.** An evidence item `{type: assert, ref: <command>, spec: "1"}`
  declares that the command exits 0 exactly when the subject is fixed — a
  regression test for it. `verify --assert CMD` (repeatable) writes one, and
  MCP `memory_verify` can pass the same item in `evidence`. Only assertions
  settle a claim.
- **Diagnostic.** Legacy `command` evidence is run and reported, but it never
  changes the claim: a command that exits 0 has not shown that the subject is
  fixed. `--bind-commands` is the operator saying that, for this record, the
  command *is* the assertion; the new record then stores it as one.
- **Pointer.** `test` evidence is a test-file path and is never executed.

**Settlement.** When every assertion was evaluated:
- all passed → `fixed`;
- one failed on a claim recorded as `fixed` or `not_applicable` → `regressed`;
- otherwise → `open`.

The result is a new verification that supersedes the old one and keeps its
subject, scope, branch, confidence, tags and evidence (`method: runtime`). A
`Notes` section lists each run's status, exit code and last 3 non-empty output
lines; a line that looks like a secret is replaced by
`[line dropped: looked like a secret]`.

If no assertion is declared, or one could not be evaluated, **nothing is
written**, the old record stands unchanged, and the result carries
`settled: false` and a `reason`. An assertion is not evaluated when the shell
could not find or run the command (exit 126/127, or 9009 on Windows), it timed
out, it was killed by a signal, or its `spec` is not `1`.

**Where it runs.** A branch-scoped verification recorded on another branch is
not rechecked from this checkout: the run would describe this branch. Check that
branch out first.

**How it runs.** Each command runs through the platform's shell in the project
root, as typed; POSIX parsing is never applied to a Windows string. Each run
gets its own process group and a 300-second timeout, and output is kept in a
rolling 64 KiB window while it runs. The whole group is terminated on timeout,
on Ctrl-C, and after the command returns, so a background child cannot outlive
its check. On Windows, `taskkill /T` is used; a process that detaches itself
from the group is out of reach.

**Other behavior:**
- The near-duplicate gate does not apply.
- `--all` takes every active verification with an assertion or a command.
- A named id that is not a verification, has nothing to run, or is scoped to
  another branch is reported with a `CRUMB-WARN` line and skipped.

**Exit codes:** `0` means every record was processed (settled or not; a
declined record counts as skipped); `1` means nothing to recheck, or a new
record could not be written; `2` means no store, or no terminal without
`--yes`.

**JSON output.** `--json` returns `{rechecked: [{ok, id, settled, new_id,
outcome, reason, runs}], summary: {rechecked, settled, not_settled, fixed, open,
regressed, skipped}}`. Each run is `{command, kind, status, exit_code, signal,
timed_out, duration_s, output_bytes, truncated, tail, cwd, platform, detail}`,
where `status` is one of `passed`, `failed`, `unavailable`, `timeout`, `killed`
or `unsupported`.

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

## `promote` and `demote` (built, WM-40 to WM-43)

```bash
crumb promote dec_20260625_repo-local-memory-source-of-truth    # into CLAUDE.md, else AGENTS.md
crumb promote att_… --to AGENTS.md                               # a named file (moves it if promoted elsewhere)
crumb promote trap_gradlew-stop --rule "stop the Gradle daemon by pid, never with --stop"
crumb demote dec_… --reason "no longer a hard rule"
```

The bridge from the store (short- and medium-term memory) to the long-term
tier: the agent's instruction file, which the harness loads whole every
session. `promote` writes one rule line for a record into that file; `demote`
takes it out.

**The promoted-rules block.** Rules go into a second managed block, separate
from the `crumb init` signpost block, appended to the end of the file the first
time and rewritten in place after that:

```markdown
<!-- >>> breadcrumbs promoted rules (managed by `crumb promote`) — edit with crumb promote/demote, not by hand >>> -->
## Project rules promoted from memory
- Use sqlite for the cache. _(why: concurrent writers corrupted the JSON file; source: `dec_20260922_use-sqlite-for-the-cache`)_
<!-- <<< breadcrumbs promoted rules <<< -->
```

One bullet per source id: `- <rule>. _(why: <rationale>; source: \`<id>\`)_`,
or `_(source: \`<id>\`)_` when there is no rationale (or when the rationale only
repeats the rule). The rule's case is left alone — it may start with a command —
and it is clipped to 200 characters and the rationale to 160 (whitespace collapsed,
trailing `.` dropped, `…` marking a cut). The `source:` id is how `demote` and
the audit checks find the line again. See
[`record-schema.md`](record-schema.md) §13.

**`promote <id>`:**

- Takes a decision, attempt or trap id. Any other kind, an unknown id, a record
  that is not `active`, or one at `confidence: low` → exit 2 with the reason.
- **Target:** `--to CLAUDE.md|AGENTS.md`, else the first of `CLAUDE.md`,
  `AGENTS.md` that exists in the project root. Neither exists, or the named one
  does not → exit 2. The file is never created. Other adapter files
  (`.cursorrules`, …) take the signpost only.
- **Default rule text**, rendered from the record:

  | Kind | Rule | Why |
  |---|---|---|
  | decision | its title | the first line of *Rationale*, else of *Decision*, else the title |
  | attempt | `Do not retry: <title> — unless <first line of Do Not Retry Unless>` (the `— unless` part only when that section has text) | the first line of *Why It Failed / Succeeded*, else of *Result* |
  | trap | `<summary>: <Safe approach>` (the summary alone when there is no safe approach) | the trap's *Why* |

  `--rule "…"` replaces the rule text (one line; a newline → exit 2) and is
  stored on the record as `promoted_rule`; later promotions keep it until a new
  `--rule` or `--default-rule` (back to the rendered text). The *why* part is
  always rendered from the record.
- **On the record:** `promoted_to: <file>` and `promoted_at: <iso>` (plus
  `promoted_rule` for an override) in frontmatter; on a schema-2 trap block, a
  `- Promoted to: <file>` bullet. Written through the validate gate; if that
  fails, the line is taken back out of the file (and, on a move, put back in
  the file it came from) and the command exits 1.
  `status` stays `active`: the record is still true, and now also long-term.
- **Idempotent.** Promoting again replaces the bullet with a fresh rendering
  (there is only ever one per id), which is how a `promoted-drift` finding is
  answered; an earlier `--rule` override is kept. Promoting to the other file
  moves the bullet.
- Reindexes. `--json`: `{id, kind, to, rule}`, `rule` being the bullet written.
- Exit codes: `0` promoted, `1` the promotion could not be recorded on the
  record, `2` a refusal above or no store.

**What promotion changes elsewhere.** The resume packet leaves the record out
of its lists and says how many it left out (see `resume`); `guard` still scores
it at full weight; `search` marks it `promoted`; the missing-evidence warning
still checks it. `audit` reports `promoted-bloat`, `demote-candidate`,
`promoted-drift` and `promote-candidate`, and `doctor` a `promoted_rules` row
(see `audit` and the command table).

**`demote <id>`:**

- Removes the bullet for `<id>` from whichever of `CLAUDE.md`/`AGENTS.md` has
  it, and clears `promoted_to`, `promoted_at` and `promoted_rule` (or the
  block's `- Promoted to:` bullet). A block left with no rules is removed,
  markers and heading included. The record is otherwise unchanged.
- Works on an id whose record no longer exists, as long as a bullet names it:
  that is the answer to a `demote-candidate` finding.
- `--reason` is echoed in the output (`reason:` line; `--json`:
  `{id, removed_from, reason}`); it is not written anywhere.
- Exit codes: `0` demoted, `1` the id is a record that is not promoted, `2` an
  unknown id that no bullet names, or no store.

**Retiring a promoted record demotes it.** `set_record_status` to
`superseded`, `stale`, `rejected`, `disputed` or `quarantined` removes the rule
and clears the fields in the same call, whichever route gets there: `crumb
mark-status`, `memory_mark_status`, a writer's `--supersedes`, `consolidate
--merge`. Every route reports it: `mark-status` prints `also demoted: its
promoted rule was removed from <file>`, the writers print `also demoted: <id>`,
and the `--json` / MCP results carry `demoted`. `quarantined` above all — a
record suspected of carrying injected text must not stay in the file every
session loads.

**No MCP tool, on purpose.** An agent writing its own permanent instructions
through a tool call is the persistence step of a prompt injection. A person
runs `crumb promote`, or an agent runs it where a person can see the command.
`memory_mark_status` still auto-demotes.

---

## Branch handoffs (built, WM-50)

```bash
crumb capture session --next "…"   # on feature/parser-rewrite: writes handoffs/feature-parser-rewrite-<6 hex>.md
crumb resume                       # Project line ends: · handoff: handoffs/feature-parser-rewrite-<6 hex>.md
crumb prune handoffs --dry-run     # branch handoffs whose branch is gone, 30+ days old
crumb prune handoffs [--json]
```

At schema 4 the store keeps one handoff per branch, so two sessions on two
branches no longer overwrite each other's Next Action. A schema-3 store keeps a
single `handoff.md` for every branch; readers and the writer decide by the
manifest's `schema_version`.

- **The default branch** is the target of `refs/remotes/origin/HEAD` when the
  clone knows it; otherwise `main` if that local branch exists, else `master`.
  Without git, when none of these exists, or on a detached HEAD, every capture
  writes `handoff.md`, as before.
- **Writing.** `capture session` — and so the Stop hook, which goes through it
  — writes `handoff.md` on the default branch and `handoffs/<branch-slug>.md`
  on any other. The slug is the branch name slugified (lowercased, each run of
  characters outside `[a-z0-9]` becomes `-`) and cut to 60 characters. When
  that is exactly the branch name, it is the file name as is (`feature-x` →
  `handoffs/feature-x.md`); otherwise the first 6 hex digits of the branch
  name's SHA-1 are appended (`feature/parser-rewrite` →
  `handoffs/feature-parser-rewrite-<6 hex>.md`), so branches that slugify alike
  — `feature/parser-rewrite` and `feature-parser-rewrite`, or names differing
  only in case — never share a file. The file has the same `_Last updated_` /
  `_Branch_` / `_Commit_` lines and sections as `handoff.md` (see
  [`record-schema.md`](record-schema.md) §10). The human output names it
  (`handoff: handoffs/<slug>.md (updated)` or `handoff: handoff.md (updated)`),
  and `--json`'s `handoff` is its absolute path.
- **The first write carries over the focus only.** A branch handoff that does
  not exist yet starts from `handoff.md`'s *Current Focus* and nothing else, so
  the focus the branch was cut from survives, while another branch's Next
  Action is never passed off under this branch's fresh date, branch and commit
  lines. `--focus` and `--next` then apply as on any capture.
- **`current.md` stays single.** It is the project's focus, not a branch's;
  a capture on any branch updates it.
- **Reading.** `resume` (and the packet the `SessionStart` hook injects),
  `guard` and `audit` read the current branch's handoff when it exists and
  `handoff.md` otherwise; the packet's Project line and `project.handoff` say
  which (see `resume`), and so does `memory://handoff`. Branch handoffs are
  inputs to `inputs_hash`, like `handoff.md`.

**`prune handoffs`** deletes a branch handoff only when both hold:

- its file name is the handoff name (as above, hash suffix included) of no
  local branch and no `origin/…` remote-tracking branch. These are the local
  refs; nothing is fetched, so a
  branch deleted on the remote still counts until `git fetch --prune` drops its
  tracking ref;
- its `_Last updated_` is at least 30 days old. A file without a parseable
  timestamp is kept. A branch deleted this morning may be recreated this
  afternoon, and its handoff is what that session wants.

Without git nothing is pruned; `handoff.md` is never a candidate. `--dry-run`
lists what would go (`- handoffs/<file> (<age>d)`); `--keep` does not apply.
The projections are rebuilt when anything was deleted. `--json`: `{pruned:
[{path, branch, age_days}], dry_run}` (`items` aliases `pruned`). Exit codes:
`0`, or `2` when no store is present.

---

## Branch scope (built, WM-52)

```bash
crumb jot "the tokenizer test flakes on this branch" --scope branch
crumb verify "parser suite" --status regressed --evidence command "pytest tests/parser" --scope branch
```

`scope: branch` marks a record that describes the state of the branch it was
written on — a verification of work in progress, an observation mined mid-session
— and applies only while that branch is checked out. The branch is the record's
existing `branch` field, derived from git at write time.

- **Where it is set.** `--scope project|branch` on `jot` and `verify`, and the
  `scope` parameter on `memory_jot` / `memory_verify`. `crumb jot` and
  `memory_jot` default to `project`; jots the hooks write (a captured
  correction, mined candidates) default to `branch`. `remember --scope` and
  `memory_record` take the same two values. They took free text before the
  record contract, and a legacy record with another value still counts as
  `project` but fails `validate` (`scope-unsupported`, `record-schema.md` §4).
- **Elsewhere.** A record is *branch-scoped elsewhere* when its `scope` is
  `branch`, it has a recorded branch, the current branch is known, and the two
  differ. Such a record:
  - leaves the resume packet's *Active Decisions*, *Failed Attempts To Avoid*,
    *Verifications* and *Inbox* sections;
  - is listed by `guard` under `history` instead of driving the verdict;
  - is not injected by the `UserPromptSubmit` hook;
  - is not a near-duplicate candidate: a similar record written on this branch
    is not refused because of it, and nobody is told to supersede another
    branch's record.
- **Never elsewhere:** without git, on a detached HEAD, or when the record has
  no recorded branch (or `(no-git)`).
- **Still visible:** the record stays on disk and in `search` (the `--json`
  match carries `scope`), `show`, `crumb inbox` (`--json` rows carry `scope`
  and `branch`) and `expired`. `jot --json` echoes the `scope` written.
- `inbox promote` keeps the jot's scope; `--scope project` widens a branch jot,
  and the output says it did.

---

## Multi-record operations and `recover` (built, audit WP06)

Some changes are several writes. Each is one **operation**: it either happens
completely, or it has not happened at all.

- `remember`, `note`, `verify` and MCP `memory_record` with `--supersedes`: the
  new record and the old one's retirement.
- `inbox promote`: the target, anything it supersedes, and the jot's
  retirement.
- `consolidate --merge`: the merged record and every source's retirement.
- `rollup sessions`: the rollup and the deletion of the snapshots it folds.
- `mark-status` of a promoted record: the retirement and the rule's removal
  from `CLAUDE.md` / `AGENTS.md`.
- `promote` and `demote`: the record and the instruction file.

**How it works** (`breadcrumbs/mutations.py`):

- **Journal first.** Before an operation first writes or deletes a record, a
  singleton or an instruction file, it saves the file's prior bytes (or its
  absence), and a digest of what it is about to write, to
  `private/operations/<id>/`. `generated/`, `index/` and `private/` are derived
  or local and are rebuilt instead. A clean finish removes the journal.
- **A failed step undoes the whole operation.** For example, a retirement the
  writer checked and found refused, or a rule that could not be removed. Every
  touched file is restored, the projections are rebuilt, and the command fails
  with the reason and `nothing was changed` (exit 1; MCP `{ok: false}`). Before
  0.3.x, a failed retirement was ignored: the replacement was written, both
  records stayed live, and the command exited 0.
- **A writer killed midway leaves its journal.** `crumb doctor` reports it (an
  `operations` row), and `resume` warns on stderr.
  - `crumb recover` lists unfinished operations and what rolling each back
    would do to every file (`restore`, `remove`, `unchanged`, or `conflict`).
  - `crumb recover --apply` rolls them back. A file is restored only if it
    still holds its before-image or a state the operation wrote. One changed by
    anybody since is a `conflict`: it is left alone, and the journal stays.
  - A file the operation created and the rollback removes is copied to
    `private/recovered/<id>/` first, so rolling back never erases what was
    written.
  - `--json` returns `{operations: [{id, kind, files: [{path, action}],
    rolled_back?, conflicts?, kept?}], applied}`. Exit 1 while any operation
    remains unfinished.
- **A rewrite checks its revision.** A rewrite of a record (a status change, a
  retitle, a trap confirmation, a promotion's fields) refuses when the file no
  longer holds the text the writer read. The error says the file "changed since
  it was read"; nothing is written, and the other edit survives.
- **A failed projection rebuild is visible.** After a committed write, a
  rebuild that raises leaves `private/projections-pending`. It is reported by
  `doctor` (a `projections` row) and cleared by the next rebuild that works.

Operations run under the store write lock, which is why a journal found while
holding the lock belongs to a writer that stopped.

---

## Coherent projections (built, audit WP07)

The `generated/` files and the search index are derived from the records. Each
one carries `inputs_hash`, the digest `validate` and `audit` compare against the
store to decide whether it is current. WP07 makes that stamp, and the set of
files, trustworthy.

**A stamp describes the snapshot that was actually read**
(`breadcrumbs/snapshots.py`).

- A build hashes the inputs, builds and stamps with that hash, then hashes
  again. The two match only if nothing changed in between, so the stamp names
  exactly what the build read.
- If they differ, the build retries, up to three attempts. A store that keeps
  changing gets the stamp `unstable` instead of a digest:
  - the packet adds a warning saying it is not certified current;
  - `validate` reports a `freshness` failure, because `unstable` never equals a
    digest;
  - `reindex` / `try_reindex_projections` return
    `(False, "the store kept changing during publication; projections stamped unstable")`.

  Before 0.3.x, the hash was taken after the records were read. A record
  written in between was missing from the packet but covered by its stamp, so
  `validate` called the packet current.
- Publication runs under the store lock, so a cooperating writer cannot land
  mid-build. The check covers everything else: a hand edit, a `git checkout`, an
  older crumb-kit, and unlocked readers such as `resume --fast`.

**One publication is one generation** (`breadcrumbs/projections.py`).

- The packet, pre-filter, related map and conflict list are built from one
  snapshot and carry the same stamp. The guard pre-filter is now stamped too.
- The search index is built into a unique temp file (`index/.index.*.tmp`). It
  is moved into place only if the snapshot proved stable, and staged files from
  discarded attempts or a failed publication are removed.
- The previous manifest is removed before the files are replaced. The new
  **`index/generation.json`** is written last, only after every output is in
  place. It records:
  - `inputs_hash` and `stable`;
  - the sha256 of each generated file;
  - a stat fingerprint (paths, sizes, mtimes) of the canonical inputs at that
    moment.
- The manifest is machine-local (under the gitignored `index/`). It describes
  this checkout's publication; a committed copy would churn and be wrong on
  another machine.

**Consumers trust a projection only when the generation vouches for it.**
`projections.verified(name)` returns the file only when:

- the manifest exists and says `stable`;
- the file's sha256 matches its entry;
- the canonical inputs have not moved since (the fingerprint still matches).

The guard hook's pre-filter is the consumer that needs this (see `guard`).
Otherwise, a missing, corrupt, replaced or out-of-date pre-filter reads as
"nothing risky here" (audit F11). The stat fingerprint is a cheap "did anything
move" test for that hot path, not proof of equal content. The strict checks, the
search index's freshness and `validate`, compare content hashes.

**The search index is fresh only by content hash** (audit F12). See `search`.
The index format is `2`; an older index is rebuilt.

---

## Store write lock (built, WM-51)

Parallel sessions in one checkout write the same store: two Stop hooks capture
at once, a prompt hook jots while another session reindexes. Each file write is
already atomic; the lock stops two read-modify-write sequences (a handoff
rewrite, an index rebuild) from interleaving so that one silently undoes the
other.

- **The lock is an operating-system lock** (audit WP05): `flock` on POSIX and
  `msvcrt.locking` on Windows, on `.project-memory/private/.store.lock`
  (gitignored with the rest of `private/`). The kernel holds it, so it is
  released the moment its holder exits, however that happens.
  - There is no heartbeat, no age limit and no "stale lock" rule: a live
    writer is never judged dead because a clock jumped or a process was
    suspended, and a crashed one never wedges the store.
  - The file is permanent and never unlinked. While a writer holds it, the file
    carries the writer's pid, a Unix timestamp and the host, but only for error
    messages.
  - Within one process, an in-process lock per store serialises threads, and
    the lock is re-entrant within a thread.
- **Filesystems.** An OS lock is exact on a local filesystem. If the store's
  filesystem refuses one (some network or sync-managed mounts), a write fails
  with `cannot take a write lock on …; the store must be on a local filesystem
  for concurrent writers to be safe` rather than proceeding uncoordinated.
- **Older versions.** crumb-kit 0.3.0 and earlier used an exclusive-create
  `private/.write-lock` with a heartbeat. While such a file is fresh (touched
  within 60 seconds) and its process alive, this version waits for it too; it
  never removes one. An older version does not see this version's lock, so run
  one version per checkout.
- **`init --force`** keeps both lock files while it replaces everything else in
  the store. An OS lock lives on the file's inode, so replacing the file would
  let a second writer lock a new one while `init` still runs.
- **Publishing projections takes the lock.** The four `generated/` files and
  the search index are each replaced atomically, but not together, so every
  rebuild runs under the lock. A writer already holds it. `resume` waits only
  0.5 seconds; if another writer holds the lock, it still prints the packet it
  built but writes nothing, warns on stderr, and reports
  `publication: {published: false, reason}` in `--json`. The search index is
  built in a temp file of its own, and it is moved into place only as part of a
  stable generation (audit WP07).
- **Which invocations take it** is decided per invocation (`_needs_lock` over
  `LOCKED_COMMANDS` in `breadcrumbs/cli.py`): `init` (when a store exists),
  `remember`, `note`, `jot`, `inbox promote` and `inbox drop`, `verify`,
  `mark-status`, `retitle`, `traps --confirm`, `prune`, `migrate`, `reindex`,
  `capture`, `promote`, `demote`, `consolidate --merge` and `rollup`. Each
  waits up to 2 seconds, then exits 1:

  ```text
  CRUMB-ERROR: crumb jot: store is locked by pid 9502; try again shortly
  ```

  Under `--json` that is `{ok: false, command, error}`. When the holder is
  another thread of the same process, the message says `store is locked by
  another thread of this process; …`. With no store, the command runs without
  the lock and reports the missing store itself (exit 2).
- **Invocations that never wait:** everything else — `resume` (it waits 0.5
  seconds to publish, never to show the packet),
  the `inbox`, `traps` and `consolidate` listings, `search`, `guard`, `show`,
  `validate`, `audit`, `scan-secrets`, `doctor`, `usage`, `expired`,
  `questions`, `schema`, `mcp`.
- **Hooks** skip rather than fail, after a 0.5-second wait: `capture`,
  `compact` and `subagent` per event, `prompt` only for its correction jot (see
  [Hook events](#hook-events)). The MCP writers wait 2 seconds and return
  `{ok: false, error: "store is locked by pid N; …"}` (see
  [`mcp-spec.md`](mcp-spec.md)).
- A lock held by a process that is still running but stuck stays held until
  that process exits or is killed. Deleting the file does not release it.

---

## `usage` (built, WM-02, WM-60)

```bash
crumb usage                  # records with surfacing history, most-surfaced first
crumb usage --sessions       # ...ordered by distinct sessions instead
crumb usage --never          # active records nothing has ever surfaced, oldest first
crumb usage --decay          # old records nothing surfaced in the last 180 days
crumb usage --decay 90       # ...with a 90-day window
crumb usage --top N          # rows to print (default: 25)
```

`--never`, `--sessions` and `--decay` are mutually exclusive (exit 2 on a
combination).

Behavior:

- **What counts.** A record counts when its id is in output a host received:
  a packet printed or injected, a guard verdict, a hook advisory. A reindex
  does not count, or the numbers would measure writes. The counts live in
  `private/usage.json` (machine-local, never committed; see
  [`record-schema.md`](record-schema.md) §1): per record the total, the count
  by source, `last_surfaced_at` and the last 20 session ids.
- **Accounting model (audit WP12).** The stages are distinct, and only the
  last is counted:
  - *retrieved*: records the lookup scored;
  - *selected*: current records under the cap;
  - *emitted*: ids in the printed output, after budget trimming and after
    the per-session dedupe.

  A deduplicated repeat, an output trimmed to nothing, a silent `PROCEED` and a
  failed hook count nothing. The guard hook counts the three matches its reason
  names; `crumb guard` counts every match it prints; a packet counts the ids
  left after its budget. A count says a record was shown, not that it was read
  or that it helped. Confirmation comes only from authored records (`crumb
  verify`, `crumb traps --confirm`), and nothing acts on a count by itself:
  `--decay` and audit's promotion hint print commands for a person.
- **Contention.** Each emission is one event file in `private/usage-events/`,
  folded into `usage.json` under a lock of its own, exactly once. Parallel
  hooks never lose each other's counts, and a reader counts an event that is
  still waiting to be folded. `crumb usage` prints the model and a
  *Completeness* line when events are pending, unreadable or evicted by the
  2000-record cap; `--json` returns it as `accounting`. An emission that could
  not be written is noted `usage_dropped` in the hook log.
- **`--sessions`** sorts by distinct sessions, then by raw count. Forty guard
  calls in one session are one piece of evidence; five sessions are five. Only
  the last 20 session ids are kept per record, so a row at that cap prints
  `20+`, and every `--json` row carries `sessions_capped`.
- **`--decay [DAYS]`** (default 180, `DECAY_DAYS_DEFAULT`) lists active
  decisions, attempts and traps that are at least DAYS old and that nothing
  has surfaced in the last DAYS, oldest first. Age is taken from `updated_at`,
  else `created_at`, so an edit resets it. Each row carries the command a
  person can run:

  ```text
  crumb mark-status <id> stale --reason "not surfaced in DAYS days"
  ```

  `usage --decay` prints the commands and never runs them. Left out:
  promoted records (standing rules, which the `SessionStart` packet leaves out
  whenever `CLAUDE.md` carries them, so their surfacing counts say little), records past their `expires_at`, and traps confirmed with `crumb
  traps --confirm` within the window. Verifications and questions have TTLs of
  their own and are never candidates. A trap still stored as a block (a
  schema-2 store) has no file to date it and is never a candidate either.
- **Decay needs history.** "Nothing surfaced it in 180 days" needs 180 days of
  counting, so `usage.json` records `started_at`, when counting began on this
  machine. With less history than DAYS, `--decay` says how much it has and
  lists nothing. A file written before `started_at` existed falls back to its
  oldest `last_surfaced_at`, which can only understate the history.
- `--json` under `--decay` returns `days`, `coverage_start`, `coverage_days`,
  `enough_history` and `candidates` (also as `items`).
- `audit` reports the same candidates, with the default window, as
  `decay-candidate` (see `audit`).
- Exit codes: `0` on success (including an empty report), `2` on a usage error
  or when no `.project-memory/` store is present.

---

## Hook log (built, WM-62)

```bash
crumb doctor --hook-log         # per-hook summary of private/hook-log.jsonl
crumb doctor --hook-log --json
```

Every hook firing appends one line to `.project-memory/private/hook-log.jsonl`
(gitignored with the rest of `private/`). The line is one JSON object:

- `event` (`session`, `guard`, `capture`, `prompt`, `compact`, `subagent`),
  `at`, `ms` (how long the hook took), and `session` when the payload carried
  a session id;
- `outcome`, read off the JSON the hook printed, so it describes what the host
  received: `silent` (`{}`), `context` (`additionalContext`), `ask` (a
  permission prompt), `block` (the Stop hook's extraction turn), `locked` (a
  writing hook skipped on the store lock), `other` (any other JSON object) or
  `unparsed` (output that was not JSON);
- what the handler noted: guard's `tool`, `verdict`, `skipped: "prefilter"`,
  `deduped`, and the accounting stages `candidates`, `matches` and `emitted`;
  the prompt hook's `retrieval`, `candidates`, `matches`, `trimmed`,
  `emitted`, `deduped` and `correction`; `usage_dropped` and `state_dropped`
  when a count or a state update could not be written;
  `capture`'s `mined`, `snapshot`, `redundant` and `offered`; `mined` for
  `compact` and `subagent`.

No prompt, command, file path or transcript text is logged, only counts and
verdicts. The hook's stdout is captured and then written out unchanged, even
when the handler raises. Logging is best-effort: a failed write is dropped.
The line is written only when `private/` exists; a hook does not create it.
Each line is a single append. The log is bounded by rotation (audit WP12):
when the current file reaches 2500 lines (half of `HOOK_LOG_MAX_LINES`) it is
renamed to `hook-log.1.jsonl`, replacing the previous one. Rotation takes
`private/.hook-log.lock` without waiting and re-checks the size under it.
Nothing rewrites a file other hooks append to, so parallel hooks never drop
each other's lines; a line leaves only when its rotated half is replaced.
`crumb doctor --hook-log` reads both files.

`crumb doctor --hook-log` summarises the log per event: firings, outcomes, the
spoke rate (the share that were `context`, `ask` or `block`), `ms` p50 / p95 /
max, verdicts, and the handler counts (numbers summed, flags counted). It adds
the total, the number of sessions, the first and last timestamp, and how many
writing firings skipped on the lock. `--json` returns `entries`, `first_at`,
`last_at`, `sessions`, `events` and `locked`. It exits `0`, including when
nothing is logged yet, and `2` when no store is present.
[`field-test.md`](field-test.md) is the protocol that reads it.

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
