"""breadcrumbs relevance and delivery evals (WM-61, audit WP18).

Nothing else measures whether retrieval gets better or worse. A change to the
stemmer, a scoring weight or the packet's ordering can move what an agent sees
for a task without failing a single unit test. This harness pins that down: a
few synthetic stores, a list of tasks per store, and for each task the records
that must surface (`expect`) and the ones that must not (`reject`).

Run it from the repo root (stdlib only, nothing to install):

    python evals/run.py                     # tables, critical cases, compare with the baseline
    python evals/run.py --verbose           # also list every task's misses
    python evals/run.py --release           # the release gate: known critical failures fail too
    python evals/run.py --write-baseline --reason "why"   # record reviewed numbers
    python evals/run.py --json              # machine-readable results, definitions included

Exit codes: 0 no regression and no critical failure; 1 a metric fell below
`baseline.json` by more than `TOLERANCE` (or a count rose), a critical case
failed, a `known` marker is stale, or (with `--release`) a known critical
failure remains; 2 a suite or critical case is malformed.

Three layers, reported separately (definitions: METRIC_DEFINITIONS):

- **Ranking diagnostics** (unchanged since WM-61): `prompt` (retrieve),
  `packet` (the bounded packet re-ranked by task score) and `guard` (the
  library verdict).
- **Delivery** (audit WP18): `prompt_delivered` runs `crumb hook prompt` for
  real, with length gating, deduplication and rendering; `packet_delivered`
  scores `crumb resume --task` as printed, in reading order, with its token
  cost and declared budget; `hook_guard_accuracy` runs `crumb hook guard`.
- **Critical cases** (`evals/critical/cases.yml`): pass/fail assertions that
  no baseline can approve. See that file for the checks and markers.

Each suite is a directory under `evals/suites/` with:

- `store.crumb` — the commands that build the store, one per `@DATE` line
  (continuation lines are indented). Each runs with the clock set to that date,
  through `crumb.main`, so the store is made by the same writers a user's is.
  A line whose command starts with `!` works on the project's files and git
  history instead (health review 1.1): `!lines PATH N [TAG]` writes N numbered
  lines, `!append PATH TEXT`, `!rm PATH`, and `!commit MESSAGE` commits
  everything, dated that day. The first `!` line makes the project a git
  repository before the store is created.
- `files/` (optional) — copied into the store as-is (`aliases.txt`, say).
- `tasks.yml` — `as_of` (the clock for the queries), optionally `split:
  holdout` or `split: checks`, and the tasks. A `checks` suite has no scored
  tasks: it exists for its critical cases and is left out of every aggregate.

Stores are built in a temporary directory on every run; nothing in the repo is
written except `baseline.json`, and only with `--write-baseline --reason`.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

EVALS_DIR = Path(__file__).resolve().parent
REPO_ROOT = EVALS_DIR.parent
SUITES_DIR = EVALS_DIR / "suites"
BASELINE_PATH = EVALS_DIR / "baseline.json"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from breadcrumbs import cli, hooks_prompt  # noqa: E402
from breadcrumbs import audit as _audit  # noqa: E402
from breadcrumbs import packet as _packet  # noqa: E402
from breadcrumbs import scoring as _scoring  # noqa: E402

TOP_K = 5
TOLERANCE = 0.05
# The ranking diagnostics (WM-61). Their definitions are unchanged by audit
# WP18; see METRIC_DEFINITIONS.
SYSTEMS = ("prompt", "packet")
# What a reader actually receives (audit WP18): the hooks and `resume` run for
# real and their output is scored as printed.
DELIVERY_SYSTEMS = ("prompt_delivered", "packet_delivered")
# Higher is better for these; a drop past TOLERANCE is a regression.
RATE_METRICS = (
    "precision_at_5",
    "recall_at_5",
    "recall_in_view",
    "quiet",
    "dedupe",
    "guard_accuracy",
    "hook_guard_accuracy",
    "within_budget",
)
# Lower is better; any increase is a regression.
COUNT_METRICS = ("reject_hits",)
# Reported, never gated: cost moves with any content change.
DIAGNOSTIC_METRICS = ("tokens_mean", "tokens_max")
TASK_KEYS = {"task", "expect", "reject", "verdict", "files", "note"}
VERDICTS = set(_scoring.GUARD_VERDICT_EXIT_CODES)
# `split: holdout` in a suite's tasks.yml: a fixed scenario set, reported under
# its own scope and left out of `overall`, whose tasks are not edited to suit
# the tool (evals/README.md).
# `split: checks`: a suite that only backs critical cases (no tasks, no scope).
SPLITS = ("dev", "holdout", "checks")
CRITICAL_PATH = EVALS_DIR / "critical" / "cases.yml"

# What every reported metric means, and what it is divided by. Serialized with
# every `--json` run and every baseline, so a number never travels without its
# definition (audit F19).
METRIC_DEFINITIONS = {
    "prompt": {
        "_system": "hooks_prompt.retrieve(prompt=task): the prompt hook's ranking, "
        "before length gating, deduplication and rendering",
        "precision_at_5": {
            "definition": "|top ∩ expect| / |top|, top = the first 5 returned (fewer if fewer "
            "were returned; not divided by 5); 0 when nothing is returned",
            "denominator": "tasks with a non-empty `expect`",
        },
        "recall_at_5": {
            "definition": "|top ∩ expect| / |expect|",
            "denominator": "tasks with a non-empty `expect`",
        },
        "reject_hits": {
            "definition": "`reject` ids in a top 5, summed",
            "denominator": "all tasks",
        },
        "quiet": {
            "definition": "share of control tasks where retrieve returned nothing",
            "denominator": "control tasks (`expect: []`)",
        },
    },
    "packet": {
        "_system": "build_resume_packet(task=…): records the bounded packet kept, re-ranked by "
        "task_relevance_scores, zero-score entries dropped; not the reading order",
        "precision_at_5": {
            "definition": "as for prompt, over that re-ranked list",
            "denominator": "tasks with a non-empty `expect`",
        },
        "recall_at_5": {
            "definition": "as for prompt, over that re-ranked list",
            "denominator": "tasks with a non-empty `expect`",
        },
        "reject_hits": {
            "definition": "`reject` ids in a top 5, summed",
            "denominator": "all tasks",
        },
    },
    "guard": {
        "_system": "scoring.guard(task, files): the verdict the library computes",
        "guard_accuracy": {
            "definition": "share of tasks whose verdict is one of those listed",
            "denominator": "tasks that set `verdict`",
        },
        "hook_guard_accuracy": {
            "definition": "share of tasks where `crumb hook guard` delivered a warning exactly "
            "when PROCEED is not listed (either is fine when both PROCEED and another verdict are "
            "listed); an Edit of `files[0]` when `files` is set, else a Bash command",
            "denominator": "tasks that set `verdict`",
        },
    },
    "prompt_delivered": {
        "_system": "`crumb hook prompt` run for real (JSON in, JSON out), one fresh session "
        "per task: length gating, deduplication and rendering included",
        "precision_at_5": {
            "definition": "|delivered ∩ expect| / |delivered| over the ids in the injected text, "
            "in its order; 0 when silent",
            "denominator": "tasks with a non-empty `expect`",
        },
        "recall_at_5": {
            "definition": "|delivered ∩ expect| / |expect|",
            "denominator": "tasks with a non-empty `expect`",
        },
        "reject_hits": {"definition": "`reject` ids delivered, summed", "denominator": "all tasks"},
        "quiet": {
            "definition": "share of control tasks where the hook printed nothing",
            "denominator": "control tasks (`expect: []`)",
        },
        "dedupe": {
            "definition": "share of tasks the hook spoke on where the same prompt, repeated in "
            "the same session, was silent",
            "denominator": "tasks the hook spoke on",
        },
        "tokens_mean": {
            "definition": "mean approx_tokens of the injected text",
            "denominator": "tasks the hook spoke on",
        },
        "tokens_max": {
            "definition": "largest approx_tokens of an injected text",
            "denominator": "tasks the hook spoke on",
        },
    },
    "packet_delivered": {
        "_system": "`crumb resume --task TASK` as printed: Markdown, headers and warnings "
        "included, entries in reading order (the recency floor first)",
        "precision_at_5": {
            "definition": "|first5 ∩ expect| / |first5|, first5 = the first 5 record entries in "
            "reading order, recency-floor entries included",
            "denominator": "tasks with a non-empty `expect`",
        },
        "recall_in_view": {
            "definition": "|delivered ∩ expect| / |expect| over every record entry in the packet",
            "denominator": "tasks with a non-empty `expect`",
        },
        "reject_hits": {
            "definition": "`reject` ids among the delivered entries, summed",
            "denominator": "all tasks",
        },
        "within_budget": {
            "definition": "share of packets whose printed text is within the budget its header "
            "declares",
            "denominator": "all tasks",
        },
        "tokens_mean": {
            "definition": "mean approx_tokens of the printed packet",
            "denominator": "all tasks",
        },
        "tokens_max": {
            "definition": "largest approx_tokens of a printed packet",
            "denominator": "all tasks",
        },
    },
}


class SuiteError(Exception):
    """A suite that cannot be run as written (exit 2)."""


# ---- tasks.yml: a small, strict YAML subset -------------------------------- #


def _strip_comment(line: str) -> str:
    quote = None
    escaped = False
    for i, ch in enumerate(line):
        if quote:
            if escaped:
                escaped = False
            elif ch == "\\" and quote == '"':
                escaped = True
            elif ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


# Escapes in a double-quoted value: a task that is a multi-line command (a
# heredoc) needs `\n`, and one holding double quotes needs `\"`.
_ESCAPES = {"n": "\n", '"': '"', "\\": "\\"}


def _unescape(body: str, where: str) -> str:
    out, i = [], 0
    while i < len(body):
        ch = body[i]
        if ch == "\\":
            nxt = body[i + 1 : i + 2]
            if nxt not in _ESCAPES:
                raise SuiteError(f'{where}: unknown escape \\{nxt} (use \\n, \\" or \\\\)')
            out.append(_ESCAPES[nxt])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _scalar(raw: str, where: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        return _unescape(raw[1:-1], where)
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    if raw.startswith(("[", "{", '"', "'")):
        raise SuiteError(f"{where}: cannot parse {raw!r}")
    return raw


def _value(raw: str, where: str):
    raw = raw.strip()
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise SuiteError(f"{where}: unterminated list {raw!r}")
        inner = raw[1:-1].strip()
        if not inner:
            return []
        parts = next(csv.reader([inner], skipinitialspace=True))
        return [_scalar(p, where) for p in parts]
    return _scalar(raw, where)


def _parse_list_doc(text: str, source: str, list_key: str, allowed: set[str]) -> dict:
    """Top-level `key: value` lines, and `list_key:` as an indented list of maps."""
    doc: dict = {}
    tasks: list[dict] = []
    in_tasks = False
    current: dict | None = None
    for lineno, raw in enumerate(text.splitlines(), 1):
        where = f"{source}:{lineno}"
        line = _strip_comment(raw).rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        body = line.strip()
        if indent == 0:
            in_tasks = False
            key, sep, rest = body.partition(":")
            if not sep:
                raise SuiteError(f"{where}: expected `key: value`")
            if key == list_key:
                if rest.strip():
                    raise SuiteError(f"{where}: `{list_key}:` takes an indented list")
                in_tasks = True
                continue
            doc[key] = _value(rest, where)
            continue
        if not in_tasks:
            raise SuiteError(f"{where}: unexpected indentation")
        if body.startswith("- "):
            current = {}
            tasks.append(current)
            body = body[2:].strip()
        if current is None:
            raise SuiteError(f"{where}: an item must start with `- `")
        key, sep, rest = body.partition(":")
        if not sep:
            raise SuiteError(f"{where}: expected `key: value`")
        key = key.strip()
        if key not in allowed:
            raise SuiteError(f"{where}: unknown key {key!r}")
        if key in current:
            raise SuiteError(f"{where}: duplicate key {key!r}")
        current[key] = _value(rest, where)
    doc[list_key] = tasks
    return doc


def parse_tasks(text: str, source: str = "tasks.yml") -> dict:
    """Parse the `tasks.yml` subset: top-level keys, and `tasks:` as a list of maps.

    Values are a quoted or bare string, or a one-line `[a, b]` list. Anything
    else is an error rather than a guess — a silently misread task would pass
    or fail for a reason nobody wrote down.
    """
    doc = _parse_list_doc(text, source, "tasks", TASK_KEYS)
    tasks = doc["tasks"]
    if doc.get("split", "dev") not in SPLITS:
        raise SuiteError(f"{source}: `split` must be one of {list(SPLITS)}")
    for i, task in enumerate(tasks, 1):
        if not task.get("task"):
            raise SuiteError(f"{source}: task {i} has no `task:`")
        for key in ("expect", "reject", "verdict", "files"):
            val = task.setdefault(key, [])
            if not isinstance(val, list):
                raise SuiteError(f"{source}: task {i} `{key}` must be a list")
        bad = set(task["verdict"]) - VERDICTS
        if bad:
            raise SuiteError(f"{source}: task {i} names unknown verdicts {sorted(bad)}")
    return doc


# ---- store.crumb ----------------------------------------------------------- #


def parse_store(text: str, source: str = "store.crumb") -> list[tuple[str, list[str]]]:
    """`[(date, argv)]` from `@DATE command…` lines with indented continuations."""
    commands: list[tuple[str, list[str]]] = []
    buf: list[str] = []
    start = 0

    def flush() -> None:
        if not buf:
            return
        try:
            tokens = shlex.split(" ".join(buf))
        except ValueError as exc:
            raise SuiteError(f"{source}:{start}: {exc}") from None
        if not tokens or not tokens[0].startswith("@"):
            raise SuiteError(f"{source}:{start}: a command starts with `@DATE`")
        date = tokens[0][1:]
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except ValueError:
            raise SuiteError(f"{source}:{start}: bad date {date!r}") from None
        commands.append((date, tokens[1:]))
        buf.clear()

    for lineno, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0].isspace():
            if not buf:
                raise SuiteError(f"{source}:{lineno}: continuation with no command")
            buf.append(raw.strip())
            continue
        flush()
        start = lineno
        buf.append(raw.strip())
    flush()
    return commands


def _git(project: Path, date: str, *args: str) -> None:
    stamp = _clock(date).isoformat()
    env = {**os.environ, "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp}
    r = subprocess.run(["git", *args], cwd=str(project), env=env, capture_output=True, text=True)
    if r.returncode != 0:
        raise SuiteError(f"`git {' '.join(args)}` failed: {r.stderr.strip()}")


def _file_step(suite: str, project: Path, date: str, argv: list[str]) -> None:
    """One `!` line of a store.crumb: the project's files and history."""
    verb, args = argv[0], argv[1:]
    where = f"{suite}/store.crumb `{shlex.join(argv)}`"
    path = project / args[0] if args else None
    if verb == "!lines" and len(args) in (2, 3) and args[1].isdigit():
        tag = args[2] if len(args) == 3 else "v1"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(f"line {i} {tag}\n" for i in range(1, int(args[1]) + 1)), "utf-8")
    elif verb == "!append" and len(args) == 2:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(args[1] + "\n")
    elif verb == "!rm" and len(args) == 1:
        path.unlink()
    elif verb == "!commit" and len(args) == 1:
        _git(project, date, "add", "-A")
        _git(project, date, "commit", "-q", "-m", args[0])
    else:
        raise SuiteError(f"{where}: unknown or malformed file step")


def _clock(date: str) -> datetime:
    return datetime.strptime(date, "%Y-%m-%d").replace(hour=12, tzinfo=timezone.utc)


def _quiet_main(argv: list[str]) -> tuple[int, str]:
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = cli.main(argv)
    return code, out.getvalue()


def build_store(suite_dir: Path, project: Path) -> Path:
    """Build the suite's store under `project`; return its memory dir."""
    commands = parse_store(
        (suite_dir / "store.crumb").read_text("utf-8"), f"{suite_dir.name}/store.crumb"
    )
    if not commands:
        raise SuiteError(f"{suite_dir.name}/store.crumb has no commands")
    project.mkdir(parents=True, exist_ok=True)
    first = commands[0][0]
    if any(argv and argv[0].startswith("!") for _date, argv in commands):
        _git(project, first, "init", "-q", "-b", "main")
        _git(project, first, "config", "user.email", "evals@example.invalid")
        _git(project, first, "config", "user.name", "evals")
    with mock.patch.object(cli, "_now", return_value=_clock(first)):
        code, out = _quiet_main(["init", "--project", str(project), "--session-tracking", "full"])
    if code != 0:
        raise SuiteError(f"{suite_dir.name}: init failed:\n{out}")
    for date, argv in commands:
        if argv and argv[0].startswith("!"):
            _file_step(suite_dir.name, project, date, argv)
            continue
        with mock.patch.object(cli, "_now", return_value=_clock(date)):
            code, out = _quiet_main([*argv, "--project", str(project)])
        if code != 0:
            raise SuiteError(
                f"{suite_dir.name}: `crumb {shlex.join(argv)}` exited {code}:\n{out.strip()}"
            )
    memory_dir = project / cli.MEMORY_DIRNAME
    extra = suite_dir / "files"
    if extra.is_dir():
        for src in sorted(extra.rglob("*")):
            if src.is_file():
                dest = memory_dir / src.relative_to(extra)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
    return memory_dir


# ---- delivery: what a reader actually receives (audit WP18) ---------------- #

_ENTRY_RE = re.compile(r"^- `([^`]+)`")
_TRAP_ENTRY_RE = re.compile(r"^- (trap_[A-Za-z0-9_.-]+):")
_BUDGET_RE = re.compile(r"<!-- view: [^|]*\| budget: (\d+)/(\d+) ")


def delivered_ids(text: str) -> list[str]:
    """The record ids a reader is shown as entries, in reading order.

    Warnings and "landed since" lines may name a record without presenting
    it, so they are not entries. Open questions are shown by their text, and
    mapped back to their id.
    """
    ids: list[str] = []
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section.startswith(("Stale / Risk Warnings", "Landed Since")):
            continue
        match = _ENTRY_RE.match(line) or _TRAP_ENTRY_RE.match(line)
        rid = match.group(1) if match else None
        if rid is None and section.startswith("Open Questions") and line.startswith("- "):
            rid = _scoring.question_item_id(line[2:])
        if rid and rid not in ids:
            ids.append(rid)
    return ids


def _stdout_main(argv: list[str], stdin: str | None = None) -> tuple[int, str]:
    """Run the CLI as a harness would: stdout is the delivery, stderr is not."""
    out = io.StringIO()
    saved = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(stdin)
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(argv)
    finally:
        sys.stdin = saved
    return code, out.getvalue()


def _hook(event: str, payload: dict) -> dict:
    """One real hook firing: its JSON document, or `{"_malformed": text}`."""
    _code, text = _stdout_main(["hook", event], json.dumps(payload))
    text = text.strip()
    try:
        doc = json.loads(text) if text else {}
    except ValueError:
        return {"_malformed": text[:200]}
    return doc if isinstance(doc, dict) else {"_malformed": text[:200]}


def _hook_text(doc: dict) -> str:
    hso = doc.get("hookSpecificOutput") or {}
    return str(hso.get("additionalContext") or hso.get("permissionDecisionReason") or "")


def deliver_prompt(project: Path, text: str, session: str) -> dict:
    """The prompt hook, for real, twice in one session (the second tests dedupe).

    Correction capture is switched off: it is a write, not delivery, and a
    correction jot from one task would change what later tasks see.
    """
    payload = {"cwd": str(project), "session_id": session, "prompt": text}
    with mock.patch.object(hooks_prompt, "_capture_correction", lambda *a, **k: None):
        first = _hook("prompt", payload)
        second = _hook("prompt", payload)
    injected = _hook_text(first)
    return {
        "ids": delivered_ids(injected),
        "spoke": bool(injected),
        "repeat_spoke": bool(_hook_text(second)),
        "tokens": _packet.approx_tokens(injected) if injected else 0,
        "malformed": "_malformed" in first or "_malformed" in second,
    }


def deliver_packet(project: Path, text: str) -> dict:
    """`crumb resume --task TEXT` as printed."""
    _code, out = _stdout_main(["resume", "--task", text, "--project", str(project)])
    out = out.rstrip("\n")
    match = _BUDGET_RE.search(out)
    limit = int(match.group(2)) if match else None
    tokens = _packet.approx_tokens(out)
    return {
        "ids": delivered_ids(out),
        "tokens": tokens,
        "limit": limit,
        "within_budget": limit is not None and tokens <= limit,
    }


def deliver_guard_hook(project: Path, text: str, files: list[str], session: str) -> dict:
    """`crumb hook guard` on the task as a tool call: an Edit of `files[0]`, else Bash."""
    if files:
        tool = {"tool_name": "Edit", "tool_input": {"file_path": files[0], "new_string": text}}
    else:
        tool = {"tool_name": "Bash", "tool_input": {"command": text}}
    doc = _hook("guard", {"cwd": str(project), "session_id": session, **tool})
    return {"spoke": bool(_hook_text(doc)), "malformed": "_malformed" in doc}


def _hook_guard_ok(allowed: list[str], spoke: bool) -> bool:
    if allowed == ["PROCEED"]:
        return not spoke
    if "PROCEED" not in allowed:
        return spoke
    return True


# ---- critical cases (audit WP18) ------------------------------------------- #
#
# Assertions no baseline can approve. Each is pass or fail on its own; an
# aggregate equal to the baseline does not excuse one. A case that fails today
# for a reason the repair program already tracks carries `known: <finding>`:
# it is reported loudly on every run and blocks `--release`, and once it passes
# the marker must be removed (a stale marker fails the run). A capability the
# project does not claim carries `waiver: <reason>` and is reported, never gated.

CRITICAL_KEYS = {
    "id",
    "suite",
    "check",
    "task",
    "files",
    "forbid",
    "require",
    "verdict_not",
    "via",
    "known",
    "waiver",
    "note",
}
CRITICAL_CHECKS = {
    "guard_not": "scoring.guard(task) must not return any of `verdict_not`",
    "guard_cites_none": "scoring.guard(task) must cite none of `forbid` among its matches",
    "guard_no_blocking": "scoring.guard(task) must show no match as blocking (`[objects]`)",
    "guard_objects": "scoring.guard(task) must cite every `require` id as blocking (`[objects]`)",
    "hook_guard_warns": "`crumb hook guard` on the task must deliver a warning",
    "never_delivered": "no `forbid` id is delivered as an entry (`via`: prompt, packet)",
    "delivered": "every `require` id is delivered as an entry (`via`: prompt, packet)",
    "quiet": "the prompt hook prints nothing for the task",
    "delivery_bounded": "every delivered packet is within its declared budget, every prompt "
    "injection within PROMPT_HOOK_TOKEN_BUDGET, and every hook output is JSON",
    "audit_flags": "`crumb audit` questions every `require` decision (a staleness finding)",
    "audit_quiet": "`crumb audit` questions none of the `forbid` decisions",
}
# The audit findings that question whether a decision still holds (health
# review 1.1). A true staleness case must raise one of them.
AUDIT_STALENESS_CHECKS = frozenset(
    {
        "decision-evidence-rewritten",
        "decision-evidence-changed",
        "decision-aged",
        "possible-contradiction",
        "near-duplicates",
        "evidence-missing-file",
    }
)
_NO_TASK_CHECKS = {"delivery_bounded", "audit_flags", "audit_quiet"}
_VIAS = {"prompt", "packet"}


def parse_critical(text: str, source: str = "critical/cases.yml") -> list[dict]:
    doc = _parse_list_doc(text, source, "cases", CRITICAL_KEYS)
    seen: set[str] = set()
    cases = doc["cases"]
    for i, case in enumerate(cases, 1):
        for key in ("files", "forbid", "require", "verdict_not", "via"):
            val = case.setdefault(key, [])
            if not isinstance(val, list):
                raise SuiteError(f"{source}: case {i} `{key}` must be a list")
        for key in ("id", "suite", "check"):
            if not case.get(key):
                raise SuiteError(f"{source}: case {i} has no `{key}`")
        if case["id"] in seen:
            raise SuiteError(f"{source}: duplicate case id {case['id']!r}")
        seen.add(case["id"])
        if case["check"] not in CRITICAL_CHECKS:
            raise SuiteError(f"{source}: case {case['id']} has unknown check {case['check']!r}")
        if case["check"] not in _NO_TASK_CHECKS and not case.get("task"):
            raise SuiteError(f"{source}: case {case['id']} needs a `task`")
        if set(case["via"]) - _VIAS:
            raise SuiteError(f"{source}: case {case['id']} `via` must be within {sorted(_VIAS)}")
        if set(case["verdict_not"]) - VERDICTS:
            raise SuiteError(f"{source}: case {case['id']} names unknown verdicts")
        if case.get("known") and case.get("waiver"):
            raise SuiteError(f"{source}: case {case['id']} is either known or waived, not both")
    return cases


def load_critical(path: Path = CRITICAL_PATH) -> list[dict]:
    path = Path(path)
    if not path.is_file():
        return []
    return parse_critical(path.read_text("utf-8"), str(path.name))


def _critical_status(case: dict, ok: bool) -> str:
    if case.get("waiver"):
        return "waived"
    if case.get("known"):
        return "stale" if ok else "known"
    return "pass" if ok else "fail"


# ---- running --------------------------------------------------------------- #


def _packet_ranking(memory_dir: Path, root: Path, task: str) -> list[str]:
    packet = _packet.build_resume_packet(memory_dir, root, task=task)
    scores = _packet.task_relevance_scores(memory_dir, root, task)
    seen: list[str] = []
    for key, id_of in _packet._RELEVANCE_SECTIONS.items():
        for entry in packet.get(key) or []:
            rid = id_of(entry)
            if rid and rid not in seen and scores.get(rid, 0) > 0:
                seen.append(rid)
    # Stable: equal scores keep the packet's section order.
    return sorted(seen, key=lambda rid: -scores[rid])


def _task_metrics(ranking: list[str], task: dict) -> dict:
    top = ranking[:TOP_K]
    expect, reject = task["expect"], task["reject"]
    hits = [rid for rid in top if rid in expect]
    out = {
        "top": top,
        "missed": [rid for rid in expect if rid not in top],
        "rejected": [rid for rid in top if rid in reject],
    }
    if expect:
        out["precision_at_5"] = len(hits) / len(top) if top else 0.0
        out["recall_at_5"] = len(set(hits)) / len(set(expect))
    return out


def _delivered_packet_metrics(delivery: dict, task: dict) -> dict:
    ids = delivery["ids"]
    out = _task_metrics(ids, task)
    expect, reject = task["expect"], task["reject"]
    out["missed"] = [rid for rid in expect if rid not in ids]
    out["rejected"] = [rid for rid in ids if rid in reject]
    if expect:
        out["recall_in_view"] = len(set(expect) & set(ids)) / len(set(expect))
    out.pop("recall_at_5", None)
    out["tokens"] = delivery["tokens"]
    out["within_budget"] = delivery["within_budget"]
    return out


def _delivered_prompt_metrics(delivery: dict, task: dict) -> dict:
    out = _task_metrics(delivery["ids"], task)
    out["spoke"] = delivery["spoke"]
    out["tokens"] = delivery["tokens"]
    if delivery["spoke"]:
        out["deduped"] = not delivery["repeat_spoke"]
    out["malformed"] = delivery["malformed"]
    return out


def run_suite(suite_dir: Path, critical: list[dict] | None = None) -> dict:
    """Build the suite's store, run every task, return per-task and summary results."""
    suite_dir = Path(suite_dir)
    spec = parse_tasks((suite_dir / "tasks.yml").read_text("utf-8"), f"{suite_dir.name}/tasks.yml")
    as_of = str(spec.get("as_of") or "")
    try:
        now = _clock(as_of)
    except ValueError:
        raise SuiteError(f"{suite_dir.name}/tasks.yml: `as_of` must be YYYY-MM-DD") from None
    critical = critical or []
    with tempfile.TemporaryDirectory(prefix="crumb-eval-") as tmp:
        project = Path(tmp) / suite_dir.name
        memory_dir = build_store(suite_dir, project)
        with mock.patch.object(cli, "_now", return_value=now):
            known = {
                item["id"] for item in _scoring._candidate_items(memory_dir, include_ideas=True)
            }
            for i, task in enumerate(spec["tasks"], 1):
                unknown = sorted((set(task["expect"]) | set(task["reject"])) - known)
                if unknown:
                    raise SuiteError(
                        f"{suite_dir.name}/tasks.yml: task {i} names ids not in the store: "
                        f"{unknown}"
                    )
            for case in critical:
                unknown = sorted((set(case["forbid"]) | set(case["require"])) - known)
                if unknown:
                    raise SuiteError(
                        f"critical case {case['id']} names ids not in {suite_dir.name}: {unknown}"
                    )
            results = []
            for i, task in enumerate(spec["tasks"], 1):
                text = task["task"]
                row = {"task": text}
                prompt = [m["id"] for m in hooks_prompt.retrieve(memory_dir, project, text)]
                row["prompt"] = _task_metrics(prompt, task)
                row["packet"] = _task_metrics(_packet_ranking(memory_dir, project, text), task)
                row["prompt_delivered"] = _delivered_prompt_metrics(
                    deliver_prompt(project, text, f"eval-{suite_dir.name}-{i}"), task
                )
                row["packet_delivered"] = _delivered_packet_metrics(
                    deliver_packet(project, text), task
                )
                if task["verdict"]:
                    verdict = _scoring.guard(
                        memory_dir, project, text, files=task["files"] or None
                    )["verdict"]
                    hook = deliver_guard_hook(
                        project, text, task["files"], f"eval-guard-{suite_dir.name}-{i}"
                    )
                    row["guard"] = {
                        "verdict": verdict,
                        "ok": verdict in task["verdict"],
                        "hook_spoke": hook["spoke"],
                        "hook_ok": _hook_guard_ok(task["verdict"], hook["spoke"])
                        and not hook["malformed"],
                    }
                if not task["expect"]:
                    row["control"] = True
                results.append(row)
            crit = [
                run_critical(case, memory_dir, project, results, n)
                for n, case in enumerate(critical, 1)
            ]
    return {
        "suite": suite_dir.name,
        "split": spec.get("split", "dev"),
        "tasks": results,
        "summary": summarize(results),
        "critical": crit,
    }


def run_critical(case: dict, memory_dir: Path, project: Path, rows: list[dict], n: int) -> dict:
    """Evaluate one critical case against the suite's built store."""
    check = case["check"]
    session = f"eval-critical-{case['id']}-{n}"
    detail = ""
    if check == "guard_not":
        verdict = _scoring.guard(memory_dir, project, case["task"], files=case["files"] or None)[
            "verdict"
        ]
        ok = verdict not in case["verdict_not"]
        detail = f"guard said {verdict}"
    elif check in ("guard_cites_none", "guard_no_blocking", "guard_objects"):
        matches = _scoring.guard(memory_dir, project, case["task"], files=case["files"] or None)[
            "matches"
        ]
        if check == "guard_objects":
            blocking = {m["id"] for m in matches if m.get("stance") == "blocking"}
            bad = [rid for rid in case["require"] if rid not in blocking]
            detail = f"not blocking: {bad}" if bad else "all blocking"
        elif check == "guard_cites_none":
            bad = [m["id"] for m in matches if m["id"] in case["forbid"]]
            detail = f"cited {bad}" if bad else "none cited"
        else:
            bad = [m["id"] for m in matches if m.get("stance") == "blocking"]
            detail = f"blocking: {bad}" if bad else "nothing blocking"
        ok = not bad
    elif check == "hook_guard_warns":
        hook = deliver_guard_hook(project, case["task"], case["files"], session)
        ok = hook["spoke"] and not hook["malformed"]
        detail = "the hook delivered a warning" if ok else "the hook was silent"
    elif check in ("never_delivered", "delivered", "quiet"):
        via = case["via"] or (["prompt"] if check in ("delivered", "quiet") else sorted(_VIAS))
        shown: dict[str, list[str]] = {}
        if "prompt" in via or check == "quiet":
            shown["prompt"] = deliver_prompt(project, case["task"], session)["ids"]
        if "packet" in via and check != "quiet":
            shown["packet"] = deliver_packet(project, case["task"])["ids"]
        if check == "never_delivered":
            leaked = {w: [r for r in ids if r in case["forbid"]] for w, ids in shown.items()}
            leaked = {w: ids for w, ids in leaked.items() if ids}
            ok = not leaked
            detail = f"delivered {leaked}" if leaked else "none delivered"
        elif check == "delivered":
            missing = {w: [r for r in case["require"] if r not in ids] for w, ids in shown.items()}
            missing = {w: ids for w, ids in missing.items() if ids}
            ok = not missing
            detail = f"not delivered {missing}" if missing else "all delivered"
        else:
            ok = not shown["prompt"]
            detail = "silent" if ok else f"delivered {shown['prompt']}"
    elif check in ("audit_flags", "audit_quiet"):
        findings = _audit.run_audit(memory_dir, project)
        named: dict[str, set[str]] = {}
        for f in findings:
            if f["check"] not in AUDIT_STALENESS_CHECKS:
                continue
            for rid in [f.get("id"), *(f.get("ids") or ())]:
                if rid:
                    named.setdefault(str(rid), set()).add(f["check"])
        if check == "audit_flags":
            missing = [rid for rid in case["require"] if rid not in named]
            ok = not missing
            detail = (
                f"not questioned: {missing}"
                if missing
                else (
                    "questioned: "
                    + ", ".join(f"{r} ({'/'.join(sorted(named[r]))})" for r in case["require"])
                )
            )
        else:
            loud = {rid: sorted(named[rid]) for rid in case["forbid"] if rid in named}
            ok = not loud
            detail = f"questioned: {loud}" if loud else "none questioned"
    else:  # delivery_bounded
        problems = []
        for row in rows:
            if not row["packet_delivered"]["within_budget"]:
                problems.append(f"packet over budget for {row['task']!r}")
            if row["prompt_delivered"]["tokens"] > hooks_prompt.PROMPT_HOOK_TOKEN_BUDGET:
                problems.append(f"prompt injection over budget for {row['task']!r}")
            if row["prompt_delivered"]["malformed"]:
                problems.append(f"prompt hook output was not JSON for {row['task']!r}")
        ok = not problems
        detail = "; ".join(problems[:3]) if problems else f"{len(rows)} task(s) within bounds"
    return {
        "id": case["id"],
        "check": check,
        "status": _critical_status(case, ok),
        "ok": ok,
        "detail": detail,
        "known": case.get("known") or None,
        "waiver": case.get("waiver") or None,
        "note": case.get("note") or None,
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize(rows: list[dict]) -> dict:
    """Aggregate per-task rows into `{system: {metric: value, "n": denominators}}`."""
    summary: dict = {}
    controls = [r for r in rows if r.get("control")]
    for system in (*SYSTEMS, *DELIVERY_SYSTEMS):
        scored = [r[system] for r in rows if "precision_at_5" in r[system]]
        metrics: dict = {
            "precision_at_5": _mean([m["precision_at_5"] for m in scored]),
            "reject_hits": sum(len(r[system]["rejected"]) for r in rows),
        }
        n = {"precision_at_5": len(scored), "reject_hits": len(rows)}
        if system == "packet_delivered":
            metrics["recall_in_view"] = _mean([m["recall_in_view"] for m in scored])
            n["recall_in_view"] = len(scored)
            metrics["within_budget"] = _mean(
                [1.0 if r[system]["within_budget"] else 0.0 for r in rows]
            )
            n["within_budget"] = len(rows)
            tokens = [r[system]["tokens"] for r in rows]
        else:
            metrics["recall_at_5"] = _mean([m["recall_at_5"] for m in scored])
            n["recall_at_5"] = len(scored)
        if system in ("prompt", "prompt_delivered"):
            key = "top" if system == "prompt" else "spoke"
            metrics["quiet"] = _mean([0.0 if r[system][key] else 1.0 for r in controls])
            n["quiet"] = len(controls)
        if system == "prompt_delivered":
            spoke = [r[system] for r in rows if r[system]["spoke"]]
            metrics["dedupe"] = _mean([1.0 if m["deduped"] else 0.0 for m in spoke])
            n["dedupe"] = len(spoke)
            tokens = [m["tokens"] for m in spoke]
        if system in DELIVERY_SYSTEMS:
            metrics["tokens_mean"] = _mean([float(t) for t in tokens])
            metrics["tokens_max"] = max(tokens) if tokens else None
            n["tokens_mean"] = n["tokens_max"] = len(tokens)
        metrics["n"] = n
        summary[system] = metrics
    guarded = [r["guard"] for r in rows if "guard" in r]
    summary["guard"] = {
        "guard_accuracy": _mean([1.0 if g["ok"] else 0.0 for g in guarded]),
        "hook_guard_accuracy": _mean([1.0 if g["hook_ok"] else 0.0 for g in guarded]),
        "n": {"guard_accuracy": len(guarded), "hook_guard_accuracy": len(guarded)},
    }
    summary["tasks"] = len(rows)
    return summary


def overall(results: list[dict]) -> dict:
    return summarize([row for res in results for row in res["tasks"]])


# ---- baseline changes are reviewed task by task (audit WP18) --------------- #


def task_snapshot(results: list[dict]) -> dict:
    """What each task showed, per system: stored in the baseline for review."""
    snap: dict = {}
    for res in results:
        for row in res["tasks"]:
            entry: dict = {}
            for system in (*SYSTEMS, *DELIVERY_SYSTEMS):
                entry[system] = {
                    "missed": list(row[system]["missed"]),
                    "rejected": list(row[system]["rejected"]),
                }
            if row.get("control"):
                entry["control_spoke"] = {
                    "prompt": bool(row["prompt"]["top"]),
                    "prompt_delivered": bool(row["prompt_delivered"]["spoke"]),
                }
            if "guard" in row:
                entry["guard"] = {k: row["guard"][k] for k in ("verdict", "ok", "hook_ok")}
            snap[f"{res['suite']}::{row['task']}"] = entry
    return snap


def task_deltas(current: dict, previous: dict | None) -> dict:
    """Task-level changes from `previous` to `current` snapshot."""
    out: dict = {"regressions": [], "improvements": [], "added": [], "removed": []}
    if previous is None:
        out["added"] = sorted(current)
        out["note"] = "the old baseline had no task-level snapshot"
        return out
    out["added"] = sorted(set(current) - set(previous))
    out["removed"] = sorted(set(previous) - set(current))
    out["regressions"] += [f"{key}: task removed" for key in out["removed"]]
    for key in sorted(set(current) & set(previous)):
        cur, old = current[key], previous[key]
        for system in (*SYSTEMS, *DELIVERY_SYSTEMS):
            c, o = cur.get(system) or {}, old.get(system) or {}
            for field, worse in (("missed", "now misses"), ("rejected", "now shows rejected")):
                new = sorted(set(c.get(field) or []) - set(o.get(field) or []))
                gone = sorted(set(o.get(field) or []) - set(c.get(field) or []))
                if new:
                    out["regressions"].append(f"{key}: {system} {worse} {', '.join(new)}")
                if gone:
                    out["improvements"].append(
                        f"{key}: {system} no longer {field} {', '.join(gone)}"
                    )
        for system, spoke in (cur.get("control_spoke") or {}).items():
            was = (old.get("control_spoke") or {}).get(system)
            if spoke and was is False:
                out["regressions"].append(f"{key}: {system} now speaks on a control task")
        cg, og = cur.get("guard") or {}, old.get("guard") or {}
        for field in ("ok", "hook_ok"):
            if og.get(field) is True and cg.get(field) is False:
                out["regressions"].append(f"{key}: {field} lost (verdict {cg.get('verdict')})")
            if og.get(field) is False and cg.get(field) is True:
                out["improvements"].append(f"{key}: {field} gained (verdict {cg.get('verdict')})")
    return out


def compare(current: dict, baseline: dict, tolerance: float = TOLERANCE) -> list[str]:
    """Regressions of `current` against `baseline`, both `{scope: summary}`.

    A rate falling by more than `tolerance`, or any rise in a count, is a
    regression. A scope or metric missing from the baseline is not: it is new,
    and the next `--write-baseline` adopts it.
    """
    problems: list[str] = []
    for scope, base in sorted(baseline.items()):
        cur = current.get(scope)
        if cur is None:
            problems.append(f"{scope}: in the baseline but not run")
            continue
        for system, base_metrics in sorted(base.items()):
            if not isinstance(base_metrics, dict):
                continue
            cur_metrics = cur.get(system) or {}
            for metric, was in sorted(base_metrics.items()):
                now = cur_metrics.get(metric)
                if was is None:
                    continue
                if now is None:
                    problems.append(f"{scope} {system} {metric}: {was} -> not measured")
                elif metric in COUNT_METRICS and now > was:
                    problems.append(f"{scope} {system} {metric}: {was} -> {now}")
                elif metric in RATE_METRICS and now < was - tolerance:
                    problems.append(f"{scope} {system} {metric}: {was:.3f} -> {now:.3f}")
    return problems


def improvements(current: dict, baseline: dict, tolerance: float = TOLERANCE) -> list[str]:
    better: list[str] = []
    for scope, cur in sorted(current.items()):
        base = baseline.get(scope) or {}
        for system, metrics in sorted(cur.items()):
            if not isinstance(metrics, dict):
                continue
            for metric, now in sorted(metrics.items()):
                was = (base.get(system) or {}).get(metric)
                if now is None or was is None:
                    continue
                if (metric in RATE_METRICS and now > was + tolerance) or (
                    metric in COUNT_METRICS and now < was
                ):
                    better.append(f"{scope} {system} {metric}: {was} -> {now}")
    return better


def discover(suites_dir: Path = SUITES_DIR) -> list[Path]:
    return sorted(p for p in Path(suites_dir).iterdir() if (p / "tasks.yml").is_file())


def _fmt(value) -> str:
    if value is None:
        return "   -"
    if isinstance(value, int):
        return f"{value:4d}"
    return f"{value:.2f}"


def render_table(scopes: dict) -> str:
    lines = [
        f"{'suite':<14} {'tasks':>5}  {'system':<7} {'P@5':>5} {'R@5':>5} {'reject':>6} "
        f"{'quiet':>5}  {'guard':>5}"
    ]
    for scope, summ in scopes.items():
        for i, system in enumerate(SYSTEMS):
            m = summ[system]
            lines.append(
                f"{scope if i == 0 else '':<14} {summ['tasks'] if i == 0 else '':>5}  "
                f"{system:<7} {_fmt(m['precision_at_5']):>5} {_fmt(m['recall_at_5']):>5} "
                f"{_fmt(m['reject_hits']):>6} {_fmt(m.get('quiet')):>5}  "
                f"{_fmt(summ['guard']['guard_accuracy']) if i == 0 else '':>5}"
            )
    return "\n".join(lines)


def render_delivery_table(scopes: dict) -> str:
    """The delivered experience, as the hooks and `resume` printed it (audit WP18)."""
    lines = [
        "delivered (as printed; see METRIC_DEFINITIONS):",
        f"{'suite':<14} {'system':<7} {'P@5':>5} {'R':>5} {'reject':>6} {'quiet':>5} "
        f"{'dedup':>5} {'budget':>6} {'tok':>5} {'tokmax':>6}  {'hook-guard':>10}",
    ]
    for scope, summ in scopes.items():
        for i, (system, label) in enumerate(
            (("prompt_delivered", "prompt"), ("packet_delivered", "packet"))
        ):
            m = summ[system]
            recall = m.get("recall_at_5", m.get("recall_in_view"))
            lines.append(
                f"{scope if i == 0 else '':<14} {label:<7} {_fmt(m['precision_at_5']):>5} "
                f"{_fmt(recall):>5} {_fmt(m['reject_hits']):>6} {_fmt(m.get('quiet')):>5} "
                f"{_fmt(m.get('dedupe')):>5} {_fmt(m.get('within_budget')):>6} "
                f"{_fmt(int(m['tokens_mean']) if m.get('tokens_mean') is not None else None):>5} "
                f"{_fmt(m.get('tokens_max')):>6}  "
                f"{_fmt(summ['guard']['hook_guard_accuracy']) if i == 0 else '':>10}"
            )
    return "\n".join(lines)


def render_critical(critical: list[dict], *, release: bool) -> str:
    if not critical:
        return "critical: no cases"
    counts: dict[str, int] = {}
    for c in critical:
        counts[c["status"]] = counts.get(c["status"], 0) + 1
    order = ("fail", "stale", "known", "waived", "pass")
    head = ", ".join(f"{counts[k]} {k}" for k in order if counts.get(k))
    lines = [f"critical ({len(critical)} cases): {head}"]
    labels = {
        "fail": "FAIL",
        "stale": "STALE MARKER (it passes now: remove `known`)",
        "known": "KNOWN FAILURE" + (" — blocks release" if release else ""),
        "waived": "waived",
    }
    for c in critical:
        if c["status"] == "pass":
            continue
        tag = f" [{c['known']}]" if c.get("known") else ""
        why = f" ({c['waiver']})" if c.get("waiver") else ""
        lines.append(f"  {labels[c['status']]}{tag}: {c['id']} — {c['detail']}{why}")
    return "\n".join(lines)


def _annotate(critical: list[dict]) -> None:
    """GitHub Actions annotations, so a known failure shows on every CI run."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return
    for c in critical:
        if c["status"] in ("fail", "stale"):
            print(f"::error title=Critical eval {c['status']}::{c['id']}: {c['detail']}")
        elif c["status"] == "known":
            print(
                f"::warning title=Known critical failure ({c['known']})::{c['id']}: {c['detail']}"
            )


def render_misses(results: list[dict]) -> str:
    lines: list[str] = []
    for res in results:
        for row in res["tasks"]:
            notes = []
            for system in (*SYSTEMS, *DELIVERY_SYSTEMS):
                m = row[system]
                if m["missed"]:
                    notes.append(f"{system} missed {', '.join(m['missed'])}")
                if m["rejected"]:
                    notes.append(f"{system} showed rejected {', '.join(m['rejected'])}")
            if row.get("control") and row["prompt"]["top"]:
                notes.append(f"prompt spoke on a control task: {', '.join(row['prompt']['top'])}")
            if row.get("control") and row["prompt_delivered"]["spoke"]:
                notes.append("prompt_delivered spoke on a control task")
            if "guard" in row and not row["guard"]["ok"]:
                notes.append(f"guard said {row['guard']['verdict']}")
            if "guard" in row and not row["guard"]["hook_ok"]:
                spoke = "warned" if row["guard"]["hook_spoke"] else "was silent"
                notes.append(f"the guard hook {spoke}")
            if notes:
                lines.append(f"- [{res['suite']}] {row['task']}")
                lines.extend(f"    {n}" for n in notes)
    return "\n".join(lines) if lines else "(no misses)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals/run.py", description="Relevance and delivery evals.")
    ap.add_argument("--suites", type=Path, default=SUITES_DIR, help="suites directory")
    ap.add_argument("--baseline", type=Path, default=BASELINE_PATH, help="baseline JSON")
    ap.add_argument(
        "--critical",
        type=Path,
        default=None,
        help="critical cases (default: evals/critical/cases.yml with the default suites)",
    )
    ap.add_argument("--write-baseline", action="store_true", help="accept the current numbers")
    ap.add_argument(
        "--reason", default=None, help="why the baseline changes (required with --write-baseline)"
    )
    ap.add_argument(
        "--accept-regressions",
        action="store_true",
        help="with --write-baseline: accept the task-level regressions it lists",
    )
    ap.add_argument(
        "--release",
        action="store_true",
        help="release gate: a known critical failure fails the run too",
    )
    ap.add_argument("--json", action="store_true", help="print full results as JSON")
    ap.add_argument("--verbose", action="store_true", help="list every task's misses")
    args = ap.parse_args(argv)

    try:
        suites = discover(args.suites)
        critical_path = args.critical
        if critical_path is None and Path(args.suites).resolve() == SUITES_DIR.resolve():
            critical_path = CRITICAL_PATH
        cases = load_critical(critical_path) if critical_path else []
        names = {d.name for d in suites}
        for case in cases:
            if case["suite"] not in names:
                raise SuiteError(f"critical case {case['id']}: no suite {case['suite']!r}")
        results = [run_suite(d, [c for c in cases if c["suite"] == d.name]) for d in suites]
    except SuiteError as exc:
        print(f"eval suite error: {exc}", file=sys.stderr)
        return 2
    if not results:
        print(f"no suites under {args.suites}", file=sys.stderr)
        return 2
    scored = [res for res in results if res["split"] != "checks"]
    scopes = {res["suite"]: res["summary"] for res in scored}
    dev = [res for res in results if res["split"] == "dev"]
    holdout = [res for res in results if res["split"] == "holdout"]
    # `overall` is the development suites, as it always was; the held-out
    # scenarios are reported beside it, never folded in.
    scopes["overall"] = overall(dev or scored)
    if holdout:
        scopes["holdout"] = overall(holdout)
    critical = [c for res in results for c in res["critical"]]
    broken = [c for c in critical if c["status"] in ("fail", "stale")]
    known = [c for c in critical if c["status"] == "known"]

    old_doc: dict = {}
    if args.baseline.is_file():
        old_doc = json.loads(args.baseline.read_text("utf-8"))
    baseline = old_doc.get("scopes", {})
    snapshot = task_snapshot(scored)
    deltas = task_deltas(snapshot, old_doc.get("tasks"))
    problems = [] if args.write_baseline else compare(scopes, baseline)

    if args.json:
        print(
            json.dumps(
                {
                    "definitions": METRIC_DEFINITIONS,
                    "critical_checks": CRITICAL_CHECKS,
                    "scopes": scopes,
                    "results": results,
                    "critical": critical,
                    "task_deltas": deltas,
                    "regressions": problems,
                },
                indent=2,
            )
        )
    else:
        print(render_table(scopes))
        print()
        print(render_delivery_table(scopes))
        print()
        print(render_critical(critical, release=args.release))
        if args.verbose:
            print()
            print(render_misses(results))
    _annotate(critical)

    if args.write_baseline:
        # A baseline records what the tool does; it can never approve a
        # critical failure. Fix it, or mark it `known`/`waiver` in
        # evals/critical/cases.yml, which is reviewed like any code change.
        if broken:
            print(
                "\nrefusing to write the baseline: critical cases fail "
                f"({', '.join(c['id'] for c in broken)})",
                file=sys.stderr,
            )
            return 1
        if not args.reason:
            print("\n--write-baseline needs --reason: say why the numbers change", file=sys.stderr)
            return 2
        print("\ntask-level changes against the old baseline:", file=sys.stderr)
        for kind in ("regressions", "improvements", "added", "removed"):
            for item in deltas[kind]:
                print(f"  {kind[:-1] if kind.endswith('s') else kind}: {item}", file=sys.stderr)
        if deltas["regressions"] and not args.accept_regressions:
            print(
                f"\nrefusing to write the baseline: {len(deltas['regressions'])} task-level "
                "regression(s) above. Review each; if they are the intended cost of the change, "
                "rerun with --accept-regressions.",
                file=sys.stderr,
            )
            return 1
        changes = list(old_doc.get("changes") or [])
        changes.append(
            {
                "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                "reason": args.reason,
                "regressions": deltas["regressions"],
                "improvements": deltas["improvements"],
                "added": len(deltas["added"]),
                "removed": deltas["removed"],
            }
        )
        payload = {
            "comment": "Written by `python evals/run.py --write-baseline --reason …`. "
            "See evals/README.md.",
            "tolerance": TOLERANCE,
            "definitions": METRIC_DEFINITIONS,
            "scopes": scopes,
            "tasks": snapshot,
            "changes": changes,
        }
        args.baseline.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
        print(f"\nbaseline written: {args.baseline}", file=sys.stderr)
        return 0

    code = 0
    if baseline and problems:
        print("\nREGRESSION against evals/baseline.json:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        code = 1
    if broken:
        print("\nCRITICAL: cases fail regardless of the baseline:", file=sys.stderr)
        for c in broken:
            print(f"  {c['id']} — {c['detail']}", file=sys.stderr)
        code = 1
    if known:
        verb = "block the release" if args.release else "are open (they block --release)"
        print(f"\nknown critical failures {verb}:", file=sys.stderr)
        for c in known:
            print(f"  [{c['known']}] {c['id']} — {c['detail']}", file=sys.stderr)
        if args.release:
            code = 1
    if not baseline:
        print(
            "\nno baseline yet: run with --write-baseline --reason … to record one", file=sys.stderr
        )
        return code
    better = improvements(scopes, baseline)
    if better and not args.json and code == 0:
        print("\nabove the baseline (consider --write-baseline):", file=sys.stderr)
        for b in better:
            print(f"  {b}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
