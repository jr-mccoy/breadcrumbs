---
id: idea_20260620_cache-parsed-sessions-in-the-auth-middleware
type: idea
slug: cache-parsed-sessions-in-the-auth-middleware
title: Cache parsed sessions in the auth middleware
status: active
created_at: 2026-06-20T10:00:00-05:00
updated_at: 2026-06-20T10:00:00-05:00
created_by: alex
agent: human
project: demo-service
scope: project
branch: main
commit: b4c5d6e
dirty_files: []
confidence: medium
privacy: repo-safe
review_status: unreviewed
reviewed_by: null
supersedes: []
superseded_by: null
expires_at: null
tags:
  - auth
  - session
evidence: []
---

## Idea

Cache parsed sessions in the auth middleware instead of re-parsing per request.

## Motivation

`src/auth/middleware.ts` parses the session on every request. Nobody has measured
it — this is a hunch, which is exactly why it is an idea and not a verification.

## Sketch

A small LRU in `src/auth/middleware.ts` keyed by the session id, invalidated on
logout. Untried.

## Open Questions

Does the session parser contract permit caching at all?
