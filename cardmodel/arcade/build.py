"""build — a game card to a native package and a depot the launcher downloads.

    game card ──gen + card language──▶ card-IR module ──language card──▶ shared library
    platform card's effect shell ──its compile command──▶ executable
    the game's own drawings (icon, poster, title, duels played headless) ──▶ store media
    all of it ──▶ a bundle (the platform card's layout) ──▶ depot: a manifest of files split into chunks
    stored by SHA-256 (the launcher fetches chunks, checks every hash, assembles the files)

Nothing here knows a language or a platform: the language card says how to compile the module, the platform
card how to compile its shell and lay out the package. A build is identified by the hash of what went into
it, so a new card version (or any change) is a new build the launcher sees as an update.

Every game builds for any platform card. A platform card may have targets (platform/ios: the iOS Simulator, a
real iPhone or iPad, Mac Catalyst); a build names one by its key, ``ios-iphonesimulator`` (a card without
targets is its own key, ``macos``). The target says the values its commands name ({sdk}, {triple}: literals,
what a command prints, what a probe finds), the environment they run in, and may override any of the card's
sections (bundle, icon, ...). A game's own platform (its card's ``platform``, macOS) keeps the depot pointer
``latest``; every other key has ``latest@KEY`` beside it. The store pictures are the same on every platform.

Honest limits (L1): macOS packages carry only the linker's ad-hoc signature (iOS ones are signed as their
target says: ad hoc for the Simulator and Mac Catalyst, with the user's identity for a device); the store
pictures are fixed moments of a scripted run, not chosen shots.
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
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


def platform_card(store, game, platform: str | None = None):
    """The platform card a build is for: the one ``platform`` (a key, ``ios-iphonesimulator``) names, else the game's."""
    name = (platform or "").split("-", 1)[0] or game.get("platform", "macos")
    p = store.get(f"platform/{name}")
    if p is None:
        raise BuildError(f"no platform card platform/{name}")
    return p


def resolve_platform(store, game, platform: str | None = None) -> tuple:
    """(platform card, target name or None, key) for a build of game; no target named: the card's default one."""
    plat = platform_card(store, game, platform)
    names = list(plat.get("targets") or {})
    target = platform.split("-", 1)[1] if platform and "-" in platform else None
    if names:
        target = target or plat.get("default_target") or names[0]
        if target not in names:
            raise BuildError(f"platform/{plat.name} has no target {target} (it has {', '.join(names)})")
    elif target:
        raise BuildError(f"platform/{plat.name} has no targets")
    return plat, target, f"{plat.name}-{target}" if target else plat.name


def home_key(store, game) -> str:
    """The key of the game's own platform: its builds keep the depot pointer ``latest``."""
    return resolve_platform(store, game)[2]


def platform_arg(store, game, platform: str | None) -> str | None:
    """A requested platform as builds and depots name it: None for the game's own (``latest``), else its key."""
    if not platform:
        return None
    key = resolve_platform(store, game, platform)[2]
    return None if key == home_key(store, game) else key


def _merge(base, over):
    if not isinstance(base, dict) or not isinstance(over, dict):
        return over
    out = dict(base)
    for k, v in over.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = _merge(base.get(k), v)
    return out


def section(plat, target: str | None, key: str):
    """A platform card's section as one of its targets has it (a target may override any part; null drops a key)."""
    t = ((plat.get("targets") or {}).get(target) or {}) if target else {}
    return _merge(plat.get(key), t[key]) if key in t else plat.get(key)


_RESOLVED: dict = {}


def target_values(plat, target: str | None) -> tuple[dict, dict]:
    """The values a platform card's commands name for one of its targets, and the environment they run in.
    ``{exe}`` is the card's probe, each of its ``tools`` is its own name; a target's value is a string or a list
    (placeholders filled from the others), {"run": command} (what it prints) or {"probe": probe} (what it finds).
    A value that cannot be had stops the build with what the target ``needs``."""
    key = (plat.name, target, json.dumps(dict(plat), sort_keys=True, default=str))
    if key in _RESOLVED:
        return _RESOLVED[key]
    t = ((plat.get("targets") or {}).get(target) or {}) if target else {}
    need = t.get("needs") or f"what platform/{plat.name} names"
    values: dict = {"exe": _tool(plat["probe"])}
    for name, probe in (plat.get("tools") or {}).items():
        values[name] = _tool(probe)
    env = dict(os.environ)

    def got(v):
        if "probe" in v:
            ok, detail = probes.probe(v["probe"])
            if not ok:
                raise BuildError(f"{plat.name} {target}: needs {need} ({detail})")
            return detail
        args = [a.format(**values) for a in v["run"]]
        try:
            p = resources.run(args, timeout=120, heavy=False, env=env, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BuildError(f"{plat.name} {target}: needs {need} ({exc})") from exc
        if p.returncode != 0:
            raise BuildError(f"{plat.name} {target}: needs {need} ({' '.join(args)}: {(p.stderr or p.stdout).strip()[-400:]})")
        return p.stdout.strip()

    for k, v in (t.get("env") or {}).items():
        env[k] = got(v) if isinstance(v, dict) else str(v)
    later = {}
    for k, v in (t.get("values") or {}).items():
        if isinstance(v, dict):
            values[k] = got(v)
        else:
            later[k] = v
    for k, v in later.items():
        values[k] = _fill(v, values)
    _RESOLVED[key] = (values, env)
    return values, env


def _args(template: list, values: dict) -> list[str]:
    """A command from a card: each "{name}" filled in; an argument that is only "{name}" of a list is the list."""
    out = []
    for a in template:
        m = re.fullmatch(r"\{(\w+)\}", a)
        if m and isinstance(values.get(m.group(1)), list):
            out += [str(x) for x in values[m.group(1)]]
        else:
            out.append(a.format(**values))
    return out


def ident(gid: str) -> str:
    """An arcade id as a bundle identifier may spell it (letters, digits, hyphens and dots)."""
    return re.sub(r"[^A-Za-z0-9.-]", "-", gid)


def _run(args: list[str], cwd: Path, env: dict | None = None) -> None:
    try:
        p = resources.run(args, cwd=cwd, timeout=TIMEOUT_S, stdin=subprocess.DEVNULL, env=env)
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
def shell_binary(ctx, plat, target: str | None = None) -> Path:
    sh = section(plat, target, "effect_shell")
    srcs = [plat.path / s for s in sh["sources"]]
    values, env = target_values(plat, target)
    h = hashlib.sha256(json.dumps(sh, sort_keys=True).encode())
    if target:
        h.update(json.dumps(values, sort_keys=True, default=str).encode())
    for s in srcs:
        h.update(s.read_bytes())
    d = ctx.state_root / "arcade" / "shells" / f"{plat.name}{'-' + target if target else ''}-{h.hexdigest()[:16]}"
    out = d / "effect-shell"
    if out.is_file():
        return out
    d.mkdir(parents=True, exist_ok=True)
    tmp = d / f".building-{os.getpid()}"
    _run(_args(sh["compile"], {**values, "out": str(tmp), "srcs": [str(s) for s in srcs]}), d, env)
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


def icns(ctx, plat, icon_rgba: bytes, d: Path, target: str | None = None) -> Path:
    ic = section(plat, target, "icon")
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


def icon(ctx, plat, target: str | None, icon_rgba: bytes, work: Path, app: Path, bundle: dict) -> None:
    """The app's icon as the platform card says: an icon file its tool compiles (``compile``), or PNG files of the
    sizes it names (``files``), in the bundle's resources folder."""
    ic = section(plat, target, "icon") or {}
    res = app / bundle["resources_dir"]
    if ic.get("compile"):
        shutil.copy(icns(ctx, plat, icon_rgba, work, target), res / bundle["icon_file"])
    for fname, n in (ic.get("files") or {}).items():
        (res / fname).write_bytes(png_rgba(scale(icon_rgba, 128, 128, n, n), n, n))


def _fill(v, values: dict):
    if isinstance(v, str):
        return v.format(**values)
    if isinstance(v, list):
        return [_fill(x, values) for x in v]
    if isinstance(v, dict):
        return {k: _fill(x, values) for k, x in v.items()}
    return v


def sign(plat, target: str | None, paths: list[Path]) -> None:
    """Sign as the platform card's ``sign`` says (inner code first): nothing for a card without one."""
    s = section(plat, target, "sign")
    if not s:
        return
    values, env = target_values(plat, target)
    for p in paths:
        _run(_args(s["args"], {**values, "path": str(p)}), p.parent, env)


def media_for(ctx, name: str, ir: dict, render, card=None) -> dict[str, bytes]:
    """The store's pictures: the same on every platform (the module draws them headless on this machine), so they
    are kept by the hash of what draws them (the module, the card, the arcade code that frames them) and drawn once."""
    h = hashlib.sha256(json.dumps(ir, sort_keys=True, default=str).encode())
    h.update(json.dumps(dict(card) if card is not None else {}, sort_keys=True, default=str).encode())
    for fname in ("build.py", "system.py"):
        h.update((Path(__file__).parent / fname).read_bytes())
    key = h.hexdigest()[:20]
    d = ctx.state_root / "arcade" / "media" / f"{name}-{key}"
    if (d / ".done").is_file():
        return {p.name: p.read_bytes() for p in sorted(d.iterdir()) if p.name != ".done"}
    media = render()
    d.mkdir(parents=True, exist_ok=True)
    for fname, data in media.items():
        (d / fname).write_bytes(data)
    (d / ".done").write_text("", encoding="utf-8")
    return media


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


def platform_hash(h, store, card, platform: str | None) -> None:
    """What a build takes from its platform card: the card and its shell's sources (and the target it builds for)."""
    plat, target, key = resolve_platform(store, card, platform)
    h.update(json.dumps(dict(plat), sort_keys=True, default=str).encode())
    if platform_arg(store, card, platform):
        h.update(key.encode())
    for s in section(plat, target, "effect_shell")["sources"]:
        h.update((plat.path / s).read_bytes())


def source_hash(ctx, card, platform: str | None = None) -> str:
    """What a build of this game is made of (cheap: files, not a compile)."""
    h = hashlib.sha256(json.dumps(dict(card), sort_keys=True, default=str).encode())
    for rel in card.get("logic") or []:
        h.update((card.path / rel).read_bytes())
    platform_hash(h, ctx.store, card, platform)
    here = Path(__file__).parent
    for name in ("gen.py", "game.py", "build.py"):
        h.update((here / name).read_bytes())
    for fighter in card.get("fighters") or []:
        h.update(json.dumps(dict(ctx.store.get(f"fighter/{fighter}")), sort_keys=True, default=str).encode())
    from . import gen
    for m in gen.moves_of(ctx.store, list(card.get("fighters") or [])):
        h.update(json.dumps(dict(ctx.store.get(f"move/{m}")), sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def native_parts(ctx, card, ir, platform: str | None, say, steps: int = 6) -> tuple:
    """Steps 2 and 3 of a build: the module through the platform's language card (with its target's flags), and the
    platform's effect shell. Returns (library, shell, language)."""
    plat, target, _ = resolve_platform(ctx.store, card, platform)
    values, env = target_values(plat, target)
    lib_spec = section(plat, target, "library")
    say(2, steps, "emitting native code and compiling it")
    lib, _ = N.build_library(ctx, ir, lib_spec["language"], flags=_args(lib_spec.get("flags") or [], values) or None,
                             env=env if target else None)
    say(3, steps, "building the effect shell")
    return lib, shell_binary(ctx, plat, target), lib_spec["language"]


def pack(ctx, gid: str, card, platform: str | None, lib: Path, exe: Path, sp: dict, media: dict, say, t0: float,
         source: str, save: dict, extra: dict | None = None) -> dict:
    """Steps 5 and 6 of a build (a game's or a console player's): the package in the platform card's layout, signed
    as it says, then the depot (its files split into chunks named by their SHA-256) and the pointer to it."""
    steps = 6
    plat, target, key = resolve_platform(ctx.store, card, platform)
    media = dict(media)
    h = hashlib.sha256(lib.read_bytes() + exe.read_bytes() + json.dumps(sp, sort_keys=True).encode()
                       + card["version"].encode())
    build_id = h.hexdigest()[:12]
    say(5, steps, "packing the bundle")
    root = arcade_root(ctx) / "depots" / gid / f"{card['version']}+{build_id}"
    if root.exists():
        shutil.rmtree(root)
    work = root / "work"
    work.mkdir(parents=True)
    bundle = section(plat, target, "bundle")
    app_name = card["title"] + bundle.get("suffix", "")
    content = root / "content"
    app = content / app_name
    for k in ("executable_dir", "frameworks_dir", "resources_dir"):
        (app / bundle[k]).mkdir(parents=True, exist_ok=True)
    values = {**(target_values(plat, target)[0] if target else {}), "title": card["title"], "id": gid,
              "ident": ident(gid), "version": card["version"], "build": build_id}
    shutil.copy(exe, app / bundle["executable_dir"] / card["title"])
    os.chmod(app / bundle["executable_dir"] / card["title"], 0o755)
    lib_file = app / bundle["frameworks_dir"] / section(plat, target, "library")["file"]
    shutil.copy(lib, lib_file)
    (app / bundle["resources_dir"] / bundle["spec_file"]).write_text(json.dumps(sp, indent=1), encoding="utf-8")
    icon(ctx, plat, target, media.pop("_icon_rgba"), work, app, bundle)
    (app / bundle.get("plist", "Contents/Info.plist")).write_bytes(plistlib.dumps(_fill(bundle["info_plist"], values)))
    shutil.rmtree(work)
    sign(plat, target, [lib_file, app])
    say(6, steps, "writing the depot")
    chunks = arcade_root(ctx) / "chunks"
    chunks.mkdir(parents=True, exist_ok=True)
    man = manifest(content, chunks)
    mdir = root / "media"
    mdir.mkdir()
    for fname, data in media.items():
        (mdir / fname).write_bytes(data)
    info = {"id": gid, "title": card["title"], "version": card["version"], "build": build_id, "source": source,
            **(extra or {}), "platform": key,
            "app": app_name, "executable": "/".join(p for p in (app_name, bundle["executable_dir"], card["title"]) if p),
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seconds": round(time.time() - t0, 1),
            "media": sorted(media), "save": {"dir": (section(plat, target, "saves") or "").format(id=gid), **save}, **man}
    (root / "manifest.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    pointer(ctx, gid, platform_arg(ctx.store, card, platform)).write_text(root.name, encoding="utf-8")
    return info


def build(ctx, name: str, progress=None, platform: str | None = None) -> dict:
    """The game for its own platform, or for the one ``platform`` names (a key: ``ios``, ``ios-iphonesimulator``)."""
    say = progress or (lambda step, n, msg: None)
    steps = 6
    t0 = time.time()
    card = G.game_card(ctx.store, name)
    plat, target, _ = resolve_platform(ctx.store, card, platform)
    target_values(plat, target)                     # what the target needs, before the long steps
    say(1, steps, "compiling the cards")
    ir = G.module(ctx, name)
    lib, exe, lang = native_parts(ctx, card, ir, platform, say, steps)
    say(4, steps, "rendering the store media")
    media = media_for(ctx, card.name, ir, lambda: render_media(ctx, name), card)
    sp = spec(ctx, card, ir, lang)
    return pack(ctx, card.name, card, platform, lib, exe, sp, media, say, t0, source=source_hash(ctx, card, platform),
                save={"file": "save.bin", "achievements_offset": 32})


def pointer(ctx, name: str, platform: str | None = None) -> Path:
    """The file naming a program's latest build: ``latest`` for its own platform, ``latest@KEY`` for another."""
    return arcade_root(ctx) / "depots" / name / ("latest" if not platform else f"latest@{platform}")


def latest(ctx, name: str, platform: str | None = None) -> Path | None:
    p = pointer(ctx, name, platform)
    if not p.is_file():
        return None
    root = p.parent / p.read_text(encoding="utf-8").strip()
    return root if (root / "manifest.json").is_file() else None


__all__ = ["BuildError", "arcade_root", "build", "home_key", "latest", "manifest", "media_for", "native_parts", "pack",
           "platform_arg", "pointer", "render_media", "resolve_platform", "section", "source_hash", "target_values"]
