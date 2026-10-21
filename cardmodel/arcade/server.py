"""server — the arcade's content service (stdlib HTTP): what the launcher's Store, Library and Downloads read.

    GET  /api/catalog                    every game card: its data, its latest build, whether a new build is due
    GET  /api/game/ID                    one game in full (about, versions, achievements, media, build)
    POST /api/build/ID                   build the game from its cards now (in the background)
    GET  /api/build/ID                   that build's progress: state, step, of, label, error
    GET  /depot/ID/BUILD/manifest.json   a build's files and chunks
    GET  /chunk/SHA256[?rate=B]          one chunk (content-addressed), at most B bytes a second when asked
    GET  /media/ID/BUILD/FILE            store and library pictures (drawn by the game)
    GET  /ui/...                         the launcher's pages (the app card's ui folder)

A build is due when the hash of the game's sources (its cards, its logic, the platform shell, the arcade build
code) differs from the latest build's. The service only reads the cards and writes under state/arcade.

Honest limits (L1): localhost only and unauthenticated; one build at a time per game; card changes are seen
through file times, code changes need a restart of the service.
"""
from __future__ import annotations

import json
import mimetypes
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import build as B
from . import game as G

ENDPOINTS = ("/api/status", "/api/catalog", "/api/game", "/api/build")   # what the pages may ask (client.pages)
_builds: dict[str, dict] = {}
_lock = threading.Lock()
_seen = {"mark": None}
WATCH = ("game", "platform", "app", "asset", "move", "fighter", "payoff")


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


def latest_info(ctx, gid: str) -> dict | None:
    root = B.latest(ctx, gid)
    if root is None:
        return None
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def game_entry(ctx, card, full: bool = False) -> dict:
    info = latest_info(ctx, card.name)
    src = B.source_hash(ctx, card)
    build_dir = f"{info['version']}+{info['build']}" if info else None
    media = {}
    if info:
        media = {m.rsplit(".", 1)[0]: f"/media/{card.name}/{build_dir}/{m}" for m in info.get("media", [])}
    out = {
        "id": card.name, "title": card["title"], "version": card["version"], "developer": card.get("developer"),
        "genre": card.get("genre", []), "tags": card.get("tags", []),
        "short_description": card.get("short_description", ""),
        "achievements": card.get("achievements", []),
        "changelog": card.get("changelog", []),
        "build": None if not info else {
            "version": info["version"], "build": info["build"], "size": info["size"], "created": info["created"],
            "manifest": f"/depot/{card.name}/{build_dir}/manifest.json", "executable": info["executable"],
            "app": info["app"], "save": info.get("save"), "chunks": info.get("chunks")},
        "build_due": info is None or info.get("source") != src,
        "source": src, "media": media,
        "building": _builds.get(card.name, {}).get("state") == "building",
    }
    if full:
        out["about"] = card.get("about", [])
        out["statement"] = card.get("statement", "")
    return out


def start_build(ctx, gid: str) -> dict:
    with _lock:
        st = _builds.get(gid)
        if st and st.get("state") == "building":
            return st
        st = {"state": "building", "step": 0, "of": 6, "label": "starting", "started": time.time()}
        _builds[gid] = st

    def run():
        try:
            def say(step, of, label):
                st.update(step=step, of=of, label=label)
            info = B.build(ctx, gid, progress=say)
            st.update(state="done", step=st["of"], label="ready", build=info["build"], version=info["version"],
                      seconds=info["seconds"])
        except Exception as exc:  # noqa: BLE001 -- the launcher shows the reason
            st.update(state="error", error=f"{type(exc).__name__}: {exc}"[:2000])
    threading.Thread(target=run, daemon=True).start()
    return st


class Handler(BaseHTTPRequestHandler):
    ctx = None
    ui_dir: Path | None = None
    server_version = "CardmodelArcade/1"

    def log_message(self, fmt, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json", extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
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

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        fresh(self.ctx)
        if len(parts) == 3 and parts[:2] == ["api", "build"]:
            try:
                G.game_card(self.ctx.store, parts[2])
            except KeyError:
                return self._json({"error": "no such game"}, 404)
            return self._json(start_build(self.ctx, parts[2]))
        self._json({"error": "not found"}, 404)

    def do_GET(self):
        u = urlparse(self.path)
        parts = [p for p in u.path.split("/") if p]
        q = parse_qs(u.query)
        ctx = self.ctx
        if parts[:1] == ["api"]:
            with _lock:
                fresh(ctx)
        try:
            if parts == ["api", "status"]:
                return self._json({"ok": True, "service": self.server_version, "time": time.time()})
            if parts == ["api", "catalog"]:
                return self._json([game_entry(ctx, c) for c in ctx.store.cards("game")])
            if len(parts) == 3 and parts[:2] == ["api", "game"]:
                return self._json(game_entry(ctx, G.game_card(ctx.store, parts[2]), full=True))
            if len(parts) == 3 and parts[:2] == ["api", "build"]:
                return self._json(_builds.get(parts[2], {"state": "idle"}))
            if len(parts) == 4 and parts[0] == "depot" and parts[3] == "manifest.json":
                p = B.arcade_root(ctx) / "depots" / parts[1] / parts[2] / "manifest.json"
                return self._send(200, p.read_bytes()) if p.is_file() else self._json({"error": "no build"}, 404)
            if len(parts) == 2 and parts[0] == "chunk" and len(parts[1]) == 64:
                p = B.arcade_root(ctx) / "chunks" / parts[1]
                if not p.is_file():
                    return self._json({"error": "no chunk"}, 404)
                return self._chunk(p.read_bytes(), int((q.get("rate") or ["0"])[0] or 0))
            if len(parts) == 4 and parts[0] == "media":
                p = B.arcade_root(ctx) / "depots" / parts[1] / parts[2] / "media" / Path(parts[3]).name
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
        self._json({"error": "not found"}, 404)

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


def serve(ctx, port: int = 8770, ui_dir: Path | None = None, ready=None) -> None:
    Handler.ctx = ctx
    Handler.ui_dir = ui_dir
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if ready:
        ready(httpd.server_address[1])
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


__all__ = ["Handler", "game_entry", "serve", "start_build"]
