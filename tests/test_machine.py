"""Machines as cards: instruction cards (conformance in every engine, timing and flag data), the Game Boy machine
on synthetic ROMs built by the card assembler (no game is needed or stored), banking, saves, the survey."""
import copy
import os
import random
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.machine import asm, bench, gb, isa, native, survey
from cardmodel.machine import build as Bd

SERIAL = [("LD SP,nn", 0xFFFE), ("LD HL,nn", "msg"),
          ("label", "loop"), ("LD A,(HL+)",), ("CP n", 0), ("JR Z,e", "done"),
          ("LDH (n),A", 0x01), ("LD A,n", 0x81), ("LDH (n),A", 0x02),
          ("label", "wait"), ("LDH A,(n)", 0x02), ("BIT 7,A",), ("JR NZ,e", "wait"), ("JR e", "loop"),
          ("label", "done"), ("HALT",), ("JR e", "done"),
          ("label", "msg"), ("db", b"Passed\n\0")]


def send_a():
    """Send A over the serial port and wait for the transfer."""
    return [("LDH (n),A", 0x01), ("LD A,n", 0x81), ("LDH (n),A", 0x02)]


def graphics_rom(ctx):
    """A checkerboard tile on the whole background, one sprite, the LCD on, then HALT in a loop on V-blank."""
    tile = bytes([0xAA, 0x55] * 8)
    prog = [("LD SP,nn", 0xFFFE), ("LD A,n", 0), ("LDH (n),A", 0x40),          # LCD off
            ("LD HL,nn", 0x8010), ("LD DE,nn", "tile"), ("LD B,n", 16),
            ("label", "copy"), ("LD A,(DE)",), ("LD (HL+),A",), ("INC DE",), ("DEC B",), ("JR NZ,e", "copy"),
            ("LD HL,nn", 0x9800), ("LD BC,nn", 0x0400),
            ("label", "fill"), ("LD A,n", 1), ("LD (HL+),A",), ("DEC BC",), ("LD A,B",), ("OR C",),
            ("JR NZ,e", "fill"),
            ("LD HL,nn", 0xFE00), ("LD A,n", 40), ("LD (HL+),A",), ("LD A,n", 30), ("LD (HL+),A",),
            ("LD A,n", 1), ("LD (HL+),A",), ("LD A,n", 0), ("LD (HL+),A",),
            ("LD A,n", 0xE4), ("LDH (n),A", 0x47), ("LD A,n", 0xD0), ("LDH (n),A", 0x48),
            ("LD A,n", 0x01), ("LDH (n),A", 0xFF), ("LD A,n", 0x93), ("LDH (n),A", 0x40), ("EI",),
            ("label", "idle"), ("HALT",), ("JR e", "idle"),
            ("label", "tile"), ("db", tile)]
    vblank = asm.assemble(ctx.store, [("RETI",)], org=0x40)
    return asm.rom(ctx.store, prog, title="GFXTEST", extra={0x40: vblank})


def mbc_rom(ctx, cart_type, rom_size_code, select):
    """Every bank n holds byte n at 0x4000; select each bank in turn and print what 0x4000 reads."""
    prog = [("LD SP,nn", 0xFFFE)]
    for bank, writes in select:
        for addr, value in writes:
            prog += [("LD A,n", value), ("LD (nn),A", addr)]
        prog += [("LD A,(nn)", 0x4000)] + send_a() + [("label", f"w{bank}"), ("LDH A,(n)", 0x02),
                                                     ("BIT 7,A",), ("JR NZ,e", f"w{bank}")]
    prog += [("label", "end"), ("HALT",), ("JR e", "end")]
    img = bytearray(asm.rom(ctx.store, prog, title="MBCTEST", cart_type=cart_type, rom_size_code=rom_size_code))
    for b in range(1, len(img) // 0x4000):
        img[b * 0x4000] = b & 0xFF
    return bytes(img)


class Instructions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_isa_cards_in_sync(self):
        r = isa.in_sync(self.ctx, "lr35902")
        self.assertEqual(r["status"], "pass", r["drifted"][:5])
        s = isa.summary(self.ctx.store, "lr35902")
        self.assertEqual(s["instructions"], 512)
        self.assertEqual(s["with_ir"], 512)

    def test_instruction_cards_conform_in_every_engine(self):
        r = bench.conformance(self.ctx, samples=2, seed=SEED)
        bad = {k: v["problems"] for k, v in r["per_card"].items() if v["status"] != "pass"}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertEqual(r["status"], "pass")
        self.assertGreaterEqual(len(r["engines"]), 3, r["unavailable"])

    def test_wrong_instruction_is_caught(self):
        """CM07: an engine running a wrong ADD (a SUB) must disagree with the reference."""
        ir = Bd.module(self.ctx, "lr35902_bench")
        bad = copy.deepcopy(ir)
        for f in bad["functions"]:
            if f["name"] == "LR35902_80":
                f["body"] = [{"k": "do", "value": ["CALL", "alu_sub", ["var", "B"], ["int", 0]]}]
        good_m, bad_m = native.load(self.ctx, ir, "ir"), native.load(self.ctx, bad, "host")
        card = self.ctx.store.get("isa/LR35902_80")
        rng = random.Random(SEED)
        caught = 0
        for _ in range(8):
            st = bench._case_state(rng, card, None)
            ram = rng.randbytes(0x10000)
            if bench._compare(bench.run_case(good_m, card, st, ram), bench.run_case(bad_m, card, st, ram)):
                caught += 1
        self.assertGreater(caught, 0, seed_note(self))

    def test_card_data_is_checked(self):
        card = self.ctx.store.get("isa/LR35902_09")
        m = native.load(self.ctx, Bd.module(self.ctx, "lr35902_bench"), "ir")
        st = bench._case_state(random.Random(SEED), card, None)
        out = bench.run_case(m, card, st, bytes(0x10000))
        self.assertEqual(bench.check_data(card, st, out, None), [])
        wrong = dict(card)
        wrong["cycles"] = 12
        wrong["flags"] = {"Z": "*", "N": "0", "H": "*", "C": "*"}
        self.assertTrue(any("cycles" in p for p in bench.check_data(wrong, st, out, None)))
        wrong["cycles"] = 8
        wrong["mcycles"] = ["fetch:PC"]
        self.assertTrue(any("mcycles" in p for p in bench.check_data(wrong, st, out, None)))

    def test_assembler_reads_the_cards(self):
        code = asm.assemble(self.ctx.store, [("label", "x"), ("LD A,n", 0x41), ("JR e", "x"), ("CALL nn", 0x1234),
                                             ("SET 7,(HL)",)], org=0x150)
        self.assertEqual(code, bytes([0x3E, 0x41, 0x18, 0xFC, 0xCD, 0x34, 0x12, 0xCB, 0xFE]))


class GameBoy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_machine_compiles(self):
        ir = Bd.module(self.ctx, "gameboy")
        st = Bd.stats(ir)
        self.assertGreater(st["functions"], 600)
        self.assertIn("run_frame", {f["name"] for f in ir["functions"] if f.get("export")})

    def test_serial_program_runs_the_same_in_every_engine(self):
        rom = asm.rom(self.ctx.store, SERIAL, title="SERIALTEST")
        seen = {}
        for engine in ("native", "host"):
            g = gb.GameBoy(self.ctx, rom, engine)
            for _ in range(3):
                g.run_frame()
            seen[engine] = (g.serial_text(), g.state_hash())
        self.assertEqual(seen["native"][0], "Passed\n")
        self.assertEqual(seen["native"], seen["host"])

    def test_reference_interpreter_runs_the_machine(self):
        """The IR reference interpreter executes the same machine module (slowly) and agrees on the serial bytes."""
        rom = asm.rom(self.ctx.store, SERIAL, title="SERIALTEST")
        g = gb.GameBoy(self.ctx, rom, "ir", sample_rate=0)
        g.m.call("run_dots", 70224 // 2)
        self.assertEqual(g.serial_text(), "Passed\n")

    def test_frame_hash_is_stable_across_engines(self):
        rom = graphics_rom(self.ctx)
        hashes = {}
        for engine in ("native", "host"):
            g = gb.GameBoy(self.ctx, rom, engine, sample_rate=0)
            for _ in range(4):
                g.run_frame()
            hashes[engine] = g.state_hash()
            f = g.frame()
            self.assertGreater(gb.frame_stats(f)["colours"], 1)
        self.assertEqual(hashes["native"], hashes["host"])

    def test_ei_halt_with_a_pending_interrupt(self):
        """EI; HALT while an interrupt is pending: the handler (reached through JP at 0x40) runs, and RETI returns
        to the HALT, which then waits (the HALT bug meeting the dispatch pushes the HALT's address)."""
        prog = [("LD SP,nn", 0xFFFE), ("XOR A",), ("LDH (n),A", 0x80), ("LD A,n", 0x01), ("LDH (n),A", 0xFF),
                ("LDH (n),A", 0x0F), ("EI",), ("HALT",), ("label", "loop"), ("HALT",), ("JR e", "loop")]
        extra = {0x40: asm.assemble(self.ctx.store, [("JP nn", 0x0200)], org=0x40),
                 0x200: asm.assemble(self.ctx.store, [("LDH A,(n)", 0x80), ("INC A",), ("LDH (n),A", 0x80),
                                                      ("RETI",)], org=0x200)}
        rom = asm.rom(self.ctx.store, prog, title="EIHALT", extra=extra)
        g = gb.GameBoy(self.ctx, rom, "native", sample_rate=0, fresh=True)
        for _ in range(6):
            g.run_frame()
        self.assertFalse(g.m.get("locked"))
        self.assertLess(g.m.get("PC"), 0x8000)
        self.assertIn(g.m.read("hram", 0, 1)[0], (5, 6, 7), "one V-blank handler run per frame")

    def test_dmg_oam_corruption(self):
        """The DMG's OAM bug (Pan Docs' write pattern): the IDU putting an address in FE00-FEFF on the bus during
        the OAM scan rewrites the row being read from the row before; row 0, other addresses and the CGB are
        spared (Blargg oam_bug is the hardware witness)."""
        m = native.IRMachine(self.ctx, Bd.module(self.ctx, "gameboy"))
        fill = bytes(range(0xA0))

        def after(addr, dot, cgb=0):
            m.array("oam")[:] = fill
            for k, v in {"lcdc": 0x91, "ly": 10, "first_line": 0, "mode": 2, "cgb": cgb, "md": 4, "now": 4000,
                         "line_start": 4000 - dot, "ppu_next": 99999}.items():
                m.set(k, v)
            m.call("idu", addr)
            return bytes(m.array("oam"))

        def word(b, r, i):
            return b[r * 8 + i * 2] | (b[r * 8 + i * 2 + 1] << 8)

        got = after(0xFE00, 8)                     # dot 8 of mode 2: the scan reads row 2
        a, b, c = word(fill, 2, 0), word(fill, 1, 0), word(fill, 1, 2)
        self.assertEqual(word(got, 2, 0), ((a ^ c) & (b ^ c)) ^ c)
        self.assertEqual(got[18:24], fill[10:16])
        self.assertEqual(got[:16] + got[24:], fill[:16] + fill[24:])
        for spared in (after(0xFE00, 0), after(0xFDFF, 8), after(0xFE00, 8, cgb=1), after(0xFE00, 80)):
            self.assertEqual(spared, fill)

    def test_a_run_of_eis_lets_the_interrupt_in_after_the_second(self):
        """EI only schedules IME; a second EI does not push it back (mooneye ei_sequence): with an interrupt
        pending, the handler's return address is the third EI's."""
        prog = [("LD SP,nn", 0xFFFE), ("LD A,n", 0x08), ("LDH (n),A", 0xFF), ("LDH (n),A", 0x0F)] + \
               [("EI",)] * 5 + [("label", "end"), ("HALT",), ("JR e", "end")]
        third_ei = 0x150 + 3 + 2 + 2 + 2 + 2
        handler = asm.assemble(self.ctx.store, [("POP BC",), ("LD A,B",), ("LDH (n),A", 0x80), ("LD A,C",),
                                                ("LDH (n),A", 0x81), ("label", "h"), ("JR e", "h")], org=0x58)
        rom = asm.rom(self.ctx.store, prog, title="EISEQ", extra={0x58: handler})
        g = gb.GameBoy(self.ctx, rom, "native", sample_rate=0, fresh=True)
        g.run_frame()
        self.assertEqual(list(g.m.read("hram", 0, 2)), [third_ei >> 8, third_ei & 0xFF])

    def test_cgb_hands_over_with_vram_open(self):
        """The CGB hands over in V-blank, so a Color game can probe the second VRAM bank at once (Trouballs does,
        within the first scanline's time, which a hand-over at the start of line 0 would put in mode 3)."""
        prog = [("LD SP,nn", 0xFFFE), ("LD A,n", 1), ("LDH (n),A", 0x4F)] + [("NOP",)] * 16 + [
                ("LD A,n", 0x5A), ("LD (nn),A", 0x8000), ("XOR A",), ("LDH (n),A", 0x4F),
                ("LD A,(nn)", 0x8000), ("LDH (n),A", 0x80), ("LD A,n", 1), ("LDH (n),A", 0x4F),
                ("LD A,(nn)", 0x8000), ("LDH (n),A", 0x81), ("label", "end"), ("HALT",), ("JR e", "end")]
        rom = asm.rom(self.ctx.store, prog, title="CGBVRAM", cgb=0x80)
        g = gb.GameBoy(self.ctx, rom, "native", sample_rate=0, fresh=True)
        g.run_frame()
        self.assertEqual(list(g.m.read("hram", 0, 2)), [0x00, 0x5A], "bank 0 and bank 1 differ: a Color")

    def test_cgb_raises_line_144s_mode2_source_a_cycle_before_vblank(self):
        """Line 144 raises the mode 2 STAT source: with V-blank on the DMG, one M-cycle (4 dots) before it on the
        CGB in either mode (mooneye vblank_stat_intr-GS and vblank_stat_intr-C are the hardware witnesses)."""
        m = native.IRMachine(self.ctx, Bd.module(self.ctx, "gameboy"))
        start = 100 * 456

        def requests(cgb, cgb_mode):
            for k, v in {"lcdc": 0x91, "ly": 143, "mode": 3, "first_line": 0, "line_start": start,
                         "ppu_next": start + 80 + 172, "stat_sel": 0x20, "stat_line": 0, "if_reg": 0, "cgb": cgb,
                         "cgb_mode": cgb_mode, "hdma_on": 0}.items():
                m.set(k, v)
            seen = []
            for t in (451, 452, 455, 456):
                m.set("now", start + t)
                m.call("ppu_sync")
                seen.append(m.get("if_reg") & 3)
            return seen

        self.assertEqual(requests(0, 0), [0, 0, 0, 3], "DMG: STAT (mode 2) and V-blank at the line's start")
        self.assertEqual(requests(1, 1), [0, 2, 2, 3], "CGB mode: STAT 4 dots early")
        self.assertEqual(requests(1, 0), [0, 2, 2, 3], "DMG compatibility mode: the same CGB PPU")

    def test_dmg_cartridge_on_the_cgb_runs_in_compatibility_mode(self):
        """A DMG cartridge on the CGB model runs as the CGB's boot ROM leaves it: KEY0 = 0x04 (DMG compatibility
        mode), OPRI = 1, the CPU registers mooneye boot_regs-cgb measures, the default compatibility palette from
        the gb_cgb card in BG 0 and OBJ 0/1, and the picture drawn through it. A CGB cartridge keeps CGB mode."""
        rom = graphics_rom(self.ctx)
        g = gb.GameBoy(self.ctx, rom, "native", model="cgb", sample_rate=0, fresh=True)
        self.assertEqual(g.model, "cgb-compat")
        regs = {r: g.m.get(r) for r in ("A", "F", "B", "C", "D", "E", "H", "L", "SP", "PC")}
        self.assertEqual(regs, {"A": 0x11, "F": 0x80, "B": 0, "C": 0, "D": 0, "E": 0x08, "H": 0, "L": 0x7C,
                                "SP": 0xFFFE, "PC": 0x100})
        self.assertEqual((g.m.get("key0"), g.m.get("opri"), g.m.get("cgb_mode")), (0x04, 1, 0))
        pal = self.ctx.store.get("hardware/gb_cgb").get("dmg_compat")["palettes"]

        def words(cs):
            return b"".join(bytes((c & 0xFF, c >> 8)) for c in cs)

        def rgb(c):
            return bytes((v << 3) | (v >> 2) for v in (c & 31, (c >> 5) & 31, (c >> 10) & 31))

        self.assertEqual(bytes(g.m.read("bgpal", 0, 8)), words(pal["bg"]))
        self.assertEqual(bytes(g.m.read("obpal", 0, 16)), words(pal["obj0"] + pal["obj1"]))
        for _ in range(4):
            g.run_frame()
        f = g.frame()
        colours = {f[i:i + 3] for i in range(0, len(f), 3)}
        self.assertLessEqual(colours, {rgb(c) for c in pal["bg"] + pal["obj0"]})
        self.assertGreater(len(colours), 2)
        host = gb.GameBoy(self.ctx, rom, "host", model="cgb", sample_rate=0)
        for _ in range(4):
            host.run_frame()
        self.assertEqual(host.state_hash(), g.state_hash(), "the same machine in Python and in C")
        cart = asm.rom(self.ctx.store, [("label", "x"), ("JR e", "x")], title="CGBCART", cgb=0x80)
        h = gb.GameBoy(self.ctx, cart, "native", model="cgb", sample_rate=0, fresh=True)
        self.assertEqual((h.model, h.m.get("key0"), h.m.get("cgb_mode"), h.m.get("D")), ("cgb", 0x80, 1, 0xFF))

    def test_compatibility_mode_registers_follow_their_cards(self):
        """In DMG compatibility mode every register a card gives a ``post_boot_dmg_compat`` value reads it after
        the boot; a ``locked`` one reads 0xFF and ignores writes, a ``read-only`` one keeps its value. The card
        data and the logic agree (mooneye boot_hwio-C and unused_hwio-C are the hardware witnesses)."""
        regs = [r for name in ("gb_joypad", "gb_serial", "gb_cgb", "gb_dma")
                for r in self.ctx.store.get(f"hardware/{name}").get("registers") if "post_boot_dmg_compat" in r]
        self.assertGreaterEqual(len(regs), 20)
        prog = [("LD SP,nn", 0xFFFE), ("LD HL,nn", 0xC000)]
        want = []
        for r in regs:
            a = r["address"] & 0xFF
            prog += [("LDH A,(n)", a), ("LD (HL+),A",)]
            want.append((r["name"], r["post_boot_dmg_compat"]))
            if r.get("dmg_compat"):
                for v in (0x00, 0xFF):
                    prog += [("LD A,n", v), ("LDH (n),A", a), ("LDH A,(n)", a), ("LD (HL+),A",)]
                    want.append((r["name"] + f" after writing {v:#04x}",
                                 0xFF if r["dmg_compat"] == "locked" else r["post_boot_dmg_compat"]))
        prog += [("label", "end"), ("HALT",), ("JR e", "end")]
        g = gb.GameBoy(self.ctx, asm.rom(self.ctx.store, prog, title="COMPATREGS"), "native", model="cgb",
                       sample_rate=0, fresh=True)
        g.run_frame()
        got = list(g.m.read("wram", 0, len(want)))
        self.assertEqual([(n, v) for (n, _), v in zip(want, got)], want)

    def test_title_checksum_sets_b_and_hl(self):
        """In DMG compatibility mode B is the boot ROM's title checksum (Nintendo-licensed cartridges only, old
        licensee 0x01 or 0x33 with "01") and HL is 0x991A when it is 0x43 or 0x58, else 0x007C (Pan Docs)."""
        def regs(title, old, new=b"\0\0"):
            img = bytearray(asm.rom(self.ctx.store, [("label", "x"), ("JR e", "x")]))
            img[0x134:0x144] = title.ljust(16, b"\0")
            img[0x144:0x146] = new
            img[0x14B] = old
            g = gb.GameBoy(self.ctx, bytes(img), "native", model="cgb", sample_rate=0, fresh=True)
            return g.m.get("B"), (g.m.get("H") << 8) | g.m.get("L")

        self.assertEqual(regs(b"\x43", 0x01), (0x43, 0x991A))
        self.assertEqual(regs(b"\x50\x08", 0x33, b"01"), (0x58, 0x991A))
        self.assertEqual(regs(b"TETRIS", 0x01), (sum(b"TETRIS") & 0xFF, 0x007C))
        self.assertEqual(regs(b"TETRIS", 0x00), (0, 0x007C))
        self.assertEqual(regs(b"TETRIS", 0x33, b"52"), (0, 0x007C))

    def test_mbc1_and_mbc5_banking(self):
        r1 = mbc_rom(self.ctx, 0x01, 2, [(1, [(0x2000, 1)]), (2, [(0x2000, 2)]), (3, [(0x2000, 3)]),
                                         (0, [(0x2000, 0)])])
        g = gb.GameBoy(self.ctx, r1, "native")
        for _ in range(3):
            g.run_frame()
        self.assertEqual(g.serial_text(), "\x01\x02\x03\x01", "MBC1: bank 0 selects bank 1")
        r5 = mbc_rom(self.ctx, 0x19, 2, [(1, [(0x2000, 1)]), (2, [(0x2000, 2)]), (0, [(0x2000, 0)])])
        g = gb.GameBoy(self.ctx, r5, "native")
        for _ in range(3):
            g.run_frame()
        self.assertEqual(g.serial_text(), "\x01\x02\x00", "MBC5: bank 0 is bank 0")

    def test_battery_ram_round_trips(self):
        prog = [("LD SP,nn", 0xFFFE), ("LD A,n", 0x0A), ("LD (nn),A", 0x0000), ("LD A,n", 0x5A),
                ("LD (nn),A", 0xA123), ("label", "end"), ("HALT",), ("JR e", "end")]
        rom = asm.rom(self.ctx.store, prog, title="SAVETEST", cart_type=0x03, ram_size_code=2)
        g = gb.GameBoy(self.ctx, rom, "native")
        g.run_frame()
        data = g.save_bytes()
        self.assertEqual(len(data), 8192)
        self.assertEqual(data[0x123], 0x5A)
        h = gb.GameBoy(self.ctx, rom, "native", fresh=True)
        h.load_save(data)
        self.assertEqual(h.save_bytes(), data)

    def test_survey_classifies_honestly(self):
        import tempfile
        from pathlib import Path
        d = Path(tempfile.mkdtemp(prefix="cardmodel_survey_"))
        (d / "runs.gb").write_bytes(graphics_rom(self.ctx))
        (d / "locks.gb").write_bytes(asm.rom(self.ctx.store, [("db", b"\xd3")], title="LOCK"))
        (d / "blank.gb").write_bytes(asm.rom(self.ctx.store, [("LD A,n", 0), ("LDH (n),A", 0x40),
                                                               ("label", "x"), ("JR e", "x")], title="BLANK"))
        r = survey.run(self.ctx, d, frames=120)
        by = {row["file"]: row["status"] for row in r["rows"]}
        self.assertEqual(by, {"blank.gb": "blank", "locks.gb": "locked", "runs.gb": "static"})


def _png_filtered(rows, depth=2):
    """A greyscale PNG whose rows use filters 0..4 in turn (the reader must undo each)."""
    import struct
    import zlib
    w = len(rows[0])
    raw, prev = b"", bytes((w * depth + 7) // 8)
    for y, row in enumerate(rows):
        packed = bytearray((w * depth + 7) // 8)
        for x, v in enumerate(row):
            packed[x * depth // 8] |= v << (8 - depth - (x * depth) % 8)
        f = y % 5
        line = bytearray()
        for i, cur in enumerate(packed):
            a = packed[i - 1] if i else 0
            b = prev[i]
            c = prev[i - 1] if i else 0
            pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
            pred = (0, a, b, (a + b) // 2, a if pa <= pb and pa <= pc else b if pb <= pc else c)[f]
            line.append((cur - pred) & 0xFF)
        raw += bytes([f]) + line
        prev = bytes(packed)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, len(rows), depth, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class TestROMs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_revisions_in_file_names(self):
        from cardmodel.machine import testroms as T
        self.assertEqual(T.revisions_named("boot_div-dmgABCmgb"), {"dmgABC", "mgb"})
        self.assertEqual(T.revisions_named("di_timing-GS"), {"dmg0", "dmgABC", "mgb", "sgb", "sgb2"})
        self.assertEqual(T.revisions_named("boot_regs-cgb"), {"cgb0", "cgbABCDE"})
        for stem in ("01-read_timing", "dmg-acid2", "add_sp_e_timing", "02-len ctr"):
            self.assertIsNone(T.revisions_named(stem), stem)

    def test_tests_for_other_hardware_are_skipped(self):
        from pathlib import Path
        from cardmodel.machine import testroms as T
        dmg_cart, cgb_cart = {"cgb": False}, {"cgb": True}
        self.assertEqual(T.model_for(self.ctx, Path("a/boot_regs-dmgABC.gb"), dmg_cart), ("dmg", ""))
        self.assertEqual(T.model_for(self.ctx, Path("a/ei_sequence.gb"), dmg_cart), ("auto", ""))
        self.assertEqual(T.model_for(self.ctx, Path("b/oam_bug/1-lcd_sync.gb"), cgb_cart), ("dmg", ""))
        self.assertIsNone(T.model_for(self.ctx, Path("a/boot_regs-sgb2.gb"), dmg_cart)[0])
        self.assertEqual(T.model_for(self.ctx, Path("a/boot_regs-cgb.gb"), dmg_cart), ("cgb", ""),
                         "a DMG cartridge for a CGB runs in its DMG compatibility mode")
        self.assertIsNone(T.model_for(self.ctx, Path("m/utils/dump_boot_hwio.gb"), dmg_cart)[0])

    def test_png_reader_undoes_every_filter(self):
        rows = [[(x * 7 + y * 3) % 4 for x in range(13)] for y in range(10)]
        w, h, rgb = gb.png_read(_png_filtered(rows))
        self.assertEqual((w, h), (13, 10))
        self.assertEqual([rgb[(y * w + x) * 3] for y in range(h) for x in range(w)],
                         [v * 85 for row in rows for v in row])

    def test_screen_test_against_a_reference(self):
        """A screen test passes when the picture equals the reference (DMG shades as the reference's greys) and
        fails, naming the pixels, when one pixel differs."""
        import tempfile
        from pathlib import Path
        from cardmodel.machine import testroms as T
        rom = graphics_rom(self.ctx)
        g = gb.GameBoy(self.ctx, rom, "native", sample_rate=0, fresh=True)
        for _ in range(T.SCREEN_FRAMES):
            g.run_frame()
        shades = {bytes(c): i for i, c in enumerate(self.ctx.store.get("hardware/gb_ppu").get("dmg_shades_rgb"))}
        f = g.frame()
        greys = bytearray(b"".join(bytes((T.DMG_GREYS[shades[f[i:i + 3]]],) * 3) for i in range(0, len(f), 3)))
        d = Path(tempfile.mkdtemp(prefix="cardmodel_screen_"))
        (d / "img").mkdir()
        (d / "screen-test.gb").write_bytes(rom)
        (d / "img" / "reference-dmg.png").write_bytes(gb.png(bytes(greys)))
        r = T.run_one(self.ctx, d / "screen-test.gb", root=d)
        self.assertEqual(r["verdict"], "pass", r)
        greys[(5 * 160 + 7) * 3:(5 * 160 + 7) * 3 + 3] = bytes((0x55,) * 3) if greys[(5 * 160 + 7) * 3] != 0x55 \
            else bytes((0xAA,) * 3)
        (d / "img" / "reference-dmg.png").write_bytes(gb.png(bytes(greys)))
        r = T.run_one(self.ctx, d / "screen-test.gb", root=d)
        self.assertEqual(r["verdict"], "fail")
        self.assertIn("1 of 23040 pixels differ", r["detail"])
        self.assertIn("x=7 y=5", r["detail"])


class ScreenModels(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_dmg_screen_test_runs_on_both_models(self):
        """A DMG screen test whose suite also has the CGB's picture (dmg-acid2) runs on the DMG and on the CGB in
        DMG compatibility mode, each against its own reference."""
        import tempfile
        from pathlib import Path
        from cardmodel.machine import testroms as T
        rom = graphics_rom(self.ctx)
        frames = {}
        for model in ("dmg", "cgb"):
            g = gb.GameBoy(self.ctx, rom, "native", model=model, sample_rate=0, fresh=True)
            for _ in range(T.SCREEN_FRAMES):
                g.run_frame()
            frames[model] = g.frame()
        shades = {bytes(c): i for i, c in enumerate(self.ctx.store.get("hardware/gb_ppu").get("dmg_shades_rgb"))}
        f = frames["dmg"]
        greys = b"".join(bytes((T.DMG_GREYS[shades[f[i:i + 3]]],) * 3) for i in range(0, len(f), 3))
        d = Path(tempfile.mkdtemp(prefix="cardmodel_screens_"))
        (d / "img").mkdir()
        (d / "screen-test.gb").write_bytes(rom)
        (d / "img" / "reference-dmg.png").write_bytes(gb.png(greys))
        (d / "img" / "reference-cgb.png").write_bytes(gb.png(frames["cgb"]))
        self.assertEqual(T.screen_models(d / "screen-test.gb", gb.header(rom, self.ctx.store)), ["dmg", "cgb"])
        r = T.run(self.ctx, d)
        self.assertEqual([(row["model"], row["verdict"]) for row in r["rows"]],
                         [("dmg", "pass"), ("cgb-compat", "pass")], r["rows"])


def busy_rom(ctx):
    """Loops over WRAM, bank switches (MBC1), LY reads, HALT and a V-blank handler: what lifted blocks must get
    exactly right."""
    prog = [("LD SP,nn", 0xFFFE), ("LD A,n", 0x01), ("LDH (n),A", 0xFF), ("EI",),
            ("label", "main"), ("LD HL,nn", 0xC000), ("LD B,n", 0),
            ("label", "loop"), ("LD A,(HL)",), ("ADD A,B",), ("LD (HL+),A",), ("INC B",), ("LD A,H",), ("CP n", 0xC4),
            ("JR NZ,e", "loop"),
            ("LD A,(nn)", 0x4000), ("INC A",), ("AND n", 3), ("LD (nn),A", 0x2000), ("LDH A,(n)", 0x44),
            ("LD (nn),A", 0xC000), ("LDH A,(n)", 0x80), ("RLCA",), ("LD (nn),A", 0xC001), ("HALT",), ("JR e", "main")]
    vblank = asm.assemble(ctx.store, [("PUSH AF",), ("LDH A,(n)", 0x80), ("INC A",), ("LDH (n),A", 0x80),
                                      ("POP AF",), ("RETI",)], org=0x40)
    img = bytearray(asm.rom(ctx.store, prog, title="BUSYTEST", cart_type=0x01, rom_size_code=1,
                            extra={0x40: vblank}))
    for b in range(1, 4):
        img[b * 0x4000] = b
    return bytes(img)


def speed_rom(ctx):
    """A CGB cartridge that switches to double speed with STOP (two bytes; the CPU skips the second) and then
    counts in WRAM: what follows STOP runs from the byte after both."""
    prog = [("LD SP,nn", 0xFFFE), ("LD A,n", 0x01), ("LDH (n),A", 0x4D), ("db", bytes([0x10, 0x00])),
            ("label", "main"), ("LD HL,nn", 0xC000), ("INC (HL)",), ("LDH A,(n)", 0x4D), ("LD (nn),A", 0xC001),
            ("JR e", "main")]
    return asm.rom(ctx.store, prog, title="SPEEDTEST", cgb=0xC0)


def overlay_rom(ctx):
    """Code in RAM as games run it: two routines copied over each other at C100 (another opcode at the same address)
    and one at C200 whose operand the program patches before every call; the main loop calls all three."""
    ra = asm.assemble(ctx.store, [("LD A,n", 0x11), ("LD (nn),A", 0xC000), ("RET",)], org=0xC100)
    rb = asm.assemble(ctx.store, [("LD A,(nn)", 0xC000), ("INC A",), ("LD (nn),A", 0xC001), ("RET",)], org=0xC100)
    rc = asm.assemble(ctx.store, [("LD A,n", 0x00), ("RET",)], org=0xC200)
    prog = [("LD SP,nn", 0xFFFE),
            ("LD HL,nn", 0xC200), ("LD DE,nn", "rc"), ("LD B,n", len(rc)), ("CALL nn", "copy"),
            ("label", "main"),
            ("LD HL,nn", 0xC100), ("LD DE,nn", "ra"), ("LD B,n", len(ra)), ("CALL nn", "copy"), ("CALL nn", 0xC100),
            ("LD HL,nn", 0xC100), ("LD DE,nn", "rb"), ("LD B,n", len(rb)), ("CALL nn", "copy"), ("CALL nn", 0xC100),
            ("LD A,(nn)", 0xC002), ("INC A",), ("LD (nn),A", 0xC002), ("LD (nn),A", 0xC201), ("CALL nn", 0xC200),
            ("LD (nn),A", 0xC003), ("JR e", "main"),
            ("label", "copy"), ("LD A,(DE)",), ("LD (HL+),A",), ("INC DE",), ("DEC B",), ("JR NZ,e", "copy"), ("RET",),
            ("label", "ra"), ("db", ra), ("label", "rb"), ("db", rb), ("label", "rc"), ("db", rc)]
    return asm.rom(ctx.store, prog, title="OVERLAYS")


class Lifting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.rom = busy_rom(cls.ctx)
        from cardmodel.machine import lift
        seen, entries = lift.profile_rom(cls.ctx, cls.rom, frames=30)
        cls.mod, cls.rep = lift.lift_rom(cls.ctx, cls.rom, 0xFFFF, seen, entries)

    def _run_pair(self, mod, frames=60, rom=None):
        import tempfile
        from pathlib import Path
        from cardmodel.machine import lift
        rom = rom or self.rom
        lib = lift.build_parts(self.ctx, mod, "c", Path(tempfile.mkdtemp(prefix="cardmodel_lift_")))
        m = native.CABIMachine(self.ctx, mod, "c", lib_path=lib)
        lifted = gb.GameBoy(self.ctx, rom, machine=m, sample_rate=0)
        m.set("lifted_on", 1)
        ref = gb.GameBoy(self.ctx, rom, "native", sample_rate=0, fresh=True)
        self.last_pair = (m, ref.m)
        for f in range(frames):
            lifted.run_frame()
            ref.run_frame()
            if lifted.state_hash() != ref.state_hash():
                return f, m.get("block_runs")
        return None, m.get("block_runs")

    def test_lifted_blocks_match_the_interpreter(self):
        self.assertGreater(self.rep["blocks"], 3)
        diverged, runs = self._run_pair(self.mod)
        self.assertIsNone(diverged, f"lifted run diverged at frame {diverged}")
        self.assertGreater(runs, 100, "blocks must actually run")

    def test_lifted_stop_switches_speed_and_skips_its_second_byte(self):
        from cardmodel.machine import lift
        rom = speed_rom(self.ctx)
        seen, entries = lift.profile_rom(self.ctx, rom, frames=5)
        mod, _ = lift.lift_rom(self.ctx, rom, 0x7FFF, seen, entries)
        diverged, _ = self._run_pair(mod, frames=10, rom=rom)
        self.assertIsNone(diverged, f"lifted run diverged at frame {diverged}")
        m, ref = self.last_pair
        self.assertTrue(ref.read("wram")[1] & 0x80, "the cartridge runs at double speed")
        self.assertEqual(m.get("interpreted"), 0, "STOP and everything after it ran as lifted card IR")

    def test_routines_copied_over_each_other_and_patched_operands_run_lifted(self):
        from cardmodel.machine import lift
        rom = overlay_rom(self.ctx)
        p = lift.profile(self.ctx, rom, 5)
        mod, rep = lift.lift_rom(self.ctx, rom, 0x7FFF, p["seen"], p["entries"], ram_ops=p["ram_ops"],
                                 ram_cb=p["ram_cb"])
        self.assertEqual(sorted(e[0] for e in lift.ram_encodings(p["ram_ops"], p["ram_cb"])[0xC100]), [0x3E, 0xFA],
                         "both routines' first instructions at C100")
        diverged, _ = self._run_pair(mod, frames=10, rom=rom)
        self.assertIsNone(diverged, f"lifted run diverged at frame {diverged}")
        m, ref = self.last_pair
        self.assertGreater(ref.read("wram")[2], 0, "the patched operand counts up")
        self.assertEqual(m.get("interpreted_ram"), 0, "every RAM instruction ran as lifted card IR")
        self.assertEqual(m.get("interpreted"), 0)

    def test_planted_lifter_bug_is_caught(self):
        """CM07: change the loop bound (CP 0xC4 -> 0xC3) in every lifted block; the differential run must see it."""
        bad = copy.deepcopy(self.mod)
        hits = []

        def mutate(x):
            if isinstance(x, list):
                if x == ["int", 0xC4]:
                    hits.append(True)
                    x[1] = 0xC3
                    return
                for y in x:
                    mutate(y)
            elif isinstance(x, dict):
                for y in x.values():
                    mutate(y)

        for f in bad["functions"]:
            if f["name"].startswith("blk_"):
                mutate(f["body"])
        self.assertTrue(hits, "the loop's CP 0xC4 must be a constant in a lifted block")
        diverged, _ = self._run_pair(bad, frames=20)
        self.assertIsNotNone(diverged)


class Shell(unittest.TestCase):
    """CM21 for machines: the machine module does no I/O; the shell around it is the only effect."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_shell_is_the_only_effect(self):
        ir = Bd.module(self.ctx, "gameboy")
        names = {f["name"] for f in ir["functions"]}
        from cardmodel.machine.lift import _exprs, _stmts
        calls = {x[1] for f in ir["functions"] for st in _stmts(f["body"]) for x in _exprs(st) if x[0] == "CALL"}
        self.assertLessEqual(calls, names, "every call stays inside the machine module (no host functions)")
        ops = {x[0] for f in ir["functions"] for st in _stmts(f["body"]) for x in _exprs(st)}
        effect_ops = {o for o in ops if o in self.ctx.ops and self.ctx.ops[o].card.get("effect")}
        self.assertEqual(effect_ops, set())
        # the headless shell's frame is exactly the machine's frame for the same run
        import tempfile
        from pathlib import Path
        from cardmodel.machine import shell
        d = Path(tempfile.mkdtemp(prefix="cardmodel_shell_"))
        (d / "gfx.gb").write_bytes(graphics_rom(self.ctx))
        s = shell.Session(self.ctx, d / "gfx.gb", engine="native", sample_rate=0, save_dir=d)
        r = shell.run_headless(s, 5)
        g = gb.GameBoy(self.ctx, graphics_rom(self.ctx), "native", sample_rate=0, fresh=True)
        for _ in range(5):
            g.run_frame()
        self.assertEqual(r["frame"], g.frame())

    def test_web_shell_streams_the_machines_frames(self):
        import base64
        import os
        import socket
        import tempfile
        import threading
        from pathlib import Path
        from cardmodel.machine import shell
        d = Path(tempfile.mkdtemp(prefix="cardmodel_web_"))
        (d / "gfx.gb").write_bytes(graphics_rom(self.ctx))
        sess = shell.Session(self.ctx, d / "gfx.gb", engine="native", sample_rate=0, save_dir=d)
        ports = []
        orig_log = []
        t = threading.Thread(target=lambda: ports.append(shell.serve(sess, port=0, open_browser=False,
                                                                     log=orig_log.append)), daemon=True)
        t.start()
        for _ in range(100):
            if orig_log:
                break
            __import__("time").sleep(0.05)
        port = int(orig_log[0].split("127.0.0.1:")[1].split("/")[0])
        c = socket.create_connection(("127.0.0.1", port), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        c.sendall(f"GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                  f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        ws = shell._WS(c)
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += c.recv(1)
        self.assertIn(b"101", buf.split(b"\r\n")[0])

        def frame():
            h = ws._exact(2)
            n = h[1] & 0x7F
            if n == 126:
                n = int.from_bytes(ws._exact(2), "big")
            elif n == 127:
                n = int.from_bytes(ws._exact(8), "big")
            return h[0] & 0x0F, ws._exact(n)

        op, hello = frame()
        self.assertEqual(op, 1)
        self.assertIn(b"GFXTEST", hello)
        op, video = frame()
        self.assertEqual(video[0], 1)
        g = gb.GameBoy(self.ctx, graphics_rom(self.ctx), "native", sample_rate=0, fresh=True)
        g.run_frame()
        self.assertEqual(video[1:], g.frame(), "the first streamed frame is the machine's first frame")
        mask = os.urandom(4)
        msg = b'{"cmd": "quit"}'
        c.sendall(bytes([0x81, 0x80 | len(msg)]) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(msg)))
        t.join(timeout=10)
        self.assertFalse(t.is_alive())

    def test_input_script(self):
        from cardmodel.machine import shell
        self.assertEqual(shell.parse_input("10:start,16:-,20:a+right"), {10: 0x80, 16: 0, 20: 0x11})
        with self.assertRaises(ValueError):
            shell.parse_input("5:jump")


def synthetic_nds() -> bytes:
    """A tiny DS image: the ARM9 sums 1..10, stores it and sends it through the IPC FIFO; the ARM7 receives it and
    stores it too (hand-encoded ARM words; the secure area marker so the loader accepts it)."""
    import struct
    arm9 = [0xE7FFDEFF, 0xE7FFDEFF, 0xE3A00000, 0xE3A0100A, 0xE0800001, 0xE2511001, 0x1AFFFFFC, 0xE3A02621,
            0xE5820000, 0xE3A03301, 0xE3833E18, 0xE3A04902, 0xE3844008, 0xE1C340B4, 0xE5830008, 0xEAFFFFFE]
    arm7 = [0xE3A03301, 0xE3833E18, 0xE3A04902, 0xE1C340B4, 0xE1D350B4, 0xE3150C01, 0x1AFFFFFA, 0xE3A06641,
            0xE5967000, 0xE3A02621, 0xE5827004, 0xEAFFFFFE]
    img = bytearray(0x10000)
    img[0:6] = b"CMTEST"
    img[12:16] = b"CMTS"
    struct.pack_into("<IIII", img, 0x20, 0x4000, 0x02000008, 0x02000000, len(arm9) * 4)
    struct.pack_into("<IIII", img, 0x30, 0x8000, 0x02380000, 0x02380000, len(arm7) * 4)
    img[0x4000:0x4000 + len(arm9) * 4] = struct.pack(f"<{len(arm9)}I", *arm9)
    img[0x8000:0x8000 + len(arm7) * 4] = struct.pack(f"<{len(arm7)}I", *arm7)
    return bytes(img)


class ARM(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_arm_cards_conform_in_every_engine(self):
        r = bench.conformance(self.ctx, "armv5te", samples=2, seed=SEED)
        bad = {k: v["problems"] for k, v in r["per_card"].items() if v["status"] != "pass"}
        self.assertEqual(bad, {}, seed_note(self))
        self.assertGreaterEqual(len(r["engines"]), 3)
        self.assertEqual(isa.in_sync(self.ctx, "armv5te")["status"], "pass")

    def test_wrong_arm_instruction_is_caught(self):
        ir = Bd.module(self.ctx, "armv5te_bench")
        bad = copy.deepcopy(ir)
        for f in bad["functions"]:
            if f["name"] == "ARM_ADD_rsi":
                f["name"] = "ARM_ADD_rsi"
                for g in bad["functions"]:
                    if g["name"] == "ARM_SUB_rsi":
                        f["body"] = copy.deepcopy(g["body"])
                        f["locals"] = dict(g.get("locals") or {})
        good_m, bad_m = native.load(self.ctx, ir, "ir"), native.load(self.ctx, bad, "host")
        card = self.ctx.store.get("isa/ARM_ADD_rsi")
        rng = random.Random(SEED)
        caught = 0
        for _ in range(8):
            op = 0xE0800000 | (rng.getrandbits(4) << 12) | (rng.getrandbits(4) << 16) | rng.getrandbits(4)
            st = bench._arm_state(rng, card)
            ram = rng.randbytes(0x10000)
            a, b = bench.run_arm_case(good_m, st, op, ram), bench.run_arm_case(bad_m, st, op, ram)
            caught += a["regs"] != b["regs"] or a["cpsr"] != b["cpsr"]
        self.assertGreater(caught, 0, seed_note(self))

    def test_ds_machine_runs_both_cpus(self):
        from cardmodel.machine import nds
        ds = nds.DS(self.ctx, synthetic_nds())
        ds.run(3)
        mram = ds.m.read("mram", 0x100000, 8)
        self.assertEqual(int.from_bytes(mram[0:4], "little"), 55, "the ARM9 summed 1..10")
        self.assertEqual(int.from_bytes(mram[4:8], "little"), 55, "the ARM7 received it over the IPC FIFO")
        cov = nds.coverage(ds)
        self.assertEqual(cov["cpus"]["arm9"]["undecodable_executed"], 0)
        self.assertIn("ARM_ADD_rsi", cov["cpus"]["arm9"]["card_uses"])

    def test_encrypted_secure_area_is_refused(self):
        from cardmodel.machine import nds
        img = bytearray(synthetic_nds())
        img[0x4000:0x4008] = bytes(8)
        with self.assertRaises(ValueError):
            nds.DS(self.ctx, bytes(img))


class ArmLifting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_lifted_arm_code_matches_the_interpreter(self):
        import tempfile
        from cardmodel.machine import lift_arm
        r = lift_arm.differential(self.ctx, synthetic_nds(), 2, 4, out_dir=tempfile.mkdtemp(prefix="cardmodel_arm_"))
        self.assertEqual(r["verdict"], "identical", r)
        self.assertGreater(r["blocks"], 0)
        self.assertGreater(r["block_runs"], 0)

    def test_planted_arm_lifter_bug_is_caught(self):
        """CM07: the lifted block loads 9 instead of 10 as the loop bound; the sum in RAM must differ (45, not 55)."""
        import tempfile
        from pathlib import Path
        from cardmodel.machine import lift, lift_arm, native as N, nds
        prof = nds.DS(self.ctx, synthetic_nds())
        prof.run(2)
        mod, _ = lift_arm.lifted_nds_module(self.ctx, prof)
        hits = []

        def mutate(x):
            if isinstance(x, list):
                if x == ["int", 10] and not hits:
                    hits.append(True)
                    x[1] = 9
                for y in x:
                    mutate(y)
            elif isinstance(x, dict):
                for y in x.values():
                    mutate(y)

        for f in mod["functions"]:
            if f["name"].startswith("ablk_"):
                mutate(f["body"])
        self.assertTrue(hits)
        lib = lift.build_parts(self.ctx, mod, "c", Path(tempfile.mkdtemp(prefix="cardmodel_arm_")))
        ml = N.CABIMachine(self.ctx, mod, "c", lib_path=lib)
        d = nds.DS.__new__(nds.DS)
        d.ctx, d.rom, d.info, d.ir, d.m = self.ctx, synthetic_nds(), nds.header(synthetic_nds(), self.ctx.store), mod, ml
        d.load()
        ml.set("lifted_on", 1)
        ml.call("run_frame")
        self.assertNotEqual(int.from_bytes(ml.read("mram", 0x100000, 4), "little"), 55)


class FreshCopies(unittest.TestCase):
    """A fresh native machine loads a private copy of its library. The copy goes with the machine (closed or
    collected), and copies a killed process left behind go when the next process makes a fresh machine; 8,918 had
    piled up in the temp folder (about 2 GB) before."""

    def test_a_fresh_copy_goes_with_its_machine(self):
        import gc
        from pathlib import Path
        ctx = model_ctx()
        try:
            m = native.load(ctx, Bd.module(ctx, "gameboy"), "native", fresh=True)
        except native.EngineError as exc:
            self.skipTest(f"no native engine here: {exc}")
        d = Path(m._tmpdir)
        self.assertTrue(d.is_dir() and d.name.startswith(f"{native.COPY_PREFIX}{os.getpid()}-"))
        del m
        gc.collect()
        self.assertFalse(d.exists(), "collected: its copy is gone")
        m = native.load(ctx, Bd.module(ctx, "gameboy"), "native", fresh=True)
        d = Path(m._tmpdir)
        m.close()
        self.assertFalse(d.exists(), "closed: its copy is gone")
        m.close()                                    # twice is fine

    def test_copies_of_a_process_that_is_gone_are_swept(self):
        import subprocess
        import tempfile
        from pathlib import Path
        tmp = Path(tempfile.mkdtemp(prefix="cardmodel_sweep_"))
        p = subprocess.Popen(["true"])
        p.wait()                                     # a process id that no longer runs
        dead = tmp / f"{native.COPY_PREFIX}{p.pid}-abc"
        mine = tmp / f"{native.COPY_PREFIX}{os.getpid()}-def"
        old = tmp / f"cardmodel_machine_{p.pid}_x1"  # named before process ids (mkdtemp's letters): left alone
        other = tmp / "unrelated_1"
        for d in (dead, mine, old, other):
            d.mkdir()
            (d / "lib.dylib").write_bytes(b"x")
        self.assertEqual(native.sweep_copies(tmp), 1)
        self.assertEqual(sorted(x.name for x in tmp.iterdir()), sorted([mine.name, old.name, other.name]))


if __name__ == "__main__":
    unittest.main()
