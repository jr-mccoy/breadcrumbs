# Project Handoff

_Last updated: 2026-10-01T23:54:12+00:00_
_Branch: claude/zealous-hamilton-ba7e5m_
_Commit: 54eeaab_

## Current Focus
crumb-kit 0.4.0 is on PyPI. 0.5.0 (the DoWhat field-report fixes: Next Action log, migration safety, Stop-hook session cursor, guard rework and speed, repair/rename/handoff trim) is version-bumped and merged to main, ready to publish. docs/reviews/2026-10-01-dowhat-field-report-plan.md is the record; do not redo it.

## Next Action
### 2026-10-01 · `54eeaab`
Publish 0.5.0: Actions -> release -> Run workflow on main, mode dry-run, then mode publish (RELEASING.md). Before publishing, run the native Windows job of the ci workflow on main to confirm the long-path migration backup/restore, UTF-8 output under Git Bash and `crumb mcp register --local`, which were only tested on Linux.

### Earlier, as written
A person reviews the work packages the tracker marks `review_required`, then merges the branch to main. The branch already carries the 0.4.0 bump (version, CHANGELOG, compatibility row); the release runs through release.yml with a dry-run first (RELEASING.md). docs/releases/reliability-release-checklist.md lists the gates, exclusions and the operator's steps; read the native-full jobs on the merge commit before publishing. After the merge, reconcile this file on main (docs/operator-guide.md §6).

## Blockers / Open Questions
Publishing 0.5.0 needs the operator: release.yml runs only from main and only by hand.

## Active Decisions To Respect
See the resume packet (`crumb resume`); the durable decisions are the records, not this file.

## Failed Attempts To Avoid


## Known Traps
Never tag or create a GitHub Release by hand (CLAUDE.md); release.yml owns both.

## Likely Relevant Files
docs/reviews/2026-09-26-breadcrumbs-work-packages.json, docs/releases/reliability-release-checklist.md, RELEASING.md, docs/compatibility.md

## Verification Commands
python -m unittest discover -s tests -p "test_*.py"; python evals/run.py --release

## Stale If
the branch has merged and 0.4.0 is released, or the tracker's statuses have changed.
