<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: 7edf192 | inputs_hash: 3982d863357d | generated_at: 2026-10-01T21:38:05+00:00 -->
<!-- view: markdown | budget: 3558/5000 approx_tokens (approx-tokens/2: ceil(ASCII chars / 4) + 1 per non-ASCII char — a heuristic, not a model tokenizer) | rules: portable -->

# Resume Packet

## Project
**breadcrumbs** — `.`  
branch `claude/zealous-hamilton-ba7e5m` · commit `7edf192` · 11 uncommitted file(s) · handoff: handoffs/claude-zealous-hamilton-ba7e5m-2a7c4d.md

## Current Focus
Stabilization per the 2026-09-26 audit roadmap (WP00-05 done; WP06 awaiting review)

## Next Action
Operator reviews docs/reviews/2026-10-01-dowhat-field-report-plan.md and answers D1b (should the first --next append set requires: next-action-log?). Then start Release 1 item 1 (capture --next appends; --replace saves what it replaced).

## Active Decisions
- `dec_20260928_the-native-full-suite-runs-on-main-weekly-and-on-demand` — Keeps per-push cost low while main and a weekly run still see platform regressions; run it by hand on a branch before merging platform-sensitive changes.
- `dec_20260928_store-relative-paths-are-posix-and-line-endings` — A store is shared across machines and platforms; a value that differs by OS makes stamps stale everywhere and made rollback and the write gate silently wrong on Windows.
- `dec_20260927_transports-reach-the-store-through-breadcrumbs-service` — CLI, MCP and hooks call service functions (record, mark_status, search, guard, resume_packet, prompt_lookup, admit) inside service.active(ctx); wording, exit codes and envelopes stay in the adapters. Parser lives in cli_parser.py. Aliases and clock are per-thread scoped state. Any further move out o… [excerpt: 300 of 379 chars; full text: crumb show dec_20260927_transports-reach-the-store-through-breadcrumbs-service]
- `dec_20260927_pair-generation-uses-postings-and-exact-prefix-filtering` — related, conflicts and the near-duplicate sweep score only pairs that can reach their thresholds; pairwise versions stay as test oracles. Past RELATED_PAIR_BUDGET the related map reports degraded (audit: related-degraded) instead of skipping. Parses are shared per operation via cli.operation() keyed… [excerpt: 300 of 332 chars; full text: crumb show dec_20260927_pair-generation-uses-postings-and-exact-prefix-filtering]
- `dec_20260927_review-profiles-solo-by-default-team-makes-agent-written` — Proportional: ordinary capture never waits for a person; only the writes that make memory authoritative are gated. Opt-in semantics use requires: instead of a store-wide schema bump.
- `dec_20260927_pre-1-0-releases-bump-the-minor-for-breaking-changes-newer` — The lock is the one place every committed write already passes, and every caller already handles StoreLocked, so the refusal needs no per-writer code. Released readers (<=0.3.1) cannot be changed, so semantic changes must also be designed to fail safe for them (schema bump, meaning kept out of field… [excerpt: 300 of 456 chars; full text: crumb show dec_20260927_pre-1-0-releases-bump-the-minor-for-breaking-changes-newer]
- `dec_20260927_nothing-inside-the-store-may-be-a-link-record-text-reaches` — No links at all is the simplest rule to audit and nothing in the tool creates one. Descriptor-relative no-follow opens close the check/use race on POSIX. Raising a sanitized PermissionError, rather than returning placeholder text, keeps a refusal from being mistaken for content. Batching reads per d… [excerpt: 300 of 356 chars; full text: crumb show dec_20260927_nothing-inside-the-store-may-be-a-link-record-text-reaches]
- `dec_20260927_usage-counts-emitted-ids-from-append-only-events-the-latest` — A count must mean the host received the record; anything else inflates decay/promotion signals. Event files make acknowledged increments durable without a shared read-modify-write, and the fold's folded_last makes a crash between write and delete harmless. Telemetry never takes the store lock, so it… [excerpt: 300 of 322 chars; full text: crumb show dec_20260927_usage-counts-emitted-ids-from-append-only-events-the-latest]
- `dec_20260927_the-guard-pre-filter-is-a-strict-superset-of-what-full` — Audit F11/WP11: the traps-only pre-filter made the hook silent on 27 of 193 warnings full guard gives on the eval stores; the superset costs ~0.3 ms median on routine commands.
- `dec_20260927_a-trap-naming-the-exact-command-floors-read-first-prompts` — Audit F09/F10: memory vanished above 500 records and for prompts under 12 characters, and npm test got PROCEED from a trap about npm test.
- `dec_20260927_evals-score-delivered-context-and-critical-cases` — Audit F19: a known false-safe (npm test -> PROCEED) sat inside an accepted baseline with CI green, and ranking metrics did not describe what readers receive.
- `dec_20260927_transcript-mining-uses-a-byte-cursor-carried-calls` — Audit F02: an entry count over a sliding 8 MB tail froze once transcripts outgrew it, lost cross-firing call/result pairs, and discarded capped or failed candidates silently.
- `dec_20260927_packets-are-bounded-on-the-delivered-view-and-promoted` — Audit F14: the bound covered lists only (7,333 tokens under a 5,000 ceiling). F13: a promoted decision vanished from every packet when CLAUDE.md was gone or unread by the consumer. Promotion is an extra delivery channel, not a reason for memory to disappear.
- `dec_20260927_projections-are-stamped-from-a-verified-snapshot` — Audit F07/F11/F12: a stamp taken after the read certified omitted records; an unusable pre-filter silenced real hazards; a size/mtime shortcut made indexed search diverge from the full scan. Re-hashing costs ~17 ms at 1000 records; the unverified hook path costs ~40-90 ms, never silence.
- `dec_20260927_installed-hook-launchers-never-pass-a-failure-through` — A hook we install must never be able to veto the host by failing; a real veto is JSON on stdout. Version skew between an installed hook config and a CLI on PATH is normal (global pipx vs project venv).
_(… 33 more omitted to stay within the per-section cap)_

## Failed Attempts To Avoid
_(none recorded)_

## Known Traps
- trap_a-bare-n-in-a-commit-message-links-an-issue-but-never: A bare (#N) in a commit message links an issue but never closes it
- trap_a-hand-written-version-literal-in-prose-drifts-silently: A hand-written version literal in prose drifts silently
- trap_a-record-s-remedy-fields-are-mined-for-file-paths: A record's remedy fields are mined for file paths and become its blast radius
- trap_eval-baseline-after-retrieval-change: A retrieval change fails the evals CI job and test_evals until the baseline is rewritten
- trap_guard-exit-code-in-ci: A CI step that calls crumb guard dies on guard's own verdict exit code
- trap_hand-tagged-releases: Never create a git tag or GitHub Release by hand
- trap_linux-cannot-show-a-windows-path-separator-bug: Linux cannot show a Windows path-separator bug
- trap_the-mcp-surface-of-0-1-11-was-never-exercised-the-field: The MCP surface of 0.1.11 was never exercised: the field audit had to kill the server to allow the upgrade, so no mcp__breadcrumbs__* tool ran on that release at all

## Open Questions / Blockers
- Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first.

## Inbox (unsorted, expires)
_(candidates, not findings — promote with `crumb inbox promote <id> <type>` or drop with `crumb inbox drop <id>`)_
- `jot_20260922_phase-1-wm-14-s-transcript-miner-must-write-via-inbox-34ba` (9d, agent) Phase 1 WM-14's transcript miner must write via inbox.write_jot(source='transcript', local=True) — the private/inbox sp…

## Likely Relevant Files
- .github/workflows/ci.yml
- tests/test_platform_portability.py
- breadcrumbs/service.py
- tests/test_application_parity.py
- breadcrumbs/related.py
- breadcrumbs/lifecycle.py
- breadcrumbs/admission.py
- tests/test_admission_policy.py
- docs/reviews/2026-09-27-breadcrumbs-wp14/README.md
- docs/compatibility.md
- breadcrumbs/compat.py
- tests/test_store_upgrade_contract.py
- docs/reviews/2026-09-27-breadcrumbs-wp21/README.md
- breadcrumbs/path_policy.py
- breadcrumbs/safetext.py
- tests/test_path_containment.py
- docs/reviews/2026-09-27-breadcrumbs-wp13/README.md
- breadcrumbs/usage.py
- breadcrumbs/hooks_prompt.py
- tests/test_emission_accounting.py
_(… 36 more omitted to stay within the per-section cap)_

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
- active decision dec_20260905_a-read-only-action-caps-at-read-first-and-entropy-warns is 26 days old with no update — is this still true?
- active decision dec_20260905_path-extraction-is-structural-and-a-mined-path is 26 days old with no update — is this still true?
- active decision dec_20260905_a-wrong-set-heading-parks-content-it-never-discards-the-call is 26 days old with no update — is this still true?
- active decision dec_20260903_branch-mismatch-is-judged-on-whether-the-file-reached-head is 28 days old with no update — is this still true?
- active decision dec_20260818_repo-presentation-is-a-release-artifact-no-hand-pinned is 44 days old with no update — is this still true?
- active decision dec_20260818_hook-guard-never-overrides-the-session-s-permission-mode is 44 days old with no update — is this still true?
- active decision dec_20260818_blast-radius-is-scored-separately-from-retrieval-overlap is 44 days old with no update — is this still true?
- active decision dec_20260817_guard-verdicts-are-capped-by-record-stance-not-by-retrieval is 45 days old with no update — is this still true?
- active decision dec_20260816_questions-get-their-own-status-vocabulary-not-the-record-one is 46 days old with no update — is this still true?
- active decision dec_20260816_traps-carry-a-lifecycle-status-and-mark-status-resolves-them is 46 days old with no update — is this still true?
- active decision dec_20260815_crumb-guard-exits-verdict-mapped-codes-0-10-15-20 is 47 days old with no update — is this still true?
- active decision dec_20260815_guard-verdict-floors-require-file-tag-specificity-keyword is 47 days old with no update — is this still true?
- active decision dec_20260815_pypi-trusted-publisher-must-be-re-pointed-after-a-repo is 47 days old with no update — is this still true?
- active decision dec_20260815_cut-0-1-10-as-the-agent-authorship-release is 47 days old with no update — is this still true?
- active decision dec_20260815_the-tool-s-own-repo-commits-its-own-memory-store is 47 days old with no update — is this still true?
- active decision dec_20260815_stop-hook-extraction-turn-makes-the-agent-the-memory-author is 47 days old with no update — is this still true?
- active decision dec_20260815_guard-folds-morphology-with-a-deterministic-fixpoint is 47 days old with no update — is this still true?
- open question "Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first." has been open 47 days — did this ever get resolved?
