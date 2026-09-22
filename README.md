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
   (they hold a signpost, plus the few rules you explicitly `crumb promote`
   into `CLAUDE.md` / `AGENTS.md`).
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
`schema_version:`, currently `3`). These are independent: the package version moves with the
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
crumb mark-status "q_…" answered --reason "see dec_…"              # ...and answer an open question
crumb show "dec_…"               # the full text behind any id the tool prints (+ "see also")
crumb note question|trap|idea    # leave a note for the next agent (no hand-editing)
crumb jot "flaky under -n auto"  # short-term note: a TTL, no evidence rule
crumb inbox                      # triage the jots; promote the durable ones
crumb migrate                    # bring an older store up to this build's schema
crumb usage --never              # which records nothing has ever surfaced
crumb retitle "ses_…" "what that session was really about"   # fix a title that says nothing
crumb traps --stale              # traps nobody has confirmed lately, and what they cost
crumb expired                    # records past their expires_at (still on disk, out of the packet)
crumb questions --aging          # open questions older than the question TTL
crumb verify --recheck "ver_…"   # rerun a verification's commands; record the result (asks first)
crumb consolidate                # clusters of near-duplicate records; --merge them into one
crumb rollup sessions --before 2026-09-01   # fold old machine session snapshots into one record
crumb promote "dec_…"            # make a proven record a standing rule in CLAUDE.md / AGENTS.md
crumb demote "dec_…"             # ...and take it back out (the record stays)
crumb capture session            # record session end (git-prefilled); updates handoff + current
crumb resume                     # print a bounded resume packet with computed staleness
crumb reindex                    # rebuild generated/ projections (mutations reindex automatically)
crumb search "auth middleware"   # deterministic keyword/tag/file lookup over records
crumb search "login" --explain   # ...and show the stems the query became
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

**A near-duplicate is refused.** `remember`, `note`, `verify` and `jot` compare
a new record with the live records of its type (shared specific words, files and
tags). One that nearly repeats an existing record is not written: the command
exits **3** with `CRUMB-ERROR: … looks like <id> (0.71 similar) — pass
--supersedes <id> to replace it, or --allow-duplicate to write anyway`.
`--supersedes <id>` writes the new record and marks the old one `superseded`
by it; `--allow-duplicate` keeps both (a jot takes only `--allow-duplicate`).
The MCP writers take the same two options. `crumb audit` reports near-duplicates already in the store.

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

A `fixed` or `not_applicable` result expires after 90 days
(`ttl_verification_days`): it leaves the packet's list and `guard`'s live set,
and stays searchable. An actionable one never expires; after 90 days the packet
asks for a recheck. `crumb verify --recheck <id>` (repeatable) or `--all`
reruns the recorded `command`/`test` evidence in the project root and writes the
result as a new verification (`fixed` if every command exited 0, else `open`,
with exit codes and the last output lines in its notes) that supersedes the old
one. It prints each command and asks first; `--yes` skips the question, and
without a terminal it refuses (exit 2) unless `--yes` is given. There is no MCP
equivalent.

### `crumb schema`

```bash
python crumb.py schema                       # the full record contract (human)
python crumb.py schema attempt --json        # one record type, machine-readable
python crumb.py schema attempt --template    # a copy-pasteable `remember` skeleton
python crumb.py schema trap --template       # ...or a `crumb note trap` one
```

`schema` prints the record contract — body sections per type, required/derived
frontmatter, status/privacy/confidence vocabularies, and the evidence-or-low-
confidence rule — straight from the source constants, with no `.project-memory/`
required. `--template <type>` emits a fill-in command so an agent reads the
contract once instead of probing `--help` repeatedly (`trap` and `question`
templates are `crumb note …` commands, since that is how both are written).

### `crumb note question | trap | idea`

```bash
python crumb.py note question "Should age signals gate compliance?" --why "blocks export"
python crumb.py note trap "gradlew --stop corrupts R.jar lock" --area build --safe "kill by pid"
python crumb.py note idea "cache the resume packet" --set Idea "memoize across sessions"
```

`note` is the write-surface for the three record kinds that previously had no
command: open questions, known traps, and ideas. `question`/`trap` write one
validated file each — `questions/<slug>.md` (id `q_<slug>`) / `traps/<slug>.md`
(id `trap_<slug>`) — and `open-questions.md` / `known-traps.md` are rebuilt as
one-line-per-record indexes of them; on a store still at `schema_version` 2 they
append a parse-verified block to those files instead (`crumb migrate` moves the
blocks into files). `idea` writes a validated record under `ideas/`. Each
refreshes `generated/resume-packet.md` so the projection never lags the note.
Mirrored over MCP as the `memory_note` tool.

### `crumb show`

```bash
python crumb.py show dec_20260625_repo-local-memory-source-of-truth
python crumb.py show q_should-age-signals-gate-compliance --json
```

The resume packet and the hook injections carry one line per record; `show`
fetches the rest. It takes any id the tool prints — a decision, attempt,
verification, idea, session, jot, trap or question (`q:…` still accepted) —
prints the file, and ends with a `See also:` line naming up to three related
records from `generated/related.json` (records that share files, tags or
specific vocabulary, recomputed at every reindex). An unknown id exits 1. Over
MCP: the `memory_show` tool and the `memory://records/{id}` resource.

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
python crumb.py resume --task "verify the perf audit"   # order sections by relevance to the task (print-only)
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
- **expired** (`expires_at`) and **low-confidence** records;
- **lifecycle nudges**: an actionable verification older than 90 days, a trap
  nobody has confirmed in 180, a `current.md` unchanged for 14 (each
  configurable, see *Lifecycle* below);
- a record citing a file that is **neither on disk nor in HEAD** — it may
  describe code that no longer exists;
- **possible contradictions**: a decision written after an attempt that said
  "do not retry" and doing much the same thing, or two live decisions that
  overlap heavily, written more than a week apart, neither superseding the
  other.

A record past its `expires_at` is left out of the packet's lists (it stays on
disk and in `search`). Current/handoff/active-decisions are prioritized over old session observations, and
sections are capped then trimmed to stay within budget even with hundreds of
records. The packet carries a source `commit`/`inputs_hash`/`generated_at` header so
both `validate` and `audit` can detect drift. Raw transcripts are never included.
`--fast` is a print-only reorientation view and does not overwrite the committed
packet. `--task TEXT` reorders every list section — decisions, failed attempts,
verifications, traps, open questions — by relevance to the task: the three newest
entries in each stay first, then the ones the task matches, best first, then the
rest. Nothing is hidden; the caps and the budget apply afterwards, so what changes
is which entries survive a trim, and the packet says it is relevance-ordered
(`ordering` in `--json`). It also scopes **Likely Relevant Files** to the records
that actually match the task (and labels an empty result `starting cold` rather
than falling back to store-global noise). It is likewise print-only. After a
compaction the `SessionStart` hook builds its packet the same way, with the last
prompt as the task.

Mutations (`remember`, `note`, `verify`, `capture session`, `mark-status`, and
their MCP equivalents) **reindex on write**, so `generated/resume-packet.md`
never silently desyncs from the records. `crumb resume` and `crumb reindex` go
through that same reindex — every projection (`resume-packet.md`, the hook's
`guard-prefilter.json`, `related.json` and `conflicts.json`), each written
atomically — and
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
python crumb.py search "login flow" --explain   # print the stems the query became
```

`search` is a **deterministic, dependency-free** lookup over the canonical records
(decisions, attempts, verifications, ideas, jots, traps, open questions). It
matches on exact/keyword text, tags/component, and file paths — **no embeddings**.
Same input → same output. It is the permissive lookup layer that `guard` builds
on.

Words are compared as stems, so "reconciliation" meets "reconciler". A project's
own synonyms go in `.project-memory/aliases.txt` (committed): one group per line,
every word folding to the first — `auth authn authz login`. `--explain` prints
the stems a query became, which is how you find out a synonym needs a line
there; `crumb audit` flags a line it had to ignore.

Past 200 records, reindex also builds `index/search.sqlite`, a machine-local,
gitignored index that lets `search` parse only the records that could match. It
narrows and never ranks: results are identical with and without it, and a stale
or missing index just means the full scan. `crumb doctor` reports its state.

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

Superseded/rejected/stale records, records past their `expires_at`, and resolved
questions are demoted to a **history** note (mentioned, never treated as active). A stale or wrong-branch handoff surfaces the
same computed staleness warnings `resume` shows. Verdict aggressiveness is governed by
named `GUARD_*` thresholds at the top of the guard section in `breadcrumbs/cli.py`, so it can
be tuned from dogfood feedback without rearchitecting.

---

### `crumb jot` and `crumb inbox` — the short-term tier

```bash
python crumb.py jot "the flaky screenshot test only fails under pytest -n auto" \
  --file tests/test_shot.py --tags flaky,ci
python crumb.py jot "the user said not to touch the migration" --local
python crumb.py inbox                                   # triage queue
python crumb.py inbox promote jot_… trap --area tests/test_shot.py --why "…"
python crumb.py inbox drop jot_…                        # noise
```

Every durable write asks for a title, body sections, and evidence or an explicit
`--confidence low`. That is the right price for a decision and the wrong price
for a two-line observation — so observations at that size were simply not
written down. A **jot** is that observation: one line, a TTL (14 days by
default, `ttl_jot_days` in `manifest.yml` — the older `jot_ttl_days` still
works), and no evidence rule. A near-verbatim repeat of a live jot is refused
(exit 3) unless `--allow-duplicate`.

A jot is **searchable and never judged**. It rides the same corpus switch as an
idea: `crumb search --type jot` finds it; `guard` never rests a verdict on it.
An unconfirmed one-line note that happens to name the file you are editing must
not gate the edit.

`--file` is what makes one findable later — it becomes file evidence, so
`search --file` and the guard's declared-file signal both reach it.

**Two inboxes, and the split is a privacy boundary.** `inbox/` is committed:
somebody chose to write this. `private/inbox/` is gitignored and is where every
*automatic* writer must put things, because a hook cannot know whether the
prompt it just saw is publishable. Machine-written content earns a commit by
being promoted, never by default. For the same reason the committed resume
packet lists committed jots only: a machine-local jot in a committed projection
would make that file differ between two checkouts of one store while the
freshness hash called both current.

**Promotion goes through the normal writer.** `crumb inbox promote <id>
decision` runs the same validate gate a hand-written decision does, evidence
rule included — a jot is a shortcut into memory, not around its contract. The
jot's file evidence and tags carry over, and the jot is marked `superseded` with
`superseded_by` pointing at the new record, so the trail from one-line note to
record survives. `crumb prune jots` deletes expired and dropped jots older than
30 days; an active, unexpired one is never deleted however old the store is.

### `crumb migrate` and `crumb usage`

```bash
python crumb.py migrate --dry-run        # what would change
python crumb.py migrate                  # apply; backs the store up first
python crumb.py usage                    # most-surfaced records
python crumb.py usage --never            # active records nothing has ever reached
```

`migrate` moves a store's on-disk format up to this build's `schema_version`.
Steps are ordered and idempotent, `manifest.yml` is written after each one (so a
failure halts at the last version that actually completed, never at one whose
step did not finish), and the whole committed store is copied to
`private/migrations/<timestamp>/` first. `validate` names the remedy in each
direction: an older store says `run crumb migrate`, a newer one says `upgrade
crumb-kit` — a build must never write its own format into a store that is ahead
of it. Schema 3 moves every trap and open question out of `known-traps.md` /
`open-questions.md` into a file of its own under `traps/` / `questions/`,
keeping its id and every line, and turns the two files into generated indexes.
Until a store migrates it keeps reading and writing the blocks.

`usage` answers the question `audit`'s `[unreachable]` check cannot: not whether
a record *could* be found, but whether it ever *was*. A record counts when it
was shown — a packet printed or injected, a guard verdict, a hook advisory —
and deliberately not when a write triggers a reindex, which would make the
counts measure writes. The counts live in `private/usage.json` and are never
committed: in frontmatter they would churn every record on every guard call, and
in a committed file they would conflict on every merge.

### `crumb scan-secrets` and `crumb traps`

```bash
python crumb.py scan-secrets                 # gate before committing memory
python crumb.py traps --stale                # traps nobody has confirmed within ttl_trap_days (180)
python crumb.py traps --confirm "trap_…"     # "still true", dated, in the trap's own file
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
when somebody last checked (the `last_confirmed` frontmatter key; a `- Last
confirmed:` bullet on a schema-2 store). Retire one with `crumb mark-status <id>
stale`; it stays on disk for history and stops driving `guard`. `audit` raises
`traps-growth` when the active traps' text outgrows its budget (on a schema-2
store, the whole of `known-traps.md`).

### Lifecycle: `crumb expired`, `questions`, `consolidate`, `rollup`

```bash
python crumb.py expired                          # active records past their expires_at
python crumb.py questions --aging                # open questions older than 45 days
python crumb.py consolidate                      # clusters of near-duplicates
python crumb.py consolidate --merge dec_… dec_… --title "One account of the auth choice"
python crumb.py rollup sessions --before 2026-09-01 --dry-run
```

Records go stale. Nothing is retired or merged automatically — expiry hides a
record from the packet and `guard`, the rest are warnings — and the only
command that deletes files is `rollup`, which only touches machine snapshots.

**Every type has a lifespan**, set per store in `manifest.yml`:
`ttl_jot_days` (14), `ttl_question_days` (45), `ttl_verification_days` (90),
`ttl_trap_days` (180), `ttl_current_days` (14). A jot or a settled verification
gets an `expires_at`; once past it, the record keeps its status and stays in
`search`, but leaves the packet's lists and `guard`'s live set. `crumb expired`
lists those. An actionable verification, an unconfirmed trap and an untouched
`current.md` never expire — the packet warns about them instead. `crumb
questions --aging` lists open questions past their lifespan. Decisions and
attempts have no lifespan.

**`consolidate`** groups near-duplicates `audit` finds into clusters.
`--merge <id> <id>… --title "…"` writes one decision, attempt, verification or
idea whose sections are each source's text in date order, tagged
`_(from <id>)_` (`--set HEADING TEXT` replaces a section), with the sources'
evidence and tags combined and their lowest confidence; every source is marked
`superseded`. Edit the merged body before relying on it.

**Contradictions** are reported, never resolved: a decision written after an
attempt that said "do not retry" and doing much the same thing, or two live
decisions that overlap heavily and were written more than a week apart. They
are written to `generated/conflicts.json` at reindex and shown in the packet
and in `audit` (`possible-contradiction`).

**`rollup sessions --before <date>`** folds the machine session snapshots
(placeholder Next Action) created before the date into one session record — a
one-line summary per snapshot — and deletes them. Sessions somebody wrote are
never touched. The rollup takes the date and commit of the last snapshot it
replaces, so the Stop hook's next capture still diffs from the right commit.

### `crumb promote` and `crumb demote` — the long-term tier

```bash
python crumb.py promote dec_…                     # into CLAUDE.md, else AGENTS.md (never creates either)
python crumb.py promote att_… --to AGENTS.md      # a named file
python crumb.py promote trap_… --rule "stop the daemon by pid, never with --stop"
python crumb.py demote dec_…                      # take the rule back out
```

Memory here comes in three tiers. The **short term** — `current.md`,
`handoff.md`, jots — is what is in flight. The **medium term** is the typed
records: decisions, attempts, traps, questions, verifications, which can go
stale and are surfaced by the packet, `guard` and the hooks. The **long term**
is the agent's own instruction file, `CLAUDE.md` or `AGENTS.md`, which the
harness loads whole every session and nothing ages out of. Breadcrumbs keeps
the first two; `promote` is the bridge to the third.

`crumb promote <id>` turns an active decision, attempt or trap into one line in
a managed block of its own, separate from the `init` signpost:

```markdown
## Project rules promoted from memory
- Use sqlite for the cache. _(why: concurrent writers corrupted the JSON file; source: `dec_20260922_use-sqlite-for-the-cache`)_
```

The rule is rendered from the record (a decision's title, an attempt's "do
not retry … unless …", a trap's summary and safe approach), or given with
`--rule`. A record that is not active, or is `confidence: low`, is refused.
The record stays `active`; the resume packet leaves it out of its lists (the
instruction file already carries it) and says how many it left out, `guard`
still uses it, and `search` marks it `promoted`. Promoting again re-renders
the line; there is only ever one per record.

`crumb demote <id>` removes the line; so does retiring the record with
`mark-status … stale` (or `superseded`, `rejected`, `disputed`), because a
rule nobody believes any more must not stay in the file every session loads.
`crumb audit` suggests decisions and attempts that have held for at least 60
days and surfaced in at least five sessions (`promote-candidate`), and flags rules whose record is gone or retired
(`demote-candidate`), rules that no longer match their record
(`promoted-drift`), and a block over 4000 characters (`promoted-bloat`).

There is no MCP tool for this, on purpose: an agent writing its own permanent
instructions through a tool call is how a prompt injection makes itself
permanent. A person runs `crumb promote`, or an agent runs it where a person
can see the command.

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
  well under the bloat threshold so `audit` stays green. `--remove-integrations`
  removes this block only: rules added with `crumb promote` sit in a block of
  their own and stay, since they are the project's instructions now.
- **MCP registration** (`--with-mcp`) — merges a `breadcrumbs` server into
  `.mcp.json` (preserving any other servers). Needs the optional `[mcp]` extra to
  actually run: `pip install "crumb-kit[mcp]"` (the SDK needs Python ≥ 3.10; on
  3.9 that command succeeds and installs nothing). Both MCP SDK **1.x and 2.x**
  work — 2.0 renamed the server class, so an older `crumb-kit` paired with a new
  SDK reports "SDK not installed"; upgrade `crumb-kit` if you see that.
- **Claude Code hooks** (`--with-hooks[=session,guard,capture,prompt,compact,subagent]`)
  — merges six hooks into `.claude/settings.json` so memory is consulted
  **without the agent choosing to**:
  - `SessionStart → crumb hook session` loads the resume packet as context.
    After a compaction (`source: compact`) it first says what was in flight:
    the last prompt, the records that were surfaced for it, and anything the
    miner salvaged. The model that just lost its context is the one reader who
    cannot reconstruct that for itself.
  - `PreToolUse → crumb hook guard` runs a cost-aware guard before risky
    Bash/Edit calls **and before a subagent launch** (a cheap local risk
    pre-filter keeps the common path free of record I/O). A subagent starts
    cold, and its launch prompt is the best description of a proposed action a
    session produces; a launch caps at `READ_FIRST`, because the launch is not
    itself the irreversible act and the subagent's own tool calls hit this same
    guard. it surfaces matched memory but **never decides for you** — it neither
    allows nor denies. `PROCEED`→silent, `READ_FIRST`→the matched records as
    context with the normal permission flow untouched, `PAUSE`/`ASK_HUMAN`→ask,
    with the reason.

    **It will not re-raise a prompt you have opted out of.** The hook reads the
    session's `permission_mode`, and under `bypassPermissions`
    (`--dangerously-skip-permissions`) or `dontAsk` it emits no permission
    decision at all — the matched records still arrive as context, but the
    interruption you turned off stays off. Set `CRUMB_GUARD_ADVISORY=1` to get
    that advisory-only shape in *every* mode.
  - `UserPromptSubmit → crumb hook prompt` injects the records that are about
    *this prompt* — the moment the task is finally known, and the one the
    recency-ordered resume packet cannot serve. It scores the prompt with the
    same retrieval `guard` uses and shows at most five matches, pointing at
    `crumb show <id>` (or `memory://records/{id}`) for the full text. It **never
    blocks**: that decision is available on this event and it erases the
    prompt, which is the worst thing a memory tool could do.

    It also captures **corrections**. A prompt beginning "no, don't…" is a
    durable constraint arriving as an ordinary message, and nothing used to
    write it down, so the next session re-violated it. Captured to
    `private/inbox/` only, after a secret scan; `capture_corrections: false` in
    `manifest.yml` turns it off.
  - `PreCompact → crumb hook compact` mines the transcript just before the
    context is destroyed. Compaction is the biggest memory-loss event in a long
    session and this hook cannot speak to the model at all (its stdout goes to
    the debug log), so it writes candidates to `private/inbox/` and leaves a
    marker that the next `SessionStart` reads.
  - `SubagentStop → crumb hook subagent` mines a finished subagent's transcript.
    Its findings otherwise vanish: the parent only ever sees the final message.
    It does not hold the subagent — that is a prompt-fatigue question awaiting a
    field test, and `subagent_extraction` is reserved for it.
  - `Stop → crumb hook capture` snapshots a session record when the turn ends —
    once per unit of work, not once per turn: a firing is skipped when the HEAD
    commit and dirty-file set are unchanged since the newest session record, and
    its stand-in Next Action never overwrites one you set.

    It also **mines the transcript** on every firing, which is a side effect
    and not a decision: even a firing that stays silent should salvage what the
    transcript shows, because nothing reads it again.

    When the ending turn produced **new commits** — or the miner found a
    failed-then-fixed command, or three candidates of any kind — the hook does
    more than snapshot: it holds the stop once (**the extraction turn**) and
    hands the agent a concrete instruction, with the mined candidates listed by
    id. That turns the request from "compose a record about what just happened",
    at the moment the model has least context left, into "promote this one, drop
    that one". Record any durable decision, failed attempt, or verification
    (`crumb remember` / `verify` / `mark-status` / `crumb inbox promote`), then
    `crumb capture session --next "…"`. That last command
    is also what clears the prompt, so completing the instruction and moving on
    are the same act. This is what makes the agent the memory *author* with no
    human in the loop: the request lands while the model still holds the
    session's "why", instead of relying on a signpost it read hundreds of turns
    ago. Proportionality rules keep it quiet: edit-only turns and no-change
    turns never prompt, a continuation of a held stop is never held again (the
    machine snapshot is the floor if the agent ignores the instruction), and
    the very first firing in a store takes a silent baseline instead of
    interrogating the agent about pre-existing history. A candidate the agent
    declined is never offered again in the same session. Opt out per project
    with `extraction_prompt: false` in `manifest.yml` — which stops the prompt,
    not the mining.

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
When rules have been promoted it also reports how many, and their size, per
instruction file.

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
   `decisions/`, `attempts/`, `traps/`, `questions/`. `known-traps.md` and
   `open-questions.md` are one-line-per-record indexes of the last two, each line
   naming the file to open (on a store still at `schema_version` 2 they hold the
   traps and questions themselves).

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
| `resume` (incl. `--fast`, computed staleness, `--task` relevance ordering) | implemented (**MVP-core**) |
| `search` (deterministic keyword/tag/file, store aliases, `--explain`, disposable index past 200 records) | implemented |
| `show` (full text of any id, with "see also") | implemented |
| `guard` (deterministic ranking, §11 verdicts) | implemented |
| `audit` (heuristic: secrets, instruction-like, drift, staleness, bloat, missing cited files, near-duplicates, possible contradictions) | implemented (**MVP-trust**) |
| `scan-secrets` (committed-memory secret gate) | implemented |
| `schema` (record contract introspection + template) | implemented |
| `note question` / `note trap` / `note idea` (write-surface) | implemented |
| `jot` / `inbox` / `inbox promote` / `inbox drop` (short-term tier) | implemented |
| `migrate` (store-format upgrade, backed up and idempotent; schema 3 = one file per trap/question) | implemented |
| `usage` (local surfacing counts, `--never`) | implemented |
| `retitle` (rewrite a record's title; id/slug/filename unchanged) | implemented |
| `traps` (staleness + always-on context cost, `--stale`, `--confirm`) | implemented |
| Lifecycle: per-type TTLs, `expired`, `questions --aging`, `verify --recheck`, near-duplicate gate (exit 3), `consolidate`, contradiction warnings, `rollup sessions` | implemented |
| `promote` / `demote` (the long-term tier: rules in `CLAUDE.md`/`AGENTS.md`, auto-demote on retire, audit suggestions and drift) | implemented |
| `pipx`/`pip` packaging (`crumb` console script, bundled templates) | implemented |
| MCP server (`breadcrumbs-mcp`: 14 resources, 6 prompts, 13 tools) | implemented (**optional**) |
| Integrations: `init` bootstrapper, `doctor`, `mcp`, `hook` (adapter + `.mcp.json` + hooks) | implemented |

The full loop (capture → resume → trust) is complete and CI-guarded, and ships as
a `pipx`-installable `crumb` binary (see **Install** above). An **optional** MCP
server (`pip install "crumb-kit[mcp]"`) exposes the same memory engine to agents
without shelling out — a thin wrapper over the same core functions, never
required for baseline use. The **Integrations** layer (`crumb init --with-*`,
`crumb doctor`, `crumb hook`) wires that engine into your agent so the store is consulted
automatically rather than only when an agent remembers to. See [`docs/`](docs/)
for the architecture, record schema, CLI spec, [MCP spec](docs/mcp-spec.md), and
security posture, and [`docs/roadmap-working-memory.md`](docs/roadmap-working-memory.md)
for the phased plan that takes the tool from a ledger to a working memory.

---

## Memory is advisory

Current user instruction, source code, tests, build output, current authoritative
docs, and security policy **outrank** anything stored in `.project-memory/`.
If memory conflicts with reality, mark it `disputed` or `stale` and link evidence —
do not let it override the present.
