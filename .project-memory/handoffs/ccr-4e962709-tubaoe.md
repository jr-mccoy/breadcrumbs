# Project Handoff

_Last updated: 2026-10-03T13:07:58+00:00_
_Branch: ccr-4e962709-tubaoe_
_Commit: 7d941f4_

## Current Focus
crumb-kit 0.5.0 is on PyPI. 0.6.0 (the DoWhat retest fixes: guard verdicts and speed, machine-local guard pre-filter, `min_crumb_version`, plus the Stop-hook snapshot settle fix) is version-bumped on branch ccr-e63a7edc-aluyzm, ready to merge and publish. docs/reviews/2026-10-02-dowhat-retest-plan.md and dec_20261002_a-head-that-moved-only-by-memory-store-commits-is-not-new are the record; do not redo them.

## Next Action
### 2026-10-03 · `7d941f4`
2.2 git half is on branch ccr-4e962709-tubaoe (breadcrumbs/git.py). Next for 2.2: one timestamp parser (cli._parse_iso vs validation.parse_timestamp), one lenient reader, path_policy for store-relative POSIX paths, one shell tokenizer; then 2.1 seam 1 (hooks_stop). 0.6.0 is still unpublished: run the release workflow on main (dry-run, then publish) after checking the native-full Windows job.

## Blockers / Open Questions


## Active Decisions To Respect


## Failed Attempts To Avoid


## Known Traps


## Likely Relevant Files


## Verification Commands


## Stale If
