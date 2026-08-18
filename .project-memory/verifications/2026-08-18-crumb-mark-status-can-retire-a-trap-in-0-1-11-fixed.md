---
id: ver_20260818_crumb-mark-status-can-retire-a-trap-in-0-1-11-fixed
type: verification
slug: crumb-mark-status-can-retire-a-trap-in-0-1-11-fixed
title: crumb mark-status can retire a trap in 0.1.11 — fixed
status: active
created_at: 2026-08-18T05:00:33+00:00
updated_at: 2026-08-18T05:00:33+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/crumb-permission-override-pyxru7
commit: add2115
dirty_files:
  - .project-memory/generated/guard-prefilter.json
  - .project-memory/generated/resume-packet.md
  - .project-memory/known-traps.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - tests/test_guard.py
  - tests/test_hooks.py
  - tests/test_note.py
  - .project-memory/decisions/2026-08-18-blast-radius-is-scored-separately-from-retrieval-overlap.md
  - .project-memory/decisions/2026-08-18-hook-guard-never-overrides-the-session-s-permission-mode.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: crumb mark-status can retire a trap in 0.1.11
outcome: fixed
method: test
tags: []
evidence:
  - type: command
    ref: crumb mark-status trap_<slug> stale --reason ...
---

## Subject
crumb mark-status can retire a trap in 0.1.11

## Outcome
fixed

## Method
test

## Notes
A downstream store still carries a note claiming mark-status reports 'no record with id' for a trap id. That was true before 0.1.11 and was fixed in it (CHANGELOG P0-3). Re-confirmed on 0.1.11+: stale and back to active both exit 0.
