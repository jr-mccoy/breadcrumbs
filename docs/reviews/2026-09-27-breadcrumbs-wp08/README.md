# WP08: bounded, portable packets (2026-09-27)

This implements work package WP08 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), findings F13
and F14. The starting commit is `344fd88`, after WP07.

## Cause

- **F14: the bound covered the lists, not the view.** `_bound_packet` trimmed
  the list sections under `TOKEN_BUDGET_MAX`, and gave up ("emit slightly over
  rather than loop forever") once they were empty.
  - Current Focus, Next Action, Requested Task, the project line and every
    single list entry or warning were unbounded. A 28,500-character focus
    produced a 7,333-token packet under a 5,000-token ceiling (`packet_bound`
    probe).
  - `--fast` skipped the budget entirely.
  - The JSON views (`resume --json`, MCP) were never measured at all.
  - `len/4` was reported as a token count, a quarter of the real count for CJK
    or emoji.
- **F13: promotion made records disappear.** `_build_resume_packet_once`
  dropped every record with `promoted_to` from its list, on the assumption
  that the rule was in the reader's context. A reader of the committed packet,
  of `resume`, or of the MCP packet may be any harness, and `CLAUDE.md` may no
  longer hold the rule. With the file removed, a live decision appeared nowhere
  (`promoted_adapter_missing` probe).

## Change

**Every view is bounded on its final text** (`_bound_packet` in `cli.py`).

- **Views.** A view is a format (`markdown`, `json`) plus `fast` or not. Each
  has a default budget (5,000; 1,500 for fast) and a smallest honourable budget
  (`PACKET_MIN_BUDGET`: 500 / 400 / 700 / 700). The minimums are at least 30%
  above the pointer-only floor measured for a worst-case store (375 / 282 /
  528 / 504).
- **What is measured is what is emitted.**
  - Markdown: `render_packet_markdown`.
  - `resume --json`: the exact printed document, measured through the new
    `_json_document` (the shared envelope). `publication.reason` is reserved at
    its widest and clipped to 200 ASCII chars (`_ascii_clip`).
  - MCP `memory_build_resume_packet`: the returned document, `ok` included.
- **The fitting order:**
  1. excerpt every list entry and warning (300 chars), and Current Focus and
     Next Action (2,000; Requested Task 500);
  2. apply the per-section caps;
  3. trim the lists in `TRIM_ORDER`, which now includes
     `commits_since_handoff` before the warnings;
  4. shrink the protected fields and project names through 1,000 / 500 / 250 /
     120 chars to a bare pointer (names never below 40).

  Every step removes something, so the loop terminates.
- **Excerpts are marked and point at the whole.** For example:
  - `… [excerpt: 2000 of 31499 chars; full text: handoff.md → Next Action]`;
  - `[omitted: 45000 chars; full text: current.md → Current Focus]`;
  - entries point at `crumb show <id>`.

  `excerpted` counts them: per section, a number; per protected field,
  `{shown_chars, total_chars, source}`. Canonical files are never modified.
- **Self-identifying.** The packet gets `budget: {view, unit, estimator,
  estimator_rule, limit, used, within, requested?}`, and the Markdown gets a
  header line: `<!-- view: … | budget: used/limit approx_tokens (…) | rules: … -->`.
  `used` is measured with placeholders at least as wide as the final values, so
  the emitted text is never longer than reported.
- **Named estimator** (`TOKEN_ESTIMATOR = "approx-tokens/2"`). `approx_tokens`
  is ASCII chars / 4, rounded up, plus one per non-ASCII character. That is
  unchanged for ASCII text, and every caller shares it.
- **`crumb resume --budget TOKENS`** bounds the printed view. Below the view's
  minimum it exits 2. A library call below the minimum is raised to it and
  reports `requested`. The committed packet always uses the default.
- **Smaller changes.**
  - The unstable-snapshot warning (WP07) is now part of the build
    (`lead_warnings`) rather than inserted after bounding, so it counts
    against the budget.
  - The relevance-ordering note no longer repeats the task text.

**Promoted records are portable** (`promote.py`, `_build_resume_packet_once`).

- New `rules_in_files`, `loaded_rules`, `rule_text` and `effective_rule`. The
  rule in force is the bullet in the instruction file, even one edited by hand.
  If the file or the bullet is gone, the rule is rendered from the record as
  `promote` would write it.
- **Portable packets keep promoted records.** Their entries gain `promoted_to`,
  `rule` and `rule_in_file`, and render as `` `<id>` — standing rule in
  CLAUDE.md: <rule> `` or `… (promoted to CLAUDE.md, not found there): …`. A
  promoted trap entry reads `<trap id>: standing rule in …: <rule>`. Portable
  packets are `resume` in every form, the committed packet, and the MCP tool
  and resource. `packet.rules = {mode: "portable"}`.
- **Only a consumer with verified loaded rules elides.** `build_resume_packet(…,
  loaded_rules=, loaded_rules_from=)`: the `SessionStart` hook, which is Claude
  Code's, passes the bullets in the project's `CLAUDE.md` read at that moment.
  - Records promoted there are left out and counted in `promoted`, with a note
    naming the file.
  - A rule promoted to `AGENTS.md`, which Claude Code does not load, stays.
  - `packet.rules = {mode: "elided-when-loaded", loaded_from, elided}`.
- `crumb promote`'s closing message says what now happens.

**Tests updated because they pinned the defect.** Three `test_promote` tests
asserted that promoted records vanish from the default packet. They now assert
both sides: the portable packet keeps the rule, and the loaded view leaves it
out.

- `test_the_packet_leaves_it_out_and_counts_it` is renamed
  `…keeps_it_as_a_rule_unless_its_reader_loaded_it`.
- `test_attempts_and_traps_render_as_rules`.
- `test_a_schema2_trap_block_is_promoted_with_a_bullet`.

Two other tests changed for smaller reasons:

- `test_inbox`'s trim sweep gets a long focus, so its store is larger than the
  new minimum budget and the sweep still forces trims. Its invariant, that no
  decision is trimmed while a jot remains, is unchanged.
- `test_resume`'s ordering-note assertion follows the note's new wording.

**Docs.**

- `cli-spec.md` (`resume`): a views/budgets table, the estimator,
  `--budget`, the fitting order, the header line and JSON fields, and the
  promoted-records rules; the `usage --decay` note.
- `mcp-spec.md`, `record-schema.md` (the packet row and §13), `architecture.md`,
  `README.md`, `CHANGELOG.md`, and the `promote.py` docstring.

## Tests

`tests/test_packet_delivery.py` has 7 tests, including the four the roadmap
names.

- **`test_long_focus_cannot_exceed_declared_view_budget`.** It uses a
  45,000-char focus and a 36,000-char Next Action. Every view stays within its
  declared limit, and within `used`: markdown, markdown-fast, json, json-fast,
  the MCP tool and the hook. The excerpt marks name `current.md → Current Focus`
  and `handoff.md → Next Action`, `current.md` is byte-identical, and the
  committed packet is within 5,000.
- **`test_missing_adapter_does_not_hide_promoted_decision`.** After promotion,
  `CLAUDE.md` is deleted. The portable packet, the Claude hook view and the
  committed packet all keep the decision, marked "not found there", with the
  rule rendered from the record.
- **`test_cross_harness_packet_includes_effective_rules`.** One rule is
  promoted to `CLAUDE.md` with `--rule` and then edited by hand; another goes
  to `AGENTS.md`.
  - The portable packets (library, MCP, `resume --json`) carry both, the
    hand-edited text included.
  - The hook leaves out only the `CLAUDE.md` one and keeps the `AGENTS.md`
    one.
  - After `demote`, the decision renders normally everywhere.
- **`test_unicode_and_tiny_budgets_terminate_and_disclose_omissions`.**
  - The estimator counts 8 for `日本語のテキスト` and 10 for 40 ASCII chars.
  - The store has a CJK and emoji focus, 30 CJK decisions, 15 traps and 15
    questions. Each of the four views is built at budgets 1, min, min+1,
    2×min, 2,500 and 5,000. Every build terminates in under 30 s and stays
    within its limit (the minimum for a request below it, with `requested`
    set). Omissions are disclosed, and shown plus omitted decisions add up to
    exactly 30.
  - `resume --budget 10` exits 2.
- **Also covered:**
  - a huge title and rationale are excerpted with `crumb show <id>` pointers;
  - 60 long warnings are excerpted and trimmed;
  - the compaction hook adds at most its declared preamble;
  - a read-only clone gets the rule from the committed packet with
    `CLAUDE.md` absent.

Against the pre-change code (`344fd88`), **all 7 fail**:

- **4 behaviorally:**
  - the hook context at 15,962 estimated tokens against 6,000;
  - the estimator counting 2 for 8 CJK characters;
  - the clone's packet without the rule;
  - the hook hiding the `AGENTS.md` rule.
- **3 on the new API** (`view=`, `budget`, `promote.loaded_rules`). Their
  substance is the same commit's probe results: `packet_bound` at 7,333
  tokens, and `promoted_adapter_missing` with an empty decision list.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1252 run, 0 failures, 6 skipped |
| WP08 and affected packet/promote/resume/inbox/fixtures/hooks/traps/snapshot/MCP tests on 3.9.23 | 0 | 278 OK |
| `test_mcp` with MCP SDK 2.2.0 | 0 | OK (2 skipped) |
| `python evals/run.py` | 0 | Identical to WP07's output |
| `regression_probes.py … --fail-on-observed` | 2 | 8 defect signals, 2 probe errors (WP04/WP05's recorded instrument errors). `packet_bound` (now 778 tokens) and `promoted_adapter_missing` are no longer observed ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |
| Packet build, 1,000 records with a 28,500-char focus, before vs after | — | 2,379 ms vs 2,321 ms (markdown), 2,385 ms (json). The packet was 7,392 tokens before and is 3,415 after |

The remaining signals belong to other packages:

- `sliding_cursor`;
- `prompt_cliff`;
- `guard_prefilter` (F10);
- `symlink_read`;
- `powershell_translation`;
- `short_prompt_and_stale_task`;
- `guard_usage_dedupe`;
- `resume_ignores_lock`, the false positive recorded in WP05.

## Compatibility

- **Promoted records now appear in every portable packet** (`resume`, the
  committed packet, MCP), shown as their rules. `packet.promoted` is `{}` there;
  it counts only what a loaded-rules view left out. The Claude Code
  `SessionStart` context is unchanged for rules its `CLAUDE.md` carries. A
  consumer that relied on the default packet dropping promoted records now
  sees them.
- **New packet fields:**
  - `budget`, `rules` and (when anything was shortened) `excerpted`;
  - `promoted_to`, `rule` and `rule_in_file` on promoted entries;
  - a promoted trap's entry string reads `<id>: standing rule in <file>: <rule>`.
- **`approx_tokens` in `resume --json`** is now the JSON view's own size
  (`budget.used`). It used to be the Markdown rendering's size.
- **The estimator changed for non-ASCII text.** ASCII is unchanged. A Unicode-
  heavy packet, prompt-hook injection or `audit` bloat figure now counts
  higher, so more is trimmed.
- **Long fields are shortened in views.** A focus or next action over 2,000
  chars, or an entry or warning over 300, appears as a marked excerpt. The
  canonical files are untouched.
- **The JSON views are now bounded.** A large store may show fewer entries in
  `--json` or MCP than in Markdown, since JSON is larger for the same content;
  each view says what it omitted.
- **The Markdown packet has a third header line** (`<!-- view: … -->`). The
  `inputs_hash` stamp parsing is unaffected.
- **New flag:** `crumb resume --budget`.

## Limits

- **The estimator is a heuristic, not a tokenizer.** Budgets are exact in its
  unit, `approx-tokens/2`, not in any model's tokens. Emoji and some scripts can
  cost more than one real token per character. Exact per-consumer tokenizer
  accounting (optional in the roadmap) is not implemented.
- **"Loaded" is established by reading `CLAUDE.md` when the hook runs.**
  - Rules Claude Code loads from elsewhere (a parent directory, `~/.claude`,
    an `@AGENTS.md` import) are not counted, so they are shown, possibly
    twice.
  - A hand edit to `CLAUDE.md` during the session is not seen until the next
    session start.
- **No other harness has a loaded-rules view yet.** Every other consumer gets
  the portable packet, which is the safe default.
- **The hook's total is packet plus preamble.** After a compaction, the
  `SessionStart` context is bounded as the Markdown packet's budget plus
  `_COMPACT_PREAMBLE_TOKENS` (1,000), as before. It is not one combined
  budget.
- **Excerpts cut by characters.** A cut can split a grapheme cluster, such as
  a combining sequence or a multi-codepoint emoji.
- **No separate view-identity digest.** The WP07 note deferred a view identity
  to this package. The packet now names its view, budget and rule mode in
  `budget` and `rules`, and its snapshot in `source.inputs_hash`. There is no
  single digest over all of them.
