"""bits — the smallest piece of computation, mastered: one bit, and every function of at most two bits.

This is level L01 of the understanding roadmap (``cards/understanding``, docs/UNDERSTANDING.md). Everything a
computer does is built from this level, and it is the only level small enough to be understood *completely*: it
has finitely many objects (16 functions of two bits contain every function of zero, one or two bits), every claim
about it can be checked on every input (4 rows), and every search over it can be run to the end. So here "checked
on all inputs" is a proof and "not found by an exhaustive search" is a proof that it does not exist.

What is given, and what is learned:

* **Given (the basics).** A bit is one of two values. The op cards with a ``bool`` rank (``cards/op``: AND, OR,
  NOT, CMP_EQ, CMP_NE, IF_EXPR) and the IR interpreter that runs them (engines/ir.py). Nothing in this file says
  what any function does.
* **Observed.** Each op card's truth table is read by running the card through the IR interpreter on every row.
* **Derived, by exhaustive search, all checked on every row:**

  1. *The space.* All 2^(2^n) truth tables of n bits; which inputs each one depends on (so the constants and the
     one-bit functions are found inside the 16, not listed); which op card realises each one.
  2. *Construction.* For every function, a smallest circuit (straight-line program, sharing allowed) over a basis,
     with the number of smaller programs that were searched and failed: a proof of minimality. Bases: the op
     cards (with the literals true and false) and any single gate the model finds complete on its own.
  3. *Sufficiency.* For each of the 2^16 sets of gates, whether it builds every function (closure under
     composition). The minimal complete sets, the gates complete on their own (the model finds NAND and NOR,
     neither of which has an op card), and the maximal *incomplete* sets: the obstructions. Post's five classes
     (1941) are an independent cross-check of every one of the 65,536 answers, computed from their definitions.
  4. *Laws.* Every equation between terms over the op cards up to a size, in three variables, found by
     enumeration (a term whose truth table was already seen gives an equation), never from templates. Each is
     checked on all 8 rows, so each is proved.
  5. *Expression in the core.* Every function as an IR term over the op cards, re-run by the IR interpreter on
     every row: the same check every lifted function gets.

The search code is generic in the number of inputs, so the next level (L02, functions of n bits) starts from it:
``formula_sizes(3)`` already gives a smallest formula for each of the 256 functions of three bits.

Honest limits (L1): minimality is in gate count (each gate costs 1), not in depth or in the op cards' costs;
circuits are over gates of at most two inputs (IF_EXPR, three inputs, is observed but belongs to L02); laws are
complete only up to the stated size; the names NAND, NOR, IMPLIES and so on are labels for humans, not logic
(the function is its truth table).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass

from .ir import Interpreter

MAX_GATES = 6             # deepest circuit search (the hardest two-bit function over NAND needs 5)
LAW_SIZE = 3              # laws: every term with at most this many op nodes, in three variables
VARS = ("x", "y", "z")

# Labels only, for readers: the function *is* its truth table (bit r is the value on row r, where row r has
# x = bit 1 of r and y = bit 0 of r). Nothing is computed from these names.
LABELS = {0b0000: "FALSE", 0b0001: "NOR", 0b0010: "NOT_X_AND_Y", 0b0011: "NOT_X", 0b0100: "X_AND_NOT_Y",
          0b0101: "NOT_Y", 0b0110: "XOR", 0b0111: "NAND", 0b1000: "AND", 0b1001: "XNOR", 0b1010: "Y",
          0b1011: "X_IMPLIES_Y", 0b1100: "X", 0b1101: "Y_IMPLIES_X", 0b1110: "OR", 0b1111: "TRUE"}


class BitsError(Exception):
    pass


# -- truth tables -------------------------------------------------------------------------------------------------
def rows(n: int) -> list[tuple]:
    """Row r of an n-input table: input j is bit (n-1-j) of r, so x is the high bit (row 2 of two inputs: x=1, y=0)."""
    return [tuple(bool((r >> (n - 1 - j)) & 1) for j in range(n)) for r in range(1 << n)]


def table_of(fn, n: int) -> int:
    return sum(1 << r for r, row in enumerate(rows(n)) if fn(*row))


def projection(n: int, j: int) -> int:
    return table_of(lambda *a: a[j], n)


def full(n: int) -> int:
    return (1 << (1 << n)) - 1


def bit(t: int, r: int) -> bool:
    return bool((t >> r) & 1)


@dataclass(frozen=True)
class Gate:
    """A function of ``arity`` bits used as a building block; ``table`` is its truth table over its own inputs."""
    name: str
    arity: int
    table: int

    def apply(self, n: int, *args: int) -> int:
        """The table (over n inputs) of this gate fed with the tables ``args``."""
        out = 0
        for r in range(1 << n):
            idx = 0
            for a in args:
                idx = (idx << 1) | ((a >> r) & 1)
            out |= ((self.table >> idx) & 1) << r
        return out

    @property
    def symmetric(self) -> bool:
        """Swapping the inputs never changes the output (read from the table, so the search may skip mirrors)."""
        return self.arity == 2 and self.apply(2, projection(2, 1), projection(2, 0)) == self.table


def depends_on(t: int, n: int) -> list[str]:
    """The inputs a table actually depends on: flipping input j changes the value on some row."""
    out = []
    for j in range(n):
        m = 1 << (n - 1 - j)
        if any(bit(t, r) != bit(t, r ^ m) for r in range(1 << n)):
            out.append(VARS[j])
    return out


# -- observing the op cards ---------------------------------------------------------------------------------------
def observe_ops(ops) -> list[dict]:
    """The truth table of every op card with an all-bool rank, read by running the card in the IR interpreter."""
    out = []
    for name, spec in sorted(ops.items()):
        if not any(len(sig) == spec.arity + 1 and all(t == "bool" for t in sig) for sig in spec.types):
            continue
        params = [{"name": f"a{i}", "type": "bool"} for i in range(spec.arity)]
        fn = {"name": "f", "params": params, "returns": "bool", "locals": {},
              "body": [{"k": "return", "value": [name, *(["var", p["name"]] for p in params)]}]}
        interp = Interpreter({"functions": [fn]}, ops)
        t = table_of(lambda *a: interp.call("f", list(a)) is True, spec.arity)
        out.append({"op": name, "arity": spec.arity, "table": t})
    return out


def card_gates(ops) -> list[Gate]:
    """The op cards of at most two inputs as gates (IF_EXPR, three inputs, is observed but belongs to L02)."""
    return [Gate(o["op"], o["arity"], o["table"]) for o in observe_ops(ops) if o["arity"] <= 2]


def all_binary_gates() -> list[Gate]:
    return [Gate(LABELS[t], 2, t) for t in range(16)]


# -- construction: smallest circuits ------------------------------------------------------------------------------
def smallest_circuits(gates: list[Gate], n: int = 2, constants: bool = False, max_gates: int = MAX_GATES,
                      targets: set | None = None, cost: dict | None = None) -> dict:
    """Smallest straight-line programs over ``gates`` for every table of n inputs, by iterative deepening.

    Every program of k gates is enumerated before any of k+1, so a function first reached at k gates has no
    program with fewer: ``searched[k]`` is how many programs of exactly k gates were tried. A gate whose output is
    already a node is skipped (removing it gives a smaller program with the same nodes), and a symmetric gate is
    fed each unordered pair once. Among the smallest programs for a function the cheapest by ``cost`` (the op
    cards' own costs) is kept, so ties go to the basic form. Inputs are the n projections, plus the literals FALSE and TRUE if ``constants``.
    Returns {"best": {table: program}, "searched": [count per k], "complete": bool}; a program is a list of
    (gate name, input node indices), its nodes numbered inputs first."""
    leaves = [projection(n, j) for j in range(n)] + ([0, full(n)] if constants else [])
    want = set(range(1 << (1 << n))) if targets is None else set(targets)
    best: dict[int, list] = {}
    for i, t in enumerate(leaves):
        best.setdefault(t, [("leaf", (i,))])
    searched = [1]
    by_name = {g.name: g for g in gates}
    price = (lambda prog: sum(cost.get(g, 1.0) for g, _ in prog)) if cost else (lambda prog: 0.0)

    def args_for(g: Gate, m: int):
        if g.arity == 1:
            return ((i,) for i in range(m))
        if g.symmetric:
            return itertools.combinations_with_replacement(range(m), 2)
        return itertools.product(range(m), repeat=g.arity)

    def extend(nodes: list, prog: list, k: int, count: list):
        if len(prog) == k:
            count[0] += 1
            return
        for g in gates:
            for a in args_for(g, len(nodes)):
                t = g.apply(n, *(nodes[i] for i in a))
                if t in nodes:
                    continue
                step = prog + [(g.name, a)]
                if len(step) == k and (t not in best or (len(best[t]) == k and best[t][0][0] != "leaf"
                                                         and price(step) < price(best[t]))):
                    best[t] = step
                nodes.append(t)
                extend(nodes, step, k, count)
                nodes.pop()

    k = 0
    while not want <= set(best) and k < max_gates:
        k += 1
        count = [0]
        extend(list(leaves), [], k, count)
        searched.append(count[0])
    assert all(_run(p, n, leaves, by_name)[-1] == t for t, p in best.items() if p[0][0] != "leaf")
    return {"best": best, "searched": searched, "leaves": leaves, "complete": want <= set(best)}


def _run(prog, n, leaves, by_name) -> list[int]:
    nodes = list(leaves)
    for name, a in prog:
        nodes.append(by_name[name].apply(n, *(nodes[i] for i in a)))
    return nodes


def leaf_names(n: int, constants: bool) -> list[str]:
    return list(VARS[:n]) + (["FALSE", "TRUE"] if constants else [])


def show_program(prog, n: int, constants: bool) -> str:
    names = leaf_names(n, constants)
    if prog[0][0] == "leaf":
        return names[prog[0][1][0]]
    lines = []
    for i, (g, a) in enumerate(prog):
        names.append(f"g{i + 1}")
        lines.append(f"g{i + 1} = {g}({', '.join(names[j] for j in a)})")
    return "; ".join(lines)


def program_term(prog, n: int, constants: bool, op_of=lambda g: g) -> list:
    """The program as one IR term (shared nodes are inlined): leaves are IR vars and bool literals."""
    nodes = [["var", v] for v in VARS[:n]] + ([["bool", False], ["bool", True]] if constants else [])
    if prog[0][0] == "leaf":
        return nodes[prog[0][1][0]]
    for g, a in prog:
        nodes.append([op_of(g), *(nodes[i] for i in a)])
    return nodes[-1]


def show_term(t) -> str:
    if t[0] == "var":
        return t[1]
    if t[0] == "bool":
        return "TRUE" if t[1] else "FALSE"
    return f"{t[0]}({', '.join(show_term(a) for a in t[1:])})"


def check_term(term, n: int, table: int, ops) -> bool:
    """Run the term in the IR interpreter on every row and compare with the table: the core's own check."""
    fn = {"name": "f", "params": [{"name": v, "type": "bool"} for v in VARS[:n]], "returns": "bool",
          "locals": {}, "body": [{"k": "return", "value": term}]}
    interp = Interpreter({"functions": [fn]}, ops)
    return all((interp.call("f", list(row)) is True) == bit(table, r) for r, row in enumerate(rows(n)))


# -- sufficiency: which sets of gates build everything ------------------------------------------------------------
def _compose_table() -> list:
    """comp[f][a][b]: the two-input table f(a, b) where a and b are themselves two-input tables."""
    gates = all_binary_gates()
    return [[[gates[f].apply(2, a, b) for b in range(16)] for a in range(16)] for f in range(16)]


def closure_masks():
    """cl(S) for every set S of two-input functions (a 16-bit mask): the smallest set holding x, y and S and closed
    under using any of its members as a gate. A clone's two-input part is closed this way, so S builds every
    function of every arity exactly when cl(S) holds all 16 (it then holds NAND, which builds the rest)."""
    comp = _compose_table()
    xy = (1 << 0b1100) | (1 << 0b1010)
    memo: dict[int, int] = {}

    def close(mask: int) -> int:
        if mask in memo:
            return memo[mask]
        cur = mask
        while True:
            mem = [t for t in range(16) if (cur >> t) & 1]
            new = cur
            for f in mem:
                cf = comp[f]
                for a in mem:
                    for b in mem:
                        new |= 1 << cf[a][b]
            if new == cur:
                break
            cur = new
        memo[mask] = cur
        return cur

    cl = [0] * (1 << 16)
    cl[0] = close(xy)
    for s in range(1, 1 << 16):
        low = s & -s
        cl[s] = close(cl[s ^ low] | low)
    return cl


def post_classes(t: int) -> dict:
    """Post's five properties of a two-input table, from their definitions (the independent cross-check)."""
    f = [bit(t, r) for r in range(4)]          # f[2x+y]
    return {
        "preserves_false": not f[0],
        "preserves_true": f[3],
        "self_dual": all(f[r] != f[3 - r] for r in range(4)),
        "monotone": all(f[a] <= f[b] for a in range(4) for b in range(4) if a & b == a),
        "affine": not (f[0] ^ f[1] ^ f[2] ^ f[3]),
    }


def sufficiency() -> dict:
    full16 = (1 << 16) - 1
    cl = closure_masks()
    complete = [s for s in range(1 << 16) if cl[s] == full16]
    cset = set(complete)
    minimal = [s for s in complete if all((s ^ (1 << t)) not in cset for t in range(16) if (s >> t) & 1)]
    closed = sorted({cl[s] for s in range(1 << 16)})
    proper = [c for c in closed if c != full16]
    maximal = [c for c in proper if not any(c != d and c & d == c for d in proper)]
    # cross-check every answer with Post's criterion: complete iff, for each property, some member lacks it
    props = {t: post_classes(t) for t in range(16)}
    names = list(props[0])
    disagree = 0
    for s in range(1 << 16):
        members = [t for t in range(16) if (s >> t) & 1]
        post = all(any(not props[t][p] for t in members) for p in names)
        disagree += post != (s in cset)
    # each obstruction is the set of functions with one of Post's properties, restricted to two inputs
    classes = {p: sum(1 << t for t in range(16) if props[t][p]) for p in names}
    obstruction = []
    for c in maximal:
        obstruction.append({"members": _members(c), "post_property": [p for p, m in classes.items() if m == c]})
    # a Post class that is no obstruction here sits inside one (two-input self-dual functions are all affine)
    inside = {p: [q for o in obstruction for q in o["post_property"] if classes[p] & _mask(o["members"]) == classes[p]]
              for p in names if not any(p in o["post_property"] for o in obstruction)}
    # functions of one input or none (they depend on at most one variable) never build everything
    degenerate = sum(1 << t for t in range(16) if len(depends_on(t, 2)) <= 1)
    unary_complete = any(s & ~degenerate == 0 for s in complete)
    return {"sets": 1 << 16, "complete": len(complete), "closed_sets": len(closed), "unary_complete": unary_complete,
            "minimal_complete": [_members(s) for s in sorted(minimal, key=lambda s: (bin(s).count("1"), s))],
            "sole": [_label(t) for t in range(16) if (1 << t) in cset],
            "obstructions": obstruction, "post_disagreements": disagree,
            "post_inside": inside}


def _members(mask: int) -> list[str]:
    return [_label(t) for t in range(16) if (mask >> t) & 1]


def _mask(labels) -> int:
    inv = {v: k for k, v in LABELS.items()}
    return sum(1 << inv[x] for x in labels)


def _label(t: int) -> str:
    return LABELS[t]


# -- laws: equations found by enumeration -------------------------------------------------------------------------
def discover_laws(gates: list[Gate], n: int = 3, size: int = LAW_SIZE, constants: bool = True,
                  cost: dict | None = None) -> dict:
    """Every equation l = r between terms over ``gates`` with at most ``size`` gate nodes, in n variables.

    Terms are enumerated by size, and within a size in the term order (fewer nodes, then cheaper by the op cards'
    costs, then structure). The first term seen for a truth table is its *representative*; every later term with
    that table gives the law ``term = representative``. A term with a non-representative subterm is never built:
    its equation follows from a smaller law by substituting equals. A law that is a renaming of the variables of
    a kept one is dropped, and a law whose two sides the kept laws already rewrite to the same term (ordered
    rewriting: an instance is used only when it makes the term smaller in the term order) is counted as derived,
    not kept. Every law is checked on all 2^n rows by construction (equal truth tables), so every law is proved;
    the kept ones are a basis the derived ones follow from."""
    leaves = [["var", v] for v in VARS[:n]] + ([["bool", False], ["bool", True]] if constants else [])
    tables = [projection(n, j) for j in range(n)] + ([0, full(n)] if constants else [])
    order = TermOrder(gates, leaves, cost)
    by_name = {g.name: g for g in gates}
    rep: dict[int, list] = {}
    by_size: dict[int, list] = {0: []}
    for term, t in zip(leaves, tables):
        if t not in rep:
            rep[t] = term
            by_size[0].append((term, t))
    laws, seen, derived = [], set(), 0
    rules = Rules(order, frozenset(g.name for g in gates if g.symmetric))
    for s in range(1, size + 1):
        cands = []
        for g in gates:
            for parts in _size_splits(s - 1, g.arity):
                for args in itertools.product(*(by_size[p] for p in parts)):
                    cands.append(([g.name, *(a[0] for a in args)], g.apply(n, *(a[1] for a in args))))
        cands.sort(key=lambda c: order.key(c[0]))
        by_size[s] = []
        for term, t in cands:
            if t not in rep:
                rep[t] = term
                by_size[s].append((term, t))
                continue
            key = _canon_vars((term, rep[t]))
            if key in seen:
                continue
            seen.add(key)
            if rules.normalize(term) == rules.normalize(rep[t]):
                derived += 1
                continue
            laws.append({"lhs": term, "rhs": rep[t], "size": s, "table": t})
            rules.add(term, rep[t])
    assert all(_eval_term(l["lhs"], n, leaves, tables, by_name) == _eval_term(l["rhs"], n, leaves, tables, by_name)
               for l in laws)
    return {"laws": laws, "derived": derived, "representatives": len(rep), "functions": 1 << (1 << n),
            "size": size, "rules": rules}


def _eval_term(t, n, leaves, tables, by_name) -> int:
    if t[0] in ("var", "bool"):
        return tables[leaves.index(t)]
    return by_name[t[0]].apply(n, *(_eval_term(a, n, leaves, tables, by_name) for a in t[1:]))


class TermOrder:
    """A total, well-founded order on terms: node count, then the op cards' cost, then structure (gate order,
    then the arguments). Representatives are the least term of their truth table in this order."""

    def __init__(self, gates, leaves, cost):
        self.gi = {g.name: i for i, g in enumerate(gates)}
        self.li = {repr(l): i for i, l in enumerate(leaves)}
        self.cost = cost or {}
        self._memo: dict = {}

    def key(self, t) -> tuple:
        r = repr(t)
        k = self._memo.get(r)
        if k is None:
            k = self._memo[r] = (_size(t), self._cost(t), self._struct(t))
        return k

    def _cost(self, t) -> float:
        if t[0] in ("var", "bool"):
            return 0.0
        return self.cost.get(t[0], 1.0) + sum(self._cost(a) for a in t[1:])

    def _struct(self, t) -> tuple:
        if t[0] in ("var", "bool"):
            return (0, self.li.get(repr(t), -1))
        return (1, self.gi[t[0]], tuple(_size(a) for a in t[1:]), tuple(self._struct(a) for a in t[1:]))


class Rules:
    """Kept laws used both ways as ordered rewrite rules (indexed by the head of the side being matched), matched
    modulo the symmetry of the gates that are symmetric."""

    def __init__(self, order: TermOrder, sym=frozenset()):
        self.order = order
        self.sym = sym
        self.by_head: dict[str, list] = {}

    def add(self, lhs, rhs) -> None:
        for l, r in ((lhs, rhs), (rhs, lhs)):
            self.by_head.setdefault(l[0] if l[0] != "var" else "*", []).append((l, r))

    def normalize(self, term, limit: int = 100):
        for _ in range(limit):
            nxt = self._once(term)
            if nxt is None:
                return term
            term = nxt
        return term

    def _once(self, t):
        if t[0] not in ("var", "bool"):
            for i, a in enumerate(t[1:], 1):
                r = self._once(a)
                if r is not None:
                    return t[:i] + [r] + t[i + 1:]
        for l, r in self.by_head.get(t[0], []) + self.by_head.get("*", []):
            env: dict = {}
            if _match(l, t, env, self.sym):
                out = _subst(r, env)
                if self.order.key(out) < self.order.key(t):
                    return out
        return None


def _size(t) -> int:
    return 0 if t[0] in ("var", "bool") else 1 + sum(_size(a) for a in t[1:])


def _match(pat, t, env: dict, sym=frozenset()) -> bool:
    """Bind the pattern's variables so that it equals ``t``; a gate in ``sym`` (symmetric, read from its table)
    matches its arguments in either order."""
    if pat[0] == "var":
        if pat[1] in env:
            return env[pat[1]] == t
        env[pat[1]] = t
        return True
    if pat[0] == "bool" or t[0] != pat[0] or len(t) != len(pat):
        return pat == t
    if pat[0] in sym and len(pat) == 3:
        for order in ((t[1], t[2]), (t[2], t[1])):
            trial = dict(env)
            if _match(pat[1], order[0], trial, sym) and _match(pat[2], order[1], trial, sym):
                env.clear()
                env.update(trial)
                return True
        return False
    return all(_match(p, a, env, sym) for p, a in zip(pat[1:], t[1:]))


def _subst(t, env):
    if t[0] == "var":
        return env.get(t[1], t)
    if t[0] == "bool":
        return t
    return [t[0], *(_subst(a, env) for a in t[1:])]


def _size_splits(total: int, k: int):
    if k == 1:
        yield (total,)
        return
    for i in range(total + 1):
        for rest in _size_splits(total - i, k - 1):
            yield (i, *rest)


def _canon_vars(pair) -> str:
    order: dict[str, str] = {}

    def walk(t):
        if t[0] == "var":
            if t[1] not in order:
                order[t[1]] = VARS[len(order)]
            return ["var", order[t[1]]]
        if t[0] == "bool":
            return t
        return [t[0], *(walk(a) for a in t[1:])]
    return repr([walk(pair[0]), walk(pair[1])])


# -- level 2 starts here: smallest formulas for every function of n inputs ----------------------------------------
def formula_sizes(n: int, gates: list[Gate] | None = None, max_size: int = 12) -> dict:
    """The smallest formula (a tree: no sharing) for every table of n inputs over ``gates`` (default: all 16
    two-input gates), by dynamic programming over size; exhaustive, so each size is a minimum."""
    gates = [g for g in (gates or all_binary_gates()) if g.arity == 2]
    best: dict[int, tuple] = {projection(n, j): (0, ["var", VARS[j]]) for j in range(n)}
    layer: dict[int, list] = {0: list(best)}
    size = 0
    while len(best) < 1 << (1 << n) and size < max_size:
        size += 1
        layer[size] = []
        for i in range(size):
            for a in layer[i]:
                for b in layer[size - 1 - i]:
                    for g in gates:
                        t = g.apply(n, a, b)
                        if t not in best:
                            best[t] = (size, [g.name, best[a][1], best[b][1]])
                            layer[size].append(t)
    return {"n": n, "found": len(best), "functions": 1 << (1 << n), "best": best}


# -- the level, mastered ------------------------------------------------------------------------------------------
def master(ops) -> dict:
    """Run every part of L01 and return the results and the cards they become."""
    observed = observe_ops(ops)
    cards = card_gates(ops)
    by_table: dict[int, list] = {}
    for o in observed:
        if o["arity"] == 2:
            by_table.setdefault(o["table"], []).append(o["op"])
        elif o["arity"] == 1:   # a one-input card is two functions of two inputs: on x, and on y
            for j in range(2):
                t = Gate(o["op"], 1, o["table"]).apply(2, projection(2, j))
                by_table.setdefault(t, []).append(f"{o['op']}({VARS[j]})")
    suff = sufficiency()
    sole = [LABELS_INV[s] for s in suff["sole"]]
    costs = {g.name: float(ops[g.name].card.get("cost", 1.0)) for g in cards}
    over_cards = smallest_circuits(cards, constants=True, cost=costs)
    over_sole = {LABELS[t]: smallest_circuits([Gate(LABELS[t], 2, t)]) for t in sole}
    laws = discover_laws(cards, cost=costs)
    fns = []
    for t in range(16):
        prog = over_cards["best"][t]
        term = program_term(prog, 2, True)
        fns.append({
            "name": LABELS[t], "table": t, "truth": [int(bit(t, r)) for r in range(4)],
            "depends_on": depends_on(t, 2), "op_cards": sorted(by_table.get(t, [])),
            "over_op_cards": {"gates": _gates(prog), "program": show_program(prog, 2, True),
                              "term": term, "ir_checked": check_term(term, 2, t, ops)},
            "over_sole_gate": {g: {"gates": _gates(r["best"][t]), "program": show_program(r["best"][t], 2, False)}
                               for g, r in over_sole.items()},
            "post": post_classes(t),
            "complete_alone": LABELS[t] in suff["sole"],
        })
    fa = formula_sizes(3)
    return {
        "observed": observed, "functions": fns, "sufficiency": suff,
        "searched": {"op_cards": over_cards["searched"], **{g: r["searched"] for g, r in over_sole.items()}},
        "laws": laws,
        "level2": {"n": 3, "found": fa["found"], "functions": fa["functions"],
                   "max_size": max(s for s, _ in fa["best"].values()),
                   "full_adder": {k: {"size": fa["best"][t][0], "term": show_term(fa["best"][t][1])}
                                  for k, t in (("sum", table_of(lambda a, b, c: a ^ b ^ c, 3)),
                                               ("carry", table_of(lambda a, b, c: (a + b + c) >= 2, 3)))}},
    }


LABELS_INV = {v: k for k, v in LABELS.items()}


def _gates(prog) -> int:
    return 0 if prog[0][0] == "leaf" else len(prog)


def mastery(res: dict, level: str = "L01_two_bit_functions") -> list[dict]:
    """The mastery criteria of a level this engine owns (L00, L01), each computed from the results, never
    asserted. Their order is the order of the ``mastery`` list on the level's card."""
    fns = res["functions"]
    suff = res["sufficiency"]
    obs = {o["op"]: o for o in res["observed"]}
    if level == "L00_bit":
        eq = obs.get("CMP_EQ", {}).get("table")
        return [
            {"id": "M1_two_values", "ok": eq is not None and eq == table_of(lambda a, b: a == b, 2)
             and len({bit(eq, r) for r in range(4)}) == 2},
            {"id": "M2_rows", "ok": all(len(set(rows(n))) == 1 << n and rows(n) == sorted(rows(n))
                                        for n in range(0, 5))},
            {"id": "M3_identity", "ok": len({f["table"] for f in fns}) == len(fns) == 16},
        ]
    return [
        {"id": "M1_space", "ok": len(fns) == 16 and sorted(len(f["depends_on"]) for f in fns)
         == [0] * 2 + [1] * 4 + [2] * 10},
        {"id": "M2_observed", "ok": bool(res["observed"]) and all(isinstance(o["table"], int)
                                                                  for o in res["observed"])},
        {"id": "M3_constructed", "ok": all(f["over_op_cards"]["ir_checked"] for f in fns)},
        {"id": "M4_one_gate", "ok": bool(suff["sole"]) and all(len(f["over_sole_gate"]) == len(suff["sole"])
                                                               for f in fns)},
        {"id": "M5_sufficiency", "ok": suff["sets"] == 1 << 16 and suff["post_disagreements"] == 0
         and not suff["unary_complete"]},
        {"id": "M6_laws", "ok": len(res["laws"]["laws"]) > 0},
    ]


# Classic laws of Boolean algebra, written over the op cards. Used only to *report* which of them the
# enumeration rediscovered (kept as a basis law, or derived from the kept ones); nothing is derived from them.
CLASSIC = {
    "commutativity of AND": (["AND", ["var", "y"], ["var", "x"]], ["AND", ["var", "x"], ["var", "y"]]),
    "associativity of AND": (["AND", ["AND", ["var", "x"], ["var", "y"]], ["var", "z"]],
                             ["AND", ["var", "x"], ["AND", ["var", "y"], ["var", "z"]]]),
    "identity of AND": (["AND", ["var", "x"], ["bool", True]], ["var", "x"]),
    "annihilator of AND": (["AND", ["var", "x"], ["bool", False]], ["bool", False]),
    "idempotence of AND": (["AND", ["var", "x"], ["var", "x"]], ["var", "x"]),
    "complement (AND)": (["AND", ["var", "x"], ["NOT", ["var", "x"]]], ["bool", False]),
    "complement (OR)": (["OR", ["var", "x"], ["NOT", ["var", "x"]]], ["bool", True]),
    "double negation": (["NOT", ["NOT", ["var", "x"]]], ["var", "x"]),
    "absorption": (["AND", ["var", "x"], ["OR", ["var", "x"], ["var", "y"]]], ["var", "x"]),
    "De Morgan (AND)": (["NOT", ["AND", ["var", "x"], ["var", "y"]]],
                        ["OR", ["NOT", ["var", "x"]], ["NOT", ["var", "y"]]]),
    "De Morgan (OR)": (["NOT", ["OR", ["var", "x"], ["var", "y"]]],
                       ["AND", ["NOT", ["var", "x"]], ["NOT", ["var", "y"]]]),
    "AND distributes over OR": (["AND", ["var", "x"], ["OR", ["var", "y"], ["var", "z"]]],
                                ["OR", ["AND", ["var", "x"], ["var", "y"]], ["AND", ["var", "x"], ["var", "z"]]]),
    "OR distributes over AND": (["OR", ["var", "x"], ["AND", ["var", "y"], ["var", "z"]]],
                                ["AND", ["OR", ["var", "x"], ["var", "y"]], ["OR", ["var", "x"], ["var", "z"]]]),
    "XOR is associative": (["CMP_NE", ["CMP_NE", ["var", "x"], ["var", "y"]], ["var", "z"]],
                           ["CMP_NE", ["var", "x"], ["CMP_NE", ["var", "y"], ["var", "z"]]]),
    "AND distributes over XOR": (["AND", ["var", "x"], ["CMP_NE", ["var", "y"], ["var", "z"]]],
                                 ["CMP_NE", ["AND", ["var", "x"], ["var", "y"]],
                                  ["AND", ["var", "x"], ["var", "z"]]]),
    "XOR with itself": (["CMP_NE", ["var", "x"], ["var", "x"]], ["bool", False]),
}


def rediscovered(res: dict) -> dict:
    """For each classic law: whether the enumeration found it (kept, or both sides rewrite to one term)."""
    rules = res["laws"]["rules"]
    out = {}
    for name, (l, r) in CLASSIC.items():
        out[name] = rules.normalize(l) == rules.normalize(r)
    return out


def law_text(law) -> str:
    return f"{show_term(law['lhs'])} = {show_term(law['rhs'])}"


def function_cards(res: dict) -> list[dict]:
    out = []
    for f in res["functions"]:
        out.append({"name": f"bit2_{f['name']}", "label": f["name"], "tier": 1, "arity": 2, "table": f["table"],
                    "truth": f["truth"], "depends_on": f["depends_on"], "op_cards": f["op_cards"],
                    "over_op_cards": f["over_op_cards"], "over_sole_gate": f["over_sole_gate"], "post": f["post"],
                    "complete_alone": f["complete_alone"],
                    "statement": f"{f['name']}(x, y): truth {''.join(map(str, f['truth']))} on rows xy=00,01,10,11"
                                 f" = {show_term(f['over_op_cards']['term'])}",
                    "evidence": {"kind": "exhaustive", "rows": 4, "tier": "proved"},
                    "provenance": {"tool": "cardmodel basics bits --save", "engine": "engines/bits.py"}})
    return out


def law_cards(res: dict) -> list[dict]:
    return [{"name": f"bitlaw_{i:04d}", "tier": 1, "lhs": law["lhs"], "rhs": law["rhs"], "size": law["size"],
             "statement": law_text(law), "vars": list(VARS), "evidence": {"kind": "exhaustive", "rows": 8,
                                                                          "tier": "proved"},
             "provenance": {"tool": "cardmodel basics bits --save", "engine": "engines/bits.py"}}
            for i, law in enumerate(res["laws"]["laws"])]
