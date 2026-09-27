"""The two-session handoff demo (audit WP19): one mistake a later session is
warned off, with the trail that warned it.

    python evals/task_replays/demo.py

Runs in a temporary git repository with this checkout's `crumb`, and prints
each step: the command, then what came back. Nothing is simulated: every
output is the CLI's or a Claude Code hook's own, fed the JSON Claude Code
sends. No model runs. The demo shows what the next session is *handed*, not
what an agent then does with it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CRUMB = [sys.executable, str(ROOT / "crumb.py")]
ENV = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
ENV.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})


def show(title: str, argv: list[str], cwd: Path, stdin: str | None = None) -> str:
    shown = " ".join(a if " " not in a else repr(a) for a in argv)
    print(f"\n### {title}\n\n$ {shown}" + (f"   # stdin: {stdin}" if stdin else ""))
    p = subprocess.run(argv, cwd=cwd, input=stdin, capture_output=True, text=True, env=ENV)
    out = p.stdout.strip()
    print(textwrap.indent(out or "(no output)", "  "))
    print(f"  [exit {p.returncode}]")
    return out


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "shop"
        (root / "src" / "pricing").mkdir(parents=True)
        (root / "src" / "pricing" / "cache.py").write_text("TTL = 300\n", encoding="utf-8")
        for args in (
            ["init", "-q"],
            ["symbolic-ref", "HEAD", "refs/heads/main"],
            ["config", "user.email", "demo@example.invalid"],
            ["config", "user.name", "demo"],
            ["add", "-A"],
            ["commit", "-q", "-m", "shop"],
        ):
            subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, env=ENV)
        crumb = [*CRUMB, "--project", str(root)]
        subprocess.run([*crumb, "init", "--session-tracking", "full"], capture_output=True, env=ENV)

        print("## Session 1: an attempt fails, and is recorded")
        show(
            "The agent records what it tried and why it must not be retried",
            [
                *crumb,
                "remember",
                "attempt",
                "--title",
                "Tried an in-process LRU cache for pricing",
                "--problem",
                "the pricing API is slow",
                "--tried",
                "an in-process LRU cache in front of the pricing client",
                "--result",
                "workers served stale prices for up to an hour",
                "--do-not-retry",
                "all pricing workers share one process",
                "--evidence",
                "file",
                "src/pricing/cache.py",
                "--tags",
                "pricing,cache",
            ],
            root,
        )

        print("\n## Session 2: a fresh session is asked to do the same thing")
        hook = {"cwd": str(root), "session_id": "session-2"}
        out = show(
            "SessionStart: the packet Claude Code injects",
            [*CRUMB, "hook", "session"],
            root,
            json.dumps({**hook, "source": "startup"}),
        )
        packet = json.loads(out)["hookSpecificOutput"]["additionalContext"]
        start = packet.index("## Failed Attempts To Avoid")
        print("\n  (the packet's failed-attempts section, from the context above:)")
        print(textwrap.indent(packet[start : packet.index("##", start + 3)].strip(), "  | "))
        show(
            "UserPromptSubmit: the prompt names the same idea",
            [*CRUMB, "hook", "prompt"],
            root,
            json.dumps(
                {**hook, "prompt": "add an in-process LRU cache to speed up the pricing client"}
            ),
        )
        show(
            "PreToolUse: the first edit toward it",
            [*CRUMB, "hook", "guard"],
            root,
            json.dumps(
                {
                    **hook,
                    "tool_name": "Edit",
                    "tool_input": {
                        "file_path": str(root / "src/pricing/cache.py"),
                        "old_string": "TTL = 300",
                        "new_string": "from functools import lru_cache",
                    },
                }
            ),
        )

        print("\n## The trail: what the warning points to")
        ids = json.loads(
            subprocess.run(
                [*crumb, "search", "LRU cache pricing", "--json"],
                capture_output=True,
                text=True,
                env=ENV,
            ).stdout
        )["matches"]
        show("The record, as `crumb show` prints it", [*crumb, "show", ids[0]["id"]], root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
