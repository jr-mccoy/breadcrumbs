# Architecture

This document distills the system principles, source-of-truth rules, record
taxonomy, and build philosophy for `breadcrumbs`. It is the conceptual map;
[`record-schema.md`](record-schema.md) is the concrete data contract and
[`cli-spec.md`](cli-spec.md) is the command surface.

---

## 1. System principles

1. **Plain files first.** Any agent or human can read `.project-memory/` without a
   special runtime.
2. **Typed records over transcript sludge.** Memory is structured enough to
   validate, search, audit, and guard against.
3. **Generated projections are not source of truth.** Resume packets, guard
   pre-filters, FTS databases, and vector stores are rebuildable artifacts.
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
   signposts only.
5. Memory cannot override: current user instruction, source code, tests, build
   output, current authoritative docs, or security policy.
6. If memory conflicts with reality, mark it `disputed` or `stale` and link
   evidence.
7. If a decision changes, create a **new** decision and set the old one to
   `superseded` (with `superseded_by`).
8. If a failed attempt becomes newly viable, update its status or create a new
   attempt/decision explaining why conditions changed.

---

## 3. Record taxonomy

| Type | Purpose | Path | Lifespan | Source of truth? |
|---|---|---|---|---|
| Current state | What matters right now | `current.md` | days to 2 weeks | yes |
| Handoff | What the next session does first | `handoff.md` | until resumed/superseded | yes |
| Decision | What was decided/rejected and why | `decisions/YYYY-MM-DD-slug.md` | long-lived | yes |
| Attempt | What was tried, outcome, do-not-retry | `attempts/YYYY-MM-DD-slug.md` | long-lived if instructive | yes |
| Verification | A finding about reality: "I checked X; here is its state" | `verifications/YYYY-MM-DD-slug.md` | until the subject changes | yes |
| Trap | Reusable warning about fragile areas | `known-traps.md` (or future `traps/`) | long-lived, reviewed | yes |
| Open question | Unresolved ambiguity or blocker | `open-questions.md` | until resolved | yes |
| Idea | Potential future direction | `ideas/YYYY-MM-DD-slug.md` | reviewed periodically | yes |
| Session | What happened in one work session | `sessions/YYYY-MM-DD-tool-topic.md` | historical | yes (lower priority) |
| Evidence | Pointers to commits/tests/docs/issues/PRs | each record's `evidence:` frontmatter | with its record | yes |
| Private note | Local-only personal/sensitive context | `private/` | local policy | local-only |
| Resume packet | Bounded generated boot summary | `generated/resume-packet.md` | regenerated | no |
| Guard pre-filter | Token/path index the `PreToolUse` hook reads before a risky call | `generated/guard-prefilter.json` | regenerated | no |
| Search index | FTS/vector/cache | `index/` | regenerated | no |

Evidence is **not a file of its own**. It is a frontmatter field on the record it
supports, which is what makes it consumable: `resume` builds *Likely Relevant
Files* and *Verification Commands* out of it, and `guard` cites those commands in
its next-safest-action. Through 0.1.7 `init` also scaffolded an `evidence/refs.yml`
for a cross-record ledger. Nothing read or wrote it in any released version, and it
was **removed** rather than given a writer — a hand-maintained second copy of these
pointers would have had no validator, no consumer, and no way to notice a dangling
reference, while the per-record field already answers the question. Old stores can
delete the file; no code looks for it.

One row is still reserved space rather than working machinery: nothing builds an
`index/` today (`search` scans the records directly). It stays because it is
gitignored and therefore costs a user nothing — the difference from `refs.yml`,
which shipped committed, with example entries to clean up.

**Ideas are searchable but never judged.** `ideas/` is in `search`'s corpus and
deliberately absent from `guard`'s: an idea is a proposal, exempt from the
evidence rule, and `guard`'s scoring band is kind-agnostic, so a speculative note
naming the right files would otherwise gate a real edit. See `cli-spec.md` →
`search`, and Fixture 12.

See [`record-schema.md`](record-schema.md) for the directory layout and the
git-tracking policy.

---

## 4. Layered interop

```text
plain files  →  CLI  →  agent signposts  →  MCP  →  hooks  →  indexes/vectors
(always)        (built) (built)            (built) (built)   (not built)
```

The baseline (plain files) must always work. Each higher layer is optional and
must have a manual fallback to the layer below it. A read-only cloud agent that can
only read files still resumes from `current.md`, `handoff.md`, `decisions/`,
`attempts/`, `known-traps.md`, and `open-questions.md`.

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
