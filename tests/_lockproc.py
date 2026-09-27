"""Real processes that hold, or try to take, a store's write lock.

Not a test module — `unittest discover` ignores it. The lock is an OS lock
(audit WP05), so a test of it has to use a second process: a pid written into a
file proves nothing to the kernel.
"""

from __future__ import annotations

import contextlib
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

_HOLD = """
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from breadcrumbs import lock
with lock.store_lock(Path(sys.argv[2]), timeout=10):
    print("held", flush=True)
    sys.stdin.readline()  # hold until the parent says so
"""

_PROBE = """
import sys
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from breadcrumbs import lock
try:
    with lock.store_lock(Path(sys.argv[2]), timeout=float(sys.argv[3])):
        pass
except lock.StoreLocked:
    sys.exit(1)
"""


def spawn_holder(mem: Path) -> subprocess.Popen:
    """A process that has taken the lock by the time this returns."""
    proc = subprocess.Popen(
        [sys.executable, "-c", _HOLD, str(REPO_ROOT), str(mem)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    line = proc.stdout.readline().strip()
    if line != "held":  # pragma: no cover - a broken fixture, not a finding
        proc.kill()
        raise RuntimeError(f"lock holder did not start: {line!r}")
    return proc


@contextlib.contextmanager
def held_by_another_process(mem: Path):
    """A live foreign process holds the lock for the `with` body; yields its pid."""
    proc = spawn_holder(mem)
    try:
        yield proc.pid
    finally:
        with contextlib.suppress(OSError):
            proc.stdin.close()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:  # pragma: no cover
            proc.kill()
            proc.wait()


def can_take(mem: Path, timeout: float = 0.0) -> bool:
    """Could a separate process take the lock right now (within `timeout`)?"""
    return (
        subprocess.run(
            [sys.executable, "-c", _PROBE, str(REPO_ROOT), str(mem), str(timeout)],
            capture_output=True,
        ).returncode
        == 0
    )
