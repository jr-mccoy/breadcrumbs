---
id: ver_20260816_ci-yml-guard-steps-survive-guard-s-verdict-exit-codes-fixed
type: verification
slug: ci-yml-guard-steps-survive-guard-s-verdict-exit-codes-fixed
title: ci.yml guard steps survive guard's verdict exit codes — fixed
status: active
created_at: 2026-08-16T03:51:48+00:00
updated_at: 2026-08-16T03:51:48+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/trap-retirement-mark-status-o64qqs
commit: 5f7c317
dirty_files:
  - .github/workflows/ci.yml
  - .project-memory/generated/guard-prefilter.json
  - .project-memory/generated/resume-packet.md
  - .project-memory/known-traps.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
subject: ci.yml guard steps survive guard's verdict exit codes
outcome: fixed
method: test
tags: []
evidence:
  - type: file
    ref: .github/workflows/ci.yml
---

## Subject
ci.yml guard steps survive guard's verdict exit codes

## Outcome
fixed

## Method
test

## Notes
Extracted each changed step body and ran it under 'bash -e' locally, including the installed-binary smoke test against a real venv install: all three exit 0 and now assert the code matches the verdict. Root cause reproduced first: fixture-02 guard exits 15, the package smoke guard exits 10.
