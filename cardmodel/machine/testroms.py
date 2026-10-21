"""testroms — run hardware test ROMs and read their own verdicts.

Freely licensed test suites report results in ways a headless machine can read:

* Blargg's tests (cpu_instrs, instr_timing, mem_timing, halt_bug, ...): text over the serial port ("Passed",
  "Failed"), and the memory protocol at 0xA000 (signature DE B0 61 at A001-A003, status at A000: 0x80 still
  running, 0x00 passed, anything else the failure code; text from A004);
* mooneye-test-suite: at the end the registers B C D E H L hold 3 5 8 13 21 34 (pass) or 0x42 everywhere
  (fail), and the same six bytes go out over the serial port.

``run(ctx, folder)`` finds every .gb/.gbc below the folder and runs it until it reports (or a time limit),
recording pass / fail / timeout with the detail. The ROMs are read where they are; nothing is copied.

Honest limits (L1): screen-only tests (dmg-acid2 and similar) need their reference image and are reported
``needs-reference``; a timeout is a failure to report, not a pass.
"""
from __future__ import annotations

from pathlib import Path

from . import gb as G

FIB = (3, 5, 8, 13, 21, 34)


def verdict(g) -> tuple[str, str] | None:
    m = g.m
    serial = g.serial_text()
    if "Passed" in serial:
        return "pass", serial.strip()[-200:]
    if "Failed" in serial:
        return "fail", serial.strip()[-200:]
    raw = serial.encode("latin-1")
    if raw.endswith(bytes(FIB)):
        return "pass", "mooneye: serial 3 5 8 13 21 34"
    if raw.endswith(b"\x42" * 6):
        return "fail", "mooneye: serial 0x42 x6"
    regs = tuple(m.get(r) for r in ("B", "C", "D", "E", "H", "L"))
    if regs == FIB:
        return "pass", "mooneye: registers 3 5 8 13 21 34"
    if regs == (0x42,) * 6:
        return "fail", "mooneye: registers 0x42"
    sig = [g.m.array("cram")[i] for i in range(1, 4)] if g.info["ram_size"] else []
    if sig == [0xDE, 0xB0, 0x61]:
        status = g.m.array("cram")[0]
        if status != 0x80:
            text = bytes(g.m.array("cram")[4:4 + 512]).split(b"\0")[0].decode("latin-1", "replace").strip()
            return ("pass" if status == 0 else "fail"), f"A000 status {status:#04x}: {text[-200:]}"
    return None


def run_one(ctx, path: Path, engine: str = "native", max_frames: int = 7200, model: str = "auto") -> dict:
    rom, name = G.open_rom(path)
    g = G.GameBoy(ctx, rom, engine, model=model, sample_rate=0, fresh=True)
    for f in range(max_frames):
        g.run_frame()
        if g.m.get("locked"):
            return {"file": str(path.name), "verdict": "fail", "detail": f"CPU locked near {g.m.get('PC'):#06x}",
                    "frames": f + 1}
        if f % 30 == 29 or f == max_frames - 1:
            v = verdict(g)
            if v:
                return {"file": str(path.name), "verdict": v[0], "detail": v[1], "frames": f + 1}
    return {"file": str(path.name), "verdict": "timeout", "detail": g.serial_text().strip()[-200:],
            "frames": max_frames}


def run(ctx, folder, engine: str = "native", max_frames: int = 7200) -> dict:
    rows = []
    for p in sorted(Path(folder).expanduser().rglob("*")):
        if p.is_file() and p.suffix.lower() in (".gb", ".gbc"):
            rows.append(run_one(ctx, p, engine, max_frames))
    passed = sum(1 for r in rows if r["verdict"] == "pass")
    return {"total": len(rows), "passed": passed, "engine": engine, "rows": rows}


__all__ = ["run", "run_one", "verdict"]
