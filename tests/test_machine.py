"""Machines as cards: instruction cards (conformance in every engine, timing and flag data), the Game Boy machine
on synthetic ROMs built by the card assembler (no game is needed or stored), banking, saves, the survey."""
import copy
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


if __name__ == "__main__":
    unittest.main()
