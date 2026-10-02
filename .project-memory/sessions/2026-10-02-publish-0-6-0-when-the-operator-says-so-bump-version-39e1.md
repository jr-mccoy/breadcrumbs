---
id: ses_20261002_publish-0-6-0-when-the-operator-says-so-bump-version-39e1
type: session
slug: publish-0-6-0-when-the-operator-says-so-bump-version-39e1
title: Publish 0.6.0 when the operator says so: bump __version__ to 0.6.0,
status: active
created_at: 2026-10-02T04:33:07+00:00
updated_at: 2026-10-02T04:33:07+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/sharp-hopper-g0wbvw
commit: 06932b3
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
- 06932b3 CHANGELOG, README and plan status for the 0.5.0 retest; tests proven to fail on 0.5.0

_Prefill window: `cd61363`..HEAD — 1 commit(s) since the last session record._

## Files Touched
9 files changed, +256/-61 (vs `cd61363`)

## Next Action
Publish 0.6.0 when the operator says so: bump __version__ to 0.6.0, move CHANGELOG [Unreleased] to a [0.6.0] heading, add the docs/compatibility.md section 3 row, merge to main, then release.yml dry-run and publish. Before running crumb migrate on this repo's or DoWhat's store, upgrade every machine and the cloud setup: migrate sets min_crumb_version 0.5.0 with requires: min-crumb-version, so 0.4.x and 0.5.0 then refuse to write. On Windows, read crumb doctor --hook-log's p50 phases (import_ms, git_ms) to settle decision D7.
