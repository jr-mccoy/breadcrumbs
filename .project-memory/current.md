# Current State

_What matters right now. Lifespan: days to ~2 weeks. Keep it short and true._

## Current Focus
Stabilization per the 2026-09-26 audit roadmap (WP00-04 done; WP05 awaiting review)

## Recently Changed
WP05: store lock rewritten on OS locks (flock/msvcrt) over permanent private/.store.lock, no heartbeat/staleness; projection publication locked (resume prints regardless, publishes within 0.5 s, reports publication); init --force keeps lock files; index builds in a unique temp file. 10 real-process tests; suite green; lock tests stable over 5 runs.

## Watch Out For
