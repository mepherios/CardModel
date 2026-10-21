"""gb — the Game Boy machine card driven from the host: ROM in, frames/audio/saves out.

``open_rom(path)`` reads a .gb/.gbc file or the first such member of a .zip (in memory; nothing is extracted or
copied). ``header(rom, store)`` decodes the cartridge header with the ``hardware/gb_cartridge`` card's tables.
``GameBoy(ctx, rom, engine)`` builds (or reuses) the machine module, loads it in an engine, configures the
cartridge from the header and powers on in DMG or CGB mode (``model``: auto = CGB when the header asks for it).

Everything here is plumbing between the host and the pure machine: bytes into ``rom``, header fields into four
globals, ``run_frame`` per frame, ``frame``/``audio``/``cram`` out. The behaviour is the cards'.

Honest limits (L1): MMM01, MBC6, MBC7, HuC1/HuC3, TAMA5 and the camera are reported as unsupported (the
game runs as ROM-only and will likely misbehave); no boot ROM (the documented post-boot state is used, so DMG
games on a CGB get no colourisation palette: they run in DMG mode).
"""
from __future__ import annotations

import hashlib
import struct
import zipfile
import zlib
from pathlib import Path

from . import build as Bd
from . import native as N

ROM_EXTS = (".gb", ".gbc", ".sgb")


def open_rom(path) -> tuple[bytes, str]:
    """(ROM bytes, display name). A zip is read in memory; the first .gb/.gbc member is used."""
    p = Path(path).expanduser()
    if p.suffix.lower() == ".zip":
        with zipfile.ZipFile(p) as z:
            names = [n for n in z.namelist() if n.lower().endswith(ROM_EXTS)]
            if not names:
                raise ValueError(f"{p.name}: no .gb/.gbc file inside")
            return z.read(names[0]), Path(names[0]).stem
    return p.read_bytes(), p.stem


def header(rom: bytes, store) -> dict:
    card = store.get("hardware/gb_cartridge")
    if len(rom) < 0x150:
        raise ValueError("not a Game Boy ROM (shorter than its header)")
    t = rom[0x147]
    info = dict((card.get("types") or {}).get(f"0x{t:02X}") or {"mbc": "unknown", "unsupported": True})
    title_end = 0x143 if rom[0x143] in (0x80, 0xC0) else 0x144
    title = rom[0x134:title_end].split(b"\0")[0].decode("ascii", "replace").strip()
    ram_size = int((card.get("ram_size_bytes") or {}).get(str(rom[0x149]), 0))
    if info.get("mbc") == "mbc2":
        ram_size = 512
    if not info.get("ram") and info.get("mbc") != "mbc2":
        ram_size = 0
    chk = 0
    for b in rom[0x134:0x14D]:
        chk = (chk - b - 1) & 0xFF
    return {"title": title, "type": t, "mbc": info.get("mbc"), "supported": not info.get("unsupported"),
            "battery": bool(info.get("battery")), "rtc": bool(info.get("rtc")), "rumble": bool(info.get("rumble")),
            "cgb_flag": rom[0x143], "cgb": rom[0x143] in (0x80, 0xC0), "cgb_only": rom[0x143] == 0xC0,
            "sgb": rom[0x146] == 0x03, "rom_size": 32768 << rom[0x148] if rom[0x148] < 9 else len(rom),
            "ram_size": ram_size, "header_checksum_ok": chk == rom[0x14D],
            "mbc_kind": int((card.get("mbc_kind") or {}).get(info.get("mbc"), 0)),
            "sha1": hashlib.sha1(rom).hexdigest()}


def _pow2(n: int) -> int:
    p = 0x8000
    while p < n:
        p <<= 1
    return p


class GameBoy:
    """One machine instance with a cartridge inserted."""

    def __init__(self, ctx, rom: bytes, engine: str = "native", model: str = "auto", fresh: bool = False,
                 sample_rate: int = 48000, machine: Machine | None = None, progress=None):
        self.ctx = ctx
        self.rom = rom
        self.info = header(rom, ctx.store)
        self.lift_report = None
        if machine is None and engine == "lifted":
            from . import lift
            machine, self.lift_report = lift.lifted_machine(ctx, rom, progress=progress)
        self.ir = machine.ir if machine else Bd.module(ctx, "gameboy")
        self.m = machine or N.load(ctx, self.ir, engine, fresh=fresh)
        self.engine = self.m.engine + ("+lifted" if self.lift_report is not None else "")
        want = {"auto": 1 if self.info["cgb"] else 0, "dmg": 0, "cgb": 1}[model]
        self.cgb = want
        self.sample_rate = sample_rate
        self.reset()

    def reset(self) -> None:
        m, info = self.m, self.info
        m.call("reset_all")
        size = min(len(self.rom), 0x800000)
        m.write("rom", self.rom[:size])
        rom_bytes = _pow2(max(size, info["rom_size"] if info["rom_size"] <= 0x800000 else size))
        if rom_bytes > size:
            # mirror a short dump so every bank number maps somewhere defined
            for off in range(size, rom_bytes, max(size, 1)):
                m.write("rom", self.rom[:min(size, rom_bytes - off)], start=off)
        m.set("rom_mask", rom_bytes - 1)
        m.set("mbc_kind", info["mbc_kind"])
        m.set("ram_mask", (info["ram_size"] - 1) if info["ram_size"] else -1)
        m.set("has_rtc", 1 if info["rtc"] else 0)
        m.set("sample_rate", self.sample_rate)
        m.write("cram", bytes(0x20000))
        m.call("power_on", self.cgb)
        if self.lift_report is not None:
            m.set("lifted_on", 1)
            m.set("profiling", 1)

    # -- per frame --------------------------------------------------------------------------------------
    def run_frame(self) -> int:
        return self.m.call("run_frame")

    def frame(self) -> bytes:
        return self.m.read("frame")

    def drain_audio(self) -> bytes:
        n = self.m.get("audio_n")
        data = self.m.read("audio", 0, n) if n else b""
        self.m.set("audio_n", 0)
        return data

    def set_buttons(self, mask: int) -> None:
        self.m.call("set_buttons", mask & 0xFF)

    def serial_text(self) -> str:
        n = self.m.get("serial_n")
        return self.m.read("serial_out", 0, n).decode("latin-1") if n else ""

    def state_hash(self) -> str:
        """A digest of the CPU registers, time, frame and work RAM (for differential runs)."""
        h = hashlib.sha1()
        for r in ("A", "F", "B", "C", "D", "E", "H", "L", "SP", "PC", "now", "ime", "halted", "ly"):
            h.update(struct.pack("<q", int(self.m.get(r))))
        h.update(self.m.read("frame"))
        h.update(self.m.read("wram"))
        h.update(self.m.read("hram"))
        return h.hexdigest()

    # -- saves --------------------------------------------------------------------------------------------
    def save_bytes(self) -> bytes:
        size = self.info["ram_size"]
        data = self.m.read("cram", 0, size) if size else b""
        if self.info["rtc"]:
            regs = [int(self.m.get(n)) for n in ("rtc_s", "rtc_m", "rtc_h", "rtc_dl", "rtc_dh",
                                                 "rtc_ls", "rtc_lm", "rtc_lh", "rtc_ldl", "rtc_ldh")]
            import time
            data += struct.pack("<10I", *regs) + struct.pack("<Q", int(time.time()))
        return data

    def load_save(self, data: bytes) -> int:
        """Load battery RAM (+ RTC in the common 48-byte trailer). Returns seconds the RTC was advanced."""
        size = self.info["ram_size"]
        if size:
            self.m.write("cram", data[:size])
        advanced = 0
        if self.info["rtc"] and len(data) >= size + 48:
            regs = struct.unpack("<10I", data[size:size + 40])
            stamp = struct.unpack("<Q", data[size + 40:size + 48])[0]
            for n, v in zip(("rtc_s", "rtc_m", "rtc_h", "rtc_dl", "rtc_dh", "rtc_ls", "rtc_lm", "rtc_lh",
                             "rtc_ldl", "rtc_ldh"), regs):
                self.m.set(n, v & 0xFF)
            import time
            advanced = max(0, int(time.time()) - int(stamp))
            if advanced:
                self.m.call("rtc_add_seconds", min(advanced, 10 * 365 * 86400))
        self.m.set("cram_dirty", 0)
        return advanced


Machine = N.Machine


def png(rgb: bytes, width: int = 160, height: int = 144, scale: int = 1) -> bytes:
    """An RGB888 buffer as a PNG file (stdlib zlib), optionally scaled up by pixel repetition."""
    rows = []
    for y in range(height):
        line = rgb[y * width * 3:(y + 1) * width * 3]
        if scale > 1:
            line = b"".join(line[i:i + 3] * scale for i in range(0, len(line), 3))
        rows.extend([b"\0" + line] * scale)
    raw = b"".join(rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width * scale, height * scale, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def wav(pcm: bytes, rate: int) -> bytes:
    """Signed 16-bit stereo PCM as a WAV file."""
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt " +
            struct.pack("<IHHIIHH", 16, 1, 2, rate, rate * 4, 4, 16) + b"data" + struct.pack("<I", len(pcm)) + pcm)


def frame_stats(rgb: bytes) -> dict:
    """How much of a frame is not one flat colour (a blank screen is a boot failure signal)."""
    px = [rgb[i:i + 3] for i in range(0, len(rgb), 3 * 7)]
    counts: dict = {}
    for p in px:
        counts[p] = counts.get(p, 0) + 1
    top = max(counts.values()) if counts else 0
    return {"colours": len(counts), "dominant_fraction": round(top / max(1, len(px)), 3)}


__all__ = ["GameBoy", "frame_stats", "header", "open_rom", "png", "wav"]
