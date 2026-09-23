---
id: trap_guard-exit-code-in-ci
type: trap
slug: guard-exit-code-in-ci
title: A CI step that calls crumb guard dies on guard's own verdict exit code
status: active
created_at: 2026-09-22T19:27:00+00:00
updated_at: 2026-09-22T19:27:00+00:00
created_by: unknown
agent: migration
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: ce0d42f
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

## Area / files
.github/workflows/ci.yml

## Symptom
A CI step fails with 'Process completed with exit code 10/15' right after a guard call, with no assertion output — the asserts after it never ran.

## Why
guard exits its verdict (GUARD_VERDICT_EXIT_CODES: PROCEED 0, READ_FIRST 10, PAUSE 15, ASK_HUMAN 20) and GitHub Actions runs 'run:' blocks under 'bash -e', so a guard fixture behaving correctly aborts the step. This broke ci.yml's test and package jobs the moment the exit codes landed in 0.1.10.

## Safe approach
Wrap the guard call in 'set +e' / capture $? / 'set -e', then assert the code against the verdict in the Python block — the exit-code contract gets tested instead of killing the step.

## Verification
bash -e on the extracted step body, or: python crumb.py guard '<action>' --project fixtures/fixture-02-guard-true-positive --json; echo $?
