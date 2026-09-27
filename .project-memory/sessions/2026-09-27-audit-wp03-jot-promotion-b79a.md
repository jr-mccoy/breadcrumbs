---
id: ses_20260927_audit-wp03-jot-promotion-b79a
type: session
slug: audit-wp03-jot-promotion-b79a
title: Audit WP03 jot promotion
status: active
created_at: 2026-09-27T01:03:27+00:00
updated_at: 2026-09-27T01:03:27+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: a2b58ff
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
WP03: jot promotion carries the note into every target (body section or a 'From jot <id>' provenance paragraph), records promoted_from/digest, inherits scope and confidence unless explicitly widened/raised, applies the near-duplicate gate on all targets, refuses publishing a private jot with a credential. CLI/MCP gain --scope/--allow-duplicate/--supersedes. 13 new tests; suite green; MCP tests green with SDK.

## Decisions Made
Promotion itself authorizes publishing a private jot (disclosed in output, credentials refused); a stricter --share flag is left to WP14. Attempt jot text goes to Result, not Why It Failed, to avoid claiming a cause.

## Files Touched
21 files changed, +976/-46 (vs `7eca8c7`)

## Next Action
Review WP03 (docs/reviews/2026-09-27-breadcrumbs-wp03/README.md), including whether private-jot promotion should require an explicit --share flag; once approved mark it completed in the tracker. Then pick ONE dependency-ready package: WP04, WP05, WP13 or WP18.
