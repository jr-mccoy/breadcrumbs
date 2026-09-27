---
id: dec_20260927_the-guard-pre-filter-is-a-strict-superset-of-what-full
type: decision
slug: the-guard-pre-filter-is-a-strict-superset-of-what-full
title: The guard pre-filter is a strict superset of what full guard can surface
status: active
created_at: 2026-09-27T05:22:43+00:00
updated_at: 2026-09-27T05:22:43+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: e309db6
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - audit
  - wp11
  - guard
  - hooks
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: tests/test_guard_delivery.py
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp11/README.md
---

## Decision
_build_guard_prefilter (format 3) covers every record that could drive a guard verdict (tokens, titles, tags, declared and mentioned paths, kinded command heads), and _prefilter_trap_hit mirrors each _score_item gate; it may admit extra actions but never drops a warning. crumb guard --exit-zero is the only opt-in change to exit codes.

## Rationale
Audit F11/WP11: the traps-only pre-filter made the hook silent on 27 of 193 warnings full guard gives on the eval stores; the superset costs ~0.3 ms median on routine commands.
