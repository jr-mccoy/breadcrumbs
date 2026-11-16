---
id: dec_20261114_scan-secrets-reads-every-committed-file-and-needs
type: decision
slug: scan-secrets-reads-every-committed-file-and-needs
title: scan-secrets reads every committed file and needs a credential-shaped value after a label
status: active
created_at: 2026-11-14T15:15:53+00:00
updated_at: 2026-11-14T15:15:53+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 10f8a9d
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - security
  - secrets
evidence:
  - type: file
    ref: breadcrumbs/secretscan.py
  - type: test
    ref: tests/test_gate.py
  - type: commit
    ref: 10f8a9d
---

## Decision
The scan covers every file the store commits (all but private/ and index/, plus index/README.md), whatever its suffix; NUL bytes make a file unscannable. A label may sit inside a variable name, and the value must hold a letter plus a digit or both cases (quoted: 12+ chars, letter and digit). .crumbignore: # comments only at line start; an empty-matching pattern is reported and unused; runs report exempted lines.

## Rationale
Common env-style secrets passed as OK, files outside five suffixes were never read, and one .crumbignore line could disable the scan silently. The value rule keeps prose such as token budgets and key-file paths from blocking; this repository's own store and docs stay clean under the new patterns.
