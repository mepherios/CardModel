"""run — one bounded cycle: the model running, checking and improving itself as one unit (law CM38).

    run(profile, record=False, stages=None, seed=None, budget_s=None, commit=False, auto=False)

1. a machine-wide lock: one cycle at a time across every checkout (one heavy job at a time);
2. the cycle card's profile (``cards/cycle/default``): which stages, which verify sections, the time budget;
3. every stage in turn: the remaining budget caps each child process, the resource governor caps memory and
   parallel compilers, and a stage that raises is recorded as an error while the next one still runs (a
   ``MemoryBudget`` stops the cycle: the machine comes first);
4. the analysis against the last run (``report.analyse``): findings, regressions, strengths, next actions;
5. ``state/cycle``: ``last.json`` (this run), ``runs/`` (the last N runs), ``history.jsonl`` (one line per run),
   ``report.md``. ``record`` also writes the evidence that lasts: ledger growth, learned function cards, the
   generated documents and WEAKNESSES.md; ``record_verdicts`` adds verify's per-card verdicts; ``commit`` makes a
   local commit of exactly what the cycle changed, only when the tree was clean before it started (never a push).

An ``auto`` run (started by the hook) first checks the model's fingerprint and returns at once when nothing
changed since the last completed run and that run is younger than the card's ``max_interval_s``.

Every stage also runs under a deadline (the remaining budget, or the card's ``stage_limits_s`` when shorter): a
stage that runs in this process and does not return in time is interrupted (``StageTimeout``), its children are
killed, it is recorded as an error, and the next stage runs.

Honest limits (L1): the deadline is a timer signal, so it interrupts Python code but not one long call inside C
(a single huge integer operation finishes first); it needs the main thread (elsewhere stages run unbounded and
the budget is checked between them); the lock is advisory (flock on the system's temporary folder), so it
coordinates the processes of one machine only.
"""
from __future__ import annotations

import json
import os
import socket
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from ..kernel import paths, resources
from . import report
from .stages import STAGES

LOCK_NAME = "cardmodel-cycle.lock"


class Busy(RuntimeError):
    """Another cycle holds the machine-wide lock."""


class StageTimeout(Exception):
    """A stage ran past its deadline."""


@contextmanager
def deadline_after(seconds: float | None):
    """Interrupt the code inside after ``seconds`` (a real-time timer signal; main thread only)."""
    import signal
    import threading
    if not seconds or not hasattr(signal, "setitimer") or threading.current_thread() is not threading.main_thread():
        yield
        return

    def ring(signum, frame):
        raise StageTimeout(f"ran past its deadline ({seconds:.0f} s)")
    old = signal.signal(signal.SIGALRM, ring)
    signal.setitimer(signal.ITIMER_REAL, float(seconds))
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _lock_path() -> str:
    import tempfile
    return os.path.join(tempfile.gettempdir(), os.environ.get("CARDMODEL_CYCLE_LOCK") or LOCK_NAME)


@contextmanager
def machine_lock(info: dict):
    import fcntl
    f = open(_lock_path(), "a+")  # noqa: SIM115 -- held for the whole cycle
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        held = f.read().strip()
        f.close()
        raise Busy(held or "another cycle is running") from None
    f.seek(0)
    f.truncate()
    f.write(json.dumps(info))
    f.flush()
    try:
        yield
    finally:
        f.seek(0)
        f.truncate()
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


def running() -> dict | None:
    """The running cycle's lock record, or None when no cycle runs on this machine."""
    import fcntl
    try:
        f = open(_lock_path(), "a+")  # noqa: SIM115
    except OSError:
        return None
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        text = f.read().strip()
        f.close()
        try:
            return json.loads(text) if text else {"pid": None}
        except json.JSONDecodeError:
            return {"pid": None}
    fcntl.flock(f, fcntl.LOCK_UN)
    f.close()
    return None


def model_ctx():
    """The cycle is about the model itself: never a project's layer."""
    from ..engines.context import Ctx
    from ..kernel.store import open_store
    return Ctx(open_store(project=False))


def config(ctx) -> dict:
    card = ctx.store.get("cycle/default")
    if card is None:
        raise KeyError("no cycle card (cards/cycle/default): the cycle's profiles are data, see docs/CYCLE.md")
    return dict(card)


def cycle_dir(ctx) -> Path:
    d = ctx.state_root / "cycle"
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_last(state: Path) -> dict | None:
    p = state / "last.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def fingerprint(home: Path | None = None) -> str:
    """Sizes and modification times of the files that make the model (code, cards, stdlib, tests, examples)."""
    import hashlib
    home = home or paths.home()
    h = hashlib.sha256()
    for top in ("cardmodel", "cards", "stdlib", "tests", "examples", "arena"):
        for root, dirs, files in os.walk(home / top):
            dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "_versions"))
            for name in sorted(files):
                try:
                    st = os.stat(os.path.join(root, name))
                except OSError:
                    continue
                h.update(f"{root}/{name}:{st.st_size}:{int(st.st_mtime)}\n".encode())
    return h.hexdigest()[:16]


class Env:
    """What every stage sees: the model, the cycle card, the profile, the seed, the budget, earlier results."""

    def __init__(self, ctx, cfg: dict, profile_name: str, seed: int, record: bool, record_verdicts: bool,
                 deadline: float, state: Path, say):
        self.ctx, self.cfg = ctx, cfg
        self.profile_name = profile_name
        self.profile = cfg["profiles"][profile_name]
        self.seed = seed
        self.record, self.record_verdicts = record, record_verdicts
        self.deadline = deadline
        self.state = state
        self.say = say
        self.results: dict = {}
        self.verify_report = None
        self.self_observation = None

    def remaining(self, cap: float | None = None) -> float:
        left = max(60.0, self.deadline - time.monotonic())
        return min(left, cap) if cap else left

    def restore_verify(self) -> None:
        """Put this cycle's verify report back as last_verify.json (a test's partial verify may have replaced it)."""
        if self.verify_report is not None:
            from ..engines.verify import save_report
            save_report(self.ctx, self.verify_report)

    def note(self, **kw) -> None:
        """Numbers the goals read (coverage: law_witnesses_failing, store_items_failing, cycle_regressions)."""
        from . import evidence
        evidence.note(self.ctx, **kw)


def _history_line(run: dict) -> dict:
    st = run.get("stages") or {}
    goals = {g["goal"]: g["value"] for g in (st.get("goals") or {}).get("goals") or []}
    an = run.get("analysis") or {}
    a = (st.get("optimize") or {}).get("arena") or {}
    return {"started": run["started"], "finished": run["finished"], "seconds": run["seconds"],
            "profile": run["profile"], "seed": run["seed"], "record": run.get("record"), "auto": run.get("auto"),
            "status": run["status"], "counts": an.get("counts"), "regressions": an.get("regressions"),
            "stages": {n: [r.get("status"), r.get("seconds")] for n, r in st.items()}, "goals": goals,
            "self_named_fraction": ((st.get("learn") or {}).get("self") or {}).get("named_fraction"),
            "arena": {k: a.get(k) for k in ("sound", "recall", "geomean_speedup")} if a else None,
            "tests": (st.get("tests") or {}).get("counts"), "peak_memory_mb": run.get("peak_memory_mb")}


def _save(state: Path, run: dict, md: str, cfg: dict) -> None:
    keep = cfg.get("history") or {}
    text = json.dumps(run, indent=1, sort_keys=True, default=str)
    (state / "last.json").write_text(text, encoding="utf-8")
    runs = state / "runs"
    runs.mkdir(exist_ok=True)
    stamp = run["started"].replace(":", "").replace("-", "").replace("+0000", "Z")
    (runs / f"{stamp}-{run['seed']}.json").write_text(text, encoding="utf-8")
    for old in sorted(runs.glob("*.json"))[:-int(keep.get("runs_kept", 30))]:
        old.unlink(missing_ok=True)
    hist = state / "history.jsonl"
    lines = hist.read_text(encoding="utf-8").splitlines() if hist.is_file() else []
    lines.append(json.dumps(_history_line(run), sort_keys=True, default=str))
    hist.write_text("\n".join(lines[-int(keep.get("lines_kept", 1000)):]) + "\n", encoding="utf-8")
    (state / "report.md").write_text(md, encoding="utf-8")


def _git(args: list[str], home: Path, timeout: float = 120):
    return resources.run(["git", *args], cwd=str(home), timeout=timeout, heavy=False)


def git_clean(home: Path) -> bool | None:
    """True when the checkout has no uncommitted changes; None when it is not a git checkout."""
    try:
        p = _git(["status", "--porcelain=v1", "-uall"], home)
    except Exception:  # noqa: BLE001 -- no git (or it hung): nothing to commit, nothing to compare
        return None
    if p.returncode != 0:
        return None
    return not p.stdout.strip()


def commit(home: Path, run: dict, clean_before: bool | None) -> dict:
    """A local commit of what the cycle wrote (cards, generated documents). Never a push."""
    if clean_before is not True:
        return {"committed": False, "reason": "the tree was not clean when the cycle started (or not a git "
                                              "checkout): nothing is committed, so no one's work is swept in"}
    p = _git(["status", "--porcelain=v1", "-uall"], home)
    paths_ = []
    for line in p.stdout.splitlines():
        path = line[3:].split(" -> ")[-1].strip().strip('"')
        if path.startswith(("cards/", "docs/")) or path in ("LAWS.md", "COVERAGE.md", "WEAKNESSES.md"):
            paths_.append(path)
    if not paths_:
        return {"committed": False, "reason": "the cycle changed nothing that is committed"}
    a = _git(["add", "--", *paths_], home)
    if a.returncode != 0:
        return {"committed": False, "reason": f"git add failed: {a.stderr[-400:]}"}
    an = run.get("analysis") or {}
    msg = (f"cardmodel cycle: evidence of {run['started'][:16]} (profile {run['profile']}, seed {run['seed']})\n\n"
           f"Status {run['status']}: " + ", ".join(f"{n} {s}" for s, n in (an.get("counts") or {}).items() if n)
           + f"; {an.get('regressions', 0)} regression(s). Written by `cardmodel cycle run --record --commit`.")
    c = _git(["commit", "-m", msg], home)
    if c.returncode != 0:
        return {"committed": False, "reason": f"git commit failed: {(c.stderr or c.stdout)[-400:]}"}
    head = _git(["rev-parse", "--short", "HEAD"], home).stdout.strip()
    return {"committed": True, "commit": head, "files": len(paths_)}


def run(profile: str | None = None, record: bool = False, record_verdicts: bool = False,
        stages: list[str] | None = None, seed: int | None = None, budget_s: float | None = None,
        commit_changes: bool = False, auto: bool = False, say=None, ctx=None, write: str | None = None) -> dict:
    from ..engines import values as V
    say = say or (lambda m: None)
    ctx = ctx or model_ctx()
    cfg = config(ctx)
    profile = profile or ((cfg.get("auto") or {}).get("profile", "standard") if auto else "standard")
    if profile not in cfg["profiles"]:
        raise ValueError(f"no profile {profile!r} in cycle/default (have {sorted(cfg['profiles'])})")
    prof = cfg["profiles"][profile]
    names = list(stages or prof["stages"])
    unknown = [n for n in names if n not in STAGES]
    if unknown:
        raise ValueError(f"unknown stage(s) {unknown} (have {sorted(STAGES)})")
    home = paths.home()
    state = cycle_dir(ctx)
    os.environ["CARDMODEL_AUTO_CYCLE"] = "0"       # nothing this cycle starts may start another one
    if auto:
        a = (cfg.get("auto") or {})
        last = load_last(state)
        fp = fingerprint(home)
        if last and last.get("fingerprint") == fp and \
                time.time() - _epoch(last.get("finished")) < float(a.get("max_interval_s", 86400)):
            return {"status": "skipped", "reason": "nothing changed since the last cycle", "started": _now()}
    seed = V.fresh_seed() if seed is None else seed
    clean_before = git_clean(home) if commit_changes else None
    info = {"pid": os.getpid(), "home": str(home), "profile": profile, "started": _now(), "host": socket.gethostname()}
    with machine_lock(info):
        prev = load_last(state)
        t0 = time.monotonic()
        started = _now()
        deadline = t0 + float(budget_s or prof.get("budget_s", 1800))
        env = Env(ctx, cfg, profile, seed, record, record_verdicts, deadline, state, say)
        stop = None
        for i, name in enumerate(names, 1):
            if stop or time.monotonic() > deadline - 10:
                env.results[name] = {"status": "skipped", "seconds": 0.0,
                                     "reason": stop or f"budget: {budget_s or prof.get('budget_s')} s were used up",
                                     "summary": stop or "skipped: the budget was used up"}
                continue
            say(f"[{i}/{len(names)}] {name}")
            ts = time.perf_counter()
            limit = min(max(30.0, deadline - time.monotonic()),
                        float((cfg.get("stage_limits_s") or {}).get(name) or 1e9))
            try:
                with deadline_after(limit):
                    res = STAGES[name](env)
            except StageTimeout as exc:
                res = {"status": "error", "error": f"the {name} stage {exc}", "summary": f"stopped: {exc}"}
            except resources.MemoryBudget as exc:
                res = {"status": "error", "error": str(exc), "summary": str(exc)}
                stop = f"stopped after {name}: {exc}"
            except Exception as exc:  # noqa: BLE001 -- one stage failing must not hide the others' evidence
                res = {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:1500],
                       "trace": traceback.format_exc()[-3000:], "summary": f"{type(exc).__name__}: {exc}"[:300]}
            res["seconds"] = round(time.perf_counter() - ts, 2)
            env.results[name] = res
            say(f"      {res.get('status')}: {str(res.get('summary', ''))[:300]}")
        env.restore_verify()
        out = {"started": started, "finished": _now(), "seconds": round(time.monotonic() - t0, 1),
               "profile": profile, "seed": seed, "record": record, "record_verdicts": record_verdicts, "auto": auto,
               "home": str(home), "host": socket.gethostname(), "stages": env.results,
               "peak_memory_mb": round(resources.peak_mb(), 1),
               "shortfalls": {"limits": report.honest_limits(), "roadmap": report.roadmap_open()}}
        an = report.analyse(out, prev, cfg)
        if _settle_regressions_goal(env.results.get("goals"), an["regressions"]):
            an = report.analyse(out, prev, cfg)       # the regressions goal now holds this run's own count
        out["analysis"] = an
        out["status"] = an["status"]
        md = report.markdown(out, an, prev)
        written = list((env.results.get("docs") or {}).get("written") or [])
        if record or write:
            target = Path(write) if write else home / "WEAKNESSES.md"
            target.write_text(md, encoding="utf-8")
            written.append(str(target))
        out["written"] = written
        out["fingerprint"] = fingerprint(home)
        env.note(regressions=an["regressions"], last_status=out["status"], last_started=started)
        if commit_changes:
            out["commit"] = commit(home, out, clean_before) if record else \
                {"committed": False, "reason": "--commit needs --record (only recorded evidence is committed)"}
        _save(state, out, md, cfg)
        _remember(state, out)
    return out


def _settle_regressions_goal(goals: dict | None, regressions: int) -> bool:
    """The goals stage ran before the analysis, so the cycle_regressions goal read the last run's count; give it
    this run's. True when a row changed."""
    changed = False
    for g in (goals or {}).get("goals") or []:
        if g["metric"] == "cycle_regressions" and g["value"] != regressions:
            g["value"] = regressions
            g["met"] = regressions <= g["target"] if g["direction"] == "lower" else regressions >= g["target"]
            changed = True
    if changed:
        rows = goals["goals"]
        goals["met"] = sum(1 for g in rows if g["met"])
        goals["unmet"] = [g["goal"] for g in rows if g["met"] is False]
        goals["unknown"] = [g["goal"] for g in rows if g["met"] is None]
        goals["status"] = "pass" if not goals["unmet"] and not goals["unknown"] else "partial"
        goals["summary"] = (f"{goals['met']} of {len(rows)} goals met; unmet: {', '.join(goals['unmet']) or 'none'}"
                            + (f"; not measured here: {len(goals['unknown'])}" if goals["unknown"] else ""))
    return changed


def _epoch(iso: str | None) -> float:
    if not iso:
        return 0.0
    try:
        return datetime.fromisoformat(iso).timestamp()
    except ValueError:
        return 0.0


def _remember(state: Path, run: dict) -> None:
    """What the hook shows on the next command: the last finished run, in auto.json."""
    p = state / "auto.json"
    try:
        a = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, json.JSONDecodeError):
        a = {}
    an = run.get("analysis") or {}
    a["last_run"] = {"started": run["started"], "finished": run["finished"], "profile": run["profile"],
                     "status": run["status"], "counts": an.get("counts"), "regressions": an.get("regressions"),
                     "auto": run.get("auto")}
    tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(a, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


__all__ = ["Busy", "Env", "StageTimeout", "commit", "config", "cycle_dir", "deadline_after", "fingerprint",
           "git_clean", "load_last", "machine_lock", "model_ctx", "run", "running"]
