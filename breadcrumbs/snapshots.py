"""A projection's stamp describes the inputs it was actually built from (audit F07).

Every generated projection carries `inputs_hash`, the digest `validate` and
`audit` compare against the store to decide whether it is current. It used to
be computed *after* the records were read. A record written in between was
missing from the projection, yet included in the stamp, so the stamp certified
content the projection never saw.

`stable_build()` removes that gap without holding every record in memory:

1. Hash the inputs.
2. Build, stamping with that hash.
3. Hash again.

If nothing changed, the stamp is exactly the snapshot the build read. If
something did, the build is retried. After `ATTEMPTS` unstable tries, the result
is stamped `UNSTABLE`, which never equals a real digest, so `validate` reports
it stale rather than current.

Cooperating writers cannot interleave with a publication: it runs under the
store lock (WP05). This guards against everything else — a hand edit, a
`git checkout`, an older crumb-kit — and against unlocked readers such as
`resume`.

A change that is undone during the build, leaving identical bytes, is invisible
here; the built output then equals what those bytes produce.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, TypeVar

T = TypeVar("T")

# Never a hex digest, so a projection stamped with it can never read as current.
UNSTABLE = "unstable"
ATTEMPTS = 3

UNSTABLE_WARNING = (
    "⚠ the store changed while this was being built "
    f"({ATTEMPTS} attempts); it is not certified current — run `crumb reindex`."
)


def input_digest(memory_dir: Path, root: Path) -> str:
    from breadcrumbs import cli

    return cli._inputs_hash(Path(memory_dir), Path(root))


def stable_build(memory_dir: Path, root: Path, build: Callable[[str], T]) -> tuple[T, str | None]:
    """`(result, digest)`, where `digest` is None when no attempt was stable.

    `build(digest)` must stamp its output with the digest it is given. On an
    unstable outcome, the caller restamps the last result with `UNSTABLE`.
    """
    result = None
    for _ in range(ATTEMPTS):
        before = input_digest(memory_dir, root)
        result = build(before)
        if input_digest(memory_dir, root) == before:
            return result, before
    return result, None
