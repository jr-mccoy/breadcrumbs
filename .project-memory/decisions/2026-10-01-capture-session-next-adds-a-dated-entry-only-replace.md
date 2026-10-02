---
id: dec_20261001_capture-session-next-adds-a-dated-entry-only-replace
type: decision
slug: capture-session-next-adds-a-dated-entry-only-replace
title: capture session --next adds a dated entry; only --replace overwrites
status: active
created_at: 2026-10-01T22:29:02+00:00
updated_at: 2026-10-01T22:29:02+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/zealous-hamilton-ba7e5m
commit: 3085c5d
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - handoff
  - capture
evidence:
  - type: commit
    ref: f7b9c75
---

## Decision
The handoff's Next Action is a newest-first log. --next prepends a dated entry and never removes text; --replace overwrites and saves the replaced text in the session record; handoff trim moves old entries to a history file.

## Rationale
Field report 2026-10-01 issue 1: a one-line --next destroyed a 139-line hand-kept log with no copy. Operator decision D1 (append unless --replace); D1b: no requires: flag.
