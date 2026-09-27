---
id: ses_20260927_audit-wp01-record-contract-cc8e
type: session
slug: audit-wp01-record-contract-cc8e
title: Audit WP01 record contract
status: active
created_at: 2026-09-27T00:33:15+00:00
updated_at: 2026-09-27T00:33:15+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: 0144825
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
WP01: breadcrumbs/validation.py record contract with stable codes, used by run_validate and a pre-write gate in write_record; rewrite gates refuse only newly introduced problems; packet warns on contract breaks. 18 new tests; full suite green on 3.11 and 3.9; evals unchanged; schema_types probe resolved.

## Decisions Made
Legacy records that break the contract are reported, never rewritten, and stay retirable; free-text scope is still read as project (WP21 decides any migration). supersedes targets are not checked because rollups delete folded snapshots.

## Files Touched
22 files changed, +1360/-84 (vs `31e56da`)

## Next Action
Review WP01 (docs/reviews/2026-09-27-breadcrumbs-wp01/README.md); once approved mark it completed in the tracker. Then pick ONE dependency-ready package: WP02, WP05, WP13 or WP18 (WP03/WP04 are now also unblocked by WP01, after its approval).
