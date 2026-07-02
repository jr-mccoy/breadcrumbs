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
__version__ = "0.1.7"

from breadcrumbs.cli import SCHEMA_VERSION, get_version, main

__all__ = ["main", "get_version", "SCHEMA_VERSION", "__version__"]
