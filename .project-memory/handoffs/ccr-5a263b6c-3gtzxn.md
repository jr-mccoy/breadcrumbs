# Project Handoff

_Last updated: 2026-11-16T13:05:28+00:00_
_Branch: ccr-5a263b6c-3gtzxn_
_Commit: 1420040_

## Current Focus
Review 2026-11-13 items 1 to 7 are done on ccr-5a263b6c-3gtzxn and pushed; not yet merged or released (next: 0.7.0).

## Next Action
### 2026-11-16 · `1420040`
Unchanged from aeadbcb: decide the guard stall (q_should-guard-stop-escalating-a-plain-language-pl-348193), then merge ccr-5a263b6c-3gtzxn to main, confirm ci, release 0.7.0. Item 7's open points are in docs/reviews/2026-11-13-system-review.md section 6.

### 2026-11-16 · `251655b`
Review items 1 to 7 are done on ccr-5a263b6c-3gtzxn. Decide on the guard stall (open question q_should-guard-stop-escalating-a-plain-language-pl-348193), then merge to main, confirm ci, and release 0.7.0. Open from item 7 by design: R7 identifier parts (needs a lookup-only match), four hook design points (SessionEnd, launcher re-runs, extraction via additionalContext, Windows without Git Bash), branch protection on main.

### 2026-11-15 · `9cd5b74`
Decide on the guard stall (open question; docs/benchmarks/agent-outcomes.md 'What to do with it' 1-2), then rerun evals/agent_outcomes/run.py --scenarios index-migration. Merge ccr-5a263b6c-3gtzxn to main, confirm ci, release 0.7.0. Remaining review work: the section 3 tables and trap_miner-reads-hook-feedback-as-a-correction.

### 2026-11-14 · `8a6ee60`
Merge ccr-5a263b6c-3gtzxn to main and confirm ci is green there; release 0.7.0 per CLAUDE.md (search-index format is now 3: the first reindex after upgrade rebuilds it). Next review work: item 6 (agent-outcome eval, review section 5.1), the section 3 tables, and trap_miner-reads-hook-feedback-as-a-correction.

### 2026-11-14 · `10f8a9d`
Merge ccr-5a263b6c-3gtzxn to main and confirm ci is green there (6f39bbb fixed a format failure in 973bbcb); release 0.7.0 per CLAUDE.md. Next review work: item 5 in docs/reviews/2026-11-13-system-review.md section 6 (guard here-string and redirect parsing, then the allowlist and wrapper redesign with property tests), and trap_miner-reads-hook-feedback-as-a-correction.

### 2026-11-14 · `e3f6036`
Merge ccr-5a263b6c-3gtzxn (head after this capture) to main; confirm ci is green there; release 0.7.0 per CLAUDE.md. Then review item 4 (docs/reviews/2026-11-13-system-review.md section 6), and look at trap_miner-reads-hook-feedback-as-a-correction.

### 2026-11-14 · `973bbcb`
Merge ccr-5a263b6c-3gtzxn to main and confirm ci is green there. Then release 0.7.0: bump __version__, date the [Unreleased] CHANGELOG section as 0.7.0, add the docs/compatibility.md section 3 row, dry-run, publish. Next review item is 4 (docs/reviews/2026-11-13-system-review.md section 6): close the gate (frontmatter line separators, memory_note supersede under propose, secret-scan patterns, jot evidence, invisible characters).

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
