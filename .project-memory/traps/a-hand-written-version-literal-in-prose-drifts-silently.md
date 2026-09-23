---
id: trap_a-hand-written-version-literal-in-prose-drifts-silently
type: trap
slug: a-hand-written-version-literal-in-prose-drifts-silently
title: A hand-written version literal in prose drifts silently
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
README.md (Status section); any doc that restates the package version

## Symptom
README's Status section claimed the checkout was 0.1.8 while breadcrumbs/__init__.py said 0.1.12 — four releases of drift, invisible to CI, tests, validate and audit alike.

## Why
The single-source-of-truth design covers pyproject.toml and cli.py, which READ __version__. Prose does not read anything: a version written into a sentence is a copy, and nothing in the bench compares that copy against the source. Release only bumps the one line it is told to.

## Safe approach
Do not restate the version in prose. Point readers at 'crumb --version' and the top section of CHANGELOG.md, so the text stays true at any version.

## Verification
grep -n '0\.1\.[0-9]' README.md # should return nothing
