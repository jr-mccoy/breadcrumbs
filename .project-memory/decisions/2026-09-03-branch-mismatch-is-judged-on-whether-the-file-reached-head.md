---
id: dec_20260903_branch-mismatch-is-judged-on-whether-the-file-reached-head
type: decision
slug: branch-mismatch-is-judged-on-whether-the-file-reached-head
title: Branch mismatch is judged on whether the file reached HEAD, not on the record's commit
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
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - staleness
  - resume
  - guard
  - audit
  - git
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: tests/test_resume.py
  - type: test
    ref: tests/test_audit.py
---

## Context
In a branch-per-session workflow every record is written on some other branch, so resume, guard and audit printed a handoff mismatch plus a roll-call of all 13 records on every run of this repo. Six of the seven lines under Stale / Risk Warnings were false.

## Options Considered
(a) Check whether the record's commit: sha is an ancestor of HEAD via the existing topo-order rev-list index. (b) Check whether the record FILE is committed in HEAD's tree and clean in the worktree. (c) Downgrade the warning to a note instead of suppressing it.

## Decision
Suppress the mismatch when the file is committed at HEAD and unmodified (HeadTree in cli.py). Records use their own path; the handoff needs memory_dir, and callers that pass none keep the old unconditional report.

## Rationale
A record's commit: is HEAD at write time, i.e. where the code was, so commit ancestry is unsound: a commit can be an ancestor of HEAD while the record beside it is uncommitted or on an unmerged branch. A file committed at HEAD and clean in the worktree has provably reached this history, and that test also covers squash and rebase merges, where no feature sha survives. Downgrading to a note would keep the noise. Three git calls per staleness pass regardless of store size: rev-parse --show-prefix (the project root may sit below the repo root and ls-tree/status print repo-root-relative paths), ls-tree -r -z HEAD, status --porcelain.

## Consequences
An uncommitted or locally edited file from another branch still warns; an unborn HEAD warns as before. The guard path stops repeating the merged-handoff mismatch on every edit.

## What Not To Retry
Do not switch the test to commit ancestry to save a git call; it silently certifies records that never reached this branch.
