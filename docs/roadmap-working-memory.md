# Roadmap: from ledger to working memory

**Status:** approved plan, not yet started. **Owner of the plan:** the repo.
**Audience:** whoever implements it, human or agent. The plan assumes the
implementer has *not* read the codebase and may be a smaller model, so every
work item names the files, functions, constants, data shapes, tests and
acceptance checks it needs. When this document and the code disagree, the
code is the fact and this document is the intent; fix the document.

---

## 0. How to work this plan

### 0.1 The three memory tiers

| Tier | Holds | Lives in | Written by | Injected by |
|---|---|---|---|---|
| **Long-term** | Permanent rules for agents: conventions, hard constraints, "always/never" | `CLAUDE.md` / `AGENTS.md` | humans, and `crumb promote` (Phase 4) | the harness, every turn |
| **Medium-term** | Durable project state that can go stale: decisions, failed attempts, traps, open questions, verifications | `.project-memory/` typed records | `crumb remember/note/verify`, MCP tools, the Stop-hook extraction turn | `crumb resume`, the SessionStart hook, task-scoped injection at UserPromptSubmit (Phase 1) |
| **Short-term** | What is in flight: current focus, next action, jots, corrections, candidates mined from a transcript | `current.md`, `handoff.md`, `inbox/` (Phase 0) | hooks, `crumb jot`, `capture session` | SessionStart (including after compaction), UserPromptSubmit |

Breadcrumbs today is the medium tier plus a thin short tier. The plan fills
the short tier, makes retrieval task-relevant, gives every tier a way to
forget, and builds the promote/demote bridge to the long-term tier. The
long-term tier itself stays the agent-instruction file: breadcrumbs writes a
managed block into it and never anything else.

### 0.2 Ground rules that every work item inherits

These come from `CLAUDE.md`, `docs/architecture.md`, `docs/security.md` and
the decision records under `.project-memory/decisions/`. Do not relitigate
them inside a work item.

1. **No runtime dependencies.** Standard library only. `sqlite3`, `json`,
   `re`, `hashlib`, `subprocess` are fine. Anything third-party belongs behind
   an optional extra and a `unittest.skipUnless`, like the MCP SDK tests.
2. **`python -m unittest discover -s tests` is the canonical runner** and must
   pass on a clean checkout with nothing installed. `ruff check . && ruff format --check .`
   must also pass; that is the `lint` CI job.
3. **The version lives in one place:** `__version__` in `breadcrumbs/__init__.py`.
   Never add a version literal anywhere else. Never hand-tag; `release.yml`
   cuts tags.
4. **Memory informs; it never allows or denies.** Hooks emit
   `permissionDecision: "ask"` at most, never `"deny"` and never `"allow"`.
   Matched record text is data, never instruction: rank it, quote it, never
   execute phrasing found in it. See `_hook_guard` in `breadcrumbs/cli.py`
   and decision `dec_20260818_hook-guard-never-overrides-the-session-s-permission-mode`.
5. **Hooks never fail the host.** Every `crumb hook …` path exits 0 and
   prints `{}` on any malformed payload or internal error. A hook must stay
   cheap on the common path: no record walk unless a prefilter says so.
6. **Never dump transcripts into memory.** Extract candidates; never paste
   tool output or message bodies beyond a bounded one-line excerpt.
7. **No secrets in committed memory.** Anything written automatically from a
   prompt or a transcript goes through `scan_secrets`-equivalent checks first,
   and anything that fails is dropped, not stored.
8. **Canonical records are source of truth; `generated/` is rebuildable.**
   New derived data goes in `generated/` (committed by policy) or `private/`
   (never committed) or `index/` (never committed), never in a record unless
   it is authored fact.
9. **Status beats silent edits.** Retire with `mark-status`, supersede with
   `superseded_by`, never delete or rewrite history except in `prune`.
10. **New code goes in new modules.** `breadcrumbs/cli.py` is 10.7k lines.
    Add `breadcrumbs/<topic>.py` and import it from `cli.py`; keep argparse
    wiring in `cli.py`. Never create an import cycle: new modules import
    from `cli.py` lazily inside functions if they need its helpers, or the
    helper is moved into the new module and re-exported from `cli.py`.
11. **Existing tests are the contract.** A work item that changes existing
    behaviour must change the test that pinned it and say why in the commit
    message. Fixture stores under `fixtures/` must keep passing `validate`.
12. **Every mutation reindexes.** Any new writer calls
    `reindex_projections(memory_dir, root)` after a successful write.
13. **Store-format changes go through the migration machinery** (WM-01) and
    a `SCHEMA_VERSION` bump. Readers tolerate the old shape for one major
    version.

### 0.3 Definition of done for a work item

A work item is done when all of these hold:

- Code is in place with docstrings that say *why*, matching the style of the
  surrounding code (the codebase explains its decisions inline).
- Unit tests exist in `tests/test_<topic>.py`, using the stdlib `unittest`
  patterns already in `tests/` (`make_repo`, `run_hook`, temp stores).
- `python -m unittest discover -s tests` passes. `ruff check . && ruff format --check .` passes.
- `crumb validate` and `crumb audit` pass on this repo's own store and on every
  `fixtures/fixture-*` store (see `tests/test_fixtures.py`).
- `docs/cli-spec.md`, `docs/record-schema.md`, `docs/mcp-spec.md`, `README.md`
  and the `crumb schema` output are updated where the item touches them.
- `CHANGELOG.md` has an entry under `## [Unreleased]`.
- If the item is a behaviour change to an existing command or hook, the
  CHANGELOG entry is under a `### Changed` heading and says what a consumer
  will notice.
- The implementer ran `crumb remember decision` for any design choice made
  during the work that this plan did not already make, and
  `crumb capture session --next "…"` at the end.

### 0.4 Order of work

Phases are ordered by dependency, then by payoff. Within a phase, items are
listed in the order to build them. Sizes: **S** under a day, **M** one to
three days, **L** a week.

| Phase | Theme | Items | Release |
|---|---|---|---|
| 0 | Foundations: migration, inbox, telemetry — **shipped**, see §0.5 | WM-01, WM-02, WM-03 | 0.3.0 |
| 1 | Capture everywhere: new hooks and the transcript miner — **shipped**, see §0.6 | WM-10 to WM-16 | 0.4.0 |
| 2 | Retrieval by relevance — **shipped**, see §0.7 | WM-20 to WM-25 | 0.5.0 |
| 3 | Lifecycle: decay, dedup, consolidation, contradiction — **shipped**, see §0.8 | WM-30 to WM-35 | 0.6.0 |
| 4 | The bridge to long-term memory — **shipped**, see §0.9 | WM-40 to WM-43 | 0.7.0 |
| 5 | Scope and multi-agent — **shipped**, see §0.10 | WM-50 to WM-52 | 0.8.0 |
| 6 | Measurement and evals — **shipped**, see §0.11 | WM-60 to WM-62 | 0.9.0 |
| 7 | Other harnesses | WM-70 | 1.0.0 |

Each phase ends with a release. A release is only the two steps in
`CLAUDE.md`: bump `__version__`, add the CHANGELOG entry, run `release.yml`.

### 0.5 Phase 0: what shipped, and where it differs from this plan

Phase 0 is implemented. `SCHEMA_VERSION` is 2. New modules:
`breadcrumbs/migrate.py`, `breadcrumbs/usage.py`, `breadcrumbs/inbox.py`; new
tests: `tests/test_migrate.py`, `tests/test_usage.py`, `tests/test_inbox.py`.

Seven places where the implementation departed from what this document
specified. Each is a decision a later phase inherits, so read these before
building on Phase 0.

1. **Telemetry is recorded at the call sites, not inside `build_resume_packet`
   or `guard`.** The plan put it in `build_resume_packet`; every mutation
   reindexes and every reindex builds a packet, so that would have counted
   *writes*, which is the one thing the metric is not for. It lives in
   `cmd_resume`, `_hook_session`, `cmd_guard` and `_hook_guard` instead — the
   places a packet or a verdict is genuinely shown. Splitting `guard` between
   the command and the hook also avoids double-counting every hook advisory,
   since the hook shows a filtered subset of the same result.
2. **`private/usage.json` carries a `sessions` list per record** as well as the
   counts. WM-42 asks how many *sessions* a record reached, and a raw count
   cannot answer it: one session firing the hook forty times is not forty
   pieces of evidence. Bounded at 20 ids per record.
3. **Jots reuse the existing `include_ideas` corpus switch** rather than the
   parallel `include_jots` flag the plan described. The semantics are identical
   — findable by lookup, never the basis of a verdict — so a second flag would
   have been two names for one rule. `SPECULATIVE_ITEM_TYPES` is now
   `("idea", "jot")`.
4. **`crumb prune jots`, not `crumb prune --inbox`.** `prune` already takes a
   positional `what`; a flag would have been a second grammar for one command.
5. **The committed packet lists committed jots only**, where the plan said
   "open jots". A machine-local jot in a committed projection makes that file
   differ between two checkouts of one store while `_inputs_hash` — which
   cannot read gitignored input without the same problem — calls both fresh.
   That is exactly the ping-pong `_hashed_input_dirs` exists to prevent. Private
   jots reach an agent through `crumb inbox`, the `memory://inbox` resource, and
   (from Phase 1) the hooks that wrote them. **WM-12 and WM-15 must surface them
   explicitly; they will not arrive via the packet.**
6. **A migration backs up the whole store, not the paths a step declares.** A
   step that under-declares its paths is a silent data-loss bug that only
   appears on somebody else's store, and the thing being copied is a few
   hundred kilobytes of markdown.
7. **A migration reindexes only when `generated/` already exists.** Creating it
   would invent a committed artifact in a store whose owner chose not to have
   one — which is what happened to nine fixtures on the first run.

Two smaller notes for implementers of later phases: the validate check for the
version is named `schema-version` (the `manifest` check now only covers the file
being present), and the `local-private` privacy rule is now path-aware, because
`private/inbox/` is the first record directory that is not committed.

---

## 1. Where the code is today

Facts an implementer needs, with pointers. Line numbers are as of commit
`53b5dac`; use `grep -n "def <name>"` if they have moved.

**Record shapes.** Two storage shapes exist. Decisions, attempts,
verifications, ideas and sessions are one file per record with YAML
frontmatter under `<type>/YYYY-MM-DD-<slug>.md`. Traps and questions are
`## ` blocks inside the singleton files `known-traps.md` and
`open-questions.md`, parsed by `_md_blocks` (`cli.py:4868`), `load_traps`
(`cli.py:4946`) and `load_open_questions` (`cli.py:4982`). `current.md` and
`handoff.md` are plain sectioned markdown. Vocabularies are at `cli.py:146`
(`VALID_STATUS`), `cli.py:162` (`VALID_QUESTION_STATUS`), `cli.py:172`
(`DIR_TYPES`), `cli.py:181` (`TYPE_PREFIX`), `cli.py:1968`
(`FRONTMATTER_ORDER`), `cli.py:1774` (`BODY_SECTIONS`). `SCHEMA_VERSION = 1`
at `cli.py:42` has never been bumped and there is no migration code.

**Writers.** `write_record` (`cli.py:2229`) for directory records, `note`
(`cli.py:3316`) for traps, questions and ideas, `verify` (`cli.py:3571`),
`cmd_capture_session` (`cli.py:4188`) plus `update_handoff` (`cli.py:4510`)
and `update_current` (`cli.py:4550`). All validate the new file and revert
on failure, then call `reindex_projections` (`cli.py:3294`). The only
automatic writer is the Stop hook's machine snapshot; it reads git, never
the transcript. Machine snapshots from one host session coalesce
(`cli.py:3896`); durable records never dedupe.

**Retrieval.** `search` (`cli.py:7014`) is deterministic: tokenize, stem
(`_stem`, `cli.py:6423`, idempotent), drop stop words (`_specific`,
`cli.py:6460`), score by file 6 / tag 4 / mention 2 / keyword 1 plus
bonuses (`cli.py:6057` to `6076`), decay by age and branch
(`cli.py:6089` to `6092`). `guard` (`cli.py:7269`) wraps it and decides a
verdict per match with a stance cap (`_match_stance`, `cli.py:7123`;
`_decide_verdict`, `cli.py:7153`). `build_resume_packet` (`cli.py:5519`)
lists active records **newest first** with `SECTION_CAPS` (`cli.py:4621`)
and trims to `TOKEN_BUDGET_MAX = 5000` (`cli.py:4606`) in `TRIM_ORDER`
(`cli.py:4639`). Only `likely_files` is task-scoped (`--task`).

**Hooks.** Three events in `HOOK_EVENTS` and `_HOOK_SPECS` (`cli.py:8675`
to `8681`): `session` (SessionStart, no matcher), `guard` (PreToolUse,
`Bash|Edit|Write|MultiEdit`), `capture` (Stop). Installed by
`install_claude_hooks` (`cli.py:8821`) into `.claude/settings.json`, keyed
by the `breadcrumbsHook` marker. Dispatch is `cmd_hook` (`cli.py:9836`).
The Stop hook's extraction turn (`_hook_capture`, `cli.py:9804`;
`_extraction_reason`, `cli.py:9734`) fires only when new commits landed.

**MCP.** `breadcrumbs/mcp_core.py` wraps `cli` functions with no SDK
import; `breadcrumbs/mcp_server.py` binds them with FastMCP. 8 resources,
6 prompts, 10 tools. `tests/test_mcp.py` asserts bound URIs equal the
`STATIC_RESOURCES`/`TEMPLATE_RESOURCES` keys.

**Staleness.** `compute_staleness` (`cli.py:5162`): age vs
`STALE_AGE_DAYS = 21`, commit distance, and whether the record file has
reached HEAD (`HeadTree`, `cli.py:5092`). `expires_at` exists in
frontmatter and is never set automatically. Traps never age out; `crumb
traps --confirm` stamps a confirmation date.

**Conflict detection.** Only `_focus_verification_conflicts`
(`cli.py:5332`). Nothing compares record to record.

**Audit.** `run_audit` (`cli.py:8071`) returns findings with severity
`AUDIT_FAIL` (secrets only), `AUDIT_WARN`, `AUDIT_INFO`. New heuristics are
warnings, never failures.

---

## Phase 0: Foundations

### WM-01 Schema migration machinery — **M** — SHIPPED

**Goal.** Make store-format changes safe to ship. Later items (WM-03,
WM-22, WM-30, WM-40, WM-50) add directories, frontmatter keys and a new
shape for traps. Without a migration path each of those is a breaking
change for every existing store.

**Design.**

- New module `breadcrumbs/migrate.py`.
- `MIGRATIONS: list[tuple[int, Callable[[Path, Path], list[str]]]]`, ordered
  by target version. Each function takes `(memory_dir, project_root)`,
  performs one idempotent step, and returns a list of human-readable lines
  describing what it changed. Migration `n` upgrades a store at
  `schema_version n-1` to `n`.
- `store_schema_version(memory_dir) -> int` reads `schema_version` from
  `manifest.yml` via the existing `load_manifest`; missing means `1`.
- `migrate(memory_dir, project_root, *, dry_run: bool) -> dict` applies
  every migration above the store's version up to `SCHEMA_VERSION`, in
  order, writing `manifest.yml` after each step with `write_text_atomic`.
  A failure stops at the last completed step and leaves the manifest at
  that version. Returns `{"from": n, "to": m, "steps": [...], "ok": bool}`.
- **Backups.** Before the first step, copy every file that a step will
  modify to `private/migrations/<timestamp>/<relative path>`. `private/` is
  gitignored, so the backup never leaks. Print where the backup is.
- New CLI command `crumb migrate [--dry-run] [--json]`. Exit 0 on success
  or nothing to do, 1 on a failed step, 2 with no store.
- `validate` gains check `schema-version`: fails with message
  `store is schema_version N, this crumb understands M — run \`crumb migrate\``
  when the store is **older**. When the store is **newer** than the tool,
  fail with `upgrade crumb-kit`. Add to `run_validate` (`cli.py:1406`).
- Every reader that a future migration will change must **tolerate both
  shapes** for one major version. State that in the migration function's
  docstring.
- `SCHEMA_VERSION` stays `1` in this item. This item ships the machinery
  with an empty `MIGRATIONS` list and a test-only migration.

**Files.** New `breadcrumbs/migrate.py`; `cli.py` (argparse wiring for
`migrate`, new validate check); `docs/record-schema.md` §3 (manifest) and a
new §11 "Migrations"; `docs/cli-spec.md` command table; `README.md`
quickstart line.

**Tests** in `tests/test_migrate.py`:
- Empty migration list: `migrate` reports `from == to`, no writes, manifest
  byte-identical.
- With a monkeypatched `MIGRATIONS` of two steps: both applied in order,
  manifest reads the target version, backup directory contains the
  pre-change bytes.
- Second step raises: manifest stays at the first step's version, `ok` is
  false, exit code 1.
- `--dry-run` writes nothing and lists steps.
- `validate` fails on a store whose manifest says `schema_version: 0` and
  on one that says `99`, with the two different hints.

**Acceptance.** `crumb migrate` on this repo's store prints "nothing to
do" and exits 0. All fixtures still validate.

### WM-02 Record usage telemetry — **S** — SHIPPED

**Goal.** Know which records actually get surfaced and used, so ranking
(Phase 2), decay (Phase 3) and promotion suggestions (Phase 4) have a
signal. Today nothing records that a surfaced record was ever seen.

**Design.**

- New module `breadcrumbs/usage.py`.
- Storage: `private/usage.json`, machine-local, never committed. Shape:
  ```json
  {"records": {"<record id>": {"surfaced": 12, "last_surfaced_at": "<iso>",
                              "by": {"resume": 5, "guard": 4, "prompt": 3}}}}
  ```
  Keyed by record id, so it survives retitles and file moves. Bounded to
  2000 ids; when over, drop the ids with the oldest `last_surfaced_at`.
- `record_surfaced(memory_dir, ids: Iterable[str], source: str) -> None`.
  Best-effort: any I/O error is swallowed. Writes with `write_text_atomic`.
  Must add under 5 ms on a 300-record store; measure in the test with a
  loose upper bound of 50 ms.
- `load_usage(memory_dir) -> dict`.
- Call sites: `build_resume_packet` after `_bound_packet` (source
  `"resume"`, the ids that survived trimming); `guard` for every match in
  `result["matches"]` (source `"guard"`); the hook guard for the matches it
  actually shows (source `"hook-guard"`); WM-10 (source `"prompt"`).
  **Do not** record from `search`: a search is a lookup, not a surfacing.
- Do **not** write usage from the MCP resource reads either; keep the
  write surface small.
- `crumb usage [--json] [--never] [--top N]` lists records by surfaced
  count, or with `--never` the active records with no entry, oldest first.
- `audit` finding `never-surfaced`, severity `AUDIT_INFO`: active
  decision/attempt/trap older than 90 days with no usage entry. Only when
  `private/usage.json` exists, since a fresh clone has no history.

**Why private, not committed.** Writing counts into record frontmatter
would churn every record and the `inputs_hash` on every guard call, and
break the "records are authored facts" rule. A committed counter file
would conflict on every merge. Local-only is the correct v1; a shared
signal is a later item once WM-60 shows it is worth the merge cost.

**Files.** New `breadcrumbs/usage.py`; `cli.py` call sites and the
`usage` command; `docs/cli-spec.md`; `docs/record-schema.md` §2 (mention
the file under `private/`).

**Tests** in `tests/test_usage.py`: counts increment per source; bound
enforced; unreadable file is treated as empty; `resume` on a fixture store
creates the file with the surfaced ids; `--never` lists an active decision
that was never surfaced; `audit` emits `never-surfaced` only when the file
exists.

### WM-03 The inbox: a low-friction short-term tier — **M** — SHIPPED

**Goal.** Give agents and hooks a place to put a two-line observation
without a title, sections and evidence. Every durable write today requires
evidence or `--confidence low`; that is right for a decision and wrong for
"the flaky test is `test_x`, it fails under `-n auto`". Phases 1 and 3 both
write here.

**Design.**

- Two directories, same record shape:
  - `.project-memory/inbox/` — committed. Jots an agent or human chose to
    write (`crumb jot`), and jots promoted from private.
  - `.project-memory/private/inbox/` — never committed (already under the
    gitignored `private/**`). Jots written automatically by hooks from
    prompts or transcripts (Phase 1). Automatic capture must default to
    local because a user prompt can contain anything.
- Record type `jot`, prefix `jot`, filename
  `YYYY-MM-DD-<slug>-<4hex>.md` (add `"jot"` to `UNIQUE_SUFFIX_TYPES`,
  `cli.py:2188`, because hooks write these concurrently). Add
  `"inbox": "jot"` to `DIR_TYPES` and `"jot": "jot"` to `TYPE_PREFIX`.
  `load_records` must also walk `private/inbox/`; add a helper
  `inbox_dirs(memory_dir) -> list[Path]` and use it everywhere jots are
  read.
- Frontmatter: the standard set from `write_record` plus
  `source: agent|human|prompt|transcript|hook` and `expires_at` set
  automatically to `created_at + 14 days` (constant `JOT_TTL_DAYS = 14`,
  overridable in `manifest.yml` as `jot_ttl_days`). Add `source` to
  `FRONTMATTER_ORDER` after `agent`. Status uses `VALID_STATUS`; a promoted
  jot becomes `superseded` with `superseded_by: <new record id>`; an expired
  jot stays `active` on disk and is filtered by `expires_at`.
- Body: a single `## Note` section, max 600 characters after whitespace
  normalisation (constant `JOT_MAX_CHARS`); longer input is truncated with
  `…` and a `CRUMB-WARN`.
- **Validate:** jots are exempt from the evidence-or-low-confidence rule
  (§16.9). Add the type to the exemption where ideas are exempted. Jots
  under `inbox/` must be `privacy: repo-safe`; jots under `private/inbox/`
  may be `local-private`, and the existing §16.8 rule (local-private must
  live under `private/`) already enforces the direction.
- CLI:
  - `crumb jot "<text>" [--tag T]... [--file PATH]... [--local] [--json]`.
    `--file` becomes `evidence: [{type: file, ref: PATH}]` so guard's file
    signal works. `--local` writes to `private/inbox/`.
  - `crumb inbox [--all] [--expired] [--json]` lists open jots newest
    first: id, age, source, first 80 chars.
  - `crumb inbox promote <jot id> decision|attempt|trap|question|verification|idea [remember/note flags…]`
    creates the target record through the existing writer with the jot's
    text prefilled as the title (decision/attempt/idea/verification) or
    the question/trap text, passes through any further flags, then marks
    the jot `superseded` with `superseded_by` set to the new id. For a jot
    in `private/inbox/`, promotion is what moves content into committed
    memory; the jot file itself stays private.
  - `crumb inbox drop <jot id> [--reason …]` marks it `rejected`.
  - `crumb prune --inbox` deletes jots that are expired or non-active and
    older than 30 days. Extend `cmd_prune` (`cli.py:4375`); keep the
    existing session behaviour unchanged.
- **Resume packet:** new section `## Inbox (unsorted, expires)` after
  `Open Questions / Blockers`, listing open unexpired jots newest first,
  `SECTION_CAPS["inbox"] = 10`, in `TRIM_ORDER` right after
  `"verification"` so it is trimmed early. Each line: `- \`jot_…\` (<age>d,
  <source>) <text up to 120 chars>`. Add `"inbox"` to `_FAST_DROP`.
- **Search and guard:** jots are in the `search` corpus (`--type jot`) and
  **not** in the guard corpus, exactly like ideas (`_candidate_items`,
  `include_ideas`; add a parallel `include_jots` that `search` sets true
  and `guard` leaves false). A jot is a note, not a finding.
- **MCP:** tool `memory_jot(text, tags, files, local)` and resource
  `memory://inbox` (rendered list). Add to `mcp_core.py` and
  `mcp_server.py`, and to the URI assertions in `tests/test_mcp.py`.
- **Adapter block** (`adapter_block`, `cli.py:8601`): add one bullet
  "Quick observation mid-task, no ceremony: `crumb jot "…"`. Promote later
  with `crumb inbox promote`." Keep the block under `ADAPTER_BLOAT_CHARS`.
- **Migration:** add `inbox/.gitkeep` and `private/inbox/` to the template
  tree under `breadcrumbs/templates/project-memory/`, and a WM-01 migration
  step `2` that creates the two directories in existing stores. Bump
  `SCHEMA_VERSION` to `2`. Readers must not fail when the directories are
  absent (an un-migrated store simply has no jots).

**Files.** New `breadcrumbs/inbox.py` (jot writing, listing, promotion,
expiry filter); `cli.py` (vocabularies, argparse, packet section, prune,
validate exemption, adapter bullet); `mcp_core.py`, `mcp_server.py`;
templates; `docs/record-schema.md` (type table, frontmatter, TTL),
`docs/cli-spec.md`, `docs/mcp-spec.md`, `README.md`.

**Tests** in `tests/test_inbox.py`:
- `jot` writes a valid record; `validate` passes without evidence.
- Two jots with the same text on the same day get different filenames.
- `--local` lands under `private/inbox/`; `git status` does not list it
  in a repo initialised with `crumb init`.
- Expired jot is absent from the packet and from `crumb inbox`, present
  with `--expired`.
- `promote … decision --set Decision "…" --evidence commit abc` creates
  the decision and marks the jot superseded with the right id; the jot
  text is the decision title.
- Packet section appears, is capped at 10, and is trimmed before
  `known_traps` when over budget (construct a store with 30 jots and a
  budget forced low by monkeypatching `TOKEN_BUDGET_MAX`).
- `guard` on an action matching only a jot returns `PROCEED`; `search`
  finds it.
- `prune --inbox` deletes only expired or non-active jots older than 30
  days and reports them.

**Acceptance.** This repo's store migrates to schema 2 with `crumb
migrate`, all fixtures migrate in a temp copy and still validate, and the
resume packet of a store with no jots shows no Inbox section.

---

## Phase 1: Capture everywhere

The theme: the agent should not have to *decide* to remember. Today the
only automatic write is a git snapshot at Stop, and the extraction turn
fires only when a turn produced commits. Five moments in a session carry
memory that is currently lost: the user's prompt (especially a
correction), the point just before context compaction, the end of a
subagent, the moment a subagent is *launched* (it starts cold), and
edit-only turns.

**Claude Code hook contract, as used by this phase.** Verify against the
current docs at https://code.claude.com/docs/en/hooks before implementing;
record any discrepancy as a `crumb note trap`.

Common stdin fields on every event: `session_id`, `prompt_id`,
`transcript_path`, `cwd`, `permission_mode`, `hook_event_name`.

| Event | Event-specific stdin fields | Matcher filters | Output this plan uses |
|---|---|---|---|
| `SessionStart` | `source`: `startup` \| `resume` \| `clear` \| `compact` \| `fork` | the `source` value | `hookSpecificOutput.additionalContext` (reaches the model). Plain stdout also reaches the model; always emit JSON. |
| `UserPromptSubmit` | `prompt` | none | `hookSpecificOutput.additionalContext` (reaches the model). `decision: "block"` exists and **erases the prompt**; this plan never uses it. |
| `PreToolUse` | `tool_name`, `tool_input` | tool name (regex) | `additionalContext`, `permissionDecision: "ask"` |
| `PostToolUse` | `tool_name`, `tool_input`, `tool_response` | tool name | not used by this plan; stdout goes to the debug log only |
| `Stop` | `stop_hook_active`, `last_assistant_message` | none | `decision: "block"` + `reason` (the extraction turn); the reason is fed back to the model |
| `SubagentStop` | `stop_hook_active`, `agent_id`, `agent_type`, `last_assistant_message`, `stop_reason`; `transcript_path` is the **subagent's** transcript | agent type (`Explore`, `general-purpose`, custom names) | Can block like `Stop`; the reason is fed back to the subagent. This plan does **not** block here (WM-13). |
| `PreCompact` | `trigger`: `manual` \| `auto`; `custom_instructions` | the `trigger` value | **Nothing.** stdout goes to the debug log only; no `additionalContext`, no blocking. Side effects only. |
| `PostCompact` | `trigger` | the `trigger` value | Nothing reaches the model. Not used; `SessionStart` with `source: compact` is the re-injection point. |
| `SessionEnd` | `reason`: `clear` \| `resume` \| `logout` \| `prompt_input_exit` \| `other` | the `reason` value | side effects only; 1.5 s shared time budget, so not used by this plan |

**Transcript lag.** The docs state the transcript file is written
asynchronously and may not yet contain the current turn's last messages
when a hook fires. The miner (WM-14) therefore treats the transcript as
"everything up to the previous turn" and WM-15 reads `last_assistant_message`
from the payload for anything about the ending turn.

All hooks receive the event's JSON on stdin and must print JSON on stdout.
The existing reader is `_read_hook_stdin` (`cli.py:9342`); the existing
dispatcher is `cmd_hook` (`cli.py:9836`). New events extend `HOOK_EVENTS`,
`_HOOK_SPECS` (add a third tuple element, the matcher, or `None`) and the
`hook` subparser. `install_claude_hooks` and `remove_claude_hooks` must
handle the new events with no other change, because they iterate
`_HOOK_SPECS`. `crumb init --with-hooks` installs all events by default;
`--with-hooks=session,guard,capture` keeps selecting a subset. Add the new
names to the help text.

### WM-14 The transcript miner — **L** — SHIPPED (build first; WM-11, WM-13, WM-15 depend on it)

**Goal.** Turn a Claude Code transcript into a bounded list of memory
*candidates* with no LLM: failed-then-fixed commands, verification
commands that passed, files under churn, user corrections. Candidates
become private jots (WM-03) that the agent can promote.

**Transcript format.** The file at `transcript_path` is JSONL. Each line
is an object with at least `type` (`"user"` or `"assistant"`, plus other
types to ignore), `uuid`, `parentUuid`, `timestamp`, and `message` with
`role` and `content`. `content` is a string or a list of blocks. Blocks of
`type: "tool_use"` have `id`, `name`, `input`. Blocks of
`type: "tool_result"` have `tool_use_id`, `content` (string or list of
`{type: "text", text}`), and `is_error` (boolean, may be absent). Lines
may also carry a `toolUseResult` object with structured output; treat it
as optional. **Parse defensively:** skip any line that is not valid JSON
or lacks the fields; never raise.

**Design.**

- New module `breadcrumbs/transcript.py`, pure functions, no I/O except
  `read_transcript(path, *, max_bytes=8_000_000) -> list[dict]` which reads
  at most the last `max_bytes` (seek from the end; discard the first
  partial line).
- `pair_tool_calls(entries) -> list[ToolCall]` where `ToolCall` is a
  dataclass: `name`, `input` (dict), `result_text` (first 400 chars,
  whitespace-normalised), `is_error` (bool), `index` (position in
  transcript), `timestamp`.
  - A Bash call is an error if `is_error` is true **or** its result text
    matches `_BASH_FAILURE_RE` =
    `(?i)\b(traceback|error:|failed|exit code [1-9]|command not found|FAIL(ED)?\b|AssertionError|npm ERR!)`.
    Document the regex in the module and keep it tunable.
- `normalize_command(cmd) -> str`: strip leading `cd … &&`, collapse
  whitespace, drop trailing `2>&1`, `| head …`, `| tail …`; cut at 200
  chars. Used as the identity of a command across retries.
- `mine(entries, *, since_index: int = 0) -> list[Candidate]`.
  `Candidate` dataclass: `kind` (`attempt` | `verification` | `trap` |
  `correction`), `title` (≤ 120 chars), `note` (≤ 600 chars), `files`
  (list), `command` (str or None), `confidence` (`"low"` always),
  `evidence` (list of `{type, ref}`), `fingerprint` (sha1 of
  `kind + title`, used to dedupe across firings).
  Rules, in this order, each bounded:
  1. **Failed then fixed (kind `attempt`).** A Bash call `A` is an error;
     a later Bash call with the same `normalize_command` is not an error;
     between them there is at least one `Edit`/`Write`/`MultiEdit`. Title:
     `"<normalized command> failed until <N> file(s) changed"`. Note: the
     first line of the failing result, then `Fixed after editing: <up to 3
     file paths>`. Files: those edited between. Command: normalized.
     Evidence: `{type: command, ref: <normalized>}` and one
     `{type: file, ref}` per file. Max 5 per transcript.
  2. **Verification command (kind `verification`).** A Bash call whose
     normalized command matches `_TEST_CMD_RE` =
     `(?i)^(python -m (unittest|pytest)|pytest|npm test|npm run (test|lint)|yarn test|cargo test|go test|make (test|check)|ruff (check|format)|mypy|tsc\b|gradlew? test|mvn test)`
     and is not an error. Title: `"<command> passed"`. Command: normalized.
     Evidence: `{type: command}`. Dedupe by normalized command; max 5.
  3. **Churn (kind `trap`).** A file path edited by `Edit`/`Write`/
     `MultiEdit` **4 or more times** (`CHURN_MIN_EDITS = 4`). Title:
     `"<path> was edited <N> times this session"`. Note: `"Repeated edits
     suggest a fragile area or a missing test; confirm before recording
     a trap."` Files: `[path]`. Max 3.
  4. **Correction (kind `correction`).** A `user` entry whose text content
     (not tool results) matches `_CORRECTION_RE` =
     `(?i)^\s*(no[,.! ]|don'?t|do not|stop\b|not that|that'?s (wrong|not)|instead[, ]|never\b|wrong\b|undo\b|revert\b|actually[, ])`
     and is under 500 characters. Title: first 120 chars of the message.
     Note: the message, truncated to 600. Max 5. Skip when WM-10 already
     captured this prompt: the fingerprint matches an existing private jot
     from this `session_id`.
- Every candidate's `title` and `note` pass through
  `redact_secrets(text) -> str | None` which runs the secret regexes used
  by `scan_secrets` (factor them out of `cli.py:7540` region into a
  helper the miner can import, or call `cli._secret_hits_in_text` if you
  add one) and returns `None` when anything blocking matches. A `None`
  candidate is dropped, counted, and reported as `dropped_for_secrets`.
- `write_candidates(memory_dir, root, candidates, *, session_id, source)
  -> list[str]` writes each as a `private/inbox/` jot with
  `source: transcript`, tags `["mined", kind]`, `evidence` from the
  candidate, and `host_session: <session_id>` so WM-15 can scope to the
  session. Skip any whose fingerprint already exists among jots from this
  session (store the fingerprint in frontmatter as `fingerprint`; add it to
  `FRONTMATTER_ORDER` after `host_session`). Returns the ids written.
  Max total `MINER_MAX_JOTS_PER_FIRING = 10`.
- Performance: a 5 MB transcript must mine in under 300 ms on CI. Test
  with a synthetic transcript of 20k lines.

**Files.** New `breadcrumbs/transcript.py`; `cli.py` (frontmatter key,
secret helper factoring); `docs/record-schema.md` (the `fingerprint`,
`host_session`, `source` keys on jots); `docs/architecture.md` §3 (a row
for mined jots: "candidates, never source of truth until promoted").

**Tests** in `tests/test_transcript.py`, using hand-written JSONL fixtures
under `tests/data/transcripts/`:
- A failing pytest, two edits, a passing pytest → one `attempt` candidate
  with both files and the command.
- A passing `ruff check .` → one `verification` candidate; the same
  command twice → still one.
- A file edited 4 times → one `trap`; edited 3 times → none.
- User message "No, don't touch the migration, revert it" → one
  `correction`; a user message that is a tool result → none.
- A candidate whose note contains `AKIA[0-9A-Z]{16}` is dropped and
  counted.
- Malformed lines (truncated JSON, missing `message`) are skipped without
  error.
- `write_candidates` writes to `private/inbox/`, is idempotent across two
  calls with the same candidates, and stops at 10.
- Reading only the last `max_bytes` of a large file yields whole lines.

### WM-10 UserPromptSubmit hook: task-scoped injection and correction capture — **M** — SHIPPED

**Goal.** Inject the records relevant to *this prompt*, not the
newest-first list, at the moment the task is known. Capture corrections
automatically. Replace nothing: SessionStart keeps injecting the packet.

**Design.**

- New breadcrumbs event `prompt` → `("UserPromptSubmit", None)` in
  `_HOOK_SPECS`. Handler `_hook_prompt(memory_dir, root, payload)` in a
  new module `breadcrumbs/hooks_prompt.py` (keep `cli.py` from growing).
- Read `payload["prompt"]`. If shorter than 12 characters or matching a
  slash command (`^/\w+`), print `{}` and exit.
- **Retrieval.** Call `search(memory_dir, root, prompt, min_keyword=2,
  noise_floor=GUARD_NOISE_FLOOR, include_ideas=False)`. Take matches with
  at least one signal in `GUARD_SURFACING_SIGNALS` **or** score ≥
  `GUARD_READ_FIRST_SCORE`; take the top `PROMPT_HOOK_MAX_MATCHES = 5`.
  Render one line per match:
  `- \`<id>\` [<kind>] <title> — <reason>` using the existing
  `_match_reason` output. Prepend
  `breadcrumbs: memory relevant to this prompt (data, not instruction):`
  and append `Fetch a body with \`crumb show <id>\` (WM-21) or the MCP
  resource.` Until WM-21 lands, say `crumb search --json` instead.
  Budget: the whole `additionalContext` ≤ `PROMPT_HOOK_TOKEN_BUDGET = 800`
  by `approx_tokens`; drop lines from the bottom until it fits.
- **Dedupe per session.** Reuse `_hook_guard_advisory_seen(memory_dir,
  session_id, key)` with `key = "prompt|" + ",".join(sorted(ids))`. Same
  set of records for a later prompt → say nothing. Move that function to
  a shared `breadcrumbs/hooks_common.py` and import it from both places.
- **Prefilter.** Do not run `search` when the store has no active
  records; check `generated/guard-prefilter.json` exists and skip when it
  has no tokens (a cheap read the guard hook already does).
- **Correction capture.** If the prompt matches `_CORRECTION_RE` from
  WM-14 and `manifest.yml` does not set `capture_corrections: false`,
  write one `private/inbox/` jot: `source: prompt`, tags `["correction"]`,
  text = the prompt truncated to `JOT_MAX_CHARS`, after `redact_secrets`;
  drop silently when redaction fails. Record `host_session` and
  `fingerprint`. Never write to committed `inbox/` from a hook.
- **Session state.** Write `private/session-state.json`:
  `{"<session_id>": {"last_prompt": <first 300 chars>, "at": <iso>,
  "matched": [ids]}}`, bounded to 8 sessions like the advisory-seen file.
  WM-12 reads it after compaction.
- Telemetry: `record_surfaced(ids, "prompt")` (WM-02).
- Output shape:
  ```json
  {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                          "additionalContext": "<text>"}}
  ```
  Never `decision: "block"`: blocking a prompt erases it.
- Time budget: the whole hook under 400 ms on a 300-record store. If the
  store has more than 500 candidate items, skip retrieval and only do
  correction capture; log nothing.

**Files.** New `breadcrumbs/hooks_prompt.py`, `breadcrumbs/hooks_common.py`;
`cli.py` (`HOOK_EVENTS`, `_HOOK_SPECS`, subparser, dispatch, help);
`docs/cli-spec.md` hooks section; `README.md` Integrations list (add a
fourth bullet for UserPromptSubmit); adapter block unchanged.

**Tests** in `tests/test_hooks_prompt.py` (reuse `run_hook` from
`tests/test_hooks.py`; move it to a `tests/_hookutil.py` helper if
importing across test modules is awkward):
- Prompt naming a file that a decision cites as `--evidence file` →
  `additionalContext` contains that decision id and the
  `hookEventName` is `UserPromptSubmit`.
- Same prompt twice in one session → second output is `{}`.
- Prompt sharing only generic words with records → `{}`.
- Slash command → `{}`; empty store → `{}`.
- "No, don't rewrite the parser" → a jot exists under `private/inbox/`
  with `source: prompt`; the committed `inbox/` is empty; with
  `capture_corrections: false` in the manifest no jot is written.
- A prompt containing a PEM block → no jot, output still well-formed.
- Output stays under 800 approx tokens with 40 matching records.
- `install_claude_hooks(root, ["prompt"])` writes a `UserPromptSubmit`
  entry with no `matcher` key and the `breadcrumbsHook: "prompt"` marker;
  `remove_claude_hooks` removes it; `doctor` reports it.

### WM-11 PreCompact hook: mine before the context is destroyed — **S** — SHIPPED (after WM-14)

**Goal.** Compaction is the biggest memory-loss event in a long session.
The hook cannot speak to the model, so it does the deterministic thing:
mine the transcript into private jots and leave a marker for the
post-compaction SessionStart (WM-12).

**Design.**

- New event `compact` → `("PreCompact", None)`; handler `_hook_compact`
  in `breadcrumbs/hooks_compact.py`.
- Read `payload["transcript_path"]`; if missing or unreadable, print `{}`.
- Determine `since_index`: `private/miner-cursor.json` stores, per
  `session_id`, the transcript line count already mined (WM-11, WM-13 and
  WM-15 all update it). Mine only entries after the cursor; update the
  cursor after writing.
- `candidates = transcript.mine(entries, since_index)`;
  `ids = transcript.write_candidates(..., source="transcript")`.
- Write `private/compaction-marker.json`:
  `{"<session_id>": {"at": <iso>, "trigger": payload["trigger"],
  "commit": git_commit(root), "jots": ids}}`.
- Print `{}`. The `trigger` value is stored, not acted on.
- Whole hook under 500 ms; if the transcript is over 8 MB only the tail is
  read (WM-14's `max_bytes`).

**Tests** in `tests/test_hooks_compact.py`: given a transcript fixture with
one failed-then-fixed command, the hook writes one private jot and a
marker naming it; running twice writes no second jot (cursor); missing
transcript path → `{}` and no files; `install_claude_hooks(root,
["compact"])` writes a `PreCompact` entry with no matcher.

### WM-12 SessionStart after compaction: re-orient with what was in flight — **S** — SHIPPED (after WM-10, WM-11)

**Goal.** After compaction the model has a summary and no memory of the
records it was shown. The SessionStart hook already fires with
`source: "compact"` because it has no matcher; make its output
source-aware.

**Design.** In `_hook_session` (`cli.py:9541`):

- Read `payload.get("source")`. For `startup`, `resume`, `clear`: current
  behaviour, plus a trailing `## Inbox` block if WM-03's section is
  non-empty (it already is part of the packet; nothing to add).
- For `compact`:
  1. Prepend a header:
     `breadcrumbs: context was compacted. Memory below is what was
     relevant before compaction; the full packet follows.`
  2. Read `private/session-state.json` for this `session_id` (WM-10) and
     add `Last prompt before compaction: <text>` and
     `Records surfaced for it: <ids>`.
  3. Read `private/compaction-marker.json` for this `session_id` (WM-11)
     and list the jots it wrote, each on one line with its id and text,
     under `Mined from the transcript just now (unconfirmed, promote or
     drop):`. Cap at 10 lines.
  4. Then the normal packet.
  Total stays within `TOKEN_BUDGET_MAX + 1000`; trim the mined list first.
- The `source` field is absent in older harness versions; treat absent as
  `startup`.

**Tests** in `tests/test_hooks.py`: payload with `source: "compact"` and
both private files present → output contains the header, the last prompt
and the jot ids; `source: "startup"` → unchanged output; missing private
files → header only.

### WM-13 SubagentStop hook: subagent findings do not die with the subagent — **S** — SHIPPED (after WM-14)

**Goal.** A subagent's failures and verifications currently vanish.

**Design.**

- New event `subagent` → `("SubagentStop", None)`; handler in
  `breadcrumbs/hooks_compact.py` next to WM-11 (same shape: mine, write,
  no blocking).
- Mine the subagent's `transcript_path` fully (no cursor; the subagent is
  finished). Write candidates as private jots with `source: transcript`,
  tags `["mined", kind, "subagent"]`.
- Do **not** emit `decision: "block"` in this item, although the event
  supports it exactly like `Stop` (the reason is fed back to the subagent
  and it keeps working). Holding a subagent to make it write records is a
  prompt-fatigue question that needs the field test the open question in
  `open-questions.md` already asks for. Leave a `crumb note idea` when
  implementing, and reserve a manifest key `subagent_extraction: false`
  for that later work.
- `agent_type` is available; store it in the jot tags as
  `agent:<agent_type>` so a later review can see which subagents produce
  useful candidates.
- Print `{}`.

**Tests**: mining a subagent transcript writes tagged jots; a
transcript with nothing to mine writes nothing; the entry installs under
`SubagentStop` without a matcher.

### WM-15 Stop hook: extraction on more than commits, with candidates in hand — **M** — SHIPPED (after WM-14, WM-03)

**Goal.** Today `_hook_capture` asks the agent to write records only when
commits landed, and asks from scratch. Ask also when the transcript
shows failed-then-fixed work, and hand the agent the mined candidates so
the answer is "promote jot_x as an attempt" rather than composing a
record with little context left.

**Design.** Modify `_hook_capture` (`cli.py:9804`) and
`_extraction_reason` (`cli.py:9734`):

- Before the redundancy check, mine the transcript from the cursor
  (`private/miner-cursor.json`) and write private jots, exactly like
  WM-11. Failures here never affect the rest of the hook. The transcript
  may lag the ending turn (see the contract table), so the cursor is
  advanced only past lines actually read, and the next firing picks up
  the rest.
- Compute `session_jots`: private jots with `host_session == session_id`
  that are `active`, unexpired, from any source. Compute
  `attempt_jots = [j for j in session_jots if "attempt" in tags]`.
- Extraction trigger becomes: `commits` non-empty **or**
  `len(attempt_jots) >= 1` **or** `len(session_jots) >= 3`. The existing
  loop guard (`stop_hook_active`), the manifest kill switch
  `extraction_prompt`, and "first firing takes a silent baseline" stay
  exactly as they are.
- `_extraction_reason(commits, session_jots)`: after the commit listing
  (unchanged when non-empty), add a block:
  ```
  Candidates mined from this session (unconfirmed; each is a private jot):
    jot_… [attempt] pytest tests/x failed until 2 file(s) changed
    jot_… [verification] ruff check . passed
  Promote what is durable:  crumb inbox promote <jot id> attempt|verification|trap --evidence commit <sha>
  Drop what is noise:       crumb inbox drop <jot id>
  ```
  Cap at `EXTRACTION_MAX_JOTS_SHOWN = 6`. Keep the existing four numbered
  items and the closing `capture session` instruction; that command is
  still what clears the prompt.
- Redundancy check unchanged: a fresh session record makes the re-fired
  Stop silent. Additionally, jots left unpromoted after the capture are
  **not** re-prompted for in later turns: the check "did we already ask
  about these jots" is `private/extraction-asked.json` keyed by session
  with the set of jot ids already shown.

**Tests** in `tests/test_hooks.py`:
- No commits, transcript with one failed-then-fixed command → output is
  `decision: block` and the reason names the jot id and
  `crumb inbox promote`.
- No commits, transcript with only one verification candidate → no block,
  snapshot as before (one candidate under the threshold).
- Commits and candidates → both blocks in the reason, commits first.
- `stop_hook_active: true` → never blocks, snapshot taken, jots still
  mined (mining is side-effect only).
- Second Stop in the same session with the same jots, no new commits →
  `{}` (already asked).
- `extraction_prompt: false` → never blocks, jots still mined.

### WM-16 Guard for subagent launches and other tools — **S** — SHIPPED

**Goal.** A subagent starts cold. Its prompt is the best description of an
action the session produces, and the guard never sees it.

**Design.**

- Extend the PreToolUse matcher in `_HOOK_SPECS["guard"]` to
  `Bash|Edit|Write|MultiEdit|Task|Agent`. Both `Task` and `Agent` are
  included because the subagent tool has carried both names across
  harness versions; confirm the current name by launching a subagent with
  the guard hook logging `tool_name` to `private/hook-log.jsonl` (WM-62)
  before relying on either.
- In `_hook_action_from_tool` (`cli.py:9402`): for `Task`/`Agent`, action
  = `tool_input.get("prompt") or tool_input.get("description") or ""`,
  truncated to 1200 chars; files = paths extracted with the existing
  `_paths_from_text` (`cli.py:6472` region) from that prompt.
- Run the normal flow, but for these two tools the verdict is **always
  capped at `READ_FIRST`**: the hook injects `additionalContext` and never
  asks. Rationale: a subagent launch is not itself an irreversible action;
  the subagent's own tool calls will hit the guard.
- Add the subagent case to `_hook_surfacing_matches` unchanged.
- Existing installs: `install_claude_hooks` rewrites the command only when
  it generated it; it must also update the `matcher` on an entry it owns
  (marker present) when the matcher differs. Add that to `_mut` and a
  test.

**Tests**: a `Task` payload whose prompt names a file with a
do-not-retry attempt → `additionalContext` present, no
`permissionDecision`; matcher upgrade on re-install; an unowned entry's
matcher is left alone.

---

### 0.6 Phase 1: what shipped, and where it differs from this plan

Phase 1 is implemented. New modules: `breadcrumbs/transcript.py`,
`breadcrumbs/hooks_common.py`, `breadcrumbs/hooks_prompt.py`,
`breadcrumbs/hooks_compact.py`; new tests: `tests/test_transcript.py`,
`tests/test_hooks_phase1.py`, with the shared transcript builders in
`tests/_jsonl.py`. No schema change — Phase 1 writes only jots, which
schema 2 already defined.

Seven departures from what this document specified. Read these before Phase 2.

1. **`mine()` returns `(candidates, entries_read)`, not just candidates.** The
   caller needs to know how far the miner got to store its cursor, and deriving
   it from `len(entries)` at the call site would have put the same arithmetic in
   three hooks. `mine_transcript_into_jots()` wraps read, mine, write and cursor
   into the one call every hook actually makes.
2. **The post-compaction preamble lists the session's live jots, not the
   marker's.** The plan said to list what `PreCompact` just mined. A compaction
   that finds nothing new — because the Stop hook already mined the same range —
   would then report "nothing salvaged" while the inbox held a dozen candidates
   from that very session. What the model needs is what it can act on, not which
   firing wrote it. The marker is still written (and still written when nothing
   was mined, because "compacted and nothing survived" is a different fact from
   "no compaction happened"); it is now only the signal that a compaction
   occurred.
3. **Candidates carry a `title` separate from their note**, and `write_jot`
   grew `title` and `evidence` parameters to take them. Without it a churn
   candidate displayed as "Repeated edits suggest a fragile area…" in every
   listing, with the file name only visible inside the id.
4. **`SubagentStop` keys its jots to the parent `session_id`.** The plan did not
   say. A subagent's own id dies with it, so keying to that would make the
   candidates unreachable by the Stop hook's "what did this session produce"
   query — written, and never offered to anyone.
5. **The extraction turn's "already asked" check covers the jots it showed, not
   the whole session.** Same intent, but scoped to what was actually listed, so
   a candidate mined *after* a prompt fired is still offered next time.
6. **`redact_secrets` uses the blocking half of the secret table only.** The
   high-entropy heuristic is warn-only for `scan-secrets` precisely because it
   has no structure behind it; using it here would silently drop candidates that
   merely cite a build hash.
7. **A failing command that passes on a bare retry is not an attempt.** The plan
   required an edit between the two; this makes the reason explicit — it passed
   with nothing changed, which is a flaky test, not a fix, and recording it as
   "X failed until 0 files changed" would be a false claim in the store.

Two notes for Phase 2: `cli._hook_guard_advisory_seen` is now a thin shim over
`hooks_common.advisory_seen` (the name stays because tests and the docs know the
state by it), and `_HOOK_SPECS` gained no third tuple element — the matcher was
already the second.

---

## Phase 2: Retrieval by relevance

### WM-20 A task-relevant packet — **M** — SHIPPED

**Goal.** `build_resume_packet(task=…)` scopes only `likely_files`. Scope
every list section by relevance when a task is known, and keep a recency
floor so brand-new records still show.

**Design.** In `build_resume_packet` (`cli.py:5519`) and `_bound_packet`
(`cli.py:5755`):

- When `task` is given: run `search(memory_dir, root, task,
  include_ideas=False, min_keyword=1)` once and build `score_by_id`.
- For each of `active_decisions`, `failed_attempts`, `known_traps`,
  `open_questions`, `verifications`: order = the top `RECENCY_FLOOR = 3`
  by recency (current order), then the remaining items by `score_by_id`
  descending, then the rest by recency. Items with score 0 after the floor
  are still listed (nothing is hidden by relevance; caps and budget still
  apply), so the change is ordering only. Traps and questions need an id
  to score by: `load_traps` items already carry `id`; questions carry `id`
  from `load_open_questions`.
- Record `ordering: "relevance"` or `"recency"` in the packet dict and
  render it in the header line after `## Project`:
  `_(sections ordered by relevance to: <task>)_`.
- The hook path: WM-10 does not build a packet; leave it. But
  `_hook_session` for `source: compact` (WM-12) passes the last prompt as
  `task`, so the post-compaction packet is relevance-ordered.
- `crumb resume --task` already prints only and does not overwrite the
  committed packet; keep that.

**Tests** in `tests/test_resume.py`: with a store of 20 decisions where
one old decision cites the task's file, `--task` lists that decision
within the first 4 lines of Active Decisions while the 3 newest stay
first; without `--task` order is unchanged; `ordering` is in `--json`.

### WM-21 Progressive disclosure: `crumb show` and generic MCP resources — **S** — SHIPPED

**Goal.** Packets and hook injections should carry one line per record and
a way to fetch the body. Only decisions and attempts have MCP resources.

**Design.**

- `crumb show <id> [--json]` prints a record body (frontmatter + body for
  directory records; the block for a trap or question; the jot note).
  Resolve by id prefix: `dec_`, `att_`, `ver_`, `idea_`, `ses_`, `jot_`,
  `trap_`, `q:`. Exit 1 when not found. Use the existing resolvers in
  `set_record_status`/`set_trap_status`/`set_question_status` to find the
  file; factor a `find_item(memory_dir, id) -> dict | None` helper that
  returns `{kind, path, text, meta}` and reuse it in `mark-status`.
- MCP: resource template `memory://records/{id}` returning the same text,
  plus `memory://traps/{id}`, `memory://questions/{id}`,
  `memory://verifications/{id}`, `memory://inbox/{id}`. Add to
  `TEMPLATE_RESOURCES`, bind in `mcp_server.py`, extend the URI assertion
  test. Tool `memory_show(id)` returning `{ok, kind, text}` for clients
  without resource support.
- Update the hint line in WM-10 and the packet footer: `Fetch a body:
  crumb show <id>`.

**Tests**: `show` for each id kind; unknown id exits 1 with
`CRUMB-ERROR`; MCP resource text equals CLI text.

### WM-22 Traps and questions as one file per record — **L** — SHIPPED (needs WM-01)

**Goal.** `known-traps.md` reached 167 KB and 77 active traps in a field
store and is parsed in full on every hook firing. This is the recorded
idea `idea_20260905_split-known-traps-md-into-traps-id-md-with-a-generated-one`.

**Design.**

- New directories `traps/` and `questions/`; one file per record with the
  standard frontmatter (`type: trap` / `type: question`, ids `trap_<slug>`
  and `q_<slug>`) and body sections matching today's bullets: trap →
  `## Area / files`, `## Symptom`, `## Why`, `## Safe approach`,
  `## Verification`, `## Last confirmed`; question → `## Question`,
  `## Why it matters`, `## Needs`. Status lives in frontmatter, using the
  existing vocabularies. Add both to `DIR_TYPES` and `BODY_SECTIONS`.
- **Question ids change** from `q:<slug>` to `q_<slug>`. Accept both on
  input everywhere (`mark-status`, `show`, MCP); print the new form.
- Migration step (WM-01) `3`: for every block in `known-traps.md` and
  `open-questions.md`, write the file, then replace the singleton's
  content with a header and a generated index line per record:
  `- trap_<slug>: <summary> (<status>)`. Mark both singletons with the
  generated-projection comment used by `resume-packet.md`. Keep them
  because cloud agents without a CLI read them (README "Plain-file
  fallback"); they become projections rebuilt by `reindex_projections`.
- Readers: `load_traps`, `active_traps`, `load_open_questions`,
  `set_trap_status`, `set_question_status`, `set_trap_confirmed`,
  `_build_guard_prefilter`, `_candidate_items`, `_item_from_trap`, the
  packet, `note("trap"|"question")`, `cmd_traps`, `validate` checks on the
  singletons. During the transition (store at schema 2), readers read the
  blocks; at schema 3 they read the directories and treat the singletons
  as projections. Implement as `traps_source(memory_dir) -> "blocks" |
  "files"` decided by `store_schema_version`.
- `SCHEMA_VERSION` to `3`. Update the template tree and `init`.
- The MCP resources `memory://known-traps` and `memory://open-questions`
  keep returning the singleton file (now the index) so existing clients
  see the same URI; add `memory://traps/{id}` from WM-21.

**Tests**: migration of a fixture store with 5 traps and 3 questions
produces 8 files, an index with 8 lines, and `validate` passes; every
reader returns the same items before and after migration (parametrise
over both `traps_source` values); `note trap` at schema 3 writes a file and
refreshes the index; `guard` verdicts on `fixtures/fixture-02` and
`fixture-03` are unchanged after migration (copy the fixture to a temp
dir, migrate, compare `--json` output minus timestamps).

### WM-23 SQLite FTS5 index as a disposable recall accelerator — **M** — SHIPPED

**Goal.** Bag-of-words scanning is fine to 300 records and gets slow and
narrow past that. `architecture.md` already reserves `index/` for a
disposable FTS or vector index. Build the FTS one with the standard
library and keep ranking deterministic.

**Design.**

- New module `breadcrumbs/ftsindex.py`. Database at
  `index/search.sqlite` (already gitignored).
- `fts_available() -> bool`: try `CREATE VIRTUAL TABLE t USING fts5(x)` in
  an in-memory connection; cache the answer. When false, every function
  is a no-op and `search` behaves as today.
- `build_index(memory_dir, root)`: table `items(id, kind, title, text,
  files, tags, stems)`; the `stems` column is the space-joined `_specific`
  output so FTS tokenisation matches ours. A `meta(inputs_hash)` table
  stores the `_inputs_hash` the index was built from. Called from
  `try_reindex_projections`; failures are swallowed (best-effort, like
  the projections).
- In `_candidate_items` (or a wrapper used by `search`): when the index
  exists **and** its `inputs_hash` equals the current one, and the corpus
  has more than `FTS_MIN_CORPUS = 200` items, use an FTS `MATCH` over the
  query stems (OR-joined) to fetch candidate ids, then load only those
  items plus every item with a file or tag hit for the query. Otherwise
  scan as today. Scoring is unchanged and still runs on the loaded items.
- `crumb reindex --fts` forces a rebuild; `crumb doctor` reports the index
  row: present, fresh, stale, or FTS5 unavailable.
- Equivalence guarantee: for any query, the set of items with score ≥
  `GUARD_NOISE_FLOOR` must be identical with and without the index. The
  FTS pass only narrows the candidate list to items that share at least
  one specific stem, file or tag, and an item scoring at the noise floor
  necessarily shares one.

**Tests** (skip the FTS parts with `skipUnless(fts_available())`): build,
freshness check, stale detection after a record write without reindex;
equivalence over `fixtures/fixture-10-many-sessions` plus a synthetic
500-record store for 20 queries; `doctor` row.

### WM-24 Store-local aliases for the stemmer — **S** — SHIPPED

**Goal.** `GUARD_STEM_ALIASES` has five entries. Each project has its own
vocabulary (a service nickname, a module and its acronym).

**Design.** `.project-memory/aliases.txt`, committed, one line per group,
whitespace-separated words that fold to the first word's stem:
`auth authn authz login`. Loaded once per process by `_stem` through a
small cache keyed by the file's mtime; merged over the built-in table.
Validate warns on a group with one word. `crumb search --explain` prints
the stems used for the query so a user can see why a synonym missed.
Reindex must include the file in `_inputs_hash`, since it changes what
the prefilter contains.

**Tests**: alias makes a query hit a record it did not before; malformed
lines are ignored; `_inputs_hash` changes when the file changes.

### WM-25 Related records — **S** — SHIPPED

**Goal.** Records that share files or specific stems should point at each
other, so `show` and the packet can say "see also".

**Design.** At reindex, compute for each active item the top 3 other
items by the existing `_score_item` overlap (score ≥ `GUARD_NOISE_FLOOR`)
and write `generated/related.json`: `{"<id>": ["<id>", …]}`. `crumb show`
prints a `See also:` line from it; the MCP `memory_show` includes
`related`. No frontmatter changes; the file is a projection and is stamped
with `inputs_hash` like the packet. Cost: O(n²) over specific-stem sets;
skip when the corpus exceeds 2000 items and say so in the file.

**Tests**: two records citing the same file relate to each other; a
superseded record is never listed; drift detection covers the new file.

---

### 0.7 Phase 2: what shipped, and where it differs from this plan

Phase 2 is implemented. New modules: `breadcrumbs/blockfiles.py` (traps and
questions as files), `breadcrumbs/related.py`, `breadcrumbs/searchindex.py`; new
tests: `tests/test_aliases.py`, `tests/test_show.py`, `tests/test_searchindex.py`,
`tests/test_blockfiles.py`, plus `RelevanceOrderingTests` in
`tests/test_resume.py`. `tests/_schema2.py` builds a schema-2 store, so the tests
that pin the block format still run against the shape an unmigrated store has.
**Record `schema_version` is 3.**

Eight departures from what this document specified. Read these before Phase 3.

1. **WM-23 is not FTS5.** It is a plain inverted index in sqlite
   (`postings(field, token, rid)`), in `searchindex.py`, flag
   `crumb reindex --search-index`, threshold `INDEX_MIN_CORPUS = 200`. FTS5
   tokenises text itself, and its tokens are not `_specific`'s stems: a record
   FTS5 missed could still score, which breaks the equivalence rule. Storing
   our own stems as postings makes the narrowing exact by construction. It
   also works on Python builds compiled without FTS5.
2. **The index computes ubiquity itself.** `_ubiquitous_stems` depends on
   document frequency across the *whole* corpus. Computing it over the
   narrowed candidates changed which stems were ubiquitous, and so the
   scores. The index stores enough to answer document frequency for the query's
   stems, which is the only part scoring reads.
3. **The index's freshness check is a stat fingerprint first.** `_inputs_hash`
   reads every file. On a 500-record store that cost as much as the scan the
   index saves. A fingerprint of names, sizes and mtimes decides "fresh"
   cheaply, and `_inputs_hash` runs only when the fingerprint differs (a
   checkout that changed mtimes but no content).
4. **WM-25 does not use `_score_item`.** That score decays by age and by branch,
   so two machines would compute different neighbours and the committed
   `related.json` would churn on every reindex. `related.pair_score` is the pure
   overlap part: files ×6, tag stems ×4, non-ubiquitous specific stems ×1,
   ties broken by id.
5. **WM-22 keeps loose prose in a `## Notes` section, and `Last confirmed` is
   frontmatter** (`last_confirmed`), not a body section. A block's bookkeeping
   bullets (`Status`, `Last confirmed`, `Superseded by`, `Opened`) become
   frontmatter. Everything that is neither a known bullet nor bookkeeping
   (free prose, the provenance comments `mark-status` leaves) goes to `Notes`,
   because "every line of every block is kept" was the migration's one hard
   rule. There is no `traps_source()`. `blockfiles.uses_files()` reads the
   manifest version, never what is on disk.
6. **WM-22 files are undated.** Every other record type is
   `YYYY-MM-DD-<slug>.md`. A date in a trap's filename would put a date in its id,
   and trap ids are cited everywhere. `derive_identity` takes an undated stem for
   `trap` and `question` (`UNDATED_ID_PREFIX`).
7. **At schema 3 a hand-written block is adopted, not ignored.** The plan made
   the singletons pure projections. But people and older tool versions still
   append `## trap_…` blocks, and a branch that has not migrated merges them
   in. Regenerating the index would silently delete them. So readers union
   files with blocks (the file wins on an id clash), and the next reindex
   moves each block into its own file. A block whose id already has a *different*
   file is kept under the index and reported by `crumb audit` as
   `unadopted-block`. Merging two versions of a trap is a judgement call, and
   the tool does not make it.
8. **Aliases are reported by `audit`, not `validate`,** and the first group to
   claim a word keeps it. A malformed line is skipped, so the store is still
   valid. Validate is for invalid stores. First-group-wins means adding a line
   can never silently change what an older line did.

A bug the migration tests caught: a trap with no sections is stored with the
`_(not recorded)_` stub so its file parses. Rendering that stub back as a
bullet gave the migrated trap keywords (`record`) its block never had.
`blockfiles._flat` drops it.

Notes for Phase 3: `find_item` is the one resolver for any printed id. Use it
rather than adding a per-type lookup. WM-30's `expires_at` on traps and
questions is now plain frontmatter like every other type. Anything that writes a
trap or question must check `blockfiles.uses_files()`: at schema 3 it goes
through `blockfiles.write_trap` / `write_question`, and below schema 3 it uses
the block writers, as `cli.note` does.

---

## Phase 3: Lifecycle

### WM-30 Typed time-to-live — **M** — SHIPPED

**Goal.** Short-term memory must decay. `expires_at` exists and is never
set. `current.md`'s "days to two weeks" is a doc convention.

**Design.**

- Defaults, overridable in `manifest.yml` under a `ttl:` block
  (`ttl_jot_days`, `ttl_question_days`, …; flat keys because
  `load_manifest` parses flat `key: value`):

  | Type | Default | Effect when reached |
  |---|---|---|
  | jot | 14 days (`expires_at` set at write) | hidden from packet and `inbox`; `prune --inbox` may delete |
  | question | 45 days aging, no expiry | packet warning already exists at 21; add `crumb inbox`-style listing `crumb questions --aging` |
  | verification | 90 days | packet warning `verification <id> is 90+ days old; recheck (WM-31)`; still listed |
  | trap | 180 days since `Last confirmed` | existing `traps --stale` behaviour; add the same warning to the packet, capped 3 |
  | current.md items | 14 days since the file's last write | packet warning `current.md has not changed in N days; is Current Focus still true?` |
  | decision, attempt | none | unchanged |

- `expires_at` is set at write time only for jots (WM-03 already does)
  and for verifications with outcome `fixed` or `not_applicable`
  (90 days), because a settled verification is the type that silently goes
  stale. Actionable outcomes never expire.
- `expired_items(memory_dir) -> list[dict]` in a new
  `breadcrumbs/lifecycle.py`; `crumb expired [--json]` lists them; the
  packet's existing `expires_at` warning stays.
- Expired records are hidden from the packet's list sections and from the
  guard's **live** set (they go to `history`, like superseded), never
  deleted.

**Tests** in `tests/test_lifecycle.py`: each row of the table with a
temp store and monkeypatched clock (`_dt_sort_key`/`now_iso` are the
seams; add `_now()` indirection if needed); manifest overrides work; an
expired verification is in guard's history and not its live matches.

### WM-31 Evidence-driven staleness — **M** — SHIPPED

**Goal.** A record whose evidence points at a file that no longer exists,
or a verification whose command can be rerun, should tell you so instead
of waiting for a human to notice.

**Design.**

- **File evidence check** in `compute_staleness`: for every active
  decision/attempt/verification with `evidence: [{type: file, ref}]`,
  check `ref` (path part before any `:line`) against `HeadTree`
  (already computed; it lists files in HEAD). Missing → warning
  `<id> cites <ref>, which is not in HEAD — verify the record still
  applies`. Cap 5. **Do not** change guard scoring; decision
  `dec_20260905_path-extraction-is-structural-and-a-mined-path` rejected
  existence-on-disk for scoring on purpose. A warning is a different
  consumer.
- **Recheck**: `crumb verify --recheck <ver id> | --all [--yes]`. For each
  verification with `evidence: [{type: command, ref}]`: print the command,
  require `--yes` or an interactive `y` (never run commands unattended
  from a hook or MCP), run it with `subprocess.run(shell=True, timeout=300)`
  in the project root, and write a **new** verification record with the
  same subject, `method: runtime`, outcome `fixed` on exit 0 else `open`,
  evidence `{type: command, ref}` plus a `Notes` line with the exit code
  and the last 3 output lines (redacted). Mark the old one
  `superseded_by` the new id. The MCP tool `memory_verify` gets no
  recheck; running arbitrary commands is a CLI-only, human-confirmed act.
- `audit` finding `evidence-missing-file`, `AUDIT_WARN`, same content as
  the packet warning.

**Tests**: record citing a deleted file warns; citing an existing file
does not; `--recheck --yes` on `true` produces `fixed`, on `false`
produces `open` and supersedes; without `--yes` and no TTY exits 2 having
run nothing.

### WM-32 Near-duplicate detection on write — **M** — SHIPPED

**Goal.** Two decisions saying the same thing coexist untouched. Catch it
at write time, where the author can still choose supersede or append.

**Design.**

- `find_near_duplicates(memory_dir, rtype, title, sections, files, tags)
  -> list[dict]` in `breadcrumbs/lifecycle.py`. Candidate set: active
  items of the same type (traps with traps, questions with questions).
  Similarity = weighted Jaccard over `_specific(title + body)` with
  `+0.15` for each shared declared file and `+0.1` for each shared tag,
  capped at 1.0. Threshold `DUP_THRESHOLD = 0.6`. Return `[{id, title,
  similarity}]` sorted descending, max 3.
- **CLI writers** (`remember`, `note trap|question|idea`, `verify`,
  `jot`): when duplicates are found and none of `--supersedes <id>`,
  `--allow-duplicate` was passed, refuse with exit code **3** and message
  `CRUMB-ERROR: <cmd>: looks like <id> (0.71 similar) — pass --supersedes
  <id> to replace it, or --allow-duplicate to write anyway`. `--supersedes`
  writes the new record with `supersedes: [id]` and marks the old one
  `superseded` with `superseded_by`. Jots use a lower bar: only refuse
  when similarity ≥ 0.9 (a jot is cheap and repetition is the signal).
- **MCP writers** (`memory_record`, `memory_note`, `memory_verify`,
  `memory_jot`): return `{ok: false, error: "near-duplicate",
  duplicates: [...]}` unless `allow_duplicate: true` or `supersedes: id`.
- The Stop-hook extraction prompt (WM-15) mentions the flag in one line so
  an agent that hits exit 3 knows what to do.
- `crumb audit` finding `near-duplicates`, `AUDIT_WARN`: pairs of active
  same-type items over the threshold, capped at 10 pairs. This is the
  retrospective sweep for stores that predate the gate.

**Tests** in `tests/test_lifecycle.py`: identical title and body → refused
with exit 3 and the id in the message; `--supersedes` writes and
supersedes; `--allow-duplicate` writes; different topics → no refusal;
MCP returns the structured error; audit lists a planted pair on a fixture
copy; the `fixtures/` stores produce **no** `near-duplicates` finding as
they are (adjust the threshold or the fixture if they do, and say which
in the commit message).

### WM-33 Consolidation — **M** — SHIPPED (after WM-32)

**Goal.** Give a human or agent a guided way to merge a cluster of
near-duplicates or roll up a supersede chain, with no automatic merging.

**Design.** `crumb consolidate [--type T] [--json]` prints clusters
(connected components over the WM-32 pair graph) with ids, titles and
similarities. `crumb consolidate --merge <id> <id>... --title "…" [--set
…]` writes one new record of the same type whose sections are the
concatenation of the sources' non-empty sections in date order, each
prefixed by `_(from <id>)_`, with `supersedes: [ids]`, evidence = the
union, tags = the union, confidence = the minimum; then marks every
source `superseded` with `superseded_by`. Refuses mixed types. Never
touches sessions. Prints the new id and a reminder to edit the merged
body.

**Tests**: two planted duplicates merge into one record whose
`supersedes` lists both; sources are superseded; mixed types refuse with
exit 2; `guard` no longer lists the sources as live.

### WM-34 Contradiction detection — **M** — SHIPPED

**Goal.** Memory that argues with itself is worse than no memory. Only
focus-versus-verification conflicts are detected today.

**Design.** In `breadcrumbs/lifecycle.py`, `find_contradictions(memory_dir)
-> list[dict]`, computed at reindex into `generated/conflicts.json` and
rendered as packet warnings (cap `PACKET_CONFLICTS_MAX = 3`) and an audit
finding `possible-contradiction` (`AUDIT_WARN`, cap 10). Two rules only;
both are overlap heuristics and are worded as questions:

1. **Attempt versus later decision.** An active attempt with a non-empty
   `Do Not Retry Unless` section, and an active decision created after
   it, with similarity (WM-32's measure over the attempt's `Tried` and the
   decision's `Decision` sections) ≥ 0.5 or a shared declared file. Message:
   `decision <id> may do what attempt <id> says not to retry — confirm
   the retry condition was met, or mark one stale`.
2. **Decision versus decision.** Two active decisions with similarity ≥
   0.7 created more than 7 days apart and neither superseding the other.
   Message: `decisions <id> and <id> overlap heavily — supersede one or
   consolidate (crumb consolidate)`.

A pair already listed by `near-duplicates` is not listed again here.

**Tests**: planted attempt-then-decision on the same file warns; the same
with the attempt superseded does not; two overlapping decisions 10 days
apart warn, 2 days apart do not; fixtures produce none.

### WM-35 Session rollup — **S** — SHIPPED

**Goal.** `prune` deletes machine snapshots but nothing summarises them,
so the audit's `sessions-growth` advice is "promote and prune by hand".

**Design.** `crumb rollup sessions --before YYYY-MM-DD [--dry-run]`:
collect session records older than the date that are machine snapshots or
have a placeholder Next Action; write one session record titled
`rollup: <first date>..<last date> (<N> sessions)` whose `Work Completed`
is the concatenated non-empty `Work Completed` lines (one per source, with
the source date), `Next Action` = `(rolled up)`, and `supersedes` = the
source ids; then delete the sources. Human-authored sessions (real Next
Action) are never rolled up. `audit`'s `sessions-growth` message names the
command.

**Tests**: 10 snapshots roll into one record with 10 `supersedes`; a
human session survives; `--dry-run` deletes nothing; the Stop-hook
redundancy check still works after a rollup (the newest record is
untouched because `--before` excludes it).

---

### 0.8 Phase 3: what shipped, and where it differs from this plan

Phase 3 is implemented. New modules: `breadcrumbs/lifecycle.py` (all six items)
and `breadcrumbs/lifecycle_cmds.py` (the `expired`, `questions`, `consolidate`,
`rollup` and `verify --recheck` command surface, imported only when one of them
runs). New tests: `tests/test_lifecycle.py`. No schema change.

Nine departures from what this document specified. Read these before Phase 4.

1. **Expiry is computed, not a status.** An expired record keeps `status:
   active`. Items carry an `expired` flag, guard's liveness test checks it, and
   the packet filters on it. Writing a new status would have needed a writer
   running on a clock, and "expired" is a fact about now, not about the record.
   The clock is one seam, `cli._now()`.
2. **"Missing" means neither on disk nor in HEAD (WM-31)**, not "not in HEAD".
   A file the author just created is uncommitted and plainly not missing. The
   check lives in packet assembly and `lifecycle.audit_findings`, not in
   `compute_staleness`, so audit gets its own `evidence-missing-file` finding
   rather than a `staleness` line.
3. **Recheck:** `--recheck` is repeatable and `--all` is its own flag. A
   verification with several commands is `fixed` only if every one exits 0, and
   a timeout counts as `open`.
4. **The duplicate measure has two guards the plan did not.** A pair needs at
   least three shared stems (Jaccard on five words is noise), and the file and
   tag bonus is capped at 0.2. Uncapped, four shared files alone cleared the
   0.6 threshold on this repository's own store at 0.24 text overlap: two
   related decisions, not duplicates. Section headings are excluded from the
   text, because every record of a type shares them.
5. **The gate is off at the core and on at the edges.** `note()` and `verify()`
   take `dedupe=False` by default. `crumb` and the MCP tools pass it on.
   Internal writers (inbox promotion, migrations, the transcript miner) write
   what they were given. An exact repeat (same question text, same trap slug)
   keeps its old exit-1 "reopen it" error, which is more useful than "similar".
6. **Superseding a trap or question:** the new file carries no `supersedes`
   key (the block writer has nowhere to put one), and a question retires as
   `closed` with `superseded_by`, since its vocabulary has no `superseded`.
   Jots take `--allow-duplicate` only. Superseding a jot is promotion.
7. **Consolidate merges decisions, attempts, verifications and ideas only.**
   Traps and questions have their own writers and retirement, and a merged
   trap would need the block shape at schema 2.
8. **WM-34 rule 2 wins over the near-duplicate finding, not the reverse.** Two
   decisions at 0.7 are always also near-duplicates at 0.6. The plan's "a pair
   already listed by `near-duplicates` is not listed again" would have hidden
   rule 2 forever. The contradiction is the more specific finding, so the
   near-duplicate one is suppressed for that pair.
9. **The rollup is dated at its last source (WM-35).** Stamped "now", it would
   become the newest session record, and the Stop hook diffs from the newest
   session's commit. Every commit made since the last kept snapshot would
   silently fall out of the next capture. `created_at`, `updated_at`, `branch`
   and `commit` are pinned to the last snapshot it replaces, and earlier
   rollups are never rolled up again.

Notes for Phase 4: `lifecycle.find_near_duplicates` is the similarity measure
to reuse for promotion candidates (WM-40), and `lifecycle.mark_superseded` is
the one way to retire a record in favour of another. Exit code 3 is taken.

---

## Phase 4: The bridge to long-term memory

### WM-40 `crumb promote` — **M** — SHIPPED

**Goal.** A decision that has proven durable belongs in the agent's
permanent instructions. Today the adapter block is a signpost only and no
command moves content between tiers.

**Design.**

- A **second managed block** in the adapter file, separate from the
  signpost block so `--remove-integrations` and the bloat check keep their
  meaning:
  ```
  <!-- >>> breadcrumbs promoted rules (managed by `crumb promote`) — edit with crumb promote/demote, not by hand >>> -->
  ## Project rules promoted from memory
  - <one-line rule>. _(why: <one-line rationale>; source: `<record id>`)_
  <!-- <<< breadcrumbs promoted rules <<< -->
  ```
  Constants `PROMOTED_BEGIN`/`PROMOTED_END`; reuse `rewrite_managed_block`
  (`cli.py:409`).
- `crumb promote <id> [--to CLAUDE.md|AGENTS.md] [--rule "…"]`:
  - Accepts decision, attempt and trap ids. Rule text defaults to the
    record title for a decision, `Do not <title>; <Do Not Retry Unless
    first line>` for an attempt, `<Safe approach>` for a trap. `--rule`
    overrides. The rationale line is `_decision_rationale` / the attempt's
    `Why It Failed` first line / the trap's `Why` bullet, cut to 160 chars.
  - Target file: `--to`, else the first of `CLAUDE.md`, `AGENTS.md` that
    exists (`ADAPTER_FILENAMES`, `cli.py:7654`); none → exit 2 with a hint
    to create one. Never create the file.
  - Writes the bullet (replacing an existing bullet with the same
    `source:` id), then sets frontmatter `promoted_to: <filename>` and
    `promoted_at: <iso>` on the record (add both to `FRONTMATTER_ORDER`
    after `expires_at`; for traps in the block shape, a `- Promoted to:`
    bullet). Status stays `active`: the record is still true, it is just
    also long-term now. Reindex.
  - Refuses a record that is not `active`, or is `confidence: low`, with
    exit 2 and a reason.
- **Readers.** The packet omits promoted records from `Active Decisions`,
  `Failed Attempts` and `Known Traps` (they are already in the model's
  context via the instruction file) and adds one line at the end of the
  section: `_(N promoted to CLAUDE.md — see its "Project rules promoted
  from memory")_`. `guard` still uses them at full weight. `search` lists
  them with a `[promoted]` tag.
- **Audit**: the promoted block is measured against `ADAPTER_BLOAT_CHARS`
  separately (finding `promoted-bloat`); the §16.13 "signpost duplicates a
  record" check exempts the promoted block (its bullets intentionally
  mirror records).
- The `instruction-like` scan in audit scans records, not adapter files;
  no change needed, but add a test that proves a promoted rule containing
  "never" does not create an audit warning.

**Tests** in `tests/test_promote.py`: promote a decision → bullet present
once, frontmatter set, packet omits it and prints the count, guard still
matches it; promote again → still one bullet (idempotent); promote a
superseded record → exit 2; no adapter file → exit 2 and nothing
created; block stays under the bloat threshold with 20 promoted rules
(or the audit finding fires and the test asserts it does).

### WM-41 `crumb demote` — **S** — SHIPPED

`crumb demote <id> [--reason …]` removes the bullet whose `source:` is
the id, clears `promoted_to`/`promoted_at`, reindexes. If the block
becomes empty, remove the block entirely. `mark-status <id>
superseded|stale|rejected|disputed` on a promoted record **also demotes**
automatically and says so, because a retired rule must not stay in the
long-term file. Tests: demote removes exactly one bullet; retiring a
promoted record removes its bullet; the block disappears when empty.

### WM-42 Promotion and demotion suggestions — **S** — SHIPPED (after WM-02)

In `audit`:
- `promote-candidate` (`AUDIT_INFO`): an active decision or attempt,
  `confidence` not low, older than 60 days, surfaced in ≥ 5 distinct
  sessions per `private/usage.json` (extend WM-02's shape with
  `sessions: [ids]`, bounded to 20), not promoted. Message names the
  command.
- `demote-candidate` (`AUDIT_WARN`): a bullet in the promoted block whose
  `source:` id is missing, or whose record is not active. WM-41's
  auto-demote should make this rare; this catches hand edits.
- `doctor` prints the count of promoted rules and the block size.

### WM-43 Long-term drift check — **S** — SHIPPED

`crumb audit` compares each promoted bullet's text with the current
default rendering of its source record; a mismatch (someone edited the
bullet by hand, or the record was retitled) is `promoted-drift`
(`AUDIT_INFO`) with the hint `crumb promote <id>` to re-render. Tests:
hand-edit a bullet → finding; re-promote → clears.

---

### 0.9 Phase 4: what shipped, and where it differs from this plan

Phase 4 is implemented in one new module, `breadcrumbs/promote.py`, which holds
the block, `promote`, `demote`, the audit checks, the doctor summary and the
command surface. Tests are in `tests/test_promote.py`. No schema change.

Seven departures from what this document specified. Read these before Phase 5.

1. **A trap's rule is `<summary>: <safe approach>`**, not the safe approach
   alone. "Stop the daemon first" says what to do but not when; the summary is
   the when. An attempt's rule is `Do not retry: <title> — unless <condition>`
   rather than `Do not <title>`, because titles are noun phrases ("Stopping the
   gradle daemon") and "Do not stopping…" is what the literal template
   produced.
2. **`promoted_rule` is a third frontmatter key.** WM-43 compares a bullet
   with "the current default rendering". A rule written with `--rule` would
   then report drift forever. The override is stored, and the drift check
   renders with it.
3. **Retiring through any path demotes.** The hook is in `set_record_status`
   itself (the old body is now `_set_record_status`), so `mark-status`, MCP
   `memory_mark_status`, `--supersedes` on a writer and `consolidate --merge`
   all demote. The plan named only `mark-status`.
4. **`demote` works on an id whose record is gone.** Deleting a record by
   hand is exactly what leaves an orphan bullet. The demote-candidate finding
   names the command, so the command has to accept the id.
5. **Promoting to the other file moves the rule.** `--to AGENTS.md` on a rule
   already in `CLAUDE.md` removes it there, so one source never has two rules.
6. **No MCP tool.** The plan did not say either way. An agent writing its
   own permanent instructions through a tool call is the persistence step of
   a prompt injection. Promotion is a person's decision, or at least a
   command a person can see.
7. **`--remove-integrations` leaves the promoted block.** It removes the
   signpost it installed. The promoted rules are the project's rules now, and
   deleting them on uninstall would be data loss.

Notes for Phase 5: `promote.promoted_to()` answers "is this promoted" for a
record, a trap dict and a `find_item` result alike. A scope field (WM-50)
should decide whether a user-scoped record can be promoted into a project
file at all. The answer is probably no.

---

## Phase 5: Scope and multi-agent

### WM-50 Per-branch handoff — **M** — SHIPPED

**Goal.** `handoff.md` and `current.md` are singletons. Two agents on two
branches overwrite each other's next action, and a feature-branch handoff
is wrong for `main`.

**Design.**

- New directory `handoffs/`, committed. `capture session` writes
  `handoffs/<branch-slug>.md` (same sections as `handoff.md`, same
  metadata lines) when the current branch is not the repository's default
  branch (`git symbolic-ref refs/remotes/origin/HEAD`, falling back to
  `main`/`master` if present, else treat every branch as default). On the
  default branch it writes `handoff.md` as today.
- `build_resume_packet` picks the handoff for the current branch if it
  exists, else `handoff.md`, and says which in the `## Project` line:
  `handoff: handoffs/<slug>.md` or `handoff: handoff.md (no branch
  handoff)`. Branch mismatch warnings compare against the chosen file.
- `current.md` stays a singleton: it is the project's focus, not the
  branch's.
- `crumb prune --handoffs` deletes branch handoffs whose branch no longer
  exists locally or on `origin` and whose file is older than 30 days.
- Migration step: create `handoffs/.gitkeep`. `SCHEMA_VERSION` to `4`.
  Readers tolerate a missing directory.

**Tests** in `tests/test_multi_machine.py` or a new
`tests/test_handoffs.py`: capture on a feature branch writes the branch
file and leaves `handoff.md` unchanged; resume on that branch reads it;
resume on `main` reads `handoff.md`; prune removes an orphan.

### WM-51 Concurrent-writer safety — **S** — SHIPPED

**Goal.** Hooks from parallel sessions in one checkout write the same
store. A torn `handoff.md` or a lost jot is plausible.

**Design.** `breadcrumbs/lock.py` with a context manager
`store_lock(memory_dir, timeout=2.0)` using `os.open(path, O_CREAT |
O_EXCL)` on `private/.write-lock` with the pid and time inside; stale
locks older than 60 s are broken. Wrap every canonical write (the writers
listed in §1) and `reindex_projections`. Hooks pass `timeout=0.5` and on
timeout skip the write silently (a hook never blocks the host). CLI
commands wait the full timeout then fail with exit 1 and `CRUMB-ERROR:
store is locked by pid N`. Tests: two threads writing jots produce two
files; a stale lock is broken; a hook with a held lock prints `{}` fast.

### WM-52 Record scope — **S** — SHIPPED

`scope` is already in frontmatter and always `project`. Allow
`scope: branch` on jots (default for hook-written jots) and on
verifications (`--scope branch`), storing the branch in the existing
`branch` key. The packet and the guard's live set include branch-scoped
records only when their `branch` equals the current branch; elsewhere
they are history. `search` always finds them. Tests: a branch-scoped jot
disappears from the packet after `git checkout -b other`.

---

### 0.10 Phase 5: what shipped, and where it differs from this plan

Phase 5 is implemented in `breadcrumbs/handoffs.py` (WM-50) and
`breadcrumbs/lock.py` (WM-51), with WM-52 spread through the readers in
`cli.py` and `inbox.py`. New tests: `tests/test_handoffs.py`,
`tests/test_lock.py`, `tests/test_scope.py`. **Record `schema_version` is 4.**

Eleven departures from what this document specified. Read these before Phase 6.

1. **`crumb prune handoffs`, not `crumb prune --handoffs`.** `prune` already
   takes what to prune as a positional (`sessions`, `jots`), and one command
   with two grammars is worse than a small deviation from the plan.
2. **A branch's first handoff starts from `handoff.md`.** A branch is usually
   cut mid-thought from the default branch. Starting its handoff empty would
   drop the Current Focus the session was just given.
3. **The lock is taken once per command, at dispatch**, not by wrapping each
   writer. Every writer reindexes, so per-writer locking would have taken the
   lock several times per command. A command-level lock also covers the
   read-modify-write sequences that span several writers (capture writes a
   session, the handoff, `current.md` and every projection). The lock is
   re-entrant within a thread for the writers that are also called directly.
4. **The lock also covers threads and MCP.** An in-process lock per store
   serialises threads, since two threads of one process share a pid and the
   lock file alone cannot tell them apart. The MCP writers take it too and
   return `{ok: false, error}` when it is held. On POSIX, a lock whose process
   is gone is broken at once instead of after 60 s; on Windows `os.kill(pid, 0)`
   is not a probe, so the age rule alone applies there.
5. **The `session` and `guard` hooks never take the lock.** One boots a
   session and the other runs before every tool call. Neither writes
   canonical records, and making either wait on a parallel session's capture
   would stall the agent for a lock it does not need.
6. **Branch scope applies to any record that carries it**, not just jots and
   verifications. `remember --scope` already accepted free text. A decision
   someone scoped to a branch is filtered the same way, since two readers
   disagreeing about the same field would be a bug. Only jots and
   verifications get the `--scope` choice and the hook default.
7. **"Elsewhere" is never true without a branch to compare.** With no git,
   on a detached HEAD, or for a record with no recorded branch, a
   branch-scoped record stays live. This matches guard's existing
   branch-mismatch rule, which already ignores a detached HEAD.

Four more, found while documenting it and fixed before the phase closed:

8. **A branch whose name is not already a slug gets a hash suffix**
   (`feature/parser-rewrite` → `handoffs/feature-parser-rewrite-<6 hex>.md`).
   Slugging is lossy, and two branches sharing one handoff file is the overwrite
   WM-50 exists to stop.
9. **A branch's first handoff inherits `handoff.md`'s Current Focus only.** Copying
   the whole file passed off the default branch's Next Action under the new
   branch's fresh date, branch and commit lines, which also hid it from the
   age and branch-mismatch warnings.
10. **The lock is decided per invocation, and `resume` does not take it.** Listings
    (`inbox`, `traps`, `consolidate` without `--merge`) never wait. `resume` only
    regenerates projections, each replaced atomically, and a session must not
    fail to start because another is capturing. The prompt hook locks only its
    correction write, so contention never costs the injection.
11. **The holder heartbeats the lock and records its host.** A writer running
    past 60 s (a migration backup, a search-index build) kept losing its lock.
    A pid is only checked on the host that wrote it. Breaking a stale lock is
    itself exclusive (a short-lived `.write-lock.break` file and a re-check
    under it), so two waiters can never both proceed, and `init --force` keeps
    its own lock file while it replaces the rest of the store.

Notes for Phase 6: the lock means an eval harness that runs parallel sessions
against one store will see skipped hook writes when they collide. Count them
(`{}` from a writing hook) rather than treating them as lost memory.

### 0.11 Phase 6: what shipped, and where it differs from this plan

Phase 6 is implemented in `evals/` (WM-61), `breadcrumbs/usage.py` (WM-60) and
`breadcrumbs/hooklog.py` with `docs/field-test.md` (WM-62). New tests:
`tests/test_evals.py`, `tests/test_hooklog.py`, and a WM-60 block in
`tests/test_usage.py`. No schema change.

Departures from what this document specified. Read these before Phase 7.

1. **Stores are built, not copied.** Each suite is a `store.crumb` file of
   CLI commands, one per `@DATE` line, run through `crumb.main` with the clock
   pinned to that date. A copied store would drift away from the writers it is
   meant to measure, and 100-odd committed record files are harder to review
   than one script. Ids and ages are reproducible. The fixtures stay what they
   were: small, single-purpose regression stores.
2. **The packet is ranked by its own task score.** The packet has no single
   ranked list. Its sections are each ordered, with the newest three pinned
   first whatever the task is. The eval ranks the records the bounded packet
   kept by `cli.task_relevance_scores`, the score `_order_by_relevance` sorts
   by, so the two cannot drift apart. The recency floor is a reading-order
   rule, not relevance, so it is not what is measured.
3. **Guard is a third system**, for tasks that name a `verdict`. The two
   field-review cases (`git status` versus `npm test`) are verdict cases, not
   retrieval cases. A `quiet` metric covers control tasks (`expect: []`),
   where the right answer for the prompt hook is to say nothing.
4. **Precision counts what was shown.** precision@5 is hits over what the
   system returned (at most 5), not over 5. A hook that shows one right record
   and stops scores 1.0, not 0.2, because quiet is the behavior the prompt
   hook is built for. Showing nothing when something was expected scores 0.
5. **The first run found two bugs, fixed in this phase.** The prompt hook
   injected superseded, stale, expired and answered records. And a query too
   short to reach guard's two-keyword floor (`npm test`, where "test" is
   generic) could match nothing on text. A record whose title holds every word
   of such a query now passes the gate. Prompt precision@5 went from 0.57 to
   0.66, recall@5 from 0.84 to 0.87, and reject hits fell from 4 to 1.
6. **Decay needs history.** "Zero surfacings in the last 180 days" can only
   be said after 180 days of counting, so `usage.json` gained `started_at`.
   Files from before it fall back to their oldest `last_surfaced_at`, which
   can only understate coverage. Promoted records never decay, because the
   packet hides them on purpose. A trap confirmed inside the window is left
   out too. A record reported as `decay-candidate` is not also reported as
   `never-surfaced`.
7. **The hook log is written by a wrapper, not by each handler.** `cmd_hook`
   runs every handler through `hooklog.run_logged`, which times it, reads the
   outcome off the JSON it printed, and passes that output through unchanged.
   Handlers only add detail (`hooklog.note`). A new hook is logged without
   code of its own. The log is trimmed back to 4000 lines once it passes 5000,
   so a long session does not rewrite it on every tool call.
8. **The field test is written but has not run.** It needs a real session on a
   real store. `q_should-the-extraction-turn-also-fire-on-precompa-ebd583`
   stays open until it has.

Still open, measured and left alone:

- Guard gives PROCEED for `npm test` against a trap titled for it. Since the
  0.1.10 field test, a trap that matches only on text cannot floor a verdict.
  Re-tuning that without field data would re-open the fatigue that rule closed.
  `docs/field-test.md` asks the question.
- Synonyms (`brand colors` versus a Tailwind theme decision), identifiers
  (`VITE_API_URL` is one token, so it never meets `vite`), and generic verbs
  (`upgrade ruff`) are the remaining prompt-hook misses. §3 open decision 3
  (embeddings) now has a baseline to be judged against.
- The packet's loose task score (one shared word) ranks a status-page decision
  into the top 5 for "add a refunded order status". It only orders and never
  hides, so this costs reading order, not recall.

Notes for Phase 7: WM-70 is conditioned on the hooks paying for themselves.
That is the field test's answer, not the evals'. Run `docs/field-test.md`
first.

---

## Phase 6: Measurement and evals

### WM-60 `crumb usage` report and decay — **S** — SHIPPED (after WM-02, WM-30)

Extend `crumb usage` with `--sessions` (distinct sessions per record) and
`--decay`: active decisions, attempts and traps with **zero** surfacings
in the last 180 days of usage data **and** older than 180 days are listed
as decay candidates with the exact `mark-status … stale --reason "not
surfaced in 180 days"` command for each. Never auto-retire: print the
commands, do not run them. Add `decay-candidate` (`AUDIT_INFO`) to audit,
capped 10.

### WM-61 Relevance eval harness — **M** — SHIPPED

**Goal.** Nothing measures whether retrieval improves. Phases 1 and 2
change ranking; a regression would be invisible.

**Design.**

- `evals/` directory (not shipped in the wheel; exclude in
  `pyproject.toml` package data). Each eval store is a copy of a fixture
  or a new synthetic store plus `tasks.yml`:
  ```yaml
  - task: "fix the flaky screenshot test on CI"
    expect: [trap_…, att_…]
    reject: [dec_…]        # must not appear in the top 5
  ```
- `evals/run.py` (stdlib only): for each task, run `build_resume_packet(task=…)`
  and `hooks_prompt.retrieve(prompt=task)`; compute precision@5 and
  recall of `expect`, count `reject` hits. Print a table and write
  `evals/baseline.json` with `--write-baseline`. Exit 1 when any metric
  falls below the committed baseline by more than 0.05.
- CI: a new job in `.github/workflows/ci.yml` runs `python evals/run.py`.
  Guard steps in CI must wrap `crumb guard` calls per
  `trap_guard-exit-code-in-ci`; the eval runner is plain Python so this
  does not apply, but say so in the workflow comment.
- Seed with 3 stores and at least 20 tasks total; include the field-review
  cases the CHANGELOG 0.2.0 section describes (screenshot-test trap versus
  a JSON-reading script; `git status` versus `npm test`).

**Tests**: `tests/test_evals.py` runs the harness on one store and checks
the metric shape; the baseline comparison logic is unit-tested with a
fake baseline.

### WM-62 Field-test protocol — **S** — SHIPPED (the test itself has not run yet)

Write `docs/field-test.md`: how to run one session with all hooks on,
what to count (hook prompts shown, records written, jots promoted versus
dropped, guard verdict distribution from `private/usage.json` and a new
`private/hook-log.jsonl` written by every hook with `{event, at, ms,
outcome}` bounded to 5000 lines), and the two questions the open question
in `open-questions.md` asks: does the extraction turn fatigue, and should
SubagentStop block. Add `crumb doctor --hook-log` to summarise the log.
Answer the open question with `crumb mark-status q:… answered` when the
test has run.

---

## Phase 7: Other harnesses

### WM-70 Hook adapters for other agents — **M**, optional

Only after Phase 6 shows the Claude Code hooks pay for themselves. Survey
which harnesses support pre-tool, prompt and stop hooks (Cursor and Codex
have hook systems with different payloads); write `breadcrumbs/hooks_<name>.py`
translators that map their payloads onto the same `_hook_*` handlers, and
`crumb init --with-hooks --harness <name>` installers. MCP remains the
common path for harnesses without hooks. Do not build this speculatively.

---

## 2. Cross-cutting checklists

### 2.1 Adding a hook event (WM-10, 11, 12, 13, 16)

1. `HOOK_EVENTS` and `_HOOK_SPECS` in `cli.py`: add the event and its
   Claude Code name and matcher.
2. The `hook` subparser: add the subcommand with a one-line help.
3. `cmd_hook`: dispatch to the handler. Handler signature
   `(memory_dir: Path, root: Path, payload: dict) -> int`, always returns
   0, always prints exactly one JSON object.
4. Handler lives in `breadcrumbs/hooks_<name>.py`; helpers shared with the
   guard hook move to `breadcrumbs/hooks_common.py`.
5. `_hook_fallback_json`: decide what the resolver prints when the CLI is
   missing (`{}` for everything except `session`).
6. `install_claude_hooks`/`remove_claude_hooks`/`doctor`: no code change
   expected; add a test that installs, detects and removes the new event.
7. `README.md` Integrations bullet list; `docs/cli-spec.md` hooks table.
8. Test with `run_hook(event, payload)` from `tests/test_hooks.py`.

### 2.2 Adding a record type or frontmatter key (WM-03, 14, 22, 40)

1. `DIR_TYPES`, `TYPE_PREFIX`, `BODY_SECTIONS`, `FRONTMATTER_ORDER`,
   `UNIQUE_SUFFIX_TYPES` as needed.
2. `write_record` `extra=` carries type-specific keys; validate them in
   `run_validate` with a named check.
3. `crumb schema` prints from the constants; check its output.
4. Template tree under `breadcrumbs/templates/project-memory/` and a
   migration step (WM-01).
5. `docs/record-schema.md` §1, §4, §10.
6. `_inputs_hash` covers the new directory automatically if it is under
   the store and not gitignored; confirm with a test that a write changes
   the hash.

### 2.3 Adding an MCP tool or resource

1. Function in `mcp_core.py` that calls `cli` and returns JSON-safe data
   with store-relative paths (`_rel`).
2. Binding in `mcp_server.py` with a one-line docstring.
3. `STATIC_RESOURCES`/`TEMPLATE_RESOURCES` for resources; update the URI
   assertion in `tests/test_mcp.py`.
4. `docs/mcp-spec.md`; the README "MCP server" table counts.

### 2.4 Things that are always wrong

- A hook that emits `permissionDecision: "deny"` or `"allow"`.
- A hook that raises, exits non-zero, or prints two JSON objects.
- Writing a user's prompt or a transcript excerpt into committed `inbox/`
  or any committed record automatically.
- Running a recorded command from a hook or an MCP tool.
- Auto-retiring, auto-merging or auto-deleting a record. Suggest, never do.
- Changing guard scoring to depend on whether a file exists on disk.
- A new third-party import outside an optional extra.
- Bumping `SCHEMA_VERSION` without a migration step and dual-shape readers.
- Adding a version literal anywhere but `breadcrumbs/__init__.py`.

---

## 3. Open decisions this plan does not make

Record the answer as a decision record when you reach it.

1. **Shared usage telemetry.** WM-02 is local-only. If WM-60 shows the
   signal is valuable across machines, the options are a committed
   `generated/usage.json` merged by a custom git merge driver, or a
   `usage/` directory with one file per machine. Both have costs; decide
   with data.
2. **SubagentStop blocking.** WM-13 mines only. Whether to hold a
   subagent for an extraction turn waits on the WM-62 field test.
3. **Embeddings.** Not in this plan. If WM-61 shows FTS plus aliases
   still misses synonyms the project cares about, a disposable
   embedding index behind an optional extra is the next item, and it
   must obey the WM-23 equivalence rule: recall only, deterministic
   scoring.
4. **Where `current.md` goes in a per-branch world.** WM-50 keeps it a
   singleton. Revisit if field use shows branch-specific focus is common.
