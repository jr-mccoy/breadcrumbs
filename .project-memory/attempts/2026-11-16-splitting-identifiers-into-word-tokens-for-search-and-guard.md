---
id: att_20261116_splitting-identifiers-into-word-tokens-for-search-and-guard
type: attempt
slug: splitting-identifiers-into-word-tokens-for-search-and-guard
title: Splitting identifiers into word tokens for search and guard
status: active
created_at: 2026-11-16T13:05:10+00:00
updated_at: 2026-11-16T13:05:10+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: aeadbcb
dirty_files: []
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
  - tokenizer
evidence:
  - type: commit
    ref: 512f31f
  - type: file
    ref: breadcrumbs/textmatch.py
---

## Tried
Tokenizer emitted the parts of snake_case (parse_frontmatter -> parse, frontmatter) and camelCase identifiers on both sides of every match (review 2026-11-13 R7).

## Result
snake_case parts cut holdout packet precision@5 from 0.514 to 0.389; camelCase parts made fallbackToDestructiveMigration() share 'migration' with a Room migration-test attempt and failed critical eval android-room-builder-edit-shows-nothing-blocking.

## Do Not Retry Unless
the split is applied only to crumb search lookups (a lookup-only match), not to the shared scorer behind guard, the prompt hook and the packet
