---
id: dec_20261114_the-project-root-is-the-nearest-store-at-or-above-cwd
type: decision
slug: the-project-root-is-the-nearest-store-at-or-above-cwd
title: The project root is the nearest store at or above cwd, stopping at .git
status: active
created_at: 2026-11-14T14:57:15+00:00
updated_at: 2026-11-14T14:57:15+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 973bbcb
dirty_files:
  - .claude/
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - hooks
  - cli
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: tests/test_delivery_reach.py
---

## Decision
Without --project, the CLI and MCP use the nearest directory at or above cwd holding .project-memory/ (cli.find_store_root), stopping at the first .git and never taking home or /; else cwd. --project is exact. Hooks walk from the payload cwd, then CLAUDE_PROJECT_DIR, then BREADCRUMBS_PROJECT.

## Rationale
Payload cwd follows every cd, so hooks went silent in subdirectories and crumb init from src/ made a nested store. Stopping at .git keeps an enclosing repo's store out of submodules and nested repos. Payload cwd comes before CLAUDE_PROJECT_DIR because inside a linked worktree it is the worktree, whose store is the branch being worked on. CLAUDE_PROJECT_DIR is not set in Bash tool shells, so the CLI does not read it.
