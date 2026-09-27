"""WP14 behavior check: MCP core and CLI of a tree, in a subprocess per tree.

Usage: python behavior.py <source-tree>
The team policy is written into the manifest directly, so the check runs the
same on a tree that has no `crumb policy` command (it ignores the keys). The
`info_` line is not a defect: a build without review profiles refusing a store
that requires them is the WP21 gate working.
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
import contextlib, io, json, re, subprocess, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import crumb
from breadcrumbs import cli, mcp_core

root = Path(sys.argv[2]); mode = sys.argv[3]
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
(root / "CLAUDE.md").write_text("# rules\n")
run(["init", "--project", str(root), "--session-tracking", "full"])
code, out = run(["remember", "decision", "--project", str(root), "--title", "Quasar routing uses the slow queue",
                 "--set", "Decision", "x", "--evidence", "file", "src/q.py", "--json"])
rid = json.loads(out)["id"]
# Policy keys only: `requires: review-profiles` would make a pre-WP14 build
# refuse every write (the WP21 gate), which hides what it does with the policy.
extra = {"team": "review_profile: team\nmcp_mode: propose\n",
         "readonly": "review_profile: team\nmcp_mode: read-only\n",
         "requires": "review_profile: team\nrequires: review-profiles\n"}[mode]
m = mem / "manifest.yml"; m.write_text(m.read_text() + extra)
payload = {"title": "An MCP decision", "sections": {"Decision": "y"},
           "evidence": [{"type": "file", "ref": "src/q.py"}], "allow_duplicate": True}
out = {}
if mode == "team":
    r = mcp_core.tool_record("decision", {**payload, "agent": "human"}, root=root)
    out["mcp_agent_human_accepted"] = bool(r.get("ok"))
    r = mcp_core.tool_record("decision", {**payload, "title": "Forged review", "review_status": "reviewed",
                                          "reviewed_by": "alice"}, root=root)
    out["mcp_forged_review_fields_not_refused"] = bool(r.get("ok"))
    r = mcp_core.tool_record("decision", {**payload, "title": "Plain agent proposal"}, root=root)
    out["mcp_guidance_written_as_proposal"] = bool(r.get("ok")) and cli.find_record_by_id(mem, r["id"]).meta.get("review_status") == "needs-review"
    r = mcp_core.tool_mark_status(rid, "quarantined", "x", root=root)
    out["mcp_quarantine_allowed_in_team"] = bool(r.get("ok"))
    run(["mark-status", rid, "active", "--reason", "back", "--project", str(root)])
    code, _ = run(["promote", rid, "--project", str(root)])
    out["unreviewed_promotion_allowed_in_team"] = code == 0
elif mode == "readonly":
    r = mcp_core.tool_jot("anything", root=root)
    out["mcp_write_allowed_when_read_only"] = bool(r.get("ok"))
else:
    code, _ = run(["note", "question", "Anything?", "--project", str(root)])
    out["info_writes_a_store_requiring_review_profiles"] = code == 0
print(json.dumps(out))
"""


def probe(mode: str) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        p = subprocess.run(
            [sys.executable, "-c", PROBE, str(TREE), tmp, mode],
            capture_output=True,
            text=True,
            env=ENV,
        )
        if p.returncode != 0:
            return {"error": p.stderr.strip().splitlines()[-1:]}
        return json.loads(p.stdout.strip().splitlines()[-1])


results = {**probe("team"), **probe("readonly"), **probe("requires")}
bad = {
    "mcp_agent_human_accepted": True,
    "mcp_forged_review_fields_not_refused": True,
    "mcp_guidance_written_as_proposal": False,
    "mcp_quarantine_allowed_in_team": True,
    "unreviewed_promotion_allowed_in_team": True,
    "mcp_write_allowed_when_read_only": True,
}
results["defects_observed"] = sum(1 for k, v in bad.items() if results.get(k) == v)
print(json.dumps(results, indent=1))
