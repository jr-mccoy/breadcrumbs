---
id: trap_linux-cannot-show-a-windows-path-separator-bug
type: trap
slug: linux-cannot-show-a-windows-path-separator-bug
title: Linux cannot show a Windows path-separator bug
status: active
created_at: 2026-09-28T02:02:38+00:00
updated_at: 2026-09-28T02:02:38+00:00
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
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags: []
evidence: []
---

## Area / files
breadcrumbs/*.py

## Symptom
str(p.relative_to(x)) passes every Linux test but is backslashed on Windows, where comparisons against POSIX paths silently match nothing

## Why
on POSIX str() and as_posix() of a relative path are identical

## Safe approach
use .as_posix(); run the native-full job (workflow_dispatch) before merging platform-sensitive changes

## Verification
python -m unittest discover -s tests -p test_platform_portability.py
