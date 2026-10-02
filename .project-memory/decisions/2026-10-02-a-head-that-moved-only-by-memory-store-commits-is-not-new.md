---
id: dec_20261002_a-head-that-moved-only-by-memory-store-commits-is-not-new
type: decision
slug: a-head-that-moved-only-by-memory-store-commits-is-not-new
title: A HEAD that moved only by memory-store commits is not new work for the Stop hook
status: active
created_at: 2026-10-02T19:18:35+00:00
updated_at: 2026-10-02T19:18:35+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-e63a7edc-aluyzm
commit: 84633e4
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/__init__.py
  - breadcrumbs/cli.py
  - docs/compatibility.md
  - tests/test_hooks.py
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - stop-hook
  - capture
  - snapshot
  - release-0.6.0
evidence:
  - type: file
    ref: breadcrumbs/cli.py
  - type: test
    ref: tests/test_hooks.py::HookCaptureTests::test_committing_the_snapshot_is_not_new_work
---

## Context
The Stop hook's snapshot records HEAD and the projections record source_commit. The agent commits the snapshot, HEAD moves, the next Stop reads 'work moved', rewrites the record with the sha of the commit that committed it, and the store is dirty again. Reproduced in a scratch repo: every memory commit was followed by another dirty snapshot, forever. The stop_hook_active guard only stops the hook from blocking twice; it never covered the silent snapshot path.

## Decision
_hook_capture_is_redundant treats HEAD movement as work only when base..HEAD contains a commit touching something outside .project-memory/ (_work_commits_between), the same :(exclude) filter _session_commits already applies. A base the clone cannot resolve still counts as work.

## Rationale
The hook runs after the agent's last commit by construction, so any tracked file it writes is left uncommitted; the one-round cost is acceptable, an unbounded one is not. Reusing the commit counter's definition of work keeps one notion of 'this session's work' across the ask and the snapshot.

## Consequences
After the extraction turn, the agent's own capture session, committed, is the session's capture: the continuation writes nothing beside it. A snapshot's commit: field now names the last work commit, not the memory commit on top of it. Not covered: an agent that bundles code and memory into one commit after the ask still gets a machine snapshot stacked beside its authored record (an ask-time guard would close that). The larger design option, Stop writing only under private/ and SessionStart folding it forward, was not taken in 0.6.0.

## Stale / Review Conditions
Revisit if the Stop hook stops writing tracked files, or if _session_commits changes what counts as the session's work.
