# Current State

_What matters right now. Lifespan: days to ~2 weeks. Keep it short and true._

## Current Focus
Stabilization per the 2026-09-26 audit roadmap (WP00-05 done; WP06 awaiting review)

## Recently Changed
WP06: new breadcrumbs/mutations.py (write-ahead before-image journal, rollback on failure, nested transactions doom the parent, crash recovery keeping copies, RevisionConflict). All multi-record writers are single operations; retire_all raises on failed retirement; crumb recover; doctor operations/projections rows. 10 tests incl. real crash-after-every-write loop; suite green.

## Watch Out For
