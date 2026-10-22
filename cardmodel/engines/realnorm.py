"""realnorm — a canonical form for terms over the real numbers (the semantic core's decided fragment).

A term's real view reads it over ℝ: rounding to binary32 (F32) and int -> float conversion (TO_FLOAT) are the
identity there. Its normal form is a polynomial with exact rational coefficients over *atoms*: variables, and
applications of every other operation (SIN, FSQRT, IF_EXPR, MIN, comparisons, ...) whose arguments are themselves
in normal form. ADD, SUB, NEG and MUL are expanded and collected; DIV by a constant is a rational coefficient, DIV
by a monomial is a negative exponent, DIV by anything else is the inverse of that polynomial as an atom; POW with a
small integer exponent is repeated multiplication. Commutative atoms (MIN, MAX, AND, OR, CMP_EQ, CMP_NE) sort their
arguments; a comparison becomes ``p REL 0`` with p scaled so its leading coefficient is 1 (scaling by a negative
number flips the relation); NOT of a comparison is the opposite relation; odd functions (SIN, TAN, ASIN, ATAN,
SINH, TANH, CBRT) take a positive leading coefficient out as a sign, even ones (COS, COSH, ABS) drop it.

Two terms with the same normal form are equal as real functions wherever both are defined: this decides equality
for the polynomial fragment with uninterpreted atoms (a commutative ring with congruence), and is sound beyond it.
``render`` turns a normal form back into a term (monomials by degree, then by their atoms), so the canonical term,
its hash and its Gödel content are functions of the normal form only.

Honest limits (L1): over ℝ, not IEEE floats (a float program is an action of this truth, and its distance from it
is what a witness measures); identities between atoms beyond those above (sin² + cos² = 1, sqrt(x)² = x for x >= 0,
(x+y)/(x+y) = 1) are not used, so equal terms may keep different normal forms; expansion is bounded (MAX_TERMS), and
a product past the bound stays an atom.
"""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction

LEAVES = ("var", "int", "float", "bool")
ERASED = ("F32", "TO_FLOAT")                       # the identity over ℝ
COMMUTATIVE = ("MIN", "MAX", "AND", "OR", "CMP_EQ", "CMP_NE", "FMIN", "FMAX", "HYPOT")
ODD = ("SIN", "TAN", "ASIN", "ATAN", "SINH", "TANH", "CBRT")
EVEN = ("COS", "COSH", "ABS")
FLIP = {"CMP_LT": "CMP_GT", "CMP_GT": "CMP_LT", "CMP_LE": "CMP_GE", "CMP_GE": "CMP_LE", "CMP_EQ": "CMP_EQ",
        "CMP_NE": "CMP_NE"}
NEGATE = {"CMP_LT": "CMP_GE", "CMP_GE": "CMP_LT", "CMP_GT": "CMP_LE", "CMP_LE": "CMP_GT", "CMP_EQ": "CMP_NE",
          "CMP_NE": "CMP_EQ"}
MAX_TERMS = 512
MAX_POW = 8


class Poly:
    """sum of coeff * prod(atom ** exp); ``terms``: {monomial: Fraction}, a monomial a sorted tuple of
    (atom key, exponent)."""
    __slots__ = ("terms",)

    def __init__(self, terms=None):
        self.terms = {m: c for m, c in (terms or {}).items() if c != 0}

    @classmethod
    def const(cls, c) -> Poly:
        return cls({(): Fraction(c)})

    @classmethod
    def atom(cls, key: str, exp: int = 1) -> Poly:
        return cls({((key, exp),): Fraction(1)})

    def is_const(self) -> bool:
        return all(m == () for m in self.terms)

    def value(self) -> Fraction:
        return self.terms.get((), Fraction(0))

    def __add__(self, o: Poly) -> Poly:
        out = dict(self.terms)
        for m, c in o.terms.items():
            out[m] = out.get(m, Fraction(0)) + c
        return Poly(out)

    def scale(self, k: Fraction) -> Poly:
        return Poly({m: c * k for m, c in self.terms.items()})

    def __mul__(self, o: Poly) -> Poly | None:
        if len(self.terms) * len(o.terms) > MAX_TERMS:
            return None
        out: dict = {}
        for m1, c1 in self.terms.items():
            for m2, c2 in o.terms.items():
                m = _mono_mul(m1, m2)
                out[m] = out.get(m, Fraction(0)) + c1 * c2
        return Poly(out)

    def ordered(self) -> list:
        return sorted(self.terms.items(), key=lambda mc: _mono_order(mc[0]))

    def leading(self) -> Fraction:
        return self.ordered()[0][1] if self.terms else Fraction(0)

    def monomial(self):
        """(coefficient, monomial) when this is one monomial, else None."""
        if len(self.terms) == 1:
            m, c = next(iter(self.terms.items()))
            return c, m
        return None


def _mono_mul(a: tuple, b: tuple) -> tuple:
    exps: dict = dict(a)
    for k, e in b:
        exps[k] = exps.get(k, 0) + e
    return tuple(sorted((k, e) for k, e in exps.items() if e != 0))


def _mono_order(m: tuple):
    deg = sum(abs(e) for _k, e in m)
    return (-deg, [(k, -e) for k, e in m])


def key(term) -> str:
    return json.dumps(term, separators=(",", ":"), sort_keys=False)


class Normalizer:
    """Normalizes terms; ``atoms`` maps an atom key back to its (normalized) term for rendering."""

    def __init__(self):
        self.atoms: dict[str, list] = {}
        self.memo: dict[int, tuple] = {}

    # -- numbers ------------------------------------------------------------------------------------------------
    def poly(self, t) -> Poly:
        if isinstance(t, list) and t and t[0] in ("int", "float"):
            v = t[1]
            if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
                return self._atom(t)
            return Poly.const(Fraction(v))
        if not isinstance(t, list) or not t:
            raise ValueError(f"not a term: {t!r}")
        if t[0] == "var" or t[0] == "bool":
            return self._atom(t)
        hit = self.memo.get(id(t))
        if hit is not None and hit[0] is t:            # shared subterms are normalized once (the term is a DAG)
            return hit[1]
        out = self._poly(t)
        self.memo[id(t)] = (t, out)
        return out

    def _poly(self, t) -> Poly:
        head, args = t[0], t[1:]
        if head in ERASED and len(args) == 1:
            return self.poly(args[0])
        if head == "ADD":
            return self.poly(args[0]) + self.poly(args[1])
        if head == "SUB":
            return self.poly(args[0]) + self.poly(args[1]).scale(Fraction(-1))
        if head == "NEG":
            return self.poly(args[0]).scale(Fraction(-1))
        if head == "MUL":
            a, b = self.poly(args[0]), self.poly(args[1])
            got = a * b
            return got if got is not None else self._opaque_product(a, b)
        if head == "DIV":
            return self._div(self.poly(args[0]), self.poly(args[1]))
        if head == "POW" and len(args) == 2 and isinstance(args[1], list) and args[1][0] == "int" \
                and abs(args[1][1]) <= MAX_POW:
            n = args[1][1]
            base = self.poly(args[0])
            acc = Poly.const(1)
            for _ in range(abs(n)):
                nxt = acc * base
                if nxt is None:
                    return self._atom(["POW", self.render(base), args[1]])
                acc = nxt
            return acc if n >= 0 else self._div(Poly.const(1), acc)
        return self._atom(self._normalize_atom(head, args))

    def _div(self, a: Poly, b: Poly) -> Poly:
        if b.is_const():
            v = b.value()
            if v == 0:
                return self._atom(["DIV", self.render(a), self.render(b)])
            return a.scale(1 / v)
        mono = b.monomial()
        if mono is not None:
            c, m = mono
            inv = Poly({tuple(sorted((k, -e) for k, e in m)): 1 / c})
            got = a * inv
            return got if got is not None else self._opaque_product(a, inv)
        # the inverse of a polynomial: an atom (scaled to a monic denominator, so k/(2x+2y) == (k/2)/(x+y))
        lead = b.leading()
        bn = b.scale(1 / lead)
        k = self._intern(["DIV", ["int", 1], self.render(bn)])
        got = a * Poly.atom(k)
        return (got if got is not None else self._opaque_product(a, Poly.atom(k))).scale(1 / lead)

    def _opaque_product(self, a: Poly, b: Poly) -> Poly:
        ra, rb = self.render(a), self.render(b)
        return self._atom(["MUL", *sorted([ra, rb], key=key)])

    # -- atoms --------------------------------------------------------------------------------------------------
    def _intern(self, term) -> str:
        k = key(term)
        self.atoms.setdefault(k, term)
        return k

    def _atom(self, term) -> Poly:
        return Poly.atom(self._intern(term))

    def _normalize_atom(self, head: str, args: list) -> list:
        if head in ("CMP_LT", "CMP_GT", "CMP_LE", "CMP_GE", "CMP_EQ", "CMP_NE") and len(args) == 2:
            return self._compare(head, self.poly(args[0]) + self.poly(args[1]).scale(Fraction(-1)))
        if head == "NOT" and len(args) == 1:
            inner = self.boolean(args[0])
            if isinstance(inner, list) and inner and inner[0] in NEGATE:
                return [NEGATE[inner[0]], *inner[1:]]
            if isinstance(inner, list) and inner and inner[0] == "NOT":
                return inner[1]
            return ["NOT", inner]
        if head in ("AND", "OR"):
            items = []
            for a in args:
                b = self.boolean(a)
                items += b[1:] if isinstance(b, list) and b and b[0] == head else [b]
            uniq = sorted({key(x): x for x in items}.values(), key=key)
            return uniq[0] if len(uniq) == 1 else [head, *uniq]
        if head == "IF_EXPR" and len(args) == 3:
            c = self.boolean(args[0])
            a, b = self.render(self.poly(args[1])), self.render(self.poly(args[2]))
            if isinstance(c, list) and c and c[0] == "NOT":
                c, a, b = c[1], b, a
            if c == ["bool", True]:
                return a
            if c == ["bool", False]:
                return b
            return ["IF_EXPR", c, a, b]
        if head in ODD + EVEN and len(args) == 1:
            p = self.poly(args[0])
            if p.terms and p.leading() < 0:
                inner = self.render(p.scale(Fraction(-1)))
                return ["NEG", [head, inner]] if head in ODD else [head, inner]
            return [head, self.render(p)]
        if head in COMMUTATIVE:
            items = [self.boolean(a) if head in ("AND", "OR") else self.render(self.poly(a)) for a in args]
            return [head, *sorted(items, key=key)]
        return [head, *[self._child(a) for a in args]]

    def _child(self, a):
        if isinstance(a, list) and a and a[0] in ("var", "int", "float", "bool"):
            return self.render(self.poly(a)) if a[0] in ("int", "float") else a
        if isinstance(a, (str, int, float)):
            return a
        try:
            return self.render(self.poly(a))
        except ValueError:
            return a

    def _compare(self, rel: str, p: Poly):
        if p.is_const():
            v = p.value()
            return ["bool", {"CMP_LT": v < 0, "CMP_GT": v > 0, "CMP_LE": v <= 0, "CMP_GE": v >= 0, "CMP_EQ": v == 0,
                             "CMP_NE": v != 0}[rel]]
        lead = p.leading()
        if lead < 0:                           # p REL 0  is  (-p) FLIP(REL) 0: the leading coefficient is made 1
            rel = FLIP[rel]
        p = p.scale(1 / lead)
        return [rel, self.render(p), ["int", 0]]

    def boolean(self, t):
        """A condition's canonical term."""
        if isinstance(t, list) and t and t[0] == "bool":
            return t
        if isinstance(t, list) and t and t[0] in ("CMP_LT", "CMP_GT", "CMP_LE", "CMP_GE", "CMP_EQ", "CMP_NE", "AND",
                                                  "OR", "NOT", "IF_EXPR"):
            r = self._normalize_atom(t[0], t[1:])
            return r
        return self.render(self.poly(t))

    # -- back to a term -----------------------------------------------------------------------------------------
    def render(self, p: Poly):
        if not p.terms:
            return ["int", 0]
        out = None
        for m, c in p.ordered():
            mono = self._render_mono(m)
            if mono is None:
                piece, neg = _num(abs(c)), c < 0
            elif abs(c) == 1:
                piece, neg = mono, c < 0
            else:
                piece, neg = ["MUL", _num(abs(c)), mono], c < 0
            if out is None:
                out = ["NEG", piece] if neg else piece
            else:
                out = ["SUB" if neg else "ADD", out, piece]
        return out

    def _render_mono(self, m: tuple):
        num, den = [], []
        for k, e in m:
            base = self.atoms[k]
            (num if e > 0 else den).extend([base] * abs(e))
        if not num and not den:
            return None
        top = _product(num) if num else ["int", 1]
        return top if not den else ["DIV", top, _product(den)]


def _product(items: list):
    out = items[0]
    for x in items[1:]:
        out = ["MUL", out, x]
    return out


def _num(c: Fraction):
    if c.denominator == 1:
        return ["int", int(c)]
    return ["DIV", ["int", c.numerator], ["int", c.denominator]]


def canonical(term, normalizer: Normalizer | None = None):
    """The canonical term of ``term`` over ℝ."""
    n = normalizer or Normalizer()
    if isinstance(term, list) and term and term[0] in ("CMP_LT", "CMP_GT", "CMP_LE", "CMP_GE", "CMP_EQ", "CMP_NE",
                                                       "AND", "OR", "NOT", "bool"):
        return n.boolean(term)
    return n.render(n.poly(term))


def rename(term, names: dict):
    """Variables renamed (``names``: old -> new); everything else kept."""
    if isinstance(term, list) and term and term[0] == "var":
        return ["var", names.get(term[1], term[1])]
    if isinstance(term, list):
        return [rename(x, names) if isinstance(x, list) else x for x in term]
    return term


POLY_HEADS = ("ADD", "SUB", "MUL", "NEG", "DIV", *ERASED)
MAX_POINTS = 20000
MAX_WORK = 4_000_000


def _dag_size(t) -> int:
    seen, stack = set(), [t]
    while stack:
        x = stack.pop()
        if isinstance(x, list) and id(x) not in seen:
            seen.add(id(x))
            stack.extend(a for a in x[1:] if isinstance(a, list))
    return len(seen)


def _degrees(t, memo=None) -> dict | None:
    """Per-variable degree bounds of a term in the polynomial class (DIV only by a constant), or None."""
    memo = {} if memo is None else memo
    if isinstance(t, list) and t and t[0] in ("int", "float"):
        return {} if isinstance(t[1], (int, float)) and t[1] == t[1] and abs(t[1]) != float("inf") else None
    if isinstance(t, list) and t and t[0] == "var":
        return {t[1]: 1}
    if not (isinstance(t, list) and t and t[0] in POLY_HEADS):
        return None
    hit = memo.get(id(t))
    if hit is not None and hit[0] is t:
        return hit[1]
    head, args = t[0], t[1:]
    ds = [_degrees(a, memo) for a in args]
    if any(d is None for d in ds):
        out = None
    elif head == "MUL":
        out = dict(ds[0])
        for k, e in ds[1].items():
            out[k] = out.get(k, 0) + e
    elif head == "DIV":
        out = ds[0] if not ds[1] and _const_value(args[1]) not in (None, 0) else None
    else:
        out = {}
        for d in ds:
            for k, e in d.items():
                out[k] = max(out.get(k, 0), e)
    memo[id(t)] = (t, out)
    return out


def _const_value(t):
    try:
        return Fraction(_exact(t, {}, {}))
    except (ValueError, ZeroDivisionError, TypeError):
        return None


def _exact(t, env: dict, memo: dict):
    """A polynomial-class term at a point, in exact rationals (F32 and TO_FLOAT are the identity over ℝ)."""
    if t[0] in ("int", "float"):
        return Fraction(t[1])
    if t[0] == "var":
        return env[t[1]]
    hit = memo.get(id(t))
    if hit is not None and hit[0] is t:
        return hit[1]
    a = [_exact(x, env, memo) for x in t[1:]]
    head = t[0]
    v = (a[0] + a[1] if head == "ADD" else a[0] - a[1] if head == "SUB" else a[0] * a[1] if head == "MUL" else
         -a[0] if head == "NEG" else a[0] / a[1] if head == "DIV" else a[0])
    memo[id(t)] = (t, v)
    return v


def sized_witness(a, b) -> dict | None:
    """A proof that two polynomial terms are equal over ℝ: if each variable's degree in a - b is at most d_v,
    agreeing on the grid {0..d_v} for every v forces a - b to be the zero polynomial (a nonzero polynomial of
    degree at most d_v in each variable does not vanish on a grid with d_v + 1 values per variable). None when a
    term is outside the polynomial class or the grid is past MAX_POINTS."""
    da, db = _degrees(a), _degrees(b)
    if da is None or db is None:
        return None
    deg = {v: max(da.get(v, 0), db.get(v, 0)) for v in set(da) | set(db)}
    points = 1
    for d in deg.values():
        points *= d + 1
        if points > MAX_POINTS:
            return None
    if points * (_dag_size(a) + _dag_size(b)) > MAX_WORK:      # exact rationals are slow: a bounded budget
        return None
    names = sorted(deg)
    grid = [[]]
    for v in names:
        grid = [g + [Fraction(i)] for g in grid for i in range(deg[v] + 1)]
    for g in grid:
        env = dict(zip(names, g))
        if _exact(a, env, {}) != _exact(b, env, {}):
            return {"tier": "proof", "status": "refuted", "at": {k: str(x) for k, x in env.items()}}
    return {"tier": "proof", "status": "proved", "points": len(grid),
            "by": "a grid of degree + 1 values per variable, in exact rationals"}


def digest(obj) -> str:
    return "sha256:" + hashlib.sha256(json.dumps(obj, separators=(",", ":"), sort_keys=True).encode()).hexdigest()[:24]


__all__ = ["Normalizer", "Poly", "canonical", "digest", "rename"]
