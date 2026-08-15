---
id: dec_20260815_crumb-guard-exits-verdict-mapped-codes-0-10-15-20
type: decision
slug: crumb-guard-exits-verdict-mapped-codes-0-10-15-20
title: crumb guard exits verdict-mapped codes: 0, 10, 15, 20
status: active
created_at: 2026-08-15T20:29:40+00:00
updated_at: 2026-08-15T20:29:40+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/crumb-kit-0.1.10-triage-l3qo5a
commit: c34db39
dirty_files:
  - .project-memory/generated/resume-packet.md
  - .project-memory/decisions/2026-08-15-guard-verdict-floors-require-file-tag-specificity-keyword.md
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - cli-contract
evidence:
  - type: commit
    ref: d7c639e
---

## Decision
PROCEED=0, READ_FIRST=10, PAUSE=15, ASK_HUMAN=20; 2 stays usage-error; hook paths always exit 0. Codes deliberately avoid 1/2/126+.

## Rationale
Callers could not script on verdicts at all (everything exited 0), and a Windows field-test harness rendered advisory verdicts as tool failures; documented spaced codes make 'block only on ASK_HUMAN' possible and any host-layer weirdness diagnosable.
