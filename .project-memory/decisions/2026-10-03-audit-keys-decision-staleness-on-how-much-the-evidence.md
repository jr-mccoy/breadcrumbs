---
id: dec_20261003_audit-keys-decision-staleness-on-how-much-the-evidence
type: decision
slug: audit-keys-decision-staleness-on-how-much-the-evidence
title: Audit keys decision staleness on how much the evidence moved, not on age; the packet carries no decision age line
status: active
created_at: 2026-10-03T14:54:57+00:00
updated_at: 2026-10-03T14:54:57+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-4e962709-tubaoe
commit: 78f6691
dirty_files:
  - docs/reviews/2026-10-02-deferred-health-review.md
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - audit
  - staleness
  - evals
evidence:
  - type: file
    ref: breadcrumbs/audit.py
  - type: file
    ref: tests/test_decision_staleness.py
  - type: file
    ref: evals/suites/staleness/store.crumb
---

## Context
Health review 1.1: 17 of 21 audit warnings were 'active decision … is N days old with no update', repeated in every resume packet. Keying on 'a cited file changed since' instead flagged 48 of 56 decisions on main, because cited code changes in a project under work.

## Decision
compute_staleness no longer warns on a decision's age. audit.decision_staleness_findings: decision-evidence-rewritten (WARN) when a cited file churned by >= 0.5x its current size since the decision's commit (ancestry; commit time when the clone lacks it), excluding the decision's own landing (the commit creating a cited file, or the first touching a file dirty at record time) and hub files (> 15% of commits, once there are 40); decision-evidence-changed (one INFO line) for smaller changes; decision-aged (INFO) past 8x the cutoff when nothing else questions the record. possible-contradiction, near-duplicates and evidence-missing-file still question a decision.

## Rationale
Measured on this store: 6 warnings on main where the age rule gave 17 and 'touched since' gave 48, each a real candidate. Two git processes for the whole store. The staleness eval suite (split: checks) asserts every true staleness kind is questioned and an old untouched decision is not.

## What Not To Retry
Do not warn on 'a cited file changed since' alone, and do not put decision age back in the packet: both were measured as noise. Tune AUDIT_EVIDENCE_REWRITE_SHARE / AUDIT_EVIDENCE_HUB_SHARE against evals/suites/staleness and this store's audit, not by feel.
