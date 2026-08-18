---
id: dec_20260818_blast-radius-is-scored-separately-from-retrieval-overlap
type: decision
slug: blast-radius-is-scored-separately-from-retrieval-overlap
title: Blast radius is scored separately from retrieval overlap
status: active
created_at: 2026-08-18T05:00:20+00:00
updated_at: 2026-08-18T05:00:20+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/crumb-permission-override-pyxru7
commit: add2115
dirty_files:
  - .project-memory/generated/resume-packet.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - tests/test_guard.py
  - tests/test_hooks.py
  - tests/test_note.py
  - .project-memory/decisions/2026-08-18-hook-guard-never-overrides-the-session-s-permission-mode.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - scoring
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: python -m unittest tests.test_guard
---

## Context
guard ranked only memory overlap, so interruption frequency tracked how much of the repo the store cites — which only grows. Measured on a real store: rm of two cited docs escalated while git push --force origin main stayed advisory.

## Decision
The destructive-op regex that existed only as a hook pre-filter (and was then discarded) becomes guard()['destructive'], reported in the JSON and folded into the ASK_HUMAN escalation alongside GUARD_HIGH_IMPACT_CLASSES. It still needs an existing memory collision to escalate.

## Rationale
Overlap answers 'is a record about this action'; it has never answered 'how much damage does this do'. Danger belongs on the escalation side where it can raise a verdict, not on the prompt gate where it could only suppress an authored one.

## What Not To Retry
Gating the permission prompt on destructive as well as verdict. It was tried and reverted: PAUSE already implies a blocking match (an attempt with an explicit Do Not Retry Unless) and ASK_HUMAN already implies a high-impact class, so the gate suppressed authored do-not-retry blocks and broke test_pause_is_never_deduplicated.
