---
id: dec_20261003_git-state-has-one-owner-breadcrumbs-git-full-shas
type: decision
slug: git-state-has-one-owner-breadcrumbs-git-full-shas
title: Git state has one owner: breadcrumbs.git; full shas for identity, short only for display and the record commit field
status: active
created_at: 2026-10-03T13:07:33+00:00
updated_at: 2026-10-03T13:07:33+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-4e962709-tubaoe
commit: b8266a3
dirty_files:
  - breadcrumbs/admission.py
  - breadcrumbs/cli.py
  - breadcrumbs/git.py
  - breadcrumbs/handoffs.py
  - breadcrumbs/hooks_common.py
  - breadcrumbs/hooks_compact.py
  - breadcrumbs/lifecycle.py
  - breadcrumbs/repair.py
  - docs/reviews/2026-10-02-deferred-health-review.md
  - tests/test_git.py
  - tests/test_gitrefs.py
  - tests/test_guard.py
  - tests/test_guard_field_report.py
  - tests/test_hooks.py
  - tests/test_regressions.py
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - git
  - architecture
evidence:
  - type: file
    ref: breadcrumbs/git.py
  - type: file
    ref: tests/test_git.py
---

## Context
Deferred health review 2.2: git was read two ways (cli._git_out spawned git, gitrefs read .git), five modules called the private cli._git_out, and a short sha from one compared by string with a full sha from the other was field-report item N8.

## Decision
breadcrumbs/git.py owns every git spawn (run, check_ignore) and is the only importer of gitrefs. HEAD identity is git.head (full sha, disk first, git fallback; spawn=False for callers that must not start a process). The record commit field keeps git's short form (git.short_head) and is compared with git.same_commit. cli keeps git_branch (op-memoized) and git_dirty_files (store filter) only.

## Rationale
One implementation per question removes the class of drift that produced N8, and moving HEAD reads to the disk reader removes git spawns from the Stop hook path on Windows. Storing full shas in records would change a stored format, so it was kept out.

## What Not To Retry
Do not add a git subprocess or a gitrefs import outside breadcrumbs/git.py; tests/test_git.py::OwnershipTests fails on it.
