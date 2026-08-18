---
id: dec_20260818_hook-guard-never-overrides-the-session-s-permission-mode
type: decision
slug: hook-guard-never-overrides-the-session-s-permission-mode
title: hook guard never overrides the session's permission mode
status: active
created_at: 2026-08-18T05:00:20+00:00
updated_at: 2026-08-18T05:00:20+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/crumb-permission-override-pyxru7
commit: add2115
dirty_files:
  - CHANGELOG.md
  - README.md
  - breadcrumbs/cli.py
  - tests/test_guard.py
  - tests/test_hooks.py
  - tests/test_note.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - hooks
  - permissions
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: python -m unittest tests.test_hooks
---

## Context
A downstream repo wrapped `crumb hook guard` in a sed filter that stripped our permissionDecision keys and rewrote PAUSE/ASK_HUMAN into the advisory shape, deliberately placed in the wrapper rather than site-packages so pip install -U could not undo it. A hook-issued decision outranks the session's permission mode, so the guard reinstated approval prompts for sessions started under bypassPermissions.

## Decision
Read permission_mode from the hook payload. Under bypassPermissions or dontAsk, emit no permissionDecision at all and downgrade to additionalContext; the warning survives, the interruption does not. acceptEdits still prompts (it auto-accepts edits, not destructive shell). CRUMB_GUARD_ADVISORY=1 forces the advisory shape in every mode.

## Rationale
The contract in our own source is 'memory informs; it never allows or denies on its own'. Re-raising a prompt the user explicitly turned off is deciding for them. A user armouring a workaround against our upgrades is the strongest available evidence the default was wrong.

## Consequences
The advisory downgrade never drops the matched records — a suppressed prompt still delivers context. Anyone who wants enforcement in a non-prompting mode has no override, deliberately: the mode is the user's word.
