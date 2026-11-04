"""dimensions — physical dimension as content (docs/GODEL_TARGET.md G13; the Gödel set ``physics``).

The SI base quantities are atoms of the set, of arity 0: a quantity is a leaf of a term. A dimension is a signed
content vector over them: acceleration is {length: 1, time: -2}, a ratio has negative exponents, a square root
halves them (exponents are rationals, kept as integers when they are). The IR's ops act on dimensions through
the model the set card states (its ``model`` block): MUL adds, DIV subtracts, POW scales by its integer exponent,
FSQRT halves, ADD, SUB, MIN and MAX need one dimension and keep it, a comparison needs one dimension and gives
none, EXP, LOG and the trigonometric family need none. That model is a Σ-algebra whose carrier is the content
group (FOUNDATIONS D14: a model is another algebra of the signature): its operations are engines/godel's add, sub
and scale, and nothing here is new algebra. An equation is dimensionally consistent exactly when its two sides
have one dimension, which is equality of content.

Nothing here computes a number. M stays the only numeric meaning of a term (FOUNDATIONS A2); the dimension model
is a second, named model (D9), stated on the set card and read from it, never a private table in this module.

Derived quantities (force, energy, ...) are a carry map from their names to base content. Their images overlap
in support (energy and force share mass, length and time), so the map does not preserve gcd (GodelCore T2): the
base quantities are the free generators, and a derived quantity is a product of them, which is what a
``deprecate`` event records for an atom found to be a product.
"""
from __future__ import annotations

import re
from collections import Counter
from fractions import Fraction

from . import godel as G

SET = "physics"
REGISTRY = "physics_law"
QUANTITIES = ("length", "mass", "time", "current", "temperature", "amount", "luminosity")
ATOMS = tuple(f"quantity/{q}" for q in QUANTITIES)
ACTIONS = ("add", "sub", "same", "scale", "half", "compare", "none", "branches")
_TOKEN = re.compile(r"\s*([*/])?\s*([A-Za-z_][A-Za-z0-9_]*)\s*(?:(?:\^|\*\*)\s*(\(?\s*-?\d+(?:\s*/\s*\d+)?\s*\)?))?\s*")


def atom(q: str) -> str:
    return q if q.startswith("quantity/") else f"quantity/{q}"


def _norm(c) -> Counter:
    """Exponents as integers when they are, zeros dropped (a Counter keeps negatives: ``+c`` would not)."""
    out: Counter = Counter()
    for k, e in c.items():
        f = Fraction(e)
        if f:
            out[k] = int(f) if f.denominator == 1 else f
    return out


def parse(text, derived: dict | None = None) -> Counter:
    """A dimension from text: ``mass*length/time^2``, ``length*time**-2``, ``time^(1/2)``, ``1`` (none); the
    name of a base quantity, or of a derived one when ``derived`` maps names to dimensions."""
    s = str(text).strip()
    if s in ("", "1", "none", "dimensionless"):
        return Counter()
    out: Counter = Counter()
    pos = 0
    for m in _TOKEN.finditer(s):
        if m.start() != pos or m.end() == m.start():
            break
        pos = m.end()
        op, name, exp = m.groups()
        e = Fraction(exp.replace(" ", "").strip("()")) if exp else Fraction(1)
        if op == "/":
            e = -e
        vec = (derived or {}).get(name)
        if vec is None:
            if name not in QUANTITIES:
                raise ValueError(f"{name!r} is not a base quantity or a derived one")
            vec = Counter({atom(name): 1})
        for a, f in vec.items():
            out[a] += e * f
    if pos != len(s):
        raise ValueError(f"cannot read the dimension {text!r} at {s[pos:]!r}")
    return _norm(out)


def text(dim) -> str:
    """A dimension as text that ``parse`` reads back: ``mass*length*time^-2``; ``1`` when none."""
    if not dim:
        return "1"
    order = {a: i for i, a in enumerate(ATOMS)}
    parts = []
    for a, e in sorted(dim.items(), key=lambda kv: (order.get(kv[0], len(order)), kv[0])):
        name = a.split("/", 1)[1] if "/" in a else a
        parts.append(name if e == 1 else f"{name}^{e}")
    return "*".join(parts)


def set_card(ctx):
    return ctx.store.get(f"godel_set/{SET}")


def model_of(ctx) -> dict:
    """The dimension model, as the set card states it: op name -> action."""
    return dict((set_card(ctx) or {}).get("model") or {})


def derived_of(ctx) -> dict[str, Counter]:
    """The derived quantities' carry map: name -> base content."""
    raw = (set_card(ctx) or {}).get("derived") or {}
    return {name: parse(spec) for name, spec in raw.items()}


def name_of(dim, derived: dict[str, Counter] | None = None) -> str | None:
    """The quantity a dimension is, when it has a name: a base quantity, or a derived one."""
    dim = _norm(dim)
    if not dim:
        return "1"
    for a in ATOMS:
        if dim == Counter({a: 1}):
            return a.split("/", 1)[1]
    for name, vec in (derived or {}).items():
        if _norm(vec) == dim:
            return name
    return None


def of(term, env: dict, model: dict, problems: list[str] | None = None, derived: dict | None = None) -> Counter | None:
    """The dimension of a term in the model, or None when it has none (then ``problems`` says where and why,
    naming the op). ``env`` maps a variable to its dimension (a Counter, or text for ``parse``, which may name a
    derived quantity when ``derived`` is given)."""
    problems = [] if problems is None else problems

    def fail(why):
        problems.append(why)
        return None

    def go(t):
        if not (isinstance(t, list) and t):
            return fail(f"not a term: {t!r}")
        head = t[0]
        if head == "var":
            d = env.get(t[1])
            if d is None:
                return fail(f"the variable {t[1]} has no stated dimension")
            try:
                return _norm(parse(d, derived) if isinstance(d, str) else d)
            except ValueError as exc:
                return fail(f"the variable {t[1]}: {exc}")
        if head in ("int", "float", "bool"):
            return Counter()
        if isinstance(head, str) and head.startswith("quantity/") and len(t) == 1:
            return Counter({head: 1})
        action = model.get(head)
        if action is None:
            return fail(f"no dimension rule for {head} (the set card's model does not state one)")
        args = [go(a) for a in t[1:]]
        if any(a is None for a in args):
            return None
        if action == "add":
            return _norm(G.add(*args))
        if action == "sub":
            if len(args) != 2:
                return fail(f"{head}: sub takes two arguments")
            return _norm(G.sub(args[0], args[1]))
        if action in ("same", "compare"):
            if any(a != args[0] for a in args[1:]):
                return fail(f"{head}: {' and '.join(text(a) for a in args)} differ")
            return Counter() if action == "compare" else args[0]
        if action == "scale":
            exp = t[2] if len(t) > 2 else None
            if isinstance(exp, list) and exp and exp[0] in ("int", "float") and Fraction(exp[1]).denominator == 1:
                return _norm(G.scale(args[0], int(Fraction(exp[1]))))
            if not args[0]:
                return Counter()                        # a dimensionless base: any exponent keeps it so
            return fail(f"{head}: a variable exponent needs a dimensionless base, not {text(args[0])}")
        if action == "half":
            return _norm(Counter({k: Fraction(e, 2) for k, e in args[0].items()}))
        if action == "none":
            bad = [text(a) for a in args if a]
            if bad:
                return fail(f"{head} needs dimensionless arguments, not {' and '.join(bad)}")
            return Counter()
        if action == "branches":                        # IF_EXPR: a dimensionless condition, branches alike
            if len(args) != 3 or args[0]:
                return fail(f"{head}: the condition must be dimensionless")
            if args[1] != args[2]:
                return fail(f"{head}: the branches differ, {text(args[1])} and {text(args[2])}")
            return args[1]
        return fail(f"{head}: the set card states an unknown action {action!r} ({', '.join(ACTIONS)})")
    return go(term)


def check_equation(lhs, rhs, env: dict, model: dict, derived: dict | None = None) -> dict:
    """Both sides' dimensions, whether they agree, and the problems found; ``name`` is the dimension's name."""
    problems: list[str] = []
    a, b = of(lhs, env, model, problems, derived), of(rhs, env, model, problems, derived)
    ok = a is not None and b is not None and a == b
    if a is not None and b is not None and a != b:
        problems.append(f"the sides differ: {text(a)} = {text(b)}")
    return {"lhs": a, "rhs": b, "consistent": ok, "problems": problems,
            "dimension": text(a) if ok else None, "name": name_of(a, derived) if ok else None}


def check_law(ctx, card, model: dict | None = None, derived: dict | None = None) -> dict:
    model = model_of(ctx) if model is None else model
    derived = derived_of(ctx) if derived is None else derived
    env = {v: parse(spec, derived) for v, spec in (card.get("dimensions") or {}).items()}
    return {"card": card.qualified, "statement": card.get("statement"),
            **check_equation(card.get("lhs"), card.get("rhs"), env, model, derived)}


def check(ctx) -> dict:
    """The physics set: its atoms in the ledger, its model naming only known actions, every law consistent, and
    whether the derived quantities' carry preserves gcd (it cannot: their supports overlap)."""
    problems: list[str] = []
    card = set_card(ctx)
    if card is None:
        return {"status": "vacuous", "problems": [f"no godel_set/{SET} card"], "laws": {}}
    index = G.index_of(ctx.store)
    for a in ATOMS:
        e = index.get(a)
        if e is None:
            problems.append(f"{a} is not in the ledger")
        elif e.get("set") != SET:
            problems.append(f"{a} entered the ledger with set {e.get('set')}, not {SET}")
        if (card.get("arities") or {}).get(a) != 0:
            problems.append(f"{a}: the set card does not state arity 0")
    model = model_of(ctx)
    for op, action in model.items():
        if action not in ACTIONS:
            problems.append(f"model: {op} -> {action!r} is not an action ({', '.join(ACTIONS)})")
    derived = derived_of(ctx)
    laws = {}
    for law in ctx.store.cards(REGISTRY):
        r = check_law(ctx, law, model, derived)
        laws[law.qualified] = r
        if not r["consistent"]:
            problems.append(f"{law.qualified} ({law.get('statement')}): {'; '.join(r['problems'])}")
    return {"status": "fail" if problems else "pass", "problems": problems, "laws": laws,
            "derived": {k: text(v) for k, v in derived.items()},
            "derived_preserves_gcd": G.preserves_gcd(derived),
            "base_preserves_gcd": G.preserves_gcd({a: Counter({a: 1}) for a in ATOMS})}


__all__ = ["ACTIONS", "ATOMS", "QUANTITIES", "REGISTRY", "SET", "atom", "check", "check_equation", "check_law",
           "derived_of", "model_of", "name_of", "of", "parse", "set_card", "text"]
