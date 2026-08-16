---
id: ver_20260816_crumb-mark-status-can-retire-a-trap-fixed
type: verification
slug: crumb-mark-status-can-retire-a-trap-fixed
title: crumb mark-status can retire a trap — fixed
status: active
created_at: 2026-08-16T00:30:39+00:00
updated_at: 2026-08-16T00:30:39+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/trap-retirement-mark-status-o64qqs
commit: 5c861c4
dirty_files:
  - .project-memory/generated/resume-packet.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - breadcrumbs/mcp_server.py
  - breadcrumbs/templates/project-memory/known-traps.md
  - docs/cli-spec.md
  - docs/mcp-spec.md
  - tests/test_note.py
  - .project-memory/decisions/2026-08-16-traps-carry-a-lifecycle-status-and-mark-status-resolves-them.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: crumb mark-status can retire a trap
outcome: fixed
method: test
tags: []
evidence:
  - type: file
    ref: tests/test_note.py
---

## Subject
crumb mark-status can retire a trap

## Outcome
fixed

## Method
test

## Notes
TrapLifecycleTests covers the reported repro (note trap id -> search [active] -> mark-status), the retired trap leaving the packet/prefilter/guard verdict, search still finding it under its real status, in-place block editing that leaves the template comment and sibling traps untouched, pre-existing status-less traps, and lifecycle bullets never reaching the keyword index. 616 tests pass.
