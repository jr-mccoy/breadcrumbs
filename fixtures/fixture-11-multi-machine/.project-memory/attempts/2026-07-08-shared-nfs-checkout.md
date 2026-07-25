---
id: att_20260708_shared-nfs-checkout
type: attempt
slug: shared-nfs-checkout
title: One shared NFS checkout for both developers
status: active
created_at: 2026-07-08T14:00:00-05:00
updated_at: 2026-07-08T14:00:00-05:00
created_by: sam
agent: human
project: shared-service
scope: project
branch: main
commit: 7c31f0a
dirty_files: []
confidence: high
privacy: repo-safe
review_status: reviewed
reviewed_by: dana
supersedes: []
superseded_by: null
expires_at: null
tags:
  - multi-machine
evidence:
  - type: commit
    ref: 7c31f0a
---

## What Was Tried
Putting a single checkout on an NFS share so both developers use the same path.

## Why
It would have made every machine-dependent artifact agree by construction.

## Result
Failed. The editors fought over file locks and the test suite ran ~6x slower.

## Root Cause (if known)
Shared-filesystem latency plus two concurrent watchers on the same tree.

## Do Not Retry Unless
The tooling stops writing per-machine state into committed files, which is the
actual problem this was trying to work around.

## Evidence
- commit 7c31f0a

## Stale / Review Conditions
Revisit if the team moves to a remote-development host.
