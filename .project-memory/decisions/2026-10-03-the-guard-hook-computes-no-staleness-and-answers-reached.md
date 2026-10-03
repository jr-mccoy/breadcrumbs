---
id: dec_20261003_the-guard-hook-computes-no-staleness-and-answers-reached
type: decision
slug: the-guard-hook-computes-no-staleness-and-answers-reached
title: The guard hook computes no staleness and answers reached-HEAD for store files from a per-HEAD tree cache, never git
status: active
created_at: 2026-10-03T16:53:15+00:00
updated_at: 2026-10-03T16:53:15+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/charming-sagan-9o911q
commit: be529bc
dirty_files: []
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - git
  - performance
  - retest
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: file
    ref: breadcrumbs/hooks_guard.py
  - type: file
    ref: tests/test_retest_060.py
---

## Context
DoWhat retest of 0.6.0, item 1: 2 to 5 git processes per firing (40 ms each on Windows) came from handoff staleness the hook never shows, and from HeadTree (rev-parse, ls-tree, status) for records written on cloud branches.

## Decision
scoring.guard(staleness=False) from the hook; crumb guard keeps it. HeadTree answers store paths from index/head-tree.txt (blob ids of the store at HEAD, keyed by HEAD sha and store prefix) by hashing the work-tree file, CRLF folded; paths outside the store still ask git.

## Rationale
At a stable HEAD a full firing now starts 0 processes, including on a shallow blob-filtered clone; after HEAD moves at most 2 (rev-list, ls-tree), neither needing a blob.
