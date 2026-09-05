---
id: ver_20260905_retiring-a-trap-now-lowers-the-reported-always-on-context
type: verification
slug: retiring-a-trap-now-lowers-the-reported-always-on-context
title: retiring a trap now lowers the reported always-on context cost — fixed
status: active
created_at: 2026-09-05T03:23:15+00:00
updated_at: 2026-09-05T03:23:15+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/guard-context-bloat-wcle08
commit: 53b5dac
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/cli.py
  - breadcrumbs/templates/project-memory/known-traps.md
  - tests/test_hooks.py
  - tests/test_traps.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: retiring a trap now lowers the reported always-on context cost
outcome: fixed
tags: []
evidence:
  - type: command
    ref: python -m unittest discover -s tests
  - type: file
    ref: breadcrumbs/cli.py
---

## Subject
retiring a trap now lowers the reported always-on context cost

## Outcome
fixed
