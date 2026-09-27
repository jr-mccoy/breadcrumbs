# Current State

_What matters right now. Lifespan: days to ~2 weeks. Keep it short and true._

## Current Focus
Stabilization per the 2026-09-26 audit roadmap (WP00-03 done; WP04 awaiting review)

## Recently Changed
WP04: new breadcrumbs/checks.py (CheckResult, assertion spec 1, settle, bounded process-group runner). Recheck settles only via assertions (verify --assert, or --bind-commands); command evidence is a diagnostic; test evidence never executed; inconclusive runs write nothing; settled records keep scope/branch/confidence; branch claims not rechecked from another branch. 16 new tests; suite green.

## Watch Out For
