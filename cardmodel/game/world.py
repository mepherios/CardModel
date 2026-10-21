"""world — tick-by-tick systemic simulation on logic cards, with causes you can ask for.

The state at tick T is a set of facts. stdlib/world.card derives ``next_*`` facts (the state at T + 1) from
the state, the static map and the actions scheduled at T. Each tick is one stratified evaluation, so rules
may use negation freely within a tick (feedback such as "an alarm sends guards toward the fire" runs across
ticks). Every fact keeps its derivation; ``explain`` follows the derivations back through earlier ticks to
the actions that caused an outcome, and ``impact`` removes each action in turn and measures how much of the
final world changes: the specific action-vector that modified the total structure.

Honest limits (L1): discrete ticks; a fact's first derivation per tick is its recorded cause (other causes
may also exist); impact counts differing facts, it does not weigh them.
"""
from __future__ import annotations

from ..engines import logic as L
from ..kernel import paths

SCENARIO = {
    "state": [("burning_none",), ("guard", "warden_ann", "tavern"), ("guard", "warden_bo", "tower"),
              ("standing", "watch", 50), ("standing", "village", 50), ("wind", "barn", "granary")],
    "actions": {1: [("ignite", "cart")], 4: [("douse", "granary")]},
    "ticks": 10,
}


def load_rules(ctx):
    from ..lang.compile import compile_file
    return compile_file(paths.home() / "stdlib" / "world.card", ctx.ops, ctx.store)


def run(ctx, scenario: dict | None = None, without: tuple | None = None) -> dict:
    sc = scenario or SCENARIO
    mod = load_rules(ctx)
    static = list(mod.program.facts)
    state = [tuple(f) for f in sc["state"] if f[0] != "burning_none"]
    history = []
    for t in range(sc["ticks"]):
        prog = L.Program(rules=list(mod.program.rules), facts=list(static), name="world")
        for f in state:
            prog.add_fact(f[0], list(f[1:]), f"state@{t}")
        acts = [a for a in sc["actions"].get(t, []) if (t, a) != without]
        for verb, target in acts:
            prog.add_fact("act", [verb, target], f"action@{t}")
        model = L.evaluate(prog, ctx.ops)
        nxt = []
        for pred, rows in model.db.rel.items():
            if pred.startswith("next_"):
                nxt += [(pred[5:], *r) for r in rows]
        events = sorted((p, *r) for p, rows in model.db.rel.items() if p.startswith("event_") for r in rows)
        history.append({"tick": t, "actions": acts, "state": sorted(state, key=str), "events": events,
                        "model": model})
        state = sorted(set(nxt), key=str)
    return {"history": history, "final": state, "ticks": sc["ticks"]}


def explain(result: dict, fact: tuple, tick: int, depth: int = 0, max_depth: int = 30) -> list[str]:
    """Why does ``fact`` hold at ``tick``? Follow derivations back through the ticks to the actions."""
    pad = "  " * depth
    if tick <= 0 or depth > max_depth:
        return [f"{pad}{_fmt(fact)} @ tick {tick}: initial state"]
    prev = result["history"][tick - 1]
    model = prev["model"]
    key = ("next_" + fact[0], tuple(fact[1:]))
    if key not in model.why:
        return [f"{pad}{_fmt(fact)} @ tick {tick}: not derived"]
    proof = model.proof(key[0], list(key[1]))
    lines = [f"{pad}{_fmt(fact)} @ tick {tick}  [{proof.get('by')}: {proof.get('rule', '')}]"]
    for prem in proof.get("premises", []):
        if "fact" in prem:
            src = model.why.get((prem["pred"], tuple(prem["args"])), ("given", ""))
            if src[0] == "given" and str(src[1]).startswith("state@"):
                lines += explain(result, (prem["pred"], *prem["args"]), tick - 1, depth + 1, max_depth)
            elif src[0] == "given" and str(src[1]).startswith("action@"):
                lines.append(f"{pad}  {prem['fact']}  <- the player's action at tick {tick - 1}")
            elif src[0] == "given":
                lines.append(f"{pad}  {prem['fact']}  (the map)")
            else:
                lines.append(f"{pad}  {prem['fact']}  (derived at tick {tick - 1})")
                sub = model.proof(prem["pred"], prem["args"])
                for k in sub.get("premises", []):
                    if "fact" in k:
                        s2 = model.why.get((k["pred"], tuple(k["args"])), ("given", ""))
                        if s2[0] == "given" and str(s2[1]).startswith("state@"):
                            lines += explain(result, (k["pred"], *k["args"]), tick - 1, depth + 2, max_depth)
                        elif s2[0] == "given" and str(s2[1]).startswith("action@"):
                            lines.append(f"{pad}    {k['fact']}  <- the player's action at tick {tick - 1}")
        elif "absent" in prem:
            lines.append(f"{pad}  not {prem['absent']}")
        elif "bind" in prem or "test" in prem:
            lines.append(f"{pad}  {prem.get('bind') or prem.get('test')}")
    return lines


def impact(ctx, scenario: dict | None = None) -> list[dict]:
    """Remove each action in turn; how much of the final world changes?"""
    sc = scenario or SCENARIO
    base = set(run(ctx, sc)["final"])
    out = []
    for t, acts in sorted(sc["actions"].items()):
        for a in acts:
            alt = set(run(ctx, sc, without=(t, a))["final"])
            diff = sorted(base ^ alt, key=str)
            out.append({"action": f"{a[0]} {a[1]} @ tick {t}", "changed": len(diff),
                        "only_with_it": [_fmt(f) for f in sorted(base - alt, key=str)][:12],
                        "only_without_it": [_fmt(f) for f in sorted(alt - base, key=str)][:12]})
    return sorted(out, key=lambda r: -r["changed"])


def _fmt(f) -> str:
    return f"{f[0]}({', '.join(str(x) for x in f[1:])})" if len(f) > 1 else f[0]


__all__ = ["SCENARIO", "explain", "impact", "run"]
