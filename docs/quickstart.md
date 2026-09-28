# Quickstart

Ten minutes, one project. You will:
1. install breadcrumbs;
2. record one decision;
3. resume from it;
4. see *why* it surfaces;
5. retire it;
6. recover from a broken record on purpose.

Everything else is reference. [`operator-guide.md`](operator-guide.md) covers
running it day to day, and [`cli-spec.md`](cli-spec.md) documents every
command.

This page is executed: `python tools/quickstart_check.py` runs every `$`
line below, in order, against an installed `crumb`, and checks each exit code.
If this page drifts from the tool, CI fails.

## 1. Install and initialize

```console
$ pipx install crumb-kit            # or: pip install crumb-kit
$ cd your-project                   # any git repository
$ crumb init --session-tracking full --with-adapter=AGENTS.md
```

`init` creates `.project-memory/`: Markdown files you commit, review and
diff like code. `--with-adapter=AGENTS.md` adds a short signpost to
`AGENTS.md`, so an agent that reads it knows the store exists. Nothing else
changes until you ask:
- `--with-adapter` names the instruction file (`CLAUDE.md`, `AGENTS.md`, …);
- `--with-mcp` registers the MCP server;
- `--with-hooks` installs the Claude Code hooks.

`crumb doctor` exits 1 while no integration is wired up, because a store no
agent reads is the most common way to get nothing from it.

## 2. Record one decision

```console
$ crumb remember decision --title "Pricing cache TTL is five minutes" --set Decision "cache pricing responses for 300 seconds" --set Rationale "the upstream API rate-limits us" --evidence file src/pricing/cache.py --tags pricing,cache
```

A decision needs evidence (here, the file it is about) or
`--confidence low`. It is written to `.project-memory/decisions/` with an id
like `dec_YYYYMMDD_pricing-cache-ttl-is-five-minutes`, where the date is the
day it was written.

## 3. Resume

```console
$ crumb resume
```

The resume packet is what a new session reads first:
- active decisions;
- failed attempts not to retry;
- traps;
- open questions;
- the files that matter.

It is bounded (5,000 approx-tokens by default). Under Claude Code, the
`SessionStart` hook injects it for you.

## 4. See why a memory surfaces

```console
$ crumb search "pricing cache" --explain
$ crumb guard "change the pricing cache TTL" --files src/pricing/cache.py   # exit 10
$ crumb show dec_YYYYMMDD_pricing-cache-ttl-is-five-minutes
```

- **`search`** lists matches with their reasons: shared keywords, tags,
  files, "named in the record's title". `--explain` shows the stems your query
  became.
- **`guard`** answers `PROCEED`, `READ_FIRST`, `PAUSE` or `ASK_HUMAN`, and its
  exit code (0, 10, 15, 20) matches. Here it is `READ_FIRST` (10), because the
  file and the tags match. **A verdict is advice about what memory says, not
  an authorization.** `PROCEED` means no relevant memory, not "safe".
- **`show`** prints the whole record: what, why, evidence, who wrote it, on
  which branch and commit, and its review status.

## 5. Correct it, or retire it

A decision changed? Record the new one and say what it replaces:

```console
$ crumb remember decision --title "Pricing cache TTL is one minute" --set Decision "cache pricing responses for 60 seconds" --set Rationale "prices now change intraday" --evidence file src/pricing/cache.py --tags pricing,cache --supersedes dec_YYYYMMDD_pricing-cache-ttl-is-five-minutes
$ crumb resume
```

The old record stays, marked `superseded`, as history. The packet shows only
the new one. To retire a record without a replacement:

```console
$ crumb mark-status dec_YYYYMMDD_pricing-cache-ttl-is-one-minute stale --reason "pricing moved to the vendor SDK"
```

## 6. Recover from a broken record

Records are plain files, so they can be broken by hand. Try it: open the
retired decision's file in `.project-memory/decisions/` and change
`confidence: medium` to `confidence: certainly`.

<!-- quickstart-check: set-field decisions/*-pricing-cache-ttl-is-one-minute.md confidence certainly -->

```console
$ crumb validate                    # exit 1
```

`validate` names the file, the field and the rule. Put `medium` back:

<!-- quickstart-check: set-field decisions/*-pricing-cache-ttl-is-one-minute.md confidence medium -->

```console
$ crumb validate
$ crumb doctor
```

`doctor` checks the rest:
- integrations;
- a stale packet;
- the search index;
- unfinished operations (`crumb recover`);
- records that fail validation;
- a store this build cannot write;
- an outdated hook matcher.

Each finding names its fix. [`operator-guide.md`](operator-guide.md) covers
every recovery.

## Next

- **Using another agent** (Codex, Cursor, Gemini CLI, …)? See
  [`compatibility-matrix.md`](compatibility-matrix.md). It gets the files,
  the CLI and MCP; hooks are Claude Code's.
- **Working in a team?** `crumb policy set team` makes agent-written guidance
  a proposal for a person to `crumb review` (see
  [`security.md`](security.md) §4).
- **What breadcrumbs promises, and what it does not:** see
  [`continuity-contract.md`](continuity-contract.md).
