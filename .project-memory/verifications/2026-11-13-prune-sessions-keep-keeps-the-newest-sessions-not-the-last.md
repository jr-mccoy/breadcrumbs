---
id: ver_20261113_prune-sessions-keep-keeps-the-newest-sessions-not-the-last
type: verification
slug: prune-sessions-keep-keeps-the-newest-sessions-not-the-last
title: prune sessions --keep keeps the newest sessions, not the last by file name — fixed
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
subject: prune sessions --keep keeps the newest sessions, not the last by file name
outcome: fixed
method: test
tags:
  - prune
evidence:
  - type: test
    ref: tests/test_capture.py
  - type: file
    ref: breadcrumbs/cli.py
---

## Subject
prune sessions --keep keeps the newest sessions, not the last by file name

## Outcome
fixed

## Method
test
