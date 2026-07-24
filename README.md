# Breadcrumbs

**Breadcrumbs — leave a trail your future self and your agents can follow back.**

A portable, repo-local, human-readable ledger of durable project state for
human–agent software work (the **Project Continuity Memory** capability).

> **North-star.** Project Continuity Memory is a repo-local, human-readable ledger
> of durable project state: what was decided, what failed, what is active, what is
> risky, what is unresolved, and what the next agent or human must know before
> acting. It is **not** a transcript archive, **not** a vector database, and **not**
> a replacement for source code, tests, current human instruction, or authoritative
> docs.

It stores durable project state as typed, human-readable records inside a target
project's `.project-memory/` directory, so humans and agents can resume work across
sessions, tools, devices, branches, and time without re-discovering decisions,
repeating failed attempts, or trusting stale context.

- **PyPI package name:** `crumb-kit` (`pip install crumb-kit`)
- **Import package / GitHub repo:** `breadcrumbs`
- **CLI binary name:** `crumb`
- **Formal capability name:** Project Continuity Memory

---

## Non-goals

This tool deliberately does **not**:

1. Build a vector database as the source of truth (vectors are a later, disposable
   search accelerator).
2. Store full chat transcripts as memory (it extracts durable decisions, attempts,
   handoffs, questions, traps, and evidence).
3. Rely on one vendor's memory feature (Claude, Codex, Cursor, Gemini, and future
   agents all read the same plain records).
4. Require MCP, hooks, or a daemon for baseline functionality (plain files + CLI
   work first).
5. Use `AGENTS.md` / `CLAUDE.md` / Cursor / Gemini rules as the memory database
   (those are signposts only).
6. Store secrets, credentials, customer PII, or sensitive local notes in committed
   project memory.
7. Make capture so heavy that humans stop using it (routine capture targets under
   90 seconds).

---

## Install

`breadcrumbs` is a stdlib-only Python package (no third-party runtime
dependencies) that installs a single `crumb` binary. The recommended path
is [`pipx`](https://pipx.pypa.io/), which puts the CLI on your PATH in its own
isolated environment:

```bash
pipx install crumb-kit          # from a published artifact (future)
pipx install .                       # from a source checkout (this repo dir)
```

Plain `pip` works too (prefer a virtualenv):

```bash
python -m pip install .              # or: pip install <built-wheel>.whl
```

After install, the binary is on PATH and the `.project-memory/` template tree
ships **inside the package** (`breadcrumbs/templates/`), so `init` finds it
wherever the package lives — there is no repo-relative path dependency:

```bash
crumb --version                 # breadcrumbs X.Y.Z (record schema_version N)
crumb init                      # locates bundled templates post-install
```

**Versioning.** The package uses semantic versioning. `crumb --version`
prints the package version *and* the **record `schema_version`** (the manifest's
`schema_version: 1`). These are independent: the package version moves with the
code; the record schema version moves only on a breaking change to the on-disk
record format, and a package MAJOR bump accompanies it.

**Requires** Python ≥ 3.9.

### No `npx` (deliberate)

There is intentionally **no `npx`/Node distribution**. The tool is Python and
ships via `pipx`/`pip`. JavaScript-ecosystem reach (an `npx crumb` wrapper)
is a separately-justified future decision, **not** a default migration — it would
only be added if dogfooding shows a concrete need, and would wrap the same Python
core rather than reimplement it.

---

## Quickstart

> **Two invocation forms.** Once installed (above), run `crumb <command>`.
> From a **source checkout** without installing, the equivalent is
> `python crumb.py <command>` (a thin shim over `breadcrumbs.cli`); the
> per-command examples below use that source form. They are interchangeable.

```bash
crumb init                       # install .project-memory/ + manifest + .gitignore rules
crumb init --with-adapter --with-mcp --with-hooks   # ...and wire it into your agent (see Integrations)
crumb validate                   # deterministically check the store (schema + invariants)
crumb schema                     # print the record contract (sections, vocab, rules)
crumb remember decision          # capture a durable choice
crumb verify "finding#1" --status fixed   # record a verification result (a finding about reality)
crumb mark-status "dec_…" stale --reason "superseded by reality"   # record lifecycle mutation
crumb note question|trap|idea    # leave a note for the next agent (no hand-editing)
crumb capture session            # record session end (git-prefilled); updates handoff + current
crumb resume                     # print a bounded resume packet with computed staleness
crumb reindex                    # rebuild generated/ projections (mutations reindex automatically)
crumb search "auth middleware"   # deterministic keyword/tag/file lookup over records
crumb guard "rewrite the auth middleware"   # warn before repeating a known mistake
crumb audit                      # heuristic health/safety report (stale/unsafe/bloated)
crumb scan-secrets               # block if committed memory holds token-like strings
crumb doctor                     # is memory actually wired into your agent?
crumb mcp serve | register | doctor   # run / register / health-check the optional MCP server
```

In this build, `init`, `validate`, `remember`, `capture session`, `resume`,
`search`, `guard`, `audit`, and `scan-secrets` are all implemented — the full
**MVP** (capture → resume → trust). `resume` closes the **capture → resume value
loop (MVP-core)**; `guard` adds the **"don't repeat the expensive mistake"**
capability that separates a continuity engine from a scrapbook; and `audit` +
`scan-secrets` complete **MVP-trust** — the heuristic safety net (secrets,
instruction-like text, generated-packet drift, staleness, bloat) that lets you
*trust* the memory, not just use it.

### `crumb init`

```bash
python crumb.py init                                   # prompt for session policy (default: full)
python crumb.py init --session-tracking distillate     # keep sessions/ local
python crumb.py init --no-commit-generated             # keep generated/*.md local
python crumb.py init --project /path/to/repo --json    # init elsewhere, JSON summary
python crumb.py init --force                           # replace an existing scaffold (DELETES all records)
```

`init` copies the `.project-memory/` template tree into the target project,
writes `manifest.yml` (recording the chosen tracking policies), and inserts a
managed block into the project `.gitignore`. It runs on non-git folders too,
printing a notice that git-derived record fields will use defined sentinels.

On a terminal, `init` also offers to wire the store into your agent (inject a
signpost into `CLAUDE.md`/`AGENTS.md`, register the MCP server, install hooks).
Default non-interactive `init` touches none of those and prints a one-line nudge.
See **Integrations** below; flags: `--with-adapter`/`--with-mcp`/`--with-hooks`
(and `--no-*`), `--print-integrations` (dry run), `--remove-integrations`.

Running `init` with any integration flag against a project that **already has**
a `.project-memory/` store applies just those integrations and leaves the store
untouched — no `--force` needed (and none should be used: `--force` replaces the
scaffold and deletes all existing records).

### `crumb validate`

```bash
python crumb.py validate                      # human-readable report; exit 1 on problems
python crumb.py validate --json               # structured findings + exit code
python crumb.py validate --verbose            # also list the passing checks
python crumb.py validate --project /path/repo # validate elsewhere
```

`validate` is **fully deterministic** — it checks structural invariants only
(manifest version, core files, record frontmatter, filename-canonical identity,
status/privacy vocabularies, evidence/handoff/session requirements, generated
markers). It performs **no** heuristic content scanning; secret and
instruction-like-text detection live in `audit` / `scan-secrets`. Exit codes: `0`
clean, `1` problems found, `2` no `.project-memory/` store present.

### `crumb remember decision | attempt`

```bash
# non-interactive (agent-friendly): title + sections + evidence as flags
python crumb.py remember decision \
  --title "Use repo-local Markdown as source of truth" \
  --set Context "needed a tool-independent store" \
  --set Decision "Markdown + YAML frontmatter" \
  --evidence commit abc1234 --evidence command "npm test" \
  --tags memory,architecture

python crumb.py remember attempt --title "Tried a sqlite store" \
  --set Result "too heavy for the value" --confidence low
```

Frontmatter is auto-derived (clock + git) and defaulted; you supply only a title
and a few section lines (`--set HEADING TEXT`, repeatable). Run with no `--title`
in a terminal for an interactive prompt. A decision/attempt **must** carry
evidence or `--confidence low` (validate §16.9) — the command enforces this and
refuses to write an invalid record. `--json` emits a machine summary.

`remember attempt` also accepts the fixed attempt vocabulary as **named flags**
(`--problem`, `--tried`, `--result`, `--why`, `--do-not-retry`, `--related`), so
the contract is visible in `--help` instead of discoverable only by rejection.

### `crumb verify`

```bash
python crumb.py verify "perf-audit-2026-05-15#F1" \
  --status fixed --method static \
  --evidence file app/DoWhatApplication.kt:170 \
  --note "DB validation moved to applicationScope.launch(ioDispatcher)"
```

Records a **verification result** — "I checked X; here is its state" — the most
common agentic output in maintenance, audits, and "is this bug still real?" work.
Without a home for it, agents either drop it or mis-file it as a decision/attempt
and pollute those categories. `--status` is the outcome
(`fixed|open|regressed|not_applicable|inconclusive`); `--method` is
`static|runtime|test`. Like a decision/attempt it needs evidence or
`--confidence low`. Verifications surface in the resume packet's **Verifications**
section (actionable outcomes first) and are searchable with `crumb search --type
verification --status open` (here `--status` filters on the outcome). Mirrored
over MCP as `memory_verify`.

### `crumb schema`

```bash
python crumb.py schema                       # the full record contract (human)
python crumb.py schema attempt --json        # one record type, machine-readable
python crumb.py schema attempt --template    # a copy-pasteable `remember` skeleton
```

`schema` prints the record contract — body sections per type, required/derived
frontmatter, status/privacy/confidence vocabularies, and the evidence-or-low-
confidence rule — straight from the source constants, with no `.project-memory/`
required. `--template <type>` emits a fill-in command so an agent reads the
contract once instead of probing `--help` repeatedly.

### `crumb note question | trap | idea`

```bash
python crumb.py note question "Should age signals gate compliance?" --why "blocks export"
python crumb.py note trap "gradlew --stop corrupts R.jar lock" --area build --safe "kill by pid"
python crumb.py note idea "cache the resume packet" --set Idea "memoize across sessions"
```

`note` is the write-surface for the three record kinds that previously had no
command: open questions, known traps, and ideas. `question`/`trap` append a
parse-verified block to `open-questions.md` / `known-traps.md`; `idea` writes a
validated record under `ideas/`. Each refreshes `generated/resume-packet.md` so
the projection never lags the note. Mirrored over MCP as the `memory_note` tool.

### `crumb capture session`

```bash
python crumb.py capture session --next "wire up the resume packet"   # git-prefilled
python crumb.py capture session --fast --next "tired — resume here"    # ~15s, no prompts
```

`capture session` reads git since the last session record and pre-fills **Work
Completed** (`git log`), **Files Touched** (a one-line `git diff --shortstat`
summary — `N files changed, +X/-Y`, not an inlined per-file list, so records stay
small and the secret scanner never trips on path-shaped tokens), then asks only
for narrative confirmation + a required **Next Action**. It writes the session record
and refreshes `handoff.md` and `current.md`. `--fast` skips all prompts and any
LLM, writing a git snapshot + the one-line `--next`. No path requires an LLM.
With `session_tracking: distillate`, the session file is written locally but stays
gitignored — promote durable items with `remember` to commit them.

### `crumb resume`

```bash
python crumb.py resume                       # full bounded packet (writes generated/resume-packet.md)
python crumb.py resume --fast                # git snapshot + focus + next action + staleness (print-only)
python crumb.py resume --json                # structured packet (sections + warnings) for agents
python crumb.py resume --stale-days 14       # tighten the aged-unresolved threshold (default 21)
python crumb.py resume --task "verify the perf audit"   # scope likely-files to matching records (print-only)
```

`resume` assembles a **bounded, paste-anywhere packet** (≤5k tokens) from the
canonical records — project/branch/commit, current focus, next action, active
decisions (id + one-line rationale), failed attempts to avoid (id + do-not-retry),
known traps, open questions, likely files, verifications (recorded results,
actionable outcomes first), and verification commands — followed by
**computed staleness warnings**:

- handoff **age + commit-distance** ("handoff is 6 days old, written 14 commits
  behind current HEAD") — the primary "train of thought went cold" signal;
- **aged-unresolved** open questions and active decisions older than the threshold;
- **branch mismatch** (record/handoff branch ≠ current HEAD, incl. detached HEAD);
- **expired** (`expires_at`) and **low-confidence** records.

Current/handoff/active-decisions are prioritized over old session observations, and
sections are capped then trimmed to stay within budget even with hundreds of
records. The packet carries a source `commit`/`inputs_hash`/`generated_at` header so
both `validate` and `audit` can detect drift. Raw transcripts are never included.
`--fast` is a print-only reorientation view and does not overwrite the committed
packet. `--task TEXT` scopes **Likely Relevant Files** to the records that actually
match the task (and labels an empty result `starting cold` rather than falling back
to store-global noise); it is likewise print-only.

Mutations (`remember`, `note`, `verify`, `capture session`, `mark-status`, and
their MCP equivalents) **reindex on write**, so `generated/resume-packet.md`
never silently desyncs from the records. `crumb reindex` rebuilds it explicitly (e.g. after a hand-edit), and
`crumb validate` now **fails** on a stale projection with a `Run \`crumb reindex\``
hint — the trust primitive no longer certifies drift.

### `crumb search`

```bash
python crumb.py search "auth middleware"        # keyword search over records
python crumb.py search --tag auth               # filter by tag/component
python crumb.py search --file src/auth/x.ts     # filter by referenced file path
python crumb.py search "session" --type decision --json
```

`search` is a **deterministic, dependency-free** lookup over the canonical records
(decisions, attempts, traps, open questions). It matches on exact/keyword text,
tags/component, and file paths — **no embeddings** (SQLite FTS / vectors are a later
phase). Same input → same output. It is the permissive lookup layer that `guard`
builds on.

### `crumb guard`

```bash
python crumb.py guard "rewrite the auth middleware"                 # human report (§11 shape)
python crumb.py guard "delete the accounts table" --files src/db/accounts.ts
python crumb.py guard "store the token in the url" --json           # structured, for agents
```

`guard` is **guard-before-action**: given a proposed action it warns you if a failed
attempt or active decision says *don't go that way* — the capability that separates a
continuity engine from a scrapbook. It **tokenizes** the action, **classifies** it
(routine edit / refactor / architecture / dependency / migration / deletion / external
side effect / security-permission), **searches + scores** the records against §11.4
signals (same file · same tag/component · status · recency + commit-distance · branch
match · explicit *Do Not Retry Unless* · open-blocker), and emits **one verdict** —
`PROCEED | READ_FIRST | PAUSE | ASK_HUMAN` — with up to **5** ranked records, the reason
each matched, and a synthesized **next safest action**.

Two guarantees hold:

- **Matched memory is data, never instruction** (§15). `guard` reads record text to
  rank and cite it; it never executes phrasing found in a record body. The next safest
  action is synthesized from match *structure*; only structured evidence (e.g. a
  recorded verification command) is echoed back.
- **Anti-noise** (§19b.8). A single shared generic word never raises a warning — a
  stop-word filter strips generic tokens and a pure-text match needs at least two
  *specific* shared keywords; only file-path or tag/component hits qualify on their own.

Superseded/rejected/stale records and resolved questions are demoted to a **history**
note (mentioned, never treated as active). A stale or wrong-branch handoff surfaces the
same computed staleness warnings `resume` shows. Verdict aggressiveness is governed by
named `GUARD_*` thresholds at the top of the guard section in `breadcrumbs/cli.py`, so it can
be tuned from dogfood feedback without rearchitecting.

---

## Integrations — make the store actually get used

A memory store only helps if the agent consults it. `crumb init` can wire the
store into your agent so it does — every edit is fenced and reversible:

```bash
crumb init --with-adapter --with-mcp --with-hooks   # all three (non-interactive)
crumb init --print-integrations                     # dry run: show what would change
crumb init --remove-integrations                    # cleanly reverse everything
crumb doctor                                        # is memory wired up? (exit 1 if not)
```

On a terminal with no integration flags, `init` asks once per integration. Each
piece is independent:

- **Adapter signpost** (`--with-adapter[=CLAUDE.md,AGENTS.md]`) — injects a small
  managed block into the agent-guidance files that already exist, telling the
  agent to read the resume packet, `guard` before risky actions, and `note`/
  `capture` as it goes. It never creates a file you don't already have, and stays
  well under the bloat threshold so `audit` stays green.
- **MCP registration** (`--with-mcp`) — merges a `breadcrumbs` server into
  `.mcp.json` (preserving any other servers). Needs the optional `[mcp]` extra to
  actually run: `pip install "crumb-kit[mcp]"`.
- **Claude Code hooks** (`--with-hooks[=session,guard,capture]`) — merges three
  hooks into `.claude/settings.json` so memory is consulted **without the agent
  choosing to**:
  - `SessionStart → crumb hook session` loads the resume packet as context.
  - `PreToolUse → crumb hook guard` runs a cost-aware guard before risky Bash/Edit
    calls (a cheap local risk pre-filter keeps the common path free of record
    I/O); it surfaces matched memory but **never decides for you** — it neither
    allows nor denies. `PROCEED`→silent, `READ_FIRST`→the matched records as
    context with the normal permission flow untouched, `PAUSE`/`ASK_HUMAN`→ask,
    with the reason.
  - `Stop → crumb hook capture` snapshots a session record when the turn ends —
    once per unit of work, not once per turn: a firing is skipped when the HEAD
    commit and dirty-file set are unchanged since the newest session record, and
    its stand-in Next Action never overwrites one you set.

`crumb doctor` reports whether each piece is in place (and whether the resume
packet is stale), exiting non-zero when a store exists but nothing is wired up.

`crumb mcp serve` runs the server over stdio (same as `breadcrumbs-mcp`); `crumb
mcp register` is the standalone form of `--with-mcp`.

---

## Plain-file fallback (cloud agents, no CLI)

The tool degrades gracefully when `crumb` cannot run (e.g. a read-only cloud
agent). With the default policy `commit_generated_projections: true`, `resume`
writes `generated/resume-packet.md` and that file is **committed**, so an agent that
cannot execute the CLI can still reorient by reading:

1. `.project-memory/generated/resume-packet.md` — the pre-built bounded packet; then
2. the plain canonical files directly — `current.md`, `handoff.md`,
   `decisions/`, `attempts/`, `known-traps.md`, `open-questions.md`.

Everything is human-readable Markdown, so no binary store or vendor runtime is
required to resume. (`generated/resume-packet.md` is a rebuildable projection — if
it disagrees with the canonical records, the records win and it should be
regenerated; both `validate` and `audit` flag this drift by comparing the packet's
stamped `inputs_hash` against the canonical inputs, and mutations reindex it
automatically so it stays in step.)

---

## Status

| Command | State |
|---|---|
| `init` | implemented (Phase 1) |
| `validate` | implemented (Phase 2) |
| `remember decision` / `remember attempt` | implemented (Phase 3) |
| `verify` (verification result: outcome + method + evidence) | implemented |
| `mark-status` (record lifecycle mutation, validate-gated, `--superseded-by`) | implemented |
| `reindex` (rebuild generated projections) | implemented |
| `capture session` (incl. `--fast`) | implemented (Phase 3) |
| `resume` (incl. `--fast`, computed staleness) | implemented (Phase 4 — **MVP-core**) |
| `search` (deterministic keyword/tag/file) | implemented (Phase 5) |
| `guard` (deterministic ranking, §11 verdicts) | implemented (Phase 5) |
| `audit` (heuristic: secrets, instruction-like, drift, staleness, bloat) | implemented (Phase 6 — **MVP-trust**) |
| `scan-secrets` (committed-memory secret gate) | implemented (Phase 6) |
| `schema` (record contract introspection + template) | implemented |
| `note question` / `note trap` / `note idea` (write-surface) | implemented |
| `pipx`/`pip` packaging (`crumb` console script, bundled templates) | implemented (Phase 7) |
| MCP server (`breadcrumbs-mcp`: 8 resources, 6 prompts, 10 tools) | implemented (Phase 8 — **optional**) |
| Integrations: `init` bootstrapper, `doctor`, `mcp`, `hook` (adapter + `.mcp.json` + hooks) | implemented |

With Phase 6 the full MVP (capture → resume → trust) is complete and CI-guarded;
Phase 7 packages it as a `pipx`-installable `crumb` binary (see **Install**
above). Phase 8 adds an **optional** MCP server (`pip install
"crumb-kit[mcp]"`) that exposes the same memory engine to agents without
shelling out — a thin wrapper over the Phase 1–6 functions, never required for
baseline use. The **Integrations** layer (`crumb init --with-*`, `crumb doctor`,
`crumb hook`) wires that engine into your agent so the store is consulted
automatically rather than only when an agent remembers to. See [`docs/`](docs/)
for the architecture, record schema, CLI spec, [MCP spec](docs/mcp-spec.md), and
security posture.

---

## Memory is advisory

Current user instruction, source code, tests, build output, current authoritative
docs, and security policy **outrank** anything stored in `.project-memory/`.
If memory conflicts with reality, mark it `disputed` or `stale` and link evidence —
do not let it override the present.
