# Current State

_What matters right now. Lifespan: days to ~2 weeks. Keep it short and true._

## Current Focus

Splitting the ingest worker out of the API process.

## Recently Changed

- Moved the queue consumer behind a feature flag
- Two developers now share this store from different checkout paths

## Watch Out For

Nothing in a committed projection may depend on one machine: no absolute paths,
and no hash over `sessions/`, which this store keeps local.
