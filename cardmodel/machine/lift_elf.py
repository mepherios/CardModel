"""lift_elf — a foreign program's code translated ahead of time into card-language blocks, compiled natively.

The interpreter (``process.card``'s ``run``) fetches and decodes every instruction word as it runs. Here the
program is loaded once by its own machine's card logic (the format card's loader), its code is read back, and each
word is decoded by the instruction cards (``bench.decoded_by``, the decoder the generated dispatch implements).
Every block becomes one card-language function that calls those cards with constant words; the machine module
plus these blocks is emitted through the C language card, and the C compiler inlines the cards and folds every
field extraction, so the program runs as straight-line native code with no fetch and no decode.

**No instruction is known here by name.** What the block former needs about a word comes from that word's card,
read as mathematics (``symbolic.Executor``: the card's IR executed with the word constant, every register a
variable):

* it is a control transfer when its terms write ``bpending``; always taken when that term is the constant 1;
* its target is the taken value of ``btarget``, when that term depends on ``pc`` only (a direct branch or jump);
* it skips its delay slot when not taken (a branch-likely) when it writes ``next_pc``;
* it is a call when it writes a register with a value that depends on ``pc`` only (the return address), and that
  value is where the call returns, so a block starts there;
* it can stop the process (so the block checks after it) when its terms have any bus or hook effect.

Leaders (where a block starts): the entry point, every direct target, every return address, every word of the
program's data that points at an instruction (function pointers, switch tables), and wherever another block
stops. A block runs until an always-taken transfer, a word no card decodes, a transfer whose delay slot is another
transfer, or ``MAX_BLOCK`` instructions; a branch that is not taken continues the block with its delay slot. Any
other address runs in the interpreter, one instruction at a time, and is counted (``interpreted``); so is
everything after the program writes into its own code (``code_dirty``).

The witness is the differential run: the lifted program and the interpreter must end in the same state, output
and instruction count (tests/test_foreign.py).

Honest limits (L1): the block rules assume the delay-slot model of the ISA's core (``bpending``/``btarget``/
``next_pc``, as the MIPS cards have it); code is lifted from the loaded image, so code a program generates runs
interpreted.
"""
from __future__ import annotations

import hashlib
import json

from ..engines.logic import eval_expr
from ..lang.compile import compile_sources
from . import build as Bd
from . import isa as I
from . import native as N
from . import symbolic as SY
from .bench import decoded_by

MAX_BLOCK = 64


def _vars(t, out: set) -> set:
    if isinstance(t, list):
        if t[:1] == ["var"] and isinstance(t[1], str):
            out.add(t[1])
        else:
            for x in t:
                _vars(x, out)
    return out


def _taken(t):
    """The value a term has on the side that changes it (IF_EXPR(c, new, old) -> new)."""
    while isinstance(t, list) and t[:1] == ["IF_EXPR"]:
        t = t[2]
    return t


class Facts:
    """What the block former needs about one word, read from its card's terms."""

    def __init__(self, res: dict, at: int, ops):
        st = res["state"]
        self.transfer = "bpending" in st
        self.always = st.get("bpending") == ["int", 1]
        self.likely = "next_pc" in st
        self.effects = bool(res["effects"])
        self.target = None
        bt = _taken(st.get("btarget"))
        if self.transfer and bt is not None and _vars(bt, set()) <= {"pc"}:
            self.target = eval_expr(bt, {"pc": at}, ops) & 0xFFFFFFFF
        self.returns_to = None
        for k, t in st.items():
            if k.startswith("regs") and _vars(t, set()) == {"pc"}:
                self.returns_to = eval_expr(t, {"pc": at}, ops) & 0xFFFFFFFF


class Code:
    """The program's words by address, decoded by the instruction cards, with each word's facts."""

    def __init__(self, ctx, isa: str, code: dict, data_words: list, entry: int):
        self.ctx = ctx
        ic = I.isa_card(ctx.store, isa)
        self.set = next(iter((ic.get("decode") or {}).get("sets") or {"": None}))
        self.cards = I.instructions(ctx.store, isa)
        self.words = code
        self.data_words = data_words
        self.entry = entry
        mod, _ = SY.module(ctx, isa)
        self.param = ic.get("operand_param", "op")
        self.ex = SY.Executor(ctx, mod)
        self._dec: dict = {}
        self._facts: dict = {}

    def card(self, a: int):
        if a not in self._dec:
            w = self.words.get(a)
            self._dec[a] = None if w is None else decoded_by(self.cards, w, self.set)
        return self._dec[a]

    def facts(self, a: int) -> Facts | None:
        if a not in self._facts:
            c = self.card(a)
            if c is None:
                self._facts[a] = None
            else:
                try:
                    res = self.ex.run(c.name, {self.param: self.words[a]})
                    self._facts[a] = Facts(res, a, self.ctx.ops)
                except SY.Unsupported:
                    self._facts[a] = None               # a card the executor can't read: not lifted
        return self._facts[a]

    def leaders(self) -> list[int]:
        out = {self.entry}
        for a in self.words:
            f = self.facts(a)
            if f is None:
                continue
            for t in (f.target, f.returns_to):
                if t is not None and t in self.words:
                    out.add(t)
        out.update(w for w in self.data_words if w in self.words)
        return sorted(a for a in out if self.facts(a) is not None)


def block_source(code: Code, start: int) -> tuple[str, int, int | None]:
    """One block as a card-language function returning how many instructions it ran, and the address where it
    stops without an always-taken transfer (None otherwise), which is a leader too."""
    lines = [f"fn blk_{start:x}() -> Int {{"]
    a, k = start, 0
    while k < MAX_BLOCK:
        f = code.facts(a)
        if f is None:
            break
        c, w = code.card(a), code.words[a]
        if f.transfer:
            sa = a + 4
            fs = code.facts(sa)
            if fs is None or fs.transfer:
                break                                   # a transfer in a delay slot: leave it to the interpreter
            slot = [f"    pc = {sa:#x}", f"    {code.card(sa).name}({code.words[sa]:#x})"]
            if fs.effects:
                slot += ["    if state != 0 {", f"      return {k + 2}", "    }"]
            lines += [f"  pc = {a:#x}", f"  next_pc = {sa:#x}", f"  {c.name}({w:#x})"]
            if f.effects:
                lines += ["  if state != 0 {", f"    return {k + 1}", "  }"]
            lines += ["  if bpending != 0 {", "    bpending = 0", *slot, "    pc = btarget", f"    return {k + 2}", "  }"]
            if f.likely:
                lines += [f"  if next_pc != {sa:#x} {{", "    pc = next_pc", f"    return {k + 1}", "  }"]
            k += 1
            a += 4
            if f.always:
                lines += [f"  pc = {a:#x}", f"  return {k}", "}"]
                return "\n".join(lines) + "\n", k, None
            continue
        if f.effects:
            lines += [f"  pc = {a:#x}", f"  {c.name}({w:#x})", "  if state != 0 {", f"    return {k + 1}", "  }"]
        else:
            lines.append(f"  {c.name}({w:#x})")
        k += 1
        a += 4
    lines += [f"  pc = {a:#x}", f"  return {k}", "}"]
    return "\n".join(lines) + "\n", k, a


def lifted_source(code: Code) -> tuple[str, dict]:
    blocks, cases, sizes, starts = [], [], [], []
    todo, seen = list(code.leaders()), set()
    while todo:
        a = todo.pop()
        if a in seen:
            continue
        seen.add(a)
        src, n, stop = block_source(code, a)
        if stop is not None and stop not in seen and code.facts(stop) is not None:
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


def loaded_image(ctx, machine: str, data: bytes) -> tuple[dict, list, int]:
    """The program as its machine's own loader (card logic) leaves it: code words by address, data words, entry."""
    mc = Bd.machine_card(ctx.store, machine)
    engine = "native"
    try:
        lang = N.resolve_engine(ctx, engine)
    except N.EngineError:
        lang = N.resolve_engine(ctx, "host")
    m = N.load(ctx, Bd.module(ctx, machine), lang, fresh=True)
    m.call("reset_all")
    m.write("file", data)
    m.set("file_len", len(data))
    if m.call("load_elf", mc["e_machine"]):
        raise ValueError("the program does not load (see Process for the reason)")
    lo, hi, top, entry = m.get("code_lo"), m.get("code_hi"), m.get("brk_start"), m.get("pc")
    img = m.read("mem", 0, top)
    code = {a: int.from_bytes(img[a:a + 4], "little") for a in range(lo, hi - 3, 4)}
    data_words = [int.from_bytes(img[a:a + 4], "little") for a in range(0x1000, top - 3, 4) if not lo <= a < hi]
    if hasattr(m, "close"):
        m.close()
    return code, data_words, entry


def module(ctx, machine: str, data: bytes) -> tuple[dict, dict]:
    """The machine module with the program's lifted blocks and ``run_lifted`` (cached by content)."""
    srcs, externs, mc = Bd.sources(ctx.store, machine)
    words, data_words, entry = loaded_image(ctx, machine, data)
    code = Code(ctx, mc["isa"], words, data_words, entry)
    text, stats = lifted_source(code)
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


__all__ = ["Code", "Facts", "block_source", "lifted_source", "loaded_image", "module"]
