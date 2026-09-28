---
id: dec_20260928_store-relative-paths-are-posix-and-line-endings
type: decision
slug: store-relative-paths-are-posix-and-line-endings
title: Store-relative paths are POSIX and line endings are not content
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
  - windows
  - portability
evidence:
  - type: commit
    ref: 48bc814
  - type: commit
    ref: f528a24
  - type: file
    ref: tests/test_platform_portability.py
---

## Context
The first native CI runs found Windows and macOS defects Linux could not show: CRLF made hashes and the mutation journal disagree with disk, and backslashed relative paths matched nothing.

## Decision
Render every store-relative path with as_posix(); never str(p.relative_to(...)). Normalize CRLF to LF before hashing inputs or projection digests. Journal the bytes actually written, not the text before translation.

## Rationale
A store is shared across machines and platforms; a value that differs by OS makes stamps stale everywhere and made rollback and the write gate silently wrong on Windows.

## Consequences
tests/test_platform_portability.py refuses str(...relative_to(...)) in the package by AST; an LF-only store hashes exactly as before.
