---
id: ses_20260927_audit-wp05-os-store-lock-a7a3
type: session
slug: audit-wp05-os-store-lock-a7a3
title: Audit WP05 OS store lock
status: active
created_at: 2026-09-27T01:36:55+00:00
updated_at: 2026-09-27T01:36:55+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: 0eada75
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
WP05: store lock rewritten on OS locks (flock/msvcrt) over permanent private/.store.lock, no heartbeat/staleness; projection publication locked (resume prints regardless, publishes within 0.5 s, reports publication); init --force keeps lock files; index builds in a unique temp file. 10 real-process tests; suite green; lock tests stable over 5 runs.

## Decisions Made
New lock filename so 0.3.0-era writers cannot delete it; this version waits on a live legacy lock but never removes one. Filesystems refusing OS locks refuse writes rather than run uncoordinated.

## Files Touched
23 files changed, +1115/-249 (vs `b85314f`)

## Next Action
Review WP05 (docs/reviews/2026-09-27-breadcrumbs-wp05/README.md); once approved mark it completed in the tracker. Next in the report's single-agent order is WP06 (recoverable replacement/lifecycle mutations; depends on WP01+WP05); WP13 and WP18 are also ready.
