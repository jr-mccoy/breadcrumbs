# WP05: writer coordination and lock ownership (2026-09-27)

This implements work package WP05 of the
[audit roadmap](../2026-09-26-breadcrumbs-audit-and-roadmap.md), findings F06 and
F08. The starting commit is `16aa8f1`, after WP04.

## Cause

- **F08: the lock could be taken from a live writer.** The store lock was an
  exclusive-create file (`private/.write-lock`) holding a pid, a time and a
  host. The holder touched it every 15 s, and `_is_stale` judged it by **age
  first**: a lock untouched for 60 s was stale and could be broken, even if its
  writer was alive. A suspended process, a missed heartbeat or a clock jump let
  a second writer in while the first could still resume and publish.
- **F06: `resume` published without the lock.** `crumb resume` was exempt from
  the lock (`_needs_lock`), yet ran `try_reindex_projections`. That republishes
  `resume-packet.md`, `guard-prefilter.json`, `related.json` and
  `conflicts.json` and rebuilds the SQLite search index: five writes, each
  atomic, none coordinated. The index builder also used one fixed `.tmp` name,
  so two builders would share a file.

## Change

**`breadcrumbs/lock.py` (rewritten).**
- The cross-process lock is an **OS lock**: `fcntl.flock` on POSIX,
  `msvcrt.locking` on Windows. It sits on a permanent file,
  `private/.store.lock`.
- The kernel releases it when the holder exits, however that happens.
- The heartbeat, the age rule, the stale-breaker and the `.break` file are gone.
  The file is never unlinked, so every writer locks the same inode.
- The pid, time and host written into it serve error messages only.
- Thread serialisation, re-entrancy and the CLI, hook and MCP timeouts are
  unchanged.
- A filesystem that refuses an OS lock raises `LockUnsupported` (a
  `StoreLocked`), so the write is refused rather than run uncoordinated.
- For version skew, a fresh 0.3.0-era `.write-lock` held by a live process is
  waited on, never removed. The OS lock uses a new file name, because an older
  version breaks and deletes a `.write-lock` it thinks is stale.

**`cli.try_reindex_projections`.** Publication is now a locked write. A caller
already holding the lock (every writer) re-enters for free. Any other caller
waits at most `lock_timeout` and otherwise publishes nothing, returning
`(False, "not published: store is locked by pid N; …")`. The body moved to
`_publish_projections`.

**`crumb resume`.**
- It always builds and prints the packet.
- It publishes only if it can take the lock within `HOOK_TIMEOUT` (0.5 s), so a
  session still starts promptly while another one writes.
- `--json` adds `publication: {published, reason}`; a skipped publish also
  warns on stderr.

**`init --force`.** It keeps both lock files while replacing the store
(`_replace_store_contents`).

**`searchindex.build_index`.** It builds in a unique `mkstemp` file and removes
it on failure.

**Docs.** The lock sections of `cli-spec.md` (*Store write lock*),
`architecture.md`, `record-schema.md`, `README.md`, and the error text in
`mcp-spec.md` are updated. The error now reads "try again shortly", not "or
remove a stale lock", since deleting the file no longer releases anything.

## Tests

**`tests/test_lock_processes.py`** has 10 tests using real processes, including
the four the roadmap names:

- `test_resume_does_not_publish_under_foreign_writer`: a separate process holds
  the lock. `resume --json` exits 0 within 3.5 s and prints a packet that
  includes a new record. All four projections are byte-identical, and
  `publication` names the holder's pid. After release, the next resume
  publishes.
- `test_process_death_releases_os_lock`: the holder is killed with SIGKILL and
  the lock is taken in under 1 s.
- `test_live_owner_is_not_stolen_after_clock_gap`: the lock file is backdated an
  hour and this process's clock jumped an hour; neither this process nor
  another can take it.
- `test_force_init_preserves_coordination`: `init --force` under a foreign
  holder is refused and the store is intact. Uncontended, it keeps the same lock
  inode.

Also covered:
- a SIGSTOP-suspended holder keeps its lock;
- six parallel `crumb jot` processes: every acknowledged write is on disk and
  `validate` is clean;
- three parallel `reindex` processes leave consistent projections and no temp
  files;
- a live legacy lock is waited on and never removed, and an ancient one is
  ignored;
- a filesystem refusing locks is reported.

Against the pre-change `lock.py`, `cli.py` and `searchindex.py`, the two core
findings fail behaviorally: the clock-gap lock is taken, and resume publishes
under a foreign lock. Four more tests error on APIs that did not exist. The
five-run repeat was clean.

**`tests/_lockproc.py`** (a helper) spawns real lock holders and probes.

**Updated tests.**
- `test_lock.py`: tests of file existence, the heartbeat and the stale-breaker
  described the removed mechanism. Replaced by exclusion checked from a second
  process, re-entrancy, and `init --force` keeping the same inode while
  exclusive.
- The "foreign holder" fixture in `test_lock.py` and `test_hooklog.py` used to
  write a live pid into the lock file. It is now a process that holds the lock.

## Results

| Command | Exit | Result |
|---|---|---|
| `python -m unittest discover -s tests -p "test_*.py"` (3.11.15) | 0 | 1224 run, 0 failures, 6 skipped |
| `test_lock test_lock_processes test_hooklog test_init` on 3.9.23 | 0 | OK |
| `test_lock_processes test_lock` ×5 | 0 | OK every run |
| `python evals/run.py` | 0 | Unchanged |
| `regression_probes.py … --fail-on-observed` | 2 | 13 defect signals, **2 probe errors** (below) ([probe-results.json](probe-results.json)) |
| CI `test` job fixture steps, replayed | 0 | All 7 pass |
| `ruff check . && ruff format --check .` (0.16.1) | 0 | Clean |

### Both lock probes are now invalid instruments

These are not repairs shown by the probes; the audit scripts are kept
byte-identical.

- **`live_lock_stale` errors.** It patches `lock.STALE_SECONDS` and calls
  `lock._is_stale`, and neither exists: there is no staleness rule left to
  mis-classify a live owner. The test above covers the property it probed.
- **`resume_ignores_lock` still reports a defect, but that is a false
  positive.** It simulates a foreign holder by writing a live pid into
  `lock.lock_path(mem)`. Under an OS lock, writing a pid into the file holds
  nothing, so resume correctly takes the free lock and publishes.
  `test_resume_does_not_publish_under_foreign_writer` runs the same scenario
  with a process that really holds the lock, and resume does not publish.

## Compatibility

- **New lock file.** It is `private/.store.lock`, which is gitignored under
  `private/**` like the old one. A leftover `.write-lock` from an older version
  is ignored once untouched for 60 s, and is never deleted.
- **Mixed versions.** This version waits for a live older writer; an older
  version does **not** wait for this one. Run one crumb-kit version per
  checkout.
- **`resume` can skip publishing.** Under contention it still prints the packet
  but may leave `generated/` untouched; the next writer or resume publishes.
  `--json` gains `publication`.
- **A stuck lock is released differently.** A stuck-but-alive holder keeps the
  lock until it exits; deleting the file no longer helps. Kill the process.
- **Non-local filesystems.** A store on a filesystem without OS locks now
  refuses writes, where before it silently used the file protocol.

## Limits

- **Windows is untested.** The `msvcrt.locking` path is not exercised here;
  native qualification is WP17.
- **Filesystem support.** Only local filesystems are supported. NFS and SMB
  emulate `flock` with varying guarantees, and sync-managed folders do not
  coordinate across machines at all.
- **Private state stays outside the lock.** Telemetry (`private/usage.json`)
  and hook state files (miner cursor, prompt state) are still written without
  it. They are machine-local, best-effort state and belong to WP09 and WP12.
- **Locking is not snapshotting.** `resume` still builds its printed packet from
  records read without the lock. A coherent snapshot and a provenance stamp that
  matches it are WP07.
