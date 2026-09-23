"""breadcrumbs relevance evals (WM-61).

Nothing else measures whether retrieval gets better or worse. A change to the
stemmer, a scoring weight or the packet's ordering can move what an agent sees
for a task without failing a single unit test. This harness pins that down: a
few synthetic stores, a list of tasks per store, and for each task the records
that must surface (`expect`) and the ones that must not (`reject`).

Run it from the repo root (stdlib only, nothing to install):

    python evals/run.py                     # print the table, compare with the baseline
    python evals/run.py --verbose           # also list every task's misses
    python evals/run.py --write-baseline    # accept the current numbers
    python evals/run.py --json              # machine-readable results

Exit codes: 0 no regression, 1 a metric fell below `baseline.json` by more than
`TOLERANCE` (or a reject hit / wrong guard verdict appeared), 2 a suite is
malformed (an unknown id in `tasks.yml`, a store command that failed).

What is measured, per task:

- **prompt** — `hooks_prompt.retrieve(prompt=task)`: what the UserPromptSubmit
  hook would inject. Its ranking is its own output order.
- **packet** — `build_resume_packet(task=…)`: which records the task-ordered
  packet keeps, ranked by the same task score that orders it. The recency floor
  keeps the newest entries of each section first whatever the task is; that is
  a reading-order rule, not relevance, so it is not what is ranked here.
- **guard** — for a task that names `verdict`, the verdict `crumb guard` gives
  the task text treated as an action must be one of those listed.

`precision@5` is the share of the top 5 that is expected, over tasks that expect
something (nothing shown when something was expected scores 0). `recall@5` is
the share of `expect` found in the top 5. `reject_hits` counts `reject` ids in a
top 5. For the prompt hook, `quiet` is the share of control tasks (`expect: []`)
where it injected nothing: a hook that fires on everything is noise.

Each suite is a directory under `evals/suites/` with:

- `store.crumb` — the commands that build the store, one per `@DATE` line
  (continuation lines are indented). Each runs with the clock set to that date,
  through `crumb.main`, so the store is made by the same writers a user's is.
- `files/` (optional) — copied into the store as-is (`aliases.txt`, say).
- `tasks.yml` — `as_of` (the clock for the queries) and the tasks.

Stores are built in a temporary directory on every run; nothing in the repo is
written except `baseline.json`, and only with `--write-baseline`.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import io
import json
import shlex
import shutil
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

TOP_K = 5
TOLERANCE = 0.05
SYSTEMS = ("prompt", "packet")
# Higher is better for these; a drop past TOLERANCE is a regression.
RATE_METRICS = ("precision_at_5", "recall_at_5", "quiet", "guard_accuracy")
# Lower is better; any increase is a regression.
COUNT_METRICS = ("reject_hits",)
TASK_KEYS = {"task", "expect", "reject", "verdict", "files", "note"}
VERDICTS = set(cli.GUARD_VERDICT_EXIT_CODES)


class SuiteError(Exception):
    """A suite that cannot be run as written (exit 2)."""


# ---- tasks.yml: a small, strict YAML subset -------------------------------- #


def _strip_comment(line: str) -> str:
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def _scalar(raw: str, where: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
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


def parse_tasks(text: str, source: str = "tasks.yml") -> dict:
    """Parse the `tasks.yml` subset: top-level keys, and `tasks:` as a list of maps.

    Values are a quoted or bare string, or a one-line `[a, b]` list. Anything
    else is an error rather than a guess — a silently misread task would pass
    or fail for a reason nobody wrote down.
    """
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
            if key == "tasks":
                if rest.strip():
                    raise SuiteError(f"{where}: `tasks:` takes an indented list")
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
            raise SuiteError(f"{where}: a task must start with `- `")
        key, sep, rest = body.partition(":")
        if not sep:
            raise SuiteError(f"{where}: expected `key: value`")
        key = key.strip()
        if key not in TASK_KEYS:
            raise SuiteError(f"{where}: unknown task key {key!r}")
        if key in current:
            raise SuiteError(f"{where}: duplicate key {key!r}")
        current[key] = _value(rest, where)
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
    doc["tasks"] = tasks
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
    with mock.patch.object(cli, "_now", return_value=_clock(first)):
        code, out = _quiet_main(["init", "--project", str(project), "--session-tracking", "full"])
    if code != 0:
        raise SuiteError(f"{suite_dir.name}: init failed:\n{out}")
    for date, argv in commands:
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


# ---- running --------------------------------------------------------------- #


def _packet_ranking(memory_dir: Path, root: Path, task: str) -> list[str]:
    packet = cli.build_resume_packet(memory_dir, root, task=task)
    scores = cli.task_relevance_scores(memory_dir, root, task)
    seen: list[str] = []
    for key, id_of in cli._RELEVANCE_SECTIONS.items():
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


def run_suite(suite_dir: Path) -> dict:
    """Build the suite's store, run every task, return per-task and summary results."""
    suite_dir = Path(suite_dir)
    spec = parse_tasks((suite_dir / "tasks.yml").read_text("utf-8"), f"{suite_dir.name}/tasks.yml")
    as_of = str(spec.get("as_of") or "")
    try:
        now = _clock(as_of)
    except ValueError:
        raise SuiteError(f"{suite_dir.name}/tasks.yml: `as_of` must be YYYY-MM-DD") from None
    with tempfile.TemporaryDirectory(prefix="crumb-eval-") as tmp:
        project = Path(tmp) / suite_dir.name
        memory_dir = build_store(suite_dir, project)
        with mock.patch.object(cli, "_now", return_value=now):
            known = {item["id"] for item in cli._candidate_items(memory_dir, include_ideas=True)}
            for i, task in enumerate(spec["tasks"], 1):
                unknown = sorted((set(task["expect"]) | set(task["reject"])) - known)
                if unknown:
                    raise SuiteError(
                        f"{suite_dir.name}/tasks.yml: task {i} names ids not in the store: "
                        f"{unknown}"
                    )
            results = []
            for task in spec["tasks"]:
                text = task["task"]
                row = {"task": text}
                prompt = [m["id"] for m in hooks_prompt.retrieve(memory_dir, project, text)]
                row["prompt"] = _task_metrics(prompt, task)
                row["packet"] = _task_metrics(_packet_ranking(memory_dir, project, text), task)
                if task["verdict"]:
                    verdict = cli.guard(memory_dir, project, text, files=task["files"] or None)[
                        "verdict"
                    ]
                    row["guard"] = {"verdict": verdict, "ok": verdict in task["verdict"]}
                if not task["expect"]:
                    row["control"] = True
                results.append(row)
    return {"suite": suite_dir.name, "tasks": results, "summary": summarize(results)}


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize(rows: list[dict]) -> dict:
    """Aggregate per-task rows into `{system: {metric: value}}`."""
    summary: dict = {}
    for system in SYSTEMS:
        scored = [r[system] for r in rows if "precision_at_5" in r[system]]
        metrics = {
            "precision_at_5": _mean([m["precision_at_5"] for m in scored]),
            "recall_at_5": _mean([m["recall_at_5"] for m in scored]),
            "reject_hits": sum(len(r[system]["rejected"]) for r in rows),
        }
        if system == "prompt":
            controls = [r for r in rows if r.get("control")]
            metrics["quiet"] = _mean([0.0 if r["prompt"]["top"] else 1.0 for r in controls])
        summary[system] = metrics
    guarded = [r["guard"]["ok"] for r in rows if "guard" in r]
    summary["guard"] = {"guard_accuracy": _mean([1.0 if ok else 0.0 for ok in guarded])}
    summary["tasks"] = len(rows)
    return summary


def overall(results: list[dict]) -> dict:
    return summarize([row for res in results for row in res["tasks"]])


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


def render_misses(results: list[dict]) -> str:
    lines: list[str] = []
    for res in results:
        for row in res["tasks"]:
            notes = []
            for system in SYSTEMS:
                m = row[system]
                if m["missed"]:
                    notes.append(f"{system} missed {', '.join(m['missed'])}")
                if m["rejected"]:
                    notes.append(f"{system} showed rejected {', '.join(m['rejected'])}")
                if row.get("control") and system == "prompt" and m["top"]:
                    notes.append(f"prompt spoke on a control task: {', '.join(m['top'])}")
            if "guard" in row and not row["guard"]["ok"]:
                notes.append(f"guard said {row['guard']['verdict']}")
            if notes:
                lines.append(f"- [{res['suite']}] {row['task']}")
                lines.extend(f"    {n}" for n in notes)
    return "\n".join(lines) if lines else "(no misses)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="evals/run.py", description="Relevance evals (WM-61).")
    ap.add_argument("--suites", type=Path, default=SUITES_DIR, help="suites directory")
    ap.add_argument("--baseline", type=Path, default=BASELINE_PATH, help="baseline JSON")
    ap.add_argument("--write-baseline", action="store_true", help="accept the current numbers")
    ap.add_argument("--json", action="store_true", help="print full results as JSON")
    ap.add_argument("--verbose", action="store_true", help="list every task's misses")
    args = ap.parse_args(argv)

    try:
        results = [run_suite(d) for d in discover(args.suites)]
    except SuiteError as exc:
        print(f"eval suite error: {exc}", file=sys.stderr)
        return 2
    if not results:
        print(f"no suites under {args.suites}", file=sys.stderr)
        return 2
    scopes = {res["suite"]: res["summary"] for res in results}
    scopes["overall"] = overall(results)

    baseline = {}
    if args.baseline.is_file():
        baseline = json.loads(args.baseline.read_text("utf-8")).get("scopes", {})
    problems = [] if args.write_baseline else compare(scopes, baseline)

    if args.json:
        print(json.dumps({"scopes": scopes, "results": results, "regressions": problems}, indent=2))
    else:
        print(render_table(scopes))
        if args.verbose:
            print()
            print(render_misses(results))
    if args.write_baseline:
        payload = {
            "comment": "Written by `python evals/run.py --write-baseline`. See evals/README.md.",
            "tolerance": TOLERANCE,
            "scopes": scopes,
        }
        args.baseline.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", "utf-8")
        print(f"\nbaseline written: {args.baseline}", file=sys.stderr)
        return 0
    if not baseline:
        print("\nno baseline yet: run with --write-baseline to record one", file=sys.stderr)
        return 0
    if problems:
        print("\nREGRESSION against evals/baseline.json:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    better = improvements(scopes, baseline)
    if better and not args.json:
        print("\nabove the baseline (consider --write-baseline):", file=sys.stderr)
        for b in better:
            print(f"  {b}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
