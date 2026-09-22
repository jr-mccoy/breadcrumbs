# Architecture

This document distills the system principles, source-of-truth rules, record
taxonomy, build philosophy, and code map for `breadcrumbs`. It is the conceptual map;
[`record-schema.md`](record-schema.md) is the concrete data contract and
[`cli-spec.md`](cli-spec.md) is the command surface.

---

## 1. System principles

1. **Plain files first.** Any agent or human can read `.project-memory/` without a
   special runtime.
2. **Typed records over transcript sludge.** Memory is structured enough to
   validate, search, audit, and guard against.
3. **Generated projections are not source of truth.** Resume packets, guard
   pre-filters, related-record maps, conflict lists, search indexes, and vector
   stores are rebuildable artifacts.
4. **Memory is advisory.** Current user instruction, code, tests, build output, and
   authoritative docs outrank memory.
5. **Status beats silent edits.** Use `active`, `superseded`, `stale`, `disputed`,
   `rejected`, and `quarantined` instead of quietly rewriting history.
6. **Failed attempts are first-class.** They prevent repeated expensive mistakes.
7. **Branch and commit context matter.** Memory written on another branch may be
   stale or misleading.
8. **Interop is layered.** Plain files → CLI → agent signposts → MCP → hooks →
   optional indexes/vectors.
9. **Security is part of memory design.** Memory can be stale, poisoned, private, or
   executable-adapter-adjacent.
10. **The system must degrade gracefully.** Read-only cloud agents still benefit from
    the memory files even if CLI/MCP/hooks are unavailable.

---

## 2. Source-of-truth rules

1. Canonical typed records are source of truth.
2. Generated projections are convenience only.
3. SQLite/FTS/vector indexes are disposable.
4. Agent-specific files (`AGENTS.md`, `CLAUDE.md`, Cursor/Gemini rules) are
   signposts. `CLAUDE.md` / `AGENTS.md` may also carry rules promoted from
   records (`crumb promote`); each names its source record, which stays the
   source of truth.
5. Memory cannot override: current user instruction, source code, tests, build
   output, current authoritative docs, or security policy.
6. If memory conflicts with reality, mark it `disputed` or `stale` and link
   evidence.
7. If a decision changes, create a **new** decision and set the old one to
   `superseded` (with `superseded_by`). `--supersedes <old-id>` on the writer
   does both in one step.
8. If a failed attempt becomes newly viable, update its status or create a new
   attempt/decision explaining why conditions changed.

---

## 3. Record taxonomy

| Type | Purpose | Path | Lifespan | Source of truth? |
|---|---|---|---|---|
| Current state | What matters right now | `current.md` | days to 2 weeks | yes |
| Handoff | What the next session does first | `handoff.md` (default branch); `handoffs/<branch-slug>.md` for any other branch (schema 4) | until resumed/superseded; a branch's is prunable once its branch is gone and it is 30+ days old | yes |
| Decision | What was decided/rejected and why | `decisions/YYYY-MM-DD-slug.md` | long-lived | yes |
| Attempt | What was tried, outcome, do-not-retry | `attempts/YYYY-MM-DD-slug.md` | long-lived if instructive | yes |
| Verification | A finding about reality: "I checked X; here is its state" | `verifications/YYYY-MM-DD-slug.md` | settled: expires after `ttl_verification_days` (90); actionable: until rechecked | yes |
| Trap | Reusable warning about fragile areas | `traps/slug.md` (schema 3; a block in `known-traps.md` before) | long-lived; confirm within `ttl_trap_days` (180) | yes |
| Open question | Unresolved ambiguity or blocker | `questions/slug.md` (schema 3; a block in `open-questions.md` before) | until resolved; aging after `ttl_question_days` (45) | yes |
| Idea | Potential future direction | `ideas/YYYY-MM-DD-slug.md` | reviewed periodically | yes |
| Session | What happened in one work session | `sessions/YYYY-MM-DD-tool-topic.md` | historical | yes (lower priority) |
| Evidence | Pointers to commits/tests/docs/issues/PRs | each record's `evidence:` frontmatter | with its record | yes |
| Jot | A short-term observation with a TTL: one line, no evidence rule | `inbox/YYYY-MM-DD-slug-xxxx.md` | `ttl_jot_days` (default 14) | yes, until promoted |
| Mined candidate | A jot a hook wrote from a transcript or prompt — unconfirmed | `private/inbox/` | same TTL | **no** — a candidate, never source of truth until promoted |
| Private note | Local-only personal/sensitive context | `private/` | local policy | local-only |
| Resume packet | Bounded generated boot summary | `generated/resume-packet.md` | regenerated | no |
| Guard pre-filter | Token/path index the `PreToolUse` hook reads before a risky call | `generated/guard-prefilter.json` | regenerated | no |
| Related records | Up to three "see also" ids per live item, by shared files/tags/stems | `generated/related.json` | regenerated | no |
| Possible contradictions | Pairs of live records that may argue with each other | `generated/conflicts.json` | regenerated | no |
| Trap / question index | One line per trap or question, for a reader without the CLI | `known-traps.md`, `open-questions.md` (schema 3) | regenerated | no |
| Search index | Inverted index that narrows `search`'s candidate set | `index/search.sqlite` | regenerated; machine-local | no |
| Store aliases | The project's synonyms for the stemmer | `aliases.txt` | hand-maintained | yes (configuration) |
| Promoted rule | A decision, attempt or trap made a standing instruction, one line naming its source | the promoted-rules block in `CLAUDE.md` / `AGENTS.md` (outside the store) | until demoted or its record is retired | no — the record is |

Evidence is **not a file of its own**. It is a frontmatter field on the record it
supports, which is what makes it consumable: `resume` builds *Likely Relevant
Files* and *Verification Commands* out of it, and `guard` cites those commands in
its next-safest-action. Through 0.1.7 `init` also scaffolded an `evidence/refs.yml`
for a cross-record ledger. Nothing read or wrote it in any released version, and it
was **removed** rather than given a writer — a hand-maintained second copy of these
pointers would have had no validator, no consumer, and no way to notice a dangling
reference, while the per-record field already answers the question. Old stores can
delete the file; no code looks for it.

`index/` was reserved space until the search index filled it. It is gitignored,
so it costs a user nothing — the difference from `refs.yml`, which shipped
committed, with example entries to clean up — and what it holds is disposable
in the strict sense: `index/search.sqlite` is built at reindex only once the
store has 200 indexable records, is used only while the `inputs_hash` it was
stamped with still matches, and only narrows which records `search` parses.
Matches and scores are identical with and without it, and deleting it costs
nothing but speed.

**Traps and questions became files at schema 3.** Through schema 2 each was a
`## ` block in one aggregate file, parsed whole on every hook firing, and every
edit was a splice into a file other writers were splicing too. They are now one
file each, with the ids they had as blocks. `known-traps.md` and
`open-questions.md` stay, because a reader without the CLI looks there, but as
generated indexes: one line per record, pointing at the file. Every reader gets
the same dict shapes from both layouts, and chooses between them by the
manifest's `schema_version`, never by what is on disk.

**Mined candidates are proposals, not findings.** A hook writes what four
deterministic regex rules noticed in a transcript. That is enough to be worth
offering and nowhere near enough to be a record: the miner has no idea whether a
file was edited four times because it is fragile or because a feature landed in
it. Candidates live in `private/inbox/` — gitignored, so a machine's guesses
never reach a teammate's clone — carry `confidence: low`, and become memory only
when somebody promotes them through the real writer, which applies the evidence
rule and the validate gate as usual.

**Ideas are searchable but never judged.** `ideas/` is in `search`'s corpus and
deliberately absent from `guard`'s: an idea is a proposal, exempt from the
evidence rule, and `guard`'s scoring band is kind-agnostic, so a speculative note
naming the right files would otherwise gate a real edit. See `cli-spec.md` →
`search`, and Fixture 12.

**Memory decays, and heuristics only ask (Phase 3).** Deciding that a claim is
wrong is the author's job, so the lifecycle code hides, warns or refuses and
never retires a record on its own. *Decay*: each type has a lifespan
(`ttl_<type>_days` in the manifest). A jot or a settled verification carries an
`expires_at`; past it the record keeps `status: active` and stays in `search`,
but leaves the packet's lists and `guard`'s live set (it is shown as history).
Things that must not silently vanish — an actionable verification, a trap, an
open question, `current.md` — never expire; age turns them into a packet
warning or an `--aging` listing instead. A cited file that is neither on disk
nor in HEAD is another warning, never a scoring input. *Dedup*: the writers
refuse a record that nearly repeats a live one of the same type (exit 3), and
the author answers with `--supersedes <id>` or `--allow-duplicate`; `audit`
and `consolidate` find the pairs that predate the gate, and `consolidate
--merge` replaces them only when somebody names the ids. *Conflict*: two
overlap rules write `generated/conflicts.json` at reindex, from `created_at`
dates rather than the clock so every clone computes the same file, and the
packet and `audit` word each hit as a question. The one deletion is `rollup
sessions`, which folds machine snapshots into a single session record.

**The three tiers connect (Phase 4).** Short-term memory is what is in flight
(`current.md`, `handoff.md`, jots, mined candidates); medium-term is the typed
records; long-term is the agent's instruction file, `CLAUDE.md` or
`AGENTS.md`, which the harness loads whole every session. `inbox promote`
already moved a jot into a record. `crumb promote` moves a record one tier
further: it writes one rule line, naming the record's id, into a managed block
of its own in the instruction file — separate from the signpost block, so
`--remove-integrations` and the signpost's bloat check keep their meaning —
and marks the record `promoted_to`. The record stays `active` and stays the
source of truth. The packet leaves it out of its lists, since the harness
already injects the rule; `guard` and `search` still see it. Demotion is the
way back down, and it is automatic when the record is retired: a rule nobody
believes any more must not stay in the file every session loads. `audit`
closes the loop in both directions — `promote-candidate` from the local usage
counts, `demote-candidate` and `promoted-drift` from comparing each rule with
its record. Promotion is CLI-only: an MCP tool that let an agent write its own
permanent instructions would be a persistence path for a prompt injection.

**Several agents, several branches, one store (Phase 5).** A store is shared
by every session in a checkout and, through git, by every branch. Three
mechanisms keep them from stepping on each other. *Handoffs per branch*: at
schema 4 a capture on a branch other than the default branch writes
`handoffs/<branch-slug>.md` rather than `handoff.md` (a hash suffix keeps
branches that slugify alike apart), and a resume reads its own branch's
handoff, falling back to `handoff.md` and saying which. A new branch handoff
inherits only `handoff.md`'s Current Focus, never another branch's Next
Action; `current.md` stays single because it is the project's focus. *Branch
scope*: a record with `scope: branch` — a verification of work in progress, a
jot a hook mined — applies only on the branch it was written on; elsewhere it
leaves the packet's lists, `guard`'s live set, the prompt hook's injection and
the near-duplicate candidates, and stays in `search`. *One writer at a time*:
every writing invocation — CLI, hook write, MCP writer — takes an exclusive
lock file, `private/.write-lock`, so two read-modify-write sequences cannot
interleave and lose an update. The CLI and MCP wait 2 seconds and then refuse;
a hook waits 0.5 seconds and then skips its write, because a hook must never
block its host. The holder refreshes the file every 15 seconds; a lock
untouched for 60 seconds, or whose process on this host is gone (POSIX), is
broken — by one waiter at a time, holding a short break file while it re-checks,
so two waiters cannot both take it. Read paths
never wait: `resume`, the listings, `search`, `guard`, the `SessionStart` and
`PreToolUse` hooks, and the prompt hook's injection.

See [`record-schema.md`](record-schema.md) for the directory layout and the
git-tracking policy.

---

## 4. Layered interop

```text
plain files  →  CLI  →  agent signposts  →  MCP  →  hooks  →  index    →  vectors
(always)        (built) (built)            (built) (built)   (built)     (not built)

hooks, in the order a session fires them:
  SessionStart → UserPromptSubmit → PreToolUse → (SubagentStop) → PreCompact → Stop
```

The baseline (plain files) must always work. Each higher layer is optional and
must have a manual fallback to the layer below it. A read-only cloud agent that can
only read files still resumes from `current.md`, `handoff.md` (or its branch's
`handoffs/<branch-slug>.md`), `decisions/`,
`attempts/`, `traps/` and `questions/` (indexed by `known-traps.md` and
`open-questions.md`). The search index sits above the CLI in the same way: a
missing, stale or unreadable index, or a Python without `sqlite3`, means the
full scan, never a different answer.

---

## 5. Build philosophy

Build the boring useful version first. The load-bearing order is:

```text
plain files
→ deterministic CLI
→ validation/audit
→ guard-before-action
→ fixtures/evals
→ dogfood
→ packaging
→ MCP
→ hooks
→ search/index acceleration
→ vectors if still needed
```

Three falsifiable bars:

- If it cannot help a read-only cloud agent by exposing clear files, it is not
  portable enough.
- If it cannot help a tired human capture a session in under 90 seconds, it is too
  heavy.
- If it cannot warn before a repeated failed attempt, it is just a scrapbook.

The goal is a small continuity engine — a project cockpit with labeled switches,
not a haunted attic of embeddings.

---

## 6. Code map

Everything is in the `breadcrumbs` package, standard library only.

| Module | Holds |
|---|---|
| `cli.py` | The CLI: record I/O, validate, the resume packet, search/guard scoring, audit, doctor, the integrations and the hook translators. The other modules call back into it. |
| `blockfiles.py` | Traps and questions as one file each (schema 3): reading them in the dict shape the block readers return, writing them, rebuilding `known-traps.md` / `open-questions.md` as indexes, adopting hand-written blocks, and migration step 3. |
| `related.py` | `generated/related.json`: "see also" by pure overlap, written at reindex. |
| `searchindex.py` | `index/search.sqlite`: build, freshness check, and the narrowed candidate set `search` uses when the index is fresh. |
| `migrate.py` | Ordered, idempotent store-format steps (2: inboxes, 3: trap/question files, 4: `handoffs/`), the manifest version write, the pre-migration backup. |
| `inbox.py` | Jots: writing, listing, promotion, dropping. |
| `lifecycle.py` | Record lifecycle (Phase 3): per-type TTLs and expiry, the packet's lifecycle and missing-evidence warnings, `verify --recheck`, near-duplicate similarity and the write gate, `supersedes` handling, clusters and `--merge`, contradiction rules and `generated/conflicts.json`, session rollup, and its `audit` findings. Reads the clock only through `cli._now()`. |
| `lifecycle_cmds.py` | The CLI surface of `lifecycle.py`: `expired`, `questions`, `consolidate`, `rollup` and the `verify --recheck` runner, imported only when one of them runs. |
| `promote.py` | The bridge to long-term memory (Phase 4): `promote` / `demote` and their CLI surface, the promoted-rules block in `CLAUDE.md` / `AGENTS.md` (rendering, reading, rewriting), the `promoted_*` fields and the trap-block bullet, auto-demote on retire (called from `set_record_status`), the "is it promoted" predicates the packet uses, and the `promoted-bloat` / `demote-candidate` / `promoted-drift` / `promote-candidate` audit checks and the doctor summary. |
| `handoffs.py` | One handoff per branch (schema 4): the default-branch rule, the handoff file name (slug, plus a hash when the slug is not the branch name), which file a capture writes and a resume or `memory://handoff` reads (and the label it reports), seeding a new branch handoff with `handoff.md`'s Current Focus, and `prune handoffs`. |
| `lock.py` | The store write lock: `store_lock(memory_dir, timeout)` over `private/.write-lock` (exclusive create; pid, time and host; a 15 s heartbeat; stale after 60 s untouched or a dead pid on this host; broken under an exclusive `.write-lock.break` with a re-check), an in-process lock per store for threads, re-entrant within a thread; the CLI, hook and MCP timeouts. Which CLI invocations take it is `cli._needs_lock`. |
| `transcript.py` | Deterministic transcript mining into jot candidates. |
| `hooks_common.py`, `hooks_prompt.py`, `hooks_compact.py` | Hook state, the `UserPromptSubmit` hook, the `PreCompact` / `SubagentStop` hooks. |
| `usage.py` | Local surfacing counts (`private/usage.json`). |
| `mcp_core.py`, `mcp_server.py` | The MCP adapter over the same core functions, and its SDK binding. |
