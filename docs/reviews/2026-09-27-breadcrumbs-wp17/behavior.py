"""WP17 behavior check: one tree, in a subprocess.

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
import json, re, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from breadcrumbs import cli, mcp_core
out = {}
ps, _ = cli._hook_action_from_tool("PowerShell", {"command": "Remove-Item ./cache -Recurse -Force"})
out["powershell_action"] = ps
out["powershell_has_no_action"] = not ps
nb, nb_files = cli._hook_action_from_tool("NotebookEdit", {"notebook_path": "nb/a.ipynb", "new_source": "x = 1"})
out["notebook_action"] = nb
out["notebook_edit_has_no_action"] = not nb
matcher = cli._HOOK_SPECS["guard"][1]
out["guard_matcher"] = matcher
pattern = re.compile(f"^(?:{matcher})$")
out["installed_matcher_misses_powershell_or_notebookedit"] = not (pattern.match("PowerShell") and pattern.match("NotebookEdit"))
out["no_versioned_mcp_contract"] = not hasattr(mcp_core, "contract")
src = (Path(sys.argv[1]) / "breadcrumbs" / "mcp_server.py").read_text(encoding="utf-8")
out["mcp_tools_have_no_annotations"] = "ToolAnnotations" not in src
ci = (Path(sys.argv[1]) / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
out["no_native_windows_or_macos_job"] = not ("windows-latest" in ci and "macos-latest" in ci)
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
    "powershell_has_no_action",
    "notebook_edit_has_no_action",
    "installed_matcher_misses_powershell_or_notebookedit",
    "no_versioned_mcp_contract",
    "mcp_tools_have_no_annotations",
    "no_native_windows_or_macos_job",
)
results["defects_observed"] = sum(1 for k in bad if results.get(k) is True)
print(json.dumps(results, indent=1))
