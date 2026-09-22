<!-- GENERATED PROJECTION — do not edit by hand. Rebuilt by `crumb resume`. -->
<!-- source_commit: d71a7e3 | inputs_hash: 99f020c63e36 | generated_at: 2026-09-22T16:54:34+00:00 -->

# Resume Packet

## Project
**breadcrumbs** — `.`  
branch `claude/agentic-memory-system-mybkpi` · commit `d71a7e3` · 61 uncommitted file(s)

## Current Focus
Phase 0 shipped (schema_version 2); Phase 1 capture hooks are next

## Next Action
Start Phase 1 of docs/roadmap-working-memory.md with WM-14 (breadcrumbs/transcript.py: the deterministic transcript miner), since WM-11, WM-13 and WM-15 all depend on it. Read docs/roadmap-working-memory.md §0.5 first — it lists seven places Phase 0 departed from the plan.

## Active Decisions
- `dec_20260922_usage-telemetry-counts-surfacings-at-the-call-sites` — Every mutation reindexes and every reindex builds a packet, so counting inside build_resume_packet would have measured writes rather than surfacings. Splitting guard between the command and the hook avoids double-counting every hook advisory, since the hook shows a filtered subset of the same result. Counters in frontmatter would churn every record on every guard call and break 'records are authored facts'; a committed counter file would conflict on every merge.
- `dec_20260922_automatic-memory-writes-land-in-private-inbox-and-earn` — A machine-local jot in a committed projection makes that file differ between two checkouts of one store while _inputs_hash calls both fresh, since the hash cannot read gitignored input without the same problem. That is the cross-machine ping-pong _hashed_input_dirs already exists to prevent. Excluding private jots from the packet keeps the projection machine-independent by construction.
- `dec_20260922_the-working-memory-roadmap-is-the-plan-of-record-for-phases` — Hook facts were verified against the Claude Code hooks reference: PreCompact output never reaches the model (so it mines and marks; SessionStart source=compact re-injects), SubagentStop can block but the plan defers that behind the existing prompt-fatigue open question, UserPromptSubmit additionalContext reaches the model, and the transcript file may lag the current turn. New code goes in new modules; cli.py is 10.7k lines. Usage telemetry is local-only in v1 to avoid churning records and merge conflicts.
- `dec_20260905_a-read-only-action-caps-at-read-first-and-entropy-warns` — Neither is a scoring problem. Overlap is symmetric, so corpus frequency reads as relevance and no weighting fixes a command that cannot do the thing being warned about. And a gate that is hand-overridden every time has stopped being a gate — worse, it punishes exactly the records that cite a concrete path, which are the most useful ones a store has. Both classifications are conservative: an unrecognized action keeps its full verdict, and a structured credential still blocks.
- `dec_20260905_path-extraction-is-structural-and-a-mined-path` — Existence on disk was rejected deliberately: a record citing a file that was since deleted or renamed is often exactly the trap worth raising, and a store must mean the same thing in every checkout that reads it. The shape test rejects 15 of the 16 junk tokens the review names and keeps every real path tested. Tiering is the review's own point 3 — a trap author knows which files their trap is about — without a schema change, because the declaration field already exists in both record types.
- `dec_20260905_a-wrong-set-heading-parks-content-it-never-discards-the-call` — The error was accurate and the cost was everything else on the command line. Content an agent has already synthesised is the most expensive thing in the system to reproduce, and the moment it is lost is the moment the agent has least context left. A guess that lands content under the wrong heading is worse than parking it, so the synonym table stays short.
- `dec_20260903_branch-mismatch-is-judged-on-whether-the-file-reached-head` — A record's commit: is HEAD at write time, i.e. where the code was, so commit ancestry is unsound: a commit can be an ancestor of HEAD while the record beside it is uncommitted or on an unmerged branch. A file committed at HEAD and clean in the worktree has provably reached this history, and that test also covers squash and rebase merges, where no feature sha survives. Downgrading to a note would keep the noise. Three git calls per staleness pass regardless of store size: rev-parse --show-prefix (the project root may sit below the repo root and ls-tree/status print repo-root-relative paths), ls-tree -r -z HEAD, status --porcelain.
- `dec_20260818_repo-presentation-is-a-release-artifact-no-hand-pinned` — A hand-maintained version literal in prose is the same defect the project already removed from pyproject.toml and cli.py; it went four releases stale precisely because nothing checked it. Badge link targets must be absolute because README.md is also the PyPI long description, where a relative href resolves to nothing. GitHub's native badge.svg endpoint could not be verified from this environment (403 through the proxy), so every badge URL used was one that returned 200 and the expected aria-label.
- `dec_20260818_hook-guard-never-overrides-the-session-s-permission-mode` — The contract in our own source is 'memory informs; it never allows or denies on its own'. Re-raising a prompt the user explicitly turned off is deciding for them. A user armouring a workaround against our upgrades is the strongest available evidence the default was wrong.
- `dec_20260818_blast-radius-is-scored-separately-from-retrieval-overlap` — Overlap answers 'is a record about this action'; it has never answered 'how much damage does this do'. Danger belongs on the escalation side where it can raise a verdict, not on the prompt gate where it could only suppress an authored one.
- `dec_20260817_guard-verdicts-are-capped-by-record-stance-not-by-retrieval` — A match's stance decides its verdict ceiling: blocking (an attempt with an explicit Do Not Retry Unless) may reach PAUSE; advisory (trap, decision, verification, open question) is capped at READ_FIRST. The score band is applied per match rather than once from the best score across all matches.
- `dec_20260816_questions-get-their-own-status-vocabulary-not-the-record-one` — The record words do not fit. The dominant way a question retires is that somebody answered it, and no lifecycle value says that — marking an answered question 'stale' records the opposite of what happened. The codebase already has this shape: a verification's outcome is deliberately not its status, for the same reason. The id decides which vocabulary applies and a mismatch is rejected by name, so the two never silently cross.
- `dec_20260816_traps-carry-a-lifecycle-status-and-mark-status-resolves-them` — Reusing VALID_STATUS through the existing mark-status entry point keeps one vocabulary and one writer, and gives the MCP memory_mark_status tool the same reach with no new code. search already printed [active] for traps, so the vocabulary was implied by the UI before it existed in the file.
- `dec_20260815_crumb-guard-exits-verdict-mapped-codes-0-10-15-20` — Callers could not script on verdicts at all (everything exited 0), and a Windows field-test harness rendered advisory verdicts as tool failures; documented spaced codes make 'block only on ASK_HUMAN' possible and any host-layer weirdness diagnosable.
- `dec_20260815_guard-verdict-floors-require-file-tag-specificity-keyword` — 0.1.10 field test: the unconditional trap keyword floor fired READ_FIRST on 13/13 edits with one relevant hit; an ignored alarm is worse than no alarm.
_(… 5 more omitted to stay within the per-section cap)_

## Failed Attempts To Avoid
_(none recorded)_

## Known Traps
- trap_hand-tagged-releases: Never create a git tag or GitHub Release by hand
- trap_guard-exit-code-in-ci: A CI step that calls crumb guard dies on guard's own verdict exit code
- trap_the-mcp-surface-of-0-1-11-was-never-exercised-the-field: The MCP surface of 0.1.11 was never exercised: the field audit had to kill the server to allow the upgrade, so no mcp__breadcrumbs__* tool ran on that release at all
- trap_a-record-s-remedy-fields-are-mined-for-file-paths: A record's remedy fields are mined for file paths and become its blast radius
- trap_a-hand-written-version-literal-in-prose-drifts-silently: A hand-written version literal in prose drifts silently
- trap_a-bare-n-in-a-commit-message-links-an-issue-but-never: A bare (#N) in a commit message links an issue but never closes it

## Open Questions / Blockers
- Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first.

## Inbox (unsorted, expires)
_(candidates, not findings — promote with `crumb inbox promote <id> <type>` or drop with `crumb inbox drop <id>`)_
- `jot_20260922_phase-1-wm-14-s-transcript-miner-must-write-via-inbox-34ba` (0d, agent) Phase 1 WM-14's transcript miner must write via inbox.write_jot(source='transcript', local=True) — the private/inbox sp…

## Likely Relevant Files
- breadcrumbs/usage.py
- breadcrumbs/inbox.py
- breadcrumbs/cli.py
- docs/roadmap-working-memory.md
- CHANGELOG.md
- README.md
- pyproject.toml
- breadcrumbs/templates/project-memory/README.md
- tests/test_note.py
- .github/workflows/release.yml:36
- RELEASING.md:22
- breadcrumbs/__init__.py
- .gitignore

## Verifications
- `ver_20260817_f-5-guard-reprints-the-staleness-block-on-every-call` — F-5 (guard reprints the staleness block on every call) is already fixed on main and in 0.1.11: **not_applicable** · runtime
- `ver_20260922_phase-0-of-the-working-memory-roadmap-wm-01-migration-wm-02` — Phase 0 of the working-memory roadmap (WM-01 migration, WM-02 usage, WM-03 inbox): **fixed** · test
- `ver_20260905_the-16-findings-of-the-0-1-11-crumb-kit-field-review-re` — the 16 findings of the 0.1.11 crumb-kit field review, re-checked against 0.1.12: **fixed** · static
- `ver_20260903_resume-s-possible-drift-line-fires-on-incidental-two-word` — resume's possible-drift line fires on incidental two-word overlap and version fragments: **fixed** · test
- `ver_20260818_readme-status-blurb-no-longer-hard-codes-a-package-version` — README Status blurb no longer hard-codes a package version: **fixed** · static
- `ver_20260818_remember-set-validates-section-headings-exactly-as-capture` — remember --set validates section headings exactly as capture session does: **fixed** · test
- `ver_20260818_crumb-mark-status-can-retire-a-trap-in-0-1-11-fixed` — crumb mark-status can retire a trap in 0.1.11: **fixed** · test
- `ver_20260817_python-m-breadcrumbs-mcp-serve-speaks-mcp-stdio-identically` — python -m breadcrumbs mcp serve speaks MCP stdio identically to the breadcrumbs-mcp console script: **fixed** · runtime
- `ver_20260816_release-0-1-10-blocked-by-pypi-invalid-publisher-fixed` — release 0.1.10 blocked by PyPI invalid-publisher: **fixed** · static
- `ver_20260816_ci-yml-guard-steps-survive-guard-s-verdict-exit-codes-fixed` — ci.yml guard steps survive guard's verdict exit codes: **fixed** · test
- `ver_20260816_crumb-mark-status-can-answer-an-open-question-fixed` — crumb mark-status can answer an open question: **fixed** · test
- `ver_20260816_crumb-mark-status-can-retire-a-trap-fixed` — crumb mark-status can retire a trap: **fixed** · test
_(… 1 more omitted to stay within the per-section cap)_

## Verification Commands
- python -m unittest tests.test_usage
- python -m unittest tests.test_inbox
- tests/test_secret_precision.py
- tests/test_guard_precision.py
- tests/test_sections.py
- tests/test_resume.py
- tests/test_audit.py
- python -m unittest discover -s tests
- python -m unittest tests.test_hooks
- python -m unittest tests.test_guard
- python -m build --wheel
- python crumb.py validate

## Stale / Risk Warnings
_(ages below are measured; the cutoff is 21 days — set with `--stale-days`)_
- handoff is 0 day(s) old, written 0 commit(s) behind current HEAD.
- active decision dec_20260818_repo-presentation-is-a-release-artifact-no-hand-pinned is 34 days old with no update — is this still true?
- active decision dec_20260818_hook-guard-never-overrides-the-session-s-permission-mode is 35 days old with no update — is this still true?
- active decision dec_20260818_blast-radius-is-scored-separately-from-retrieval-overlap is 35 days old with no update — is this still true?
- active decision dec_20260817_guard-verdicts-are-capped-by-record-stance-not-by-retrieval is 36 days old with no update — is this still true?
- active decision dec_20260816_questions-get-their-own-status-vocabulary-not-the-record-one is 37 days old with no update — is this still true?
- active decision dec_20260816_traps-carry-a-lifecycle-status-and-mark-status-resolves-them is 37 days old with no update — is this still true?
- active decision dec_20260815_crumb-guard-exits-verdict-mapped-codes-0-10-15-20 is 37 days old with no update — is this still true?
- active decision dec_20260815_guard-verdict-floors-require-file-tag-specificity-keyword is 37 days old with no update — is this still true?
- active decision dec_20260815_pypi-trusted-publisher-must-be-re-pointed-after-a-repo is 38 days old with no update — is this still true?
- active decision dec_20260815_cut-0-1-10-as-the-agent-authorship-release is 38 days old with no update — is this still true?
- active decision dec_20260815_the-tool-s-own-repo-commits-its-own-memory-store is 38 days old with no update — is this still true?
- active decision dec_20260815_stop-hook-extraction-turn-makes-the-agent-the-memory-author is 38 days old with no update — is this still true?
- active decision dec_20260815_guard-folds-morphology-with-a-deterministic-fixpoint is 38 days old with no update — is this still true?
- open question "Should the extraction turn also fire on PreCompact (memory extraction at the moment context is about to be destroyed)? Needs a field test of prompt fatigue first." has been open 38 days — did this ever get resolved?
