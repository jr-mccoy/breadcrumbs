---
id: ses_20261003_dowhat-0-6-0-retest-fixes-are-on-claude-charming-sagan-85c8
type: session
slug: dowhat-0-6-0-retest-fixes-are-on-claude-charming-sagan-85c8
title: DoWhat 0.6.0 retest fixes are on claude/charming-sagan-9o911q (plan:
status: active
created_at: 2026-10-03T17:53:41+00:00
updated_at: 2026-10-03T17:53:41+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/charming-sagan-9o911q
commit: 25bf611
dirty_files:
  - docs/reviews/2026-10-03-dowhat-0.6.0-retest-plan.md
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
- 25bf611 Guard-only objection rule; git.work_tree; evals module loaded under its own name
- be529bc CHANGELOG [Unreleased] and the retest plan, updated to what was built
- 1001ea9 README: --refresh-package crumb-kit for uv installs and upgrades (DoWhat retest of 0.6.0, item 9)
- 9c62815 Stop hook: log where a slow firing's time went (DoWhat retest of 0.6.0, item 8)
- 1db728d test_retest_060: the prose-only path case runs in the padded store, where it failed at 0.6.0
- 67a0bb9 Guard: generated indexes are memory, named paths are topical, objections need the action (DoWhat retest of 0.6.0, items 3, 4, 5a)
- acad50c Guard reads what a command does, not its data (DoWhat retest of 0.6.0, items 5b, 6, 7)
- 3753119 Guard hook: load only what a firing uses (DoWhat retest of 0.6.0, item 2)
- 724d8a1 Guard hook: no git processes at a stable HEAD (DoWhat retest of 0.6.0, item 1)
- 45d6f82 Plan: the DoWhat retest of 0.6.0 (claims checked, causes, fixes, tests)
- 60ff21b Merge pull request #59 from jr-mccoy/ccr-4e962709-tubaoe
- 843ceb3 test_hooks: turn off git's auto-maintenance in the test repositories
- 28dd70c Health review 1.1 done; decisions for the extraction pattern and decision staleness; session capture

_Prefill window: `78f6691`..HEAD — 13 commit(s) since the last session record._

## Decisions Made
Guard hook computes no staleness and answers reached-HEAD from index/head-tree.txt; objections (blocking) need a file, the exact command or two rare title words, guard only; generated store indexes are not a record's subject; scratch-file rm is cleanup; data heredocs and package-install --force are not destructive.

## Files Touched
36 files changed, +1949/-218 (vs `78f6691`) — 1 uncommitted file(s), see `dirty_files`

## Next Action
DoWhat 0.6.0 retest fixes are on claude/charming-sagan-9o911q (plan: docs/reviews/2026-10-03-dowhat-0.6.0-retest-plan.md, CHANGELOG [Unreleased], proposed 0.6.1). Waiting on the operator: the launcher DECIDE (item 2) and the go to release. To release: bump __version__ to 0.6.1, move [Unreleased] to [0.6.1] with the date, add the docs/compatibility.md section 3 row, merge to main, run release.yml dry-run then publish. Then remeasure the hook on Windows with doctor --hook-log.
