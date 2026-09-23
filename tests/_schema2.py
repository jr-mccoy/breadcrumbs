"""Test helper: turn a freshly initialised store back into a schema-2 store.

Schema 3 (WM-22) moved traps and questions from `## …` blocks in
known-traps.md / open-questions.md into one file each. Readers still accept the
block format for a store that has not migrated, and the block editors
(`mark-status`, `traps --confirm`, `note` appends) still run on such a store —
so the tests that pin that behaviour run against a schema-2 store built here,
not against whatever `crumb init` writes today.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from breadcrumbs import migrate

DATA = Path(__file__).resolve().parent / "data" / "schema2"


def downgrade_to_schema2(mem: Path) -> Path:
    """Put the schema-2 singleton templates back and set `schema_version: 2`.

    Only valid on a store with no trap or question files yet — it exists to
    build the pre-migration shape, not to reverse a migration.
    """
    mem = Path(mem)
    for name in ("known-traps.md", "open-questions.md"):
        shutil.copy(DATA / name, mem / name)
    for sub in ("traps", "questions"):
        directory = mem / sub
        if directory.is_dir():
            leftover = [p for p in directory.iterdir() if p.name != ".gitkeep"]
            assert not leftover, f"{directory} already holds records: {leftover}"
            shutil.rmtree(directory)
    migrate.set_manifest_version(mem, 2)
    return mem
