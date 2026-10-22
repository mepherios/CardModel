"""Cardmodel Arcade on iPhone and iPad, without Xcode or a Simulator: a build names a platform card and one of its
targets by a key (``ios-iphonesimulator``), a target overrides the card's sections and says the values its commands
name, builds are kept per platform (``latest`` and ``latest@KEY``), the service lists each platform's builds, a
device on the local network pairs with a code the Mac shows and is let in by its token, and a listed cartridge is
served to it. Nothing here compiles, signs or listens beyond 127.0.0.1 (a device's address is put on the connection
instead); the depots, the devices file and the library are temporary, the cartridge is synthetic (the card
assembler)."""
import argparse
import hashlib
import http.client
import io
import json
import os
import plistlib
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from urllib.parse import parse_qs, unquote

from helpers import model_ctx

from cardmodel.arcade import build as B
from cardmodel.arcade import game as G
from cardmodel.arcade import library as L
from cardmodel.arcade import pairing as P
from cardmodel.arcade import server
from cardmodel.arcade import system as S
from cardmodel.kernel.card import Card
from cardmodel.machine import asm

DEVICE = "192.0.2.7"            # a device on the local network (a documentation address: nothing is sent to it)
UA_SIMULATOR = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Mobile/15E148 CardmodelArcade CardmodelPlatform/ios-iphonesimulator")
ARABIC_INDIC = str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩")


def card_values(plat, target):
    """The values a target's commands name, as target_values gives them but without running anything: the card's
    tools by name, a stand-in for each value a command prints or a probe finds, the literals filled in from those."""
    values = {"exe": "/usr/bin/" + plat["probe"]["name"]}
    values.update({k: "/usr/bin/" + p["name"] for k, p in (plat.get("tools") or {}).items()})
    t = ((plat.get("targets") or {}).get(target) or {}) if target else {}
    literals = {}
    for k, v in (t.get("values") or {}).items():
        if isinstance(v, dict):
            values[k] = f"/stand-in/{k}"
        else:
            literals[k] = v
    for k, v in literals.items():
        values[k] = B._fill(v, values)
    return values


def other_code(code: str) -> str:
    return f"{(int(code) + 1) % 10 ** 6:06d}"


def headers(**kw) -> http.client.HTTPMessage:
    """Request headers as the service's handler has them (User_Agent: User-Agent)."""
    m = http.client.HTTPMessage()
    for k, v in kw.items():
        m[k.replace("_", "-")] = v
    return m


class FromThisMac(server.Handler):
    """The service's handler with this test's context (set on this class, not on server.Handler)."""


class FromTheNetwork(FromThisMac):
    """The same handler for a connection from a device on the local network: the test listens on 127.0.0.1 only
    and puts the device's address on the connection."""

    def __init__(self, request, client_address, srv):
        super().__init__(request, (DEVICE, client_address[1]), srv)


class LocalService(ThreadingHTTPServer):
    """A service on 127.0.0.1 (a free port); a request whose handler raised is recorded here, not printed."""

    def __init__(self, handler):
        super().__init__(("127.0.0.1", 0), handler)
        self.errors: list = []
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def handle_error(self, request, client_address):
        self.errors.append(sys.exc_info()[1])

    def call(self, method: str, path: str, body=None, headers: dict | None = None) -> tuple:
        """(status, headers, body) of one request; a connection the service drops fails the test with what its
        handler raised."""
        data = body if body is None or isinstance(body, bytes) else json.dumps(body).encode()
        h = {"Content-Type": "application/json"} if data else {}
        h.update(headers or {})
        seen = len(self.errors)
        c = http.client.HTTPConnection("127.0.0.1", self.server_address[1], timeout=30)
        try:
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            return r.status, r.headers, r.read()
        except (http.client.RemoteDisconnected, ConnectionError) as exc:
            raise AssertionError(f"{method} {path}: the service dropped the connection ({exc}); its handler raised "
                                 f"{self.errors[seen:]!r}") from None
        finally:
            c.close()

    def stop(self):
        self.shutdown()
        self.server_close()


class Targets(unittest.TestCase):
    """build.py's platform keys, the sections a target overrides and the values its commands name (no tool runs but
    a shell, in the one test with a platform card of its own)."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.store = cls.ctx.store
        cls.game = G.game_card(cls.store, "vector_duel")
        cls.ios = cls.store.get("platform/ios")

    def test_a_key_names_a_platform_card_and_one_of_its_targets(self):
        st, game = self.store, self.game
        plat, target, key = B.resolve_platform(st, game)
        self.assertEqual((plat.name, target, key), ("macos", None, "macos"), "the game's own platform")
        for asked, target in (("ios", "iphonesimulator"), ("ios-iphonesimulator", "iphonesimulator"),
                              ("ios-iphoneos", "iphoneos"), ("ios-maccatalyst", "maccatalyst")):
            plat, got, key = B.resolve_platform(st, game, asked)
            self.assertEqual((plat.name, got, key), ("ios", target, f"ios-{target}"), asked)
        for asked, why in (("ios-watchos", "platform/ios has no target watchos"),
                           ("macos-arm64", "platform/macos has no targets"),
                           ("android", "no platform card platform/android")):
            with self.assertRaisesRegex(B.BuildError, why):
                B.resolve_platform(st, game, asked)
        self.assertEqual(B.home_key(st, game), "macos")
        self.assertEqual(B.home_key(st, S.system_card(st, "gameboy")), "macos")
        self.assertIsNone(B.platform_arg(st, game, None))
        self.assertIsNone(B.platform_arg(st, game, "macos"), "the game's own platform keeps the pointer latest")
        self.assertEqual(B.platform_arg(st, game, "ios"), "ios-iphonesimulator")
        self.assertEqual(B.platform_arg(st, game, "ios-iphoneos"), "ios-iphoneos")
        app = st.get("app/arcade_ios")              # a card whose own platform is iOS: there macOS is the other one
        self.assertEqual(B.home_key(st, app), "ios-iphonesimulator")
        self.assertIsNone(B.platform_arg(st, app, "ios"))
        self.assertEqual(B.platform_arg(st, app, "macos"), "macos")

    def test_a_target_overrides_sections_and_null_drops_a_key(self):
        ios = self.ios
        self.assertEqual(B.section(ios, "iphonesimulator", "bundle"), ios["bundle"], "no bundle of its own")
        self.assertEqual(B.section(ios, None, "bundle"), ios["bundle"])
        cat = B.section(ios, "maccatalyst", "bundle")
        self.assertEqual((cat["executable_dir"], cat["frameworks_dir"], cat["resources_dir"], cat["plist"]),
                         ("Contents/MacOS", "Contents/Frameworks", "Contents/Resources", "Contents/Info.plist"))
        self.assertEqual((cat["spec_file"], cat["suffix"]), (ios["bundle"]["spec_file"], ios["bundle"]["suffix"]))
        plist = cat["info_plist"]
        for gone in ("MinimumOSVersion", "LSRequiresIPhoneOS", "CFBundleIcons", "CFBundleIcons~ipad",
                     "UIRequiredDeviceCapabilities"):
            self.assertNotIn(gone, plist)
            self.assertIn(gone, ios["bundle"]["info_plist"], "the card itself is not changed")
        self.assertEqual(plist["UIDeviceFamily"], [2], "a list is replaced, not merged")
        self.assertEqual(plist["LSMinimumSystemVersion"], "13.0")
        self.assertEqual(plist["CFBundleIdentifier"], ios["bundle"]["info_plist"]["CFBundleIdentifier"])
        icon = B.section(ios, "maccatalyst", "icon")
        self.assertNotIn("files", icon)
        self.assertTrue(icon["compile"] and icon["sizes"] and icon["probe"])
        self.assertIn("files", ios["icon"])
        self.assertEqual(B.section(ios, "iphonesimulator", "icon"), ios["icon"])
        self.assertIsNone(B.section(ios, "iphonesimulator", "no_such_section"))

    def test_every_target_fills_its_commands_and_info_plist(self):
        """Every placeholder in the cards' commands and Info.plist is a value the target names or one the build
        adds; a list value ({swift_flags}, {srcs}) is spliced as arguments; no null is left for the plist."""
        mac, ios = self.store.get("platform/macos"), self.ios
        app = self.store.get("app/arcade_ios")
        for plat, target in [(mac, None)] + [(ios, t) for t in ios["targets"]]:
            with self.subTest(platform=plat.name, target=target):
                vals = card_values(plat, target)
                sh = B.section(plat, target, "effect_shell")
                srcs = [str(plat.path / s) for s in sh["sources"]]
                self.assertTrue(all(Path(s).is_file() for s in srcs))
                self.assertLessEqual(set(sh.get("shared") or []), set(sh["sources"]))
                cmds = [B._args(sh["compile"], {**vals, "out": "/out/shell", "srcs": srcs})]
                for s in srcs:
                    self.assertEqual(cmds[0].count(s), 1, "each source one argument")
                flags = (B.section(plat, target, "library") or {}).get("flags")
                if flags:
                    cmds.append(B._args(flags, vals))
                sign = B.section(plat, target, "sign")
                if sign:
                    cmds.append(B._args(sign["args"], {**vals, "path": "/out/Vector Duel.app"}))
                for cmd in cmds:
                    self.assertEqual([a for a in cmd if "{" in a or "[" in a], [], cmd)
                if vals.get("swift_flags"):
                    i = cmds[0].index(vals["swift_flags"][0])
                    self.assertEqual(cmds[0][i:i + len(vals["swift_flags"])], vals["swift_flags"])
                    self.assertTrue(all("{" not in f for f in vals["swift_flags"]))
                names = {**vals, "title": "Vector Duel", "id": "vector_duel", "ident": "vector-duel",
                         "version": "0.4.0", "build": "0123456789ab"}
                bundle = B.section(plat, target, "bundle")
                plist = B._fill(bundle["info_plist"], names)
                self.assertNotIn(b"{", plistlib.dumps(plist))
                self.assertEqual(plist["CFBundleExecutable"], "Vector Duel")
                if target:
                    self.assertEqual(plist["CFBundleIdentifier"], "org.cardmodel.arcade.vector-duel")
                    self.assertEqual(plist["CFBundleSupportedPlatforms"], [vals["platform_name"]])
                    # ios.py: the launcher's own keys over the bundle's
                    own = B._fill(B._merge(bundle["info_plist"], app["info_plist"]),
                                  {**names, "identifier": app["identifier"], "service": "http://127.0.0.1:8770"})
                    self.assertNotIn(b"{", plistlib.dumps(own))
                    self.assertEqual((own["CFBundleIdentifier"], own["CardmodelService"]),
                                     (app["identifier"], "http://127.0.0.1:8770"))

    def test_a_list_value_is_spliced_and_fill_goes_all_the_way_down(self):
        vals = {"exe": "/usr/bin/xcrun", "sdk": "/SDK", "swift_flags": ["-Fsystem", "/SDK/F"], "none": [],
                "srcs": ["a.swift", "b c.swift"], "out": "/o"}
        self.assertEqual(B._args(["{exe}", "-sdk", "{sdk}", "{swift_flags}", "{none}", "-o", "{out}", "{srcs}"], vals),
                         ["/usr/bin/xcrun", "-sdk", "/SDK", "-Fsystem", "/SDK/F", "-o", "/o", "a.swift", "b c.swift"])
        self.assertEqual(B._args(["-isysroot={sdk}"], vals), ["-isysroot=/SDK"])
        self.assertEqual(B._fill({"a": "{sdk}/x", "b": ["{exe}", {"c": "{out}", "n": 2}], "t": True, "f": 1.5}, vals),
                         {"a": "/SDK/x", "b": ["/usr/bin/xcrun", {"c": "/o", "n": 2}], "t": True, "f": 1.5})
        base = {"a": {"b": 1, "c": 2}, "d": [1, 2], "e": 3}
        self.assertEqual(B._merge(base, {"a": {"c": None, "x": 4}, "d": [9], "e": None}), {"a": {"b": 1, "x": 4},
                                                                                          "d": [9]})
        self.assertEqual(base, {"a": {"b": 1, "c": 2}, "d": [1, 2], "e": 3}, "the base is not changed")
        self.assertEqual(B.ident("vector_duel"), "vector-duel")
        self.assertEqual(B.ident("gameboy_player"), "gameboy-player")
        self.assertEqual(B.ident("a.b-c_d e/f"), "a.b-c-d-e-f")

    def test_target_values_come_from_literals_commands_and_probes(self):
        """A platform card of the test's own (its tool is the shell): a value a command prints (run in the target's
        environment), one a probe finds, literals filled from them; a value that cannot be had says what the target
        needs."""
        d = Path(tempfile.mkdtemp(prefix="cardmodel_platform_"))
        plat = Card({
            "name": "cardmodel-test-platform", "category": "platform",
            "probe": {"kind": "executable", "name": "sh"},
            "tools": {"shell": {"kind": "executable", "name": "sh"}},
            "targets": {
                "here": {"needs": "a shell",
                         "env": {"CARDMODEL_TEST_PLATFORM_DIR": {"probe": {"kind": "path_exists", "path": str(d)}}},
                         "values": {"printed": {"run": ["{exe}", "-c", "echo printed:$CARDMODEL_TEST_PLATFORM_DIR"]},
                                    "found": {"probe": {"kind": "env", "var": "CARDMODEL_TEST_PLATFORM_VALUE"}},
                                    "literal": "-",
                                    "flags": ["-I", "{printed}/include", "{literal}"]}},
                "unset": {"needs": "a value nobody set",
                          "values": {"x": {"probe": {"kind": "env", "var": "CARDMODEL_TEST_PLATFORM_NEVER_SET"}}}},
                "failing": {"needs": "a command that works",
                            "values": {"x": {"run": ["{exe}", "-c", "echo broken >&2; exit 3"]}}}}},
            path=d, registry="platform")
        try:
            with mock.patch.dict(os.environ, {"CARDMODEL_TEST_PLATFORM_VALUE": "found-it"}):
                values, env = B.target_values(plat, "here")
            self.assertTrue(values["exe"].endswith("sh"))
            self.assertEqual(values["shell"], values["exe"])
            self.assertEqual(env["CARDMODEL_TEST_PLATFORM_DIR"], str(d))
            self.assertEqual(values["printed"], f"printed:{d}", "the command ran in the target's environment")
            self.assertEqual((values["found"], values["literal"]), ("found-it", "-"))
            self.assertEqual(values["flags"], ["-I", f"printed:{d}/include", "-"])
            with self.assertRaisesRegex(B.BuildError, r"unset: needs a value nobody set"):
                B.target_values(plat, "unset")
            with self.assertRaisesRegex(B.BuildError, r"failing: needs a command that works .*broken"):
                B.target_values(plat, "failing")
        finally:
            for k in [k for k in B._RESOLVED if k[0] == plat.name]:
                B._RESOLVED.pop(k)
            shutil.rmtree(d, ignore_errors=True)

    def test_an_ios_icon_is_png_files_of_the_sizes_the_card_names(self):
        d = Path(tempfile.mkdtemp(prefix="cardmodel_icon_"))
        try:
            app = d / "Vector Duel.app"
            app.mkdir()
            bundle = B.section(self.ios, "iphonesimulator", "bundle")
            B.icon(self.ctx, self.ios, "iphonesimulator", bytes([40, 160, 220, 255]) * (128 * 128), d, app, bundle)
            sizes = {p.name: struct.unpack(">II", p.read_bytes()[16:24]) for p in app.iterdir()}
            self.assertEqual(sizes, {f: (n, n) for f, n in self.ios["icon"]["files"].items()})
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_the_source_hash_names_the_platform(self):
        """A build is due per platform: the same game's sources hash differently for macOS and for each iOS target
        (cheap: the cards and files, no compile)."""
        ctx, game = self.ctx, self.game
        mac = B.source_hash(ctx, game)
        self.assertEqual(B.source_hash(ctx, game, "macos"), mac, "the game's own platform, named or not")
        ios = {t: B.source_hash(ctx, game, f"ios-{t}") for t in ("iphonesimulator", "iphoneos", "maccatalyst")}
        self.assertEqual(B.source_hash(ctx, game, "ios"), ios["iphonesimulator"], "ios is its default target")
        self.assertEqual(len({mac, *ios.values()}), 4)
        gb = S.system_card(self.store, "gameboy")
        self.assertEqual(len({S.source_hash(ctx, gb), S.source_hash(ctx, gb, "ios-iphonesimulator"),
                              S.source_hash(ctx, gb, "ios-iphoneos")}), 3, "a console player's too")


class Depots(unittest.TestCase):
    """A build is kept per platform: the game's own platform's pointer is ``latest``, another's ``latest@KEY``; the
    service reads each, and a package is laid out as its target says (temporary depots)."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.card = G.game_card(cls.ctx.store, "vector_duel")

    def setUp(self):
        self.old_root = B.ROOT_OVERRIDE
        B.ROOT_OVERRIDE = Path(tempfile.mkdtemp(prefix="cardmodel_arcade_"))      # not the live depots

    def tearDown(self):
        shutil.rmtree(B.ROOT_OVERRIDE, ignore_errors=True)
        B.ROOT_OVERRIDE = self.old_root

    def depot(self, build: str, key: str | None, source: str) -> Path:
        """A build of vector_duel for key (None: its own platform): its folder and manifest (no files), the pointer."""
        root = B.arcade_root(self.ctx) / "depots" / "vector_duel" / f"0.4.0+{build}"
        root.mkdir(parents=True)
        man = {"id": "vector_duel", "title": "Vector Duel", "version": "0.4.0", "build": build, "source": source,
               "platform": key or "macos", "app": "Vector Duel.app", "executable": "Vector Duel.app/Vector Duel",
               "created": "2026-10-22T12:00:00+0200", "seconds": 1.0, "media": ["icon.png"],
               "save": {"dir": "saves/vector_duel", "file": "save.bin"}, "files": [], "size": 0, "chunks": 0}
        (root / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
        B.pointer(self.ctx, "vector_duel", key).write_text(root.name, encoding="utf-8")
        return root

    def test_each_platform_has_its_own_pointer(self):
        ctx = self.ctx
        here = B.arcade_root(ctx) / "depots" / "vector_duel"
        self.assertEqual(B.pointer(ctx, "vector_duel"), here / "latest")
        self.assertEqual(B.pointer(ctx, "vector_duel", "ios-iphonesimulator"), here / "latest@ios-iphonesimulator")
        self.assertIsNone(B.latest(ctx, "vector_duel"))
        mac = self.depot("aaaaaaaaaaaa", None, "macOS sources")
        self.assertIsNone(B.latest(ctx, "vector_duel", "ios-iphonesimulator"), "a macOS build is no iOS one")
        sim = self.depot("bbbbbbbbbbbb", "ios-iphonesimulator", "iOS sources")
        self.assertEqual(B.latest(ctx, "vector_duel"), mac)
        self.assertEqual(B.latest(ctx, "vector_duel", "ios-iphonesimulator"), sim)
        self.assertIsNone(B.latest(ctx, "vector_duel", "ios-iphoneos"))
        B.pointer(ctx, "vector_duel", "ios-iphoneos").write_text("0.4.0+removed", encoding="utf-8")
        self.assertIsNone(B.latest(ctx, "vector_duel", "ios-iphoneos"), "a pointer to a build that is gone")

    def test_the_service_reads_each_platforms_build(self):
        ctx, card = self.ctx, self.card
        self.depot("aaaaaaaaaaaa", None, "older sources")
        self.depot("bbbbbbbbbbbb", "ios-iphonesimulator", B.source_hash(ctx, card, "ios-iphonesimulator"))
        sim = server.game_entry(ctx, card, platform="ios")
        self.assertEqual((sim["platform"], sim["build"]["build"], sim["build_due"]),
                         ("ios-iphonesimulator", "bbbbbbbbbbbb", False))
        self.assertEqual(sim["build"]["manifest"], "/depot/vector_duel/0.4.0+bbbbbbbbbbbb/manifest.json")
        self.assertEqual(sim["media"], {"icon": "/media/vector_duel/0.4.0+bbbbbbbbbbbb/icon.png"})
        mac = server.game_entry(ctx, card)
        self.assertEqual((mac["platform"], mac["build"]["build"], mac["build_due"]), ("macos", "aaaaaaaaaaaa", True))
        cat = server.game_entry(ctx, card, platform="ios-maccatalyst")
        self.assertEqual((cat["platform"], cat["build"], cat["build_due"]), ("ios-maccatalyst", None, True))

    def test_a_package_is_laid_out_as_its_target_says(self):
        """pack (a build's last two steps) for the Simulator and Mac Catalyst, with stand-ins for the compiled
        library and shell, the values the target's tools would give, the icon compiler and the signing: the bundle
        is in the target's layout, the manifest names the platform, and only that platform's pointer moves."""
        ctx, card, ios = self.ctx, self.card, self.ctx.store.get("platform/ios")
        inputs = B.arcade_root(ctx) / "inputs"
        inputs.mkdir(parents=True)
        signed = []

        def icns(ctx, plat, rgba, d, target=None):
            (d / "AppIcon.icns").write_bytes(b"icns")
            return d / "AppIcon.icns"

        rgba = bytes([40, 160, 220, 255]) * (128 * 128)
        info = {}
        with mock.patch.object(B, "target_values", lambda plat, target: (card_values(plat, target), {})), \
                mock.patch.object(B, "sign", lambda plat, target, paths: signed.append((target, list(paths)))), \
                mock.patch.object(B, "icns", icns):
            for key in ("ios", "ios-maccatalyst"):
                lib, exe = inputs / f"{key}.dylib", inputs / f"{key}-shell"
                lib.write_bytes(f"library for {key}".encode())
                exe.write_bytes(f"shell for {key}".encode())
                info[key] = B.pack(ctx, "vector_duel", card, key, lib, exe, {"id": "vector_duel"},
                                   {"_icon_rgba": rgba, "icon.png": b"png"}, lambda *a: None, time.time(),
                                   source=f"sources for {key}", save={"file": "save.bin"})
        sim, cat = info["ios"], info["ios-maccatalyst"]
        self.assertIsNone(B.latest(ctx, "vector_duel"), "the game's own pointer did not move")
        self.assertEqual(B.latest(ctx, "vector_duel", "ios-iphonesimulator").name, f"0.4.0+{sim['build']}")
        self.assertEqual(B.latest(ctx, "vector_duel", "ios-maccatalyst").name, f"0.4.0+{cat['build']}")
        self.assertEqual([(t, [p.name for p in ps]) for t, ps in signed],
                         [(t, ["game.dylib", "Vector Duel.app"]) for t in ("iphonesimulator", "maccatalyst")],
                         "the inner code signed first, then the app")

        app = B.latest(ctx, "vector_duel", "ios-iphonesimulator") / "content" / "Vector Duel.app"
        self.assertEqual((sim["platform"], sim["app"], sim["executable"]),
                         ("ios-iphonesimulator", "Vector Duel.app", "Vector Duel.app/Vector Duel"))
        self.assertTrue(os.access(app / "Vector Duel", os.X_OK))
        self.assertEqual((app / "Frameworks" / "game.dylib").read_bytes(), b"library for ios")
        self.assertEqual(json.loads((app / "game.json").read_text()), {"id": "vector_duel"})
        plist = plistlib.loads((app / "Info.plist").read_bytes())
        self.assertEqual((plist["CFBundleExecutable"], plist["CFBundleIdentifier"], plist["CFBundleVersion"],
                          plist["MinimumOSVersion"]), ("Vector Duel", "org.cardmodel.arcade.vector-duel", sim["build"],
                                                       "16.0"))
        self.assertEqual(sorted(p.name for p in app.glob("AppIcon*")), sorted(ios["icon"]["files"]))
        self.assertEqual(sim["save"], {"dir": ios["saves"].format(id="vector_duel"), "file": "save.bin"})
        self.assertIn("Vector Duel.app/Info.plist", {f["path"] for f in sim["files"]})

        app = B.latest(ctx, "vector_duel", "ios-maccatalyst") / "content" / "Vector Duel.app"
        self.assertEqual((cat["platform"], cat["executable"]),
                         ("ios-maccatalyst", "Vector Duel.app/Contents/MacOS/Vector Duel"))
        self.assertTrue(os.access(app / "Contents" / "MacOS" / "Vector Duel", os.X_OK))
        self.assertEqual((app / "Contents" / "Frameworks" / "game.dylib").read_bytes(), b"library for ios-maccatalyst")
        self.assertEqual((app / "Contents" / "Resources" / "AppIcon.icns").read_bytes(), b"icns")
        self.assertTrue((app / "Contents" / "Resources" / "game.json").is_file())
        plist = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        self.assertNotIn("MinimumOSVersion", plist)
        self.assertEqual((plist["LSMinimumSystemVersion"], plist["UIDeviceFamily"]), ("13.0", [2]))
        self.assertEqual(list(app.rglob("AppIcon60x60*")), [], "no iPhone icon files on the Mac")
        self.assertIn("Vector Duel.app/Contents/Info.plist", {f["path"] for f in cat["files"]})


class Pairing(unittest.TestCase):
    """pairing.py: a code good for ten minutes and five tries, a token kept as its SHA-256 only, the gate (a
    temporary devices file)."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()

    def setUp(self):
        self.old = P.DEVICES_OVERRIDE
        self.dir = Path(tempfile.mkdtemp(prefix="cardmodel_devices_"))
        P.DEVICES_OVERRIDE = self.dir / "devices.json"
        P._code.clear()

    def tearDown(self):
        P._code.clear()
        P.DEVICES_OVERRIDE = self.old
        shutil.rmtree(self.dir, ignore_errors=True)

    def names(self) -> list[str]:
        return sorted(x["name"] for x in P.load(self.ctx)["devices"])

    def test_a_code_pairs_one_device_once(self):
        self.assertEqual((P.CODE_TTL_S, P.CODE_TRIES), (600, 5), "ten minutes and five tries, as the Mac says")
        got = P.new_code(self.ctx)
        code = got["code"]
        self.assertRegex(code, r"^[0-9]{6}$")
        self.assertAlmostEqual(got["expires"] - time.time(), P.CODE_TTL_S, delta=5)
        self.assertFalse(P.load(self.ctx)["lan"], "a code alone does not keep the network listener on")
        self.assertIsNone(P.pair(self.ctx, other_code(code), "Test iPhone"))
        token = P.pair(self.ctx, f" {code} ", "Test iPhone")
        self.assertTrue(P.load(self.ctx)["lan"], "a paired device keeps it on")
        self.assertRegex(token, r"^[0-9a-f]{64}$")
        self.assertIsNone(P.pair(self.ctx, code, "Another iPhone"), "a code pairs once")
        self.assertEqual(self.names(), ["Test iPhone"])

    def test_five_wrong_tries_void_the_code(self):
        code = P.new_code(self.ctx)["code"]
        for _ in range(P.CODE_TRIES - 1):
            self.assertIsNone(P.pair(self.ctx, other_code(code), "Test iPhone"))
        self.assertIsNotNone(P.pair(self.ctx, code, "Test iPhone"), "the fifth try may still be the right one")
        code = P.new_code(self.ctx)["code"]
        for _ in range(P.CODE_TRIES):
            self.assertIsNone(P.pair(self.ctx, other_code(code), "Test iPad"))
        self.assertIsNone(P.pair(self.ctx, code, "Test iPad"), "after five wrong tries the right code is void")
        self.assertEqual(self.names(), ["Test iPhone"])

    def test_a_code_lasts_ten_minutes_and_a_new_one_voids_it(self):
        got = P.new_code(self.ctx)
        with mock.patch.object(P, "time", SimpleNamespace(time=lambda: got["expires"] + 1)):
            self.assertIsNone(P.pair(self.ctx, got["code"], "Test iPhone"))
        self.assertIsNone(P.pair(self.ctx, got["code"], "Test iPhone"), "an expired code is gone")
        got = P.new_code(self.ctx)
        with mock.patch.object(P, "time", SimpleNamespace(time=lambda: got["expires"] - 1)):
            self.assertIsNotNone(P.pair(self.ctx, got["code"], "Test iPhone"), "a second before it expires")
        first = P.new_code(self.ctx)["code"]
        second = P.new_code(self.ctx)["code"]
        if first != second:                     # one time in a million they are the same six digits
            self.assertIsNone(P.pair(self.ctx, first, "Test iPad"), "a new code voids the last")
        self.assertIsNotNone(P.pair(self.ctx, second, "Test iPad"))

    def test_the_devices_file_keeps_only_each_tokens_hash(self):
        token = P.pair(self.ctx, P.new_code(self.ctx)["code"], "  Test iPhone  ")
        text = P.DEVICES_OVERRIDE.read_text(encoding="utf-8")
        self.assertNotIn(token, text)
        sha = hashlib.sha256(token.encode()).hexdigest()
        self.assertEqual([(x["name"], x["sha256"]) for x in json.loads(text)["devices"]], [("Test iPhone", sha)])
        self.assertEqual(P.device(self.ctx, token), "Test iPhone")
        self.assertIsNone(P.device(self.ctx, token[:-1] + ("1" if token[-1] == "0" else "0")))
        self.assertIsNone(P.device(self.ctx, sha), "the hash in the file is no token")
        self.assertIsNone(P.device(self.ctx, ""))
        self.assertTrue(P.forget(self.ctx, "Test iPhone"))
        self.assertIsNone(P.device(self.ctx, token))
        self.assertFalse(P.forget(self.ctx, "Test iPhone"))

    def test_pairing_a_name_again_replaces_its_token(self):
        old = P.pair(self.ctx, P.new_code(self.ctx)["code"], "Test iPad")
        phone = P.pair(self.ctx, P.new_code(self.ctx)["code"], "Test iPhone")
        new = P.pair(self.ctx, P.new_code(self.ctx)["code"], "Test iPad")
        self.assertEqual((P.device(self.ctx, old), P.device(self.ctx, new), P.device(self.ctx, phone)),
                         (None, "Test iPad", "Test iPhone"))
        self.assertEqual(self.names(), ["Test iPad", "Test iPhone"])
        self.assertEqual(P.device(self.ctx, P.pair(self.ctx, P.new_code(self.ctx)["code"], "   ")), "device")
        self.assertEqual(P.device(self.ctx, P.pair(self.ctx, P.new_code(self.ctx)["code"], "x" * 100)), "x" * 60)

    def test_a_token_comes_as_a_bearer_header_or_the_cookie(self):
        self.assertEqual(P.COOKIE, "cardmodel_device", "the cookie the iOS launcher sets for its pages")
        self.assertEqual(P.token_of(headers(Authorization="Bearer abc123 ")), "abc123")
        self.assertEqual(P.token_of(headers(Cookie=f"theme=dark; {P.COOKIE}=def456; other=1")), "def456")
        self.assertEqual(P.token_of(headers(Authorization="Bearer abc", Cookie=f"{P.COOKIE}=def")), "abc")
        self.assertEqual(P.token_of(headers(Authorization="Basic dXNlcjpwYXNz", Cookie=f"{P.COOKIE}=def")), "def")
        self.assertEqual(P.token_of(headers(Cookie=f"x{P.COOKIE}=no")), "")
        self.assertEqual(P.token_of(headers()), "")

    def test_the_gate(self):
        """This Mac always; a device on the network for the status and the pairing itself, else with a token and only
        for what the launcher on a device needs."""
        token = P.pair(self.ctx, P.new_code(self.ctx)["code"], "Test iPad")
        none = headers()
        good = [headers(Authorization=f"Bearer {token}"), headers(Cookie=f"{P.COOKIE}={token}")]
        bad = [headers(Authorization="Bearer " + "0" * 64),
               headers(Authorization="Bearer " + hashlib.sha256(token.encode()).hexdigest())]
        for mac in P.LOOPBACK:
            self.assertTrue(P.allowed(self.ctx, mac, "GET", ["api", "catalog"], none), mac)
            self.assertTrue(P.allowed(self.ctx, mac, "POST", ["api", "pair", "code"], none), mac)
        self.assertTrue(P.allowed(self.ctx, DEVICE, "GET", ["api", "status"], none))
        self.assertTrue(P.allowed(self.ctx, DEVICE, "POST", ["api", "pair"], none))
        for method, parts in (("GET", ["api", "catalog"]), ("GET", ["api", "pair"]),
                              ("GET", ["api", "cartridge", "rom-0123456789abcdef"]), ("GET", ["api", "library"]),
                              ("POST", ["api", "build", "vector_duel"]), ("GET", ["chunk", "0" * 64]), ("GET", []),
                              ("GET", ["ui", "index.html"]), ("POST", ["api", "library", "scan"])):
            self.assertFalse(P.allowed(self.ctx, DEVICE, method, parts, none), (method, parts))
            for h in bad:
                self.assertFalse(P.allowed(self.ctx, DEVICE, method, parts, h), (method, parts))
            for h in good:
                self.assertTrue(P.allowed(self.ctx, DEVICE, method, parts, h), (method, parts))
        # a token opens only what the launcher on a device needs: the work in progress, other branches' builds, the
        # Mac's folders and pairing codes stay on the Mac
        for method, parts, q in (("GET", ["api", "work"], {}), ("GET", ["api", "dev"], {}), ("GET", ["api", "events"], {}),
                                 ("POST", ["api", "status"], {}), ("POST", ["api", "pair", "code"], {}),
                                 ("POST", ["api", "library", "folders"], {}),
                                 ("POST", ["api", "build", "vector_duel"], {"branch": ["x"]}),
                                 ("GET", ["depot", "vector_duel", "1+a", "manifest.json"], {"wt": ["x"]})):
            for h in good:
                self.assertFalse(P.allowed(self.ctx, DEVICE, method, parts, h, q), (method, parts, q))
        P.forget(self.ctx, "Test iPad")
        self.assertFalse(P.allowed(self.ctx, DEVICE, "GET", ["api", "catalog"], good[0]), "a forgotten device")

    # -- what a device may send ---------------------------------------------------------------------------------------
    def test_the_code_as_the_mac_shows_it_pairs(self):
        """`cardmodel arcade pair` shows the code in two groups ("123 456"); typed or pasted that way on the device
        (an iPad's keyboard has a space bar, Universal Clipboard pastes the Mac's text) it is the same code."""
        code = P.new_code(self.ctx)["code"]
        self.assertIsNotNone(P.pair(self.ctx, f"{code[:3]} {code[3:]}", "Test iPad"))

    def test_a_code_in_other_digits_is_answered(self):
        """A number pad in another script types other digits (Arabic-Indic, in an Arabic region): such a code pairs
        or is refused like a wrong one; it never raises (the service would drop the connection)."""
        code = P.new_code(self.ctx)["code"]
        try:
            token = P.pair(self.ctx, code.translate(ARABIC_INDIC), "Test iPhone")
        except Exception as exc:  # noqa: BLE001 -- what the device would see is a dropped connection
            self.fail(f"pair raised {type(exc).__name__}: {exc}")
        if token is None:
            self.assertIsNotNone(P.pair(self.ctx, code, "Test iPhone"), "refused like a wrong code: it still works")

    def test_parallel_requests_after_a_quiet_spell_all_know_the_device(self):
        """A device's page asks for many things at once. When the device was last seen over five minutes ago each
        of those lookups records the time (devices.json is saved): every one of them still finds the device (a
        lookup that does not is a 401 for a paired device; one that raises, a dropped connection)."""
        token = P.pair(self.ctx, P.new_code(self.ctx)["code"], "Test iPad")
        failures = []

        def look(start):
            try:
                start.wait(timeout=30)
                if P.device(self.ctx, token) != "Test iPad":
                    failures.append("not found")
            except Exception as exc:  # noqa: BLE001
                failures.append(type(exc).__name__)

        for _ in range(20):
            d = json.loads(P.DEVICES_OVERRIDE.read_text(encoding="utf-8"))
            d["devices"][0]["seen"] = 0                         # five minutes and more without a request
            P.DEVICES_OVERRIDE.write_text(json.dumps(d), encoding="utf-8")
            start = threading.Barrier(8)
            threads = [threading.Thread(target=look, args=(start,)) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(dict(Counter(failures)), {}, "failed lookups of 160")


class Service(unittest.TestCase):
    """The service as this Mac and as a device on the local network reach it (two services on 127.0.0.1, one of
    them putting a device's address on its connections): the gate, pairing over HTTP, the catalog for another
    platform, a cartridge for a device, `cardmodel arcade pair`. listen_lan and the addresses are stand-ins (no
    socket beyond 127.0.0.1); the library draws no pictures."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.tmp = Path(tempfile.mkdtemp(prefix="cardmodel_ios_service_"))
        old = (B.ROOT_OVERRIDE, P.DEVICES_OVERRIDE, L.SETTINGS_OVERRIDE)

        def restore():
            B.ROOT_OVERRIDE, P.DEVICES_OVERRIDE, L.SETTINGS_OVERRIDE = old
            P._code.clear()
            L.scan(cls.ctx, force=True)
            shutil.rmtree(cls.tmp, ignore_errors=True)

        cls.addClassCleanup(restore)
        B.ROOT_OVERRIDE = cls.tmp / "arcade"                    # no build here: every build is due
        P.DEVICES_OVERRIDE = cls.tmp / "devices.json"
        L.SETTINGS_OVERRIDE = cls.tmp / "library" / "library.json"
        cls.lan_ports = []
        for obj, name, new in ((server, "listen_lan", lambda ctx, port: cls.lan_ports.append(port) or True),
                               (P, "addresses", lambda port: [f"this-mac.local:{port}"]),
                               (L, "start_drawing", lambda ctx: None)):
            p = mock.patch.object(obj, name, new)
            p.start()
            cls.addClassCleanup(p.stop)
        gb = cls.tmp / "library" / "gb"
        gb.mkdir(parents=True)
        cls.rom = asm.rom(cls.ctx.store, [("label", "end"), ("HALT",), ("JR e", "end")], title="PAIRTEST")
        cls.rom_file = gb / "Pair Test (World).gb"
        cls.rom_file.write_bytes(cls.rom)
        cls.rom_id = "rom-" + hashlib.sha1(cls.rom).hexdigest()[:16]
        L.set_folder(cls.ctx, "gameboy", add=str(gb))
        FromThisMac.ctx, FromThisMac.ui_dir = cls.ctx, None
        cls.mac, cls.lan = LocalService(FromThisMac), LocalService(FromTheNetwork)
        cls.addClassCleanup(cls.mac.stop)
        cls.addClassCleanup(cls.lan.stop)

    def setUp(self):
        P._code.clear()
        P.DEVICES_OVERRIDE.unlink(missing_ok=True)
        self.lan_ports.clear()

    def test_this_mac_is_let_in_and_shows_a_pairing_code(self):
        port = self.mac.server_address[1]
        self.assertEqual(self.mac.call("GET", "/api/status")[0], 200)
        self.assertEqual(json.loads(self.mac.call("GET", "/api/pair")[2]), {"device": "this Mac"})
        status, _, body = self.mac.call("POST", "/api/pair/code")
        self.assertEqual(status, 200, body)
        got = json.loads(body)
        self.assertRegex(got["code"], r"^[0-9]{6}$")
        self.assertEqual(got["addresses"], [f"this-mac.local:{port}"])
        self.assertEqual(self.lan_ports, [port], "a code starts the network listener (a stand-in here)")
        self.assertFalse(P.load(self.ctx)["lan"], "it stays on across restarts only once a device pairs")
        status, _, body = self.mac.call("POST", "/api/pair/code", headers={"Origin": f"http://localhost:{port}"})
        self.assertEqual(status, 200, "a page this service serves may ask")
        code = json.loads(body)["code"]
        for origin in ("http://evil.example", "http://127.0.0.1:1", "null"):
            self.assertEqual(self.mac.call("POST", "/api/pair/code", headers={"Origin": origin})[0], 403, origin)
        self.assertEqual(P._code["code"], code, "a refused request makes no new code")
        self.assertEqual(len(self.lan_ports), 2)

    def test_a_device_pairs_over_the_network_and_then_gets_in(self):
        code = json.loads(self.mac.call("POST", "/api/pair/code")[2])["code"]
        self.assertEqual(self.lan.call("GET", "/api/status")[0], 200, "open: a device looks for the service")
        for method, path in (("GET", "/api/catalog"), ("GET", "/api/pair"), ("GET", "/api/library"),
                             ("GET", f"/api/cartridge/{self.rom_id}"), ("POST", "/api/library/scan"),
                             ("POST", "/api/build/vector_duel"), ("GET", "/ui/index.html")):
            self.assertEqual(self.lan.call(method, path)[0], 401, path)
        self.assertEqual(self.lan.call("POST", "/api/pair", {"code": other_code(code), "name": "Test iPad"})[0], 403)
        status, _, body = self.lan.call("POST", "/api/pair", {"code": code, "name": "Test iPad"})
        self.assertEqual(status, 200, body)
        token = json.loads(body)["token"]
        bearer = {"Authorization": f"Bearer {token}"}
        for h in (bearer, {"Cookie": f"{P.COOKIE}={token}"}):
            status, _, body = self.lan.call("GET", "/api/pair", headers=h)
            self.assertEqual((status, json.loads(body)), (200, {"device": "Test iPad"}))
        status, _, data = self.lan.call("GET", f"/api/cartridge/{self.rom_id}", headers=bearer)
        self.assertEqual((status, data), (200, self.rom))
        self.assertEqual(json.loads(self.lan.call("POST", "/api/library/scan", headers=bearer)[2]), {"roms": 1})
        # what stays the Mac's: its pairing codes and its cartridge folders
        self.assertEqual(self.lan.call("POST", "/api/pair/code", headers=bearer)[0], 403)
        self.assertEqual(self.lan.call("POST", "/api/library/folders", {"system": "gameboy", "add": "/"},
                                       headers=bearer)[0], 403)
        self.assertEqual(L.load_settings(self.ctx)["folders"]["gameboy"], [str(self.rom_file.parent)])
        P.forget(self.ctx, "Test iPad")
        self.assertEqual(self.lan.call("GET", "/api/pair", headers=bearer)[0], 401, "a forgotten device")

    def test_a_malformed_pairing_request_is_answered(self):
        """POST /api/pair is open to any device on the network: a body that is no code (other digits, JSON that is
        not an object) is answered (refused like a wrong code), never with a dropped connection."""
        code = json.loads(self.mac.call("POST", "/api/pair/code")[2])["code"]
        for what, body, ok in (("a code in Arabic-Indic digits", {"code": code.translate(ARABIC_INDIC), "name": "x"},
                                (200, 403)),
                               ("a JSON list", [code], (400, 403)),
                               ("a JSON string", code, (400, 403)),
                               ("a JSON number", int(code), (400, 403))):
            with self.subTest(what):
                self.assertIn(self.lan.call("POST", "/api/pair", json.dumps(body).encode())[0], ok)

    def test_a_client_names_its_platform_by_query_or_user_agent(self):
        def asked(query="", ua=None):
            return server.requested_platform(SimpleNamespace(headers=headers(User_Agent=ua) if ua else headers()),
                                             parse_qs(query))
        self.assertEqual(asked("platform=ios"), "ios")
        self.assertEqual(asked(ua=UA_SIMULATOR), "ios-iphonesimulator")
        self.assertEqual(asked("platform=ios-maccatalyst", UA_SIMULATOR), "ios-maccatalyst", "the query first")
        self.assertEqual(asked("platform=", UA_SIMULATOR), "ios-iphonesimulator")
        self.assertIsNone(asked(ua="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15"))
        self.assertIsNone(asked())
        self.assertEqual(server.build_key("vector_duel", None), "vector_duel")
        self.assertEqual(server.build_key("vector_duel", "ios-iphoneos"), "vector_duel#ios-iphoneos")

    def test_the_catalog_for_another_platform(self):
        """?platform=ios or the iOS launcher's User-Agent: every program with its build for that target (none here:
        due) and no branch versions (a branch builds its own platform)."""
        st = self.ctx.store
        ids = sorted([c.name for c in st.cards("game")] + [S.arcade_id(c) for c in st.cards("system")
                                                             if c.get("machine")])
        for path, h, key in (("/api/catalog?platform=ios", {}, "ios-iphonesimulator"),
                             ("/api/catalog", {"User-Agent": UA_SIMULATOR}, "ios-iphonesimulator"),
                             ("/api/catalog?platform=ios-maccatalyst", {"User-Agent": UA_SIMULATOR}, "ios-maccatalyst")):
            with self.subTest(path=path, headers=h):
                status, _, body = self.mac.call("GET", path, headers=h)
                self.assertEqual(status, 200, body[:300])
                cat = json.loads(body)
                self.assertEqual(sorted(e["id"] for e in cat), ids)
                for e in cat:
                    card = server.card_for(self.ctx, e["id"])
                    src = (S.source_hash if card.category == "system" else B.source_hash)(self.ctx, card, key)
                    self.assertEqual((e["platform"], e["branch"], e["branches"], e["worktree"]), (key, "", [], None))
                    self.assertEqual((e["build"], e["build_due"], e["building"], e["source"]), (None, True, False, src))
        for path, why in (("/api/catalog?platform=android", "no platform card platform/android"),
                          ("/api/catalog?platform=ios-watchos", "has no target watchos")):
            status, _, body = self.mac.call("GET", path)
            self.assertEqual(status, 400, path)
            self.assertIn(why, json.loads(body)["error"])

    def test_a_program_and_its_build_progress_for_another_platform(self):
        status, _, body = self.mac.call("GET", "/api/game/vector_duel?platform=ios")
        g = json.loads(body)
        self.assertEqual((status, g["platform"], g["branches"], g["build"]), (200, "ios-iphonesimulator", [], None))
        self.assertIn("about", g)
        key = server.build_key("vector_duel", "ios-iphonesimulator")
        server._builds[key] = {"state": "building", "step": 2, "of": 6, "label": "emitting native code",
                               "source": g["source"]}
        try:
            got = json.loads(self.mac.call("GET", "/api/build/vector_duel", headers={"User-Agent": UA_SIMULATOR})[2])
            self.assertEqual(got["label"], "emitting native code")
            self.assertEqual(json.loads(self.mac.call("GET", "/api/build/vector_duel")[2]), {"state": "idle"},
                             "the Mac's own build is another")
            sim = json.loads(self.mac.call("GET", "/api/catalog?platform=ios")[2])
            self.assertTrue(next(e for e in sim if e["id"] == "vector_duel")["building"])
        finally:
            server._builds.pop(key, None)
        self.assertEqual(self.mac.call("GET", "/api/game/vector_duel?platform=ios-watchos")[0], 400)
        self.assertEqual(self.mac.call("GET", "/api/game/no_such_game?platform=ios")[0], 404)

    def test_a_listed_cartridge_is_served_by_its_id(self):
        status, _, body = self.mac.call("GET", "/api/library")
        self.assertEqual(status, 200)
        self.assertEqual([r["id"] for r in json.loads(body)["roms"] if r["file"] == self.rom_file.name], [self.rom_id])
        status, h, data = self.mac.call("GET", f"/api/cartridge/{self.rom_id}")
        self.assertEqual((status, data), (200, self.rom))
        self.assertEqual(h["X-Cartridge-File"], "Pair%20Test%20%28World%29.gb", "quoted: any file name is a header")
        self.assertEqual(unquote(h["X-Cartridge-File"]), self.rom_file.name)
        tag = h["ETag"]
        self.assertRegex(tag, r'^"[0-9]+-[0-9]+"$')
        status, h, data = self.mac.call("GET", f"/api/cartridge/{self.rom_id}", headers={"If-None-Match": tag})
        self.assertEqual((status, data, h["ETag"]), (304, b"", tag), "a device that has it is told so")
        status, _, data = self.mac.call("GET", f"/api/cartridge/{self.rom_id}", headers={"If-None-Match": '"1-1"'})
        self.assertEqual((status, data), (200, self.rom))
        self.assertEqual(self.mac.call("GET", "/api/cartridge/rom-0000000000000000")[0], 404)
        self.assertNotIn("Access-Control-Allow-Origin", h, "no web page of another origin may read a cartridge")
        port = self.mac.server_address[1]
        for origin in ("http://evil.example", f"http://evil.example:{port}", "null"):     # a page, a rebound name
            status, h, data = self.mac.call("GET", f"/api/cartridge/{self.rom_id}", headers={"Origin": origin})
            self.assertEqual(status, 403, origin)
            self.assertNotIn(self.rom, data)
        moved = self.rom_file.with_name("moved away.bin")
        self.rom_file.rename(moved)
        try:
            status, _, body = self.mac.call("GET", f"/api/cartridge/{self.rom_id}")
        finally:
            moved.rename(self.rom_file)
        self.assertEqual(status, 404)
        self.assertIn("not where the library saw it", json.loads(body)["error"])

    def test_cardmodel_arcade_pair(self):
        """The command on the Mac: a code from the running service with the address to type on the device, then
        --list (names and times, no token or hash), --forget NAME and --off."""
        from cardmodel.arcade import cli as A

        def run(**kw):
            args = argparse.Namespace(**{"list": False, "forget": None, "off": False, "json": False,
                                         "port": self.mac.server_address[1], **kw})
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                rc = A.pair(self.ctx, args)
            return rc, out.getvalue(), err.getvalue()

        rc, out, _ = run()
        code = P._code["code"]
        self.assertEqual(rc, 0)
        self.assertIn(f"{code[:3]} {code[3:]}", out)
        self.assertIn(f"this-mac.local:{self.mac.server_address[1]}", out)
        token = P.pair(self.ctx, code, "Test iPhone")
        rc, out, _ = run(list=True, json=True)
        listed = json.loads(out)
        self.assertEqual((rc, listed["lan"], [x["name"] for x in listed["devices"]]), (0, True, ["Test iPhone"]))
        self.assertNotIn(token, out)
        self.assertNotIn(hashlib.sha256(token.encode()).hexdigest(), out)
        rc, out, err = run(forget="Test iPhone", off=True, json=True)
        self.assertEqual((rc, json.loads(out)), (0, {"lan": False, "devices": []}))
        self.assertIn("Test iPhone: forgotten", err)


if __name__ == "__main__":
    unittest.main()
