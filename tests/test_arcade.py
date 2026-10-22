"""Games as cards: Vector Duel compiles from its cards, runs the same in two engines, and its duel decides counters
with the combat kernel (a timed guard redirects), links strings as its chain cards allow, and changes its boss's
phase as the game card says; the build makes a package and a depot whose chunks check out through the arcade
service. No game binary or picture is stored in the repository: everything is built here."""
import hashlib
import json
import threading
import unittest
import urllib.request

from helpers import model_ctx

from cardmodel.arcade import build as B
from cardmodel.arcade import game as G
from cardmodel.arcade import gen
from cardmodel.engines import probes


def to_versus(g):
    """Title -> VERSUS -> P1 keeps the Warden, P2 moves from the Duelist to the Warden -> the round starts."""
    b = lambda *n: G.bits(g.card, n)  # noqa: E731
    script = {200: b("down"), 204: b("down"), 210: b("confirm"), 226: b("confirm")}
    script2 = {218: b("left")}
    for f in range(240):
        g.frame(script.get(f, 0), script2.get(f, 0))
        g.drain_audio()
    assert list(g.m.array("f_ft")) == [0, 0], list(g.m.array("f_ft"))
    return b


def close_in(g, b):
    """The round intro, then both walk in to striking distance and stand."""
    for f in range(110):
        g.frame(0, 0)
    for f in range(40):
        g.frame(b("right"), b("left"))
    for f in range(20):
        g.frame(0, 0)


class VectorDuel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def test_tables_come_from_the_cards(self):
        card = G.game_card(self.ctx.store, "vector_duel")
        src, rep = gen.generate(self.ctx, card)
        moves = rep["moves"]
        self.assertIn("slash_left", moves)
        self.assertIn(f"const MV_SLASH_LEFT = {moves.index('slash_left')}", src)
        # the equilibrium tables are the model's exact solutions (one per fighter pair and distance)
        self.assertEqual(len(rep["equilibria"]), len(rep["fighters"]) ** 2 * 3)
        # the string links are the chain cards; the duel tree is solved once per pair of fighters; the boss's
        # phases are the game card's
        chains = [c for c in self.ctx.store.cards("chain") if c["from"] in moves and c["to"] in moves]
        self.assertIn(f"const N_CHAINS = {len(chains)}", src)
        n = len(rep["fighters"])
        self.assertEqual(len(rep["tree"]), n * (n + 1) // 2)
        self.assertTrue(all(t["depth"] == card["duel_tree"]["depth"] for t in rep["tree"]))
        self.assertIn(f"const N_PHASES = {len(card['boss']['phases'])}", src)

    def test_module_runs_the_same_in_two_engines(self):
        hashes = {}
        for engine in ("native", "host"):
            g = G.Game(self.ctx, "vector_duel", engine, fresh=True)
            for f in range(24):
                g.frame(G.bits(g.card, ["confirm"]) if f == 3 else 0, 0)
                g.drain_audio()
            hashes[engine] = g.state_hash()
        self.assertEqual(hashes["native"], hashes["host"])

    def test_a_timed_guard_redirects(self):
        """Versus, both human: P2 starts an overhead; P1 raises a high guard so that it is up 1 frame before the
        impact (overhead startup 16, guard startup 2, perfect window 4): the kernel's outcome is a redirect."""
        g = G.Game(self.ctx, "vector_duel", "native", fresh=True)
        b = to_versus(g)
        for f in range(110):            # the round intro
            g.frame(0, 0)
        # close in to mid distance
        for f in range(40):
            g.frame(b("right"), b("left"))
        for f in range(20):
            g.frame(0, 0)
        g.drain_audio()
        start = g.m.get("duel_t")
        script1 = {13: b("guard", "up"), 14: b("guard", "up")}
        for k in range(15, 40):
            script1[k] = b("guard", "up")
        for k in range(40):
            g.frame(script1.get(k, 0), b("attack", "up") if k == 0 else 0)
        self.assertGreater(g.m.get("duel_t"), start)
        self.assertEqual(g.m.array("st_redirects")[0], 1, "P1's timed high guard redirects P2's overhead")

    def test_an_early_guard_only_blocks(self):
        """A high guard held long before the overhead lands is "just holding" (timing class 0): a block. Fully
        aligned, the kernel lets no HP through (damage_through: dmg * (2 - al) // 8) but the guard takes posture."""
        g = G.Game(self.ctx, "vector_duel", "native", fresh=True)
        b = to_versus(g)
        for f in range(110):
            g.frame(0, 0)
        for f in range(40):
            g.frame(b("right"), b("left"))
        for f in range(20):
            g.frame(0, 0)
        hp0 = g.m.array("f_hp")[0]
        for k in range(40):
            g.frame(b("guard", "up"), b("attack", "up") if k == 12 else 0)
        self.assertEqual(g.m.array("st_redirects")[0], 0)
        self.assertEqual(g.m.array("st_deflects")[0], 0)
        self.assertEqual(g.m.array("f_hp")[0], hp0)
        self.assertGreater(g.m.array("f_post")[0], 0, "a block costs posture")


class Strings(unittest.TestCase):
    """Versus, both human, at striking distance: P1's slash_left (startup 12, active 3) hits P2."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def duel(self):
        g = G.Game(self.ctx, "vector_duel", "native", fresh=True)
        b = to_versus(g)
        close_in(g, b)
        return g, b

    def test_a_string_links_on_a_connect(self):
        """Attack + up pressed during the hit's freeze cancels the recovery into the slash_left_to_overhead link
        (window 0..10 of the recovery): the overhead lands too, prorated to 80 % (22 -> 17)."""
        g, b = self.duel()
        hp = g.m.array("f_hp")[1]
        for k in range(60):
            g.frame(b("attack", "left") if k == 0 else (b("attack", "up") if k == 14 else 0), 0)
        self.assertEqual(g.m.array("st_links")[0], 1)
        self.assertEqual(g.m.get("combo_n"), 2)
        self.assertEqual(hp - g.m.array("f_hp")[1], 14 + 22 * 80 // 100)

    def test_only_a_connected_attack_links(self):
        """From far away the slash whiffs: the same press does not cancel its recovery."""
        g = G.Game(self.ctx, "vector_duel", "native", fresh=True)
        b = to_versus(g)
        for f in range(110):
            g.frame(0, 0)
        for k in range(24):
            g.frame(b("attack", "left") if k == 0 else (b("attack", "up") if k == 14 else 0), 0)
        self.assertEqual(g.m.array("f_links")[0], 0)
        self.assertEqual(gen.moves_of(self.ctx.store, g.card["fighters"])[g.m.array("f_move")[0]], "slash_left")

    def test_a_redirected_link_breaks_the_string(self):
        """P2, struck and stunned, holds a high guard: it rises as the hit-stun ends, a few frames before the linked
        overhead lands (GL10 keeps that time), inside the guard's perfect window: a redirect breaks the string."""
        g, b = self.duel()
        for k in range(60):
            g.frame(b("attack", "left") if k == 0 else (b("attack", "up") if k == 14 else 0),
                    b("guard", "up") if k >= 20 else 0)
        self.assertEqual(g.m.array("st_string_breaks")[1], 1)
        self.assertEqual(g.m.array("st_links")[0], 0)


class BossPhases(unittest.TestCase):
    def test_the_boss_changes_phase_from_its_card(self):
        """The Architect's stage: when a hit takes its health under the next phase's share, everything stops, it
        clears its posture and plays at that phase's level and tempo; after the phase intro the fight goes on."""
        ctx = model_ctx()
        g = G.Game(ctx, "vector_duel", "native", fresh=True)
        b = lambda *n: G.bits(g.card, n)  # noqa: E731
        phases = g.card["boss"]["phases"]
        for f in range(240):                                # title -> arcade -> fighter -> the ladder
            g.frame({200: b("confirm"), 216: b("confirm")}.get(f, 0), 0)
        g.m.set("stage", len(g.card["ladder"]) - 1)
        for f in range(4):
            g.frame(b("confirm") if f == 1 else 0, 0)
        close_in(g, b)
        self.assertEqual(g.m.array("f_ctl")[1], gen.AIS.index("boss"))
        self.assertEqual((g.m.get("boss_phase"), g.m.array("ai_level")[1]), (0, phases[0]["level"]))
        hpmax = g.m.array("f_hpmax")[1]
        g.m.array("f_hp")[1] = hpmax * phases[1]["at"] // 100 + 1
        g.m.array("f_stance")[1] = 3                        # broken: it stands still for the slash
        g.m.array("f_stun")[1] = 72
        for k in range(30):
            g.frame(b("attack", "left") if k == 0 else 0, 0)
            if g.m.get("round_state") == 3:
                break
        self.assertEqual(g.m.get("round_state"), 3)
        self.assertEqual(g.m.get("boss_phase"), 1)
        self.assertEqual(g.m.array("ai_level")[1], phases[1]["level"])
        self.assertEqual(g.m.get("mus_tempo"), phases[1]["tempo"])
        self.assertEqual(g.m.array("f_post")[1], 0)
        for f in range(200):
            g.frame(0, 0)
        self.assertEqual(g.m.get("round_state"), 1)


class Pages(unittest.TestCase):
    def test_the_pages_hash_changes_with_the_pages(self):
        """/api/status carries a hash of the launcher's pages: an open page that sees it change loads the new ones
        (a reinstalled launcher, a service restarted from another checkout)."""
        import tempfile
        from pathlib import Path
        from cardmodel.arcade import server
        d = Path(tempfile.mkdtemp(prefix="cardmodel_ui_"))
        (d / "index.html").write_text("<p>one</p>")
        a = server.ui_hash(d)
        (d / "app.js").write_text("// two")
        b = server.ui_hash(d)
        self.assertTrue(a and b and a != b)
        self.assertEqual(server.ui_hash(d), b, "the same pages, the same hash")
        self.assertEqual(server.ui_hash(None), "")


@unittest.skipUnless(probes.probe({"kind": "executable", "name": "swiftc"})[0], "needs swiftc (macOS)")
class Depot(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tempfile
        from pathlib import Path
        cls.ctx = model_ctx()
        cls.old_root = B.ROOT_OVERRIDE
        B.ROOT_OVERRIDE = Path(tempfile.mkdtemp(prefix="cardmodel_arcade_"))   # not the live depots
        cls.info = B.build(cls.ctx, "vector_duel")

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(B.ROOT_OVERRIDE, ignore_errors=True)
        B.ROOT_OVERRIDE = cls.old_root

    def test_manifest_chunks_rebuild_the_files(self):
        root = B.latest(self.ctx, "vector_duel")
        man = json.loads((root / "manifest.json").read_text())
        self.assertEqual(man["build"], self.info["build"])
        chunks = B.arcade_root(self.ctx) / "chunks"
        for f in man["files"]:
            data = b"".join((chunks / c["sha256"]).read_bytes() for c in f["chunks"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), f["sha256"], f["path"])
            self.assertEqual(data, (root / "content" / f["path"]).read_bytes())
        self.assertTrue(any(f["executable"] for f in man["files"]))
        self.assertIn("screenshot_1.png", man["media"])

    def test_service_serves_catalog_manifest_and_chunks(self):
        from http.server import ThreadingHTTPServer
        from cardmodel.arcade import server as S
        S.Handler.ctx = self.ctx
        S.Handler.ui_dir = None
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        try:
            cat = json.loads(urllib.request.urlopen(base + "/api/catalog", timeout=10).read())
            g = next(x for x in cat if x["id"] == "vector_duel")
            self.assertFalse(g["build_due"], "the build just made is current")
            man = json.loads(urllib.request.urlopen(base + g["build"]["manifest"], timeout=10).read())
            c = man["files"][0]["chunks"][0]
            data = urllib.request.urlopen(f"{base}/chunk/{c['sha256']}", timeout=10).read()
            self.assertEqual(hashlib.sha256(data).hexdigest(), c["sha256"])
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_every_catalogue_item_launches_from_the_store(self):
        """CM42: every program the catalogue lists (the games and the console players), through the service exactly
        as the launcher does it: installed with every chunk and file checked, verified, damaged and repaired (only
        the damaged file is fetched again), played natively headless with its own save folder, drawing a frame that
        is not one flat colour (a player plays its system card's check cartridge: the picture its cards compute,
        the card's byte in the save); the launcher's pages are served and name only routes the service documents."""
        from cardmodel.arcade import client
        from cardmodel.arcade import system as S
        rep = client.check_catalog(self.ctx, frames=60)
        self.assertEqual(rep["status"], "pass", json.dumps(rep, default=str)[:3000])
        players = [S.arcade_id(c) for c in self.ctx.store.cards("system") if c.get("machine") and c.get("logic")]
        self.assertEqual(players, ["gameboy_player", "nds_player"])
        self.assertEqual(sorted(rep["items"]), sorted([c.name for c in self.ctx.store.cards("game")] + players))
        self.assertEqual(sorted(rep["items"]), sorted(rep["catalog"]), "the release catalogue lists exactly these")
        for gid, r in rep["items"].items():
            self.assertTrue(r["repair"]["seen"], gid)
            self.assertLess(r["repair"]["fetched"], r["install"]["size"], f"{gid}: repair fetched only the damage")
            self.assertGreater(r["play"]["picture"]["colours_sampled"], 1, gid)
        for player in players:                  # each on its check cartridge: the cards' picture, the card's byte saved
            pl = rep["items"][player]["play"]
            self.assertTrue(pl["same_as_cards"] and pl["save_kept"], (player, pl))
        self.assertEqual(rep["cartridges"]["listed"], 0, "the tests' own library is empty (tests/helpers.py)")
        self.assertTrue(rep["pages"]["ok"], rep["pages"])
        self.assertIn("/api/library", rep["pages"]["api"])

    def test_native_package_runs_headless(self):
        import tempfile
        from cardmodel.kernel import resources
        root = B.latest(self.ctx, "vector_duel")
        man = json.loads((root / "manifest.json").read_text())
        d = tempfile.mkdtemp(prefix="cardmodel_vd_")
        p = resources.run([str(root / "content" / man["executable"]), "--frames", "120", "--save-dir", d,
                           "--shot", d + "/shot.png"], timeout=120, heavy=False)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("ran 120 frames", p.stdout)


class BuildWait(unittest.TestCase):
    """The launcher's wait for a build (Launcher.install; client.wait_build is the same steps) always ends: a build
    the service refuses ends it with the service's reason, and a build the service no longer knows (it restarted) is
    asked for again and, if it stays unknown, ends it. It used to wait for ever, and the launcher then ignored every
    later install until it was restarted."""

    @classmethod
    def setUpClass(cls):
        from http.server import ThreadingHTTPServer
        from cardmodel.arcade import client
        from cardmodel.arcade import server
        cls.S, cls.C = server, client
        server.Handler.ctx = model_ctx()
        server.Handler.ui_dir = None
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.real, self.limits = self.S.start_build, (self.C.LOST_ASK_AGAIN, self.C.LOST_GIVE_UP)
        self.C.LOST_ASK_AGAIN, self.C.LOST_GIVE_UP = 2, 6         # the launcher's 2 s and 10 s, shortened
        self.asked = []

    def tearDown(self):
        self.S.start_build = self.real
        self.C.LOST_ASK_AGAIN, self.C.LOST_GIVE_UP = self.limits
        self.S._builds.pop("vector_duel", None)

    def forget_until(self, n):
        """The service forgets each build it starts (as a restart does) until it has been asked n times."""
        def start(ctx, gid):
            self.asked.append(gid)
            if len(self.asked) >= n:
                self.S._builds[gid] = {"state": "done", "step": 6, "of": 6, "label": "ready", "build": "b1"}
            return {"state": "building"}
        self.S.start_build = start

    def test_a_lost_build_is_asked_for_again(self):
        self.forget_until(2)
        self.assertEqual(self.C.wait_build(self.base, "vector_duel", timeout=60), "b1")
        self.assertEqual(self.asked, ["vector_duel", "vector_duel"])

    def test_a_build_that_stays_lost_ends_the_wait(self):
        import time
        self.forget_until(99)
        t0 = time.monotonic()
        with self.assertRaisesRegex(self.C.StoreError, "lost the build of vector_duel"):
            self.C.wait_build(self.base, "vector_duel", timeout=60)
        self.assertLess(time.monotonic() - t0, 20)
        self.assertEqual(len(self.asked), 2, "asked once more, then the wait ended")

    def test_a_refused_build_ends_the_wait_with_the_reason(self):
        with self.assertRaisesRegex(self.C.StoreError, "would not build no_such_program: no such game"):
            self.C.wait_build(self.base, "no_such_program", timeout=60)


@unittest.skipUnless(probes.probe({"kind": "executable", "name": "swiftc"})[0], "needs swiftc (macOS)")
class LauncherRecord(unittest.TestCase):
    def test_the_record_follows_the_library_folder(self):
        """The launcher compiles, and at start what it records as installed is what its library folder holds: an
        installation the record lost (another launcher had saved over it) comes back from its own manifest, one
        updated behind the record's back gets the folder's build and keeps its play time, a record whose folder is
        gone goes, and a half-done install (its .staging folder) is no installation. Everything else in the record
        stays. (--check-library runs this without a window, in the folder CARDMODEL_ARCADE_SUPPORT names.)"""
        import os
        import tempfile
        from pathlib import Path
        from cardmodel.kernel import resources
        ctx = model_ctx()
        app = ctx.store.get("app/arcade")
        plat = ctx.store.get(f"platform/{app['platform']}")
        work = Path(tempfile.mkdtemp(prefix="cardmodel_launcher_"))
        exe = work / "launcher"
        p = resources.run([B._tool(plat["probe"]), "-Onone", "-swift-version", "5", "-o", str(exe)]
                          + [str(app.path / s) for s in app["sources"]]
                          + ["-framework", "AppKit", "-framework", "WebKit", "-framework", "CryptoKit"], timeout=900)
        self.assertEqual(p.returncode, 0, p.stderr[-3000:])
        sup = work / "support"

        def manifest(i, version, build):
            d = sup / "library" / i
            d.mkdir(parents=True)
            (d / ".manifest.json").write_text(json.dumps({
                "id": i.split(".")[0], "title": i, "version": version, "build": build, "app": f"{i}.app",
                "executable": f"{i}.app/Contents/MacOS/{i}", "size": 10, "files": []}))

        def record(version, build, seconds):
            return {"version": version, "build": build, "size": 1, "installedAt": 1.0, "playSeconds": seconds,
                    "lastPlayed": 2.0, "app": "x.app", "executable": "x", "manifest": "/depot/x"}
        manifest("kept", "1.1.0", "b2")              # updated behind the record's back
        manifest("lost", "0.4.0", "b9")              # installed, the record lost it
        manifest("lost.staging", "0.5.0", "zz")      # an install that did not finish
        (sup / "launcher.json").write_text(json.dumps({
            "library": {"kept": record("1.0.0", "b1", 50.0), "gone": record("2.0.0", "b3", 7.0)},
            "settings": {"bandwidth": 0, "user": "T"}, "played": {"rom-1": {"playSeconds": 3.0, "lastPlayed": 4.0}}}))
        r = resources.run([str(exe), "--check-library"], timeout=60, heavy=False,
                          env={**os.environ, "CARDMODEL_ARCADE_SUPPORT": str(sup)})
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        lib = json.loads(r.stdout)
        self.assertEqual(sorted(lib), ["kept", "lost"])
        kept = lib["kept"]
        self.assertEqual((kept["build"], kept["version"], kept["playSeconds"]), ("b2", "1.1.0", 50))
        self.assertEqual((lib["lost"]["build"], lib["lost"]["playSeconds"]), ("b9", 0))
        self.assertEqual(lib["lost"]["executable"], "lost.app/Contents/MacOS/lost")
        saved = json.loads((sup / "launcher.json").read_text())
        self.assertEqual(sorted(saved["library"]), ["kept", "lost"], "the healed record is saved")
        self.assertEqual(saved["library"]["kept"]["installedAt"], 1.0)
        self.assertEqual(saved["library"]["lost"]["manifest"], "/depot/lost/0.4.0+b9/manifest.json")
        self.assertEqual(saved["played"], {"rom-1": {"playSeconds": 3, "lastPlayed": 4}})
        self.assertEqual(saved["settings"]["user"], "T")


class Store(unittest.TestCase):
    def test_a_headless_run_never_writes_the_players_save(self):
        import argparse
        import tempfile
        from pathlib import Path
        from cardmodel.arcade import cli as A
        from cardmodel.kernel import resources
        seen = []
        root = Path(tempfile.mkdtemp(prefix="cardmodel_run_"))
        (root / "manifest.json").write_text(json.dumps({"executable": "x"}))
        old_latest, old_run = B.latest, resources.run
        B.latest = lambda ctx, name: root
        resources.run = lambda cmd, **kw: (seen.append(cmd), type("P", (), {"stdout": "", "returncode": 0})())[1]
        try:
            for target, rom in (("vector_duel", None), ("gameboy", "/somewhere/Cart (World).gb")):
                args = argparse.Namespace(action="run", target=target, frames=10, shot=None, input=None, rom=rom,
                                          save_dir=None, json=False, cards=None, no_project=True, project=None)
                self.assertEqual(A.cmd_arcade(args), 0)
        finally:
            B.latest, resources.run = old_latest, old_run
        for cmd in seen:                        # a game, and a cartridge in a console player
            self.assertIn("--save-dir", cmd)
            self.assertNotIn("Cardmodel Arcade", cmd[cmd.index("--save-dir") + 1])
        self.assertEqual(seen[1][seen[1].index("--rom") + 1], "/somewhere/Cart (World).gb")

    def test_the_launcher_starts_the_service_from_the_main_checkout(self):
        import tempfile
        from pathlib import Path
        from cardmodel.arcade.cli import primary_checkout
        base = Path(tempfile.mkdtemp(prefix="cardmodel_wt_"))
        main, wt = base / "main", base / "main" / ".claude" / "worktrees" / "x"
        (main / ".git" / "worktrees" / "x").mkdir(parents=True)
        (main / "bin").mkdir()
        (main / "bin" / "cardmodel").write_text("#!/bin/sh\n")
        (main / "cardmodel" / "arcade").mkdir(parents=True)
        wt.mkdir(parents=True)
        (wt / ".git").write_text(f"gitdir: {main / '.git' / 'worktrees' / 'x'}\n")
        self.assertEqual(primary_checkout(wt), main)
        self.assertIsNone(primary_checkout(main))


if __name__ == "__main__":
    unittest.main()
