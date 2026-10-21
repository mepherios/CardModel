"""resources — keep the machine responsive: bounded parallel work, memory caps for children and for this process.

Policy (environment overrides; otherwise derived from this machine's RAM and CPUs):

  CARDMODEL_MAX_PARALLEL   heavy subprocesses at once, machine-wide (every cardmodel process shares the slots)
                           default min(4, cpus // 2, RAM GiB // 4), at least 1
  CARDMODEL_CHILD_MB       memory cap per subprocess tree   default 40% of RAM shared by the slots (max 3072)
  CARDMODEL_SELF_MB        memory cap for this process      default min(4096, RAM MiB // 4)
  CARDMODEL_MIN_FREE_MB    wait (up to WAIT_S) before heavy work while available memory is below this
  CARDMODEL_NICE           niceness for children            default 10

``run`` is ``subprocess.run`` with a machine-wide slot (a file lock in the system temp folder, so tests, CLI runs
and other checkouts never stack their compilers), a lower priority, its own process group and
a watchdog that sums the resident memory of the whole group (compilers spawn children) and kills the group when
it passes the cap. macOS does not enforce RLIMIT_AS, so the cap is enforced by watching. A killed run comes back
as returncode -9 with the reason appended to stderr; a timeout still raises ``subprocess.TimeoutExpired`` after
the group is killed (callers keep their handling).

``guard()`` raises ``MemoryBudget`` once this process's peak resident memory passes its cap. Hot loops (logic
rounds, witnesses, arena, function algebra) call it, so a runaway becomes a clean error, not a frozen machine.

Honest limits (L1): the watchdog samples every POLL_S seconds, so a child can briefly exceed its cap between
samples; peak memory (ru_maxrss) never goes down, so once the self cap trips this process stays tripped.
"""
from __future__ import annotations

import os
import resource
import signal
import subprocess
import sys
import threading
import time

POLL_S = 0.4
WAIT_S = 60.0


class MemoryBudget(MemoryError):
    """This process passed its memory cap (CARDMODEL_SELF_MB)."""


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def total_ram_mb() -> int:
    try:
        return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1 << 20))
    except (ValueError, OSError, AttributeError):
        return 8192


def available_mb() -> int | None:
    """Memory the OS can hand out without swapping (macOS: free + inactive + speculative + purgeable pages)."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
            page = 4096
            first = out.splitlines()[0] if out else ""
            if "page size of" in first:
                page = int(first.split("page size of")[1].split()[0])
            pages = 0
            for line in out.splitlines()[1:]:
                key, _, val = line.partition(":")
                if key.strip() in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
                    pages += int(val.strip().rstrip("."))
            return pages * page // (1 << 20)
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None
    return None


def policy() -> dict:
    ram = total_ram_mb()
    cpus = os.cpu_count() or 2
    return {
        "ram_mb": ram, "cpus": cpus,
        "max_parallel": _env_int("CARDMODEL_MAX_PARALLEL", max(1, min(4, cpus // 2, ram // 4096))),
        "child_mb": _env_int("CARDMODEL_CHILD_MB", min(3072, int(ram * 0.4) // max(1, min(4, cpus // 2, ram // 4096)))),
        "self_mb": _env_int("CARDMODEL_SELF_MB", min(4096, ram // 4)),
        "min_free_mb": _env_int("CARDMODEL_MIN_FREE_MB", 1024),
        "nice": _env_int("CARDMODEL_NICE", 10),
    }


_POLICY = policy()


class _Slot:
    """One of max_parallel machine-wide slots: an exclusive flock on <tmp>/cardmodel-slots/<i>.lock."""

    def __enter__(self):
        import fcntl
        import tempfile
        d = os.path.join(tempfile.gettempdir(), "cardmodel-slots")
        os.makedirs(d, exist_ok=True)
        n = _POLICY["max_parallel"]
        while True:
            for i in range(n):
                f = open(os.path.join(d, f"{i}.lock"), "a")  # noqa: SIM115 -- held for the slot's lifetime
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.f = f
                    return self
                except OSError:
                    f.close()
            time.sleep(0.2)

    def __exit__(self, *exc):
        import fcntl
        try:
            fcntl.flock(self.f, fcntl.LOCK_UN)
        finally:
            self.f.close()


def max_parallel() -> int:
    return _POLICY["max_parallel"]


def peak_mb() -> float:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1 << 20) if sys.platform == "darwin" else rss / 1024


def guard(where: str = "") -> None:
    """Raise MemoryBudget when this process's peak memory passed its cap. Cheap (one getrusage call)."""
    peak = peak_mb()
    if peak > _POLICY["self_mb"]:
        raise MemoryBudget(f"cardmodel used {peak:.0f} MB (cap {_POLICY['self_mb']} MB, CARDMODEL_SELF_MB)"
                           + (f" in {where}" if where else "") + "; stopped before the machine runs out of memory")


_LIBPROC = None


def _libproc():
    """macOS libproc via ctypes: list a process group and read resident sizes without spawning ``ps`` (which can
    stall exactly when memory is short)."""
    global _LIBPROC
    if _LIBPROC is None:
        _LIBPROC = False
        if sys.platform == "darwin":
            try:
                import ctypes
                lib = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
                lib.proc_listpgrppids.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
                lib.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
                _LIBPROC = (ctypes, lib)
            except OSError:
                _LIBPROC = False
    return _LIBPROC


def _group_rss_mb(pgid: int) -> float:
    lp = _libproc()
    if lp:
        ctypes, lib = lp
        pids = (ctypes.c_int * 512)()
        n = lib.proc_listpgrppids(pgid, pids, ctypes.sizeof(pids))
        count = max(0, n) // ctypes.sizeof(ctypes.c_int) if n > 512 else max(0, n)
        info = (ctypes.c_uint64 * 12)()                     # struct proc_taskinfo: resident size at index 1
        total = 0
        for pid in list(pids)[:min(count, 512)]:
            if pid <= 0:
                continue
            if lib.proc_pidinfo(pid, 4, 0, info, ctypes.sizeof(info)) > 0:   # PROC_PIDTASKINFO
                total += info[1]
        return total / (1 << 20)
    try:
        out = subprocess.run(["ps", "-A", "-o", "pgid=,rss="], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return 0.0
    total = 0
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) == pgid:
            total += int(parts[1])
    return total / 1024


def _wait_for_memory() -> None:
    need = _POLICY["min_free_mb"]
    deadline = time.monotonic() + WAIT_S
    while time.monotonic() < deadline:
        avail = available_mb()
        if avail is None or avail >= need:
            return
        time.sleep(1.0)


def run(args, *, timeout: float, heavy: bool = True, mem_cap_mb: int | None = None, input=None,  # noqa: A002
        capture_output: bool = True, text: bool = True, **kw) -> subprocess.CompletedProcess:
    """subprocess.run under the policy: a parallel slot, lower priority, a process-group memory cap."""
    cap = mem_cap_mb or _POLICY["child_mb"]
    slot = _Slot() if heavy else None
    if heavy:
        _wait_for_memory()
        slot.__enter__()
    try:
        if capture_output:
            kw.setdefault("stdout", subprocess.PIPE)
            kw.setdefault("stderr", subprocess.PIPE)
        if input is not None:
            kw["stdin"] = subprocess.PIPE
        p = subprocess.Popen(args, text=text, start_new_session=True, **kw)
        try:
            os.setpriority(os.PRIO_PGRP, p.pid, _POLICY["nice"])
        except (OSError, AttributeError):
            pass
        state = {"killed": False, "rss": 0.0}
        done = threading.Event()

        def watch():
            while not done.wait(POLL_S):
                rss = _group_rss_mb(p.pid)
                state["rss"] = max(state["rss"], rss)
                if rss > cap:
                    state["killed"] = True
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        pass
                    return

        w = threading.Thread(target=watch, daemon=True)
        w.start()
        try:
            out, err = p.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            p.communicate()
            done.set()
            raise
        finally:
            done.set()
        if state["killed"]:
            note = (f"\n[cardmodel] killed: the process group used {state['rss']:.0f} MB, over the "
                    f"{cap} MB cap (CARDMODEL_CHILD_MB)\n")
            err = (err or "") + note if text else (err or b"") + note.encode()
            return subprocess.CompletedProcess(args, -9, out, err)
        return subprocess.CompletedProcess(args, p.returncode, out, err)
    finally:
        if heavy:
            slot.__exit__(None, None, None)


__all__ = ["MemoryBudget", "available_mb", "guard", "max_parallel", "peak_mb", "policy", "run", "total_ram_mb"]
