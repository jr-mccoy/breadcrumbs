# Breadcrumbs v2: memory that writes itself

**Status:** draft for discussion, started 2026-10-13. Nothing here is built.
Questions that need an answer before or during the build are marked **Open**
and collected in §14. Facts about host tools that have not been checked
against a real install are marked *(unverified)* and listed in §14.2.

This document proposes a new core for breadcrumbs. It keeps v1's store format,
safety work and evals, and replaces how memory gets **written** and how it gets
**matched**. [`architecture.md`](architecture.md) describes v1 as it is. This
document says what changes, why, and in what order to build it.

---

## 0. Summary

v1 is a well-engineered filing cabinet. The agent is the clerk who has to
decide what to file. When the agent does that well, breadcrumbs works. When it
doesn't, the store stays empty or one-sided, and no amount of hook polish fixes
that.

v2 makes breadcrumbs itself the clerk. A background **curator** reads each
finished stretch of work and writes the records. It is a small model, run
through the agent CLI the person is already signed in to (`claude -p`,
`codex exec`), so the person needs no API key, account or server. The curator
runs off the hot path. Everything a hook does while the agent waits stays
deterministic and fast, and reads files the curator prepared earlier.

| | v1 | v2 |
|---|---|---|
| Who writes records | The agent, when it remembers to; the Stop hook asks it to | The curator, after every session, whatever the agent did |
| Failed attempts | Recorded only if the agent volunteers them | Read from what actually happened: failing commands, abandoned approaches, "no, not that" |
| Duplicates and contradictions | Detected; the writer refuses with exit 3, or `audit` lists them for a person | Detected the same way, then resolved by the curator (§7), with every change listed and reversible |
| When a record applies | Keyword scoring of the record's prose against the action | Triggers (paths, commands, task phrases) written into the record when it is curated, then matched exactly (§8) |
| What the agent must do | Follow the instructions in `CLAUDE.md`: `resume`, `remember`, `verify`, `capture session` | Nothing. Explicit `crumb remember` still works and is treated as high-confidence input |
| Setup | `pip install`, `crumb init --with-hooks` | The same, or one plugin install. No key, no login beyond the agent's own |
| With no model available | — | Behaves like v1 (§9.4) |

---

## 1. Why a new core

### 1.1 The problem

Breadcrumbs succeeds only as far as the agent using it does everything right.
The code and this repo's own store show it:

- **Writing is delegated to the agent.** The Stop hook's main job is the
  *extraction ask*: holding the stop once and asking the agent to record what
  it learned (`hooks_stop.py`). Most of that module decides when and how often
  to ask. The transcript miner (`transcript.py`) is four regex rules whose
  output is `confidence: low` jots that somebody must promote.
- **Agents record what they're comfortable with.** This repo's own store has
  63 decisions and **0 attempt records**, although `CLAUDE.md` says
  hand-tagging "caused nearly every past failed release".
  [`architecture.md`](architecture.md) §5 sets the bar this misses: *"If it
  cannot warn before a repeated failed attempt, it is just a scrapbook."*
- **Matching is text heuristics, and they can't all be fixed.** Guard,
  search and the prompt hook rank records by tokens, stems and aliases, and
  guard reads shell commands with a hand-built classifier. 38 of 217
  non-merge commits are guard, hook or classifier work. The latest retest fixed
  heredoc bodies, `--force` as a substring, `rm -f` on a temp file, and git
  process counts. Each fix was right. There will always be a next case,
  because the rules don't know what a command is *for*.

### 1.2 The root cause

v1 runs no model on any path (`cli.py`: "no LLM is required on any path").
Memory has two jobs that need judgment: deciding what is worth remembering,
and deciding what is relevant now. With no model, the first fell to the agent
and the second to text rules.

`transcript.py` gives three reasons for staying deterministic. They were right
for v1's design. v2 answers each one instead of giving up the property they
protect:

| v1's reason | v2's answer |
|---|---|
| A model's output is unreproducible, and reproducibility is what makes `validate`, the fixtures and guard's precision testable. | Model output is a *proposal*. It passes the same deterministic gate as any other write (§6), and the gate's checks are reproducible. CI replays recorded model outputs, so the suite stays deterministic. Live-model evals run separately (§11). |
| It costs a round trip at the moment the session is ending. | The curator is detached. No hook waits for it (§5.1). |
| `PreCompact` can't talk to a model. | `PreCompact` only spools the transcript range. The curator handles it afterwards (§4). |

### 1.3 What v1 got right, and keeps

- **The store:** plain Markdown and YAML in the repo, typed records (decision,
  attempt, trap, verification, question, idea, session), filename-canonical
  ids, statuses instead of silent edits, `supersedes` links, typed TTLs.
- **The safety work:** the store lock, atomic writes and transactions
  (`lock.py`, `mutations.py`), `path_policy.py`, `safetext.py`, the secret
  scan, the admission profiles (`admission.py`), and schema compatibility
  checks (`compat.py`).
- **The contracts:** [`continuity-contract.md`](continuity-contract.md)
  (stable ids, current means current, every surfaced record says why, bounded
  delivery, correctable, portable, safe to share), and the rule that memory
  informs and never allows or denies.
- **The measurement:** the evals harness, the critical cases, the task
  replays, the hook log and the field-test protocol.
- **The release machinery:** `release.yml`, one version source, the
  compatibility table.
- **Stdlib only.** v2 reaches a model through a subprocess to the host's own
  CLI, so the package still has no runtime dependencies (§5.2).

---

## 2. Goals and non-goals

### 2.1 Goals

- **G1. Zero required agent actions.** Memory builds up and gets delivered for
  an agent that has never heard of breadcrumbs, with no memory instructions in
  `CLAUDE.md` or `AGENTS.md`. This is the headline eval (§11).
- **G2. Plug and play.** No API key, no account, no server, no daemon to
  install. The model is whatever agent CLI the person is already signed in to.
- **G3. A fast, deterministic hot path.** Hooks never call a model and never
  wait on the curator. They read precomputed files, within v1's budgets: 300 ms
  on guard's common path, from the DoWhat field-report plan.
- **G4. Failures get remembered.** Failed attempts come from what happened in
  the session, not from what the agent chose to report.
- **G5. Portable and reviewable.** Records stay plain files in git. A person
  can read, diff, edit, revert and code-review them.
- **G6. Graceful degradation.** With no usable model, breadcrumbs behaves like
  v1. Nothing breaks and nothing blocks.
- **G7. Not tied to one agent.** One core, with a small adapter per host
  (§9).

### 2.2 Non-goals

- A hosted service, a sync backend, or anything that needs an account.
- A vector database as source of truth. Embeddings may come later as a
  disposable recall aid, under v1's rule (roadmap §3, open decision 3).
- Blocking the agent. Hooks still emit `ask` at most, never `deny` or `allow`.
- Replacing `CLAUDE.md` / `AGENTS.md`. They stay the long-term tier, and
  promotion into them stays a human act.
- Memory across repositories (user-wide preferences). **Open** (§14, Q7).

---

## 3. Architecture

```text
 host session (Claude Code, Codex, …)
   │
   ├─ hooks: capture ───────────▶ spool (private/spool/)      cheap, deterministic
   │   SessionEnd, PreCompact,         │
   │   Stop, SubagentStop              ▼
   │                             condenser ──▶ episode (private/episodes/)
   │                                            │  secret-scrubbed, bounded
   │                                            ▼
   │                             curator (detached) ──▶ brain: host CLI, small model
   │                                            │
   │                                            ▼  proposed operations (JSON)
   │                             gate (deterministic): schema, evidence, secrets,
   │                                   injection, dedup, admission profile
   │                                            │
   │                                            ▼
   │                             store (.project-memory/ records)   ◀── human / agent edits
   │                                            │
   │                                            ▼
   │                             compiler (deterministic): packet, trigger index,
   │                                   briefings, "since last time"
   │                                            │
   └─ hooks: deliver ◀──────────────────────────┘                  cheap, deterministic
       SessionStart, UserPromptSubmit, PreToolUse
```

There are three loops:

1. **Capture**, once per stretch of work: spool, condense, curate, gate,
   write. Asynchronous.
2. **Consolidate**, about once a day: merge, supersede, re-check stale
   decisions. Asynchronous, and may use a stronger model (§7).
3. **Deliver**, on every hook firing: read compiled files, match, inject.
   Synchronous, no model.

Only loop 3 is on the path the agent waits on.

---

## 4. Capture

### 4.1 Triggers

| Host event | What breadcrumbs does |
|---|---|
| `SessionEnd` | Spool the session's unprocessed transcript range and start the curator. This is the main trigger. |
| `PreCompact` | Spool the range that is about to be compacted, and start the curator. Context compaction is exactly when an unrecorded failure would otherwise be lost for good. |
| `Stop` | Spool only: advance the cursor. Start the curator only after a long stretch with nothing curated (debounced, e.g. every 30 minutes of work). No extraction ask. |
| `SubagentStop` | Spool the subagent's own transcript (`agent_transcript_path`) as a child episode. |
| `SessionStart` | **Sweep:** anything spooled but never curated (a crash, a killed terminal, a host with no end event) is curated now, in the background. |

The sweep is what makes capture reliable. Every other trigger is best-effort,
and the sweep catches what they missed. On a host with no hooks at all, any
`crumb` command or the MCP server starting up runs the same sweep.

v1's cursor machinery carries over: the byte cursor with file identity and
the durable backlog in `transcript.ingest()`. The spool stores the transcript
path, byte range, session id, branch, HEAD at start and end, and the commits
the session made (v1's `_session_commits`). It doesn't copy the transcript
until condensing.

### 4.2 The episode

The condenser turns a transcript range into an **episode**: a compact, typed
account of what happened. It is deterministic code, mostly v1's tool-call
pairing and outcome classification (`SUCCESS`, `FAILURE`, `INTERRUPTED`,
`NOT_RUN`, `UNKNOWN`).

An episode holds, in order, numbered events:

- user prompts, in full up to a bound;
- assistant text, trimmed;
- tool calls: the tool, normalized arguments (`shellcmd.normalize_command`),
  and the outcome;
- tool results: failures kept up to a few kB, successes reduced to a line;
- edits: file and size of change, not content;
- commits made, with subject lines.

Every event carries a **source**: `user`, `agent`, `tool`, or `external` (web
fetches, files from outside the repo, issue and PR bodies). The gate uses the
source to resist injection (§6).

Episodes are secret-scrubbed before they are written, with v1's
`secretscan` patterns plus redaction instead of rejection. They live in
`private/episodes/`, which is gitignored and machine-local, and expire on a
TTL. A long session is split into chunks of at most about 30k tokens, cut at
user-prompt boundaries.

Why condense instead of handing the model the raw transcript: it cuts cost
roughly tenfold, it removes bulky tool output that buries the signal, and it
gives every claim the curator makes an event number to cite.

---

## 5. The curator

### 5.1 How it runs

- **Launched by a hook, never by the agent.** On Claude Code it is an
  `"async": true` command hook, so the host doesn't wait. Elsewhere the hook
  detaches its own process.
- **One at a time per store.** A side lock in `private/curator/` makes it
  single-flight. A second trigger while one runs just enqueues its episode.
- **Takes the store lock only to commit.** Model calls happen outside the
  lock. At commit time the curator re-reads every record it plans to touch.
  If one changed since it read it, that operation becomes a proposal
  instead.
- **Never fails the host,** like every hook. Errors go to the hook log, with
  counts and never content (`hooklog.py`).

### 5.2 The brain: the host's own CLI

The curator reaches a model through a **brain adapter**: a subprocess call to
an agent CLI that is already installed and signed in.

| Brain | Command (sketch) | Auth |
|---|---|---|
| Claude Code | `claude -p --model haiku --output-format json --json-schema <schema> --settings '{"disableAllHooks": true}'`, with the episode on stdin | The person's Claude Code login, including Pro/Max subscriptions. No key needed. |
| Codex | `codex exec --model gpt-6-luna --json …` *(flags unverified)* | The person's ChatGPT sign-in *(unattended use unverified)* |
| None | — | Fallback (§9.4) |

Rules for the Claude adapter, from the hooks and headless docs:

- **Recursion guard.** The child is a real session and loads the same hooks.
  `disableAllHooks` doesn't switch off managed hooks, so the curator also sets
  `BREADCRUMBS_CURATOR=1`, and every breadcrumbs hook exits at once when it
  sees it.
- **Auth precedence.** In `-p` mode an `ANTHROPIC_API_KEY` in the environment
  wins over the subscription login. `crumb doctor` and the installer say which
  credential the curator will use, so nobody is billed through an API account
  by surprise. Never pass `--bare`: it skips the OAuth login.
- **No tools.** The curator reads only what it's given and runs nothing. The
  exact flag that disables tools is *unverified*.
- **Structured output.** `--json-schema` returns the operations in
  `structured_output`, so nothing parses model prose.

**Choosing a brain:** the store's config first, then the host that produced
the episode, then whatever is on `PATH`. The brain and model are recorded on
every record the curator writes (§10).

**Model size.** Capture is extraction into a fixed schema, which is well
within a Haiku-class model. Consolidation (§7) needs more judgment, so its
model is configured separately and may be larger. Both are settings, not
constants.

**Cost.** One call per episode chunk, about 10–30k input tokens and a few
hundred to a few thousand output tokens. On a subscription this uses the
person's quota. How hook-spawned `-p` calls count against usage limits is
*unverified*, and is a P2 measurement (§13).

### 5.3 Input

- The episode chunk.
- A **context slice:** the live records most related to the episode, found
  deterministically by v1's scoring over the files it touched and the words
  of its prompts. The model can then say "this confirms `dec_…`" or "this
  replaces `dec_…`" instead of writing a duplicate. Bounded to a few thousand
  tokens.
- The prompt: a versioned file shipped in the package. Its version is stamped
  on every record.

### 5.4 Output: operations, not files

The curator returns a list of operations. Code applies them, and the model
never writes a file.

| Operation | Meaning |
|---|---|
| `create` | A new record: type, title, the type's body fields, evidence, `triggers`, `severity`, `confidence` |
| `confirm` | An existing record was seen to hold again. Refreshes `last_confirmed` and adds evidence |
| `supersede` | A new record replaces an old one, and the episode shows why |
| `flag` | An existing record looks wrong or stale. Becomes a question or packet warning, never a status change by itself |
| `handoff` | Current focus, next action, open threads. Written as a dated entry, like v1's `--next` |
| `nothing` | Nothing in this chunk is worth remembering. This is the expected answer for most chunks |

Every claim cites **evidence**: episode event numbers, plus at least one
*portable* pointer (a commit, a file path, a command, a test name) if the
record is going to be committed. Episodes are machine-local, so a teammate
can't follow an event number.

### 5.5 What it looks for

Ranked by how much each is worth:

1. **Failed attempts:** a command or approach that failed and was abandoned
   or replaced; the user rejecting an approach. The *do-not-retry-unless*
   condition matters most.
2. **Traps:** something broke in a surprising way and needed a workaround.
3. **Decisions with their reasons:** a choice between options, an instruction
   from the user that will still matter tomorrow.
4. **Verifications:** something was checked, with its result and how.
5. **Open threads:** unanswered questions, the next step.
6. **Corrections and preferences:** "don't do X", "always Y". These are
   candidates for promotion to `CLAUDE.md`, which only a person can do.

It is told what to skip: routine work, anything obvious from the code or the
commit log, and anything that only mattered for that session.

---

## 6. The gate

Every curator operation passes the same deterministic gate as any other write,
plus checks that exist because a model wrote it:

1. **Schema:** v1's `validate`, unchanged.
2. **Evidence resolves.** Every cited event exists in the episode. Every quote
   a record carries appears verbatim in the episode. A claim the model can't
   tie to what happened is dropped. This is the main defense against made-up
   records.
3. **Secrets:** scanned again. A hit drops the operation, not the run.
4. **Injection.**
   - A record whose only evidence comes from `external` events gets
     `confidence: low`. It can't raise a guard verdict above `READ_FIRST`, and
     it can't be a promotion candidate.
   - Instruction-like text (v1's `audit` check) sends a record to
     `quarantined`, not `active`.
   - The curator's prompt frames the episode as data. That framing helps but
     is not relied on.
5. **Dedup.** v1's near-duplicate check turns a `create` that repeats a live
   record into a `confirm` of that record.
6. **Admission.** v1's profiles apply unchanged, with the channel `curator`:
   - `solo`: admitted as `review_status: unreviewed`, `agent: curator`.
   - `team`: admitted as proposals (`needs-review`).
   - Promotion into `CLAUDE.md` / `AGENTS.md` is never automatic, under either
     profile.

### 6.1 v1 rules this changes on purpose

Roadmap §2.4 lists things that are "always wrong" in v1. v2 changes two of
them. Each change needs a decision record when it is built.

| v1 rule | v2 |
|---|---|
| Never write transcript content into committed records automatically. | Raw excerpts: still never. The curator writes *records* automatically: authored summaries with bounded quotes that passed the gate and the secret scan. |
| Never auto-retire, auto-merge or auto-delete a record; suggest, never do. | `supersede` is allowed under `solo` only when the episode shows the replacement explicitly: a user instruction, or the code changing. Every automatic status change is listed in the next session's packet under *Changed since last time*, with the one command that undoes it. Under `team` it is a proposal. Deletion stays prune-only. **Open** (§14, Q3). |

Kept unchanged: hooks never deny or allow, record text is data, no runtime
dependencies, version in one place, store-format changes go through
migrations.

### 6.2 Commits

The curator writes to the working tree and **never commits**. Records land in
git through the person's or agent's normal commits, so git review stays the
boundary for anyone with a shell ([`security.md`](security.md) §4.2). **Open**
(§14, Q6): whether a separate `crumb commit-memory` helper is worth having.

---

## 7. Consolidation

About once a day, or after N new records, the curator runs a consolidation
pass, started by a `SessionStart` sweep:

- **Clusters:** v1's near-duplicate and contradiction detectors
  (`lifecycle.py`) find candidate groups deterministically, as they do now.
  The model judges each group (merge, supersede, keep both, flag), where v1
  asks a person.
- **Staleness:** v1's `audit` already finds decisions whose evidence moved: a
  cited file rewritten, a contradicting newer record. The model gets the
  record plus a summary of the change and answers *still true*, *stale*, or
  *unsure*. *Unsure* becomes a question, never a status change.
- **Trap confirmation:** traps not seen for `ttl_trap_days` are checked the
  same way.

Consolidation never runs a recorded command, as in v1.

---

## 8. Delivery

Delivery stays deterministic and model-free. The change is *what* it matches
against.

### 8.1 Triggers instead of prose

When the curator creates a record, it also writes when the record applies:

```yaml
triggers:
  paths: [".github/workflows/release.yml", "breadcrumbs/__init__.py"]
  commands: ["git tag", "git push --tags", "gh release create"]
  tasks: ["cut a release", "publish to pypi", "tag a version"]
severity: high     # low | medium | high; the gate caps it (§6, step 4)
```

The compiler builds one trigger index from every live record. At hook time:

- **Guard** normalizes the action (v1's `shellcmd` normalization stays) and
  looks up paths and command prefixes in the index. A hit's severity picks the
  verdict on v1's ladder: `PROCEED`, `READ_FIRST`, `PAUSE`, `ASK_HUMAN`.
  Keyword scoring of prose against commands is no longer the main signal.
  v1 scoring stays as the fallback for records with no triggers (old records,
  hand-written ones).
- **The prompt hook** matches `tasks` phrases and their words on top of v1's
  retrieval. Synonyms come from the curator, so the hand-kept `aliases.txt`
  matters less.

This moves the judgment that guard's heuristics approximate today to
curation time, where a model is available and nobody is waiting.

### 8.2 What each hook delivers

| Hook | Delivers |
|---|---|
| `SessionStart` | v1's resume packet, plus *Changed since last time*: what the curator learned, superseded or flagged since this branch's last session |
| `UserPromptSubmit` | Up to 5 relevant records, as now |
| `PreToolUse` | Trigger-matched warnings with the record's do-not-retry condition |

The extraction ask goes away. The Stop hook stops holding the agent.

---

## 9. Host adapters

### 9.1 What an adapter answers

1. **When:** which host events trigger capture, and which deliver.
2. **Where:** how to find the transcript and parse it into the episode's event
   types.
3. **Which brain:** how to call the host's CLI headless.
4. **How to deliver:** hook output format, or files and MCP when there are no
   hooks.

### 9.2 Known hosts

| | Claude Code | Codex | No hooks (any agent) |
|---|---|---|---|
| Capture trigger | `SessionEnd`, `PreCompact`, `Stop`, `SubagentStop`; sweep at `SessionStart` | Hooks *unverified*; otherwise the sweep at the next `crumb` / MCP start, or a git `post-commit` hook | The sweep |
| Transcript | `transcript_path` in every hook payload | Session logs *(location and format unverified)* | None: episodes built from git alone (commits, diffs, messages) |
| Brain | `claude -p` | `codex exec` | Whatever brain is on `PATH`, else fallback |
| Delivery | Hooks | `AGENTS.md` signpost and MCP | Plain files, CLI, MCP |

Even git-only episodes are worth having: a reverted commit, a fix-up chain or
a "revert: …" message is a failed attempt v1 never recorded.

### 9.3 Packaging

- **Claude Code:** one plugin bundling the hooks, the MCP server and a short
  skill, installed with `/plugin install`. The plugin needs the `crumb`
  executable. **Open** (§14, Q8): whether its hook commands should run through
  `uvx crumb-kit …` so the plugin works with nothing preinstalled.
- **Everything else:** `pip install crumb-kit` / `uv tool install crumb-kit`,
  then `crumb init`, which detects the host and brain and says what it found.

### 9.4 Fallback with no brain

With no usable brain, v2 runs v1's deterministic path: the regex miner writes
jots, v1 scoring delivers, and the extraction ask is available as an opt-in.
`crumb doctor` says that the curator is off, and why.

---

## 10. Store format

The store stays v1's: same directories, record types, ids and statuses. The
additions:

| Field / path | Purpose |
|---|---|
| `agent: curator` | Who wrote it (the channel), as v1's `agent` |
| `curator: {brain, model, prompt}` | Provenance, e.g. `{brain: claude, model: haiku, prompt: capture-v3}` |
| `episodes: [ep_…]` | Machine-local evidence; never the only evidence of a committed record |
| `triggers:` / `severity:` | §8.1 |
| `private/spool/`, `private/episodes/`, `private/curator/` | Machine-local, gitignored |

This is schema 5, through v1's migration machinery. v1 builds refuse a v5
store through `requires:` (`compat.py`). A v1 store migrates forward with no
loss. Old records have no triggers and use the fallback scoring.

---

## 11. Evaluation: proving v2 is better before building most of it

The evals come first (phase P0). v2 is worth building only if it beats v1 on
these.

- **E1. Autonomy.** Replay recorded sessions through the curator with an agent
  that has no memory instructions. Measure:
  - recall against hand-labeled *gold* memories per session (decisions, failed
    attempts, traps);
  - precision: was each record judged useful?
  - fabrication: claims the gate dropped, plus claims a person finds wrong
    despite passing the gate.
- **E2. Repeat failure.** Session 1 fails at approach X. Session 2, with a
  fresh agent, gets the same task. It passes if the agent is warned *before*
  retrying X. This is [`architecture.md`](architecture.md) §5's third bar as a
  test. It extends `evals/task_replays/`.
- **E3. No regression.** v1's relevance, delivery and critical evals keep
  passing.
- **E4. Cost.** Hook milliseconds (from the hook log), curator tokens per
  session, and time from session end to record written.

**The headline comparison:** v2 with no instructions must beat v1 *with* its
`CLAUDE.md` instructions on E1 recall of failed attempts and on E2, without
losing on E3.

**Gold data:**
- This repo's history: 269 commits, and the field reports and retest plans in
  `docs/reviews/`, which list what went wrong in detail.
- Real transcripts, if the operator provides them. They stay local and are
  never committed.
- Synthetic scenarios scripted for E2.

**Keeping CI deterministic:** model outputs are recorded once per prompt
version as cassettes and replayed in CI, so the gate, compiler and delivery
are tested exactly. A live-model eval job runs by hand and before releases,
and its numbers are tracked like `evals/baseline.json`.

---

## 12. Coexistence with v1

- v1 stays released and maintained on its current minor line until v2 beats
  it on §11.
- v2 is built in this repository on the same store, so most of the package
  carries over: the store, the gate, delivery and the safety modules.
- The curator ships first as **opt-in** on top of the v1 store
  (`crumb curator enable`), in shadow mode, before it writes anything live
  (§13, P2).
- The major version and naming are **Open** (§14, Q1).

---

## 13. Build phases

Each phase ends at a gate: the numbers from §11 it must reach before the next
phase starts.

| Phase | Builds | Gate |
|---|---|---|
| **P0** | Gold set; E1/E2 harness; v1 baseline numbers, with and without instructions | Baseline recorded |
| **P1** | Spool, sweep, condenser, episodes, secret scrubbing. No model. | Episodes cover the gold events; hook budgets unchanged |
| **P2** | Curator v0: Claude brain, schema, gate. **Shadow mode:** proposals go to `private/curator/proposals/`, nothing enters the store. `crumb curator review` shows them next to what the agent actually recorded. | E1 recall and fabrication on gold; quota cost measured on a real subscription |
| **P3** | Proposals admitted to the store; auto-handoff; *Changed since last time* | E2 passes on the scenarios; E3 does not regress |
| **P4** | Triggers, the trigger index, guard matching on triggers with v1 fallback | Guard critical cases pass; false-warning rate below v1's |
| **P5** | Consolidation pass | Duplicate and stale counts on this repo's store fall, with no wrong supersede in review |
| **P6** | Codex adapter; git-only episodes | E1 on Codex sessions |
| **P7** | Shrink the `CLAUDE.md` block to "memory is automatic; `crumb remember` if you want to be explicit"; extraction ask off by default | G1 holds in a field test |

---

## 14. Open questions

### 14.1 Decisions for the operator

- **Q1. Name and version.** Is v2 still `crumb-kit` / `breadcrumbs`, as the
  next major (1.0.0), or a new name? *Leaning:* same package, 1.0.0. The store
  carries over, and users keep their install.
- **Q2. On by default?** After install, does the curator run without being
  asked, or is it one `crumb curator enable`? It spends the person's model
  quota. *Leaning:* on by default for new installs, with the cost shown at
  `init`; opt-in for upgraded v1 stores.
- **Q3. Automatic supersede under `solo`?** §6.1 allows it with explicit
  evidence and a visible undo. The alternative is proposals only, everywhere.
- **Q4. Episodes leave the machine.** The curator sends a condensed,
  secret-scrubbed episode to the same provider that already saw the session.
  Is that acceptable by default, and does `team` need an opt-out?
- **Q5. Explicit `remember`.** Is an agent's own `crumb remember` trusted over
  the curator's version of the same event, or merged with it?
- **Q6. Commits.** The curator never commits (§6.2). Is that right, or should
  memory have its own commits?
- **Q7. Memory across repositories.** Preferences that follow a person
  between repos are useful, and they are a different store with different
  privacy rules. In scope for v2, or later?

### 14.2 Facts to verify before relying on them

- **Q8.** Can a Claude Code plugin's hook commands run `uvx crumb-kit …`
  reliably on all three platforms?
- How hook-spawned `claude -p` calls count against subscription usage limits.
- The exact `claude -p` flag that gives the curator no tools.
- `async: true` hook behavior on `SessionEnd`: does the detached process
  survive the host exiting?
- Codex: whether it has hooks; `codex exec` flags for model and structured
  output; whether ChatGPT sign-in is allowed for unattended runs (OpenAI's docs
  recommend API keys for automation); where session logs live, and their
  format.
- How long hosts keep transcripts before cleaning them up. This sets how
  promptly the sweep must condense a spooled range.
