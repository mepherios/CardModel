"""system — a console as an arcade player: a system card's machine plus its card-language player, built into a
native package and a depot exactly like a game (cardmodel/arcade/build.py), so the launcher installs and updates it.

    system card ──▶ the machine card's sources (machine/build.py) + the cartridge tables generated from the card it
    names + the system's own logic (player.card) ──▶ one card-IR module ──language card──▶ shared library
    the platform card's effect shell + game.json (with the cartridge, the clock and the flush entry) ──▶ the app

The player is shared by every cartridge of the system: the launcher starts it with ``--rom PATH`` (the shell
reads the file, a .zip in memory, and hands the bytes to the module) and a save folder per cartridge.

Honest limits (L1): one system so far (the Game Boy / Color); the machine runs in the interpreter (no lifted
blocks, which are per cartridge); the player's store pictures are its own drawing, not the games'.
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import time
from pathlib import Path

from ..kernel.canon import card_hash
from ..lang.compile import compile_sources
from ..machine import build as Bd
from ..machine import native as N
from . import build as B

ID_SUFFIX = "_player"


def system_card(store, name: str):
    """A system card by its name or by its arcade id (``gameboy_player``)."""
    base = name[:-len(ID_SUFFIX)] if name.endswith(ID_SUFFIX) else name
    card = store.get(base if "/" in base else f"system/{base}")
    if card is None:
        raise KeyError(f"no system card system/{base}")
    return card


def arcade_id(card) -> str:
    return card.name + ID_SUFFIX


def is_system(store, gid: str) -> bool:
    return gid.endswith(ID_SUFFIX) and store.get(f"system/{gid[:-len(ID_SUFFIX)]}") is not None


def tables(ctx, card) -> str:
    """The cartridge card's tables as card-language arrays (the language has no records): per type byte its
    controller kind and features, the RAM size codes, the multicart signature, the player's sample rate. A system
    card without ``tables`` (its player reads its cartridge's layout through card constants) gets the rate only."""
    if not card.get("tables"):
        return f"const PLAYER_RATE = {int(card['audio']['rate'])}\n"
    cc = ctx.store.get(card["tables"])
    kinds = cc.get("mbc_kind") or {}
    types = cc.get("types") or {}
    rows = {k: [0] * 256 for k in ("kind", "ram", "battery", "rtc")}
    for t in range(256):
        info = types.get(f"0x{t:02X}") or {}
        rows["kind"][t] = int(kinds.get(info.get("mbc"), 0)) if not info.get("unsupported") else 0
        for k in ("ram", "battery", "rtc"):
            rows[k][t] = 1 if info.get(k) else 0
    sizes = [int((cc.get("ram_size_bytes") or {}).get(str(c), 0)) for c in range(8)]
    multi = cc.get("mbc1_multicart") or {}
    lo, hi = (multi.get("logo") or [0, 0])[:2]

    def arr(name, vals):
        return f"array {name}: Int[{len(vals)}] = [{', '.join(str(v) for v in vals)}]"

    return "\n".join([
        f"-- generated from {cc.qualified} by cardmodel/arcade/system.py: what each cartridge type byte is",
        arr("cart_kind", rows["kind"]), arr("cart_ram", rows["ram"]), arr("cart_battery", rows["battery"]),
        arr("cart_rtc", rows["rtc"]), arr("cart_ram_size", sizes),
        f"const CART_RAM_UNSIZED = {int(cc.get('ram_unsized_bytes') or 0)}",
        f"const CART_MULTI_BYTES = {int(multi.get('rom_bytes') or 0)}",
        f"const CART_LOGO_LO = {int(lo)}", f"const CART_LOGO_HI = {int(hi)}",
        f"const CART_LOGO2 = {int(multi.get('second_logo_at') or 0)}",
        f"const PLAYER_RATE = {int(card['audio']['rate'])}", ""])


def sources(ctx, card) -> tuple[list, dict]:
    srcs, externs, _ = Bd.sources(ctx.store, card["machine"])
    srcs = srcs + [(tables(ctx, card), f"{card.qualified} (generated tables)")]
    for rel in card.get("logic") or []:
        srcs.append(((card.path / rel).read_text(encoding="utf-8"), f"{card.qualified}/{rel}"))
    return srcs, externs


_CARD_REF = re.compile(r"\bcard\.([A-Za-z_]\w*)\.([A-Za-z_]\w*)")


def module(ctx, name: str, use_cache: bool = True) -> dict:
    card = system_card(ctx.store, name)
    srcs, externs = sources(ctx, card)
    h = hashlib.sha256()
    for text, label in srcs:
        h.update(label.encode() + b"\0" + text.encode() + b"\0")
    h.update(json.dumps(externs, sort_keys=True).encode())
    # constants read from card data (`const X = card.registry.name.field`) are compiled in, so the cards they
    # read are part of the key: a store with other values (a test's stand-in card) must not reuse this build
    for ref in sorted({m.group(1) + "/" + m.group(2) for text, _ in srcs for m in _CARD_REF.finditer(text)}):
        ref_card = ctx.store.get(ref)
        h.update(ref.encode() + b"\0" + (card_hash(ref_card) if ref_card is not None else "-").encode() + b"\0")
    h.update(Path(__file__).read_bytes())
    h.update(Path(Bd.__file__).read_bytes())
    key = h.hexdigest()[:20]
    cache = ctx.state_root / "arcade" / f"system-{card.name}-{key}.json"
    if use_cache and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    mod = compile_sources(srcs, ctx.ops, ctx.store, name=arcade_id(card), externs=externs)
    ir = mod.ir_module((card.get("entry") or {}).get("frame"))
    ir["functions"].append(Bd.reset_function(ir))
    for x in (*ir.get("globals", []), *ir.get("arrays", [])):
        x["export"] = True
    ir["system"] = card.name
    ir["hash"] = key
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(ir), encoding="utf-8")
    tmp.replace(cache)
    return ir


class Player:
    """The player headless (tests, the library's title screens, the store check, cartapp's witness): a cartridge in,
    frames out, in any engine. ``machine`` is a loaded module to use (``start`` inserts the next cartridge into it);
    ``ir`` is its module when it is not the plain player's (lifted code)."""

    def __init__(self, ctx, name: str, rom: bytes, engine: str = "native", fresh: bool = False, clock: int = 0,
                 save: bytes | None = None, machine=None, ir: dict | None = None):
        self.ctx = ctx
        self.card = system_card(ctx.store, name)
        # machine: a loaded module to reuse (the store check) or one with lifted code (cartapp, with its ir)
        self.ir = ir if ir is not None else (machine.ir if machine is not None else module(ctx, name))
        self.m = machine if machine is not None else N.load(ctx, self.ir, engine, fresh=fresh)
        self.start(rom, clock=clock, save=save)

    def start(self, rom: bytes, clock: int = 0, save: bytes | None = None) -> None:
        """What the shell does before the first frame: reset, the cartridge's bytes in (the whole array, since
        reset_all leaves the big arrays to the host), decode them, the save and the clock, init."""
        c = self.card
        self.m.call("reset_all")
        cart = c["cartridge"]
        cap = int(cart["bytes"])
        data = rom[:cap]
        self.m.write(cart["array"], data + bytes(cap - len(data)))
        self.m.call(cart["load"], len(data))
        if save:
            self.m.write(c["save"]["array"], save[:int(c["save"]["bytes"])])
        self.m.set(c["clock"], clock)
        self.m.call(c["entry"]["init"])

    def frame(self, buttons: int = 0) -> int:
        return self.m.call(self.card["entry"]["frame"], buttons, 0)

    def rgba(self) -> bytes:
        return self.m.read(self.card["screen"]["array"])

    def rgb(self) -> bytes:
        px = self.rgba()
        return b"".join(px[i:i + 3] for i in range(0, len(px), 4))

    def drain_audio(self) -> bytes:
        a = self.card["audio"]
        n = self.m.get(a["count"])
        data = self.m.read(a["array"], 0, n) if n else b""
        self.m.set(a["count"], 0)
        return data


def _num(v):
    """card data writes addresses and bytes as "0x.." strings; anything else (a label) stays as it is"""
    if isinstance(v, str) and v.lower().startswith("0x"):
        return int(v, 16)
    if isinstance(v, list):
        return [_num(x) for x in v]
    return v


def check_cartridge(ctx, name: str) -> dict | None:
    """The system card's check cartridge, assembled from the instruction cards: no one's game, so the store check
    can launch the installed player when no library lists a cartridge. {file, bytes, save: {offset, byte}}."""
    from ..machine import asm
    card = system_card(ctx.store, name)
    c = card.get("check_cartridge")
    if not c:
        return None
    isa = c.get("isa", "lr35902")
    if isa == "armv5te":                     # a DS image: its ARM9 does the card's stores, then idles
        from ..machine import nds
        data = nds.check_image(ctx.store, [tuple(_num(x) for x in it) for it in c["stores"]],
                               title=c.get("title", "CARDCHECK"), code=c.get("game_code", "CMCK"))
    else:
        items = [tuple(_num(x) for x in it) for it in c["program"]]
        extra = {int(a, 16): asm.assemble(ctx.store, [tuple(_num(x) for x in it) for it in prog], org=int(a, 16),
                                          isa=isa)
                 for a, prog in (c.get("at") or {}).items()}
        data = asm.rom(ctx.store, items, title=c.get("title", "CARDCHECK"), cart_type=_num(c.get("cart_type", "0x00")),
                       ram_size_code=int(c.get("ram_size_code", 0)), extra=extra)
    save = c.get("save") or {}
    return {"file": c.get("file", "check.gb"), "bytes": data,
            "save": {"offset": _num(save["offset"]), "byte": _num(save["byte"])} if save else None}


def spec(ctx, card, ir, lang: str) -> dict:
    """game.json for the shell: the game card fields build.spec writes, plus the cartridge, clock and flush."""
    em = B.Emitter(ctx.store, lang, ctx.ops)
    em.state(ir)
    sym = em.ident
    entry = card["entry"]
    inp = card["input"]
    cart = card["cartridge"]
    return {
        "id": arcade_id(card), "title": card["title"],
        "screen": {"width": card["screen"]["width"], "height": card["screen"]["height"],
                   "scale": card["screen"].get("scale", 2), "symbol": sym(card["screen"]["array"])},
        "audio": {"rate": card["audio"]["rate"], "symbol": sym(card["audio"]["array"]),
                  "count": sym(card["audio"]["count"])},
        "save": {"symbol": sym(card["save"]["array"]), "dirty": sym(card["save"]["dirty"]),
                 "bytes": card["save"]["bytes"]},
        "entry": {"reset": sym("reset_all"), "initFn": sym(entry["init"]), "frame": sym(entry["frame"]),
                  "quit": sym(entry["quit"]), "fullscreen": sym(entry["fullscreen"])},
        "bits": inp["bits"], "keys": inp.get("keys", {}), "keys2": inp.get("keys2", {}),
        "gamepad": inp.get("gamepad", {}),
        "cartridge": {"symbol": sym(cart["array"]), "bytes": cart["bytes"], "load": sym(cart["load"]),
                      "extensions": cart.get("extensions", []), "zip": bool(cart.get("zip"))},
        "clock": sym(card["clock"]),
        **({"clockOffset": sym(card["clock_offset"])} if card.get("clock_offset") else {}),
        "flush": sym("player_flush"),
        **({"pointer": {"x": sym(card["pointer"]["x"]), "y": sym(card["pointer"]["y"]),
                        "down": sym(card["pointer"]["down"]), "area": card["pointer"]["area"]}}
           if card.get("pointer") else {}),
    }


def render_media(ctx, name: str) -> dict[str, bytes]:
    """The store's pictures: the player's own drawing (player_draw_art), framed for each slot."""
    card = system_card(ctx.store, name)
    m = N.load(ctx, module(ctx, name), "native", fresh=True)
    m.call("reset_all")
    m.call("player_draw_art")
    W, H = card["screen"]["width"], card["screen"]["height"]
    art = m.read(card["screen"]["array"])
    out: dict[str, bytes] = {}
    icon = B.scale(B.crop(art, W, 16, 8, 128, 128), 128, 128, 128, 128)
    out["_icon_rgba"] = icon
    out["icon.png"] = B.png_rgba(icon, 128, 128)

    def framed(w, h):
        """the art scaled to fit w x h, centred on the art's own ground colour"""
        k = min(w / W, h / H)
        sw, sh = max(1, int(W * k)), max(1, int(H * k))
        big = B.scale(art, W, H, sw, sh)
        bg = art[0:4]
        canvas = bytearray(bg * (w * h))
        ox, oy = (w - sw) // 2, (h - sh) // 2
        for y in range(sh):
            o = ((oy + y) * w + ox) * 4
            canvas[o:o + sw * 4] = big[y * sw * 4:(y + 1) * sw * 4]
        return B.png_rgba(bytes(canvas), w, h)

    for fname, (w, h) in {"library_600x900.png": (600, 900), "header_460x215.png": (460, 215),
                          "hero_1920x620.png": (1920, 620), "capsule_231x87.png": (231, 87),
                          "screenshot_1.png": (W * 2, H * 2)}.items():
        out[fname] = framed(w, h)
    return out


def source_hash(ctx, card) -> str:
    h = hashlib.sha256(json.dumps(dict(card), sort_keys=True, default=str).encode())
    for text, label in sources(ctx, card)[0]:
        h.update(label.encode() + text.encode())
    plat = B.platform_card(ctx.store, card)
    h.update(json.dumps(dict(plat), sort_keys=True, default=str).encode())
    for s in plat["effect_shell"]["sources"]:
        h.update((plat.path / s).read_bytes())
    here = Path(__file__).parent
    for fname in ("system.py", "build.py"):
        h.update((here / fname).read_bytes())
    return h.hexdigest()[:16]


def build(ctx, name: str, progress=None) -> dict:
    """The player as a depot, in the same layout as a game's (build.build), under its arcade id."""
    say = progress or (lambda step, n, msg: None)
    steps = 6
    t0 = time.time()
    card = system_card(ctx.store, name)
    gid = arcade_id(card)
    plat = B.platform_card(ctx.store, card)
    say(1, steps, "compiling the machine's cards")
    ir = module(ctx, name)
    lang = plat["library"]["language"]
    say(2, steps, "emitting native code and compiling it")
    lib, _ = N.build_library(ctx, ir, lang)
    say(3, steps, "building the effect shell")
    exe = B.shell_binary(ctx, plat)
    say(4, steps, "drawing the store pictures")
    media = render_media(ctx, name)
    sp = spec(ctx, card, ir, lang)
    h = hashlib.sha256(lib.read_bytes() + exe.read_bytes() + json.dumps(sp, sort_keys=True).encode()
                       + card["version"].encode())
    build_id = h.hexdigest()[:12]
    say(5, steps, "packing the bundle")
    root = B.arcade_root(ctx) / "depots" / gid / f"{card['version']}+{build_id}"
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
    values = {"title": card["title"], "id": gid, "version": card["version"], "build": build_id}
    shutil.copy(exe, app / bundle["executable_dir"] / card["title"])
    os.chmod(app / bundle["executable_dir"] / card["title"], 0o755)
    shutil.copy(lib, app / bundle["frameworks_dir"] / plat["library"]["file"])
    (app / bundle["resources_dir"] / bundle["spec_file"]).write_text(json.dumps(sp, indent=1), encoding="utf-8")
    shutil.copy(B.icns(ctx, plat, media.pop("_icon_rgba"), work), app / bundle["resources_dir"] / bundle["icon_file"])
    plist = {k: B._fill(v, values) for k, v in bundle["info_plist"].items()}
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
    shutil.rmtree(work)
    say(6, steps, "writing the depot")
    chunks = B.arcade_root(ctx) / "chunks"
    chunks.mkdir(parents=True, exist_ok=True)
    man = B.manifest(content, chunks)
    mdir = root / "media"
    mdir.mkdir()
    for fname, data in media.items():
        (mdir / fname).write_bytes(data)
    info = {"id": gid, "title": card["title"], "version": card["version"], "build": build_id,
            "source": source_hash(ctx, card), "kind": "system", "system": card.name,
            "app": app_name, "executable": f"{app_name}/{bundle['executable_dir']}/{card['title']}",
            "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "seconds": round(time.time() - t0, 1),
            "media": sorted(media), "save": {"dir": plat.get("saves", "").format(id=gid), "file": "save.bin"}, **man}
    (root / "manifest.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    (B.arcade_root(ctx) / "depots" / gid / "latest").write_text(root.name, encoding="utf-8")
    return info


__all__ = ["ID_SUFFIX", "Player", "arcade_id", "build", "check_cartridge", "is_system", "module", "render_media",
           "source_hash", "spec", "system_card", "tables"]
