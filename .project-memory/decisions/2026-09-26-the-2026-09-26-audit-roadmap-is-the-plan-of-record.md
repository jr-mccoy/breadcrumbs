---
id: dec_20260926_the-2026-09-26-audit-roadmap-is-the-plan-of-record
type: decision
slug: the-2026-09-26-audit-roadmap-is-the-plan-of-record
title: The 2026-09-26 audit roadmap is the plan of record for stabilization; its evidence and tools/audit scripts stay byte-identical
status: active
created_at: 2026-09-26T23:13:12+00:00
updated_at: 2026-09-26T23:13:12+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: 30e41f6
dirty_files:
  - docs/reviews/
  - pyproject.toml
  - tools/
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - audit
  - roadmap
  - process
evidence:
  - type: file
    ref: docs/reviews/2026-09-26-breadcrumbs-audit-and-roadmap.md
  - type: file
    ref: docs/reviews/2026-09-26-breadcrumbs-wp00-baseline/baseline.json
---

## Context
The operator supplied a technical audit of 0.3.0 (26 findings, 23 dependency-ordered work packages WP00-WP22) with evidence and three diagnostic scripts, pinned to 30e41f6.

## Decision
Work from docs/reviews/2026-09-26-breadcrumbs-audit-and-roadmap.md one package at a time, stopping for review after each. Track status in docs/reviews/2026-09-26-breadcrumbs-work-packages.json, and only with evidence. Keep docs/reviews/2026-09-26-breadcrumbs-evidence/ and tools/audit/ unmodified (verify with the committed bundle SHA256SUMS). tools/audit is excluded from ruff for that reason.

## Rationale
The audit evidence is only useful if it stays exactly what was reviewed. Reformatting the scripts would break the checksums. Each package's regressions belong in ordinary tests when that package lands, not in the probe script.

## Consequences
Each repair package converts its probe cases into focused tests under tests/. A probe that errors does not show a fixed defect. Do not rewrite evals/baseline.json to hide a critical miss (F19).
