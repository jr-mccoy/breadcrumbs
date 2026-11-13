"""Decide whether the `ci` workflow passed on the commit a release would publish.

Called by `.github/workflows/release.yml` in `mode: publish`, before anything
irreversible. It reads the GitHub API's list of `ci` runs for the commit on
stdin (`GET /repos/{repo}/actions/workflows/ci.yml/runs?head_sha=…`) and exits
0 only when the newest run that tested the commit as written succeeded. It
lives here, as a plain stdlib module with unit tests
(`tests/test_release_process.py`), for the same reason as
`release_preflight.py`: the rule failed in ways nobody saw until a release.

* **It fails closed.** No readable answer, no run, a run still going, or a run
  that did not succeed all stop the publish. The shell step it replaced
  printed a warning and published when the API call failed or found nothing.
* **Scheduled runs are not the commit's result.** The weekly run re-tests an
  unchanged `main` on whatever the runner image has become. When Ubuntu 26.04
  dropped Python 3.9 (2026-11), that run went red on a commit whose push run
  was green, and because the gate read only the newest run of any kind, the
  commit became unpublishable. A push, pull-request or manual run decides; a
  newer failed scheduled run is still reported, as a warning.
"""

from __future__ import annotations

import argparse
import json
import sys

# The weekly drift check (ci.yml `schedule`). Everything else tested the commit
# as written: `push`, `pull_request`, and a manual `workflow_dispatch` re-run.
DRIFT_EVENTS = frozenset({"schedule"})


class Decision:
    # A plain class: the tests load this file by path, outside `sys.modules`,
    # where a dataclass with string annotations cannot be built.
    def __init__(self, ok: bool, messages: list[tuple[str, str]] | None = None):
        self.ok = ok
        self.messages = list(messages or [])  # (level, text)

    def text(self) -> str:
        return "\n".join(t for _level, t in self.messages)


def _newest(runs: list[dict]) -> dict | None:
    # The API lists newest first; sorting makes that an explicit property.
    return max(runs, key=lambda r: (str(r.get("created_at") or ""), r.get("id") or 0), default=None)


def decide(payload: str, sha: str) -> Decision:
    try:
        data = json.loads(payload)
        runs = [r for r in data["workflow_runs"] if r.get("head_sha") in (None, sha)]
    except (ValueError, KeyError, TypeError):
        return Decision(
            False,
            [
                (
                    "error",
                    f"Could not read the 'ci' runs for {sha} from the GitHub API; not publishing.",
                )
            ],
        )
    tested = _newest([r for r in runs if r.get("event") not in DRIFT_EVENTS])
    msgs: list[tuple[str, str]] = []
    if tested is None:
        return Decision(
            False,
            [
                (
                    "error",
                    f"No 'ci' run tested {sha} (scheduled runs do not count). Run 'ci' on "
                    "main (Actions → ci → Run workflow), wait for it to pass, then re-run.",
                )
            ],
        )
    status, conclusion, url = tested.get("status"), tested.get("conclusion"), tested.get("html_url")
    drift = _newest([r for r in runs if r.get("event") in DRIFT_EVENTS])
    if (
        drift is not None
        and drift.get("status") == "completed"
        and drift.get("conclusion") != "success"
        and str(drift.get("created_at") or "") > str(tested.get("created_at") or "")
    ):
        msgs.append(
            (
                "warning",
                f"A later scheduled 'ci' run on {sha} concluded '{drift.get('conclusion')}' "
                f"({drift.get('html_url')}): the runner image may have changed since this "
                "commit was tested. It does not block the publish.",
            )
        )
    if status != "completed":
        msgs.append(
            ("error", f"CI is still {status} on {sha} ({url}). Wait for it to finish, then re-run.")
        )
        return Decision(False, msgs)
    if conclusion != "success":
        msgs.append(
            (
                "error",
                f"CI concluded '{conclusion}' on {sha} ({url}). Fix it and merge before publishing.",
            )
        )
        return Decision(False, msgs)
    msgs.append(("notice", f"CI succeeded on {sha} ({tested.get('event')} run, {url})."))
    return Decision(True, msgs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--sha", required=True, help="the commit the release builds")
    args = p.parse_args(argv)
    decision = decide(sys.stdin.read(), args.sha)
    for level, text in decision.messages:
        # GitHub Actions annotations; readable as plain text anywhere else.
        print(f"::{level}::{text}")
    return 0 if decision.ok else 1


if __name__ == "__main__":
    sys.exit(main())
