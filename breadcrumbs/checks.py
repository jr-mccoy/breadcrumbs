"""Replay: running a recorded check, and what its result may claim (audit F04, F25).

`crumb verify --recheck` used to run every `command` and `test` evidence string
and write `fixed` when all of them exited 0. A successful process is not proof:
a `python -c pass` "fixed" an authentication bug, and a test-file path was run
as if it were a program. This module keeps two things apart:

- **Execution** — a `CheckResult`: did the command run, how did it end, what did
  it print (bounded). It says nothing about the subject.
- **Settlement** — only an *assertion* may settle a verification's claim. An
  assertion is an evidence item `{type: assert, ref: <command>, spec: "1"}`
  declaring that the command exits 0 exactly when the subject is fixed (a
  regression test for it). Legacy `command` evidence is a *diagnostic*: it may be
  run, with consent, and reported, but it cannot change the claim. `test`
  evidence is a pointer to a test file and is never executed.

A check that could not be evaluated (the tool is missing, it timed out, it was
killed, its spec is unknown) is inconclusive: it neither opens nor fixes
anything.

Commands run through the platform's shell, as they always have, so a recorded
command means what its author typed. POSIX parsing is never applied to a
Windows string. Each run gets its own process group (on Windows, a Job Object)
and bounded, rolling output capture. The whole group is terminated on timeout,
on interruption, and after the command returns, so a background child cannot
outlive its check.
"""

from __future__ import annotations

import os
import platform
import signal
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# The assertion format this build evaluates. An assertion with any other `spec`
# is reported and not run: guessing what a newer format meant is how a check
# settles a claim it was never written to settle.
ASSERTION_SPEC = "1"
ASSERT_TYPE = "assert"
DIAGNOSTIC_TYPE = "command"

TIMEOUT_SECONDS = 300
# What is kept of a run's output while it runs: a rolling window, so a command
# that prints gigabytes costs this much memory, not gigabytes.
OUTPUT_WINDOW_BYTES = 64 * 1024
TAIL_LINES = 3
KILL_GRACE_SECONDS = 2.0

# Execution statuses. Only PASSED and FAILED are evaluations; the rest say the
# check did not produce one.
PASSED = "passed"
FAILED = "failed"
UNAVAILABLE = "unavailable"  # could not start, or the shell could not find/run it
TIMEOUT = "timeout"
KILLED = "killed"  # ended by a signal it did not ask for
UNSUPPORTED = "unsupported"  # an assertion spec this build does not know
EVALUATED = (PASSED, FAILED)

# What a shell reports when it could not run the command at all: POSIX `sh`
# uses 127 (not found) and 126 (found, not executable); `cmd.exe` uses 9009.
_UNAVAILABLE_CODES = (126, 127) if os.name == "posix" else (9009,)


@dataclass
class CheckResult:
    """One execution of one recorded command. Never a verdict on a subject."""

    command: str
    kind: str  # "assert" | "diagnostic"
    status: str
    exit_code: int | None = None
    signal: int | None = None
    timed_out: bool = False
    duration_s: float = 0.0
    output_bytes: int = 0
    truncated: bool = False
    tail: list[str] = field(default_factory=list)
    cwd: str = ""
    platform: str = ""
    detail: str | None = None
    # How the run's processes were contained, so a report can say what ended
    # them (audit F25): "process-group" (POSIX), "job-object" (Windows), or
    # "taskkill" with the reason a job was not available.
    containment: str = ""

    @property
    def evaluated(self) -> bool:
        return self.status in EVALUATED

    def to_dict(self) -> dict:
        return asdict(self)


def assertion_items(meta: dict) -> list[dict]:
    """A verification's declared assertions, in order."""
    return [
        e
        for e in (meta.get("evidence") or [])
        if isinstance(e, dict) and e.get("type") == ASSERT_TYPE and str(e.get("ref") or "").strip()
    ]


def diagnostic_commands(meta: dict) -> list[str]:
    """Legacy `command` evidence: runnable, reportable, never settling."""
    return [
        str(e["ref"])
        for e in (meta.get("evidence") or [])
        if isinstance(e, dict) and e.get("type") == DIAGNOSTIC_TYPE and e.get("ref")
    ]


def assertion_item(command: str) -> dict:
    """The evidence item `crumb verify --assert CMD` writes."""
    return {"type": ASSERT_TYPE, "ref": command, "spec": ASSERTION_SPEC}


def _tail(raw: bytes) -> list[str]:
    from breadcrumbs.transcript import redact_secrets

    text = raw.decode("utf-8", errors="replace")
    lines = [ln for ln in text.splitlines() if ln.strip()][-TAIL_LINES:]
    return [
        ln if redact_secrets(ln) is not None else "[line dropped: looked like a secret]"
        for ln in lines
    ]


def _windows_job(proc: subprocess.Popen):
    """Put `proc` in a new Windows Job Object: `(handle, None)`, or `(None, why not)`.

    A process group is not a tree on Windows: once the shell has returned,
    `taskkill /T` can no longer find a child it left running, and that child
    outlived its check (seen on the WP17 native CI job). Every process `proc`
    starts after this call is in the job too, whether or not its parent is
    still alive, and terminating the job ends them all. The job is also
    kill-on-close, so the tree ends if this process dies first. One window
    remains: a child started between the shell starting and joining the job
    (immediately after `Popen` returns) would not be in it. Shell startup is
    far slower than that call, but the race is not eliminated; closing it
    needs a suspended start, which `subprocess` does not offer.
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
        ]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]

        class _Basic(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _Io(ctypes.Structure):
            _fields_ = [
                (name, ctypes.c_uint64)
                for name in ("Read", "Write", "Other", "ReadBytes", "WriteBytes", "OtherBytes")
            ]

        class _Extended(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _Basic),
                ("IoInfo", _Io),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return None, f"CreateJobObject failed ({ctypes.get_last_error()})"
        info = _Extended()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
            note = f"SetInformationJobObject failed ({ctypes.get_last_error()})"
            kernel32.CloseHandle(job)
            return None, note
        if not kernel32.AssignProcessToJobObject(job, int(proc._handle)):
            note = f"AssignProcessToJobObject failed ({ctypes.get_last_error()})"
            kernel32.CloseHandle(job)
            return None, note
        return job, None
    except Exception as exc:  # pragma: no cover - fall back to taskkill
        return None, f"{type(exc).__name__}: {exc}"


def _windows_sweep(root_pid: int, started_filetime: int) -> tuple[int, int]:
    """End every process descended from `root_pid` that started after the run
    did; return `(descendants found, ended)`. Windows only, best effort.

    Windows keeps a process's parent id after the parent exits, so an orphan
    is still found through a dead intermediate. A process that started before
    the run cannot be a descendant (its id could have been reused), so it is
    never touched.
    """
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class _Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD),
                ("th32DefaultHeapID", ctypes.c_size_t),
                ("th32ModuleID", wintypes.DWORD),
                ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wintypes.DWORD),
                ("szExeFile", ctypes.c_wchar * 260),
            ]

        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.OpenProcess.restype = wintypes.HANDLE
        snap = kernel32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
        if not snap or snap == wintypes.HANDLE(-1).value:
            return 0, 0
        parents: dict[int, int] = {}
        try:
            entry = _Entry()
            entry.dwSize = ctypes.sizeof(_Entry)
            ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
            while ok:
                parents[entry.th32ProcessID] = entry.th32ParentProcessID
                ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snap)
        tree, frontier = set(), {root_pid}
        while frontier:
            frontier = (
                {pid for pid, ppid in parents.items() if ppid in frontier} - tree - {root_pid}
            )
            tree |= frontier
        ended = 0
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [
            ctypes.POINTER(wintypes.FILETIME)
        ] * 4
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        for pid in tree:
            handle = kernel32.OpenProcess(0x1000 | 0x0001, False, pid)  # QUERY_LIMITED | TERMINATE
            if not handle:
                continue
            try:
                created, t1, t2, t3 = (wintypes.FILETIME() for _ in range(4))
                if kernel32.GetProcessTimes(
                    handle, *(ctypes.byref(t) for t in (created, t1, t2, t3))
                ):
                    when = (created.dwHighDateTime << 32) | created.dwLowDateTime
                    if when >= started_filetime and kernel32.TerminateProcess(handle, 1):
                        ended += 1
            finally:
                kernel32.CloseHandle(handle)
        return len(tree), ended
    except Exception:  # pragma: no cover
        return -1, 0


def _filetime_now() -> int:
    """Now, as a Windows FILETIME (100 ns ticks since 1601)."""
    return int((time.time() + 11644473600) * 10_000_000)


def _end_windows_job(job) -> str:
    """Terminate and close the job; say how that went (for `containment`)."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        ok = kernel32.TerminateJobObject(job, 1)
        note = "job terminated" if ok else f"TerminateJobObject failed ({ctypes.get_last_error()})"
        kernel32.CloseHandle(job)
        return note
    except Exception as exc:  # pragma: no cover
        return f"job not terminated: {type(exc).__name__}: {exc}"


def _kill_tree(proc: subprocess.Popen, job=None, started_filetime: int | None = None) -> str:
    """End the run's whole process group; best effort, never raises. Returns a
    note on what ended it, for the run's `containment` (empty on POSIX)."""
    if os.name == "posix":
        # SIGTERM first, so the leader can clean up; then SIGKILL for whatever
        # is left. The group itself cannot be polled for "done": an exited
        # member stays a zombie until its parent reaps it, and an orphan's new
        # parent (PID 1, which in a container is often not a real init) may not
        # reap it promptly. So wait on the one process we own, the leader.
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            return ""  # the group is gone
        deadline = time.monotonic() + KILL_GRACE_SECONDS
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.05)  # a moment for the rest of the group's SIGTERM handlers
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    else:  # pragma: no cover - exercised on Windows only (the native CI job)
        notes = []
        if job is not None:
            # Ends every process the run started that is in the job.
            notes.append(_end_windows_job(job))
        else:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=10,
                )
            except (OSError, subprocess.SubprocessError):
                pass
        # A job does not hold a child that broke away from it (a CI runner's
        # job can allow that silently), and taskkill cannot find an orphan
        # whose parent has exited. The sweep finds both by parent id.
        if started_filetime is not None:
            found, ended = _windows_sweep(proc.pid, started_filetime)
            notes.append(f"sweep: {found} descendant(s) found, {ended} ended")
        return "; ".join(notes)
    return ""


def run_check(
    command: str,
    cwd: Path,
    *,
    kind: str = "diagnostic",
    timeout: float | None = None,
    window: int | None = None,
) -> CheckResult:
    """Run one command in `cwd` and describe how it ended. Never raises except
    KeyboardInterrupt, which first ends the whole process group."""
    timeout = TIMEOUT_SECONDS if timeout is None else timeout
    window = OUTPUT_WINDOW_BYTES if window is None else window
    result = CheckResult(
        command=command,
        kind=kind,
        status=UNAVAILABLE,
        cwd=str(cwd),
        platform=f"{platform.system()} ({'sh' if os.name == 'posix' else 'cmd'})",
    )
    kwargs: dict = {
        "shell": True,
        "cwd": str(cwd),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "posix":
        kwargs["start_new_session"] = True
    else:  # pragma: no cover
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    started = time.monotonic()
    started_filetime = _filetime_now() - 10_000_000  # a second of clock slack
    try:
        proc = subprocess.Popen(command, **kwargs)
    except (OSError, ValueError) as exc:
        result.detail = f"could not start: {exc}"
        return result
    job = None
    if os.name == "nt":  # pragma: no cover - exercised on Windows only
        job, why_not = _windows_job(proc)
        result.containment = "job-object" if job is not None else f"taskkill ({why_not})"
    else:
        result.containment = "process-group"

    kept = bytearray()
    seen = [0]
    kill_notes: list[str] = []

    def read() -> None:
        stream = proc.stdout
        try:
            while True:
                chunk = stream.read1(65536) if hasattr(stream, "read1") else stream.read(65536)
                if not chunk:
                    return
                seen[0] += len(chunk)
                kept.extend(chunk)
                if len(kept) > window:
                    del kept[: len(kept) - window]
        except (OSError, ValueError):
            return

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        result.timed_out = True
    except KeyboardInterrupt:
        raise  # the `finally` below ends the whole tree first, exactly once
    finally:
        # After a timeout this ends the command; after a normal return it ends
        # whatever the command left running in the background.
        note = _kill_tree(proc, job, started_filetime)
        if note:
            kill_notes.append(note)
    try:
        proc.wait(timeout=KILL_GRACE_SECONDS + 1)
    except subprocess.TimeoutExpired:  # pragma: no cover - SIGKILL did not land
        pass
    reader.join(timeout=KILL_GRACE_SECONDS + 1)
    if not reader.is_alive():
        # Closing while the reader still blocks on the pipe would wait for every
        # writer to exit — including one that escaped the group (`setsid`). The
        # daemon reader is left to end with the pipe instead.
        try:
            proc.stdout.close()
        except OSError:  # pragma: no cover
            pass
    escaped = reader.is_alive()

    result.duration_s = round(time.monotonic() - started, 3)
    result.output_bytes = seen[0]
    result.truncated = seen[0] > len(kept)
    result.tail = _tail(bytes(kept))
    code = proc.returncode
    if result.timed_out:
        result.status = TIMEOUT
        result.detail = f"timed out after {timeout:g}s; process group terminated"
    elif code is None:  # pragma: no cover
        result.status = KILLED
    elif code < 0:
        result.status, result.signal = KILLED, -code
    else:
        result.exit_code = code
        if code in _UNAVAILABLE_CODES:
            result.status = UNAVAILABLE
            result.detail = f"exit {code}: the shell could not find or run the command"
        else:
            result.status = PASSED if code == 0 else FAILED
    if kill_notes:
        result.containment += "; " + "; ".join(kill_notes)
    if escaped:
        note = "a process that left the group kept the output open and was not ended"
        result.detail = f"{result.detail}; {note}" if result.detail else note
    return result


def run_assertion(item: dict, cwd: Path, **kwargs) -> CheckResult:
    """Run one assertion item, or report why it cannot be run."""
    command = str(item.get("ref") or "")
    spec = str(item.get("spec") or "")
    if spec != ASSERTION_SPEC:
        return CheckResult(
            command=command,
            kind="assert",
            status=UNSUPPORTED,
            cwd=str(cwd),
            detail=f"assertion spec {spec or '(none)'!r} is not one this build evaluates "
            f"(supported: {ASSERTION_SPEC})",
        )
    return run_check(command, cwd, kind="assert", **kwargs)


def settle(old_outcome: str | None, assertions: list[CheckResult]) -> tuple[str | None, str]:
    """(new outcome or None, why) from a verification's assertion runs.

    None means the claim stands as it was: there was no assertion, or one of
    them could not be evaluated. Diagnostics are never passed in here.
    """
    if not assertions:
        return None, "no assertion is declared; diagnostics do not settle a claim"
    unevaluated = [r for r in assertions if not r.evaluated]
    if unevaluated:
        first = unevaluated[0]
        return None, f"inconclusive: `{first.command}` {first.status}"
    if all(r.status == PASSED for r in assertions):
        return "fixed", "every assertion passed"
    if (old_outcome or "") in ("fixed", "not_applicable"):
        return "regressed", "an assertion failed on a subject recorded as fixed"
    return "open", "an assertion failed"
