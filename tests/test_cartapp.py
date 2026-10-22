"""One cartridge as its own app (cardmodel/arcade/cartapp.py): the Game Boy Player with the cartridge's code lifted
into card IR. On a synthetic cartridge that, like every real one, copies a routine into HRAM and calls it every
frame: the lifted player shows the same pictures and plays the same sound as the plain one, every instruction it
runs (the HRAM routine, HALT, EI included) runs as lifted card IR, the app plays the cartridge from where it is
without being told the path, and what the interpreter ran while it played is kept beside the save. No ROM is
stored or needed: the cartridge is built by the card assembler."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import model_ctx

from cardmodel.arcade import build as B
from cardmodel.arcade import cartapp as C
from cardmodel.arcade import system as S
from cardmodel.engines import probes
from cardmodel.machine import asm, gb as G

ROUTINE = bytes([0x3E, 0x28, 0x3D, 0x20, 0xFD, 0xC9])    # LD A,40; .w: DEC A; JR NZ,.w; RET (an OAM-DMA-like wait)


def hram_cart(ctx) -> bytes:
    """A checkerboard and a V-blank loop that copies ROUTINE to FF80 first and calls it after every HALT."""
    tile = bytes([0xAA, 0x55] * 8)
    prog = [("LD SP,nn", 0xFFFE),
            ("LD HL,nn", 0xFF80), ("LD DE,nn", "routine"), ("LD B,n", len(ROUTINE)),
            ("label", "rcopy"), ("LD A,(DE)",), ("LD (HL+),A",), ("INC DE",), ("DEC B",), ("JR NZ,e", "rcopy"),
            ("LD A,n", 0), ("LDH (n),A", 0x40),
            ("LD HL,nn", 0x8010), ("LD DE,nn", "tile"), ("LD B,n", 16),
            ("label", "copy"), ("LD A,(DE)",), ("LD (HL+),A",), ("INC DE",), ("DEC B",), ("JR NZ,e", "copy"),
            ("LD HL,nn", 0x9800), ("LD BC,nn", 0x0400),
            ("label", "fill"), ("LD A,n", 1), ("LD (HL+),A",), ("DEC BC",), ("LD A,B",), ("OR C",),
            ("JR NZ,e", "fill"),
            ("LD A,n", 0xE4), ("LDH (n),A", 0x47), ("LD A,n", 0x01), ("LDH (n),A", 0xFF), ("LD A,n", 0x91),
            ("LDH (n),A", 0x40), ("EI",),
            ("label", "idle"), ("HALT",), ("CALL nn", 0xFF80), ("JR e", "idle"),
            ("label", "routine"), ("db", ROUTINE), ("label", "tile"), ("db", tile)]
    vblank = asm.assemble(ctx.store, [("LDH A,(n)", 0x44), ("RETI",)], org=0x40)
    return asm.rom(ctx.store, prog, title="HRAMCODE", cart_type=0x00, extra={0x40: vblank})


@unittest.skipUnless(probes.probe({"kind": "executable", "name": "swiftc"})[0], "needs swiftc (macOS)")
class CartridgeApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.tmp = Path(tempfile.mkdtemp(prefix="cardmodel_cartapp_"))
        cls.old = (B.ROOT_OVERRIDE, C.EXPLORE_FRAMES, C.WITNESS_FRAMES)
        B.ROOT_OVERRIDE = cls.tmp / "arcade"                # the app and its parts, not the live depots
        C.EXPLORE_FRAMES, C.WITNESS_FRAMES = 300, 240
        cls.rom = hram_cart(cls.ctx)
        cls.path = cls.tmp / "HRAM Code (World).gb"
        cls.path.write_bytes(cls.rom)
        cls.info = C.build(cls.ctx, cls.path)

    @classmethod
    def tearDownClass(cls):
        B.ROOT_OVERRIDE, C.EXPLORE_FRAMES, C.WITNESS_FRAMES = cls.old
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_lifted_player_is_the_player_and_runs_only_lifted_code(self):
        w = self.info["witness"]
        self.assertTrue(w["identical"], w)
        self.assertEqual(w["frames"], C.WITNESS_FRAMES)
        self.assertGreaterEqual(self.info["lift"]["ram_instructions_lifted"], 4, "the HRAM routine is lifted")
        self.assertEqual(w["interpreted_ram"], 0, "the routine in HRAM runs as lifted card IR")
        self.assertEqual(w["interpreted"], 0, "every instruction ran as lifted card IR (HALT, EI, the loop)")
        self.assertGreater(w["instructions"], 10000)

    def test_the_app_plays_the_cartridge_where_it_is_and_keeps_what_ran(self):
        from cardmodel.kernel import resources
        app = Path(self.info["app"])
        spec = json.loads(next(app.rglob("game.json")).read_text())
        self.assertEqual(spec["cartridge"]["path"], str(self.path.resolve()))
        self.assertEqual(spec["id"], self.info["id"])
        self.assertIn(1, spec["globals"].values())
        exe = next(p for p in (app / "Contents" / "MacOS").iterdir())
        save = self.tmp / "save"
        p = resources.run([str(exe), "--frames", "120", "--save-dir", str(save), "--shot", str(self.tmp / "shot.png")],
                          timeout=120, heavy=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        w, h, rgb = G.png_read((self.tmp / "shot.png").read_bytes())
        ref = S.Player(self.ctx, "gameboy", self.rom, "native", fresh=True)
        for _ in range(120):
            ref.frame(0)
        self.assertEqual((w, h), (160, 144))
        self.assertEqual(rgb, ref.rgb(), "the app shows what the plain player computes")
        for _, f, _ in C.KEEP:
            self.assertTrue((save / f).is_file(), f"{f} is kept beside the save")
        self.assertEqual(spec["relift"]["argv"][1:4], ["arcade", "app", str(self.path.resolve())])

    def test_quitting_after_interpreted_code_starts_the_next_build(self):
        """With the lifted code switched off (everything interpreted), quitting starts the relift command."""
        from cardmodel.kernel import resources
        app = Path(self.info["app"])
        spec_path = next(app.rglob("game.json"))
        original = spec_path.read_text()
        spec = json.loads(original)
        marker = self.tmp / "relifted"
        spec["globals"] = {k: 0 for k in spec["globals"]}                      # lifted_on off
        spec["relift"]["argv"] = ["/bin/sh", "-c", f"echo relifted > '{marker}'"]
        spec_path.write_text(json.dumps(spec))
        exe = next(p for p in (app / "Contents" / "MacOS").iterdir())
        save = self.tmp / "save2"
        try:
            p = resources.run([str(exe), "--frames", "30", "--save-dir", str(save), "--relift"], timeout=120,
                              heavy=False)
        finally:
            spec_path.write_text(original)
        self.assertEqual(p.returncode, 0, p.stderr)
        for _ in range(100):
            if marker.is_file():
                break
            import time
            time.sleep(0.05)
        self.assertEqual(marker.read_text().strip(), "relifted")


if __name__ == "__main__":
    unittest.main()
