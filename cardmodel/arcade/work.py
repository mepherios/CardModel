"""work — the repository's work in progress, for the launcher's WORK tab and for programs built on other branches.

Every git worktree of this repository is a piece of current work (a session's branch). For each: its branch, the
last commit, the commits not on main, what is changed but not committed, which programs and card areas it
touches, and the arcade programs it has (game cards, system cards with a player) with their versions and latest
builds. The store shows each program from the worktree with its newest version; the others are its branches,
installable like a game's betas. A program on another worktree is built there, by that worktree's own
``bin/cardmodel`` (its code, its cards), and served from its state folder.

    GET /api/work                    every worktree: branch, commits, changes, programs, builds

Honest limits (L1): git and the other worktrees are only read (a build there writes only under its state/);
versions are compared as dotted numbers; a branch whose cards are mid-edit may not build, and then its last good
build is what installs.
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
from pathlib import Path

from ..kernel import paths, resources

CACHE_S = 15
_cache: dict = {"at": 0.0, "data": None}
_lock = threading.Lock()


def git(args: list[str], cwd: Path, timeout: int = 20) -> str:
    try:
        p = resources.run(["git", *args], cwd=cwd, timeout=timeout, stdin=subprocess.DEVNULL, heavy=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return p.stdout if p.returncode == 0 else ""


def worktrees() -> list[dict]:
    """[{path, name, branch, head, own}] for the repository the service runs in."""
    home = paths.home()
    out, cur = [], {}
    for line in git(["worktree", "list", "--porcelain"], home).splitlines() + [""]:
        if not line.strip():
            if cur.get("worktree"):
                p = Path(cur["worktree"])
                out.append({"path": str(p), "name": p.name, "branch": cur.get("branch", "").replace("refs/heads/", ""),
                            "head": cur.get("HEAD", "")[:12], "own": p.resolve() == home.resolve()})
            cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v
    return out


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
            depot = latest_manifest(wt, gid)
            out.append({"id": gid, "kind": kind, "card": c, "title": c.get("title", gid), "version": c.get("version", "0"),
                        "build": depot, "changed": f.stat().st_mtime})
    return out


def latest_manifest(wt: Path, gid: str) -> dict | None:
    p = wt / "state" / "arcade" / "depots" / gid / "latest"
    try:
        root = p.parent / p.read_text(encoding="utf-8").strip()
        return json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


AREAS = (("cards/game/", "game"), ("cards/system/", "player"), ("cards/machine/", "machine"), ("cards/hardware/", "hardware"),
         ("cards/isa/", "instruction set"), ("cards/app/", "launcher"), ("cards/law/", "law"), ("cards/", "cards"),
         ("cardmodel/", "engine"), ("tests/", "tests"), ("docs/", "docs"), ("tools/", "tools"))


def areas(files: list[str]) -> list[str]:
    """What a set of changed paths is about: 'game vector_duel', 'machine gameboy', 'engine arcade', ..."""
    seen: dict = {}
    for f in files:
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
            seen[f.split("/")[0]] = seen.get(f.split("/")[0], 0) + 1
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
    progs = programs(p)
    return {**wt, "subject": head[1] if len(head) > 1 else "", "time": int(head[2]) if len(head) > 2 and head[2] else 0,
            "ahead": ahead, "ahead_count": len(git(["rev-list", "main..HEAD"], p).split()),
            "uncommitted": len(status), "uncommitted_files": status[:40], "areas": areas(committed + status),
            "programs": [{k: v for k, v in g.items() if k != "card"} for g in progs]}


def overview(force: bool = False) -> list[dict]:
    with _lock:
        if not force and _cache["data"] is not None and time.time() - _cache["at"] < CACHE_S:
            return _cache["data"]
    data = [describe(w) for w in worktrees()]
    data.sort(key=lambda w: (not w["own"], -max([w["time"]] + [c["time"] for c in w["ahead"][:1]])))
    with _lock:
        _cache.update(at=time.time(), data=data)
    return data


def candidates(gid: str) -> list[dict]:
    """Every worktree that has program gid: [{worktree, path, branch, own, version, card, build}], newest first."""
    out = []
    for w in worktrees():
        for g in programs(Path(w["path"])):
            if g["id"] == gid:
                out.append({"worktree": w["name"], "path": w["path"], "branch": w["branch"], "own": w["own"],
                            "version": g["version"], "card": g["card"], "build": g["build"], "changed": g["changed"]})
    out.sort(key=lambda c: (version_key(c["version"]), c["own"], c["changed"]), reverse=True)
    return out


def all_programs() -> dict[str, list[dict]]:
    ids: list[str] = []
    for w in worktrees():
        for g in programs(Path(w["path"])):
            if g["id"] not in ids:
                ids.append(g["id"])
    return {gid: candidates(gid) for gid in ids}


def worktree_path(name: str) -> Path | None:
    for w in worktrees():
        if w["name"] == name:
            return Path(w["path"])
    return None


def build_elsewhere(path: Path, gid: str, say) -> dict:
    """Build program gid in another worktree with its own bin/cardmodel (its code, its cards); its depot lands in
    that worktree's state folder, where the service serves it from."""
    target = gid[:-len("_player")] if gid.endswith("_player") and (path / "cards" / "system" / gid[:-7]).is_dir() else gid
    say(1, 2, f"building on {path.name} with its own cards")
    p = resources.run([str(path / "bin" / "cardmodel"), "--json", "arcade", "build", target], cwd=path, timeout=900,
                      stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        lines = [x for x in (p.stderr or "").splitlines() if x.strip() and not re.match(r"\[\d+/\d+\]", x.strip())]
        raise RuntimeError("; ".join(lines[-6:])[-1500:] or f"the build exited {p.returncode}")
    say(2, 2, "ready")
    try:
        return json.loads(p.stdout)
    except ValueError:
        m = latest_manifest(path, gid)
        if m is None:
            raise RuntimeError("the build left no depot") from None
        return m


__all__ = ["all_programs", "areas", "build_elsewhere", "candidates", "describe", "latest_manifest", "overview",
           "programs", "version_key", "worktree_path", "worktrees"]
