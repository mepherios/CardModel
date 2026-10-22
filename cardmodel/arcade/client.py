"""client — the launcher's side of the arcade service in Python: what Cardmodel Arcade.app does, step for step, so
the store can be checked end to end wherever the toolchains are (law CM42; the self-run's `store` step).

    install(base, gid, library)   ask the service to build when the cards changed (wait_build: POST /api/build/ID,
                                  then poll its progress; a refused or lost build ends the wait), fetch the
                                  manifest, download every chunk that is not already
                                  installed, check each chunk's and each file's SHA-256, assemble the files in a
                                  staging folder and swap it in; ``repair`` reuses every intact chunk of the
                                  installed build and fetches only what failed (the launcher's verify -> repair)
    verify(library, gid)          re-hash every installed file against the installed manifest
    play(library, gid, ...)       start the installed executable with its own save folder (and, for a console
                                  player, the cartridge where it is: Launcher.playRom); with ``frames`` it runs
                                  headless and draws its last frame into a PNG
    achievements(save_dir, info)  the unlocked achievements, read from the save the way the launcher reads them
    check_catalog(ctx)            every program in the catalogue (games and console players), through the service:
                                  install, verify, corrupt a file and repair it, play headless, look at the
                                  picture it drew; then every cartridge the library lists (check_cartridges); the
                                  store's pages are served and name only endpoints the service has
    check_cartridges(...)         each listed cartridge started in its store-installed player as the launcher
                                  starts it, headless: it runs, exits cleanly, keeps its save folder where the
                                  launcher keeps it and shows the picture its system's cards compute (Reference)

Honest limits (L1): this mirrors Launcher.swift (the native window and its page bridge are not driven; the
launcher is checked by compiling it); a game counts as launched when its native executable runs the frames it
was asked for, exits cleanly and draws a frame that is not one flat colour. A cartridge counts as launched when
the installed player runs it and shows exactly the picture the player module computes in this process for the
same bytes and frames: that checks the store's path (listing, player, shell, cartridge reading), not how well
the game itself runs (the ROM survey's verdict says that, and many games still show a blank or white screen
after the check's frames).
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
import urllib.error
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


LOST_ASK_AGAIN, LOST_GIVE_UP = 8, 40     # polls of 0.25 s the service may not know the build (Launcher.install)


def wait_build(base: str, gid: str, timeout: float = 900, say=None) -> str | None:
    """Ask the service to build gid and wait for it, as the launcher does: a request the service refuses ends the
    wait with its reason; a build it no longer knows (it restarted) is asked for once more after 2 s, and after
    10 s more the wait ends, so an install never waits on a build that will not finish."""
    say = say or (lambda *a: None)
    try:
        _post(base, f"/api/build/{gid}")
    except urllib.error.HTTPError as exc:
        with exc:
            why = json.loads(exc.read() or b"{}").get("error") or exc.reason
        raise StoreError(f"the arcade service would not build {gid}: {why}") from None
    deadline, lost = time.monotonic() + timeout, 0
    while True:
        time.sleep(0.25)
        st = _json(base, f"/api/build/{gid}")
        if st.get("state") not in ("building", "done", "error"):
            lost += 1
            if lost == LOST_ASK_AGAIN:
                try:
                    _post(base, f"/api/build/{gid}")
                except urllib.error.HTTPError as exc:
                    exc.close()
            if lost > LOST_GIVE_UP:
                raise StoreError(f"the arcade service lost the build of {gid} (it restarted?): try again")
            continue
        lost = 0
        say("building", st.get("step"), st.get("of"), st.get("label"))
        if st.get("state") == "done":
            return st.get("build")
        if st.get("state") == "error":
            raise StoreError(f"the service could not build {gid}: {st.get('error')}")
        if time.monotonic() > deadline:
            raise StoreError(f"building {gid} took longer than {timeout:.0f} s")


def install(base: str, gid: str, library: Path, repair: bool = False, build_timeout: float = 900,
            progress=None) -> dict:
    say = progress or (lambda *a: None)
    entry = _json(base, f"/api/game/{gid}")
    built = None
    if entry.get("build_due"):
        built = wait_build(base, gid, build_timeout, say)
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
    """How much a PNG shows: its size and how many distinct colours its pixels have (every pixel of a small
    picture; every 7th of a large one: an odd stride, so a one-pixel stripe pattern cannot alias to one colour)."""
    from ..machine.gb import png_read
    w, h, rgb = png_read(png)
    step = 3 if w * h <= 300_000 else 21
    seen = {rgb[i:i + 3] for i in range(0, len(rgb) - 2, step)}
    return {"width": w, "height": h, "colours_sampled": len(seen)}


def play(library: Path, gid: str, frames: int, save_dir: Path, shot: Path | None = None, script: str | None = None,
         timeout: float = 300, rom: str | Path | None = None, title: str | None = None) -> dict:
    man = json.loads((library / gid / ".manifest.json").read_text(encoding="utf-8"))
    exe = library / gid / man["executable"]
    cmd = [str(exe)]
    if rom is not None:                      # a console player: what Launcher.playRom passes
        cmd += ["--rom", str(rom), "--title", title or Path(rom).stem]
    cmd += ["--frames", str(frames), "--save-dir", str(save_dir)]
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
    """The launcher's pages are served, and every API route their scripts name is one the service documents."""
    html = _get(base, "/ui/index.html").decode("utf-8", "replace")
    assets = re.findall(r'(?:src|href)="([^"/][^"]*\.(?:js|css))"', html)
    missing, script = [], ""
    for a in assets:
        try:
            body = _get(base, f"/ui/{a}")
        except OSError:
            missing.append(a)
            continue
        if a.endswith(".js"):
            script += body.decode("utf-8", "replace")
    named = sorted(set(re.findall(r'["\'`](/api/[a-z_]+)', script)))
    from . import server
    documented = set(re.findall(r"(/api/[a-z_]+)", server.__doc__ or ""))   # the service lists every route it serves
    unknown = [n for n in named if n not in documented]
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


class Reference:
    """What a system's cards compute for a cartridge: its player module loaded once in this process (a fresh copy
    of the native library, system.Player), each cartridge inserted as the shell inserts it and run the same frames
    with no buttons, the sound buffer emptied every frame as the shell empties it."""

    def __init__(self, ctx, system: str):
        self.ctx, self.system, self.player = ctx, system, None

    def picture(self, rom: bytes, frames: int) -> tuple[int, int, bytes]:
        from . import system as Sy
        if self.player is None:
            self.player = Sy.Player(self.ctx, self.system, rom, "native", fresh=True)
        else:
            self.player.start(rom)
        p = self.player
        count = p.card["audio"]["count"]
        for _ in range(frames):
            p.frame(0)
            p.m.set(count, 0)
        return p.card["screen"]["width"], p.card["screen"]["height"], p.rgb()

    def close(self) -> None:
        if self.player is not None and hasattr(self.player.m, "close"):
            self.player.m.close()


def check_cartridges(ctx, base: str, library: Path, work: Path, frames: int, installed: set, refs: dict,
                     limit: int | None = None, progress=None) -> dict:
    """Every cartridge the store's library lists (GET /api/library), started the way Launcher.playRom starts it
    (the store-installed player, the cartridge where it is, its title, a save folder per cartridge under the
    check's own saves), headless: it must run its frames, exit cleanly, keep that save folder, and show the
    picture its system's cards compute for the same bytes (Reference). A cartridge of a console with no player
    yet (the DS) is listed but not launchable, and is counted as such. ``limit`` checks only the first N."""
    from . import library as Lib
    from ..machine.gb import frame_stats, png_read
    say = progress or (lambda m: None)
    listing = _json(base, "/api/library")
    systems = {s_["id"]: s_ for s_ in listing.get("systems") or []}
    roms = list(listing.get("roms") or [])
    todo = roms if limit is None else roms[:max(0, int(limit))]
    players: dict = {}
    failed, unplayable = [], {}
    launched = colourful = saves_written = 0
    t0 = time.perf_counter()
    for k, r in enumerate(todo):
        sy = systems.get(r.get("system_card")) or {}
        if not sy.get("playable"):
            key = r.get("system_card") or "?"
            unplayable[key] = unplayable.get(key, 0) + 1
            continue
        pid = sy.get("player")
        tally = players.setdefault(pid, {"listed": 0, "launched": 0, "colourful": 0, "verdicts": {}})
        tally["listed"] += 1
        level = (r.get("verdict") or {}).get("level", "unknown")
        tally["verdicts"][level] = tally["verdicts"].get(level, 0) + 1
        try:
            missing = [f for f in ("id", "title", "path", "system_card") if not r.get(f)]
            if missing:
                raise StoreError(f"the library lists it without {', '.join(missing)}")
            if pid not in installed:
                raise StoreError(f"its player {pid} did not pass the store's own check (install, verify, repair, "
                                 "its check cartridge)")
            if not Path(r["path"]).is_file():                   # Launcher.playRom's own guard
                raise StoreError(f"the cartridge is not at {r['path']} any more")
            if r.get("cover") and not _get(base, r["cover"]).startswith(b"\x89PNG"):
                raise StoreError("its picture in the store is not a PNG")
            saves = work / "saves" / r["id"]
            shot = work / "shots" / f"{r['id']}.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            out = play(library, pid, frames, saves, shot=shot, rom=r["path"], title=r["title"], timeout=120)
            if out.get("returncode") != 0 or not out.get("ran"):
                raise StoreError("the installed player did not run it: "
                                 + (out.get("reason") or (out.get("stderr") or "").strip()[-300:] or str(out)))
            if not saves.is_dir():
                raise StoreError("the player did not keep the save folder the launcher gives it")
            card = ctx.store.get(f"system/{r['system_card']}")
            exts = tuple((card.get("cartridge") or {}).get("extensions") or ())
            ref = refs.get(r["system_card"]) or refs.setdefault(r["system_card"], Reference(ctx, r["system_card"]))
            want = ref.picture(Lib.read_cartridge(Path(r["path"]), exts), frames)
            got = png_read(shot.read_bytes())
            if got != want:
                raise StoreError(f"after {frames} frames it shows a picture its cards do not compute")
            launched += 1
            tally["launched"] += 1
            if frame_stats(got[2])["colours"] > 1:
                colourful += 1
                tally["colourful"] += 1
            saves_written += (saves / "save.bin").is_file()
        except (StoreError, OSError, ValueError, KeyError) as exc:
            failed.append({"id": r.get("id"), "title": r.get("title"), "path": r.get("path"),
                           "error": f"{type(exc).__name__}: {exc}"[:600]})
        if k % 100 == 99:
            say(f"cartridges: {k + 1} of {len(todo)} started through the store")
    shutil.rmtree(work / "shots", ignore_errors=True)
    return {"listed": len(roms), "checked": len(todo) - sum(unplayable.values()), "launched": launched,
            "failed": len(failed), "failed_ids": [f["id"] for f in failed], "failing": failed[:50],
            "colourful": colourful, "saves_written": saves_written, "unplayable": unplayable, "players": players,
            "frames": frames, "limit": limit, "seconds": round(time.perf_counter() - t0, 1)}


def check_catalog(ctx, frames: int = 120, only: list[str] | None = None, build: bool = True,
                  progress=None, cartridges: int | None = None) -> dict:
    """Every item of the store's release catalogue (not other worktrees' branch versions), launched through the
    store as the launcher would (a temporary library and saves: the player's own installation is never touched):
    the games, and each console player played on its system card's check cartridge; then, when a player is
    checked, every cartridge the library lists (check_cartridges; ``cartridges`` checks only the first N, 0 none).
    A game or player card the catalogue does not list fails too."""
    from . import build as B
    from . import system as Sy
    say = progress or (lambda m: None)
    app = ctx.store.get("app/arcade")
    ui = (app.path / app["ui"]) if app is not None and app.get("ui") else None
    games = [(c, c.name) for c in ctx.store.cards("game") if not only or c.name in only]
    systems = [(c, Sy.arcade_id(c)) for c in ctx.store.cards("system")
               if c.get("machine") and c.get("logic") and (not only or Sy.arcade_id(c) in only)]
    programs = games + systems
    if not programs:
        return {"status": "vacuous", "reason": "no game or player cards in the catalogue", "items": {}}
    probe = B.platform_card(ctx.store, programs[0][0]).get("probe")
    from ..engines import probes
    ok, why = probes.probe(probe) if probe else (True, "")
    if not ok:
        return {"status": "skipped", "reason": f"the platform card's toolchain is not here: {why}", "items": {}}
    base, stop = serve_here(ctx, ui)
    work = Path(tempfile.mkdtemp(prefix="cardmodel_store_"))
    items, catalog, refs = {}, [], {}
    page: dict = {"ok": False, "reason": "not reached"}
    carts: dict | None = None
    try:
        catalog = [g for g in _json(base, "/api/catalog") if not g.get("worktree")]     # the release channel
        page = pages(base) if ui is not None else {"ok": False, "reason": "no launcher pages (app/arcade)"}
        listed = {g["id"]: g for g in catalog}
        lib = work / "library"
        for card, gid in programs:
            row: dict = {"title": card.get("title"), "version": card.get("version"), "listed": gid in listed,
                         "kind": card.category}
            items[gid] = row
            t0 = time.perf_counter()
            try:
                if not row["listed"]:
                    raise StoreError("the catalogue does not list it")
                if listed[gid].get("build_due") and not build:
                    raise StoreError("its cards changed since the last build (building was not allowed)")
                say(f"{gid}: installing through the store")
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
                if card.category == "system":
                    row["play"] = _play_check_cartridge(ctx, card, lib, gid, work, frames, refs)
                else:
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
        if systems and cartridges != 0:
            installed = {gid for _, gid in systems if items.get(gid, {}).get("ok")}
            say("cartridges: every one the library lists, started through the store")
            carts = check_cartridges(ctx, base, lib, work, frames, installed, refs, limit=cartridges, progress=say)
            for _, gid in systems:          # playing cartridges leaves the installed player as it was
                if items.get(gid, {}).get("ok"):
                    items[gid]["verify_after_cartridges"] = verify(lib, gid)
                    items[gid]["ok"] = items[gid]["verify_after_cartridges"]["ok"]
    finally:
        stop()
        for ref in refs.values():
            ref.close()
        shutil.rmtree(work, ignore_errors=True)
    failing = [g for g, r in items.items() if not r.get("ok")]
    bad = bool(failing or not page.get("ok") or (carts and carts["failed"]))
    return {"status": "fail" if bad else "pass", "items": items, "failing": failing, "pages": page,
            "catalog": [g["id"] for g in catalog], "frames": frames, "cartridges": carts}


def _play_check_cartridge(ctx, card, lib: Path, gid: str, work: Path, frames: int, refs: dict) -> dict:
    """A console player, played as the launcher plays a cartridge, on its system card's check cartridge (no one's
    game): it must show the picture its cards compute and leave the card's byte in the save, in the save folder
    the launcher gives that cartridge."""
    from . import system as Sy
    from ..machine.gb import png_read
    cc = Sy.check_cartridge(ctx, card.name)
    if cc is None:
        raise StoreError(f"system/{card.name} has no check_cartridge to play")
    rom = work / "cartridges" / cc["file"]
    rom.parent.mkdir(parents=True, exist_ok=True)
    rom.write_bytes(cc["bytes"])
    saves = work / "saves" / f"check-{card.name}"
    shot = work / f"{gid}.png"
    out = play(lib, gid, frames, saves, shot=shot, rom=rom, title=Path(cc["file"]).stem)
    ref = refs.get(card.name) or refs.setdefault(card.name, Reference(ctx, card.name))
    out["same_as_cards"] = shot.is_file() and png_read(shot.read_bytes()) == ref.picture(cc["bytes"], frames)
    save = (saves / "save.bin").read_bytes() if (saves / "save.bin").is_file() else b""
    want = cc.get("save")
    out["save_kept"] = want is None or (len(save) > want["offset"] and save[want["offset"]] == want["byte"])
    out["ok"] = bool(out["ok"] and out["same_as_cards"] and out["save_kept"])
    return out


__all__ = ["Reference", "StoreError", "achievements", "check_cartridges", "check_catalog", "install", "pages",
           "picture", "play", "serve_here", "verify", "wait_build"]
