# WP01: the record contract (2026-09-27)

This implements work package WP01 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), finding F05. The
[WP00 baseline](../2026-09-26-breadcrumbs-wp00-baseline/README.md) is the starting point.
The starting commit is `ec9dac7`, with product code identical to the audited `30e41f6`.

## Cause

The per-record checks in `run_validate` established presence, not shape:

- The evidence rule was `bool(evidence)`, so `[{nonsense: x}]` counted as evidence.
- `confidence`, `review_status`, `scope` and timestamps were never checked.
- `superseded_by` only had to be non-empty.

`crumb remember --scope` and MCP `memory_record` stored any scope text, and
readers treat unknown text as `project`. The `schema_types` probe reproduced
all five cases.

Readers already tolerated these values. The packet, reindex, prompt retrieval
and guard all ran over each malformed shape without crashing. So the gap was in
validation and visibility, not robustness.

## Change

- **`breadcrumbs/validation.py`** (new, stdlib-only, no package imports) holds
  the contract. `record_issues()` checks a record's field vocabularies,
  evidence shape, timestamps, scope and self-links. `store_issues()` checks
  whether a `superseded_by` target is missing and whether replacement links
  form a cycle. Each issue has a stable code.
- **`run_validate`** runs both, and every finding now carries a `code`. The
  evidence rule counts only well-formed items.
- **`write_record`** runs the record checks before writing. That covers every
  writer: the CLI, MCP `memory_record`, hooks, inbox promotion, consolidate and
  rollup. `remember --scope` now takes `choices`.
- **Rewrite gates** (mark-status, trap confirm, promote, session coalesce) pass
  the original text. A rewrite is refused only for failures it introduces, so a
  legacy-invalid record stays retirable.
- **The resume packet** adds one warning line naming records that break the
  contract. It counts committed directories only, so the projection stays
  machine-independent.
- **`_parse_iso`** reads a trailing `Z` on Python 3.9 and 3.10.
- Docs: `record-schema.md` §4 → *The record contract*; `cli-spec.md` and
  `mcp-spec.md` scope wording; `CHANGELOG.md` → Unreleased.

## Tests

`tests/test_validation_contract.py` has 18 tests, including the four the roadmap
names:

- `test_invalid_confidence_evidence_and_dates_are_reported`
- `test_new_write_rejects_unknown_scope_without_widening_legacy_scope`
- `test_missing_replacement_self_link_and_cycle_are_reported`
- `test_unknown_metadata_round_trips_without_loss`

Against the pre-change `cli.py`, 16 of the 18 fail. The two that pass either way
are invariants that must hold before and after (unknown-key round trip, rollup
`supersedes` history).

Two existing tests encoded the defect: they superseded a record with an id that
did not exist. `test_note.TrapLifecycleTests.test_superseded_needs_a_pointer` and
`test_regressions…test_R25_mark_status_cli_supersede_flow` now assert that the
dangling pointer is refused, then supersede with a real record.
`test_R3_status_change_preserves_awkward_frontmatter` failed until rewrite gates
learned to ignore pre-existing problems. It passes unchanged.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1165 run, 0 failures, 6 skipped |
| same, Python 3.9.23 (the documented floor) | 0 | 1165 run, 0 failures, 6 skipped |
| `test_validation_contract test_regressions test_note test_validate` on 3.10.20 | 0 | OK |
| `python evals/run.py --verbose` | 0 | Score table identical to the WP00 baseline |
| `python tools/audit/regression_probes.py … --fail-on-observed` | 1 | 18 defect signals, 0 errors. `schema_types` is no longer observed; the other 18 probes are unchanged ([probe-results.json](probe-results.json)). |
| CI `test` job fixture steps, replayed locally | 0 | All 7 pass. Only fixture 08 fails `validate`, on its intended freshness finding. |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |
| `crumb validate` on this repo's store | 0 | OK |

**Cost.** `record_contract_warnings` takes about 22 ms at 500 records and 57 ms
at 1000, roughly 6–10% of a packet build. It re-parses records the packet has
already read; WP15 owns that duplication.

## Compatibility

No record is rewritten and no id changes. Every record in this repository's
store and in all 12 fixtures already satisfied the contract (checked by
`test_existing_stores_still_validate`).

Behavior that changes for a caller:

- `crumb validate` fails on a store that breaks the new checks.
- `remember --scope <other>` is an argparse error (exit 2).
- `memory_record` refuses an unsupported scope or an evidence item without a
  `type` or `ref`.
- `mark-status --superseded-by` must name an existing record.
- Validate JSON findings gain a `code` key.

A legacy record with a free-text scope is still read as `project`. That is the
documented legacy interpretation, now reported rather than silent. WP21 decides
whether a migration should make authors choose explicitly.

## Limits

- **Flow sequences are not parsed.** The frontmatter parser reads
  `tags: [a, b]` or `supersedes: [id]` as one string (fixture 05 has one). That
  shape is not flagged, because doing so would fail an existing fixture and
  probably user stores. Fixing it is a parser change, out of scope here.
- **No size or depth limits** on field values, beyond what the renderer already
  refuses.
- **Only local link targets.** `superseded_by` can only name a local record;
  there is no namespace for an external reference.
- **Hook degraded output is unchanged.** The degraded signal lives in the
  packet's warnings, which the SessionStart hook injects. The prompt and guard
  hooks still read malformed records silently, as before, without crashing.
- **Risky defaults are unchanged.** `confidence: medium` is still the default
  when evidence is given without a confidence. Changing that is a semantic
  change for WP21 or WP14.
