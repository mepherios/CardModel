"""client — the launcher's side of the arcade service in Python: what Cardmodel Arcade.app does, step for step, so
the store can be checked end to end wherever the toolchains are (law CM39).

    install(base, gid, library)   ask the service to build when the cards changed (POST /api/build/ID, then poll
                                  its progress), fetch the manifest, download every chunk that is not already
                                  installed, check each chunk's and each file's SHA-256, assemble the files in a
                                  staging folder and swap it in; ``repair`` reuses every intact chunk of the
                                  installed build and fetches only what failed (the launcher's verify -> repair)
    verify(library, gid)          re-hash every installed file against the installed manifest
    play(library, gid, ...)       start the installed executable with its own save folder; with ``frames`` it
                                  runs headless and draws its last frame into a PNG
    achievements(save_dir, info)  the unlocked achievements, read from the save the way the launcher reads them
    check_catalog(ctx)            every game in the catalogue, through the service: install, verify, corrupt a
                                  file and repair it, play headless, look at the picture it drew; the store's
                                  pages are served and name only endpoints the service has

Honest limits (L1): this mirrors Launcher.swift (the native window and its page bridge are not driven; the
launcher is checked by compiling it); a game counts as launched when its native executable runs the frames it
was asked for, exits cleanly and draws a frame that is not one flat colour.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from ..kernel import resources


class StoreError(RuntimeError):
    pass


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # the service is local: never via a proxy


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _get(base: str, path: str, timeout: float = 60) -> bytes:
    with _OPENER.open(base + path, timeout=timeout) as r:
        return r.read()


def _json(base: str, path: str):
    return json.loads(_get(base, path))


def _post(base: str, path: str):
    req = urllib.request.Request(base + path, data=b"", method="POST")
    with _OPENER.open(req, timeout=60) as r:
        return json.loads(r.read())


def install(base: str, gid: str, library: Path, repair: bool = False, build_timeout: float = 900,
            progress=None) -> dict:
    say = progress or (lambda *a: None)
    entry = _json(base, f"/api/game/{gid}")
    built = None
    if entry.get("build_due"):
        _post(base, f"/api/build/{gid}")
        deadline = time.monotonic() + build_timeout
        while True:
            time.sleep(0.25)
            st = _json(base, f"/api/build/{gid}")
            say("building", st.get("step"), st.get("of"), st.get("label"))
            if st.get("state") == "done":
                built = st.get("build")
                break
            if st.get("state") == "error":
                raise StoreError(f"the service could not build {gid}: {st.get('error')}")
            if time.monotonic() > deadline:
                raise StoreError(f"building {gid} took longer than {build_timeout:.0f} s")
        entry = _json(base, f"/api/game/{gid}")
    b = entry.get("build")
    if not b:
        raise StoreError(f"{gid} has no build to download")
    man_bytes = _get(base, b["manifest"])
    man = json.loads(man_bytes)
    library.mkdir(parents=True, exist_ok=True)
    dest, staging = library / gid, library / f"{gid}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    have: dict[str, tuple[Path, int]] = {}
    old = dest / ".manifest.json"
    if old.is_file():
        om = json.loads(old.read_text(encoding="utf-8"))
        if repair or om.get("build") != man["build"]:
            for f in om.get("files", []):
                off = 0
                for c in f["chunks"]:
                    have[c["sha256"]] = (dest / f["path"], off)
                    off += c["size"]
    fetched = reused = 0
    for f in man["files"]:
        parts = []
        for c in f["chunks"]:
            part = None
            if c["sha256"] in have:
                p, off = have[c["sha256"]]
                try:
                    with open(p, "rb") as fh:
                        fh.seek(off)
                        d = fh.read(c["size"])
                    if _sha(d) == c["sha256"]:
                        part, reused = d, reused + len(d)
                except OSError:
                    part = None
            if part is None:
                d = _get(base, f"/chunk/{c['sha256']}")
                if _sha(d) != c["sha256"]:
                    raise StoreError(f"chunk {c['sha256'][:12]} of {f['path']} failed its check")
                part, fetched = d, fetched + len(d)
            parts.append(part)
        data = b"".join(parts)
        if _sha(data) != f["sha256"]:
            raise StoreError(f"{f['path']} failed its check")
        out = staging / f["path"]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        if f.get("executable"):
            os.chmod(out, 0o755)
        say("downloading", fetched, man["size"], f["path"])
    (staging / ".manifest.json").write_bytes(man_bytes)
    shutil.rmtree(dest, ignore_errors=True)
    staging.rename(dest)
    return {"build": man["build"], "version": man["version"], "files": len(man["files"]), "size": man["size"],
            "fetched": fetched, "reused": reused, "built": built, "executable": man["executable"],
            "save": man.get("save")}


def verify(library: Path, gid: str) -> dict:
    d = library / gid
    man = json.loads((d / ".manifest.json").read_text(encoding="utf-8"))
    bad = [f["path"] for f in man["files"]
           if not (d / f["path"]).is_file() or _sha((d / f["path"]).read_bytes()) != f["sha256"]]
    return {"ok": not bad, "bad": bad, "files": len(man["files"])}


def picture(png: bytes) -> dict:
    """How much a PNG shows: its size and how many distinct colours a grid of samples finds."""
    from ..machine.gb import png_read
    w, h, rgb = png_read(png)
    seen = set()
    for y in range(0, h, max(1, h // 48)):
        for x in range(0, w, max(1, w // 64)):
            i = (y * w + x) * 3
            seen.add(rgb[i:i + 3])
    return {"width": w, "height": h, "colours_sampled": len(seen)}


def play(library: Path, gid: str, frames: int, save_dir: Path, shot: Path | None = None, script: str | None = None,
         timeout: float = 300) -> dict:
    man = json.loads((library / gid / ".manifest.json").read_text(encoding="utf-8"))
    exe = library / gid / man["executable"]
    cmd = [str(exe), "--frames", str(frames), "--save-dir", str(save_dir)]
    if shot:
        cmd += ["--shot", str(shot)]
    if script:
        cmd += ["--input", script]
    t0 = time.perf_counter()
    try:
        p = resources.run(cmd, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return {"ok": False, "reason": f"no exit after {timeout:.0f} s", "seconds": timeout}
    out = {"returncode": p.returncode, "ran": f"ran {frames} frames" in (p.stdout or ""),
           "seconds": round(time.perf_counter() - t0, 2), "stderr": (p.stderr or "")[-600:]}
    if shot:
        out["picture"] = picture(Path(shot).read_bytes()) if Path(shot).is_file() else None
    pic = out.get("picture")
    out["ok"] = p.returncode == 0 and out["ran"] and (shot is None or bool(pic and pic["colours_sampled"] > 1))
    return out


def achievements(save_dir: Path, info: dict | None) -> list[int]:
    """One byte per achievement from ``achievements_offset`` (the layout the game's save card documents)."""
    off = int(((info or {}).get("save") or {}).get("achievements_offset", 32))
    f = save_dir / ((info or {}).get("save") or {}).get("file", "save.bin")
    data = f.read_bytes() if f.is_file() else b""
    return list(data[off:off + 16]) if len(data) > off else []


def pages(base: str) -> dict:
    """The launcher's pages are served, and every API path the page script names exists on the service."""
    html = _get(base, "/ui/index.html").decode("utf-8", "replace")
    assets = re.findall(r'(?:src|href)="([^"/][^"]*\.(?:js|css))"', html)
    missing = []
    for a in assets:
        try:
            _get(base, f"/ui/{a}")
        except OSError:
            missing.append(a)
    script = _get(base, "/ui/app.js").decode("utf-8", "replace") if "app.js" in assets else ""
    named = sorted(set(re.findall(r'"(/api/[a-z]+)/?', script)))
    from .server import ENDPOINTS
    unknown = [n for n in named if n not in ENDPOINTS]
    return {"ok": not missing and not unknown, "assets": assets, "missing": missing, "api": named,
            "unknown_endpoints": unknown}


def serve_here(ctx, ui_dir: Path | None):
    """The arcade service on a free localhost port, in this process (a thread); returns (base URL, stop)."""
    from http.server import ThreadingHTTPServer
    from . import server as S
    S.Handler.ctx = ctx
    S.Handler.ui_dir = ui_dir
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def stop():
        httpd.shutdown()
        httpd.server_close()
    return f"http://127.0.0.1:{httpd.server_address[1]}", stop


def check_catalog(ctx, frames: int = 120, only: list[str] | None = None, build: bool = True,
                  progress=None) -> dict:
    """Every catalogue item, launched through the store as the launcher would (a temporary library and saves:
    the player's own installation is never touched)."""
    from . import build as B
    say = progress or (lambda m: None)
    app = ctx.store.get("app/arcade")
    ui = (app.path / app["ui"]) if app is not None and app.get("ui") else None
    games = [c for c in ctx.store.cards("game") if not only or c.name in only]
    if not games:
        return {"status": "vacuous", "reason": "no game cards in the catalogue", "items": {}}
    probe = B.platform_card(ctx.store, games[0]).get("probe")
    from ..engines import probes
    ok, why = probes.probe(probe) if probe else (True, "")
    if not ok:
        return {"status": "skipped", "reason": f"the platform card's toolchain is not here: {why}", "items": {}}
    base, stop = serve_here(ctx, ui)
    work = Path(tempfile.mkdtemp(prefix="cardmodel_store_"))
    items, catalog = {}, []
    page: dict = {"ok": False, "reason": "not reached"}
    try:
        catalog = _json(base, "/api/catalog")
        page = pages(base) if ui is not None else {"ok": False, "reason": "no launcher pages (app/arcade)"}
        listed = {g["id"]: g for g in catalog}
        for card in games:
            gid = card.name
            row: dict = {"title": card.get("title"), "version": card.get("version"), "listed": gid in listed}
            items[gid] = row
            t0 = time.perf_counter()
            try:
                if not row["listed"]:
                    raise StoreError("the catalogue does not list it")
                if listed[gid].get("build_due") and not build:
                    raise StoreError("its cards changed since the last build (building was not allowed)")
                say(f"{gid}: installing through the store")
                lib = work / "library"
                inst = install(base, gid, lib)
                row["install"] = {k: inst[k] for k in ("build", "version", "files", "size", "fetched", "built")}
                row["verify"] = verify(lib, gid)
                victim = next(f for f in json.loads((lib / gid / ".manifest.json").read_text())["files"]
                              if f["size"] > 0)
                p = lib / gid / victim["path"]
                p.write_bytes(b"\0" * victim["size"])          # a damaged file: verify must see it, repair fix it
                broken = verify(lib, gid)
                fixed = install(base, gid, lib, repair=True)
                row["repair"] = {"file": victim["path"], "seen": victim["path"] in broken["bad"],
                                 "fetched": fixed["fetched"], "reused": fixed["reused"], "ok": verify(lib, gid)["ok"]}
                saves = work / "saves" / gid
                say(f"{gid}: playing {frames} frames headless")
                row["play"] = play(lib, gid, frames, saves, shot=work / f"{gid}.png")
                row["achievements_readable"] = isinstance(achievements(saves, inst), list)
                row["ok"] = bool(row["verify"]["ok"] and row["repair"]["seen"] and row["repair"]["ok"]
                                 and row["repair"]["fetched"] <= victim["size"] and row["play"]["ok"])
            except (StoreError, OSError, ValueError, KeyError, StopIteration) as exc:
                row["ok"] = False
                row["error"] = f"{type(exc).__name__}: {exc}"
            row["seconds"] = round(time.perf_counter() - t0, 2)
    finally:
        stop()
        shutil.rmtree(work, ignore_errors=True)
    failing = [g for g, r in items.items() if not r.get("ok")]
    return {"status": "fail" if failing or not page.get("ok") else "pass", "items": items, "failing": failing,
            "pages": page, "catalog": [g["id"] for g in catalog], "frames": frames}


__all__ = ["StoreError", "achievements", "check_catalog", "install", "pages", "picture", "play", "serve_here",
           "verify"]
