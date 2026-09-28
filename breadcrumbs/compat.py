"""breadcrumbs — can this build safely read and write this store? (audit WP21)

A store says what it needs in `manifest.yml`:

- **`schema_version`**, the on-disk format (`cli.SCHEMA_VERSION`). A store at an
  older version is read as it is and upgraded by `crumb migrate`. A store at a
  newer version was written by a newer crumb-kit, whose meaning this build
  cannot know.
- **`requires`** (optional), features a reader must implement to read the store
  correctly: `requires: review-profiles, signed-reviews`. It is how a later
  change that old readers must not ignore, but that needs no format change,
  says so. A feature this build does not know makes the store "newer" in the
  same sense.

**The rule (approved by the operator for WP21): refuse writes, warn reads.**

- Nothing is written to a newer store. The check runs when the store's write
  lock is taken (`lock.store_lock`), which every committed write already does,
  and fails as `lock.IncompatibleStore`, a `StoreLocked`. So every writer
  refuses the way it already refuses a busy store: the CLI exits 1 with the
  reason, MCP tools return `{ok: false, error}`, the hooks skip their capture,
  and `resume` prints its packet without publishing it.
- Reads keep working, with the warning from `warning()` shown where they report:
  the resume packet, `guard` (and the guard hook when it speaks), and stderr
  for the CLI's read commands.

**The limit.** crumb-kit 0.3.1 and earlier do not run this check. They read and
write a newer store as though it were theirs; only their `validate` objects.
`docs/compatibility.md` says how a semantic change is designed so that those
readers fail safe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Features this build implements, by the name a store lists under `requires`.
# A change that defines one adds its name here in the same release that starts
# writing it. `review-profiles`: a team-profile store (`admission.py`, WP14).
KNOWN_FEATURES: frozenset[str] = frozenset({"review-profiles"})  # audit WP14

REQUIRES_KEY = "requires"

CURRENT = "current"
OLDER = "older"
NEWER = "newer"
UNKNOWN_FEATURES = "unknown-features"
UNREADABLE = "unreadable"
ABSENT = "absent"


@dataclass(frozen=True)
class Compatibility:
    state: str
    store_version: int | None
    build_version: int
    unknown_features: tuple[str, ...] = field(default_factory=tuple)

    @property
    def writable(self) -> bool:
        """May this build write the store? Only if it understands all of it."""
        return self.state in (CURRENT, OLDER, ABSENT)

    @property
    def message(self) -> str | None:
        """Why the store is not fully understood, or None when it is."""
        from breadcrumbs import cli

        tool = f"crumb-kit {cli.get_version()}"
        if self.state == NEWER:
            return (
                f"this store is schema_version {self.store_version}; {tool} understands "
                f"{self.build_version}. Upgrade crumb-kit."
            )
        if self.state == UNKNOWN_FEATURES:
            names = ", ".join(self.unknown_features)
            return (
                f"this store requires {names}, which {tool} does not implement. Upgrade crumb-kit."
            )
        if self.state == UNREADABLE:
            return (
                f"this store's manifest.yml has an unreadable schema_version; {tool} "
                "cannot tell what wrote it. Fix the manifest (or run `crumb validate`)."
            )
        return None


def parse_features(value) -> tuple[str, ...]:
    """`requires:` as written (`a, b`, `[a, b]` or `a b`) to a sorted tuple."""
    if value is None:
        return ()
    text = str(value).strip().strip("[]")
    return tuple(sorted({v for v in re.split(r"[\s,]+", text) if v}))


def check(memory_dir: Path) -> Compatibility:
    """Classify the store against this build. Never raises."""
    from breadcrumbs import cli

    build = cli.SCHEMA_VERSION
    try:
        manifest = cli.load_manifest(Path(memory_dir))
    except Exception:
        manifest = None
    if manifest is None:
        return Compatibility(ABSENT, None, build)
    raw = manifest.get("schema_version")
    if raw is None or str(raw).strip() == "":
        version = 1  # a manifest from before the field existed (see migrate)
    else:
        try:
            version = int(str(raw).strip())
        except ValueError:
            return Compatibility(UNREADABLE, None, build)
    if version > build:
        return Compatibility(NEWER, version, build)
    unknown = tuple(
        f for f in parse_features(manifest.get(REQUIRES_KEY)) if f not in KNOWN_FEATURES
    )
    if unknown:
        return Compatibility(UNKNOWN_FEATURES, version, build, unknown)
    return Compatibility(OLDER if version < build else CURRENT, version, build)


def warning(memory_dir: Path) -> str | None:
    """The line a reader shows when it reads a store it does not fully understand."""
    result = check(memory_dir)
    if result.writable:
        return None
    return f"breadcrumbs: {result.message} Reads may be misinterpreted; writes are refused."
