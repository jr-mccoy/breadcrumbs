---
id: dec_20260905_a-read-only-action-caps-at-read-first-and-entropy-warns
type: decision
slug: a-read-only-action-caps-at-read-first-and-entropy-warns
title: A read-only action caps at READ_FIRST, and entropy warns instead of gating
status: active
created_at: 2026-09-05T00:29:54+00:00
updated_at: 2026-09-05T00:29:54+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/artifact-388cc819-sm0ipj
commit: a5de02b
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags: []
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: tests/test_secret_precision.py
---

## Context
Field review G2 and R5: git status was the loudest command measured (PAUSE, 5 records) while npm test was silent at PROCEED; and every secret-scan hit was a Firebase push id in a production path, blocking the memory commit until hand-overridden.

## Decision
Classify the action's side effects before the verdict: a reporting command (cat/ls/grep/find without acting flags, git status|log|diff|show|blame|…) caps at READ_FIRST, reported as read_only in --json. And split scan-secrets by severity: only structured shapes exit non-zero; high-entropy-string warns, with .project-memory/.crumbignore to retire a false positive once.

## Rationale
Neither is a scoring problem. Overlap is symmetric, so corpus frequency reads as relevance and no weighting fixes a command that cannot do the thing being warned about. And a gate that is hand-overridden every time has stopped being a gate — worse, it punishes exactly the records that cite a concrete path, which are the most useful ones a store has. Both classifications are conservative: an unrecognized action keeps its full verdict, and a structured credential still blocks.

## Consequences
GUARD_READ_ONLY_COMMANDS is an allowlist and will miss commands; the cost is an unnecessary PAUSE, never a swallowed one. scan-secrets can now exit 0 with hits printed — a caller that treated any output as failure must read the exit code or the blocking count.
