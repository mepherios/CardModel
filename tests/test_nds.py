"""The DS machine's video and peripherals as cards: a synthetic image whose ARM9 code draws on both screens, each 2D
engine feature checked pixel by pixel through the bus (the way the CPUs' stores reach it), VRAM bank mapping, the
save chip, the SPI devices, the real-time clock, the sound channels' busy bits, the geometry FIFO, the cartridge's
per-word DMA, and (when the image is on this machine) Pokemon Diamond's first screens. No game is stored here."""
import datetime
import os
import struct
import unittest
from pathlib import Path

from helpers import model_ctx

from cardmodel.machine import nds

DIAMOND = Path(os.environ.get("CARDMODEL_DS_ROM", "~/Downloads/Pokemon Diamond/Pokemon Diamond.nds")).expanduser()
LOOP = 0xEAFFFFFE                                   # B . (a branch to itself)


class Arm:
    """Hand-encoded ARM words for a synthetic image: literal-pool loads and 8/16/32-bit stores, ending in B ."""

    def __init__(self, base: int):
        self.base = base
        self.items = []

    def store(self, addr: int, value: int, width: int = 4):
        self.items += [("ldr", 0, addr), ("ldr", 1, value), ("str", width)]
        return self

    def words(self) -> list:
        n = len(self.items) + 1
        lits: list = []
        out = []
        for i, it in enumerate(self.items):
            if it[0] == "ldr":
                if it[2] not in lits:
                    lits.append(it[2])
                offset = self.base + 4 * (n + lits.index(it[2])) - (self.base + 4 * i + 8)
                out.append(0xE59F0000 | (it[1] << 12) | offset)
            else:                                   # STR / STRH / STRB r1, [r0]
                out.append({4: 0xE5801000, 2: 0xE1C010B0, 1: 0xE5C01000}[it[1]])
        return out + [LOOP] + lits


def image(arm9: list, rom_data: dict | None = None) -> bytes:
    """A DS image: the ARM9 words after the decrypted secure-area marker, the ARM7 idling in B ., data at offsets."""
    img = bytearray(0x10000)
    img[0:6] = b"CMTEST"
    img[12:16] = b"CMTS"
    words9 = [0xE7FFDEFF, 0xE7FFDEFF] + (list(arm9) or [LOOP])
    struct.pack_into("<IIII", img, 0x20, 0x4000, 0x02000008, 0x02000000, len(words9) * 4)
    struct.pack_into("<IIII", img, 0x30, 0x8000, 0x02380000, 0x02380000, 4)
    img[0x4000:0x4000 + len(words9) * 4] = struct.pack(f"<{len(words9)}I", *words9)
    img[0x8000:0x8004] = struct.pack("<I", LOOP)
    for off, data in (rom_data or {}).items():
        img[off:off + len(data)] = data
    return bytes(img)


def rgb(c: int) -> tuple:
    """A 15-bit colour as the screen shows it (5 -> 6 -> 8 bits per channel, as the 2D card widens it)."""
    out = []
    for k in (0, 5, 10):
        v = (c >> k) & 31
        v6 = (v << 1) | (v >> 4)
        out.append((v6 << 2) | (v6 >> 4))
    return tuple(out)


RED, GREEN, BLUE, WHITE, BLACK = 0x001F, 0x03E0, 0x7C00, 0x7FFF, 0x0000
_SHARED: dict = {}


def make_ds(img: bytes, **kw) -> nds.DS:
    """A DS with this image, in the one machine the tests share (a load resets everything a game can reach)."""
    if "ctx" not in _SHARED:
        _SHARED["ctx"] = model_ctx()
    ds = nds.DS(_SHARED["ctx"], img, machine=_SHARED.get("m"), **kw)
    _SHARED["m"] = ds.m
    return ds


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = _SHARED.get("ctx") or model_ctx()
        _SHARED["ctx"] = cls.ctx

    def setUp(self):
        self.ds = make_ds(image([]))

    def w(self, addr, value, width=4, cpu=0):
        self.ds.m.call("bus_write", cpu, addr, value, width)

    def r(self, addr, width=4, cpu=0):
        return self.ds.m.call("bus_read", cpu, addr, width)

    def px(self, screen: int, x: int, y: int) -> tuple:
        s = self.ds.screens()
        o = screen * nds.SCREEN_BYTES + (y * 256 + x) * 3
        return tuple(s[o:o + 3])

    def draw(self, *lines):
        for y in lines:
            self.ds.m.call("render_line", y)

    def tiles(self, addr, rows):
        for i, word in enumerate(rows):
            self.w(addr + 4 * i, word)


class Screens(Base):
    def test_arm9_code_draws_both_screens(self):
        """The ARM9's own stores map VRAM banks, fill palettes, tiles, OAM and the display registers; after a frame
        the top screen (engine A, POWCNT1 bit 15) shows its background and a sprite, the bottom engine B's."""
        a = Arm(0x02000008)
        a.store(0x04000304, 0x820F, 2)
        a.store(0x04000240, 0x8281, 2)                     # bank A: engine A BG, bank B: engine A OBJ
        a.store(0x04000242, 0x0084, 2)                     # bank C: engine B BG
        a.store(0x05000000, (RED << 16) | BLUE)            # engine A: backdrop blue, colour 1 red
        a.store(0x05000200, GREEN << 16)                   # engine A OBJ colour 1 green
        a.store(0x05000400, (WHITE << 16) | BLACK)         # engine B: backdrop black, colour 1 white
        for i in range(8):
            a.store(0x06000000 + 4 * i, 0x00001111)        # BG tile 0: left half colour 1
            a.store(0x06200000 + 4 * i, 0x01010101)        # engine B tile 0: every other pixel colour 1
            a.store(0x06400020 + 4 * i, 0x11111111)        # OBJ tile 1: solid colour 1
        a.store(0x07000000, (24 << 16) | 16)               # OBJ 0 at (24, 16), 8x8
        a.store(0x07000004, 1, 2)                          # tile 1
        a.store(0x04000008, 0x0100, 2)                     # BG0: map at 2 KiB (all entries tile 0)
        a.store(0x04001008, 0x0100, 2)
        a.store(0x04000000, 0x00011110)                    # graphics, 1D OBJ, BG0 and OBJ on
        a.store(0x04001000, 0x00010100)
        ds = make_ds(image(a.words()))
        ds.run(2, watch=True)
        self.ds = ds
        self.assertEqual(self.px(0, 0, 50), rgb(RED))
        self.assertEqual(self.px(0, 5, 50), rgb(BLUE))
        self.assertEqual(self.px(0, 24, 16), rgb(GREEN))
        self.assertEqual(self.px(0, 31, 23), rgb(GREEN))
        self.assertEqual(self.px(0, 32, 16), rgb(RED))
        self.assertEqual(self.px(1, 0, 100), rgb(WHITE))
        self.assertEqual(self.px(1, 1, 100), rgb(BLACK))
        self.assertEqual(ds.first_drawn, {"top": 1, "bottom": 1}, "both screens show a picture after frame 1")
        st = nds.screen_stats(ds.screens())
        self.assertFalse(st["top"]["blank"] or st["bottom"]["blank"])
        cov = nds.coverage(ds)
        self.assertEqual(cov["cpus"]["arm9"]["undecodable_executed"], 0)
        self.assertNotIn("2D engine B", cov["cpus"]["arm9"]["unmodelled_hardware_touched"])

    def test_input_script_names_come_from_the_card(self):
        self.assertEqual(nds.parse_input("10:start,16:-,20:a+r", self.ctx.store), {10: 0x008, 16: 0, 20: 0x101})
        with self.assertRaises(ValueError):
            nds.parse_input("5:jump", self.ctx.store)
        self.ds.set_buttons(0x401)                         # A and X
        self.assertEqual(self.r(0x04000130, 2) & 0x3FF, 0x3FE)
        self.assertEqual(self.r(0x04000136, 1, cpu=1) & 3, 2)

    def test_screen_swap_and_master_brightness(self):
        self.w(0x05000400, WHITE, 2)
        self.w(0x04000000, 0x00010000)                     # engine A: graphics, nothing on: its black backdrop
        self.w(0x04001000, 0x00010000)                     # engine B likewise: white
        self.w(0x04000304, 0x820F, 2)
        self.draw(0)
        self.assertEqual((self.px(0, 0, 0), self.px(1, 0, 0)), (rgb(BLACK), rgb(WHITE)))
        self.w(0x04000304, 0x020F, 2)                      # engine A to the bottom, B to the top
        self.draw(0)
        self.assertEqual((self.px(0, 0, 0), self.px(1, 0, 0)), (rgb(WHITE), rgb(BLACK)))
        self.w(0x0400106C, 0x8008, 2)                      # master brightness down by 8/16
        self.draw(0)
        self.assertEqual(self.px(0, 0, 0), (130, 130, 130))
        self.w(0x05000400, BLACK, 2)
        self.w(0x0400106C, 0x4008, 2)                      # up by 8/16
        self.draw(0)
        self.assertEqual(self.px(0, 0, 0), (125, 125, 125))
        self.w(0x04001000, 0x00010080)                     # forced blank: white
        self.draw(0)
        self.assertEqual(self.px(0, 0, 0), (255, 255, 255))


class Engines(Base):
    def setUp(self):
        super().setUp()
        self.w(0x04000304, 0x820F, 2)                      # engine A on the top screen
        self.w(0x04000240, 0x8281, 2)                      # A: engine A BG, B: engine A OBJ
        self.w(0x05000000, RED << 16)                      # backdrop black, colour 1 red, 2 green
        self.w(0x05000004, GREEN, 2)

    def test_text_background_8bpp_scroll_and_flip(self):
        self.tiles(0x06000040, [0x02020201, 0x02020202] * 8)   # 8bpp tile 1: pixel 0 red, the rest green
        self.w(0x06000800, 0x00010401)                     # map (0,0): tile 1 flipped; (1,0): tile 1
        self.w(0x04000008, 0x0180, 2)                      # 256 colours, map at 2 KiB
        self.w(0x04000010, 4, 2)                           # HOFS 4
        self.w(0x04000000, 0x00010100)
        self.draw(0)
        row = [self.px(0, x, 0) for x in range(13)]
        self.assertEqual(row[:3], [rgb(GREEN)] * 3)
        self.assertEqual(row[3:5], [rgb(RED)] * 2, "flipped pixel 0 at the tile's right edge, then the next tile")
        self.assertEqual(row[5:12], [rgb(GREEN)] * 7)
        self.assertEqual(row[12], rgb(BLACK), "tile 0 is transparent: the backdrop")

    def test_obj_and_background_priorities(self):
        self.tiles(0x06000000, [0x11111111] * 8)           # BG tile 0 solid red
        self.tiles(0x06400020, [0x22222222] * 8)           # OBJ tile 1 solid colour 2
        self.w(0x05000204, GREEN, 2)
        self.w(0x04000008, 0x0101, 2)                      # BG0 priority 1, map at 2 KiB
        self.w(0x07000000, (8 << 16) | 0)                  # OBJ 0 at x 8, priority 2: behind BG0
        self.w(0x07000004, 0x0801, 2)
        self.w(0x07000008, (16 << 16) | 0)                 # OBJ 1 at x 16, priority 0: in front
        self.w(0x0700000C, 0x0001, 2)
        self.w(0x04000000, 0x00011110)
        self.draw(0)
        self.assertEqual(self.px(0, 8, 0), rgb(RED))
        self.assertEqual(self.px(0, 16, 0), rgb(GREEN))
        self.assertEqual(self.px(0, 24, 0), rgb(RED))

    def _two_layers(self):
        self.tiles(0x06000000, [0x11111111] * 8)           # tile 0 colour 1 (red), tile 1 colour 2 (green)
        self.tiles(0x06000020, [0x22222222] * 8)
        for i in range(0, 0x800, 4):
            self.w(0x06001000 + i, 0x00010001)             # BG1's map (at 4 KiB): tile 1 everywhere
        self.w(0x04000008, 0x0100, 2)                      # BG0 priority 0, map at 2 KiB
        self.w(0x0400000A, 0x0201, 2)                      # BG1 priority 1, map at 4 KiB

    def test_alpha_blending_and_brightness(self):
        self._two_layers()
        self.w(0x04000000, 0x00010300)
        self.w(0x04000050, 0x0241, 2)                      # BG0 over BG1, alpha
        self.w(0x04000052, 0x0808, 2)                      # EVA 8, EVB 8
        self.draw(0)
        self.assertEqual(self.px(0, 0, 0), rgb(15 | (15 << 5)))
        self.w(0x04000050, 0x0081, 2)                      # brighten BG0
        self.w(0x04000054, 8, 2)
        self.draw(0)
        self.assertEqual(self.px(0, 0, 0), rgb(31 | (15 << 5) | (15 << 10)))
        self.w(0x04000050, 0x00C1, 2)                      # darken BG0
        self.draw(0)
        self.assertEqual(self.px(0, 0, 0), rgb(16))

    def test_window_hides_a_layer(self):
        self._two_layers()
        self.w(0x04000040, 0x0810, 2)                      # WIN0 x 8..15
        self.w(0x04000044, 0x00C0, 2)                      # y 0..191
        self.w(0x04000048, 0x0002, 2)                      # inside: BG1 only
        self.w(0x0400004A, 0x0003, 2)                      # outside: BG0 and BG1
        self.w(0x04000000, 0x00012300)
        self.draw(5)
        self.assertEqual(self.px(0, 7, 5), rgb(RED))
        self.assertEqual(self.px(0, 8, 5), rgb(GREEN))
        self.assertEqual(self.px(0, 15, 5), rgb(GREEN))
        self.assertEqual(self.px(0, 16, 5), rgb(RED))

    def test_affine_background_steps_and_wraps(self):
        self.tiles(0x06000040, [0x01010101] * 16)          # 8bpp tile 1 solid colour 1
        self.w(0x06000800, 0x0100, 2)                      # 8-bit map (16x16 tiles): (1, 0) = tile 1
        self.w(0x0400000C, 0x0100, 2)                      # BG2: 128x128, map at 2 KiB
        self.w(0x04000020, 0x0100, 2)                      # PA = 1
        self.w(0x04000026, 0x0100, 2)                      # PD = 1
        self.w(0x04000000, 0x00010402)                     # mode 2, BG2 on
        self.draw(0, 1)
        self.assertEqual([self.px(0, x, 1) for x in (7, 8, 15, 16)],
                         [rgb(BLACK), rgb(RED), rgb(RED), rgb(BLACK)])
        self.w(0x04000020, 0x0080, 2)                      # PA = 1/2: twice as wide
        self.draw(0)
        self.assertEqual([self.px(0, x, 0) for x in (15, 16, 31, 32)],
                         [rgb(BLACK), rgb(RED), rgb(RED), rgb(BLACK)])
        self.w(0x04000020, 0x0100, 2)
        self.w(0x04000026, 0x0800, 2)                      # PD = 8: line 1 reads texture row 8 (tile row 1)
        self.draw(0, 1)
        self.assertEqual(self.px(0, 8, 0), rgb(RED))
        self.assertEqual(self.px(0, 8, 1), rgb(BLACK))
        self.w(0x04000028, 120 << 8)                       # X = 120: past the 128-pixel edge at x = 8
        self.draw(0)
        self.assertEqual(self.px(0, 16, 0), rgb(BLACK), "outside the texture without wraparound")
        self.w(0x0400000C, 0x2100, 2)                      # wraparound
        self.draw(0)
        self.assertEqual(self.px(0, 16, 0), rgb(RED))

    def test_direct_colour_bitmap(self):
        self.w(0x06000006, 0x8000 | BLUE, 2)               # pixel (3, 0): blue, alpha bit set
        self.w(0x06000008, BLUE, 2)                        # pixel (4, 0): no alpha bit: transparent
        self.w(0x0400000E, 0x4084, 2)                      # BG3: direct-colour bitmap 256x256
        self.w(0x04000030, 0x0100, 2)
        self.w(0x04000036, 0x0100, 2)
        self.w(0x04000000, 0x00010805)                     # mode 5, BG3 on
        self.draw(0)
        self.assertEqual(self.px(0, 3, 0), rgb(BLUE))
        self.assertEqual(self.px(0, 4, 0), rgb(BLACK))

    def test_extended_palettes(self):
        self.tiles(0x06000040, [0x05050505] * 16)          # 8bpp tile 1: colour 5
        self.w(0x06000800, 0x3001, 2)                      # map (0, 0): tile 1, palette 3
        self.w(0x04000244, 0x80, 1)                        # bank E to the LCDC window
        self.w(0x06880000 + 3 * 512 + 5 * 2, BLUE, 2)      # slot 0, palette 3, colour 5
        self.w(0x04000244, 0x84, 1)                        # bank E: engine A BG extended palettes
        self.w(0x04000008, 0x0180, 2)
        self.w(0x04000000, 0x40010100)                     # BG extended palettes on
        self.draw(0)
        self.assertEqual(self.px(0, 0, 0), rgb(BLUE))
        self.w(0x04000000, 0x00010100)                     # off: the standard palette's colour 5 (black)
        self.draw(0)
        self.assertEqual(self.px(0, 0, 0), rgb(BLACK))


def fx(v: float) -> int:
    """A 4.12 fixed-point number as the 16-bit field the vertex commands take."""
    return int(round(v * 4096)) & 0xFFFF


class Geometry3D(Base):
    """The 3D engine through its command ports, as a game's stores reach it: identity matrices make the vertices
    clip coordinates, so a vertex (x, y) lands at screen ((x + 1) * 128, (1 - y) * 96)."""

    PORT = {"mode": 0x10, "push": 0x11, "pop": 0x12, "identity": 0x15, "trans": 0x1C, "color": 0x20,
            "texcoord": 0x22, "vtx16": 0x23, "attr": 0x29, "teximage": 0x2A, "begin": 0x40, "end": 0x41,
            "swap": 0x50, "viewport": 0x60, "box": 0x70}

    def gx(self, name, *params):
        port = 0x04000440 + (self.PORT[name] - 0x10) * 4
        for v in params or (0,):
            self.w(port, v & 0xFFFFFFFF)

    def setUp(self):
        super().setUp()
        for mode in (0, 1, 3):
            self.gx("mode", mode)
            self.gx("identity")
        self.gx("mode", 2)
        self.gx("viewport", 0xBFFF0000)
        self.w(0x04000060, 0x0001, 2)                      # DISP3DCNT: texture mapping
        self.w(0x04000350, 0)                              # rear plane: transparent
        self.w(0x04000354, 0x7FFF, 2)

    def tri(self, pts, color, attr=0x001F00C0, z=0.0):
        self.gx("attr", attr)
        self.gx("begin", 0)
        self.gx("color", color)
        for x, y in pts:
            self.gx("vtx16", fx(x) | (fx(y) << 16), fx(z))
        self.gx("end")

    def frame(self, swap=0):
        self.gx("swap", swap)
        self.ds.run(1)

    def pix(self, x, y):
        p = self.ds.m.array("fb3d")[y * 256 + x]
        c = ((p & 63) >> 1) | (((p >> 6) & 63) >> 1) << 5 | (((p >> 12) & 63) >> 1) << 10
        return (p >> 18) & 31, c

    FRONT = [(-0.5, -0.5), (0.5, -0.5), (0.0, 0.5)]        # counter-clockwise on the screen: a front face

    def test_triangle_lands_where_the_viewport_puts_it(self):
        self.tri(self.FRONT, RED)
        self.frame()
        self.assertEqual(self.pix(128, 112), (31, RED))
        self.assertEqual(self.pix(128, 40)[0], 0, "above the apex (screen y 48): nothing")
        self.assertEqual(self.pix(60, 140)[0], 0, "left of the base corner (64, 144)")
        self.assertEqual(self.ds.m.get("frames3d"), 1)

    def test_back_faces_follow_polygon_attr(self):
        back = list(reversed(self.FRONT))
        self.tri(back, RED, attr=0x001F0080)               # front only: a clockwise polygon is its back
        self.frame()
        self.assertEqual(self.pix(128, 112)[0], 0)
        self.tri(back, GREEN, attr=0x001F0040)             # back only
        self.frame()
        self.assertEqual(self.pix(128, 112), (31, GREEN))

    def test_depth_test_keeps_the_nearer_polygon(self):
        self.tri(self.FRONT, RED, z=-0.5)
        self.tri(self.FRONT, GREEN, z=0.5)                    # farther, drawn later: hidden
        self.tri([(-0.25, -0.25), (0.25, -0.25), (0.0, 0.25)], BLUE, z=-0.75)
        self.frame()
        self.assertEqual(self.pix(128, 112), (31, BLUE))
        self.assertEqual(self.pix(128, 135), (31, RED))

    def test_translation_and_the_matrix_stack(self):
        self.gx("push")
        self.gx("trans", 0x800, 0, 0)                      # +0.5 in x: 64 pixels to the right
        self.tri(self.FRONT, RED)
        self.gx("pop", 1)
        self.tri([(-0.9, -0.9), (-0.7, -0.9), (-0.8, -0.7)], GREEN)
        self.frame()
        self.assertEqual(self.pix(192, 112), (31, RED))
        self.assertEqual(self.pix(100, 112)[0], 0, "the translated triangle left x 100 empty")
        self.assertEqual(self.pix(25, 178), (31, GREEN), "the pop restored the identity")

    def test_direct_colour_texture(self):
        self.w(0x04000240, 0x80, 1)                        # bank A to LCDC, write an 8x8 texture, then texture slot 0
        for y in range(8):
            for x in range(8):
                self.w(0x06800000 + (y * 8 + x) * 2, 0x8000 | (BLUE if x < 4 else GREEN), 2)
        self.w(0x04000240, 0x83, 1)
        self.gx("teximage", (7 << 26) | 0)                 # direct colour, 8x8, at offset 0
        self.gx("attr", 0x001F00C0)
        self.gx("begin", 1)                                # a quad over the whole screen
        self.gx("color", WHITE)
        for (x, y), (s, t) in (((-1, 1), (0, 0)), ((1, 1), (8, 0)), ((1, -1), (8, 8)), ((-1, -1), (0, 8))):
            self.gx("texcoord", ((s * 16) & 0xFFFF) | ((t * 16) << 16))
            self.gx("vtx16", fx(x * 0.999) | (fx(y * 0.999) << 16), 0)
        self.gx("end")
        self.frame()
        self.assertEqual(self.pix(20, 96), (31, BLUE))
        self.assertEqual(self.pix(230, 96), (31, GREEN))

    def test_packed_fifo_commands(self):
        """GXFIFO words carry the command bytes, then the parameters: COLOR, BEGIN_VTXS and POLYGON_ATTR packed."""
        fifo = 0x04000400
        self.w(fifo, 0x00402920)                           # COLOR, POLYGON_ATTR, BEGIN_VTXS
        self.w(fifo, RED)
        self.w(fifo, 0x001F00C0)
        self.w(fifo, 0)                                    # triangles
        self.w(fifo, 0x00232323)                           # three VTX_16
        for x, y in self.FRONT:
            self.w(fifo, fx(x) | (fx(y) << 16))
            self.w(fifo, 0)
        self.w(fifo, 0x00000041)                           # END_VTXS
        self.frame()
        self.assertEqual(self.pix(128, 112), (31, RED))

    def test_box_test(self):
        self.gx("box", fx(-0.1) | (fx(-0.1) << 16), fx(-0.1) | (fx(0.2) << 16), fx(0.2) | (fx(0.2) << 16))
        self.assertEqual((self.r(0x04000600) >> 1) & 1, 1, "inside the view volume")
        self.gx("box", fx(2.0) | (fx(2.0) << 16), fx(0.0) | (fx(0.5) << 16), fx(0.5) | (fx(0.5) << 16))
        self.assertEqual((self.r(0x04000600) >> 1) & 1, 0, "entirely right of it")

    def test_3d_layer_is_bg0(self):
        self.tri(self.FRONT, RED)
        self.frame()
        self.w(0x04000304, 0x820F, 2)
        self.w(0x04000000, 0x00010108)                     # engine A: BG0 on, as 3D
        self.draw(112)
        self.assertEqual(self.px(0, 128, 112), rgb(RED))
        self.assertEqual(self.px(0, 10, 112), rgb(BLACK), "transparent 3D pixels show the backdrop")
        self.w(0x04000010, 64, 2)                          # BG0HOFS scrolls the 3D layer
        self.draw(112)
        self.assertEqual(self.px(0, 64, 112), rgb(RED))


class Vram(Base):
    def test_a_bank_moves_between_windows(self):
        self.w(0x04000240, 0x80, 1)                        # bank A: LCDC
        self.w(0x06800000, 0x12345678)
        self.assertEqual(self.r(0x06800000), 0x12345678)
        self.assertEqual(self.r(0x06000000), 0, "nothing mapped at engine A BG")
        self.w(0x04000240, 0x81, 1)
        self.assertEqual(self.r(0x06000000), 0x12345678)
        self.assertEqual(self.r(0x06800000), 0)
        self.w(0x04000240, 0x89, 1)                        # offset 1: the second 128 KiB
        self.assertEqual(self.r(0x06020000), 0x12345678)
        self.assertEqual(self.r(0x06000000), 0)

    def test_arm7_sees_bank_c(self):
        self.w(0x04000242, 0x80, 1)
        self.w(0x06840010, 0xCAFE, 2)
        self.assertEqual(self.r(0x04000240, 1, cpu=1) & 1, 0)
        self.w(0x04000242, 0x82, 1)                        # bank C to the ARM7 at 0x06000000
        self.assertEqual(self.r(0x04000240, 1, cpu=1) & 1, 1, "VRAMSTAT shows it")
        self.assertEqual(self.r(0x06000010, 2, cpu=1), 0xCAFE)

    def test_palette_takes_halfwords_not_bytes(self):
        self.w(0x05000010, 0x1234, 2)
        self.w(0x05000010, 0xFF, 1)
        self.assertEqual(self.r(0x05000010, 2), 0x1234)
        self.assertGreater(self.ds.m.get("dropped_byte_writes"), 0)


class SaveChip(Base):
    def aux(self, v, hold):
        self.w(0x040001A0, 0xA040 if hold else 0xA000, 2, cpu=1)
        self.w(0x040001A2, v, 1, cpu=1)
        return self.r(0x040001A2, 1, cpu=1)

    def command(self, *data, read=0):
        seq = list(data) + [0] * read
        out = [self.aux(v, i < len(seq) - 1) for i, v in enumerate(seq)]
        return out[len(data):]

    def test_flash_identifies_and_reports_status(self):
        chip = nds.backup_chip({"game_code": "ADAE"}, self.ctx.store)
        self.assertEqual((chip["kind"], chip["bytes"]), ("flash", 512 * 1024))
        self.assertEqual(self.command(0x9F, read=3), [0x20, 0x40, 0x13])
        self.assertEqual(self.command(0x05, read=1), [0])
        self.command(0x06)
        self.assertEqual(self.command(0x05, read=1), [2], "write enabled")

    def test_page_write_read_and_erase(self):
        self.assertEqual(self.command(0x03, 0x00, 0x01, 0x00, read=2), [0xFF, 0xFF], "erased flash")
        self.command(0x0A, 0x00, 0x01, 0x00, 0x11, 0x22)   # without WREN: ignored
        self.assertEqual(self.command(0x03, 0x00, 0x01, 0x00, read=2), [0xFF, 0xFF])
        self.command(0x06)
        self.command(0x0A, 0x00, 0x01, 0x00, 0x11, 0x22)
        self.assertEqual(self.command(0x03, 0x00, 0x01, 0x00, read=2), [0x11, 0x22])
        self.assertEqual(self.ds.save_bytes()[0x100:0x102], b"\x11\x22")
        self.assertEqual(self.ds.m.get("backup_dirty"), 1)
        self.assertEqual(self.command(0x05, read=1), [0], "the write cleared write enable")
        self.command(0x06)
        self.command(0xDB, 0x00, 0x01, 0x00)               # page erase
        self.assertEqual(self.command(0x0B, 0x00, 0x01, 0x00, 0x00, read=2), [0xFF, 0xFF])

    def test_a_save_is_loaded(self):
        ds = make_ds(image([]), save=b"\x5A" * 16)
        self.ds = ds
        self.assertEqual(self.command(0x03, 0x00, 0x00, 0x0F, read=2), [0x5A, 0xFF])


class Spi(Base):
    def spi(self, dev, v, hold):
        self.w(0x040001C0, 0x8000 | (dev << 8) | (0x800 if hold else 0), 2, cpu=1)
        self.w(0x040001C2, v, 1, cpu=1)
        return self.r(0x040001C2, 1, cpu=1)

    def command(self, dev, *data, read=0):
        seq = list(data) + [0] * read
        out = [self.spi(dev, v, i < len(seq) - 1) for i, v in enumerate(seq)]
        return out[len(data):]

    def test_firmware_user_settings(self):
        self.assertEqual(self.command(1, 0x9F, read=3), [0x20, 0x40, 0x12])
        head = bytes(self.command(1, 0x03, 0x00, 0x00, 0x20, read=2))
        offset = int.from_bytes(head, "little") * 8
        us = bytes(self.command(1, 0x03, offset >> 16, (offset >> 8) & 0xFF, offset & 0xFF, read=0x74))
        self.assertEqual(us[6:14].decode("utf-16-le"), "CARD")
        self.assertEqual(int.from_bytes(us[0x72:0x74], "little"), nds.crc16(us[:0x70]))
        self.assertEqual(us[:0x70], self.ds.m.read("mram", 0x3FFC80, 0x70), "the copy the firmware leaves in RAM")

    def test_touch_screen_reports_the_pen(self):
        self.assertEqual(self.r(0x04000136, 1, cpu=1) & 0x40, 0x40, "pen up")
        self.ds.touch(128, 96)
        self.assertEqual(self.r(0x04000136, 1, cpu=1) & 0x40, 0, "pen down")
        cal = self.ctx.store.get("hardware/nds_spi")["touch_calibration"]
        for cmd, axis, pos in ((0xD0, "x", 128), (0x90, "y", 96)):
            hi, lo = self.command(2, cmd, read=2)
            adc = ((hi << 8) | lo) >> 3
            back = (adc - cal[f"adc_{axis}1"]) * (cal[f"scr_{axis}2"] - cal[f"scr_{axis}1"]) / \
                (cal[f"adc_{axis}2"] - cal[f"adc_{axis}1"]) + cal[f"scr_{axis}1"] - 1
            self.assertLessEqual(abs(back - pos), 1, (axis, adc, back))

    def test_power_management_registers(self):
        self.assertEqual(self.command(0, 0x80, read=1), [0x0D], "backlights and sound amplifier on")
        self.command(0, 0x00, 0x0C)
        self.assertEqual(self.command(0, 0x80, read=1), [0x0C])


class Clock(Base):
    def rtc(self, v):
        self.w(0x04000138, v, 2, cpu=1)

    def transfer(self, command, n):
        self.rtc(0x70)
        self.rtc(0x74)                                     # chip select up: a new transfer
        for i in range(8):
            bit = (command >> i) & 1
            self.rtc(0x74 | bit)
            self.rtc(0x76 | bit)
        out = []
        for _ in range(n):
            b = 0
            for i in range(8):
                self.rtc(0x64)
                b |= (self.r(0x04000138, 1, cpu=1) & 1) << i
                self.rtc(0x66)
            out.append(b)
        self.rtc(0x70)
        return out

    def test_date_and_time_in_bcd(self):
        self.ds.set_clock(datetime.datetime(2026, 10, 22, 13, 45, 30))
        self.assertEqual(self.transfer(0x65, 7), [0x26, 0x10, 0x22, 0x04, 0x53, 0x45, 0x30])
        self.assertEqual(self.transfer(0xA6, 3), [0x26, 0x10, 0x22], "the command sent the other way round")
        self.assertEqual(self.transfer(0x67, 3), [0x53, 0x45, 0x30], "time only")
        self.assertEqual(self.transfer(0x61, 1), [0x02], "status 1: 24-hour mode, no power-on or battery flags")

    def test_the_clock_runs_on_machine_time(self):
        self.ds.set_clock(datetime.datetime(2026, 12, 31, 23, 59, 59))
        self.ds.run(60)                                    # 60 frames: just over a second
        self.assertEqual(self.transfer(0x65, 7), [0x27, 0x01, 0x01, 0x05, 0x00, 0x00, 0x00])


class Sound(Base):
    """The channels through their registers, as the ARM7 sets them; the mixer's samples drained from `audio`."""

    def channel(self, ch, cnt, sad=0x02200000, tmr=0x10000 - 511, pnt=0, length=4):
        base = 0x04000400 + ch * 16
        self.w(base + 4, sad, cpu=1)
        self.w(base + 8, tmr, 2, cpu=1)
        self.w(base + 10, pnt, 2, cpu=1)
        self.w(base + 12, length, cpu=1)
        self.w(0x04000500, 0x807F, 2, cpu=1)               # SOUNDCNT: enabled, master volume 127
        self.ds.drain_audio()
        self.w(base, cnt, cpu=1)

    def samples(self, frames=1):
        pcm = bytearray()
        self.ds.run(frames, pcm=pcm)
        vals = struct.unpack(f"<{len(pcm) // 2}h", bytes(pcm))
        return vals[0::2], vals[1::2]

    def test_pcm8_is_mixed_with_volume_and_panning(self):
        self.ds.m.write("mram", bytes([0x40, 0xC0] * 8), start=0x200000)   # +64, -64, ...
        self.channel(0, 0x80000000 | (1 << 27) | (64 << 16) | 127)       # loop, PCM8, centre, volume 127
        left, right = self.samples()
        self.assertEqual(max(left), (((64 << 8) * 127 >> 7) * 63 >> 7) * 127 >> 9)
        self.assertEqual(min(left), (((-64 << 8) * 127 >> 7) * 63 >> 7) * 127 >> 9)
        self.assertEqual(max(right), (((64 << 8) * 127 >> 7) * 64 >> 7) * 127 >> 9)
        self.w(0x04000500, 0x007F, 2, cpu=1)               # master enable off: silence
        left, right = self.samples()
        self.assertEqual(set(left) | set(right), {0})

    def test_psg_duty_and_noise(self):
        self.channel(8, 0x80000000 | (3 << 29) | (3 << 24) | (64 << 16) | 127, tmr=0x10000 - 4096)
        left, _ = self.samples(2)                          # a step every 8 output samples: the wave is resolved
        high = sum(1 for v in left if v > 0)
        self.assertAlmostEqual(high / len(left), 0.5, delta=0.05, msg="duty 3: high 4 of 8 steps")
        self.w(0x04000480, 0, cpu=1)
        self.channel(14, 0x80000000 | (3 << 29) | (64 << 16) | 127, tmr=0x10000 - 4096)
        left, _ = self.samples()
        self.assertTrue(any(v > 0 for v in left) and any(v < 0 for v in left))

    def test_adpcm_decodes_nibbles_after_its_header(self):
        """A header word (sample 0x0100, index 3), then 24 nibbles alternating 7 and 0xF: the one-shot ends with the
        decoder where the card's step and index tables put it, and its busy bit clears."""
        self.ds.m.write("mram", bytes([0x00, 0x01, 3, 0]) + bytes([0xF7] * 12), start=0x200000)
        self.channel(0, 0x80000000 | (2 << 29) | (2 << 27) | (64 << 16) | 127, pnt=1, length=3, tmr=0x10000 - 255)
        adpcm = self.ctx.store.get("hardware/nds_sound")["adpcm"]
        v, i = 0x100, 3
        for n in [0x7, 0xF] * 12:
            st = adpcm["step_table"][i]
            d = (st >> 3) + (st >> 2) + (st >> 1) + st
            v = max(-0x7FFF, v - d) if n & 8 else min(0x7FFF, v + d)
            i = max(0, min(88, i + adpcm["index_table"][n & 7]))
        self.ds.run(1)
        self.assertEqual((self.ds.m.array("ch_adv")[0], self.ds.m.array("ch_adi")[0]), (v, i))
        self.assertEqual(self.r(0x04000403, 1, cpu=1) & 0x80, 0)

    def test_one_shot_channel_stops_and_a_loop_keeps_playing(self):
        self.w(0x04000408, 0xFE00, 2, cpu=1)               # 512 ticks per sample
        self.w(0x0400040C, 16, cpu=1)                      # 16 words = 64 PCM8 samples
        self.w(0x04000400, 0x90000000, cpu=1)              # start, one-shot, PCM8
        self.assertEqual(self.r(0x04000403, 1, cpu=1) & 0x80, 0x80)
        self.ds.run(1)
        self.assertEqual(self.r(0x04000403, 1, cpu=1) & 0x80, 0, "64 samples played out within a frame")
        self.w(0x04000400, 0x88000000, cpu=1)              # start, looping
        self.ds.run(1)
        self.assertEqual(self.r(0x04000403, 1, cpu=1) & 0x80, 0x80)


class Geometry(Base):
    def test_fifo_is_always_empty_and_fifo_dma_finishes(self):
        st = self.r(0x04000600)
        self.assertEqual(st & 0x0E000000, 0x06000000, "empty, less than half full, not busy")
        self.w(0x04000600, 0x80000000)                     # interrupt when empty
        self.assertEqual(self.r(0x04000600) >> 30, 2)
        self.w(0x040000B0, 0x02100000)
        self.w(0x040000B4, 0x04000400)
        self.w(0x040000B8, 0xBC000000 | 4)                 # geometry-FIFO mode, words, source increments
        self.assertEqual(self.r(0x040000B8) & 0x80000000, 0, "the transfer finished at once")


class Cartridge(Base):
    def test_one_word_repeating_dma_moves_a_whole_block(self):
        """NitroSDK reads the card with a 1-word DMA in cartridge mode that the bus starts again for every ready
        word (Pokemon Diamond's menu needs it)."""
        block = bytes((i * 7) & 0xFF for i in range(0x200))
        self.ds = make_ds(image([], {0x9000: block}))
        self.w(0x040000B0, 0x04100010)
        self.w(0x040000B4, 0x02100000)
        self.w(0x040000B8, 0xAF000001)                     # card mode, repeat, words, fixed source, 1 word
        self.w(0x040001A0, 0x8000, 2)
        self.w(0x040001A8, 0x900000B7)                     # B7, address 0x00009000 (most significant first)
        self.w(0x040001AC, 0)
        self.w(0x040001A4, 0x81000000)                     # start, 0x200 bytes
        self.assertEqual(self.ds.m.read("mram", 0x100000, 0x200), block)
        self.assertEqual(self.r(0x040001A4) & 0x80000000, 0, "transfer done")


@unittest.skipUnless(DIAMOND.is_file(), f"Pokemon Diamond is not at {DIAMOND} (set CARDMODEL_DS_ROM)")
class PokemonDiamond(unittest.TestCase):
    def test_first_screens(self):
        """Read where it is: the copyright and ESRB screens appear within the first two seconds, with text on both
        screens, every BIOS call modelled and no undefined instruction run."""
        ds = make_ds(nds.open_nds(DIAMOND))
        ds.run(120, watch=True)
        self.assertEqual(set(ds.first_drawn), {"top", "bottom"}, ds.first_drawn)
        self.assertLess(max(ds.first_drawn.values()), 120)
        st = nds.screen_stats(ds.screens())
        self.assertGreaterEqual(st["top"]["colours"], 4, st)
        self.assertGreaterEqual(st["bottom"]["colours"], 4, st)
        cov = nds.coverage(ds)
        for cpu in cov["cpus"].values():
            self.assertEqual(cpu["undecodable_executed"], 0)
            self.assertEqual(cpu["swi_unmodelled"], [])
            self.assertFalse(cpu["stopped"])

    def test_title_screen_dialga_in_3d(self):
        """START skips the intro to the title screen, whose Dialga is a 3D model: hundreds of polygons reach the
        rendering engine and cover a large part of its picture; the intro's music comes out of the mixer."""
        ds = make_ds(nds.open_nds(DIAMOND))
        pcm = bytearray()
        ds.run(1800, script=nds.parse_input("1500:start,1506:-", ds.ctx.store), pcm=pcm)
        left = struct.unpack(f"<{len(pcm) // 2}h", bytes(pcm))[0::2]
        self.assertGreater(len(left), 32768 * 25, "about 30 s of sound")
        self.assertGreater(max(left), 4000)
        self.assertGreater(len(set(left[-32768:])), 500, "the last second is not a constant or a few levels")
        m = ds.m
        self.assertGreater(m.get("frames3d"), 100)
        self.assertGreater(m.array("gx_polys")[4], 300)
        fb = m.array("fb3d")
        drawn = sum(1 for i in range(0, 49152, 4) if (fb[i] >> 18) & 31)
        self.assertGreater(drawn, 2500, "Dialga covers about a fifth of the 3D picture")


if __name__ == "__main__":
    unittest.main()
