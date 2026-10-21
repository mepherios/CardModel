"""library — the user's own cartridges in the arcade: every file in a system card's library folders, read where it
is (a .zip in memory, nothing copied), with its header, the ROM survey's verdict and a title-screen picture the
machine draws headless (cached under state/arcade/covers/). The launcher starts the system's player on the file.

    GET  /api/library              systems and cartridges (title, system, header, verdict, cover, path)
    POST /api/library/scan         look through the folders again
    GET  /api/cover/ID.png         a cartridge's picture, once drawn
    POST /api/library/folders      {"system": NAME, "add": PATH} or {"system": NAME, "remove": PATH}

Which folders: the user's choice, kept in library.json in the arcade's own folder (beside its saves, which the
platform card places), so any checkout's service sees the same library and no card carries a user's path.

A system card with a ``machine`` and ``logic`` is playable (its player is an arcade build, ``system.py``); one
without (the DS) is listed with what the card model can do with it so far. A cartridge's title is its No-Intro
file name when it has one (region tags in parentheses), else the title in its cartridge header (``entry_title``).
`cardmodel arcade check` launches every listed cartridge through the store (arcade/client.py).

Honest limits (L1): the picture is a frame of the first ten seconds picked by colour, not a chosen shot; the first scan of a
big folder takes a minute to draw every picture (the service draws in the background and the page fills in).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import time
import zipfile
from pathlib import Path

from ..machine import gb as G
from . import system as S

COVER_FRAMES = 600                     # ten seconds, no buttons: intros and title screens
COVER_EVERY = 30
VERDICTS = {
    "runs": ("verified", "Boots and runs: the ROM survey saw it draw and animate"),
    "static": ("playable", "Boots to a still title screen under the survey's scripted input"),
    "blank": ("unsupported", "The screen stays blank"),
    "locked": ("unsupported", "Stops on an instruction no Game Boy has (an unlicensed board)"),
    "error": ("unsupported", "Could not be read"),
}
_lock = threading.Lock()
_state = {"scan": None, "drawing": False, "drawn": 0, "to_draw": 0}


def systems(store) -> list:
    return list(store.cards("system"))


def folders(ctx, card) -> list[Path]:
    extra = (load_settings(ctx).get("folders") or {}).get(card.name, [])
    out = []
    for f in [*(card.get("library") or {}).get("folders", []), *extra]:
        p = Path(f).expanduser()
        if p not in out:
            out.append(p)
    return out


SETTINGS_OVERRIDE: Path | None = None       # tests point it at a temporary file


def settings_file(ctx) -> Path:
    """library.json in the arcade's folder: the parent of the saves folder the platform card names."""
    if SETTINGS_OVERRIDE is not None:
        return SETTINGS_OVERRIDE
    plat = ctx.store.get("platform/macos")
    saves = Path(str((plat or {}).get("saves", "") or "~/Library/Application Support/Cardmodel Arcade/saves/{id}"))
    return Path(str(saves).replace("{id}", "")).expanduser().parent / "library.json"


def load_settings(ctx) -> dict:
    try:
        return json.loads(settings_file(ctx).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def set_folder(ctx, system: str, add: str | None = None, remove: str | None = None) -> list[str]:
    """Add or remove one of a system's cartridge folders; returns the system's folders."""
    if ctx.store.get(f"system/{system}") is None:
        raise KeyError(f"no system card system/{system}")
    st = load_settings(ctx)
    lst = list((st.setdefault("folders", {})).get(system, []))
    if add:
        p = str(Path(add).expanduser())
        if p not in lst:
            lst.append(p)
    if remove:
        r = str(Path(remove).expanduser())
        lst = [x for x in lst if x != r]
    st["folders"][system] = lst
    f = settings_file(ctx)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1), encoding="utf-8")
    tmp.replace(f)
    with _lock:
        _state["scan"] = None
    return lst


def display_title(stem: str) -> tuple[str, str]:
    """No-Intro file names: 'Legend of Zelda, The - Link's Awakening (USA) (Rev B)' -> the title, the tags."""
    m = re.match(r"^(.*?)\s*((?:\([^)]*\)\s*|\[[^\]]*\]\s*)*)$", stem)
    title, tags = (m.group(1), m.group(2).strip()) if m else (stem, "")
    for article in ("The", "A", "An"):
        t = re.sub(rf"^(.*?), {article}( - |$)", rf"{article} \1\2", title)
        if t != title:
            title = t
            break
    return title.strip() or stem, tags


def read_cartridge(path: Path, exts) -> bytes:
    """The cartridge's bytes (the first member with a known extension, for a .zip), read where it is."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as z:
            for n in z.namelist():
                if Path(n).suffix.lower() in exts:
                    return z.read(n)
        raise ValueError("no cartridge inside")
    return path.read_bytes()


def survey_rows(ctx) -> dict:
    sv = ctx.load_state("emu_survey") or {}
    return {r.get("sha1"): r for r in sv.get("rows", []) if r.get("sha1")}


def nds_status(ctx) -> dict:
    cov = ctx.load_state("nds_coverage") or {}
    if not cov:
        return {}
    cpus = cov.get("cpus") or {}
    return {"frames": cov.get("frames"), "title": cov.get("title"),
            "cpus": {k: {"instructions": c.get("instructions_executed"), "distinct": c.get("distinct_instruction_addresses"),
                         "not_modelled": sorted((c.get("unmodelled_hardware_touched") or {}).keys())}
                     for k, c in cpus.items()}}


def scan(ctx, force: bool = False) -> dict:
    """Systems and cartridges. Files are read once and remembered by path, size and time."""
    with _lock:
        if _state["scan"] is not None and not force:
            return _state["scan"]
    cache_path = ctx.state_root / "arcade" / "library-cache.json"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    survey = survey_rows(ctx)
    out_systems, roms, fresh_cache = [], [], {}
    for card in systems(ctx.store):
        lib = card.get("library") or {}
        cart = card.get("cartridge") or {}
        exts = tuple(cart.get("extensions") or lib.get("extensions") or [])
        playable = bool(card.get("machine") and card.get("logic"))
        sub = lib.get("systems") or [{"id": card.name, "label": card["title"]}]
        out_systems.append({"id": card.name, "title": card["title"], "player": S.arcade_id(card) if playable else None,
                            "playable": playable, "systems": sub, "folders": [str(f) for f in folders(ctx, card)],
                            "status": card.get("playable_note")})
        for folder in folders(ctx, card):
            if not folder.is_dir():
                continue
            for p in sorted(folder.rglob("*")):
                if not p.is_file() or p.suffix.lower() not in (".zip", *exts):
                    continue
                st = p.stat()
                key = f"{p}|{st.st_size}|{int(st.st_mtime)}"
                row = cache.get(key)
                if row is None:
                    row = describe(ctx, card, p, exts)
                fresh_cache[key] = row
                if row is None:
                    continue
                row = dict(row)
                row["path"] = str(p)
                head = (row.get("header") or {}).get("title", "")
                row["title"], row["tags"], row["title_from"] = entry_title(p.stem, head)
                v = survey.get(row.get("sha1"))
                if card.name == "nds":
                    row["verdict"] = {"level": "unavailable", "text": card.get("playable_note", ""), "detail": nds_status(ctx)}
                elif v:
                    level, text = VERDICTS.get(v.get("status"), ("unknown", v.get("status", "")))
                    if v.get("unsupported_mapper"):
                        level, text = "unsupported", f"Its bank controller ({v.get('mbc')}) has no card yet"
                    row["verdict"] = {"level": level, "text": text, "reason": v.get("reason")}
                else:
                    row["verdict"] = {"level": "unknown", "text": "Not surveyed yet (cardmodel machine survey)"}
                row["cover"] = f"/api/cover/{row['id']}.png" if cover_path(ctx, row["id"]).is_file() else None
                roms.append(row)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(fresh_cache), encoding="utf-8")
    result = {"systems": out_systems, "roms": roms, "scanned": time.time(),
              "drawing": {"busy": _state["drawing"], "drawn": _state["drawn"], "of": _state["to_draw"]}}
    with _lock:
        _state["scan"] = result
    return result


def entry_title(stem: str, header_title: str) -> tuple[str, str, str]:
    """(title, tags, where the title came from): a No-Intro file name (its region tags show it is one) names the
    game better than the 11 to 16 capitals of the header ('Pokemon - Crystal Version' for PM_CRYSTAL); any other
    file is titled by its cartridge header, and a header without a readable title leaves the file's name."""
    title, tags = display_title(stem)
    if tags:
        return title, tags, "file name"
    head = " ".join(header_title.replace("�", " ").split())
    if head and sum(ch.isalnum() for ch in head) >= 2:
        return head, "", "header"
    return title, tags, "file name"


def describe(ctx, card, path: Path, exts) -> dict | None:
    try:
        data = read_cartridge(path, exts)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError):
        return None
    sha = hashlib.sha1(data).hexdigest()
    row = {"id": f"rom-{sha[:16]}", "sha1": sha, "file": path.name, "size": len(data), "system_card": card.name}
    if card.name == "gameboy":
        try:
            h = G.header(data, ctx.store)
        except ValueError:
            return None
        flags = {s["id"]: s.get("cgb_flags", []) for s in (card.get("library") or {}).get("systems", [])}
        row["system"] = next((k for k, v in flags.items() if h["cgb_flag"] in v), "gb")
        row["header"] = {"title": h["title"], "mbc": h["mbc"], "supported": h["supported"], "battery": h["battery"],
                         "rtc": h["rtc"], "ram": h["ram_size"], "rom": h["rom_size"], "cgb_only": h["cgb_only"],
                         "sgb": h["sgb"]}
    else:
        row["system"] = card.name
        row["header"] = {"title": data[0:12].split(b"\0")[0].decode("ascii", "replace").strip(),
                         "code": data[12:16].decode("ascii", "replace")}
    row["title"], row["tags"], row["title_from"] = entry_title(path.stem, row["header"]["title"])
    return row


def cover_path(ctx, rom_id: str) -> Path:
    return ctx.state_root / "arcade" / "covers" / f"{rom_id}.png"


def cover(ctx, rom_id: str) -> bytes | None:
    p = cover_path(ctx, rom_id)
    return p.read_bytes() if p.is_file() else None


def draw_cover(ctx, machine, path: Path) -> bytes | None:
    """A frame from the first ten seconds (no buttons) as a PNG: the latest one at least half as colourful as the
    most colourful, so a title screen after the company logos usually wins over the logos."""
    try:
        rom = read_cartridge(path, G.ROM_EXTS)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError):
        return None
    g = G.GameBoy(ctx, rom, machine=machine, sample_rate=0)
    seen = []
    for i in range(COVER_FRAMES):
        g.run_frame()
        if machine.get("locked"):
            break
        if i % COVER_EVERY == COVER_EVERY - 1:
            f = g.frame()
            seen.append((G.frame_stats(f)["colours"], f))
    if not seen:
        return None
    top = max(n for n, _ in seen)
    if top <= 1:
        return None
    return G.png([f for n, f in seen if 2 * n >= top][-1])


def draw_covers(ctx, progress=None) -> int:
    """Draw every missing picture (one machine, reset per cartridge). Returns how many were drawn."""
    from ..kernel import resources
    from ..machine import build as Bd
    from ..machine import native as N
    lib = scan(ctx)
    todo = [r for r in lib["roms"] if r.get("system_card") == "gameboy" and not cover_path(ctx, r["id"]).is_file()]
    _state.update(drawing=True, drawn=0, to_draw=len(todo))
    machine = N.load(ctx, Bd.module(ctx, "gameboy"), "native")
    n = 0
    try:
        for r in todo:
            resources.guard("covers")
            png = draw_cover(ctx, machine, Path(r["path"]))
            p = cover_path(ctx, r["id"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(png if png is not None else b"")
            n += 1
            _state["drawn"] = n
            if progress:
                progress(n, len(todo), r)
    finally:
        _state["drawing"] = False
        with _lock:
            _state["scan"] = None
    return n


def start_drawing(ctx) -> None:
    if _state["drawing"]:
        return
    _state["drawing"] = True
    threading.Thread(target=lambda: draw_covers(ctx), daemon=True).start()


def route(handler, method: str, parts: list[str]) -> bool:
    """The library's part of the arcade service (server.Handler calls this first). True when it answered."""
    ctx = handler.ctx
    if method == "POST" and parts == ["api", "library", "scan"]:
        lib = scan(ctx, force=True)
        start_drawing(ctx)
        handler._json({"roms": len(lib["roms"])})
        return True
    if method == "POST" and parts == ["api", "library", "folders"]:
        try:
            n = int(handler.headers.get("Content-Length") or 0)
            body = json.loads(handler.rfile.read(n) or b"{}")
            got = set_folder(ctx, str(body.get("system", "")), body.get("add"), body.get("remove"))
        except (KeyError, ValueError) as exc:
            handler._json({"error": str(exc)}, 400)
            return True
        lib = scan(ctx, force=True)
        start_drawing(ctx)
        handler._json({"folders": got, "roms": len(lib["roms"])})
        return True
    if method != "GET":
        return False
    if parts == ["api", "library"]:
        lib = scan(ctx)
        if any(r.get("cover") is None for r in lib["roms"] if r.get("system_card") == "gameboy"):
            start_drawing(ctx)
        lib = dict(lib, drawing={"busy": _state["drawing"], "drawn": _state["drawn"], "of": _state["to_draw"]})
        handler._json(lib)
        return True
    if len(parts) == 3 and parts[:2] == ["api", "cover"] and parts[2].endswith(".png"):
        data = cover(ctx, parts[2][:-4])
        if data:
            handler.send_response(200)                 # a picture does not change: the page may keep it
            handler.send_header("Content-Type", "image/png")
            handler.send_header("Content-Length", str(len(data)))
            handler.send_header("Cache-Control", "max-age=86400")
            handler.end_headers()
            handler.wfile.write(data)
        else:
            handler._json({"error": "no picture yet"}, 404)
        return True
    return False


__all__ = ["cover", "display_title", "draw_covers", "entry_title", "read_cartridge", "route", "scan", "start_drawing",
           "systems"]
