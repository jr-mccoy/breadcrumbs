"""The application layer (audit WP16, finding F21).

The CLI, the MCP server and the hooks are transports. What they do to a store
is one set of operations here, each run inside an explicit `Context`:

- `root` and `memory_dir`: which store;
- `channel`: `cli`, `mcp` or `hook`, set by the transport (it decides
  admission, `breadcrumbs.admission`);
- `clock`: the time source for the operation (None: the real clock);
- `agent`: the author label the transport vouches for.

`active(ctx)` makes those current for one operation: the admission channel,
the clock, the store's search aliases (per thread, so two contexts never share
them) and one parse cache (`cli.operation`). Every function below enters it,
so a caller never has to.

Transports stay at the edges: argument parsing, prompts, output formatting,
exit codes and host payload mapping. Documented differences between them (the
CLI refuses an unstated confidence without evidence, MCP records it as `low`)
are applied by the adapter before it calls in, and error text is worded by the
adapter from a `ServiceError`'s `kind`.

This module imports the domain functions, which still live in `cli.py`, but
not the argument parser (`breadcrumbs.cli_parser`), and it never prints.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from breadcrumbs import admission, cli
from breadcrumbs import packet as _packet
from breadcrumbs import textmatch as _textmatch
from breadcrumbs import scoring as _scoring

RECORD_TYPES = ("decision", "attempt")


class ServiceError(Exception):
    """An operation that did not happen, and why.

    `kind` is what an adapter maps to its own wording and exit code:
    `missing-store`, `usage`, `refused` (policy), `needs-evidence`,
    `duplicate`, `invalid` (the writer refused a value), `rejected`
    (`validate` refused the new record) or `failed` (a multi-record change
    rolled back). `data` carries structured detail (`duplicates`, …).
    """

    def __init__(self, kind: str, message: str, **data):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.data = data


@dataclass(frozen=True)
class Context:
    root: Path
    memory_dir: Path
    channel: str = "cli"
    clock: Callable[[], datetime] | None = None
    agent: str | None = None

    def admission(self) -> admission.Context:
        """This store's policy as it applies to this channel, read now."""
        return admission.context(self.memory_dir, self.channel)


def open_context(
    root: str | Path | None = None,
    *,
    channel: str = "cli",
    clock: Callable[[], datetime] | None = None,
    agent: str | None = None,
) -> Context:
    """A context for the store at `root` (resolved like `--project`)."""
    if channel not in admission.CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    project_root = cli.resolve_root(str(root) if root is not None else None)
    return Context(project_root, project_root / cli.MEMORY_DIRNAME, channel, clock, agent)


@contextlib.contextmanager
def active(ctx: Context):
    """Make `ctx` current for one operation (re-entrant)."""
    with (
        admission.channel(ctx.channel),
        cli.clock(ctx.clock),
        _textmatch.store_aliases(ctx.memory_dir),
        cli.operation(),
    ):
        yield ctx


def _require_store(ctx: Context) -> None:
    if not ctx.memory_dir.is_dir():
        raise ServiceError(
            "missing-store",
            f"no {cli.MEMORY_DIRNAME}/ found at {ctx.root}. Run `crumb init` first.",
        )


# --------------------------------------------------------------------------- #
# Admission
# --------------------------------------------------------------------------- #


def admit(ctx: Context, payload: dict | None = None, *, supersedes: str | None = None) -> None:
    """Raise `ServiceError('refused')` when this channel may not make the write.

    One decision for every transport: the payload's review fields and `agent`
    claim, the channel's MCP mode, and superseding as a high-impact change.
    """
    actx = ctx.admission()
    try:
        admission.check_write(actx, payload)
        if supersedes:
            admission.check_status_change(actx, "active", "superseded")
    except admission.Refused as exc:
        raise ServiceError("refused", str(exc)) from None


def review_status_for(ctx: Context, rtype: str) -> str:
    """The `review_status` a new `rtype` record written through `ctx` starts with."""
    return "needs-review" if admission.is_proposal(ctx.admission(), rtype) else "unreviewed"


# --------------------------------------------------------------------------- #
# Writes
# --------------------------------------------------------------------------- #


def record(ctx: Context, rtype: str, payload: dict, *, operation: str = "remember") -> dict:
    """Write a decision or attempt: admission, the evidence rule, the
    supersede check, the near-duplicate gate, the write, the `validate` gate,
    retirement of what it supersedes (one change, audit F20), and the reindex.

    `payload`: `title`, `sections`, `evidence`, `tags`, `confidence`,
    `privacy`, `scope`, `status`, `agent`, `supersedes`, `allow_duplicate`.
    The author is `payload['agent']`, else `ctx.agent`; the retirement is
    attributed to `ctx.agent`, else the payload's.

    `operation` names the change in the mutation journal (`remember`,
    `memory_record`). Returns `{id, type, slug, confidence, path, meta}` plus
    `supersedes` and `demoted` when it replaced a record.
    """
    from breadcrumbs import lifecycle, mutations

    with active(ctx):
        _require_store(ctx)
        if rtype not in RECORD_TYPES:
            raise ServiceError("usage", "type must be 'decision' or 'attempt'", field="type")
        payload = dict(payload or {})
        supersedes = payload.get("supersedes")
        admit(ctx, payload, supersedes=supersedes)
        title = payload.get("title")
        if not title:
            raise ServiceError("usage", "a title is required", field="title")
        sections = dict(payload.get("sections") or {})
        evidence = list(payload.get("evidence") or [])
        tags = list(payload.get("tags") or [])
        confidence = payload.get("confidence")
        if not evidence and confidence != "low":
            raise ServiceError("needs-evidence", f"a {rtype} needs evidence or low confidence")

        memory_dir, root = ctx.memory_dir, ctx.root
        problem = lifecycle.check_supersedes(memory_dir, rtype, supersedes)
        if problem:
            raise ServiceError("usage", problem)
        if not supersedes and not payload.get("allow_duplicate"):
            dups = lifecycle.find_near_duplicates(
                memory_dir,
                rtype,
                title,
                "\n".join(str(v) for v in sections.values()),
                files=[
                    e.get("ref")
                    for e in evidence
                    if isinstance(e, dict) and e.get("type") in ("file", "path")
                ],
                tags=tags,
            )
            if dups:
                raise ServiceError(
                    "duplicate",
                    lifecycle.duplicate_message(dups),
                    duplicates=dups,
                )

        author = payload.get("agent") or ctx.agent
        retirer = ctx.agent if ctx.agent is not None else payload.get("agent")
        try:
            with mutations.transaction(memory_dir, operation):
                try:
                    path, meta = cli.write_record(
                        memory_dir,
                        root,
                        rtype,
                        title,
                        sections,
                        tags=tags,
                        evidence=evidence,
                        confidence=confidence,
                        privacy=payload.get("privacy"),
                        scope=payload.get("scope"),
                        status=payload.get("status"),
                        agent=author,
                        extra={"supersedes": [supersedes]} if supersedes else None,
                    )
                except ValueError as exc:
                    raise ServiceError("invalid", str(exc)) from None
                fails = cli._validate_new_file(memory_dir, path)
                if fails:
                    path.unlink()
                    raise ServiceError(
                        "rejected", "; ".join(f["message"] for f in fails), findings=fails
                    )
                demoted: list[str] = []
                if supersedes:
                    demoted = lifecycle.demoted_ids(
                        lifecycle.retire_all(memory_dir, [supersedes], meta["id"], agent=retirer)
                    )
        except mutations.MutationFailed as exc:
            raise ServiceError("failed", mutations.describe(exc)) from None
        # Reindex-on-write: keep generated/ in step with the new record.
        cli.reindex_projections(memory_dir, root)
        out = {
            "id": meta["id"],
            "type": rtype,
            "slug": meta["slug"],
            "confidence": meta["confidence"],
            "path": path,
            "meta": meta,
        }
        if supersedes:
            out["supersedes"] = [supersedes]
        if demoted:
            out["demoted"] = demoted
        return out


def mark_status(
    ctx: Context,
    rid: str,
    status: str,
    reason: str,
    *,
    superseded_by: str | None = None,
    agent: str | None = None,
) -> dict:
    """Change a record's status, if this channel may make that change.

    Returns what `cli.set_record_status` returns (`{ok, …}`); a policy
    refusal raises `ServiceError('refused')`.
    """
    with active(ctx):
        _require_store(ctx)
        item = cli.find_item(ctx.memory_dir, rid)
        old = (item or {}).get("status")
        try:
            admission.check_status_change(ctx.admission(), old, status)
        except admission.Refused as exc:
            raise ServiceError("refused", str(exc)) from None
        return cli.set_record_status(
            ctx.memory_dir,
            rid,
            status,
            reason,
            agent=agent or ctx.agent,
            superseded_by=superseded_by,
        )


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #


def search(
    ctx: Context,
    query: str,
    *,
    files: list[str] | None = None,
    filters: dict | None = None,
    include_ideas: bool = True,
    **kwargs,
) -> tuple[list[dict], dict]:
    """`scoring.search` in this context: `(matches, by_id)`."""
    with active(ctx):
        _require_store(ctx)
        return _scoring.search(
            ctx.memory_dir,
            ctx.root,
            query,
            files=files,
            filters=filters or {},
            include_ideas=include_ideas,
            **kwargs,
        )


def guard(ctx: Context, action: str, *, files: list[str] | None = None, **kwargs) -> dict:
    """`scoring.guard` in this context: the verdict and what drove it."""
    with active(ctx):
        _require_store(ctx)
        return _scoring.guard(ctx.memory_dir, ctx.root, action, files=files, **kwargs)


def resume_packet(ctx: Context, **kwargs) -> dict:
    """`packet.build_resume_packet` in this context."""
    with active(ctx):
        _require_store(ctx)
        return _packet.build_resume_packet(ctx.memory_dir, ctx.root, **kwargs)


def prompt_lookup(ctx: Context, prompt: str, *, limit: int):
    """The prompt hook's lookup (`retrieval.prompt_lookup`) in this context."""
    from breadcrumbs import retrieval

    with active(ctx):
        return retrieval.prompt_lookup(ctx.memory_dir, ctx.root, prompt, limit=limit)
