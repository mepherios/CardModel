"""hook — using the model starts a cycle by itself when one is due; a schedule can run the full profile.

``after(args)``  runs after every command. When the cycle card's ``auto`` settings say a cycle is due (at least
                 ``min_interval_s`` since the last start; the run itself returns at once when nothing changed since
                 the last completed cycle and that one is younger than ``max_interval_s``), no cycle is running
                 anywhere on this machine, enough memory is free and the load is low, it starts
                 ``cardmodel cycle run --auto`` in the background (detached, niced, its output in
                 state/cycle/auto.log) and returns at once. It never runs in a cardmodel process started by another
                 one, never with CARDMODEL_AUTO_CYCLE=0 (or after ``cardmodel cycle auto off``), never for the
                 commands the card lists (servers, the emulator, the REPL), never in a linked git worktree unless
                 CARDMODEL_AUTO_CYCLE=1, and never loudly: a hook that fails is silent.
``before(args)`` on a terminal, one line when the last cycle found critical or high problems not shown yet.
``schedule``     a launchd agent (macOS) or a cron line that runs a profile on a timer; installing it is an
                 explicit command (``cardmodel cycle schedule --install``), never a side effect.

Honest limits (L1): "nothing changed" is a fingerprint of file sizes and times, so an edit that keeps both is
seen only after max_interval_s; the background cycle runs at a lower priority but still uses CPU and memory while
you work; the schedule installs for the current user only.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from ..kernel import paths

OFF = ("0", "off", "false", "no")
LABEL = "org.cardmodel.cycle"
_ENTERED = {"depth": None}


def enter() -> int:
    """Count how deep this cardmodel process is (1 = started by a person or a tool, 2+ = by another cardmodel
    process); children inherit CARDMODEL_DEPTH, so a nested process never starts a cycle."""
    if _ENTERED["depth"] is None:
        try:
            parent = int(os.environ.get("CARDMODEL_DEPTH", "0") or 0)
        except ValueError:
            parent = 0
        _ENTERED["depth"] = parent + 1
        os.environ["CARDMODEL_DEPTH"] = str(parent + 1)
    return _ENTERED["depth"]


def _state_dir(home: Path) -> Path:
    return paths.state_dir(home / "cards") / "cycle"


def _read(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def auto_config(home: Path) -> dict:
    """The cycle card's auto settings, read straight from the file (the hook must cost nothing when not due)."""
    data = _read(home / "cards" / "cycle" / "default" / "card.json")
    return data.get("auto") or {}


def linked_worktree(home: Path) -> bool:
    return (home / ".git").is_file()


def decide(args, home: Path, now: float | None = None) -> tuple[bool, str]:
    """(start a cycle now?, why). Pure apart from reading state, the card and the machine's load."""
    flag = os.environ.get("CARDMODEL_AUTO_CYCLE", "").strip().lower()
    if flag in OFF:
        return False, "CARDMODEL_AUTO_CYCLE is off"
    if (_ENTERED["depth"] or 1) > 1:
        return False, "started by another cardmodel process"
    if linked_worktree(home) and flag not in ("1", "on", "true", "yes"):
        return False, "a linked git worktree (set CARDMODEL_AUTO_CYCLE=1 to cycle here)"
    cfg = auto_config(home)
    if not cfg:
        return False, "no cycle card"
    cmd = getattr(args, "cmd", "") or ""
    action = getattr(args, "action", None)
    skip = set(cfg.get("skip_commands") or [])
    if cmd in skip or (action and f"{cmd} {action}" in skip):
        return False, f"`{cmd}` does not start cycles"
    st = _read(_state_dir(home) / "auto.json")
    if st.get("disabled"):
        return False, "turned off (cardmodel cycle auto on)"
    now = time.time() if now is None else now
    if now - float(st.get("last_start") or 0) < float(cfg.get("min_interval_s", 3600)):
        return False, "not due yet"
    from .run import running
    if running():
        return False, "a cycle is running"
    from ..kernel import resources
    free = resources.available_mb()
    if free is not None and free < int(cfg.get("min_free_mb", 3072)):
        return False, f"only {free} MB free"
    try:
        load = os.getloadavg()[0] / (os.cpu_count() or 1)
    except OSError:
        load = 0.0
    if load > float(cfg.get("max_load_per_cpu", 0.75)):
        return False, f"the machine is busy (load {load:.2f} per CPU)"
    return True, "due"


def start(home: Path) -> int:
    """Start the background cycle; record when, so the next command does not start another."""
    from ..kernel import resources
    d = _state_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    st = _read(d / "auto.json")
    st["last_start"] = time.time()
    env = dict(os.environ, PYTHONPATH=str(home), PYTHONDONTWRITEBYTECODE="1")
    env.pop("CARDMODEL_DEPTH", None)
    pid = resources.spawn_detached([sys.executable, "-B", "-m", "cardmodel", "--no-project", "cycle", "run", "--auto"],
                                   log_path=d / "auto.log", cwd=str(home), env=env)
    st["pid"] = pid
    _write(d / "auto.json", st)
    return pid


def after(args) -> None:
    try:
        home = paths.home()
        go, _why = decide(args, home)
        if go:
            start(home)
    except Exception:  # noqa: BLE001 -- the hook must never break the command that ran
        return


def notice(home: Path) -> str | None:
    p = _state_dir(home) / "auto.json"
    st = _read(p)
    last = st.get("last_run") or {}
    counts = last.get("counts") or {}
    bad = (counts.get("critical") or 0) + (counts.get("high") or 0)
    if not last or not bad or st.get("noticed") == last.get("started"):
        return None
    st["noticed"] = last.get("started")
    _write(p, st)
    return (f"cardmodel: the self-cycle of {last.get('started', '')[:16]} found {counts.get('critical') or 0} critical "
            f"and {counts.get('high') or 0} high finding(s), {last.get('regressions') or 0} regression(s): "
            "cardmodel cycle report")


def before(args) -> None:
    try:
        if getattr(args, "json", False) or not sys.stderr.isatty() or getattr(args, "cmd", "") == "cycle":
            return
        line = notice(paths.home())
        if line:
            print(line, file=sys.stderr)
    except Exception:  # noqa: BLE001 -- a notice is never worth an error
        return


def set_auto(home: Path, on: bool) -> dict:
    p = _state_dir(home) / "auto.json"
    st = _read(p)
    st["disabled"] = not on
    _write(p, st)
    return st


# -- the schedule ----------------------------------------------------------------------------------------------------
def schedule_args(home: Path, profile: str, record: bool, commit: bool) -> list[str]:
    args = [sys.executable, "-B", "-m", "cardmodel", "--no-project", "cycle", "run", "--profile", profile]
    if record:
        args.append("--record")
    if commit:
        args.append("--commit")
    return args


def plist(home: Path, profile: str = "full", record: bool = False, commit: bool = False,
          every_hours: float | None = 6, at: str | None = None) -> bytes:
    import plistlib
    log = str(_state_dir(home) / "schedule.log")
    d = {"Label": LABEL, "ProgramArguments": schedule_args(home, profile, record, commit),
         "WorkingDirectory": str(home), "StandardOutPath": log, "StandardErrorPath": log,
         "EnvironmentVariables": {"PYTHONPATH": str(home), "PYTHONDONTWRITEBYTECODE": "1",
                                  "CARDMODEL_AUTO_CYCLE": "0"},
         "Nice": 10, "LowPriorityIO": True, "ProcessType": "Background", "RunAtLoad": False}
    if at:
        h, m = (int(x) for x in at.split(":"))
        d["StartCalendarInterval"] = {"Hour": h, "Minute": m}
    else:
        d["StartInterval"] = int(float(every_hours or 6) * 3600)
    return plistlib.dumps(d)


def cron_line(home: Path, profile: str = "full", record: bool = False, commit: bool = False,
              every_hours: float | None = 6, at: str | None = None) -> str:
    if at:
        h, m = (int(x) for x in at.split(":"))
        when = f"{m} {h} * * *"
    else:
        when = f"0 */{max(1, int(every_hours or 6))} * * *"
    args = " ".join(schedule_args(home, profile, record, commit))
    log = _state_dir(home) / "schedule.log"
    return f"{when} cd {home} && PYTHONPATH={home} CARDMODEL_AUTO_CYCLE=0 {args} >> {log} 2>&1"


def agent_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def install(data: bytes) -> dict:
    """Write the launchd agent and load it for this user (macOS)."""
    from ..kernel import resources
    p = agent_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    domain = f"gui/{os.getuid()}"
    resources.run(["launchctl", "bootout", domain, str(p)], timeout=30, heavy=False)
    p.write_bytes(data)
    r = resources.run(["launchctl", "bootstrap", domain, str(p)], timeout=30, heavy=False)
    return {"path": str(p), "loaded": r.returncode == 0, "detail": (r.stderr or r.stdout or "")[-400:]}


def uninstall() -> dict:
    from ..kernel import resources
    p = agent_path()
    if not p.exists():
        return {"path": str(p), "removed": False, "detail": "not installed"}
    resources.run(["launchctl", "bootout", f"gui/{os.getuid()}", str(p)], timeout=30, heavy=False)
    p.unlink()
    return {"path": str(p), "removed": True}


__all__ = ["after", "agent_path", "before", "cron_line", "decide", "enter", "install", "linked_worktree", "notice",
           "plist", "set_auto", "start", "uninstall"]
