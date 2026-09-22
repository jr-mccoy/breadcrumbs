---
id: dec_20260922_the-working-memory-roadmap-is-the-plan-of-record-for-phases
type: decision
slug: the-working-memory-roadmap-is-the-plan-of-record-for-phases
title: The working-memory roadmap is the plan of record for phases 0-7
status: active
created_at: 2026-09-22T03:49:13+00:00
updated_at: 2026-09-22T03:49:13+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 99b60a0
dirty_files:
  - CHANGELOG.md
  - README.md
  - docs/roadmap-working-memory.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - roadmap
  - memory
  - hooks
  - architecture
evidence:
  - type: file
    ref: docs/roadmap-working-memory.md
  - type: file
    ref: CHANGELOG.md
---

## Context
Asked what would make breadcrumbs the perfect short/medium-term agentic memory, with CLAUDE.md/AGENTS.md as the long-term tier. The codebase is a solid ledger: typed records, bounded packet, stance-capped guard, Stop-hook extraction. The gaps are capture (only git snapshots are automatic; extraction fires only on commits; no UserPromptSubmit/PreCompact/SubagentStop hooks; transcripts never read), retrieval (packet is recency-ordered; only likely_files is task-scoped), lifecycle (expires_at never set; no dedup, contradiction detection, rollup or migration machinery) and the missing promote/demote bridge to the instruction file.

## Decision
docs/roadmap-working-memory.md is the plan of record. Seven phases, one release each: 0 foundations (migrate, usage telemetry, inbox jots), 1 capture hooks + deterministic transcript miner, 2 relevance retrieval (task-ordered packet, crumb show, per-record traps, FTS5, aliases, related), 3 lifecycle (TTLs, evidence staleness, near-duplicate gate, consolidate, contradictions, rollup), 4 promote/demote into CLAUDE.md, 5 per-branch handoffs + store lock + branch scope, 6 usage report + eval harness + field test, 7 other harnesses. Work items WM-01..WM-70 name files, functions, data shapes, tests and acceptance checks so a less capable implementer can execute them.

## Rationale
Hook facts were verified against the Claude Code hooks reference: PreCompact output never reaches the model (so it mines and marks; SessionStart source=compact re-injects), SubagentStop can block but the plan defers that behind the existing prompt-fatigue open question, UserPromptSubmit additionalContext reaches the model, and the transcript file may lag the current turn. New code goes in new modules; cli.py is 10.7k lines. Usage telemetry is local-only in v1 to avoid churning records and merge conflicts.

## Consequences
Every phase ends in a release and a SCHEMA_VERSION bump goes through WM-01 migrations with dual-shape readers. Open decisions deferred: shared telemetry, SubagentStop blocking, embeddings, per-branch current.md.
