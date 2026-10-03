"""The `crumb` argument parser (audit WP16).

Moved out of `cli.py` so that the application layer (`breadcrumbs.service`)
and every module that only needs the domain functions can be imported without
it. `cli.main` builds it lazily; `cli.build_parser` and the other names are
forwarded for compatibility.
"""

from __future__ import annotations

import argparse

from breadcrumbs import cli
from breadcrumbs import packet as _packet
from breadcrumbs import textmatch as _textmatch


def _add_duplicate_flags(parser: argparse.ArgumentParser, *, supersede: bool = True) -> None:
    """`--allow-duplicate` (and `--supersedes ID`) for a writer that gates duplicates."""
    parser.add_argument(
        "--allow-duplicate",
        action="store_true",
        help="write even if a live record of this type says nearly the same thing",
    )
    if supersede:
        parser.add_argument(
            "--supersedes",
            metavar="ID",
            default=None,
            help="replace this live record of the same type: it is marked superseded by "
            "the new one (also answers a near-duplicate refusal)",
        )


# Global flags live on a shared parent parser inherited by every subparser, so
# they can be passed either before or after the subcommand. The catch: argparse's
# subparser action (_SubParsersAction.__call__) parses the subcommand into a
# *fresh* namespace and copies its keys back over the parent namespace — which
# clobbers any global a user set before the subcommand (issue #3). Two-part fix:
#   1. The shared globals default to SUPPRESS, so an absent flag never lands in
#      the sub-namespace and therefore never overwrites the parent's value.
#   2. The top-level parser backfills the real defaults once, after parsing.
# Subparsers stay plain argparse.ArgumentParser (see add_subparsers below) so the
# backfill happens exactly once, at the top — never inside a sub-namespace that
# would then be copied back.
_GLOBAL_FLAG_DEFAULTS = {"project": None, "json": False, "plain": False, "verbose": False}


# One wording for every `--agent` flag. The default is deliberately *not* `human`:
# an omitted flag is an absence of evidence, so it resolves to the
# detected harness or to `unknown`, and a person asserts authorship explicitly.
_AGENT_FLAG_HELP = "{what} label (default: detected agent harness, else 'unknown')"


class _LazyVersionAction(argparse.Action):
    """`--version`, without charging every *other* command for it.

    argparse's built-in `version` action wants the finished string at parser
    construction time, so `build_parser()` called `get_version()` — which imports
    `importlib.metadata`, and with it `email`, `zipfile`, `csv`, `socket`,
    `typing`, … That was ~24 ms of a ~30 ms `build_parser()`, paid on every
    invocation including the `hook guard` pre-filter that fires on every tool
    call, for a flag almost nothing passes. Resolving the version inside
    `__call__` moves that cost to the one command that asked for it.
    """

    def __init__(
        self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None
    ):
        super().__init__(
            option_strings=option_strings, dest=dest, default=default, nargs=0, help=help
        )

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"breadcrumbs {cli.get_version()} (record schema_version {cli.SCHEMA_VERSION})")
        parser.exit()


class _CrumbParser(argparse.ArgumentParser):
    """An argparse parser whose usage errors lead with `CRUMB-ERROR:` (C2).

    argparse prints the usage block first and the reason last, so a caller that
    bounds output with `head` keeps the usage and drops the reason — and one that
    bounds it with `tail` keeps a line that ends in the author's own prose
    (`unrecognized arguments: --body some long text`), which reads like output,
    not like a rejection. Leading with the marker puts the fact that this failed
    on the first line either way, and `self.prog` names the exact subcommand.
    """

    def error(self, message: str):  # noqa: D102 - argparse contract
        self.exit(2, f"{cli.ERROR_PREFIX} {self.prog}: {message}\n{self.format_usage()}")


class _BreadcrumbsParser(_CrumbParser):
    """Top-level parser that keeps global flags working in any position."""

    def parse_known_args(self, args=None, namespace=None):
        ns, argv = super().parse_known_args(args, namespace)
        for dest, default in _GLOBAL_FLAG_DEFAULTS.items():
            if not hasattr(ns, dest):
                setattr(ns, dest, default)
        return ns, argv

    def parse_args(self, args=None, namespace=None):
        """As argparse, but the leftover-argument error names the subcommand.

        argparse checks for unconsumed argv at the *top* level, so the stock
        message is prefixed `crumb:` however deep the rejected flag was — the
        caller is told a flag is unknown without being told which of twenty
        subcommands does not know it, and is then handed the top-level usage,
        which cannot list the flags the subcommand does accept.
        """
        ns, argv = self.parse_known_args(args, namespace)
        if argv:
            label = cli.command_label(ns)
            self.exit(
                2,
                f"{cli.ERROR_PREFIX} {label}: unrecognized arguments: {' '.join(argv)}\n"
                f"try `{label} --help` for the flags this subcommand accepts.\n",
            )
        return ns


# init
def _add_init(sub, global_parser: argparse.ArgumentParser) -> None:
    p_init = sub.add_parser(
        "init",
        parents=[global_parser],
        help="install the .project-memory/ layout into a project",
    )
    p_init.add_argument(
        "--session-tracking",
        choices=cli.VALID_SESSION_TRACKING,
        help="session record policy (default: prompt, then 'full')",
    )
    p_init.add_argument(
        "--no-commit-generated",
        action="store_true",
        help="keep generated/*.md projections local (gitignored)",
    )
    p_init.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing .project-memory/ scaffold",
    )
    # Integration flags. Tri-state: unset -> prompt on a TTY / off when
    # non-interactive; --with-* enables; --no-* disables. set_defaults keeps all three
    # at None so default `crumb init` is byte-identical to before.
    p_init.add_argument(
        "--with-adapter",
        dest="adapter",
        nargs="?",
        const="*",
        metavar="FILES",
        help="inject the signpost block into detected agent-guidance "
        "files (optional: comma-separated list)",
    )
    p_init.add_argument(
        "--no-adapter",
        dest="adapter",
        action="store_const",
        const=False,
        help="do not touch agent-guidance files",
    )
    p_init.add_argument(
        "--with-mcp",
        dest="mcp",
        action="store_const",
        const=True,
        help="register the MCP server in .mcp.json",
    )
    p_init.add_argument(
        "--no-mcp",
        dest="mcp",
        action="store_const",
        const=False,
        help="do not register the MCP server",
    )
    p_init.add_argument(
        "--with-hooks",
        dest="hooks",
        nargs="?",
        const="*",
        metavar="EVENTS",
        help="install Claude Code hooks (bare: all of them; or a comma list of "
        + ",".join(cli.HOOK_EVENTS)
        + ")",
    )
    p_init.add_argument(
        "--no-hooks", dest="hooks", action="store_const", const=False, help="do not install hooks"
    )
    p_init.add_argument(
        "--print-integrations",
        action="store_true",
        help="show which integrations would be applied, then exit",
    )
    p_init.add_argument(
        "--remove-integrations",
        action="store_true",
        help="reverse every breadcrumbs integration, then exit",
    )
    p_init.set_defaults(func=cli.cmd_init, adapter=None, mcp=None, hooks=None)


# validate
def _add_validate(sub, global_parser: argparse.ArgumentParser) -> None:
    p_validate = sub.add_parser(
        "validate",
        parents=[global_parser],
        help="deterministically check the .project-memory/ store ",
    )
    p_validate.set_defaults(func=cli.cmd_validate)


# remember decision | attempt
def _set_flag_help(rtype: str, verb: str = "set") -> str:
    """`--set` help that names the vocabulary (C1).

    The section list was reachable only through `crumb schema <type>` — which is
    excellent, and is not where anyone looks — or by being rejected. Both facts a
    caller needs (the headings, and where the full contract lives) go in the
    help text of the flag that takes them.
    """
    return (
        f"{verb} a body section (repeatable). HEADING is one of: "
        f"{', '.join(cli.BODY_SECTIONS[rtype])}. Matching ignores case, spacing and "
        f"punctuation; anything else is kept under `## {cli.UNSORTED_SECTION}` with a "
        f"warning. Full contract: `crumb schema {rtype}`"
    )


def _add_remember(sub, global_parser: argparse.ArgumentParser) -> None:
    p_remember = sub.add_parser(
        "remember",
        parents=[global_parser],
        help="record a durable decision or attempt",
    )
    p_remember.set_defaults(func=cli.cmd_remember, record_type=None)
    rem_sub = p_remember.add_subparsers(dest="record_type", metavar="<type>")
    for rtype in ("decision", "attempt"):
        pr = rem_sub.add_parser(
            rtype,
            parents=[global_parser],
            help=f"record a durable {rtype}",
        )
        pr.add_argument("--title", help="record title (prompted if omitted in a TTY)")
        pr.add_argument(
            "--set",
            nargs=2,
            action="append",
            metavar=("HEADING", "TEXT"),
            help=_set_flag_help(rtype),
        )
        pr.add_argument(
            "--evidence",
            nargs=2,
            action="append",
            metavar=("TYPE", "REF"),
            help="add an evidence pointer, e.g. --evidence commit abc1234 (repeatable)",
        )
        pr.add_argument("--tags", help="comma-separated tags")
        pr.add_argument("--confidence", choices=("low", "medium", "high"))
        pr.add_argument("--privacy", choices=cli.VALID_PRIVACY)
        # Free text until the record contract (audit F05): any other value was
        # stored and silently read as `project`, whatever its author meant.
        pr.add_argument("--scope", choices=cli.RECORD_SCOPES)
        pr.add_argument("--status", choices=cli.VALID_STATUS)
        pr.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="record author"))
        _add_duplicate_flags(pr)
        if rtype == "attempt":
            # The fixed attempt vocabulary as named flags; each
            # overrides the matching --set heading.
            pr.add_argument("--problem", help="Problem section")
            pr.add_argument("--tried", help="Tried section")
            pr.add_argument("--result", help="Result section")
            pr.add_argument("--why", help="'Why It Failed / Succeeded' section")
            pr.add_argument(
                "--do-not-retry", dest="do_not_retry", help="'Do Not Retry Unless' section"
            )
            pr.add_argument("--related", help="'Related Records' section")
        pr.set_defaults(func=cli.cmd_remember)


# schema introspection
def _add_schema(sub, global_parser: argparse.ArgumentParser) -> None:
    p_schema = sub.add_parser(
        "schema",
        parents=[global_parser],
        help="print the record schema contract (or a fill-in template)",
    )
    p_schema.add_argument(
        "schema_type",
        nargs="?",
        metavar="<type>",
        help="limit to one record type (decision|attempt|verification|session|idea|"
        "jot|trap|question)",
    )
    p_schema.add_argument(
        "--template",
        action="store_true",
        help="emit a copy-pasteable command skeleton for <type> "
        "(`crumb remember`, `crumb note`, `crumb verify` or `crumb jot`)",
    )
    p_schema.set_defaults(func=cli.cmd_schema)


# note question|trap|idea
def _add_note(sub, global_parser: argparse.ArgumentParser) -> None:
    p_note = sub.add_parser(
        "note",
        parents=[global_parser],
        help="leave an open question, known trap, or idea for the next agent",
    )
    p_note.set_defaults(func=cli.cmd_note, note_kind=None)
    note_sub = p_note.add_subparsers(dest="note_kind", metavar="<kind>")

    pq = note_sub.add_parser("question", parents=[global_parser], help="record an open question")
    pq.add_argument("text", nargs="?", help="the question, in one line")
    pq.add_argument("--title", help="the question (alias for the positional, as on `remember`)")
    pq.add_argument("--why", help="why it matters / what is blocked")
    pq.add_argument("--needs", help="human input | investigation | a decision")
    pq.add_argument("--tags", help="comma-separated tags")
    pq.add_argument(
        "--status",
        default="open",
        choices=cli.VALID_QUESTION_STATUS,
        help="status (default: open); retire one later with `crumb mark-status <id> answered`",
    )
    _add_duplicate_flags(pq)
    pq.set_defaults(func=cli.cmd_note)

    pt = note_sub.add_parser("trap", parents=[global_parser], help="record a reusable known trap")
    pt.add_argument("text", nargs="?", help="one-line trap summary")
    pt.add_argument("--title", help="trap summary (alias for the positional, as on `remember`)")
    pt.add_argument("--slug", help="short slug (derived from the summary if omitted)")
    pt.add_argument("--area", help="where this bites (files / area)")
    pt.add_argument("--symptom", help="what goes wrong")
    pt.add_argument("--why", help="the mechanism, not vibes")
    pt.add_argument("--safe", help="the safe approach to use instead")
    pt.add_argument("--verify", help="a command that proves it is OK")
    pt.add_argument("--tags", help="comma-separated tags")
    _add_duplicate_flags(pt)
    pt.set_defaults(func=cli.cmd_note)

    pi = note_sub.add_parser("idea", parents=[global_parser], help="record a speculative idea")
    pi.add_argument("text", nargs="?", help="the idea title")
    pi.add_argument("--title", help="the idea title (alias for the positional, as on `remember`)")
    pi.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("HEADING", "TEXT"),
        help=_set_flag_help("idea"),
    )
    pi.add_argument("--tags", help="comma-separated tags")
    pi.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="note author"))
    _add_duplicate_flags(pi)
    pi.set_defaults(func=cli.cmd_note)


# verify — record a verification result (a finding about reality)
def _add_verify(sub, global_parser: argparse.ArgumentParser) -> None:
    p_verify = sub.add_parser(
        "verify",
        parents=[global_parser],
        help="record a verification result (checked X; status fixed/open/regressed/…)",
    )
    p_verify.add_argument(
        "subject",
        nargs="?",
        default=None,
        metavar="SUBJECT",
        help="what was checked — a finding id, file, or claim (prompted if omitted in a TTY)",
    )
    p_verify.add_argument(
        "--status",
        choices=cli.VALID_VERIFICATION_OUTCOME,
        help="the verification outcome (required unless --recheck / --all)",
    )
    p_verify.add_argument(
        "--method",
        choices=cli.VALID_VERIFICATION_METHOD,
        help="how it was checked (static|runtime|test)",
    )
    p_verify.add_argument("--note", help="free-text notes / what the evidence shows")
    p_verify.add_argument(
        "--evidence",
        nargs=2,
        action="append",
        metavar=("TYPE", "REF"),
        help="add an evidence pointer, e.g. --evidence file path/to/file.py:170 (repeatable)",
    )
    p_verify.add_argument("--tags", help="comma-separated tags")
    p_verify.add_argument("--confidence", choices=("low", "medium", "high"))
    p_verify.add_argument(
        "--agent", default=None, help=_AGENT_FLAG_HELP.format(what="record author")
    )
    _add_duplicate_flags(p_verify)
    p_verify.add_argument(
        "--scope",
        choices=cli.RECORD_SCOPES,
        default=None,
        help="branch: this result applies only while the current branch is checked out "
        "(default: project)",
    )
    p_verify.add_argument(
        "--assert",
        dest="assertions",
        metavar="CMD",
        action="append",
        default=None,
        help="an assertion for this subject: a command that exits 0 exactly when it is "
        "fixed (a regression test). Only assertions let `--recheck` settle the claim "
        "(repeatable)",
    )
    p_verify.add_argument(
        "--bind-commands",
        action="store_true",
        help="with --recheck: treat the record's command evidence as its assertion for this "
        "run, and record it as one (otherwise a command is only a diagnostic)",
    )
    p_verify.add_argument(
        "--recheck",
        metavar="ID",
        action="append",
        default=None,
        help="rerun this verification's assertions (and any command evidence, as diagnostics); "
        "a new verification supersedes it only when its assertions settle the claim "
        "(repeatable; asks before running anything)",
    )
    p_verify.add_argument(
        "--all",
        dest="recheck_all",
        action="store_true",
        help="with --recheck semantics: every active verification with an assertion or command",
    )
    p_verify.add_argument(
        "--yes",
        action="store_true",
        help="run the commands without asking (required when there is no terminal)",
    )
    p_verify.set_defaults(func=cli.cmd_verify)


# mark-status — record lifecycle mutation from the CLI
def _add_mark_status(sub, global_parser: argparse.ArgumentParser) -> None:
    p_mark = sub.add_parser(
        "mark-status",
        parents=[global_parser],
        help="change a record's, trap's or question's status, validate-gated",
    )
    p_mark.add_argument(
        "record_id",
        metavar="ID",
        help="record id (e.g. dec_20260510_markdown-source-of-truth), trap id "
        "(e.g. trap_hand-tagged-releases) or question id (e.g. q:should-we-shard) — "
        "retiring a trap or answering a question stops it raising guard",
    )
    # Positional STATUS, with `--status` accepted for the same value (C3). This
    # is the only place in the CLI where a vocabulary value is positional —
    # `crumb verify` takes the same words as `--status` — and that inconsistency
    # is the whole trap: `--status superseded` exited 2 with an argparse error
    # naming no subcommand. Accepting both costs nothing and removes the class.
    p_mark.add_argument(
        "new_status",
        metavar="STATUS",
        nargs="?",
        choices=cli.MARK_STATUS_CHOICES,
        help=f"new status — records and traps: {', '.join(cli.VALID_STATUS)}; "
        f"questions: {', '.join(cli.VALID_QUESTION_STATUS)}",
    )
    p_mark.add_argument(
        "--status",
        dest="status_flag",
        default=None,
        choices=cli.MARK_STATUS_CHOICES,
        help="the same value as the positional STATUS, spelled as `crumb verify` spells it",
    )
    p_mark.add_argument(
        "--reason", default="", help="why the status changed (recorded as a trailing comment)"
    )
    p_mark.add_argument(
        "--superseded-by",
        dest="superseded_by",
        default=None,
        metavar="ID",
        help="the replacing record's id (required by validate when marking superseded)",
    )
    p_mark.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="author"))
    p_mark.set_defaults(func=cli.cmd_mark_status)


# traps — what the always-on context costs, and what can be retired
def _add_traps(sub, global_parser: argparse.ArgumentParser) -> None:
    p_traps = sub.add_parser(
        "traps",
        parents=[global_parser],
        help="list known traps with their staleness and context cost",
    )
    p_traps.add_argument(
        "--stale",
        nargs="?",
        type=int,
        const=-1,  # "no DAYS given": the store's ttl_trap_days (WM-30)
        default=None,
        metavar="DAYS",
        help=f"only traps not confirmed in DAYS (default: the store's ttl_trap_days, "
        f"{cli.TRAPS_STALE_DAYS_DEFAULT} unless set); never-confirmed traps always qualify",
    )
    p_traps.add_argument(
        "--status", choices=cli.VALID_STATUS, default=None, help="only traps with this status"
    )
    p_traps.add_argument(
        "--confirm",
        metavar="ID",
        default=None,
        help=f"stamp a trap's `- {cli.TRAP_CONFIRMED_KEY}:` bullet with today's date",
    )
    p_traps.set_defaults(func=cli.cmd_traps)


# show — the body behind a one-line mention
def _add_show(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "show",
        parents=[global_parser],
        help="print one record, trap, question or jot by id (the body behind a one-line mention)",
    )
    p.add_argument(
        "record_id",
        metavar="ID",
        help="any id the tool prints: dec_…, att_…, ver_…, idea_…, ses_…, jot_…, trap_…, q_…",
    )
    p.set_defaults(func=cli.cmd_show)


# Phase 3 lifecycle commands — implemented in `breadcrumbs.lifecycle_cmds`,
# imported only when one of them runs.
def _add_expired(sub, global_parser: argparse.ArgumentParser) -> None:
    from breadcrumbs import lifecycle_cmds

    lifecycle_cmds.add_expired(sub, global_parser)


def _add_questions(sub, global_parser: argparse.ArgumentParser) -> None:
    from breadcrumbs import lifecycle_cmds

    lifecycle_cmds.add_questions(sub, global_parser)


def _add_promote(sub, global_parser: argparse.ArgumentParser) -> None:
    from breadcrumbs import promote

    promote.add_promote(sub, global_parser)


def _add_demote(sub, global_parser: argparse.ArgumentParser) -> None:
    from breadcrumbs import promote

    promote.add_demote(sub, global_parser)


def _add_consolidate(sub, global_parser: argparse.ArgumentParser) -> None:
    from breadcrumbs import lifecycle_cmds

    lifecycle_cmds.add_consolidate(sub, global_parser)


def _add_rollup(sub, global_parser: argparse.ArgumentParser) -> None:
    from breadcrumbs import lifecycle_cmds

    lifecycle_cmds.add_rollup(sub, global_parser)


# retitle — repair a record whose title carries no information
def _add_retitle(sub, global_parser: argparse.ArgumentParser) -> None:
    p_retitle = sub.add_parser(
        "retitle",
        parents=[global_parser],
        help="rewrite a record's title (id, slug and filename are left alone)",
    )
    p_retitle.add_argument(
        "record_id",
        metavar="ID",
        help="record id, e.g. ses_20260904_session-8",
    )
    p_retitle.add_argument("title", metavar="TITLE", help="the new title")
    p_retitle.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="author"))
    p_retitle.set_defaults(func=cli.cmd_retitle)


# prune — explicit retention for machine session snapshots
def _add_prune(sub, global_parser: argparse.ArgumentParser) -> None:
    p_prune = sub.add_parser(
        "prune",
        parents=[global_parser],
        help="delete old machine session snapshots, expired jots, or branch handoffs "
        "whose branch is gone",
    )
    p_prune.add_argument(
        "what",
        choices=("sessions", "jots", "handoffs"),
        help="what to prune: machine session snapshots, expired/retired jots, or branch "
        "handoffs whose branch is gone",
    )
    p_prune.add_argument(
        "--keep",
        type=int,
        default=cli.PRUNE_SESSIONS_KEEP_DEFAULT,
        metavar="N",
        help=f"newest sessions never pruned (default: {cli.PRUNE_SESSIONS_KEEP_DEFAULT})",
    )
    p_prune.add_argument(
        "--dry-run", action="store_true", help="list what would be deleted; delete nothing"
    )
    p_prune.set_defaults(func=cli.cmd_prune)


# reindex — explicit projection refresh (mutations reindex automatically)
def _add_reindex(sub, global_parser: argparse.ArgumentParser) -> None:
    p_reindex = sub.add_parser(
        "reindex",
        parents=[global_parser],
        help="rebuild generated/ projections from the canonical records",
    )
    p_reindex.add_argument(
        "--search-index",
        action="store_true",
        help="also build index/search.sqlite even if the store is under the size threshold",
    )
    p_reindex.set_defaults(func=cli.cmd_reindex)


# recover — roll back unfinished multi-record operations (audit WP06)
def _add_recover(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "recover",
        parents=[global_parser],
        help="list, or --apply to roll back, operations a crash left unfinished",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="roll each unfinished operation back to its before-image",
    )
    p.set_defaults(func=cli.cmd_recover)


# capture session
def _add_capture(sub, global_parser: argparse.ArgumentParser) -> None:
    p_capture = sub.add_parser(
        "capture",
        parents=[global_parser],
        help="capture a work session (git-prefilled); updates handoff + current",
    )
    p_capture.set_defaults(func=cli._capture_dispatch, capture_what=None)
    cap_sub = p_capture.add_subparsers(dest="capture_what", metavar="<what>")
    p_session = cap_sub.add_parser(
        "session",
        parents=[global_parser],
        help="record session end; auto-fills work/files/commands from git",
    )
    p_session.add_argument(
        "--fast", action="store_true", help="git snapshot + --next only; no prompts, no LLM"
    )
    p_session.add_argument(
        "--next",
        dest="next_action",
        help="the Next Action (required on --fast); added as a dated entry above the "
        "handoff's earlier ones, which are kept",
    )
    p_session.add_argument(
        "--recent",
        help="a note for current.md's Recently Changed, added above what is there",
    )
    p_session.add_argument(
        "--replace",
        action="store_true",
        help="overwrite the handoff's Next Action (and Recently Changed, with --recent) "
        "instead of adding to it; the replaced text is kept in the session record",
    )
    p_session.add_argument("--title", help="session topic (default: 'session')")
    p_session.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("HEADING", "TEXT"),
        help=_set_flag_help("session", verb="override"),
    )
    p_session.add_argument(
        "--include-memory",
        dest="include_memory",
        action="store_true",
        help=f"keep {cli.MEMORY_DIRNAME}/ paths in dirty_files (default: excluded — every "
        "capture rewrites the store, and in a shared tree it also sees other sessions')",
    )
    p_session.add_argument(
        "--focus", help="Current Focus for handoff/current (default: keep the previous focus)"
    )
    p_session.add_argument(
        "--agent", default=None, help=_AGENT_FLAG_HELP.format(what="session author")
    )
    p_session.set_defaults(func=cli.cmd_capture_session)


# resume
def _add_resume(sub, global_parser: argparse.ArgumentParser) -> None:
    p_resume = sub.add_parser(
        "resume",
        parents=[global_parser],
        help="print a bounded resume packet with computed staleness",
    )
    p_resume.add_argument(
        "--fast",
        action="store_true",
        help="git snapshot + current focus + next action + staleness only (print-only)",
    )
    p_resume.add_argument(
        "--stale-days",
        type=int,
        default=None,
        metavar="N",
        help=f"{cli.STALE_DAYS_HELP}; aged questions/decisions raise a staleness warning",
    )
    p_resume.add_argument(
        "--task",
        default=None,
        metavar="TEXT",
        help="resume FOR this task: order every section by relevance to it (the "
        "3 newest per section stay first) and scope likely-files to matching records; "
        "a task-scoped packet prints only and does not overwrite the committed snapshot",
    )
    p_resume.add_argument(
        "--budget",
        type=int,
        default=None,
        metavar="TOKENS",
        help=f"bound the printed view to TOKENS approx tokens ({_packet.TOKEN_ESTIMATOR}; "
        f"default {_packet.TOKEN_BUDGET_MAX}, {_packet.FAST_TOKEN_BUDGET} with --fast); affects what you "
        "see, never the committed packet",
    )
    p_resume.set_defaults(func=cli.cmd_resume)


# search — deterministic exact/keyword/tag/file lookup
def _add_search(sub, global_parser: argparse.ArgumentParser) -> None:
    p_search = sub.add_parser(
        "search",
        parents=[global_parser],
        help="deterministic keyword/tag/file search over records (no embeddings)",
    )
    p_search.add_argument(
        "query", nargs="?", default="", help="search text (optional with filters)"
    )
    p_search.add_argument(
        "--type",
        choices=("decision", "attempt", "verification", "idea", "trap", "question", "jot"),
        help="narrow the corpus to one record type ('idea' and 'jot' are searchable "
        "but never reach a guard verdict)",
    )
    p_search.add_argument(
        "--explain",
        action="store_true",
        help=f"print the stems the query became (and whether {_textmatch.ALIASES_FILENAME} is active)",
    )
    p_search.add_argument(
        "--status",
        help="filter by record status (e.g. active, superseded; "
        "for verifications: the outcome, e.g. open/fixed)",
    )
    p_search.add_argument("--tag", help="filter by tag/component")
    p_search.add_argument("--file", help="filter by file path referenced in a record")
    p_search.add_argument(
        "--stale-days",
        type=int,
        default=None,
        metavar="N",
        help=f"{cli.STALE_DAYS_HELP}; aged records score lower",
    )
    p_search.set_defaults(func=cli.cmd_search)


# guard — guard-before-action: warn before repeating a mistake
def _add_guard(sub, global_parser: argparse.ArgumentParser) -> None:
    p_guard = sub.add_parser(
        "guard",
        parents=[global_parser],
        help="warn before an action that conflicts with memory (§11)",
    )
    p_guard.add_argument("action", help='the proposed action, e.g. "rewrite the auth middleware"')
    p_guard.add_argument(
        "--files",
        nargs="*",
        default=None,
        metavar="PATH",
        help="explicit file paths the action will touch (sharpens file-overlap scoring)",
    )
    p_guard.add_argument(
        "--stale-days",
        type=int,
        default=None,
        metavar="N",
        help=f"{cli.STALE_DAYS_HELP}; aged records score lower",
    )
    p_guard.add_argument(
        "--exit-zero",
        action="store_true",
        help="exit 0 whatever the verdict (the verdict is still printed); by default "
        "PROCEED=0, READ_FIRST=10, PAUSE=15, ASK_HUMAN=20",
    )
    p_guard.set_defaults(func=cli.cmd_guard)


# audit — heuristic stale/unsafe/bloated detection (does NOT gate validate)
def _add_audit(sub, global_parser: argparse.ArgumentParser) -> None:
    p_audit = sub.add_parser(
        "audit",
        parents=[global_parser],
        help="heuristic health/safety audit: stale, unsafe (secrets), instruction-like, drift, bloat",
    )
    p_audit.add_argument(
        "--stale-days",
        type=int,
        default=None,
        metavar="N",
        help=f"{cli.STALE_DAYS_HELP}; aged questions/decisions become warn findings",
    )
    p_audit.set_defaults(func=cli.cmd_audit)


# scan-secrets — the secret sub-check as a standalone command
def _add_scan_secrets(sub, global_parser: argparse.ArgumentParser) -> None:
    p_scan = sub.add_parser(
        "scan-secrets",
        parents=[global_parser],
        help="scan committed memory for secret-like strings (run before committing memory)",
        description=(
            "Scan committed memory for secret-like strings. A structured credential "
            "shape (AWS key, PEM block, bearer token, …) exits non-zero; the "
            "high-entropy heuristic warns without blocking. Add one regex per line to "
            f"{cli.MEMORY_DIRNAME}/{cli.CRUMBIGNORE_FILENAME} to silence a shape this project "
            "has already decided is not a secret."
        ),
    )
    p_scan.set_defaults(func=cli.cmd_scan_secrets)


# mcp serve|register — surface the optional MCP server from the CLI
def _add_mcp(sub, global_parser: argparse.ArgumentParser) -> None:
    p_mcp = sub.add_parser(
        "mcp",
        parents=[global_parser],
        help="run or register the optional breadcrumbs MCP server",
    )
    p_mcp.set_defaults(func=cli.cmd_mcp, mcp_what=None)
    mcp_sub = p_mcp.add_subparsers(dest="mcp_what", metavar="<what>")
    p_mcp_serve = mcp_sub.add_parser(
        "serve",
        parents=[global_parser],
        help="run the MCP server over stdio (needs the [mcp] extra)",
    )
    p_mcp_serve.set_defaults(func=cli.cmd_mcp, mcp_what="serve")
    p_mcp_register = mcp_sub.add_parser(
        "register",
        parents=[global_parser],
        help="add the breadcrumbs server to .mcp.json (preserves other servers)",
    )
    p_mcp_register.add_argument(
        "--local",
        action="store_true",
        help="keep the committed .mcp.json portable (`breadcrumbs-mcp`) and register this "
        "machine's interpreter (`<python> -m breadcrumbs mcp serve`) at Claude Code's local "
        "scope, which overrides it here only — for a repo shared across machines",
    )
    p_mcp_register.set_defaults(func=cli.cmd_mcp, mcp_what="register")
    p_mcp_doctor = mcp_sub.add_parser(
        "doctor",
        parents=[global_parser],
        help="report MCP wiring: [mcp] extra, .mcp.json registration",
    )
    p_mcp_doctor.set_defaults(func=cli.cmd_mcp, mcp_what="doctor")


# doctor — integration health
# migrate — bring a store's on-disk format up to this build
def _add_migrate(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "migrate",
        parents=[global_parser],
        help=f"upgrade the store's on-disk format to schema_version {cli.SCHEMA_VERSION}",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="list the steps that would run (or, with --restore, the files that would "
        "change); change nothing",
    )
    p.add_argument(
        "--restore",
        nargs="?",
        const="latest",
        default=None,
        metavar="BACKUP",
        help="put the committed store back as a verified migration backup holds it "
        "(default: the interrupted migration's backup, else the newest)",
    )
    p.set_defaults(func=cli.cmd_migrate)


# rename — shorten a record's file name; handoff trim — move old entries
def _add_rename(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "rename",
        parents=[global_parser],
        help="give a record a shorter file name (and id); references are updated and the "
        "old id still resolves",
    )
    p.add_argument("record_id", metavar="ID", help="the record to rename")
    p.add_argument("--slug", required=True, help="the new slug: lowercase words and hyphens")
    p.set_defaults(func=cli.cmd_rename)


def _add_handoff(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "handoff", parents=[global_parser], help="maintain the handoff's Next Action log"
    )
    p.set_defaults(func=cli.cmd_handoff, handoff_what=None)
    hs = p.add_subparsers(dest="handoff_what", metavar="<what>")
    pt = hs.add_parser(
        "trim",
        parents=[global_parser],
        help="move all but the newest N Next Action entries to a history file (none deleted)",
    )
    pt.add_argument("--keep", type=int, default=None, help="entries to keep (default 10)")
    pt.add_argument(
        "--before",
        metavar="YYYY-MM-DD",
        help="instead of --keep: move the first entry dated before this day and every entry "
        "below it",
    )
    pt.add_argument(
        "--split-on",
        metavar="REGEX",
        help="a line pattern that starts an entry inside a hand-kept log (default: a bold date "
        "lead-in, `**2026-10-01 …`)",
    )
    pt.set_defaults(func=cli.cmd_handoff, handoff_what="trim")


# repair — assisted repair of records that break the record contract
def _add_repair(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "repair",
        parents=[global_parser],
        help="fill in what can be derived for records that fail validation (hand-written "
        "ones), map legacy values, and list what needs a person; --apply writes",
    )
    p.add_argument("--apply", action="store_true", help="write the changes (default: preview)")
    p.add_argument(
        "--set",
        action="append",
        metavar="ID.FIELD=VALUE",
        help="supply a value repair will not guess, e.g. ver_20260920_x.outcome=fixed "
        "(repeatable; only `outcome` is accepted today)",
    )
    p.set_defaults(func=cli.cmd_repair)


# usage — local surfacing counts
def _add_usage(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "usage",
        parents=[global_parser],
        help="which records actually get surfaced (local counts, never committed)",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--never",
        action="store_true",
        help="instead list active records that have never been surfaced, oldest first",
    )
    mode.add_argument(
        "--sessions",
        action="store_true",
        help="order by distinct sessions that surfaced a record, not raw count",
    )
    mode.add_argument(
        "--decay",
        nargs="?",
        type=int,
        const=cli.DECAY_DAYS_DEFAULT,
        default=None,
        metavar="DAYS",
        help="list active decisions, attempts and traps at least DAYS old (default 180) "
        "that nothing surfaced in the last DAYS, with the mark-status command for "
        "each; prints commands, never runs them",
    )
    p.add_argument("--top", type=int, default=25, metavar="N", help="rows to print (default: 25)")
    p.set_defaults(func=cli.cmd_usage)


# jot — one observation, no ceremony
def _add_jot(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "jot",
        parents=[global_parser],
        help="leave a short-term note with a TTL (promote it later, or let it expire)",
    )
    p.add_argument("text", help="the observation, in a line or two")
    p.add_argument("--tags", help="comma-separated tags")
    p.add_argument(
        "--file",
        action="append",
        metavar="PATH",
        help="a file this is about (repeatable); recorded as file evidence so "
        "`search --file` and the guard's file signal can reach it",
    )
    p.add_argument(
        "--local",
        action="store_true",
        help=f"write to {cli.MEMORY_DIRNAME}/private/inbox/ instead — never committed",
    )
    p.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="note author"))
    _add_duplicate_flags(p, supersede=False)
    p.add_argument(
        "--scope",
        choices=cli.RECORD_SCOPES,
        default=None,
        help="branch: the note applies only while the current branch is checked out "
        "(default: project for a jot you write; hooks write branch-scoped jots)",
    )
    p.set_defaults(func=cli.cmd_jot)


# inbox — list / promote / drop
def _add_inbox(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "inbox",
        parents=[global_parser],
        help="list short-term jots; promote the durable ones, drop the noise",
    )
    p.add_argument("--all", action="store_true", help="include expired and retired jots")
    p.add_argument("--expired", action="store_true", help="only jots past their TTL")
    p.set_defaults(func=cli.cmd_inbox, inbox_what=None)
    inbox_sub = p.add_subparsers(dest="inbox_what", metavar="<what>")

    pp = inbox_sub.add_parser(
        "promote",
        parents=[global_parser],
        help="turn a jot into a durable record (same validate gate as writing one by hand)",
    )
    pp.add_argument("jot_id", metavar="ID", help="the jot id, e.g. jot_20260922_flaky-test-a3f2")
    pp.add_argument("target", choices=cli.INBOX_PROMOTE_TARGETS, help="the record type to create")
    pp.add_argument("--title", help="override the record title (default: the jot's text)")
    pp.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("HEADING", "TEXT"),
        help="body section on the new record (repeatable)",
    )
    pp.add_argument(
        "--evidence",
        nargs=2,
        action="append",
        metavar=("TYPE", "REF"),
        help="evidence on the new record (repeatable); the jot's own file evidence carries over",
    )
    pp.add_argument("--tags", help="comma-separated tags to add")
    pp.add_argument(
        "--confidence",
        choices=("low", "medium", "high"),
        default=None,
        help="raise the record's confidence (default: the jot's, which is low)",
    )
    pp.add_argument(
        "--scope",
        choices=cli.RECORD_SCOPES,
        default=None,
        help="the record's scope (default: the jot's; `project` widens a branch jot)",
    )
    _add_duplicate_flags(pp)
    pp.add_argument(
        "--status",
        default=None,
        choices=cli.VALID_VERIFICATION_OUTCOME,
        help="verification outcome (only with `promote <id> verification`)",
    )
    pp.add_argument(
        "--method",
        default=None,
        choices=cli.VALID_VERIFICATION_METHOD,
        help="verification method (only with `promote <id> verification`)",
    )
    pp.add_argument("--why", default=None, help="trap/question: the mechanism, or why it matters")
    pp.add_argument("--area", default=None, help="trap: where this bites (files / area)")
    pp.add_argument("--safe", default=None, help="trap: the safe approach to use instead")
    pp.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="author"))
    pp.set_defaults(func=cli.cmd_inbox, all=False, expired=False)

    pi = inbox_sub.add_parser(
        "import",
        parents=[global_parser],
        help="turn notes left in inbox/drafts/ (by an agent without the CLI) into jots",
    )
    pi.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="importer"))
    pi.set_defaults(func=cli.cmd_inbox, all=False, expired=False)

    pd = inbox_sub.add_parser(
        "drop", parents=[global_parser], help="retire a jot as noise (kept as history)"
    )
    pd.add_argument("jot_id", metavar="ID", help="the jot id")
    pd.add_argument("--reason", default=None, help="why it is noise")
    pd.add_argument("--agent", default=None, help=_AGENT_FLAG_HELP.format(what="author"))
    pd.set_defaults(func=cli.cmd_inbox, all=False, expired=False)


def _add_doctor(sub, global_parser: argparse.ArgumentParser) -> None:
    p_doctor = sub.add_parser(
        "doctor",
        parents=[global_parser],
        help="report whether memory is actually wired up (adapter/mcp/hooks/packet)",
    )
    p_doctor.add_argument(
        "--hook-log",
        action="store_true",
        help="instead summarise private/hook-log.jsonl: firings, outcomes and timings "
        "per hook (the field-test report, docs/field-test.md)",
    )
    p_doctor.set_defaults(func=cli.cmd_doctor)


# hook session|guard|capture — harness translation layer
def _add_hook(sub, global_parser: argparse.ArgumentParser) -> None:
    p_hook = sub.add_parser(
        "hook",
        parents=[global_parser],
        help="Claude Code hook entry points (read stdin payload, emit hook JSON)",
    )
    p_hook.set_defaults(func=cli.cmd_hook, hook_event=None)
    hook_sub = p_hook.add_subparsers(dest="hook_event", metavar="<event>")
    for ev, _help in (
        ("session", "SessionStart: emit the resume packet as additional context"),
        ("guard", "PreToolUse: cost-aware guard verdict for the proposed tool call"),
        ("capture", "Stop: snapshot a session record, mine the transcript, maybe extract"),
        ("prompt", "UserPromptSubmit: inject memory relevant to this prompt; capture corrections"),
        ("compact", "PreCompact: mine the transcript before the context is destroyed"),
        ("subagent", "SubagentStop: mine the finished subagent's transcript"),
    ):
        ph = hook_sub.add_parser(ev, parents=[global_parser], help=_help)
        ph.set_defaults(func=cli.cmd_hook, hook_event=ev)


# Every subcommand's parser, built on demand. `build_parser()` used to
# construct all of these up front — ~5 ms before argparse had even looked at
# argv — on every invocation, including the `hook guard` pre-filter that fires
# on every tool call and usually returns `{}` without touching memory. `main()`
# now names the one command argv asks for and only that parser is built; the
# full set is still built for `--help`, for an unrecognised command (so the
# "invalid choice" message lists everything), and for any caller that wants the
# whole parser. Insertion order is the order `--help` lists them in.
# review / policy — the authority model (audit WP14, `breadcrumbs/admission.py`)
def _add_review(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "review",
        parents=[global_parser],
        help="stamp a record as reviewed by a person (content-bound; an edit makes it stale)",
    )
    p.add_argument("id", help="decision, attempt, verification or trap id")
    p.add_argument(
        "--reviewer", default=None, help="who reviewed (default: git user.email, else the OS user)"
    )
    p.set_defaults(func=cli.cmd_review)


def _add_policy(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "policy",
        parents=[global_parser],
        help="show or set the store's review profile (solo | team) and MCP mode",
    )
    p.add_argument("action", nargs="?", choices=["show", "set"], default="show")
    p.add_argument("profile", nargs="?", choices=["solo", "team"], default=None)
    p.add_argument(
        "--mcp-mode",
        choices=["write", "propose", "read-only"],
        default=None,
        help="what MCP may write (default: write for solo, propose for team)",
    )
    p.set_defaults(func=cli.cmd_policy)


_SUBCOMMAND_BUILDERS: dict[str, object] = {
    "init": _add_init,
    "validate": _add_validate,
    "remember": _add_remember,
    "schema": _add_schema,
    "note": _add_note,
    "jot": _add_jot,
    "inbox": _add_inbox,
    "verify": _add_verify,
    "mark-status": _add_mark_status,
    "show": _add_show,
    "retitle": _add_retitle,
    "traps": _add_traps,
    "questions": _add_questions,
    "expired": _add_expired,
    "consolidate": _add_consolidate,
    "promote": _add_promote,
    "demote": _add_demote,
    "review": _add_review,
    "policy": _add_policy,
    "prune": _add_prune,
    "rollup": _add_rollup,
    "migrate": _add_migrate,
    "repair": _add_repair,
    "rename": _add_rename,
    "handoff": _add_handoff,
    "usage": _add_usage,
    "reindex": _add_reindex,
    "recover": _add_recover,
    "capture": _add_capture,
    "resume": _add_resume,
    "search": _add_search,
    "guard": _add_guard,
    "audit": _add_audit,
    "scan-secrets": _add_scan_secrets,
    "mcp": _add_mcp,
    "doctor": _add_doctor,
    "hook": _add_hook,
}


def build_parser(only: str | None = None) -> argparse.ArgumentParser:
    """The `crumb` parser. `only` builds just that one subcommand's parser.

    `only` is an optimisation, never a behaviour change: pass a name from
    `_SUBCOMMAND_BUILDERS` and the returned parser handles exactly that command;
    pass nothing (every caller that needs help text, or an unknown command) and
    the full parser is built as before.
    """
    # Parent parser holds the global flags so every subcommand inherits them.
    # default=SUPPRESS is load-bearing — see _BreadcrumbsParser above.
    global_parser = argparse.ArgumentParser(add_help=False)
    global_parser.add_argument(
        "--json",
        action="store_true",
        default=argparse.SUPPRESS,
        help="machine-readable JSON output",
    )
    global_parser.add_argument(
        "--plain",
        action="store_true",
        default=argparse.SUPPRESS,
        help="plain-text output (no decoration)",
    )
    global_parser.add_argument(
        "--verbose", action="store_true", default=argparse.SUPPRESS, help="verbose output"
    )
    global_parser.add_argument(
        "--project", metavar="PATH", default=argparse.SUPPRESS, help="project root (default: cwd)"
    )

    parser = _BreadcrumbsParser(
        prog="crumb",
        description="Breadcrumbs — a repo-local ledger of durable project state you and your agents can follow back.",
        parents=[global_parser],
    )
    parser.add_argument(
        "--version",
        action=_LazyVersionAction,
        help="show version and record schema_version, then exit",
    )
    # Subparsers are _CrumbParser (not _BreadcrumbsParser) so the global backfill
    # runs only once, at the top level — never in a copied-back sub-namespace —
    # while every usage error still leads with the CRUMB-ERROR marker.
    sub = parser.add_subparsers(dest="command", metavar="<command>", parser_class=_CrumbParser)
    for name, add_subcommand in _SUBCOMMAND_BUILDERS.items():
        if only is None or name == only:
            add_subcommand(sub, global_parser)

    return parser
