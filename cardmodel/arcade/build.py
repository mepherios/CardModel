"""build — a game card to a native package and a depot the launcher downloads.

    game card ──gen + card language──▶ card-IR module ──language card──▶ shared library
    platform card's effect shell ──its compile command──▶ executable
    the game's own drawings (icon, poster, title, duels played headless) ──▶ store media
    all of it ──▶ a bundle (the platform card's layout) ──▶ depot: a manifest of files split into chunks
    stored by SHA-256 (the launcher fetches chunks, checks every hash, assembles the files)

Nothing here knows a language or a platform: the language card says how to compile the module, the platform
card how to compile its shell and lay out the package. A build is identified by the hash of what went into
it, so a new card version (or any change) is a new build the launcher sees as an update.

Honest limits (L1): one platform card so far (macOS); packages carry only the linker's ad-hoc signature; the
store pictures are fixed moments of a scripted run, not chosen shots.
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import struct
import subprocess
import time
import zlib
from pathlib import Path

from ..kernel import resources
from ..engines.codegen import Emitter
from ..engines import probes
from ..machine import native as N
from . import game as G

CHUNK = 1 << 20
TIMEOUT_S = 600


class BuildError(RuntimeError):
    pass


ROOT_OVERRIDE: Path | None = None


def arcade_root(ctx) -> Path:
    """Where depots, chunks and the launcher build go (tests point it at a temporary folder)."""
    return ROOT_OVERRIDE if ROOT_OVERRIDE is not None else ctx.state_root / "arcade"


def platform_card(store, game):
    p = store.get(f"platform/{game.get('platform', 'macos')}")
    if p is None:
        raise BuildError(f"no platform card platform/{game.get('platform', 'macos')}")
    return p


def _run(args: list[str], cwd: Path) -> None:
    try:
        p = resources.run(args, cwd=cwd, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as exc:
        raise BuildError(f"timed out: {args[0]}") from exc
    if p.returncode != 0:
        raise BuildError(f"{Path(args[0]).name} failed ({p.returncode}): {(p.stderr or p.stdout)[-3000:]}")


def _tool(probe: dict) -> str:
    ok, exe = probes.probe(probe)
    if not ok:
        raise BuildError(f"{probe.get('name')} is not available here: {exe}")
    return exe


# -- images (stdlib) ---------------------------------------------------------------------------------------------------
def png_rgba(px: bytes, w: int, h: int) -> bytes:
    rows = b"".join(b"\0" + px[y * w * 4:(y + 1) * w * 4] for y in range(h))

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))


def crop(px: bytes, w: int, x: int, y: int, cw: int, ch: int) -> bytes:
    return b"".join(px[((y + r) * w + x) * 4:((y + r) * w + x + cw) * 4] for r in range(ch))


def scale(px: bytes, w: int, h: int, nw: int, nh: int) -> bytes:
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        sy = y * h // nh
        for x in range(nw):
            sx = x * w // nw
            o, i = (y * nw + x) * 4, (sy * w + sx) * 4
            out[o:o + 4] = px[i:i + 4]
    return bytes(out)


def transparent_black(px: bytes) -> bytes:
    b = bytearray(px)
    for i in range(0, len(b), 4):
        if b[i] == 0 and b[i + 1] == 0 and b[i + 2] == 0:
            b[i + 3] = 0
    return bytes(b)


def render_media(ctx, name: str) -> dict[str, bytes]:
    """The store's pictures, drawn by the game itself (headless, in the native engine)."""
    g = G.Game(ctx, name, "native", fresh=True)
    W, H = g.w, g.h
    out: dict[str, bytes] = {}
    g.m.call("draw_icon")
    icon = transparent_black(crop(g.screen(), W, 0, 0, 128, 128))
    out["icon.png"] = png_rgba(icon, 128, 128)
    out["_icon_rgba"] = icon
    g.m.call("draw_poster")
    poster = crop(g.screen(), W, 0, 0, 180, 270)
    out["library_600x900.png"] = png_rgba(scale(poster, 180, 270, 600, 900), 600, 900)
    # the title screen, then a duel as the arcade plays it (the same inputs give the same pictures)
    g = G.Game(ctx, name, "native", fresh=True)
    b = lambda *n: G.bits(g.card, n)  # noqa: E731
    shots = {}
    # boot ends at frame 150; confirm through title, fighter select and the ladder; the round starts 100 later
    script = {220: b("confirm"), 240: b("confirm"), 250: b("confirm")}
    plan = [(352, 392, b("right")), (398, 399, b("attack", "up")), (470, 520, b("guard", "up")),
            (575, 576, b("attack", "left")), (650, 690, b("guard", "left")), (750, 751, b("heavy", "up"))]
    for a, z, bits in plan:
        for f in range(a, z):
            script[f] = bits
    want = {210: "title", 236: "select", 290: "duel_intro", 410: "duel_1", 505: "duel_2", 590: "duel_3",
            765: "duel_4"}
    for f in range(max(want) + 1):
        g.frame(script.get(f, 0), 0)
        g.drain_audio()
        if f in want:
            shots[want[f]] = g.screen()
    title = shots["title"]
    out["header_460x215.png"] = png_rgba(scale(crop(title, W, 10, 6, 460, 215), 460, 215, 460, 215), 460, 215)
    out["hero_1920x620.png"] = png_rgba(scale(crop(title, W, 0, 20, 480, 155), 480, 155, 1920, 620), 1920, 620)
    out["capsule_231x87.png"] = png_rgba(scale(crop(title, W, 0, 20, 480, 181), 480, 181, 231, 87), 231, 87)
    shots.update(_scenes(ctx, name))
    keys = ["duel_1", "string", "stage_tree", "boss_phase", "duel_4"]
    for k, key in enumerate(key for key in keys if key in shots):
        out[f"screenshot_{k + 1}.png"] = png_rgba(scale(shots[key], W, H, W * 2, H * 2), W * 2, H * 2)
    return out


def _scenes(ctx, name: str) -> dict[str, bytes]:
    """Scripted moments of the newer features: a two-hit string in versus, the arcade's duel-tree stage, and the
    boss's second phase starting (its health is set just above the phase's share, then a slash crosses it)."""
    out: dict[str, bytes] = {}
    g = G.Game(ctx, name, "native", fresh=True)
    b = lambda *n: G.bits(g.card, n)  # noqa: E731
    p1 = {200: b("down"), 204: b("down"), 210: b("confirm"), 226: b("confirm")}      # title -> versus -> fight
    p2 = {218: b("left")}
    for f in range(240):
        g.frame(p1.get(f, 0), p2.get(f, 0))
    for f in range(170):
        g.frame(b("right") if 110 <= f < 150 else 0, b("left") if 110 <= f < 150 else 0)
    for k in range(48):                              # slash_left hits; attack + up links the overhead
        g.frame(b("attack", "left") if k == 0 else (b("attack", "up") if k == 14 else 0), 0)
        g.drain_audio()
    out["string"] = g.screen()
    ladder = g.card.get("ladder") or []
    stages = {s.get("ai"): k for k, s in enumerate(ladder)}
    for key, ai in (("stage_tree", "tree"), ("boss_phase", "boss")):
        if ai not in stages:
            continue
        g = G.Game(ctx, name, "native", fresh=True)
        for f in range(240):                         # title -> arcade -> fighter -> the ladder
            g.frame({200: b("confirm"), 216: b("confirm")}.get(f, 0), 0)
        g.m.set("stage", stages[ai])
        for f in range(4):
            g.frame(b("confirm") if f == 1 else 0, 0)
        for f in range(170):
            g.frame(b("right") if 110 <= f < 140 else 0, 0)
            g.drain_audio()
        if ai == "boss":
            phases = (g.card.get("boss") or {}).get("phases") or []
            if len(phases) < 2:
                continue
            g.m.array("f_hp")[1] = g.m.array("f_hpmax")[1] * phases[1]["at"] // 100 + 1
            g.m.array("f_stance")[1] = 3
            g.m.array("f_stun")[1] = 72
            for f in range(200):
                g.frame(b("right") if f < 30 and g.m.get("round_state") != 3 else
                        (b("attack", "left") if f % 6 == 0 and g.m.get("round_state") != 3 else 0), 0)
                g.drain_audio()
                if g.m.get("round_state") == 3 and g.m.get("round_t") >= 44:
                    break
        out[key] = g.screen()
    return out


# -- the shell and the bundle ---------------------------------------------------------------------------------------
def shell_binary(ctx, plat) -> Path:
    sh = plat["effect_shell"]
    srcs = [plat.path / s for s in sh["sources"]]
    h = hashlib.sha256(json.dumps(sh, sort_keys=True).encode())
    for s in srcs:
        h.update(s.read_bytes())
    d = ctx.state_root / "arcade" / "shells" / f"{plat.name}-{h.hexdigest()[:16]}"
    out = d / "effect-shell"
    if out.is_file():
        return out
    d.mkdir(parents=True, exist_ok=True)
    exe = _tool(plat["probe"])
    tmp = d / f".building-{os.getpid()}"
    args = []
    for a in sh["compile"]:
        if a == "{srcs}":
            args += [str(s) for s in srcs]
        else:
            args.append(a.format(exe=exe, out=str(tmp)))
    _run(args, d)
    tmp.replace(out)
    return out


def spec(ctx, card, ir, lang: str) -> dict:
    em = Emitter(ctx.store, lang, ctx.ops)
    em.state(ir)
    sym = em.ident
    entry = card.get("entry") or {}
    inp = card["input"]
    return {
        "id": card.name, "title": card["title"],
        "screen": {"width": card["screen"]["width"], "height": card["screen"]["height"],
                   "scale": card["screen"].get("scale", 2), "symbol": sym(card["screen"]["array"])},
        "audio": {"rate": card["audio"]["rate"], "symbol": sym(card["audio"]["array"]),
                  "count": sym(card["audio"]["count"])},
        "save": {"symbol": sym(card["save"]["array"]), "dirty": sym(card["save"]["dirty"]),
                 "bytes": card["save"]["bytes"]},
        "entry": {"reset": sym("reset_all"), "initFn": sym(entry.get("init", "game_init")),
                  "frame": sym(entry.get("frame", "game_frame")), "quit": sym(entry.get("quit", "quit_req")),
                  "fullscreen": sym(entry.get("fullscreen", "fullscreen_req"))},
        "bits": inp["bits"], "keys": inp.get("keys", {}), "keys2": inp.get("keys2", {}),
        "gamepad": inp.get("gamepad", {}),
    }


def icns(ctx, plat, icon_rgba: bytes, d: Path) -> Path:
    ic = plat["icon"]
    iconset = d / "AppIcon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    for s in ic["sizes"]:
        for k, suffix in ((1, ""), (2, "@2x")):
            n = s * k
            (iconset / f"icon_{s}x{s}{suffix}.png").write_bytes(png_rgba(scale(icon_rgba, 128, 128, n, n), n, n))
    out = d / "AppIcon.icns"
    exe = _tool(ic["probe"])
    _run([a.format(exe=exe, out=str(out), iconset=str(iconset)) for a in ic["compile"]], d)
    return out


def _fill(v, values: dict):
    if isinstance(v, str):
        return v.format(**values)
    return v


# -- depots -----------------------------------------------------------------------------------------------------------
def manifest(content: Path, chunks: Path) -> dict:
    files = []
    total = 0
    for p in sorted(content.rglob("*")):
        if p.is_dir():
            continue
        data = p.read_bytes()
        parts = []
        for o in range(0, max(1, len(data)), CHUNK):
            part = data[o:o + CHUNK]
            hx = hashlib.sha256(part).hexdigest()
            (chunks / hx).write_bytes(part) if not (chunks / hx).exists() else None
            parts.append({"sha256": hx, "size": len(part)})
        files.append({"path": str(p.relative_to(content)), "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest(),
                      "executable": bool(p.stat().st_mode & 0o111), "chunks": parts})
        total += len(data)
    return {"files": files, "size": total, "chunks": sum(len(f["chunks"]) for f in files)}


def source_hash(ctx, card) -> str:
    """What a build of this game is made of (cheap: files, not a compile)."""
    h = hashlib.sha256(json.dumps(dict(card), sort_keys=True, default=str).encode())
    for rel in card.get("logic") or []:
        h.update((card.path / rel).read_bytes())
    plat = platform_card(ctx.store, card)
    h.update(json.dumps(dict(plat), sort_keys=True, default=str).encode())
    for s in plat["effect_shell"]["sources"]:
        h.update((plat.path / s).read_bytes())
    here = Path(__file__).parent
    for name in ("gen.py", "game.py", "build.py"):
        h.update((here / name).read_bytes())
    for fighter in card.get("fighters") or []:
        h.update(json.dumps(dict(ctx.store.get(f"fighter/{fighter}")), sort_keys=True, default=str).encode())
    from . import gen
    for m in gen.moves_of(ctx.store, list(card.get("fighters") or [])):
        h.update(json.dumps(dict(ctx.store.get(f"move/{m}")), sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def build(ctx, name: str, progress=None) -> dict:
    say = progress or (lambda step, n, msg: None)
    steps = 6
    t0 = time.time()
    card = G.game_card(ctx.store, name)
    plat = platform_card(ctx.store, card)
    say(1, steps, "compiling the cards")
    ir = G.module(ctx, name)
    lang = plat["library"]["language"]
    say(2, steps, "emitting native code and compiling it")
    lib, _ = N.build_library(ctx, ir, lang)
    say(3, steps, "building the effect shell")
    exe = shell_binary(ctx, plat)
    say(4, steps, "rendering the store media")
    media = render_media(ctx, name)
    sp = spec(ctx, card, ir, lang)
    h = hashlib.sha256(lib.read_bytes() + exe.read_bytes() + json.dumps(sp, sort_keys=True).encode()
                       + card["version"].encode())
    build_id = h.hexdigest()[:12]
    say(5, steps, "packing the bundle")
    root = arcade_root(ctx) / "depots" / card.name / f"{card['version']}+{build_id}"
    if root.exists():
        shutil.rmtree(root)
    work = root / "work"
    work.mkdir(parents=True)
    bundle = plat["bundle"]
    app_name = card["title"] + bundle.get("suffix", "")
    content = root / "content"
    app = content / app_name
    for key in ("executable_dir", "frameworks_dir", "resources_dir"):
        (app / bundle[key]).mkdir(parents=True, exist_ok=True)
    values = {"title": card["title"], "id": card.name, "version": card["version"], "build": build_id}
    shutil.copy(exe, app / bundle["executable_dir"] / card["title"])
    os.chmod(app / bundle["executable_dir"] / card["title"], 0o755)
    shutil.copy(lib, app / bundle["frameworks_dir"] / plat["library"]["file"])
    (app / bundle["resources_dir"] / bundle["spec_file"]).write_text(json.dumps(sp, indent=1), encoding="utf-8")
    shutil.copy(icns(ctx, plat, media.pop("_icon_rgba"), work), app / bundle["resources_dir"] / bundle["icon_file"])
    plist = {k: _fill(v, values) for k, v in bundle["info_plist"].items()}
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
    shutil.rmtree(work)
    say(6, steps, "writing the depot")
    chunks = arcade_root(ctx) / "chunks"
    chunks.mkdir(parents=True, exist_ok=True)
    man = manifest(content, chunks)
    mdir = root / "media"
    mdir.mkdir()
    for fname, data in media.items():
        (mdir / fname).write_bytes(data)
    info = {"id": card.name, "title": card["title"], "version": card["version"], "build": build_id,
            "source": source_hash(ctx, card),
            "app": app_name, "executable": f"{app_name}/{bundle['executable_dir']}/{card['title']}",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seconds": round(time.time() - t0, 1),
            "media": sorted(media), "save": {"dir": plat.get("saves", "").format(id=card.name),
                                              "file": "save.bin", "achievements_offset": 32}, **man}
    (root / "manifest.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    (arcade_root(ctx) / "depots" / card.name / "latest").write_text(root.name, encoding="utf-8")
    return info


def latest(ctx, name: str) -> Path | None:
    p = arcade_root(ctx) / "depots" / name / "latest"
    if not p.is_file():
        return None
    root = p.parent / p.read_text(encoding="utf-8").strip()
    return root if (root / "manifest.json").is_file() else None


__all__ = ["BuildError", "arcade_root", "build", "latest", "manifest", "render_media", "source_hash"]
