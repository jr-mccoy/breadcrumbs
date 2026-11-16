---
id: dec_20261116_stop-words-match-as-written-or-as-regular-inflections
type: decision
slug: stop-words-match-as-written-or-as-regular-inflections
title: Stop words match as written or as regular inflections; identifiers stay whole
status: active
created_at: 2026-11-16T03:28:37+00:00
updated_at: 2026-11-16T03:28:37+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 251655b
dirty_files:
  - docs/reviews/2026-11-13-system-review.md
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - retrieval
  - search
  - guard
evidence:
  - type: commit
    ref: 512f31f
  - type: file
    ref: breadcrumbs/textmatch.py
---

## Decision
A token is a stop word if it is one, or a regular -s/-es/-ed/-ing form of a development stop word. Function words and path segments (index, test, src) match only as written. Tokens are \w+ in any script, CJK runs add bigrams, and a dotted version is one token. Identifiers are not split.

## Rationale
Filtering on stems dropped projection, note, handler, worker and indexing from every query. Splitting identifiers was measured: on _ it cut holdout packet precision@5 from 0.514 to 0.389, and camelCase failed the critical eval android-room-builder-edit-shows-nothing-blocking. Finding parse_frontmatter from frontmatter needs a lookup-only match.
