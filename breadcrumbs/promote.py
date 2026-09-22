"""breadcrumbs — the bridge to long-term memory (Phase 4: WM-40 to WM-43).

Breadcrumbs is short-to-medium-term memory. The long-term tier is the agent's
own instruction file — `CLAUDE.md` or `AGENTS.md` — which every session loads
whole and nothing ages out of. A decision that has held for months, or a trap
that keeps biting, belongs there. Until now the only thing breadcrumbs wrote into
that file was a signpost, and no command moved content between the tiers.

**A second managed block, not the signpost.** Promoted rules live between their
own markers, separate from the `crumb init` signpost block, so
`--remove-integrations` still removes exactly the signpost and the signpost's
bloat check still measures a pointer. Each rule is one line that names its
source record, which is what lets `demote`, the drift check and the
demote-candidate check find it again:

    - <rule>. _(why: <rationale>; source: `<record id>`)_

**Promotion does not retire the record.** It is still true — it is now also
long-term. The packet leaves it out (it is already in the model's context
through the instruction file) and says how many it left out; `guard` still
scores it at full weight; `search` marks it `promoted`. Retiring a promoted
record demotes it: a rule nobody believes any more must not stay in the file
every session loads.

**CLI only.** There is no MCP tool for promote. An agent writing its own
permanent instructions through a tool call is the persistence step of a prompt
injection; a person runs `crumb promote`, or an agent runs it where a person can
see the command.
"""

from __future__ import annotations

import re
from pathlib import Path

from breadcrumbs import cli

PROMOTED_BEGIN = (
    "<!-- >>> breadcrumbs promoted rules (managed by `crumb promote`) "
    "— edit with crumb promote/demote, not by hand >>> -->"
)
PROMOTED_END = "<!-- <<< breadcrumbs promoted rules <<< -->"
PROMOTED_HEADING = "## Project rules promoted from memory"

# The two instruction files a rule can go to, in the order `promote` picks one
# when `--to` is not given. The other adapter files (.cursorrules, …) are
# signpost-only: their formats are not Markdown sections every harness reads.
PROMOTE_TARGETS = ("CLAUDE.md", "AGENTS.md")
PROMOTABLE_TYPES = ("decision", "attempt", "trap")
# A status that retires a record also demotes it (WM-41).
# `quarantined` above all: a record suspected of carrying injected text is the
# last thing that should stay in the file every session loads.
RETIRING_STATUSES = ("superseded", "stale", "rejected", "disputed", "quarantined")

RULE_MAX_CHARS = 200
RATIONALE_MAX_CHARS = 160

# The trap-block bullet that carries `promoted_to` on a schema-2 store.
PROMOTED_BULLET_KEY = "Promoted to"
_BLOCK_PROMOTED_LINE_RE = re.compile(r"\s*-\s*promoted[ _]to\s*:\s*(.+)", re.I)
_SOURCE_RE = re.compile(r"source:\s*`([^`]+)`")

# WM-42: what earns a promotion suggestion.
PROMOTE_MIN_AGE_DAYS = 60
PROMOTE_MIN_SESSIONS = 5


# --------------------------------------------------------------------------- #
# Rendering one rule
# --------------------------------------------------------------------------- #


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _item_texts(item: dict) -> tuple[str, str]:
    """`(default rule, rationale)` for a `find_item` result."""
    kind = item["kind"]
    meta = item.get("meta") or {}
    title = str(meta.get("title") or "").strip()
    if kind == "trap":
        trap = cli.find_trap_by_id(item["_memory_dir"], item["id"]) or {}
        body = trap.get("body") or ""
        fields = {}
        for line in body.splitlines():
            m = re.match(r"\s*-\s*([^:]+?)\s*:\s*(.*)$", line)
            if m:
                fields[m.group(1).strip().lower()] = m.group(2).strip()
        # The safe approach alone ("stop the daemon first") says what to do but
        # not when; the trap's summary is the "when", so the rule carries both.
        summary = trap.get("summary") or item["id"]
        safe = fields.get("safe approach")
        rule = f"{summary}: {safe}" if safe else summary
        why = fields.get("why") or ""
        return rule, why
    rec = cli.Record.from_file(Path(item["path"]), kind)
    if kind == "decision":
        return (title or rec.stem), cli._decision_rationale(rec)
    # attempt
    unless = cli._first_line(rec.sections.get("Do Not Retry Unless", ""))
    rule = f"Do not retry: {title or rec.stem}" + (f" — unless {unless}" if unless else "")
    why = cli._first_line(rec.sections.get("Why It Failed / Succeeded", "")) or cli._first_line(
        rec.sections.get("Result", "")
    )
    return rule, why


def render_bullet(rid: str, rule: str, why: str) -> str:
    # No case change: a rule can start with a command or an identifier
    # (`gradlew --stop …`), and capitalising it would change what it says.
    rule = _clip(rule, RULE_MAX_CHARS).rstrip(".")
    why = _clip(why, RATIONALE_MAX_CHARS).rstrip(".")
    if why == rule:
        why = ""  # a rationale that only repeats the rule says nothing
    note = f"why: {why}; source: `{rid}`" if why else f"source: `{rid}`"
    return f"- {rule}. _({note})_"


def expected_bullet(memory_dir: Path, item: dict) -> str:
    """The bullet `promote` would write for this item now."""
    item = {**item, "_memory_dir": Path(memory_dir)}
    rule, why = _item_texts(item)
    custom = (item.get("meta") or {}).get("promoted_rule")
    return render_bullet(item["id"], custom or rule, why)


# --------------------------------------------------------------------------- #
# The block
# --------------------------------------------------------------------------- #


def block_text(text: str) -> str | None:
    """The promoted-rules region of an instruction file, markers included."""
    if PROMOTED_BEGIN not in text:
        return None
    _, _, rest = text.partition(PROMOTED_BEGIN)
    inner, sep, _ = rest.partition(PROMOTED_END)
    return PROMOTED_BEGIN + inner + (PROMOTED_END if sep else "")


def read_bullets(path: Path) -> list[tuple[str | None, str]]:
    """`[(source id or None, line)]` for every bullet in the file's block."""
    if not path.is_file():
        return []
    block = block_text(cli.read_text_lenient(path)[0])
    if block is None:
        return []
    out = []
    for line in block.splitlines():
        if line.lstrip().startswith("- "):
            m = _SOURCE_RE.search(line)
            out.append((m.group(1) if m else None, line.rstrip()))
    return out


def _write_block(path: Path, bullets: list[str]) -> bool:
    """Rewrite the block with `bullets`; remove it entirely when there are none."""
    if not bullets:
        return cli.rewrite_managed_block(path, PROMOTED_BEGIN, PROMOTED_END, None)
    block = "\n".join([PROMOTED_BEGIN, PROMOTED_HEADING, *bullets, PROMOTED_END]) + "\n"
    return cli.rewrite_managed_block(path, PROMOTED_BEGIN, PROMOTED_END, block)


def _upsert(path: Path, rid: str, bullet: str) -> None:
    lines = [line for sid, line in read_bullets(path) if sid != rid]
    lines.append(bullet)
    _write_block(path, lines)


def _remove(path: Path, rid: str) -> bool:
    current = read_bullets(path)
    kept = [line for sid, line in current if sid != rid]
    if len(kept) == len(current):
        return False
    _write_block(path, kept)
    return True


def promoted_to(item_or_trap: dict) -> str | None:
    """Where a record, trap dict or `find_item` result is promoted, if anywhere."""
    meta = item_or_trap.get("meta") or {}
    if meta.get("promoted_to"):
        return str(meta["promoted_to"])
    body = item_or_trap.get("body") or ""
    m = _BLOCK_PROMOTED_LINE_RE.search(body) if body else None
    if m:
        return cli._strip_inline_comment(m.group(1)).strip() or None
    path = item_or_trap.get("record_path")
    if path:
        rec = cli.Record.from_file(Path(path), "trap")
        if not rec.error and rec.meta.get("promoted_to"):
            return str(rec.meta["promoted_to"])
    return None


# --------------------------------------------------------------------------- #
# Recording the promotion on the source
# --------------------------------------------------------------------------- #


def _set_fields(memory_dir: Path, item: dict, fields: dict) -> dict:
    """Set (or, with None, remove) frontmatter keys on a record file — or, for a
    trap block, the `- Promoted to:` bullet. Validate-gated; reverted on failure."""
    memory_dir = Path(memory_dir)
    path = Path(item["path"])
    original = path.read_text(encoding="utf-8")
    if path.parent.name in cli.DIR_TYPES:
        meta, body = cli.parse_frontmatter(original)
        for key, value in fields.items():
            if value is None:
                meta.pop(key, None)
            else:
                meta[key] = value
        try:
            new_text = cli.render_frontmatter(meta) + "\n" + body.lstrip("\n")
        except ValueError as exc:
            return {"ok": False, "error": f"cannot re-render frontmatter: {exc}"}
    else:
        # A trap block in known-traps.md (schema 2).
        span = next(
            (
                (start, end)
                for start, end, heading in cli._md_heading_spans(original)
                if heading.partition(":")[0].strip().lower() == item["id"].lower()
            ),
            None,
        )
        if span is None:
            return {"ok": False, "error": f"could not locate the {item['id']} block"}
        start, end = span
        block = original[start:end]
        target = fields.get("promoted_to")
        if target:
            block = cli._set_block_bullet(block, PROMOTED_BULLET_KEY, target)
        else:
            block = "".join(
                ln
                for ln in block.splitlines(keepends=True)
                if not _BLOCK_PROMOTED_LINE_RE.match(ln)
            )
        new_text = original[:start] + block + original[end:]
    cli.write_text_atomic(path, new_text)
    fails = cli._validate_new_file(memory_dir, path)
    if fails:
        cli.write_text_atomic(path, original)
        return {"ok": False, "error": "; ".join(f["message"] for f in fails)}
    return {"ok": True}


def _resolve_target(root: Path, to: str | None) -> tuple[Path | None, str | None]:
    root = Path(root)
    if to:
        name = to.strip()
        if name not in PROMOTE_TARGETS:
            return None, f"--to must be one of {', '.join(PROMOTE_TARGETS)}"
        path = root / name
        if not path.is_file():
            return None, f"{name} does not exist; create it first (promote never creates it)"
        return path, None
    for name in PROMOTE_TARGETS:
        if (root / name).is_file():
            return root / name, None
    return None, (
        f"no {' or '.join(PROMOTE_TARGETS)} in {root}; create the instruction file your agent "
        "reads (promote never creates it), or pass --to"
    )


# --------------------------------------------------------------------------- #
# WM-40 / WM-41: promote and demote
# --------------------------------------------------------------------------- #


def promote(
    memory_dir: Path,
    root: Path,
    rid: str,
    *,
    to: str | None = None,
    rule: str | None = None,
    default_rule: bool = False,
) -> dict:
    """Write `rid` into the long-term file as one rule. Returns `{ok, code?, …}`.

    Re-promoting keeps an earlier `--rule` override unless a new `rule` is
    given or `default_rule` asks for the rendered text again — so the drift
    check's hint (`crumb promote <id>`) re-renders a rule without discarding
    the wording its author chose.
    """
    memory_dir, root = Path(memory_dir), Path(root)
    item = cli.find_item(memory_dir, rid)
    if item is None:
        return {"ok": False, "code": 2, "error": f"no record or trap with id {rid!r}"}
    if item["kind"] not in PROMOTABLE_TYPES:
        return {
            "ok": False,
            "code": 2,
            "error": f"{item['id']} is a {item['kind']}; promote takes decisions, attempts and traps",
        }
    if (item.get("status") or "active") != "active":
        return {
            "ok": False,
            "code": 2,
            "error": f"{item['id']} is {item['status']}; only an active record can become a rule",
        }
    if str((item.get("meta") or {}).get("confidence") or "") == "low":
        return {
            "ok": False,
            "code": 2,
            "error": f"{item['id']} is confidence: low; add evidence before making it permanent",
        }
    target, problem = _resolve_target(root, to)
    if problem:
        return {"ok": False, "code": 2, "error": problem}
    rule = (rule or "").strip() or None
    if rule and "\n" in rule:
        return {"ok": False, "code": 2, "error": "--rule must be one line"}
    if rule is None and not default_rule:
        rule = (item.get("meta") or {}).get("promoted_rule") or None

    # Moving between files: take it out of the old one — and remember what it
    # said, so a failure below can put it back rather than lose the rule.
    previous = promoted_to({**item, "body": ""}) or promoted_to(
        cli.find_trap_by_id(memory_dir, item["id"]) or {}
    )
    moved_from: tuple[Path, str] | None = None
    if previous and previous != target.name and (root / previous).is_file():
        old_line = next(
            (line for sid, line in read_bullets(root / previous) if sid == item["id"]), None
        )
        if _remove(root / previous, item["id"]) and old_line:
            moved_from = (root / previous, old_line)

    bullet = expected_bullet(
        memory_dir, {**item, "meta": {**(item.get("meta") or {}), "promoted_rule": rule}}
    )
    _upsert(target, item["id"], bullet)
    fields = {"promoted_to": target.name, "promoted_at": cli.now_iso(), "promoted_rule": rule}
    res = _set_fields(memory_dir, item, fields)
    if not res.get("ok"):
        _remove(target, item["id"])
        if moved_from:
            _upsert(moved_from[0], item["id"], moved_from[1])
        return {"ok": False, "code": 1, "error": f"could not record the promotion: {res['error']}"}
    cli.reindex_projections(memory_dir, root)
    return {"ok": True, "id": item["id"], "kind": item["kind"], "to": target.name, "rule": bullet}


def demote(memory_dir: Path, root: Path, rid: str, *, reason: str | None = None) -> dict:
    """Remove `rid`'s rule from the long-term file and clear its promotion fields."""
    memory_dir, root = Path(memory_dir), Path(root)
    item = cli.find_item(memory_dir, rid)
    rid = item["id"] if item else rid
    was_promoted = item is not None and bool(
        promoted_to(item) or promoted_to(cli.find_trap_by_id(memory_dir, rid) or {})
    )
    # A bullet whose record is gone can still be demoted by id — that is how the
    # audit's demote-candidate finding is answered.
    removed_from = [name for name in PROMOTE_TARGETS if _remove(root / name, rid)]
    if not removed_from and not was_promoted:
        if item is None:
            return {"ok": False, "code": 2, "error": f"no record, trap or promoted rule {rid!r}"}
        return {"ok": False, "code": 1, "error": f"{rid} is not promoted"}
    if was_promoted:
        res = _set_fields(
            memory_dir, item, {"promoted_to": None, "promoted_at": None, "promoted_rule": None}
        )
        if not res.get("ok"):
            return {
                "ok": False,
                "code": 1,
                "error": f"could not clear the promotion: {res['error']}",
            }
    cli.reindex_projections(memory_dir, root)
    return {"ok": True, "id": rid, "removed_from": removed_from, "reason": reason}


def auto_demote(memory_dir: Path, rid: str, status: str) -> dict | None:
    """Demote a promoted record that `status` retires. None when nothing to do."""
    if status not in RETIRING_STATUSES:
        return None
    memory_dir = Path(memory_dir)
    item = cli.find_item(memory_dir, rid)
    if item is None or item["kind"] not in PROMOTABLE_TYPES:
        return None
    where = promoted_to(item) or promoted_to(cli.find_trap_by_id(memory_dir, item["id"]) or {})
    if not where:
        return None
    return demote(memory_dir, memory_dir.parent, item["id"], reason=f"marked {status}")


# --------------------------------------------------------------------------- #
# Readers: what is promoted
# --------------------------------------------------------------------------- #


def is_promoted_record(rec) -> bool:
    return bool(rec.meta.get("promoted_to"))


def is_promoted_trap(trap: dict) -> bool:
    return bool(promoted_to(trap))


# --------------------------------------------------------------------------- #
# WM-40/42/43: audit and doctor
# --------------------------------------------------------------------------- #


def audit_findings(memory_dir: Path, root: Path) -> list[dict]:
    memory_dir, root = Path(memory_dir), Path(root)
    findings: list[dict] = []
    promoted_ids: set[str] = set()
    for name in PROMOTE_TARGETS:
        path = root / name
        if not path.is_file():
            continue
        block = block_text(cli.read_text_lenient(path)[0])
        if block is None:
            continue
        if len(block) > cli.ADAPTER_BLOAT_CHARS:
            findings.append(
                cli._audit_finding(
                    "promoted-bloat",
                    cli.AUDIT_WARN,
                    name,
                    f"the promoted-rules block in {name} is {len(block)} chars (over "
                    f"{cli.ADAPTER_BLOAT_CHARS}); every session loads it — demote rules that "
                    "no longer earn a place (`crumb demote <id>`)",
                )
            )
        for sid, line in read_bullets(path):
            if sid is None:
                findings.append(
                    cli._audit_finding(
                        "demote-candidate",
                        cli.AUDIT_WARN,
                        name,
                        f"a rule in {name}'s promoted block names no source record: {line.strip()[:80]}",
                    )
                )
                continue
            promoted_ids.add(sid)
            item = cli.find_item(memory_dir, sid)
            if item is None:
                findings.append(
                    cli._audit_finding(
                        "demote-candidate",
                        cli.AUDIT_WARN,
                        name,
                        f"promoted rule's source {sid} no longer exists — `crumb demote {sid}`",
                        id=sid,
                    )
                )
                continue
            if (item.get("status") or "active") != "active":
                findings.append(
                    cli._audit_finding(
                        "demote-candidate",
                        cli.AUDIT_WARN,
                        name,
                        f"promoted rule's source {sid} is {item['status']} — `crumb demote {sid}`",
                        id=sid,
                    )
                )
                continue
            if expected_bullet(memory_dir, item).strip() != line.strip():
                findings.append(
                    cli._audit_finding(
                        "promoted-drift",
                        cli.AUDIT_INFO,
                        name,
                        f"the promoted rule for {sid} no longer matches its record (edited by "
                        f"hand, or the record changed) — `crumb promote {sid}` re-renders it",
                        id=sid,
                    )
                )

    from breadcrumbs import usage as _usage

    usage = _usage.load_usage(memory_dir)["records"]
    for rtype in ("decision", "attempt"):
        for rec in cli.active_records(memory_dir, rtype):
            rid = rec.meta.get("id", rec.stem)
            if rid in promoted_ids or rec.meta.get("promoted_to"):
                continue
            if str(rec.meta.get("confidence") or "") == "low":
                continue
            age = cli._age_days(rec.meta.get("created_at"))
            if age is None or age < PROMOTE_MIN_AGE_DAYS:
                continue
            entry = usage.get(rid) if isinstance(usage.get(rid), dict) else {}
            sessions = entry.get("sessions") if isinstance(entry.get("sessions"), list) else []
            if len(set(sessions)) < PROMOTE_MIN_SESSIONS:
                continue
            findings.append(
                cli._audit_finding(
                    "promote-candidate",
                    cli.AUDIT_INFO,
                    str(rec.path.relative_to(memory_dir)),
                    f"{rid} has held for {age} days and surfaced in {len(set(sessions))} "
                    f"sessions — make it a standing rule with `crumb promote {rid}`",
                    id=rid,
                )
            )
    return findings


def doctor_summary(root: Path) -> dict:
    """`{files: {name: {rules, chars}}, rules, chars}` across the instruction files."""
    out: dict = {"files": {}, "rules": 0, "chars": 0}
    for name in PROMOTE_TARGETS:
        path = Path(root) / name
        if not path.is_file():
            continue
        block = block_text(cli.read_text_lenient(path)[0])
        if block is None:
            continue
        n = len(read_bullets(path))
        out["files"][name] = {"rules": n, "chars": len(block)}
        out["rules"] += n
        out["chars"] += len(block)
    return out


def strip_block(text: str) -> str:
    """`text` without its promoted-rules block (for the signpost duplication check)."""
    block = block_text(text)
    return text.replace(block, "") if block else text


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def add_promote(sub, global_parser) -> None:
    p = sub.add_parser(
        "promote",
        parents=[global_parser],
        help="make a durable decision, attempt or trap a standing rule in CLAUDE.md/AGENTS.md",
    )
    p.add_argument("record_id", metavar="ID", help="decision, attempt or trap id")
    p.add_argument(
        "--to",
        choices=PROMOTE_TARGETS,
        default=None,
        help="instruction file (default: the first of CLAUDE.md, AGENTS.md that exists)",
    )
    p.add_argument(
        "--rule",
        default=None,
        help="one-line rule text (default: rendered from the record, or the rule given last time)",
    )
    p.add_argument(
        "--default-rule",
        action="store_true",
        help="drop an earlier --rule and render the rule from the record again",
    )
    p.set_defaults(func=cmd_promote)


def add_demote(sub, global_parser) -> None:
    p = sub.add_parser(
        "demote",
        parents=[global_parser],
        help="take a promoted rule back out of CLAUDE.md/AGENTS.md (the record stays)",
    )
    p.add_argument("record_id", metavar="ID", help="the promoted record's id")
    p.add_argument(
        "--reason", default=None, help="why (echoed in the output; the record is not changed)"
    )
    p.set_defaults(func=cmd_demote)


def _memory_dir(args):
    root = cli.resolve_root(args.project)
    memory_dir = root / cli.MEMORY_DIRNAME
    if not memory_dir.is_dir():
        cli._emit_error(args, f"no {cli.MEMORY_DIRNAME}/ found at {root}. Run `crumb init` first.")
        return None, root
    return memory_dir, root


def cmd_promote(args) -> int:
    memory_dir, root = _memory_dir(args)
    if memory_dir is None:
        return 2
    res = promote(
        memory_dir, root, args.record_id, to=args.to, rule=args.rule, default_rule=args.default_rule
    )
    if not res.get("ok"):
        cli._emit_error(args, res["error"])
        return res.get("code", 1)
    if args.json:
        cli._print_json(args, res)
        return 0
    print(f"Promoted {res['id']} to {res['to']}:")
    print(f"  {res['rule']}")
    print(
        "  The record stays active; the packet now leaves it out because the rule is in "
        f"{res['to']}. Take it back out with `crumb demote {res['id']}`."
    )
    return 0


def cmd_demote(args) -> int:
    memory_dir, root = _memory_dir(args)
    if memory_dir is None:
        return 2
    res = demote(memory_dir, root, args.record_id, reason=args.reason)
    if not res.get("ok"):
        cli._emit_error(args, res["error"])
        return res.get("code", 1)
    if args.json:
        cli._print_json(args, res)
        return 0
    where = ", ".join(res["removed_from"]) or "its record"
    print(f"Demoted {res['id']} (removed from {where}). The record itself is unchanged.")
    if res.get("reason"):
        print(f"  reason: {res['reason']}")
    return 0
