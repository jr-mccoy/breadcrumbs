---
id: ver_20260905_the-16-findings-of-the-0-1-11-crumb-kit-field-review-re
type: verification
slug: the-16-findings-of-the-0-1-11-crumb-kit-field-review-re
title: the 16 findings of the 0.1.11 crumb-kit field review, re-checked against 0.1.12 — fixed
status: active
created_at: 2026-09-05T00:30:04+00:00
updated_at: 2026-09-05T00:30:04+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/artifact-388cc819-sm0ipj
commit: a5de02b
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: the 16 findings of the 0.1.11 crumb-kit field review, re-checked against 0.1.12
outcome: fixed
method: static
tags: []
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: commit
    ref: 08c94e3
---

## Subject
the 16 findings of the 0.1.11 crumb-kit field review, re-checked against 0.1.12

## Outcome
fixed

## Method
static

## Notes
Three were already fixed before this pass and must not be re-fixed: W2 (mcp_server_entry already launches 'python -m breadcrumbs mcp serve' on Windows), R4 (truncate_slug already cuts on a word boundary and trims trailing function words), and G4 plus most of G3 (render_guard_human emits one line per match and never a trap body; _hook_guard_advisory_seen already dedupes READ_FIRST advisories per host session). The remaining thirteen were reproduced on 0.1.12 before being fixed here.
