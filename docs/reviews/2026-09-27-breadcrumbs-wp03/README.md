# WP03: lossless, scope-preserving jot promotion (2026-09-27)

This implements work package WP03 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F03. The
starting commit is `7fc3b50`, after WP02.

## Cause

`inbox.promote_jot` had four problems:

1. **Text lost.** Promotion to a decision, attempt or idea passed `sections or {}`
   to `write_record`. Without `--set`, the jot's note, the one thing it said, was
   not in the record. The verification, trap and question targets likewise kept
   only the title.
2. **Scope widened.** The target got `write_record`'s default scope, `project`,
   whatever the jot's scope was.
3. **Confidence raised.** It defaulted to `medium` (the trap and question writers
   hard-coded it), though a jot is `low`.
4. **No duplicate gate.** Decisions, attempts and ideas went straight to
   `write_record`; verifications, traps and questions were written with
   `dedupe=False`.

The `jot_promotion_loss` probe reproduced the first three problems.

## Change

- **`promote_jot` carries the note into every target.**
  - With no sections given, the note is the body section the packet reads for
    that type. A decision gets `Decision`, an attempt `Result` (not
    `Why It Failed`, which would claim a cause), an idea `Idea`, and a
    verification, trap or question `Notes`.
  - With sections or trap fields given, the note is kept as a
    `From jot <id>: …` paragraph in `Context` (decision), `Problem` (attempt),
    `Motivation` (idea) or `Notes` (the rest), unless a section already quotes
    it.
  - The record gets two new frontmatter keys: `promoted_from` (the jot's id) and
    `promoted_from_digest` (sha256 of the note, first 16 hex digits).
- **Scope and confidence come from the jot** unless `scope=` or `confidence=` is
  given. The result reports `scope`, `confidence`, `scope_widened` and
  `from_private`. To make this possible, `blockfiles.write_trap` and
  `write_question` now accept `meta_extra`, `cli.note` passes `notes` and `meta`
  through, and `cli.verify` accepts `extra`.
- **The near-duplicate gate** applies to every target, with `allow_duplicate`
  and `supersedes`. `supersedes` retires the old record through the same path
  `remember` uses.
- **A private jot carrying a structured credential is refused** rather than
  published. Its text is unchanged and it stays live.
- **The jot is retired only after the target is written and valid,** as
  before; the tests now pin that down.
- **CLI:** `inbox promote` gains `--scope`, `--allow-duplicate` and
  `--supersedes`. A near-duplicate exits 3, as `remember` does. The output
  prints the scope and confidence written, and says when private text is now
  committed.
- **MCP:** `memory_inbox_promote` gains `scope`, `allow_duplicate` and
  `supersedes`.
- **Docs:** `cli-spec.md` (the promote row, the near-duplicate gate, branch
  scope), `mcp-spec.md`, `record-schema.md` (the `promoted_from` keys), and
  `CHANGELOG.md`. The CHANGELOG also gains the WP02 entry it was missing.

## Tests

`tests/test_promotion_contract.py` has 13 tests, including the four the roadmap
names:

- `test_promote_without_sections_preserves_note_text` (all six targets)
- `test_private_branch_promotion_does_not_default_to_project_medium` (all six)
- `test_promotion_obeys_duplicate_gate` (library, CLI exit 3, `--supersedes`)
- `test_failed_target_leaves_source_live`: covers the evidence rule, the record
  contract and a trap slug collision

Against the pre-change code, 12 of the 13 fail or error. The errors are mostly
the new keyword arguments; the probe already showed the behavior on the old
code.

`test_inbox.PromoteTests.test_promotion_obeys_the_evidence_rule` relied on the
old inflated default: a jot with no evidence was refused only because the target
became `medium`. It now inherits `low`, which the evidence rule allows. The test
now asserts that an explicit `--confidence medium` without evidence is still
refused and leaves the jot live.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1200 run, 0 failures, 6 skipped |
| `test_promotion_contract test_inbox test_note test_mcp` on Python 3.9.23 | 0 | OK |
| `test_mcp test_promotion_contract test_inbox` with the MCP SDK (2.2.0) installed | 0 | 102 run, OK |
| CI `mcp` job registration step, SDK 2.2.0 | 0 | 13 tools, 6 prompts, 14 resources. `memory_inbox_promote` shows `scope`, `allow_duplicate` and `supersedes` |
| `python evals/run.py` | 0 | Score table identical to WP00 |
| `regression_probes.py … --fail-on-observed` | 1 | 15 defect signals, 0 errors. `jot_promotion_loss` is no longer observed: the note is in `## Decision`, scope `branch`, confidence `low` ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |

## Compatibility

- No record is rewritten and no schema version changes. The two new frontmatter
  keys are additive; older readers carry unknown keys through untouched.
- **Default promotions write different records.** A promoted record keeps the
  jot's `low` confidence and its scope. A mined, hook-written jot is
  `branch`-scoped, so its promoted record leaves the packet on other branches
  until someone passes `--scope project`.
- **A jot with no evidence now promotes** as a `low` decision or attempt instead
  of being refused.
- **Promotion can now be refused as a near-duplicate** (exit 3; MCP
  `error: "near-duplicate"`).
- The CLI promote output gains two lines, and the JSON and MCP results gain four
  keys.

## Needs your decision

F03 asks for "explicit authorization for … sharing private content". Here,
naming the jot in `inbox promote` is treated as that authorization. That matches
the module's design ("promoting a private jot is what moves its content into
committed memory") and the audit's solo profile (§5.4: no redundant ceremony,
but the effect must be apparent). The result says so, and credential-shaped text
is refused. A stricter rule would add a required `--share` flag for private
jots. That is a policy question for the WP14 review and capability profiles.

## Limits

- **Promotion is not atomic.** If the target is written but marking the jot
  superseded fails, the result is `ok` with a `warning` (unchanged). Making this
  recoverable is WP06.
- **Legacy stores are not covered.** On a schema-2 store (block traps and
  questions), inherited scope, confidence and provenance are not written, and
  the store must be migrated anyway.
- **Only structured credentials are checked.** The secret check uses the
  structured patterns; the high-entropy heuristic is not consulted, as with the
  miner.
