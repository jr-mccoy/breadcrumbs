---
id: dec_20260928_the-native-full-suite-runs-on-main-weekly-and-on-demand
type: decision
slug: the-native-full-suite-runs-on-main-weekly-and-on-demand
title: The native full suite runs on main, weekly and on demand
status: active
created_at: 2026-09-28T02:02:37+00:00
updated_at: 2026-09-28T02:02:37+00:00
created_by: unknown
agent: unknown
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: 529356e
dirty_files:
  - RELEASING.md
  - docs/releases/
  - docs/reviews/2026-09-26-breadcrumbs-work-packages.json
  - docs/reviews/2026-09-28-breadcrumbs-wp22/
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - ci
evidence:
  - type: commit
    ref: a8c3960
  - type: file
    ref: .github/workflows/ci.yml
---

## Context
The Windows full suite takes 20-25 minutes per Python; running it on every push was more runner time than the operator wanted (2026-09-28).

## Decision
Every push gates on the native installed-wheel smoke and contract tests. The whole unit suite on Windows and macOS runs in the native-full job only on pushes to main, weekly (Monday 06:17 UTC) and via workflow_dispatch, reported and not gating.

## Rationale
Keeps per-push cost low while main and a weekly run still see platform regressions; run it by hand on a branch before merging platform-sensitive changes.
