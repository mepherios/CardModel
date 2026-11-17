"""process — run a foreign program (an ELF executable for another CPU and OS) on the card model.

The program's CPU is its ISA's instruction cards, its operating system is an ``os`` card (system calls as card
logic), and both compile with a process machine card into one card-IR module that runs in any engine: the
reference interpreter, Python, or C compiled to native code for this computer. Nothing here knows MIPS or Linux:
the ELF layout, which ISA an ``e_machine`` names and which machine runs it are card data (``format/elf32``), and
the process's memory layout comes from the os card.

The host's part is the effect shell (CM21): it loads the file, writes the start state (argc, argv, envp, auxv) the
os card describes, feeds standard input, runs the machine in slices and drains its output.

Honest limits (L1): 32-bit little-endian ELF executables, statically linked (a program that asks for a dynamic
loader, PT_INTERP, is refused); one thread; the os card's system calls only (others answer ENOSYS and are
counted in ``unknown_syscalls``); no signals; no floating-point unit yet (programs built with soft float).
"""
from __future__ import annotations

import struct
import time
from pathlib import Path

from . import build as Bd
from . import native as N

SLICE = 1_000_000


class LoadError(ValueError):
    pass


def _field(data: bytes, at: int, spec, little: bool) -> int:
    off, size = spec
    return int.from_bytes(data[at + off:at + off + size], "little" if little else "big")


def read_elf(store, data: bytes) -> dict:
    """The executable's header and loadable segments, read by the ``format/elf32`` card's layout."""
    lay = store.get("format/elf32")
    k = lay["constants"]
    if data[:4] != b"\x7fELF":
        raise LoadError("not an ELF file")
    if data[4] != k["ELFCLASS32"]:
        raise LoadError("not a 32-bit ELF file (64-bit programs need a 64-bit ISA card, which does not exist yet)")
    little = data[5] == k["ELFDATA2LSB"]
    h = {name: _field(data, 0, spec, little) for name, spec in lay["header"].items()}
    isa = (lay.get("isa_of_machine") or {}).get(str(h["e_machine"]))
    if isa is None:
        raise LoadError(f"no ISA card for ELF machine {h['e_machine']}")
    segs, interp = [], False
    for i in range(h["e_phnum"]):
        at = h["e_phoff"] + i * h["e_phentsize"]
        p = {name: _field(data, at, spec, little) for name, spec in lay["program_header"].items()}
        if p["p_type"] == k["PT_INTERP"]:
            interp = True
        if p["p_type"] == k["PT_LOAD"]:
            segs.append(p)
    if interp:
        raise LoadError("the program asks for a dynamic loader (PT_INTERP): only static executables run yet")
    if h["e_type"] not in (k["ET_EXEC"], k["ET_DYN"]):
        raise LoadError(f"ELF type {h['e_type']:#x} is not an executable")
    return {"little": little, "isa": isa, "machine": lay["machine_of_isa"][isa], "entry": h["e_entry"],
            "segments": segs, "header": h}


class Process:
    """A foreign program loaded into its machine: ``run()``, then ``stdout``, ``stderr``, ``exit_code``."""

    def __init__(self, ctx, program, argv: list[str] | None = None, env: list[str] | None = None,
                 stdin: bytes = b"", engine: str = "native", variant: str | None = None, fresh: bool = True,
                 lifted: bool = False):
        data = Path(program).read_bytes() if not isinstance(program, (bytes, bytearray)) else bytes(program)
        self.ctx = ctx
        self.elf = read_elf(ctx.store, data)
        if not self.elf["little"]:
            raise LoadError("big-endian programs need a big-endian bus in the machine card (not built yet)")
        self.machine_card = ctx.store.get(f"machine/{self.elf['machine']}")
        self.os = ctx.store.get(self.machine_card["components"][0])
        self.lifted = lifted
        self.lift_stats: dict = {}
        if lifted:
            from . import lift_elf
            self.ir, self.lift_stats = lift_elf.module(ctx, self.elf["machine"], data, self.elf)
        else:
            self.ir = Bd.module(ctx, self.elf["machine"])
        self.engine = N.resolve_engine(ctx, engine)
        self.m = N.load(ctx, self.ir, self.engine, fresh=fresh) if self.engine != "ir" else N.load(ctx, self.ir, "ir")
        self.m.call("reset_all")
        lay = self.os["layout"]
        size = lay["memory_bytes"]
        top = 0
        for s in self.elf["segments"]:
            end = s["p_vaddr"] + s["p_memsz"]
            if s["p_vaddr"] < 0x1000 or end > lay["mmap_top"]:
                raise LoadError(f"segment at {s['p_vaddr']:#x}..{end:#x} is outside the process's memory "
                                f"(0x1000..{lay['mmap_top']:#x})")
            self.m.write("mem", data[s["p_offset"]:s["p_offset"] + s["p_filesz"]], s["p_vaddr"])
            top = max(top, end)
            if s["p_flags"] & 1:                                  # PF_X: the program's code
                lo, hi = self.m.get("code_lo"), self.m.get("code_hi")
                self.m.set("code_lo", s["p_vaddr"] if hi == 0 else min(lo, s["p_vaddr"]))
                self.m.set("code_hi", max(hi, s["p_vaddr"] + s["p_filesz"]))
        brk = (top + 0xFFF) & ~0xFFF
        self.m.set("brk_start", brk)
        self.m.set("brk_cur", brk)
        isa = ctx.store.get(f"isa/{self.elf['isa']}")
        if variant is not None:
            self.m.set("variant", isa["variants"][variant])
        sp = self._start_stack(argv or [Path(str(program)).name if not isinstance(program, (bytes, bytearray)) else "a.out"],
                               env or [], lay["stack_top"], size)
        regs = self.m.array("regs")
        regs[29] = sp
        self.m.set("pc", self.elf["entry"])
        if stdin:
            self.m.write("inp", stdin[:0x100000])
            self.m.set("inp_len", min(len(stdin), 0x100000))
        self._out, self._err = bytearray(), bytearray()
        self.seconds = 0.0

    def _start_stack(self, argv, env, top: int, size: int) -> int:
        """argc, argv[], 0, envp[], 0, auxv (AT_PAGESZ, AT_NULL) as the os card's start state says."""
        strings = bytearray()
        offs = []
        for s in [*argv, *env]:
            offs.append(len(strings))
            strings += s.encode() + b"\0"
        base = (top - len(strings)) & ~15
        self.m.write("mem", bytes(strings), base)
        ptrs = [len(argv)] + [base + o for o in offs[:len(argv)]] + [0] + [base + o for o in offs[len(argv):]] + [0]
        ptrs += [6, 4096, 0, 0]                                  # AT_PAGESZ 4096, AT_NULL
        sp = (base - 4 * len(ptrs)) & ~15
        self.m.write("mem", struct.pack(f"<{len(ptrs)}I", *ptrs), sp)
        return sp

    def _drain(self) -> None:
        for name, buf in (("out", self._out), ("err", self._err)):
            n = self.m.get(f"{name}_len")
            if n:
                buf += self.m.read(name, 0, n)
                self.m.set(f"{name}_len", 0)

    def run(self, max_steps: int = 10**10) -> dict:
        t0 = time.perf_counter()
        left = max_steps
        while left > 0 and self.m.get("state") == 0:
            ran = self.m.call("run_lifted" if self.lifted else "run", min(SLICE, left))
            left -= ran
            self._drain()
        self._drain()
        self.seconds += time.perf_counter() - t0
        return self.result()

    @property
    def stdout(self) -> bytes:
        return bytes(self._out)

    @property
    def stderr(self) -> bytes:
        return bytes(self._err)

    def result(self) -> dict:
        g = self.m.get
        state = {0: "running", 1: "exited", 2: "faulted"}[g("state")]
        r = {"state": state, "exit_code": g("exit_code") if state == "exited" else None, "steps": g("steps"),
             "seconds": round(self.seconds, 4), "engine": self.engine, "isa": self.elf["isa"],
             "machine": self.elf["machine"], "syscalls": g("syscalls"), "unknown_syscalls": g("unknown_syscalls"),
             "stdout": self.stdout.decode("utf-8", "replace"), "stderr": self.stderr.decode("utf-8", "replace"),
             "output_dropped": g("out_dropped")}
        if self.lifted:
            r["lifted"] = {**self.lift_stats, "interpreted": g("interpreted")}
        if g("unknown_syscalls"):
            r["last_unknown_syscall"] = g("last_unknown")
        if state == "faulted":
            r["fault"] = {"code": g("fault_code"), "addr": g("fault_addr"), "pc": g("fault_pc")}
        if self.seconds and r["steps"]:
            r["mips_per_second"] = round(r["steps"] / self.seconds / 1e6, 2)
        return r


def run(ctx, program, **kw) -> dict:
    max_steps = kw.pop("max_steps", 10**10)
    return Process(ctx, program, **kw).run(max_steps)


__all__ = ["LoadError", "Process", "read_elf", "run"]
