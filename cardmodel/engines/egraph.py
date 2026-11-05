"""egraph — equality saturation over the model's equalities (docs/MATH_CORE.md phase 0, F4).

An e-graph holds many equal terms at once. An e-class is a set of equal e-nodes (an op over child classes, or a
leaf); congruence closure keeps two applications of one op to equal arguments in one class. The equalities come
from the cards: every unconditional rewrite rule, and every discovered law (a theorem ``l == r`` with no hypotheses)
that is proved or witnessed, in both directions. ``saturate`` applies them until nothing changes or the budget is
spent. ``extract`` picks a class's cheapest term under the op costs, ties broken by size and then by a fixed order,
so it is the class's canonical term, and ``semantic_hash`` names it.

The e-graph is many-sorted (docs/FOUNDATIONS.md D6, rule A3): every class carries the sort of its terms (``sorts``:
the op cards' ranks and the variables' sorts), and every rule the sorts its pattern variables must have (a rule
card's ``domain``, a theorem's ``vars[].type``). A rule fires only where each pattern variable binds a class of its
sort, so a law proved on ``int`` never reaches a ``float`` term, and saturation stays sound.

Two terms are proved equal when they land in one class. The certificate is the equalities that fired, plus a seeded
numeric witness of the two original terms.

The equalities are keyed by identity (docs/GODEL_AUDIT.md §4.2): a rule is its two sides up to the names of its
pattern variables, with the sorts they must bind (``rule_key``), and ``rules_from_cards`` keeps one rule per key (the
store states many laws twice, as a rewrite rule and as a discovered theorem: 89 of 262); the matching is done once
per law and the classes unioned are the same. ``canonical`` is memoized by its input (the term, its variables'
sorts, the rules, costs, ops and budget), so a term canonicalised once is not saturated again.

Honest limits (L1): saturation is bounded (iterations and nodes), so two terms in different classes are "not
shown equal", never unequal. Conditional rules are left out: their side conditions are not checked here. A
canonical term is canonical only within what the equalities reach. The certificate names the equalities but not yet
the chain between the two terms; a Lean proof from the chain is a later step (``search.prove`` finds chains for
short distances).
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
from collections import Counter, defaultdict

from . import sorts as S

LEAVES = ("var", "int", "float", "bool", "const")


class Rule:
    __slots__ = ("name", "lhs", "rhs", "origin", "sorts", "also")

    def __init__(self, name, lhs, rhs, origin, sorts=None, also=None):
        self.name, self.lhs, self.rhs, self.origin = name, lhs, rhs, origin
        self.sorts = sorts          # pattern variable -> sort it must bind (None: the law states no sort)
        self.also = list(also or [])    # origins of the same equality stated again elsewhere (``dedupe``)


def rule_key(lhs, rhs, sorts: dict | None = None) -> str:
    """The identity of an equality: its two sides with the pattern variables renamed by first appearance, and the
    sorts they must bind (FOUNDATIONS D7 for a law). Two rules with one key state one law, whatever their names."""
    names: dict = {}

    def walk(p):
        if isinstance(p, str) and p.startswith("?"):
            names.setdefault(p, f"?{len(names)}")
            return names[p]
        if isinstance(p, list):
            return [walk(x) for x in p]
        return p
    l, r = walk(lhs), walk(rhs)
    return semantic_hash([l, r, None if sorts is None else sorted((names.get(v, v), t) for v, t in sorts.items())])


def dedupe(rules: list[Rule]) -> list[Rule]:
    """One rule per identity: the first stands for the others and records their origins in ``also``. The duplicates
    would match where it matches and union the classes it unions, so saturation reaches the same classes with the
    matching done once per law."""
    out: list[Rule] = []
    by_key: dict[str, Rule] = {}
    for r in rules:
        first = by_key.get(rule_key(r.lhs, r.rhs, r.sorts))
        if first is None:
            by_key[rule_key(r.lhs, r.rhs, r.sorts)] = r
            out.append(r)
        elif r.origin != first.origin and r.origin not in first.also:
            first.also.append(r.origin)
    return out


def _norm(t):
    """A call of a named function (["FN", name, args...] or ["CALL", name, args...]) becomes the op "FN:name" or
    "CALL:name" over its args."""
    if isinstance(t, list) and t and t[0] in ("FN", "CALL") and len(t) >= 2 and isinstance(t[1], str):
        return [f"{t[0]}:{t[1]}", *[_norm(a) for a in t[2:]]]
    if isinstance(t, list) and t and t[0] not in LEAVES:
        return [t[0], *[_norm(a) for a in t[1:]]]
    return t


def _denorm(t):
    if isinstance(t, list) and t and isinstance(t[0], str) and t[0].startswith(("FN:", "CALL:")):
        head, name = t[0].split(":", 1)
        return [head, name, *[_denorm(a) for a in t[1:]]]
    if isinstance(t, list) and t and t[0] not in LEAVES:
        return [t[0], *[_denorm(a) for a in t[1:]]]
    return t


def _pvars(p) -> set:
    if isinstance(p, str) and p.startswith("?"):
        return {p}
    if isinstance(p, list):
        return set().union(*(_pvars(x) for x in p)) if p else set()
    return set()


def _to_pattern(t, names: set):
    """A theorem's term with its variables turned into pattern variables."""
    if isinstance(t, list) and t and t[0] == "var" and t[1] in names:
        return "?" + t[1]
    if isinstance(t, list):
        return [_to_pattern(x, names) for x in t]
    return t


def rules_from_cards(store, deduped: bool = True) -> list[Rule]:
    """Unconditional rewrite rules (with their reverses when bidirectional) and discovered laws, both ways, one rule
    per identity (``dedupe``; ``deduped=False`` keeps every statement). A rule whose left side is a bare variable,
    or whose right side needs a variable the left side does not bind, is left out: it would match everything or
    invent terms."""
    from .search import load_rules
    out = [Rule(r.name, _norm(r.lhs), _norm(r.rhs), f"rewrite_rule/{r.card}",
                S.law_sorts(_pvars(r.lhs) | _pvars(r.rhs), r.domain)) for r in load_rules(store) if not r.condition]
    for card in store.cards("theorem"):
        if card.get("hyps") or (card.get("origin") or {}).get("kind") != "discovered":
            continue
        if card.get("status") not in ("proved", "witnessed"):
            continue
        concl = card.get("concl")
        if isinstance(concl, list) and len(concl) == 3 and concl[0] == "eq":
            l, r = concl[1], concl[2]
        elif isinstance(concl, list) and len(concl) == 2 and concl[0] == "bool" and isinstance(concl[1], list) \
                and concl[1][:1] == ["CMP_EQ"]:
            l, r = concl[1][1], concl[1][2]
        else:
            continue
        types = {v["name"]: v.get("type") for v in card.get("vars") or []}
        lhs, rhs = _norm(_to_pattern(l, set(types))), _norm(_to_pattern(r, set(types)))
        sorts = S.law_sorts(_pvars(lhs) | _pvars(rhs), types=types)
        out.append(Rule(card.name, lhs, rhs, f"theorem/{card.name}", sorts))
        out.append(Rule(card.name + "~rev", rhs, lhs, f"theorem/{card.name}", sorts))
    out = [r for r in out if not (isinstance(r.lhs, str) and r.lhs.startswith("?")) and _pvars(r.rhs) <= _pvars(r.lhs)]
    return dedupe(out) if deduped else out


class EGraph:
    def __init__(self, var_sorts: dict | None = None, ops: dict | None = None):
        """``var_sorts``: variable name -> sort (an untyped variable is int); ``ops``: the op table (ir.op_table),
        whose ranks give each application's sort."""
        self.var_sorts, self.ops = var_sorts or {}, ops
        self.sort: dict[int, str | None] = {}
        self.parent: list[int] = []
        self.nodes: dict[int, set] = {}
        self.hashcons: dict = {}
        self.by_head: dict = defaultdict(set)
        self.count = 0

    # union-find --------------------------------------------------------------------------------------------------
    def find(self, a: int) -> int:
        while self.parent[a] != a:
            self.parent[a] = self.parent[self.parent[a]]
            a = self.parent[a]
        return a

    def _canon(self, node):
        if node[0] in LEAVES:
            return node
        return (node[0], tuple(self.find(c) for c in node[1]))

    def _new(self, node) -> int:
        cid = len(self.parent)
        self.parent.append(cid)
        self.nodes[cid] = {node}
        self.hashcons[node] = cid
        self.by_head[node[0]].add(cid)
        self.sort[cid] = self._node_sort(node)
        self.count += 1
        return cid

    def _node_sort(self, node) -> str | None:
        if node[0] in LEAVES:
            return S.leaf_sort([node[0], *json.loads(node[1])], self.var_sorts)
        got = S.result_sort(node[0], [self.sort.get(self.find(c)) for c in node[1]], self.ops)
        width = self._literal(node[1][1]) if len(node[1]) > 1 else None
        sub = S.refine(node[0], width, self.ops) if got is not None else None
        return sub if sub is not None and S.base(sub) == got else got

    def _literal(self, cid):
        for n in self.nodes.get(self.find(cid), ()):
            if n[0] == "int":
                return json.loads(n[1])[0]
        return None

    def add_node(self, node) -> int:
        node = self._canon(node)
        if node in self.hashcons:
            return self.find(self.hashcons[node])
        return self._new(node)

    def add(self, term) -> int:
        if isinstance(term, list) and term and term[0] in LEAVES:
            return self.add_node((term[0], json.dumps(term[1:])))
        if isinstance(term, list) and term:
            return self.add_node((term[0], tuple(self.add(c) for c in term[1:])))
        raise ValueError(f"not a term: {term!r}")

    def union(self, a: int, b: int) -> bool:
        a, b = self.find(a), self.find(b)
        if a == b:
            return False
        if len(self.nodes[a]) < len(self.nodes[b]):
            a, b = b, a
        self.parent[b] = a
        self.nodes[a] |= self.nodes.pop(b)
        sa, sb = self.sort.get(a), self.sort.pop(b, None)
        # one class, two sorts proved for it: it has the more specific (an int term equal to WRAPU(x, 8) is a u8);
        # sorts that cannot meet (int and float) make it unknown, so no law fires on it
        self.sort[a] = S.meet(sa, sb) if sa is not None and sb is not None else (sa if sb is None else sb)
        for head, cls in self.by_head.items():
            if b in cls:
                cls.discard(b)
                cls.add(a)
        return True

    def rebuild(self) -> None:
        """Congruence closure: nodes that become equal once their children are canonical merge their classes.
        Collisions are collected first and merged after, until a pass finds none."""
        while True:
            seen: dict = {}
            pairs = []
            for cid, nodes in self.nodes.items():
                for node in nodes:
                    n = self._canon(node)
                    other = seen.setdefault(n, cid)
                    if other != cid:
                        pairs.append((other, cid))
            merged = False
            for a, b in pairs:
                merged |= self.union(a, b)
            for cid in list(self.nodes):
                self.nodes[cid] = {self._canon(n) for n in self.nodes[cid]}
            self.hashcons = {n: cid for cid, ns in self.nodes.items() for n in ns}
            if not merged:
                return

    # matching ------------------------------------------------------------------------------------------------------
    def ematch(self, pat, cid: int, b: dict) -> list[dict]:
        cid = self.find(cid)
        if isinstance(pat, str) and pat.startswith("?"):
            if pat in b:
                return [b] if self.find(b[pat]) == cid else []
            return [{**b, pat: cid}]
        if isinstance(pat, list) and pat and pat[0] in LEAVES:
            return [b] if (pat[0], json.dumps(pat[1:])) in self.nodes[cid] else []
        out = []
        for node in self.nodes[cid]:
            if node[0] != pat[0] or node[0] in LEAVES or len(node[1]) != len(pat) - 1:
                continue
            bs = [b]
            for p, k in zip(pat[1:], node[1]):
                bs = [b2 for b1 in bs for b2 in self.ematch(p, k, b1)]
                if not bs:
                    break
            out += bs
        return out

    def instantiate(self, pat, b: dict) -> int:
        if isinstance(pat, str) and pat.startswith("?"):
            return self.find(b[pat])
        if isinstance(pat, list) and pat and pat[0] in LEAVES:
            return self.add_node((pat[0], json.dumps(pat[1:])))
        return self.add_node((pat[0], tuple(self.instantiate(p, b) for p in pat[1:])))

    def saturate(self, rules: list[Rule], max_iter: int = 8, max_nodes: int = 4000) -> dict:
        fired: Counter = Counter()
        saturated = False
        it = 0
        for it in range(1, max_iter + 1):
            matches = []
            for r in rules:
                head = r.lhs[0] if isinstance(r.lhs, list) and r.lhs else None
                for cid in list(self.by_head.get(head, ())):
                    for b in self.ematch(r.lhs, cid, {}):
                        if S.admits(r.sorts, b, lambda c: self.sort.get(self.find(c))):
                            matches.append((r, cid, b))
            changed = False
            for r, cid, b in matches:
                if self.count > max_nodes:
                    break
                if self.union(cid, self.instantiate(r.rhs, b)):
                    changed = True
                    fired[r.origin] += 1
            self.rebuild()
            if not changed:
                saturated = True
                break
            if self.count > max_nodes:
                break
        return {"iterations": it, "nodes": self.count, "classes": len(self.nodes), "saturated": saturated,
                "fired": dict(fired.most_common())}

    # extraction ----------------------------------------------------------------------------------------------------
    def extract(self, cid: int, costs: dict[str, float]):
        """The cheapest term of a class: cost, then size, then a fixed order (so it is canonical)."""
        INF = (float("inf"), 0, "")
        best: dict[int, tuple] = {}
        changed = True
        while changed:
            changed = False
            for c, nodes in self.nodes.items():
                for node in nodes:
                    if node[0] in LEAVES:
                        term = [node[0], *json.loads(node[1])]
                        cand = (0.0, 1, json.dumps(term), term)
                    else:
                        kids = [best.get(self.find(k)) for k in node[1]]
                        if any(k is None for k in kids):
                            continue
                        term = [node[0], *[k[3] for k in kids]]
                        cand = (costs.get(node[0], 1.0) + sum(k[0] for k in kids), 1 + sum(k[1] for k in kids),
                                json.dumps(term), term)
                    if cand[:3] < best.get(c, INF)[:3]:
                        best[c] = cand
                        changed = True
        got = best.get(self.find(cid))
        return (got[3], got[0]) if got else (None, None)


def semantic_hash(term) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(term, sort_keys=True).encode()).hexdigest()[:24]


_MEMO: dict[str, dict] = {}
MEMO_CAP = 50_000
STATS: Counter = Counter()      # hits and misses of the memo, for measurement


def _variables(term, out: set) -> set:
    if isinstance(term, list) and term:
        if term[0] == "var":
            out.add(term[1])
        elif term[0] not in LEAVES:
            for a in term[1:]:
                _variables(a, out)
    return out


def _memo_key(term, rules, costs, var_sorts, ops, budget) -> str:
    """Everything the canonical form depends on: the term, the sorts of its variables, the rules (by origin and
    name, in order), the costs, the op table's names and ranks, and the budget."""
    used = sorted(_variables(term, set()))
    return semantic_hash([term, [(v, (var_sorts or {}).get(v)) for v in used], [[r.origin, r.name] for r in rules],
                          sorted(costs.items()), None if ops is None else sorted((n, getattr(o, "types", None))
                                                                                  for n, o in ops.items()),
                          sorted(budget.items())])


def clear_memo() -> None:
    _MEMO.clear()
    STATS.clear()


def canonical(term, rules: list[Rule], costs: dict[str, float], var_sorts: dict | None = None,
              ops: dict | None = None, memo: bool = True, **budget) -> dict:
    """The class's cheapest term, its cost, its hash and the saturation's record. Memoized by ``_memo_key`` (the
    result is a copy, so a caller may change it); ``memo=False`` always saturates."""
    key = _memo_key(term, rules, costs, var_sorts, ops, budget) if memo else None
    if key is not None:
        got = _MEMO.get(key)
        if got is not None:
            STATS["hits"] += 1
            return copy.deepcopy(got)
        STATS["misses"] += 1
    g = EGraph(var_sorts, ops)
    root = g.add(_norm(term))
    info = g.saturate(rules, **budget)
    best, cost = g.extract(root, costs)
    best = _denorm(best)
    out = {"term": best, "cost": cost, "hash": semantic_hash(best), **info}
    if key is not None:
        if len(_MEMO) >= MEMO_CAP:
            _MEMO.clear()
        _MEMO[key] = copy.deepcopy(out)
    return out


def equal(a, b, rules: list[Rule], var_sorts: dict | None = None, ops: dict | None = None, **budget) -> dict:
    g = EGraph(var_sorts, ops)
    ra, rb = g.add(_norm(a)), g.add(_norm(b))
    info = g.saturate(rules, **budget)
    return {"equal": g.find(ra) == g.find(rb), **info}


def witness(a, b, seed: int, samples: int = 64, ops: dict | None = None) -> dict:
    """The two terms agree on seeded integers (values where either side is undefined are skipped). With ``ops``
    (``ir.op_table``) they are evaluated in the model M, the op cards' semantics (FOUNDATIONS.md rule A2)."""
    from .exprs import evaluate, resolve_ops, variables
    if ops is not None:
        from .logic import LogicError, eval_expr
        a, b = resolve_ops(a, ops), resolve_ops(b, ops)

        def evaluate(t, env):          # noqa: F811
            try:
                return eval_expr(t, env, ops)
            except LogicError as exc:
                raise ValueError(str(exc)) from exc
    rng = random.Random(seed)
    names = sorted(variables(a) | variables(b))
    checked = 0
    for _ in range(samples * 4):
        env = {n: rng.randint(-60, 60) for n in names}
        try:
            x, y = evaluate(a, env), evaluate(b, env)
        except (ZeroDivisionError, ValueError, OverflowError, ArithmeticError):
            continue
        if x != y:
            return {"status": "refuted", "at": env, "values": [x, y], "checks": checked}
        checked += 1
        if checked >= samples:
            break
    return {"status": "witnessed" if checked else "vacuous", "checks": checked, "seed": seed}


def measure(ctx, seed: int = 0) -> dict:
    """The e-graph on the function cards' result expressions: how many reduce, and which share a canonical term."""
    from .search import op_costs
    rules, costs = rules_from_cards(ctx.store), op_costs(ctx.store)
    rows, groups = [], defaultdict(list)
    for card in sorted(ctx.store.cards("function"), key=lambda c: c.name):
        mod = card.get("ir") or {}
        fn = next((f for f in mod.get("functions") or [] if f.get("name") == mod.get("entry")), None)
        body = (fn or {}).get("body") or []
        if len(body) != 1 or body[0].get("k") != "return":
            continue
        term = body[0]["value"]
        from .search import expr_cost
        try:
            r = canonical(term, rules, costs, max_iter=6, max_nodes=3000)
        except ValueError as exc:
            rows.append({"card": card.qualified, "skipped": str(exc)})
            continue
        rows.append({"card": card.qualified, "before": expr_cost(term, costs), "after": r["cost"], "hash": r["hash"],
                     "saturated": r["saturated"]})
        groups[r["hash"]].append(card.qualified)
    done = [x for x in rows if "hash" in x]
    return {"terms": len(done), "skipped": len(rows) - len(done),
            "reduced": sum(1 for x in done if x["after"] < x["before"]),
            "saturated": sum(1 for x in done if x["saturated"]), "rules": len(rules),
            "shared": {h: cs for h, cs in groups.items() if len(cs) > 1}, "rows": rows}


__all__ = ["EGraph", "Rule", "canonical", "clear_memo", "dedupe", "equal", "measure", "rule_key", "rules_from_cards",
           "semantic_hash", "witness"]
