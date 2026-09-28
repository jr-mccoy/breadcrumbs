"""Execute docs/quickstart.md against an installed `crumb` (audit WP20).

Every `$ ` line in the quickstart's ```console blocks runs, in order, in a
fresh git repository, and its exit code must match the line's `# exit N`
comment (default 0). `<!-- quickstart-check: set-field GLOB FIELD VALUE -->`
comments make the manual edit the page describes. An id written
`dec_YYYYMMDD_<slug>` is resolved from the ids the CLI printed earlier.
Install and `cd` lines are the reader's setup and are skipped here.

    python tools/quickstart_check.py --crumb PATH      # an installed crumb
    python tools/quickstart_check.py --wheel dist/crumb_kit-*.whl
    python tools/quickstart_check.py                    # this checkout (python crumb.py)

Exit 0 when the page works as written.
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs" / "quickstart.md"
SKIP = ("pipx", "pip", "cd")
ID_RE = re.compile(r"\b((?:dec|att|ver)_\d{8}_[a-z0-9-]+)")
PLACEHOLDER_RE = re.compile(r"\b(dec|att|ver)_YYYYMMDD_([a-z0-9-]+)")


def steps(page: str) -> list[tuple[str, str]]:
    """`[(kind, text)]`: ("run", command line) or ("set-field", args)."""
    out, in_console = [], False
    for line in page.splitlines():
        if line.startswith("```"):
            in_console = line.strip() == "```console" if not in_console else False
            continue
        directive = re.match(r"<!-- quickstart-check: set-field (.+?) -->", line.strip())
        if directive:
            out.append(("set-field", directive.group(1)))
        elif in_console and line.startswith("$ "):
            out.append(("run", line[2:]))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--crumb", help="an installed crumb executable")
    ap.add_argument("--wheel", type=Path, help="install this wheel into a fresh venv first")
    args = ap.parse_args()
    if args.wheel:
        sys.path.insert(0, str(ROOT / "tools"))
        from platform_smoke import install_wheel

        crumb = [install_wheel(args.wheel)[0]]
    elif args.crumb:
        crumb = [args.crumb]
    else:
        crumb = [sys.executable, str(ROOT / "crumb.py")]
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    ids: dict[str, str] = {}
    failures = 0
    with tempfile.TemporaryDirectory() as tmp:
        project = Path(tmp) / "your-project"
        project.mkdir()
        for a in (
            ["init", "-q"],
            ["config", "user.email", "q@example.invalid"],
            ["config", "user.name", "q"],
        ):
            subprocess.run(["git", *a], cwd=project, check=True, capture_output=True, env=env)
        for kind, text in steps(PAGE.read_text(encoding="utf-8")):
            if kind == "set-field":
                pattern, field, value = text.split()
                matches = list((project / ".project-memory").glob(pattern))
                if len(matches) != 1:
                    print(f"FAIL set-field {pattern}: {len(matches)} match(es)")
                    failures += 1
                    continue
                body = matches[0].read_text(encoding="utf-8")
                matches[0].write_text(
                    re.sub(rf"(?m)^{re.escape(field)}: .*$", f"{field}: {value}", body, count=1),
                    encoding="utf-8",
                )
                print(f"ok   set-field {matches[0].name} {field}={value}")
                continue
            expect = 0
            m = re.search(r"#\s*exit\s+(\d+)\s*$", text)
            if m:
                expect = int(m.group(1))
            argv = shlex.split(text, comments=True)
            if not argv or argv[0] in SKIP:
                continue

            def resolve(match: re.Match) -> str:
                return ids.get(match.group(2), match.group(0))

            argv = [PLACEHOLDER_RE.sub(resolve, a) for a in argv]
            if argv[0] == "crumb":
                argv = crumb + argv[1:]
            p = subprocess.run(argv, cwd=project, capture_output=True, text=True, env=env)
            for rid in ID_RE.findall(p.stdout):
                ids[rid.split("_", 2)[2]] = rid
            ok = p.returncode == expect
            failures += not ok
            shown = text if len(text) < 100 else text[:97] + "..."
            print(f"{'ok  ' if ok else 'FAIL'} [exit {p.returncode}, want {expect}] $ {shown}")
            if not ok:
                print("     stdout:", p.stdout.strip()[-600:])
                print("     stderr:", p.stderr.strip()[-600:])
    print(f"\nquickstart: {'works as written' if not failures else f'{failures} step(s) failed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
