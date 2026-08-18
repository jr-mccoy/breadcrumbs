---
id: ver_20260818_remember-set-validates-section-headings-exactly-as-capture
type: verification
slug: remember-set-validates-section-headings-exactly-as-capture
title: remember --set validates section headings exactly as capture session does — fixed
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
  - .project-memory/verifications/2026-08-18-crumb-mark-status-can-retire-a-trap-in-0-1-11-fixed.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: remember --set validates section headings exactly as capture session does
outcome: fixed
method: test
tags: []
evidence:
  - type: command
    ref: crumb remember decision --set Bananas x
---

## Subject
remember --set validates section headings exactly as capture session does

## Outcome
fixed

## Method
test

## Notes
Field report suspected remember accepted free-form headings. It does not: --set Bananas exits 2 with 'unknown section ... valid: Context, Options Considered, Decision, Rationale, Consequences, What Not To Retry, Evidence, Stale / Review Conditions'. The reporter's 'Decision' was simply a valid heading. No asymmetry.
