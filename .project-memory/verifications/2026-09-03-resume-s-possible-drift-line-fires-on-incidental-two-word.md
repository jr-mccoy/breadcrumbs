---
id: ver_20260903_resume-s-possible-drift-line-fires-on-incidental-two-word
type: verification
slug: resume-s-possible-drift-line-fires-on-incidental-two-word
title: resume's possible-drift line fires on incidental two-word overlap and version fragments — fixed
status: active
created_at: 2026-09-03T03:21:08+00:00
updated_at: 2026-09-03T03:21:08+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-ai-memory-qbm4fk
commit: 95f7a72
dirty_files:
  - .project-memory/generated/resume-packet.md
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - docs/cli-spec.md
  - tests/test_audit.py
  - tests/test_resume.py
  - .project-memory/decisions/2026-09-03-branch-mismatch-is-judged-on-whether-the-file-reached-head.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: resume's possible-drift line fires on incidental two-word overlap and version fragments
outcome: fixed
method: test
tags:
  - resume
  - staleness
  - drift
evidence:
  - type: test
    ref: tests/test_resume.py
  - type: file
    ref: breadcrumbs/cli.py
---

## Subject
resume's possible-drift line fires on incidental two-word overlap and version fragments

## Outcome
fixed

## Method
test

## Notes
On this repo's own store the old rule (any two shared stems) flagged 4 of 9 fixed verifications, all false: crumb+open, sect+sess, and the bare 11 from 0.1.11. The rule now needs two-thirds of the subject's stems (floor 2) and ignores digit-only tokens; the intended restated-subject catch still fires.
