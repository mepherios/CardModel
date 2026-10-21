"""cartapp — one cartridge as an app of its own, its code lifted into cards (`cardmodel arcade app ROM`).

The Game Boy Player (system/gameboy: the machine cards plus player.card) with the cartridge's own code lifted
into card IR (machine/lift.py: every block the profile found, every instruction of a block an entry, the code
the cartridge copies into RAM), compiled natively in parts and packed with the platform card's shell as
``<title>.app``. The cartridge is read where it is when the app starts (never copied). Saves go where the
arcade's library keeps that cartridge's (``~/Library/Application Support/Cardmodel Arcade/saves/<id>``), so the
app and the library play the same save. The app keeps, beside the save, what the interpreter still had to run
while you played (``profile-*.bin``); the next build of the app lifts that too.

    cardmodel arcade app ROM [--install]          the app (in state/arcade/cartapps; --install: ~/Applications)

Before packing, the app's module plays the cartridge headless next to the plain player, frame by frame with the
same buttons (a witness: the pictures and the sound must be equal), and its purity is measured there: the share
of instructions that ran as lifted card IR rather than in the instruction-at-a-time interpreter.

Honest limits (L1): code no profile reached runs in the interpreter until a build after you played it; the
profile's exploration presses buttons by a seeded rule, it does not play the game; the witness is equality on
its frames, not a proof; Game Boy and Game Boy Color cartridges only.
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import time
from pathlib import Path

from ..engines.codegen import Emitter
from ..machine import build as Bd
from ..machine import gb as G
from ..machine import lift
from ..machine import native as N
from ..machine.survey import script as survey_script
from . import build as B
from . import library as L
from . import system as S

SYSTEM = "gameboy"
EXPLORE_FRAMES = 30000             # 8 1/3 minutes of the cartridge's time, a few seconds of the interpreter's
WITNESS_FRAMES = 2400
BUTTONS = (0x10, 0x10, 0x10, 0x80, 0x20, 0x04, 0x08, 0x02, 0x01, 0x04, 0x08, 0x10)   # A most often, START, B, moves
# what the app keeps beside the save while it is played: (array, file, how a new session merges in)
KEEP = (("seen", "profile-seen.bin", "or"), ("entries", "profile-entries.bin", "or"),
        ("ram_seen", "profile-ram-seen.bin", "or"), ("ram_code", "profile-ram-code.bin", "copy"))


def explore(seed: int):
    """Buttons for a profile run: the survey's START and A presses for the first 30 s, then a seeded walk (a
    button or a direction held 6 frames in 10, A most often), so dialogs and menus move on and maps get walked."""
    def press(i: int) -> int:
        if i < 1800:
            return survey_script(i)
        k = i // 10
        if i % 10 >= 6:
            return 0
        r = (((k + seed * 7919) * 1103515245 + 12345) & 0x7FFFFFFF) >> 8
        return BUTTONS[r % len(BUTTONS)]
    return press


def saves_dir(rom_id: str) -> Path:
    return Path.home() / "Library" / "Application Support" / "Cardmodel Arcade" / "saves" / rom_id


def apps_dir() -> Path:
    return Path.home() / "Applications" / "Cardmodel Games"


def rom_size(rom: bytes) -> int:
    size = 0x8000
    while size < len(rom):
        size <<= 1
    return size


def lifted_player(ctx, rom: bytes, row: dict, say=lambda msg: None) -> tuple[dict, dict]:
    """The player module with the cartridge's lifted code: (module, the lift's report). The profile is the
    survey's run, a long seeded exploration, and what the app kept from being played."""
    machine_ir = Bd.module(ctx, SYSTEM)
    d = lift.cache_dir(ctx, row["sha1"], machine_ir["hash"])
    marker = d / f"explored-{EXPLORE_FRAMES}"
    if not marker.is_file():
        say(f"profiling: {EXPLORE_FRAMES:,} frames of seeded play in the interpreter")
        lift.add_profile(d, lift.profile(ctx, rom, 1800))
        lift.add_profile(d, lift.profile(ctx, rom, EXPLORE_FRAMES, script=explore(1)))
        marker.write_text("1", encoding="utf-8")
    sd = saves_dir(row["id"])
    played = {name: (sd / f).read_bytes() for name, f, _ in KEEP if (sd / f).is_file()}
    if played:
        say("adding what the app ran in the interpreter while it was played")
        lift.add_profile(d, played)
    prof = lift.stored_profile(d)
    bc = d / "blocks.json"
    cache = json.loads(bc.read_text(encoding="utf-8")) if bc.is_file() else {}
    n0 = len(cache)
    say("lifting the cartridge's code into card IR")
    blocks, ram, rep = lift.lift_blocks(ctx, rom, rom_size(rom) - 1, prof["seen"], prof["entries"], SYSTEM, cache,
                                        prof["ram_seen"], prof["ram_code"])
    if len(cache) != n0:
        tmp = bc.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(bc)
    player = S.module(ctx, SYSTEM)
    mod = lift.lifted_module(player, blocks, ram)
    h = hashlib.sha256()
    for part in (player["hash"], machine_ir["hash"], row["sha1"], *[prof[k] for k in ("seen", "entries", "ram_seen",
                                                                                        "ram_code")]):
        h.update(part if isinstance(part, bytes) else part.encode())
        h.update(b"\0")
    h.update(Path(lift.__file__).read_bytes())
    mod["hash"] = h.hexdigest()[:20]
    return mod, rep


def witness(ctx, mod: dict, lib: Path, lang: str, rom: bytes, frames: int | None = None) -> dict:
    """The lifted player against the plain one, frame by frame with the same buttons: pictures and sound equal;
    and how much of the cartridge's code ran as lifted card IR."""
    frames = frames or WITNESS_FRAMES
    plain = S.Player(ctx, SYSTEM, rom, fresh=True)
    m = N.CABIMachine(ctx, mod, lang, lib_path=lib, fresh=True)
    lifted = S.Player(ctx, SYSTEM, rom, machine=m, ir=mod)
    m.set("lifted_on", 1)
    press = explore(2)
    first = None
    best = (0, None)
    for f in range(frames):
        b = press(f)
        plain.frame(b)
        lifted.frame(b)
        a, z = plain.rgba(), lifted.rgba()
        if a != z or plain.drain_audio() != lifted.drain_audio():
            first = f
            break
        if f % 60 == 59:
            colours = len(set(a[i:i + 3] for i in range(0, len(a), 4)))
            if colours * 2 >= best[0]:
                best = (max(best[0], colours), a)
    total, interp = m.get("instructions"), m.get("interpreted")
    return {"identical": first is None, "first_difference": first, "frames": frames if first is None else first + 1,
            "instructions": total, "interpreted": interp, "interpreted_ram": m.get("interpreted_ram"),
            "purity": round(1 - interp / max(1, total), 5), "_picture": best[1] or lifted.rgba()}


def icon_rgba(frame: bytes, w: int, h: int) -> bytes:
    """A 128 x 128 icon: the picture scaled to fit, on its own top-left colour."""
    k = min(128 / w, 128 / h)
    sw, sh = int(w * k), int(h * k)
    big = B.scale(frame, w, h, sw, sh)
    canvas = bytearray(frame[0:3] + b"\xff") * (128 * 128)
    ox, oy = (128 - sw) // 2, (128 - sh) // 2
    for y in range(sh):
        o = ((oy + y) * 128 + ox) * 4
        canvas[o:o + sw * 4] = big[y * sw * 4:(y + 1) * sw * 4]
    return bytes(canvas)


def build(ctx, rom_path: Path, install: bool = False, progress=None) -> dict:
    """The app for one cartridge: lifted, witnessed, packed (and installed in ~/Applications/Cardmodel Games)."""
    say = progress or (lambda msg: None)
    t0 = time.time()
    path = Path(rom_path).expanduser().resolve()
    card = S.system_card(ctx.store, SYSTEM)
    exts = tuple(card["cartridge"].get("extensions") or G.ROM_EXTS)
    row = L.describe(ctx, card, path, exts)
    if row is None:
        raise ValueError(f"{path} is not a cartridge the {card['title']} can read")
    rom = L.read_cartridge(path, exts)
    mod, rep = lifted_player(ctx, rom, row, say)
    plat = B.platform_card(ctx.store, card)
    lang = plat["library"]["language"]
    out = B.arcade_root(ctx) / "cartapps" / row["id"]
    out.mkdir(parents=True, exist_ok=True)
    say(f"compiling {rep['blocks']:,} blocks and {rep['ram_instructions_lifted']} RAM instructions natively")
    lib = lift.build_parts(ctx, mod, lang, out)
    say(f"witness: {WITNESS_FRAMES:,} frames next to the plain player")
    wit = witness(ctx, mod, lib, lang, rom)
    if not wit["identical"]:
        raise RuntimeError(f"the lifted player differs from the plain one at frame {wit['first_difference']}")
    picture = wit.pop("_picture")
    say("packing the app")
    exe = B.shell_binary(ctx, plat)
    sp = S.spec(ctx, card, mod, lang)
    em = Emitter(ctx.store, lang, ctx.ops)
    em.state(mod)
    sym = em.ident
    sp.update(id=row["id"], title=row["title"])
    sp["cartridge"]["path"] = str(path)
    sizes = {"seen": rom_size(rom) // 8, "entries": rom_size(rom) // 8, "ram_seen": 0x1000, "ram_code": 0x8000}
    sp["keep"] = [{"symbol": sym(a), "bytes": sizes[a], "file": f, "mode": mode} for a, f, mode in KEEP]
    sp["globals"] = {sym("lifted_on"): 1, sym("profiling"): 1}
    build_id = hashlib.sha256(lib.read_bytes() + exe.read_bytes() + json.dumps(sp, sort_keys=True).encode()
                              ).hexdigest()[:12]
    bundle = plat["bundle"]
    name = row["title"].replace("/", "-")
    app = out / f"{name}.app"
    if app.exists():
        shutil.rmtree(app)
    for key in ("executable_dir", "frameworks_dir", "resources_dir"):
        (app / bundle[key]).mkdir(parents=True, exist_ok=True)
    shutil.copy(exe, app / bundle["executable_dir"] / name)
    os.chmod(app / bundle["executable_dir"] / name, 0o755)
    shutil.copy(lib, app / bundle["frameworks_dir"] / plat["library"]["file"])
    (app / bundle["resources_dir"] / bundle["spec_file"]).write_text(json.dumps(sp, indent=1), encoding="utf-8")
    work = out / "work"
    work.mkdir(exist_ok=True)
    W, H = card["screen"]["width"], card["screen"]["height"]
    shutil.copy(B.icns(ctx, plat, icon_rgba(picture, W, H), work), app / bundle["resources_dir"] / bundle["icon_file"])
    shutil.rmtree(work, ignore_errors=True)
    values = {"title": name, "id": row["id"], "version": card["version"], "build": build_id}
    plist = {k: B._fill(v, values) for k, v in bundle["info_plist"].items()}
    (app / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
    installed = None
    if install:
        dest = apps_dir() / app.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(app, dest, symlinks=True)
        installed = str(dest)
    info = {"title": row["title"], "id": row["id"], "rom": str(path), "app": str(app), "installed": installed,
            "build": build_id, "lift": rep, "witness": wit, "saves": str(saves_dir(row["id"])),
            "seconds": round(time.time() - t0, 1)}
    (out / "app.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    return info


__all__ = ["apps_dir", "build", "explore", "lifted_player", "saves_dir", "witness"]
