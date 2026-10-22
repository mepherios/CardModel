"""lift — a ROM's code as card IR: basic blocks lifted from the instruction cards, specialised, run natively.

REA-style distillation, kept internal: the ROM is read as code (recursive descent from the entry and interrupt
vectors, plus the addresses an execution profile saw), cut into basic blocks, and every block becomes ONE card-IR
function made of its instruction cards' IR with the bytes filled in. That function is then specialised:

* **inlining** - the instruction semantics and the CPU helpers (core.card) are inlined; a memory access whose
  address is a constant is specialised through the machine's own bus logic (an HRAM read becomes an array load);
* **constant propagation** - immediates, PC and every derived address fold; conditions that fold remove code;
* **register caching** - CPU registers live in locals for the block (only when no remaining call reads them),
  written back at every exit;
* **dead code** - flags computed and overwritten before anything reads them disappear.

A block runs whole only when it can finish before the next event (``now + its longest time <= next_event``);
inside it, nothing can raise an interrupt except the CPU's own writes, so after any instruction that may move
``next_event`` (an I/O or bank-switch write) the block checks and leaves. Every instruction start the blocks cover
is also lifted on its own (``ins_K``: the instruction specialised to its bytes, then what the interpreter does
after every instruction): a block whose next event is too close, a step right after EI or after the frame ended,
and an entry into the middle of a block (an interrupt's return) run these, one instruction per step. HALT, STOP
and EI are only lifted on their own. So the ROM's code that was found runs as lifted card IR, and the
interpreter runs only what discovery did not find; a block is always equivalent to the instructions it replaces
(the differential runs check this, frame by frame).

The lifted functions join the machine module (``run_block`` becomes a switch over every instruction start: a
leader goes to its block, any other to its instruction) and are emitted through a language card like the rest of
it: split into parts by bank and size so no compile unit outgrows a compiler, compiled one part per slot, linked
into one library cached per ROM and machine.

Code the cartridge copies into RAM (work RAM, HRAM: the OAM DMA routine every game has) is lifted too, one
instruction at a time: at each address, one case for every encoding the profiles saw an instruction start with
there (routines copied over each other), guarded by its opcode as RAM holds it when it runs, with its operands
read from RAM then (code that patches its own operands); during OAM DMA only HRAM's (the only memory the CPU can
read then). RAM holding none of them leaves the instruction to the interpreter.

Honest limits (L1): code no profile or static successor reached, RAM code with an encoding no profile saw at
its address, code in video or cartridge RAM, illegal opcodes and the instruction after a HALT bug run in the
interpreter (the machine counts them: ``interpreted``, ``interpreted_ram``), and so does a Sachen board's
scrambled header page (0x0100-0x01FF: the bytes there are not what the CPU reads); a key is (ROM offset, which
half of the address space), so a bank mapped at an unusual place gets its own blocks; MBC1 multicart remapping
and Wisdom Tree's 32 KiB banks are treated like any bank.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

from ..engines.codegen import Emitter
from ..kernel import resources
from . import build as Bd
from . import isa as I
from . import native as N

REGS = ("A", "F", "B", "C", "D", "E", "H", "L", "SP", "PC")
ENDS = ("jump", "call", "ret")                 # groups that end a block
EXCLUDED = {0x76, 0x10, 0xFB}                  # HALT, STOP, EI: each a block of its own (one instruction)
STOP = 0x10                                    # one opcode byte, and it skips the next byte (PC + 2)
LIFTER = 5                                     # the lifted blocks' shape (in the cache key)
PART_STATEMENTS = 120000                       # at most this many IR statements in one compile unit
RAM_LIFTED = ((0xC000, 0xFE00), (0xFF80, 0xFFFF))   # work RAM and its echo, HRAM (not video or cartridge RAM)
RAM_BASE = 0xC000                              # the RAM profile's first address (32 bytes, 256 bits, per address)
MAX_INSTRUCTIONS = 48
LEAVES = ("var", "int", "float", "bool")


# -- effects: which globals and arrays each function reads and writes (transitively) -------------------------
def effects(module: dict) -> dict:
    gnames = {g["name"] for g in module.get("globals") or []}
    fns = {f["name"]: f for f in module["functions"]}
    direct = {}
    for name, fn in fns.items():
        local = {p["name"] for p in fn["params"]} | set(fn.get("locals") or {})
        r, w, calls = set(), set(), set()
        for st in _stmts(fn["body"]):
            if st["k"] == "assign" and st["target"] not in local and st["target"] in gnames:
                w.add(st["target"])
            if st["k"] == "for_range" and st["var"] not in local and st["var"] in gnames:
                w.add(st["var"])
            if st["k"] == "store":
                w.add("@" + st["array"])
            for e in _exprs(st):
                if e[0] == "var" and e[1] in gnames and e[1] not in local:
                    r.add(e[1])
                elif e[0] == "LOAD":
                    r.add("@" + e[1])
                elif e[0] == "CALL":
                    calls.add(e[1])
        direct[name] = (r, w, calls)
    out = {n: (set(r), set(w)) for n, (r, w, _) in direct.items()}
    changed = True
    while changed:
        changed = False
        for n, (_, _, calls) in direct.items():
            r, w = out[n]
            for c in calls:
                if c in out:
                    cr, cw = out[c]
                    if not cr <= r or not cw <= w:
                        r |= cr
                        w |= cw
                        changed = True
    return out


def _stmts(body):
    for s in body:
        yield s
        for key in ("then", "else", "body", "default"):
            if key in s:
                yield from _stmts(s[key])
        for case in s.get("cases") or ():
            yield from _stmts(case["body"])


def _iter(e):
    if isinstance(e, list) and e:
        yield e
        if e[0] not in LEAVES:
            for a in e[(2 if e[0] in ("CALL", "LOAD") else 1):]:
                yield from _iter(a)


def _exprs(st):
    for key in ("value", "cond", "start", "stop", "step", "index"):
        if isinstance(st.get(key), list):
            yield from _iter(st[key])


def _loop_free(fn) -> bool:
    return not any(s["k"] in ("while", "for_range", "switch", "break", "continue") for s in _stmts(fn["body"]))


# -- decoding the ROM -------------------------------------------------------------------------------------
class Decoder:
    """Instruction cards by the bytes at a ROM offset. ``avoid``: a CPU address range in bank 0's half whose bytes
    the board does not show the CPU as they are stored (a Sachen board's scrambled header page); no block covers
    it, so that code runs in the interpreter, which reads through the board."""

    def __init__(self, store, isa: str = "lr35902", avoid: tuple | None = None):
        self.table = I.decode_table(store, isa)
        self.avoid = avoid

    def at(self, rom: bytes, phys: int, mask: int):
        op = rom[phys & mask]
        if op == 0xCB:
            card = self.table[(0xCB, rom[(phys + 1) & mask])]
            return card, 2, [rom[(phys + 1) & mask]]
        card = self.table[(None, op)]
        n = card["bytes"]
        return card, n, [rom[(phys + k) & mask] for k in range(1, n)]


def _pc_of(key: int) -> int:
    phys, half = key >> 1, key & 1
    return (0x4000 | (phys & 0x3FFF)) if half else (phys & 0x3FFF)


def _key(phys: int, pc: int) -> int:
    return (phys << 1) | (1 if pc >= 0x4000 else 0)


def block_extent(dec: Decoder, rom: bytes, key: int, mask: int) -> list:
    """[(pc, phys, card, operand bytes)] from a leader to the block's end."""
    phys, pc = key >> 1, _pc_of(key)
    out = []
    region_end = 0x8000 if pc >= 0x4000 else 0x4000
    while len(out) < MAX_INSTRUCTIONS:
        if dec.avoid and pc < 0x4000 and dec.avoid[0] < pc + 3 and pc < dec.avoid[1]:
            break                                       # the instruction may reach into the scrambled page
        card, n, imm = dec.at(rom, phys, mask)
        if card.get("illegal") or pc + n > region_end:
            break
        if card.get("prefix") is None and card["opcode"] in EXCLUDED:
            if not out:                    # HALT, STOP, EI: a block of one instruction, then the step loop
                out.append((pc, phys, card, imm))
            break
        out.append((pc, phys, card, imm))
        pc += n
        phys += n
        if card["group"] in ENDS:
            break
    return out


CONDITIONS = ("Z", "NZ", "C", "NC")


def conditional(mnemonic: str) -> bool:
    """A jump, call or return that may not be taken (JP NZ,nn; CALL Z,nn; JR C,e; RET NC): it can fall through."""
    return mnemonic.partition(" ")[2].split(",")[0] in CONDITIONS


def successors(card, pc: int, n: int, imm: list) -> list[int]:
    """Statically known next addresses (CPU addresses)."""
    m = card["mnemonic"]
    nxt = pc + n
    out = []
    if card["group"] not in ENDS or (card["group"] in ("jump", "call", "ret") and conditional(m)):
        out.append(nxt)
    if m.startswith("JR"):
        e = imm[0] - 256 if imm[0] >= 128 else imm[0]
        out.append((nxt + e) & 0xFFFF)
    elif m.startswith(("JP ", "CALL")) and "nn" in m:
        out.append(imm[0] | (imm[1] << 8))
    elif m.startswith("RST"):
        out.append(card["opcode"] & 0x38)
    if m.startswith(("CALL", "RST")):
        out.append(nxt)
    return out


def discover(store, rom: bytes, mask: int, seen: bytes | None = None, entries: bytes | None = None,
             avoid: tuple | None = None) -> dict:
    """Block leaders: recursive descent through bank 0 from the vectors, plus the profile's entry points (any
    bank), plus static successors of everything the profile saw. Returns {key: [pc list]}. ``avoid``: the
    scrambled page (``scrambled_page``), found from the ROM when not given."""
    dec = Decoder(store, avoid=avoid if avoid is not None else scrambled_page(store, rom))
    leaders: set = set()
    todo = [0x100] + list(range(0x00, 0x40, 8)) + list(range(0x40, 0x68, 8))
    work = [(_key(a, a)) for a in todo]
    if entries:
        for i, byte in enumerate(entries):
            if byte:
                for b in range(8):
                    if byte >> b & 1:
                        phys = i * 8 + b
                        if phys <= mask:
                            pc = phys if phys < 0x4000 else 0x4000 | (phys & 0x3FFF)
                            work.append(_key(phys, pc))
    visited: set = set()
    while work and len(leaders) < 200000:
        key = work.pop()
        if key in visited:
            continue
        visited.add(key)
        if (key >> 1) > mask:
            continue
        ext = block_extent(dec, rom, key, mask)
        if not ext:
            continue
        leaders.add(key)
        pc, phys, card, imm = ext[-1]
        n = len(imm) + 1
        for t in successors(card, pc, n, imm):
            if t < 0x4000:
                work.append(_key(t, t))                       # bank 0 (the usual mapping)
            elif t < 0x8000 and pc >= 0x4000:
                tphys = (phys & ~0x3FFF) | (t & 0x3FFF)       # same switchable bank
                work.append(_key(tphys, t))
        if card.get("prefix") is None and card["opcode"] == STOP:
            n = 2
        if len(ext) == MAX_INSTRUCTIONS or (card["group"] not in ENDS):
            npc = pc + n
            if npc < (0x8000 if pc >= 0x4000 else 0x4000):
                work.append(_key(phys + n, npc))
    return {"leaders": sorted(leaders), "visited": len(visited)}


# -- specialising a block ---------------------------------------------------------------------------------
class Lifter:
    def __init__(self, ctx, machine_ir: dict, isa: str = "lr35902"):
        self.ctx = ctx
        self.ops = ctx.ops
        self.ir = machine_ir
        self.fns = {f["name"]: f for f in machine_ir["functions"]}
        self.eff = effects(machine_ir)
        self.gnames = {g["name"] for g in machine_ir.get("globals") or []}
        core = I.isa_card(ctx.store, isa)
        core_mod_fns = set()
        from ..lang.syntax import parse
        for d in parse(I.library_text(core, "core")):
            if d.kind == "fn":
                core_mod_fns.add(d.data["name"])
        self.inline_always = {n for n in core_mod_fns | {"rd8", "wr8", "idle", "idu", "rd8_idu", "fetch8", "fetch16"}
                              if n in self.fns and _loop_free(self.fns[n])}
        self.inline_const = {"bus_read", "bus_write", "wram_index", "io_read", "io_write", "rom_read", "peek8",
                             "code_byte"}
        self.n = 0

    def fresh(self, base: str) -> str:
        self.n += 1
        return f"x{self.n}_{base}"

    # ---- expression helpers ----
    def single_return(self, fn) -> list | None:
        b = fn["body"]
        if len(b) == 1 and b[0]["k"] == "return" and "value" in b[0] and fn["returns"] != "void":
            return b[0]["value"]
        return None

    def subst(self, e, m: dict):
        if not isinstance(e, list) or not e:
            return e
        if e[0] == "var":
            return copy.deepcopy(m[e[1]]) if e[1] in m else e
        if e[0] in LEAVES:
            return e
        start = 2 if e[0] in ("CALL", "LOAD") else 1
        return [*e[:start], *[self.subst(a, m) for a in e[start:]]]

    def expand_pure(self, e):
        """Inline calls to single-return functions inside an expression."""
        if not isinstance(e, list) or not e or e[0] in LEAVES:
            return e
        if e[0] == "CALL":
            args = [self.expand_pure(a) for a in e[2:]]
            fn = self.fns.get(e[1])
            body = self.single_return(fn) if fn else None
            if body is not None and not self.eff[e[1]][1]:
                m = {p["name"]: a for p, a in zip(fn["params"], args)}
                return self.expand_pure(self.subst(body, m))
            return ["CALL", e[1], *args]
        start = 2 if e[0] == "LOAD" else 1
        return [*e[:start], *[self.expand_pure(a) for a in e[start:]]]

    # ---- statement inlining ----
    def inline_body(self, fname: str, args: list, target: str | None, locals_: dict) -> list:
        fn = self.fns[fname]
        pfx = self.fresh(fname)
        ren = {}
        out = []
        for p, a in zip(fn["params"], args):
            ln = f"{pfx}_{p['name']}"
            ren[p["name"]] = ["var", ln]
            locals_[ln] = p["type"]
            out.append({"k": "assign", "target": ln, "value": a})
        for name, t in (fn.get("locals") or {}).items():
            ln = f"{pfx}_{name}"
            ren[name] = ["var", ln]
            locals_[ln] = t
        done = f"{pfx}_done"
        res = target
        body = copy.deepcopy(fn["body"])
        body = self.rename_body(body, ren)
        needs_flag = any(s["k"] == "return" for s in _stmts(body[:-1])) or \
            any(s["k"] == "return" for s in _stmts([b for b in body[-1:] if b["k"] != "return"]))
        if needs_flag:
            locals_[done] = "bool"
            out.append({"k": "assign", "target": done, "value": ["bool", False]})
        out += self.elim_returns(body, res, done if needs_flag else None)
        return out

    def rename_body(self, body, ren):
        out = []
        for s in body:
            s = dict(s)
            for key in ("value", "cond", "start", "stop", "step", "index"):
                if key in s:
                    s[key] = self.subst(s[key], ren)
            if s["k"] == "assign" and s["target"] in ren:
                s["target"] = ren[s["target"]][1]
            if s["k"] == "for_range":
                s["var"] = ren.get(s["var"], ["var", s["var"]])[1]
            for key in ("then", "else", "body", "default"):
                if key in s:
                    s[key] = self.rename_body(s[key], ren)
            if "cases" in s:
                s["cases"] = [{**c, "body": self.rename_body(c["body"], ren)} for c in s["cases"]]
            out.append(s)
        return out

    def elim_returns(self, body, res, done):
        out = []
        for i, s in enumerate(body):
            if s["k"] == "return":
                if "value" in s and res is not None:
                    out.append({"k": "assign", "target": res, "value": s["value"]})
                if done is not None:
                    out.append({"k": "assign", "target": done, "value": ["bool", True]})
                return out
            if s["k"] == "if" and any(x["k"] == "return" for x in _stmts([s])):
                out.append({**s, "then": self.elim_returns(s.get("then") or [], res, done),
                            "else": self.elim_returns(s.get("else") or [], res, done)})
                rest = self.elim_returns(body[i + 1:], res, done)
                if rest:
                    out.append({"k": "if", "cond": ["NOT", ["var", done]], "then": rest, "else": []})
                return out
            out.append(s)
        return out

    def hoist_calls(self, e, pre: list, locals_: dict, consts: dict, top: bool):
        """Calls to inlinable functions nested inside an expression move to temporaries before the statement (only
        from positions that are always evaluated, so nothing runs that would not have run)."""
        if not isinstance(e, list) or not e or e[0] in LEAVES:
            return e
        if e[0] == "CALL":
            args = [self.hoist_calls(a, pre, locals_, consts, False) for a in e[2:]]
            call = ["CALL", e[1], *args]
            fn = self.fns.get(e[1])
            if not top and fn is not None and fn["returns"] != "void" and self._inlinable(call, consts):
                t = self.fresh("h")
                locals_[t] = fn["returns"]
                pre.append({"k": "assign", "target": t, "value": call})
                return ["var", t]
            return call
        if e[0] in ("AND", "OR"):
            return [e[0], self.hoist_calls(e[1], pre, locals_, consts, False), e[2]]
        if e[0] == "IF_EXPR":
            return [e[0], self.hoist_calls(e[1], pre, locals_, consts, False), e[2], e[3]]
        start = 2 if e[0] == "LOAD" else 1
        return [*e[:start], *[self.hoist_calls(a, pre, locals_, consts, False) for a in e[start:]]]

    def inline_stmts(self, body, locals_, consts: dict, depth=0) -> list:
        """Inline calls (statement level) to inlinable functions; constant-address bus calls are specialised."""
        out = []
        for s in body:
            s = dict(s)
            for key in ("value", "cond", "index"):
                if key in s:
                    s[key] = self.expand_pure(s[key])
            if depth < 8 and s["k"] in ("assign", "if", "store", "return", "do"):
                pre: list = []
                for key in ("index", "value", "cond"):
                    if key in s:
                        s[key] = self.hoist_calls(s[key], pre, locals_, consts,
                                                  top=(key == "value" and s["k"] in ("assign", "do")))
                if pre:
                    out += self.inline_stmts(pre, locals_, consts, depth + 1)
            call = None
            if s["k"] in ("assign", "do") and isinstance(s.get("value"), list) and s["value"][0] == "CALL":
                call = s["value"]
            if call is not None and depth < 8 and self._inlinable(call, consts):
                target = s["target"] if s["k"] == "assign" else None
                inner = self.inline_body(call[1], call[2:], target, locals_)
                inner = self.fold_block(inner, dict(consts), locals_)
                out += self.inline_stmts(inner, locals_, consts, depth + 1)
                continue
            for key in ("then", "else"):
                if key in s:
                    s[key] = self.inline_stmts(s[key], locals_, consts, depth)
            out.append(s)
        return out

    def _inlinable(self, call, consts) -> bool:
        name = call[1]
        if name not in self.fns or not _loop_free(self.fns[name]):
            return False
        if name in self.inline_always:
            return True
        if name in self.inline_const:
            return len(call) > 2 and self.const_of(call[2], consts) is not None
        return False

    # ---- constant folding / propagation ----
    def const_of(self, e, env):
        e = self.fold(self.subst(e, {k: v for k, v in env.items()}))
        return e[1] if e[0] in ("int", "bool") else None

    def fold(self, e):
        if not isinstance(e, list) or not e or e[0] in LEAVES:
            return e
        head = e[0]
        if head == "CALL":
            return ["CALL", e[1], *[self.fold(a) for a in e[2:]]]
        if head == "LOAD":
            return ["LOAD", e[1], self.fold(e[2])]
        args = [self.fold(a) for a in e[1:]]
        if head == "AND":
            a, b = args
            if a[0] == "bool":
                return b if a[1] else ["bool", False]
            if b[0] == "bool" and not b[1]:
                return ["bool", False] if not self._has_call(a) else [head, a, b]
            return [head, a, b]
        if head == "OR":
            a, b = args
            if a[0] == "bool":
                return ["bool", True] if a[1] else b
            return [head, a, b]
        if head == "IF_EXPR":
            c, a, b = args
            if c[0] == "bool":
                return a if c[1] else b
            return [head, c, a, b]
        if head == "NOT":
            a = args[0]
            return ["bool", not a[1]] if a[0] == "bool" else [head, a]
        consts = all(a[0] in ("int", "bool") for a in args)
        spec = self.ops.get(head)
        if consts and spec and spec.fn:
            try:
                v = spec.fn(*[a[1] for a in args])
            except Exception:  # noqa: BLE001 -- a folding failure keeps the expression (the runtime decides)
                return [head, *args]
            if isinstance(v, bool):
                return ["bool", v]
            if isinstance(v, int):
                return ["int", v]
        # algebraic identities that keep exact semantics
        if head == "BIT_OR":
            if args[0] == ["int", 0]:
                return args[1]
            if args[1] == ["int", 0]:
                return args[0]
        if head == "BIT_AND" and (args[0] == ["int", 0] or args[1] == ["int", 0]):
            if not self._has_call(args[0]) and not self._has_call(args[1]):
                return ["int", 0]
        if head == "ADD":
            if args[1] == ["int", 0]:
                return args[0]
            if args[0] == ["int", 0]:
                return args[1]
        return [head, *args]

    def _has_call(self, e) -> bool:
        return any(x[0] == "CALL" for x in _iter(e))

    def fold_block(self, body, env: dict, locals_: dict) -> list:
        """Constant propagation over locals and PC (env: name -> ["int", v] / ["bool", v])."""
        out = []
        for s in body:
            k = s["k"]
            s = dict(s)
            for key in ("value", "cond", "index"):
                if key in s:
                    s[key] = self.fold(self.subst(s[key], env))
            if k == "assign":
                tgt = s["target"]
                if tgt in locals_ or tgt == "PC":
                    if s["value"][0] in ("int", "bool"):
                        env[tgt] = s["value"]
                    else:
                        env.pop(tgt, None)
                self._kill_calls(s.get("value"), env)
                out.append(s)
            elif k == "if":
                c = s["cond"]
                if c[0] == "bool":
                    out += self.fold_block(s["then"] if c[1] else (s.get("else") or []), env, locals_)
                    continue
                e1, e2 = dict(env), dict(env)
                t = self.fold_block(s.get("then") or [], e1, locals_)
                el = self.fold_block(s.get("else") or [], e2, locals_)
                env.clear()
                env.update({n: v for n, v in e1.items() if e2.get(n) == v})
                if t or el:
                    out.append({**s, "then": t, "else": el})
            elif k in ("do", "store", "return"):
                self._kill_calls(s.get("value"), env)
                out.append(s)
            else:
                for st in _stmts([s]):
                    if st["k"] == "assign":
                        env.pop(st["target"], None)
                env.pop("PC", None)
                out.append(s)
        return out

    def _kill_calls(self, e, env):
        if not isinstance(e, list):
            return
        for x in _iter(e):
            if x[0] == "CALL" and x[1] in self.eff and "PC" in self.eff[x[1]][1]:
                env.pop("PC", None)

    # ---- liveness / dead code ----
    def dce(self, body, live: set) -> tuple[list, set]:
        out = []
        for s in reversed(body):
            k = s["k"]
            if k == "assign":
                uses = self._uses(s["value"])
                if s["target"] not in live and s["target"] in self._locals and not self._has_call(s["value"]):
                    continue
                live = (live - {s["target"]}) | uses
                out.append(s)
            elif k == "if":
                t, lt = self.dce(s.get("then") or [], set(live))
                e, le = self.dce(s.get("else") or [], set(live))
                if not t and not e and not self._has_call(s["cond"]):
                    continue
                live = lt | le | self._uses(s["cond"])
                out.append({**s, "then": t, "else": e})
            elif k == "return":
                live = set(self._exit_live) | (self._uses(s["value"]) if "value" in s else set())
                out.append(s)
            else:
                for key in ("value", "index", "cond"):
                    if key in s:
                        live = live | self._uses(s[key])
                if k not in ("do", "store"):
                    live = live | set(self._locals)
                out.append(s)
        return list(reversed(out)), live

    def _uses(self, e) -> set:
        return {x[1] for x in _iter(e) if x[0] == "var"}

    # ---- a whole block ----
    def entered(self, card, imm: list | None, pc: int, locals_: dict, operands_at: int | None = None
                ) -> tuple[int, list]:
        """PC as the card's IR finds it (past the opcode, a prefix and the operands its fetches take: STOP's IR skips
        its second byte itself) and that IR with the bytes in (``instance``)."""
        body = self.instance(card, imm, locals_, operands_at)
        npc = (pc + 1 + (card.get("prefix") is not None) + self.taken) & 0xFFFF
        return npc, [{"k": "assign", "target": "PC", "value": ["int", npc]}] + body

    def step_ir(self, card, imm: list | None, pc: int, locals_: dict, operands_at: int | None = None) -> list:
        """One instruction's statements: its fetch time, PC past it, its card's IR with the bytes in, specialised."""
        ins: list = [{"k": "assign", "target": "now", "value": ["ADD", ["var", "now"], ["var", "md"]]}]
        if card.get("prefix") is not None:
            ins.append({"k": "assign", "target": "now", "value": ["ADD", ["var", "now"], ["var", "md"]]})
        npc, body = self.entered(card, imm, pc, locals_, operands_at)
        ins += body
        consts = {"PC": ["int", npc]}
        ins = self.fold_block(ins, dict(consts), locals_)
        ins = self.inline_stmts(ins, locals_, consts)
        return self.fold_block(ins, dict(consts), locals_)

    def finish(self, name: str, params: list, body: list, locals_: dict, cache_regs: bool) -> dict:
        body = self.fold_block(body, {}, locals_)
        if cache_regs:
            body = self.cache_registers(body, locals_)
        self._locals = set(locals_)
        self._exit_live = set()
        body, _ = self.dce(body, set())
        used = {x[1] for s in _stmts(body) for x in _exprs(s) if x[0] == "var"} | \
               {s["target"] for s in _stmts(body) if s["k"] == "assign"}
        return {"name": name, "params": params, "returns": "int",
                "locals": {k: v for k, v in locals_.items() if k in used}, "body": body}

    def single(self, rom: bytes, key: int, mask: int, dec: Decoder) -> dict | None:
        """``ins_K``: the instruction at key on its own, exactly what the interpreter does for it (with EI's delay
        counted down after it), specialised to its bytes."""
        phys, pc = key >> 1, _pc_of(key)
        if dec.avoid and pc < 0x4000 and dec.avoid[0] < pc + 3 and pc < dec.avoid[1]:
            return None                                  # it may read from the scrambled page
        card, n, imm = dec.at(rom, phys, mask)
        if card.get("illegal") or pc + n > (0x8000 if pc >= 0x4000 else 0x4000):
            return None
        locals_: dict = {}
        body = self.step_ir(card, imm, pc, locals_) + copy.deepcopy(COUNTDOWN) + [
            {"k": "assign", "target": "instructions", "value": ["ADD", ["var", "instructions"], ["int", 1]]},
            {"k": "return", "value": ["int", 1]}]
        fn = self.finish(f"ins_{key:x}", [], body, locals_, cache_regs=False)
        fn.update(pc=pc, phys=phys, instructions=1)
        return fn

    def lift(self, rom: bytes, key: int, mask: int, dec: Decoder) -> dict | None:
        """``blk_K(single)``: the block that leads at key, whole when its longest time fits before the next event
        (and not single), else its first instruction on its own (``ins_K``). None for HALT, STOP and EI, which are
        only lifted on their own."""
        ext = block_extent(dec, rom, key, mask)
        if not ext or (ext[0][2].get("prefix") is None and ext[0][2]["opcode"] in EXCLUDED):
            return None
        locals_: dict = {}
        body: list = []
        max_mc = 0
        exits_after = []
        add = lambda k: {"k": "assign", "target": "instructions",  # noqa: E731
                         "value": ["ADD", ["var", "instructions"], ["int", k]]}
        for i, (pc, phys, card, imm) in enumerate(ext):
            mcs = card["mcycles"]
            max_mc += max(len(v) for v in mcs.values()) if isinstance(mcs, dict) else len(mcs)
            ins = self.step_ir(card, imm, pc, locals_)
            body += ins
            if self._moves_event(ins) and i < len(ext) - 1:
                body.append({"k": "if", "cond": ["CMP_GE", ["var", "now"], ["var", "next_event"]],
                             "then": [add(i + 1), {"k": "return", "value": ["int", 1]}], "else": []})
                exits_after.append(i + 1)
        body += [add(len(ext)), {"k": "return", "value": ["int", 1]}]
        pre = [{"k": "if", "cond": ["OR", ["CMP_NE", ["var", "single"], ["int", 0]],
                                    ["CMP_GT", ["ADD", ["var", "now"], ["MUL", ["int", max_mc], ["var", "md"]]],
                                     ["var", "next_event"]]],
                "then": [{"k": "return", "value": ["CALL", f"ins_{key:x}"]}], "else": []}]
        fn = self.finish(f"blk_{key:x}", [{"name": "single", "type": "int"}], pre + body, locals_, cache_regs=True)
        fn.update(pc=_pc_of(key), phys=key >> 1, instructions=len(ext), max_mcycles=max_mc, exits=exits_after,
                  keys=[_key(phys, pc) for pc, phys, _c, _i in ext])
        return fn

    def lift_ram(self, addr: int, encodings: list, dec: Decoder) -> dict | None:
        """``lram_<addr>``: the instruction at RAM address addr, one case for each encoding (opcode, a CB prefix's
        second byte) the profiles saw start there, chosen by the bytes RAM holds when it runs, with its operands read
        from RAM then; 0 when RAM holds none of them, or during OAM DMA outside HRAM (the interpreter runs it)."""
        locals_: dict = {"lf_op": "int", "lf_cb": "int"}
        done = [{"k": "assign", "target": "instructions", "value": ["ADD", ["var", "instructions"], ["int", 1]]},
                {"k": "return", "value": ["int", 1]}]
        plain: list = []
        cb: list = []
        for op, second in sorted(encodings, key=lambda e: (e[0], -1 if e[1] is None else e[1])):
            card = dec.table[(0xCB, second)] if op == 0xCB else dec.table[(None, op)]
            n = 2 if op == 0xCB else card["bytes"]
            if card.get("illegal") or not all(any(lo <= a < hi for lo, hi in RAM_LIFTED) for a in range(addr, addr + n)):
                continue
            body = self.step_ir(card, None, addr, locals_, operands_at=(addr + (2 if op == 0xCB else 1)) & 0xFFFF)
            (cb if op == 0xCB else plain).append((second if op == 0xCB else op,
                                                  body + copy.deepcopy(COUNTDOWN) + copy.deepcopy(done)))
        if not plain and not cb:
            return None

        def chain(var: str, cases: list) -> list:
            out = [{"k": "return", "value": ["int", 0]}]
            for v, b in reversed(cases):
                out = [{"k": "if", "cond": ["CMP_EQ", ["var", var], ["int", v]], "then": b, "else": out}]
            return out

        def read(var: str, a: int) -> list:
            return self.inline_stmts([{"k": "assign", "target": var, "value": ["CALL", "code_byte", ["int", a]]}],
                                     locals_, {})
        if cb:
            plain.append((0xCB, read("lf_cb", (addr + 1) & 0xFFFF) + chain("lf_cb", cb)))
            plain.sort(key=lambda c: c[0])
        body = read("lf_op", addr) + chain("lf_op", plain)
        if addr < 0xFF80:
            body = [{"k": "if", "cond": ["CMP_NE", ["var", "dma_active"], ["int", 0]],
                     "then": [{"k": "return", "value": ["int", 0]}], "else": []}] + body
        body = self.fold_block(body, {}, locals_)
        self._locals = set(locals_)
        self._exit_live = set()
        body, _ = self.dce(body, set())
        used = {x[1] for s in _stmts(body) for x in _exprs(s) if x[0] == "var"} | \
               {s["target"] for s in _stmts(body) if s["k"] == "assign"}
        return {"name": f"lram_{addr:x}", "params": [{"name": "single", "type": "int"}], "returns": "int",
                "locals": {k: v for k, v in locals_.items() if k in used}, "body": body, "pc": addr,
                "encodings": sorted([op, second] for op, second in encodings), "instructions": len(cb) + len(plain) - bool(cb)}

    def instance(self, card, imm: list | None, locals_: dict, operands_at: int | None = None) -> list:
        """The card's IR with its locals renamed and every fetch replaced by the byte it would read: the
        instruction's own bytes (imm), or, with operands_at, what memory holds there when it runs (code in RAM)."""
        if card.get("prefix") is not None:
            fn = card["ir"]
        else:
            fn = card["ir"]
        pfx = self.fresh(card.name.lower())
        ren = {}
        for name, t in (fn.get("locals") or {}).items():
            ren[name] = ["var", f"{pfx}_{name}"]
            locals_[f"{pfx}_{name}"] = t
        body = self.rename_body(copy.deepcopy(fn["body"]), ren)
        pos = [0]

        def take(k):
            v = 0
            for j in range(k):
                v |= imm[pos[0] + j] << (8 * j)
            pos[0] += k
            return v

        out = []
        for s in body:
            if s["k"] == "assign" and isinstance(s["value"], list) and s["value"][0] == "CALL" and \
                    s["value"][1] in ("fetch8", "fetch16"):
                k = 1 if s["value"][1] == "fetch8" else 2
                for _ in range(k):
                    out.append({"k": "assign", "target": "now", "value": ["ADD", ["var", "now"], ["var", "md"]]})
                if operands_at is None:
                    out.append({"k": "assign", "target": s["target"], "value": ["int", take(k)]})
                    continue
                a = (operands_at + pos[0]) & 0xFFFF
                v = ["CALL", "code_byte", ["int", a]]
                if k == 2:
                    v = ["BIT_OR", v, ["SHIFT_LEFT", ["CALL", "code_byte", ["int", (a + 1) & 0xFFFF]], ["int", 8]]]
                pos[0] += k
                out.append({"k": "assign", "target": s["target"], "value": v})
                continue
            if any(x[0] == "CALL" and x[1] in ("fetch8", "fetch16", "cb_dispatch") for st in _stmts([s])
                   for x in _exprs(st)):
                raise ValueError(f"{card.name}: a fetch the lifter cannot place ({s})")
            out.append(s)
        self.taken = pos[0]
        return out

    def _moves_event(self, body) -> bool:
        for st in _stmts(body):
            if st["k"] == "assign" and st["target"] == "next_event":
                return True
            for x in _exprs(st):
                if x[0] == "CALL" and x[1] in self.eff and "next_event" in self.eff[x[1]][1]:
                    return True
        return False

    def cache_registers(self, body, locals_: dict) -> list:
        """CPU registers in locals for the block, when no remaining call reads or writes them."""
        touched = set()
        for st in _stmts(body):
            for x in _exprs(st):
                if x[0] == "CALL" and x[1] in self.eff:
                    r, w = self.eff[x[1]]
                    touched |= r | w
        regs = [r for r in REGS if r not in touched]
        if not regs:
            return body
        written = {st["target"] for st in _stmts(body) if st["k"] == "assign"}
        ren = {r: ["var", f"r_{r}"] for r in regs}
        for r in regs:
            locals_[f"r_{r}"] = "int"
        back = [r for r in regs if r in written]

        def conv(b):
            out = []
            for s in b:
                s = dict(s)
                for key in ("value", "cond", "index"):
                    if key in s:
                        s[key] = self.subst(s[key], ren)
                if s["k"] == "assign" and s["target"] in ren:
                    s["target"] = ren[s["target"]][1]
                if s["k"] == "return":
                    out += [{"k": "assign", "target": r, "value": ["var", f"r_{r}"]} for r in back]
                for key in ("then", "else"):
                    if key in s:
                        s[key] = conv(s[key])
                out.append(s)
            return out

        pro = [{"k": "assign", "target": f"r_{r}", "value": ["var", r]} for r in regs]
        # a precheck that only returns (nothing changed yet) stays before the registers are loaded
        pre = []
        if body and body[0]["k"] == "if" and len(body[0]["then"]) == 1 and body[0]["then"][0]["k"] == "return" \
                and not body[0].get("else"):
            pre, body = [body[0]], body[1:]
        return pre + pro + conv(body)


# -- the lifted machine --------------------------------------------------------------------------------
# what the interpreter does after every instruction: EI's delay counts down, then interrupts are enabled
COUNTDOWN = [{"k": "if", "cond": ["CMP_NE", ["var", "ime_delay"], ["int", 0]], "else": [],
              "then": [{"k": "assign", "target": "ime_delay", "value": ["SUB", ["var", "ime_delay"], ["int", 1]]},
                       {"k": "if", "cond": ["CMP_EQ", ["var", "ime_delay"], ["int", 0]], "else": [],
                        "then": [{"k": "assign", "target": "ime", "value": ["int", 1]}]}]}]


def lifted_module(machine_ir: dict, blocks: list, ram: list = ()) -> dict:
    """The machine with the lifted code: ``run_block(key, single)`` switches over every instruction start, to the
    block it leads (``blk_K``) or else to the instruction on its own (``ins_K``); ``run_ram(pc, single)`` over the
    lifted RAM instructions. ``blocks``: blocks and single instructions together."""
    mod = copy.deepcopy(machine_ir)
    for b in (*blocks, *ram):
        f = {k: v for k, v in b.items() if k in ("name", "params", "returns", "locals", "body")}
        f["export"] = True
        mod["functions"].append(f)
    where: dict = {}
    for b in blocks:
        k = int(b["name"][4:], 16)
        if b["name"].startswith("blk_"):
            where[k] = ["CALL", b["name"], ["var", "single"]]
    for b in blocks:
        k = int(b["name"][4:], 16)
        if b["name"].startswith("ins_"):
            where.setdefault(k, ["CALL", b["name"]])
    cases = [{"match": [k], "body": [{"k": "return", "value": call}]} for k, call in sorted(where.items())]
    ram_cases = [{"match": [r["pc"]], "body": [{"k": "return", "value": ["CALL", r["name"], ["var", "single"]]}]}
                 for r in sorted(ram, key=lambda r: r["pc"])]
    for f in mod["functions"]:
        if f["name"] == "run_block":
            f["body"] = [{"k": "switch", "value": ["var", "key"], "cases": cases},
                         {"k": "return", "value": ["int", 0]}]
            f["export"] = True
        if f["name"] == "run_ram" and ram_cases:
            f["body"] = [{"k": "switch", "value": ["var", "pc"], "cases": ram_cases},
                         {"k": "return", "value": ["int", 0]}]
            f["export"] = True
    for x in (*mod.get("globals", []), *mod.get("arrays", []), *mod["functions"]):
        x["export"] = True
    return mod


def cache_dir(ctx, rom_sha: str, machine_hash: str) -> Path:
    """The ROM's folder for a machine: its profile (what the interpreter saw, which no lifter changes) and what
    lifters made from it, in files whose names carry LIFTER."""
    d = ctx.state_root / "emu" / f"{rom_sha[:16]}-{machine_hash[:10]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def merge_profile(d: Path, name: str, data: bytes) -> bytes:
    p = d / f"{name}.bin"
    old = p.read_bytes() if p.is_file() else b""
    n = max(len(old), len(data))
    a, b = old.ljust(n, b"\0"), data.ljust(n, b"\0")
    merged = bytes(x | y for x, y in zip(a, b)).rstrip(b"\0")
    p.write_bytes(merged)
    return merged


def scrambled_page(store, rom: bytes) -> tuple | None:
    """The CPU address range whose bytes the cartridge's board scrambles (Sachen: the header page), from the
    cartridge card; None for every other board. ``store``: a card store, or a context holding one."""
    from . import gb as G
    card = getattr(store, "store", store).get("hardware/gb_cartridge")
    if G.unlicensed(rom, card, None) != "sachen":
        return None
    lo, hi = ((card.get("unlicensed") or {}).get("sachen") or {}).get("header_page") or (0x100, 0x200)
    return int(lo), int(hi)


def ram_encodings(ram_ops: bytes | None, ram_cb: bytes | None) -> dict[int, list[tuple[int, int | None]]]:
    """{RAM address: [(opcode, a CB prefix's second byte or None)]}: every encoding the profile saw an instruction
    start with at each address (the machine's ram_ops and ram_cb: 256 bits per address from RAM_BASE)."""
    out: dict = {}
    ops, cbs = ram_ops or b"", ram_cb or b""
    for row in range((len(ops) + 31) >> 5):                  # a stored profile ends at its last byte in use
        bits = ops[row << 5:(row + 1) << 5].ljust(32, b"\0")
        if not any(bits):
            continue
        found = []
        for op in range(256):
            if not bits[op >> 3] >> (op & 7) & 1:
                continue
            if op != 0xCB:
                found.append((op, None))
                continue
            second = cbs[row << 5:(row + 1) << 5].ljust(32, b"\0")
            found += [(0xCB, c) for c in range(256) if second[c >> 3] >> (c & 7) & 1]
        if found:
            out[RAM_BASE + row] = found
    return out


def lift_blocks(ctx, rom: bytes, mask: int, seen: bytes | None = None, entries: bytes | None = None,
                machine: str = "gameboy", cache: dict | None = None, ram_ops: bytes | None = None,
                ram_cb: bytes | None = None) -> tuple[list, list, dict]:
    """Discover and lift every block, and every RAM instruction the profile saw: (blocks, RAM instructions,
    report). ``cache`` maps block keys to blocks lifted before (for the same ROM and machine) and receives the new
    ones."""
    ir = Bd.module(ctx, machine)
    avoid = scrambled_page(ctx.store, rom)
    found = discover(ctx.store, rom, mask, seen, entries, avoid)
    lifter = Lifter(ctx, ir)
    dec = Decoder(ctx.store, avoid=avoid)
    blocks = []
    singles: dict = {}
    instrs = 0
    reused = 0

    def cached(ck, make):
        nonlocal reused
        b = (cache or {}).get(ck)
        if b is None:
            b = make()
            if cache is not None and b is not None:
                cache[ck] = b
        else:
            reused += 1
        return b
    for key in found["leaders"]:
        resources.guard("lift")
        b = cached(str(key), lambda: lifter.lift(rom, key, mask, dec))
        keys = b["keys"] if b is not None else [key]
        if b is not None:
            blocks.append(b)
            instrs += b["instructions"]
        for k in keys:
            if k not in singles:
                singles[k] = cached(f"i{k}", lambda k=k: lifter.single(rom, k, mask, dec))
    blocks += [s for s in singles.values() if s is not None]
    encodings = ram_encodings(ram_ops, ram_cb)
    ram = [r for r in (lifter.lift_ram(a, e, dec) for a, e in sorted(encodings.items())) if r is not None]
    stmts = sum(1 for b in blocks for _ in _stmts(b["body"]))
    seen_n = sum(bin(x).count("1") for x in seen) if seen else 0
    nblk = sum(1 for b in blocks if b["name"].startswith("blk_"))
    rep = {"blocks": nblk, "single_instructions": len(blocks) - nblk, "reused": reused,
           "instructions_lifted": instrs, "statements": stmts,
           "profiled_instructions": seen_n, "visited": found["visited"],
           "mean_block_instructions": round(instrs / max(1, nblk), 2),
           "ram_instructions_seen": sum(len(e) for e in encodings.values()),
           "ram_instructions_lifted": sum(r["instructions"] for r in ram), "ram_addresses_lifted": len(ram)}
    return blocks, ram, rep


def lift_rom(ctx, rom: bytes, mask: int, seen: bytes | None = None, entries: bytes | None = None,
             machine: str = "gameboy", cache: dict | None = None, ram_ops: bytes | None = None,
             ram_cb: bytes | None = None) -> tuple[dict, dict]:
    """The machine with the ROM's lifted blocks (and its lifted RAM code): (module, report)."""
    ir = Bd.module(ctx, machine)
    blocks, ram, rep = lift_blocks(ctx, rom, mask, seen, entries, machine, cache, ram_ops, ram_cb)
    mod = lifted_module(ir, blocks, ram)
    mod["hash"] = hashlib.sha256((ir["hash"] + json.dumps([blocks, ram], sort_keys=True)).encode()).hexdigest()[:20]
    return mod, rep


# -- building the library in parts ---------------------------------------------------------------------
def build_parts(ctx, mod: dict, lang: str, out_dir: Path, per_part: int = 1500, prune: bool = False) -> Path:
    """Emit the lifted module as several compile units, compile them (cached), link one library. prune: the
    folder holds one library's parts, so parts and libraries of earlier builds go."""
    card = ctx.language(lang)
    emb = card["embed"]
    if "compile_object" not in emb or "link" not in emb:
        lib, _ = N.build_library(ctx, mod, lang)
        return lib
    ok, exe = N.probes.probe(card.get("probe"))
    if not ok:
        raise N.EngineError(f"{lang} is not available: {exe}")
    lifted = [f for f in mod["functions"] if f["name"].startswith(("blk_", "ins_"))]
    blocks = sorted((int(f["name"][4:], 16), f["name"]) for f in lifted)
    size = {f["name"]: sum(1 for _ in _stmts(f["body"])) for f in lifted}
    # stable groups: one part per ROM bank (split further when a bank is very busy: at most per_part blocks and
    # PART_STATEMENTS statements, so no compile unit outgrows a compiler's memory), the dispatcher on its own, so a
    # grown profile recompiles only the banks that gained blocks
    by_bank: dict = {}
    for key, name in blocks:
        by_bank.setdefault(key >> 15, []).append(name)
    groups = [["run_block"]]
    for bank in sorted(by_bank):
        cur: list = []
        n = 0
        for name in by_bank[bank]:
            if cur and (len(cur) >= per_part or n + size[name] > PART_STATEMENTS):
                groups.append(cur)
                cur, n = [], 0
            cur.append(name)
            n += size[name]
        if cur:
            groups.append(cur)
    ram = [f["name"] for f in mod["functions"] if f["name"].startswith("lram_")]
    if ram:
        groups.append(ram + ["run_ram"])
    em = Emitter(ctx.store, lang, ctx.ops)
    parts = em.split_sources(mod, groups)
    objs = []
    for i, src in enumerate(parts):
        h = hashlib.sha256(f"{lang}\0{src}\0{emb['compile_object']}".encode()).hexdigest()[:20]
        obj = out_dir / f"part-{h}.o"
        if not obj.is_file():
            srcp = out_dir / f"part-{h}{Path(emb.get('file', 'm.c')).suffix}"
            srcp.write_text(src, encoding="utf-8")
            tmp = out_dir / f".obj-{os.getpid()}-{i}.o"
            args = [a.format(exe=exe, src=str(srcp), obj=str(tmp), dir=str(out_dir)) for a in emb["compile_object"]]
            p = resources.run(args, cwd=out_dir, timeout=N.COMPILE_TIMEOUT_S, stdin=subprocess.DEVNULL)
            if p.returncode != 0:
                raise N.EngineError(f"{lang}: compiling part {i} failed: {(p.stderr or p.stdout)[-2000:]}")
            tmp.replace(obj)
            srcp.unlink()
        objs.append(obj)
    lib = out_dir / f"lifted-{mod['hash']}{N._lib_suffix()}"
    if not lib.is_file():
        tmp = out_dir / f".lib-{os.getpid()}{N._lib_suffix()}"
        args = []
        for a in emb["link"]:
            if a == "{objs}":
                args += [str(o) for o in objs]
            else:
                args.append(a.format(exe=exe, lib=str(tmp), dir=str(out_dir)))
        p = resources.run(args, cwd=out_dir, timeout=N.COMPILE_TIMEOUT_S, stdin=subprocess.DEVNULL)
        if p.returncode != 0:
            raise N.EngineError(f"{lang}: linking failed: {(p.stderr or p.stdout)[-2000:]}")
        tmp.replace(lib)
    if prune:
        for old in [*out_dir.glob("part-*.o"), *out_dir.glob(f"lifted-*{N._lib_suffix()}")]:
            if old not in objs and old != lib:
                old.unlink(missing_ok=True)
    return lib




# -- the lifted engine for a ROM ------------------------------------------------------------------------
def profile(ctx, rom: bytes, frames: int = 1800, machine: str = "gameboy", script=None) -> dict:
    """Run the interpreter headless with a scripted input (the survey's by default) and return what it ran:
    {seen, entries} (ROM bitmaps), {ram_ops, ram_cb} (the encodings seen at each RAM address)."""
    from . import gb as G
    from .survey import script as survey_script
    press = script or survey_script
    g = G.GameBoy(ctx, rom, "native", sample_rate=0, fresh=True)
    g.m.set("profiling", 1)
    for i in range(frames):
        g.set_buttons(press(i))
        g.run_frame()
    n = (int(g.m.get("rom_mask")) + 1) // 8
    out = {"seen": g.m.read("seen", 0, n), "entries": g.m.read("entries", 0, n), **ram_profile(g.m)}
    if hasattr(g.m, "close"):
        g.m.close()
    return out


def profile_rom(ctx, rom: bytes, frames: int = 1800, machine: str = "gameboy") -> tuple[bytes, bytes]:
    """(seen, entries) of a profile run (``profile``)."""
    p = profile(ctx, rom, frames, machine)
    return p["seen"], p["entries"]


def ram_profile(m) -> dict:
    """What a machine saw run in RAM: {ram_ops, ram_cb}, only the rows in use (an empty profile is b"")."""
    return {k: m.read(k, 0, 0x80000).rstrip(b"\0") for k in ("ram_ops", "ram_cb")}


PROFILE = ("seen", "entries", "ram_ops", "ram_cb")     # a profile's bitmaps (each merges by OR)


def stored_profile(d: Path) -> dict:
    """The profile kept in a ROM's lift folder (empty bitmaps where there is none yet)."""
    def get(name):
        p = d / f"{name}.bin"
        return p.read_bytes() if p.is_file() else b""
    return {k: get(k) for k in PROFILE}


def add_profile(d: Path, p: dict) -> dict:
    """Merge a profile run into the ROM's lift folder; returns the merged profile."""
    for k in PROFILE:
        merge_profile(d, k, p.get(k) or b"")
    return stored_profile(d)


def lifted_machine(ctx, rom: bytes, lang: str = "native", machine: str = "gameboy", profile_frames: int = 1800,
                   progress=None, relift: bool = False) -> tuple:
    """(Machine running the ROM's lifted blocks, report). Cached per ROM + machine + profile; the profile grows
    with every session that calls ``save_profile``."""
    from . import gb as G
    say = progress or (lambda msg: None)
    lang = N.resolve_engine(ctx, lang)
    info = G.header(rom, ctx.store)
    base = Bd.module(ctx, machine)
    d = cache_dir(ctx, info["sha1"], base["hash"])
    ent_p = d / "entries.bin"
    if not ent_p.is_file():
        say(f"profiling {profile_frames} frames in the interpreter (first run of this ROM)")
        add_profile(d, profile(ctx, rom, profile_frames, machine))
    prof = stored_profile(d)
    seen, entries = prof["seen"], prof["entries"]
    bits = sum(bin(x).count("1") for x in entries + prof["ram_ops"] + prof["ram_cb"])
    pkey = hashlib.sha256(b"\0".join(prof[k] for k in PROFILE)).hexdigest()[:16]
    meta_p = d / f"lifted-{pkey}-{lang}-l{LIFTER}.json"
    latest = d / f"latest-{lang}-l{LIFTER}.json"
    if not meta_p.is_file() and latest.is_file() and not relift:
        last = json.loads(latest.read_text(encoding="utf-8"))
        if bits - last.get("entries", 0) < max(64, bits // 50):      # little new code seen: keep the last build
            meta_p = latest
    if meta_p.is_file():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        lib = Path(meta["lib"])
        if lib.is_file():
            ir = copy.deepcopy(base)
            for x in (*ir.get("globals", []), *ir.get("arrays", []), *ir["functions"]):
                x["export"] = True
            return N.CABIMachine(ctx, ir, lang, lib_path=lib), meta["report"]
    size = 0x8000
    while size < len(rom):
        size <<= 1
    say("lifting the ROM's code into card IR")
    bc = d / f"blocks-l{LIFTER}.json"
    cache = json.loads(bc.read_text(encoding="utf-8")) if bc.is_file() else {}
    n0 = len(cache)
    mod, rep = lift_rom(ctx, rom, size - 1, seen, entries, machine, cache=cache, ram_ops=prof["ram_ops"],
                        ram_cb=prof["ram_cb"])
    if len(cache) != n0:
        tmp = bc.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        tmp.replace(bc)
    say(f"lifted {rep['blocks']} blocks ({rep['instructions_lifted']} instructions); compiling natively")
    lib = build_parts(ctx, mod, lang, d)
    rep["library"] = lib.name
    meta = json.dumps({"lib": str(lib), "report": rep, "entries": bits}, indent=1)
    meta_p.write_text(meta, encoding="utf-8")
    latest.write_text(meta, encoding="utf-8")
    return N.CABIMachine(ctx, mod, lang, lib_path=lib), rep


def save_profile(ctx, rom: bytes, m, machine: str = "gameboy") -> dict:
    """Merge what this session's interpreter fallback saw into the ROM's profile (next launch lifts it)."""
    from . import gb as G
    info = G.header(rom, ctx.store)
    d = cache_dir(ctx, info["sha1"], Bd.module(ctx, machine)["hash"])
    n = (int(m.get("rom_mask")) + 1) // 8
    before = (d / "entries.bin").read_bytes() if (d / "entries.bin").is_file() else b""
    after = add_profile(d, {"seen": m.read("seen", 0, n), "entries": m.read("entries", 0, n), **ram_profile(m)})
    return {"new_entries": sum(bin(x).count("1") for x in after["entries"]) - sum(bin(x).count("1") for x in before)}


__all__ = ["Decoder", "Lifter", "add_profile", "conditional", "block_extent", "build_parts", "cache_dir", "discover", "effects",
           "lift_blocks", "lift_rom", "lifted_machine", "lifted_module", "merge_profile", "profile", "profile_rom",
           "ram_encodings", "ram_profile", "save_profile", "stored_profile"]
