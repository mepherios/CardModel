"""Consoles in the arcade: the Game Boy player (system/gameboy) is the gameboy machine plus card-language glue. It
configures a cartridge exactly as the Python host does, shows the picture the machine finished, keeps battery RAM
and the clock in its save, and its native package plays a zipped cartridge headless. The library lists cartridges
where they are. Every cartridge here is synthetic (built by the card assembler): no ROM is stored or needed."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from helpers import model_ctx

from cardmodel.arcade import build as B
from cardmodel.arcade import library as L
from cardmodel.arcade import system as S
from cardmodel.engines import probes
from cardmodel.machine import asm, gb as G, native as N


def cart(ctx, cart_type=0x00, ram_code=0, cgb=0x00, rom_code=0, title="CARDTEST"):
    """The graphics program of the machine tests (a checkerboard, a sprite, V-blank HALTs) on a chosen board."""
    tile = bytes([0xAA, 0x55] * 8)
    prog = [("LD SP,nn", 0xFFFE), ("LD A,n", 0), ("LDH (n),A", 0x40),
            ("LD HL,nn", 0x8010), ("LD DE,nn", "tile"), ("LD B,n", 16),
            ("label", "copy"), ("LD A,(DE)",), ("LD (HL+),A",), ("INC DE",), ("DEC B",), ("JR NZ,e", "copy"),
            ("LD HL,nn", 0x9800), ("LD BC,nn", 0x0400),
            ("label", "fill"), ("LD A,n", 1), ("LD (HL+),A",), ("DEC BC",), ("LD A,B",), ("OR C",),
            ("JR NZ,e", "fill"),
            ("LD A,n", 0xE4), ("LDH (n),A", 0x47), ("LD A,n", 0x01), ("LDH (n),A", 0xFF), ("LD A,n", 0x91),
            ("LDH (n),A", 0x40), ("EI",), ("label", "idle"), ("HALT",), ("JR e", "idle"), ("label", "tile"), ("db", tile)]
    vblank = asm.assemble(ctx.store, [("LDH A,(n)", 0x44), ("RETI",)], org=0x40)
    return asm.rom(ctx.store, prog, title=title, cart_type=cart_type, ram_size_code=ram_code, cgb=cgb,
                   rom_size_code=rom_code, extra={0x40: vblank})


def ram_writer(ctx):
    """MBC3 + RAM + battery + RTC: enables RAM, writes 0x5A at 0xA010, then waits."""
    prog = [("LD SP,nn", 0xFFFE), ("LD A,n", 0x0A), ("LD (nn),A", 0x0000), ("LD A,n", 0x5A), ("LD (nn),A", 0xA010),
            ("label", "end"), ("HALT",), ("JR e", "end")]
    return asm.rom(ctx.store, prog, title="SAVECLOCK", cart_type=0x10, ram_size_code=2)


class GameBoyPlayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_tables_come_from_the_cartridge_card(self):
        card = S.system_card(self.ctx.store, "gameboy")
        src = S.tables(self.ctx, card)
        cc = self.ctx.store.get("hardware/gb_cartridge")
        kinds = [int(x) for x in src.split("array cart_kind: Int[256] = [")[1].split("]")[0].split(", ")]
        self.assertEqual(kinds[0x13], int(cc["mbc_kind"]["mbc3"]))
        self.assertEqual(kinds[0x1B], int(cc["mbc_kind"]["mbc5"]))
        self.assertEqual(kinds[0x22], int(cc["mbc_kind"]["mbc7"]))
        self.assertEqual(kinds[0xFF], 0, "an unsupported controller (HuC1) runs as ROM only, as the Python host does")
        self.assertIn(f"const CART_RAM_UNSIZED = {cc['ram_unsized_bytes']}", src)

    def test_the_player_configures_a_cartridge_like_the_host(self):
        m = N.load(self.ctx, S.module(self.ctx, "gameboy"), "native", fresh=True)
        names = ("mbc_kind", "rom_mask", "ram_mask", "has_rtc", "mbc1m", "cgb")
        boards = [(0x00, 0, 0x00, 0), (0x03, 2, 0x80, 2), (0x13, 3, 0xC0, 1), (0x10, 2, 0x00, 0), (0x06, 0, 0x00, 1),
                  (0x02, 0, 0x00, 0), (0x1B, 4, 0x80, 3), (0x22, 0, 0x00, 0), (0xFE, 3, 0x80, 5), (0xFC, 4, 0x00, 5)]
        for t, ram, cgb, rom_code in boards:
            rom = cart(self.ctx, t, ram, cgb, rom_code)
            m.call("reset_all")
            m.write("rom", rom)
            m.call("player_load", len(rom))
            info = G.header(rom, self.ctx.store)
            want = {"mbc_kind": info["mbc_kind"], "rom_mask": G._pow2(max(len(rom), info["rom_size"])) - 1,
                    "ram_mask": info["ram_size"] - 1 if info["ram_size"] else -1, "has_rtc": int(info["rtc"]),
                    "mbc1m": int(info["mbc1m"]), "cgb": int(info["cgb"])}
            self.assertEqual({n: m.get(n) for n in names}, want, hex(t))

    def test_the_picture_is_the_one_the_machine_finished(self):
        rom = cart(self.ctx)
        p = S.Player(self.ctx, "gameboy", rom, "native", fresh=True)
        ref = G.GameBoy(self.ctx, rom, "native", sample_rate=48000, fresh=True)
        seen = 0
        for k in range(90):
            p.frame(0)
            self.assertIn(len(p.drain_audio()) // 4, (800, 801), "1/60 s of sound at 48 kHz per frame")
            while ref.m.get("frames") < p.m.get("frames"):
                ref.run_frame()
            if k % 15 == 14:
                self.assertEqual(p.rgb(), ref.frame())
                seen += 1
        self.assertGreater(seen, 0)
        self.assertEqual(set(p.rgba()[3::4]), {255})

    def test_battery_ram_and_the_clock_survive_closing(self):
        rom = ram_writer(self.ctx)
        p = S.Player(self.ctx, "gameboy", rom, "native", fresh=True, clock=1_000_000)
        for _ in range(70):                       # the write, then a second without changes: the save is packed
            p.frame(0)
        self.assertEqual(p.m.get("player_save_dirty"), 1)
        p.m.set("rtc_h", 5)
        p.m.call("player_flush")
        save = p.m.read("player_save")
        self.assertEqual(save[0x10], 0x5A)
        self.assertEqual(bytes(save[0x20030:0x20034]), b"CMSV")
        q = S.Player(self.ctx, "gameboy", rom, "native", fresh=True, clock=1_000_000 + 3600, save=save)
        self.assertEqual(q.m.read("cram", 0x10, 1)[0], 0x5A)
        self.assertEqual(q.m.get("rtc_h"), 6, "an hour closed is an hour on the cartridge's clock")

    def test_the_check_cartridge_comes_from_the_system_card(self):
        """The store check's own cartridge is assembled from the instruction cards (no one's game): its header is
        the card's board, it draws a two-shade checkerboard and leaves the card's byte in battery RAM."""
        c = S.check_cartridge(self.ctx, "gameboy")
        h = G.header(c["bytes"], self.ctx.store)
        self.assertEqual((h["title"], h["mbc"], h["battery"], h["ram_size"], h["header_checksum_ok"]),
                         ("CARDCHECK", "mbc3", True, 8192, True))
        p = S.Player(self.ctx, "gameboy", c["bytes"], "native", fresh=True)
        for _ in range(30):
            p.frame(0)
        p.m.call("player_flush")
        save = p.m.read("player_save")
        self.assertEqual(save[c["save"]["offset"]], c["save"]["byte"])
        self.assertEqual(bytes(save[0x20030:0x20034]), b"CMSV")
        self.assertEqual(G.frame_stats(p.rgb())["colours"], 2)

    def test_a_reused_machine_starts_each_cartridge_as_a_fresh_one(self):
        """The store check inserts cartridge after cartridge into one loaded player (start): each one's picture is
        the one a freshly loaded module draws, whatever ran before (reset_all leaves the ROM array to the host)."""
        big = bytearray(cart(self.ctx, 0x1B, 0, 0x80, 3, "BIGFIRST"))  # 256 KiB first, then a 32 KiB cartridge
        big[0x8000:] = b"\x76" * (len(big) - 0x8000)                     # banks the first one never runs, not zero
        big = bytes(big)
        small = cart(self.ctx, 0x00, 0, 0x00, 0, "SMALLNEXT")
        p = S.Player(self.ctx, "gameboy", big, "native", fresh=True)
        for _ in range(20):
            p.frame(0)
        p.start(small)
        fresh = S.Player(self.ctx, "gameboy", small, "native", fresh=True)
        for _ in range(45):
            p.frame(0)
            fresh.frame(0)
        self.assertEqual(p.rgb(), fresh.rgb())
        self.assertEqual(p.m.read("rom", 0x8000, 64), fresh.m.read("rom", 0x8000, 64), "no bytes of the first left")


class Library(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_no_intro_names_read_as_titles(self):
        self.assertEqual(L.display_title("Legend of Zelda, The - Link's Awakening (USA, Europe) (Rev B)"),
                         ("The Legend of Zelda - Link's Awakening", "(USA, Europe) (Rev B)"))
        self.assertEqual(L.display_title("Tetris (World) (Rev A)"), ("Tetris", "(World) (Rev A)"))
        self.assertEqual(L.display_title("Plain"), ("Plain", ""))

    def test_a_file_without_a_no_intro_name_is_titled_by_its_header(self):
        d = Path(tempfile.mkdtemp(prefix="cardmodel_carts_"))
        card = S.system_card(self.ctx.store, "gameboy")
        (d / "my cartridge.gb").write_bytes(cart(self.ctx, title="HEADERNAME"))
        (d / "Named Game (Europe).gb").write_bytes(cart(self.ctx, title="HEADERNAME"))
        (d / "untitled.gb").write_bytes(cart(self.ctx, title=""))
        got = {p: L.describe(self.ctx, card, d / p, (".gb",)) for p in ("my cartridge.gb", "Named Game (Europe).gb",
                                                                         "untitled.gb")}
        mine = got["my cartridge.gb"]
        self.assertEqual((mine["title"], mine["title_from"]), ("HEADERNAME", "header"))
        self.assertEqual((got["Named Game (Europe).gb"]["title"], got["Named Game (Europe).gb"]["title_from"]),
                         ("Named Game", "file name"))
        self.assertEqual((got["untitled.gb"]["title"], got["untitled.gb"]["title_from"]), ("untitled", "file name"))

    def test_a_folder_of_cartridges_is_listed_where_it_is(self):
        d = Path(tempfile.mkdtemp(prefix="cardmodel_carts_"))
        rom = cart(self.ctx, 0x00, 0, 0x80, 0, "COLORTEST")
        with zipfile.ZipFile(d / "Color Test (World).zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Color Test (World).gbc", rom)
        card = S.system_card(self.ctx.store, "gameboy")
        row = L.describe(self.ctx, card, d / "Color Test (World).zip", (".gb", ".gbc"))
        self.assertEqual((row["title"], row["tags"], row["system"]), ("Color Test", "(World)", "gbc"))
        self.assertEqual(row["header"]["title"], "COLORTEST")
        self.assertEqual(L.read_cartridge(d / "Color Test (World).zip", (".gbc",)), rom)
        (d / "Plain Test (World).gb").write_bytes(cart(self.ctx))      # a DMG cartridge: BGP sets its shades
        m = N.load(self.ctx, S.Bd.module(self.ctx, "gameboy"), "native", fresh=True)
        png = L.draw_cover(self.ctx, m, d / "Plain Test (World).gb")
        self.assertTrue(png.startswith(b"\x89PNG"))
        self.assertGreater(G.frame_stats(G.png_read(png)[2])["colours"], 1)


# the SHA-256 of the 48 bytes every licensed cartridge carries at 0x104 (the boot ROM checks them); only the hash is
# here, computed from the user's cartridges in memory
LOGO_SHA256 = "daf4cabdc852baa0291849203f0b41fd0b4ecd58e0d7aff4a509f5de4d7f9a2e"
CART_EXTS = (".gb", ".gbc", ".sgb", ".nds")


def cartridges_in(files, logo_sha256: str = LOGO_SHA256) -> list[str]:
    """The files that are, or zip, a cartridge: by extension, or by the logo's hash at 0x104."""
    import hashlib
    import io

    def is_cart(data: bytes) -> bool:
        return len(data) >= 0x150 and hashlib.sha256(data[0x104:0x134]).hexdigest() == logo_sha256
    found = []
    for f in files:
        f = Path(f)
        if f.suffix.lower() in CART_EXTS:
            found.append(str(f))
            continue
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if is_cart(data):
            found.append(str(f))
        elif f.suffix.lower() == ".zip":
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if any(Path(n).suffix.lower() in CART_EXTS or is_cart(z.read(n)) for n in z.namelist()):
                    found.append(str(f))
    return found


class NoCartridgeInTheRepository(unittest.TestCase):
    """Cartridges are read where the user keeps them: no tracked file is one or zips one, and the folders that
    hold what is derived from them (state/: pictures, lifted code, surveys) and the saves are ignored by git."""

    def test_no_tracked_file_is_a_cartridge(self):
        import subprocess
        from helpers import ROOT
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
        files = [ROOT / f.decode() for f in out.split(b"\0") if f]
        self.assertGreater(len(files), 100)
        self.assertEqual(cartridges_in(files), [])

    def test_the_detector_sees_cartridges(self):
        """A planted cartridge of each kind is found: a .gb file, a .zip holding a .gbc, and (standing in for the
        logo, whose bytes are not here) a renamed file whose bytes at 0x104 have the hash looked for."""
        import hashlib
        ctx = model_ctx()
        rom = cart(ctx)
        d = Path(tempfile.mkdtemp(prefix="cardmodel_planted_"))
        (d / "a.gb").write_bytes(rom)
        with zipfile.ZipFile(d / "b.zip", "w") as z:
            z.writestr("b.gbc", rom)
        (d / "c.bin").write_bytes(rom)
        (d / "d.txt").write_text("no cartridge")
        logo = hashlib.sha256(rom[0x104:0x134]).hexdigest()
        self.assertEqual(sorted(Path(f).name for f in cartridges_in(sorted(d.iterdir()), logo)),
                         ["a.gb", "b.zip", "c.bin"])
        self.assertEqual(cartridges_in([d / "c.bin"]), [], "the card assembler leaves the real logo out")

    def test_state_and_saves_are_ignored(self):
        import subprocess
        from helpers import ROOT
        for rel in ("state/emu/x.json", "state/arcade/covers/rom-0.png", "saves/x/save.bin"):
            p = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT)
            self.assertEqual(p.returncode, 0, f"{rel} is not ignored by git")


@unittest.skipUnless(probes.probe({"kind": "executable", "name": "swiftc"})[0], "needs swiftc (macOS)")
class PlayerPackage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.old_root = B.ROOT_OVERRIDE
        B.ROOT_OVERRIDE = Path(tempfile.mkdtemp(prefix="cardmodel_arcade_"))   # not the live depots
        cls.info = S.build(cls.ctx, "gameboy")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(B.ROOT_OVERRIDE, ignore_errors=True)
        B.ROOT_OVERRIDE = cls.old_root

    def test_the_package_plays_a_zipped_cartridge(self):
        from cardmodel.kernel import resources
        root = B.latest(self.ctx, "gameboy_player")
        man = json.loads((root / "manifest.json").read_text())
        self.assertEqual(man["kind"], "system")
        spec = json.loads(next((root / "content").rglob("game.json")).read_text())
        self.assertEqual(spec["cartridge"]["extensions"], [".gb", ".gbc", ".sgb"])
        d = Path(tempfile.mkdtemp(prefix="cardmodel_gbp_"))
        rom = cart(self.ctx)
        with zipfile.ZipFile(d / "test.zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("test.gb", rom)
        p = resources.run([str(root / "content" / man["executable"]), "--rom", str(d / "test.zip"), "--frames", "60",
                           "--save-dir", str(d / "save"), "--shot", str(d / "shot.png")], timeout=120, heavy=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("ran 60 frames", p.stdout)
        w, h, rgb = G.png_read((d / "shot.png").read_bytes())
        ref = S.Player(self.ctx, "gameboy", rom, "native", fresh=True)
        for _ in range(60):
            ref.frame(0)
        self.assertEqual((w, h), (160, 144))
        self.assertEqual(rgb, ref.rgb(), "the native package shows what the module computes")



@unittest.skipUnless(probes.probe({"kind": "executable", "name": "swiftc"})[0], "needs swiftc (macOS)")
class CartridgesThroughTheStore(unittest.TestCase):
    """Every cartridge the store's library lists launches through the store as Launcher.playRom launches it: the
    Game Boy Player installed from its depot, the cartridge where it is (a plain file, a zip), its title, a save
    folder per cartridge; it runs headless and shows the picture the player's cards compute for those bytes. A DS
    cartridge is listed but has no player; a cartridge moved after the listing does not launch (the launcher's own
    guard). The library is a temporary one with synthetic cartridges (the card assembler)."""

    @classmethod
    def setUpClass(cls):
        from cardmodel.arcade import client
        cls.client = client
        cls.ctx = model_ctx()
        cls.old = (B.ROOT_OVERRIDE, L.SETTINGS_OVERRIDE)
        B.ROOT_OVERRIDE = Path(tempfile.mkdtemp(prefix="cardmodel_arcade_"))      # not the live depots
        d = Path(tempfile.mkdtemp(prefix="cardmodel_carts_"))
        L.SETTINGS_OVERRIDE = d / "library.json"
        gb, ds = d / "gb", d / "ds"
        gb.mkdir()
        ds.mkdir()
        (gb / "Checker Board (World).gb").write_bytes(cart(cls.ctx))
        with zipfile.ZipFile(gb / "Color Test (World).zip", "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("Color Test (World).gbc", cart(cls.ctx, 0x00, 0, 0x80, 0, "COLORTEST"))
        (gb / "save test.gb").write_bytes(ram_writer(cls.ctx))       # titled by its header; writes battery RAM
        (ds / "Some Game (Europe).nds").write_bytes(b"SOMEGAME\0\0\0\0ABCE" + bytes(0x200))
        L.set_folder(cls.ctx, "gameboy", add=str(gb))
        L.set_folder(cls.ctx, "nds", add=str(ds))
        L.draw_covers(cls.ctx)                  # now, so no background drawing changes the listing under a test
        cls.gb = gb

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(B.ROOT_OVERRIDE, ignore_errors=True)
        B.ROOT_OVERRIDE, L.SETTINGS_OVERRIDE = cls.old
        L.scan(cls.ctx, force=True)

    def test_every_listed_cartridge_launches_through_the_store(self):
        L.scan(self.ctx, force=True)
        rep = self.client.check_catalog(self.ctx, frames=90, only=["gameboy_player"])
        self.assertEqual(rep["status"], "pass", json.dumps(rep, default=str)[:3000])
        self.assertEqual(sorted(rep["items"]), ["gameboy_player"])
        ct = rep["cartridges"]
        self.assertEqual((ct["listed"], ct["checked"], ct["launched"], ct["failed"]), (4, 3, 3, 0), ct)
        self.assertEqual(ct["unplayable"], {"nds": 1})
        self.assertEqual(ct["players"]["gameboy_player"]["launched"], 3)
        self.assertGreaterEqual(ct["players"]["gameboy_player"]["colourful"], 1)
        self.assertEqual(ct["saves_written"], 1, "the battery cartridge's save is in its own folder")
        self.assertTrue(rep["items"]["gameboy_player"]["verify_after_cartridges"]["ok"])
        titles = sorted(r["title"] for r in L.scan(self.ctx)["roms"])
        self.assertEqual(titles, ["Checker Board", "Color Test", "SAVECLOCK", "Some Game"])

    def test_a_cartridge_moved_after_the_listing_does_not_launch(self):
        L.scan(self.ctx, force=True)
        moved = self.gb / "Checker Board (World).gb"
        away = self.gb.parent / "elsewhere.gb"
        moved.rename(away)
        try:
            rep = self.client.check_catalog(self.ctx, frames=30, only=["gameboy_player"])
        finally:
            away.rename(moved)
        ct = rep["cartridges"]
        self.assertEqual(rep["status"], "fail")
        self.assertEqual((ct["launched"], ct["failed"]), (2, 1), ct)
        self.assertIn("is not at", ct["failing"][0]["error"])
        self.assertEqual(ct["failing"][0]["title"], "Checker Board")

    def test_a_picture_the_cards_do_not_compute_fails(self):
        """The comparison is what makes a launch count: when the cards' picture differs from the player's by one
        pixel (the reference is altered here: for the listed cartridges only, then for the check cartridge too),
        those launches fail; a player whose own check fails launches no cartridge."""
        from unittest import mock
        real = self.client.Reference.picture
        check = S.check_cartridge(self.ctx, "gameboy")["bytes"]

        def altered(also_check):
            def picture(ref, rom, frames):
                w, h, rgb = real(ref, rom, frames)
                return (w, h, bytes([rgb[0] ^ 0xFF]) + rgb[1:]) if also_check or rom != check else (w, h, rgb)
            return picture
        L.scan(self.ctx, force=True)
        with mock.patch.object(self.client.Reference, "picture", altered(False)):
            rep = self.client.check_catalog(self.ctx, frames=30, only=["gameboy_player"])
        ct = rep["cartridges"]
        self.assertEqual(rep["status"], "fail")
        self.assertTrue(rep["items"]["gameboy_player"]["ok"])
        self.assertEqual((ct["launched"], ct["failed"]), (0, 3))
        self.assertTrue(all("picture its cards do not compute" in f["error"] for f in ct["failing"]), ct["failing"])
        with mock.patch.object(self.client.Reference, "picture", altered(True)):
            rep = self.client.check_catalog(self.ctx, frames=30, only=["gameboy_player"])
        self.assertFalse(rep["items"]["gameboy_player"]["play"]["same_as_cards"])
        self.assertEqual(rep["cartridges"]["launched"], 0)
        self.assertTrue(all("did not pass the store's own check" in f["error"] for f in rep["cartridges"]["failing"]))

    def test_a_player_that_did_not_install_launches_nothing(self):
        """check_cartridges on its own: with no player that passed its own store check, no cartridge is started."""
        import shutil
        L.scan(self.ctx, force=True)
        base, stop = self.client.serve_here(self.ctx, None)
        work = Path(tempfile.mkdtemp(prefix="cardmodel_store_"))
        try:
            ct = self.client.check_cartridges(self.ctx, base, work / "library", work, 30, set(), {})
        finally:
            stop()
            shutil.rmtree(work, ignore_errors=True)
        self.assertEqual((ct["launched"], ct["failed"]), (0, 3))
        self.assertTrue(all("did not pass the store's own check" in f["error"] for f in ct["failing"]))


if __name__ == "__main__":
    unittest.main()
