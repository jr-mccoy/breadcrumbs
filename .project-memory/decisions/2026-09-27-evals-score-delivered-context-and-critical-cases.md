---
id: dec_20260927_evals-score-delivered-context-and-critical-cases
type: decision
slug: evals-score-delivered-context-and-critical-cases
title: Evals score delivered context and critical cases no baseline can approve
status: active
created_at: 2026-09-27T04:30:55+00:00
updated_at: 2026-09-27T04:30:55+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: b7f37ce
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - audit
  - wp18
  - evals
  - release
evidence:
  - type: file
    ref: evals/run.py
  - type: file
    ref: evals/critical/cases.yml
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp18/README.md
---

## Decision
evals/run.py keeps the WM-61 ranking diagnostics unchanged and adds delivery systems (real prompt/guard hooks, resume as printed) plus evals/critical/cases.yml. A critical failure fails the run regardless of baseline; known: markers stay visible and fail --release; baseline writes need --reason and reviewed task-level deltas.

## Rationale
Audit F19: a known false-safe (npm test -> PROCEED) sat inside an accepted baseline with CI green, and ranking metrics did not describe what readers receive.
