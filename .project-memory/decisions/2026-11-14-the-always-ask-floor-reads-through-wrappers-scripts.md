---
id: dec_20261114_the-always-ask-floor-reads-through-wrappers-scripts
type: decision
slug: the-always-ask-floor-reads-through-wrappers-scripts
title: The always-ask floor reads through wrappers, scripts and every spelling of its actions
status: active
created_at: 2026-11-14T17:17:05+00:00
updated_at: 2026-11-14T17:17:05+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: ccr-5a263b6c-3gtzxn
commit: 8a6ee60
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - guard
  - shell
evidence:
  - type: file
    ref: breadcrumbs/shellcmd.py
  - type: test
    ref: tests/test_guard_reading.py
  - type: commit
    ref: 8a6ee60
---

## Decision
shellcmd.words() strips command wrappers (sudo, env, command, nice, timeout, stdbuf, ...); expanded_words() adds bash -c/eval scripts, $() bodies and code heredocs, read even when dynamic. The floor covers --force-with-lease, refs/heads/, deletes of a default branch, rm -rf on anything but project-relative build paths or temp paths, and crumb migrate with global options.

## Rationale
Each of these spellings returned PROCEED for an action the floor exists to catch. Reading through wrappers in one place ends the pattern of adding one rule per spelling; property tests pin that a rewrite never lowers a verdict. It stays a reminder: a command assembled from variables at run time can still pass.
