---
id: dec_20260905_a-trap-summary-is-capped-at-write-time-and-again-at-display
type: decision
slug: a-trap-summary-is-capped-at-write-time-and-again-at-display
title: A trap summary is capped at write time and again at display time
status: active
created_at: 2026-09-05T03:23:15+00:00
updated_at: 2026-09-05T03:23:15+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/guard-context-bloat-wcle08
commit: 53b5dac
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/cli.py
  - breadcrumbs/templates/project-memory/known-traps.md
  - tests/test_hooks.py
  - tests/test_traps.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - traps
  - context-budget
  - guard
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: tests/test_traps.py
---

## Context
A trap's summary is its heading, and the heading is what crumb traps, the resume packet and the PreToolUse guard advisory all print — the last of those on every tool call. Nothing bounded it. One field-store trap carried an 1,123-character summary and surfaced 15 times in one session: 16,845 bytes, 40% of that session's whole guard cost from a single record.

## Decision
TRAP_SUMMARY_MAX_CHARS = 200, enforced in _trap_block (so every writer, CLI and MCP alike, gets it) with the author's full sentence parked in a '- Full summary:' bullet, and enforced again in _hook_guard_reason and the resume packet's known_traps.

## Rationale
Capping at write time alone fixes nothing that matters: the traps that dominate a store's always-on context are the ones already written, and no store rewrites its history. Capping at display alone would let the file keep growing summaries no reader shows. Parking rather than truncating is what makes the write-time cap safe — _block_content keeps the bullet, so guard still scores against every word the author wrote, and the file still reads in full.

## Consequences
The worst measured record drops from 1,123 to 200 characters wherever it is re-read. A first-firing advisory for two traps went from 1,425 to 422 bytes.
