"""process — the effect shell for a foreign program (an ELF executable for another CPU and OS).

Everything that decides anything is card logic: the program's CPU is its ISA's instruction cards, its operating
system is an ``os`` card (system calls and the process's start state), and its file format is a ``format`` card
(``probe.card`` says which machine runs a file, ``load.card`` loads it). They compile with a process machine card
into one card-IR module that runs in any engine: the reference interpreter, Python, or C compiled to native code
for this computer.

What this file does is only what the card model's pure core must not (CM21): read the file and hand its bytes to
the cards, hand over the argument strings and standard input, run the machine in slices, drain its output, time
it, and turn the cards' error codes into the cards' messages.

Honest limits (L1): 32-bit little-endian static ELF executables; one thread; the os card's system calls only
(others answer ENOSYS and are counted in ``unknown_syscalls``); no signals; no floating-point unit yet.
"""
from __future__ import annotations

import time
from pathlib import Path

from ..lang.compile import compile_sources
from . import build as Bd
from . import native as N

SLICE = 1_000_000


class LoadError(ValueError):
    pass


def _probe_module(ctx) -> dict:
    fc = ctx.store.get("format/elf32")
    text = (fc.path / fc["probe"]).read_text(encoding="utf-8")
    return compile_sources([(text, "format/elf32/probe.card")], ctx.ops, ctx.store, name="elf32_probe").ir_module(None)


def machine_for(ctx, data: bytes) -> str:
    """Which machine card runs this file, by the format card's own probe (card logic, reference interpreter)."""
    fc = ctx.store.get("format/elf32")
    m = N.load(ctx, _probe_module(ctx), "ir")
    head = data[:64]
    m.write("hdr", head)
    m.set("hdr_len", len(head))
    code = m.call("elf_machine")
    if code < 0:
        raise LoadError(fc["load_errors"][str(-code)])
    name = (fc.get("machine_of_e_machine") or {}).get(str(code))
    if name is None:
        raise LoadError(f"no machine card runs ELF machine {code}")
    return name


class Process:
    """A foreign program loaded into its machine: ``run()``, then ``stdout``, ``stderr``, ``exit_code``."""

    def __init__(self, ctx, program, argv: list[str] | None = None, env: list[str] | None = None,
                 stdin: bytes = b"", engine: str = "native", variant: str | None = None, fresh: bool = True,
                 lifted: bool = False):
        data = bytes(program) if isinstance(program, (bytes, bytearray)) else Path(program).read_bytes()
        self.ctx = ctx
        self.machine = machine_for(ctx, data)
        mc = ctx.store.get(f"machine/{self.machine}")
        self.isa = mc["isa"]
        fc = ctx.store.get("format/elf32")
        if len(data) > fc["file_max"]:
            raise LoadError(f"the file is larger than the format card's file_max ({fc['file_max']} bytes)")
        self.lifted = lifted
        self.lift_stats: dict = {}
        if lifted:
            from . import lift_elf
            self.ir, self.lift_stats = lift_elf.module(ctx, self.machine, data)
        else:
            self.ir = Bd.module(ctx, self.machine)
        self.engine = N.resolve_engine(ctx, engine)
        self.m = N.load(ctx, self.ir, self.engine, fresh=fresh)
        self.m.call("reset_all")
        self.m.write("file", data)
        self.m.set("file_len", len(data))
        err = self.m.call("load_elf", mc["e_machine"])
        if err:
            raise LoadError(fc["load_errors"][str(err)])
        if variant is not None:
            self.m.set("variant", ctx.store.get(f"isa/{self.isa}")["variants"][variant])
        argv = argv or ["a.out" if isinstance(program, (bytes, bytearray)) else Path(str(program)).name]
        env = env or []
        strings = b"".join(s.encode() + b"\0" for s in [*argv, *env])
        self.m.write("args", strings)
        self.m.set("args_len", len(strings))
        self.m.call("start_process", len(argv), len(env))
        if stdin:
            self.m.write("inp", stdin[:0x100000])
            self.m.set("inp_len", min(len(stdin), 0x100000))
        self._out, self._err = bytearray(), bytearray()
        self.seconds = 0.0

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
             "seconds": round(self.seconds, 4), "engine": self.engine, "isa": self.isa,
             "machine": self.machine, "syscalls": g("syscalls"), "unknown_syscalls": g("unknown_syscalls"),
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


__all__ = ["LoadError", "Process", "machine_for", "run"]
