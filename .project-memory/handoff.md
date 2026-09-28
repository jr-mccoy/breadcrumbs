# Project Handoff

_Last updated: 2026-09-28T02:20:00+00:00_
_Branch: claude/new-session-9f1k6i_
_Commit: 529356e_

## Current Focus
crumb-kit 0.3.1 is released (2026-09-27). Phases 0–6 of docs/roadmap-working-memory.md shipped in 0.3.0; do not redo them. The audit remediation (docs/reviews/2026-09-26-breadcrumbs-audit-and-roadmap.md, work packages WP00–WP22) is implemented on branch claude/new-session-9f1k6i. The tracker, docs/reviews/2026-09-26-breadcrumbs-work-packages.json, is authoritative for each package's status; each has a review record under docs/reviews/2026-09-27-breadcrumbs-wpNN/.

## Next Action
A person reviews the work packages the tracker marks `review_required`, then merges the branch to main. The release is 0.4.0 (docs/compatibility.md: pre-1.0, minor = breaking), run through release.yml with a dry-run first (RELEASING.md). docs/releases/reliability-release-checklist.md lists the gates, exclusions and the operator's steps; read the native-full jobs on the merge commit before publishing. After the merge, reconcile this file on main (docs/operator-guide.md §6).

## Blockers / Open Questions
Merging to main and publishing 0.4.0 need the operator's approval.

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
