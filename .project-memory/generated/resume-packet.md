<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: 5210aa8 | inputs_hash: 023cf80b2792 | generated_at: 2026-09-27T04:58:56+00:00 -->
<!-- view: markdown | budget: 3303/5000 approx_tokens (approx-tokens/2: ceil(ASCII chars / 4) + 1 per non-ASCII char — a heuristic, not a model tokenizer) | rules: portable -->

# Resume Packet

## Project
**breadcrumbs** — `.`  
branch `claude/new-session-9f1k6i` · commit `5210aa8` · 10 uncommitted file(s) · handoff: handoffs/claude-new-session-9f1k6i-e54e91.md

## Current Focus
Stabilization per the 2026-09-26 audit roadmap (WP00-05 done; WP06 awaiting review)

## Next Action
WP10 is at review_required (commits 725eb76, 5210aa8 release gate). Wait for operator approval; then mark WP10 completed in the tracker and start the next package in the roadmap's single-agent order (WP11).

## Active Decisions
- `dec_20260927_a-trap-naming-the-exact-command-floors-read-first-prompts` — Audit F09/F10: memory vanished above 500 records and for prompts under 12 characters, and npm test got PROCEED from a trap about npm test.
- `dec_20260927_evals-score-delivered-context-and-critical-cases` — Audit F19: a known false-safe (npm test -> PROCEED) sat inside an accepted baseline with CI green, and ranking metrics did not describe what readers receive.
- `dec_20260927_transcript-mining-uses-a-byte-cursor-carried-calls` — Audit F02: an entry count over a sliding 8 MB tail froze once transcripts outgrew it, lost cross-firing call/result pairs, and discarded capped or failed candidates silently.
- `dec_20260927_packets-are-bounded-on-the-delivered-view-and-promoted` — Audit F14: the bound covered lists only (7,333 tokens under a 5,000 ceiling). F13: a promoted decision vanished from every packet when CLAUDE.md was gone or unread by the consumer. Promotion is an extra delivery channel, not a reason for memory to disappear.
- `dec_20260927_projections-are-stamped-from-a-verified-snapshot` — Audit F07/F11/F12: a stamp taken after the read certified omitted records; an unusable pre-filter silenced real hazards; a size/mtime shortcut made indexed search diverge from the full scan. Re-hashing costs ~17 ms at 1000 records; the unverified hook path costs ~40-90 ms, never silence.
- `dec_20260926_the-2026-09-26-audit-roadmap-is-the-plan-of-record` — The audit evidence is only useful if it stays exactly what was reviewed. Reformatting the scripts would break the checksums. Each package's regressions belong in ordinary tests when that package lands, not in the probe script.
- `dec_20260924_phases-0-6-ship-together-as-0-3-0-not-the-roadmap-s-per` — No per-phase release was ever cut. The next minor after 0.2.0 is the honest number for a schema 1->4 jump, and cli.py already said the guard matcher changed in 0.3.0. Numbering it 0.9.0 would imply six releases that never existed.
- `dec_20260923_retrieval-changes-are-measured-by-evals-run-py-against` — A ranking regression is invisible to unit tests. Building stores through the CLI keeps the eval honest to the current writers.
- `dec_20260922_the-user-pre-approves-store-migrations-of-this-repo-s-own` — The user said (2026-09-22): 'I approve any migration.' A crumb migrate of this repo's own store may proceed without asking again; still run guard, back up (migrate does), validate after, and commit the result.
- `dec_20260922_multi-agent-safety-branch-handoffs-one-command-level-store` — Every writer reindexes, so per-writer locking would take the lock many times per command and still not cover multi-writer sequences like capture. Hooks must never block the host. A feature branch's next action must not be what a session on main reads first.
- `dec_20260922_promotion-to-claude-md-or-agents-md-is-cli-only-and-writes` — An agent writing its own permanent instructions through a tool call is the persistence step of a prompt injection. A separate block keeps the signpost's bloat and removal semantics. A retired rule must not stay in the file every session loads, so demotion cannot be a second manual step.
- `dec_20260922_near-duplicate-similarity-needs-three-shared-stems-and-caps` — Records about the same files are related (related.json says so), not duplicates. A refusal that fires on related work teaches agents to pass --allow-duplicate by reflex.
- `dec_20260922_lifecycle-decay-hides-and-asks-it-never-deletes-a-claim` — Deciding that a claim is wrong is the author's job, not a heuristic's. A status written on a clock needs a writer running on a clock and churns committed files; a computed flag does neither.
- `dec_20260922_the-search-index-is-a-plain-sqlite-inverted-index-of-our` — Equivalence is the one rule: indexed search must return exactly the full scan's matches and scores. Our own stems make that true by construction. Computing ubiquity over only the narrowed set changed scores. _inputs_hash reads every file, which cost as much as the scan the index saves.
- `dec_20260922_related-records-use-a-pure-overlap-score-so-the-committed` — A committed projection that differs per machine churns on every reindex and every commit.
_(… 23 more omitted to stay within the per-section cap)_

## Failed Attempts To Avoid
_(none recorded)_

## Known Traps
- trap_a-bare-n-in-a-commit-message-links-an-issue-but-never: A bare (#N) in a commit message links an issue but never closes it
- trap_a-hand-written-version-literal-in-prose-drifts-silently: A hand-written version literal in prose drifts silently
- trap_a-record-s-remedy-fields-are-mined-for-file-paths: A record's remedy fields are mined for file paths and become its blast radius
- trap_eval-baseline-after-retrieval-change: A retrieval change fails the evals CI job and test_evals until the baseline is rewritten
- trap_guard-exit-code-in-ci: A CI step that calls crumb guard dies on guard's own verdict exit code
- trap_hand-tagged-releases: Never create a git tag or GitHub Release by hand
- trap_the-mcp-surface-of-0-1-11-was-never-exercised-the-field: The MCP surface of 0.1.11 was never exercised: the field audit had to kill the server to allow the upgrade, so no mcp__breadcrumbs__* tool ran on that release at all

## Open Questions / Blockers
- Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first.

## Inbox (unsorted, expires)
_(candidates, not findings — promote with `crumb inbox promote <id> <type>` or drop with `crumb inbox drop <id>`)_
- `jot_20260922_phase-1-wm-14-s-transcript-miner-must-write-via-inbox-34ba` (4d, agent) Phase 1 WM-14's transcript miner must write via inbox.write_jot(source='transcript', local=True) — the private/inbox sp…

## Likely Relevant Files
- breadcrumbs/retrieval.py
- breadcrumbs/cli.py
- docs/reviews/2026-09-27-breadcrumbs-wp10/README.md
- evals/run.py
- evals/critical/cases.yml
- docs/reviews/2026-09-27-breadcrumbs-wp18/README.md
- breadcrumbs/transcript.py
- breadcrumbs/hooks_common.py
- docs/reviews/2026-09-27-breadcrumbs-wp09/README.md
- breadcrumbs/promote.py
- docs/reviews/2026-09-27-breadcrumbs-wp08/README.md
- breadcrumbs/snapshots.py
- breadcrumbs/projections.py
- docs/reviews/2026-09-27-breadcrumbs-wp07/README.md
- docs/reviews/2026-09-26-breadcrumbs-audit-and-roadmap.md
- docs/reviews/2026-09-26-breadcrumbs-wp00-baseline/baseline.json
- CHANGELOG.md
- docs/roadmap-working-memory.md
- breadcrumbs/__init__.py
- evals/baseline.json
_(… 15 more omitted to stay within the per-section cap)_

## Verifications
- `ver_20260817_f-5-guard-reprints-the-staleness-block-on-every-call` — F-5 (guard reprints the staleness block on every call) is already fixed on main and in 0.1.11: **not_applicable** · runtime
- `ver_20260925_ci-mcp-job-fails-stale-pinned-tool-resource-counts-in-ci` — CI mcp job fails: stale pinned tool/resource counts in ci.yml: **fixed** · test
- `ver_20260923_relevance-evals-hold-the-committed-baseline-prompt-p-5-0-66` — Relevance evals hold the committed baseline (prompt P@5 0.66, R@5 0.87, 1 reject hit): **fixed**
- `ver_20260922_phase-5-of-the-working-memory-roadmap-wm-50-to-wm-52` — Phase 5 of the working-memory roadmap (WM-50 to WM-52) is implemented and green: **fixed** · test
- `ver_20260922_phase-4-of-the-working-memory-roadmap-wm-40-to-wm-43` — Phase 4 of the working-memory roadmap (WM-40 to WM-43) is implemented and green: **fixed** · test
- `ver_20260922_phase-3-of-the-working-memory-roadmap-wm-30-to-wm-35` — Phase 3 of the working-memory roadmap (WM-30 to WM-35) is implemented and green: **fixed** · test
- `ver_20260922_phase-2-of-the-working-memory-roadmap-wm-20-to-wm-25` — Phase 2 of the working-memory roadmap (WM-20 to WM-25) is implemented and green: **fixed** · test
- `ver_20260922_phase-1-of-the-working-memory-roadmap-wm-10-to-wm-16` — Phase 1 of the working-memory roadmap (WM-10 to WM-16: capture hooks and the transcript miner): **fixed** · test
- `ver_20260922_phase-0-of-the-working-memory-roadmap-wm-01-migration-wm-02` — Phase 0 of the working-memory roadmap (WM-01 migration, WM-02 usage, WM-03 inbox): **fixed** · test
- `ver_20260905_the-16-findings-of-the-0-1-11-crumb-kit-field-review-re` — the 16 findings of the 0.1.11 crumb-kit field review, re-checked against 0.1.12: **fixed** · static
- `ver_20260903_resume-s-possible-drift-line-fires-on-incidental-two-word` — resume's possible-drift line fires on incidental two-word overlap and version fragments: **fixed** · test
- `ver_20260818_readme-status-blurb-no-longer-hard-codes-a-package-version` — README Status blurb no longer hard-codes a package version: **fixed** · static
_(… 8 more omitted to stay within the per-section cap)_

## Verification Commands
- python -m unittest tests.test_handoffs tests.test_lock tests.test_scope
- python -m unittest tests.test_promote
- python -m unittest tests.test_lifecycle
- python -m unittest tests.test_searchindex
- python -m unittest tests.test_blockfiles
- python -m unittest tests.test_transcript
- python -m unittest tests.test_hooks_phase1
- python -m unittest tests.test_usage
- python -m unittest tests.test_inbox
- tests/test_secret_precision.py
- tests/test_guard_precision.py
- tests/test_sections.py
_(… 7 more omitted to stay within the per-section cap)_

## Stale / Risk Warnings
_(ages below are measured; the cutoff is 21 days — set with `--stale-days`)_
- handoff is 0 day(s) old, written 0 commit(s) behind current HEAD.
- active decision dec_20260905_a-read-only-action-caps-at-read-first-and-entropy-warns is 22 days old with no update — is this still true?
- active decision dec_20260905_path-extraction-is-structural-and-a-mined-path is 22 days old with no update — is this still true?
- active decision dec_20260905_a-wrong-set-heading-parks-content-it-never-discards-the-call is 22 days old with no update — is this still true?
- active decision dec_20260903_branch-mismatch-is-judged-on-whether-the-file-reached-head is 24 days old with no update — is this still true?
- active decision dec_20260818_repo-presentation-is-a-release-artifact-no-hand-pinned is 39 days old with no update — is this still true?
- active decision dec_20260818_hook-guard-never-overrides-the-session-s-permission-mode is 39 days old with no update — is this still true?
- active decision dec_20260818_blast-radius-is-scored-separately-from-retrieval-overlap is 39 days old with no update — is this still true?
- active decision dec_20260817_guard-verdicts-are-capped-by-record-stance-not-by-retrieval is 41 days old with no update — is this still true?
- active decision dec_20260816_questions-get-their-own-status-vocabulary-not-the-record-one is 42 days old with no update — is this still true?
- active decision dec_20260816_traps-carry-a-lifecycle-status-and-mark-status-resolves-them is 42 days old with no update — is this still true?
- active decision dec_20260815_crumb-guard-exits-verdict-mapped-codes-0-10-15-20 is 42 days old with no update — is this still true?
- active decision dec_20260815_guard-verdict-floors-require-file-tag-specificity-keyword is 42 days old with no update — is this still true?
- active decision dec_20260815_pypi-trusted-publisher-must-be-re-pointed-after-a-repo is 43 days old with no update — is this still true?
- active decision dec_20260815_cut-0-1-10-as-the-agent-authorship-release is 43 days old with no update — is this still true?
- active decision dec_20260815_the-tool-s-own-repo-commits-its-own-memory-store is 43 days old with no update — is this still true?
- active decision dec_20260815_stop-hook-extraction-turn-makes-the-agent-the-memory-author is 43 days old with no update — is this still true?
- active decision dec_20260815_guard-folds-morphology-with-a-deterministic-fixpoint is 43 days old with no update — is this still true?
- open question "Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first." has been open 43 days — did this ever get resolved?
