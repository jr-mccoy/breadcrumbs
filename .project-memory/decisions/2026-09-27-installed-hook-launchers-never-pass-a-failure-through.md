---
id: dec_20260927_installed-hook-launchers-never-pass-a-failure-through
type: decision
slug: installed-hook-launchers-never-pass-a-failure-through
title: Installed hook launchers never pass a failure through to the host
status: active
created_at: 2026-09-27T00:24:50+00:00
updated_at: 2026-09-27T00:24:50+00:00
created_by: unknown
agent: claude-code
project: breadcrumbs
scope: project
branch: claude/focused-sagan-axv5ru
commit: 30e41f6
dirty_files:
  - CHANGELOG.md
  - breadcrumbs/__init__.py
  - breadcrumbs/cli.py
  - docs/cli-spec.md
  - tests/test_integrations.py
confidence: high
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - hooks
  - release
evidence:
  - type: file
    ref: tests/test_integrations.py
---

## Context
0.3.0's launcher exec'd the first crumb found. A stale crumb-kit 0.2.0 on PATH answered 'crumb hook prompt' (new UserPromptSubmit hook) with an argparse usage error, exit 2; Claude Code reads exit 2 from UserPromptSubmit/PreToolUse as block, so every prompt in a user's repo was refused.

## Decision
The launcher runs each candidate, forwards output only on success, falls through otherwise (stdin buffered with cat and replayed), and always exits 0. crumb hook <unknown event> prints {} and exits 0. The 0.3.0 launcher is kept verbatim in _legacy_hook_command_0_3_0 so init --with-hooks upgrades it in place.

## Rationale
A hook we install must never be able to veto the host by failing; a real veto is JSON on stdout. Version skew between an installed hook config and a CLI on PATH is normal (global pipx vs project venv).

## What Not To Retry
exec in the launcher; relying on argparse to handle unknown hook events.
