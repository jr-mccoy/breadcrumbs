---
id: trap_a-hook-test-payload-without-cwd-fires-the-hook
type: trap
slug: a-hook-test-payload-without-cwd-fires-the-hook
title: A hook test payload without cwd fires the hook at the repository the suite runs in
status: active
created_at: 2026-10-02T20:25:27+00:00
updated_at: 2026-10-02T20:25:27+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-e63a7edc-aluyzm
commit: 1b26438
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/cli.py
  - breadcrumbs/hooks_common.py
  - breadcrumbs/hooks_compact.py
  - breadcrumbs/inbox.py
  - breadcrumbs/mcp_core.py
  - breadcrumbs/migrate.py
  - docs/cli-spec.md
  - docs/compatibility.md
  - docs/operator-guide.md
  - docs/reviews/2026-10-02-deferred-health-review.md
  - docs/roadmap-working-memory.md
  - tests/test_hooks.py
  - tests/test_hooks_phase1.py
  - tests/test_multi_machine.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - hooks
  - tests
evidence: []
---

## Area / files
tests/test_hooks*.py, any test calling crumb.main(["hook", ...])

## Symptom
After a test run this repo's own .project-memory has a stray sessions/*-session-*.md snapshot and rewritten generated/ files; git add -A then commits them.

## Why
_hook_root falls back to the process working directory when the payload has no cwd, and unittest runs from the repo root.

## Safe approach
Always pass cwd pointing at the temp repo, or os.chdir into it for payloads that deliberately omit cwd (BadPayloadTests does).

## Verification
python -m unittest discover -s tests && git status --short -- .project-memory
