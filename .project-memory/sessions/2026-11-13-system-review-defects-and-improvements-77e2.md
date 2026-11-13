---
id: ses_20261113_system-review-defects-and-improvements-77e2
type: session
slug: system-review-defects-and-improvements-77e2
title: System review: defects and improvements
status: active
created_at: 2026-11-13T05:05:30+00:00
updated_at: 2026-11-13T05:05:30+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: b8c6066
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
Ran the full suite (1,565 tests, green). Read the failing scheduled CI runs. Five parallel audits (guard and security, write path, hooks and MCP, CI and release and docs, read path), main findings re-run by hand. Wrote docs/reviews/2026-11-13-system-review.md.

## Open Questions
Drop Python 3.9 (end of life) or pin the runner to keep testing it? Run the agent-outcome eval (review section 5.1) before v2 phase P1?

## Files Touched
7 files changed, +1479/-19 (vs `5615583`)

## Next Action
Work docs/reviews/2026-11-13-system-review.md in the order of its section 6. First: pin the ci.yml test job's Python 3.9 leg to ubuntu-24.04 (ubuntu-latest is 26.04 and has no 3.9; scheduled CI red since 2026-11-02, so mode publish is refused), or decide to drop 3.9. Second: fix crumb rename (it deletes the record; trap_crumb-rename-deletes-the-record), the journal-discard window in mutations.py and prune sessions ordering. Third: cap the SessionStart packet at 10,000 characters and resolve the store root from CLAUDE_PROJECT_DIR or by walking up from cwd.
