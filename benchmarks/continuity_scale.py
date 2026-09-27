"""Scale benchmark for capture, publication and retrieval (audit WP15, F23).

Builds a synthetic store of N live records (decisions, attempts and traps that
share files, tags and vocabulary the way a real store does), then measures:

- a full `crumb reindex`, and one `remember` (a write plus its reindex);
- a machine-local jot (local capture);
- the prompt and guard hooks, and an indexed search;
- per operation: wall time (median of `--repeat` untraced runs), records
  parsed, whole-store input hashes, bytes written (write amplification), and
  peak Python memory (tracemalloc, from one extra run);
- what "see also" and the conflict report still produce at N (quality: a
  projection that silently stops being built is a regression, not a speedup).

Stdlib only. Run from a source checkout:

    python benchmarks/continuity_scale.py --records 1000 --repeat 3 [--json out.json]

The numbers are local measurements on a synthetic store, not production
percentiles; they are for comparing versions on the same machine.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import crumb  # noqa: E402
from breadcrumbs import cli, path_policy  # noqa: E402

WORDS = (
    "cache queue router parser session token schema index ledger worker retry "
    "timeout backoff shard replica snapshot migration payload webhook scheduler "
    "billing invoice export import auth cookie tenant quota metrics tracing"
).split()
AREAS = ["api", "billing", "auth", "search", "ingest", "export", "infra", "web"]


class Counters:
    """Parses, hashes and bytes written while a block runs."""

    def __init__(self):
        self.parses = 0
        self.hashes = 0
        self.bytes_written = 0

    @contextlib.contextmanager
    def watch(self):
        # Actual parses: `_parse` where the parse cache exists (audit WP15),
        # else `from_bytes`, which parsed every time.
        attr = "_parse" if hasattr(cli.Record, "_parse") else "from_bytes"
        orig_parse = getattr(cli.Record, attr).__func__
        orig_hash = cli._inputs_hash
        orig_write = path_policy.write_atomic
        counters = self

        def parse(cls, *a, **k):
            counters.parses += 1
            return orig_parse(cls, *a, **k)

        def hashed(*a, **k):
            counters.hashes += 1
            return orig_hash(*a, **k)

        def write(path, data):
            counters.bytes_written += len(data)
            return orig_write(path, data)

        setattr(cli.Record, attr, classmethod(parse))
        cli._inputs_hash = hashed
        path_policy.write_atomic = write
        try:
            yield self
        finally:
            setattr(cli.Record, attr, classmethod(orig_parse))
            cli._inputs_hash = orig_hash
            path_policy.write_atomic = orig_write


def quiet(argv: list[str]) -> int:
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        try:
            return crumb.main(argv)
        except SystemExit as exc:
            return int(exc.code or 0)


def hook(event: str, payload: dict) -> int:
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        return quiet(["hook", event])
    finally:
        sys.stdin = saved


def build_store(root: Path, n: int, seed: int = 7) -> Path:
    rnd = random.Random(seed)
    for args in (["init", "-q"], ["config", "user.email", "b@b"], ["config", "user.name", "b"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "i"], cwd=root, check=True)
    quiet(["init", "--project", str(root), "--session-tracking", "full"])
    mem = root / crumb.MEMORY_DIRNAME
    quiet(
        [
            "remember",
            "decision",
            "--project",
            str(root),
            "--title",
            "Seed decision about the cache",
            "--set",
            "Decision",
            "seed",
            "--evidence",
            "file",
            "src/api/cache.py",
        ]
    )
    template = next((mem / "decisions").glob("*.md")).read_text()
    kinds = [("decisions", "decision", "dec"), ("attempts", "attempt", "att")]
    for i in range(n):
        area = rnd.choice(AREAS)
        words = rnd.sample(WORDS, 4)
        title = f"{words[0].title()} {words[1]} rule {i} for the {area} {words[2]}"
        slug = cli.slugify(title)
        dirname, rtype, prefix = kinds[i % 5 == 0]
        text = template
        text = text.replace("seed-decision-about-the-cache", slug)
        text = text.replace("Seed decision about the cache", title)
        text = text.replace("src/api/cache.py", f"src/{area}/{words[3]}.py")
        text = text.replace("type: decision", f"type: {rtype}")
        text = text.replace("dec_", f"{prefix}_", 1)
        text = text.replace("tags: []", f"tags:\n  - {area}\n  - {words[1]}")
        text = text.replace("seed", f"{' '.join(words)} in {area}; see {rnd.choice(WORDS)}")
        (mem / dirname / f"2026-09-27-{slug}.md").write_text(text)
    for f in (mem / "decisions").glob("*seed-decision*"):
        f.unlink()
    return mem


def measure(fn, repeat: int) -> dict:
    """Median wall time, parses, hashes and bytes written over `repeat` runs,
    then one more run under tracemalloc for peak memory. Timed runs are not
    traced: tracemalloc slows allocation-heavy code several-fold."""
    times, parses, hashes, written = [], [], [], []

    def once() -> Counters:
        counters = Counters()
        with counters.watch():
            t = time.perf_counter()
            code = fn()
            counters.ms = (time.perf_counter() - t) * 1000
        # A refused or failed command is not a measurement of the command.
        if code:
            raise SystemExit(f"benchmarked command exited {code}")
        return counters

    for _ in range(repeat):
        counters = once()
        times.append(counters.ms)
        parses.append(counters.parses)
        hashes.append(counters.hashes)
        written.append(counters.bytes_written)
    tracemalloc.start()
    try:
        once()
        peak = tracemalloc.get_traced_memory()[1] / 1e6
    finally:
        tracemalloc.stop()
    return {
        "ms": round(statistics.median(times), 1),
        "parses": int(statistics.median(parses)),
        "input_hashes": int(statistics.median(hashes)),
        "bytes_written": int(statistics.median(written)),
        "peak_mb": round(peak, 1),
    }


def run(n: int, repeat: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        mem = build_store(root, n)
        quiet(["reindex", "--project", str(root)])
        out: dict = {"records": n}
        out["reindex"] = measure(lambda: quiet(["reindex", "--project", str(root)]), repeat)
        counter = iter(range(10**6))
        out["remember"] = measure(
            lambda: quiet(
                [
                    "remember",
                    "decision",
                    "--project",
                    str(root),
                    "--title",
                    f"Benchmark decision {next(counter)} about the scheduler",
                    "--set",
                    "Decision",
                    "x",
                    "--evidence",
                    "file",
                    "src/infra/scheduler.py",
                    "--allow-duplicate",
                ]
            ),
            repeat,
        )
        out["jot_local"] = measure(
            lambda: quiet(
                [
                    "jot",
                    f"local note {next(counter)} about the cache",
                    "--local",
                    "--allow-duplicate",
                    "--project",
                    str(root),
                ]
            ),
            repeat,
        )
        out["prompt_hook"] = measure(
            lambda: hook(
                "prompt",
                {
                    "cwd": tmp,
                    "session_id": f"p{next(counter)}",
                    "prompt": "change the billing invoice retry backoff",
                },
            ),
            repeat,
        )
        out["guard_hook"] = measure(
            lambda: hook(
                "guard",
                {
                    "cwd": tmp,
                    "session_id": f"g{next(counter)}",
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "src/billing/invoice.py", "new_string": "x"},
                },
            ),
            repeat,
        )
        out["search"] = measure(
            lambda: quiet(["search", "billing invoice retry", "--project", str(root)]), repeat
        )
        related = json.loads((mem / "generated" / "related.json").read_text())
        conflicts = json.loads((mem / "generated" / "conflicts.json").read_text())
        out["quality"] = {
            "related_items": len(related.get("related") or {}),
            "related_skipped": related.get("skipped"),
            "conflict_pairs": len(conflicts.get("conflicts") or conflicts.get("pairs") or []),
            "conflicts_skipped": conflicts.get("skipped"),
        }
        return out


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--records", type=int, nargs="+", default=[1000])
    p.add_argument("--repeat", type=int, default=3)
    p.add_argument("--json", type=Path, default=None)
    args = p.parse_args()
    results = [run(n, args.repeat) for n in args.records]
    text = json.dumps(results, indent=1)
    print(text)
    if args.json:
        args.json.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
