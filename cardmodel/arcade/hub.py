"""hub — the store's live view of everything in progress: project cards, their status computed from git and from
the model's own records, an activity feed and early-access builds, pushed to the launcher's pages as they change.

A ``project`` card (cards/project) names what to watch: ``repo`` (another folder, read-only; this repository when
absent), ``paths`` (what in the repository belongs to the project: a folder, a file, or a glob), ``games`` (games
whose builds belong to it), ``metrics`` and ``docs``. Nothing on the card says how far along the project is:

  detail     what the owning session keeps on the card (law CM41, engines/projects.py): goal, standing, done / in
             progress / left, blockers, next steps, the user's actions, owner, when it was revised, and whether
             the card is stale; every user action, gathered and ranked by what it unblocks
  status     the last commit on the main branch that touches the project's paths; branches with unmerged commits
             touching them (ahead / behind main, last commit, the worktree they are checked out in); uncommitted
             changes under its paths in every worktree (how many files, the newest change); its phase: active now
             (a change in the last 15 minutes), active today, in development (commits this week or open branches),
             dormant, or not on this machine; its metrics; its builds
  metrics    a goal (evaluated against each checkout's own records; main's value first, else the newest), a
             verify section (the newest record holding it), a state value (the newest record), a card count, a
             count of committed files in the project's repository, or the last self-run
  activity   commits and merges in every repository watched (7 days), verify runs, self-run cycles, new builds
  early      early access is the store's branch versions (arcade/work.py): a program's version on a branch with
             unmerged work, when it is not older than the release and not the release's own build. It is built on
             that branch by its own code and installed from the program's store page like a beta: one mechanism.
             The hub only lists them.
  live       a watcher thread compares, every 2 s, the modification times of the git refs, HEADs and logs and of the
             records and depots it reads; when anything moved it recomputes and pushes the snapshot to every page
             listening on /api/events (server-sent events). Uncommitted changes are re-read every 60 s in this
             repository's worktrees and every 5 minutes (tracked files only) in the other repositories.

Read-only by construction: git runs with --no-optional-locks (``status`` then never refreshes an index, so it never
holds a lock a session's commit could trip over) and only log, status, rev-list, for-each-ref, ls-files and worktree
list; files are read, never written. Other repositories (Ting, rea-cards, the AnyPS5 copy) are read the same way.

Honest limits (L1): "active now" means files changed in a worktree in the last 15 minutes, not that someone is at
work; a metric is only as fresh as the record a checkout last wrote, and says which checkout and when; the feed is
git history plus the records the model keeps, not a log of everything that happened.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from ..kernel import paths, resources

POLL_S = 2.0
DIRTY_EVERY_S = 60.0              # this repository's worktrees
DIRTY_OTHER_EVERY_S = 300.0       # other repositories (tracked files only: their untracked trees can be large)
ACTIVE_NOW_S = 15 * 60
ACTIVE_DAY_S = 24 * 3600
RECENT_DAYS = 7
FEED = 120
STATE_FILES = ("last_verify.json", "emu_survey.json", "emu_testroms.json", "nds_coverage.json", "emu_diffs.json")


# -- reading git, read-only ---------------------------------------------------------------------------------------
def git(repo: Path, *args: str, timeout: float = 30) -> str | None:
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C", GIT_TERMINAL_PROMPT="0")
    try:
        p = resources.run(["git", "--no-optional-locks", "-C", str(repo), *args], timeout=timeout, heavy=False,
                          env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return p.stdout if p.returncode == 0 else None


def _commits(repo: Path, rev: str, since_days: int | None = None, merges: bool = True,
             first_parent: bool = False, limit: int = 300) -> list[dict]:
    args = ["log", f"--max-count={limit}", "--format=%x1e%H%x1f%ct%x1f%an%x1f%s%x1f%P", "--name-only"]
    if since_days:
        args.append(f"--since={since_days}.days")
    if not merges:
        args.append("--no-merges")
    if first_parent:
        args += ["--first-parent", "-m"]
    out = git(repo, *args, rev, "--")
    rows = []
    for rec in (out or "").split("\x1e")[1:]:
        lines = rec.strip("\n").split("\n")
        h, t, who, title, parents = (lines[0].split("\x1f") + [""] * 5)[:5]
        rows.append({"hash": h, "t": int(t or 0), "who": who, "title": title, "parents": len(parents.split()),
                     "files": [x for x in lines[1:] if x]})
    return rows


def match(path: str, patterns: list[str]) -> bool:
    """A file belongs to a project when it is one of its paths, under one of its folders, or matches its glob."""
    if not patterns:
        return True
    for p in patterns:
        if any(ch in p for ch in "*?["):
            if fnmatch.fnmatch(path, p):
                return True
        elif path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/"):
            return True
    return False


def _pathspecs(patterns: list[str]) -> list[str]:
    return [f":(glob){p}" if any(ch in p for ch in "*?[") else p for p in patterns]


def _ts(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    for parse in (datetime.fromisoformat, lambda s: datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")):
        try:
            d = parse(str(value))
            return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError:
            continue
    return None


def _version(v) -> tuple:
    """Dotted versions compare as numbers; no version sorts first."""
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return ()


def _read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# -- one scan of a repository ---------------------------------------------------------------------------------------
class RepoScan:
    """What git says about one repository now: its main branch, worktrees, other branches and recent commits."""

    def __init__(self, root: Path, label: str, own: bool):
        self.root, self.label, self.own = root, label, own
        self.ok = (root / ".git").exists() and git(root, "rev-parse", "--git-dir") is not None
        self.main = None
        self.worktrees: list[dict] = []
        self.branches: list[dict] = []
        self.main_commits: list[dict] = []
        if not self.ok:
            return
        if own:
            self.main = "main" if git(root, "rev-parse", "--verify", "--quiet", "refs/heads/main") else None
        self.main = self.main or (git(root, "rev-parse", "--abbrev-ref", "HEAD") or "HEAD").strip()
        self.main_commits = _commits(root, self.main, RECENT_DAYS, first_parent=True)
        for block in (git(root, "worktree", "list", "--porcelain") or "").split("\n\n"):
            info = dict(line.split(" ", 1) for line in block.splitlines() if " " in line)
            if "worktree" in info:
                wpath = Path(info["worktree"])
                self.worktrees.append({"path": wpath, "name": wpath.name if wpath != root else "main",
                                       "branch": info.get("branch", "").replace("refs/heads/", "") or "(detached)",
                                       "dirty": []})
        cut = time.time() - 30 * 86400
        refs = git(root, "for-each-ref", "--format=%(refname:short)%1f%(committerdate:unix)", "refs/heads") or ""
        for line in refs.splitlines():
            name, _, t = line.partition("\x1f")
            if name == self.main or not t or int(t) < cut:
                continue
            counts = (git(root, "rev-list", "--left-right", "--count", f"{self.main}...{name}") or "0\t0").split()
            behind, ahead = (int(counts[0]), int(counts[1])) if len(counts) == 2 else (0, 0)
            wt = next((w["name"] for w in self.worktrees if w["branch"] == name), None)
            self.branches.append({"name": name, "t": int(t), "ahead": ahead, "behind": behind, "worktree": wt,
                                  "commits": _commits(root, f"{self.main}..{name}", merges=False) if ahead else []})
            if len(self.branches) >= 16:
                break

    def last_touch(self, patterns: list[str]) -> dict | None:
        out = git(self.root, "log", "-1", "--format=%H%x1f%ct%x1f%an%x1f%s", self.main, "--", *_pathspecs(patterns))
        if not out or not out.strip():
            return None
        h, t, who, title = (out.strip().split("\x1f") + [""] * 4)[:4]
        return {"hash": h, "t": int(t or 0), "who": who, "title": title}


def scan_dirty(worktree: dict, untracked: bool = True) -> list[dict]:
    out = git(worktree["path"], "status", "--porcelain=v1", "-z",
              "--untracked-files=normal" if untracked else "--untracked-files=no")
    files = []
    parts = (out or "").split("\0")
    i = 0
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        code, rel = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            i += 1                                     # a rename carries its old path next
        try:
            mtime = (worktree["path"] / rel).stat().st_mtime
        except OSError:
            mtime = None
        files.append({"path": rel.rstrip("/"), "code": code.strip(), "mtime": mtime})
    return files


# -- the snapshot ---------------------------------------------------------------------------------------------------
class Checkout:
    """A checkout of this repository and the records it keeps (state/)."""

    def __init__(self, name: str, path: Path, branch: str):
        self.name, self.path, self.branch = name, path, branch
        self.state = path / "state"

    def load_state(self, name: str, default=None):
        d = _read(self.state / f"{name}.json")
        return default if d is None else d

    def mtime(self, rel: str) -> float:
        try:
            return (self.state / rel).stat().st_mtime
        except OSError:
            return 0.0


class _View:
    """What coverage's goal metrics read (``store``, ``load_state``), pointed at one checkout's records."""

    def __init__(self, ctx, co: Checkout):
        self.store, self.ops, self._co = ctx.store, ctx.ops, co

    def load_state(self, name, default=None):
        return self._co.load_state(name, default)


def _dig(data, path: str):
    """'a.b.c' into nested dicts; '*' sums over a dict's values (numbers only)."""
    cur = [data]
    for part in path.split("."):
        nxt = []
        for c in cur:
            if not isinstance(c, dict):
                continue
            nxt += list(c.values()) if part == "*" else ([c[part]] if part in c else [])
        cur = nxt
    if len(cur) == 1:
        return cur[0]
    nums = [c for c in cur if isinstance(c, (int, float)) and not isinstance(c, bool)]
    return sum(nums) if nums else None


def _fmt(template: str, data: dict) -> str | None:
    try:
        return template.format(**{k: v for k, v in data.items() if not isinstance(v, (dict, list))})
    except (KeyError, IndexError, ValueError):
        return None


class Snapshot:
    def __init__(self, ctx, dirty: dict[str, list[dict]]):
        self.ctx = ctx
        home = paths.home()
        self.repos: dict[str, RepoScan] = {"": RepoScan(home, "cardmodel", own=True)}
        own = self.repos[""]
        for wt in own.worktrees:
            wt["dirty"] = dirty.get(str(wt["path"]), [])
        self.checkouts = [Checkout(w["name"], w["path"], w["branch"]) for w in own.worktrees] or \
            [Checkout("main", home, own.main or "main")]
        self.checkouts.sort(key=lambda c: c.name != "main")
        for card in ctx.store.cards("project"):
            if card.get("repo"):
                root = Path(os.path.expanduser(card["repo"]))
                key = str(root)
                if key not in self.repos:
                    self.repos[key] = RepoScan(root, root.name, own=False)
                    for wt in self.repos[key].worktrees:
                        wt["dirty"] = dirty.get(str(wt["path"]), [])

    # metrics ----------------------------------------------------------------------------------------------------
    def _newest(self, have) -> Checkout | None:
        cands = [c for c in self.checkouts if have(c)]
        return max(cands, key=lambda c: c.mtime("last_verify.json")) if cands else None

    def metric(self, spec: dict, repo: RepoScan | None) -> dict:
        from ..engines import coverage
        label = spec.get("label") or spec.get("goal") or spec.get("verify") or spec.get("state") or spec.get("cards")
        out = {"label": label, "value": None}
        if "goal" in spec:
            g = self.ctx.store.get(f"goal/{spec['goal']}")
            if g is None:
                return {**out, "note": "no such goal"}
            for co in self.checkouts:                   # main first, then the other checkouts
                lv = co.load_state("last_verify") or {}
                val = coverage._metric(_View(self.ctx, co), g["metric"], {"peak_memory_mb": lv.get("peak_memory_mb")},
                                       lv.get("sections") or {})
                if val is not None:
                    met = val >= g["target"] if g["direction"] == "higher" else val <= g["target"]
                    return {**out, "value": val, "target": g["target"], "direction": g["direction"], "met": met,
                            "where": co.name, "goal": g.name}
            return {**out, "target": g["target"], "direction": g["direction"], "goal": g.name, "note": "not measured yet"}
        if "verify" in spec:
            sec = spec["verify"]
            co = self._newest(lambda c: sec == "*" and c.load_state("last_verify") or
                              ((c.load_state("last_verify") or {}).get("sections") or {}).get(sec))
            if co is None:
                return {**out, "note": "no verify record yet"}
            lv = co.load_state("last_verify")
            at = lv.get("started")
            if sec == "*":
                secs = lv.get("sections") or {}
                bad = sorted(s for s, r in secs.items() if r.get("status") == "fail")
                return {**out, "value": f"{lv.get('status')}: {len(secs) - len(bad)}/{len(secs)} sections pass",
                        "met": not bad, "where": co.name, "at": at}
            r = lv["sections"][sec]
            return {**out, "value": _fmt(spec.get("format", "{status}"), r) or r.get("status"),
                    "met": r.get("status") == "pass", "where": co.name, "at": at}
        if "state" in spec:
            rel = f"{spec['state']}.json"
            co = max((c for c in self.checkouts if c.mtime(rel)), key=lambda c: c.mtime(rel), default=None)
            if co is None:
                return {**out, "note": "not measured on this machine yet"}
            data = co.load_state(spec["state"]) or {}
            if "format" in spec:
                val = _fmt(spec["format"], data)
            else:
                val = _dig(data, spec.get("sum") or spec.get("path") or "")
            return {**out, "value": val, "where": co.name,
                    "at": datetime.fromtimestamp(co.mtime(rel), timezone.utc).isoformat(timespec="seconds")}
        if "cards" in spec:
            cards = self.ctx.store.cards(spec["cards"])
            if spec.get("match"):
                cards = [c for c in cards if fnmatch.fnmatch(c.name, spec["match"])]
            return {**out, "value": len(cards)}
        if "git_files" in spec:
            if repo is None or not repo.ok:
                return {**out, "note": "repository not on this machine"}
            listed = git(repo.root, "ls-files", "--", spec["git_files"] or ".") or ""
            files = [f for f in listed.splitlines() if f]
            if spec.get("count") == "dirs":
                pre = spec["git_files"]
                files = {f[len(pre):].split("/", 1)[0] for f in files if "/" in f[len(pre):]}
            return {**out, "value": len(files), "where": repo.label}
        if "self" in spec:
            last = _read(paths.home() / "state" / "self" / "last.json")
            if not last:
                return {**out, "note": "no self-run yet (cardmodel self run)"}
            top = (last.get("plan") or [{}])[0]
            return {**out, "value": f"{last.get('status')}; next: {top.get('what', 'nothing')}",
                    "met": last.get("status") == "pass", "at": last.get("finished")}
        return {**out, "note": "unknown metric"}

    # builds -----------------------------------------------------------------------------------------------------
    def releases(self) -> dict[str, dict]:
        from . import build as B
        out = {}
        for card in self.ctx.store.cards("game"):
            root = B.latest(self.ctx, card.name)
            m = _read(root / "manifest.json") if root else None
            if m:
                out[card.name] = {"id": card.name, "title": m.get("title"), "version": m.get("version"),
                                  "build": m.get("build"), "created": m.get("created"), "channel": "release"}
        return out

    def early(self) -> list[dict]:
        """Every program's versions on branches with unmerged work (work.branches) that differ from the program
        here: a newer version, or the same version where the branch changed the program's own card (committed or
        not). An older version, or one a branch only inherited, is not early access."""
        from . import work as W
        rel = self.releases()
        own = self.repos[""]
        info = {b["name"]: b for b in own.branches}
        dirty = {wt["name"]: wt["dirty"] for wt in own.worktrees}
        here = {g["id"]: g["version"] for g in W.programs(paths.home())}
        out = []
        for gid, versions in W.branches().items():
            r = rel.get(gid) or {}
            base = r.get("version") or here.get(gid)
            for v in versions:
                b = info.get(v["branch"])
                if not b or not b["ahead"]:
                    continue
                card = v.get("card") or {}
                if base is not None and W.version_key(v["version"]) <= W.version_key(base):
                    if W.version_key(v["version"]) < W.version_key(base):
                        continue
                    where = f"cards/{'system' if gid.endswith('_player') else 'game'}/{card.get('name', gid)}/"
                    if not (any(f.startswith(where) for c in b["commits"] for f in c["files"])
                            or any(f["path"].startswith(where) for f in dirty.get(v["worktree"], []))):
                        continue
                bd = v.get("build") or {}
                out.append({"game": gid, "title": card.get("title") or gid, "version": v["version"],
                            "branch": v["branch"], "worktree": v["worktree"], "channel": "early access",
                            "release": r.get("version"), "build": bd.get("build"), "created": bd.get("created"),
                            "size": bd.get("size")})
        return sorted(out, key=lambda e: (e["game"], str(e.get("created"))), reverse=True)

    # projects ---------------------------------------------------------------------------------------------------
    def project(self, card, early: list[dict], releases: dict, now: float) -> dict:
        repo = self.repos.get(str(Path(os.path.expanduser(card["repo"]))) if card.get("repo") else "")
        out = {"id": card.name, "title": card["title"], "kind": card["kind"], "statement": card.get("statement", ""),
               "docs": card.get("docs") or [], "repo": repo.label if repo else card.get("repo"),
               "order": card.get("order", 999)}
        if repo is None or not repo.ok:
            return {**out, "phase": "not on this machine", "metrics": [], "branches": [], "changes": [],
                    "builds": [], "last": None, "recent": 0}
        pats = card.get("paths") or []
        mine = [c for c in repo.main_commits if not pats or any(match(f, pats) for f in c["files"])]
        last = mine[0] if mine else repo.last_touch(pats)
        branches = []
        for b in repo.branches:
            own = [c for c in b["commits"] if not pats or any(match(f, pats) for f in c["files"])]
            if own:
                branches.append({"branch": b["name"], "worktree": b["worktree"], "ahead": b["ahead"],
                                 "behind": b["behind"], "commits": len(own), "last": {k: own[0][k] for k in
                                                                                      ("hash", "t", "who", "title")}})
        changes = []
        for wt in repo.worktrees:
            files = [f for f in wt["dirty"] if match(f["path"], pats)]
            if files:
                times = [f["mtime"] for f in files if f["mtime"]]
                changes.append({"worktree": wt["name"], "branch": wt["branch"], "files": len(files),
                                "newest": max(times) if times else None, "sample": [f["path"] for f in files[:6]]})
        stamps = [last["t"] if last else 0] + [b["last"]["t"] for b in branches] + \
            [c["newest"] or 0 for c in changes]
        newest = max(stamps) if stamps else 0
        if newest and now - newest <= ACTIVE_NOW_S:
            phase = "active now"
        elif newest and now - newest <= ACTIVE_DAY_S:
            phase = "active today"
        elif (newest and now - newest <= RECENT_DAYS * 86400) or branches:
            phase = "in development"
        elif last is None and not pats:
            phase = "no commits yet"
        elif last is None:
            phase = "not started here"
        else:
            phase = "dormant"
        builds = [releases[g] for g in card.get("games") or [] if g in releases] + \
            [e for e in early if e["game"] in (card.get("games") or [])]
        return {**out, "phase": phase, "newest": newest or None, "recent": len(mine),
                "last": {k: last[k] for k in ("hash", "t", "who", "title")} if last else None,
                "branches": branches, "changes": changes, "builds": builds,
                "metrics": [self.metric(m, repo) for m in card.get("metrics") or []]}

    def activity(self) -> list[dict]:
        seen, ev = set(), []
        for repo in self.repos.values():
            if not repo.ok:
                continue
            for c in repo.main_commits:
                seen.add(c["hash"])
                ev.append({"t": c["t"], "kind": "merge" if c["parents"] > 1 else "commit", "repo": repo.label,
                           "branch": repo.main, "title": c["title"], "who": c["who"], "hash": c["hash"][:9]})
            for b in repo.branches:
                for c in b["commits"]:
                    if c["hash"] in seen or c["t"] < time.time() - RECENT_DAYS * 86400:
                        continue
                    seen.add(c["hash"])
                    ev.append({"t": c["t"], "kind": "commit", "repo": repo.label, "branch": b["name"],
                               "title": c["title"], "who": c["who"], "hash": c["hash"][:9]})
        for co in self.checkouts:
            lv = co.load_state("last_verify")
            if lv and _ts(lv.get("started")):
                secs = lv.get("sections") or {}
                bad = sum(1 for r in secs.values() if r.get("status") == "fail")
                ev.append({"t": _ts(lv["started"]), "kind": "verify", "repo": "cardmodel", "branch": co.branch,
                           "title": f"verify {lv.get('status')}: {len(secs) - bad}/{len(secs)} sections pass"
                                    + (f" (seed {lv.get('seed')})" if lv.get("seed") else ""), "who": co.name})
            depots = co.state / "arcade" / "depots"
            for man in sorted(depots.glob("*/*/manifest.json")) if depots.is_dir() else []:
                m = _read(man)
                if m and _ts(m.get("created")):
                    ev.append({"t": _ts(m["created"]), "kind": "build", "repo": "cardmodel", "branch": co.branch,
                               "title": f"{m.get('title')} {m.get('version')} build {m.get('build')}", "who": co.name})
        for run in sorted((paths.home() / "state" / "self" / "runs").glob("*.json"))[-10:]:
            r = _read(run) or {}
            if _ts(r.get("finished")):
                top = (r.get("plan") or [{}])[0]
                ev.append({"t": _ts(r["finished"]), "kind": "self-run", "repo": "cardmodel", "branch": "main",
                           "title": f"self-run {r.get('status')}" + (f"; next: {top['what']}" if top.get("what") else ""),
                           "who": "auto" if r.get("auto") else "manual"})
        ev = [e for e in ev if e["t"] and e["t"] >= time.time() - RECENT_DAYS * 86400]
        return sorted(ev, key=lambda e: e["t"], reverse=True)[:FEED]

    def compute(self) -> dict:
        from ..engines import projects as PJ
        now = time.time()
        early, releases = self.early(), self.releases()
        checked = PJ.check(self.ctx, now)
        projects = []
        for c in self.ctx.store.cards("project"):
            row = self.project(c, early, releases, now)
            d = PJ.detail(c)
            row["detail"] = {k: d.get(k) for k in ("goal", "standing", "done", "in_progress", "left", "blockers",
                                                   "next_steps", "user_actions", "owner", "updated", "source")}
            row["card"] = checked["projects"].get(c.name, {})
            projects.append(row)
        projects.sort(key=lambda p: ({"game": 0, "program": 1, "research": 2}.get(p["kind"], 3), p["order"]))
        return {"generated": now, "projects": projects, "activity": self.activity(), "early": early,
                "waiting_on_you": PJ.waiting_on_you(self.ctx), "card_problems": checked["problems"],
                "releases": list(releases.values()),
                "repos": [{"label": r.label, "path": str(r.root), "ok": r.ok, "main": r.main,
                           "worktrees": [{"name": w["name"], "branch": w["branch"], "dirty": len(w["dirty"])}
                                         for w in r.worktrees]} for r in self.repos.values()]}


# -- the live hub ---------------------------------------------------------------------------------------------------
class Hub:
    def __init__(self, ctx):
        self.ctx = ctx
        self.cond = threading.Condition()
        self.version = 0
        self.snapshot: dict | None = None
        self.sig = None
        self.dirty: dict[str, list[dict]] = {}
        self.dirty_at = 0.0
        self.others_at = 0.0
        self.errors: list[str] = []
        self.thread: threading.Thread | None = None
        self.stop = threading.Event()
        self.lock = threading.Lock()

    def _repo_roots(self) -> list[Path]:
        roots = [paths.home()]
        for card in self.ctx.store.cards("project"):
            if card.get("repo"):
                roots.append(Path(os.path.expanduser(card["repo"])))
        return roots

    def signature(self) -> tuple:
        """File times only: the git refs, HEADs and logs of every repository and worktree, the records and depots."""
        files: list[Path] = []
        for root in self._repo_roots():
            g = root / ".git"
            if not g.is_dir():
                continue
            files += [g / "HEAD", g / "packed-refs", g / "logs" / "HEAD"]
            files += [p for p in (g / "refs" / "heads").rglob("*")]
            for w in (g / "worktrees").glob("*") if (g / "worktrees").is_dir() else []:
                files += [w / "HEAD", w / "logs" / "HEAD"]
        for co_root in [paths.home(), *sorted((paths.home() / ".claude" / "worktrees").glob("*"))]:
            st = co_root / "state"
            files += [st / f for f in STATE_FILES] + [st / "self" / "last.json"]
            files += list((st / "arcade" / "depots").glob("*/latest"))
        files += list((paths.home() / "cards" / "project").rglob("card.json"))
        files += [r / ".cardmodel" / "project.json" for r in self._repo_roots()]
        out = []
        for f in files:
            try:
                out.append((str(f), f.stat().st_mtime_ns))
            except OSError:
                out.append((str(f), 0))
        return tuple(sorted(out))

    def _scan_dirty(self) -> bool:
        before = {k: [(f["path"], f["mtime"]) for f in v] for k, v in self.dirty.items()}
        now = time.monotonic()
        others_due = now - self.others_at >= DIRTY_OTHER_EVERY_S
        new = {}
        for root in self._repo_roots():
            if not (root / ".git").exists():
                continue
            own = root == paths.home()
            for block in (git(root, "worktree", "list", "--porcelain") or "").split("\n\n"):
                line = next((x for x in block.splitlines() if x.startswith("worktree ")), None)
                if not line:
                    continue
                wp = Path(line.split(" ", 1)[1])
                if own or others_due or str(wp) not in self.dirty:
                    new[str(wp)] = scan_dirty({"path": wp}, untracked=own)
                else:
                    new[str(wp)] = self.dirty[str(wp)]
        if others_due:
            self.others_at = now
        self.dirty = new
        self.dirty_at = now
        return before != {k: [(f["path"], f["mtime"]) for f in v] for k, v in new.items()}

    def refresh(self, force: bool = False, dirty: bool = False) -> bool:
        with self.lock:
            sig = self.signature()
            moved = dirty and self._scan_dirty()
            if not (force or moved or sig != self.sig):
                return False
            if force and not self.dirty_at:
                self._scan_dirty()
            self.ctx.store.invalidate()                  # a session may have revised its project card (CM41)
            snap = Snapshot(self.ctx, self.dirty).compute()
            self.sig = sig
            with self.cond:
                self.version += 1
                snap["version"] = self.version
                self.snapshot = snap
                self.cond.notify_all()
            return True

    def _loop(self) -> None:
        while not self.stop.wait(POLL_S):
            try:
                self.refresh(dirty=time.monotonic() - self.dirty_at >= DIRTY_EVERY_S)
            except Exception as exc:  # noqa: BLE001 -- a bad moment (a branch mid-rewrite) must not stop the hub
                self.errors = (self.errors + [f"{type(exc).__name__}: {exc}"])[-5:]

    def start(self) -> "Hub":
        if self.thread is None:
            self.refresh(force=True)
            self.thread = threading.Thread(target=self._loop, name="arcade-hub", daemon=True)
            self.thread.start()
        return self

    def current(self) -> dict:
        return {**(self.snapshot or {}), "errors": self.errors}

    def wait(self, seen: int, timeout: float) -> dict | None:
        with self.cond:
            if self.version <= seen:
                self.cond.wait(timeout)
            return self.current() if self.version > seen else None


_HUB: Hub | None = None
_HUB_LOCK = threading.Lock()


def get(ctx) -> Hub:
    global _HUB
    with _HUB_LOCK:
        if _HUB is None:
            _HUB = Hub(ctx).start()
        return _HUB


def events(handler, hub: Hub) -> None:
    """Server-sent events: the snapshot now, then again every time it changes; a comment every 15 s keeps it open."""
    handler.send_response(200)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    seen = -1
    try:
        while True:
            snap = hub.wait(seen, timeout=15.0)
            if snap is None:
                handler.wfile.write(b": still here\n\n")
            else:
                seen = snap["version"]
                handler.wfile.write(f"event: hub\nid: {seen}\ndata: {json.dumps(snap)}\n\n".encode())
            handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError, OSError):
        return


def route(handler, parts: list[str], query: dict) -> bool:
    """The hub's part of the service; True when it answered."""
    if parts == ["api", "events"]:
        events(handler, get(handler.ctx))
        return True
    if parts == ["api", "dev"]:
        handler._json(get(handler.ctx).current())
        return True
    return False


__all__ = ["Hub", "RepoScan", "Snapshot", "get", "git", "match", "route", "scan_dirty"]
