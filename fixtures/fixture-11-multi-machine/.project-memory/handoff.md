# Project Handoff

_Last updated: 2026-07-20T16:30:00-05:00_
_Branch: main_
_Commit: 7c31f0a_

## Current Focus

Splitting the ingest worker out of the API process.

## Next Action

Move `IngestConsumer` behind the feature flag in `api/app.py` and run the worker suite.

## Blockers / Open Questions

q:should-the-worker-own-its-own-schema-migrations

## Active Decisions To Respect

dec_20260702_distillate-sessions

## Failed Attempts To Avoid

att_20260708_shared-nfs-checkout

## Known Traps

trap_absolute-paths-in-committed-files

## Likely Relevant Files

- api/app.py
- worker/ingest.py

## Verification Commands

- python -m unittest discover -s tests

## Stale If

- the feature flag is removed, or the worker split lands
