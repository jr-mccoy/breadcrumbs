---
id: trap_a-bare-n-in-a-commit-message-links-an-issue-but-never
type: trap
slug: a-bare-n-in-a-commit-message-links-an-issue-but-never
title: A bare (#N) in a commit message links an issue but never closes it
status: active
created_at: 2026-09-22T19:27:00+00:00
updated_at: 2026-09-22T19:27:00+00:00
created_by: unknown
agent: migration
project: breadcrumbs
scope: project
branch: claude/agentic-memory-system-mybkpi
commit: ce0d42f
dirty_files: []
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
commit messages, PR descriptions; .github/ has no automation for this

## Symptom
Issues #5-#8 were fixed on 2026-06-27, one day after being filed, by commits titled 'fix(secrets): flag labeled hex tokens (#5)' and siblings. All four stayed OPEN for seven weeks, publicly advertising bugs that no longer existed, until a portfolio review re-checked them against the code.

## Why
GitHub auto-closes only on a closing keyword — 'Fixes #N' / 'Closes #N' / 'Resolves #N'. A parenthetical '(#N)' creates a cross-reference link and nothing more. The link makes the commit look connected, which is exactly why nobody notices the issue never closed.

## Safe approach
Write 'Fixes #N' on its own line in the commit message or PR body. Documented in CONTRIBUTING.md under Submitting. When closing late, comment with the fix commit and what shipped rather than closing silently.

## Verification
gh issue list --state open # every open issue should describe a bug that still reproduces
