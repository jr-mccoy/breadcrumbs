"""WP20 behavior check: one tree, in a subprocess.

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
import contextlib, io, json, re, subprocess, sys, tempfile
from datetime import date
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import crumb
from breadcrumbs import cli
tree = Path(sys.argv[1])
def run(argv):
    with contextlib.redirect_stdout(io.StringIO()) as o, contextlib.redirect_stderr(io.StringIO()):
        try:
            return crumb.main(argv), o.getvalue()
        except SystemExit as e:
            return e.code, o.getvalue()
out = {}
with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp); subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    run(["init", "--project", str(root), "--session-tracking", "full"])
    mem = root / ".project-memory"
    run(["remember", "decision", "--title", "Behavior fixture", "--set", "Decision", "x",
         "--evidence", "file", "a.py", "--project", str(root)])
    rec = next((mem / "decisions").glob("*.md"))
    rec.write_text(rec.read_text().replace("confidence: medium", "confidence: certainly"))
    (mem / "manifest.yml").write_text((mem / "manifest.yml").read_text() + "requires: future-thing\n")
    cli.install_claude_hooks(root, ["guard"])
    s = root / ".claude" / "settings.json"; d = json.loads(s.read_text())
    d["hooks"]["PreToolUse"][0]["matcher"] = "Bash|Edit|Write|MultiEdit|Task|Agent"; s.write_text(json.dumps(d))
    report = cli.doctor_report(root)
    failing = " ".join(c["detail"] for c in report["checks"] if not c["ok"])
    out["doctor_silent_on_invalid_record"] = "crumb validate" not in failing
    out["doctor_silent_on_unwritable_store"] = "future-thing" not in failing
    out["doctor_silent_on_outdated_hook_matcher"] = "--with-hooks" not in failing
docs = tree / "docs"
out["no_executed_quickstart"] = not ((docs / "quickstart.md").exists() and (tree / "tools" / "quickstart_check.py").exists())
out["no_operator_guide_or_contract"] = not ((docs / "operator-guide.md").exists() and (docs / "continuity-contract.md").exists())
changelog = (tree / "CHANGELOG.md").read_text()
latest = max(date.fromisoformat(d) for d in re.findall(r"^## \[\d+\.\d+\.\d+\] — (\d{4}-\d{2}-\d{2})", changelog, re.M))
stamp = re.search(r"_Last updated: (\d{4}-\d{2}-\d{2})", (tree / ".project-memory" / "handoff.md").read_text())
out["handoff_predates_latest_release"] = date.fromisoformat(stamp.group(1)) < latest
out["no_contributor_path"] = "failing scenario" not in (tree / "CONTRIBUTING.md").read_text()
print(json.dumps(out))
"""

p = subprocess.run(
    [sys.executable, "-c", PROBE, str(TREE)], capture_output=True, text=True, env=ENV
)
if p.returncode != 0:
    results = {"error": p.stderr.strip().splitlines()[-3:]}
else:
    results = json.loads(p.stdout.strip().splitlines()[-1])
results["defects_observed"] = sum(1 for k, v in results.items() if v is True)
print(json.dumps(results, indent=1))
