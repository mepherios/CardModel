"""funcalg — functions as algebra: canonical forms, the GCD of functions, cofactors, totals, Gödel numbers.

The lineage (cards in cards/lineage): Servois (1814) named *distributive* and *commutative* for operators
and showed that linear operators which commute obey the algebra of numbers, so identities proved for
numbers carry to them. Peacock (1830/1833) made "equivalent forms stay equivalent" a principle. Gödel (1931)
numbered syntax so that structure becomes arithmetic. This module puts the three together for integer
functions of one variable:

* **Canonical form (behaviour, not code).** Sample f(start), f(start+1), ... and find the shortest linear
  recurrence (Berlekamp–Massey over Q): its *annihilator* p(E), a polynomial in the shift operator E, with
  the initial terms, is the function's card. Any implementation with the same behaviour (a loop, a
  recursion, a closed form) has the same canonical form. Polynomials are exactly the annihilators (E - 1)^k;
  their closed form comes from Newton's forward differences (integer coefficients in the binomial basis).
  Every canonical form is checked on terms it was not fitted on.
* **Gödel number.** The canonical form is a short integer sequence; its Gödel number prod p_i^(z(a_i)+1)
  (p_i the i-th prime, z the zigzag map of the integers onto the naturals) names the behaviour. It decodes
  back exactly. Equal numbers mean identical behaviour: redefinition classes.
* **GCD of functions**, in two views:
  - operators (Servois): gcd of the annihilators = the dynamics two functions share; lcm = the annihilator
    of their sum; equal annihilators mean one is a fixed combination of shifts of the other (a basis change:
    Lucas = 2 F(n+1) - F(n));
  - values (polynomial functions): the gcd in Q[n] gives the common factor h and cofactors p, q with
    f = p h and g = q h, hence the integer cross identity q' f = p' g (e.g. 3 S(n) = (2n + 1) T(n) for the
    sum of squares and the triangular numbers); a polynomial composition g = Q(f) is found when it exists
    (sum of cubes = triangular squared).
* **Fixed divisor**: the gcd of all values of an integer polynomial = the gcd of its Newton coefficients, a
  divisibility law that carries to every multiple.
* **Totals**: the running sum of a canonical form is canonical again (annihilator (E - 1) p(E)).
* **Redefinitions for the optimizer**: a polynomial becomes an exact integer closed form; a recurrence of
  order d becomes d x d matrix powering (O(d^3 log n)), both in the liftable subset, so improve can verify,
  time and splice them, and every language card can emit them.

Honest limits (L1): functions of one integer variable; behaviours that are not linear recurrences of order
<= MAX_ORDER on the sampled range (exponentials of n^2, primes, ...) have no canonical form here; "checked" is
evidence on sampled terms, proof comes from the algebra of the fitted form (exact rational arithmetic) only
for the fitted range.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from fractions import Fraction

from ..kernel import resources

MAX_ORDER = 8
EXTRA = 8


# -- univariate polynomials over Q --------------------------------------------------------------------------------
class Poly:
    __slots__ = ("c",)

    def __init__(self, coeffs):
        c = [Fraction(x) for x in coeffs]
        while c and c[-1] == 0:
            c.pop()
        self.c = c

    @property
    def deg(self) -> int:
        return len(self.c) - 1

    def __bool__(self):
        return bool(self.c)

    def __eq__(self, other):
        return isinstance(other, Poly) and self.c == other.c

    def __hash__(self):
        return hash(tuple(self.c))

    def __call__(self, x):
        acc = Fraction(0)
        for a in reversed(self.c):
            acc = acc * x + a
        return acc

    def __add__(self, o):
        n = max(len(self.c), len(o.c))
        return Poly([(self.c[i] if i < len(self.c) else 0) + (o.c[i] if i < len(o.c) else 0) for i in range(n)])

    def __sub__(self, o):
        return self + Poly([-x for x in o.c])

    def __mul__(self, o):
        if isinstance(o, (int, Fraction)):
            return Poly([x * o for x in self.c])
        if not self.c or not o.c:
            return Poly([])
        out = [Fraction(0)] * (len(self.c) + len(o.c) - 1)
        for i, a in enumerate(self.c):
            for j, b in enumerate(o.c):
                out[i + j] += a * b
        return Poly(out)

    __rmul__ = __mul__

    def divmod(self, d: "Poly"):
        if not d:
            raise ZeroDivisionError("polynomial division by zero")
        q = [Fraction(0)] * max(1, len(self.c) - len(d.c) + 1)
        r = list(self.c)
        while len(r) >= len(d.c) and any(r):
            shift = len(r) - len(d.c)
            f = r[-1] / d.c[-1]
            q[shift] = f
            for i, b in enumerate(d.c):
                r[i + shift] -= f * b
            while r and r[-1] == 0:
                r.pop()
        return Poly(q), Poly(r)

    def monic(self) -> "Poly":
        return Poly([x / self.c[-1] for x in self.c]) if self.c else self

    def primitive(self) -> "Poly":
        """Integer coefficients with gcd 1 and a positive leading coefficient (same roots)."""
        if not self.c:
            return self
        den = 1
        for x in self.c:
            den = den * x.denominator // math.gcd(den, x.denominator)
        ints = [int(x * den) for x in self.c]
        g = 0
        for v in ints:
            g = math.gcd(g, v)
        ints = [v // g for v in ints]
        if ints[-1] < 0:
            ints = [-v for v in ints]
        return Poly(ints)

    def integer_form(self) -> tuple[int, list[int]]:
        """(D, coefficients) with self(x) = (sum c_i x^i) / D, all integers."""
        den = 1
        for x in self.c:
            den = den * x.denominator // math.gcd(den, x.denominator)
        return den, [int(x * den) for x in self.c]

    def text(self, var: str = "n") -> str:
        if not self.c:
            return "0"
        terms = []
        for i in range(len(self.c) - 1, -1, -1):
            a = self.c[i]
            if a == 0:
                continue
            mono = "" if i == 0 else (var if i == 1 else f"{var}^{i}")
            coef = str(abs(a)) if (abs(a) != 1 or i == 0) else ""
            body = f"{coef}{'*' if coef and mono else ''}{mono}" or "1"
            terms.append(("-" if a < 0 else "+", body))
        s = " ".join(f"{sg} {b}" for sg, b in terms)
        return s[2:] if s.startswith("+ ") else "-" + s[2:]

    def __repr__(self):
        return f"Poly({self.text('x')})"


def pgcd(a: Poly, b: Poly) -> Poly:
    while b:
        _, r = a.divmod(b)
        a, b = b, r
    return a.monic() if a else Poly([1])


def plcm(a: Poly, b: Poly) -> Poly:
    q, r = (a * b).divmod(pgcd(a, b))
    return q.monic()


# -- sequences: Newton, Berlekamp–Massey ----------------------------------------------------------------------------
def newton(values) -> list[Fraction]:
    """Forward differences at the first point: values = f(s), f(s+1), ... -> [Δ^k f(s)]."""
    row = [Fraction(v) for v in values]
    out = []
    while row:
        out.append(row[0])
        row = [b - a for a, b in zip(row, row[1:])]
    return out


def poly_from_newton(a: list, start: int = 0) -> Poly:
    """sum_k a_k * C(n - start, k) as a polynomial in n."""
    total = Poly([])
    for k, ak in enumerate(a):
        if ak == 0:
            continue
        term = Poly([1])
        for j in range(k):
            term = term * Poly([-(start + j), 1])
        total = total + term * (Fraction(ak) / math.factorial(k))
    return total


def berlekamp_massey(seq) -> list[Fraction]:
    """Shortest c_1..c_L with s_n = sum c_i s_{n-i} for every n >= L in ``seq`` (over Q)."""
    s = [Fraction(x) for x in seq]
    C, B = [Fraction(1)], [Fraction(1)]
    L, m, b = 0, 1, Fraction(1)
    for n in range(len(s)):
        d = s[n] + sum(C[i] * s[n - i] for i in range(1, L + 1))
        if d == 0:
            m += 1
            continue
        T = list(C)
        coef = d / b
        C = C + [Fraction(0)] * max(0, len(B) + m - len(C))
        for i, x in enumerate(B):
            C[i + m] -= coef * x
        if 2 * L <= n:
            L, B, b, m = n + 1 - L, T, d, 1
        else:
            m += 1
    return [-x for x in C[1:L + 1]] + [Fraction(0)] * max(0, L - (len(C) - 1))


# -- canonical forms ------------------------------------------------------------------------------------------------
@dataclass
class Form:
    start: int
    coeffs: list                      # c_1..c_d: f(n) = sum c_i f(n - i)
    initial: list                     # f(start .. start + d - 1)
    poly: Poly | None = None          # closed form when the annihilator is (E - 1)^d
    checked: int = 0                  # terms verified that the fit did not use
    sampled: list = field(default_factory=list)

    @property
    def order(self) -> int:
        return len(self.coeffs)

    def annihilator(self) -> Poly:
        d = self.order
        return Poly([-self.coeffs[d - 1 - i] for i in range(d)] + [1]) if d else Poly([1])

    def value(self, n: int):
        if self.poly is not None:
            v = self.poly(n)
            return int(v) if v.denominator == 1 else v
        k = n - self.start
        if k < 0:
            raise ValueError("before the start of the canonical form")
        vals = list(self.initial)
        while len(vals) <= k:
            vals.append(sum(c * vals[-1 - i] for i, c in enumerate(self.coeffs)))
        v = Fraction(vals[k])
        return int(v) if v.denominator == 1 else v

    def kind(self) -> str:
        if self.order == 0:
            return "zero"
        if self.poly is not None:
            return f"polynomial of degree {self.poly.deg}"
        return f"linear recurrence of order {self.order}"

    def code(self) -> list[int]:
        """The canonical integer sequence [start, d, coefficients (num, den), initial terms (num, den)]."""
        out = [self.start, self.order]
        for x in list(self.coeffs) + list(self.initial):
            x = Fraction(x)
            out += [x.numerator, x.denominator]
        return out

    def godel(self) -> int:
        return godel_encode(self.code())

    def describe(self) -> str:
        if self.order == 0:
            return "f(n) = 0"
        if self.poly is not None:
            return f"f(n) = {self.poly.text()}"
        rec = " + ".join(f"{_frac(c)}*f(n-{i + 1})" for i, c in enumerate(self.coeffs) if c != 0)
        return f"f(n) = {rec};  f({self.start}..{self.start + self.order - 1}) = {[_frac(x) for x in self.initial]}"


def _frac(x) -> str:
    x = Fraction(x)
    return str(x.numerator) if x.denominator == 1 else f"{x.numerator}/{x.denominator}"


def sample(fn, start: int, count: int, budget_s: float = 2.0, per_call_s: float = 0.25) -> list:
    """fn(start), fn(start+1), ... until count values, an error, a slow call or the budget."""
    out, t_all = [], time.perf_counter()
    for i in range(count):
        if i % 16 == 0:
            resources.guard("function algebra sampling")
        t0 = time.perf_counter()
        try:
            v = fn(start + i)
        except Exception:  # noqa: BLE001 -- outside the function's domain: the sample ends here
            break
        if isinstance(v, bool) or not isinstance(v, (int, Fraction)):
            break
        out.append(v)
        if time.perf_counter() - t0 > per_call_s or time.perf_counter() - t_all > budget_s:
            break
    return out


def fit(fn, start: int = 0, max_order: int = MAX_ORDER, extra: int = EXTRA, values: list | None = None) -> Form | None:
    """The canonical form of an integer function of one variable, checked on terms the fit did not use."""
    vals = values if values is not None else sample(fn, start, 2 * max_order + extra)
    if len(vals) < extra + 2:
        return None
    for used in range(2, len(vals) - extra + 1):
        rec = berlekamp_massey(vals[:used])
        d = len(rec)
        if 2 * d > used:
            continue
        if all(sum(c * vals[n - i - 1] for i, c in enumerate(rec)) == vals[n] for n in range(d, len(vals))):
            form = Form(start, rec, list(vals[:d]), checked=len(vals) - used, sampled=list(vals))
            ann = form.annihilator()
            if d and ann == _power_x_minus_1(d):
                form.poly = poly_from_newton(newton(vals[:d + 1])[:d], start)
            return form
    return None


def _power_x_minus_1(k: int) -> Poly:
    p = Poly([1])
    for _ in range(k):
        p = p * Poly([-1, 1])
    return p


# -- Gödel numbering (the primes and the zigzag are engines/godel's) ---------------------------------------------------
def godel_encode(seq: list[int]) -> int:
    """Gödel's numbering of an integer sequence: prod p_i ** (zig(a_i) + 1). Exact; decodes back."""
    from . import godel as G
    if len(seq) > 256 or any(abs(int(a)) > 10**6 for a in seq):
        raise ValueError("too large to number (keep Gödel numbers for canonical forms, not raw data)")
    n = 1
    for p, a in zip(G.primes(len(seq)), seq):
        n *= p ** (G.zig(int(a)) + 1)
    return n


def godel_decode(n: int) -> list[int]:
    """The sequence back: the exponents of the consecutive primes, up to the first prime that is absent."""
    from . import godel as G
    out = []
    for e in G.exponents(n):
        if e == 0:
            break
        out.append(G.unzig(e - 1))
    return out


# -- comparing functions ------------------------------------------------------------------------------------------------
def fixed_divisor(form: Form) -> int | None:
    """gcd of all values of an integer-valued polynomial = gcd of its Newton coefficients."""
    if form.poly is None:
        return None
    a = newton([form.poly(form.start + i) for i in range(form.poly.deg + 1)])
    g = 0
    for x in a:
        if x.denominator != 1:
            return None
        g = math.gcd(g, int(x))
    return g


def basis_change(f: Form, g: Form) -> list | None:
    """Weights w with g(n) = sum_i w_i f(n + i), i < d, when f and g share their annihilator."""
    d = f.order
    if d == 0 or f.annihilator() != g.annihilator() or f.start != g.start:
        return None
    rows = [[Fraction(f.value(f.start + j + i)) for i in range(d)] for j in range(d)]
    rhs = [Fraction(g.value(g.start + j)) for j in range(d)]
    w = _solve(rows, rhs)
    if w is None:
        return None
    for j in range(d, d + 6):
        if sum(w[i] * f.value(f.start + j + i) for i in range(d)) != g.value(g.start + j):
            return None
    return w


def _solve(a, b):
    n = len(a)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = next((r for r in range(col, n) if m[r][col] != 0), None)
        if piv is None:
            return None
        m[col], m[piv] = m[piv], m[col]
        for r in range(n):
            if r != col and m[r][col] != 0:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][n] / m[i][i] for i in range(n)]


def shift_relation(f: Form, g: Form, max_shift: int = 4) -> int | None:
    """s with g(n) = f(n + s) on the shared range (|s| <= max_shift), the simplest identity two forms can share."""
    if f.annihilator() != g.annihilator():
        return None
    lo = max(f.start, g.start) + max_shift
    for s in range(-max_shift, max_shift + 1):
        if s == 0:
            continue
        try:
            if all(Fraction(g.value(n)) == Fraction(f.value(n + s)) for n in range(lo, lo + 2 * f.order + 6)):
                return s
        except ValueError:
            continue
    return None


def composition(f: Form, g: Form) -> Poly | None:
    """Q with g = Q(f), when both are polynomials and deg g = k * deg f."""
    if f.poly is None or g.poly is None or f.poly.deg < 1 or g.poly.deg % f.poly.deg:
        return None
    k = g.poly.deg // f.poly.deg
    pts, seen = [], set()
    n = f.start
    while len(pts) < k + 1 and n < f.start + 200:
        x = f.poly(n)
        if x not in seen:
            seen.add(x)
            pts.append((x, g.poly(n)))
        n += 1
    if len(pts) < k + 1:
        return None
    rows = [[x ** i for i in range(k + 1)] for x, _ in pts]
    q = _solve(rows, [y for _, y in pts])
    if q is None:
        return None
    Q = Poly(q)
    if all(Q(f.poly(m)) == g.poly(m) for m in range(f.start, f.start + 3 * k + 6)):
        return Q
    return None


def gcd_functions(f: Form, g: Form) -> dict:
    """Everything the two canonical forms share, and the identities that let the logic of one carry to the other."""
    out = {"f": f.describe(), "g": g.describe(), "same_function": f.code() == g.code()}
    af, ag = f.annihilator(), g.annihilator()
    h = pgcd(af, ag)
    out["operators"] = {"gcd": h.text("E"), "lcm": plcm(af, ag).text("E"),
                        "cofactor_f": af.divmod(h)[0].text("E"), "cofactor_g": ag.divmod(h)[0].text("E"),
                        "shared_order": h.deg}
    sh = shift_relation(f, g)
    if sh is not None:
        out["shift"] = f"g(n) = f(n {'+' if sh > 0 else '-'} {abs(sh)})"
        out["shift_by"] = sh
    w = basis_change(f, g)
    if w is not None and sh is None:
        out["basis_change"] = " + ".join(f"{_frac(x)}*f(n+{i})" for i, x in enumerate(w) if x != 0) or "0"
    if f.poly is not None and g.poly is not None:
        hv = pgcd(f.poly, g.poly) if f.poly and g.poly else Poly([1])
        hp = hv.primitive() if hv.deg >= 1 else Poly([1])
        p, rp = f.poly.divmod(hp)
        q, rq = g.poly.divmod(hp)
        values = {"common_factor": hp.text(), "cofactor_f": p.text(), "cofactor_g": q.text()}
        if not rp and not rq and hp.deg >= 1:
            # f = p h and g = q h, so q f = p g; clear denominators with one common scale for both sides
            den = math.lcm(p.integer_form()[0], q.integer_form()[0])
            pi = [int(x * den) for x in p.c]
            qi = [int(x * den) for x in q.c]
            g_all = 0
            for v in pi + qi:
                g_all = math.gcd(g_all, v)
            P2, Q2 = Poly([v // g_all for v in pi]), Poly([v // g_all for v in qi])
            values["cross_identity"] = f"({Q2.text()}) * f(n) == ({P2.text()}) * g(n)"
            values["cross_polys"] = ([int(x) for x in Q2.c], [int(x) for x in P2.c])
        out["values"] = values
        fd_f, fd_g = fixed_divisor(f), fixed_divisor(g)
        out["fixed_divisors"] = {"f": fd_f, "g": fd_g, "both": math.gcd(fd_f or 0, fd_g or 0)}
    comp = composition(f, g)
    if comp is not None:
        out["composition"] = f"g = Q(f) with Q(x) = {comp.text('x')}"
    comp2 = composition(g, f)
    if comp2 is not None:
        out["composition_rev"] = f"f = Q(g) with Q(x) = {comp2.text('x')}"
    return out


def total(f: Form) -> Form | None:
    """The running sum T(n) = f(start) + ... + f(n): canonical again (annihilator (E - 1) p(E))."""
    n = 2 * (f.order + 1) + EXTRA + 2
    acc, vals = Fraction(0), []
    for i in range(n):
        acc += Fraction(f.value(f.start + i))
        vals.append(acc)
    return fit(None, f.start, max_order=f.order + 1, values=vals)


# -- redefinitions as code (liftable Python) ------------------------------------------------------------------------
def python_source(f: Form, name: str, param: str = "n") -> str | None:
    """An exact fast form: an integer closed form for polynomials, matrix powering for recurrences."""
    if f.order == 0:
        return f"def {name}({param}: int) -> int:\n    return 0\n"
    if f.poly is not None:
        den, ints = f.poly.integer_form()
        expr = str(ints[-1])
        for c in reversed(ints[:-1]):
            expr = f"({c} + {param} * {expr})" if c else f"({param} * {expr})"
        body = f"{expr} // {den}" if den != 1 else expr
        return f"def {name}({param}: int) -> int:\n    return {body}\n"
    if any(Fraction(c).denominator != 1 for c in f.coeffs) or any(Fraction(x).denominator != 1 for x in f.initial):
        return None
    d = f.order
    if d > 4:
        return None
    c = [int(x) for x in f.coeffs]
    init = [int(x) for x in f.initial]
    L = [f"def {name}({param}: int) -> int:", f"    k = {param} - {f.start}"]
    for i in range(d):
        L.append(f"    if k == {i}:\n        return {init[i]}")
    # companion matrix M (row 0 = coefficients, sub-diagonal ones); R = M^(k - d + 1) by squaring
    for i in range(d):
        for j in range(d):
            L.append(f"    m{i}{j} = {c[j] if i == 0 else (1 if j == i - 1 else 0)}")
            L.append(f"    r{i}{j} = {1 if i == j else 0}")
    L.append(f"    e = k - {d - 1}")
    L.append("    while e > 0:")
    L.append("        if e % 2 == 1:")
    for i in range(d):
        for j in range(d):
            L.append(f"            t{i}{j} = " + " + ".join(f"r{i}{x} * m{x}{j}" for x in range(d)))
    for i in range(d):
        for j in range(d):
            L.append(f"            r{i}{j} = t{i}{j}")
    for i in range(d):
        for j in range(d):
            L.append(f"        t{i}{j} = " + " + ".join(f"m{i}{x} * m{x}{j}" for x in range(d)))
    for i in range(d):
        for j in range(d):
            L.append(f"        m{i}{j} = t{i}{j}")
    L.append("        e = e // 2")
    state = [init[d - 1 - j] for j in range(d)]              # f(start + d - 1), ..., f(start)
    L.append("    return " + " + ".join(f"r0{j} * {state[j]}" for j in range(d)))
    return "\n".join(L) + "\n"


__all__ = ["Form", "Poly", "basis_change", "berlekamp_massey", "composition", "fit", "fixed_divisor", "gcd_functions",
           "godel_decode", "godel_encode", "newton", "pgcd", "plcm", "python_source", "total"]


# -- scanning the algorithm cards ----------------------------------------------------------------------------------
def scan_algorithms(ctx) -> dict:
    """Canonical forms of every one-integer algorithm card form; classes by Gödel number; pairwise identities."""
    from .witness import python_callable
    forms: dict[str, dict] = {}
    problems = []
    for card in sorted(ctx.store.cards("algorithm"), key=lambda c: c.name):
        sig = card.get("signature") or {}
        if [p["type"] for p in sig.get("params", [])] != ["int"] or sig.get("returns") != "int":
            continue
        per_form = {}
        for form in card.get("forms") or []:
            try:
                fn = python_callable(ctx, form, card)
            except Exception:  # noqa: BLE001 -- a broken form is reported by verify, not here
                continue
            f = fit(fn, 0) or fit(fn, 1)
            if f is not None:
                per_form[form["name"]] = f
        if not per_form:
            continue
        nums = {name: f.godel() for name, f in per_form.items()}
        if len(set(nums.values())) > 1:
            problems.append(f"algorithm/{card.name}: its forms behave differently: {sorted(nums)}")
        ref = per_form.get(card.get("reference_form")) or next(iter(per_form.values()))
        forms[card.name] = {"form": ref, "forms": sorted(per_form), "godel": ref.godel()}
    classes: dict[int, list] = {}
    for name, info in forms.items():
        classes.setdefault(info["godel"], []).append(name)
    relations = []
    names = sorted(forms)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            fa, fb = forms[a]["form"], forms[b]["form"]
            if fa.code() == fb.code():
                continue
            r = gcd_functions(fa, fb)
            rel = {"f": a, "g": b}
            if r.get("shift"):
                rel["shift"], rel["shift_by"] = r["shift"], r["shift_by"]
            if r.get("basis_change"):
                rel["basis_change"] = r["basis_change"]
            if (r.get("values") or {}).get("cross_identity"):
                rel["cross_identity"] = r["values"]["cross_identity"]
                rel["cross_polys"] = r["values"]["cross_polys"]
                rel["common_factor"] = r["values"]["common_factor"]
            if r.get("composition"):
                rel["composition"] = r["composition"]
            if r.get("composition_rev"):
                rel["composition_rev"] = r["composition_rev"]
            if r["operators"]["shared_order"] and fa.order and fb.order:
                rel["shared_operator"] = r["operators"]["gcd"]
            if len(rel) > 2:
                relations.append(rel)
    divisors = {name: fixed_divisor(info["form"]) for name, info in forms.items()
                if info["form"].poly is not None and (fixed_divisor(info["form"]) or 1) > 1}
    return {"forms": {n: {"canonical": i["form"].describe(), "kind": i["form"].kind(), "godel": str(i["godel"]),
                          "checked": i["form"].checked, "forms": i["forms"]} for n, i in forms.items()},
            "classes": [sorted(v) for v in classes.values() if len(v) > 1], "relations": relations,
            "fixed_divisors": divisors, "problems": problems, "_forms": forms}


def card_source(scan: dict) -> str:
    """The identities a scan found, as card-language theorems over the algorithm cards (witnessed on every run)."""
    L = ["-- generated by `cardmodel algebra scan --write` (engines/funcalg.py): identities between algorithm cards",
         "-- found from their behaviour. Edit the algorithm cards, not this file.", "module algebra", ""]
    k = 0
    for cls in scan["classes"]:
        for other in cls[1:]:
            k += 1
            L.append(f"theorem same_{cls[0]}_{other}(n: Nat) requires n <= 500: "
                     f"algorithm.{cls[0]}(n) == algorithm.{other}(n)")
    for rel in scan["relations"]:
        a, b = rel["f"], rel["g"]
        if "shift_by" in rel:
            sh = rel["shift_by"]
            arg = f"n {'+' if sh > 0 else '-'} {abs(sh)}"
            lo = max(0, -sh)
            L.append(f"theorem shift_{b}_{a}(n: Nat) requires n >= {lo}, n <= 500: "
                     f"algorithm.{b}(n) == algorithm.{a}({arg})")
            continue                              # a shift says everything the cofactor identity would
        if "cross_polys" in rel:
            q, p = rel["cross_polys"]
            L.append(f"theorem cofactor_{a}_{b}(n: Nat) requires n <= 500: "
                     f"({_poly_card(q)}) * algorithm.{a}(n) == ({_poly_card(p)}) * algorithm.{b}(n)")
        if "composition" in rel:
            q = rel["composition"].split("Q(x) = ", 1)[1]
            L.append(f"theorem compose_{b}_of_{a}(n: Nat) requires n <= 500: "
                     f"algorithm.{b}(n) == {_q_card(q, f'algorithm.{a}(n)')}")
        if "composition_rev" in rel:
            q = rel["composition_rev"].split("Q(x) = ", 1)[1]
            L.append(f"theorem compose_{a}_of_{b}(n: Nat) requires n <= 500: "
                     f"algorithm.{a}(n) == {_q_card(q, f'algorithm.{b}(n)')}")
    for name, d in scan["fixed_divisors"].items():
        L.append(f"theorem divisible_{name}(n: Nat) requires n <= 500: algorithm.{name}(n) % {d} == 0")
    return "\n".join(L) + "\n"


def _poly_card(coeffs) -> str:
    terms = []
    for i, c in enumerate(coeffs):
        c = int(c)
        if c == 0:
            continue
        mono = "1" if i == 0 else ("n" if i == 1 else f"n ** {i}")
        terms.append(str(c) if i == 0 else (mono if c == 1 else f"{c} * {mono}"))
    return " + ".join(terms) or "0"


def _q_card(q_text: str, inner: str) -> str:
    """Q(x) rendered with x := inner (Q's text uses x^k, coefficients maybe fractions -> only integer Q used)."""
    import re
    out = q_text.replace("^", " ** ")
    out = re.sub(r"\bx\b", f"({inner})", out)
    return out


def identity_cards(scan: dict) -> list[dict]:
    """The functional_identity cards of a ``scan_algorithms`` result: one per relation, one per canonical form."""
    prov = {"origin": "cardmodel algebra scan", "engine": "engines/funcalg.py"}
    cards = []
    for rel in scan["relations"]:
        cards.append({"name": f"{rel['f']}__{rel['g']}", "category": "functional_identity",
                      "statement": " | ".join(str(rel[k]) for k in ("shift", "composition", "composition_rev",
                                                                    "cross_identity", "basis_change") if k in rel),
                      "f": f"algorithm/{rel['f']}", "g": f"algorithm/{rel['g']}",
                      **{k: v for k, v in rel.items() if k not in ("f", "g")},
                      "depends_on": [f"algorithm/{rel['f']}", f"algorithm/{rel['g']}"], "provenance": prov})
    for n, i in scan["forms"].items():
        cards.append({"name": f"form__{n}", "category": "functional_identity", "kind": "canonical_form",
                      "statement": f"algorithm/{n}: {i['canonical']}", "canonical": i["canonical"],
                      "godel": i["godel"], "implementations": i["forms"], "checked": i["checked"],
                      "depends_on": [f"algorithm/{n}"], "provenance": prov})
    return cards

