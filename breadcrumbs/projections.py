"""The generation manifest: which projection files belong together (audit F07, F11).

A publication writes four `generated/` files and the search index one by one.
Each file is atomic; the set is not. A reader could see a new packet beside an
old prefilter, or a prefilter left from a publication that failed halfway.

`index/generation.json` is written **last**, after every output of one
publication is in place. It records:

- the snapshot digest (or `unstable`);
- each output's sha256;
- a stat fingerprint of the canonical files at that moment.

A consumer trusts a projection only when all three hold:

- the manifest is there;
- the file's digest matches its entry;
- nothing canonical has moved since (the fingerprint still matches).

The manifest lives under `index/`, which is machine-local and gitignored. It
describes this checkout's publication, and a committed copy would churn and
could not be right on another machine. The committed projections still carry
their `inputs_hash` stamps for `validate`.

The fingerprint (paths, sizes, mtimes) is a cheap "did anything move" check for
the hook path, not proof of equal content. A same-size edit with a restored
mtime can slip past it. That is why nothing here is the *strict* freshness
check: the search index and `validate` use the content hash.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

MANIFEST_RELPATH = ("index", "generation.json")
MANIFEST_FORMAT = 1


def manifest_path(memory_dir: Path) -> Path:
    return Path(memory_dir).joinpath(*MANIFEST_RELPATH)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_manifest(
    memory_dir: Path, digest: str, *, stable: bool, files: dict[str, bytes], fingerprint: str
) -> None:
    """Record one completed publication. Call after every output is in place."""
    from breadcrumbs import cli

    doc = {
        "format": MANIFEST_FORMAT,
        "inputs_hash": digest,
        "stable": stable,
        "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": {name: _sha(data) for name, data in sorted(files.items())},
        "stat_fingerprint": fingerprint,
    }
    path = manifest_path(memory_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    cli.write_text_atomic(path, json.dumps(doc, indent=1, sort_keys=True) + "\n")


def load_manifest(memory_dir: Path) -> dict | None:
    try:
        doc = json.loads(manifest_path(memory_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("format") == MANIFEST_FORMAT else None


def verified(memory_dir: Path, root: Path, name: str) -> bytes | None:
    """`generated/<name>`'s bytes, only if the current generation vouches for them.

    None means "do not rely on this file": no manifest, an unstable publication,
    a file that is missing or not the one published, or canonical files that
    moved since. The caller then falls back to the canonical records.
    """
    from breadcrumbs import searchindex

    doc = load_manifest(memory_dir)
    if doc is None or not doc.get("stable"):
        return None
    expected = (doc.get("files") or {}).get(name)
    try:
        data = (Path(memory_dir) / "generated" / name).read_bytes()
    except OSError:
        return None
    if expected != _sha(data):
        return None
    if doc.get("stat_fingerprint") != searchindex._stat_fingerprint(memory_dir, root):
        return None
    return data
