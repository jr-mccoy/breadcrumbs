#!/usr/bin/env python3
"""Source-checkout compatibility shim for the Breadcrumbs CLI.

The implementation lives in the installable ``breadcrumbs`` package
(``breadcrumbs/cli.py``). This thin shim keeps two source-tree workflows
working with zero changes:

  * ``python crumb.py <command>``  — the form CI and the docs use; and
  * ``import crumb``               — the form the test suite uses
                                     (``crumb.main``, ``crumb.Record``,
                                     ``crumb._VERDICTS``, …).

It re-exports every public *and* private module-level name from
``breadcrumbs.cli`` so existing tests that reach into internals keep passing.
Installed users get the ``crumb`` console script instead and never touch
this file.
"""

import breadcrumbs.cli as _cli

# Re-export everything except dunders, so this module's own __name__/__file__
# stay intact (the __main__ guard below depends on __name__ == "__main__").
globals().update({k: v for k, v in vars(_cli).items() if not k.startswith("__")})

main = _cli.main

if __name__ == "__main__":
    raise SystemExit(main())
