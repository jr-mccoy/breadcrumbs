---
id: dec_20260815_the-tool-s-own-repo-commits-its-own-memory-store
type: decision
slug: the-tool-s-own-repo-commits-its-own-memory-store
title: The tool's own repo commits its own memory store
status: active
created_at: 2026-08-15T01:27:17+00:00
updated_at: 2026-08-15T01:27:17+00:00
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
  - tests/test_note.py
  - .project-memory/
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - dogfood
  - repo-policy
evidence:
  - type: file
    ref: .gitignore
  - type: command
    ref: python crumb.py validate
---

## Context
The .gitignore carried a deliberate rule: never commit a real store into the tool's own repo. The 2026-08-15 audit found the cost: the project had never dogfooded, and a hook-defeating prefilter bug survived 8 releases that two weeks of self-use would have caught. architecture.md lists dogfood as a load-bearing build step.

## Options Considered
_(not recorded)_

## Decision
Remove the blanket ignore and commit .project-memory/ in this repo, exactly as a target project would (managed block still keeps private/ and index/ local). The store is the repo's continuity ledger and its live demo.

## Rationale
_(not recorded)_

## Consequences
Cloud/read-only sessions on this repo resume from the committed files. Fixture stores are unaffected. Session records accrue in-repo under the full tracking policy; revisit the policy if churn gets noisy.

## What Not To Retry
_(not recorded)_

## Evidence
_(not recorded)_

## Stale / Review Conditions
_(not recorded)_
