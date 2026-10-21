"""diff — differential runs: the lifted engine against the interpreter, frame by frame.

Both machines get the same scripted input; after every frame their state hashes (CPU registers, time, the
frame, work RAM, HRAM) must be equal. The first frame that differs is reported; a planted difference in a
lifted block must be caught (tests/test_machine.py). Timing of both is measured on this host.

Honest limits (L1): equal hashes on these frames are evidence for this input, not a proof for every input;
the script presses START and A periodically (survey.script).
"""
from __future__ import annotations

import time

from . import gb as G
from . import lift
from .survey import script


def differential(ctx, rom: bytes, frames: int = 1200) -> dict:
    m, rep = lift.lifted_machine(ctx, rom)
    lifted = G.GameBoy(ctx, rom, machine=m, sample_rate=0)
    m.set("lifted_on", 1)
    ref = G.GameBoy(ctx, rom, "native", sample_rate=0, fresh=True)
    ti = tl = 0.0
    first = None
    for f in range(frames):
        b = script(f)
        ref.set_buttons(b)
        lifted.set_buttons(b)
        t0 = time.perf_counter()
        ref.run_frame()
        ti += time.perf_counter() - t0
        t0 = time.perf_counter()
        lifted.run_frame()
        tl += time.perf_counter() - t0
        if ref.state_hash() != lifted.state_hash():
            first = f
            break
    n = frames if first is None else first + 1
    return {"verdict": "identical" if first is None else "different", "frames_compared": n,
            "first_difference": first, "interp_s": round(ti, 3), "lifted_s": round(tl, 3),
            "speedup": round(ti / tl, 2) if tl else None, "blocks": rep["blocks"],
            "block_runs": m.get("block_runs"), "instructions": m.get("instructions"), "lift": rep}


__all__ = ["differential"]
