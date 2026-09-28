"""WP15 behavior check: one tree, in a subprocess, on a 2,050-decision store.

Usage: python behavior.py <source-tree>
Each check is phrased so that `true` is the defect. The store is synthetic and
the same for both trees (seeded).
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(sys.argv[1]).resolve()
MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")
ENV = {k: v for k, v in os.environ.items() if k not in MARKERS}

PROBE = r"""
import contextlib, io, json, random, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import crumb
from breadcrumbs import cli, lifecycle

root = Path(sys.argv[2]); N = 2050
mem = root / ".project-memory"

def run(argv):
    with contextlib.redirect_stdout(io.StringIO()) as o, contextlib.redirect_stderr(io.StringIO()):
        try:
            return crumb.main(argv), o.getvalue()
        except SystemExit as e:
            return e.code, o.getvalue()

for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
    subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)
subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "i"], cwd=root, check=True)
run(["init", "--project", str(root), "--session-tracking", "full"])
run(["remember", "decision", "--project", str(root), "--title", "Seed decision about the cache",
     "--set", "Decision", "seed text", "--evidence", "file", "src/api/cache.py"])
seed = next((mem / "decisions").glob("*.md")); template = seed.read_text(); seed.unlink()
words = ("cache queue router parser session token schema index ledger worker retry timeout "
         "backoff shard replica snapshot migration payload webhook scheduler billing invoice "
         "export import auth cookie tenant quota metrics tracing").split()
areas = ["api", "billing", "auth", "search", "ingest", "export", "infra", "web"]
rnd = random.Random(15)

def write(slug, title, body, file, tags, stamp):
    text = (template.replace("seed-decision-about-the-cache", slug)
            .replace("Seed decision about the cache", title).replace("seed text", body)
            .replace("src/api/cache.py", file).replace("tags: []", "tags:\n" + "".join(f"  - {t}\n" for t in tags).rstrip("\n")))
    p = mem / "decisions" / f"{stamp}-{slug}.md"
    rid, s = cli.derive_identity(p.stem, "decision")
    text = re.sub(r"(?m)^id: .*$", f"id: {rid}", text, count=1)
    text = re.sub(r"(?m)^slug: .*$", f"slug: {s}", text, count=1)
    p.write_text(text)
    return rid

for i in range(N):
    w = rnd.sample(words, 4); area = rnd.choice(areas)
    title = f"{w[0].title()} {w[1]} rule {i} for the {area} {w[2]}"
    write(cli.slugify(title), title, f"{' '.join(w)} in {area}", f"src/{area}/{w[3]}.py",
          [area, w[1]], f"2026-0{1 + i % 9}-{1 + i % 27:02d}")
twins = sorted(write(f"quorvex-lattice-twin-{t}", "Quorvex lattice flange tessel",
                     "quorvex lattice flange tessel marrow", "src/q/lattice.py", ["quorvex"], stamp)
               for t, stamp in (("one", "2026-01-05"), ("two", "2026-02-05")))

# Count actual parses, and actual contradiction computations.
parse_attr = "_parse" if hasattr(cli.Record, "_parse") else "from_bytes"
orig_parse = getattr(cli.Record, parse_attr).__func__
counts = {"parses": 0, "conflicts": 0}
def parse(cls, *a, **k):
    counts["parses"] += 1
    return orig_parse(cls, *a, **k)
setattr(cli.Record, parse_attr, classmethod(parse))
conf_attr = "_contradictions" if hasattr(lifecycle, "_contradictions") else "find_contradictions"
orig_conf = getattr(lifecycle, conf_attr)
def conf(*a, **k):
    counts["conflicts"] += 1
    return orig_conf(*a, **k)
setattr(lifecycle, conf_attr, conf)

code, _ = run(["reindex", "--project", str(root)])
out = {"records": N + 2, "reindex_exit": code, "parses_per_reindex": counts["parses"],
       "conflict_computations_per_reindex": counts["conflicts"]}
related = json.loads((mem / "generated" / "related.json").read_text())
out["related_skipped"] = related.get("skipped")
out["related_items"] = len(related.get("related") or {})
out["related_map_skipped_above_2000"] = bool(related.get("skipped")) or not related.get("related")
pairs = [[p["a"], p["b"]] for p in lifecycle.near_duplicate_pairs(mem)]
out["duplicate_sweep_misses_planted_twins"] = twins not in pairs
gen = mem / "index" / "generation.json"
before = (gen.read_bytes(), gen.stat().st_mtime_ns)
counts["parses"] = 0
code, _ = run(["jot", "a quiet local note about quorvex", "--local", "--project", str(root)])
out["local_jot_exit"] = code
out["local_jot_parses"] = counts["parses"]
out["local_jot_republishes_shared_views"] = (gen.read_bytes(), gen.stat().st_mtime_ns) != before
out["parses_exceed_twice_the_records"] = out["parses_per_reindex"] > 2 * out["records"]
out["conflicts_computed_more_than_once"] = out["conflict_computations_per_reindex"] > 1
print(json.dumps(out))
"""


def probe() -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run(
            [sys.executable, "-c", PROBE, str(TREE), tmp],
            capture_output=True,
            text=True,
            env=ENV,
        )
        if p.returncode != 0:
            return {"error": p.stderr.strip().splitlines()[-3:]}
        return json.loads(p.stdout.strip().splitlines()[-1])


results = probe()
bad = {
    "related_map_skipped_above_2000": True,
    "duplicate_sweep_misses_planted_twins": True,
    "local_jot_republishes_shared_views": True,
    "parses_exceed_twice_the_records": True,
    "conflicts_computed_more_than_once": True,
}
results["defects_observed"] = sum(1 for k, v in bad.items() if results.get(k) == v)
print(json.dumps(results, indent=1))
