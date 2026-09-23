---
id: dec_20260923_retrieval-changes-are-measured-by-evals-run-py-against
type: decision
slug: retrieval-changes-are-measured-by-evals-run-py-against
title: Retrieval changes are measured by evals/run.py against a committed baseline
status: active
created_at: 2026-09-23T03:20:00+00:00
updated_at: 2026-09-23T03:20:00+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 5db5432
dirty_files:
  - CHANGELOG.md
  - docs/roadmap-working-memory.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - evals
  - retrieval
  - ci
evidence:
  - type: file
    ref: evals/run.py
  - type: file
    ref: evals/baseline.json
  - type: commit
    ref: aca2257
---

## Context
Phases 1-5 changed ranking, filtering and capture with nothing measuring whether retrieval got better. The first eval run found two live bugs (superseded records injected by the prompt hook; short commands unmatched).

## Decision
evals/ builds three synthetic stores from store.crumb scripts with a pinned clock and runs 39 tasks through the prompt hook, the task-ordered packet and guard. CI fails on a >0.05 drop or any new reject hit. A deliberate retrieval change commits a new evals/baseline.json with a reason per moved task.

## Rationale
A ranking regression is invisible to unit tests. Building stores through the CLI keeps the eval honest to the current writers.

## What Not To Retry
Do not tune guard verdict floors from eval numbers alone; title-only trap flooring was removed for fatigue in 0.1.10 and waits on docs/field-test.md.
