"""testroms — run hardware test ROMs and read their own verdicts.

Freely licensed test suites report results in ways a headless machine can read:

* Blargg's tests (cpu_instrs, instr_timing, mem_timing, halt_bug, ...): text over the serial port ("Passed",
  "Failed"), and the memory protocol at 0xA000 (signature DE B0 61 at A001-A003, status at A000: 0x80 still
  running, 0x00 passed, anything else the failure code; text from A004);
* mooneye-test-suite: at the end the registers B C D E H L hold 3 5 8 13 21 34 (pass) or 0x42 everywhere
  (fail), and the same six bytes go out over the serial port;
* screen tests (dmg-acid2, cgb-acid2): the picture must equal the suite's reference image (``reference*.png``
  next to the ROM, in the suite's repository).

Which model runs a test: mooneye names the hardware after the last ``-`` of the file name (revisions such as
``dmgABC``, ``cgb0``, groups such as ``G`` = DMG + MGB, or several joined: ``dmgABCmgb``, ``GS``). A test runs on
the model whose revision (the machine card's ``revisions``) it names; one for other hardware is ``skipped``
with the reason, not counted. Without a suffix the cartridge header decides.

``run(ctx, folder)`` finds every .gb/.gbc below the folder and runs it until it reports (or a time limit),
recording pass / fail / timeout / skipped with the detail. The ROMs are read where they are; nothing is copied.

Honest limits (L1): a timeout is a failure to report, not a pass; a DMG test meant for a CGB in its
DMG-compatibility mode is skipped (that mode is not modelled).
"""
from __future__ import annotations

from pathlib import Path

from . import gb as G

FIB = (3, 5, 8, 13, 21, 34)
# mooneye's hardware names, longest first so that ``dmgABCmgb`` reads as dmgABC + mgb
REVISION_TOKENS = ("cgbABCDE", "dmgABC", "dmg0", "sgb2", "cgb0", "mgb", "sgb", "cgb", "agb", "ags",
                   "G", "S", "C", "A")
GROUPS = {"G": ("dmg0", "dmgABC", "mgb"), "S": ("sgb", "sgb2"), "C": ("cgb0", "cgbABCDE"), "A": ("agb", "ags"),
          "cgb": ("cgb0", "cgbABCDE")}
# folders of the suites that hold no self-checking test, and suites meaningful on one model only
NOT_TESTS = {"utils": "a utility, not a test", "manual-only": "a person compares the screen",
             "madness": "MGB-only edge cases"}
FOLDER_MODEL = {"oam_bug": "dmg"}            # the OAM corruption bug exists on the DMG only
DMG_GREYS = (0xFF, 0xAA, 0x55, 0x00)         # the four DMG shades as the screen tests' references draw them
SCREEN_FRAMES = 30                           # acid2 draws its picture within ten frames and keeps it


def revisions_named(stem: str) -> set | None:
    """The hardware revisions a mooneye-style file name is for, or None when it names none."""
    if "-" not in stem:
        return None
    tail, out = stem.rsplit("-", 1)[1], set()
    while tail:
        tok = next((t for t in REVISION_TOKENS if tail.startswith(t)), None)
        if tok is None:
            return None
        out.update(GROUPS.get(tok, (tok,)))
        tail = tail[len(tok):]
    return out


def model_for(ctx, path: Path, info: dict) -> tuple[str | None, str]:
    """("dmg" / "cgb" / "auto", "") for a test this machine runs, (None, reason) for one it skips."""
    for folder, why in NOT_TESTS.items():
        if folder in path.parts:
            return None, why
    revs = revisions_named(path.stem)
    if revs is not None:
        for model, rev in (ctx.store.get("machine/gameboy").get("revisions") or {}).items():
            if rev in revs:
                if model == "cgb" and not info["cgb"]:
                    return None, "for a CGB in DMG-compatibility mode (not modelled)"
                return model, ""
        return None, "for other hardware: " + ", ".join(sorted(revs))
    for folder, model in FOLDER_MODEL.items():
        if folder in path.parts:
            return model, ""
    return "auto", ""


def reference_image(path: Path, cgb: bool) -> Path | None:
    """The suite's reference picture for this ROM on this model: ``reference-dmg.png`` for the DMG, the plain
    ``reference.png`` (or ``reference-cgb.png`` for a CGB cartridge) for the CGB."""
    refs = {r.stem: r for r in sorted(path.parent.rglob("reference*.png"))}
    if not cgb:
        return refs.get("reference-dmg")
    return refs.get("reference") or refs.get("reference-cgb")


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


def screen_verdict(ctx, g, ref: Path, shots: Path | None) -> tuple[str, str]:
    """Compare the machine's picture with the reference, pixel by pixel (DMG shades mapped to the reference's
    greys through the PPU card's shade table)."""
    w, h, want = G.png_read(ref.read_bytes())
    got = g.frame()
    if not g.cgb:
        shades = {bytes(c): i for i, c in enumerate(ctx.store.get("hardware/gb_ppu").get("dmg_shades_rgb"))}
        got = b"".join(bytes((DMG_GREYS[shades[got[i:i + 3]]],) * 3) if got[i:i + 3] in shades else b"\x01\x02\x03"
                       for i in range(0, len(got), 3))
    if (w, h) != (160, 144) or len(got) != len(want):
        return "fail", f"reference {ref.name} is {w}x{h}"
    bad = [i // 3 for i in range(0, len(got), 3) if got[i:i + 3] != want[i:i + 3]]
    if not bad:
        return "pass", f"screen identical to {ref.name}"
    if shots is not None:
        shots.mkdir(parents=True, exist_ok=True)
        (shots / f"{ref.parent.parent.name}-{'cgb' if g.cgb else 'dmg'}.png").write_bytes(G.png(g.frame()))
    rows = sorted({p // 160 for p in bad})
    return "fail", (f"{len(bad)} of {w * h} pixels differ from {ref.name} (rows {rows[0]}-{rows[-1]}, "
                    f"first at x={bad[0] % 160} y={bad[0] // 160})")


def run_one(ctx, path: Path, engine: str = "native", max_frames: int = 7200, root: Path | None = None,
            shots: Path | None = None) -> dict:
    rom, _ = G.open_rom(path)
    name = str(path.relative_to(root)) if root else path.name
    info = G.header(rom, ctx.store)
    model, why = model_for(ctx, path.relative_to(root) if root else Path(path.name), info)
    if model is None:
        return {"file": name, "verdict": "skipped", "detail": why, "frames": 0}
    g = G.GameBoy(ctx, rom, engine, model=model, sample_rate=0, fresh=True)
    ref = reference_image(path, bool(g.cgb))
    if ref is not None:
        for _ in range(SCREEN_FRAMES):
            g.run_frame()
        v, detail = screen_verdict(ctx, g, ref, shots)
        return {"file": name, "verdict": v, "detail": detail, "frames": SCREEN_FRAMES, "model": _model(g)}
    for f in range(max_frames):
        g.run_frame()
        if g.m.get("locked"):
            return {"file": name, "verdict": "fail", "detail": f"CPU locked near {g.m.get('PC'):#06x}",
                    "frames": f + 1, "model": _model(g)}
        if f % 30 == 29 or f == max_frames - 1:
            v = verdict(g)
            if v:
                return {"file": name, "verdict": v[0], "detail": v[1], "frames": f + 1, "model": _model(g)}
    return {"file": name, "verdict": "timeout", "detail": g.serial_text().strip()[-200:], "frames": max_frames,
            "model": _model(g)}


def _model(g) -> str:
    return "cgb" if g.cgb else "dmg"


def run(ctx, folder, engine: str = "native", max_frames: int = 7200) -> dict:
    root = Path(folder).expanduser()
    shots = ctx.state_root / "emu" / "testroms"
    rows = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in (".gb", ".gbc"):
            rows.append(run_one(ctx, p, engine, max_frames, root=root, shots=shots))
    ran = [r for r in rows if r["verdict"] != "skipped"]
    suites: dict = {}
    for r in ran:
        s = suites.setdefault(Path(r["file"]).parts[0] if len(Path(r["file"]).parts) > 1 else ".", [0, 0])
        s[0] += r["verdict"] == "pass"
        s[1] += 1
    return {"total": len(ran), "passed": sum(1 for r in ran if r["verdict"] == "pass"),
            "skipped": len(rows) - len(ran), "engine": engine,
            "suites": {k: {"passed": v[0], "total": v[1]} for k, v in sorted(suites.items())}, "rows": rows}


__all__ = ["model_for", "reference_image", "revisions_named", "run", "run_one", "screen_verdict", "verdict"]
