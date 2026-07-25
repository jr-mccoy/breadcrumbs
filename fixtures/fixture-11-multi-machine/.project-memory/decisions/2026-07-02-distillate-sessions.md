---
id: dec_20260702_distillate-sessions
type: decision
slug: distillate-sessions
title: Session records stay local; only promoted records are committed
status: active
created_at: 2026-07-02T10:00:00-05:00
updated_at: 2026-07-02T10:00:00-05:00
created_by: dana
agent: human
project: shared-service
scope: project
branch: main
commit: 7c31f0a
dirty_files: []
confidence: high
privacy: repo-safe
review_status: reviewed
reviewed_by: sam
supersedes: []
superseded_by: null
expires_at: null
tags:
  - memory
  - multi-machine
evidence:
  - type: commit
    ref: 7c31f0a
---

## Context
Two developers work this repo from different machines and different checkout
paths, and a third clone runs in CI.

## Options Considered
Commit every session record (`session_tracking: full`), or keep `sessions/`
local and commit only promoted decisions and attempts (`distillate`).

## Decision
Use `session_tracking: distillate`.

## Rationale
Session records are per-machine narration; committing them made every pull a
merge conflict without adding anything the promoted records did not already say.

## Consequences
`sessions/` is gitignored and absent from every clone, so nothing shared may be
derived from it — including the freshness stamp on the committed projection.

## What Not To Retry
Do not flip back to `full` to "fix" a projection freshness complaint; the
projection must be reproducible from the shared records alone.

## Evidence
- commit 7c31f0a

## Stale / Review Conditions
Revisit if the team stops sharing this repo across machines.
