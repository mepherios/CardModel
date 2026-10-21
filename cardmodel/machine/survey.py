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

``runs`` is evidence of booting, not of correctness; correctness is the per-instruction bench, the test
ROMs and the differential runs. The report keeps titles and ROM hashes only in the state directory (user
data); docs carry the aggregate counts.

Honest limits (L1): a scripted input cannot play a game, so "runs" means it boots and animates; games that
wait for a specific button sequence show up as ``static``.
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


def boot_one(ctx, machine, path: Path, frames: int = 1200, checkpoints: int = 8, shots_dir: Path | None = None) -> dict:
    t0 = time.perf_counter()
    try:
        rom, name = G.open_rom(path)
    except (OSError, ValueError, KeyError) as exc:
        return {"file": path.name, "status": "error", "reason": f"{type(exc).__name__}: {exc}"}
    try:
        info = G.header(rom, ctx.store)
    except ValueError as exc:
        return {"file": path.name, "status": "error", "reason": str(exc)}
    g = G.GameBoy(ctx, rom, machine=machine, sample_rate=0)
    marks = sorted({int(frames * (k + 1) / checkpoints) - 1 for k in range(checkpoints)})
    hashes, stats = [], None
    for i in range(frames):
        g.set_buttons(script(i))
        g.run_frame()
        if machine.get("locked"):
            break
        if i in marks:
            f = g.frame()
            hashes.append(hashlib.sha1(f).hexdigest()[:12])
            stats = G.frame_stats(f)
    f = g.frame()
    st = G.frame_stats(f)
    locked = bool(machine.get("locked"))
    distinct = len(set(hashes))
    flat = st["colours"] <= 1
    if locked:
        status, reason = "locked", f"illegal opcode near PC {machine.get('PC'):#06x}"
    elif distinct <= 1 and flat:
        status, reason = "blank", "every checkpoint frame is one colour"
    elif distinct <= 1:
        status, reason = "static", "drawn, but no checkpoint frame differs"
    else:
        status, reason = "runs", f"{distinct} distinct checkpoint frames"
    if shots_dir is not None:
        shots_dir.mkdir(parents=True, exist_ok=True)
        (shots_dir / f"{hashlib.sha1(rom).hexdigest()[:10]}_{status}.png").write_bytes(G.png(f))
    return {"file": path.name, "title": info["title"], "sha1": info["sha1"], "mbc": info["mbc"],
            "cgb": info["cgb"], "supported": info["supported"], "status": status, "reason": reason,
            "frames": frames, "distinct_frames": distinct, "last_frame": st, "pc": machine.get("PC"),
            "instructions": machine.get("instructions"), "seconds": round(time.perf_counter() - t0, 3),
            "unsupported_mapper": not info["supported"], "checkpoint_stats": stats}


def run(ctx, folder, frames: int = 1200, engine: str = "native", limit: int | None = None,
        shots_dir: Path | None = None, progress=None) -> dict:
    ir = Bd.module(ctx, "gameboy")
    machine = N.load(ctx, ir, engine)
    rows = []
    paths = roms_in(folder)[:limit] if limit else roms_in(folder)
    for k, p in enumerate(paths):
        resources.guard("survey")
        r = boot_one(ctx, machine, p, frames, shots_dir=shots_dir)
        rows.append(r)
        if progress:
            progress(k + 1, len(paths), r)
    counts: dict = {}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    unsupported = sum(1 for r in rows if r.get("unsupported_mapper"))
    return {"folder_files": len(paths), "frames": frames, "engine": machine.engine, "counts": counts,
            "unsupported_mappers": unsupported, "runs_fraction": round(counts.get("runs", 0) / max(1, len(rows)), 4),
            "rows": rows}


__all__ = ["boot_one", "roms_in", "run", "script"]
