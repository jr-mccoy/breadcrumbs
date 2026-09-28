---
id: dec_20260927_pair-generation-uses-postings-and-exact-prefix-filtering
type: decision
slug: pair-generation-uses-postings-and-exact-prefix-filtering
title: Pair generation uses postings and exact prefix filtering, never a corpus cutoff
status: active
created_at: 2026-09-27T22:10:56+00:00
updated_at: 2026-09-27T22:10:56+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: 4a370ce
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - performance
evidence:
  - type: file
    ref: breadcrumbs/related.py
  - type: file
    ref: breadcrumbs/lifecycle.py
---

## Decision
related, conflicts and the near-duplicate sweep score only pairs that can reach their thresholds; pairwise versions stay as test oracles. Past RELATED_PAIR_BUDGET the related map reports degraded (audit: related-degraded) instead of skipping. Parses are shared per operation via cli.operation() keyed by content digest (audit WP15).
