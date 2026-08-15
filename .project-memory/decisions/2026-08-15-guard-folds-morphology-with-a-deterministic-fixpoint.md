---
id: dec_20260815_guard-folds-morphology-with-a-deterministic-fixpoint
type: decision
slug: guard-folds-morphology-with-a-deterministic-fixpoint
title: Guard folds morphology with a deterministic fixpoint stemmer, not vectors
status: active
created_at: 2026-08-15T01:24:22+00:00
updated_at: 2026-08-15T01:24:22+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/system-audit-viability-e2sft7
commit: f981707
dirty_files:
  - .gitignore
  - CHANGELOG.md
  - CLAUDE.md
  - README.md
  - breadcrumbs/cli.py
  - docs/cli-spec.md
  - docs/record-schema.md
  - tests/test_guard.py
  - tests/test_hooks.py
  - tests/test_integrations.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - search
  - stemming
evidence:
  - type: command
    ref: python -m unittest tests.test_guard
  - type: file
    ref: breadcrumbs/cli.py
---

## Context
Exact-token matching missed paraphrases (reconciliation vs reconciler): 9/12 recall on a 16-case eval. Synonym drift is the main case, not the edge case.

## Options Considered
_(not recorded)_

## Decision
Small suffix-stripper applied longest-first to a fixpoint (idempotent, so the prefilter can re-stem older on-disk indexes), plus a tiny curated alias table (auth/config/db/repo). No embeddings; vectors stay a later disposable accelerator per architecture.md.

## Rationale
_(not recorded)_

## Consequences
Recall 11/12, zero new false positives. Two-letter abbreviations (ES) stay unmatched by design: too collision-prone.

## What Not To Retry
_(not recorded)_

## Evidence
_(not recorded)_

## Stale / Review Conditions
_(not recorded)_
