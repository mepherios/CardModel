"""lift_arm — the same pipeline for ARM code: blocks of ARM instructions as specialised card IR (the DS ARM9).

An ARM instruction card is a function of its instruction word (``op``). A block is the cards' IR inlined with
constant words, so every field extraction folds away; constant-bound loops (LDM/STM register lists) are unrolled,
pure helpers with constant arguments (``popcount16``) are evaluated at lift time, and the condition field becomes
one test of the flags.

DS code lives in RAM and overlays replace it while the game runs, so each block starts with **guards**: the
instruction words it was lifted from must still be in memory, otherwise the interpreter runs. Inside the block the
machine behaves as the interpreter would between its per-instruction checks: the block leaves after a branch,
and after any instruction that may raise an interrupt, halt or stop the CPU or change CPSR (an I/O write, MSR,
SWI, a coprocessor access, an undefined instruction).

Honest limits (L1): ARM state on the ARM9 only (Thumb and the ARM7 stay interpreted); a block ends at every
instruction that may write R15; the guards read every word through the bus, so for RAM-resident code a block
costs about what the interpreter's fetches cost (the decode is what it saves).
"""
from __future__ import annotations

import copy
import hashlib
import json

from ..engines.ir import Interpreter
from . import build as Bd
from . import isa as I
from .bench import decoded_by
from .lift import Lifter, _exprs, _iter, _stmts

MAX_BLOCK = 32
CHECKED = {"@ime", "@ie", "@irqf", "@halted_cpu", "@stopped_cpu", "cpsr", "cur"}


def _ends_block(card, op: int) -> bool:
    g = card["group"]
    rd = (op >> 12) & 0xF
    if g in ("branch", "exception", "coprocessor", "psr", "misc"):
        return True
    if g == "block" and (op >> 15) & 1 and card.name == "ARM_LDM":
        return True
    if g in ("data_processing", "load_store", "load_store_extra", "multiply", "swap", "saturating",
             "dsp_multiply") and rd == 15:
        return True
    if g in ("multiply", "dsp_multiply") and (op >> 16) & 0xF == 15:
        return True
    return False


class ArmLifter(Lifter):
    def __init__(self, ctx, machine_ir: dict):
        super().__init__(ctx, machine_ir, isa="armv5te")
        self.inline_always = {n for n in self.inline_always if n not in ("rd8", "wr8", "idle", "fetch8", "fetch16")}
        self.inline_const = set()
        self.cards = I.instructions(ctx.store, "armv5te")
        self.pure = {n for n, (r, w) in self.eff.items() if not r and not w}
        self.interp = Interpreter(machine_ir, ctx.ops, step_limit=1_000_000)
        # globals that only live inside one instruction (the shifter carry): block locals here
        self.instruction_locals = list(I.isa_card(ctx.store, "armv5te").get("instruction_locals") or [])
        # a block is entered in ARM state and only its last instruction can change state
        self.fns = dict(self.fns)
        self.fns["thumb"] = {**self.fns["thumb"], "body": [{"k": "return", "value": ["bool", False]}]}

    # constant calls to pure functions are evaluated now; constant-bound loops are unrolled
    def fold(self, e):
        e = super().fold(e)
        if isinstance(e, list) and e and e[0] == "CALL" and e[1] in self.pure and \
                all(isinstance(a, list) and a[0] in ("int", "bool") for a in e[2:]):
            try:
                v = self.interp.call(e[1], [a[1] for a in e[2:]])
            except Exception:  # noqa: BLE001 -- a failing evaluation keeps the call (the runtime decides)
                return e
            if isinstance(v, bool):
                return ["bool", v]
            if isinstance(v, int):
                return ["int", v]
        return e

    def unroll(self, body, locals_):
        out = []
        for s in body:
            if s["k"] == "for_range" and s["start"][0] == "int" and s["stop"][0] == "int" and s["step"][0] == "int":
                rng = range(s["start"][1], s["stop"][1], s["step"][1])
                if len(rng) <= 16 and not any(x["k"] in ("break", "continue") for x in _stmts(s["body"])):
                    for i in rng:
                        out.append({"k": "assign", "target": s["var"], "value": ["int", i]})
                        out += self.unroll(copy.deepcopy(s["body"]), locals_)
                    continue
            s = dict(s)
            for key in ("then", "else", "body"):
                if key in s:
                    s[key] = self.unroll(s[key], locals_)
            out.append(s)
        return out

    def extent(self, words) -> list:
        """[(address, word, card)] from a start address while the instructions do not end the block."""
        out = []
        for a, op in words:
            card = decoded_by(self.cards, op, "arm") if (op >> 28) != 0xF else None
            if card is None:
                break
            out.append((a, op, card))
            if _ends_block(card, op) or len(out) >= MAX_BLOCK:
                break
        return out

    def _checked_effect(self, body) -> bool:
        for st in _stmts(body):
            if st["k"] == "assign" and st["target"] in CHECKED:
                return True
            if st["k"] == "store" and "@" + st["array"] in CHECKED:
                return True
            for x in _exprs(st):
                if x[0] == "CALL" and x[1] in self.eff and (self.eff[x[1]][1] & CHECKED):
                    return True
        return False

    def localise(self, body, locals_):
        for g in self.instruction_locals:
            loc = f"l_{g}"
            locals_[loc] = "int"
            body = _rename_global(body, g, loc)
        return body

    def cache_array_registers(self, body, locals_, n_guards: int):
        """regs[k] with constant k in locals for the block, when every access is constant and no remaining call
        touches the array; the guards run first, so the loads come after them."""
        reads, writes, dyn = _array_accesses(body, "regs")
        if dyn or not (reads | writes):
            return body
        for st in _stmts(body):
            for x in _exprs(st):
                if x[0] == "CALL" and x[1] in self.eff and "@regs" in (self.eff[x[1]][0] | self.eff[x[1]][1]):
                    return body
        locs = {k: f"ra{k}" for k in sorted(reads | writes)}
        for v in locs.values():
            locals_[v] = "int"
        guards, rest = body[:n_guards], body[n_guards:]
        pro = [{"k": "assign", "target": locs[k], "value": ["LOAD", "regs", ["int", k]]} for k in sorted(reads | writes)]
        return guards + pro + _subst_array(rest, "regs", locs, writes)

    def lift(self, start: int, words) -> dict | None:
        ext = self.extent(words)
        if not ext:
            return None
        locals_: dict = {}
        body: list = []
        for a, op, _ in ext:
            body.append({"k": "if", "cond": ["CMP_NE", ["CALL", "guard_word", ["int", a]], ["int", op]],
                         "then": [{"k": "return", "value": ["int", 0]}], "else": []})
        n = len(ext)
        for k, (a, op, card) in enumerate(ext):
            ins = [{"k": "assign", "target": "pc", "value": ["int", a]},
                   {"k": "assign", "target": "next_pc", "value": ["int", (a + 4) & 0xFFFFFFFF]}]
            call = self.inline_body(card.name, [["int", op]], None, locals_)
            call = self.unroll(call, locals_)
            c = (op >> 28) & 0xF
            if c != 14:
                call = [{"k": "if", "cond": ["CALL", "cond_ok", ["int", c]], "then": call, "else": []}]
            ins += call
            consts = {"pc": ["int", a]}
            ins = self.fold_block(ins, dict(consts), locals_)
            ins = self.inline_stmts(ins, locals_, consts)
            ins = self.unroll(ins, locals_)
            ins = self.fold_block(ins, dict(consts), locals_)
            body += ins
            done = [{"k": "assign", "target": "pc", "value": ["var", "next_pc"]},
                    {"k": "store", "array": "executed", "index": ["int", 0],
                     "value": ["ADD", ["LOAD", "executed", ["int", 0]], ["int", k + 1]]},
                    {"k": "return", "value": ["int", k + 1]}]
            if k == n - 1:
                body += done
            else:
                cond = ["CMP_NE", ["var", "next_pc"], ["int", (a + 4) & 0xFFFFFFFF]]
                if self._checked_effect(ins):
                    cond = ["OR", cond, ["CALL", "cpu_must_check"]]
                body.append({"k": "if", "cond": cond, "then": copy.deepcopy(done), "else": []})
        body = self.fold_block(body, {}, locals_)
        body = self.localise(body, locals_)
        body = self.cache_array_registers(body, locals_, n_guards=n)
        self._locals = set(locals_)
        self._exit_live = set()
        body, _ = self.dce(body, set())
        used = {x[1] for s in _stmts(body) for x in _exprs(s) if x[0] == "var"} | \
               {s["target"] for s in _stmts(body) if s["k"] == "assign"}
        return {"name": f"ablk_{start:x}", "params": [], "returns": "int",
                "locals": {k: v for k, v in locals_.items() if k in used}, "body": body,
                "pc": start, "instructions": n}


def _rename_global(body, old: str, new: str):
    def ex(e):
        if not isinstance(e, list) or not e:
            return e
        if e[0] == "var":
            return ["var", new] if e[1] == old else e
        if e[0] in ("int", "float", "bool"):
            return e
        start = 2 if e[0] in ("CALL", "LOAD") else 1
        return [*e[:start], *[ex(a) for a in e[start:]]]
    out = []
    for s in body:
        s = dict(s)
        for key in ("value", "cond", "index", "start", "stop"):
            if key in s:
                s[key] = ex(s[key])
        if s["k"] == "assign" and s["target"] == old:
            s["target"] = new
        for key in ("then", "else", "body"):
            if key in s:
                s[key] = _rename_global(s[key], old, new)
        out.append(s)
    return out


def _array_accesses(body, name: str):
    """(constant indices read, constant indices written, any dynamic access)"""
    reads, writes, dyn = set(), set(), False
    for st in _stmts(body):
        if st["k"] == "store" and st["array"] == name:
            if st["index"][0] == "int":
                writes.add(st["index"][1])
            else:
                dyn = True
        for x in _exprs(st):
            if x[0] == "LOAD" and x[1] == name:
                if x[2][0] == "int":
                    reads.add(x[2][1])
                else:
                    dyn = True
    return reads, writes, dyn


def _subst_array(body, name: str, locs: dict, written: set):
    """Constant-index accesses of ``name`` become the locals ``locs``; the ``written`` ones are stored back before
    every exit of the block (a guard's ``return 0`` runs before the locals are loaded)."""
    def ex(e):
        if not isinstance(e, list) or not e:
            return e
        if e[0] == "LOAD" and e[1] == name and e[2][0] == "int" and e[2][1] in locs:
            return ["var", locs[e[2][1]]]
        if e[0] in ("var", "int", "float", "bool"):
            return e
        start = 2 if e[0] in ("CALL", "LOAD") else 1
        return [*e[:start], *[ex(a) for a in e[start:]]]
    out = []
    for s in body:
        s = dict(s)
        for key in ("value", "cond", "index"):
            if key in s:
                s[key] = ex(s[key])
        if s["k"] == "store" and s["array"] == name and s["index"][0] == "int" and s["index"][1] in locs:
            s = {"k": "assign", "target": locs[s["index"][1]], "value": s["value"]}
        if s["k"] == "return" and s.get("value") != ["int", 0]:
            out += [{"k": "store", "array": name, "index": ["int", k], "value": ["var", v]}
                    for k, v in sorted(locs.items()) if k in written]
        for key in ("then", "else", "body"):
            if key in s:
                s[key] = _subst_array(s[key], name, locs, written)
        out.append(s)
    return out


def leaders(exec_map: bytes, base: int) -> list[int]:
    """ARM-state instruction addresses where execution entered (the first of a run of executed words)."""
    out = []
    prev = False
    for h in range(0, len(exec_map), 2):
        arm = bool(exec_map[h] & 1)
        if arm and not prev:
            out.append(base + h * 2)
        prev = arm
    return out


def lifted_nds_module(ctx, ds, max_blocks: int = 4000) -> tuple[dict, dict]:
    """Lift the ARM9's executed ARM code (from the DS machine's exec map and memory) into a module with run_block."""
    ir = Bd.module(ctx, "nds")
    lifter = ArmLifter(ctx, ir)
    emap = ds.m.read("exec9")
    mram = ds.m.read("mram")
    starts = leaders(emap, 0x02000000)
    blocks = []
    for a in starts[:max_blocks]:
        o = a - 0x02000000
        words = [(a + 4 * i, int.from_bytes(mram[o + 4 * i:o + 4 * i + 4], "little")) for i in range(MAX_BLOCK)
                 if o + 4 * i + 4 <= len(mram)]
        b = lifter.lift(a, words)
        if b is not None:
            blocks.append(b)
    mod = copy.deepcopy(ir)
    for b in blocks:
        mod["functions"].append({k: v for k, v in b.items() if k in ("name", "params", "returns", "locals", "body")})
    cases = [{"match": [b["pc"]], "body": [{"k": "return", "value": ["CALL", b["name"]]}]} for b in blocks]
    for f in mod["functions"]:
        if f["name"] == "run_block":
            f["body"] = [{"k": "switch", "value": ["var", "key"], "cases": cases}, {"k": "return", "value": ["int", 0]}]
    for x in (*mod.get("globals", []), *mod.get("arrays", []), *mod["functions"]):
        x["export"] = True
    mod["hash"] = hashlib.sha256((ir["hash"] + json.dumps(blocks, sort_keys=True)).encode()).hexdigest()[:20]
    return mod, {"blocks": len(blocks), "instructions": sum(b["instructions"] for b in blocks), "leaders": len(starts)}


def state_hash(m) -> str:
    """Both CPUs' registers, CPSR/SPSR/PC and every RAM: what a differential run compares."""
    h = hashlib.sha1()
    for arr in ("mram", "swram", "wram7", "itcm", "dtcm"):
        h.update(m.read(arr))
    for arr in ("regs", "banked", "ctx_r", "ctx_banked", "ctx_misc", "executed"):
        a = m.array(arr)
        h.update(json.dumps([a[i] for i in range(len(a))]).encode())
    for g in ("pc", "cpsr", "spsr", "cur"):
        h.update(str(m.get(g)).encode())
    return h.hexdigest()


def differential(ctx, rom: bytes, profile_frames: int, frames: int, out_dir=None) -> dict:
    """Profile, lift the ARM9's ARM code, then run lifted and interpreted side by side for ``frames``."""
    import time
    from pathlib import Path
    from . import lift
    from . import native as N
    from . import nds
    prof = nds.DS(ctx, rom, engine="native")
    prof.run(profile_frames)
    mod, rep = lifted_nds_module(ctx, prof)
    d = Path(out_dir) if out_dir else ctx.state_root / "emu" / f"nds-{hashlib.sha1(rom).hexdigest()[:16]}"
    d.mkdir(parents=True, exist_ok=True)
    lang = N.resolve_engine(ctx, "native")
    lib = lift.build_parts(ctx, mod, lang, d, per_part=800)
    ml = N.CABIMachine(ctx, mod, lang, lib_path=lib)
    lifted = nds.DS.__new__(nds.DS)
    lifted.ctx, lifted.rom, lifted.info, lifted.ir, lifted.m = ctx, rom, nds.header(rom, ctx.store), mod, ml
    lifted.load()
    ml.set("lifted_on", 1)
    ref = nds.DS(ctx, rom, engine="native")
    ref.m = N.load(ctx, ref.ir, "native", fresh=True)
    ref.load()
    ti = tl = 0.0
    first = None
    for f in range(frames):
        t0 = time.perf_counter()
        ref.m.call("run_frame")
        ti += time.perf_counter() - t0
        t0 = time.perf_counter()
        ml.call("run_frame")
        tl += time.perf_counter() - t0
        if state_hash(ref.m) != state_hash(ml):
            first = f
            break
    return {"verdict": "identical" if first is None else "different", "first_difference": first,
            "frames_compared": frames if first is None else first + 1, "blocks": rep["blocks"],
            "instructions_lifted": rep["instructions"], "block_runs": ml.get("block_runs"),
            "interp_s": round(ti, 3), "lifted_s": round(tl, 3), "speedup": round(ti / tl, 2) if tl else None}


__all__ = ["ArmLifter", "differential", "leaders", "lifted_nds_module", "state_hash"]
