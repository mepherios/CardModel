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

import random
from collections import Counter

from ..lang.compile import compile_sources
from . import isa as I

EFFECTS = ("rd8", "wr8", "idle", "idu", "rd8_idu", "halt", "stop", "hang", "cb_dispatch")
READS = ("rd8", "rd8_idu")
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


class Executor:
    def __init__(self, ctx, mod):
        self.ops = ctx.ops
        self.fns = mod.functions
        self.globals = [g["name"] for g in mod.globals if g["name"] != "bus_effect"]

    def fold(self, t):
        head, args = t[0], t[1:]
        if head == "IF_EXPR" and _const(args[0]):
            return args[1] if _val(args[0]) else args[2]
        if head in ("AND", "OR") and all(_const(a) for a in args):
            v = (_val(args[0]) and _val(args[1])) if head == "AND" else (_val(args[0]) or _val(args[1]))
            return ["bool", bool(v)]
        if head in self.ops and head not in ("IF_EXPR", "AND", "OR") and args and all(_const(a) for a in args):
            try:
                v = self.ops[head].fn(*[_val(a) for a in args])
            except Exception:  # noqa: BLE001 -- not foldable (division by zero, ...): keep the term
                return t
            return ["bool", v] if isinstance(v, bool) else (["int", v] if isinstance(v, int) else t)
        return t

    def run(self, fname: str) -> dict:
        self.effects, self.nread = [], 0
        state = {g: ["var", g] for g in self.globals}
        env = {"g": state, "l": {}, "ret": None, "returned": False}
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
        if head == "CALL":
            name, args = e[1], [self.expr(a, env, guard) for a in e[2:]]
            if name in EFFECTS:
                entry = {"op": name, "args": args, "guard": guard}
                if name in READS:
                    v = f"rd{self.nread}"
                    self.nread += 1
                    entry["result"] = v
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

    def block(self, stmts, env, guard) -> None:
        for s in stmts:
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
                self.branch(s, env, guard)
            else:
                raise Unsupported(f"statement {k}")

    def branch(self, s, env, guard) -> None:
        c = self.expr(s["cond"], env, guard)
        if _const(c):
            self.block(s["then"] if _val(c) else (s.get("else") or []), env, guard)
            return
        g1 = c if guard is None else ["AND", guard, c]
        g2 = ["NOT", c] if guard is None else ["AND", guard, ["NOT", c]]
        e1 = {"g": dict(env["g"]), "l": dict(env["l"]), "ret": env["ret"], "returned": False}
        e2 = {"g": dict(env["g"]), "l": dict(env["l"]), "ret": env["ret"], "returned": False}
        self.block(s["then"], e1, g1)
        self.block(s.get("else") or [], e2, g2)
        if e1["returned"] != e2["returned"]:
            raise Unsupported("a return on one side of a branch only")
        for scope in ("g", "l"):
            for k in set(e1[scope]) | set(e2[scope]):
                a, b = e1[scope].get(k, ["int", 0]), e2[scope].get(k, ["int", 0])
                env[scope][k] = a if a == b else self.fold(["IF_EXPR", c, a, b])
        if e1["returned"]:
            env["ret"] = e1["ret"] if e1["ret"] == e2["ret"] else self.fold(["IF_EXPR", c, e1["ret"], e2["ret"]])
            env["returned"] = True


def evaluate(result: dict, init: dict, ram: bytes) -> dict:
    """The terms on one concrete state: final registers, bytes written, M-cycles, halt/stop/hang effects."""
    from ..engines.exprs import evaluate as ev
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


def check(ctx, isa: str = "lr35902", seed: int = 0, samples: int = 4, only: list[str] | None = None) -> dict:
    """Symbolic terms against the bench's run of the executable semantics, card by card."""
    from . import bench as BN
    from . import build as Bd
    from . import native as N
    mod, cards = module(ctx, isa)
    ex = Executor(ctx, mod)
    m = N.load(ctx, Bd.module(ctx, f"{isa}_bench"), N.resolve_engine(ctx, "host"))
    rng = random.Random(seed)
    per, results = {}, {}
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
        fetches = 2 if card.get("prefix") is not None else 1
        outcomes = ["taken", "not_taken"] if isinstance(card.get("cycles"), dict) else [None]
        problems, runs = [], 0
        for _ in range(samples):
            for outcome in outcomes:
                st = BN._case_state(rng, card, outcome)
                out = BN.run_case(m, card, st, rng.randbytes(0x10000))
                init = {k: st[k] for k in ex.globals}
                init["PC"] = (st["PC"] + fetches) & 0xFFFF
                got = evaluate(res, init, out["_ram_in"])
                runs += 1
                for k in ex.globals:
                    want = out[k] if k in out else st[k]
                    have = got["regs"].get(k, init[k])
                    if k == "locked" and got["hang"]:
                        have = 1                      # the bench's hang() locks the CPU
                    if have != want:
                        problems.append(f"{k}: terms give {have}, the semantics {want}")
                written = {a: v for a, v in got["writes"].items() if v != out["_ram_in"][a]}
                if sorted(written.items()) != out["ram_changes"]:
                    problems.append(f"memory: terms write {sorted(written.items())[:3]}, the semantics "
                                    f"{out['ram_changes'][:3]}")
                if got["cycles"] + fetches != out["ntrace"]:
                    problems.append(f"M-cycles: terms {got['cycles'] + fetches}, the semantics {out['ntrace']}")
                if got["halt"] != out["halt_calls"] or got["stop"] != out["stop_calls"]:
                    problems.append("halt/stop effects differ")
        per[card.name] = {"status": "fail" if problems else "pass", "runs": runs, "problems": sorted(set(problems))[:4],
                          "registers": sorted(res["state"]), "effects": len(res["effects"])}
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


def definitions(ctx, isa: str, checked: dict) -> tuple[list[dict], list[dict]]:
    """Definition and action cards for every instruction with terms: the terms are the truth, the card's executable
    semantics is the action, linked by the check's witness."""
    from ..engines import godel as G
    from ..engines.egraph import semantic_hash
    entries = G.ledger(ctx.store)
    cards = {c.name: c for c in I.instructions(ctx.store, isa)}
    defs, acts = [], []
    for name, res in sorted(checked["results"].items()):
        row = checked["cards"].get(name) or {}
        card = cards[name]
        dname, aname = f"isa__{name}", f"isa__{name}__semantics"
        cont = content(res, ctx.ops)
        status = {"pass": "witnessed", "fail": "refuted"}.get(row.get("status"), row.get("status", "pending"))
        term = {"state": res["state"], "effects": res["effects"]}
        defs.append({"name": dname, "category": "definition", "subject": card.qualified,
                     "math": {"text": f"{card.get('mnemonic')}: {', '.join(sorted(res['state'])) or 'no register'} "
                                      f"changed, {len(res['effects'])} bus effects",
                              "type": "State -> State", "term": term},
                     "explanation": f"{card.get('mnemonic')} as mathematics: each register it changes as a term over "
                                    f"the registers and bytes it reads, and its bus activity in order with the "
                                    f"conditions under which it happens.",
                     "canonical": {"status": "symbolic", "hash": semantic_hash(term), "by": "method/symbolic_execution",
                                   "note": "exact terms; the e-graph's canonical form is a later step"},
                     "identity": {"hash": semantic_hash(term), "of": "symbolic terms", "under": "syntax"},
                     "godel": G.stored(Counter(cont), "its symbolic terms", entries),
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


__all__ = ["Executor", "Unsupported", "check", "content", "definitions", "evaluate", "module"]
