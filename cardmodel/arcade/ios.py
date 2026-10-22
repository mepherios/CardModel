"""ios — Cardmodel Arcade on iPhone and iPad: the launcher app (app/arcade_ios) built for a platform/ios target, and
the iOS Simulator it is tried in.

    app card's sources + the platform card's shared shell (GameShell.swift) ──the target's swiftc──▶ executable
    the platform card's bundle for that target + the app's own Info.plist keys + its icon ──▶ Cardmodel Arcade.app,
    signed as the target says (ad hoc for the Simulator and Mac Catalyst; a device needs the user's identity)

The launcher reaches the arcade service on the Mac (the Simulator and Mac Catalyst at 127.0.0.1, a device on the
local network once paired: pairing.py), and plays each program's build for its own target, which the service makes
from the cards (build.py) when the launcher asks for it.

    cardmodel arcade launcher --platform ios [--install] [--device NAME]      build; --install puts it on a
                                    Simulator (booted, or the one named; the first one available otherwise) and opens it
    cardmodel arcade launcher --platform ios --check ID [--rom ROMID] [--frames N --shot PNG] [--device NAME]
                                    in the Simulator: install ID through the service, verify it, play it headless

Honest limits (L1): a real iPhone or iPad needs Xcode's signing (an Apple ID's team and a provisioning profile),
which this does not set up; every Simulator the checks use runs on this Mac's iOS runtime only.
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import time
import zlib
from pathlib import Path

from ..kernel import resources
from . import build as B
from . import pairing as P

BUNDLE_ID = "org.cardmodel.arcade.ios"
SIM_TIMEOUT_S = 300


def icon_rgba() -> bytes:
    """The launcher's icon (cli.launcher_icon, the one the Mac's has) as 128 x 128 RGBA."""
    from .cli import _png_chunks, launcher_icon
    raw = zlib.decompress(b"".join(_png_chunks(launcher_icon(), b"IDAT")))
    return b"".join(raw[1 + y * (128 * 4 + 1):(y + 1) * (128 * 4 + 1)] for y in range(128))


def build(ctx, platform: str | None = None, say=print, service: str | None = None) -> Path:
    """Cardmodel Arcade.app for one target of the iOS platform card (default: the app card's, the Simulator)."""
    app = ctx.store.get("app/arcade_ios")
    platform = platform or app.get("default_platform") or app["platform"]
    plat, target, key = B.resolve_platform(ctx.store, app, platform)
    values, env = B.target_values(plat, target)
    shell = B.section(plat, target, "effect_shell")
    srcs = [app.path / s for s in app["sources"]] + [plat.path / s for s in shell[app.get("shell_sources", "shared")]]
    if service is None:          # the Mac it is built on: this Mac itself, or its address for a device
        port = int((ctx.store.get("app/arcade") or {}).get("port", 8770))
        lan = P.addresses(port)
        service = f"http://{lan[0]}" if target == "iphoneos" and lan else f"http://127.0.0.1:{port}"
    h = hashlib.sha256(json.dumps(dict(app), sort_keys=True, default=str).encode() + key.encode() + service.encode())
    h.update(json.dumps(values, sort_keys=True, default=str).encode())
    for s in srcs:
        h.update(s.read_bytes())
    build_id = h.hexdigest()[:12]
    root = B.arcade_root(ctx) / "launcher" / f"{key}-{build_id}"   # a fresh folder: a running copy is never touched
    bundle = B.section(plat, target, "bundle")
    out = root / (app["title"] + bundle.get("suffix", ".app"))
    if (root / ".done").is_file():
        return out
    if root.exists():
        shutil.rmtree(root)
    for k in ("executable_dir", "frameworks_dir", "resources_dir"):
        (out / bundle[k]).mkdir(parents=True, exist_ok=True)
    say(f"compiling the launcher for {key}")
    binary = out / bundle["executable_dir"] / app["title"]
    B._run(B._args(app["compile"], {**values, "out": str(binary), "srcs": [str(s) for s in srcs]}), root, env)
    os.chmod(binary, 0o755)
    work = root / "work"
    work.mkdir()
    B.icon(ctx, plat, target, icon_rgba(), work, out, bundle)
    shutil.rmtree(work)
    names = {**values, "title": app["title"], "id": app.name, "ident": B.ident(app.name),
             "version": app.get("version", "1.0.0"), "build": build_id, "identifier": app.get("identifier", BUNDLE_ID),
             "service": service}
    plist = B._fill(B._merge(bundle["info_plist"], app.get("info_plist") or {}), names)
    (out / bundle.get("plist", "Contents/Info.plist")).write_bytes(plistlib.dumps(plist))
    say("signing it")
    B.sign(plat, target, [out])
    (root / ".done").write_text(key, encoding="utf-8")
    return out


# -- the Simulator ----------------------------------------------------------------------------------------------------
def simctl(args: list[str], timeout: float = SIM_TIMEOUT_S, check: bool = True) -> subprocess.CompletedProcess:
    exe = B._tool({"kind": "executable", "name": "xcrun"})
    p = resources.run([exe, "simctl", *args], timeout=timeout, heavy=False, stdin=subprocess.DEVNULL)
    if check and p.returncode != 0:
        raise B.BuildError(f"simctl {' '.join(args[:2])} failed: {(p.stderr or p.stdout).strip()[-800:]}")
    return p


def devices() -> list[dict]:
    """Every available Simulator device: name, udid, state, runtime."""
    out = []
    for rt, devs in json.loads(simctl(["list", "devices", "available", "-j"]).stdout).get("devices", {}).items():
        for d in devs:
            out.append({"name": d["name"], "udid": d["udid"], "state": d["state"], "runtime": rt})
    return out


def device(name: str | None = None) -> dict:
    """The device named (name or udid), else a booted one, else the first available iPhone; booted on the way."""
    devs = devices()
    if not devs:
        raise B.BuildError("no iOS Simulator device here (Xcode -> Settings -> Components installs the iOS runtime)")
    if name:
        d = next((x for x in devs if name in (x["name"], x["udid"])), None)
        if d is None:
            raise B.BuildError(f"no Simulator device {name!r} (have: {', '.join(x['name'] for x in devs)})")
    else:
        d = next((x for x in devs if x["state"] == "Booted"), None) or \
            next((x for x in devs if x["name"].startswith("iPhone")), devs[0])
    if d["state"] != "Booted":
        simctl(["boot", d["udid"]])
        simctl(["bootstatus", d["udid"], "-b"], timeout=SIM_TIMEOUT_S)
        d["state"] = "Booted"
    return d


def install(app: Path, dev: dict) -> None:
    simctl(["install", dev["udid"], str(app)])


def show(dev: dict) -> None:
    """The Simulator's window for the device, in front: a game playing there is seen (and heard) in a window of its
    own with its own Dock icon, which can be muted or closed like any app, never only heard from a hidden device."""
    p = resources.run(["xcode-select", "-p"], timeout=30, heavy=False, stdin=subprocess.DEVNULL)
    d = Path(os.environ.get("DEVELOPER_DIR") or p.stdout.strip())
    # Xcode up to 26: Developer/Applications/Simulator.app; Xcode 27: Contents/Applications/DeviceHub.app
    app = next((a for a in (d / "Applications" / "Simulator.app", d.parent / "Applications" / "DeviceHub.app",
                            d.parent / "Applications" / "Simulator.app") if a.is_dir()), None)
    if app is None:
        return
    resources.run(["/usr/bin/open", "-a", str(app), "--args", "-CurrentDeviceUDID", dev["udid"]], timeout=60,
                  heavy=False, stdin=subprocess.DEVNULL)


def launch(dev: dict, args: list[str] = (), console: bool = False, timeout: float = SIM_TIMEOUT_S,
           service: str | None = None) -> str:
    """Start the launcher on the device (stopping a running one first), at the service named (else its own: this
    Mac's port 8770); with console, wait for it to end and return what it printed."""
    simctl(["terminate", dev["udid"], BUNDLE_ID], check=False)
    extra = ["--service", service] if service else []
    p = simctl(["launch", *(["--console-pty"] if console else []), dev["udid"], BUNDLE_ID, *extra, *args], timeout=timeout)
    return p.stdout


def check(ctx, program: str, dev: dict, rom: str | None = None, frames: int = 120, shot: str | None = None,
          inputs: str = "", service: str | None = None) -> dict:
    """The store on the device, headless: the launcher installs program through the service (the build for this
    Simulator, made from the cards when they changed), verifies it, plays it (a cartridge from the Mac's library
    with rom) and reports one JSON line."""
    args = ["--check", program, "--frames", str(frames)]
    if rom:
        args += ["--rom", rom]
    if shot:
        args += ["--shot", shot]
    if inputs:
        args += ["--input", inputs]
    t0 = time.time()
    text = launch(dev, args, console=True, timeout=1800, service=service)
    line = next((ln for ln in text.splitlines() if ln.startswith("arcade check: ")), None)
    if line is None:
        return {"ok": False, "error": "the launcher printed no result", "output": text[-2000:]}
    out = json.loads(line[len("arcade check: "):])
    out["device"] = dev["name"]
    out["seconds"] = round(time.time() - t0, 1)
    return out


__all__ = ["BUNDLE_ID", "build", "check", "device", "devices", "install", "launch", "show", "simctl"]
