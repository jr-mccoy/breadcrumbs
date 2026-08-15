---
id: dec_20260815_guard-verdict-floors-require-file-tag-specificity-keyword
type: decision
slug: guard-verdict-floors-require-file-tag-specificity-keyword
title: Guard verdict floors require file/tag specificity; keyword-only matches ride the score bands
status: active
created_at: 2026-08-15T20:29:29+00:00
updated_at: 2026-08-15T20:29:29+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/crumb-kit-0.1.10-triage-l3qo5a
commit: c34db39
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
  - scoring
evidence:
  - type: commit
    ref: d7c639e
---

## Decision
A trap (like decisions/verifications) floors READ_FIRST only with an author-curated file or tag signal; pure keyword overlap escalates only via GUARD_READ_FIRST_SCORE/GUARD_PAUSE_SCORE. Corpus-ubiquitous stems (df > 1/3, corpus >= 8 items) carry zero keyword weight in guard and search.

## Rationale
0.1.10 field test: the unconditional trap keyword floor fired READ_FIRST on 13/13 edits with one relevant hit; an ignored alarm is worse than no alarm.
