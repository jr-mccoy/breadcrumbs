---
id: dec_20261113_the-release-ci-gate-fails-closed-and-ignores-scheduled-runs
type: decision
slug: the-release-ci-gate-fails-closed-and-ignores-scheduled-runs
title: The release CI gate fails closed and ignores scheduled runs
status: active
created_at: 2026-11-13T14:04:29+00:00
updated_at: 2026-11-13T14:04:29+00:00
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
tags:
  - release
  - ci
evidence:
  - type: file
    ref: .github/scripts/ci_gate.py
  - type: file
    ref: .github/workflows/release.yml
  - type: test
    ref: tests/test_release_process.py
---

## Decision
mode publish requires the newest push, pull_request or workflow_dispatch run of ci on the commit to have succeeded. An API error, no such run, or a run in progress stops the publish. A later failed scheduled run is a warning only. The rule is .github/scripts/ci_gate.py.

## Rationale
The shell gate published with a warning when it could not read CI, and it read the newest run of any kind, so a weekly scheduled run on a newer runner image made the green commit 4606001 unpublishable. A scheduled run measures runner drift, not the commit; the release job runs the suite and the critical evals itself.
