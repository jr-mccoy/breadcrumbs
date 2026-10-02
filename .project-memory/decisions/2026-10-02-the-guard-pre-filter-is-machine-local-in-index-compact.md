---
id: dec_20261002_the-guard-pre-filter-is-machine-local-in-index-compact
type: decision
slug: the-guard-pre-filter-is-machine-local-in-index-compact
title: The guard pre-filter is machine-local in index/, compact and sorted
status: active
created_at: 2026-10-02T04:33:00+00:00
updated_at: 2026-10-02T04:33:00+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/sharp-hopper-g0wbvw
commit: 06932b3
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - prefilter
  - hooks
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: docs/reviews/2026-10-02-dowhat-retest-plan.md
---

## Decision
index/guard-prefilter.json, one compact line with every list sorted; the first reindex deletes the committed generated/ copy. It leaves out secret-shaped and opaque tokens, and the hook runs full guard for an action holding a 12+ character token with a digit, so it stays a superset of guard.

## Rationale
DoWhat retest of 0.5.0, items 8-9, operator decision D8: the hook only trusts a copy this machine's generation manifest vouches for, so a committed copy bought nothing and was a 33,000-line diff that conflicted on merges.
