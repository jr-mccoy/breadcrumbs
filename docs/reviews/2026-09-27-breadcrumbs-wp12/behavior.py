"""WP12 behavior check: APIs present before and after the change.

Usage: python behavior.py <source-tree>
"""

import contextlib
import importlib
import io
import json
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path
from unittest import mock

SRC = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(SRC))
crumb = importlib.import_module("crumb")
hooklog = importlib.import_module("breadcrumbs.hooklog")
hooks_common = importlib.import_module("breadcrumbs.hooks_common")
hooks_prompt = importlib.import_module("breadcrumbs.hooks_prompt")
usage = importlib.import_module("breadcrumbs.usage")


def run(argv):
    with contextlib.redirect_stdout(io.StringIO()) as o, contextlib.redirect_stderr(io.StringIO()):
        code = crumb.main(argv)
    return code, o.getvalue()


def hook(event, payload):
    saved = sys.stdin
    sys.stdin = io.StringIO(json.dumps(payload))
    try:
        with contextlib.redirect_stdout(io.StringIO()) as o:
            crumb.main(["hook", event])
    finally:
        sys.stdin = saved
    t = o.getvalue().strip()
    return json.loads(t) if t else {}


def store(tmp):
    root = Path(tmp)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)
    (root / "f.txt").write_text("a\n")
    subprocess.run(["git", "add", "f.txt"], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=root, check=True, capture_output=True)
    run(["init", "--project", str(root), "--session-tracking", "full"])
    return root, root / crumb.MEMORY_DIRNAME


def decision(root, title):
    code, out = run(
        [
            "remember",
            "decision",
            "--project",
            str(root),
            "--title",
            title,
            "--set",
            "Decision",
            "x",
            "--evidence",
            "file",
            "src/quasar.py",
            "--tags",
            "routing",
            "--allow-duplicate",
            "--json",
        ]
    )
    return json.loads(out)["id"]


A = "refactor the amber quasar routing policy in src/quasar.py"
B = "design the calendar week view with drag to reschedule"
results = {}

# F15: matched A, unmatched B, then an acknowledgement.
with tempfile.TemporaryDirectory() as tmp:
    root, mem = store(tmp)
    decision(root, "Amber quasar routing uses the slow queue")
    for p in (A, B, "ok"):
        hook("prompt", {"cwd": str(root), "session_id": "s1", "prompt": p})
    st = hooks_common.prompt_state(mem, "s1")
    results["f15_latest_task_after_A_B_ok"] = st.get("last_prompt")
    results["f15_pass"] = st.get("last_prompt") == B and not st.get("matched")

# F16: identical guard call twice in one session.
with tempfile.TemporaryDirectory() as tmp:
    root, mem = store(tmp)
    rid = decision(root, "Amber quasar routing uses the slow queue")
    pl = {
        "cwd": str(root),
        "session_id": "c",
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "src/quasar.py",
            "new_string": "refactor amber quasar routing policy",
        },
    }
    outs = [bool(hook("guard", pl)), bool(hook("guard", pl))]
    n = (usage.load_usage(mem)["records"].get(rid) or {}).get("surfaced", 0)
    results["f16_guard_spoke"] = outs
    results["f16_guard_surfaced"] = n
    results["f16_guard_pass"] = outs == [True, False] and n == 1

# F16: prompt budget trimming, 5 selected, budget fits 2.
with tempfile.TemporaryDirectory() as tmp:
    root, mem = store(tmp)
    ids = [
        decision(root, f"Amber quasar routing rule {w} for the slow queue")
        for w in ("alpha", "bravo", "charlie", "delta", "echo")
    ]
    budget = None
    for b in range(50, 800):
        with mock.patch.object(hooks_prompt, "PROMPT_HOOK_TOKEN_BUDGET", b):
            text = hooks_prompt.render(hooks_prompt.retrieve(mem, root, A))
        if sum(i in text for i in ids) == 2:
            budget = b
            break
    with mock.patch.object(hooks_prompt, "PROMPT_HOOK_TOKEN_BUDGET", budget):
        out = hook("prompt", {"cwd": str(root), "session_id": "p", "prompt": A})
    text = out["hookSpecificOutput"]["additionalContext"]
    rec = usage.load_usage(mem)["records"]
    results["f16_trim_rendered"] = sum(i in text for i in ids)
    results["f16_trim_counted"] = sum(1 for i in ids if i in rec)
    results["f16_trim_pass"] = results["f16_trim_counted"] == results["f16_trim_rendered"]

# F16: parallel processes; usage increments, session state entries, hook-log lines.
WORKER = textwrap.dedent("""
    import sys, time
    from pathlib import Path
    sys.path.insert(0, %r)
    from breadcrumbs import hooklog, hooks_common, usage
    mem, w, go = Path(sys.argv[1]), int(sys.argv[2]), Path(sys.argv[3])
    hooklog.HOOK_LOG_MAX_LINES = 100; hooklog.HOOK_LOG_TRIM_TO = 60; hooklog._MIN_LINE_BYTES = 1
    while not go.exists(): time.sleep(0.001)
    for i in range(30):
        usage.record_surfaced(mem, ["dec_shared"], "hook-guard", session_id="s%%d" %% w)
        hooklog.append(mem, {"event": "guard", "worker": w, "n": i})
        hooks_common.record_prompt_state(mem, "s%%d" %% w, "task %%d" %% i, [])
""") % str(SRC)
lost_usage, lost_state, lost_lines = [], [], []
for trial in range(5):
    with tempfile.TemporaryDirectory() as tmp:
        root, mem = store(tmp)
        go = Path(tmp) / "go"
        procs = [
            subprocess.Popen([sys.executable, "-c", WORKER, str(mem), str(w), str(go)])
            for w in range(6)
        ]
        time.sleep(0.3)
        go.write_text("go")
        for p in procs:
            p.wait(timeout=120)
        got = (usage.load_usage(mem)["records"].get("dec_shared") or {}).get("surfaced", 0)
        lost_usage.append(180 - got)
        sessions = hooks_common.read_state(mem, hooks_common.SESSION_STATE_FILENAME)
        lost_state.append(sum(1 for w in range(6) if f"s{w}" not in sessions))
        entries = [e for e in hooklog.read_log(mem) if "worker" in e]
        gaps = 0
        for w in range(6):
            ns = sorted(e["n"] for e in entries if e["worker"] == w)
            if ns:
                gaps += (ns[-1] - ns[0] + 1) - len(ns)
        lost_lines.append(gaps)
results["parallel_usage_increments_lost_of_180_per_trial"] = lost_usage
results["parallel_session_entries_lost_of_6_per_trial"] = lost_state
results["parallel_hooklog_lines_lost_inside_retained_window_per_trial"] = lost_lines
results["parallel_pass"] = not any(lost_usage) and not any(lost_state) and not any(lost_lines)
print(json.dumps(results, indent=1))
