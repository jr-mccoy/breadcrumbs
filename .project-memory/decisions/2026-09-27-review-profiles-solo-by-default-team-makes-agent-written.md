---
id: dec_20260927_review-profiles-solo-by-default-team-makes-agent-written
type: decision
slug: review-profiles-solo-by-default-team-makes-agent-written
title: Review profiles: solo by default, team makes agent-written guidance a proposal and promotion needs a content-bound review
status: active
created_at: 2026-09-27T21:08:26+00:00
updated_at: 2026-09-27T21:08:26+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/new-session-9f1k6i
commit: af135ab
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
  - review
  - audit
evidence:
  - type: file
    ref: breadcrumbs/admission.py
  - type: file
    ref: tests/test_admission_policy.py
  - type: file
    ref: docs/reviews/2026-09-27-breadcrumbs-wp14/README.md
---

## Context
Audit F18/WP14: agent: human and review_status: reviewed were payload claims; promote and MCP retirement had no authority boundary.

## Decision
admission.py: solo (default, unchanged) and team profiles plus mcp_mode, set only by the CLI crumb policy; channel from the transport; payload review fields and MCP/hook agent: human refused; team: agent-written guidance is an unattended needs-review proposal, high-impact MCP status changes refused, promote needs a valid crumb review stamp (reviewed_hash), store declares requires: review-profiles; read-only MCP omits writing tools.

## Rationale
Proportional: ordinary capture never waits for a person; only the writes that make memory authoritative are gated. Opt-in semantics use requires: instead of a store-wide schema bump.

## Consequences
Does not bind a full-shell agent or crumb-kit <=0.3.1; Git review of .project-memory and instruction files is that boundary (security.md 4.2).
