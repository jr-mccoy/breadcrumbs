---
id: ses_20261113_drop-python-3-9-fix-ci-gate-and-three-data-loss-bugs-32e0
type: session
slug: drop-python-3-9-fix-ci-gate-and-three-data-loss-bugs-32e0
title: Drop Python 3.9; fix CI gate and three data-loss bugs
status: active
created_at: 2026-11-13T14:04:40+00:00
updated_at: 2026-11-13T14:04:40+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 52d3bfe
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
Dropped Python 3.9 (floor 3.10 in pyproject, CI matrices, docs; mcp extra marker removed). Release CI gate moved to .github/scripts/ci_gate.py with tests. Fixed crumb rename deleting records, recover undoing half of a finished operation, and prune sessions keeping the wrong sessions; each with a test that fails on the old code, plus crash sweeps. Full suite: 1,583 tests green.

## Decisions Made
dec_20261113_python-3-10-is-the-supported-floor-3-9-is-dropped; dec_20261113_the-release-ci-gate-fails-closed-and-ignores-scheduled-runs

## Files Touched
30 files changed, +858/-89 (vs `b8c6066`)

## Next Action
Merge ccr-5a263b6c-3gtzxn to main and confirm ci is green there (the 3.9 legs are gone). Then release 0.7.0: bump __version__, date the [Unreleased] CHANGELOG section as 0.7.0, add the docs/compatibility.md section 3 row, dry-run, publish. After that, item 3 of docs/reviews/2026-11-13-system-review.md section 6: cap the SessionStart packet at 10,000 characters and resolve the store root from CLAUDE_PROJECT_DIR or by walking up from cwd.
