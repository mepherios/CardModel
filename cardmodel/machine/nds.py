"""nds — the Nintendo DS machine card driven from the host (a prototype), and its measured coverage.

``open_nds(path)`` reads the image (in memory); ``header`` decodes it with the ``hardware/nds_cartridge`` card;
``DS(ctx, rom)`` loads it the way the BIOS and firmware would (direct boot: both binaries copied to their load
addresses, the header and chip ID at the top of main RAM, default user settings) and powers on.

``coverage(ds)`` is the honest account: instructions each CPU ran, where each one is now and why (halted,
waiting in IntrWait, stopped on an undefined instruction), which instruction cards the executed code used,
which BIOS calls were made and which of them are modelled, and every I/O register the game touched that no
card models (latched only).

Honest limits (L1): no 2D/3D graphics, sound, touch, firmware/SPI, RTC or Wi-Fi; no wait states (a nominal
instructions-per-line budget); WRAM and VRAM banking are flat; nothing here decrypts anything: an image whose
secure area is encrypted is refused.
"""
from __future__ import annotations

import struct
import time
from pathlib import Path

from . import build as Bd
from . import isa as I
from . import native as N


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


def user_settings() -> bytes:
    """Default firmware user settings (version 5, English, nickname "CARD", a plain touch calibration)."""
    u = bytearray(0x70)
    u[0:2] = (5).to_bytes(2, "little")
    u[2] = 0x0B
    u[3], u[4] = 1, 1
    name = "CARD".encode("utf-16-le")
    u[6:6 + len(name)] = name
    u[0x1A] = 4
    u[0x58:0x64] = struct.pack("<HHBBHHBB", 0x02DF, 0x032C, 0x20, 0x20, 0x0D3B, 0x0CE7, 0xE0, 0xA0)
    u[0x64] = 0x01
    return bytes(u)


class DS:
    def __init__(self, ctx, rom: bytes, engine: str = "native"):
        self.ctx = ctx
        self.rom = rom
        self.info = header(rom, ctx.store)
        if not self.info["secure_area_decrypted"]:
            raise ValueError("this image's secure area is encrypted; decrypting it would need BIOS key material, "
                             "which this program does not use")
        self.ir = Bd.module(ctx, "nds")
        self.m = N.load(ctx, self.ir, engine)
        self.load()

    def load(self) -> None:
        m, h = self.m, self.info
        m.call("reset_all")
        n = min(len(self.rom), 0x4000000)
        m.write("cart", self.rom[:n])
        m.set("cart_size", n)
        m.write("mram", bytes(0x400000))
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
        m.write("mram", user_settings(), start=0x3FFC80)
        m.set("entry9", h["arm9_entry"])
        m.set("entry7", h["arm7_entry"])
        m.call("power_on")

    def run(self, frames: int, progress=None) -> float:
        t0 = time.perf_counter()
        for f in range(frames):
            self.m.call("run_frame")
            if progress and f % 60 == 59:
                progress(f + 1, self.m.get("executed") if False else None)
            if self.m.array("stopped_cpu")[0] and self.m.array("stopped_cpu")[1]:
                break
        return time.perf_counter() - t0


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
    modelled = set()
    for item in iocard.get("modelled_registers") or []:
        rng = item.split()[0]
        if "-" in rng:
            a, b = rng.split("-")
            modelled |= set(range(int(a, 16), int(b, 16) + 1))
        else:
            modelled.add(int(rng, 16) & 0x1FFF)
    out = {"title": ds.info["title"], "game_code": ds.info["game_code"], "cpus": {}}
    touch = m.read("io_touch")
    for c, name in ((0, "arm9"), (1, "arm7")):
        st = _cpu_state(m, c)
        used: dict = {}
        undefined = 0
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
                            undefined += 1
                        else:
                            used[card.name] = used.get(card.name, 0) + 1
        hits = m.array("swi_hits")
        swis = {f"{n:#04x}": hits[c * 32 + n] for n in range(32) if hits[c * 32 + n]}
        regs = sorted(o for o in range(0x2000) if touch[c * 0x2000 + o] and o < 0x1FF0)
        how = {1: "read", 2: "written", 3: "read+written"}
        unmodelled = [f"{0x04000000 + o:#010x} {how[touch[c * 0x2000 + o] & 3]}" for o in regs if o not in modelled]
        blocks: dict = {}
        for o in regs:
            if o in modelled:
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
            "undecodable_executed": undefined, "swi_calls": swis,
            "swi_unmodelled": sorted(k for k in swis if int(k, 16) not in modelled_swi),
            "io_registers_touched": len(regs), "io_unmodelled_touched": unmodelled,
            "unmodelled_hardware_touched": dict(sorted(blocks.items(), key=lambda kv: -kv[1]))}
    total_cards = len(cards)
    used_all = set()
    for c in out["cpus"].values():
        used_all |= set(c["card_uses"])
    out.update({"frames": m.get("frames"), "instruction_cards": total_cards,
                "unmapped_reads": m.get("unmapped_reads"), "unmapped_writes": m.get("unmapped_writes"),
                "last_unmapped": f"{m.get('last_unmapped'):#010x}", "undefined_hits": m.get("undef_hits"),
                "swi_last_unknown": m.get("swi_last_unknown")})
    return out


__all__ = ["DS", "coverage", "header", "open_nds", "user_settings"]
