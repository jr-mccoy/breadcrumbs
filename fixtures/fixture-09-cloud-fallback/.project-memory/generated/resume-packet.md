<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: a1e479a | inputs_hash: 735e059ec520 | generated_at: 2026-09-22T21:47:00+00:00 -->

# Resume Packet

## Project
**demo-service** — `.`  
branch `claude/agentic-memory-system-mybkpi` · commit `a1e479a` · 24 uncommitted file(s) · handoff: handoff.md (no branch handoff)

## Current Focus
Plain-file portability.

## Next Action
Verify a CLI-less agent can resume from the committed files.

## Active Decisions
- `dec_20260610_markdown-source-of-truth` — A read-only cloud agent can read plain files without the CLI.

## Failed Attempts To Avoid
- `att_20260612_sqlite-store` — do not retry: do not use a binary store unless plain-file export is automatic and reviewed

## Known Traps
_(none recorded)_

## Open Questions / Blockers
_(none open)_

## Likely Relevant Files
- continuity.py
- .project-memory/generated/resume-packet.md

## Verifications
_(none recorded)_

## Verification Commands
- python -m unittest discover -s tests

## Stale / Risk Warnings
_(ages below are measured; the cutoff is 21 days — set with `--stale-days`)_
- ⚠ handoff is 94 day(s) old.
- active decision dec_20260610_markdown-source-of-truth is 104 days old with no update — is this still true?
- current.md has not changed in 88 days; is Current Focus still true?
