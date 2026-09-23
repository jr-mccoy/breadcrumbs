<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: 433af7f | inputs_hash: 922e55e6c662 | generated_at: 2026-09-23T02:51:21+00:00 -->

# Resume Packet

## Project
**breadcrumbs** — `.`  
branch `claude/agentic-memory-system-mybkpi` · commit `433af7f` · clean · handoff: handoffs/claude-agentic-memory-system-mybkpi-f4c610.md

## Current Focus
Phases 0 and 1 shipped; Phase 2 (retrieval by relevance) is next

## Next Action
Phase 5 shipped and the repo store is at schema 4. Next: Phase 6 starting with WM-61 (relevance eval harness: evals/, tasks.yml, precision@5/recall, baseline + CI job), then WM-60 (usage --decay) and WM-62 (field-test protocol + hook log). Read roadmap section 0.10 first.

## Landed Since The Handoff Was Written
_(check Current Focus / Next Action against these before redoing work)_
- 433af7f Finish Phase 5 docs; keep the lock through init --force and break stale locks exclusively

## Active Decisions
- `dec_20260922_the-user-pre-approves-store-migrations-of-this-repo-s-own` — The user said (2026-09-22): 'I approve any migration.' A crumb migrate of this repo's own store may proceed without asking again; still run guard, back up (migrate does), validate after, and commit the result.
- `dec_20260922_multi-agent-safety-branch-handoffs-one-command-level-store` — Every writer reindexes, so per-writer locking would take the lock many times per command and still not cover multi-writer sequences like capture. Hooks must never block the host. A feature branch's next action must not be what a session on main reads first.
- `dec_20260922_promotion-to-claude-md-or-agents-md-is-cli-only-and-writes` — An agent writing its own permanent instructions through a tool call is the persistence step of a prompt injection. A separate block keeps the signpost's bloat and removal semantics. A retired rule must not stay in the file every session loads, so demotion cannot be a second manual step.
- `dec_20260922_near-duplicate-similarity-needs-three-shared-stems-and-caps` — Records about the same files are related (related.json says so), not duplicates. A refusal that fires on related work teaches agents to pass --allow-duplicate by reflex.
- `dec_20260922_lifecycle-decay-hides-and-asks-it-never-deletes-a-claim` — Deciding that a claim is wrong is the author's job, not a heuristic's. A status written on a clock needs a writer running on a clock and churns committed files; a computed flag does neither.
- `dec_20260922_the-search-index-is-a-plain-sqlite-inverted-index-of-our` — Equivalence is the one rule: indexed search must return exactly the full scan's matches and scores. Our own stems make that true by construction. Computing ubiquity over only the narrowed set changed scores. _inputs_hash reads every file, which cost as much as the scan the index saves.
- `dec_20260922_related-records-use-a-pure-overlap-score-so-the-committed` — A committed projection that differs per machine churns on every reindex and every commit.
- `dec_20260922_traps-and-questions-are-one-file-each-the-singletons` — Ids are cited in records and commit messages, so they must not change and a dated filename would change them. Pure projections would silently delete blocks that humans, older tool versions or unmigrated branches still append; merging two versions of a trap is a judgement call the tool must not make. Readers return the same dict shapes as before so guard, search, the packet and the prefilter need no change, and results are identical across the migration.
- `dec_20260922_the-transcript-miner-is-deterministic-and-writes-only` — A model-driven miner would be unreproducible, would cost a round trip exactly when a session is ending, and could not run in PreCompact at all — that hook's output never reaches the model. Four narrow rules that are usually right beat one broad rule that cannot be tested. And what a regex noticed is not a finding: the miner cannot tell whether a file was edited four times because it is fragile or because a feature landed in it.
- `dec_20260922_a-subagent-launch-is-guarded-but-capped-at-read-first` — Launching a subagent is not itself irreversible; the subagent's own tool calls hit the same guard, which is where the blast radius actually is. Asking twice for one piece of work is how a gate becomes noise. Both tool names are matched because the tool has carried both across harness versions and a name that never fires costs nothing.
- `dec_20260922_usage-telemetry-counts-surfacings-at-the-call-sites` — Every mutation reindexes and every reindex builds a packet, so counting inside build_resume_packet would have measured writes rather than surfacings. Splitting guard between the command and the hook avoids double-counting every hook advisory, since the hook shows a filtered subset of the same result. Counters in frontmatter would churn every record on every guard call and break 'records are authored facts'; a committed counter file would conflict on every merge.
- `dec_20260922_automatic-memory-writes-land-in-private-inbox-and-earn` — A machine-local jot in a committed projection makes that file differ between two checkouts of one store while _inputs_hash calls both fresh, since the hash cannot read gitignored input without the same problem. That is the cross-machine ping-pong _hashed_input_dirs already exists to prevent. Excluding private jots from the packet keeps the projection machine-independent by construction.
- `dec_20260922_the-working-memory-roadmap-is-the-plan-of-record-for-phases` — Hook facts were verified against the Claude Code hooks reference: PreCompact output never reaches the model (so it mines and marks; SessionStart source=compact re-injects), SubagentStop can block but the plan defers that behind the existing prompt-fatigue open question, UserPromptSubmit additionalContext reaches the model, and the transcript file may lag the current turn. New code goes in new modules; cli.py is 10.7k lines. Usage telemetry is local-only in v1 to avoid churning records and merge conflicts.
- `dec_20260905_a-read-only-action-caps-at-read-first-and-entropy-warns` — Neither is a scoring problem. Overlap is symmetric, so corpus frequency reads as relevance and no weighting fixes a command that cannot do the thing being warned about. And a gate that is hand-overridden every time has stopped being a gate — worse, it punishes exactly the records that cite a concrete path, which are the most useful ones a store has. Both classifications are conservative: an unrecognized action keeps its full verdict, and a structured credential still blocks.
- `dec_20260905_path-extraction-is-structural-and-a-mined-path` — Existence on disk was rejected deliberately: a record citing a file that was since deleted or renamed is often exactly the trap worth raising, and a store must mean the same thing in every checkout that reads it. The shape test rejects 15 of the 16 junk tokens the review names and keeps every real path tested. Tiering is the review's own point 3 — a trap author knows which files their trap is about — without a schema change, because the declaration field already exists in both record types.
_(… 15 more omitted to stay within the per-section cap)_

## Failed Attempts To Avoid
_(none recorded)_

## Known Traps
- trap_a-bare-n-in-a-commit-message-links-an-issue-but-never: A bare (#N) in a commit message links an issue but never closes it
- trap_a-hand-written-version-literal-in-prose-drifts-silently: A hand-written version literal in prose drifts silently
- trap_a-record-s-remedy-fields-are-mined-for-file-paths: A record's remedy fields are mined for file paths and become its blast radius
- trap_guard-exit-code-in-ci: A CI step that calls crumb guard dies on guard's own verdict exit code
- trap_hand-tagged-releases: Never create a git tag or GitHub Release by hand
- trap_the-mcp-surface-of-0-1-11-was-never-exercised-the-field: The MCP surface of 0.1.11 was never exercised: the field audit had to kill the server to allow the upgrade, so no mcp__breadcrumbs__* tool ran on that release at all

## Open Questions / Blockers
- Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first.

## Inbox (unsorted, expires)
_(candidates, not findings — promote with `crumb inbox promote <id> <type>` or drop with `crumb inbox drop <id>`)_
- `jot_20260922_phase-1-wm-14-s-transcript-miner-must-write-via-inbox-34ba` (0d, agent) Phase 1 WM-14's transcript miner must write via inbox.write_jot(source='transcript', local=True) — the private/inbox sp…

## Likely Relevant Files
- breadcrumbs/handoffs.py
- breadcrumbs/lock.py
- breadcrumbs/promote.py
- breadcrumbs/lifecycle.py
- breadcrumbs/searchindex.py
- breadcrumbs/related.py
- breadcrumbs/blockfiles.py
- breadcrumbs/transcript.py
- breadcrumbs/cli.py
- breadcrumbs/usage.py
- breadcrumbs/inbox.py
- docs/roadmap-working-memory.md
- CHANGELOG.md
- README.md
- pyproject.toml
- breadcrumbs/templates/project-memory/README.md
- tests/test_note.py
- .github/workflows/release.yml:36
- RELEASING.md:22
- breadcrumbs/__init__.py
_(… 1 more omitted to stay within the per-section cap)_

## Verifications
- `ver_20260817_f-5-guard-reprints-the-staleness-block-on-every-call` — F-5 (guard reprints the staleness block on every call) is already fixed on main and in 0.1.11: **not_applicable** · runtime
- `ver_20260922_phase-5-of-the-working-memory-roadmap-wm-50-to-wm-52` — Phase 5 of the working-memory roadmap (WM-50 to WM-52) is implemented and green: **fixed** · test
- `ver_20260922_phase-4-of-the-working-memory-roadmap-wm-40-to-wm-43` — Phase 4 of the working-memory roadmap (WM-40 to WM-43) is implemented and green: **fixed** · test
- `ver_20260922_phase-3-of-the-working-memory-roadmap-wm-30-to-wm-35` — Phase 3 of the working-memory roadmap (WM-30 to WM-35) is implemented and green: **fixed** · test
- `ver_20260922_phase-2-of-the-working-memory-roadmap-wm-20-to-wm-25` — Phase 2 of the working-memory roadmap (WM-20 to WM-25) is implemented and green: **fixed** · test
- `ver_20260922_phase-1-of-the-working-memory-roadmap-wm-10-to-wm-16` — Phase 1 of the working-memory roadmap (WM-10 to WM-16: capture hooks and the transcript miner): **fixed** · test
- `ver_20260922_phase-0-of-the-working-memory-roadmap-wm-01-migration-wm-02` — Phase 0 of the working-memory roadmap (WM-01 migration, WM-02 usage, WM-03 inbox): **fixed** · test
- `ver_20260905_the-16-findings-of-the-0-1-11-crumb-kit-field-review-re` — the 16 findings of the 0.1.11 crumb-kit field review, re-checked against 0.1.12: **fixed** · static
- `ver_20260903_resume-s-possible-drift-line-fires-on-incidental-two-word` — resume's possible-drift line fires on incidental two-word overlap and version fragments: **fixed** · test
- `ver_20260818_readme-status-blurb-no-longer-hard-codes-a-package-version` — README Status blurb no longer hard-codes a package version: **fixed** · static
- `ver_20260818_remember-set-validates-section-headings-exactly-as-capture` — remember --set validates section headings exactly as capture session does: **fixed** · test
- `ver_20260818_crumb-mark-status-can-retire-a-trap-in-0-1-11-fixed` — crumb mark-status can retire a trap in 0.1.11: **fixed** · test
_(… 6 more omitted to stay within the per-section cap)_

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
- handoff is 0 day(s) old, written 1 commit(s) behind current HEAD.
- active decision dec_20260818_repo-presentation-is-a-release-artifact-no-hand-pinned is 35 days old with no update — is this still true?
- active decision dec_20260818_hook-guard-never-overrides-the-session-s-permission-mode is 35 days old with no update — is this still true?
- active decision dec_20260818_blast-radius-is-scored-separately-from-retrieval-overlap is 35 days old with no update — is this still true?
- active decision dec_20260817_guard-verdicts-are-capped-by-record-stance-not-by-retrieval is 36 days old with no update — is this still true?
- active decision dec_20260816_questions-get-their-own-status-vocabulary-not-the-record-one is 38 days old with no update — is this still true?
- active decision dec_20260816_traps-carry-a-lifecycle-status-and-mark-status-resolves-them is 38 days old with no update — is this still true?
- active decision dec_20260815_crumb-guard-exits-verdict-mapped-codes-0-10-15-20 is 38 days old with no update — is this still true?
- active decision dec_20260815_guard-verdict-floors-require-file-tag-specificity-keyword is 38 days old with no update — is this still true?
- active decision dec_20260815_pypi-trusted-publisher-must-be-re-pointed-after-a-repo is 38 days old with no update — is this still true?
- active decision dec_20260815_cut-0-1-10-as-the-agent-authorship-release is 38 days old with no update — is this still true?
- active decision dec_20260815_the-tool-s-own-repo-commits-its-own-memory-store is 39 days old with no update — is this still true?
- active decision dec_20260815_stop-hook-extraction-turn-makes-the-agent-the-memory-author is 39 days old with no update — is this still true?
- active decision dec_20260815_guard-folds-morphology-with-a-deterministic-fixpoint is 39 days old with no update — is this still true?
- open question "Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first." has been open 39 days — did this ever get resolved?
