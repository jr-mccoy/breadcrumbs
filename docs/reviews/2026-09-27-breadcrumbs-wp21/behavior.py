"""WP21 behavior check through each tree's CLI (subprocesses; no shared imports).

Usage: python behavior.py <source-tree>
Every store is synthetic, in a temporary directory.
"""

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TREE = Path(sys.argv[1]).resolve()
CRUMB = [sys.executable, str(TREE / "crumb.py")]


def crumb(*args, cwd):
    p = subprocess.run([*CRUMB, *args], cwd=cwd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def project(base: Path) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
        subprocess.run(["git", *a], cwd=base, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "i"], cwd=base, check=True)
    crumb("init", "--session-tracking", "full", cwd=base)
    return base / ".project-memory"


def records(mem: Path) -> int:
    return len(list((mem / "decisions").glob("*.md")))


def set_manifest(mem: Path, pattern: str, repl: str) -> None:
    m = mem / "manifest.yml"
    m.write_text(re.sub(pattern, repl, m.read_text(), flags=re.M))


def schema2(mem: Path) -> None:
    """A store with trap blocks, as schema 2 wrote them, so schema 3 has work."""
    for sub in ("traps", "questions"):
        d = mem / sub
        for p in d.glob("*"):
            p.unlink()
        d.rmdir()
    (mem / "known-traps.md").write_text(
        "# Known Traps\n\n## trap_quasar-queue: The quasar queue drops on restart\n"
        "- Symptom: messages vanish\n- Why: in-memory\n- Safe: drain first\n"
    )
    (mem / "open-questions.md").write_text("# Open Questions\n\n_No open questions yet._\n")
    set_manifest(mem, r"^schema_version: .*$", "schema_version: 2")


results = {}
with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)

    mem = project(base / "newer")
    set_manifest(mem, r"^schema_version: .*$", "schema_version: 5")
    code, out, err = crumb(
        "remember",
        "decision",
        "--title",
        "Old-semantics write",
        "--set",
        "Decision",
        "x",
        "--evidence",
        "file",
        "a.py",
        cwd=mem.parent,
    )
    results["writes_into_newer_schema_store"] = records(mem) > 0
    code, out, err = crumb("resume", cwd=mem.parent)
    results["resume_warns_on_newer_store"] = "Upgrade crumb-kit" in out

    mem = project(base / "requires")
    (mem / "manifest.yml").write_text(
        (mem / "manifest.yml").read_text() + "requires: review-profiles\n"
    )
    crumb(
        "remember",
        "decision",
        "--title",
        "Ignores a required feature",
        "--set",
        "Decision",
        "x",
        "--evidence",
        "file",
        "a.py",
        cwd=mem.parent,
    )
    results["writes_into_store_requiring_unknown_feature"] = records(mem) > 0

    mem = project(base / "migrate")
    schema2(mem)
    code, out, err = crumb("migrate", "--dry-run", cwd=mem.parent)
    results["dry_run_reports_backup_and_legacy"] = "copied to" in out
    code, out, err = crumb("migrate", "--json", cwd=mem.parent)
    backup = Path(json.loads(out)["backup"])
    results["backup_has_verifiable_manifest"] = (backup / "backup-manifest.json").is_file()
    code, out, err = crumb("migrate", "--restore", cwd=mem.parent)
    results["restore_available_and_exact"] = code == 0 and "restored" in out

    egg = TREE / "crumb_kit.egg-info"
    made = not egg.exists()
    if made:
        egg.mkdir()
        (egg / "PKG-INFO").write_text("Metadata-Version: 2.1\nName: crumb-kit\nVersion: 9.9.9\n")
    try:
        code, out, err = crumb("--version", cwd=TREE)
    finally:
        if made:
            for p in egg.iterdir():
                p.unlink()
            egg.rmdir()
    init = (TREE / "breadcrumbs" / "__init__.py").read_text()
    tree_version = re.search(r'__version__ = "([^"]+)"', init).group(1)
    results["version_reports_running_code_despite_stale_metadata"] = (
        tree_version in out and "9.9.9" not in out
    )

defects = [
    results["writes_into_newer_schema_store"],
    not results["resume_warns_on_newer_store"],
    results["writes_into_store_requiring_unknown_feature"],
    not results["dry_run_reports_backup_and_legacy"],
    not results["backup_has_verifiable_manifest"],
    not results["restore_available_and_exact"],
    not results["version_reports_running_code_despite_stale_metadata"],
]
results["defects_observed"] = sum(defects)
print(json.dumps(results, indent=1))
