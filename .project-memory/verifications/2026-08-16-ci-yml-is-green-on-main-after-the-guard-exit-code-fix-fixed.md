---
id: ver_20260816_ci-yml-is-green-on-main-after-the-guard-exit-code-fix-fixed
type: verification
slug: ci-yml-is-green-on-main-after-the-guard-exit-code-fix-fixed
title: ci.yml is green on main after the guard exit-code fix — fixed
status: active
created_at: 2026-08-16T04:47:47+00:00
updated_at: 2026-08-16T04:47:47+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: main
commit: 37d032f
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: ci.yml is green on main after the guard exit-code fix
outcome: fixed
method: test
tags: []
evidence:
  - type: command
    ref: gh run list --workflow ci.yml --branch main
---

## Subject
ci.yml is green on main after the guard exit-code fix

## Outcome
fixed

## Method
test

## Notes
main run 142 on 37d032f: all 36 checks success. Ends the red streak that ran from 5c861c4 (0.1.10 triage merge) through 5f7c317. Root cause was guard's verdict exit codes aborting the CI steps that asserted them under bash -e, fixed in a872238 and merged via PR #43/#44.
