<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: (no-git) | inputs_hash: c4a77fff7aac | generated_at: 2026-07-25T01:30:19+00:00 -->

# Resume Packet

## Project
**shared-service** — `.`  
branch `(no-git)` · commit `(no-git)` · clean

## Current Focus
Splitting the ingest worker out of the API process.

## Next Action
Move `IngestConsumer` behind the feature flag in `api/app.py` and run the worker suite.

## Active Decisions
- `dec_20260702_distillate-sessions` — Session records are per-machine narration; committing them made every pull a

## Failed Attempts To Avoid
- `att_20260708_shared-nfs-checkout` — do not retry: The tooling stops writing per-machine state into committed files, which is the

## Known Traps
- trap_absolute-paths-in-committed-files: a committed file must never carry a checkout path

## Open Questions / Blockers
- Should the worker own its own schema migrations

## Likely Relevant Files
- api/app.py
- worker/ingest.py

## Verifications
_(none recorded)_

## Verification Commands
- python -m unittest discover -s tests

## Stale / Risk Warnings
- handoff is 4 day(s) old.
- active decision dec_20260702_distillate-sessions is 22 days old with no update — is this still true?
