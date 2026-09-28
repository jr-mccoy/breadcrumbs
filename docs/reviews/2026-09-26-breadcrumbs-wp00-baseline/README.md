# WP00 baseline (2026-09-26)

WP00 of the [audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md) does two
things. It records what the repository does today, and it checks that record against the
audit's evidence. It changes no product behavior. The machine-readable record is
[`baseline.json`](baseline.json). The logs and JSON next to it are the raw output.

The audit's own evidence is in [`../2026-09-26-breadcrumbs-evidence/`](../2026-09-26-breadcrumbs-evidence/).
Those files are unchanged. Check them against the bundle checksums from the repo root:

```bash
sha256sum -c --ignore-missing docs/reviews/2026-09-26-breadcrumbs-audit-bundle-SHA256SUMS.txt
```

The work-package tracker is expected to fail that check, because it records status as work
proceeds. `BREADCRUMBS_AUDIT_START_HERE.md` was not committed. Its instructions are in
section 10 of the report and on this page.

## Revision

HEAD at baseline is `30e41f6`, the audited commit itself, with git tree `14bba98`. All 21
package modules match the audit's source manifest by git blob and by sha256. Findings could
not have been "already fixed" at this revision. Every one is still present.

## Results

Environment: Python 3.11.15 on Linux x86_64, full git clone, ruff 0.16.1. The optional MCP
SDK is not installed.

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` | 0 | 1147 run, 0 failures, 6 skipped (5 need the MCP SDK, 1 needs `typing_extensions`) |
| `python evals/run.py --verbose` | 0 | 39 tasks. Overall prompt P@5 0.66 / R@5 0.87, packet 0.59 / 0.97, guard 0.88. The run still reports `npm test: guard said PROCEED` (F19). |
| `python tools/audit/regression_probes.py --source . --output … --fail-on-observed` | 1 | 19 defect signals, 0 probe errors. All 19 are identical to the audit's results once timings are excluded. |
| `python tools/audit/run_selected_tests.py --source . --output …` | 0 | 243 run, 0 failures |
| `python tools/audit/benchmark_smoke.py --source . --output …` | 0 | Synthetic smoke timings only, not a performance claim |
| the 5 tests the audit excluded (from `tests/`) | 0 | 5 pass. The exclusions came from the audit's environment. |
| `ruff check . && ruff format --check .` | 0 | Passes with `tools/audit` excluded (see below) |
| `python crumb.py scan-secrets` | 0 | No secret-like strings |

Exit 1 from the probe runner is its documented "defect observed" code. A setup error would
exit 2.

## Finding status

- **F01–F10, F12–F17, F20, F22:** still present. Each finding's probe reproduced the
  audit's result.
- **F11, F18, F21, F23, F25, F26:** still present. They are source-confirmed findings or
  proposals, and the source is byte-identical to what was audited.
- **F19:** also re-observed. The eval job passes with exit 0 while it still reports the
  known `npm test` guard miss.
- **F24:** also re-observed. On a clean checkout, `crumb resume` still reports handoff.md's
  pre-release Next Action ("Phase 4 shipped … cut a release … or start Phase 5").

## Deviations from the report

- The complete suite and the eval harness were run here. The audit ran a 243-test subset
  and relied on CI for evals.
- The five tests the audit excluded pass on a real checkout. `run_selected_tests.py` still
  hard-codes their exclusion, so its count stays at 243.
- This baseline used Python 3.11.15; the audit used 3.13.5. The probe results are identical.
- `tools/audit/` is excluded from ruff in `pyproject.toml`. That keeps the scripts
  byte-identical to the checksummed bundle. Without the exclusion, CI's `lint` job would
  fail on them.
- `tests/test_audit_regressions.py` was not created. WP00 step 3 converts each case into a
  regression when its repair package lands. Adding 19 failing tests now would turn CI red.
  Wrapping them as expected failures would make known defects look green.

## Limits

This environment is Linux only. Native Windows and macOS were not exercised, and neither
were the MCP SDK paths (CI's `mcp` job covers those). The probes still use controlled fault
injection for F07, F08 and F20, as the report describes.

## Rerun

Write output outside both evidence folders:

```bash
python tools/audit/regression_probes.py --source . --output audit-rerun/probe-results.json --fail-on-observed
python tools/audit/run_selected_tests.py --source . --output audit-rerun/selected-tests.json
python tools/audit/benchmark_smoke.py --source . --output audit-rerun/benchmark-smoke.json
python -m unittest discover -s tests -p "test_*.py"
python evals/run.py --verbose
```
