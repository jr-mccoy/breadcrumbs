---
id: dec_20260922_lifecycle-decay-hides-and-asks-it-never-deletes-a-claim
type: decision
slug: lifecycle-decay-hides-and-asks-it-never-deletes-a-claim
title: Lifecycle decay hides and asks; it never deletes a claim or sets a status on a clock
status: active
created_at: 2026-09-22T19:56:24+00:00
updated_at: 2026-09-22T19:56:24+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 086fc4e
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
  - lifecycle
  - phase-3
  - wm-30
  - wm-32
  - wm-35
evidence:
  - type: file
    ref: breadcrumbs/lifecycle.py
  - type: command
    ref: python -m unittest tests.test_lifecycle
---

## Context
Phase 3 (WM-30 to WM-35): memory that stops being true. Options were auto-retiring records by age, or hiding and warning.

## Decision
Expiry is computed from expires_at (cli.record_expired), not written as a status: an expired record stays active on disk and in search but leaves the packet lists and guard's live set. Settled verifications (fixed/not_applicable) get expires_at at write; actionable ones never expire. Traps, old verifications and an untouched current.md get packet questions, not retirement. Duplicates are refused at write with the id (exit 3), contradictions are packet/audit questions, consolidation only runs on named ids. The only deletion is rollup of machine snapshot sessions.

## Rationale
Deciding that a claim is wrong is the author's job, not a heuristic's. A status written on a clock needs a writer running on a clock and churns committed files; a computed flag does neither.

## What Not To Retry
Do not auto-merge near-duplicates or auto-retire by age. Do not stamp a rollup session with now: the Stop hook diffs from the newest session's commit.
