# `.project-memory/` — Project Continuity Memory

This directory is a repo-local, human-readable ledger of durable project state for
human–agent software work. It is managed by [`breadcrumbs`](https://github.com/jr-mccoy/breadcrumbs)
but is **plain files first**: any human or agent can read it without the tool.

> **Memory is advisory.** Current user instruction, source code, tests, build
> output, current authoritative docs, and security policy outrank anything here. If
> memory conflicts with reality, it is marked `disputed` or `stale` — it does not
> override the present.

---

## Project memory protocol (for agents and humans)

**Before non-trivial work:**

1. Read `current.md` — what matters right now.
2. Read `handoff.md` — what to do first.
3. Review relevant records under `decisions/`, `attempts/`, `traps/` and
   `questions/` (`known-traps.md` and `open-questions.md` list them one line each).
   With the CLI, `crumb show <id>` prints any record by the id you see.
4. If the CLI is available, run `crumb guard "<proposed action>"`.
5. Check the inbox for untriaged short-term notes: `crumb inbox`.

**Mid-task:** a quick observation that is worth remembering but not worth a
record goes in with `crumb jot "<text>" --file <path>`. It expires on its own;
promote it with `crumb inbox promote <id> <type>` if it turns out to be durable.

**At session end:**

1. Run `crumb capture session --next "<what to do next>"` (add `--set "<heading>"
   "<text>"` per narrative section), or write a session record by hand. The bare
   `crumb capture session` prompts for each section, so it needs a terminal; with
   the `Stop` hook installed a snapshot is taken for you either way.
2. Record durable decisions and failed attempts as typed records.

A read-only cloud agent with no CLI can resume from these files directly:
`current.md`, `handoff.md`, `decisions/`, `attempts/`, `traps/`, `questions/`
(indexed by `known-traps.md` and `open-questions.md`), and
`generated/resume-packet.md`.

---

## What lives where

| Path | Contents |
|---|---|
| `manifest.yml` | Schema version + tracking policies chosen at `init`. |
| `current.md` | What matters right now (days to ~2 weeks). |
| `handoff.md` | What the next session should do first. |
| `open-questions.md` | Generated index of `questions/`, one line per question. |
| `known-traps.md` | Generated index of `traps/`, one line per trap. |
| `aliases.txt` | Optional. Synonym groups for search and guard, one per line (`billing payments`). |
| `decisions/` | One record per durable decision (`YYYY-MM-DD-slug.md`). |
| `attempts/` | One record per tried path + outcome + do-not-retry. |
| `traps/` | One file per reusable warning about a fragile area (`<slug>.md`, id `trap_<slug>`). |
| `questions/` | One file per unresolved ambiguity / blocker (`<slug>.md`, id `q_<slug>`). |
| `sessions/` | One record per work session. |
| `verifications/` | One record per `crumb verify` — "I checked X; here is its state". |
| `ideas/` | Potential future directions. Searchable (`crumb search --type idea`), but never the basis of a `guard` verdict — an idea is a proposal, not a finding. |
| `inbox/` | Short-term jots (`crumb jot`): one observation, a TTL, no evidence rule. Searchable, never the basis of a `guard` verdict. Promote the durable ones with `crumb inbox promote <id> <type>`; the rest expire. |
| `generated/` | Rebuildable projections — **not source of truth**. |
| `private/` | Local-only notes — **never committed**. Holds `inbox/` (jots written automatically, which must earn a commit by being promoted), `usage.json` (local surfacing counts) and `migrations/` (pre-migration store backups). |
| `index/` | Disposable search index (`search.sqlite`), built by `crumb reindex` once the store has 200+ records — **never committed** (except this kind of README). Safe to delete. |

Evidence — a commit, a test, a file, a PR — is recorded **per record**, in each
record's `evidence:` frontmatter (`crumb remember … --evidence commit SHA`). That
is the field `resume`, `guard` and `search` actually read. There is no separate
evidence ledger file; earlier versions scaffolded an `evidence/refs.yml` that
nothing ever read or wrote, and you can delete it if your store still has one.

Source-of-truth and status rules live in the tool's `docs/` (architecture,
record-schema, security).
