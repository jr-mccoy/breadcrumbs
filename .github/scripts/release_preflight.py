#!/usr/bin/env python3
"""Decide whether a release run may proceed, given PyPI and tag state.

Called by `.github/workflows/release.yml` before anything irreversible happens.
It lives here, as a plain stdlib module with unit tests
(`tests/test_release_process.py`), because the rule it encodes is subtle enough
that getting it wrong cost real releases:

  * A PyPI version is permanent, so a forgotten version bump must stop the run
    up front with a plain message rather than a cryptic `400 File already
    exists` at the upload.
  * But "already on PyPI" is NOT by itself a reason to stop. The publish job
    uploads to PyPI *first* and creates the tag + GitHub Release afterwards, so
    a failure in that last step leaves the version permanently published with no
    tag and no Release. Hard-failing on "already on PyPI" made that state
    unrecoverable by re-run: the only escapes were hand-tagging (forbidden) or
    burning a version, leaving the published one untagged forever (review #5 H5
    / MF-11). 0.1.2 is exactly that: on PyPI, never tagged.
  * The recovery path must not double as a way to tag today's commit with an old
    version, so it is allowed only when the version is the newest one on PyPI —
    which is always true of a publish that just failed, and never true of a
    version regression.

No network and no git here: the workflow gathers the facts, this module decides.
"""

from __future__ import annotations

import argparse
import sys

# PyPI reachability, as observed by the caller.
ON_PYPI_YES = "yes"
ON_PYPI_NO = "no"
ON_PYPI_UNKNOWN = "unknown"

ERROR = "error"
WARNING = "warning"
NOTICE = "notice"


class Decision:
    """`ok` plus the annotations to emit, in order."""

    def __init__(self, ok: bool, messages: list[tuple[str, str]]) -> None:
        self.ok = ok
        self.messages = messages

    @property
    def blocked(self) -> bool:
        return not self.ok

    def reason(self) -> str:
        """What stopped the run, or the primary reason it may continue.

        Messages are ordered primary-first, so the first error (if any) and
        otherwise the first message is the headline; anything after it is detail.
        """
        for level, text in self.messages:
            if level == ERROR:
                return text
        return self.messages[0][1] if self.messages else ""


def decide(
    *,
    version: str,
    on_pypi: str,
    latest_on_pypi: str | None,
    tag_exists: bool,
    mode: str,
) -> Decision:
    """Whether the run may continue, and what to tell the operator."""
    published = on_pypi == ON_PYPI_YES

    if published and tag_exists:
        return Decision(
            False,
            [
                (
                    ERROR,
                    f"crumb-kit {version} is already released: it is on PyPI and tag "
                    f"v{version} exists. A PyPI version is permanent — bump __version__ in "
                    "breadcrumbs/__init__.py, add a CHANGELOG entry, merge to main, then re-run.",
                )
            ],
        )

    if published and not tag_exists:
        # The partial-publish state: PyPI accepted the upload, the tag step did not
        # run or failed. Completing it is the whole point (MF-11) — but only for the
        # version that was just published, never as a way to re-tag an old one.
        if not latest_on_pypi:
            return Decision(
                False,
                [
                    (
                        ERROR,
                        f"crumb-kit {version} is on PyPI but has no tag, and the newest "
                        "published version could not be determined (PyPI unreachable?). "
                        "Refusing to guess. Re-run when PyPI is reachable.",
                    )
                ],
            )
        if version != latest_on_pypi:
            return Decision(
                False,
                [
                    (
                        ERROR,
                        f"version regression: {version} is on PyPI but the newest published "
                        f"version is {latest_on_pypi}. This is not a partial-publish recovery, "
                        f"and tagging the current commit as v{version} would mislabel it. Bump "
                        f"__version__ past {latest_on_pypi} and re-run.",
                    )
                ],
            )
        messages = [
            (
                WARNING,
                f"recovering an untagged publish: crumb-kit {version} is already on PyPI "
                f"but tag v{version} does not exist — a previous run published and then "
                "failed before tagging. Continuing: the upload is a no-op (skip-existing) "
                "and the tag + GitHub Release step completes the release.",
            )
        ]
        if mode == "publish":
            messages.append(
                (
                    WARNING,
                    "check that main has not advanced since that failed run — the tag is "
                    "cut on the commit this run builds, so a newer main would tag a commit "
                    f"whose build was never uploaded as v{version}.",
                )
            )
        else:
            messages.append(
                (
                    NOTICE,
                    "dry-run publishes nothing; re-run with mode=publish to complete the "
                    "release (upload no-ops, tag + Release are created).",
                )
            )
        return Decision(True, messages)

    if tag_exists:
        # Not on PyPI (or unknown) but tagged: a dead tag, like v0.1.5 / v0.1.6.
        # Re-using it would put a second, different commit behind an existing tag.
        return Decision(
            False,
            [
                (
                    ERROR,
                    f"tag v{version} already exists but crumb-kit {version} is not on PyPI — a "
                    'dead tag (see RELEASING.md, "Tag / PyPI history"). Never re-use a tag: '
                    "bump __version__ to a new version, or delete the dead tag and its Release "
                    "first if you deliberately want to re-cut it.",
                )
            ],
        )

    messages = []
    if on_pypi == ON_PYPI_UNKNOWN:
        messages.append(
            (
                WARNING,
                "could not determine whether crumb-kit "
                f"{version} is on PyPI; continuing (the upload uses skip-existing).",
            )
        )
    messages.append(
        (
            NOTICE,
            f"crumb-kit {version} is not on PyPI and tag v{version} is free — good to publish.",
        )
    )
    return Decision(True, messages)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", required=True, help="the version just built")
    p.add_argument(
        "--on-pypi",
        required=True,
        choices=[ON_PYPI_YES, ON_PYPI_NO, ON_PYPI_UNKNOWN],
        help="whether this version is already on PyPI",
    )
    p.add_argument("--latest-on-pypi", default="", help="newest version on PyPI, if known")
    p.add_argument("--tag-exists", required=True, choices=["true", "false"])
    p.add_argument("--mode", required=True, choices=["dry-run", "publish"])
    args = p.parse_args(argv)

    decision = decide(
        version=args.version,
        on_pypi=args.on_pypi,
        latest_on_pypi=args.latest_on_pypi.strip() or None,
        tag_exists=args.tag_exists == "true",
        mode=args.mode,
    )
    for level, text in decision.messages:
        # GitHub Actions annotations; readable as plain text anywhere else.
        print(f"::{level}::{text}")
    return 0 if decision.ok else 1


if __name__ == "__main__":
    sys.exit(main())
