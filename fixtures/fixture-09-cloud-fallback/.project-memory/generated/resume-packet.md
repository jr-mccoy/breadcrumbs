<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `continuity resume`. -->
<!-- source_commit: (cloud) | inputs_hash: 87a230c7e4f0 | generated_at: 2026-06-19T17:05:00-05:00 -->

# Resume Packet

## Project
**demo-service** — `.`  
branch `main` · commit `a1b2c3d` · clean

## Current Focus
Plain-file portability.

## Next Action
Verify a CLI-less agent can resume from the committed files.

## Active Decisions
- `dec_20260610_markdown-source-of-truth` — A read-only cloud agent can read plain files without the CLI.

## Failed Attempts To Avoid
- `att_20260612_sqlite-store` — do not retry: do not use a binary store unless plain-file export is automatic and reviewed.

## Known Traps
_(none recorded)_

## Open Questions / Blockers
_(none open)_

## Likely Relevant Files
- continuity.py

## Verification Commands
- python -m unittest discover -s tests

## Stale / Risk Warnings
_(no computed staleness or risk signals)_
