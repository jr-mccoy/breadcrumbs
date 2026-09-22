"""breadcrumbs — the CLI surface of `breadcrumbs.lifecycle` (Phase 3).

Parser builders and command entry points for `crumb expired`, `crumb
questions`, `crumb consolidate` and `crumb rollup`. They live here rather than
in `cli.py`, which is past eleven thousand lines; `cli._SUBCOMMAND_BUILDERS`
names a thin wrapper per command that imports this module only when that
command runs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from breadcrumbs import cli, lifecycle


def _memory_dir(args: argparse.Namespace) -> Path | None:
    root = cli.resolve_root(args.project)
    memory_dir = root / cli.MEMORY_DIRNAME
    if not memory_dir.is_dir():
        cli._emit_error(args, f"no {cli.MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return None
    return memory_dir


# --------------------------------------------------------------------------- #
# crumb expired (WM-30)
# --------------------------------------------------------------------------- #


def add_expired(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "expired",
        parents=[global_parser],
        help="list records past their expires_at (hidden from the packet and guard's live set)",
    )
    p.set_defaults(func=cmd_expired)


def cmd_expired(args: argparse.Namespace) -> int:
    memory_dir = _memory_dir(args)
    if memory_dir is None:
        return 2
    rows = lifecycle.expired_items(memory_dir)
    if args.json:
        cli._print_json(args, {"expired": rows, "items": rows}, summary={"count": len(rows)})
        return 0
    if not rows:
        print("expired: nothing has passed its expires_at.")
        return 0
    print(f"expired: {len(rows)} record(s) past their expires_at\n")
    for r in rows:
        print(f"  {r['id']} — {r['kind']}, expired {str(r['expires_at'])[:10]}: {r['title']}")
    print(
        "\nExpired records stay on disk and in `crumb search`; they no longer reach the "
        "packet's lists or drive `guard`. Still true? Record it again (or `crumb verify` "
        "it again); no longer true? `crumb mark-status <id> stale`."
    )
    return 0


# --------------------------------------------------------------------------- #
# crumb questions (WM-30)
# --------------------------------------------------------------------------- #


def add_questions(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "questions",
        parents=[global_parser],
        help="list open questions with their age; --aging keeps the ones past the question TTL",
    )
    p.add_argument(
        "--aging",
        action="store_true",
        help="only questions open longer than ttl_question_days (default 45)",
    )
    p.set_defaults(func=cmd_questions)


def cmd_questions(args: argparse.Namespace) -> int:
    memory_dir = _memory_dir(args)
    if memory_dir is None:
        return 2
    limit = lifecycle.ttl_days(memory_dir, "question")
    rows = lifecycle.aging_questions(memory_dir)
    if args.aging:
        rows = [r for r in rows if r["aging"]]
    if args.json:
        cli._print_json(
            args,
            {"questions": rows, "items": rows, "ttl_days": limit},
            summary={"count": len(rows), "aging": sum(1 for r in rows if r["aging"])},
        )
        return 0
    if not rows:
        scope = f" open longer than {limit} days" if args.aging else " open"
        print(f"questions: none{scope}.")
        return 0
    print(f"questions: {len(rows)} open (aging past {limit} days is marked)\n")
    for r in rows:
        age = f"{r['age_days']}d" if r["age_days"] is not None else "age unknown"
        mark = " AGING" if r["aging"] else ""
        print(f"  {r['id']} ({age}{mark}) {r['question']}")
    print(
        '\nAnswered? `crumb mark-status <id> answered --reason "…"`. '
        'No longer relevant? `crumb mark-status <id> closed --reason "…"`.'
    )
    return 0


# --------------------------------------------------------------------------- #
# crumb verify --recheck (WM-31)
# --------------------------------------------------------------------------- #


def run_recheck(args: argparse.Namespace, memory_dir: Path, root: Path) -> int:
    """`crumb verify --recheck <id>… | --all [--yes]`.

    Runs commands a record names, so it asks first: every command is printed,
    and nothing runs without `--yes` or a `y` at a terminal. With neither — a
    hook, a pipe, CI — it exits 2 having run nothing. There is no MCP
    equivalent on purpose: running arbitrary commands from the store is a
    human-confirmed, CLI-only act.
    """
    ids = None if args.recheck_all else list(args.recheck or [])
    targets, problems = lifecycle.recheck_targets(memory_dir, ids)
    if not targets:
        why = "; ".join(problems) or "no active verification names a command to rerun"
        cli._emit_error(args, f"nothing to recheck: {why}")
        return 1
    for problem in problems:
        cli._emit_warning(args, problem)
    if not args.yes and not cli._interactive():
        cli._emit_error(
            args,
            "rechecking runs the recorded commands; pass --yes to run them without a "
            "terminal (nothing was run)",
        )
        return 2

    results = []
    for rec in targets:
        rid = rec.meta.get("id", rec.stem)
        commands = cli._evidence_refs(rec, ("command", "test"))
        if not args.json:
            print(f"{rid}:")
            for c in commands:
                print(f"  $ {c}")
        if not args.yes:
            answer = input("  run these? [y/N] ").strip().lower()
            if answer not in ("y", "yes"):
                results.append({"ok": False, "id": rid, "skipped": True})
                continue
        res = lifecycle.recheck(memory_dir, root, rec, agent=getattr(args, "agent", None))
        results.append(res)
        if not args.json:
            if res.get("ok"):
                print(f"  -> {res['outcome']}: {res['new_id']} (supersedes {rid})")
            else:
                print(f"  -> not recorded: {res.get('error')}")

    failed = [r for r in results if not r.get("ok") and not r.get("skipped")]
    if args.json:
        cli._print_json(
            args,
            {"rechecked": results, "items": results},
            ok=not failed,
            summary={
                "rechecked": sum(1 for r in results if r.get("ok")),
                "fixed": sum(1 for r in results if r.get("outcome") == "fixed"),
                "open": sum(1 for r in results if r.get("outcome") == "open"),
                "skipped": sum(1 for r in results if r.get("skipped")),
            },
        )
    return 1 if failed else 0


# --------------------------------------------------------------------------- #
# crumb consolidate (WM-33)
# --------------------------------------------------------------------------- #


def add_consolidate(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "consolidate",
        parents=[global_parser],
        help="list clusters of near-duplicate records, or --merge some into one record",
    )
    p.add_argument(
        "--type",
        dest="consolidate_type",
        choices=lifecycle.DEDUP_TYPES,
        default=None,
        help="only clusters of this type",
    )
    p.add_argument(
        "--merge",
        nargs="+",
        metavar="ID",
        default=None,
        help="write one record replacing these (same type); each is marked superseded",
    )
    p.add_argument("--title", help="title of the merged record (required with --merge)")
    p.add_argument(
        "--set",
        nargs=2,
        action="append",
        metavar=("HEADING", "TEXT"),
        help="replace one section of the merged body outright (repeatable)",
    )
    p.add_argument("--agent", default=None, help="record author label")
    p.set_defaults(func=cmd_consolidate)


def cmd_consolidate(args: argparse.Namespace) -> int:
    memory_dir = _memory_dir(args)
    if memory_dir is None:
        return 2
    root = memory_dir.parent
    if args.merge:
        sections = {}
        for heading, text in args.set or []:
            sections[heading] = text
        res = lifecycle.merge_records(
            memory_dir,
            root,
            args.merge,
            title=args.title or "",
            sections=sections,
            agent=args.agent,
        )
        if not res.get("ok"):
            cli._emit_error(args, res["error"])
            return res.get("code", 1)
        if args.json:
            cli._print_json(args, {k: v for k, v in res.items() if k != "code"})
            return 0
        print(f"Merged {len(res['supersedes'])} {res['type']}s into {res['id']}")
        print(f"  file: {res['path']}")
        print(f"  superseded: {', '.join(res['supersedes'])}")
        if res.get("demoted"):
            print(f"  also demoted (promoted rules removed): {', '.join(res['demoted'])}")
        print(
            "  note: the merged body is each source's text in date order — edit it into "
            "one account before relying on it."
        )
        return 0

    clusters = lifecycle.duplicate_clusters(memory_dir, args.consolidate_type)
    if args.json:
        cli._print_json(
            args, {"clusters": clusters, "items": clusters}, summary={"count": len(clusters)}
        )
        return 0
    if not clusters:
        print("consolidate: no near-duplicate clusters.")
        return 0
    print(f"consolidate: {len(clusters)} cluster(s) of near-duplicates\n")
    for c in clusters:
        print(f"  [{c['kind']}] {len(c['ids'])} records")
        for rid in c["ids"]:
            print(f"    {rid} — {c['titles'].get(rid, '')}")
        for p in c["pairs"]:
            print(f"      {p['a']} ~ {p['b']}: {p['similarity']:.2f}")
    print(
        '\nMerge a cluster: `crumb consolidate --merge <id> <id>… --title "…"`. '
        "Or keep one and retire the rest: `crumb mark-status <id> superseded "
        "--superseded-by <id>`."
    )
    return 0


# --------------------------------------------------------------------------- #
# crumb rollup sessions (WM-35)
# --------------------------------------------------------------------------- #


def add_rollup(sub, global_parser: argparse.ArgumentParser) -> None:
    p = sub.add_parser(
        "rollup",
        parents=[global_parser],
        help="fold old machine-snapshot sessions into one record",
    )
    p.add_argument("what", choices=("sessions",), help="what to roll up (sessions)")
    p.add_argument(
        "--before",
        required=True,
        metavar="YYYY-MM-DD",
        help="roll up snapshots created before this date",
    )
    p.add_argument("--dry-run", action="store_true", help="list what would be rolled up")
    p.add_argument("--agent", default=None, help="record author label")
    p.set_defaults(func=cmd_rollup)


def cmd_rollup(args: argparse.Namespace) -> int:
    memory_dir = _memory_dir(args)
    if memory_dir is None:
        return 2
    res = lifecycle.rollup_sessions(
        memory_dir, memory_dir.parent, args.before, dry_run=args.dry_run, agent=args.agent
    )
    if not res.get("ok"):
        cli._emit_error(args, res["error"])
        return res.get("code", 1)
    if args.json:
        cli._print_json(args, {**res, "items": res["ids"]})
        return 0
    if res["rolled_up"] == 0:
        n = len(res["ids"])
        print(
            f"rollup sessions: {n} machine snapshot(s) before {args.before} — "
            "nothing to roll up (it takes two)."
        )
        return 0
    if res["dry_run"]:
        print(f"rollup sessions (dry run): would fold {res['rolled_up']} snapshot(s) into")
        print(f"  {res['title']}")
        for rid in res["ids"]:
            print(f"    {rid}")
        return 0
    print(f"rollup sessions: folded {res['rolled_up']} snapshot(s) into {res['id']}")
    print(f"  file: {res['path']}")
    print("  Sessions with a real Next Action were left alone.")
    return 0
