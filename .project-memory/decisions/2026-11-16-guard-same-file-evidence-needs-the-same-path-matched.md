---
id: dec_20261116_guard-same-file-evidence-needs-the-same-path-matched
type: decision
slug: guard-same-file-evidence-needs-the-same-path-matched
title: Guard same-file evidence needs the same path, matched by tail at a slash
status: active
created_at: 2026-11-16T03:28:38+00:00
updated_at: 2026-11-16T03:28:38+00:00
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
  - guard
  - scoring
evidence:
  - type: commit
    ref: 9eb1fbf
  - type: file
    ref: breadcrumbs/scoring.py
---

## Decision
A basename counts as same file only when one side named the file bare. Full paths match when equal or when one is the other's tail at a / boundary, so ./src/a.py and absolute paths meet a record's src/a.py. The hook pre-filter keeps basename overlap, which stays a superset.

## Rationale
pkg_a/__init__.py gave PAUSE for an edit of pkg_b/__init__.py, and absolute Edit paths degraded to basename matching. The parity golden changed only in the reason string (the full path is now shown); the verdict did not.
