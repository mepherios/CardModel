"""cli — `cardmodel arcade`: games built from cards, served to a launcher.

  cardmodel arcade list                         the game cards, their versions, their latest builds
  cardmodel arcade build GAME                   compile the game's cards to a native package and a depot
  cardmodel arcade serve [--port 8770]          the content service the launcher talks to
  cardmodel arcade launcher [--install]         build Cardmodel Arcade.app (and put it in ~/Applications)
  cardmodel arcade run GAME [--frames N --shot PNG --input SCRIPT]   the latest build, natively

Honest limits (L1): the launcher remembers this checkout's path (to start the service): after moving the
repository, run `cardmodel arcade launcher --install` again.
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


def build_launcher(ctx, install: bool, say=print) -> Path:
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
    values = {"build": build_id, "version": app.get("version", "1.0.0"), "home": str(paths.home()),
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
    if args.action == "list":
        rows = []
        for c in ctx.store.cards("game"):
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
        info = B.build(ctx, args.target, progress=lambda s, n, m: print(f"[{s}/{n}] {m}", file=sys.stderr))
        cli._out(args, info, f"{info['title']} {info['version']} build {info['build']}: {info['size']:,} bytes in "
                             f"{info['chunks']} chunks, {len(info['media'])} store pictures, {info['seconds']} s")
        return 0
    if args.action == "serve":
        from . import server
        app = ctx.store.get("app/arcade")
        ui = (app.path / app["ui"]) if app else None
        server.serve(ctx, port=args.port, ui_dir=ui,
                     ready=lambda p: print(f"arcade service on http://127.0.0.1:{p}/", flush=True))
        return 0
    if args.action == "launcher":
        dest = build_launcher(ctx, args.install, say=lambda m: print(m, file=sys.stderr))
        cli._out(args, {"app": str(dest)}, str(dest))
        return 0
    if args.action == "run":
        root = B.latest(ctx, args.target)
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
        from ..kernel import resources
        p = resources.run(cmd, timeout=24 * 3600, heavy=False)
        sys.stdout.write(p.stdout or "")
        return p.returncode
    del G
    return 2


def register(sub) -> None:
    s = sub.add_parser("arcade", help="games built from cards: build them natively, serve them to the launcher")
    s.add_argument("action", choices=["list", "build", "serve", "launcher", "run"])
    s.add_argument("target", nargs="?")
    s.add_argument("--port", type=int, default=8770)
    s.add_argument("--install", action="store_true")
    s.add_argument("--frames", type=int, default=0)
    s.add_argument("--shot")
    s.add_argument("--input")
    s.set_defaults(fn=cmd_arcade)


__all__ = ["build_launcher", "cmd_arcade", "launcher_icon", "register"]
