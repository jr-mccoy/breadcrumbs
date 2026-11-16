---
id: ses_20261114_item-5-guard-reads-shell-commands-as-the-shell-does-fed2
type: session
slug: item-5-guard-reads-shell-commands-as-the-shell-does-fed2
title: Item 5: guard reads shell commands as the shell does
status: active
created_at: 2026-11-14T17:17:06+00:00
updated_at: 2026-11-14T17:17:06+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 8a6ee60
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
- 8a6ee60 Guard reads shell commands as the shell does: heredocs, redirects, wrappers, the floor, index parity
- 24b02a5 Memory: decisions for the frontmatter, scanner and safetext rules; session

_Prefill window: `10f8a9d`..HEAD — 2 commit(s) since the last session record._

## Files Touched
18 files changed, +1289/-150 (vs `10f8a9d`)

## Next Action
Merge ccr-5a263b6c-3gtzxn to main and confirm ci is green there; release 0.7.0 per CLAUDE.md (search-index format is now 3: the first reindex after upgrade rebuilds it). Next review work: item 6 (agent-outcome eval, review section 5.1), the section 3 tables, and trap_miner-reads-hook-feedback-as-a-correction.
