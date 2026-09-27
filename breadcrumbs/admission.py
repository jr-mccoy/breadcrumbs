"""breadcrumbs — who may do what to the store (audit F18, WP14).

`review_status: reviewed` and `agent: human` used to be claims anybody could
make. A record committed with them, or an MCP payload carrying them, looked
exactly like a person's review. And nothing separated routine capture from the
changes that make memory authoritative: promoting a rule into `CLAUDE.md`,
retiring a decision, quarantining a record.

**Two profiles**, chosen by the operator in `manifest.yml`
(`crumb policy set …`; no MCP tool can change them):

- **`solo`** (the default): one person and the agents they delegate to. It
  changes nothing: writes are admitted as they were, and review stays a
  convention.
- **`team`**: shared memory whose authority needs a person.
  - A guidance record (decision, attempt, verification or trap) written
    through MCP, a hook, or the CLI inside an agent session lands as a
    *proposal*, `review_status: needs-review`. It is written unattended and
    stays searchable and guard-visible, but it is not reviewed.
  - A high-impact status change (superseding, rejecting, quarantining, or
    leaving quarantine) is refused through MCP.
  - `crumb promote` requires a *valid* review (below).
  - The store declares `requires: review-profiles`, so a build that does not
    implement profiles refuses to write it (`compat.py`).

**`mcp_mode`** narrows what MCP may do: `write` (the solo default), `propose`
(every MCP guidance write is a proposal and high-impact changes are refused,
the team default) or `read-only` (no MCP writes at all; the server does not
even list the writing tools).

**Where identity comes from.** The channel (`cli`, `mcp` or `hook`) is set by
the transport that received the call, never by the payload. A payload may not
set `review_status`, `reviewed_by`, `reviewed_at` or `reviewed_hash`, and an
MCP or hook payload may not claim `agent: human`. Those are refused, not
silently dropped.

**A review is a stamp on content.** `crumb review <id>` records who reviewed,
when, and `reviewed_hash`, a digest of the record's content. A later edit makes
the review *stale*. A `review_status: reviewed` with no matching hash (typed by
hand, or imported from elsewhere) is only *claimed*. Neither counts as
authority in the team profile, so an old approval, or approving text inside a
record, never becomes permission for a new change.

**What this does not do** (security.md §4): it binds MCP clients and hooks,
which reach the store only through this code. An agent with a full shell can
edit files, the manifest or `CLAUDE.md` directly, and set any environment
variable; locally nothing can stop that. For those actors the boundary is Git
review of what they commit (CODEOWNERS or branch protection on
`.project-memory/` and the instruction files), which this module does not
replace.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

SOLO = "solo"
TEAM = "team"
PROFILES = (SOLO, TEAM)

MCP_WRITE = "write"
MCP_PROPOSE = "propose"
MCP_READ_ONLY = "read-only"
MCP_MODES = (MCP_WRITE, MCP_PROPOSE, MCP_READ_ONLY)

# The `requires:` feature a team-profile store declares (compat.KNOWN_FEATURES).
FEATURE = "review-profiles"

CHANNELS = ("cli", "mcp", "hook")

# Record types whose content steers work. Jots, sessions, questions and ideas
# are candidates, history or open ends; they never need review to be written.
GUIDANCE_TYPES = frozenset({"decision", "attempt", "verification", "trap"})

# Only `crumb review` writes these.
REVIEW_FIELDS = ("review_status", "reviewed_by", "reviewed_at", "reviewed_hash")
PAYLOAD_REVIEW_STATUSES = ("unreviewed", "needs-review")

# Status changes that change what memory authorizes.
HIGH_IMPACT_STATUSES = frozenset({"superseded", "rejected", "quarantined"})

# Excluded from the review digest: bookkeeping that changes without the claim
# changing (a review, a promotion, an index rebuild's timestamps).
_DIGEST_EXCLUDE = frozenset(
    {
        *REVIEW_FIELDS,
        "updated_at",
        "promoted_to",
        "promoted_at",
        "promoted_rule",
        "last_confirmed",
    }
)


class Refused(ValueError):
    """An action the store's policy does not admit from this channel."""


@dataclass(frozen=True)
class Policy:
    profile: str = SOLO
    mcp_mode: str = MCP_WRITE


@dataclass(frozen=True)
class Context:
    channel: str
    policy: Policy
    # Running inside an agent harness (MCP and hooks always are; the CLI is
    # when the environment names one). Detection is a claim the environment
    # makes, so it can only add caution, never grant authority.
    in_agent: bool


def policy(memory_dir: Path) -> Policy:
    """The store's policy from `manifest.yml`. An unknown value fails closed:
    an unknown profile reads as `team`, an unknown MCP mode as `read-only`."""
    from breadcrumbs import cli

    manifest = cli.load_manifest(Path(memory_dir)) or {}
    profile = str(manifest.get("review_profile") or SOLO).strip().lower()
    if profile not in PROFILES:
        profile = TEAM
    default_mode = MCP_PROPOSE if profile == TEAM else MCP_WRITE
    mode = str(manifest.get("mcp_mode") or default_mode).strip().lower()
    if mode not in MCP_MODES:
        mode = MCP_READ_ONLY
    return Policy(profile, mode)


# --------------------------------------------------------------------------- #
# The channel, set by the transport
# --------------------------------------------------------------------------- #

_local = threading.local()


@contextlib.contextmanager
def channel(name: str):
    """Mark the calls in the `with` body as arriving through `name`."""
    if name not in CHANNELS:
        raise ValueError(f"unknown channel {name!r}")
    previous = getattr(_local, "channel", None)
    _local.channel = name
    try:
        yield
    finally:
        _local.channel = previous


def current_channel() -> str:
    return getattr(_local, "channel", None) or "cli"


def context(memory_dir: Path, name: str | None = None) -> Context:
    from breadcrumbs import cli

    name = name or current_channel()
    in_agent = name != "cli" or cli.detect_agent() != cli.AGENT_UNKNOWN
    return Context(name, policy(memory_dir), in_agent)


# --------------------------------------------------------------------------- #
# Admission
# --------------------------------------------------------------------------- #


def is_proposal(ctx: Context, rtype: str) -> bool:
    """Does a write of `rtype` through `ctx` land as `needs-review`?"""
    if rtype not in GUIDANCE_TYPES:
        return False
    if ctx.channel == "mcp" and ctx.policy.mcp_mode == MCP_PROPOSE:
        return True
    return ctx.policy.profile == TEAM and ctx.in_agent


def review_status_for(memory_dir: Path, rtype: str) -> str:
    """The `review_status` a new record starts with, for the current channel."""
    return "needs-review" if is_proposal(context(memory_dir), rtype) else "unreviewed"


def check_write(ctx: Context, payload: dict | None) -> None:
    """Refuse a write this channel may not make, before anything is written."""
    payload = payload or {}
    if ctx.channel == "mcp" and ctx.policy.mcp_mode == MCP_READ_ONLY:
        raise Refused("this store's policy makes MCP read-only (mcp_mode: read-only)")
    for key in REVIEW_FIELDS:
        value = payload.get(key)
        if value in (None, ""):
            continue
        if key == "review_status" and value in PAYLOAD_REVIEW_STATUSES:
            continue
        raise Refused(
            f"{key} is set only by `crumb review` (a person, at the CLI), never by a "
            "payload; drop it and the record is written unreviewed"
        )
    agent = str(payload.get("agent") or "").strip().lower()
    if agent == "human" and ctx.channel != "cli":
        raise Refused(
            f"agent: human cannot be claimed through {ctx.channel}; the channel records "
            "who wrote it"
        )


def check_status_change(ctx: Context, old_status: str | None, new_status: str) -> None:
    """Refuse a high-impact status change through a channel the policy limits."""
    if ctx.channel == "mcp" and ctx.policy.mcp_mode == MCP_READ_ONLY:
        raise Refused("this store's policy makes MCP read-only (mcp_mode: read-only)")
    limited = ctx.channel == "mcp" and (
        ctx.policy.mcp_mode == MCP_PROPOSE or ctx.policy.profile == TEAM
    )
    if not limited:
        return
    if new_status in HIGH_IMPACT_STATUSES or old_status == "quarantined":
        raise Refused(
            f"marking a record {new_status} changes what memory authorizes; under this "
            f"store's policy ({ctx.policy.profile}, mcp_mode {ctx.policy.mcp_mode}) a "
            f"person does it: `crumb mark-status <id> {new_status} --reason …`"
        )


def check_promote(ctx: Context, meta: dict, body: str) -> None:
    """Promotion writes a standing rule every session loads. In the team
    profile it needs a review that still matches the record."""
    if ctx.policy.profile != TEAM:
        return
    state = review_state(meta, body)
    if state != "valid":
        why = {
            "none": "it has not been reviewed",
            "claimed": "its review is only claimed (no `crumb review` stamp matches it)",
            "stale": "it changed after it was reviewed",
        }[state]
        raise Refused(
            f"promotion needs a valid review in the team profile, and {why}. A person "
            f"runs `crumb review {meta.get('id')}` first"
        )


# --------------------------------------------------------------------------- #
# Review stamps
# --------------------------------------------------------------------------- #


def content_digest(meta: dict, body: str) -> str:
    """What a review covers: the claim, not its bookkeeping."""
    kept = {k: meta[k] for k in sorted(meta) if k not in _DIGEST_EXCLUDE}
    blob = json.dumps(kept, sort_keys=True, default=str) + "\n" + (body or "").strip()
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def review_state(meta: dict, body: str) -> str:
    """`valid`, `stale` (edited since), `claimed` (says reviewed, no stamp that
    matches), or `none`."""
    if meta.get("review_status") != "reviewed":
        return "none"
    stamp = meta.get("reviewed_hash")
    if not stamp or not meta.get("reviewed_by"):
        return "claimed"
    return "valid" if stamp == content_digest(meta, body) else "stale"


def default_reviewer(root: Path) -> str:
    """Who is reviewing, when `--reviewer` is not given: git's user.email, else
    the OS user. A label the person running the command supplies, not proof."""
    from breadcrumbs import cli

    email = cli._git_out(Path(root), "config", "user.email")
    return (email or "").strip() or cli.current_user()


def review_record(memory_dir: Path, root: Path, rid: str, reviewer: str | None = None) -> dict:
    """Stamp `rid` as reviewed by `reviewer`: `crumb review` (a person, at the CLI).

    In the team profile, refused inside an agent session: review is a person's
    act. That is friction, not enforcement; an agent with a shell can unset
    the environment (see the module docstring).
    """
    from breadcrumbs import cli, path_policy, promote

    memory_dir, root = Path(memory_dir), Path(root)
    ctx = context(memory_dir, "cli")
    if ctx.policy.profile == TEAM and ctx.in_agent:
        return {
            "ok": False,
            "error": "review is a person's act; in the team profile it is refused inside an "
            "agent session. Run `crumb review` in your own terminal",
        }
    item = cli.find_item(memory_dir, rid)
    if item is None:
        return {"ok": False, "error": f"no record with id {rid!r}"}
    path = Path(item.get("path") or "")
    if (
        item["kind"] not in GUIDANCE_TYPES
        or path.suffix != ".md"
        or path.parent.name not in cli.DIR_TYPES
    ):
        return {
            "ok": False,
            "error": f"{item['id']} is a {item['kind']}; review takes decisions, attempts, verifications and traps (one file each)",
        }
    meta, body = cli.parse_frontmatter(path_policy.read_text(path))
    who = (reviewer or "").strip() or default_reviewer(root)
    fields = {
        "review_status": "reviewed",
        "reviewed_by": who,
        "reviewed_at": cli.now_iso(),
        "reviewed_hash": content_digest(meta, body),
    }
    result = promote._set_fields(memory_dir, {**item, "path": str(path)}, fields)
    if not result.get("ok", True):
        return result
    return {
        "ok": True,
        "id": item["id"],
        "reviewed_by": who,
        "reviewed_hash": fields["reviewed_hash"],
    }


def set_policy(memory_dir: Path, profile: str, mcp_mode: str | None = None) -> dict:
    """Write the store's policy into `manifest.yml` (`crumb policy set`).

    The team profile also declares `requires: review-profiles`, so a build
    that does not implement profiles refuses to write the store. Changing the
    policy is an operator's act: refused inside an agent session.
    """
    from breadcrumbs import cli, compat

    memory_dir = Path(memory_dir)
    if profile not in PROFILES:
        return {"ok": False, "error": f"profile must be one of {', '.join(PROFILES)}"}
    if mcp_mode is not None and mcp_mode not in MCP_MODES:
        return {"ok": False, "error": f"--mcp-mode must be one of {', '.join(MCP_MODES)}"}
    if context(memory_dir, "cli").in_agent:
        return {
            "ok": False,
            "error": "the review policy is operator configuration; it is not changed from "
            "inside an agent session. Run `crumb policy set` in your own terminal",
        }
    path = memory_dir / "manifest.yml"
    manifest = cli.load_manifest(memory_dir) or {}
    features = set(compat.parse_features(manifest.get(compat.REQUIRES_KEY)))
    if profile == TEAM:
        features.add(FEATURE)
    else:
        features.discard(FEATURE)
    values = {
        "review_profile": profile,
        "mcp_mode": mcp_mode or (MCP_PROPOSE if profile == TEAM else MCP_WRITE),
        compat.REQUIRES_KEY: ", ".join(sorted(features)) if features else None,
    }
    lines = cli.read_text_lenient(path)[0].splitlines()
    out, seen = [], set()
    for line in lines:
        key = (
            line.split(":", 1)[0].strip()
            if ":" in line and not line.lstrip().startswith("#")
            else None
        )
        if key in values:
            seen.add(key)
            if values[key] is not None:
                out.append(f"{key}: {values[key]}")
            continue
        out.append(line)
    for key, value in values.items():
        if key not in seen and value is not None:
            out.append(f"{key}: {value}")
    cli.write_text_atomic(path, "\n".join(out).rstrip("\n") + "\n")
    return {"ok": True, **{k: v for k, v in values.items()}}
