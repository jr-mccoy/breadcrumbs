---
id: ver_20260925_ci-mcp-job-fails-stale-pinned-tool-resource-counts-in-ci
type: verification
slug: ci-mcp-job-fails-stale-pinned-tool-resource-counts-in-ci
title: CI mcp job fails: stale pinned tool/resource counts in ci.yml — fixed
status: active
created_at: 2026-09-25T01:32:23+00:00
updated_at: 2026-09-25T01:32:23+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/release-prep-publish-dw1xzf
commit: ac03e26
dirty_files:
  - .github/workflows/ci.yml
  - tests/test_release_process.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: 2026-12-24T01:32:23+00:00
subject: CI mcp job fails: stale pinned tool/resource counts in ci.yml
outcome: fixed
method: test
tags:
  - ci
  - release
evidence:
  - type: command
    ref: python -m unittest discover -s tests
  - type: file
    ref: .github/workflows/ci.yml
  - type: file
    ref: tests/test_release_process.py
---

## Subject
CI mcp job fails: stale pinned tool/resource counts in ci.yml

## Outcome
fixed

## Method
test

## Notes
Every mcp leg failed from Phase 0 on: ci.yml pinned 10 tools and 8 resources, the server registers 13 and 14. Reproduced on mcp 1.30 and 2.2; fixed step prints 13 tools, 6 prompts, 14 resources on both. test_release_process now derives both counts from the source, so the stdlib suite catches the next drift.
