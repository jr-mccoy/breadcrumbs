"""breadcrumbs — leave a trail your future self and your agents can follow back.

A portable, repo-local, human-readable ledger of durable project state for
human–agent software work. The CLI lives in :mod:`breadcrumbs.cli` and is
exposed as the ``crumb`` console script (see pyproject.toml).

``__version__`` is the **single source of truth** for the package version.
``pyproject.toml`` reads it at build time via dynamic metadata
(``[tool.setuptools.dynamic] version = {attr = "breadcrumbs.__version__"}``)
and ``breadcrumbs.cli`` uses it as the source-checkout fallback, so there is
exactly one line to bump per release and nothing to hand-sync. The installed
distribution's authoritative version still comes from package metadata
(``breadcrumbs.cli.get_version``); this literal is what that metadata is built
from.
"""

# Plain literal, first statement in the module, so setuptools can read it
# statically (dynamic version via attr = "breadcrumbs.__version__") without
# importing the package — and so importing the package never requires importing
# the (heavier) CLI module just to learn the version.
#
# >>> To cut a release: bump THIS line (and add a CHANGELOG entry). That's it.
#     The release workflow tags the commit and publishes; do not tag by hand.
__version__ = "0.2.1"

__all__ = ["main", "get_version", "SCHEMA_VERSION", "__version__"]


# The re-exports are resolved lazily (PEP 562), so the claim above — that
# importing this package does not require importing the CLI module — holds for a
# real `import breadcrumbs`, not only for setuptools' static read. It used to be
# an unconditional `from breadcrumbs.cli import …` on the next line, which pulled
# in the whole CLI (and `re`, `subprocess`, `tempfile`, …) just to read
# `__version__`. `from breadcrumbs import main` still works: Python falls back to
# this hook when the attribute is not already in the module namespace.
def __getattr__(name: str):
    if name in ("main", "get_version", "SCHEMA_VERSION"):
        from breadcrumbs import cli

        return getattr(cli, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
