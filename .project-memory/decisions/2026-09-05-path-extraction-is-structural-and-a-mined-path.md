---
id: dec_20260905_path-extraction-is-structural-and-a-mined-path
type: decision
slug: path-extraction-is-structural-and-a-mined-path
title: Path extraction is structural, and a mined path is not a declared one
status: active
created_at: 2026-09-05T00:29:33+00:00
updated_at: 2026-09-05T00:29:33+00:00
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
    ref: tests/test_guard_precision.py
---

## Context
The 0.1.11 field review (G1): the guard prefilter of a 310-session store held 439 paths, 89 of which existed. same file(s) is guard's strongest signal, so json.load drew a PAUSE from a screenshot trap.

## Options Considered
(a) validate tokens against the repo tree at index time, as the review proposed; (b) a structural shape test; (c) an authored paths: field only.

## Decision
Structural test — a known file extension, or a real path shape (no leading -, no version-shaped or purely numeric segments, not all-caps, a dot alone proves nothing) — plus two tiers: evidence file/path refs and a trap's Area / files: bullet are declared (GUARD_W_FILE 6, reads as 'same file(s)'), prose-mined paths are mentions (GUARD_W_MENTION 2, reads as 'mentions:', cannot floor a verdict).

## Rationale
Existence on disk was rejected deliberately: a record citing a file that was since deleted or renamed is often exactly the trap worth raising, and a store must mean the same thing in every checkout that reads it. The shape test rejects 15 of the 16 junk tokens the review names and keeps every real path tested. Tiering is the review's own point 3 — a trap author knows which files their trap is about — without a schema change, because the declaration field already exists in both record types.

## Consequences
Retrieval is unchanged: mentions still open the candidate gate and --file search still finds them, because 'which records concern X' is a different question from 'what may this match claim'. /tmp/x is still accepted; no structural rule distinguishes it from a real path.
