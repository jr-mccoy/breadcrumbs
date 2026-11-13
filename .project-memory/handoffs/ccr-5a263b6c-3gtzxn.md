# Project Handoff

_Last updated: 2026-11-13T14:04:40+00:00_
_Branch: ccr-5a263b6c-3gtzxn_
_Commit: 52d3bfe_

## Current Focus
Review items 1 and 2 are done on ccr-5a263b6c-3gtzxn: Python floor is 3.10, the release CI gate fails closed, and rename / recover / prune sessions no longer lose records. Not yet merged or released; the next release is 0.7.0.

## Next Action
### 2026-11-13 · `52d3bfe`
Merge ccr-5a263b6c-3gtzxn to main and confirm ci is green there (the 3.9 legs are gone). Then release 0.7.0: bump __version__, date the [Unreleased] CHANGELOG section as 0.7.0, add the docs/compatibility.md section 3 row, dry-run, publish. After that, item 3 of docs/reviews/2026-11-13-system-review.md section 6: cap the SessionStart packet at 10,000 characters and resolve the store root from CLAUDE_PROJECT_DIR or by walking up from cwd.

### 2026-11-13 · `b8c6066`
Work docs/reviews/2026-11-13-system-review.md in the order of its section 6. First: pin the ci.yml test job's Python 3.9 leg to ubuntu-24.04 (ubuntu-latest is 26.04 and has no 3.9; scheduled CI red since 2026-11-02, so mode publish is refused), or decide to drop 3.9. Second: fix crumb rename (it deletes the record; trap_crumb-rename-deletes-the-record), the journal-discard window in mutations.py and prune sessions ordering. Third: cap the SessionStart packet at 10,000 characters and resolve the store root from CLAUDE_PROJECT_DIR or by walking up from cwd.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
