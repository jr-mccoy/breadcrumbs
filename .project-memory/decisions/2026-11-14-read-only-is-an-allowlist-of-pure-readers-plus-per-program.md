---
id: dec_20261114_read-only-is-an-allowlist-of-pure-readers-plus-per-program
type: decision
slug: read-only-is-an-allowlist-of-pure-readers-plus-per-program
title: Read-only is an allowlist of pure readers plus per-program checks for writers in disguise
status: active
created_at: 2026-11-14T17:17:06+00:00
updated_at: 2026-11-14T17:17:06+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 8a6ee60
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
  - shell
evidence:
  - type: file
    ref: breadcrumbs/shellcmd.py
  - type: file
    ref: breadcrumbs/scoring.py
  - type: test
    ref: tests/test_guard_reading.py
  - type: commit
    ref: 8a6ee60
---

## Decision
READ_ONLY_COMMANDS holds only programs with no write mode; sort, uniq, xxd, yq, fd, rg, tree, date, hostname, find, command and sudo are read-only only when their check passes; git -c, --output and reflog expire/delete are not read-only. A Bash or PowerShell action is never read as an edit (scoring guard shell=True from the hook).

## Rationale
Allowlisting a program by name made its writing options read-only, which capped verdicts at READ_FIRST and dropped permission prompts. A wrong 'not read-only' only costs a guard run; a wrong 'read-only' silences guard.
