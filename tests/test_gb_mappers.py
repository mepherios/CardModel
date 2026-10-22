"""The cartridge boards beyond MBC1/2/3/5, each card logic in hardware/gb_cartridge (CM32): MBC7 (banks, the
accelerometer, the 93LC56 EEPROM and its save), HuC3 (banks, RAM modes, the clock chip's commands, the infrared
port, the clock's save), the Game Boy Camera (banks, RAM, the sensor's registers, the capture's time and the picture
in RAM), Wisdom Tree (32 KiB banks by address) and Sachen (the scrambled header page, base and mask), the CGB boot's
BCPS, and the survey's second run without input. Every cartridge is built by the card assembler; no game is needed
or stored, and neither is the Nintendo logo: the boards recognised by it get a 48-byte stand-in, whose CRC the
test's own copy of the cartridge card is given."""
import unittest
import zlib

from helpers import model_ctx

from cardmodel.machine import asm, gb, lift, survey
from cardmodel.machine import build as Bd

WRAM = 0xC000          # results land in work RAM: the machine's `wram` array from index 0
FLAG = 0xF0            # a WRAM byte the test sets to let a program go on
STAND_IN = bytes((7 * k + 3) & 0xFF for k in range(48))     # the tests' own "logo"


def st(addr, value):
    return [("LD A,n", value), ("LD (nn),A", addr)]


def keep(src, slot):
    return [("LD A,(nn)", src), ("LD (nn),A", WRAM + slot)]


def wait_flag(label):
    return [("label", label), ("LD A,(nn)", WRAM + FLAG), ("CP n", 1), ("JR NZ,e", label)]


END = [("label", "end"), ("HALT",), ("JR e", "end")]


def cart(ctx, prog, cart_type, rom_size_code=2, ram_size_code=0, cgb=0):
    """A cartridge running ``prog``; byte 0x4000 of bank n (n >= 1) holds n."""
    img = bytearray(asm.rom(ctx.store, [("LD SP,nn", 0xFFFE), *prog, *END], title="BOARD", cart_type=cart_type,
                            rom_size_code=rom_size_code, ram_size_code=ram_size_code, cgb=cgb))
    for b in range(1, len(img) // 0x4000):
        img[b * 0x4000] = b
    return bytes(img)


def run(g, frames=3, buttons=0):
    for _ in range(frames):
        g.set_buttons(buttons)
        g.run_frame()
    return g


def results(g, n=64):
    return g.m.read("wram", 0, n)


def logo_ctx():
    """A context whose cartridge card fingerprints the stand-in logo instead of Nintendo's."""
    ctx = model_ctx()
    card = ctx.store.get("hardware/gb_cartridge")
    card["unlicensed"] = {**card["unlicensed"], "logo_crc32": zlib.crc32(STAND_IN)}
    return ctx


# -- MBC7 -----------------------------------------------------------------------------------------------------
EE = 0xA080


def ee_pins(cs, clk, di):
    return st(EE, (cs << 7) | (clk << 6) | (di << 1))


def ee_send(bits):
    out = []
    for b in bits:
        out += ee_pins(1, 0, b) + ee_pins(1, 1, b)
    return out


def ee_command(op, addr, data=None):
    """Start bit, opcode, 8 address bits (and 16 data bits) with CS high, then CS low."""
    bits = [1, (op >> 1) & 1, op & 1] + [(addr >> (7 - i)) & 1 for i in range(8)]
    if data is not None:
        bits += [(data >> (15 - i)) & 1 for i in range(16)]
    return ee_pins(0, 0, 0) + ee_pins(1, 0, 0) + ee_send(bits) + ee_pins(0, 0, 0)


def ee_read(addr, slot):
    """READ: DO after the address (the dummy 0) into ``slot``, then after each of 16 rising edges."""
    out = ee_pins(0, 0, 0) + ee_pins(1, 0, 0) + ee_send([1, 1, 0] + [(addr >> (7 - i)) & 1 for i in range(8)])
    out += keep(EE, slot)
    for i in range(16):
        out += ee_pins(1, 0, 0) + ee_pins(1, 1, 0) + keep(EE, slot + 1 + i)
    return out + ee_pins(0, 0, 0)


def ee_word(data, slot):
    return sum((data[slot + 1 + i] & 1) << (15 - i) for i in range(16))


class MBC7(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_banks_and_the_accelerometer(self):
        prog = [*st(0x2000, 3), *keep(0x4000, 0), *st(0x2000, 0), *keep(0x4000, 1),
                *keep(0xA020, 2),                                      # registers closed: 0xFF
                *st(0x0000, 0x0A), *st(0x4000, 0x40),
                *st(0xA000, 0x55), *keep(0xA020, 3), *keep(0xA030, 4),  # erased: 0x8000
                *st(0xA010, 0xAA), *[x for k in range(4) for x in keep(0xA020 + 0x10 * k, 5 + k)],
                *wait_flag("w1"),
                *st(0xA010, 0xAA), *keep(0xA020, 9), *keep(0xA030, 10),  # no erase first: no new latch
                *st(0xA000, 0x55), *st(0xA010, 0xAA),
                *[x for k in range(4) for x in keep(0xA020 + 0x10 * k, 11 + k)], *keep(0xA060, 15)]
        g = run(gb.GameBoy(self.ctx, cart(self.ctx, prog, 0x22), "native", sample_rate=0))
        self.assertEqual(g.info["mbc"], "mbc7")
        r = results(g)
        self.assertEqual((r[0], r[1], r[2]), (3, 0, 0xFF), "bank 3, bank 0 as itself, registers closed")
        self.assertEqual((r[3], r[4]), (0x00, 0x80))
        self.assertEqual(bytes(r[5:9]), bytes([0xD0, 0x81, 0xD0, 0x81]), "level: 0x81D0 on both axes")
        g.m.write("wram", b"\x01", FLAG)
        run(g, 2, buttons=0x01 | 0x04)                                 # right and up on the pad
        r = results(g)
        self.assertEqual(bytes(r[9:11]), bytes([0xD0, 0x81]), "0xAA latches only after 0x55")
        self.assertEqual(r[11] | (r[12] << 8), 0x81D0 - 0x70, "right lowers X by 1 g")
        self.assertEqual(r[13] | (r[14] << 8), 0x81D0 + 0x70, "up raises Y by 1 g")
        self.assertEqual(r[15], 0x00)

    def test_eeprom_protocol_and_save(self):
        prog = [*st(0x0000, 0x0A), *st(0x4000, 0x40),
                *ee_command(0, 0xC0),                     # EWEN
                *ee_command(1, 5, 0xBEEF),                # WRITE word 5
                *ee_command(0, 0x00),                     # EWDS
                *ee_command(1, 6, 0x1234),                # ignored: writes disabled
                *ee_read(5, 0), *ee_read(6, 20)]
        rom = cart(self.ctx, prog, 0x22)
        g = run(gb.GameBoy(self.ctx, rom, "native", sample_rate=0))
        r = results(g)
        self.assertEqual(r[0] & 1, 0, "the dummy bit before the data")
        self.assertEqual(ee_word(r, 0), 0xBEEF)
        self.assertEqual(ee_word(r, 20), 0x0000, "a write after EWDS changes nothing")
        self.assertEqual(g.m.read("cram", 10, 2), b"\xbe\xef", "word 5, high byte first")
        save = g.save_bytes()
        self.assertEqual((len(save), save[10:12]), (8192, b"\xbe\xef"),
                         "the save is the unsized RAM every host gives (the player too), the EEPROM its first 256 bytes")
        reader = cart(self.ctx, [*st(0x0000, 0x0A), *st(0x4000, 0x40), *ee_read(5, 0)], 0x22)
        h = gb.GameBoy(self.ctx, reader, "native", sample_rate=0, fresh=True)
        h.load_save(save)
        self.assertEqual(ee_word(results(run(h)), 0), 0xBEEF, "the save comes back")


# -- HuC3 -----------------------------------------------------------------------------------------------------
def huc3_cmd(c):
    """The way Robopon talks to the clock chip: the command in mode 0xB, then 0xFE to the semaphore."""
    return st(0x0000, 0x0B) + st(0xA000, c) + st(0x0000, 0x0D) + st(0xA000, 0xFE)


def huc3_answer(slot):
    return st(0x0000, 0x0C) + keep(0xA000, slot)


class HuC3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_banks_modes_clock_and_save(self):
        prog = [*st(0x2000, 3), *keep(0x4000, 0), *st(0x2000, 0), *keep(0x4000, 1),
                *st(0x0000, 0x0A), *st(0x4000, 1), *st(0xA123, 0x5A), *keep(0xA123, 2),
                *st(0x0000, 0x00), *st(0xA123, 0x77), *keep(0xA123, 3),      # mode 0: read-only
                *st(0x0000, 0x0D), *keep(0xA000, 4),                          # the semaphore: ready
                *st(0x0000, 0x0E), *keep(0xA000, 5),                          # infrared: no light
                # the clock: 1439 minutes (0x59F) of day 0x123, low nibbles first, then "set from nibbles"
                *huc3_cmd(0x40), *huc3_cmd(0x50),
                *huc3_cmd(0x3F), *huc3_cmd(0x39), *huc3_cmd(0x35), *huc3_cmd(0x33), *huc3_cmd(0x32), *huc3_cmd(0x31),
                *huc3_cmd(0x61), *wait_flag("w1"),
                *huc3_cmd(0x60), *huc3_cmd(0x40), *huc3_cmd(0x50),
                *[x for k in range(6) for x in huc3_cmd(0x10) + huc3_answer(8 + k)],
                *huc3_cmd(0x62), *huc3_answer(14)]
        rom = cart(self.ctx, prog, 0xFE, ram_size_code=3)
        g = run(gb.GameBoy(self.ctx, rom, "native", sample_rate=0))
        self.assertEqual((g.info["mbc"], g.info["rtc"], g.info["ram_size"]), ("huc3", True, 32768))
        r = results(g)
        self.assertEqual((r[0], r[1]), (3, 0))
        self.assertEqual((r[2], r[3]), (0x5A, 0x5A), "RAM bank 1 written in mode 0xA, not in mode 0")
        self.assertEqual(r[4] & 1, 1)
        self.assertEqual(r[5], 0xC0)
        g.m.call("rtc_add_seconds", 60)                                  # one more minute: the next day
        g.m.write("wram", b"\x01", FLAG)
        r = results(run(g))
        self.assertEqual([x & 0x0F for x in r[8:14]], [0, 0, 0, 4, 2, 1], "minute 0 of day 0x124")
        self.assertEqual(r[8] >> 4, 1, "the answer carries its command")
        self.assertEqual(r[14] & 0x0F, 1)
        save = g.save_bytes()
        self.assertEqual(len(save), 32768 + 48, "RAM, then the clock in the common trailer")
        h = gb.GameBoy(self.ctx, rom, "native", sample_rate=0, fresh=True)
        h.load_save(save)
        self.assertEqual((h.m.get("rtc_dl"), h.m.get("rtc_dh"), h.m.get("rtc_h"), h.m.get("rtc_m")), (0x24, 0x1, 0, 0))


# -- the Game Boy Camera ------------------------------------------------------------------------------------------
POLL_MCYCLES = 11      # INC BC (2), LD A,(nn) (4), AND n (2), JR NZ,e taken (3)


def camera_rom(ctx, thresholds, c=0x0100, n_bit=True):
    prog = [*st(0x2000, 3), *keep(0x4000, 0), *st(0x2000, 0), *keep(0x4000, 1),
            *st(0x0000, 0x0A), *st(0x4000, 0x02), *st(0xA010, 0x33), *keep(0xA010, 2),
            *st(0x4000, 0x10), *keep(0xA000, 3), *keep(0xA001, 4),
            *st(0xA001, 0x80 if n_bit else 0x00), *st(0xA002, c >> 8), *st(0xA003, c & 0xFF), *st(0xA004, 0x00),
            *[x for k in range(16) for i, t in enumerate(thresholds) for x in st(0xA006 + 3 * k + i, t)],
            *st(0xA000, 0x01), *keep(0xA000, 5),
            ("LD BC,nn", 0), ("label", "poll"), ("INC BC",), ("LD A,(nn)", 0xA000), ("AND n", 1), ("JR NZ,e", "poll"),
            ("LD A,B",), ("LD (nn),A", WRAM + 6), ("LD A,C",), ("LD (nn),A", WRAM + 7),
            *st(0x4000, 0x00), *keep(0xA100, 8)]
    return cart(ctx, prog, 0xFC, rom_size_code=2, ram_size_code=4)


class Camera(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_registers_capture_time_and_picture(self):
        g = run(gb.GameBoy(self.ctx, camera_rom(self.ctx, (0x00, 0x00, 0x00)), "native", sample_rate=0), 5)
        self.assertEqual((g.info["mbc"], g.info["ram_size"], g.info["battery"]), ("camera", 131072, True))
        r = results(g)
        self.assertEqual((r[0], r[1], r[2]), (3, 0, 0x33), "banks, and RAM bank 2 (always readable)")
        self.assertEqual((r[3], r[4], r[5] & 1), (0, 0, 1), "idle, write-only registers read 0, then busy")
        mcycles = ((r[6] << 8) | r[7]) * POLL_MCYCLES
        want = 32446 + 16 * 0x0100                                        # N set: no 512 extra
        self.assertLessEqual(abs(mcycles - want), 2 * POLL_MCYCLES, f"busy {mcycles} M-cycles, want {want}")
        self.assertEqual(g.m.read("cram", 0x100, 0xE00), bytes(0xE00), "every pixel above every threshold: white")
        g = run(gb.GameBoy(self.ctx, camera_rom(self.ctx, (0xFF, 0xFF, 0xFF)), "native", sample_rate=0), 5)
        self.assertEqual(g.m.read("cram", 0x100, 0xE00), b"\xff" * 0xE00, "below every threshold: black")
        self.assertEqual(results(g)[8], 0xFF, "the CPU reads the picture in RAM bank 0 at 0x100")
        g = run(gb.GameBoy(self.ctx, camera_rom(self.ctx, (0x04, 0x08, 0x0C), n_bit=False), "native",
                           sample_rate=0), 5)
        r = results(g)
        mcycles = ((r[6] << 8) | r[7]) * POLL_MCYCLES
        self.assertLessEqual(abs(mcycles - (32446 + 512 + 16 * 0x0100)), 2 * POLL_MCYCLES, "N clear: 512 more")
        self.assertGreater(len(set(g.m.read("cram", 0x100, 0xE00))), 8, "a scene, cut into four shades")
        self.assertTrue(g.m.get("cram_dirty"))


# -- Wisdom Tree and Sachen -------------------------------------------------------------------------------------
class Unlicensed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = logo_ctx()

    def kind_after_power_on(self, rom):
        """The board power_on settles on when the host only set the type byte's controller (the player's way)."""
        g = gb.GameBoy(self.ctx, rom, "native", sample_rate=0)
        card = self.ctx.store.get("hardware/gb_cartridge")
        raw = (card["types"].get(f"0x{rom[0x147]:02X}") or {}).get("mbc", "none")
        g.m.set("mbc_kind", card["mbc_kind"].get(raw, 0))
        g.m.call("power_on", 0)
        return g.m.get("mbc_kind")

    def test_wisdom_tree_switches_32_kib_by_address(self):
        prog = []
        for k, b in enumerate((2, 1, 3, 0)):
            prog += [("LD (nn),A", b), *keep(0x4000, 2 * k), *keep(0x3FF0, 2 * k + 1)]
        bank0 = bytearray(asm.rom(self.ctx.store, [("LD SP,nn", 0xFFFE), *prog, *END], title="WISDOM"))
        bank0[0x104:0x134] = STAND_IN
        img = bytearray()
        for b in range(4):
            bank = bytearray(bank0)
            bank[0x3FF0] = 0x10 + b
            bank[0x4000] = 0x20 + b
            img += bank
        rom = bytes(img)
        info = gb.header(rom, self.ctx.store)
        self.assertEqual(info["mbc"], "wisdom_tree")
        g = run(gb.GameBoy(self.ctx, rom, "native", sample_rate=0))
        self.assertEqual(list(results(g, 8)), [0x22, 0x12, 0x21, 0x11, 0x23, 0x13, 0x20, 0x10],
                         "the address's low byte picks all 32 KiB")
        self.assertEqual(self.kind_after_power_on(rom), info["mbc_kind"], "the card recognises it too")
        plain = gb.header(rom, model_ctx().store)
        self.assertEqual(plain["mbc"], "none", "without the logo's fingerprint it is a plain ROM")

    def sachen_rom(self):
        """CPU view: NOP; JP 0x150 at 0x100, JP 0x200 at 0x150 (inside the scrambled page), the program at 0x200,
        the logo where a locked board shows it (0x184), none at 0x104; then the page is stored scrambled. Bank 4
        holds a copy of bank 0 (the program switches the 0000-3FFF area to it)."""
        prog = [*keep(0x4000, 0), *st(0x2000, 5), *keep(0x4000, 1), *st(0x2000, 0), *keep(0x4000, 2),
                *st(0x0000, 4), *keep(0x3FF0, 3),                         # base ignored: no 0x30 in the bank
                *st(0x2000, 0x30), *st(0x0000, 4), *st(0x4000, 0x04),     # base 4, mask 0x04
                *st(0x2000, 1), *keep(0x4000, 4), *keep(0x3FF0, 5), *END]
        code = asm.assemble(self.ctx.store, [("LD SP,nn", 0xFFFE), *prog], org=0x200)
        view = bytearray(asm.rom(self.ctx.store, [("JP nn", 0x0200)], title="SACHEN TEST", cgb=0x80,
                                 rom_size_code=2, extra={0x200: code}))
        view[0x184:0x1B4] = STAND_IN
        for b in range(1, 8):
            view[b * 0x4000] = b
        view[0x3FF0] = 0x40
        view[0x10000:0x14000] = view[0:0x4000]
        view[0x10000] = 4
        view[0x13FF0] = 0x44
        chip = bytearray(view)
        for page in (0, 0x10000):
            for a in range(0x100, 0x200):
                chip[page + gb.sachen_lines(a)] = view[page + a]
        return bytes(chip)

    def test_sachen_scrambled_header_base_and_mask(self):
        rom = self.sachen_rom()
        info = gb.header(rom, self.ctx.store)
        self.assertEqual((info["mbc"], info["title"], info["cgb"], info["header_checksum_ok"]),
                         ("sachen", "SACHEN TEST", True, True), "the header as the CPU reads it")
        g = run(gb.GameBoy(self.ctx, rom, "native", sample_rate=0))
        self.assertEqual(g.model, "cgb", "the CGB flag through the board")
        from cardmodel.arcade import system as S
        p = S.Player(self.ctx, "gameboy", rom, "native", fresh=True)
        self.assertEqual((p.m.get("cgb"), p.m.get("mbc_kind")), (1, info["mbc_kind"]),
                         "the arcade player reads the flag through the board too")
        self.assertEqual(list(results(g, 6)), [1, 5, 1, 0x40, 5, 0x44], "banks, 0 -> 1, base and mask")
        self.assertEqual(self.kind_after_power_on(rom), info["mbc_kind"])
        self.assertEqual(lift.scrambled_page(self.ctx, rom), (0x100, 0x200))
        found = lift.discover(self.ctx.store, rom, len(rom) - 1, avoid=(0x100, 0x200))
        dec = lift.Decoder(self.ctx.store, avoid=(0x100, 0x200))
        covered = [pc for k in found["leaders"] if not k & 1
                   for pc, _, _, imm in lift.block_extent(dec, rom, k, len(rom) - 1)
                   if pc + 1 + len(imm) > 0x100 and pc < 0x200]
        self.assertEqual(covered, [], "no lifted instruction in the scrambled page")

    def test_machine_build_sees_card_data(self):
        self.assertNotEqual(Bd.module(self.ctx, "gameboy")["hash"], Bd.module(model_ctx(), "gameboy")["hash"],
                            "a `card.` constant changed, so the cached module must not be reused")


# -- the CGB boot and the survey ------------------------------------------------------------------------------
class BootAndSurvey(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_cgb_boot_leaves_bcps_auto_incrementing_from_0(self):
        prog = [x for v in (0x11, 0x22, 0x33, 0x44) for x in (("LD A,n", v), ("LDH (n),A", 0x69))]
        prog += [("LDH A,(n)", 0x68), ("LD (nn),A", WRAM)]
        g = run(gb.GameBoy(self.ctx, cart(self.ctx, prog, 0x00, rom_size_code=0, cgb=0x80), "native",
                           sample_rate=0))
        self.assertEqual(g.m.read("bgpal", 0, 4), bytes([0x11, 0x22, 0x33, 0x44]))
        self.assertEqual(results(g)[0], 0xC4)

    def test_survey_tries_again_without_input(self):
        """A screen that scrolls from frame 250 unless a button was pressed before: the survey's A at frame 220
        stops it, the run without input sees it move."""
        import tempfile
        from pathlib import Path
        tile = bytes([0xF0, 0x00] * 8)                                 # 8 pixels wide: a scroll shows
        prog = [("LD A,n", 0), ("LDH (n),A", 0x40),
                ("LD HL,nn", 0x8010), ("LD DE,nn", "tile"), ("LD B,n", 16),
                ("label", "copy"), ("LD A,(DE)",), ("LD (HL+),A",), ("INC DE",), ("DEC B",), ("JR NZ,e", "copy"),
                ("LD HL,nn", 0x9800), ("LD BC,nn", 0x0400),
                ("label", "fill"), ("LD A,n", 1), ("LD (HL+),A",), ("DEC BC",), ("LD A,B",), ("OR C",),
                ("JR NZ,e", "fill"),
                ("LD A,n", 0xE4), ("LDH (n),A", 0x47), ("LD A,n", 0x01), ("LDH (n),A", 0xFF),
                ("LD A,n", 0x91), ("LDH (n),A", 0x40), ("XOR A",), ("LDH (n),A", 0x80), ("EI",),
                ("label", "frame"), ("HALT",),
                ("LD A,n", 0x10), ("LDH (n),A", 0x00), ("LDH A,(n)", 0x00), ("AND n", 0x0F), ("CP n", 0x0F),
                ("JR NZ,e", "stop"),
                ("LDH A,(n)", 0x80), ("CP n", 250), ("JR NC,e", "move"), ("INC A",), ("LDH (n),A", 0x80),
                ("JR e", "frame"),
                ("label", "move"), ("LDH A,(n)", 0x43), ("INC A",), ("LDH (n),A", 0x43), ("JR e", "frame"),
                ("label", "stop"), ("HALT",), ("JR e", "stop"),
                ("label", "tile"), ("db", tile)]
        vblank = asm.assemble(self.ctx.store, [("RETI",)], org=0x40)
        rom = asm.rom(self.ctx.store, [("LD SP,nn", 0xFFFE), *prog], title="PAUSES", extra={0x40: vblank})
        d = Path(tempfile.mkdtemp(prefix="cardmodel_survey_"))
        (d / "pauses.gb").write_bytes(rom)
        row = survey.run(self.ctx, d, frames=400)["rows"][0]
        self.assertEqual((row["status"], row["input"]), ("runs", "none"))
        self.assertIn("with the scripted taps: drawn, but no checkpoint frame differs", row["reason"])


if __name__ == "__main__":
    unittest.main()
