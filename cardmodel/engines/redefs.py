"""redefs — verify executable redefinitions (source_form == target_form) by seeded evaluation.

Pheros L34 asks for a witness and at least one agreeing example. Here every
executable redefinition is evaluated at seeded points of its domain
(integer / nonneg_integer / modular_n: integers; real / fp64 / symbolic_real /
positive_real: doubles, each of which is an exact binary fraction):

  rational forms   + - * /, integer powers, abs, min, max, floor, ... are evaluated
                   exactly (fractions.Fraction) and compared exactly: no rounding at all
  other forms      sin, sqrt, pi, x**(1/3), ... are screened in floats (rel/abs tol 1e-7).
                   A disagreement is decided again at 30, 60, 120, 240 significant digits
                   (decimal), with exact arithmetic between those values, as soon as two
                   successive precisions agree to 20 digits. A point that never settles
                   is skipped and counted (``undecided_points``), never a counterexample.

So a counterexample is a real one: near a vanishing denominator floats can lose
every digit, and a disagreement that high precision dissolves is counted as a
rounding artefact (``rounding_artefacts``) instead of refuting a true identity.

Verdicts: verified (>= MIN_VALID valid points, all agree) · refuted (a
counterexample, with the seed to reproduce) · inconclusive (too few points
inside the domain, or a mismatch while the card's ``condition`` could not
be parsed -- the condition may exclude it) · unparsable.

The card's own ``examples`` are also re-evaluated; an example that does not
bind every variable is reported as incomplete (some auto-generated Pheros
cards carry such examples, which made their L34 check vacuous).

Optional capability: when the python module ``sympy`` is installed, a
time-boxed ``simplify(lhs - rhs) == 0`` upgrades a verified verdict to
``proved_symbolic``; it never overrides a counterexample (CM23). sympy is
never required.

Honest limits (L1): numeric agreement on sampled points is evidence, not
proof. For non-rational forms the float screen can still hide a difference
below its tolerance, and the high-precision decision is a convergence test,
not interval arithmetic: a discontinuous step (floor, a comparison) taken on
a transcendental value that sits exactly on the jump can be misjudged at
every precision.
"""
from __future__ import annotations

import decimal
import math
import random
from decimal import Decimal
from fractions import Fraction
from functools import lru_cache

from . import probes
from . import values as V
from .exprs import EXACT_FUNCS as _EXACT_FUNCS
from .exprs import EvalError, ParseError, UnknownName, evaluate, parse, sum_terms, variables

MIN_VALID = 8
REAL_TOL = 1e-7
INT_DOMAINS = {"integer": (-30, 30), "nonneg_integer": (0, 30), "modular_n": (-30, 30)}
REAL_DOMAINS = {"real": (-3.0, 3.0), "fp64": (-3.0, 3.0), "symbolic_real": (-3.0, 3.0), "positive_real": (0.05, 4.0)}
DIGITS = (30, 60, 120, 240)      # precisions that may decide a float disagreement
SETTLED = Fraction(1, 10**20)    # two successive precisions this close (relative, or absolute below 1) decide
GUARD = 10                       # decimal digits carried beyond the requested precision
MAX_BITS = 1 << 15               # an exact value larger than this falls back to floats (or to high precision)
OUTSIDE = (ArithmeticError, ValueError, TypeError, OverflowError, UnknownName, RecursionError)  # not in the domain


def _close(a, b) -> bool:
    if isinstance(a, complex) or isinstance(b, complex):
        return False
    fa, fb = float(a), float(b)
    if math.isnan(fa) or math.isnan(fb) or math.isinf(fa) or math.isinf(fb):
        return False
    return math.isclose(fa, fb, rel_tol=REAL_TOL, abs_tol=REAL_TOL)


def _close_exact(a, b) -> bool:
    """``_close`` without rounding: |a - b| <= max(tol * max(|a|, |b|), tol) on exact values."""
    tol = Fraction(REAL_TOL)
    return abs(a - b) <= max(tol * max(abs(a), abs(b)), tol)


def _num(text):
    try:
        return Fraction(str(text).strip())
    except (ValueError, ZeroDivisionError):
        try:
            return float(str(text).strip())
        except ValueError:
            return None


# ---------------------------------------------------------------- exact evaluation, high precision where it must

class _Inexact(Exception):
    """A step has no exact rational value here (a transcendental call, pi, a fractional power, a float literal)."""


class _Undecided(Exception):
    """High precision could not decide: successive precisions still disagree."""


class _NoPreciseForm(Exception):
    """A step has neither an exact nor a high-precision form here (only its float value is known)."""


def _ctx(prec: int):
    return decimal.localcontext(decimal.Context(prec=prec, Emax=999999, Emin=-999999, traps=[
        decimal.InvalidOperation, decimal.DivisionByZero, decimal.Overflow]))


def _dec(q) -> Decimal:
    """An int or Fraction rounded to the current decimal precision."""
    q = Fraction(q)
    return Decimal(q.numerator) / Decimal(q.denominator)


def _mag(q) -> int:
    """About log10 |q| for q != 0 (from bit lengths)."""
    q = Fraction(q)
    return int((abs(q.numerator).bit_length() - q.denominator.bit_length()) * 0.30103)


def _tiny(q) -> int:
    """Digits that cancel when a quantity this small is formed from numbers near 1."""
    return max(0, -_mag(q)) if q else 0


@lru_cache(maxsize=None)
def _pi(prec: int) -> Decimal:
    """pi to ``prec`` digits: Machin's formula in integer fixed point with guard digits."""
    scale = 10 ** (prec + GUARD)

    def acot(n: int) -> int:
        total, term, k, sign = 0, scale // n, 1, 1
        while term:
            total += sign * (term // k)
            term //= n * n
            k += 2
            sign = -sign
        return total

    with _ctx(prec):
        return Decimal(16 * acot(5) - 4 * acot(239)) / scale


def _reduce(q, prec: int) -> tuple[Decimal, int]:
    """(r, j) with q = r + j * pi/2 and |r| <= pi/4, at ``prec`` digits."""
    with _ctx(prec):
        x = _dec(q)
        half_pi = _pi(prec) / 2
        j = (x / half_pi).to_integral_value()
        return x - j * half_pi, int(j)


def _sin_cos(q, digits: int) -> tuple[Decimal, Decimal]:
    """(sin q, cos q): q minus the nearest multiple of pi/2, then the Taylor series of sin r and cos r."""
    prec = digits + GUARD + (max(0, _mag(q)) if q else 0) + 2
    r, j = _reduce(q, prec)
    if r and r.adjusted() < -2:          # q is near a multiple of pi/2: carry the digits that cancelled
        prec -= r.adjusted()
        r, j = _reduce(q, prec)
    with _ctx(prec):
        r2 = r * r
        s, term, n, last = r, r, 1, None
        while s != last:
            last, term = s, -term * r2 / ((n + 1) * (n + 2))
            s, n = s + term, n + 2
        c, term, n, last = Decimal(1), Decimal(1), 0, None
        while c != last:
            last, term = c, -term * r2 / ((n + 1) * (n + 2))
            c, n = c + term, n + 2
    k = j % 4
    return (s, c, -s, -c)[k], (c, -s, -c, s)[k]


def _atan_dec(x: Decimal) -> Decimal:
    """atan at the current precision: three argument halvings, then the Taylor series."""
    if not x:
        return x
    if x < 0:
        return -_atan_dec(-x)
    if x > 1:
        return _pi(decimal.getcontext().prec) / 2 - _atan_dec(1 / x)
    for _ in range(3):
        x = x / (1 + (1 + x * x).sqrt())
    x2 = x * x
    s, power, n, last = x, x, 1, None
    while s != last:
        last, power, n = s, -power * x2, n + 2
        s = s + power / n
    return 8 * s


def _ln(q, digits: int) -> Decimal:
    if q <= 0:
        raise ValueError("math domain error")
    with _ctx(digits + GUARD + _tiny(q - 1) + 2):
        return _dec(q).ln()


def _hp_log(args, digits):
    if len(args) == 1:
        return _ln(args[0], digits)
    with _ctx(digits + GUARD):
        return _ln(args[0], digits) / _ln(args[1], digits)


def _hp_exp(args, digits):
    with _ctx(digits + GUARD + (max(0, _mag(args[0])) if args[0] else 0) + 2):
        return _dec(args[0]).exp()


def _hp_sqrt(args, digits):
    if args[0] < 0:
        raise ValueError("math domain error")
    with _ctx(digits + GUARD):
        return _dec(args[0]).sqrt()


def _hp_trig(name):
    def f(args, digits):
        s, c = _sin_cos(args[0], digits)
        with _ctx(digits + GUARD):
            if name in ("sin", "cos"):
                return s if name == "sin" else c
            if name in ("tan", "cot"):
                return s / c if name == "tan" else c / s
            return 1 / c if name == "sec" else 1 / s
    return f


def _hp_log_base(base: int):
    def f(args, digits):
        with _ctx(digits + GUARD):
            return _ln(args[0], digits) / _ln(Fraction(base), digits)
    return f


def _hp_atan(args, digits):
    with _ctx(digits + GUARD):
        return _atan_dec(_dec(args[0]))


def _hp_asin(args, digits):
    q = args[0]
    w = 1 - q * q
    if w < 0:
        raise ValueError("math domain error")
    with _ctx(digits + GUARD):
        if not w:
            return _pi(digits + GUARD) / 2 * (1 if q > 0 else -1)
        return _atan_dec(_dec(q) / _dec(w).sqrt())


def _hp_acos(args, digits):
    q = args[0]
    if q < -1 or q > 1:
        raise ValueError("math domain error")
    with _ctx(digits + GUARD):
        if q == -1:
            return _pi(digits + GUARD)
        return 2 * _atan_dec(_dec((1 - q) / (1 + q)).sqrt())


def _hp_atan2(args, digits):
    y, x = args
    with _ctx(digits + GUARD):
        pi = _pi(digits + GUARD)
        if x > 0:
            return _atan_dec(_dec(y / x))
        if x < 0:
            return _atan_dec(_dec(y / x)) + (pi if y >= 0 else -pi)
        return pi / 2 if y > 0 else (-pi / 2 if y < 0 else Decimal(0))


def _hp_hyperbolic(name):
    def f(args, digits):
        q = args[0]
        if name == "tanh" and abs(q) > 2 * (digits + GUARD):
            return Decimal(1 if q > 0 else -1)       # 1 - |tanh q| < 10**-(digits + GUARD)
        with _ctx(digits + GUARD + _tiny(q) + 2):
            if name == "tanh":
                e2 = (2 * _dec(q)).exp()
                return (e2 - 1) / (e2 + 1)
            e = _dec(q).exp()
            return (e - 1 / e) / 2 if name == "sinh" else (e + 1 / e) / 2
    return f


def _hp_asinh(args, digits):
    q = args[0]
    a = abs(q)
    with _ctx(digits + GUARD + _tiny(a) + 2):
        return (_dec(a) + _dec(a * a + 1).sqrt()).ln() * (-1 if q < 0 else 1) if a else Decimal(0)


def _hp_acosh(args, digits):
    q = args[0]
    if q < 1:
        raise ValueError("math domain error")
    with _ctx(digits + GUARD + _tiny(q - 1) + 2):
        return (_dec(q) + _dec(q * q - 1).sqrt()).ln()


def _hp_atanh(args, digits):
    q = args[0]
    if abs(q) >= 1:
        raise ValueError("math domain error")
    with _ctx(digits + GUARD + _tiny(q) + 2):
        return _dec((1 + q) / (1 - q)).ln() / 2


def _hp_hypot(args, digits):
    with _ctx(digits + GUARD):
        return _dec(sum((a * a for a in args), Fraction(0))).sqrt()


def _hp_erf(args, digits):
    """2/sqrt(pi) * exp(-x^2) * sum 2^n x^(2n+1) / (1*3*...*(2n+1)): positive terms, no cancellation."""
    q = args[0]
    a = abs(q)
    if a * a > 2.31 * (digits + GUARD) + 5:         # 1 - |erf| < 10**-(digits + GUARD)
        return Decimal(1 if q > 0 else -1)
    prec = digits + GUARD + 2
    with _ctx(prec):
        x = _dec(a)
        x2 = x * x
        s, term, n, last = x, x, 0, None
        while s != last:
            n += 1
            last, term = s, term * 2 * x2 / (2 * n + 1)
            s = s + term
        return 2 * s * (-x2).exp() / _pi(prec).sqrt() * (-1 if q < 0 else 1)


_BERNOULLI = [Fraction(1)]


def _bernoulli(n: int) -> Fraction:
    while len(_BERNOULLI) <= n:
        m = len(_BERNOULLI)
        _BERNOULLI.append(-sum(math.comb(m + 1, k) * _BERNOULLI[k] for k in range(m)) / (m + 1))
    return _BERNOULLI[n]


def _hp_gamma(args, digits):
    """Stirling's series at z = q + N >= 2 * (digits + GUARD), divided by the exact product q (q+1) ... (q+N-1)."""
    q = args[0]
    if q.denominator == 1 and q <= 0:
        raise ValueError("math domain error")
    if q.denominator == 1 and q <= 1000:
        return Decimal(math.factorial(int(q) - 1))
    prec = digits + GUARD + 5
    shift = max(0, math.ceil(2 * (digits + GUARD) - q))
    product = math.prod((q + k for k in range(shift)), start=Fraction(1))
    with _ctx(prec):
        z = _dec(q + shift)
        lg = (z - Decimal("0.5")) * z.ln() - z + (2 * _pi(prec)).ln() / 2
        zk, k, last = z, 1, None
        while lg != last and k < 4 * prec:
            last = lg
            lg = lg + _dec(_bernoulli(2 * k)) / (2 * k * (2 * k - 1)) / zk
            zk, k = zk * z * z, k + 1
        return lg.exp() / _dec(product)


PRECISE = {"sqrt": _hp_sqrt, "exp": _hp_exp, "log": _hp_log, "log2": _hp_log_base(2), "log10": _hp_log_base(10),
       **{n: _hp_trig(n) for n in ("sin", "cos", "tan", "sec", "csc", "cot")},
       "asin": _hp_asin, "acos": _hp_acos, "atan": _hp_atan, "atan2": _hp_atan2,
       **{n: _hp_hyperbolic(n) for n in ("sinh", "cosh", "tanh")},
       "asinh": _hp_asinh, "acosh": _hp_acosh, "atanh": _hp_atanh, "hypot": _hp_hypot,
       "erf": _hp_erf, "gamma": _hp_gamma}
_ARITY = {"log": (1, 2), "atan2": (2,), "hypot": None}       # None: any number; otherwise 1
EXACT_FUNCS = set(_EXACT_FUNCS)   # functions evaluated on exact arguments (exprs keeps the one list)
_ARGS = [["var", f"\0{i}"] for i in range(64)]


def _hp_const(name: str, digits: int) -> Fraction:
    prec = digits + GUARD
    with _ctx(prec):
        if name in ("pi", "tau"):
            return Fraction(_pi(prec) * (2 if name == "tau" else 1))
        if name in ("E", "e"):
            return Fraction(Decimal(1).exp())
    raise _Undecided(f"{name} has no rational approximation")


def _too_big(v) -> bool:
    v = Fraction(v)
    return max(abs(v.numerator).bit_length(), v.denominator.bit_length()) > MAX_BITS


def exact_value(tree, env: dict, digits: int | None = None):
    """The value of an op tree at a rational point, every arithmetic step exact (fractions).

    A step that has no rational value (a transcendental call, pi, a fractional power, a float
    literal) raises ``_Inexact``; with ``digits`` it is computed to that many significant digits
    instead, and those steps are then the only rounding in the result. Operators keep the
    semantics of ``exprs.evaluate``: each node is handed to it with exact arguments.
    """
    if isinstance(tree, str):
        raise EvalError(f"unbound pattern variable {tree}")
    head = tree[0]
    if head == "var":
        if tree[1] not in env:
            raise UnknownName(tree[1])
        return env[tree[1]]
    if head in ("int", "bool"):
        return tree[1]
    if head == "float":
        if float(tree[1]).is_integer():
            return Fraction(tree[1])
        if digits is None:
            raise _Inexact("a float literal")
        return Fraction(repr(tree[1]))
    if head == "const":
        if digits is None:
            raise _Inexact(tree[1])
        return _hp_const(tree[1], digits)
    if head == "SUM":                       # a finite sum: every term exact, the bound variable bound per term
        sign, rng = sum_terms(exact_value(tree[2], env, digits), exact_value(tree[3], env, digits))
        total = Fraction(0)
        for k in rng:
            total += exact_value(tree[4], {**env, tree[1][1]: Fraction(k)}, digits)
        return sign * total
    args = [exact_value(a, env, digits) for a in tree[(2 if head == "FN" else 1):]]
    if head == "FN" and tree[1] in PRECISE:
        if digits is None:
            raise _Inexact(tree[1])
        arity = _ARITY.get(tree[1], (1,))
        if arity is not None and len(args) not in arity:
            raise TypeError(f"{tree[1]} takes {arity} arguments")
        return Fraction(PRECISE[tree[1]]([Fraction(a) for a in args], digits))
    if head == "POW" and len(args) == 2:
        a, b = (Fraction(x) for x in args)
        if b.denominator != 1:
            if digits is None:
                raise _Inexact("a fractional power")
            if not a:
                if b > 0:
                    return Fraction(0)
                raise ZeroDivisionError("0 to a negative power")
            if a < 0:
                raise ValueError("fractional power of a negative number")
            with _ctx(digits + GUARD + max(0, _mag(b)) + 2):
                return Fraction((_dec(b) * _dec(a).ln()).exp())
        if a and abs(b.numerator) <= 4096 and max(abs(a.numerator).bit_length(),
                                                  a.denominator.bit_length()) * abs(b.numerator) > MAX_BITS:
            if digits is None:
                raise _Inexact("a power too large to keep exact")
            with _ctx(digits + GUARD + 2):
                return Fraction(_dec(a) ** int(b))
    node = [head, *tree[1:2]] if head == "FN" else [head]
    names = _ARGS[:len(args)] if len(args) <= len(_ARGS) else [["var", f"\0{i}"] for i in range(len(args))]
    v = evaluate(node + names, {n[1]: a for n, a in zip(names, args)}, "fraction")
    if isinstance(v, (int, Fraction)):            # bool is an int
        if not _too_big(v):
            return v
        if digits is None:
            raise _Inexact("a value too large to keep exact")
        with _ctx(digits + GUARD):
            return Fraction(_dec(v))
    if digits is None:
        raise _Inexact(head)
    raise _NoPreciseForm(tree[1] if head == "FN" else head)


def _rational(tree) -> bool:
    """No step of the tree is known to leave the rationals (fractional powers are only found by evaluating)."""
    if not isinstance(tree, list):
        return True
    head = tree[0]
    if head == "const" or (head == "FN" and tree[1] in PRECISE) or (
            head == "float" and not float(tree[1]).is_integer()):
        return False
    if head in ("var", "int", "bool", "float"):
        return True
    return all(_rational(a) for a in tree[(2 if head == "FN" else 1):])


def _rational_point(env: dict) -> dict:
    """The same point with every float as the exact binary fraction it is."""
    return {k: Fraction(v) if isinstance(v, float) else v for k, v in env.items()}


def _settle(lhs, rhs, env: dict):
    """Both forms at rising precision until two successive precisions agree: (a, b, digits)."""
    prev = None
    for digits in DIGITS:
        cur = (exact_value(lhs, env, digits), exact_value(rhs, env, digits))
        if prev is not None and all(abs(c - p) <= SETTLED * max(1, abs(c)) for c, p in zip(cur, prev)):
            return cur[0], cur[1], digits
        prev = cur
    raise _Undecided(f"{DIGITS[-2]} and {DIGITS[-1]} digits still disagree")


def compare(lhs, rhs, env: dict, mode: str, exact: bool = True) -> tuple[str, object, object, str]:
    """Both forms at one point: (outcome, source value, target value, how it was decided).

    outcome: agree | differ | outside (not in the domain here) | undecided (high precision did not settle).
    how: exact (rational arithmetic) | float (the float screen agreed, or no precise form exists) | N digits.
    ``exact=False`` skips the exact attempt (a form is known to be transcendental).
    """
    if exact:
        try:
            point = _rational_point(env)
            a, b = exact_value(lhs, point), exact_value(rhs, point)
            return ("agree" if a == b else "differ"), a, b, "exact"
        except _Inexact:
            pass
        except OUTSIDE:
            return "outside", None, None, "exact"
    try:
        a, b = evaluate(lhs, env, mode), evaluate(rhs, env, mode)
    except OUTSIDE:
        return "outside", None, None, "float"
    if isinstance(a, complex) or isinstance(b, complex):
        return "outside", a, b, "float"
    try:
        if math.isnan(float(a)) or math.isinf(float(a)) or math.isnan(float(b)) or math.isinf(float(b)):
            return "outside", a, b, "float"
    except OverflowError:
        return "outside", a, b, "float"
    if ((a == b) if mode == "int" and not isinstance(a, float) and not isinstance(b, float) else _close(a, b)):
        return "agree", a, b, "float"
    try:
        qa, qb, digits = _settle(lhs, rhs, _rational_point(env))
    except _NoPreciseForm:
        return "differ", a, b, "float"          # nothing more precise exists: the float verdict stands
    except _Undecided:
        return "undecided", a, b, "float"
    except OUTSIDE:
        return "outside", a, b, "float"         # exactly, the point is not in the domain
    return ("agree" if _close_exact(qa, qb) else "differ"), qa, qb, f"{digits} digits"


def _show(v, sig: int = 20) -> str:
    if isinstance(v, Fraction) and v.denominator != 1:
        with _ctx(sig):
            return str(+_dec(v))
    return str(v)


def _key(v):
    try:
        return round(float(v), 9)
    except OverflowError:
        return v


def check_examples(card, lhs, rhs, mode) -> dict:
    out = {"total": 0, "agree": 0, "incomplete": 0, "disagree": 0}
    vars_ = variables(lhs) | variables(rhs)
    for ex in card.get("examples") or []:
        inp = ex.get("input") if isinstance(ex, dict) else None
        if not isinstance(inp, dict):
            continue
        out["total"] += 1
        if not vars_ <= set(inp):
            out["incomplete"] += 1
            continue
        env = {k: (Fraction(v) if mode == "int" and isinstance(v, (int, float)) else v) for k, v in inp.items()}
        outcome = compare(lhs, rhs, env, mode)[0]
        if outcome in ("outside", "undecided"):
            out["incomplete"] += 1
            continue
        out["agree" if outcome == "agree" else "disagree"] += 1
    return out


def verify(card, seed: int | None = None, samples: int = 40, symbolic: bool = True) -> dict:
    seed = V.fresh_seed() if seed is None else seed
    dom = card.get("domain")
    try:
        lhs, rhs = parse(card["source_form"]), parse(card["target_form"])
    except (ParseError, KeyError) as exc:
        return {"verdict": "unparsable", "detail": str(exc), "seed": seed}
    cond = None
    cond_note = None
    if card.get("condition"):
        try:
            cond = parse(card["condition"])
        except ParseError:
            cond_note = "condition is prose; not applied"
    mode = "int" if dom in INT_DOMAINS else "real"
    lo, hi = INT_DOMAINS.get(dom) or REAL_DOMAINS.get(dom) or (-3.0, 3.0)
    vars_ = sorted(variables(lhs) | variables(rhs))
    rng = random.Random(f"{seed}:{card.get('name')}")
    if cond is not None and variables(cond) - set(vars_):
        cond_note = f"condition names {sorted(variables(cond) - set(vars_))} that the forms do not; not applied"
        cond = None
    exact = _rational(lhs) and _rational(rhs)
    valid, bad, distinct = 0, None, set()
    decided = {"exact": 0, "float": 0, "high_precision": 0}
    artefacts = undecided = 0
    for _ in range(samples * 4):
        if valid >= samples:
            break
        env = {v: (rng.randint(int(lo), int(hi)) if mode == "int" else rng.uniform(lo, hi)) for v in vars_}
        try:
            if cond is not None and not evaluate(cond, env, mode):
                continue
        except OUTSIDE:
            continue
        outcome, a, b, how = compare(lhs, rhs, env, mode, exact)
        if outcome == "outside":
            continue
        if outcome == "undecided":
            undecided += 1
            continue
        valid += 1
        decided["high_precision" if how.endswith("digits") else how] += 1
        artefacts += outcome == "agree" and how.endswith("digits")
        distinct.add(_key(a))
        if outcome == "differ":
            bad = {"env": {k: (str(v) if isinstance(v, Fraction) else v) for k, v in env.items()},
                   "source": _show(a), "target": _show(b), "decided_by": how}
            break
    res = {"seed": seed, "mode": mode, "valid_points": valid, "distinct_source_values": len(distinct),
           "decided": {k: n for k, n in decided.items() if n}, "examples": check_examples(card, lhs, rhs, mode)}
    if artefacts:
        res["rounding_artefacts"] = artefacts
    if undecided:
        res["undecided_points"] = undecided
    if cond_note:
        res["condition_note"] = cond_note
    if bad is not None:
        res["verdict"] = "inconclusive" if cond_note else "refuted"
        res["counterexample"] = bad
    elif valid < MIN_VALID:
        res["verdict"] = "inconclusive"
        res["detail"] = f"only {valid} points inside the domain"
    else:
        res["verdict"] = "verified"
    if symbolic and res["verdict"] in ("verified", "inconclusive") and probes.probe(
            {"kind": "python_module", "module": "sympy"})[0]:
        res["symbolic"] = _sympy_check(card["source_form"], card["target_form"])
        if res["symbolic"] == "proved" and res["verdict"] == "verified":
            res["verdict"] = "proved_symbolic"
    return res


def _sympy_check(src: str, dst: str) -> str:
    from .witness import TimeLimit, time_limit
    try:
        with time_limit(5):
            import sympy  # noqa: PLC0415 -- optional capability, probed by the caller
            diff = sympy.simplify(sympy.sympify(src) - sympy.sympify(dst))
            return "proved" if diff == 0 else "not_simplified_to_zero"
    except TimeLimit:
        return "timeout"
    except Exception as exc:  # noqa: BLE001 -- sympy failures are a capability result, logged in the verdict
        return f"error:{type(exc).__name__}"
