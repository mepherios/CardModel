"""server — the arcade's content service (stdlib HTTP): what the launcher's Store, Library and Downloads read.

    GET  /api/catalog                    every game card: its data, its latest build, whether a new build is due
    GET  /api/game/ID                    one game in full (about, versions, achievements, media, build)
    POST /api/build/ID                   build the game from its cards now (in the background)
    GET  /api/build/ID                   that build's progress: state, step, of, label, error
    GET  /depot/ID/BUILD/manifest.json   a build's files and chunks
    GET  /chunk/SHA256[?rate=B]          one chunk (content-addressed), at most B bytes a second when asked
    GET  /media/ID/BUILD/FILE            store and library pictures (drawn by the game)
    GET  /ui/...                         the launcher's pages (the app card's ui folder)
    GET  /api/status                     alive, and ``ui``: a hash of those pages (a page that sees it change reloads)
    GET  /api/library, /api/cover/ID.png, POST /api/library/scan   the user's cartridges (library.py)
    GET  /api/work, /api/work/NAME/commit/HASH                     every session's branch (work.py)
    GET  /api/dev                        everything in progress: projects, activity, branch versions (hub.py)
    GET  /api/events                     the same, pushed as server-sent events whenever it changes (hub.py)
    GET  /api/cartridge/ID               a listed cartridge's file (an iPhone plays it; X-Cartridge-File names it)
    POST /api/pair, POST /api/pair/code  a device on the local network pairs with a code this Mac shows (pairing.py)

Every program builds for any platform card (build.py): ``?platform=KEY`` on /api/catalog, /api/game and
/api/build (``ios``, ``ios-iphonesimulator``), or ``CardmodelPlatform/KEY`` in the client's User-Agent (the iOS
launcher's pages), means that platform's builds; without it, each program's own. Branch versions are for a
program's own platform only.

A system card (a console's player, system.py) is in the catalog like a game, under its arcade id. Every program
also lists its versions on the repository's other worktrees (``branches``), and a program that only a branch has
is in the catalog with that branch as its ``worktree``. ``?branch=NAME`` on /api/game and /api/build, and
``?wt=NAME`` on /depot and /media, mean that worktree's version: it is built there by its own ``bin/cardmodel``
and served from its state folder; a chunk is found in whichever store has it.

A build is due when the hash of the game's sources (its cards, its logic, the platform shell, the arcade build
code) differs from the latest build's. The service only reads the cards and writes under state/arcade.

Honest limits (L1): unauthenticated on 127.0.0.1 (this Mac); on the local network only paired devices, over plain
HTTP; one build at a time per game and platform; card changes are seen through file times, code changes need a
restart of the service.
"""
from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import build as B
from . import game as G
from . import library as L
from . import pairing as P
from . import system as S
from . import work as W

_builds: dict[str, dict] = {}
_lock = threading.Lock()
_elock = threading.Lock()
_seen = {"mark": None}
WATCH = ("game", "system", "platform", "app", "asset", "move", "fighter", "payoff", "machine", "hardware", "isa")


def ui_hash(ui_dir: Path | None) -> str:
    """A hash of the launcher's pages as served now: an open page compares it with the one it loaded under, so a
    reinstalled launcher or a service restarted from another checkout never leaves old pages on screen."""
    if ui_dir is None or not ui_dir.is_dir():
        return ""
    h = hashlib.sha256()
    for f in sorted(ui_dir.rglob("*")):
        if f.is_file():
            st = f.stat()
            h.update(f"{f.relative_to(ui_dir)}|{st.st_size}|{st.st_mtime_ns}".encode())
    return h.hexdigest()[:16]


def fresh(ctx) -> None:
    """Re-read the cards when any card a game is built from changed on disk (a new version, new logic)."""
    from ..kernel import paths
    mark = 0.0
    for reg in WATCH:
        d = paths.home() / "cards" / reg
        if d.is_dir():
            for f in d.rglob("*"):
                try:
                    mark = max(mark, f.stat().st_mtime)
                except OSError:
                    pass
    if _seen["mark"] is not None and mark != _seen["mark"]:
        ctx.store.invalidate()
    _seen["mark"] = mark


def latest_info(ctx, gid: str, platform: str | None = None) -> dict | None:
    root = B.latest(ctx, gid, platform)
    if root is None:
        return None
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


UA_PLATFORM = re.compile(r"CardmodelPlatform/([A-Za-z0-9_.-]+)")


def requested_platform(handler, q: dict) -> str | None:
    """The platform a client asks for: ?platform=KEY, else CardmodelPlatform/KEY in its User-Agent."""
    p = (q.get("platform") or [""])[0]
    if not p:
        m = UA_PLATFORM.search(handler.headers.get("User-Agent") or "")
        p = m.group(1) if m else ""
    return p or None


def build_key(gid: str, platform: str | None) -> str:
    """A build's key in the service's progress and error records: the program, and the platform when not its own."""
    return gid if platform is None else f"{gid}#{platform}"


def card_for(ctx, gid: str):
    """The game or system card behind an arcade id."""
    if S.is_system(ctx.store, gid):
        return S.system_card(ctx.store, gid)
    return G.game_card(ctx.store, gid)


def _entry(gid: str, kind: str, system: str | None, card, info: dict | None, wt: str | None, *, build_due,
           building: bool, error: str | None, full: bool) -> dict:
    """A program as the launcher sees it, from its card (a store card or a branch's card.json) and its latest
    build; wt names the worktree its builds are served from (None: the service's own)."""
    q = f"?wt={wt}" if wt else ""
    build_dir = f"{info['version']}+{info['build']}" if info else None
    media = {}
    if info:
        media = {m.rsplit(".", 1)[0]: f"/media/{gid}/{build_dir}/{m}{q}" for m in info.get("media", [])}
    out = {
        "id": gid, "kind": kind, "system": system, "controls": card.get("controls"),
        "input": {k: (card.get("input") or {}).get(k) for k in ("bits", "keys", "keys2", "gamepad")}
                 if card.get("input") else None,
        "title": card.get("title", gid), "version": card.get("version", "0"), "developer": card.get("developer"),
        "genre": card.get("genre", []), "tags": card.get("tags", []),
        "short_description": card.get("short_description", ""),
        "achievements": card.get("achievements", []),
        "changelog": card.get("changelog", []),
        "build": None if not info else {
            "version": info["version"], "build": info["build"], "size": info["size"], "created": info["created"],
            "manifest": f"/depot/{gid}/{build_dir}/manifest.json{q}", "executable": info["executable"],
            "app": info["app"], "save": info.get("save"), "chunks": info.get("chunks"), "seconds": info.get("seconds")},
        "build_due": build_due, "media": media, "building": building, "build_error": error, "worktree": wt,
    }
    if full:
        out["about"] = card.get("about", [])
        out["statement"] = card.get("statement", "")
    return out


def game_entry(ctx, card, full: bool = False, platform: str | None = None) -> dict:
    system = card.category == "system"
    gid = S.arcade_id(card) if system else card.name
    pa = B.platform_arg(ctx.store, card, platform)
    info = latest_info(ctx, gid, pa)
    src = S.source_hash(ctx, card, pa) if system else B.source_hash(ctx, card, pa)
    key = build_key(gid, pa)
    out = _entry(gid, "system" if system else "game", card.name if system else None, card, info, None,
                 build_due=info is None or info.get("source") != src,
                 building=_builds.get(key, {}).get("state") == "building", error=build_error(ctx, key, src), full=full)
    out["source"] = src
    out["platform"] = pa or B.home_key(ctx.store, card)
    return out


def branch_entry(ctx, gid: str, b: dict, own_version: str | None = None, full: bool = False) -> dict:
    """Program gid as worktree b (from work.branches) has it: its card, its latest build there, and whether that
    branch says its cards changed since (None until the branch has been asked)."""
    card, info, name = b["card"], b["build"], b["worktree"]
    key = f"{gid}@{name}"
    row = W.status_row(name, gid)
    due = True if info is None else (row.get("build_due") if row else None)
    system = gid.endswith(S.ID_SUFFIX) and bool(card.get("machine"))
    out = _entry(gid, "system" if system else "game", card.get("name") if system else None, card, info, name,
                 build_due=due, building=_builds.get(key, {}).get("state") == "building",
                 error=build_error(ctx, key, W.fingerprint({"path": b["path"], "head": b["head"]})), full=full)
    out.update(branch=b["branch"], head=b["head"], status_known=row is not None, status_error=(row or {}).get("error"),
               newer=own_version is None or W.version_key(b["version"]) > W.version_key(own_version))
    return out


def catalog(ctx, platform: str | None = None) -> list[dict]:
    """Every program of the service's checkout with its branches, then the programs only a branch has; for another
    platform than the programs' own, their builds for it (and no branch versions: a branch builds its own)."""
    cards = [*ctx.store.cards("game"), *[c for c in ctx.store.cards("system") if c.get("machine")]]
    out = [game_entry(ctx, c, platform=platform) for c in cards]
    if platform and any(B.platform_arg(ctx.store, c, platform) for c in cards):
        for e in out:
            e["branch"], e["branches"] = "", []
        return out
    others = W.branches()
    here = next((w["branch"] for w in W.worktrees() if w["own"]), "")
    for e in out:
        e["branch"] = here
        e["branches"] = [branch_entry(ctx, e["id"], b, e["version"]) for b in others.get(e["id"], [])]
    own = {e["id"] for e in out}
    for gid, bs in others.items():
        if gid not in own:
            first = branch_entry(ctx, gid, bs[0])
            first["branches"] = [branch_entry(ctx, gid, b) for b in bs]
            out.append(first)
    W.refresh_status()
    return out


def program(ctx, gid: str, branch: str | None, platform: str | None = None) -> dict:
    """/api/game/ID[?branch=NAME]: the program in full, from the service's checkout or from that worktree; with a
    platform other than its own, its build for that platform."""
    if platform:
        card = card_for(ctx, gid)
        if B.platform_arg(ctx.store, card, platform):
            return dict(game_entry(ctx, card, full=True, platform=platform), branch="", branches=[])
    if branch:
        bs = W.branches(gid).get(gid) or []
        b = next((x for x in bs if x["worktree"] == branch), None)
        if b is None:
            raise KeyError(f"no {gid} on {branch}")
        return branch_entry(ctx, gid, b, full=True)
    try:
        card = card_for(ctx, gid)
    except KeyError:
        bs = W.branches(gid).get(gid) or []
        if not bs:
            raise
        return branch_entry(ctx, gid, bs[0], full=True)
    out = game_entry(ctx, card, full=True)
    out["branch"] = next((w["branch"] for w in W.worktrees() if w["own"]), "")
    out["branches"] = [branch_entry(ctx, gid, b, out["version"]) for b in W.branches(gid).get(gid, [])]
    return out


def work_view(ctx, force: bool = False) -> dict:
    """/api/work: every worktree (work.overview) with each program's build state as the service knows it."""
    own = {e["id"]: e for e in [game_entry(ctx, c) for c in ctx.store.cards("game")]
           + [game_entry(ctx, c) for c in ctx.store.cards("system") if c.get("machine")]}
    trees = []
    for w in W.overview(force=force):
        progs = []
        for p in w["programs"]:
            if w["own"] and p["id"] in own:
                e = own[p["id"]]
                p = {**p, "build_due": e["build_due"], "build_error": e["build_error"], "building": e["building"]}
            else:
                key = f"{p['id']}@{w['name']}"
                st = _builds.get(key) or {}
                p = {**p, "building": st.get("state") == "building",
                     "build_error": build_error(ctx, key, W.fingerprint(w)) if p.get("build_due") is not None else None}
            progs.append(p)
        trees.append({**w, "programs": progs})
    return {"worktrees": trees, "time": time.time()}


def errors_file(ctx) -> Path:
    return B.arcade_root(ctx) / "build-errors.json"


def _errors(ctx) -> dict:
    try:
        return json.loads(errors_file(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _record_error(ctx, key: str, source: str, error: str | None) -> None:
    """A failed build is remembered with what it was built from, so it is not tried again until that changes
    (across restarts of the service)."""
    with _elock:
        e = _errors(ctx)
        if error is None:
            if key not in e:
                return
            e.pop(key)
        else:
            e[key] = {"source": source, "error": error, "at": time.time()}
        p = errors_file(ctx)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(e, indent=1), encoding="utf-8")


def build_error(ctx, key: str, src: str) -> str | None:
    """Why the cards as they are now did not build, if their last build failed (the last good build stays)."""
    st = _builds.get(key) or {}
    if st.get("state") == "error" and st.get("source") == src:
        return st.get("error")
    if st.get("state") in ("building", "done") and st.get("source") == src:
        return None
    e = _errors(ctx).get(key) or {}
    return e.get("error") if e.get("source") == src else None


def start_build(ctx, gid: str, platform: str | None = None) -> dict:
    card = card_for(ctx, gid)
    pa = B.platform_arg(ctx.store, card, platform)
    src = S.source_hash(ctx, card, pa) if card.category == "system" else B.source_hash(ctx, card, pa)
    key = build_key(gid, pa)
    with _lock:
        st = _builds.get(key)
        if st and st.get("state") == "building":
            return st
        st = {"state": "building", "step": 0, "of": 6, "label": "starting", "started": time.time(), "source": src}
        _builds[key] = st

    def run():
        try:
            def say(step, of, label):
                st.update(step=step, of=of, label=label)
            builder = S.build if S.is_system(ctx.store, gid) else B.build
            info = builder(ctx, gid, progress=say, platform=pa)
            st.update(state="done", step=st["of"], label="ready", build=info["build"], version=info["version"],
                      seconds=info["seconds"])
            _record_error(ctx, key, src, None)
        except Exception as exc:  # noqa: BLE001 -- the launcher shows the reason
            st.update(state="error", error=f"{type(exc).__name__}: {exc}"[:2000])
            _record_error(ctx, key, src, st["error"])
    threading.Thread(target=run, daemon=True).start()
    return st


def start_branch_build(ctx, gid: str, name: str) -> dict:
    """Build program gid on worktree name, with that worktree's own code and cards (work.build_elsewhere)."""
    w = W.worktree(name)
    if w is None or w["own"]:
        raise KeyError(f"no other worktree {name}")
    key = f"{gid}@{name}"
    fp = W.fingerprint(w)
    with _lock:
        st = _builds.get(key)
        if st and st.get("state") == "building":
            return st
        st = {"state": "building", "step": 0, "of": 6, "label": "starting", "started": time.time(), "source": fp,
              "worktree": name}
        _builds[key] = st

    def run():
        try:
            def say(step, of, label):
                st.update(step=step, of=of, label=label)
            log = B.arcade_root(ctx) / "branch-builds" / f"{name}-{gid}.log"
            info = W.build_elsewhere(Path(w["path"]), gid, say, log)
            st.update(state="done", step=st["of"], label="ready", build=info["build"], version=info["version"],
                      seconds=info.get("seconds"))
            _record_error(ctx, key, fp, None)
            W.mark_built(name, gid)
        except Exception as exc:  # noqa: BLE001 -- the launcher shows the reason
            st.update(state="error", error=f"{type(exc).__name__}: {exc}"[:2000])
            _record_error(ctx, key, fp, st["error"])
    threading.Thread(target=run, daemon=True).start()
    return st


class Handler(BaseHTTPRequestHandler):
    ctx = None
    ui_dir: Path | None = None
    server_version = "CardmodelArcade/1"

    def log_message(self, fmt, *args):  # quiet
        pass

    def setup(self):
        # a client on the network gets a minute per read or write: a slow or silent one cannot hold a thread for ever
        self.timeout = None if self.client_address[0] in P.LOOPBACK else 60
        super().setup()

    def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None,
              cors: bool = True):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # this Mac, or a paired device on the local network for what a device needs (pairing.py); the rest is refused
    # before anything runs
    def _admit(self, parts: list[str], q: dict) -> bool:
        if P.allowed(self.ctx, self.client_address[0], self.command, parts, self.headers, q):
            return True
        if P.device(self.ctx, P.token_of(self.headers)) is not None:
            self._json({"error": "that stays on the Mac"}, 403)
        else:
            self._json({"error": "pair this device first (cardmodel arcade pair on the Mac)"}, 401)
        return False

    def _local(self) -> bool:
        """A request from this Mac that no web page of another origin made (a pairing code is this Mac's to show)."""
        origin = self.headers.get("Origin")
        port = self.server.server_address[1]
        return self.client_address[0] in P.LOOPBACK and origin in (None, f"http://127.0.0.1:{port}",
                                                                    f"http://localhost:{port}")

    def _body(self) -> dict:
        """A small JSON object (a pairing request): anything else, or more than 64 KiB, is an empty one."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if not 0 < n <= 1 << 16:
                return {}
            b = json.loads(self.rfile.read(n))
            return b if isinstance(b, dict) else {}
        except (ValueError, OSError):
            return {}

    def do_POST(self):
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/")
        q = parse_qs(u.query)
        branch = (q.get("branch") or [""])[0]
        if not self._admit(parts, q):
            return
        if parts == ["api", "pair"]:
            b = self._body()
            token = P.pair(self.ctx, str(b.get("code", "")), str(b.get("name", "")))
            return self._json({"token": token}) if token else self._json({"error": "wrong or expired code"}, 403)
        if parts == ["api", "pair", "code"]:
            if not self._local():
                return self._json({"error": "only this Mac shows a pairing code"}, 403)
            if not listen_lan(self.ctx, self.server.server_address[1]):
                return self._json({"error": "the service cannot listen on the local network (the port is taken)"}, 503)
            return self._json({**P.new_code(self.ctx), "addresses": P.addresses(self.server.server_address[1])})
        if parts[:2] == ["api", "library"] and self.client_address[0] not in P.LOOPBACK and parts != ["api", "library", "scan"]:
            return self._json({"error": "the Mac's cartridge folders are chosen on the Mac"}, 403)
        fresh(self.ctx)
        if len(parts) == 3 and parts[:2] == ["api", "build"]:
            try:
                if branch:
                    return self._json(start_branch_build(self.ctx, parts[2], branch))
                card_for(self.ctx, parts[2])
                pf = requested_platform(self, q)          # another platform's build; else the program's own
                return self._json(start_build(self.ctx, parts[2], pf) if pf else start_build(self.ctx, parts[2]))
            except KeyError:
                return self._json({"error": "no such game"}, 404)
            except B.BuildError as exc:
                return self._json({"error": str(exc)}, 400)
        if L.route(self, "POST", parts):
            return
        self._json({"error": "not found"}, 404)

    def do_GET(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = parse_qs(u.query)
        ctx = self.ctx
        if not self._admit(parts, q):
            return
        from . import hub
        if hub.route(self, parts, q):                    # in progress, live events
            return
        if parts[:1] == ["api"]:
            with _lock:
                fresh(ctx)
        try:
            if parts == ["api", "status"]:
                return self._json({"ok": True, "service": self.server_version, "time": time.time(),
                                   "ui": ui_hash(self.ui_dir)})
            if parts == ["api", "pair"]:                  # who is asking: a paired device's name, or this Mac
                return self._json({"device": P.device(ctx, P.token_of(self.headers)) or "this Mac"})
            branch = (q.get("branch") or [""])[0]
            platform = requested_platform(self, q)
            if parts == ["api", "catalog"]:
                return self._json(catalog(ctx, platform))
            if len(parts) == 3 and parts[:2] == ["api", "game"]:
                return self._json(program(ctx, parts[2], branch or None, platform))
            if len(parts) == 3 and parts[:2] == ["api", "cartridge"]:
                return self._cartridge(parts[2])
            if parts == ["api", "work"]:
                return self._json(work_view(ctx, force=bool(q.get("force"))))
            if len(parts) == 5 and parts[:2] == ["api", "work"] and parts[3] == "commit":
                c = W.commit(parts[2], parts[4])
                return self._json(c) if c else self._json({"error": "no such commit"}, 404)
            if L.route(self, "GET", parts):
                return
            if len(parts) == 3 and parts[:2] == ["api", "build"]:
                key = f"{parts[2]}@{branch}" if branch else build_key(
                    parts[2], B.platform_arg(ctx.store, card_for(ctx, parts[2]), platform) if platform else None)
                return self._json(_builds.get(key, {"state": "idle"}))
            root = B.arcade_root(ctx)
            if q.get("wt"):
                root = W.state_root(q["wt"][0])
                if root is None:
                    return self._json({"error": "no such worktree"}, 404)
            if len(parts) == 4 and parts[0] == "depot" and parts[3] == "manifest.json":
                p = root / "depots" / Path(parts[1]).name / Path(parts[2]).name / "manifest.json"
                return self._send(200, p.read_bytes()) if p.is_file() else self._json({"error": "no build"}, 404)
            if len(parts) == 2 and parts[0] == "chunk" and W.SHA256.match(parts[1]):
                p = B.arcade_root(ctx) / "chunks" / parts[1]
                if not p.is_file():
                    p = W.find_chunk(parts[1], B.arcade_root(ctx))
                if p is None:
                    return self._json({"error": "no chunk"}, 404)
                return self._chunk(p.read_bytes(), int((q.get("rate") or ["0"])[0] or 0))
            if len(parts) == 4 and parts[0] == "media":
                p = root / "depots" / Path(parts[1]).name / Path(parts[2]).name / "media" / Path(parts[3]).name
                return self._send(200, p.read_bytes(), "image/png") if p.is_file() else self._json({}, 404)
            if parts[:1] == ["ui"] and self.ui_dir is not None:
                rel = "/".join(parts[1:]) or "index.html"
                p = (self.ui_dir / rel).resolve()
                if self.ui_dir.resolve() in p.parents and p.is_file():
                    ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                    return self._send(200, p.read_bytes(), ctype)
                return self._json({"error": "not found"}, 404)
            if not parts:
                return self._send(302, b"", "text/plain", {"Location": "/ui/index.html"})
        except KeyError as exc:
            return self._json({"error": str(exc)}, 404)
        except B.BuildError as exc:                       # a platform the cards do not have
            return self._json({"error": str(exc)}, 400)
        self._json({"error": "not found"}, 404)

    def _cartridge(self, rom_id: str):
        """A cartridge the library lists, as its file (a device plays it where the Mac's player would read it). Not
        for a web page: no page of another origin may read it (no CORS header, and such a request is refused)."""
        port = self.server.server_address[1]
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
            return self._send(403, b'{"error": "not for a web page"}', cors=False)
        r = next((x for x in L.scan(self.ctx)["roms"] if x.get("id") == rom_id), None)
        if r is None or not r.get("path"):
            return self._json({"error": "no such cartridge"}, 404)
        p = Path(r["path"])
        if not p.is_file():
            return self._json({"error": "the cartridge is not where the library saw it"}, 404)
        from urllib.parse import quote
        st = p.stat()
        tag = f'"{st.st_size}-{st.st_mtime_ns}"'                # a device asks again only when the file changed
        if self.headers.get("If-None-Match") == tag:
            return self._send(304, b"", "application/octet-stream", {"ETag": tag}, cors=False)
        return self._send(200, p.read_bytes(), "application/octet-stream", {"X-Cartridge-File": quote(p.name), "ETag": tag},
                          cors=False)

    def _chunk(self, data: bytes, rate: int):
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        piece = 64 * 1024
        t0 = time.time()
        sent = 0
        for o in range(0, len(data), piece):
            self.wfile.write(data[o:o + piece])
            sent += len(data[o:o + piece])
            if rate > 0:
                ahead = sent / rate - (time.time() - t0)
                if ahead > 0:
                    time.sleep(min(ahead, 2.0))


_lan: dict = {}


def listen_lan(ctx, port: int) -> bool:
    """Also listen on the local network (every address of this Mac, the same port), once: paired devices reach the
    service there (pairing.py checks every request). False when the port cannot be had there."""
    with _lock:
        if port in _lan:
            return True
        try:
            httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        except OSError:
            return False
        _lan[port] = httpd
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return True


def serve(ctx, port: int = 8770, ui_dir: Path | None = None, ready=None, lan: bool | None = None) -> None:
    """The service on 127.0.0.1:port; on the local network too when lan (None: on the launcher's port, when a device
    has been paired and the network listener was not turned off since, pairing.py; a service on any other port, a
    test's or a session's, stays on this Mac)."""
    Handler.ctx = ctx
    Handler.ui_dir = ui_dir
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    port = httpd.server_address[1]
    own = int((ctx.store.get("app/arcade") or {}).get("port", 8770))
    paired = P.load(ctx)
    if lan or (lan is None and port == own and paired["lan"] and paired["devices"]):
        listen_lan(ctx, port)
    if ready:
        ready(port)
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()
        s = _lan.pop(port, None)
        if s is not None:
            s.shutdown()
            s.server_close()


__all__ = ["Handler", "branch_entry", "build_key", "catalog", "game_entry", "listen_lan", "program", "requested_platform",
           "serve", "start_branch_build", "start_build"]
