---
id: ver_20261113_crumb-recover-apply-no-longer-undoes-half-of-a-finished
type: verification
slug: crumb-recover-apply-no-longer-undoes-half-of-a-finished
title: crumb recover --apply no longer undoes half of a finished operation — fixed
status: active
created_at: 2026-11-13T14:04:30+00:00
updated_at: 2026-11-13T14:04:30+00:00
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
expires_at: 2027-02-11T14:04:30+00:00
subject: crumb recover --apply no longer undoes half of a finished operation
outcome: fixed
method: test
tags:
  - recover
  - journal
evidence:
  - type: test
    ref: tests/test_mutation_recovery.py
  - type: file
    ref: breadcrumbs/mutations.py
---

## Subject
crumb recover --apply no longer undoes half of a finished operation

## Outcome
fixed

## Method
test

## Notes
Journal removal deletes manifest.json first. A journal with missing before-images is reported finished and removed without touching files. Crash sweeps: remember --supersedes clean at 23 points, rollup sessions at 34.
