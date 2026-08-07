# Record Schema

The concrete data contract for `.project-memory/`: directory layout, git-tracking
policy, the manifest, canonical frontmatter, record identity, field population, the
status/privacy vocabularies, and the body templates.

---

## 1. Installed directory layout

`crumb init` creates this tree in a target project:

```text
.project-memory/
  README.md
  manifest.yml

  current.md
  handoff.md
  open-questions.md
  known-traps.md

  decisions/      .gitkeep
  attempts/       .gitkeep
  verifications/  .gitkeep
  sessions/       .gitkeep
  ideas/          .gitkeep

  generated/
    README.md
    resume-packet.md          # placeholder until the first resume/reindex
    # guard-prefilter.json    — not created by `init`; written by the first
    #                           `resume`/`reindex` (or any record write)

  private/
    README.md

  index/
    README.md
```

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
   projections (`generated/resume-packet.md`, `guard-prefilter.json`) are committed — this serves the "cloud
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
schema_version: 1
created_at: 2026-06-25T14:30:00-05:00
project: <project-name>
# Tracking policy chosen during `crumb init`:
session_tracking: full        # full | distillate
commit_generated_projections: true   # commit generated/*.md (indexes always ignored)
```

`schema_version` is `1` for this build. `project` is auto-derived from the project
root directory name. `created_at` is ISO-8601 with timezone.

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
scope: project             # project | feature | branch | local | private
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
  (session), `trap`, `q` (question).

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
| **Defaulted** (overridable) | `status: active`, `confidence: medium`, `privacy: repo-safe`, `review_status: unreviewed`, `scope: project`, `tags: []`, `supersedes/superseded_by/expires_at: null` | constants |
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

## 9. Privacy meanings

| Privacy | Meaning |
|---|---|
| `repo-safe` | May be committed. |
| `local-private` | Must live under `private/` or an external private store. |
| `secret-prohibited` | Must not be stored in project memory at all. |

---

## 10. Body templates

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
