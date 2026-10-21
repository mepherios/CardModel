"""logic — rules as cards: "if x, y -> z", evaluated to a fixpoint, with a proof for every fact.

A theory is facts and rules (and constraints). A fact is a ground atom; a
rule derives its head whenever its body holds:

    ancestor(X, Z) <- parent(X, Y), ancestor(Y, Z).

Body literals:

  atom          parent(X, Y)                  joins against known facts
  negation      not parent(X, alice)          closed world, stratified
  test          X + 1 < Y                     any bool IR expression over op cards
  binding       Z = X * 2                     computes a new value (IR expression)
  aggregate     N = count Y : parent(X, Y)    count / sum / min / max over a sub-body, stratified

Arithmetic is the card IR: the same op cards (reference semantics
``ir.eval``) that codegen emits to every language, so "carry" in a rule and
in a compiled function mean the same thing.

Evaluation (``evaluate``): predicates are stratified (Tarjan SCCs; a cycle
through negation or aggregation is rejected with the cycle), then each
stratum runs semi-naive bottom-up to a fixpoint over hash indexes. Every
derived fact keeps its first derivation (rule, bindings, premises). Because
semi-naive works in rounds, the first derivation is a proof of minimum
height. Constraints (rules without a head: ``never: p(X), q(X).``) are
checked last; each violation carries its proof. ``Model.proof`` turns any
fact into a proof tree, and ``emit/lean_logic.py`` turns that tree into a
Lean term the Lean kernel checks.

JSON (card) form: an argument is ``{"var": "X"}`` or a constant (string
symbol, int, float); a literal is ``{"pred", "args"}``, ``{"not": atom}``,
``{"test": expr}``, ``{"bind": "Z", "expr": expr}`` or
``{"agg": fn, "var", "over", "body"}``. Expressions are IR lists with the
extra leaf ``["sym", "alice"]`` for symbols.

Honest limits (L1): terms are constants (symbols, integers, floats): no
function symbols, so no lists or trees as values. Bindings can create new
values, so evaluation has a fact budget (L20) and raises LogicLimit instead
of running forever. Negation and aggregation use the closed world of the
strata below them. Booleans are stored as the symbols true/false (Python
would conflate True with 1).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field

from ..kernel import resources

AGG_FNS = ("count", "sum", "min", "max")
_IDENT = re.compile(r"^[a-z][A-Za-z0-9_]*$")


class LogicError(ValueError):
    pass


class Unsafe(LogicError):
    pass


class NotStratified(LogicError):
    pass


class LogicLimit(LogicError):
    pass


# -- terms and literals --------------------------------------------------------------------------
@dataclass(frozen=True)
class Var:
    name: str

    def __str__(self) -> str:
        return self.name


def const(v):
    """Normalise a constant: bools become the symbols true/false."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (str, int, float)):
        return v
    raise LogicError(f"constant {v!r} is not a symbol or a number")


def term_text(t) -> str:
    if isinstance(t, Var):
        return "_" if re.fullmatch(r"_a?\d+", t.name) else t.name
    if isinstance(t, str):
        return t if _IDENT.match(t) and t not in ("not", "true", "false") or t in ("true", "false") else json.dumps(t)
    return repr(t)


@dataclass(frozen=True)
class Atom:
    pred: str
    args: tuple = ()

    def vars(self) -> set[str]:
        return {a.name for a in self.args if isinstance(a, Var)}

    def ground(self) -> bool:
        return not any(isinstance(a, Var) for a in self.args)

    def __str__(self) -> str:
        return f"{self.pred}({', '.join(term_text(a) for a in self.args)})" if self.args else self.pred


@dataclass(frozen=True)
class Neg:
    atom: Atom

    def vars(self) -> set[str]:
        return self.atom.vars()

    def __str__(self) -> str:
        return f"not {self.atom}"


@dataclass(frozen=True, eq=False)
class Test:
    expr: list

    def vars(self) -> set[str]:
        return expr_vars(self.expr)

    def __str__(self) -> str:
        return expr_text(self.expr)


@dataclass(frozen=True, eq=False)
class Bind:
    var: str
    expr: list

    def vars(self) -> set[str]:
        return expr_vars(self.expr)

    def __str__(self) -> str:
        return f"{self.var} = {expr_text(self.expr)}"


@dataclass(frozen=True, eq=False)
class Agg:
    fn: str
    var: str
    over: str | None
    body: tuple

    def vars(self) -> set[str]:
        out: set[str] = set()
        for lit in self.body:
            out |= lit.vars()
        return out

    def __str__(self) -> str:
        what = f"{self.fn} {self.over}" if self.over else self.fn
        return f"{self.var} = {what} : {', '.join(str(b) for b in self.body)}"


@dataclass(eq=False)
class Rule:
    name: str
    head: Atom | None           # None: a constraint (the body must never hold)
    body: tuple
    card: str | None = None
    line: int | None = None

    def __str__(self) -> str:
        body = ", ".join(str(b) for b in self.body)
        if self.head is None:
            return f"never: {body}."
        return f"{self.head} <- {body}." if body else f"{self.head}."


def expr_vars(e) -> set[str]:
    out: set[str] = set()
    if isinstance(e, list) and e:
        if e[0] == "var":
            out.add(e[1])
        elif e[0] not in ("int", "float", "bool", "sym"):
            for a in e[(2 if e[0] == "CALL" else 1):]:
                out |= expr_vars(a)
    return out


_INFIX = {"ADD": "+", "SUB": "-", "MUL": "*", "DIV": "/", "FLOORDIV": "//", "MOD": "%", "POW": "**",
          "BIT_AND": "&", "BIT_OR": "|", "BIT_XOR": "^", "SHIFT_LEFT": "<<", "SHIFT_RIGHT": ">>",
          "CMP_EQ": "==", "CMP_NE": "!=", "CMP_LT": "<", "CMP_LE": "<=", "CMP_GT": ">", "CMP_GE": ">=",
          "AND": "and", "OR": "or"}
_CALLS = {"ABS": "abs", "MIN": "min", "MAX": "max", "GCD": "gcd", "TO_FLOAT": "float", "TRUNC_INT": "int",
          "POW_MOD": "pow"}


def expr_text(e) -> str:
    """Card-language rendering of an IR expression (the inverse of the language's expression parser)."""
    head = e[0]
    if head == "var":
        return e[1]
    if head == "sym":
        return term_text(e[1])
    if head == "bool":
        return "true" if e[1] else "false"
    if head in ("int", "float"):
        return repr(e[1])
    if head in _INFIX and len(e) == 3:
        return f"({expr_text(e[1])} {_INFIX[head]} {expr_text(e[2])})"
    if head == "NEG":
        return f"(-{expr_text(e[1])})"
    if head == "NOT":
        return f"(not {expr_text(e[1])})"
    if head == "BIT_NOT":
        return f"(~{expr_text(e[1])})"
    if head == "IF_EXPR":
        return f"(if {expr_text(e[1])} then {expr_text(e[2])} else {expr_text(e[3])})"
    if head == "CALL":
        return f"{e[1]}({', '.join(_bare(expr_text(a)) for a in e[2:])})"
    name = _CALLS.get(head, f"op.{head}")
    return f"{name}({', '.join(_bare(expr_text(a)) for a in e[1:])})"


def _bare(s: str) -> str:
    """Drop one pair of outer parentheses when they wrap the whole text."""
    if s.startswith("(") and s.endswith(")"):
        depth = 0
        for i, c in enumerate(s):
            depth += c == "("
            depth -= c == ")"
            if depth == 0 and i < len(s) - 1:
                return s
        return s[1:-1]
    return s


def eval_expr(e, env: dict, ops: dict, call=None):
    """Evaluate an IR expression with the op cards' reference semantics.

    ``call(name, args)`` evaluates ``["CALL", name, ...]`` (functions of a card-language module)."""
    head = e[0]
    if head == "var":
        try:
            return env[e[1]]
        except KeyError:
            raise LogicError(f"variable {e[1]} is unbound") from None
    if head in ("int", "float", "sym"):
        return e[1]
    if head == "bool":
        return bool(e[1])
    if head == "AND":
        return _truth(eval_expr(e[1], env, ops, call)) and _truth(eval_expr(e[2], env, ops, call))
    if head == "OR":
        return _truth(eval_expr(e[1], env, ops, call)) or _truth(eval_expr(e[2], env, ops, call))
    if head == "NOT":
        return not _truth(eval_expr(e[1], env, ops, call))
    if head == "IF_EXPR":
        return eval_expr(e[2] if _truth(eval_expr(e[1], env, ops, call)) else e[3], env, ops, call)
    if head == "CALL":
        if call is None:
            raise LogicError(f"call to {e[1]}() but no functions are in scope")
        return call(e[1], [eval_expr(a, env, ops, call) for a in e[2:]])
    spec = ops.get(head)
    if spec is None or spec.fn is None:
        raise LogicError(f"op {head!r} has no reference semantics (no op card with ir.eval)")
    args = [eval_expr(a, env, ops, call) for a in e[1:]]
    return spec.fn(*args)


def _truth(v) -> bool:
    if v == "true":
        return True
    if v == "false":
        return False
    return bool(v)


# -- JSON (card) form ------------------------------------------------------------------------------
def term_json(t):
    return {"var": t.name} if isinstance(t, Var) else t


def term_from_json(j):
    if isinstance(j, dict):
        if "var" in j:
            return Var(j["var"])
        if "sym" in j:
            return j["sym"]
        raise LogicError(f"bad term {j!r}")
    return const(j)


def atom_json(a: Atom) -> dict:
    return {"pred": a.pred, "args": [term_json(t) for t in a.args]}


def atom_from_json(j) -> Atom:
    return Atom(j["pred"], tuple(term_from_json(t) for t in j.get("args", [])))


def literal_json(lit) -> dict:
    if isinstance(lit, Atom):
        return atom_json(lit)
    if isinstance(lit, Neg):
        return {"not": atom_json(lit.atom)}
    if isinstance(lit, Test):
        return {"test": lit.expr}
    if isinstance(lit, Bind):
        return {"bind": lit.var, "expr": lit.expr}
    if isinstance(lit, Agg):
        return {"agg": lit.fn, "var": lit.var, "over": lit.over, "body": [literal_json(b) for b in lit.body]}
    raise LogicError(f"unknown literal {lit!r}")


def literal_from_json(j):
    if "pred" in j:
        return atom_from_json(j)
    if "not" in j:
        return Neg(atom_from_json(j["not"]))
    if "test" in j:
        return Test(j["test"])
    if "bind" in j:
        return Bind(j["bind"], j["expr"])
    if "agg" in j:
        return Agg(j["agg"], j["var"], j.get("over"), tuple(literal_from_json(b) for b in j["body"]))
    raise LogicError(f"unknown literal {j!r}")


def rule_json(r: Rule) -> dict:
    return {"head": atom_json(r.head) if r.head else None, "body": [literal_json(b) for b in r.body],
            "text": str(r)}


def rule_from_card(card) -> Rule:
    head = atom_from_json(card["head"]) if card.get("head") else None
    return Rule(card.get("label") or card["name"], head, tuple(literal_from_json(b) for b in card.get("body", [])),
                card=f"{card.get('category', 'logic_rule')}/{card['name']}")


# -- programs ------------------------------------------------------------------------------------
@dataclass
class Program:
    rules: list[Rule] = field(default_factory=list)
    facts: list[tuple] = field(default_factory=list)       # (pred, args tuple, source)
    name: str = "theory"

    def add_fact(self, pred: str, args, source: str | None = None) -> None:
        self.facts.append((pred, tuple(const(a) for a in args), source))

    def add_rule(self, rule: Rule) -> None:
        if rule.head is not None and rule.head.ground() and not rule.body:
            self.add_fact(rule.head.pred, rule.head.args, rule.card or rule.name)
        else:
            self.rules.append(rule)

    def predicates(self) -> dict[str, int]:
        """Predicate -> arity; conflicting arities are reported by ``check``."""
        out: dict[str, int] = {}
        for pred, args, _ in self.facts:
            out.setdefault(pred, len(args))
        for r in self.rules:
            for a in _atoms_of_rule(r):
                out.setdefault(a.pred, len(a.args))
        return out

    def idb(self) -> set[str]:
        return {r.head.pred for r in self.rules if r.head is not None}

    def check(self) -> list[str]:
        """Static problems: arity clashes, unsafe variables, recursion through negation."""
        problems = []
        arity: dict[str, set[int]] = defaultdict(set)
        for pred, args, _ in self.facts:
            arity[pred].add(len(args))
        for r in self.rules:
            for a in _atoms_of_rule(r):
                arity[a.pred].add(len(a.args))
        for pred, ns in sorted(arity.items()):
            if len(ns) > 1:
                problems.append(f"predicate {pred} used with arities {sorted(ns)}")
        for r in self.rules:
            try:
                _plan(r.body, set(), None, r)
                if r.head is not None:
                    _head_safe(r)
            except Unsafe as exc:
                problems.append(str(exc))
            for lit in r.body:
                if isinstance(lit, Agg) and lit.fn not in AGG_FNS:
                    problems.append(f"rule {r.name}: unknown aggregate {lit.fn!r}")
        try:
            strata(self)
        except NotStratified as exc:
            problems.append(str(exc))
        return problems


def _atoms_of_rule(r: Rule):
    if r.head is not None:
        yield r.head
    for lit in r.body:
        yield from _atoms_of_lit(lit)


def _atoms_of_lit(lit):
    if isinstance(lit, Atom):
        yield lit
    elif isinstance(lit, Neg):
        yield lit.atom
    elif isinstance(lit, Agg):
        for b in lit.body:
            yield from _atoms_of_lit(b)


def _head_safe(r: Rule) -> None:
    bound = _bound_by(r.body)
    free = r.head.vars() - bound
    if free:
        raise Unsafe(f"rule {r.name}: head variable(s) {', '.join(sorted(free))} not bound by a positive body "
                     f"literal or a binding")


def _bound_by(body) -> set[str]:
    out: set[str] = set()
    for lit in body:
        if isinstance(lit, Atom):
            out |= lit.vars()
        elif isinstance(lit, (Bind, Agg)):
            out.add(lit.var)
    return out


# -- stratification -------------------------------------------------------------------------------
def dependency_edges(program: Program) -> list[tuple[str, str, bool]]:
    """(body pred, head pred, negative?) for every rule; constraints use the pseudo-head ``false``."""
    edges = []
    for r in program.rules:
        h = r.head.pred if r.head else "false"
        for lit in r.body:
            if isinstance(lit, Atom):
                edges.append((lit.pred, h, False))
            elif isinstance(lit, Neg):
                edges.append((lit.atom.pred, h, True))
            elif isinstance(lit, Agg):
                for a in lit.body:
                    for at in _atoms_of_lit(a):
                        edges.append((at.pred, h, True))
    return edges


def strata(program: Program) -> list[list[str]]:
    """Predicates grouped into SCCs in dependency order. Raises NotStratified on a negative cycle."""
    preds = set(program.predicates()) | {"false"}
    edges = dependency_edges(program)
    succ: dict[str, list[str]] = defaultdict(list)
    for a, b, _ in edges:
        succ[a].append(b)
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = [0]

    def strong(v):  # iterative Tarjan (deep recursion-free)
        work = [(v, iter(succ[v]))]
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        while work:
            node, it = work[-1]
            advanced = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, iter(succ[w])))
                    advanced = True
                    break
                if w in on:
                    low[node] = min(low[node], index[w])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                sccs.append(sorted(comp))

    for p in sorted(preds):
        if p not in index:
            strong(p)
    sccs.reverse()                                   # Tarjan emits sinks first
    comp_of = {p: i for i, comp in enumerate(sccs) for p in comp}
    for a, b, neg in edges:
        if neg and comp_of[a] == comp_of[b]:
            cyc = " -> ".join(sccs[comp_of[a]])
            raise NotStratified(f"recursion through negation or aggregation: {a} -> {b} inside the cycle {{{cyc}}}")
    return sccs


# -- planning (join order) ------------------------------------------------------------------------
def _plan(body, bound: set[str], delta_pos: int | None, rule: Rule | None) -> list:
    """Order the body so every literal runs with its inputs bound. Steps keep the original index (for proofs)."""
    remaining = list(enumerate(body))
    bound = set(bound)
    steps = []
    rname = rule.name if rule else "query"

    def take(i, lit, use_delta=False):
        nonlocal bound
        if isinstance(lit, Atom):
            key_cols, key_terms, out_cols = [], [], []
            seen_here: set[str] = set()
            for c, t in enumerate(lit.args):
                if isinstance(t, Var):
                    if t.name in bound and t.name not in seen_here:
                        key_cols.append(c)
                        key_terms.append(t)
                    else:
                        out_cols.append((c, t.name))
                        seen_here.add(t.name)
                else:
                    key_cols.append(c)
                    key_terms.append(t)
            steps.append(("atom", i, lit.pred, tuple(key_cols), tuple(key_terms), tuple(out_cols), use_delta, lit))
            bound |= lit.vars()
        elif isinstance(lit, Neg):
            key_cols, key_terms, local = [], [], {}
            for c, t in enumerate(lit.atom.args):
                if isinstance(t, Var) and t.name not in bound:
                    local.setdefault(t.name, []).append(c)      # existential: "no fact matches, for any value"
                else:
                    key_cols.append(c)
                    key_terms.append(t)
            same = tuple(tuple(cs) for cs in local.values() if len(cs) > 1)
            steps.append(("neg", i, lit.atom, tuple(key_cols), tuple(key_terms), same))
        elif isinstance(lit, Test):
            steps.append(("test", i, lit.expr, lit))
        elif isinstance(lit, Bind):
            if lit.var in bound:
                steps.append(("test", i, ["CMP_EQ", ["var", lit.var], lit.expr], lit))
            else:
                steps.append(("bind", i, lit.var, lit.expr, lit))
                bound.add(lit.var)
        elif isinstance(lit, Agg):
            sub = _plan(lit.body, bound & lit.vars(), None, rule)
            steps.append(("agg", i, lit, sub))
            bound.add(lit.var)
        else:
            raise LogicError(f"unknown literal {lit!r}")

    if delta_pos is not None:
        for k, (i, lit) in enumerate(remaining):
            if i == delta_pos:
                take(i, lit, use_delta=True)
                remaining.pop(k)
                break
    while remaining:
        picked = None
        for k, (i, lit) in enumerate(remaining):          # filters and bindings as soon as they can run
            if isinstance(lit, Test) and lit.vars() <= bound:
                picked = k
                break
            if isinstance(lit, Neg) and _shared(lit, body, rule) <= bound:
                picked = k
                break
            if isinstance(lit, Bind) and lit.vars() <= bound:
                picked = k
                break
            if isinstance(lit, Agg) and _agg_inputs(lit, body) <= bound:
                picked = k
                break
        if picked is None:
            best, best_score = None, None
            for k, (i, lit) in enumerate(remaining):
                if isinstance(lit, Atom):
                    score = sum(1 for t in lit.args if not isinstance(t, Var) or t.name in bound)
                    if best_score is None or score > best_score:
                        best, best_score = k, score
            picked = best
        if picked is None:
            i, lit = remaining[0]
            need = (_agg_inputs(lit, body) if isinstance(lit, Agg) else
                    _shared(lit, body, rule) if isinstance(lit, Neg) else lit.vars()) - bound
            raise Unsafe(f"rule {rname}: `{lit}` needs {', '.join(sorted(need))} bound by a positive literal first")
        i, lit = remaining.pop(picked)
        take(i, lit)
    return steps


def _shared(neg: Neg, body, rule: Rule | None) -> set[str]:
    """Variables of a negated atom that occur elsewhere (body or head) must be bound; the rest are existential."""
    outside: set[str] = set(rule.head.vars()) if rule is not None and rule.head is not None else set()
    for lit in body:
        if lit is neg:
            continue
        outside |= lit.vars() | ({lit.var} if isinstance(lit, (Bind, Agg)) else set())
    return neg.vars() & outside


def _agg_inputs(agg: Agg, body) -> set[str]:
    """Variables of the aggregate's sub-body that also occur elsewhere in the rule: the grouping keys."""
    outside: set[str] = set()
    for lit in body:
        if lit is agg:
            continue
        outside |= lit.vars() | ({lit.var} if isinstance(lit, (Bind, Agg)) else set())
    return (agg.vars() & outside) - {agg.var}


# -- the database ---------------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.rel: dict[str, set] = defaultdict(set)
        self._idx: dict[str, dict] = defaultdict(dict)
        self.count = 0

    def add(self, pred: str, tup: tuple) -> bool:
        r = self.rel[pred]
        if tup in r:
            return False
        r.add(tup)
        self.count += 1
        for cols, ix in self._idx[pred].items():
            ix.setdefault(tuple(tup[c] for c in cols), []).append(tup)
        return True

    def lookup(self, pred: str, cols: tuple, key: tuple):
        if not cols:
            return self.rel.get(pred, ())
        ix = self._idx[pred].get(cols)
        if ix is None:
            ix = {}
            for t in self.rel.get(pred, ()):
                ix.setdefault(tuple(t[c] for c in cols), []).append(t)
            self._idx[pred][cols] = ix
        return ix.get(key, ())

    def __contains__(self, item) -> bool:
        pred, tup = item
        return tup in self.rel.get(pred, ())


# -- evaluation -----------------------------------------------------------------------------------
class _Solver:
    def __init__(self, db: DB, ops: dict, call=None):
        self.db = db
        self.ops = ops
        self.call = call

    def solve(self, steps, env: dict, delta=None, rule_name: str = "query"):
        """Yield (env, premises) for every solution; premises are (body index, evidence) pairs."""
        trail: list = []
        yield from self._go(steps, 0, env, trail, delta, rule_name)

    def _go(self, steps, i, env, trail, delta, rname):
        if i == len(steps):
            yield env, list(trail)
            return
        st = steps[i]
        kind = st[0]
        if kind == "atom":
            _, pos, pred, key_cols, key_terms, out_cols, use_delta, _lit = st
            key = tuple(env[t.name] if isinstance(t, Var) else t for t in key_terms)
            if use_delta:
                rows = [r for r in delta if all(r[c] == k for c, k in zip(key_cols, key))]
            else:
                rows = self.db.lookup(pred, key_cols, key)
            for row in rows:
                newly = []
                ok = True
                for c, name in out_cols:
                    v = row[c]
                    if name in env:
                        if env[name] != v:
                            ok = False
                            break
                    else:
                        env[name] = v
                        newly.append(name)
                if ok:
                    trail.append((pos, ("fact", pred, row)))
                    yield from self._go(steps, i + 1, env, trail, delta, rname)
                    trail.pop()
                for n in newly:
                    del env[n]
        elif kind == "neg":
            _, pos, atom, key_cols, key_terms, same = st
            key = tuple(env[t.name] if isinstance(t, Var) else t for t in key_terms)
            if len(key_cols) == len(atom.args):
                found = key in self.db.rel.get(atom.pred, ())
            else:
                found = any(all(len({row[c] for c in cs}) == 1 for cs in same)
                            for row in self.db.lookup(atom.pred, key_cols, key))
            if not found:
                pattern = tuple(env[t.name] if isinstance(t, Var) and t.name in env else t for t in atom.args)
                trail.append((pos, ("absent", atom.pred, pattern)))
                yield from self._go(steps, i + 1, env, trail, delta, rname)
                trail.pop()
        elif kind == "test":
            _, pos, expr, lit = st
            if _truth(self._eval(expr, env, rname, lit)):
                trail.append((pos, ("test", lit, _snapshot(lit, env))))
                yield from self._go(steps, i + 1, env, trail, delta, rname)
                trail.pop()
        elif kind == "bind":
            _, pos, var, expr, lit = st
            v = self._eval(expr, env, rname, lit)
            v = const(v) if isinstance(v, bool) else v
            env[var] = v
            trail.append((pos, ("bind", lit, _snapshot(lit, env), v)))
            yield from self._go(steps, i + 1, env, trail, delta, rname)
            trail.pop()
            del env[var]
        elif kind == "agg":
            _, pos, agg, sub = st
            sols = set()
            vals = []
            names = sorted(agg.vars())
            for e2, _prem in self.solve(sub, dict(env), None, rname):
                key = tuple(e2.get(n) for n in names)
                if key not in sols:
                    sols.add(key)
                    if agg.over:
                        vals.append(e2[agg.over])
            if agg.fn == "count":
                v = len(sols)
            elif not vals:
                if agg.fn == "sum":
                    v = 0
                else:
                    return                                  # min/max over nothing: no value, the literal fails
            else:
                v = {"sum": sum, "min": min, "max": max}[agg.fn](vals)
            if agg.var in env:
                if env[agg.var] != v:
                    return
                trail.append((pos, ("agg", agg, v, len(sols))))
                yield from self._go(steps, i + 1, env, trail, delta, rname)
                trail.pop()
                return
            env[agg.var] = v
            trail.append((pos, ("agg", agg, v, len(sols))))
            yield from self._go(steps, i + 1, env, trail, delta, rname)
            trail.pop()
            del env[agg.var]
        else:
            raise LogicError(f"bad plan step {kind}")

    def _eval(self, expr, env, rname, lit):
        try:
            return eval_expr(expr, env, self.ops, self.call)
        except LogicError:
            raise
        except (ArithmeticError, ValueError, TypeError) as exc:
            shown = {k: env[k] for k in sorted(expr_vars(expr)) if k in env}
            raise LogicError(f"rule {rname}: `{lit}` failed at {shown}: {type(exc).__name__}: {exc}") from None


def _snapshot(lit, env) -> dict:
    return {k: env[k] for k in sorted(lit.vars()) if k in env}


@dataclass
class Model:
    program: Program
    db: DB
    why: dict
    violations: list
    stats: dict
    ops: dict
    strata: list
    call: object = None

    def facts(self, pred: str) -> list[tuple]:
        return sorted(self.db.rel.get(pred, ()), key=_sort_key)

    def holds(self, pred: str, args) -> bool:
        return tuple(const(a) for a in args) in self.db.rel.get(pred, ())

    def query(self, literals, limit: int | None = None) -> list[dict]:
        steps = _plan(tuple(literals), set(), None, None)
        out, seen = [], set()
        names = sorted(set().union(*(lit.vars() | ({lit.var} if isinstance(lit, (Bind, Agg)) else set())
                                     for lit in literals)) if literals else set())
        for env, _ in _Solver(self.db, self.ops, self.call).solve(steps, {}):
            row = {n: env[n] for n in names if n in env}
            key = tuple(sorted(row.items(), key=lambda kv: kv[0]))
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
            if limit and len(out) >= limit:
                break
        return out

    def proof(self, pred: str, args, _depth: int = 0) -> dict:
        tup = tuple(const(a) for a in args)
        fact = Atom(pred, tup)
        w = self.why.get((pred, tup))
        if w is None:
            raise LogicError(f"{fact} does not hold")
        if w[0] == "given":
            return {"fact": str(fact), "pred": pred, "args": list(tup), "by": "given", "source": w[1]}
        _, rule, env, premises = w
        kids = []
        for _pos, ev in premises:
            kids.append(self._premise(ev, _depth))
        return {"fact": str(fact), "pred": pred, "args": list(tup), "by": rule.name, "rule": str(rule),
                "card": rule.card, "bindings": dict(env), "premises": kids}

    def _premise(self, ev, depth):
        kind = ev[0]
        if kind == "fact":
            return self.proof(ev[1], ev[2], depth + 1)
        if kind == "absent":
            return {"absent": str(Atom(ev[1], ev[2])), "pred": ev[1],
                    "args": [term_json(a) for a in ev[2]]}
        if kind == "test":
            return {"test": str(ev[1]), "expr": ev[1].expr, "at": ev[2]}
        if kind == "bind":
            return {"bind": str(ev[1]), "var": ev[1].var, "expr": ev[1].expr, "at": ev[2], "value": ev[3]}
        if kind == "agg":
            return {"agg": str(ev[1]), "value": ev[2], "solutions": ev[3]}
        raise LogicError(f"bad premise {ev!r}")

    def explain(self, pred: str, args) -> str:
        return proof_text(self.proof(pred, args))


def proof_text(p: dict, indent: int = 0) -> str:
    pad = "  " * indent
    if "absent" in p:
        return f"{pad}not {p['absent']}   (closed world: no such fact)"
    if "test" in p:
        return f"{pad}{p['test']}   with {p['at']}"
    if "bind" in p:
        return f"{pad}{p['bind']}   = {p['value']!r} with {p['at']}"
    if "agg" in p:
        return f"{pad}{p['agg']}   = {p['value']!r} over {p['solutions']} solution(s)"
    if p["by"] == "given":
        return f"{pad}{p['fact']}   [given{': ' + str(p['source']) if p.get('source') else ''}]"
    lines = [f"{pad}{p['fact']}   [by {p['by']}: {p['rule']}]"]
    for k in p["premises"]:
        lines.append(proof_text(k, indent + 1))
    return "\n".join(lines)


def proof_stats(p: dict) -> dict:
    """Height and size of a proof tree (number of rule applications and leaves)."""
    if "premises" not in p:
        return {"height": 0, "steps": 0, "leaves": 1}
    kids = [proof_stats(k) for k in p["premises"]]
    return {"height": 1 + max((k["height"] for k in kids), default=0), "steps": 1 + sum(k["steps"] for k in kids),
            "leaves": sum(k["leaves"] for k in kids) or 1}


def _sort_key(t):
    return tuple((0, x) if isinstance(x, (int, float)) else (1, str(x)) for x in t)


def evaluate(program: Program, ops: dict, max_facts: int = 400_000, max_rounds: int = 100_000,
             call=None) -> Model:
    """Least model of a stratified program, with first-derivation provenance and constraint violations."""
    problems = program.check()
    if problems:
        raise LogicError("; ".join(problems))
    comps = strata(program)
    db = DB()
    why: dict = {}
    for pred, args, source in program.facts:
        if db.add(pred, args):
            why[(pred, args)] = ("given", source)
    rules_by_head: dict[str, list[Rule]] = defaultdict(list)
    constraints = []
    for r in program.rules:
        if r.head is None:
            constraints.append(r)
        else:
            rules_by_head[r.head.pred].append(r)
    solver = _Solver(db, ops, call)
    rounds = 0
    derivations = 0
    plans: dict = {}

    def plan(rule, pos):
        k = (id(rule), pos)
        if k not in plans:
            plans[k] = _plan(rule.body, set(), pos, rule)
        return plans[k]

    def fire(rule, steps, delta, pending):
        nonlocal derivations
        head = rule.head
        for env, premises in solver.solve(steps, {}, delta, rule.name):
            tup = tuple(env[t.name] if isinstance(t, Var) else t for t in head.args)
            if tup in db.rel.get(head.pred, ()) or (head.pred, tup) in pending:
                continue
            premises.sort(key=lambda pe: pe[0])
            pending[(head.pred, tup)] = ("rule", rule, {k: env[k] for k in sorted(env)}, premises)
            derivations += 1

    for comp in comps:
        comp_set = set(comp)
        rules = [r for p in comp for r in rules_by_head.get(p, [])]
        if not rules:
            continue
        pending: dict = {}
        for r in rules:
            fire(r, plan(r, None), None, pending)
        delta = _commit(db, why, pending, max_facts)
        while delta:
            rounds += 1
            if rounds > max_rounds:
                raise LogicLimit(f"more than {max_rounds} rounds (raise max_rounds or check for unbounded arithmetic)")
            resources.guard("logic evaluation")
            pending = {}
            for r in rules:
                for pos, lit in enumerate(r.body):
                    if isinstance(lit, Atom) and lit.pred in comp_set and delta.get(lit.pred):
                        fire(r, plan(r, pos), delta[lit.pred], pending)
            delta = _commit(db, why, pending, max_facts)
    model = Model(program, db, why, [], {}, ops, comps, call)
    for c in constraints:
        for env, premises in solver.solve(plan(c, None), {}, None, c.name):
            premises.sort(key=lambda pe: pe[0])
            model.violations.append({"constraint": c.name, "rule": str(c), "card": c.card,
                                     "bindings": {k: env[k] for k in sorted(env)},
                                     "premises": [model._premise(ev, 0) for _p, ev in premises]})
    violations = model.violations
    model.stats = {"facts": db.count, "given": sum(1 for w in why.values() if w[0] == "given"),
             "derived": sum(1 for w in why.values() if w[0] == "rule"), "rules": len(program.rules),
             "rounds": rounds, "derivations": derivations, "strata": len([c for c in comps if c != ["false"]]),
             "violations": len(violations)}
    return model


def _commit(db: DB, why: dict, pending: dict, max_facts: int) -> dict:
    delta: dict[str, list] = defaultdict(list)
    for (pred, tup), w in pending.items():
        if db.add(pred, tup):
            why[(pred, tup)] = w
            delta[pred].append(tup)
    if db.count > max_facts:
        raise LogicLimit(f"more than {max_facts} facts (L20 budget); a rule probably creates values without bound")
    return delta


# -- theories as cards ------------------------------------------------------------------------------
def program_from_store(store, theory: str, _seen: set | None = None) -> Program:
    """Facts and rules of a theory card and the theories it imports (cards: theory, logic_rule, fact)."""
    seen = _seen if _seen is not None else set()
    prog = Program(name=theory)
    if theory in seen:
        return prog
    seen.add(theory)
    card = store.get(f"theory/{theory}")
    if card is None:
        raise LogicError(f"no theory card {theory!r}")
    for imp in card.get("imports") or []:
        sub = program_from_store(store, imp, seen)
        prog.rules.extend(sub.rules)
        prog.facts.extend(sub.facts)
    for rc in store.cards("logic_rule"):
        if rc.get("theory") == theory:
            prog.rules.append(rule_from_card(rc))
    for fc in store.cards("fact"):
        if fc.get("theory") == theory:
            prog.add_fact(fc["pred"], fc.get("args", []), f"fact/{fc.name}")
    return prog


__all__ = ["Agg", "Atom", "Bind", "DB", "LogicError", "LogicLimit", "Model", "Neg", "NotStratified", "Program",
           "Rule", "Test", "Unsafe", "Var", "const", "eval_expr", "evaluate", "expr_text", "expr_vars",
           "program_from_store", "proof_stats", "proof_text", "rule_from_card", "rule_json", "strata", "term_text"]
