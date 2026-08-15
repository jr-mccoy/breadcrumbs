---
id: dec_20260815_cut-0-1-10-as-the-agent-authorship-release
type: decision
slug: cut-0-1-10-as-the-agent-authorship-release
title: Cut 0.1.10 as the agent-authorship release
status: active
created_at: 2026-08-15T03:14:19+00:00
updated_at: 2026-08-15T03:14:19+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/system-audit-viability-e2sft7
commit: ac8352c
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/__init__.py
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - release
  - versioning
evidence:
  - type: file
    ref: breadcrumbs/__init__.py
  - type: command
    ref: python -m build --wheel
---

## Context
0.1.9 shipped a store whose high-value records were 100% hand-written. The audit found the authorship gap was the adoption blocker, not missing features.

## Options Considered
_(not recorded)_

## Decision
Bump __version__ to 0.1.10 (single source of truth) and date the CHANGELOG section. Headline is the Stop-hook extraction turn; the prefilter and stemming fixes make what it writes reachable. Version bump + changelog are the ONLY manual edits — release.yml cuts the tag and Release.

## Rationale
_(not recorded)_

## Consequences
Existing hook installs get the extraction prompt automatically on upgrade; extraction_prompt: false opts out. Stored inputs_hash stamps invalidate once, cleared by crumb reindex.

## What Not To Retry
_(not recorded)_

## Evidence
_(not recorded)_

## Stale / Review Conditions
_(not recorded)_
