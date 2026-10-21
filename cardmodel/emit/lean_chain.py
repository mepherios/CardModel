"""lean_chain — prove an equation by a chain of the model's own rewrite-rule cards; Lean checks every step.

``rewrite --prove`` already finds a chain ``lhs = e1 = ... = rhs`` (meet-in-the-middle search over the
rule cards). Here each step becomes a kernel-checked term: the rule's own theorem (``cm_<rule>``, proved
by grind/omega from the rule card), instantiated at the matched subterm and lifted into its context with
``congrArg (fun (cm_hole : Int) => C[cm_hole])`` (``.symm`` when the rule ran right-to-left):

    theorem cm_chain_0 (a b c : Int) : a + (b + c) = b + (a + c) := by
      calc a + (b + c) = (a + b) + c := (cm_associative_add a b c).symm
      _ = (b + a) + c := congrArg (fun (cm_hole : Int) => cm_hole + c) (cm_commutative_add a b)
      _ = b + (a + c) := cm_associative_add b a c

So the card model re-derives the statement from its own rules, and the kernel accepts the derivation.

Honest limits (L1): integer equations over the operators the rule theorems cover (+ - * ^ // % and
unary -); rules with side conditions are not used; the search is bounded (depth, nodes), so "no chain"
is not a disproof.
"""
from __future__ import annotations

from ..engines import search as S
from . import lean as LE

CHAIN_OPS = {"ADD", "SUB", "MUL", "NEG", "POW", "var", "int"}


def _positions(e, path=()):
    yield path, e
    if isinstance(e, list) and e and e[0] not in ("var", "int", "float", "bool", "const"):
        for i in range(1, len(e)):
            yield from _positions(e[i], path + (i,))


def _replace(e, path, new):
    if not path:
        return new
    copy = list(e)
    copy[path[0]] = _replace(e[path[0]], path[1:], new)
    return copy


def justify(e1, e2, rules):
    """(rule, path, binding, backward) such that rewriting e1 at path with the rule (or its reverse) gives e2."""
    for path, sub in _positions(e1):
        for backward in (False, True):
            for r in rules:
                pat, rep = (r.rhs, r.lhs) if backward else (r.lhs, r.rhs)
                b = S.match(pat, sub, {})
                if b is None:
                    continue
                out = S.instantiate(rep, b)
                if S._unbound(out):
                    continue
                if _replace(e1, path, out) == e2:
                    return r, path, b, backward
    return None


def _ctx_fun(e, path) -> str:
    hole = ["var", "cm_hole"]
    return f"(fun (cm_hole : Int) => {LE.to_lean(_replace(e, path, hole))})"


def step_term(e1, rule, path, binding, backward, rule_cards) -> str:
    base = rule.card
    card = rule_cards[base]
    args = []
    for v in card.get("vars") or []:
        t = binding.get(f"?{v}")
        if t is None:
            raise LE.NotExpressible(f"rule {base}: variable {v} unbound")
        args.append(LE.to_lean(t))
    inst = f"(cm_{base} {' '.join(args)})" if args else f"cm_{base}"
    if rule.name.endswith("~rev") != backward:
        inst = f"({inst}).symm"
    if not path:
        return inst
    return f"congrArg {_ctx_fun(e1, path)} {inst}"


def chain_source(name: str, vars_: list[str], steps: list, rules, rule_cards) -> str:
    exprs = [steps[0][1]] + [e for _, e in steps[1:]]
    binders = f" ({' '.join(vars_)} : Int)" if vars_ else ""
    lhs, rhs = LE.to_lean(exprs[0]), LE.to_lean(exprs[-1])
    if len(exprs) == 1:
        return f"theorem {name}{binders} : {lhs} = {rhs} := rfl"
    lines = [f"theorem {name}{binders} : {lhs} = {rhs} := by"]
    for k in range(len(exprs) - 1):
        j = justify(exprs[k], exprs[k + 1], rules)
        if j is None:
            raise LE.NotExpressible(f"step {k} has no single-rule justification")
        term = step_term(exprs[k], *j, rule_cards)
        head = f"  calc {LE.to_lean(exprs[k])}" if k == 0 else "  _"
        lines.append(f"{head} = {LE.to_lean(exprs[k + 1])} := {term}")
    return "\n".join(lines)


def _plain(t):
    """Drop Lean numeral type tags (["int", 2, "int"] -> ["int", 2]) so rule patterns match."""
    if isinstance(t, list):
        if t and t[0] == "int" and len(t) > 2:
            return ["int", t[1]]
        return [_plain(x) for x in t]
    return t


def eligible(card) -> bool:
    """Integer equations without hypotheses over the operators the rule theorems cover."""
    c = card.get("concl") or []
    if c[:1] != ["eq"] or card.get("hyps") or any(v["type"] != "int" for v in card.get("vars") or []):
        return False
    return all(_ops_ok(t) for t in c[1:]) and c[1] != c[2]


def _ops_ok(t) -> bool:
    if isinstance(t, list) and t:
        if t[0] not in CHAIN_OPS:
            return False
        return all(_ops_ok(a) for a in t[1:] if isinstance(a, list))
    return True


def certify(ctx, cards: list[dict], max_depth: int = 6, max_nodes: int = 30000) -> dict:
    """Find and kernel-check rule chains for each eligible card. {card name: {status, rules, steps}}."""
    rules_report = LE.check_rules(ctx)
    proved = {q.split("/", 1)[1]: r for q, r in rules_report.get("rules", {}).items() if r["status"] == "proved"}
    rule_cards = {c.name: c for c in ctx.store.cards("rewrite_rule")
                  if c.name in proved and not c.get("condition")}
    rules = [r for r in S.load_rules(ctx.store) if r.card in rule_cards]
    out: dict[str, dict] = {}
    blocks = []
    for k, card in enumerate(cards):
        if not eligible(card):
            out[card["name"]] = {"status": "not_eligible"}
            continue
        lhs, rhs = _plain(card["concl"][1]), _plain(card["concl"][2])
        found = S.prove(lhs, rhs, rules, max_depth=max_depth, max_nodes=max_nodes)
        if found is None:
            out[card["name"]] = {"status": "no_chain", "depth": max_depth}
            continue
        try:
            src = chain_source(f"cm_chain_{k}", [v["name"] for v in card["vars"]], found["steps"], rules, rule_cards)
        except LE.NotExpressible as exc:
            out[card["name"]] = {"status": "not_expressible", "detail": str(exc)}
            continue
        used = sorted({r.split("~")[0] for r, _ in found["steps"][1:]})
        out[card["name"]] = {"status": "found", "rules": used,
                             "steps": len(found["steps"]) - 1, "source": src}
        blocks.append((card["name"], src))
    exe = LE.lean_exe()
    if not blocks:
        return {"toolchain": exe, "results": out}
    if exe is None:
        for n, _ in blocks:
            out[n]["status"] = "no_toolchain"
        return {"toolchain": None, "results": out}
    header = [proved[n]["statement"] for n in sorted(rule_cards)]
    verdict = LE.check_batch(exe, blocks, header=header)
    for n, _ in blocks:
        v = verdict.get(n, "unchecked")
        out[n]["status"] = "checked" if v == "ok" else ("unchecked" if v.startswith("unchecked") else "rejected")
        if v != "ok":
            out[n]["detail"] = v
    return {"toolchain": exe, "results": out}


__all__ = ["certify", "chain_source", "eligible", "justify"]
