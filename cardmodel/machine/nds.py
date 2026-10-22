"""nds — the Nintendo DS machine card driven from the host (a prototype), its screens and its measured coverage.

``open_nds(path)`` reads the image (in memory); ``header`` decodes it with the ``hardware/nds_cartridge`` card;
``DS(ctx, rom)`` puts it in the machine's cartridge and calls the machine's own direct boot (``load_image`` in
cards/machine/nds/boot.card: the binaries, header, chip ID, user settings, a firmware image and the save chip, all
from card data), loads ``save`` bytes into the save chip when given, and sets the real-time clock to ``clock`` (a
datetime; a fixed date by default, so runs repeat exactly).

``ds.screens()`` returns both screens (RGB888, top then bottom); ``png_screens`` stacks them as on the console.
``coverage(ds)`` is the honest account: instructions each CPU ran, where each one is now and why (halted,
waiting in IntrWait, stopped on an undefined instruction), how many undefined instructions ran (counted as they
run), which instruction cards the executed code used (decoded from memory after the run: code that was
overwritten later is counted apart), which BIOS calls were made and which of them are modelled, every I/O
register the game touched that no card models (latched only), and what the screens show.

Honest limits (L1): no Wi-Fi; no wait states (a nominal instructions-per-line budget); nothing here decrypts
anything: an image whose secure area is encrypted is refused.
"""
from __future__ import annotations

import calendar
import datetime
import hashlib
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


def check_image(store, stores: list, title: str = "CARDCHECK", code: str = "CMCK") -> bytes:
    """A DS image no one owns (the store's check of the DS player): a header that says where the binaries are, the
    decrypted secure-area marker, ARM9 code that does ``stores`` ([(address, value, width)], in order) and then
    idles, and an ARM7 that idles. Every word comes from the instruction cards (asm.arm_word): per store
    LDR r0,[pc,#..], LDR r1,[pc,#..] and STR, STRH or STRB r1,[r0]; then SUB pc,pc,#8; then the literal pool.
    Where each header field goes, the marker and where it sits are the ``hardware/nds_cartridge`` card's."""
    from . import asm as A
    cc = store.get("hardware/nds_cartridge")
    h = cc["header"]
    at9, ram9, ram7, at7 = int(cc["secure_area"]["offset"]), 0x02000000, 0x02380000, 0x8000
    base = ram9 + 8                                         # the first instruction, after the 8-byte marker
    n = 3 * len(stores) + 1
    words: list = []
    lits: list = []
    for addr, value, width in stores:
        for reg, v in ((0, addr), (1, value)):
            if v not in lits:
                lits.append(v)
            off = base + 4 * (n + lits.index(v)) - (base + 4 * len(words) + 8)
            words.append(A.arm_word(store, "ARM_LDR_imm", Rd=reg, Rn=15, P=1, U=1, offset=off))
        form = {4: "ARM_STR_imm", 2: "ARM_STRH_imm", 1: "ARM_STRB_imm"}[width]
        words.append(A.arm_word(store, form, Rd=1, Rn=0, P=1, U=1))
    idle = A.arm_word(store, "ARM_SUB_imm", Rd=15, Rn=15, operand2=8)
    words.append(idle)
    marker = int(cc["secure_area"]["decrypted_word"])
    body = [marker, marker] + words + [v & 0xFFFFFFFF for v in lits]
    img = bytearray(0x10000)
    t = title.encode("ascii")[:12]
    img[h["title"]["offset"]:h["title"]["offset"] + len(t)] = t
    img[h["game_code"]["offset"]:h["game_code"]["offset"] + 4] = code.encode("ascii")[:4].ljust(4, b"\0")
    for field, value in (("arm9_rom_offset", at9), ("arm9_entry", base), ("arm9_ram_address", ram9),
                         ("arm9_size", 4 * len(body)), ("arm7_rom_offset", at7), ("arm7_entry", ram7),
                         ("arm7_ram_address", ram7), ("arm7_size", 4)):
        o = h[field]["offset"]
        img[o:o + 4] = value.to_bytes(4, "little")
    for i, w in enumerate(body):
        img[at9 + 4 * i:at9 + 4 * i + 4] = w.to_bytes(4, "little")
    img[at7:at7 + 4] = idle.to_bytes(4, "little")
    return bytes(img)


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
        """Reset, put the image in the cartridge and boot it the way the BIOS and firmware would (the machine's own
        direct boot, cards/machine/nds/boot.card), then the save chip's bytes and the clock."""
        m = self.m
        m.call("reset_all")
        n = min(len(self.rom), 0x4000000)
        m.write("cart", self.rom[:n])
        m.call("load_image", n)
        if m.get("boot_refused"):
            raise ValueError("this image's secure area is encrypted; decrypting it would need BIOS key material, "
                             "which this program does not use")
        save = getattr(self, "save", None) or b""
        if save:
            m.write("backup", save[:min(m.get("backup_size"), 0x100000)])
        self.set_clock(getattr(self, "clock", None) or DEFAULT_CLOCK)

    def set_clock(self, when: datetime.datetime) -> None:
        """Set the real-time clock to a wall-clock time (the card's rtc_set_unix counts seconds from 1970)."""
        self.m.call("rtc_set_unix", calendar.timegm(when.timetuple()))

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

    def drain_audio(self) -> bytes:
        """The sound mixed since the last call: signed 16-bit stereo at ``snd_rate``."""
        n = self.m.get("audio_n")
        data = self.m.read("audio", 0, n) if n else b""
        self.m.set("audio_n", 0)
        return data

    def save_bytes(self) -> bytes:
        """The save chip's contents."""
        return self.m.read("backup", 0, min(self.m.get("backup_size"), 0x100000))

    def run(self, frames: int, progress=None, script: dict | None = None, every: int = 0, shot=None,
            watch: bool = False, pcm: bytearray | None = None) -> float:
        """Run frames; ``script`` {frame: buttons} holds buttons from that frame on; ``shot(frame, screens)`` is
        called after every ``every``-th frame; ``watch`` records in ``first_drawn`` the first frame after which
        each screen was not one flat colour; ``pcm`` collects the sound."""
        t0 = time.perf_counter()
        start = self.m.get("frames")
        for f in range(frames):
            if script and f in script:
                self.set_buttons(script[f])
            self.m.call("run_frame")
            if pcm is not None:
                pcm += self.drain_audio()
            else:
                self.m.set("audio_n", 0)
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
                "wifi_accesses": m.get("wifi_accesses"), "unmapped_io": m.get("unmapped_io"),
                "last_unmapped": f"{m.get('last_unmapped'):#010x}", "undefined_hits": m.get("undef_hits"),
                "swi_last_unknown": m.get("swi_last_unknown")})
    return out


__all__ = ["DS", "buttons", "check_image", "coverage", "header", "open_nds", "parse_input", "png_screens",
           "screen_stats"]
