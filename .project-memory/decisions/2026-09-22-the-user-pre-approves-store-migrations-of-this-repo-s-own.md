---
id: dec_20260922_the-user-pre-approves-store-migrations-of-this-repo-s-own
type: decision
slug: the-user-pre-approves-store-migrations-of-this-repo-s-own
title: The user pre-approves store migrations of this repo's own .project-memory
status: active
created_at: 2026-09-22T22:23:06+00:00
updated_at: 2026-09-22T22:23:06+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 449c0e7
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - migration
  - approval
  - guard
evidence:
  - type: commit
    ref: HEAD
---

## Context
crumb guard returns ASK_HUMAN for every crumb migrate of the repo's own store; sessions stopped to ask at schema 3 and schema 4.

## Decision
The user said (2026-09-22): 'I approve any migration.' A crumb migrate of this repo's own store may proceed without asking again; still run guard, back up (migrate does), validate after, and commit the result.

## Stale / Review Conditions
Revisit if the user withdraws it, or for a migration that deletes or rewrites records rather than adding structure.
