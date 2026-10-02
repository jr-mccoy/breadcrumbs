---
id: trap_a-test-that-runs-resume-or-reindex-on-a-checked-in-fixture
type: trap
slug: a-test-that-runs-resume-or-reindex-on-a-checked-in-fixture
title: A test that runs resume or reindex on a checked-in fixture rewrites it
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
tags:
  - fixtures
  - tests
evidence: []
---

## Area / files
fixtures/

## Symptom
git status shows fixture files modified or deleted after the suite runs

## Why
resume publishes projections into the store it reads; since 0.6.0 that deletes generated/guard-prefilter.json

## Safe approach
Copy the fixture to a temp dir first (see tests/test_json_envelope.py setUpClass)
