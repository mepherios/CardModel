"""nds — the Nintendo DS machine card driven from the host (a prototype), its screens and its measured coverage.

``open_nds(path)`` reads the image (in memory); ``header`` decodes it with the ``hardware/nds_cartridge`` card;
``DS(ctx, rom)`` loads it the way the BIOS and firmware would (direct boot: both binaries copied to their load
addresses, the header and chip ID at the top of main RAM, the user settings) and powers on. The firmware flash
image and the user settings are made from the ``hardware/nds_spi`` card's data (no console's firmware is used);
the save chip's kind and size come from the ``hardware/nds_backup`` card (by game code) and it starts erased
unless ``save`` bytes are given; the real-time clock starts at ``clock`` (a datetime; a fixed date by default,
so runs repeat exactly).

``ds.screens()`` returns both screens (RGB888, top then bottom); ``png_screens`` stacks them as on the console.
``coverage(ds)`` is the honest account: instructions each CPU ran, where each one is now and why (halted,
waiting in IntrWait, stopped on an undefined instruction), how many undefined instructions ran (counted as they
run), which instruction cards the executed code used (decoded from memory after the run: code that was
overwritten later is counted apart), which BIOS calls were made and which of them are modelled, every I/O
register the game touched that no card models (latched only), and what the screens show.

Honest limits (L1): no sound output or Wi-Fi; no wait states (a nominal instructions-per-line budget); nothing
here decrypts anything: an image whose secure area is encrypted is refused.
"""
from __future__ import annotations

import datetime
import hashlib
import struct
import time
from pathlib import Path

from . import build as Bd
from . import isa as I
from . import native as N

SCREEN_W, SCREEN_H = 256, 192
SCREEN_BYTES = SCREEN_W * SCREEN_H * 3
DEFAULT_CLOCK = datetime.datetime(2026, 1, 1, 12, 0, 0)


def buttons(store) -> dict:
    """{button name: bit} of the host's button mask, from the ``machine/nds`` card (``buttons_layout`` says which
    register bits they are)."""
    return dict(store.get("machine/nds")["buttons"])


def open_nds(path) -> bytes:
    return Path(path).expanduser().read_bytes()


def header(rom: bytes, store) -> dict:
    card = store.get("hardware/nds_cartridge")
    out = {}
    for k, f in card["header"].items():
        raw = rom[f["offset"]:f["offset"] + f["size"]]
        out[k] = raw.split(b"\0")[0].decode("ascii", "replace") if f.get("type") == "ascii" else \
            int.from_bytes(raw, "little")
    sa = card["secure_area"]
    marker = rom[sa["offset"]:sa["offset"] + 4][::-1].hex().upper()
    out["secure_area_decrypted"] = marker == sa["decrypted_marker"]
    out["size"] = len(rom)
    return out


def crc16(data: bytes, init: int = 0xFFFF) -> int:
    """The firmware's CRC-16 (polynomial 0xA001, reflected), as the BIOS's GetCRC16 computes it."""
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def user_settings(store) -> bytes:
    """The firmware's user settings (0x70 bytes, as the firmware copies them to 0x027FFC80): version, colour,
    birthday, nickname, language and the touch calibration, from the ``hardware/nds_spi`` card."""
    spi = store.get("hardware/nds_spi")
    us, cal = spi["firmware"]["user_settings"], spi["touch_calibration"]
    u = bytearray(0x70)
    u[0:2] = int(us["version"]).to_bytes(2, "little")
    u[2] = us["favorite_color"]
    u[3], u[4] = us["birth_month"], us["birth_day"]
    name = us["nickname"][:10].encode("utf-16-le")
    u[6:6 + len(name)] = name
    u[0x1A] = len(us["nickname"][:10])
    u[0x58:0x64] = struct.pack("<HHBBHHBB", cal["adc_x1"], cal["adc_y1"], cal["scr_x1"], cal["scr_y1"],
                               cal["adc_x2"], cal["adc_y2"], cal["scr_x2"], cal["scr_y2"])
    u[0x64] = us["language"] & 7
    return bytes(u)


def firmware_image(store) -> bytes:
    """A 256 KiB firmware flash made from the ``hardware/nds_spi`` card: the header fields a game's ARM7 reads
    (console type, where the user settings are), the Wi-Fi settings block with its length, MAC address and CRC,
    and both user-settings copies (update counter, CRC). Everything else is erased flash (0xFF)."""
    fw_card = store.get("hardware/nds_spi")["firmware"]
    img = bytearray(b"\xFF" * fw_card["bytes"])
    img[0x08:0x0C] = b"MACP"
    img[0x1D] = fw_card["console_type"]
    offs = fw_card["user_settings_offsets"]
    img[0x20:0x22] = (offs[0] // 8).to_bytes(2, "little")
    w = fw_card["wifi_config_offset"]                    # CRC (2 bytes), then the block it covers
    body = bytearray(0x138)                              # length, version, MAC address, channels, RF data
    body[0:2] = len(body).to_bytes(2, "little")
    body[3] = 5
    body[4:10] = b"\xFF" * 6
    body[10:16] = bytes(fw_card["mac_address"])
    body[16:18] = (0x3FFE).to_bytes(2, "little")
    body[18:20] = b"\xFF\xFF"
    img[w + 2:w + 2 + len(body)] = body
    img[w:w + 2] = crc16(bytes(body), 0).to_bytes(2, "little")
    us = bytearray(b"\xFF" * 0x100)
    us[:0x70] = user_settings(store)
    us[0x70:0x72] = int(fw_card["user_settings"].get("update_counter", 1)).to_bytes(2, "little")
    us[0x72:0x74] = crc16(bytes(us[:0x70])).to_bytes(2, "little")
    for o in offs:
        img[o:o + 0x100] = us
    return bytes(img)


def backup_chip(rom_info: dict, store) -> dict:
    """{kind, bytes} of the game's save chip, from the ``hardware/nds_backup`` card (by game code)."""
    card = store.get("hardware/nds_backup")
    code = (rom_info.get("game_code") or "")[:3]
    row = (card.get("by_game_code") or {}).get(code) or card["default"]
    return {"kind": row["kind"], "kind_code": card["kinds"][row["kind"]], "bytes": int(row.get("bytes") or 0),
            "id": int(card.get("flash_id") or 0)}


def png_screens(rgb: bytes, scale: int = 1, gap: int = 0) -> bytes:
    """Both screens (top above bottom, ``gap`` black lines between) as one PNG."""
    from .gb import png
    if gap:
        rgb = rgb[:SCREEN_BYTES] + bytes(SCREEN_W * 3 * gap) + rgb[SCREEN_BYTES:]
    return png(rgb, SCREEN_W, SCREEN_H * 2 + gap, scale)


class DS:
    """One machine with one image inserted. ``machine`` reuses an already loaded machine module (``ds.m`` of
    another DS): the new image replaces whatever ran in it."""

    def __init__(self, ctx, rom: bytes, engine: str = "native", clock: datetime.datetime | None = None,
                 save: bytes | None = None, fresh: bool = False, machine: N.Machine | None = None):
        self.ctx = ctx
        self.rom = rom
        self.info = header(rom, ctx.store)
        if not self.info["secure_area_decrypted"]:
            raise ValueError("this image's secure area is encrypted; decrypting it would need BIOS key material, "
                             "which this program does not use")
        self.clock = clock
        self.save = save
        self.ir = machine.ir if machine is not None else Bd.module(ctx, "nds")
        self.m = machine if machine is not None else N.load(ctx, self.ir, engine, fresh=fresh)
        self.load()

    def load(self) -> None:
        m, h = self.m, self.info
        m.call("reset_all")
        n = min(len(self.rom), 0x4000000)
        m.write("cart", self.rom[:n])
        m.set("cart_size", n)
        m.write("mram", bytes(0x400000))
        for arr in ("exec9", "exec7"):                   # the execution maps are beyond reset_all's size limit
            m.write(arr, bytes(len(m.array(arr))))
        for cpu in ("arm9", "arm7"):
            off, ram, size = h[f"{cpu}_rom_offset"], h[f"{cpu}_ram_address"], h[f"{cpu}_size"]
            data = self.rom[off:off + size]
            if 0x02000000 <= ram < 0x02400000:
                m.write("mram", data, start=ram - 0x02000000)
            elif 0x03800000 <= ram < 0x03810000:
                m.write("wram7", data, start=ram - 0x03800000)
            else:
                raise ValueError(f"{cpu} loads at {ram:#x}, which this prototype does not map")
        m.write("mram", self.rom[:0x170], start=0x3FFE00)
        for a in (0x3FF800, 0x3FF804, 0x3FFC00, 0x3FFC04):
            m.write("mram", (8130).to_bytes(4, "little"), start=a)
        m.write("mram", (1).to_bytes(2, "little"), start=0x3FFC40)
        m.write("mram", user_settings(self.ctx.store), start=0x3FFC80)
        m.write("firmware", firmware_image(self.ctx.store))
        chip = backup_chip(h, self.ctx.store)
        m.set("backup_kind", chip["kind_code"])
        m.set("backup_size", max(chip["bytes"], 1))
        m.set("backup_id", chip["id"])
        save = getattr(self, "save", None) or b""
        size = min(chip["bytes"], 0x100000)
        m.write("backup", (save[:size] + b"\xFF" * size)[:size])
        m.set("entry9", h["arm9_entry"])
        m.set("entry7", h["arm7_entry"])
        m.call("power_on")
        self.set_clock(getattr(self, "clock", None) or DEFAULT_CLOCK)

    def set_clock(self, when: datetime.datetime) -> None:
        """Set the real-time clock (binary fields; the card shows them in BCD)."""
        m = self.m
        for name, v in (("rtc_year", when.year % 100), ("rtc_month", when.month), ("rtc_day", when.day),
                        ("rtc_wday", (when.weekday() + 1) % 7), ("rtc_hour", when.hour), ("rtc_min", when.minute),
                        ("rtc_sec", when.second)):
            m.set(name, v)

    def set_buttons(self, mask: int) -> None:
        """Held buttons (the ``buttons`` mask: A B Select Start Right Left Up Down R L in KEYINPUT, X Y in EXTKEYIN;
        the registers read 0 for a pressed button)."""
        self.m.set("keyinput", 0x3FF & ~mask)
        ext = self.m.get("extkey")
        self.m.set("extkey", (ext & ~0x03) | (0x03 & ~(mask >> 10)))

    def touch(self, x: int | None, y: int | None = None) -> None:
        """Pen down at (x, y) on the bottom screen, or up (None)."""
        m = self.m
        ext = m.get("extkey")
        if x is None:
            m.set("touch_down", 0)
            m.set("extkey", ext | 0x40)
        else:
            m.set("touch_down", 1)
            m.set("touch_x", max(0, min(255, int(x))))
            m.set("touch_y", max(0, min(191, int(y or 0))))
            m.set("extkey", ext & ~0x40)

    def screens(self) -> bytes:
        """Both screens, RGB888: the top screen's 256x192 pixels, then the bottom screen's."""
        return self.m.read("screen")

    def save_bytes(self) -> bytes:
        """The save chip's contents."""
        return self.m.read("backup", 0, min(self.m.get("backup_size"), 0x100000))

    def run(self, frames: int, progress=None, script: dict | None = None, every: int = 0, shot=None,
            watch: bool = False) -> float:
        """Run frames; ``script`` {frame: buttons} holds buttons from that frame on; ``shot(frame, screens)`` is
        called after every ``every``-th frame; ``watch`` records in ``first_drawn`` the first frame after which
        each screen was not one flat colour."""
        t0 = time.perf_counter()
        start = self.m.get("frames")
        for f in range(frames):
            if script and f in script:
                self.set_buttons(script[f])
            self.m.call("run_frame")
            if watch and len(self.first_drawn) < 2:
                rgb = self.screens()
                for name, k in (("top", 0), ("bottom", 1)):
                    part = rgb[k * SCREEN_BYTES:(k + 1) * SCREEN_BYTES]
                    if name not in self.first_drawn and part != part[:3] * (SCREEN_W * SCREEN_H):
                        self.first_drawn[name] = start + f + 1
            if progress and f % 60 == 59:
                progress(f + 1)
            if shot and every and (f + 1) % every == 0:
                shot(start + f + 1, self.screens())
            if self.m.array("stopped_cpu")[0] and self.m.array("stopped_cpu")[1]:
                break
        return time.perf_counter() - t0

    @property
    def first_drawn(self) -> dict:
        if not hasattr(self, "_first_drawn"):
            self._first_drawn = {}
        return self._first_drawn


def parse_input(script: str | None, store) -> dict:
    """``"300:start,306:-,400:a+up"`` -> {frame: buttons}: from that frame on, hold those buttons (names from the
    ``machine/nds`` card)."""
    names = buttons(store)
    out = {}
    for part in (script or "").split(","):
        part = part.strip()
        if not part:
            continue
        f, _, keys = part.partition(":")
        mask = 0
        for k in keys.split("+"):
            k = k.strip().lower()
            if k and k != "-":
                if k not in names:
                    raise ValueError(f"unknown button {k!r} (one of {', '.join(names)})")
                mask |= names[k]
        out[int(f)] = mask
    return out


def screen_stats(rgb: bytes) -> dict:
    """Per screen: how many colours (sampled) and whether it is one flat colour (a blank screen)."""
    out = {}
    for name, k in (("top", 0), ("bottom", 1)):
        part = rgb[k * SCREEN_BYTES:(k + 1) * SCREEN_BYTES]
        cols = {part[i:i + 3] for i in range(0, len(part), 3 * 5)}
        out[name] = {"colours": len(cols), "blank": len(cols) <= 1,
                     "sha1": hashlib.sha1(part).hexdigest()[:16]}
    return out


def _cpu_state(m, c: int) -> dict:
    """Registers of CPU c whether or not it is the one loaded in the core."""
    if m.get("cur") == c:
        return {"pc": m.get("pc"), "cpsr": m.get("cpsr"), "regs": [m.array("regs")[i] for i in range(16)]}
    misc, regs = m.array("ctx_misc"), m.array("ctx_r")
    return {"pc": misc[c * 8 + 2], "cpsr": misc[c * 8], "regs": [regs[c * 16 + i] for i in range(16)]}


def coverage(ds: DS) -> dict:
    m, store = ds.m, ds.ctx.store
    cards = I.instructions(store, "armv5te")
    from .bench import decoded_by
    bios = store.get("hardware/nds_bios")
    modelled_swi = {int(k, 16) for k in (bios.get("swi_modelled") or {})}
    iocard = store.get("hardware/nds_io")
    modelled = {0: set(), 1: set()}
    for item in iocard.get("modelled_registers") or []:
        rng = item.split()[0]
        if "-" in rng:
            a, b = rng.split("-")
            span = set(range(int(a, 16), int(b, 16) + 1))
        else:
            span = {int(rng, 16) & 0x1FFF}
        for c in (0, 1):
            if not ("(ARM7)" in item and c == 0) and not ("(ARM9)" in item and c == 1):
                modelled[c] |= span
    out = {"title": ds.info["title"], "game_code": ds.info["game_code"], "cpus": {}}
    touch = m.read("io_touch")
    for c, name in ((0, "arm9"), (1, "arm7")):
        st = _cpu_state(m, c)
        used: dict = {}
        overwritten = 0
        n_exec = 0
        maps = [("exec9", 0x02000000, 0x3FFFFF), ("exec9i", 0x0, 0x7FFF)] if c == 0 else \
            [("exec7", 0x02000000, 0x3FFFFF), ("exec7w", 0x03800000, 0xFFFF)]
        mem = {"exec9": "mram", "exec7": "mram", "exec9i": "itcm", "exec7w": "wram7"}
        for arr, base, mask in maps:
            emap = m.read(arr)
            data = m.read(mem[arr])
            for h, flags in enumerate(emap):
                if not flags:
                    continue
                a = h * 2
                for st_bit, iset in ((1, "arm"), (2, "thumb")):
                    if flags & st_bit:
                        n_exec += 1
                        if iset == "arm":
                            op = int.from_bytes(data[a:a + 4], "little")
                        else:
                            op = int.from_bytes(data[a:a + 2], "little")
                        card = decoded_by(cards, op, iset)
                        if card is None:
                            overwritten += 1
                        else:
                            used[card.name] = used.get(card.name, 0) + 1
        hits = m.array("swi_hits")
        swis = {f"{n:#04x}": hits[c * 32 + n] for n in range(32) if hits[c * 32 + n]}
        regs = sorted(o for o in range(0x2000) if touch[c * 0x2000 + o] and o < 0x1FF0)
        how = {1: "read", 2: "written", 3: "read+written"}
        unmodelled = [f"{0x04000000 + o:#010x} {how[touch[c * 0x2000 + o] & 3]}" for o in regs if o not in modelled[c]]
        blocks: dict = {}
        for o in regs:
            if o in modelled[c]:
                continue
            block = next((b["name"] for b in iocard.get("register_blocks") or []
                          if int(b["from"], 16) <= o <= int(b["to"], 16) and b.get("cpu", name) == name), "other")
            blocks[block] = blocks.get(block, 0) + 1
        out["cpus"][name] = {
            "instructions_executed": m.array("executed")[c], "distinct_instruction_addresses": n_exec,
            "pc": f"{st['pc']:#010x}", "state": "thumb" if st["cpsr"] & 0x20 else "arm",
            "mode": f"{st['cpsr'] & 0x1F:#04x}", "halted": bool(m.array("halted_cpu")[c]),
            "stopped": bool(m.array("stopped_cpu")[c]),
            "stop_pc": f"{m.array('stop_pc')[c]:#010x}" if m.array("stopped_cpu")[c] else None,
            "cards_used": len(used), "card_uses": dict(sorted(used.items(), key=lambda kv: -kv[1])[:25]),
            "undecodable_executed": m.array("undef_cpu")[c], "overwritten_after_running": overwritten,
            "swi_calls": swis,
            "swi_unmodelled": sorted(k for k in swis if int(k, 16) not in modelled_swi),
            "io_registers_touched": len(regs), "io_unmodelled_touched": unmodelled,
            "unmodelled_hardware_touched": dict(sorted(blocks.items(), key=lambda kv: -kv[1]))}
    total_cards = len(cards)
    used_all = set()
    for c in out["cpus"].values():
        used_all |= set(c["card_uses"])
    out["screens"] = screen_stats(ds.screens())
    out["lines_drawn"] = m.get("lines_drawn")
    out["geometry_commands"] = m.get("gx_commands")
    out.update({"frames": m.get("frames"), "instruction_cards": total_cards,
                "unmapped_reads": m.get("unmapped_reads"), "unmapped_writes": m.get("unmapped_writes"),
                "last_unmapped": f"{m.get('last_unmapped'):#010x}", "undefined_hits": m.get("undef_hits"),
                "swi_last_unknown": m.get("swi_last_unknown")})
    return out


__all__ = ["DS", "backup_chip", "buttons", "coverage", "crc16", "firmware_image", "header", "open_nds", "parse_input",
           "png_screens", "screen_stats", "user_settings"]
