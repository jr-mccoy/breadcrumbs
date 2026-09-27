"""Native-platform smoke test for an installed `crumb` (audit WP17, F22, F25).

Runs the installed console script (not `python crumb.py`) against a fresh
project whose path has spaces and non-ASCII characters, and checks what the
Linux-only suite could not:

- install: `init` finds the bundled templates;
- quoting and Unicode: a record with a non-ASCII title and a spaced evidence
  path is written as UTF-8, found by `search`, and `resume --json` parses;
- the guard: the exit code matches the verdict, and `crumb hook guard` answers
  a PowerShell payload with valid JSON;
- locks: a second process holding the store lock makes a write fail fast, and
  the write succeeds once the lock is released;
- atomic replacement: no temporary files are left behind in the store;
- replay containment: `verify --recheck` on an assertion that floods output
  and starts a child that outlives it records bounded output, and the child
  does not survive the check.

Usage: python tools/platform_smoke.py --wheel dist/crumb_kit-*.whl [--json OUT]
   or: python tools/platform_smoke.py --crumb PATH_TO_CRUMB [--python PY] [--json OUT]
`--wheel` installs the wheel into a fresh venv and tests its `crumb`.
`--python` is the interpreter of the environment `crumb` is installed in (for
the lock holder); it defaults to the one running this script.

Prints one JSON report and exits 1 if any check failed. Observations that are
facts about the platform, not failures (whether non-ASCII survives the
console encoding), are reported under `observations`.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import textwrap
import time
from pathlib import Path

VERDICT_EXIT = {"PROCEED": 0, "READ_FIRST": 10, "PAUSE": 15, "ASK_HUMAN": 20}
TITLE = "Café pricing cache — TTL is five minutes ✓"


def run(argv, cwd, stdin=None, timeout=120, env=None):
    p = subprocess.run(
        argv,
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    return p.returncode, p.stdout, p.stderr


def pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True
        ).stdout
        return str(pid) in out
    # A killed child whose parent already exited is re-parented, and until its
    # new parent reaps it, it is a zombie: dead, but still listed. A container's
    # PID 1 often never reaps, so a signal-0 probe would call it alive.
    out = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True
    ).stdout
    state = out.strip()
    return bool(state) and not state.startswith("Z")


def install_wheel(wheel: Path) -> tuple[str, str]:
    """A fresh venv with `wheel` installed: `(crumb, python)` inside it."""
    import venv

    home = Path(tempfile.mkdtemp(prefix="crumb-smoke-venv-"))
    venv.create(home, with_pip=True)
    bindir = home / ("Scripts" if os.name == "nt" else "bin")
    python = bindir / ("python.exe" if os.name == "nt" else "python")
    subprocess.run([str(python), "-m", "pip", "install", "-q", str(wheel.resolve())], check=True)
    crumb = bindir / ("crumb.exe" if os.name == "nt" else "crumb")
    return str(crumb), str(python)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--crumb", help="an installed `crumb` to test")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument(
        "--wheel", type=Path, help="install this wheel into a fresh venv and test its `crumb`"
    )
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    if args.wheel:
        args.crumb, args.python = install_wheel(args.wheel)
    if not args.crumb:
        ap.error("pass --crumb or --wheel")
    crumb = [args.crumb]
    checks: dict[str, dict] = {}
    observations: dict = {}

    def check(name, ok, **detail):
        checks[name] = {"ok": bool(ok), **detail}

    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    tmp = tempfile.mkdtemp(prefix="crumb-smoke-")
    try:
        _checks(crumb, args, tmp, env, check, observations)
    except Exception as exc:  # a crash is a failed check, never a lost report
        import traceback

        check(
            "smoke_script_completed",
            False,
            error=f"{type(exc).__name__}: {exc}",
            traceback=traceback.format_exc()[-1500:],
        )
    finally:
        import shutil

        leftover = []

        def retry_writable(fn, path, exc):
            # git's object files are read-only, and Windows will not delete a
            # read-only file; that is not a live process holding it.
            try:
                os.chmod(path, 0o700)
                fn(path)
            except OSError:
                leftover.append(path)

        shutil.rmtree(tmp, onerror=retry_writable)
        if leftover:
            # Windows cannot delete a directory a live process is using: that
            # is itself evidence that something outlived the smoke test.
            observations["cleanup_blocked"] = leftover[:5]

    result = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "crumb": args.crumb,
        "checks": checks,
        "observations": observations,
        "failed": sorted(k for k, v in checks.items() if not v["ok"]),
    }
    text = json.dumps(result, indent=1, ensure_ascii=False)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    sys.stdout.buffer.write(text.encode("utf-8") + b"\n")
    return 1 if result["failed"] else 0


def _checks(crumb, args, tmp, env, check, observations) -> None:
    root = Path(tmp) / "proj with spaces ünï"
    root.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "i"], cwd=root, check=True)
    mem = root / ".project-memory"

    code, out, err = run([*crumb, "--version"], root, env=env)
    check(
        "version",
        code == 0 and b"record schema_version" in out,
        stdout=out.decode(errors="replace").strip(),
    )

    code, out, err = run([*crumb, "init", "--session-tracking", "full"], root, env=env)
    check(
        "init_bundled_templates",
        code == 0 and (mem / "decisions").is_dir() and (mem / "manifest.yml").is_file(),
        exit=code,
        stderr=err.decode(errors="replace")[-400:],
    )

    evidence = "src/pricing cache/cache café.py"
    code, out, err = run(
        [
            *crumb,
            "remember",
            "decision",
            "--title",
            TITLE,
            "--set",
            "Decision",
            "cache pricing responses for 300 seconds",
            "--evidence",
            "file",
            evidence,
            "--tags",
            "pricing,cache",
            "--json",
        ],
        root,
        env=env,
    )
    rid = None
    try:
        rid = json.loads(out)["id"]
    except (ValueError, KeyError):
        pass
    files = list((mem / "decisions").glob("*.md"))
    on_disk = files[0].read_text(encoding="utf-8") if files else ""
    check(
        "unicode_and_quoting_on_disk",
        code == 0 and TITLE in on_disk and evidence in on_disk,
        exit=code,
        id=rid,
        stderr=err.decode(errors="replace")[-400:],
    )
    # Whether the title survives the console encoding. `--json` escapes
    # non-ASCII, so this reads `show`'s human output.
    code_h, out_h, _ = run([*crumb, "show", str(rid)], root, env=env)
    observations["stdout_encoding"] = {
        "human_output_roundtrips_non_ascii": TITLE.encode("utf-8") in out_h,
        "python_io_encoding": os.environ.get("PYTHONIOENCODING"),
    }

    code, out, err = run([*crumb, "search", "pricing cache", "--json"], root, env=env)
    try:
        found = [m["id"] for m in json.loads(out)["matches"]]
    except (ValueError, KeyError):
        found = []
    check("search_finds_it", code == 0 and rid in found, exit=code, found=found)

    code, out, err = run([*crumb, "resume", "--json"], root, env=env)
    try:
        packet = json.loads(out)
        ok = rid in [d["id"] for d in packet["active_decisions"]]
    except (ValueError, KeyError):
        ok = False
    check("resume_json_parses", code == 0 and ok, exit=code)

    code, out, err = run([*crumb, "guard", "change the pricing cache ttl", "--json"], root, env=env)
    try:
        verdict = json.loads(out)["verdict"]
    except (ValueError, KeyError):
        verdict = None
    check(
        "guard_exit_matches_verdict",
        verdict in VERDICT_EXIT and code == VERDICT_EXIT[verdict],
        exit=code,
        verdict=verdict,
    )

    payload = json.dumps(
        {
            "cwd": str(root),
            "session_id": "smoke",
            "tool_name": "PowerShell",
            "tool_input": {"command": "Remove-Item ./cache -Recurse -Force"},
        }
    )
    code, out, err = run([*crumb, "hook", "guard"], root, stdin=payload.encode("utf-8"), env=env)
    try:
        json.loads(out)
        ok = True
    except ValueError:
        ok = False
    check(
        "hook_guard_powershell_json",
        code == 0 and ok,
        exit=code,
        stdout=out.decode(errors="replace")[:300],
    )

    # Locks: another process holds the store lock; a write must fail fast.
    holder = subprocess.Popen(
        [
            args.python,
            "-c",
            textwrap.dedent(f"""
            import sys, time
            from pathlib import Path
            from breadcrumbs import lock
            with lock.store_lock(Path({str(mem)!r}), timeout=5):
                print("held", flush=True)
                time.sleep(8)
        """),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    line = holder.stdout.readline().strip()
    started = time.monotonic()
    code, out, err = run(
        [*crumb, "note", "question", "Is the lock honored?", "--json"], root, env=env
    )
    waited = round(time.monotonic() - started, 2)
    holder.wait(timeout=30)
    code2, out2, err2 = run(
        [*crumb, "note", "question", "Is the lock released?", "--json"], root, env=env
    )
    check(
        "lock_contention_fails_fast_then_releases",
        line == "held" and code != 0 and waited < 15 and code2 == 0,
        holder=line,
        contended_exit=code,
        waited_s=waited,
        released_exit=code2,
        contended_stderr=err.decode(errors="replace")[-300:],
    )

    # Atomic replacement leaves no temporary files behind.
    run([*crumb, "reindex"], root, env=env)
    leftovers = [
        str(p.relative_to(mem))
        for p in mem.rglob("*")
        if ".tmp" in p.name or p.name.startswith(".tmp")
    ]
    check("no_temp_files_left", not leftovers, leftovers=leftovers)

    # Replay containment: an assertion that floods output and leaves a child.
    pidfile = Path(tmp) / "child.pid"
    script = Path(tmp) / "flood.py"
    script.write_text(
        textwrap.dedent(f"""
        import subprocess, sys
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open({str(pidfile)!r}, "w").write(str(child.pid))
        for i in range(200000):
            print("line", i, "x" * 40)
        sys.exit(0)
    """),
        encoding="utf-8",
    )
    assertion = f'"{args.python}" "{script}"'
    code, out, err = run(
        [
            *crumb,
            "verify",
            "flood check",
            "--status",
            "open",
            "--assert",
            assertion,
            "--note",
            "smoke",
            "--json",
        ],
        root,
        env=env,
    )
    try:
        vid = json.loads(out)["id"]
    except (ValueError, KeyError):
        vid = None
    code, out, err = run(
        [*crumb, "verify", "--recheck", str(vid), "--yes", "--json"], root, env=env, timeout=600
    )
    try:
        report = json.loads(out)
    except ValueError:
        report = {}
    text = json.dumps(report)
    child = int(pidfile.read_text()) if pidfile.exists() else None
    time.sleep(1)
    alive = pid_alive(child) if child else None
    if alive:  # record it, then end it so it cannot hold the directory
        kill = (
            ["taskkill", "/F", "/T", "/PID", str(child)]
            if os.name == "nt"
            else ["kill", "-9", str(child)]
        )
        subprocess.run(kill, capture_output=True)
    runs = [r for item in report.get("items") or [] for r in item.get("runs") or []]
    containment = runs[0].get("containment") if runs else None
    check(
        "replay_bounded_and_contained",
        vid is not None
        and child is not None
        and alive is False
        and len(text) < 64_000
        and '"truncated": true' in text,
        recheck_exit=code,
        child_pid=child,
        child_alive=alive,
        report_chars=len(text),
        containment=containment,
        stderr=err.decode(errors="replace")[-300:],
    )


if __name__ == "__main__":
    raise SystemExit(main())
