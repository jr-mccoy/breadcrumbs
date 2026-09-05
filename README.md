# Breadcrumbs

[![ci](https://img.shields.io/github/actions/workflow/status/jr-mccoy/breadcrumbs/ci.yml?branch=main&label=ci)](https://github.com/jr-mccoy/breadcrumbs/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/crumb-kit.svg)](https://pypi.org/project/crumb-kit/)
[![Python versions](https://img.shields.io/pypi/pyversions/crumb-kit.svg)](https://pypi.org/project/crumb-kit/)
[![runtime deps: none](https://img.shields.io/badge/runtime%20deps-none-brightgreen.svg)](https://github.com/jr-mccoy/breadcrumbs/blob/main/pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/jr-mccoy/breadcrumbs/blob/main/LICENSE)

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
pipx install crumb-kit   # from PyPI
pipx install .           # from a source checkout (this repo dir)
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
crumb mark-status "trap_…" stale --reason "fixed in 2.1"           # ...retire a trap the same way
crumb mark-status "q:…" answered --reason "see dec_…"              # ...and answer an open question
crumb note question|trap|idea    # leave a note for the next agent (no hand-editing)
crumb retitle "ses_…" "what that session was really about"   # fix a title that says nothing
crumb traps --stale              # traps nobody has confirmed lately, and what they cost
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

**Every command speaks the same two dialects.** On failure, the first line of
the message is `CRUMB-ERROR: <subcommand>: …` — a fixed, greppable token, so a
run piped through `head`/`tail` still says it failed even when `$?` belongs to
the pipe rather than to `crumb`. Under `--json`, every command returns `ok`,
`command` and `items` (aliasing whichever list that command emits — `findings`,
`hits`, `matches`, …, all still present under their own names), so one reader
works across subcommands instead of a per-subcommand adapter that reports zero
problems when it guesses the key wrong.

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

Titles can be as long as you like; **filenames can't**. The slug in
`.project-memory/<type>/<date>-<slug>.md` is capped at 60 characters (cut on a
word boundary, `-2`/`-3` collision suffixes included in the budget), so a
sentence-length title never produces a sentence-length path. That keeps a store
clonable on Windows, where the whole path is capped at 260 characters unless
`core.longpaths` is on, and stops long titles from tripping Linux's 255-byte
per-name limit. The full text stays in the record's `title` frontmatter, so
nothing is lost. Records already on disk with longer names keep working — the
cap applies when a name is generated, never when one is read.

The record's `agent` frontmatter says who wrote it. Without `--agent`, the CLI
reads the environment (`CLAUDECODE`, `CURSOR_AGENT`, `CODEX_SANDBOX`, …) and
records the harness it finds, or **`unknown`** when it finds none — it will not
claim a human wrote a record just because the flag was missing. Pass
`--agent human` to make that claim explicitly.

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

The bare form prompts, so it needs a terminal. **To run it unattended**, supply
every section you want on the command line — `--next` plus `--set "<heading>"
"<text>"` for each narrative heading. That keeps the git prefill, unlike `--fast`,
which drops narrative entirely:

```bash
crumb capture session --next "wire the parser" \
  --set "Decisions Made" "kept the projection rebuild on the write path"
```

A `--set` heading is matched ignoring case, spacing and punctuation, and an
unrecognized one is **never** fatal: the content is kept under `## Unsorted`,
tagged with the heading you used, and a `CRUMB-WARN:` line on stderr names the
valid list. One wrong heading used to discard every other `--set` on the command
line, which is the most expensive thing this tool can do to an agent writing up
a long session.

A session with no `--title` is named from what you already said about it — the
`--focus`, else the Next Action, else the work summary — and its filename
carries four hex characters of entropy, so two agents capturing on the same day
in two checkouts cannot write the same file. `crumb retitle <id> "…"` fixes a
title written before that; it rewrites the searchable title only, since the id,
slug and filename are what other records reference. `dirty_files` excludes
`.project-memory/` by default (`--include-memory` puts it back) and is capped —
a capture rewrites the store on every firing, and in a shared tree it also sees
every other session's uncommitted records.

The prefill window is bounded: `since..HEAD` from the newest session record's
commit, or — when that is more than 20 commits back, or there is no prior record —
the last 20 commits. Either way the record names the window it used, so a large
diff can be read for what it is instead of taken as one sitting's work.
With `session_tracking: distillate`, the session file is written locally but stays
gitignored — promote durable items with `remember` to commit them.

### `crumb resume`

```bash
python crumb.py resume                       # full bounded packet (writes generated/resume-packet.md)
python crumb.py resume --fast                # git snapshot + focus + next action + staleness (print-only)
python crumb.py resume --json                # structured packet (sections + warnings) for agents
python crumb.py resume --stale-days 14       # tighten the age cutoff (default 21)
python crumb.py resume --task "verify the perf audit"   # scope likely-files to matching records (print-only)
```

`resume` assembles a **bounded, paste-anywhere packet** (≤5k tokens) from the
canonical records — project/branch/commit, current focus, next action, active
decisions (id + one-line rationale), failed attempts to avoid (id + do-not-retry),
known traps, open questions, likely files, verifications (recorded results,
actionable outcomes first), and verification commands — followed by
**computed staleness warnings**:

- handoff **age + commit-distance** ("handoff is 6 days old, written 14 commits
  behind current HEAD") — the primary "train of thought went cold" signal, carried
  in `--json` as `handoff_age_days` / `handoff_commit_distance`, separately from the
  `stale_after_days` threshold they are compared against;
- **aged-unresolved** open questions and active decisions older than the threshold;
- **branch mismatch** (record/handoff branch ≠ current HEAD, incl. detached HEAD) —
  only for files that have not reached HEAD; a record committed here from a
  since-merged branch is provenance, not a warning;
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
never silently desyncs from the records. `crumb resume` and `crumb reindex` go
through that same reindex — both projections (`resume-packet.md` and the hook's
`guard-prefilter.json`), both written atomically — and
`crumb validate` **fails** on a stale projection with a `Run \`crumb reindex\``
hint, so the trust primitive no longer certifies drift.

The committed packet is **machine-independent by construction**: the project path
is recorded as `.` rather than an absolute host path, and the `inputs_hash` covers
only what the store's own policy shares — under `session_tracking: distillate` it
skips the gitignored `sessions/`, so a teammate's clone reproduces the author's
stamp exactly instead of both sides reporting each other's projection stale.

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
each matched, and a synthesized **next safest action** — the `recommended_action`
key in `--json`. That is advice this code composed about the action you just
proposed, and it is never empty. It is **not** the resume packet's `next_action`,
which is recorded state (the `## Next Action` from a session handoff, `""` when
nobody set one). Two commands, two meanings, so two names.

**Relevance decides what is surfaced; *stance* decides how far it can escalate.**
Overlap (same file, same tag, shared keywords) answers "is this record about the
same thing" — it has never answered "does this record object to what I am about
to do", and conflating the two made the tool punish the behaviour it exists to
encourage: a trap documenting a hazard in `Foo.kt`, including a `Safe approach:`
prescribing the fix, would `PAUSE` every edit implementing that prescribed fix.
So each match carries a `stance`:

| stance | what it means | ceiling |
|---|---|---|
| `blocking` | the record opposes *doing this* — an attempt with an explicit **Do Not Retry Unless** | `PAUSE` |
| `advisory` | knowledge about the area: a trap, decision, verification, open question | `READ_FIRST` |

A high-impact action class (deletion / migration / external side effect) still
escalates past both ceilings to `ASK_HUMAN` — that is a property of the
*action*'s blast radius, not of any record. In the human output an advisory
match is tagged `[context]` and a blocking one `[objects]`, so a caller can tell
a record that forbids the action from one that merely names the same file.

**Blast radius cuts both ways.** A read-only action — `cat`, `ls`, `grep`,
`git status|log|diff`, … — caps at `READ_FIRST` however strong the overlap, and
`guard --json` reports it as `read_only`. Without that, verdict severity
inverts: overlap is symmetric, so `git status` (which shares vocabulary with
every record that discusses git) outranked `npm test` (which executes arbitrary
code and matched nothing). Anything the classifier does not recognize — shell
plumbing, an acting flag like `find -delete` — is treated as capable of side
effects, so a missed classification costs an unnecessary `PAUSE`, never a
swallowed one.

**A file signal says who claimed it.** `--evidence file …`, and a trap's
`Area / files:` bullet, are the author declaring what a record is about: those
score highest and read as `same file(s)`. A path mined out of a record's prose
is a `mentions:` — it still retrieves (a `--file` search finds it) but it scores
lower and cannot raise a verdict on its own. Extraction is structural, so
`json.load`, `8.13.2`, `AM/PM` and `--title/--set` are not filenames; in one
310-session field store 80% of the "paths" the old lexical rule harvested did
not exist, which is how a script that read a JSON file drew a `PAUSE` from a
screenshot-testing trap.

**To make a record hard-stop an action, record it as an attempt:**
`crumb remember attempt --do-not-retry "…"`. A trap *documents* a hazard; an
attempt *forbids* a repeat.

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

### `crumb scan-secrets` and `crumb traps`

```bash
python crumb.py scan-secrets                 # gate before committing memory
python crumb.py traps --stale                # traps nobody has confirmed in 180 days
python crumb.py traps --confirm "trap_…"     # "still true", dated, in the trap's own block
```

`scan-secrets` blocks on shapes with real structure — AWS keys, PEM blocks,
bearer tokens, a file it could not read. The bare high-entropy heuristic
**warns** instead: it has no structure behind it, and gating on it punished
exactly the records that cite a concrete production path (a Firebase push id is
public, 20 characters of base64url, timestamp-prefixed — diagnostically not a
secret). A gate that is hand-overridden on every commit has stopped being a
gate. Put one regex per line in `.project-memory/.crumbignore` to retire a false
positive once, in a file your reviewers can see, instead of re-deciding it.

`traps` reports what the always-on trap context costs and which traps nobody has
confirmed lately, never-confirmed first. Age alone cannot retire a trap — an old
trap may be perfectly live — so `--confirm` records the fact that was missing:
when somebody last checked. Retire one with `crumb mark-status <id> stale`; it
stays in the file for history and stops driving `guard`. `audit` raises
`traps-growth` when the file outgrows its budget.

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
  actually run: `pip install "crumb-kit[mcp]"` (the SDK needs Python ≥ 3.10; on
  3.9 that command succeeds and installs nothing). Both MCP SDK **1.x and 2.x**
  work — 2.0 renamed the server class, so an older `crumb-kit` paired with a new
  SDK reports "SDK not installed"; upgrade `crumb-kit` if you see that.
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

    **It will not re-raise a prompt you have opted out of.** The hook reads the
    session's `permission_mode`, and under `bypassPermissions`
    (`--dangerously-skip-permissions`) or `dontAsk` it emits no permission
    decision at all — the matched records still arrive as context, but the
    interruption you turned off stays off. Set `CRUMB_GUARD_ADVISORY=1` to get
    that advisory-only shape in *every* mode.
  - `Stop → crumb hook capture` snapshots a session record when the turn ends —
    once per unit of work, not once per turn: a firing is skipped when the HEAD
    commit and dirty-file set are unchanged since the newest session record, and
    its stand-in Next Action never overwrites one you set.

    When the ending turn produced **new commits**, the hook does more than
    snapshot: it holds the stop once (**the extraction turn**) and hands the
    agent a concrete instruction — record any durable decision, failed attempt,
    or verification from this session (`crumb remember` / `verify` /
    `mark-status`), then `crumb capture session --next "…"`. That last command
    is also what clears the prompt, so completing the instruction and moving on
    are the same act. This is what makes the agent the memory *author* with no
    human in the loop: the request lands while the model still holds the
    session's "why", instead of relying on a signpost it read hundreds of turns
    ago. Proportionality rules keep it quiet: edit-only turns and no-change
    turns never prompt, a continuation of a held stop is never held again (the
    machine snapshot is the floor if the agent ignores the instruction), and
    the very first firing in a store takes a silent baseline instead of
    interrogating the agent about pre-existing history. Opt out per project
    with `extraction_prompt: false` in `manifest.yml`.

  The installed command is a small POSIX-`sh` resolver, not a bare `crumb`: it
  tries `$PATH`, then `./.venv` (POSIX and Windows layouts), then any interpreter
  that can `import breadcrumbs`. That covers a container that provisions the CLI
  after the hooks are wired, and a Windows `pip install --user` whose Scripts
  directory is not on the PATH bash inherited. If none of them resolve, the hooks
  stay silent except `SessionStart`, which reports that **memory is inactive**
  rather than returning an empty result that looks like a healthy no-op.

  **Using your own launcher is supported.** Point the command at any wrapper you
  like and keep the `"breadcrumbsHook": "<event>"` key on the hook entry — that
  key is what `crumb doctor` and `--remove-integrations` match on, whatever the
  command looks like.

  An entry *without* the key is still recognized when its command names `crumb`
  and passes a hook event as an argument (`./crumb-hook.sh guard`), so `doctor`
  reports it as installed. But **`--remove-integrations` never deletes an unmarked
  entry** — it lists it and leaves it alone, because a heuristic match is not
  proof breadcrumbs wrote it. To get a clean uninstall for a launcher you wrote
  by hand, run `crumb init --with-hooks` first: that adopts the entry, stamping
  the marker without touching your command, and removal then takes it.

`crumb doctor` reports whether each piece is in place (and whether the resume
packet is stale), exiting non-zero when a store exists but nothing is wired up.

`crumb mcp serve` runs the server over stdio (same as `breadcrumbs-mcp`); `crumb
mcp register` is the standalone form of `--with-mcp`.

### Upgrading on Windows

On Windows, `crumb mcp register` registers the server as
`<your-python> -m breadcrumbs mcp serve` rather than the `breadcrumbs-mcp.exe`
console script. This is deliberate. `pip install --upgrade "crumb-kit[mcp]"`
fails at the uninstall step with `OSError: [WinError 32]` on
`Scripts\breadcrumbs-mcp.exe` whenever *any* MCP server is running — every live
editor session holds that shim open, and orphaned ones linger, so the upgrade
can fail against a server you did not know existed. The shim is opened without
`FILE_SHARE_DELETE`, so Windows refuses rename as well as delete and the usual
"rename the old exe aside" trick does not work either. Launching through the
interpreter means a running server holds *Python* open, which pip never needs to
delete.

**If an upgrade does fail this way, your install is fine.** pip's rollback is
clean: the previously installed version is restored intact. Close the editor
sessions running an MCP server (or stop the `breadcrumbs-mcp` processes) and run
the upgrade again. Re-run `crumb mcp register` afterwards to move an existing
`.mcp.json` onto the interpreter form.

Note that an in-place upgrade does **not** restart running servers — they keep
executing the old code until the editor is restarted, so restart it after
upgrading.

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

> **Installed vs. this checkout.** The table below describes the code in *this
> checkout*, whose version is whatever `crumb --version` prints — the single
> source of truth is `__version__` in `breadcrumbs/__init__.py`, and the top
> section of `CHANGELOG.md` says what it contains. This blurb deliberately names
> no version: it used to pin one by hand and was four releases stale before
> anyone noticed. Work landing after the newest released version collects in
> `CHANGELOG.md` → `[Unreleased]`; whenever that section is non-empty, `pipx
> install crumb-kit` gives you less than this checkout does.

| Command | State |
|---|---|
| `init` | implemented |
| `validate` | implemented |
| `remember decision` / `remember attempt` | implemented |
| `verify` (verification result: outcome + method + evidence) | implemented |
| `mark-status` (record, **trap and question** lifecycle mutation, validate-gated, `--superseded-by`) | implemented |
| `reindex` (rebuild generated projections) | implemented |
| `capture session` (incl. `--fast`) | implemented |
| `resume` (incl. `--fast`, computed staleness) | implemented (**MVP-core**) |
| `search` (deterministic keyword/tag/file) | implemented |
| `guard` (deterministic ranking, §11 verdicts) | implemented |
| `audit` (heuristic: secrets, instruction-like, drift, staleness, bloat) | implemented (**MVP-trust**) |
| `scan-secrets` (committed-memory secret gate) | implemented |
| `schema` (record contract introspection + template) | implemented |
| `note question` / `note trap` / `note idea` (write-surface) | implemented |
| `retitle` (rewrite a record's title; id/slug/filename unchanged) | implemented |
| `traps` (staleness + always-on context cost, `--stale`, `--confirm`) | implemented |
| `pipx`/`pip` packaging (`crumb` console script, bundled templates) | implemented |
| MCP server (`breadcrumbs-mcp`: 8 resources, 6 prompts, 10 tools) | implemented (**optional**) |
| Integrations: `init` bootstrapper, `doctor`, `mcp`, `hook` (adapter + `.mcp.json` + hooks) | implemented |

The full loop (capture → resume → trust) is complete and CI-guarded, and ships as
a `pipx`-installable `crumb` binary (see **Install** above). An **optional** MCP
server (`pip install "crumb-kit[mcp]"`) exposes the same memory engine to agents
without shelling out — a thin wrapper over the same core functions, never
required for baseline use. The **Integrations** layer (`crumb init --with-*`,
`crumb doctor`, `crumb hook`) wires that engine into your agent so the store is consulted
automatically rather than only when an agent remembers to. See [`docs/`](docs/)
for the architecture, record schema, CLI spec, [MCP spec](docs/mcp-spec.md), and
security posture.

---

## Memory is advisory

Current user instruction, source code, tests, build output, current authoritative
docs, and security policy **outrank** anything stored in `.project-memory/`.
If memory conflicts with reality, mark it `disputed` or `stale` and link evidence —
do not let it override the present.
