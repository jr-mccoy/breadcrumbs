---
id: ses_20261002_0-6-0-is-bumped-on-the-branch-the-dowhat-retest-fixes-5c0c
type: session
slug: 0-6-0-is-bumped-on-the-branch-the-dowhat-retest-fixes-5c0c
title: 0.6.0 is bumped on the branch: the DoWhat retest fixes plus the
status: active
created_at: 2026-10-02T19:18:46+00:00
updated_at: 2026-10-02T19:18:46+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-e63a7edc-aluyzm
commit: 84633e4
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/__init__.py
  - breadcrumbs/cli.py
  - docs/compatibility.md
  - tests/test_hooks.py
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
Reproduced the Stop-hook commit cycle in a scratch repo; _work_commits_between in cli.py; two regression tests in tests/test_hooks.py; __version__ 0.6.0, CHANGELOG [0.6.0] 2026-10-02, compatibility.md row.

## Decisions Made
dec_20261002_a-head-that-moved-only-by-memory-store-commits-is-not-new: a HEAD moved only by .project-memory/ commits is not new work for the Stop hook, so committing the snapshot no longer earns another snapshot. Explored and reproduced the commit/snapshot cycle first; the stop_hook_active guard only ever covered the double block.

## Files Touched
12 files changed, +346/-6446 (vs `06932b3`) — 5 uncommitted file(s), see `dirty_files`

## Next Action
Publish 0.6.0: Actions -> release -> Run workflow on main, mode dry-run, then mode publish (RELEASING.md). The branch ccr-e63a7edc-aluyzm carries the Stop-hook settle fix (tests/test_hooks.py: test_committing_the_snapshot_is_not_new_work) and the 0.6.0 bump; merge it to main first. Before migrating this repo's or DoWhat's store with 0.6.0, upgrade every machine (min_crumb_version). Open: the ask-time guard for a code+memory commit after the extraction turn, and whether Stop should write only under private/.
