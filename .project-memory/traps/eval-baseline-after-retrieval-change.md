---
id: trap_eval-baseline-after-retrieval-change
type: trap
slug: eval-baseline-after-retrieval-change
title: A retrieval change fails the evals CI job and test_evals until the baseline is rewritten
status: active
created_at: 2026-09-23T03:20:06+00:00
updated_at: 2026-09-23T03:20:06+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: 5db5432
dirty_files:
  - CHANGELOG.md
  - docs/roadmap-working-memory.md
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
breadcrumbs/cli.py scoring, breadcrumbs/hooks_prompt.py, evals/baseline.json

## Symptom
tests/test_evals.py test_the_committed_suites_match_the_committed_baseline fails, or the evals CI job exits 1 with REGRESSION.

## Why
evals/run.py compares every suite against evals/baseline.json; a rate falling more than 0.05 or any new reject hit is a regression by design.

## Safe approach
Run python evals/run.py --verbose, confirm each moved task moved for a reason you can name, then python evals/run.py --write-baseline and commit the baseline with the change.

## Verification
python evals/run.py
