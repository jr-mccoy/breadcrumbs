---
id: ver_20260817_f-5-guard-reprints-the-staleness-block-on-every-call
type: verification
slug: f-5-guard-reprints-the-staleness-block-on-every-call
title: F-5 (guard reprints the staleness block on every call) is already fixed on main and in 0.1.11 — not_applicable
status: active
created_at: 2026-08-17T03:42:18+00:00
updated_at: 2026-08-17T03:42:18+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/crumb-kit-audit-review-x5b51n
commit: 37d032f
dirty_files:
  - .project-memory/generated/resume-packet.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - docs/mcp-spec.md
  - tests/test_guard.py
  - tests/test_hooks.py
  - tests/test_integrations.py
  - tests/test_note.py
  - tests/test_verify.py
  - .project-memory/decisions/2026-08-17-guard-verdicts-are-capped-by-record-stance-not-by-retrieval.md
  - .project-memory/verifications/2026-08-17-python-m-breadcrumbs-mcp-serve-speaks-mcp-stdio-identically.md
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: F-5 (guard reprints the staleness block on every call) is already fixed on main and in 0.1.11
outcome: not_applicable
method: runtime
tags:
  - guard
  - staleness
  - triage
evidence:
  - type: file
    ref: breadcrumbs/cli.py
---

## Subject
F-5 (guard reprints the staleness block on every call) is already fixed on main and in 0.1.11

## Outcome
not_applicable

## Method
runtime

## Notes
guard passes risks_only=True to compute_staleness (commit d7c639e, an ancestor of the 0.1.11 release commit 7071249). Aged decisions and open questions are emitted only in the full view used by resume/audit/doctor. Reproduced with a 50-day-old decision and open question: guard printed no staleness block, audit printed both.
