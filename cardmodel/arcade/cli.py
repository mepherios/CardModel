"""cli — `cardmodel arcade`: games built from cards, served to a launcher.

  cardmodel arcade list                         the game cards, their versions, their latest builds
  cardmodel arcade build GAME                   compile the game's cards to a native package and a depot
  cardmodel arcade serve [--port 8770]          the content service the launcher talks to
  cardmodel arcade launcher [--install]         build Cardmodel Arcade.app (and put it in ~/Applications)
  cardmodel arcade run GAME [--frames N --shot PNG --input SCRIPT --save-dir DIR]   the latest build, natively
  cardmodel arcade build gameboy                a console's player (system card): your cartridges play in it
  cardmodel arcade run gameboy_player --rom PATH   a cartridge in the latest player build
  cardmodel arcade library [--draw]             the cartridges the system cards find (--draw: their title screens)
  cardmodel arcade library --add DIR --system gameboy   look for cartridges in DIR (--remove DIR to stop)
  cardmodel arcade check [GAME] [--launcher] [--no-build] [--cartridges N]   every catalogue item launched
                                                through the store as the launcher does it (install, verify, repair,
                                                play headless), then every cartridge the library lists
  cardmodel arcade app ROM [--install]          one cartridge as its own app, its code lifted into cards (cartapp.py)
  cardmodel arcade build GAME --platform ios    the same program for another platform card (a key: ios,
                                                ios-iphonesimulator, ios-iphoneos, ios-maccatalyst)
  cardmodel arcade launcher --platform ios [--install] [--device NAME]   the iPhone and iPad launcher (ios.py),
                                                installed and opened on a Simulator
  cardmodel arcade launcher --platform ios --check GAME [--rom ROMID]    in the Simulator, through the service:
                                                install, verify and play headless, as the device's store does
  cardmodel arcade pair [--list] [--forget NAME] [--off]   an iPhone or iPad on the local network (pairing.py)

Honest limits (L1): the launcher remembers a checkout's path (to start the service): after moving the
repository, run `cardmodel arcade launcher --install` again. Installing from a linked git worktree points the
launcher at the main checkout (a worktree is deleted with its session; `--home` names another checkout).
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import sys
from pathlib import Path

from ..kernel import paths


def _cli():
    from .. import cli
    return cli


def launcher_icon() -> bytes:
    """The launcher's icon: three stacked cards and a vector, drawn here (128 x 128 RGBA)."""
    w = 128
    px = bytearray(w * w * 4)

    def put(x, y, c, a=255):
        if 0 <= x < w and 0 <= y < w:
            i = (y * w + x) * 4
            px[i:i + 4] = bytes((c >> 16 & 255, c >> 8 & 255, c & 255, a))

    for y in range(w):
        for x in range(w):
            dx, dy = max(0, 18 - x, x - 109), max(0, 18 - y, y - 109)
            if dx * dx + dy * dy <= 324:
                t = y * 255 // w
                put(x, y, ((0x1B + (0x10 - 0x1B) * t // 255) << 16) | ((0x28 + (0x18 - 0x28) * t // 255) << 8)
                    | (0x38 + (0x24 - 0x38) * t // 255))
    for k, col in enumerate((0x6A7FA0, 0x9CB0CC, 0xF4EEE0)):
        ox, oy = 30 + k * 12, 26 + (2 - k) * 10
        for y in range(oy, oy + 62):
            for x in range(ox, ox + 44):
                edge = x in (ox, ox + 43) or y in (oy, oy + 61)
                put(x, y, 0x0D0F18 if edge else col)
    for t in range(0, 100):
        x, y = 58 + t * 30 // 100, 92 - t * 30 // 100
        for d in range(-2, 3):
            put(x + d, y, 0xD04040)
            put(x, y + d, 0xD04040)
    from .build import png_rgba
    return png_rgba(bytes(px), w, w)


def primary_checkout(home: Path) -> Path | None:
    """The main checkout when ``home`` is a linked git worktree (its ``.git`` is a file naming
    <main>/.git/worktrees/<name>), else None."""
    g = home / ".git"
    if not g.is_file():
        return None
    text = g.read_text(encoding="utf-8", errors="replace").strip()
    if not text.startswith("gitdir:"):
        return None
    gitdir = Path(text.split(":", 1)[1].strip())
    if not gitdir.is_absolute():
        gitdir = (home / gitdir).resolve()
    if gitdir.parent.name != "worktrees" or gitdir.parent.parent.name != ".git":
        return None
    main = gitdir.parent.parent.parent
    return main if (main / "bin" / "cardmodel").is_file() and (main / "cardmodel" / "arcade").is_dir() else None


def launcher_home(install: bool, home: str | None, say=print) -> Path:
    """Where the installed launcher starts the service: --home, else (installing from a linked worktree, which
    may be deleted with its session) the main checkout, else this checkout."""
    if home:
        return Path(home).expanduser().resolve()
    here = paths.home()
    main = primary_checkout(here) if install else None
    if main is not None:
        say(f"this checkout is a linked worktree; the launcher will start the service from the main checkout "
            f"{main} (pass --home to choose another)")
        return main
    return here


def build_launcher(ctx, install: bool, say=print, home: Path | None = None) -> Path:
    from . import build as B
    app = ctx.store.get("app/arcade")
    plat = ctx.store.get(f"platform/{app['platform']}")
    exe = B._tool(plat["probe"])
    srcs = [app.path / s for s in app["sources"]]
    h = hashlib.sha256(json.dumps(dict(app), sort_keys=True, default=str).encode())
    for s in srcs:
        h.update(s.read_bytes())
    build_id = h.hexdigest()[:12]
    root = B.arcade_root(ctx) / "launcher" / build_id      # a fresh folder: a running copy is never touched
    root.mkdir(parents=True, exist_ok=True)
    out = root / (app["title"] + app["bundle"]["suffix"])
    if out.exists():
        shutil.rmtree(out)
    b = app["bundle"]
    for key in ("executable_dir", "resources_dir"):
        (out / b[key]).mkdir(parents=True, exist_ok=True)
    binary = out / b["executable_dir"] / app["title"]
    say("compiling the launcher")
    args = []
    for a in app["compile"]:
        args += [str(s) for s in srcs] if a == "{srcs}" else [a.format(exe=exe, out=str(binary))]
    B._run(args, root)
    os.chmod(binary, 0o755)
    say("drawing its icon")
    work = root / "work"
    work.mkdir(exist_ok=True)
    from .build import png_rgba, scale  # noqa: F401
    icon_png = launcher_icon()
    iconset = work / "AppIcon.iconset"
    iconset.mkdir(exist_ok=True)
    import struct
    import zlib
    raw = zlib.decompress(b"".join(_png_chunks(icon_png, b"IDAT")))
    rgba = b"".join(raw[1 + y * (128 * 4 + 1):(y + 1) * (128 * 4 + 1)] for y in range(128))
    for s in plat["icon"]["sizes"]:
        for k, suffix in ((1, ""), (2, "@2x")):
            n = s * k
            (iconset / f"icon_{s}x{s}{suffix}.png").write_bytes(png_rgba(B.scale(rgba, 128, 128, n, n), n, n))
    icns = work / "AppIcon.icns"
    B._run([a.format(exe=B._tool(plat["icon"]["probe"]), out=str(icns), iconset=str(iconset))
            for a in plat["icon"]["compile"]], work)
    shutil.copy(icns, out / b["resources_dir"] / b["icon_file"])
    shutil.rmtree(work)
    values = {"build": build_id, "version": app.get("version", "1.0.0"), "home": str(home or paths.home()),
              "python": sys.executable}
    plist = {}
    for k, v in b["info_plist"].items():
        plist[k] = v.format(**values) if isinstance(v, str) else v
    (out / "Contents" / "Info.plist").write_bytes(plistlib.dumps(plist))
    del struct
    if install:
        dest_dir = Path(os.path.expanduser(app.get("install_dir", "~/Applications")))
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / out.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(out, dest)
        say(f"installed {dest}")
        return dest
    return out


def _png_chunks(png: bytes, tag: bytes):
    import struct
    pos = 8
    while pos < len(png):
        n, t = struct.unpack(">I4s", png[pos:pos + 8])
        if t == tag:
            yield png[pos + 8:pos + 8 + n]
        pos += 12 + n


def cmd_arcade(args) -> int:
    cli = _cli()
    ctx = cli._ctx(args)
    from . import build as B
    from . import game as G
    from . import system as S
    if args.action == "library":
        from . import library as L
        if args.add or args.remove:
            got = L.set_folder(ctx, args.system or "gameboy", args.add, args.remove)
            print(f"{args.system or 'gameboy'} folders: {', '.join(got) or 'none'}", file=sys.stderr)
        lib = L.scan(ctx, force=True)
        if args.draw:
            L.draw_covers(ctx, progress=lambda k, n, r: print(f"[{k}/{n}] {r['title']}", file=sys.stderr)
                          if k % 50 == 0 or k == n else None)
            lib = L.scan(ctx, force=True)
        counts: dict = {}
        for r in lib["roms"]:
            key = (r["system_card"], r["system"])
            c = counts.setdefault(key, {})
            c[r["verdict"]["level"]] = c.get(r["verdict"]["level"], 0) + 1
        lines = []
        for sy in lib["systems"]:
            lines.append(f"{sy['title']}: {'player ' + sy['player'] if sy['player'] else 'no player yet'}; "
                         f"folders {', '.join(sy['folders'])}")
            for sub in sy["systems"]:
                c = counts.get((sy["id"], sub["id"]), {})
                if c:
                    n = sum(c.values())
                    lines.append(f"  {sub['label']}: {n} cartridge{'' if n == 1 else 's'} "
                                 f"({', '.join(f'{k} {v}' for k, v in sorted(c.items()))})")
        cli._out(args, {"systems": lib["systems"], "counts": {f"{a}/{b}": v for (a, b), v in counts.items()}},
                 "\n".join(lines))
        return 0
    if args.action == "list":
        rows = []
        for c in [*ctx.store.cards("game"), *[x for x in ctx.store.cards("system") if x.get("machine")]]:
            if c.category == "system":
                info = B.latest(ctx, S.arcade_id(c))
                m = json.loads((info / "manifest.json").read_text()) if info else None
                rows.append({"id": S.arcade_id(c), "title": c["title"], "version": c["version"],
                             "built": None if not m else f"{m['version']}+{m['build']}",
                             "build_due": (m or {}).get("source") != S.source_hash(ctx, c)})
                continue
            info = B.latest(ctx, c.name)
            m = json.loads((info / "manifest.json").read_text()) if info else None
            due = (m or {}).get("source") != B.source_hash(ctx, c)
            rows.append({"id": c.name, "title": c["title"], "version": c["version"],
                         "built": None if not m else f"{m['version']}+{m['build']}", "build_due": due})
        cli._out(args, rows, "\n".join(f"{r['id']:<16} {r['title']:<20} v{r['version']:<8} latest build "
                                       f"{r['built'] or 'none'}{'  (cards changed: build due)' if r['build_due'] else ''}"
                                       for r in rows))
        return 0
    if args.action == "build":
        system = S.is_system(ctx.store, args.target) or ctx.store.get(f"system/{args.target}") is not None
        builder = S.build if system else B.build
        info = builder(ctx, args.target, progress=lambda s, n, m: print(f"[{s}/{n}] {m}", file=sys.stderr),
                       platform=args.platform)
        cli._out(args, info, f"{info['title']} {info['version']} build {info['build']} for {info['platform']}: "
                             f"{info['size']:,} bytes in {info['chunks']} chunks, {len(info['media'])} store pictures, "
                             f"{info['seconds']} s")
        return 0
    if args.action == "app":
        from . import cartapp
        if not args.target:
            print("error: arcade app needs a cartridge file (a .gb, .gbc or a .zip with one)", file=sys.stderr)
            return 2
        info = cartapp.build(ctx, Path(args.target), install=args.install, progress=lambda m: print(m, file=sys.stderr))
        w, lf = info["witness"], info["lift"]
        cli._out(args, info, "\n".join([
            f"{info['title']}: {info['installed'] or info['app']}",
            f"  lifted: {lf['blocks']:,} blocks ({lf['instructions_lifted']:,} instructions), "
            f"{lf.get('single_instructions', 0):,} instructions on their own, {lf['ram_instructions_lifted']} RAM "
            f"instructions; found by reasoning: {lf.get('static', {}).get('far', 0):,} far calls, "
            f"{lf.get('static', {}).get('tables', 0):,} jump-table entries",
            f"  witness: {w['frames']:,} frames identical to the plain player (a walk with seed {w['seed']}, round "
            f"{w['rounds']}); {100 * w['purity']:.2f} % of the {w['instructions']:,} instructions ran as lifted card "
            f"IR ({w['interpreted']:,} interpreted, {w['interpreted_ram']:,} of them in RAM)",
            f"  saves: {info['saves']}  ({info['seconds']} s)"]))
        return 0
    if args.action == "serve":
        from . import server
        app = ctx.store.get("app/arcade")
        ui = (app.path / app["ui"]) if app else None
        server.serve(ctx, port=args.port, ui_dir=ui, lan=True if args.lan else None,
                     ready=lambda p: print(f"arcade service on http://127.0.0.1:{p}/", flush=True))
        return 0
    if args.action == "pair":
        return pair(ctx, args)
    if args.action == "launcher" and (args.platform or "").startswith("ios"):
        return ios_launcher(ctx, args)
    if args.action == "launcher":
        say = lambda m: print(m, file=sys.stderr)  # noqa: E731
        dest = build_launcher(ctx, args.install, say=say, home=launcher_home(args.install, args.home, say=say))
        cli._out(args, {"app": str(dest)}, str(dest))
        return 0
    if args.action == "run":
        target = args.target
        if ctx.store.get(f"system/{target}") is not None and ctx.store.get(f"game/{target}") is None:
            target = target + S.ID_SUFFIX
        root = B.latest(ctx, target)
        if root is None:
            print(f"error: {args.target} has no build yet (cardmodel arcade build {args.target})", file=sys.stderr)
            return 2
        info = json.loads((root / "manifest.json").read_text())
        exe = root / "content" / info["executable"]
        cmd = [str(exe)]
        if args.frames:
            cmd += ["--frames", str(args.frames)]
        if args.shot:
            cmd += ["--shot", args.shot]
        if args.input:
            cmd += ["--input", args.input]
        if args.rom:
            cmd += ["--rom", str(Path(args.rom).expanduser())]
        import tempfile
        save_dir = args.save_dir or (tempfile.mkdtemp(prefix="cardmodel_run_") if args.frames else None)
        if save_dir:            # a headless run never writes the player's own save
            cmd += ["--save-dir", str(Path(save_dir).expanduser())]
        from ..kernel import resources
        p = resources.run(cmd, timeout=24 * 3600, heavy=False)
        sys.stdout.write(p.stdout or "")
        return p.returncode
    if args.action == "check":
        from . import client
        say = (lambda m: print(f"[store] {m}", file=sys.stderr)) if not args.json else (lambda m: None)
        rep = client.check_catalog(ctx, frames=args.frames or 120, only=[args.target] if args.target else None,
                                   build=not args.no_build, progress=say, cartridges=args.cartridges)
        if args.launcher and rep["status"] != "skipped":
            import time
            t0 = time.perf_counter()
            try:
                out = build_launcher(ctx, False, say=say)
                rep["launcher"] = {"ok": True, "app": str(out), "seconds": round(time.perf_counter() - t0, 1)}
            except (B.BuildError, OSError, KeyError) as exc:
                rep["launcher"] = {"ok": False, "error": str(exc)[-1500:]}
                rep["status"] = "fail"
        lines = []
        for gid, r in rep["items"].items():
            if r.get("ok"):
                pl, ins = r["play"], r["install"]
                on = (" on its check cartridge (the picture its cards compute, the save kept)" if "save_kept" in pl
                      else "")
                lines.append(f"  ok    {gid:<14} v{ins['version']} build {ins['build']}: {ins['files']} files "
                             f"{ins['size']:,} bytes checked; repair re-fetched {r['repair']['fetched']:,} bytes; "
                             f"played {args.frames or 120} frames{on} in {pl['seconds']} s "
                             f"({pl['picture']['colours_sampled']} colours on screen)")
            else:
                lines.append(f"  FAIL  {gid:<14} {r.get('error') or json.dumps(r, default=str)[:400]}")
        ct = rep.get("cartridges")
        if ct:
            per = "; ".join(f"{pid}: {t['launched']} of {t['listed']} ({t['colourful']} show more than one colour)"
                            for pid, t in ct["players"].items())
            none = ", ".join(f"{n} for {s_} (no player yet)" for s_, n in ct["unplayable"].items())
            lines.append(f"  {'ok  ' if not ct['failed'] else 'FAIL'}  cartridges     {ct['launched']} of "
                         f"{ct['checked']} launched through the store and showed the picture their cards compute "
                         f"after {ct['frames']} frames ({ct['seconds']} s){': ' + per if per else ''}"
                         + (f"; listed, not launchable: {none}" if none else "")
                         + (f"; only the first {ct['limit']} of {ct['listed']} checked" if ct["limit"] is not None
                            else ""))
            for f in ct["failing"][:20]:
                lines.append(f"  FAIL  {f['title'][:40]:<40} {f['error']}  ({f['path']})")
        pg = rep.get("pages") or {}
        lines.append(f"  pages {'ok' if pg.get('ok') else 'FAIL'}  assets {pg.get('assets')}, endpoints the page "
                     f"uses {pg.get('api')}" + (f", unknown {pg['unknown_endpoints']}" if pg.get("unknown_endpoints")
                                               else ""))
        if rep.get("launcher"):
            lw = rep["launcher"]
            lines.append(f"  launcher {'compiles' if lw['ok'] else 'FAILED: ' + lw['error']}"
                         + (f" ({lw['seconds']} s)" if lw.get("seconds") else ""))
        head = f"store check: {rep['status']}" + (f" ({rep.get('reason')})" if rep.get("reason") else "")
        cli._out(args, rep, "\n".join([head, *lines]))
        return 0 if rep["status"] == "pass" else (2 if rep["status"] == "skipped" else 1)
    del G
    return 2


def pair(ctx, args) -> int:
    """`cardmodel arcade pair`: a code from the running service for a device on the local network, with the
    addresses it can reach the service at; --list, --forget NAME and --off look after the paired devices."""
    import time
    from . import pairing as P
    cli = _cli()
    if args.list or args.forget or args.off:
        if args.forget:
            print(f"{args.forget}: {'forgotten' if P.forget(ctx, args.forget) else 'not paired'}", file=sys.stderr)
        if args.off:
            P.set_lan(ctx, False)
            print("the service stops listening on the local network when it next starts", file=sys.stderr)
        d = P.load(ctx)
        cli._out(args, {"lan": d["lan"], "devices": [{k: x[k] for k in ("name", "paired", "seen")} for x in d["devices"]]},
                 "\n".join([f"local network: {'on' if d['lan'] else 'off'}"]
                           + ([f"  {x['name']} (paired {time.strftime('%Y-%m-%d %H:%M', time.localtime(x['paired']))})"
                               for x in d["devices"]] or ["  no devices paired"])))
        return 0
    import urllib.error
    import urllib.request
    req = urllib.request.Request(f"http://127.0.0.1:{args.port}/api/pair/code", data=b"{}", method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        got = json.loads(urllib.request.urlopen(req, timeout=10).read())
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print(f"error: no arcade service on port {args.port} to pair with ({exc}); open Cardmodel Arcade or run "
              f"`cardmodel arcade serve`", file=sys.stderr)
        return 2
    code = got["code"]
    cli._out(args, got, "\n".join([
        "On your iPhone or iPad, in Cardmodel Arcade:",
        f"  Mac address  {' or '.join(got['addresses']) or '(this Mac has no local network address)'}",
        f"  Code         {code[:3]} {code[3:]}   (ten minutes, five tries)"]))
    return 0


def ios_launcher(ctx, args) -> int:
    """`cardmodel arcade launcher --platform ios ...` (ios.py): build; --install on a Simulator; --check GAME."""
    from . import ios
    cli = _cli()
    say = lambda m: print(m, file=sys.stderr)  # noqa: E731
    app = ios.build(ctx, args.platform, say=say)
    if not (args.install or args.check):
        cli._out(args, {"app": str(app)}, str(app))
        return 0
    if not args.platform.endswith(("ios", "iphonesimulator")):
        print("error: --install and --check use the iOS Simulator (--platform ios or ios-iphonesimulator)", file=sys.stderr)
        return 2
    dev = ios.device(args.device)
    say(f"installing it on {dev['name']}")
    ios.install(app, dev)
    service = None if args.port == 8770 else f"http://127.0.0.1:{args.port}"     # another service of this Mac
    if args.check:
        rep = ios.check(ctx, args.check, dev, rom=args.rom, frames=args.frames or 120, shot=args.shot,
                        inputs=args.input or "", service=service)
        cli._out(args, rep, json.dumps(rep, indent=1))
        return 0 if rep.get("ok") else 1
    ios.show(dev)
    ios.launch(dev, ["--mute"] if args.mute else [], service=service)
    cli._out(args, {"app": str(app), "device": dev}, f"{app} is open on {dev['name']}")
    return 0


def register(sub) -> None:
    s = sub.add_parser("arcade", help="games built from cards: build them natively, serve them to the launcher")
    s.add_argument("action", choices=["list", "build", "serve", "launcher", "run", "library", "app", "check", "pair"])
    s.add_argument("target", nargs="?")
    s.add_argument("--port", type=int, default=8770)
    s.add_argument("--install", action="store_true")
    s.add_argument("--home", help="launcher: the checkout the launcher starts the service from (default: this one)")
    s.add_argument("--frames", type=int, default=0)
    s.add_argument("--shot")
    s.add_argument("--input")
    s.add_argument("--rom", help="run: a cartridge file for a console player; launcher --platform ios --check: a "
                                 "cartridge's id in the Mac's library")
    s.add_argument("--save-dir", dest="save_dir", help="run: where the save lives (headless runs: a temporary one)")
    s.add_argument("--draw", action="store_true", help="library: draw every missing title screen")
    s.add_argument("--add", help="library: a folder to look for cartridges in")
    s.add_argument("--remove", help="library: a folder to stop looking in")
    s.add_argument("--system", help="library: which system card the folder is for (default gameboy)")
    s.add_argument("--launcher", action="store_true", help="check: also compile the launcher")
    s.add_argument("--no-build", action="store_true", help="check: fail instead of building when cards changed")
    s.add_argument("--cartridges", type=int, help="check: launch only the first N listed cartridges (0: none)")
    s.add_argument("--platform", help="build, launcher: a platform card's key (ios, ios-iphonesimulator, ...)")
    s.add_argument("--device", help="launcher --platform ios: the Simulator device (name or udid)")
    s.add_argument("--check", help="launcher --platform ios: install, verify and play this program in the Simulator")
    s.add_argument("--lan", action="store_true", help="serve: also on the local network (paired devices only)")
    s.add_argument("--mute", action="store_true", help="launcher --platform ios --install: games play without sound")
    s.add_argument("--list", action="store_true", help="pair: the paired devices")
    s.add_argument("--forget", help="pair: forget this device")
    s.add_argument("--off", action="store_true", help="pair: stop listening on the local network")
    s.set_defaults(fn=cmd_arcade)


__all__ = ["build_launcher", "cmd_arcade", "ios_launcher", "launcher_home", "launcher_icon", "pair", "primary_checkout",
           "register"]
