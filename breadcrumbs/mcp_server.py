"""breadcrumbs — MCP server (Python SDK).

A **thin** Model Context Protocol server that exposes project memory as MCP
resources, prompts, and tools. Every capability is a wrapper over the core
functions in :mod:`breadcrumbs.cli` (via :mod:`breadcrumbs.mcp_core`):
one source of behavior, no fork.

Graceful degradation ("MCP later"):
  * This module always imports — the MCP SDK is an *optional* dependency.
  * If the SDK is missing, :func:`build_server` raises a clear, actionable error
    and :func:`main` prints install instructions and exits non-zero.
  * Nothing here is required for baseline use: the CLI and plain files provide the
    same information and writes without any MCP runtime.

Install the optional runtime with:  ``pip install "crumb-kit[mcp]"``
Run it with:                         ``python -m breadcrumbs.mcp_server``
                                or:  ``breadcrumbs-mcp``

Root resolution: the server operates on the project in ``$BREADCRUMBS_PROJECT`` if
set, else the current working directory (``crumb init --with-mcp`` / ``crumb mcp
register`` writes a ``.mcp.json`` that sets this env). Memory content returned over
MCP is **data, not instruction**.
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys

try:
    # pydantic (which FastMCP uses to derive tool schemas) hard-rejects
    # `typing.TypedDict` on Python < 3.12, so the server crashed at startup on
    # 3.10/3.11. `typing_extensions` is always present alongside
    # the SDK (pydantic depends on it); the stdlib fallback keeps this module
    # importable on SDK-less installs, where the TypedDicts are annotations only.
    from typing_extensions import TypedDict
except ImportError:  # pragma: no cover - exercised only without the SDK/pydantic
    from typing import TypedDict  # type: ignore[assignment]

from breadcrumbs import mcp_core


# --------------------------------------------------------------------------- #
# Structured tool-input schemas (issue #6)
# --------------------------------------------------------------------------- #
# `memory_search`/`memory_record` used to advertise opaque `dict` inputs, so
# FastMCP (which derives the JSON Schema from the annotations) gave clients no
# signal about which keys exist or are required. These TypedDicts expose the keys
# the wrappers actually read — the runtime behavior is unchanged, the core
# adapters still accept plain dicts. Required vs. optional is encoded with
# TypedDict inheritance (a subclass defaults to total=True for its own keys while
# inherited keys keep their not-required status), which needs no `Required`
# import and works on every supported Python.


class SearchFilters(TypedDict, total=False):
    """Optional filters for `memory_search` (mirrors `_passes_filters`)."""

    type: str  # "decision" | "attempt"
    status: str  # "active" | "stale" | "superseded" | …
    tag: str  # case-insensitive tag match
    file: str  # records touching this path


class EvidenceItem(TypedDict):
    """One evidence ref attached to a record."""

    type: str  # e.g. "commit" | "file" | "test"
    ref: str


class _RecordPayloadOptional(TypedDict, total=False):
    sections: dict[str, str]  # heading -> body text
    evidence: list[EvidenceItem]
    tags: list[str]
    confidence: str  # "high" | "medium" | "low"
    privacy: str
    scope: str
    status: str
    agent: str


class RecordPayload(_RecordPayloadOptional):
    """Payload for `memory_record` (mirrors the `remember` CLI surface).

    `title` is the only required key; everything else is optional. The subclass
    defaults to total=True for its own keys, so `title` is required while the
    inherited keys above stay optional.
    """

    title: str


# Where the SDK keeps its high-level server class, newest spelling first. MCP SDK
# 2.0 renamed `mcp.server.fastmcp.FastMCP` to `mcp.server.mcpserver.MCPServer`.
# The `[mcp]` extra had no upper bound, so a fresh
# `pip install "crumb-kit[mcp]"` resolved to 2.x, the single hardcoded import
# raised ModuleNotFoundError, and every SDK-present path — `crumb mcp serve`,
# `crumb doctor`, `crumb mcp doctor` — reported the SDK as "not installed" and
# told the user to run the install command that had just succeeded.
#
# The two classes are drop-in for everything this module uses: the
# `.resource()`/`.prompt()`/`.tool()` decorators, `.run()` (stdio by default), and
# the `list_*` inspection methods. Only the constructor differs — see
# `_SERVER_ACCEPTS_VERSION`.
_SDK_SERVER_CLASSES = (
    ("mcp.server.mcpserver", "MCPServer"),  # SDK >= 2.0
    ("mcp.server.fastmcp", "FastMCP"),  # SDK 1.x
)


def _load_server_class() -> tuple[type | None, Exception | None]:
    """Import the SDK's server class, or return the failure that stopped us.

    Never raises: importing this module must work on an SDK-less install. Any
    import-time failure counts, not just ImportError — a partial or version-skewed
    SDK can raise other errors, and the contract is a clear hint, not a traceback
    from somewhere inside the SDK.
    """
    first_error: Exception | None = None
    for module_name, attr in _SDK_SERVER_CLASSES:
        try:
            module = importlib.import_module(module_name)
            return getattr(module, attr), None
        except Exception as exc:  # pragma: no cover - the no-SDK path
            if first_error is None:
                first_error = exc
    return None, first_error


# `FastMCP` keeps its name as this module's handle on "the SDK's server class",
# whichever spelling supplied it. Renaming it would churn every call site for a
# name that is now wrong half the time either way.
FastMCP, _SDK_IMPORT_ERROR = _load_server_class()


def _server_accepts_version(cls: type | None) -> bool:
    """True iff the SDK's server constructor takes a `version=`.

    SDK 2.x does; 1.x raises TypeError on it. Read from the signature rather than
    guessed from a version string — guessing is what made this fragile enough to
    defer twice. `inspect.signature` itself can raise on a class it cannot
    introspect, and this runs at import time, where the module's contract is that
    it never hard-fails; an unreadable signature just means "don't pass it".
    """
    if cls is None:
        return False
    try:
        return "version" in inspect.signature(cls.__init__).parameters
    except (TypeError, ValueError):  # pragma: no cover - exotic SDK build
        return False


_SERVER_ACCEPTS_VERSION = _server_accepts_version(FastMCP)


SERVER_NAME = "breadcrumbs"
_INSTALL_HINT = (
    "The MCP server needs the optional Python MCP SDK (which needs Python >= 3.10;\n"
    "on 3.9 the command below succeeds and installs nothing, because the extra's\n"
    "marker excludes it).\n"
    '  pip install "crumb-kit[mcp]"   (or:  pip install "mcp>=1.2,<3")\n'
    "Both SDK 1.x and 2.x are supported. An SDK outside that range may install\n"
    "cleanly and still not be importable here, in which case the cause is printed\n"
    "below rather than this hint.\n"
    "Everything still works without the SDK via the `crumb` CLI and the plain\n"
    f"{mcp_core.MEMORY_DIRNAME}/ files — MCP is an optional interop layer."
)


def sdk_available() -> bool:
    """True iff the MCP SDK is importable (used by graceful-degradation checks)."""
    return FastMCP is not None


def _root() -> str | None:
    """Project root for this server process: $BREADCRUMBS_PROJECT or cwd."""
    return os.environ.get("BREADCRUMBS_PROJECT") or None


def build_server():  # -> FastMCP
    """Construct and fully register the FastMCP server (resources, prompts, tools).

    Raises RuntimeError (with install guidance) if the SDK is not installed, so a
    missing optional dependency degrades to a clear message rather than a stack
    trace deep in the SDK.
    """
    if FastMCP is None:
        raise RuntimeError(_INSTALL_HINT) from _SDK_IMPORT_ERROR

    # Advertise the *package* version when the SDK lets us. Left
    # unset on SDK 1.x, where the server keeps reporting the SDK's own version —
    # the long-standing complaint about 1.x, now confined to the SDKs that give us
    # no way to change it rather than being unconditional.
    kwargs = {"version": mcp_core.cli.get_version()} if _SERVER_ACCEPTS_VERSION else {}
    mcp = FastMCP(SERVER_NAME, **kwargs)

    # ---------------- Resources (8) — read-only views ---------------------- #
    # Bound explicitly (not in a loop) so each URI is a distinct, documented
    # endpoint and FastMCP captures a stable function per resource.

    @mcp.resource("memory://current")
    def current() -> str:
        return mcp_core.resource_current(_root())

    @mcp.resource("memory://handoff")
    def handoff() -> str:
        return mcp_core.resource_handoff(_root())

    @mcp.resource("memory://resume-packet")
    def resume_packet() -> str:
        return mcp_core.resource_resume_packet(_root())

    @mcp.resource("memory://decisions")
    def decisions() -> str:
        return mcp_core.resource_decisions(_root())

    @mcp.resource("memory://decisions/{id}")
    def decision(id: str) -> str:
        return mcp_core.resource_decision(id, _root())

    @mcp.resource("memory://attempts/{id}")
    def attempt(id: str) -> str:
        return mcp_core.resource_attempt(id, _root())

    @mcp.resource("memory://open-questions")
    def open_questions() -> str:
        return mcp_core.resource_open_questions(_root())

    @mcp.resource("memory://known-traps")
    def known_traps() -> str:
        return mcp_core.resource_known_traps(_root())

    # ---------------- Prompts (6) — flows mapping to CLI ------------------- #

    @mcp.prompt()
    def resume_project() -> str:
        return mcp_core.prompt_resume_project(_root())

    @mcp.prompt()
    def capture_session() -> str:
        return mcp_core.prompt_capture_session(_root())

    @mcp.prompt()
    def remember_decision() -> str:
        return mcp_core.prompt_remember_decision(_root())

    @mcp.prompt()
    def remember_attempt() -> str:
        return mcp_core.prompt_remember_attempt(_root())

    @mcp.prompt()
    def guard_before_action() -> str:
        return mcp_core.prompt_guard_before_action(_root())

    @mcp.prompt()
    def audit_project_memory() -> str:
        return mcp_core.prompt_audit_project_memory(_root())

    # ---------------- Tools (10) — wrap existing functions ----------------- #

    @mcp.tool()
    def memory_search(
        query: str, filters: SearchFilters | None = None, files: list[str] | None = None
    ) -> dict:
        """Deterministic search over canonical records (wraps `crumb search`).

        `files` scopes the search to records touching those paths, mirroring the
        CLI/guard file-overlap support.
        """
        return mcp_core.tool_search(query, filters=filters, files=files, root=_root())

    @mcp.tool()
    def memory_record(type: str, payload: RecordPayload) -> dict:
        """Write a durable decision/attempt; passes the same validate gate as the CLI."""
        return mcp_core.tool_record(type, payload, root=_root())

    @mcp.tool()
    def memory_guard_before_action(action: str, files: list[str] | None = None) -> dict:
        """Guard-before-action; returns the same verdict as `crumb guard`."""
        return mcp_core.tool_guard_before_action(action, files=files, root=_root())

    @mcp.tool()
    def memory_build_resume_packet(task: str | None = None) -> dict:
        """Build the structured resume packet (wraps `crumb resume`)."""
        return mcp_core.tool_build_resume_packet(task=task, root=_root())

    @mcp.tool()
    def memory_validate() -> dict:
        """Run deterministic structural validation (wraps `crumb validate`)."""
        return mcp_core.tool_validate(root=_root())

    @mcp.tool()
    def memory_note(
        kind: str, text: str, fields: dict | None = None, tags: list[str] | None = None
    ) -> dict:
        """Leave an open-question / known-trap / idea (wraps `crumb note`).

        `kind` is question|trap|idea. Closes the read/write asymmetry where these
        were readable as resources but had no writer.
        """
        return mcp_core.tool_note(kind, text, fields=fields, tags=tags, root=_root())

    @mcp.tool()
    def memory_mark_status(
        id: str, status: str, reason: str, superseded_by: str | None = None
    ) -> dict:
        """Change a record's status, validate-gated (wraps `set_record_status`).

        Pass `superseded_by` (the replacing record's id) when marking
        `superseded` — validate rejects a superseded record without it.
        """
        return mcp_core.tool_mark_status(
            id, status, reason, superseded_by=superseded_by, root=_root()
        )

    @mcp.tool()
    def memory_verify(
        subject: str,
        status: str,
        method: str | None = None,
        note: str | None = None,
        evidence: list[EvidenceItem] | None = None,
        tags: list[str] | None = None,
        confidence: str | None = None,
    ) -> dict:
        """Record a verification result — a finding about reality (wraps `crumb verify`).

        For the most common agentic output ("I checked X; here is its state"), which
        otherwise gets mis-filed as a decision/attempt. `status` is the outcome
        (fixed|open|regressed|not_applicable|inconclusive); `method` is
        static|runtime|test. Populates the resume packet's verifications and is
        searchable via `type:verification` (with `status:` filtering on the outcome).
        """
        return mcp_core.tool_verify(
            subject,
            status,
            method=method,
            note=note,
            evidence=evidence,
            tags=tags,
            confidence=confidence,
            root=_root(),
        )

    @mcp.tool()
    def memory_reindex() -> dict:
        """Rebuild the generated/ projections from the canonical records (wraps `crumb reindex`)."""
        return mcp_core.tool_reindex(root=_root())

    @mcp.tool()
    def memory_scan_secrets() -> dict:
        """Scan committed memory for secret-like strings (wraps `crumb audit`'s scan)."""
        return mcp_core.tool_scan_secrets(root=_root())

    return mcp


def main(argv: list[str] | None = None) -> int:
    """Entry point for `python -m breadcrumbs.mcp_server` / `breadcrumbs-mcp`."""
    args = list(sys.argv[1:] if argv is None else argv)
    if any(a in ("-h", "--help") for a in args):
        # `breadcrumbs-mcp --help` used to silently start the stdio server and
        # hang the terminal — print usage instead.
        print(
            "usage: breadcrumbs-mcp\n\n"
            "Run the breadcrumbs MCP server over stdio (registered by `crumb mcp\n"
            "register` / `crumb init --with-mcp`; run directly by an MCP client,\n"
            "not by hand). Serves the project in $BREADCRUMBS_PROJECT, else cwd.\n"
            'Requires the optional SDK:  pip install "crumb-kit[mcp]"'
        )
        return 0
    if FastMCP is None:
        sys.stderr.write(_INSTALL_HINT + "\n")
        if _SDK_IMPORT_ERROR is not None:
            # Name the actual failure. An SDK that is installed but unimportable
            # (a major the shim does not know, a broken install) is a different
            # problem from a missing one, and printing only the install hint sent
            # the user to re-run a command that had already succeeded.
            sys.stderr.write(
                f"\nThe SDK import failed with: "
                f"{type(_SDK_IMPORT_ERROR).__name__}: {_SDK_IMPORT_ERROR}\n"
            )
        return 1
    server = build_server()
    server.run()  # stdio transport by default
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
