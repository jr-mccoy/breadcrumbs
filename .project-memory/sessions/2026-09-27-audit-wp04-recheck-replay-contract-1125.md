---
id: ses_20260927_audit-wp04-recheck-replay-contract-1125
type: session
slug: audit-wp04-recheck-replay-contract-1125
title: Audit WP04 recheck replay contract
status: active
created_at: 2026-09-27T01:21:13+00:00
updated_at: 2026-09-27T01:21:13+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: b85314f
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags: []
evidence: []
---

## Work Completed
WP04: new breadcrumbs/checks.py (CheckResult, assertion spec 1, settle, bounded process-group runner). Recheck settles only via assertions (verify --assert, or --bind-commands); command evidence is a diagnostic; test evidence never executed; inconclusive runs write nothing; settled records keep scope/branch/confidence; branch claims not rechecked from another branch. 16 new tests; suite green.

## Decisions Made
An unsettled recheck writes nothing to the store (no claim change, no observation record). Environment filtering and Windows Job Objects deferred (policy / WP17).

## Files Touched
19 files changed, +1429/-134 (vs `a2b58ff`)

## Next Action
Review WP04 (docs/reviews/2026-09-27-breadcrumbs-wp04/README.md); once approved mark it completed in the tracker. Then pick ONE dependency-ready package: WP05, WP13 or WP18 (WP06 needs WP05).
