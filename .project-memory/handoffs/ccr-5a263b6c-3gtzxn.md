# Project Handoff

_Last updated: 2026-11-13T05:05:31+00:00_
_Branch: ccr-5a263b6c-3gtzxn_
_Commit: b8c6066_

## Current Focus
0.6.2 is released. docs/reviews/2026-11-13-system-review.md is a full review of what is broken and what to improve; nothing in it is fixed yet. CI on main is red, which blocks the next publish.

## Next Action
### 2026-11-13 · `b8c6066`
Work docs/reviews/2026-11-13-system-review.md in the order of its section 6. First: pin the ci.yml test job's Python 3.9 leg to ubuntu-24.04 (ubuntu-latest is 26.04 and has no 3.9; scheduled CI red since 2026-11-02, so mode publish is refused), or decide to drop 3.9. Second: fix crumb rename (it deletes the record; trap_crumb-rename-deletes-the-record), the journal-discard window in mutations.py and prune sessions ordering. Third: cap the SessionStart packet at 10,000 characters and resolve the store root from CLAUDE_PROJECT_DIR or by walking up from cwd.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
