"""redefs — verify executable redefinitions (source_form == target_form) by seeded evaluation.

Pheros L34 asks for a witness and at least one agreeing example. Here every
executable redefinition is evaluated at seeded points of its domain:

  integer / nonneg_integer / modular_n   exact (ints and fractions)
  real / fp64 / symbolic_real / positive_real   floats, rel_tol 1e-7

Verdicts: verified (>= MIN_VALID valid points, all agree) · refuted (a
counterexample, with the seed to reproduce) · inconclusive (too few points
inside the domain, or a mismatch while the card's ``condition`` could not
be parsed -- the condition may exclude it) · unparsable.

The card's own ``examples`` are also re-evaluated; an example that does not
bind every variable is reported as incomplete (some auto-generated Pheros
cards carry such examples, which made their L34 check vacuous).

Optional capability: when the python module ``sympy`` is installed, a
time-boxed ``simplify(lhs - rhs) == 0`` upgrades a verdict to
``proved_symbolic``. sympy is never required.

Honest limits (L1): numeric agreement on sampled points is evidence, not
proof; floating-point cancellation can hide or fake tiny differences.
"""
from __future__ import annotations

import math
import random
from fractions import Fraction

from . import probes
from . import values as V
from .exprs import ParseError, UnknownName, evaluate, parse, variables

MIN_VALID = 8
REAL_TOL = 1e-7
INT_DOMAINS = {"integer": (-30, 30), "nonneg_integer": (0, 30), "modular_n": (-30, 30)}
REAL_DOMAINS = {"real": (-3.0, 3.0), "fp64": (-3.0, 3.0), "symbolic_real": (-3.0, 3.0), "positive_real": (0.05, 4.0)}


def _close(a, b) -> bool:
    if isinstance(a, complex) or isinstance(b, complex):
        return False
    fa, fb = float(a), float(b)
    if math.isnan(fa) or math.isnan(fb) or math.isinf(fa) or math.isinf(fb):
        return False
    return math.isclose(fa, fb, rel_tol=REAL_TOL, abs_tol=REAL_TOL)


def _num(text):
    try:
        return Fraction(str(text).strip())
    except (ValueError, ZeroDivisionError):
        try:
            return float(str(text).strip())
        except ValueError:
            return None


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
        try:
            a, b = evaluate(lhs, env, mode), evaluate(rhs, env, mode)
        except (ArithmeticError, ValueError, TypeError, UnknownName):
            out["incomplete"] += 1
            continue
        out["agree" if _close(a, b) else "disagree"] += 1
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
    valid, bad, distinct = 0, None, set()
    for _ in range(samples * 4):
        if valid >= samples:
            break
        env = {v: (rng.randint(int(lo), int(hi)) if mode == "int" else rng.uniform(lo, hi)) for v in vars_}
        try:
            if cond is not None and not evaluate(cond, env, mode):
                continue
            a = evaluate(lhs, env, mode)
            b = evaluate(rhs, env, mode)
        except (ArithmeticError, ValueError, TypeError, OverflowError, UnknownName, RecursionError):
            continue
        if isinstance(a, complex) or isinstance(b, complex):
            continue
        try:
            if math.isnan(float(a)) or math.isinf(float(a)) or math.isnan(float(b)) or math.isinf(float(b)):
                continue
        except OverflowError:
            continue
        valid += 1
        distinct.add(round(float(a), 9))
        ok = (a == b) if mode == "int" and not isinstance(a, float) and not isinstance(b, float) else _close(a, b)
        if not ok:
            bad = {"env": {k: (str(v) if isinstance(v, Fraction) else v) for k, v in env.items()},
                   "source": str(a), "target": str(b)}
            break
    res = {"seed": seed, "mode": mode, "valid_points": valid, "distinct_source_values": len(distinct),
           "examples": check_examples(card, lhs, rhs, mode)}
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
