"""symbolic — an instruction card's meaning as terms (docs/MATH_CORE.md phase 0, F5).

The instruction cards' semantics are card-language programs over the CPU's registers, calling the bus (``rd8``,
``wr8``, ``idle``, ...). ``Executor.run`` executes the compiled IR of one instruction over *symbolic* registers: every
register starts as a variable of its own name, a bus read returns a fresh variable (rd0, rd1, ...), and a condition
that depends on symbols splits the path. The two sides are merged as IF_EXPR terms, and every bus effect keeps the
condition (guard) under which it happens. The result is the instruction as mathematics: each register it changes as
a term over the registers it reads and the bytes it reads, and its bus activity, in order, with guards.

``check`` holds those terms to the instruction's executable semantics. For seeded states (registers, flags, both
outcomes of a condition, random memory with the instruction at PC), the bench machine (``machine/<isa>_bench``,
the conformance reference) runs the instruction, and the terms are evaluated on the same state and the bytes they
read. Every register, every byte written, the M-cycle count and the halt/stop/lock effects must agree.

Honest limits (L1): checked on seeded states, not proved for all of them (the exhaustive check over small
input spaces and the proof are next); the IR it reads has no loops (the LR35902 cards have none), and a return taken
on one side of a branch only is reported unsupported; terms are not simplified beyond constant folding (the
e-graph canonicalizes them as a separate step).
"""
from __future__ import annotations

import json
import random
from collections import Counter

from ..lang.compile import compile_sources
from . import isa as I

EFFECTS = ("rd8", "wr8", "idle", "idu", "rd8_idu", "halt", "stop", "hang", "cb_dispatch",
           # the ARM bus contract: halfword/word reads and writes, and the exception / coprocessor hooks
           "rd16", "rd32", "wr16", "wr32", "swi", "undefined_op", "cp_read", "cp_write",
           # the MIPS bus contract's hooks
           "syscall_op", "break_op", "exception")
READS = ("rd8", "rd8_idu")
# every effect that returns a value, with the sort of that value (a read is typed by its width)
READ_SORTS = {"rd8": "u8", "rd8_idu": "u8", "rd16": "u16", "rd32": "u32", "cp_read": "u32"}
WRITE_BYTES = {"wr8": 1, "wr16": 2, "wr32": 4}
CYCLES = ("rd8", "wr8", "idle", "idu", "rd8_idu")


class Unsupported(Exception):
    """The IR uses something the executor does not handle (said precisely)."""


def module(ctx, isa: str):
    ic = I.isa_card(ctx.store, isa)
    cards = I.instructions(ctx.store, isa)
    sources = [(I.library_text(ic, "core"), f"isa/{isa}/core"), (I.library_text(ic, "interface"), f"isa/{isa}/iface"),
               (I.semantics_source(cards, ic.get("operand_param")), f"isa/_pack_{isa}.jsonl")]
    return compile_sources(sources, ctx.ops, ctx.store, name=f"isa_{isa}"), cards


def _const(t) -> bool:
    return isinstance(t, list) and len(t) == 2 and t[0] in ("int", "bool")


def _val(t):
    return t[1]


def _walk(stmts):
    for x in stmts:
        yield x
        for key in ("then", "else", "body", "default"):
            if isinstance(x.get(key), list):
                yield from _walk(x[key])
        for c in x.get("cases") or []:
            yield from _walk(c["body"])


class Executor:
    def __init__(self, ctx, mod):
        self.ops = ctx.ops
        self.fns = mod.functions
        self.globals = [g["name"] for g in mod.globals if g["name"] != "bus_effect"]
        self.sizes = {a["name"]: a["size"] for a in getattr(mod, "arrays", None) or []}

    ARRAY_MAX = 64

    def _size(self, name):
        n = self.sizes.get(name)
        if n is None or n > self.ARRAY_MAX:
            raise Unsupported(f"{name}[] indexed by a symbolic term")
        return n

    def fold(self, t):
        head, args = t[0], t[1:]
        if head == "IF_EXPR" and _const(args[0]):
            return args[1] if _val(args[0]) else args[2]
        if head in ("AND", "OR") and all(_const(a) for a in args):
            v = (_val(args[0]) and _val(args[1])) if head == "AND" else (_val(args[0]) or _val(args[1]))
            return ["bool", bool(v)]
        if head in ("AND", "OR") and any(_const(a) and bool(_val(a)) == (head == "OR") for a in args):
            # the absorbing element: ``x or True`` is True, ``x and False`` is False (an unrolled loop's constant
            # index decides a guard, and the side it rules out must not run: it may index outside an array)
            return ["bool", head == "OR"]
        if head in self.ops and head not in ("IF_EXPR", "AND", "OR") and args and all(_const(a) for a in args):
            try:
                v = self.ops[head].fn(*[_val(a) for a in args])
            except Exception:  # noqa: BLE001 -- not foldable (division by zero, ...): keep the term
                return t
            return ["bool", v] if isinstance(v, bool) else (["int", v] if isinstance(v, int) else t)
        return t

    def run(self, fname: str, args: dict | None = None) -> dict:
        """``args`` binds the function's parameters (the ARM cards' instruction word ``op``) to concrete values: the
        terms are then the meaning of that one encoding. Array cells indexed by a constant are registers of their own
        (``regs[3]`` is the variable ``regs3``); a symbolic index is a select (load) or guarded write (store) over the
        cells. Loops unroll when their bounds fold to constants under the bound word."""
        self.effects, self.nread = [], 0
        state = {g: ["var", g] for g in self.globals}
        args = args or {}
        missing = [p["name"] for p in self.fns[fname]["params"] if p["name"] not in args]
        if missing:
            raise Unsupported(f"unbound parameter {missing[0]}")
        env = {"g": state, "l": {k: ["int", v] for k, v in args.items()}, "ret": None, "returned": False}
        self.block(self.fns[fname]["body"], env, None)
        return {"state": {k: v for k, v in state.items() if v != ["var", k]}, "effects": self.effects,
                "reads": self.nread}

    def expr(self, e, env, guard):
        head = e[0]
        if head == "var":
            name = e[1]
            if name in env["l"]:
                return env["l"][name]
            if name in env["g"]:
                return env["g"][name]
            raise Unsupported(f"unknown variable {name}")
        if head in ("int", "bool", "float"):
            return e
        if head == "LOAD":
            i = self.expr(e[2], env, guard)
            if _const(i):
                cell = f"{e[1]}{_val(i)}"
                return env["g"].get(cell, ["var", cell])
            n = self._size(e[1])                      # a symbolic index: a select over the cells
            t = env["g"].get(f"{e[1]}{n - 1}", ["var", f"{e[1]}{n - 1}"])
            for k in range(n - 2, -1, -1):
                t = ["IF_EXPR", ["CMP_EQ", i, ["int", k]], env["g"].get(f"{e[1]}{k}", ["var", f"{e[1]}{k}"]), t]
            return t
        if head == "CALL":
            name, args = e[1], [self.expr(a, env, guard) for a in e[2:]]
            if name in EFFECTS:
                entry = {"op": name, "args": args, "guard": guard}
                if name in READ_SORTS:
                    v = f"rd{self.nread}"
                    self.nread += 1
                    entry["result"], entry["sort"] = v, READ_SORTS[name]
                    self.effects.append(entry)
                    return ["var", v]
                self.effects.append(entry)
                return None
            fn = self.fns.get(name)
            if fn is None or len(fn["params"]) != len(args):
                raise Unsupported(f"call of {name}")
            sub = {"g": env["g"], "l": {p["name"]: a for p, a in zip(fn["params"], args)}, "ret": None,
                   "returned": False}
            self.block(fn["body"], sub, guard)
            return sub["ret"]
        return self.fold([head, *[self.expr(a, env, guard) for a in e[1:]]])

    def block(self, stmts, env, guard, cont=()) -> None:
        """``cont``: the statement lists that follow this block in its function (inner first), so a branch that
        returns on one side only can run the rest of the function on the other side (path splitting)."""
        for n, s in enumerate(stmts):
            if env["returned"]:
                return
            k = s["k"]
            if k == "assign":
                v = self.expr(s["value"], env, guard)
                scope = "g" if s["target"] in env["g"] and s["target"] not in env["l"] else "l"
                env[scope][s["target"]] = v
            elif k == "do":
                self.expr(s["value"], env, guard)
            elif k == "return":
                env["ret"] = self.expr(s["value"], env, guard) if s.get("value") is not None else None
                env["returned"] = True
            elif k == "if":
                self.branch(s, env, guard, (stmts[n + 1:], *cont))
            elif k == "store":
                i = self.expr(s["index"], env, guard)
                v = self.expr(s["value"], env, guard)
                if _const(i):
                    env["g"][f"{s['array']}{_val(i)}"] = v
                else:
                    # an index left symbolic (the banked[] slot of the CPSR mode): a guarded write to every cell
                    for k in range(self._size(s["array"])):
                        cell = f"{s['array']}{k}"
                        old = env["g"].get(cell, ["var", cell])
                        env["g"][cell] = self.fold(["IF_EXPR", self.fold(["CMP_EQ", i, ["int", k]]), v, old])
            elif k == "for_range":
                self.for_range(s, env, guard)
            elif k == "while":
                self.while_(s, env, guard)
            else:
                raise Unsupported(f"statement {k}")

    LOOP_MAX = 64

    def _loop_body(self, body, env, guard, what):
        """One iteration of a loop body. ``break``/``continue`` and a return from inside are not modelled."""
        if any(x["k"] in ("break", "continue", "return") for x in _walk(body)):
            raise Unsupported(f"{what} with break/continue/return")
        self.block(body, env, guard)

    def for_range(self, s, env, guard) -> None:
        """Unrolled when its bounds fold to constants under the bound instruction word; a symbolic bound is
        unsupported."""
        bounds = []
        for key in ("start", "stop", "step"):
            e = s.get(key, ["int", 1] if key == "step" else ["int", 0])
            v = e if isinstance(e, int) else self.expr(e, env, guard)
            if isinstance(v, int):
                v = ["int", v]
            if not _const(v):
                raise Unsupported(f"for_range with a symbolic {key}")
            bounds.append(int(_val(v)))
        rng = range(*bounds) if bounds[2] else range(0)
        if len(rng) > self.LOOP_MAX:
            raise Unsupported(f"for_range of {len(rng)} iterations")
        scope = "g" if s["var"] in env["g"] and s["var"] not in env["l"] else "l"
        for i in rng:
            env[scope][s["var"]] = ["int", i]
            self._loop_body(s["body"], env, guard, "for_range")
        if s.get("counter"):
            env["l"][s["counter"]] = ["int", len(rng)]

    def while_(self, s, env, guard) -> None:
        """Unrolled while its condition folds to a constant (the loop counters depend on the bound word only);
        a condition that stays symbolic is unsupported."""
        for _ in range(self.LOOP_MAX + 1):
            c = self.expr(s["cond"], env, guard)
            if not _const(c):
                raise Unsupported("while with a symbolic condition")
            if not _val(c):
                return
            self._loop_body(s["body"], env, guard, "while")
        raise Unsupported(f"while of more than {self.LOOP_MAX} iterations")

    def branch(self, s, env, guard, cont=()) -> None:
        c = self.expr(s["cond"], env, guard)
        if _const(c):
            self.block(s["then"] if _val(c) else (s.get("else") or []), env, guard, cont)
            return
        g1 = c if guard is None else ["AND", guard, c]
        g2 = ["NOT", c] if guard is None else ["AND", guard, ["NOT", c]]
        mark = (len(self.effects), self.nread)
        e1 = {"g": dict(env["g"]), "l": dict(env["l"]), "ret": env["ret"], "returned": False}
        e2 = {"g": dict(env["g"]), "l": dict(env["l"]), "ret": env["ret"], "returned": False}
        self.block(s["then"], e1, g1, cont)
        self.block(s.get("else") or [], e2, g2, cont)
        if e1["returned"] != e2["returned"]:
            # a return on one side only: split the path, each side running the rest of the function to its end
            del self.effects[mark[0]:]
            self.nread = mark[1]
            e1 = {"g": dict(env["g"]), "l": dict(env["l"]), "ret": env["ret"], "returned": False}
            e2 = {"g": dict(env["g"]), "l": dict(env["l"]), "ret": env["ret"], "returned": False}
            for side, body, g in ((e1, s["then"], g1), (e2, s.get("else") or [], g2)):
                self.block(body, side, g, cont)
                for i, rest in enumerate(cont):
                    self.block(rest, side, g, cont[i + 1:])
                side["returned"] = True               # the function ends on both sides now
        for scope in ("g", "l"):
            for k in set(e1[scope]) | set(e2[scope]):
                dflt = ["var", k] if scope == "g" else ["int", 0]    # a cell first written on one side only
                a, b = e1[scope].get(k, dflt), e2[scope].get(k, dflt)
                env[scope][k] = a if a == b else self.fold(["IF_EXPR", c, a, b])
        if e1["returned"]:
            env["ret"] = e1["ret"] if e1["ret"] == e2["ret"] else self.fold(["IF_EXPR", c, e1["ret"], e2["ret"]])
            env["returned"] = True


def evaluate(result: dict, init: dict, ram: bytes, ops: dict | None = None) -> dict:
    """The terms on one concrete state: final registers, bytes written, M-cycles, halt/stop/hang effects. With
    ``ops`` (``ir.op_table``) the terms are evaluated in the model M, the op cards' semantics (FOUNDATIONS.md A2)."""
    from ..engines.exprs import evaluate as ev
    if ops is not None:
        from ..engines.logic import eval_expr

        def ev(t, env):                 # noqa: F811
            return eval_expr(t, env, ops)
    env = dict(init)
    env.update({f"rd{i}": 0 for i in range(result["reads"])})
    writes, cycles, counts = {}, 0, {"halt": 0, "stop": 0, "hang": 0}
    for e in result["effects"]:
        if e["guard"] is not None and not ev(e["guard"], env):
            continue
        if e["op"] in CYCLES:
            cycles += 1
        if e["op"] in READS:
            a = ev(e["args"][0], env) & 0xFFFF
            env[e["result"]] = writes.get(a, ram[a])
        elif e["op"] == "wr8":
            writes[ev(e["args"][0], env) & 0xFFFF] = ev(e["args"][1], env) & 0xFF
        elif e["op"] in counts:
            counts[e["op"]] += 1
    regs = {k: ev(v, env) for k, v in result["state"].items()}
    return {"regs": regs, "writes": writes, "cycles": cycles, **counts}


def _stored_canonical(ctx, name: str, res: dict) -> tuple[dict | None, str | None]:
    """The canonical state the stored definition carries, and why it can't be used (absent, or its raw terms are not
    the card's terms any more: the pack is stale)."""
    d = ctx.store.get(f"definition/isa__{name}")
    if d is None or not isinstance((d.get("canonical") or {}).get("term"), dict):
        return None, "no stored definition"
    fresh = json.loads(json.dumps({"state": res["state"], "effects": res["effects"]}))
    if (d.get("math") or {}).get("term") != fresh:
        return None, "the stored definition's terms are not the card's symbolic terms (regenerate the pack)"
    return d["canonical"]["term"]["state"], None


def check(ctx, isa: str = "lr35902", seed: int = 0, samples: int = 4, only: list[str] | None = None,
          canonical: str = "stored") -> dict:
    """Symbolic terms against the bench's run of the executable semantics, card by card. The same cases also witness
    the canonical terms, the ones a definition stores as its canonical form, identity and Gödel content (CM44):
    ``canonical="stored"`` evaluates the stored definition's canonical terms (distilling only where none is stored),
    ``"distill"`` distills afresh (kept in ``distilled`` for ``definitions``), ``None`` checks the raw terms only.
    A canonical term that disagrees with the semantics fails its card like a raw one."""
    from . import bench as BN
    from . import build as Bd
    from . import native as N
    if canonical not in ("stored", "distill", None):
        raise ValueError(f"canonical must be 'stored', 'distill' or None, not {canonical!r}")
    if I.isa_card(ctx.store, isa).get("bench_state") == "mips":
        return {**check_mips(ctx, isa, seed=seed, samples=samples, only=only), "canonical": {}, "distilled": {}}
    if I.isa_card(ctx.store, isa).get("operand_param"):
        # an ISA decoded from the instruction word (ARM/Thumb): terms per sampled encoding; no stored canonical forms
        return {**check_arm(ctx, isa, seed=seed, samples=samples, only=only), "canonical": {}, "distilled": {}}
    mod, cards = module(ctx, isa)
    ex = Executor(ctx, mod)
    m = N.load(ctx, Bd.module(ctx, f"{isa}_bench"), N.resolve_engine(ctx, "host"))
    rng = random.Random(seed)
    per, results, canon, distilled = {}, {}, {}, {}
    laws = []                                         # rules and costs, read once when something is distilled

    def _distill(res):
        if not laws:
            from ..engines import egraph as E
            from ..engines import search
            laws.extend([E.rules_from_cards(ctx.store), search.op_costs(ctx.store)])
        return distill(ctx, isa, res["state"], *laws)
    for card in cards:
        if only and card.name not in only:
            continue
        try:
            res = ex.run(card.name)
        except Unsupported as exc:
            per[card.name] = {"status": "unsupported", "reason": str(exc)}
            continue
        results[card.name] = res
        if any(e["op"] == "cb_dispatch" for e in res["effects"]):
            per[card.name] = {"status": "dispatch", "reason": "its meaning is the prefixed card the fetched byte "
                              "selects; each of those has its own terms", "registers": sorted(res["state"]),
                              "effects": len(res["effects"])}
            continue
        cstate, csource = None, None
        if canonical == "stored":
            cstate, why = _stored_canonical(ctx, card.name, res)
            csource = "stored" if cstate is not None else f"distilled ({why})"
        if canonical is not None and cstate is None:
            distilled[card.name] = _distill(res)
            cstate, csource = distilled[card.name]["state"], csource or "distilled"
        if cstate is not None:
            canon[card.name] = cstate
        cres = {**res, "state": cstate} if cstate is not None else None
        fetches = 2 if card.get("prefix") is not None else 1
        outcomes = ["taken", "not_taken"] if isinstance(card.get("cycles"), dict) else [None]
        problems, runs = [], 0
        for _ in range(samples):
            for outcome in outcomes:
                st = BN._case_state(rng, card, outcome)
                out = BN.run_case(m, card, st, rng.randbytes(0x10000))
                init = {k: st[k] for k in ex.globals}
                init["PC"] = (st["PC"] + fetches) & 0xFFFF
                got = evaluate(res, init, out["_ram_in"], ctx.ops)
                runs += 1
                for k in ex.globals:
                    want = out[k] if k in out else st[k]
                    have = got["regs"].get(k, init[k])
                    if k == "locked" and got["hang"]:
                        have = 1                      # the bench's hang() locks the CPU
                    if have != want:
                        problems.append(f"{k}: terms give {have}, the semantics {want}")
                if cres is not None:                  # the canonical terms on the same case (effects are shared)
                    cregs = evaluate(cres, init, out["_ram_in"], ctx.ops)["regs"]
                    for k in ex.globals:
                        want = out[k] if k in out else st[k]
                        have = cregs.get(k, init[k])
                        if k == "locked" and got["hang"]:
                            have = 1
                        if have != want:
                            problems.append(f"{k}: canonical terms give {have}, the semantics {want}")
                written = {a: v for a, v in got["writes"].items() if v != out["_ram_in"][a]}
                if sorted(written.items()) != out["ram_changes"]:
                    problems.append(f"memory: terms write {sorted(written.items())[:3]}, the semantics "
                                    f"{out['ram_changes'][:3]}")
                if got["cycles"] + fetches != out["ntrace"]:
                    problems.append(f"M-cycles: terms {got['cycles'] + fetches}, the semantics {out['ntrace']}")
                if got["halt"] != out["halt_calls"] or got["stop"] != out["stop_calls"]:
                    problems.append("halt/stop effects differ")
        per[card.name] = {"status": "fail" if problems else "pass", "runs": runs, "problems": sorted(set(problems))[:4],
                          "registers": sorted(res["state"]), "effects": len(res["effects"]),
                          "canonical": csource or "not checked"}
    st = [r["status"] for r in per.values()]
    return {"status": "fail" if "fail" in st else ("pass" if "pass" in st else "vacuous"), "isa": isa, "seed": seed,
            "counts": {s: st.count(s) for s in sorted(set(st))}, "cards": per, "results": results,
            "canonical": canon, "distilled": distilled}


def arm_bus(result: dict, init: dict, ram: bytes, ops) -> dict:
    """The ARM terms' bus effects on one concrete state, in order and under their guards, over a 64 KiB memory
    mirrored across the address space (the bench's): each read binds its ``rdN`` to the little-endian value at the
    address as given (unaligned addresses are not rounded: the semantics aligns and rotates), each write stores its
    low bytes. Returns the environment with the reads bound, the access trace as the bench records it
    (``(kind, address, value)``, kinds 1-3 reads of 8/16/32 bits, 4-6 writes), and the SWI / undefined /
    coprocessor hooks' record (the bench's stubs: ``cp_read`` returns the last value written, 0x1234 at first)."""
    from ..engines.logic import eval_expr
    mem = bytearray(ram)
    env = dict(init)
    env.update({f"rd{i}": 0 for i in range(result["reads"])})
    rec = {"trace": [], "swi_calls": 0, "swi_last": -1, "undef_calls": 0, "cp_last": -1, "cp_value": 0x1234}
    kinds = {"rd8": 1, "rd16": 2, "rd32": 3, "wr8": 4, "wr16": 5, "wr32": 6}
    for e in result["effects"]:
        if e["guard"] is not None and not eval_expr(e["guard"], env, ops):
            continue
        op, args = e["op"], [eval_expr(a, env, ops) for a in e["args"]]
        if op in ("rd8", "rd16", "rd32"):
            n = {"rd8": 1, "rd16": 2, "rd32": 4}[op]
            v = sum(mem[(args[0] + i) & 0xFFFF] << (8 * i) for i in range(n))
            env[e["result"]] = v
            rec["trace"].append((kinds[op], args[0] & 0xFFFFFFFF, v))
        elif op in WRITE_BYTES:
            n = WRITE_BYTES[op]
            for i in range(n):
                mem[(args[0] + i) & 0xFFFF] = (args[1] >> (8 * i)) & 0xFF
            rec["trace"].append((kinds[op], args[0] & 0xFFFFFFFF, args[1] & ((1 << (8 * n)) - 1)))
        elif op == "swi":
            rec["swi_calls"] += 1
            rec["swi_last"] = args[0]
        elif op == "undefined_op":
            rec["undef_calls"] += 1
        elif op == "cp_read":
            rec["cp_last"] = args[0]
            env[e["result"]] = rec["cp_value"]
        elif op == "cp_write":
            rec["cp_last"], rec["cp_value"] = args[0], args[1]
        else:
            raise Unsupported(f"effect {op} on the ARM bus")
    rec["trace"] = rec["trace"][:64]
    return {"env": env, **rec}


ARM_REGS = tuple(f"regs{i}" for i in range(16)) + ("cpsr", "spsr")


def check_arm(ctx, isa: str = "armv5te", seed: int = 0, samples: int = 4, only: list[str] | None = None) -> dict:
    """The ARM/Thumb cards' terms against the bench (``machine/<isa>_bench``), one encoding at a time: for each sample
    a random word the card decodes (condition AL: the condition is ``run_one``'s, not the card's), its terms with
    ``op`` bound, and the bench's run of that word on a random state. Every register (``regs0..15`` as u32, the CPSR,
    the SPSR) and the next PC must agree, and so must the bus: both run on the same random 64 KiB memory, and the
    accesses (kind, address, value, in order: reads typed by width, writes with their width) and the SWI /
    undefined / coprocessor hooks' record must be the bench's (``arm_bus``)."""
    from . import bench as BN
    from . import build as Bd
    from . import native as N
    from ..engines.logic import eval_expr
    mod, cards = module(ctx, isa)
    ex = Executor(ctx, mod)
    m = N.load(ctx, Bd.module(ctx, f"{isa}_bench"), N.resolve_engine(ctx, "host"))
    rng = random.Random(seed)
    per, results = {}, {}
    for card in cards:
        if only and card.name not in only:
            continue
        problems, runs, reason, regs = [], 0, None, set()
        for _ in range(samples):
            op = BN._word(rng, card)
            if card["set"] == "arm" and not card.get("unconditional"):
                op = (op & 0x0FFFFFFF) | (14 << 28)
            if BN.decoded_by(cards, op, card["set"]) is not card and \
                    getattr(BN.decoded_by(cards, op, card["set"]), "name", None) != card.name:
                continue                              # a word a higher-priority card takes
            try:
                res = ex.run(card.name, {mod.functions[card.name]["params"][0]["name"]: op})
            except Unsupported as exc:
                reason = str(exc)
                break
            results.setdefault(card.name, res)
            regs |= set(res["state"])
            st = BN._arm_state(rng, card)
            init = {f"regs{i}": v for i, v in enumerate(st["regs"])}
            init.update({f"banked{i}": v for i, v in enumerate(st["banked"])})
            init.update(cpsr=st["cpsr"], spsr=st["spsr"], pc=st["pc"], sh_c=m.get("sh_c"), arch=m.get("arch"),
                        next_pc=(st["pc"] + (4 if card["set"] == "arm" else 2)) & 0xFFFFFFFF)
            ram = rng.randbytes(0x10000)
            out = BN.run_arm_case(m, st, op, ram)
            got_bus = arm_bus(res, init, ram, ctx.ops)
            if out["ntrace"] > 64:
                reason = "the bench's trace overflowed"
                break
            runs += 1
            env = got_bus["env"]
            got = {k: eval_expr(t, env, ctx.ops) for k, t in res["state"].items()}
            if got_bus["trace"] != out["trace"]:
                problems.append(f"{op:#010x} bus: terms {got_bus['trace'][:3]}, the semantics {out['trace'][:3]}")
            for k in ("swi_calls", "swi_last", "undef_calls", "cp_last", "cp_value"):
                if got_bus[k] != out[k]:
                    problems.append(f"{op:#010x} {k}: terms give {got_bus[k]}, the semantics {out[k]}")
            want = {**{f"regs{i}": v for i, v in enumerate(out["regs"])}, "cpsr": out["cpsr"], "spsr": out["spsr"],
                    "next_pc": out["pc"]}
            for k, w in want.items():
                h = got.get(k, init[k])
                if h != w:
                    problems.append(f"{op:#010x} {k}: terms give {h:#x}, the semantics {w:#x}")
        if reason is not None:
            per[card.name] = {"status": "unsupported", "reason": reason}
        elif not runs:
            per[card.name] = {"status": "unsupported", "reason": "no sampled word decodes to this card"}
        else:
            per[card.name] = {"status": "fail" if problems else "pass", "runs": runs,
                              "problems": sorted(set(problems))[:4], "registers": sorted(regs)}
    st = [r["status"] for r in per.values()]
    return {"status": "fail" if "fail" in st else ("pass" if "pass" in st else "vacuous"), "isa": isa, "seed": seed,
            "counts": {s: st.count(s) for s in sorted(set(st))}, "cards": per, "results": results}


def mips_bus(result: dict, init: dict, ram: bytes, ops) -> dict:
    """The MIPS terms' bus effects on one concrete state, as ``arm_bus`` does for ARM, with the MIPS bench's hooks:
    SYSCALL and BREAK codes, exceptions (code, info) and reserved instructions."""
    from ..engines.logic import eval_expr
    mem = bytearray(ram)
    env = dict(init)
    env.update({f"rd{i}": 0 for i in range(result["reads"])})
    rec = {"trace": [], "sys_calls": 0, "sys_last": -1, "brk_calls": 0, "exc_calls": 0, "exc_last": -1,
           "exc_info": 0, "undef_calls": 0}
    kinds = {"rd8": 1, "rd16": 2, "rd32": 3, "wr8": 4, "wr16": 5, "wr32": 6}
    for e in result["effects"]:
        if e["guard"] is not None and not eval_expr(e["guard"], env, ops):
            continue
        op, args = e["op"], [eval_expr(a, env, ops) for a in e["args"]]
        if op in ("rd8", "rd16", "rd32"):
            n = {"rd8": 1, "rd16": 2, "rd32": 4}[op]
            v = sum(mem[(args[0] + i) & 0xFFFF] << (8 * i) for i in range(n))
            env[e["result"]] = v
            rec["trace"].append((kinds[op], args[0] & 0xFFFFFFFF, v))
        elif op in WRITE_BYTES:
            n = WRITE_BYTES[op]
            for i in range(n):
                mem[(args[0] + i) & 0xFFFF] = (args[1] >> (8 * i)) & 0xFF
            rec["trace"].append((kinds[op], args[0] & 0xFFFFFFFF, args[1] & ((1 << (8 * n)) - 1)))
        elif op == "syscall_op":
            rec["sys_calls"] += 1
            rec["sys_last"] = args[0]
        elif op == "break_op":
            rec["brk_calls"] += 1
        elif op == "exception":
            rec["exc_calls"] += 1
            rec["exc_last"], rec["exc_info"] = args[0], args[1]
        elif op == "undefined_op":
            rec["undef_calls"] += 1
        else:
            raise Unsupported(f"effect {op} on the MIPS bus")
    rec["trace"] = rec["trace"][:64]
    return {"env": env, **rec}


def check_mips(ctx, isa: str = "mips32", seed: int = 0, samples: int = 4, only: list[str] | None = None) -> dict:
    """The MIPS cards' terms against the bench (``machine/<isa>_bench``), one encoding at a time, as ``check_arm``:
    every register, HI, LO and the LL bit, the branch the card takes (``bpending`` / ``btarget`` against the bench's
    delay slot) or the next PC, the bus in order, and the SYSCALL / BREAK / exception / reserved-instruction hooks."""
    from . import bench as BN
    from . import build as Bd
    from . import native as N
    from ..engines.logic import eval_expr
    mod, cards = module(ctx, isa)
    ex = Executor(ctx, mod)
    m = N.load(ctx, Bd.module(ctx, f"{isa}_bench"), N.resolve_engine(ctx, "host"))
    rng = random.Random(seed)
    per, results = {}, {}
    for card in cards:
        if only and card.name not in only:
            continue
        problems, runs, reason, regs = [], 0, None, set()
        for _ in range(samples):
            op = BN._word(rng, card)
            d = BN.decoded_by(cards, op, card["set"])
            if d is None or d.name != card.name:
                continue
            try:
                res = ex.run(card.name, {mod.functions[card.name]["params"][0]["name"]: op})
            except Unsupported as exc:
                reason = str(exc)
                break
            results.setdefault(card.name, res)
            regs |= set(res["state"])
            st = BN._mips_state(rng, card)
            init = {f"regs{i}": v for i, v in enumerate(st["regs"])}
            init.update(hi=st["hi"], lo=st["lo"], pc=st["pc"], variant=st["variant"], llbit=st["llbit"],
                        next_pc=(st["pc"] + 4) & 0xFFFFFFFF, bpending=0, btarget=0, in_slot=0, slot_target=0)
            ram = rng.randbytes(0x10000)
            out = BN.run_mips_case(m, st, op, ram)
            if out["ntrace"] > 64:
                reason = "the bench's trace overflowed"
                break
            got_bus = mips_bus(res, init, ram, ctx.ops)
            runs += 1
            env = got_bus["env"]
            got = {k: eval_expr(t, env, ctx.ops) for k, t in res["state"].items()}
            if got_bus["trace"] != out["trace"]:
                problems.append(f"{op:#010x} bus: terms {got_bus['trace'][:3]}, the semantics {out['trace'][:3]}")
            for k in ("sys_calls", "sys_last", "brk_calls", "exc_calls", "exc_last", "exc_info", "undef_calls"):
                if got_bus[k] != out[k]:
                    problems.append(f"{op:#010x} {k}: terms give {got_bus[k]}, the semantics {out[k]}")
            want = {**{f"regs{i}": v for i, v in enumerate(out["regs"])}, "hi": out["hi"], "lo": out["lo"],
                    "llbit": out["llbit"]}
            if got.get("bpending", 0):
                want.update(btarget=out["slot_target"])
                if not out["in_slot"]:
                    problems.append(f"{op:#010x}: the terms branch, the semantics do not")
            else:
                if out["in_slot"]:
                    problems.append(f"{op:#010x}: the semantics branch, the terms do not")
                want["next_pc"] = out["pc"]
            for k, w in want.items():
                h = got.get(k, init.get(k))
                if h != w:
                    problems.append(f"{op:#010x} {k}: terms give {h!r}, the semantics {w:#x}")
        if reason is not None:
            per[card.name] = {"status": "unsupported", "reason": reason}
        elif not runs:
            per[card.name] = {"status": "unsupported", "reason": "no sampled word decodes to this card"}
        else:
            per[card.name] = {"status": "fail" if problems else "pass", "runs": runs,
                              "problems": sorted(set(problems))[:4], "registers": sorted(regs)}
    st = [r["status"] for r in per.values()]
    return {"status": "fail" if "fail" in st else ("pass" if "pass" in st else "vacuous"), "isa": isa, "seed": seed,
            "counts": {s: st.count(s) for s in sorted(set(st))}, "cards": per, "results": results}


def content(res: dict, ops) -> dict:
    """The atoms of an instruction's terms and bus effects, with multiplicity (its Gödel content)."""
    from collections import Counter

    from ..engines import godel as G
    c = Counter()
    for t in res["state"].values():
        c += G.term_content(t, ops)
    for e in res["effects"]:
        c[f"effect/{e['op']}"] += 1
        for a in e["args"]:
            c += G.term_content(a, ops)
    return dict(+c)


def register_sorts(ctx, isa: str) -> dict:
    """Each register's sort from the ISA card's widths (``u8``, ``u16``): the laws of those subsorts apply to it."""
    from ..engines import sorts as S
    regs = I.isa_card(ctx.store, isa).get("registers") or {}
    return {r: f"u{w}" for r, w in regs.items() if f"u{w}" in S.SORTS}


def _reads(t, out: set) -> set:
    if isinstance(t, list) and t[:1] == ["var"] and isinstance(t[1], str) and t[1].startswith("rd"):
        out.add(t[1])
    elif isinstance(t, list):
        for x in t:
            _reads(x, out)
    return out


def distill(ctx, isa: str, state: dict, rules=None, costs=None) -> dict:
    """Each register's term canonicalized by the e-graph under the sorted laws, with the registers at their widths
    and every byte read from the bus a u8 (docs/FOUNDATIONS.md D1, D7): ``(A + B + 0) & 255`` becomes
    ``(A + B) & 255``, and a mask of a byte register vanishes."""
    from ..engines import egraph as E
    from ..engines import search
    rules = E.rules_from_cards(ctx.store) if rules is None else rules
    costs = search.op_costs(ctx.store) if costs is None else costs
    sorts = register_sorts(ctx, isa)
    out, fired, saturated = {}, Counter(), True
    for reg, t in sorted(state.items()):
        r = E.canonical(t, rules, costs, {**sorts, **{x: "u8" for x in _reads(t, set())}}, ctx.ops, max_iter=5,
                        max_nodes=1500)
        out[reg] = r["term"] if r["term"] is not None else t
        fired.update(r["fired"])
        saturated = saturated and r["saturated"]
    # the whole fired set, sorted: under the budget cut, a top-k by count depends on set order (not reproducible)
    return {"state": out, "fired": dict(sorted(fired.items())), "saturated": saturated}


def definitions(ctx, isa: str, checked: dict) -> tuple[list[dict], list[dict]]:
    """Definition and action cards for every instruction with terms: the terms are the truth, the card's executable
    semantics is the action, linked by the check's witness."""
    from ..engines import godel as G
    from ..engines.egraph import semantic_hash
    from ..engines import egraph as E
    from ..engines import search
    entries = G.ledger(ctx.store)
    rules, costs = E.rules_from_cards(ctx.store), search.op_costs(ctx.store)
    cards = {c.name: c for c in I.instructions(ctx.store, isa)}
    defs, acts = [], []
    for name, res in sorted(checked["results"].items()):
        row = checked["cards"].get(name) or {}
        card = cards[name]
        dname, aname = f"isa__{name}", f"isa__{name}__semantics"
        status = {"pass": "witnessed", "fail": "refuted"}.get(row.get("status"), row.get("status", "pending"))
        term = {"state": res["state"], "effects": res["effects"]}
        d = (checked.get("distilled") or {}).get(name) or distill(ctx, isa, res["state"], rules, costs)
        if status == "witnessed" and (checked.get("canonical") or {}).get(name) != d["state"]:
            # the witness ran on other canonical terms (or none): the stored terms' obligation is still open (CM44)
            status = "pending"
        canon = {"state": d["state"], "effects": res["effects"]}
        cont = content({"state": d["state"], "effects": res["effects"]}, ctx.ops)
        defs.append({"name": dname, "category": "definition", "subject": card.qualified,
                     "math": {"text": f"{card.get('mnemonic')}: {', '.join(sorted(res['state'])) or 'no register'} "
                                      f"changed, {len(res['effects'])} bus effects",
                              "type": "State -> State", "term": term},
                     "explanation": f"{card.get('mnemonic')} as mathematics: each register it changes as a term over "
                                    f"the registers and bytes it reads, and its bus activity in order with the "
                                    f"conditions under which it happens.",
                     "canonical": {"status": "canonical", "term": canon, "hash": semantic_hash(canon),
                                   "by": "method/saturate",
                                   "certificate": {"equalities": list(d["fired"]), "saturated": d["saturated"],
                                                   "sorts": register_sorts(ctx, isa)}},
                     "identity": {"hash": semantic_hash(canon), "of": "canonical terms", "under": "laws"},
                     "godel": G.stored(Counter(cont), "its canonical terms", entries),
                     "proof_obligations": [{"claim": "the terms equal the executable semantics", "status": status,
                                            "tier": "sample",
                                            "evidence": {"seed": checked["seed"], "runs": row.get("runs"),
                                                         "reason": row.get("reason")}}],
                     "actions": [f"action/{aname}"], "transformations": [],
                     "origin": {"kind": "symbolic", "from": card.qualified},
                     "methods": ["method/symbolic_execution", "method/witness"]})
        acts.append({"name": aname, "category": "action", "truth": f"definition/{dname}", "lang": "cardlang",
                     "code": f"{card.qualified}#semantics", "method": "method/human_written",
                     "link": {"kind": "witness" if status != "dispatch" else "source",
                              "status": status if status != "dispatch" else "source", "seed": checked["seed"],
                              "tier": "sample",
                              "checks": row.get("runs")}})
    return defs, acts


__all__ = ["Executor", "Unsupported", "check", "check_arm", "content", "definitions", "distill", "evaluate", "module", "arm_bus",
           "register_sorts"]
