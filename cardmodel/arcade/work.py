"""work — the repository's work in progress, for the launcher's WORK tab and for programs built on other branches.

Every git worktree of this repository is a piece of current work (a session's branch). For each: its branch, the
last commit, the commits not on main, what is changed but not committed, which programs and card areas it
touches, and the arcade programs it has (game cards, system cards with a player) with their versions and latest
builds. The store shows each program from the service's own checkout; the other worktrees' versions are its
branches, installable like a game's betas. A program on another worktree is built there, by that worktree's own
``bin/cardmodel`` (its code, its cards), and served from its state folder.

    GET /api/work                      every worktree: branch, commits, changes, programs, builds
    GET /api/work/NAME/commit/HASH     one commit: message, author, the files it changed

Whether a branch's program needs a new build is that branch's own answer (``cardmodel arcade list`` run there,
in the background, again whenever its cards, its arcade code or its HEAD change). ``CARDMODEL_BRANCHES=0`` keeps
the service to its own checkout (the tests set it).

Honest limits (L1): git and the other worktrees are only read, without optional locks (a build there writes only
under its state/);
versions are compared as dotted numbers; a branch whose cards are mid-edit may not build, and then its last good
build is what installs.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from ..kernel import paths, resources

CACHE_S = 15
_cache: dict = {"at": 0.0, "data": None, "trees": None, "trees_at": 0.0}
_lock = threading.Lock()
_status: dict[str, dict] = {}          # worktree name -> {"fingerprint", "rows": {id: row}, "error", "at"}
_status_lock = threading.Lock()        # one round of asking the branches at a time
# what a program's build is made of, for noticing that a branch changed (its own `arcade list` decides)
WATCHED = ("cards/game", "cards/system", "cards/platform", "cards/app", "cards/asset", "cards/move", "cards/fighter",
           "cards/payoff", "cards/chain", "cards/machine", "cards/hardware", "cards/isa", "cardmodel/arcade", "stdlib")
HASH = re.compile(r"^[0-9a-f]{4,40}$")        # a commit
SHA256 = re.compile(r"^[0-9a-f]{64}$")       # a chunk


def git(args: list[str], cwd: Path, timeout: int = 20) -> str:
    """A read of a worktree another session uses: without optional locks, so `git status` never rewrites its index
    or takes index.lock (which could make that session's commit fail)."""
    try:
        p = resources.run(["git", "--no-optional-locks", *args], cwd=cwd, timeout=timeout, stdin=subprocess.DEVNULL,
                          heavy=False, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"})
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def worktrees() -> list[dict]:
    """[{path, name, branch, head, own}] for the repository the service runs in (a few seconds' cache)."""
    with _lock:
        if _cache["trees"] is not None and time.time() - _cache["trees_at"] < 5:
            return _cache["trees"]
    home = paths.home()
    out, cur = [], {}
    only_own = os.environ.get("CARDMODEL_BRANCHES") == "0"
    for line in git(["worktree", "list", "--porcelain"], home).splitlines() + [""]:
        if not line.strip():
            if cur.get("worktree") and Path(cur["worktree"]).is_dir():
                p = Path(cur["worktree"])
                own = p.resolve() == home.resolve()
                if own or not only_own:
                    out.append({"path": str(p), "name": p.name, "branch": cur.get("branch", "").replace("refs/heads/", ""),
                                "head": cur.get("HEAD", "")[:12], "own": own})
            cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v
    with _lock:
        _cache.update(trees=out, trees_at=time.time())
    return out


def worktree(name: str) -> dict | None:
    """A worktree by its folder name (the only way a request names one: never a path)."""
    return next((w for w in worktrees() if w["name"] == name), None)


def worktree_path(name: str) -> Path | None:
    w = worktree(name)
    return Path(w["path"]) if w else None


def version_key(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def programs(wt: Path) -> list[dict]:
    """The arcade programs a worktree has: its game cards and its system cards that have a player."""
    out = []
    for reg, kind in (("game", "game"), ("system", "system")):
        for f in sorted((wt / "cards" / reg).glob("*/card.json")):
            try:
                c = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if kind == "system" and not c.get("machine"):
                continue
            gid = c.get("name", f.parent.name) + ("_player" if kind == "system" else "")
            out.append({"id": gid, "kind": kind, "card": c, "title": c.get("title", gid), "version": c.get("version", "0"),
                        "build": latest_manifest(wt, gid), "changed": f.stat().st_mtime})
    return out


def latest_manifest(wt: Path, gid: str) -> dict | None:
    p = wt / "state" / "arcade" / "depots" / gid / "latest"
    try:
        root = p.parent / p.read_text(encoding="utf-8").strip()
        return json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def state_root(name: str) -> Path | None:
    """Where a worktree's builds are (its state/arcade)."""
    p = worktree_path(name)
    return p / "state" / "arcade" if p else None


def find_chunk(sha: str, own: Path) -> Path | None:
    """A chunk by its SHA-256: the service's own store first, then every worktree's (chunks are content-addressed,
    and the launcher checks each one it gets)."""
    for root in [own] + [Path(w["path"]) / "state" / "arcade" for w in worktrees() if not w["own"]]:
        p = root / "chunks" / sha
        if p.is_file():
            return p
    return None


AREAS = (("cards/game/", "game"), ("cards/system/", "player"), ("cards/machine/", "machine"), ("cards/hardware/", "hardware"),
         ("cards/isa/", "instruction set"), ("cards/app/", "launcher"), ("cards/law/", "law"), ("cards/", "cards"),
         ("cardmodel/", "engine"), ("tests/", "tests"), ("docs/", "docs"), ("tools/", "tools"))


def areas(files: list[str]) -> list[str]:
    """What a set of changed paths is about: 'game vector_duel', 'machine gameboy', 'engine arcade', ..."""
    seen: dict = {}
    for f in files:
        if f.startswith("cards/_versions/"):        # version snapshots: bookkeeping, not an area of work
            continue
        for prefix, label in AREAS:
            if f.startswith(prefix):
                rest = f[len(prefix):].split("/")
                name = rest[0] if len(rest) > 1 or prefix == "cards/" else ""
                key = f"{label} {name}".strip() if label not in ("tests", "docs", "tools", "cards") or name else label
                if label == "cards":
                    key = f"cards {rest[0]}" if len(rest) > 1 else "cards"
                seen[key] = seen.get(key, 0) + 1
                break
        else:
            top = "docs" if f.endswith(".md") and "/" not in f else f.split("/")[0]
            seen[top] = seen.get(top, 0) + 1
    return [k for k, _ in sorted(seen.items(), key=lambda kv: -kv[1])][:12]


def describe(wt: dict) -> dict:
    p = Path(wt["path"])
    head = git(["log", "-1", "--format=%H%x1f%s%x1f%ct"], p).strip().split("\x1f")
    ahead = []
    for line in git(["log", "--format=%h%x1f%s%x1f%ct", "-n", "12", "main..HEAD"], p).splitlines():
        h, s, t = (line.split("\x1f") + ["", "", "0"])[:3]
        ahead.append({"hash": h, "subject": s, "time": int(t or 0)})
    status = [ln[3:] for ln in git(["status", "--porcelain", "--untracked-files=normal"], p).splitlines() if len(ln) > 3]
    committed = git(["diff", "--name-only", "main...HEAD"], p).splitlines()
    known = (_status.get(wt["name"]) or {}).get("rows") or {}
    progs = []
    for g in programs(p):
        row = known.get(g["id"]) or {}
        b = g["build"]
        progs.append({"id": g["id"], "kind": g["kind"], "title": g["title"], "version": g["version"],
                      "build": None if not b else {"version": b["version"], "build": b["build"], "size": b.get("size"),
                                                   "created": b.get("created")},
                      "build_due": row.get("build_due") if row else None})
    return {**wt, "subject": head[1] if len(head) > 1 else "", "time": int(head[2]) if len(head) > 2 and head[2] else 0,
            "ahead": ahead, "ahead_count": len(git(["rev-list", "main..HEAD"], p).split()),
            "uncommitted": len(status), "uncommitted_files": status[:60], "areas": areas(committed + status),
            "programs": progs, "status_error": (_status.get(wt["name"]) or {}).get("error")}


def overview(force: bool = False) -> list[dict]:
    with _lock:
        if not force and _cache["data"] is not None and time.time() - _cache["at"] < CACHE_S:
            return _cache["data"]
    refresh_status()
    data = [describe(w) for w in worktrees()]
    data.sort(key=lambda w: (not w["own"], -max([w["time"]] + [c["time"] for c in w["ahead"][:1]])))
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


def commit(name: str, ref: str) -> dict | None:
    """One commit of a worktree's branch: its message, author, time and the files it changed (+/- lines)."""
    p = worktree_path(name)
    if p is None or not HASH.match(ref):
        return None
    head = git(["show", "-s", "--format=%H%x1f%an%x1f%ct%x1f%s%x1f%b", ref], p)
    if not head:
        return None
    h, author, t, subject, body = (head.split("\x1f", 4) + [""] * 5)[:5]
    files = []
    for line in git(["show", "--numstat", "--format=", ref], p).splitlines():
        a, _, rest = line.partition("\t")
        r, _, path = rest.partition("\t")
        if path:
            files.append({"path": path, "added": int(a) if a.isdigit() else None, "removed": int(r) if r.isdigit() else None})
    return {"hash": h, "author": author, "time": int(t or 0), "subject": subject, "body": body.strip(),
            "files": files[:200], "worktree": name, "areas": areas([f["path"] for f in files])}


# -- a branch's own answer: which of its programs need a build -----------------------------------------------------------
def fingerprint(wt: dict) -> str:
    """Changes whenever the branch's HEAD, its build inputs or its builds change."""
    p, mark = Path(wt["path"]), 0.0
    for rel in WATCHED:
        d = p / rel
        if d.is_dir():
            for f in d.rglob("*"):
                try:
                    mark = max(mark, f.stat().st_mtime)
                except OSError:
                    pass
    for f in (p / "state" / "arcade" / "depots").glob("*/latest"):
        try:
            mark = max(mark, f.stat().st_mtime)
        except OSError:
            pass
    return f"{wt['head']}:{mark:.3f}"


def env() -> dict:
    """Another worktree's commands run without starting its self-run cycle (CM38) and against its own checkout."""
    e = {k: v for k, v in os.environ.items() if k not in ("CARDMODEL_HOME", "CARDMODEL_PROJECT", "PYTHONPATH")}
    e["CARDMODEL_SELF"] = "0"
    e["GIT_OPTIONAL_LOCKS"] = "0"
    return e


def ask(wt: Path) -> tuple[dict, str | None]:
    """{program id: {build_due, built, version}} from the branch's own `cardmodel arcade list`."""
    try:
        p = resources.run([str(wt / "bin" / "cardmodel"), "--json", "arcade", "list"], cwd=wt, timeout=120,
                          stdin=subprocess.DEVNULL, env=env())
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {}, f"{type(exc).__name__}: {exc}"
    if p.returncode != 0:
        lines = [x for x in (p.stderr or "").splitlines() if x.strip()]
        return {}, "; ".join(lines[-3:])[-600:] or f"exit {p.returncode}"
    try:
        return {r["id"]: r for r in json.loads(p.stdout)}, None
    except (ValueError, KeyError, TypeError):
        return {}, "its arcade list is not JSON"


def refresh_status(wait: bool = False) -> None:
    """Ask every other worktree that has programs again, when it changed (in the background, one at a time;
    wait=True: now, after any refresh already running)."""
    def run():
        with _status_lock:
            for w in worktrees():
                p = Path(w["path"])
                if w["own"] or not programs(p):
                    continue
                fp = fingerprint(w)
                if (_status.get(w["name"]) or {}).get("fingerprint") == fp:
                    continue
                rows, err = ask(p)
                _status[w["name"]] = {"fingerprint": fp, "rows": rows, "error": err, "at": time.time()}
                with _lock:
                    _cache["data"] = None
    if wait:
        run()
    elif not _status_lock.locked():
        threading.Thread(target=run, daemon=True).start()


def status_row(name: str, gid: str) -> dict | None:
    """What the branch said about program gid, or None while it has not been asked yet."""
    st = _status.get(name)
    if not st:
        return None
    return st["rows"].get(gid) or ({"build_due": None, "error": st["error"]} if st["error"] else None)


def mark_built(name: str, gid: str) -> None:
    """A build on that branch just finished: its program is current until the branch changes again."""
    row = ((_status.get(name) or {}).get("rows") or {}).get(gid)
    if row is not None:
        row["build_due"] = False
    with _lock:
        _cache["data"] = None


def branches(gid: str | None = None) -> dict[str, list[dict]]:
    """{program id: [{worktree, path, branch, version, card, build, changed}]} for every worktree but the
    service's own, newest version first."""
    out: dict[str, list[dict]] = {}
    for w in worktrees():
        if w["own"]:
            continue
        for g in programs(Path(w["path"])):
            if gid is None or g["id"] == gid:
                out.setdefault(g["id"], []).append({"worktree": w["name"], "path": w["path"], "branch": w["branch"],
                                                    "head": w["head"], "version": g["version"], "card": g["card"],
                                                    "build": g["build"], "changed": g["changed"]})
    for v in out.values():
        v.sort(key=lambda c: (version_key(c["version"]), c["changed"]), reverse=True)
    return out


def build_elsewhere(path: Path, gid: str, say, log: Path) -> dict:
    """Build program gid in another worktree with its own bin/cardmodel (its code, its cards); its depot lands in
    that worktree's state folder, where the service serves it from. Its progress lines go to log."""
    target = gid[:-len("_player")] if gid.endswith("_player") and (path / "cards" / "system" / gid[:-7]).is_dir() else gid
    say(0, 6, f"building on {path.name} with its own cards")
    log.parent.mkdir(parents=True, exist_ok=True)
    done = threading.Event()

    def follow():
        seen = ""
        while not done.wait(0.5):
            try:
                lines = re.findall(r"\[(\d+)/(\d+)\] ([^\n]*)", log.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if lines and lines[-1] != seen:
                seen = lines[-1]
                say(int(seen[0]), int(seen[1]), f"{seen[2]} (on {path.name})")
    with open(log, "w", encoding="utf-8") as fh:
        t = threading.Thread(target=follow, daemon=True)
        t.start()
        try:
            p = resources.run([str(path / "bin" / "cardmodel"), "--json", "arcade", "build", target], cwd=path,
                              timeout=900, stdin=subprocess.DEVNULL, stderr=fh, env=env())
        finally:
            done.set()
    if p.returncode != 0:
        text = log.read_text(encoding="utf-8", errors="replace")
        lines = [x for x in text.splitlines() if x.strip() and not re.match(r"\[\d+/\d+\]", x.strip())]
        raise RuntimeError("; ".join(lines[-6:])[-1500:] or f"the build exited {p.returncode}")
    try:
        return json.loads(p.stdout)
    except ValueError:
        m = latest_manifest(path, gid)
        if m is None:
            raise RuntimeError("the build left no depot") from None
        return m


__all__ = ["areas", "branches", "build_elsewhere", "commit", "describe", "find_chunk", "fingerprint", "mark_built",
           "latest_manifest", "overview", "programs", "refresh_status", "state_root", "status_row", "version_key",
           "worktree", "worktree_path", "worktrees"]
