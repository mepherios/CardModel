"""absint — a cartridge's code found by reasoning: constants carried through its trampolines and jump tables.

Recursive descent (lift.discover) follows a jump only when its target is written in the instruction. A far call
(``LD A,bank; LD HL,addr; RST`` into a routine that switches the bank and jumps through HL), a call after a bank
switch (``LD A,bank; RST bankswitch; CALL addr``) and a jump table (``LD HL,table; RST`` into a routine that reads
the word at HL + 2A and jumps to it) are found there only when a profile saw them run. Here they are found by an
abstract run of the machine's own cards: from the start of every block that leads into such a routine, the
instructions are executed by their instruction cards' IR, through the bus and cartridge cards (every machine
function without a loop is executed; the ones with loops, the hardware's catch-up, are opaque), over values that
are constants or unknown. The ROM's bytes are constants; so are the cartridge's bank registers once the code
writes a constant to them, and memory cells the code wrote at constant addresses. Calls and returns are followed
on a simulated return stack. A jump to a constant address with a known bank mapped is a new leader. At a jump
through HL, a constant HL the run held before (the table's address, loaded by the caller) from which the target
is a word lookup, or the last such address when the index is unknown, yields the table's entries, word by word,
while each is the address of code in the same region.

    absint.discover(ctx, rom, mask, leaders) -> {"entries": [phys...], "far": n, "tables": n, ...}

Honest limits (L1): only constants that the simulated path itself sets reach a routine (a value loaded from memory
the path did not write is unknown); a table's length is found by its entries (the first word that is not the
address of code ends it), so a table that runs into another adds code that may never run (harmless: a block runs
only when the CPU is at it); each run stops after a bounded number of instructions, at code in RAM, at HALT and
STOP, and where the next address is unknown.
"""
from __future__ import annotations

import time

from . import build as Bd
from . import lift

VERSION = 2                       # what the analysis finds (in the lift folder's marker)
TOP = None
JP_HL = 0xE9
MAX_STEPS = 600
MAX_PATHS = 6
MAX_DEPTH = 24
MAX_TABLE = 256


class G(dict):
    """A path's globals: its own values over the run's base (the power-on snapshot); a global it never wrote
    reads the base's value."""
    __slots__ = ("base",)

    def __init__(self, base: dict, own=()):
        super().__init__(own)
        self.base = base

    def get(self, k, d=TOP):
        return super().get(k, self.base.get(k, d))

    def copy(self) -> "G":
        return G(self.base, self)


class Path:
    __slots__ = ("g", "mem", "loc", "ret", "done")

    def __init__(self, g: G, mem: dict, loc: dict | None = None):
        self.g, self.mem, self.loc = g, mem, loc if loc is not None else {}
        self.ret = TOP
        self.done = False

    def fork(self) -> "Path":
        p = Path(self.g.copy(), dict(self.mem), dict(self.loc))
        p.ret, p.done = self.ret, self.done
        return p


def _join_into(a: Path, b: Path) -> None:
    for k in set(dict.keys(a.g)) | set(dict.keys(b.g)):
        if a.g.get(k) != b.g.get(k):
            dict.__setitem__(a.g, k, TOP)
    for k in list(a.mem):
        if b.mem.get(k, TOP) != a.mem[k]:
            del a.mem[k]
    for k in set(a.loc) | set(b.loc):
        if a.loc.get(k, TOP) != b.loc.get(k, TOP):
            a.loc[k] = TOP
    if a.ret != b.ret:
        a.ret = TOP


class Abstract:
    """The machine's IR run over constants-or-unknown, one instruction at a time."""

    def __init__(self, ctx, rom: bytes, mask: int, machine: str = "gameboy"):
        self.ir = Bd.module(ctx, machine)
        self.fns = {f["name"]: f for f in self.ir["functions"]}
        self.loop_free = {n for n, f in self.fns.items() if lift._loop_free(f)}
        self.eff = lift.effects(self.ir)
        self.ops = ctx.ops
        self.lifter = lift.Lifter(ctx, self.ir)
        self.dec = lift.Decoder(ctx.store, avoid=lift.scrambled_page(ctx.store, rom))    # no scrambled page
        self.rom, self.mask = rom, mask
        self.gl = {g["name"] for g in self.ir.get("globals") or []}
        stored = {s["array"] for f in self.ir["functions"] for s in lift._stmts(f["body"]) if s["k"] == "store"}
        self.tables = {a["name"]: list(a["init"]) for a in self.ir.get("arrays") or []
                       if a.get("init") and a["name"] not in stored}            # read-only tables: constants
        self.arrays = {a["name"] for a in self.ir.get("arrays") or []}
        self._ins: dict = {}
        self._hc: dict = {}
        # the memory accesses the lifter specialises on a constant address: with an unknown address their result
        # is unknown (and a write may change any memory), which is what running them would say, only slower
        self.by_address = (self.lifter.inline_const | {"rd8", "wr8", "rd8_idu"}) & set(self.fns)

    # ---- the state at a block's start: the hardware as the cartridge leaves it after power-on (so a memory read
    # does not fork on, say, OAM DMA), the CPU's registers unknown, a stack in work RAM (return addresses are kept
    # on the run's own stack), the switchable bank the code's own when it runs there
    def fresh(self, pc: int, phys: int, snapshot: dict) -> Path:
        g = G(snapshot)
        for r in ("A", "F", "B", "C", "D", "E", "H", "L"):
            g[r] = TOP
        g["SP"] = 0xDFF0
        g["rom_off0"] = 0
        g["rom_off1"] = (phys & ~0x3FFF & self.mask) if pc >= 0x4000 else TOP
        return Path(g, {})

    # ---- expressions
    def has_call(self, e) -> bool:
        k = id(e)
        h = self._hc.get(k)
        if h is None:
            h = self._hc[k] = (e, any(x[0] == "CALL" for x in lift._iter(e)))
        return h[1]

    def pure(self, e, p: Path):
        h = e[0]
        if h == "int" or h == "bool":
            return e[1]
        if h == "var":
            n = e[1]
            if n in p.loc:
                return p.loc[n]
            return p.g.get(n, TOP)
        if h == "LOAD":
            i = self.pure(e[2], p)
            if i is TOP:
                return TOP
            arr = e[1]
            if arr == "rom":
                return self.rom[i] if 0 <= i < len(self.rom) else 0xFF
            t = self.tables.get(arr)
            if t is not None:
                return t[i] if 0 <= i < len(t) else 0
            return p.mem.get((arr, i), TOP)
        if h == "AND":
            a = self.pure(e[1], p)
            if a is False:
                return False
            b = self.pure(e[2], p)
            if a is True:
                return b
            return False if b is False else TOP
        if h == "OR":
            a = self.pure(e[1], p)
            if a is True:
                return True
            b = self.pure(e[2], p)
            if a is False:
                return b
            return True if b is True else TOP
        if h == "IF_EXPR":
            c = self.pure(e[1], p)
            if c is TOP:
                x, y = self.pure(e[2], p), self.pure(e[3], p)
                return x if x == y else TOP
            return self.pure(e[2] if c else e[3], p)
        if h == "NOT":
            a = self.pure(e[1], p)
            return TOP if a is TOP else (not a)
        args = [self.pure(a, p) for a in e[1:]]
        if any(a is TOP for a in args):
            if h == "BIT_AND" and 0 in args:
                return 0
            if h == "MUL" and 0 in args:
                return 0
            return TOP
        spec = self.ops.get(h)
        if spec is None or spec.fn is None:
            return TOP
        try:
            return spec.fn(*args)
        except Exception:  # noqa: BLE001 -- what cannot be computed is unknown
            return TOP

    def ev(self, e, p: Path, depth: int) -> list:
        """[(path, value)] -- calls inside the expression run first, left to right."""
        if not self.has_call(e):
            return [(p, self.pure(e, p))]
        if e[0] == "CALL":
            outs = []
            for q, args in self.ev_args(e[2:], p, depth):
                outs += self.call(e[1], args, q, depth + 1)
            return outs
        # a call nested in an operator: evaluate the calls, then the operator over their values
        start = 2 if e[0] == "LOAD" else 1
        outs = []
        for q, vals in self.ev_args(e[start:], p, depth):
            ce = [*e[:start], *[["int", v] if isinstance(v, int) and not isinstance(v, bool) else
                                ["bool", v] if isinstance(v, bool) else ["var", "__top__"] for v in vals]]
            outs.append((q, self.pure(ce, q)))
        return outs

    def ev_args(self, args, p: Path, depth: int) -> list:
        combos = [(p, [])]
        for a in args:
            nxt = []
            for q, vals in combos:
                for q2, v in self.ev(a, q, depth):
                    nxt.append((q2, vals + [v]))
            combos = nxt[:MAX_PATHS]
        return combos

    # ---- calls: a machine function without loops runs; one with loops is opaque (its writes become unknown)
    def opaque(self, name: str, p: Path) -> None:
        _, w = self.eff.get(name, (set(), set()))
        for n in w:
            if n in self.arrays:
                for k in [k for k in p.mem if k[0] == n]:
                    del p.mem[k]
            else:
                p.g[n] = TOP

    def call(self, name: str, args: list, p: Path, depth: int) -> list:
        fn = self.fns.get(name)
        if fn is None or name not in self.loop_free or depth > MAX_DEPTH or \
                (name in self.by_address and args and args[0] is TOP):
            q = p.fork()
            self.opaque(name, q)
            return [(q, TOP)]
        q = Path(p.g, p.mem, {par["name"]: a for par, a in zip(fn["params"], args)})
        outs = []
        for r in self.run(fn["body"], q, depth):
            v = r.ret
            back = Path(r.g, r.mem, dict(p.loc))
            outs.append((back, v))
        return self.cap_pairs(outs)

    def cap_pairs(self, outs: list) -> list:
        if len(outs) <= MAX_PATHS:
            return outs
        base, v = outs[0][0].fork(), outs[0][1]
        for q, w in outs[1:]:
            _join_into(base, q)
            if w != v:
                v = TOP
        return [(base, v)]

    # ---- statements
    def run(self, body: list, p: Path, depth: int) -> list:
        paths = [p]
        for s in body:
            nxt = []
            for q in paths:
                if q.done:
                    nxt.append(q)
                else:
                    nxt += self.stmt(s, q, depth)
            if len(nxt) > MAX_PATHS:
                live = [q for q in nxt if not q.done]
                ended = [q for q in nxt if q.done]
                if live:
                    base = live[0].fork()
                    for q in live[1:]:
                        _join_into(base, q)
                    live = [base]
                nxt = live + ended[:MAX_PATHS]
            paths = nxt
        return paths

    def assign(self, p: Path, name: str, v) -> None:
        if name in p.loc or name not in self.gl:
            p.loc[name] = v
        else:
            p.g[name] = v

    def stmt(self, s: dict, p: Path, depth: int) -> list:
        k = s["k"]
        if k == "assign":
            out = []
            for q, v in self.ev(s["value"], p, depth):
                q = q if q is not p else p.fork()
                self.assign(q, s["target"], v)
                out.append(q)
            return out
        if k == "store":
            out = []
            for q, i in self.ev(s["index"], p, depth):
                for q2, v in self.ev(s["value"], q, depth):
                    q2 = q2 if q2 is not p else p.fork()
                    if i is TOP:
                        for key in [key for key in q2.mem if key[0] == s["array"]]:
                            del q2.mem[key]
                    elif v is TOP:
                        q2.mem.pop((s["array"], i), None)
                    else:
                        q2.mem[(s["array"], i)] = v
                    out.append(q2)
            return out
        if k == "do":
            return [q for q, _ in self.ev(s["value"], p, depth)]
        if k == "return":
            if "value" not in s:
                q = p.fork()
                q.done = True
                return [q]
            out = []
            for q, v in self.ev(s["value"], p, depth):
                q = q if q is not p else p.fork()
                q.ret, q.done = v, True
                out.append(q)
            return out
        if k == "if":
            out = []
            for q, c in self.ev(s["cond"], p, depth):
                if c is TOP:
                    out += self.run(s.get("then") or [], q.fork(), depth)
                    out += self.run(s.get("else") or [], q.fork(), depth)
                else:
                    out += self.run((s.get("then") if c else s.get("else")) or [], q, depth)
            return out
        if k == "switch":
            out = []
            for q, v in self.ev(s["value"], p, depth):
                cases = s.get("cases") or []
                if v is TOP:
                    for c in cases:
                        out += self.run(c["body"], q.fork(), depth)
                    out += self.run(s.get("default") or [], q.fork(), depth)
                else:
                    hit = next((c for c in cases if v in c["match"]), None)
                    out += self.run(hit["body"] if hit else (s.get("default") or []), q, depth)
            return out
        # loops: whatever they write becomes unknown
        q = p.fork()
        for st in lift._stmts([s]):
            if st["k"] == "assign":
                self.assign(q, st["target"], TOP)
            elif st["k"] == "store":
                for key in [key for key in q.mem if key[0] == st["array"]]:
                    del q.mem[key]
            for x in lift._exprs(st):
                if x[0] == "CALL":
                    self.opaque(x[1], q)
        return [q]

    # ---- one instruction
    def instruction(self, pc: int, phys: int):
        key = (phys, pc)
        got = self._ins.get(key)
        if got is None:
            card, n, imm = self.dec.at(self.rom, phys, self.mask)
            if card.get("illegal"):
                got = (card, n, None)
            else:
                locals_: dict = {}
                body = self.lifter.entered(card, imm, pc, locals_)[1]
                got = (card, n, body)
            self._ins[key] = got
        return got

    def phys_of(self, pc: int, p: Path):
        if pc < 0x4000:
            off = p.g.get("rom_off0", 0)
        elif pc < 0x8000:
            off = p.g.get("rom_off1", TOP)
        else:
            return TOP
        if off is TOP:
            return TOP
        return (off | (pc & 0x3FFF)) & self.mask


def snapshot(ctx, rom: bytes) -> dict:
    """Every scalar global of the machine after the cartridge is configured and powered on."""
    from . import gb as G
    g = G.GameBoy(ctx, rom, "native", sample_rate=0, fresh=True)
    ir = Bd.module(ctx, "gameboy")
    out = {x["name"]: int(g.m.get(x["name"])) for x in ir.get("globals") or []}
    if hasattr(g.m, "close"):
        g.m.close()
    return out


def discover(ctx, rom: bytes, mask: int, leaders: list, known=None, budget_s: float = 240.0) -> dict:
    """New block leaders (keys: ROM offset and the half of the address space they run in) found by running
    abstractly from the start of every block that ends in a call or a jump, or holds a JP HL or a bank switch.
    ``leaders``: the keys found so far (lift.discover's)."""
    t0 = time.time()
    a = Abstract(ctx, rom, mask)
    snap = snapshot(ctx, rom)
    dec = a.dec
    known_keys = set(leaders) | set(known or ())
    starts = []
    for k in leaders:
        ext = lift.block_extent(dec, rom, k, mask)
        if not ext:
            continue
        pc, phys, card, imm = ext[-1]
        ends_in_transfer = card["group"] in ("call", "jump") or rom[phys & mask] in RSTS
        computes = any(rom[ph & mask] == JP_HL or (c["mnemonic"] == "LD (nn),A" and 0x2000 <= (im[0] | im[1] << 8) < 0x4000)
                       for _, ph, c, im in ext)
        if ends_in_transfer or computes:
            starts.append(k)
    found: set = set()
    stats = {"runs": 0, "far": 0, "tables": 0, "steps": 0, "unresolved": 0}
    for k in starts:
        if time.time() - t0 > budget_s:
            stats["stopped_at_budget"] = True
            break
        stats["runs"] += 1
        _run_from(a, k, found, stats, snap)
    new = sorted(x for x in found if x not in known_keys)
    stats.update(entries=new, seconds=round(time.time() - t0, 1), starts=len(starts))
    return stats


RSTS = (0xC7, 0xCF, 0xD7, 0xDF, 0xE7, 0xEF, 0xF7, 0xFF)
MAX_WORK = 24


def _run_from(a: Abstract, key: int, found: set, stats: dict, snap: dict) -> None:
    """Depth-first over the paths from a block's start: straight lines run instruction by instruction; at a branch
    whose condition is unknown both ways are kept (a bounded number); calls and returns use the run's own stack."""
    rom = a.rom
    pc0 = lift._pc_of(key)
    work = [(pc0, a.fresh(pc0, key >> 1, snap), (), ())]
    steps = 0
    visits: dict = {}
    while work and steps < MAX_STEPS:
        pc, p, stack, hls = work.pop()
        while steps < MAX_STEPS:
            steps += 1
            stats["steps"] += 1
            if pc >= 0x8000:
                break
            phys = a.phys_of(pc, p)
            if phys is TOP:
                break
            v = visits.get((pc, stack[-1:]), 0)
            if v >= 3:
                break
            visits[(pc, stack[-1:])] = v + 1
            card, n, body = a.instruction(pc, phys)
            if body is None:
                break
            op = rom[phys]
            if card.get("prefix") is None and card["opcode"] in (0x76, 0x10):
                break
            h, l_ = p.g.get("H", TOP), p.g.get("L", TOP)
            if h is not TOP and l_ is not TOP and (not hls or hls[-1] != (h << 8) | l_):
                hls = (hls + ((h << 8) | l_,))[-8:]          # the constant HLs this run held, newest last
            group = card["group"]
            rst = card.get("prefix") is None and op in RSTS
            nxt = (pc + n) & 0xFFFF
            by_pc: dict = {}
            for q in a.run(body, p, 0):
                by_pc.setdefault(q.g.get("PC", TOP), q)
            if not by_pc:
                break
            choices = []
            for t, q in by_pc.items():
                if op == JP_HL:
                    base = _table_base(a, hls, t, q)
                    if base is not TOP:
                        # a known index: the routine read the table somewhere inside it, so look both ways
                        stats["tables"] += _table(a, found, base, q, back=t is not TOP)
                if t is TOP:
                    if op != JP_HL and group != "ret":
                        stats["unresolved"] += 1
                    continue
                st = stack
                if t != nxt and (group == "call" or rst):
                    st = stack + (nxt,)
                elif group == "ret" and t != nxt:
                    if not stack:
                        continue                     # back to whoever called the block: covered elsewhere
                    t = stack[-1]
                    st = stack[:-1]
                if t != nxt and _mark(a, found, t, q) and pc < 0x4000 <= t:
                    stats["far"] += 1
                choices.append((t, q, st))
            if not choices:
                break
            for t, q, st in choices[1:]:
                if len(work) < MAX_WORK:
                    work.append((t, q, st, hls))
            pc, p, stack = choices[0]


def _mark(a: Abstract, found: set, pc: int, p: Path) -> bool:
    phys = a.phys_of(pc, p)
    if phys is TOP or pc >= 0x8000:
        return False
    key = lift._key(phys, pc)
    if key in found:
        return False
    found.add(key)
    return True


def _word(a: Abstract, pc: int, p: Path):
    ph = a.phys_of(pc, p)
    if ph is TOP or ph + 1 >= len(a.rom):
        return TOP
    return a.rom[ph] | (a.rom[ph + 1] << 8)


def _table_base(a: Abstract, hls: tuple, target, p: Path):
    """The jump table a JP HL dispatched through: a constant HL held before from which the target is a word lookup
    (a known index), or, when the target is unknown, the newest constant HL that points into ROM."""
    for b in reversed(hls):
        if b >= 0x8000 or b == target:
            continue
        if target is TOP:
            return b
        if any(_word(a, b + 2 * k, p) == target for k in range(64)):
            return b
    return TOP


def _table(a: Abstract, found: set, base: int, p: Path, back: bool = False) -> int:
    """The entries of a jump table at base, while each word is the address of code in the same region (and before
    base too, when back)."""
    if base >= 0x8000 or a.phys_of(base, p) is TOP:
        return 0
    n = 0
    for step in ((2, -2) if back else (2,)):
        i = 0 if step > 0 else -2
        while abs(i) < 2 * MAX_TABLE:
            t = _word(a, base + i, p) if 0 <= base + i < 0x8000 else TOP
            if t is TOP or not _code_address(a, t, base, p):
                break
            if _mark(a, found, t, p):
                n += 1
            i += step
    return n


def _code_address(a: Abstract, t: int, base: int, p: Path) -> bool:
    """t can be where code is: in ROM, in bank 0 or (from a table in a switchable bank) the same bank, and its
    first instruction is not an illegal opcode."""
    if t >= 0x8000 or t in (0x0000, 0xFFFF):
        return False
    if base < 0x4000 <= t and p.g.get("rom_off1") is TOP:
        return False
    tp = a.phys_of(t, p)
    if tp is TOP:
        return False
    card, _, _ = a.dec.at(a.rom, tp, a.mask)
    return not card.get("illegal")


__all__ = ["Abstract", "discover", "snapshot"]
