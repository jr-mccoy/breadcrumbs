---
id: trap_a-record-s-remedy-fields-are-mined-for-file-paths
type: trap
slug: a-record-s-remedy-fields-are-mined-for-file-paths
title: A record's remedy fields are mined for file paths and become its blast radius
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
breadcrumbs/cli.py _item_from_trap / _item_from_record

## Symptom
A trap fires on commands that have nothing to do with its hazard — a trap whose Verification was './gradlew test' matched every gradle invocation in the repo, read-only './gradlew --status' included.

## Why
_paths_from_text mines path-like tokens from the WHOLE record body, including the Safe approach and Verification bullets. Those tokens then score GUARD_W_FILE (6) — the strongest signal, and the one exempted from the ubiquity gate because file references are 'author-curated'. Scraped prescriptions are not curated and name the cure, not the fragile area.

## Safe approach
Mine file signal from the hazard half only; keep the remedy as weak keyword evidence at GUARD_W_KEYWORD (1).

## Verification
python -m unittest tests.test_guard
