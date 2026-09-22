<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: d71a7e3 | inputs_hash: 2e3dc7f5b30d | generated_at: 2026-09-22T16:43:07+00:00 -->

# Resume Packet

## Project
**shared-service** — `.`  
branch `claude/agentic-memory-system-mybkpi` · commit `d71a7e3` · 36 uncommitted file(s)

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
_(ages below are measured; the cutoff is 21 days — set with `--stale-days`)_
- ⚠ handoff is 63 day(s) old.
- active decision dec_20260702_distillate-sessions is 82 days old with no update — is this still true?
- open question "Should the worker own its own schema migrations" has been open 66 days — did this ever get resolved?
