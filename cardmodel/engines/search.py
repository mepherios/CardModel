"""search — rewrite search over op trees: proof chains and cost-directed optimisation.

Ported from the hub's rewrite_search.py (BFS, ?var pattern unification,
rewriting at every position) with three changes:
  * rules are cards (cards/rewrite_rule/*), loaded at run time (Pheros L33):
    adding a rule never edits this file;
  * ``prove`` searches from both sides and meets in the middle (rules are
    equalities, so either direction is sound), with a node budget (L20);
  * ``optimize`` uses the same moves to find the cheapest equivalent
    expression, where cost = sum of op-card costs.

Honest limits (L1): bounded breadth-first search, so a proof that needs
more steps than ``max_depth`` (or more nodes than ``max_nodes``) is
reported as not found -- that is not a disproof. Side conditions on rules
(e.g. ``k >= 0``) are checked by the numeric witness, not during search.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from . import godel
from . import sorts as S
from .exprs import parse, size, to_text


@dataclass
class Rule:
    name: str
    lhs: object
    rhs: object
    card: str
    condition: str | None = None
    domain: str | None = None           # the sort the law's variables range over (FOUNDATIONS.md rule A3)


def load_rules(store, names: list[str] | None = None) -> list[Rule]:
    """The rule cards as patterns. A call of a function that is an op card (``gcd(a, b)``) is that op, so the rule
    matches the IR's terms (FOUNDATIONS.md rule A1)."""
    from .ir import op_table
    from .exprs import resolve_ops
    ops = op_table(store)
    out = []
    for card in store.cards("rewrite_rule"):
        if names and card.name not in names:
            continue
        pv = card.get("vars") or []
        try:
            lhs, rhs = resolve_ops(parse(card["lhs"], pv), ops), resolve_ops(parse(card["rhs"], pv), ops)
        except Exception as exc:  # noqa: BLE001 -- a malformed rule card is reported, not fatal
            raise ValueError(f"rewrite_rule/{card.name}: {exc}") from exc
        out.append(Rule(card.name, lhs, rhs, card.name, card.get("condition"), card.get("domain")))
        if card.get("bidirectional"):
            out.append(Rule(card.name + "~rev", rhs, lhs, card.name, card.get("condition"), card.get("domain")))
    return out


def core_pattern(pattern):
    """A ``?x`` pattern in godel's form: each ``"?x"`` becomes ``["var", "?x"]``, so matching and substitution are
    ``godel.match`` / ``godel.substitute`` (GODEL_PURITY rule 1: one core). A leaf node and the name slot of a
    CALL/LOAD are left as they are, since the core does not descend into them."""
    if isinstance(pattern, str) and pattern.startswith("?"):
        return ["var", pattern]
    if isinstance(pattern, list) and pattern:
        if isinstance(pattern[0], str) and pattern[0] in godel.LEAVES:
            return pattern
        start = 2 if isinstance(pattern[0], str) and pattern[0] in godel.SPECIAL else 1
        return [*pattern[:start], *(core_pattern(x) for x in pattern[start:])]
    return pattern


def _literal_vars(pattern) -> set:
    """The names of the term variables (``["var", "x"]``) a ``?x`` pattern contains: constants of the pattern, which
    the core would read as pattern variables."""
    if isinstance(pattern, list) and pattern:
        if pattern[0] == "var":
            return {pattern[1]}
        return set().union(*(_literal_vars(x) for x in pattern[1:]))
    return set()


def match(pattern, expr, b: dict | None = None, core=None) -> dict | None:
    """``godel.match`` over a ``?x`` pattern (``core`` = its ``core_pattern``, when already converted). A term
    variable written in the pattern is a constant here: it must bind itself, and its binding is dropped."""
    core = core_pattern(pattern) if core is None else core
    out = godel.match(core, expr, b)
    if out is None:
        return None
    for name in _literal_vars(pattern):
        if name in out and out.pop(name) != ["var", name]:
            return None
    return out


def instantiate(pattern, b: dict, core=None):
    """``godel.substitute`` over a ``?x`` pattern; a variable ``b`` does not bind stays ``"?x"``."""
    core = core_pattern(pattern) if core is None else core
    binds = {**{v: v for v in _pattern_vars(pattern)}, **b}
    return godel.substitute(core, binds)


def _key(e) -> str:
    return repr(e)


def _unbound(e) -> bool:
    if isinstance(e, str):
        return e.startswith("?")
    if isinstance(e, list):
        return any(_unbound(x) for x in e)
    return False


def _pattern_vars(p) -> set:
    if isinstance(p, str) and p.startswith("?"):
        return {p}
    return set().union(*(_pattern_vars(x) for x in p)) if isinstance(p, list) and p else set()


def rewrites(expr, rules: list[Rule], var_sorts: dict | None = None, ops: dict | None = None):
    """Every (rule name, expression) reachable by applying one rule at one position. A rule applies only where its
    variables bind terms of the rule's sort (FOUNDATIONS.md rule A3); ``var_sorts`` gives the variables' sorts
    (untyped: int) and ``ops`` the op table whose ranks give each subterm's sort."""
    out = []
    seen = set()
    law = {id(r): S.law_sorts(_pattern_vars(r.lhs) | _pattern_vars(r.rhs), r.domain) for r in rules}
    cores = {id(r): (core_pattern(r.lhs), core_pattern(r.rhs)) for r in rules}

    def sort_of(t):
        return S.term_sort(t, var_sorts, ops)

    def visit(node, rebuild):
        for r in rules:
            b = match(r.lhs, node, core=cores[id(r)][0])
            if b is not None and S.admits(law[id(r)], b, sort_of):
                sub = instantiate(r.rhs, b, core=cores[id(r)][1])
                if _unbound(sub):
                    continue            # a variable that occurs only on the other side: not a rewrite
                new = rebuild(sub)
                k = _key(new)
                if k not in seen:
                    seen.add(k)
                    out.append((r.name, new))
        if isinstance(node, list) and node and node[0] not in ("var", "int", "float", "bool", "const"):
            start = 2 if node[0] == "FN" else 1
            for i in range(start, len(node)):
                def rb(child, i=i, node=node, rebuild=rebuild):
                    copy = list(node)
                    copy[i] = child
                    return rebuild(copy)
                visit(node[i], rb)

    visit(expr, lambda x: x)
    return out


def prove(lhs, rhs, rules: list[Rule], max_depth: int = 6, max_nodes: int = 50000, var_sorts: dict | None = None,
          ops: dict | None = None) -> dict | None:
    """Meet-in-the-middle BFS. Returns {"steps": [(rule, expr), ...], "nodes": n} or None."""
    if isinstance(lhs, str) and not lhs.startswith("?"):
        lhs = parse(lhs)
    if isinstance(rhs, str) and not rhs.startswith("?"):
        rhs = parse(rhs)
    if _key(lhs) == _key(rhs):
        return {"steps": [("start", lhs)], "nodes": 1}
    parents = [{_key(lhs): None}, {_key(rhs): None}]
    exprs = [{_key(lhs): lhs}, {_key(rhs): rhs}]
    frontier = [deque([(lhs, 0)]), deque([(rhs, 0)])]
    nodes = 2
    side = 0
    while (frontier[0] or frontier[1]) and nodes < max_nodes:
        if not frontier[side]:
            side = 1 - side
            continue
        layer_depth = frontier[side][0][1]
        while frontier[side] and frontier[side][0][1] == layer_depth and nodes < max_nodes:
            cur, d = frontier[side].popleft()
            if d >= max_depth:
                continue
            for rule, new in rewrites(cur, rules, var_sorts, ops):
                k = _key(new)
                if k in parents[side]:
                    continue
                parents[side][k] = (_key(cur), rule)
                exprs[side][k] = new
                nodes += 1
                if k in parents[1 - side]:
                    return {"steps": _join(k, parents, exprs, side), "nodes": nodes}
                frontier[side].append((new, d + 1))
        side = 1 - side
    return None


def _chain(k, parents, exprs):
    out = []
    while parents[k] is not None:
        prev, rule = parents[k]
        out.append((rule, exprs[k]))
        k = prev
    out.append(("start", exprs[k]))
    return list(reversed(out))


def _join(k, parents, exprs, side):
    a = _chain(k, parents[side], exprs[side])        # start(side) ... k
    b = _chain(k, parents[1 - side], exprs[1 - side])  # start(other) ... k
    if side == 1:
        a, b = b, a                                     # a: from lhs to k, b: from rhs to k
    steps = list(a)
    # walk back from k to rhs: the rule that produced b[i] (from b[i-1]) also maps b[i] -> b[i-1]
    for i in range(len(b) - 1, 0, -1):
        steps.append((b[i][0] + "~back", b[i - 1][1]))
    return steps


def op_costs(store) -> dict[str, float]:
    out = {}
    for card in store.cards("op"):
        c = card.get("cost")
        if isinstance(c, (int, float)):
            out[card.name] = float(c)
    return out


def expr_cost(expr, costs: dict[str, float]) -> float:
    if isinstance(expr, list) and expr and expr[0] not in ("var", "int", "float", "bool", "const"):
        head = expr[0]
        own = costs.get(head, 1.0) if head != "FN" else 5.0
        return own + sum(expr_cost(a, costs) for a in expr[(2 if head == "FN" else 1):])
    return 0.0


def optimize(expr, rules: list[Rule], costs: dict[str, float], max_depth: int = 4, max_nodes: int = 20000,
             var_sorts: dict | None = None, ops: dict | None = None) -> dict:
    """Cheapest expression reachable within the budget, with the chain of rules that reaches it."""
    if isinstance(expr, str):
        expr = parse(expr)
    best = (expr_cost(expr, costs), size(expr), expr)
    parents = {_key(expr): None}
    exprs = {_key(expr): expr}
    q = deque([(expr, 0)])
    nodes = 1
    while q and nodes < max_nodes:
        cur, d = q.popleft()
        if d >= max_depth:
            continue
        for rule, new in rewrites(cur, rules, var_sorts, ops):
            k = _key(new)
            if k in parents:
                continue
            parents[k] = (_key(cur), rule)
            exprs[k] = new
            nodes += 1
            c = (expr_cost(new, costs), size(new), new)
            if c[:2] < best[:2]:
                best = c
            q.append((new, d + 1))
    chain = _chain(_key(best[2]), parents, exprs)
    conds = {r.card: r.condition for r in rules if r.condition}
    used = {r.split("~")[0] for r, _ in chain[1:]}
    return {"input": to_text(expr), "input_cost": expr_cost(expr, costs), "best": to_text(best[2]),
            "best_tree": best[2], "best_cost": best[0], "steps": [(r, to_text(e)) for r, e in chain],
            "nodes": nodes, "valid_when": sorted({f"{u}: {conds[u]}" for u in used if u in conds})}
