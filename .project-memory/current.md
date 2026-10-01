# Current State

_What matters right now. Lifespan: days to ~2 weeks. Keep it short and true._

## Current Focus
crumb-kit 0.4.0 is on PyPI. 0.5.0 (the DoWhat field-report fixes: Next Action log, migration safety, Stop-hook session cursor, guard rework and speed, repair/rename/handoff trim) is version-bumped and merged to main, ready to publish. docs/reviews/2026-10-01-dowhat-field-report-plan.md is the record; do not redo it.

## Recently Changed
- 2083046 Plan fixes for the DoWhat field report on 0.4.0
- 295c6db Merge pull request #55 from jr-mccoy/claude/new-session-9f1k6i
- cb327eb Release checklist: reference hashes for the 0.4.0 artifacts
- 8242861 Release 0.4.0: bump the version (operator's request)
- 5e04468 WP22: release checklist prepared; nothing released
- 529356e WP17: the native full suite is green on Windows and macOS (CI run 248)
- a8c3960 CI: run the native full suite on main, weekly and on demand only
- 9b55822 WP17, WP19, WP20: review records, results and tracker entries
- f528a24 WP17: the write gate compares POSIX paths too (regression from 48bc814)
- 68c8075 WP20: onboarding and operation, documented and checked
- 9366074 WP19: review record for the continuity replays
- 48bc814 WP17: fix what the first native full-suite run found on macOS and Windows
- e835448 CI: bound the native job's non-gating full suite and make it verbose
- 6157248 verify: a verification's expiry and created_at are one instant
- fb5b57a WP19 (in progress): a rerun must reproduce the published replay verdicts
- 5c60679 WP17 (in progress): track the Windows process tree while a check runs
- 1451a1f WP19 (in progress): two-session continuity replays, results, demo
- 3552a1d WP17 (in progress): report job termination and the sweep in containment
- e8268ec Parity golden pins $USER; Windows replay cleanup sweeps descendants
- 5e01027 WP17 (in progress): compatibility matrix, MCP contract docs, behavior evidence

_Prefill window: last 20 commits (`ecf0245`..HEAD). The last session record is at `22907a1`, 38 commits back — too far to attribute to one session, so the older commits are not counted here._

## Watch Out For
