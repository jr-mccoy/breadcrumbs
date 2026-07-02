"""breadcrumbs — leave a trail your future self and your agents can follow back.

A portable, repo-local, human-readable ledger of durable project state for
human–agent software work. The CLI lives in :mod:`breadcrumbs.cli` and is
exposed as the ``crumb`` console script (see pyproject.toml).

``__version__`` is the in-tree fallback used for source-checkout runs; the
installed distribution's authoritative version comes from package metadata
(``breadcrumbs.cli.get_version``).
"""

# Plain literal first so setuptools can read it statically and so importing the
# package never requires importing the (heavier) CLI module.
__version__ = "0.1.5"

from breadcrumbs.cli import SCHEMA_VERSION, get_version, main

__all__ = ["main", "get_version", "SCHEMA_VERSION", "__version__"]
