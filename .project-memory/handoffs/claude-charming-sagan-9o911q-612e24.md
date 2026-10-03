# Project Handoff

_Last updated: 2026-10-03T17:53:41+00:00_
_Branch: claude/charming-sagan-9o911q_
_Commit: 25bf611_

## Current Focus
crumb-kit 0.5.0 is on PyPI. 0.6.0 (the DoWhat retest fixes: guard verdicts and speed, machine-local guard pre-filter, `min_crumb_version`, plus the Stop-hook snapshot settle fix) is version-bumped on branch ccr-e63a7edc-aluyzm, ready to merge and publish. docs/reviews/2026-10-02-dowhat-retest-plan.md and dec_20261002_a-head-that-moved-only-by-memory-store-commits-is-not-new are the record; do not redo them.

## Next Action
### 2026-10-03 · `25bf611`
DoWhat 0.6.0 retest fixes are on claude/charming-sagan-9o911q (plan: docs/reviews/2026-10-03-dowhat-0.6.0-retest-plan.md, CHANGELOG [Unreleased], proposed 0.6.1). Waiting on the operator: the launcher DECIDE (item 2) and the go to release. To release: bump __version__ to 0.6.1, move [Unreleased] to [0.6.1] with the date, add the docs/compatibility.md section 3 row, merge to main, run release.yml dry-run then publish. Then remeasure the hook on Windows with doctor --hook-log.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
