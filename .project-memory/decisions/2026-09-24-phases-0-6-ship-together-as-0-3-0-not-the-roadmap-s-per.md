---
id: dec_20260924_phases-0-6-ship-together-as-0-3-0-not-the-roadmap-s-per
type: decision
slug: phases-0-6-ship-together-as-0-3-0-not-the-roadmap-s-per
title: Phases 0-6 ship together as 0.3.0, not the roadmap's per-phase 0.3.0-0.9.0
status: active
created_at: 2026-09-24T19:45:32+00:00
updated_at: 2026-09-24T19:45:32+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/release-prep-publish-dw1xzf
commit: 7a4a07f
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/__init__.py
  - docs/roadmap-working-memory.md
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - release
evidence:
  - type: file
    ref: CHANGELOG.md
  - type: file
    ref: docs/roadmap-working-memory.md
  - type: file
    ref: breadcrumbs/__init__.py
---

## Decision
Cut the working-memory phases 0-6 as one release, 0.3.0.

## Rationale
No per-phase release was ever cut. The next minor after 0.2.0 is the honest number for a schema 1->4 jump, and cli.py already said the guard matcher changed in 0.3.0. Numbering it 0.9.0 would imply six releases that never existed.
