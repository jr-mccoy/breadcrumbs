# Record Schema

The concrete data contract for `.project-memory/`: directory layout, git-tracking
policy, the manifest, canonical frontmatter, record identity, field population, the
status/privacy vocabularies, the body templates, store aliases, the generated
projections and search index, and the promoted-rules block `crumb promote`
writes outside the store.

---

## 1. Installed directory layout

`crumb init` creates this tree in a target project:

```text
.project-memory/
  README.md
  manifest.yml

  current.md
  handoff.md
  open-questions.md           # schema 3: generated index of questions/
  known-traps.md              # schema 3: generated index of traps/
  # aliases.txt               — optional, hand-written: store stemmer aliases (§11)

  decisions/      .gitkeep
  attempts/       .gitkeep
  verifications/  .gitkeep
  sessions/       .gitkeep
  ideas/          .gitkeep
  inbox/          .gitkeep      # committed jots (schema_version 2+)
  traps/          .gitkeep      # one file per trap (schema_version 3+)
  questions/      .gitkeep      # one file per question (schema_version 3+)
  handoffs/       .gitkeep      # one handoff per non-default branch (schema_version 4+)

  generated/
    README.md
    resume-packet.md          # placeholder until the first resume/reindex
    # guard-prefilter.json    — these three are not created by `init`; written by
    # related.json            — the first `resume`/`reindex` (or any record write)
    # conflicts.json

  private/
    README.md
    inbox/                    # machine-local jots — never committed
    # usage.json              — local surfacing counts, written on demand
    # migrations/<stamp>/     — pre-migration store backup
    # .write-lock             — present only while a command writes the store (WM-51)

  index/
    README.md
    # search.sqlite           — disposable search index, built at reindex once
    #                           the store has 200+ indexable records (§12)
```

**Schema versions.** `manifest.yml` records the on-disk format version and
`crumb migrate` moves a store forward; `validate` fails a store that is behind
(`run \`crumb migrate\``) or ahead (`upgrade crumb-kit`). Readers tolerate the
previous shape for one major version, so an un-migrated store keeps working.

| Version | Change |
|---|---|
| 1 | The original layout. |
| 2 | `inbox/` and `private/inbox/` — the jot tier (WM-03). Both are created empty; a store that never migrates simply has no jots. |
| 3 | `traps/` and `questions/` — one file per trap and per question (WM-22), with the ids they already had; `known-traps.md` and `open-questions.md` become generated indexes (§10). Readers decide by the manifest's `schema_version`, never by what is on disk, so a schema-2 store keeps reading and writing blocks. |
| 4 | `handoffs/` — one handoff per branch (WM-50). A capture on a branch other than the default branch writes `handoffs/<branch-slug>.md`; `handoff.md` stays the default branch's (§10). The step creates the directory only. A schema-3 store keeps one `handoff.md` for every branch. |

---

## 2. Git-tracking policy

**Committed by default:**

```text
.project-memory/README.md
.project-memory/manifest.yml
.project-memory/current.md
.project-memory/handoff.md
.project-memory/open-questions.md
.project-memory/known-traps.md
.project-memory/decisions/
.project-memory/attempts/
.project-memory/verifications/
.project-memory/sessions/
.project-memory/ideas/
.project-memory/inbox/
.project-memory/traps/
.project-memory/questions/
.project-memory/handoffs/
.project-memory/aliases.txt
.project-memory/generated/README.md
.project-memory/index/README.md
```

**Always gitignored:**

```gitignore
.project-memory/private/**
.project-memory/index/**
!.project-memory/index/README.md
.project-memory/generated/*.local.md
.project-memory/generated/*.tmp
```

### Two policies chosen at `init`

Recorded in `manifest.yml` so every later command stays consistent:

1. **`commit_generated_projections`** (default `true`). When `true`, the generated
   projections (`generated/resume-packet.md`, `guard-prefilter.json`, `related.json`, `conflicts.json`) are committed — this serves the "cloud
   agent with no CLI" user story (a read-only agent gets a pre-built catch-up
   file). Each Markdown projection carries a source commit/hash header so
   staleness is visible. Flip to `false` (`init --no-commit-generated`) to keep a
   clean history; `init` then adds `.project-memory/generated/*.md` **and
   `generated/*.json`** to `.gitignore` while keeping the README.
   **SQLite and vector indexes (`index/**`) are always ignored regardless.**

2. **`session_tracking`** (`full` | `distillate`):
   - `full` — commit dated session records, so handoffs and history travel across
     people and devices.
   - `distillate` — `sessions/` stays local (gitignored); only promoted
     `decisions/` and `attempts/` are committed, keeping the shared repo lean.

   `init` prompts for this (or accepts `--session-tracking <full|distillate>`,
   defaulting to `full` non-interactively) and writes the matching `.gitignore`
   rules. Solo multi-device work favors `full`; large team repos often favor
   `distillate`.

   The policy also decides what the projection freshness stamp covers: a record
   directory the store keeps *local* is not a shared input, so under `distillate`
   the `inputs_hash` skips `sessions/` (as it skips any record directory the
   committed `.gitignore` excludes). Otherwise the committed packet would carry a
   hash no clone could reproduce, and `validate` would report a permanent,
   unfixable "stale projection" that ping-pongs between machines. The policy value
   itself is folded into the hash, so flipping it invalidates the stamp once,
   deliberately.

`init` writes the managed `.gitignore` block; `audit`/`validate` read the manifest
rather than guessing.

---

## 3. Manifest (`manifest.yml`)

The per-project control file. Carries the schema version (so `validate` can check
forward-compat) and the tracking policies chosen at `init`:

```yaml
schema_version: 4
created_at: 2026-06-25T14:30:00-05:00
project: <project-name>
# Tracking policy chosen during `crumb init`:
session_tracking: full        # full | distillate
commit_generated_projections: true   # commit generated/*.md (indexes always ignored)
extraction_prompt: true   # Stop hook may hold the stop once per unit of work
                          # to ask the agent for decision/attempt records
jot_ttl_days: 14          # how long a `crumb jot` stays listed
```

Behaviour keys, all optional and all with the default that is right for a store
that has never heard of them — a key absent from an older manifest must never
change what that store does:

| Key | Default | Effect |
|---|---|---|
| `extraction_prompt` | `true` | The Stop hook may hold the stop once to ask for records. `false` leaves only the silent machine snapshot — it stops the *prompt*, not the transcript mining. |
| `jot_ttl_days` | `14` | The older spelling of `ttl_jot_days` (below). Still read; when both are set, `ttl_jot_days` wins. |
| `capture_corrections` | `true` | The `UserPromptSubmit` hook writes a prompt that opens like a correction to `private/inbox/`. `false` turns that off. |
| `subagent_extraction` | `false` | **Reserved.** Whether a finished subagent may be held for its own extraction turn. Nothing reads it yet; it waits on the prompt-fatigue field test in `open-questions.md`, and it defaults off because the parent's Stop hook already asks once per unit of work. |

**Lifespans (WM-30).** One flat key per type, `ttl_<type>_days` (flat because
the manifest reader parses flat `key: value` lines). A value that is
unparseable, zero or negative falls back to the default rather than disabling
decay or failing a write.

| Key | Default | What reaching it does |
|---|---|---|
| `ttl_jot_days` | `14` | A jot's `expires_at` is set to `created_at` + this at write; an expired jot drops out of `crumb inbox` and the resume packet. |
| `ttl_question_days` | `45` | An open question older than this is `AGING` in `crumb questions` (`--aging` lists only those). It stays open and listed. |
| `ttl_verification_days` | `90` | A **settled** verification (`fixed`, `not_applicable`) gets `expires_at` = `created_at` + this at write. An actionable one (`open`, `regressed`, `inconclusive`) never expires; once its `updated_at` (else `created_at`) is this old the packet asks for a recheck. |
| `ttl_trap_days` | `180` | An active trap not confirmed (`last_confirmed`) — or, never confirmed, not written — within this raises a packet warning. |
| `ttl_current_days` | `14` | `current.md` unchanged this long raises a packet warning. The age is the last git commit touching it (`0` when it has uncommitted changes), or its mtime outside git. |

Decisions and attempts have no lifespan: a decision holds until something
supersedes it, and an attempt records something that happened. See §4 for what
`expires_at` does to a record.

`schema_version` is `4` for this build; see §1 for what each version changed.
`project` is auto-derived from the project root directory name. `created_at` is
ISO-8601 with timezone.

---

## 4. Canonical frontmatter

Every durable record is Markdown with YAML frontmatter. Values in `<angle
brackets>` are placeholders an implementation fills — never literals to copy (e.g.
do not emit `abc1234` as a default commit).

```yaml
id: dec_20260625_repo-local-memory-source-of-truth   # computed: <type-prefix>_<YYYYMMDD>_<slug>
type: decision
slug: repo-local-memory-source-of-truth              # the human segment of the filename
title: Use repo-local Markdown as source of truth
status: active              # active | superseded | stale | disputed | rejected | quarantined
created_at: 2026-06-25T14:30:00-05:00
updated_at: 2026-06-25T14:30:00-05:00
created_by: <username>      # human username or agent label, auto-derived
agent: unknown             # unknown | agent | human | claude-code | codex | cursor | gemini | opencode | other
project: <project-name>    # auto-derived from repo/dir name
scope: project             # project | branch  (other text is accepted and read as project)
branch: <current-branch>   # auto-derived from git HEAD
commit: <short-sha>        # auto-derived from git HEAD
dirty_files: []            # auto-derived from git status
confidence: medium         # low | medium | high   (default: medium)
privacy: repo-safe         # repo-safe | local-private | secret-prohibited  (default: repo-safe)
review_status: unreviewed  # unreviewed | reviewed | needs-review  (default: unreviewed)
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
# last_confirmed: 2026-09-01   # traps only, optional — set by `crumb traps --confirm`
# promoted_to: CLAUDE.md       # decisions, attempts, traps — set by `crumb promote` (§13)
# promoted_at: 2026-09-22T20:17:34+00:00
# promoted_rule: <one line>    # only when `crumb promote --rule` overrode the rendered rule
tags:
  - memory
  - architecture
evidence:
  - type: commit
    ref: <short-sha>
  - type: command
    ref: npm test
```

**`evidence:` is the only evidence store.** There is no shared ledger file. Every
consumer reads this field: `resume` derives *Likely Relevant Files* from `file`/
`path` refs and *Verification Commands* from `command`/`test` refs, `guard` quotes
those same commands in its next-safest-action, and `search` folds the file refs
into path matching. Through 0.1.7 the scaffold also created an `evidence/refs.yml`
for a cross-record ledger; nothing ever read or wrote it, and it was removed rather
than given a writer — a second, hand-maintained copy of these pointers would have
had no validator, no consumer, and no way to detect a dangling reference. Stores
created by an older version can delete the file; nothing looks for it.

**`supersedes` / `superseded_by`** link a record to the ones it replaces and
back. `superseded_by` is set whenever a record is marked `superseded` (§8).
`supersedes` is written by `--supersedes <id>` on `remember`, `note idea` and
`verify` and the matching MCP parameters (the answer to a near-duplicate
refusal; see `cli-spec.md` → *Near-duplicate gate*), by `verify --recheck`
(the new verification supersedes the one it reran), by `consolidate --merge`
(every source) and by `rollup sessions` (every folded snapshot). Trap and
question files do not carry `supersedes`; the replaced one still gets
`superseded_by`. WM-34's `overlapping-decisions` rule treats two decisions
linked by `supersedes` as settled, not as a conflict.

**`expires_at`** is when a record decays (WM-30). It is set at write for jots
(`ttl_jot_days`) and for verifications with a settled outcome
(`ttl_verification_days`), and is `null` otherwise. A record past it keeps
`status: active` and stays on disk and findable by `search` (marked
`expired`), but leaves the resume packet's list sections and `guard`'s live set
— a match is shown under `history` instead of driving the verdict. `crumb
expired` lists such records. Expiry is not a status and nothing rewrites the
file: record the claim again if it still holds, or `mark-status` it `stale`.

**`promoted_to` / `promoted_at` / `promoted_rule`** (WM-40) say that a
decision, attempt or trap has been made a standing rule in the long-term tier:
the instruction file it went to (`CLAUDE.md` or `AGENTS.md`), when, and — only
when `crumb promote --rule` overrode the rendered text — the rule as given.
They are placed after `last_confirmed`, written by `crumb promote` and removed
by `crumb demote` or by retiring the record (§8, §13). Promotion is not a
status: the record stays `active`, stays in `search` (marked `promoted`) and in
`guard` at full weight, and leaves the resume packet's decision, attempt and
trap lists, which count it instead. `promoted_to` is what every reader keys on.

**`scope`** (WM-52) says whether a record is about the project or about the
branch it was written on. `project` is the default. `branch` means the record
describes that branch's state — the branch is the record's own `branch` field —
and applies only while that branch is checked out: on any other branch it
leaves the resume packet's decision, attempt, verification and inbox lists and
`guard`'s live set (a match is shown under `history`), is not injected by the
`UserPromptSubmit` hook, and is not a near-duplicate candidate for a record
written on this branch; it stays on disk and in `search`. Without git, on a detached HEAD, or with no recorded branch, a
branch-scoped record counts everywhere. `crumb jot` and `crumb verify` take
`--scope project|branch`; jots written by a hook (`source` other than `human` or
`agent`) default to `branch`. `crumb remember --scope` accepts free text, and
`validate` does not check the value; anything other than `branch` is read as
`project`.

---

## 5. Record identity (filename-canonical)

Identity is **filename-canonical**. The file's path is the single source of truth;
`id` and `slug` are computed from it and never stored as an independent authority.

- Filename pattern for directory records: `<YYYY-MM-DD>-<slug>.md`
  (e.g. `decisions/2026-06-25-repo-local-memory-source-of-truth.md`).
- The date must be a **real calendar date** — `2026-02-30` and `9999-99-99` are
  date-shaped but name no day, and an id built from one sorts and reads as if it
  did.
- `slug` = the human segment of the filename (everything after the date),
  restricted to `[a-z0-9]` runs joined by single hyphens — the charset the writer's
  `slugify` emits. `id` is an exact-match key; spaces and punctuation inside one
  (`dec_99999999_My Slug!`) are not something any lookup can be expected to handle.
- `id` = `<type-prefix>_<YYYYMMDD>_<slug>`, with type-prefixes:
  `dec` (decision), `att` (attempt), `ver` (verification), `idea`, `ses`
  (session), `jot`.
- **Traps and questions are undated** (schema 3+). Their filename is the slug
  alone and their id is prefix + slug: `traps/<slug>.md` → `trap_<slug>`,
  `questions/<slug>.md` → `q_<slug>`. These are the ids they carried as blocks —
  cited in decision records, commit messages and people's notes — so becoming
  files did not change them. The slug is `[a-z0-9]` runs joined by single `-` or
  `_` (block-era trap slugs used underscores). A question's slug is derived from
  its text (`question_item_id`: slugified, truncated at 48 characters with a
  6-character hash suffix when cut).
- **Question ids used to be `q:<slug>`.** The colon was the only id that was not
  a valid filename or a clean URI path segment, so every version that has
  `traps/` and `questions/` prints `q_<slug>` — on a schema-2 store too. The
  `q:<slug>` spelling is still accepted everywhere an id is read (`mark-status`,
  `show`, the MCP resources and tools).

Why filename-canonical: the filesystem cannot hold two files with the same name in
one directory, so ID uniqueness is enforced for free and id/slug/filename cannot
drift. `validate` recomputes `id`/`slug` from the filename and flags any
frontmatter that disagrees rather than trusting the stored value.

---

## 6. Field population — keeping capture under 90 seconds

Most fields are machine-filled so a human is asked for almost nothing.

| Population | Fields | Source |
|---|---|---|
| **Auto-derived** | `id`, `slug`, `created_at`, `updated_at`, `created_by`, `agent`, `project`, `branch`, `commit`, `dirty_files` | filename, system clock, git, environment |
| **Defaulted** (overridable) | `status: active`, `confidence: medium`, `privacy: repo-safe`, `review_status: unreviewed`, `scope: project`, `tags: []`, `supersedes/superseded_by/expires_at: null` | constants; `expires_at` is computed for jots and settled verifications, `supersedes` from `--supersedes` and the lifecycle commands (§4) |
| **Prompted** | `title`, the record body sections, optionally `tags` and `evidence` | interactive input |

A routine `remember`/`capture` requires only a title and a few body lines.

`agent` is derived, not assumed. With no `--agent` flag the CLI reads the
environment (`CLAUDECODE`, `CURSOR_AGENT`, `CODEX_SANDBOX`, …) and records the
harness it finds; when it finds none it records **`unknown`**, never `human`.
A missing flag is an absence of evidence, and `confidence`/`review_status` are
only worth reading if "a human stood behind this" is a claim someone actually
made — assert it with `--agent human`. The MCP tools and the Stop hook know
their writes are machine writes, so they fall back to `agent` instead of
`unknown`.

---

## 7. Non-git fallback (resolved)

Several frontmatter fields are git-derived (`branch`, `commit`, `dirty_files`).
When the project is **not** a git repo, the tool uses defined sentinels everywhere:

| Field | Non-git sentinel |
|---|---|
| `branch` | `(no-git)` |
| `commit` | `(no-git)` |
| `dirty_files` | `[]` (empty list) |

`init` detects whether the project is a git work tree and prints a notice when it is
not. Phases 3–6 (record writers, `resume`, `guard`, `audit`) consume these exact
sentinels so behavior is consistent: a record showing `branch: (no-git)` is not
flagged as a branch mismatch, and staleness logic that relies on commit-distance
degrades gracefully (age-based signals still apply).

---

## 8. Status meanings

| Status | Meaning |
|---|---|
| `active` | Current and safe to consider. |
| `superseded` | Replaced by a newer record. Must include `superseded_by`. |
| `stale` | Possibly outdated; must be revalidated. |
| `disputed` | Conflicts with another record, code, tests, docs, or user instruction. |
| `rejected` | Considered and intentionally not used. |
| `quarantined` | Suspected unsafe/private/poisoned; do not use for agent guidance. |

Traps use this vocabulary. **Questions have their own**, because no lifecycle
word says "somebody answered this":

| Question status | Meaning |
|---|---|
| `open` | Unresolved. The only live status: listed by `resume`, counted by `guard`'s open-blocker floor, aged into a staleness warning. |
| `answered` | Resolved — the answer exists (name it in `--reason`). |
| `closed` | Retired without an answer: withdrawn, obsolete, won't pursue. |

`validate` checks a question file's `status` against this list and every other
record's against the one above.

Setting a promoted record (§13) to `superseded`, `stale`, `rejected`,
`disputed` or `quarantined` also demotes it: its rule leaves the instruction
file and its `promoted_*` keys are removed.

## 9. Privacy meanings

| Privacy | Meaning |
|---|---|
| `repo-safe` | May be committed. |
| `local-private` | Must live under `private/` or an external private store. |
| `secret-prohibited` | Must not be stored in project memory at all. |

---

## 10. Body templates

### Jot record (`inbox/` or `private/inbox/`, schema_version 2+)

```markdown
## Note
```

One section, because the moment it needs a second one it has become a record and
should be promoted into one. Type-specific frontmatter:

| Key | Meaning |
|---|---|
| `source` | Who or what wrote it: `human`, `agent`, `prompt`, `transcript`, `hook`. **Required** (validate §16.9c) — a hook-written candidate and a note somebody typed are read very differently by whoever triages the inbox. |
| `expires_at` | Set automatically to `created_at + ttl_jot_days` (default 14; the older `jot_ttl_days` key is still read). An expired jot drops out of `crumb inbox` and the resume packet but stays on disk; `crumb expired` lists it. |
| `fingerprint` | Content identity (sha1 of kind + title) for an automatically written jot, so a hook that mines the same source twice does not write the same candidate twice. Scoped per session: the same failure recurring in a *later* session is news again. Optional. |
| `host_session` | The harness session that wrote it. What the Stop hook's extraction turn scopes its "what did this session produce" query to, so one terminal never asks an agent to triage another's findings. A subagent's candidates carry the *parent* session id, because the subagent's own id dies with it. Optional. |
| `scope` | The standard key (§4), defaulted by `source`: `project` for a `human` or `agent` jot, `branch` for one a hook wrote. A branch-scoped jot from another branch is left out of the resume packet's *Inbox*. |

A jot's `title` is its headline and its `## Note` is the body. They are the same
string for a jot somebody typed, and different for a mined one, whose note holds
a snippet of tool output that would make a useless heading — so every listing
shows the title.

Two rules that are not obvious from the shape:

- **Exempt from the evidence rule (§16.9).** A jot makes no claim it could
  support, which is the whole reason the tier exists. `confidence` is always
  `low`.
- **Never in a `guard` verdict.** A jot rides the same corpus switch as an idea
  (`include_ideas`): findable by `search`, never the basis of a verdict. An
  unconfirmed one-line note that happens to name the file being edited must not
  gate the edit.

`private/inbox/` is the only record directory outside the committed tree. It is
where every *automatic* writer must put things, because a hook cannot know
whether what it just saw is publishable. Promotion is what moves the content
into committed memory; the jot file itself stays private.

### Decision record

```markdown
## Context
## Options Considered
## Decision
## Rationale
## Consequences
## What Not To Retry
## Evidence
## Stale / Review Conditions
```

### Attempt record

```markdown
## Problem
## Tried
## Result
## Why It Failed / Succeeded
## Do Not Retry Unless
## Evidence
## Related Records
```

### Verification record

```markdown
## Subject
## Outcome
## Method
## Evidence
## Notes
```

A verification records a **finding about reality** — "I checked X; here is its
state" — the most common agentic output in maintenance/audit/review work, which
would otherwise be mis-filed as a decision/attempt. Write it with `crumb verify
<subject> --status <outcome> [--method <static|runtime|test>] [--evidence …]`.

Three type-specific frontmatter keys carry the structured fields (so `search` and
the resume packet can filter on them):

| Key | Values | Meaning |
|---|---|---|
| `subject` | free text | what was checked — a finding id, file, or claim |
| `outcome` | `fixed`, `open`, `regressed`, `not_applicable`, `inconclusive` | the verification result (distinct from the lifecycle `status`, which stays `active`) |
| `method` | `static`, `runtime`, `test` | how it was checked |

Like decisions/attempts, a verification needs at least one `--evidence TYPE REF`
or `--confidence low` (§16.9). It appears in the resume packet's **Verifications**
section (actionable outcomes first) and is searchable with `crumb search --type
verification --status open` (here `--status` filters on the outcome).

**A settled verification expires; an actionable one asks to be rechecked.**
`fixed` and `not_applicable` get `expires_at` = `created_at` +
`ttl_verification_days` (90) at write — they are the findings that silently go
stale. `open`, `regressed` and `inconclusive` never expire; once one is that
old the packet warns and points at `crumb verify --recheck <id>`, which reruns
its `command`/`test` evidence and writes a new verification (`method: runtime`,
outcome `fixed` or `open`) that supersedes it.

### Trap record (`traps/<slug>.md`, schema_version 3+)

```markdown
## Area / files
## Symptom
## Why
## Safe approach
## Verification
## Notes
```

Standard frontmatter with `type: trap` and the record status vocabulary (§8).
One type-specific key, optional: **`last_confirmed`** (a date, placed after
`expires_at`), the last time somebody checked the trap still holds — written by
`crumb traps --confirm <id>`, read by `crumb traps --stale` and by the
packet's `ttl_trap_days` warning (§3), which falls back to `created_at` for a
trap never confirmed. A promoted trap also carries `promoted_to` /
`promoted_at` (§4, §13). Write one with
`crumb note trap "<summary>" --area … --symptom … --why … --safe … --verify …`;
`crumb schema trap --template` prints that skeleton. Only filled sections are
written.

### Question record (`questions/<slug>.md`, schema_version 3+)

```markdown
## Question
## Why it matters
## Needs
## Notes
```

Standard frontmatter with `type: question` and the question vocabulary (§8,
`open` by default). Write one with `crumb note question "<question>" --why …
--needs …` (`crumb schema question --template`). An open question never
expires; one open longer than `ttl_question_days` (45) is listed as aging by
`crumb questions --aging`. Superseding a question (`--supersedes q_…`) marks
the old one `closed` with `superseded_by`.

Neither type is under the §16.9 evidence rule. The sections are the bullets
the block format always had, one heading each; `Notes` holds whatever a
migrated block carried that fits no bullet (free prose, status-change
comments).

**Before schema 3** a trap is a `## trap_<slug>: <summary>` block in
`known-traps.md` with `- Area / files:`, `- Symptom:`, `- Why:`,
`- Safe approach:`, `- Verification:`, `- Last confirmed:` and `- Status:`
bullets, and a question a `## Q: <question>` block in `open-questions.md` with
`- Opened:`, `- Why it matters:`, `- Needs:` and `- Status:`. A block with no
`- Status:` bullet counts as `active` (trap) / `open` (question). `crumb
migrate` step 3 moves each block into a file.

A promoted trap block also has a `- Promoted to: <file>` bullet (there is no
block form of `promoted_at` or `promoted_rule`). Like `- Status:` it is
bookkeeping, left out of the text keyword matching and the guard pre-filter
see. Migration step 3, and adoption of a hand-typed block at schema 3, turn it
into `promoted_to` frontmatter; a trap file's `promoted_to` is rendered back as
that bullet in the block-shaped view the readers share.

**From schema 3 the two singletons are generated indexes.** `known-traps.md` and
`open-questions.md` are rewritten at every reindex as one line per record —
`` - `<id>` [<status>] <summary> — `<path>` `` — under a `GENERATED INDEX`
comment. They are kept because a cloud agent without the CLI reads them, and
they are no longer inputs to `inputs_hash` (the files under `traps/` and
`questions/` are). A `## trap_…` / `## Q:` block typed into either file by hand
is still read (a file with the same id wins) and is **adopted** into its own
file at the next reindex. A block whose id already has a file with different
content is not adopted: it stays verbatim below the index under a `Not adopted`
comment for somebody to merge, and `audit` reports it as `unadopted-block`.

### Session record

```markdown
## Starting Context
## Work Completed
## Decisions Made
## Attempts / Failures
## Open Questions
## Files Touched
## Commands / Verification
## Next Action
```

The "Work Completed", "Files Touched", and "Commands / Verification" sections are
pre-filled from git (`log`, `status`, `diff --shortstat` since the last session
record — a summary line, not a per-file listing, so a large session cannot bloat
the record)
and edited by the human. A `--fast` capture writes a minimal session record (git
snapshot + "Next Action" only) and defers the narrative sections.

**Rollup record (WM-35).** `crumb rollup sessions --before <date>` replaces two
or more machine snapshots (placeholder Next Action) with one session record
titled `rollup: <first date>..<last date> (<N> sessions)`: *Work Completed* holds
one `- <date>: <text>` line per snapshot, *Next Action* is `(rolled up)`, and
`supersedes` lists the snapshot ids, which are deleted. Its `created_at`,
`updated_at`, `branch` and `commit` are copied from the last snapshot it
replaces (the filename date is the day it was written), so it never becomes the
newest session record the Stop hook diffs from.

### Handoff file

```markdown
# Project Handoff

_Last updated: <YYYY-MM-DDTHH:mm:ssZ>_
_Branch: <branch>_
_Commit: <short-sha>_

## Current Focus
## Next Action
## Blockers / Open Questions
## Active Decisions To Respect
## Failed Attempts To Avoid
## Known Traps
## Likely Relevant Files
## Verification Commands
## Stale If
```

**Branch handoffs (schema 4, WM-50).** On a store at schema 4, `crumb capture
session` on a branch other than the repository's default branch writes
`handoffs/<branch-slug>.md` instead of `handoff.md`, in exactly this format.
The default branch is `origin/HEAD`'s target when known, else a local `main`,
else a local `master`; with none of these, without git, or on a detached HEAD,
every capture writes `handoff.md`. The file name is the branch name slugified
(`[a-z0-9]` runs joined by `-`) and cut to 60 characters — as is when that
equals the branch name (`feature-x` → `handoffs/feature-x.md`), otherwise
followed by `-` and the first 6 hex digits of the branch name's SHA-1
(`feature/parser-rewrite` → `handoffs/feature-parser-rewrite-<6 hex>.md`), so
two branches never share a file. The first write of a branch handoff carries
over `handoff.md`'s *Current Focus* and nothing else. Readers (`resume`,
`guard`, `audit`, `memory://handoff`) use the current branch's file when it
exists and `handoff.md` otherwise. Branch handoffs are
inputs to `inputs_hash`. `current.md` has no per-branch form. `crumb prune
handoffs` deletes one whose branch exists neither locally nor on `origin` and
whose `_Last updated_` is at least 30 days old.

---

## 11. Store aliases (`aliases.txt`)

Optional, hand-written and committed: the project's own synonyms for the
stemmer, so a query for one name meets a record that uses another.

```text
# first word is canonical; the rest fold to its stem
auth authn authz login
billing invoicing ledger
```

- One group per line, whitespace-separated words; every word folds to the first
  word's stem. `#` starts a comment; blank lines are ignored.
- A word already claimed by an earlier group keeps its first meaning, so adding a
  line never changes what an older line did. Chains resolve to a fixpoint.
- A line with fewer than two words, or a word already in an earlier group, is
  skipped and reported by `audit` as an `aliases` warning.
- Applied wherever stems are compared: `search`, `guard` and the hook
  pre-filter. It is committed because a teammate's clone must stem the same way,
  and it is part of `inputs_hash` because it changes what the projections
  contain — editing it makes them stale until the next reindex.

`crumb search --explain` prints the stems a query became.

---

## 12. Projections and the search index

Rebuilt by every reindex; never a source of truth.

| File | Committed | Contents |
|---|---|---|
| `generated/resume-packet.md` | per `commit_generated_projections` | The bounded resume packet, with a `source_commit` / `inputs_hash` / `generated_at` header. |
| `generated/guard-prefilter.json` | per `commit_generated_projections` | Token/path index the `PreToolUse` hook reads. Unstamped. |
| `generated/related.json` | per `commit_generated_projections` | `{"_generated", "inputs_hash", "related": {id: [up to 3 ids]}, "skipped": null \| reason}` — "see also" for every live item, read by `crumb show` and `memory_show`. |
| `generated/conflicts.json` | per `commit_generated_projections` | `{"_generated", "inputs_hash", "conflicts": [{"rule", "ids", "similarity", "message"}]}` — pairs of live records that may contradict each other (WM-34). |
| `index/search.sqlite` | never (gitignored) | The disposable search index. |

**`related.json`** relates live items (status `active`; for questions, `open`)
by pure overlap — shared declared files ×6, shared tag stems ×4, shared
non-ubiquitous specific stems ×1 — keeping pairs that reach
`GUARD_NOISE_FLOOR`, best first, ties broken by id. The score is deliberately
machine-independent (no branch, clock or commit-distance decay), so every clone
computes the same file. Above 2000 live items `related` is empty and `skipped`
names the reason. `validate` and `audit` check its `inputs_hash` like the
packet's.

**`conflicts.json`** holds what two rules find among active, unexpired
records. `retry-after-do-not-retry`: an attempt with a *Do Not Retry Unless*
section and a decision created after it whose *Decision* section is at least 0.5
similar to the attempt's *Tried* section (Jaccard over specific stems), or
shares a declared file with it; `ids` is `[decision, attempt]`.
`overlapping-decisions`: two decisions at least 0.7 similar by the
near-duplicate measure, created more than 7 days apart, neither listing the
other in `supersedes`. `similarity` is the text overlap (rule 1) or the
near-duplicate score (rule 2). The file reads `created_at` dates and never the
clock, so every clone computes the same file; `validate` and `audit` check its
`inputs_hash`. The resume packet renders the first three as warnings and
`audit` reports up to ten as `possible-contradiction`.

**`index/search.sqlite`** is a plain SQLite inverted index (postings of specific
stems, tag stems and files per record) over decisions, attempts, verifications,
ideas and committed jots. It is built only once those number at least 200
(`crumb reindex --search-index` builds it regardless), stamped with the
`inputs_hash` it was built from, and consulted only while that still matches;
`search` returns exactly the same results with or without it. It needs the
standard-library `sqlite3` module and is skipped where that is missing.
Deleting `index/` is always safe.

---

## 13. The promoted-rules block (`CLAUDE.md` / `AGENTS.md`)

The one thing breadcrumbs writes into the long-term tier besides the `crumb
init` signpost. It lives in the project root's `CLAUDE.md` or `AGENTS.md`, not
in `.project-memory/`, and is not a projection: `reindex` never rebuilds it,
and the records' `promoted_*` keys (§4) are the other half of each entry.

```markdown
<!-- >>> breadcrumbs promoted rules (managed by `crumb promote`) — edit with crumb promote/demote, not by hand >>> -->
## Project rules promoted from memory
- Use sqlite for the cache. _(why: concurrent writers corrupted the JSON file; source: `dec_20260922_use-sqlite-for-the-cache`)_
- Do not retry: pickling the cache — unless the classes are frozen. _(why: class paths moved between releases; source: `att_20260922_pickle-the-cache`)_
- Gradle --stop corrupts the R.jar lock: stop the daemon by pid. _(why: the daemon holds the lock; source: `trap_gradlew-stop`)_
<!-- <<< breadcrumbs promoted rules <<< -->
```

- **Markers.** `PROMOTED_BEGIN` / `PROMOTED_END` in `breadcrumbs/promote.py`,
  distinct from the signpost block's, so each block can be rewritten, measured
  and removed without touching the other. `crumb init --remove-integrations`
  removes the signpost block only.
- **One bullet per source id**, the most recently (re)promoted last:
  `- <Rule>. _(why: <rationale>; source: \`<id>\`)_`, or `_(source: \`<id>\`)_`
  when there is no rationale. The rule is at most 200 characters and the
  rationale 160, whitespace collapsed; the rule's case is left alone (it may
  start with a command), a trailing `.` is dropped from both, and a rationale
  that only repeats the rule is left out. The rendering rules per
  kind are in `cli-spec.md` → `promote` and `demote`.
- **`source:`** is how the tool finds a line again. A bullet is any line in the
  block starting `- `; `demote`, the drift check and the demote-candidate check
  match it on the id in `` source: `…` ``. A line without one is reported by
  `audit` as a `demote-candidate` and can only be removed by hand.
- **Size.** `audit` measures the block, markers included, against
  `ADAPTER_BLOAT_CHARS` (4000) as `promoted-bloat`, separately from the
  signpost; `doctor`'s `promoted_rules` row reports rules and characters per
  file and fails when any one file's block is over that limit.
- **Empty means absent.** Demoting the last rule removes the block, markers
  and heading included.

Rules are added only by `crumb promote`; no MCP tool adds one
(`mcp-spec.md`). They are removed by `crumb demote` and by retiring the source
record (§8), which includes `memory_mark_status`. A hand edit that keeps the
`source:` id is read like any other line, and shows up in `audit` as
`promoted-drift` until `crumb promote <id>` re-renders it.
