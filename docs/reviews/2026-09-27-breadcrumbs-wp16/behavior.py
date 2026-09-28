"""WP16 behavior check: one tree, in a subprocess.

Usage: python behavior.py <source-tree>
Each check is phrased so that `true` is the defect.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

TREE = Path(sys.argv[1]).resolve()
MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT")
ENV = {k: v for k, v in os.environ.items() if k not in MARKERS}

PROBE = r"""
import inspect, json, subprocess, sys, tempfile, threading
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from breadcrumbs import cli
out = {}
# 1. Importing the domain module defines and imports the argument parser.
out["domain_import_loads_parser"] = "argparse" in sys.modules or "_CrumbParser" in vars(cli)
from breadcrumbs import mcp_core
# 2. `crumb remember` and `memory_record` are two implementations of one write.
writers = [f for f in (cli.cmd_remember, mcp_core.tool_record)
           if "write_record(" in inspect.getsource(inspect.unwrap(f))]
out["record_write_implementations"] = len(writers)
out["write_pipeline_duplicated"] = len(writers) > 1
# 3. Two stores' search aliases, active at once in two threads.
with tempfile.TemporaryDirectory() as tmp:
    a, b = Path(tmp) / "a", Path(tmp) / "b"
    for d in (a, b):
        d.mkdir()
    (a / "aliases.txt").write_text("billing payments\n")
    barrier = threading.Barrier(2)
    seen = {}
    def worker(name, mem):
        cli.activate_store_aliases(mem)
        barrier.wait()
        barrier.wait()
        seen[name] = cli._stem("payments")
    ta = threading.Thread(target=worker, args=("a", a))
    tb = threading.Thread(target=worker, args=("b", b))
    ta.start(); tb.start(); ta.join(); tb.join()
    out["alias_stems"] = seen
    out["aliases_shared_across_stores"] = seen["a"] == seen["b"]
# 4. A clock scoped to one operation (not a process-wide patch).
out["no_operation_scoped_clock"] = not hasattr(cli, "clock")
print(json.dumps(out))
"""

p = subprocess.run(
    [sys.executable, "-c", PROBE, str(TREE)], capture_output=True, text=True, env=ENV
)
if p.returncode != 0:
    results = {"error": p.stderr.strip().splitlines()[-3:]}
else:
    results = json.loads(p.stdout.strip().splitlines()[-1])
bad = (
    "domain_import_loads_parser",
    "write_pipeline_duplicated",
    "aliases_shared_across_stores",
    "no_operation_scoped_clock",
)
results["defects_observed"] = sum(1 for k in bad if results.get(k) is True)
print(json.dumps(results, indent=1))
