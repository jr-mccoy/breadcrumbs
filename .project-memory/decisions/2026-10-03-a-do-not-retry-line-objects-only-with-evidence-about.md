---
id: dec_20261003_a-do-not-retry-line-objects-only-with-evidence-about
type: decision
slug: a-do-not-retry-line-objects-only-with-evidence-about
title: A do-not-retry line objects only with evidence about the action: a file it names or writes, its exact command, or two rare title words
status: active
created_at: 2026-10-03T16:53:14+00:00
updated_at: 2026-10-03T16:53:14+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/charming-sagan-9o911q
commit: be529bc
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - scoring
  - retest
evidence:
  - type: file
    ref: breadcrumbs/scoring.py
  - type: file
    ref: tests/test_retest_060.py
---

## Context
DoWhat retest of 0.6.0, item 5: tooling attempts PAUSEd uv tool install and a timing loop on a tag plus two or three shell words; the Room migration-test attempt blocked a builder edit.

## Decision
Guard only (scoring.search(strict_objections=True), set by scoring.guard): a topical do-not-retry attempt keeps the do-not-retry score weight, but the do-not-retry signal, which makes the stance blocking, needs 'objects': a matched file, a prose-cited path the action names, a written file, or 2+ rare title words beyond tags. Naming the exact command objects via _with_command_signal. crumb search, MCP search and the prompt hook keep labelling every topical failed attempt.

## Rationale
Stance is what interrupts a human; ranking and labels are what find memory. Applying the rule to lookups changed crumb search's wire output (parity fixture) and, with the weight removed too, lost the service eval's logout/cookie attempt from the prompt hook.

## What Not To Retry
Do not gate the score weight on objects as well; it drops relevant failed attempts from the prompt hook.
