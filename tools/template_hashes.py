"""Print `breadcrumbs/template_history.py`'s hash table from git history.

Every version of each template file ever committed (under the current
`breadcrumbs/templates/project-memory/` and the older `templates/project-memory/`)
is hashed with CRLF folded to LF. Run from the repository root:

    python tools/template_hashes.py

and paste the `SHIPPED` table it prints into `breadcrumbs/template_history.py`.
"""

from __future__ import annotations

import hashlib
import subprocess

FILES = (
    "README.md",
    "generated/README.md",
    "index/README.md",
    "private/README.md",
    "evidence/refs.yml",
)
BASES = ("breadcrumbs/templates/project-memory/", "templates/project-memory/")


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, check=False)


def hashes(name: str) -> list[str]:
    out: set[str] = set()
    for base in BASES:
        log = _git("log", "--all", "--format=%H", "--", base + name).stdout.decode().split()
        for commit in log:
            for rev in (commit, commit + "^"):
                shown = _git("show", f"{rev}:{base}{name}")
                if shown.returncode == 0:
                    out.add(hashlib.sha256(shown.stdout.replace(b"\r\n", b"\n")).hexdigest())
    return sorted(out)


def main() -> None:
    print("SHIPPED: dict[str, frozenset[str]] = {")
    for name in FILES:
        print(f'    "{name}": frozenset(')
        print("        {")
        for h in hashes(name):
            print(f'            "{h}",')
        print("        }")
        print("    ),")
    print("}")


if __name__ == "__main__":
    main()
