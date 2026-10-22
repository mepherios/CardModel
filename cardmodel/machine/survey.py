"""survey — boot every ROM in a folder headless and say honestly what runs, what does not, and why.

Each ROM (``.gb``/``.gbc`` or a ``.zip`` holding one; read in memory, never copied) runs for ``frames`` frames
with a scripted input (START and A tapped periodically, so title screens move on). Classification:

* ``unsupported`` - the header names a bank controller the cartridge card marks unsupported (it still runs,
  as ROM-only, and is classified by what happens);
* ``locked``      - the CPU executed an illegal opcode (a lock-up on real hardware, so almost always our bug);
* ``blank``       - every checkpoint frame is one flat colour;
* ``static``      - something is drawn but no checkpoint differs from another (often waiting at a screen the
                    scripted input does not get past, sometimes stuck);
* ``runs``        - drawn and changing.

A ROM that comes out ``static`` or ``blank`` gets a second run with no input at all, and counts as running when
that one animates (the row says ``input: none``): START pauses some games, and the scripted taps can keep one
paused (Jeopardy!'s unpause waits about 1.5 s, and the next START comes 1.5 s later). A ROM without the
Nintendo logo at 0x104 that no board explains is a pass-through device (a cheat cartridge), which boots with the
header of the game in its slot; its reason says so.

``runs`` is evidence of booting, not of correctness; correctness is the per-instruction bench, the test
ROMs and the differential runs. The report keeps titles and ROM hashes only in the state directory (user
data); docs carry the aggregate counts.

``model`` picks the console as ``cardmodel emu --model`` does: ``auto`` (the header decides), ``dmg``, or ``cgb``
(DMG cartridges then run in the CGB's DMG compatibility mode).

Honest limits (L1): a scripted input cannot play a game, so "runs" means it boots and animates; games that
wait for a specific button sequence, with or without the taps, show up as ``static``.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path

from ..kernel import resources
from . import build as Bd
from . import gb as G
from . import native as N

START, A_BUTTON = 0x80, 0x10


def script(i: int) -> int:
    if i > 200 and (i % 90) < 6:
        return START
    if i > 200 and 40 <= (i % 90) < 46:
        return A_BUTTON
    return 0


def roms_in(folder) -> list[Path]:
    out = []
    for p in sorted(Path(folder).expanduser().rglob("*")):
        if p.is_file() and p.suffix.lower() in (".zip", *G.ROM_EXTS):
            out.append(p)
    return out


def _boot(g, machine, frames: int, checkpoints: int, keys) -> tuple[list, bytes, bool]:
    """Run ``frames`` frames with ``keys(i)`` pressed; (checkpoint frame hashes, last frame, locked)."""
    marks = sorted({int(frames * (k + 1) / checkpoints) - 1 for k in range(checkpoints)})
    hashes = []
    for i in range(frames):
        g.set_buttons(keys(i))
        g.run_frame()
        if machine.get("locked"):
            break
        if i in marks:
            hashes.append(hashlib.sha1(g.frame()).hexdigest()[:12])
    return hashes, g.frame(), bool(machine.get("locked"))


def _classify(hashes: list, frame: bytes, locked: bool, machine) -> tuple[str, str]:
    distinct = len(set(hashes))
    if locked:
        return "locked", f"illegal opcode near PC {machine.get('PC'):#06x}"
    if distinct <= 1 and G.frame_stats(frame)["colours"] <= 1:
        return "blank", "every checkpoint frame is one colour"
    if distinct <= 1:
        return "static", "drawn, but no checkpoint frame differs"
    return "runs", f"{distinct} distinct checkpoint frames"


def boot_one(ctx, machine, path: Path, frames: int = 1200, checkpoints: int = 8, shots_dir: Path | None = None,
             model: str = "auto") -> dict:
    t0 = time.perf_counter()
    try:
        rom, name = G.open_rom(path)
    except (OSError, ValueError, KeyError) as exc:
        return {"file": path.name, "status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    try:
        info = G.header(rom, ctx.store)
    except ValueError as exc:
        return {"file": path.name, "status": "error", "reason": str(exc)}
    g = G.GameBoy(ctx, rom, machine=machine, sample_rate=0, model=model)
    hashes, f, locked = _boot(g, machine, frames, checkpoints, script)
    status, reason = _classify(hashes, f, locked, machine)
    keys = "scripted"
    if status in ("static", "blank"):
        g = G.GameBoy(ctx, rom, machine=machine, sample_rate=0, model=model)
        h2, f2, l2 = _boot(g, machine, frames, checkpoints, lambda i: 0)
        s2, r2 = _classify(h2, f2, l2, machine)
        if s2 == "runs":
            status, reason, hashes, f, keys = s2, f"{r2} with no input (with the scripted taps: {reason})", h2, f2, "none"
    if status != "runs" and not info["logo"] and not info["unlicensed"]:
        reason += ("; no Nintendo logo at 0x104 and no board that explains it: a pass-through device (a cheat "
                   "cartridge), which boots with the header of the game in its slot")
    st = G.frame_stats(f)
    if shots_dir is not None:
        shots_dir.mkdir(parents=True, exist_ok=True)
        (shots_dir / f"{hashlib.sha1(rom).hexdigest()[:10]}_{status}.png").write_bytes(G.png(f))
    return {"file": path.name, "title": info["title"], "sha1": info["sha1"], "mbc": info["mbc"],
            "cgb": info["cgb"], "model": g.model, "supported": info["supported"], "status": status, "reason": reason,
            "frames": frames, "distinct_frames": len(set(hashes)), "input": keys, "last_frame": st,
            "pc": machine.get("PC"), "instructions": machine.get("instructions"),
            "seconds": round(time.perf_counter() - t0, 3), "unsupported_mapper": not info["supported"],
            "checkpoint_stats": st}


def run(ctx, folder, frames: int = 1200, engine: str = "native", limit: int | None = None,
        shots_dir: Path | None = None, progress=None, model: str = "auto") -> dict:
    ir = Bd.module(ctx, "gameboy")
    machine = N.load(ctx, ir, engine)
    rows = []
    paths = roms_in(folder)[:limit] if limit else roms_in(folder)
    for k, p in enumerate(paths):
        resources.guard("survey")
        r = boot_one(ctx, machine, p, frames, shots_dir=shots_dir, model=model)
        rows.append(r)
        if progress:
            progress(k + 1, len(paths), r)
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    unsupported = sum(1 for r in rows if r.get("unsupported_mapper"))
    return {"folder_files": len(paths), "frames": frames, "engine": machine.engine, "model": model, "counts": counts,
            "unsupported_mappers": unsupported, "runs_fraction": round(counts.get("runs", 0) / max(1, len(rows)), 4),
            "rows": rows}


__all__ = ["boot_one", "roms_in", "run", "script"]
