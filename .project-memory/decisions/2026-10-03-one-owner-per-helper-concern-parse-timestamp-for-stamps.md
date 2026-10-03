---
id: dec_20261003_one-owner-per-helper-concern-parse-timestamp-for-stamps
type: decision
slug: one-owner-per-helper-concern-parse-timestamp-for-stamps
title: One owner per helper concern: parse_timestamp for stamps, path_policy for POSIX paths, shellcmd for command text (two tokenizers on purpose)
status: active
created_at: 2026-10-03T13:37:03+00:00
updated_at: 2026-10-03T13:37:03+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-4e962709-tubaoe
commit: aedc62a
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - architecture
  - paths
  - guard
evidence:
  - type: file
    ref: breadcrumbs/shellcmd.py
  - type: file
    ref: breadcrumbs/path_policy.py
  - type: file
    ref: breadcrumbs/validation.py
---

## Context
Deferred health review 2.2, after breadcrumbs.git: timestamps were parsed two ways, POSIX conversion was open-coded 45 times in 12 modules, and command text was tokenized in cli and shellcmd.

## Decision
Readers parse timestamps with validation.parse_timestamp only (cli._parse_iso removed). Store-relative paths go through path_policy.posix_rel and path-as-text through path_policy.to_posix. shellcmd owns command text: words/segments (exact argv, for what a command does), normalize_command (identity across retries) and match_tokens (loose tokens guard retrieval matches prose trap titles with).

## Rationale
A reader that accepts more than validate acts on stamps validate rejects, and differently per interpreter. One spelling for POSIX paths keeps the store-relative POSIX rule in one place. Exact and loose tokenizing serve different jobs; merging them would change guard verdicts and the eval baseline.

## What Not To Retry
Do not merge shellcmd.match_tokens into words(): trap titles are prose and must fold the same way as the action. Do not open-code relative_to(...).as_posix() or replace('\\', '/') outside path_policy; test_platform_portability refuses it.
