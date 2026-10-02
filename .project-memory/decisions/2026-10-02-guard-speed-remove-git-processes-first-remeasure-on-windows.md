---
id: dec_20261002_guard-speed-remove-git-processes-first-remeasure-on-windows
type: decision
slug: guard-speed-remove-git-processes-first-remeasure-on-windows
title: Guard speed: remove git processes first, remeasure on Windows before a fast path
status: active
created_at: 2026-10-02T04:33:01+00:00
updated_at: 2026-10-02T04:33:01+00:00
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
  - guard
  - performance
  - windows
evidence:
  - type: file
    ref: breadcrumbs/gitrefs.py
  - type: test
    ref: tests/test_gitrefs.py
---

## Decision
The guard path reads refs from .git (gitrefs.py) and caches HEAD's history in index/commit-order.txt; the hook log records git_ms and import_ms. A slim entry point, helper process or compiled pre-check waits for Windows phase numbers from doctor --hook-log.

## Rationale
DoWhat retest of 0.5.0, item 7, operator decision D7: p50 764 ms on Windows; 24 of 29 firings took the full path with 5 git spawns each.
