---
id: dec_20260922_multi-agent-safety-branch-handoffs-one-command-level-store
type: decision
slug: multi-agent-safety-branch-handoffs-one-command-level-store
title: Multi-agent safety: branch handoffs, one command-level store lock, and branch scope
status: active
created_at: 2026-09-22T22:07:04+00:00
updated_at: 2026-09-22T22:07:04+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 600ec2d
dirty_files:
  - CHANGELOG.md
  - docs/roadmap-working-memory.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - multi-agent
  - handoff
  - lock
  - phase-5
  - wm-50
  - wm-51
  - wm-52
evidence:
  - type: file
    ref: breadcrumbs/handoffs.py
  - type: file
    ref: breadcrumbs/lock.py
  - type: command
    ref: python -m unittest tests.test_handoffs tests.test_lock tests.test_scope
---

## Context
Phase 5 (WM-50 to WM-52): several agents on several branches share one store; handoff.md was a singleton and parallel hooks could interleave read-modify-write sequences.

## Decision
Schema 4: captures on a non-default branch write handoffs/<branch-slug>.md (default branch = origin/HEAD, else main/master; first write seeded from handoff.md); readers pick the branch file and fall back to handoff.md. breadcrumbs/lock.py: an O_EXCL lock file in private/, an in-process lock per store, re-entrant per thread, taken once per writing command at dispatch (CLI waits 2 s then exit 1), per writing hook (0.5 s then skip with {}), per MCP writer; never by the session or guard hooks or read commands; stale after 60 s or a dead POSIX pid. scope: branch records are filtered out of the packet and guard's live set on other branches.

## Rationale
Every writer reindexes, so per-writer locking would take the lock many times per command and still not cover multi-writer sequences like capture. Hooks must never block the host. A feature branch's next action must not be what a session on main reads first.

## What Not To Retry
Do not lock in the guard or session hooks. Do not probe pids with os.kill(pid, 0) on Windows (signal 0 is CTRL_C_EVENT).
