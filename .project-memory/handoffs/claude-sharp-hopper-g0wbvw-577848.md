# Project Handoff

_Last updated: 2026-10-02T04:33:08+00:00_
_Branch: claude/sharp-hopper-g0wbvw_
_Commit: 06932b3_

## Current Focus
crumb-kit 0.4.0 is on PyPI. 0.5.0 (the DoWhat field-report fixes: Next Action log, migration safety, Stop-hook session cursor, guard rework and speed, repair/rename/handoff trim) is version-bumped and merged to main, ready to publish. docs/reviews/2026-10-01-dowhat-field-report-plan.md is the record; do not redo it.

## Next Action
### 2026-10-02 · `06932b3`
Publish 0.6.0 when the operator says so: bump __version__ to 0.6.0, move CHANGELOG [Unreleased] to a [0.6.0] heading, add the docs/compatibility.md section 3 row, merge to main, then release.yml dry-run and publish. Before running crumb migrate on this repo's or DoWhat's store, upgrade every machine and the cloud setup: migrate sets min_crumb_version 0.5.0 with requires: min-crumb-version, so 0.4.x and 0.5.0 then refuse to write. On Windows, read crumb doctor --hook-log's p50 phases (import_ms, git_ms) to settle decision D7.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
