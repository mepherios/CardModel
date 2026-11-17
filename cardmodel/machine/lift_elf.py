"""lift_elf — a foreign program's code translated ahead of time into card-language blocks, compiled natively.

The interpreter (``process.card``'s ``run``) fetches and decodes every instruction word as it runs. Here the
program's executable segments are read once: each instruction word is decoded by the same instruction cards
(``bench.decoded_by``, the decoder the generated dispatch implements) and every block becomes one card-language
function that calls those cards with constant words. The machine module plus these blocks is emitted through the
C language card, and the C compiler inlines the cards and folds every field extraction, so the program runs as
straight-line native code of this computer, with no fetch and no decode. Nothing here is hand-written per
instruction: the semantics are the cards'.

Leaders (where a block starts): the entry point, every direct branch and jump target, the instruction after
each call's delay slot (where a call returns), and every word in the program's data that points at an
instruction (function pointers, switch tables). A block runs until a jump, a word no card decodes, or
``MAX_BLOCK`` instructions; a conditional branch that is not taken continues the block with its delay slot. Any
other address (a target found only at run time) runs in the interpreter, one instruction at a time, and is
counted (``interpreted``); so is everything after the program writes into its own code (``code_dirty``).

The witness is the differential run: the lifted program and the interpreter must end in the same state, output
and instruction count (tests/test_foreign.py).

Honest limits (L1): MIPS only (the block rules know delay slots); a branch whose delay slot holds another branch
ends the block before it (the interpreter runs that pair); code is lifted from the file, so a program that
generates code runs that code interpreted.
"""
from __future__ import annotations

import hashlib
import json

from ..lang.compile import compile_sources
from . import build as Bd
from . import isa as I
from .bench import decoded_by

MAX_BLOCK = 64
PURE_GROUPS = {"shift", "move", "hilo", "multiply", "divide", "bits", "alu"}
MAY_FAULT = {"MIPS_ADD", "MIPS_SUB", "MIPS_ADDI"}
JUMPS = {"MIPS_J", "MIPS_JAL", "MIPS_JR", "MIPS_JALR"}
CALLS = {"MIPS_JAL", "MIPS_JALR", "MIPS_BLTZAL", "MIPS_BGEZAL", "MIPS_BLTZALL", "MIPS_BGEZALL"}
ENDS = {"MIPS_BREAK"}


def _sx16(v: int) -> int:
    return v - 0x10000 if v & 0x8000 else v


class Code:
    """The program's words by address, decoded by the instruction cards."""

    def __init__(self, store, isa: str, data: bytes, elf: dict):
        self.cards = I.instructions(store, isa)
        self.words: dict = {}
        self.data_words: list = []
        for s in elf["segments"]:
            chunk = data[s["p_offset"]:s["p_offset"] + s["p_filesz"]]
            base = s["p_vaddr"]
            for i in range(0, len(chunk) - 3, 4):
                w = int.from_bytes(chunk[i:i + 4], "little")
                if s["p_flags"] & 1:                    # PF_X
                    self.words[base + i] = w
                else:
                    self.data_words.append(w)
        self.lo = min(self.words, default=0)
        self.hi = max(self.words, default=-4) + 4
        self._dec: dict = {}

    def card(self, a: int):
        if a not in self._dec:
            w = self.words.get(a)
            self._dec[a] = None if w is None else decoded_by(self.cards, w, "mips")
        return self._dec[a]

    def target(self, a: int, c, w: int) -> int | None:
        """A direct branch's or jump's target, or None (through a register)."""
        if c.name in ("MIPS_J", "MIPS_JAL"):
            return ((a + 4) & 0xF0000000) | ((w & 0x3FFFFFF) << 2)
        if c["group"] == "branch" and c.name not in ("MIPS_JR", "MIPS_JALR"):
            return (a + 4 + (_sx16(w & 0xFFFF) << 2)) & 0xFFFFFFFF
        return None

    def leaders(self, entry: int) -> list[int]:
        out = {entry}
        for a, w in self.words.items():
            c = self.card(a)
            if c is None or c["group"] != "branch":
                continue
            t = self.target(a, c, w)
            if t is not None and t in self.words:
                out.add(t)
            if c.name in CALLS and a + 8 in self.words:
                out.add(a + 8)
        out.update(w for w in self.data_words if w in self.words and w % 4 == 0)
        return sorted(a for a in out if self.card(a) is not None)


def _call(c, w: int) -> str:
    return f"  {c.name}({w:#x})"


def block_source(code: Code, start: int) -> tuple[str, int, int | None]:
    """One block as a card-language function returning how many instructions it ran, and the address where it
    stops without a jump (None after a jump), which is a leader too."""
    lines = [f"fn blk_{start:x}() -> Int {{"]
    a, k = start, 0
    while k < MAX_BLOCK:
        c = code.card(a)
        if c is None or c.name in ENDS:
            break
        w = code.words[a]
        if c["group"] == "branch":
            sa = a + 4
            sc = code.card(sa)
            if sc is None or sc["group"] == "branch" or sc.name in ENDS:
                break                                   # a branch in a delay slot: leave it to the interpreter
            lines += [f"  pc = {a:#x}", f"  next_pc = {(a + 4):#x}", _call(c, w),
                      "  if bpending != 0 {", "    bpending = 0", f"    pc = {sa:#x}",
                      "  " + _call(sc, code.words[sa]), "    if state != 0 {", f"      return {k + 2}", "    }",
                      "    pc = btarget", f"    return {k + 2}", "  }",
                      f"  if next_pc != {(a + 4):#x} {{", "    pc = next_pc", f"    return {k + 1}", "  }"]
            k += 1
            a += 4
            if c.name in JUMPS:                         # always taken: the block ends here
                lines += [f"  pc = {a:#x}", f"  return {k}", "}"]
                return "\n".join(lines) + "\n", k, None
            continue
        if not (c["group"] in PURE_GROUPS and c.name not in MAY_FAULT and c.get("arch") == "mips32"):
            lines += [f"  pc = {a:#x}", _call(c, w), "  if state != 0 {", f"    return {k + 1}", "  }"]
        else:
            lines.append(_call(c, w))
        k += 1
        a += 4
    lines += [f"  pc = {a:#x}", f"  return {k}", "}"]
    return "\n".join(lines) + "\n", k, a


def lifted_source(code: Code, entry: int) -> tuple[str, dict]:
    blocks, cases, sizes, starts = [], [], [], []
    todo, seen = list(code.leaders(entry)), set()
    while todo:
        a = todo.pop()
        if a in seen:
            continue
        seen.add(a)
        src, n, stop = block_source(code, a)
        if stop is not None and stop not in seen and code.card(stop) is not None:
            todo.append(stop)                          # where this block stops, the next one starts
        if n == 0:
            continue
        blocks.append(src)
        cases.append(f"    case {a:#x} {{\n      return blk_{a:x}()\n    }}")
        sizes.append(n)
        starts.append(a)
    driver = f"""
global interpreted: Int = 0
fn lifted_block(a: Int) -> Int {{
  switch a {{
{chr(10).join(cases)}
  }}
  return 0
}}
-- like run(n), through the lifted blocks; anything else (and code the program rewrote) in the interpreter
export fn run_lifted(n: Int) -> Int {{
  var k = 0
  while k < n and state == 0 {{
    var c = 0
    if in_slot == 0 and code_dirty == 0 {{
      c = lifted_block(pc)
    }}
    if c == 0 {{
      if (pc & 3) != 0 or pc + 4 > MEM_SIZE {{
        fault(EXC_ADEL, pc)
      }} else {{
        step(ld32(pc))
        interpreted += 1
        c = 1
      }}
    }}
    k += c
  }}
  steps += k
  return k
}}
"""
    stats = {"blocks": len(blocks), "lifted_instructions": sum(sizes), "code_words": len(code.words),
             "covered_words": len({a + 4 * i for a, n in zip(starts, sizes) for i in range(n)})}
    return "\n".join(blocks) + driver, stats


def module(ctx, machine: str, data: bytes, elf: dict) -> tuple[dict, dict]:
    """The machine module with the program's lifted blocks and ``run_lifted`` (cached by content)."""
    srcs, externs, mc = Bd.sources(ctx.store, machine)
    code = Code(ctx.store, mc["isa"], data, elf)
    text, stats = lifted_source(code, elf["entry"])
    srcs = [*srcs, (text, f"lifted program ({len(code.words)} words)")]
    h = hashlib.sha256()
    for t, label in srcs:
        h.update(label.encode() + b"\0" + t.encode() + b"\0")
    h.update(json.dumps(externs, sort_keys=True).encode())
    for comp in [*(mc.get("components") or []), f"machine/{machine}"]:
        h.update(json.dumps(ctx.store.get(comp if "/" in comp else f"hardware/{comp}"), sort_keys=True,
                            default=str).encode())
    key = h.hexdigest()[:20]
    cache = ctx.state_root / "machine" / f"{machine}-lifted-{key}.json"
    stats["code_lo"], stats["code_hi"] = code.lo, code.hi
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8")), stats
    mod = compile_sources(srcs, ctx.ops, ctx.store, name=f"{machine}_lifted", externs=externs)
    ir = mod.ir_module(mc.get("entry"))
    ir["functions"].append(Bd.reset_function(ir))
    if mc.get("export_state"):
        for x in (*ir.get("globals", []), *ir.get("arrays", [])):
            x["export"] = True
    ir["machine"] = machine
    ir["hash"] = key
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(ir, sort_keys=True), encoding="utf-8")
    tmp.replace(cache)
    return ir, stats


__all__ = ["Code", "block_source", "lifted_source", "module"]
