"""tiers — what each claim's evidence is worth (law CM46; the research handover's witness tiers, agenda R3).

  tiers      every claim carries one: proof (a kernel-checked proof, or a finite witness sized by a theorem for the
             claim's class), probabilistic (with its error bound), bounded (exhaustive within stated bounds) or
             sample (seeded inputs).
  classes    read from the lifted IR (``shape``), never assumed:
               poly     straight-line integer arithmetic: +, -, *, NEG, SQUARE, powers by a constant, and division by
                        a constant that is exact on every integer (checked over all residues). The result is a
                        polynomial; a polynomial of degree d_i in variable i that vanishes on a grid S_1 x ... x S_k
                        with |S_i| > d_i is zero, so the grid decides equality over Z^k.
               cfinite  one counted loop ``for i in range(S, n + t)`` whose body updates its state affinely with
                        constant coefficients and adds polynomials in i and the other inputs: in n the result is a
                        C-finite sequence of order at most the state's dimension plus the monomials of i it adds
                        (Cayley-Hamilton), and a polynomial in each other input of bounded degree. Two C-finite
                        sequences of orders D1 and D2 that agree on D1 + D2 consecutive terms agree from there on
                        (their difference satisfies a recurrence of order D1 + D2).
               guards   a leading ``if n <= c: return P`` (or <, >=, >) splits n's line into regions, each decided
                        on its own: a bounded region by every point, a left-unbounded one by a polynomial's degree.
  witness    ``prove`` runs both forms on the points the classes need, with Python's exact integers. All agree:
             tier proof, with the class and the theorem named. One disagreement is a counterexample.
  census     the tier of every claim in the store, read from the cards: theorems (proof when Lean's kernel checked
             them), rewrite rules (as strong as the theorem they were learned from), redefinitions (sampled), the
             four sources (their obligations' tiers).

Honest limits (L1): only the classes above. Recursion, while loops, bit operations, modulo, comparisons used as
values, floats, and loops whose coefficients depend on the inputs stay sampled. The class is read from the lifted
IR while the witness runs the Python form, so the lifter's faithfulness on these constructs is assumed (the
conformance section witnesses it). Machine-integer forms (C, Rust) are not Z: these witnesses say nothing about
them, since the grid lemma and Schwartz-Zippel need an integral domain. The finite-witness theorems are from the
literature; their Lean proofs (handover T7) are not in formal/GodelCore yet.
"""
from __future__ import annotations

import itertools
import math
import re
from collections import Counter
from fractions import Fraction

TIERS = ("proof", "probabilistic", "bounded", "sample")
MAX_POINTS = 20000
MAX_POW = 12
MAX_RESIDUES = 50000
BOUNDED_REGION = 64


# -- exact polynomials over Q -------------------------------------------------------------------------------------
class Poly:
    """A polynomial with rational coefficients: {monomial: coefficient}, a monomial a sorted tuple of (var, exp)."""
    __slots__ = ("t",)

    def __init__(self, t=None):
        self.t = {m: Fraction(c) for m, c in (t or {}).items() if c != 0}

    @staticmethod
    def const(c) -> "Poly":
        return Poly({(): Fraction(c)})

    @staticmethod
    def var(v: str) -> "Poly":
        return Poly({((v, 1),): Fraction(1)})

    def __add__(self, o: "Poly") -> "Poly":
        t = dict(self.t)
        for m, c in o.t.items():
            t[m] = t.get(m, 0) + c
        return Poly(t)

    def __neg__(self) -> "Poly":
        return Poly({m: -c for m, c in self.t.items()})

    def __sub__(self, o: "Poly") -> "Poly":
        return self + (-o)

    def __mul__(self, o: "Poly") -> "Poly":
        t: dict = {}
        for m1, c1 in self.t.items():
            for m2, c2 in o.t.items():
                e = Counter(dict(m1))
                e.update(dict(m2))
                m = tuple(sorted(e.items()))
                t[m] = t.get(m, 0) + c1 * c2
        return Poly(t)

    def pow(self, k: int) -> "Poly":
        out = Poly.const(1)
        for _ in range(k):
            out = out * self
        return out

    def vars(self) -> set[str]:
        return {v for m in self.t for v, _ in m}

    def degree(self, v: str) -> int:
        return max((dict(m).get(v, 0) for m in self.t), default=0)

    def is_const(self) -> bool:
        return all(m == () for m in self.t)

    def value(self) -> Fraction:
        return self.t.get((), Fraction(0))

    def subst(self, env: dict[str, "Poly"]) -> "Poly":
        out = Poly()
        for m, c in self.t.items():
            term = Poly.const(c)
            for v, e in m:
                term = term * (env[v].pow(e) if v in env else Poly.var(v).pow(e))
            out = out + term
        return out

    def scale(self, f: Fraction) -> "Poly":
        return Poly({m: c * f for m, c in self.t.items()})

    def at(self, env: dict[str, int]) -> Fraction:
        return sum((c * math.prod(Fraction(env[v]) ** e for v, e in m) for m, c in self.t.items()), Fraction(0))

    def affine_in(self, vs: set[str]) -> tuple[dict[str, Fraction], "Poly"] | None:
        """(constant coefficient of each var in vs, the rest), when the polynomial is affine in vs with constant
        coefficients; None otherwise."""
        coef: dict[str, Fraction] = {}
        rest: dict = {}
        for m, c in self.t.items():
            hit = [(v, e) for v, e in m if v in vs]
            if not hit:
                rest[m] = c
            elif len(m) == 1 and hit[0][1] == 1:
                coef[hit[0][0]] = coef.get(hit[0][0], 0) + c
            else:
                return None
        return coef, Poly(rest)


def _exact_division(p: Poly, c: int) -> Poly | None:
    """p / c when c divides p(x) for every integer x (checked over all residues), else None."""
    den = 1
    for coeff in p.t.values():
        den = den * coeff.denominator // math.gcd(den, coeff.denominator)
    q = p.scale(Fraction(den))                       # integer coefficients
    mod, vs = c * den, sorted(p.vars())
    if mod ** len(vs) > MAX_RESIDUES:
        return None
    for xs in itertools.product(range(mod), repeat=len(vs)):
        if q.at(dict(zip(vs, xs))) % mod != 0:
            return None
    return p.scale(Fraction(1, c))


def expr(e, env: dict) -> Poly | None:
    """An IR expression as a polynomial over the variables in env, or None when it is not one."""
    if not isinstance(e, list) or not e:
        return None
    head = e[0]
    if head == "int":
        return Poly.const(int(e[1]))
    if head == "var":
        v = env.get(e[1])
        return v if isinstance(v, Poly) else None
    args = [expr(a, env) for a in e[1:]] if head != "POW" and head != "FLOORDIV" else None
    if head in ("ADD", "SUB", "MUL") and len(e) == 3:
        if None in args:
            return None
        return args[0] + args[1] if head == "ADD" else args[0] - args[1] if head == "SUB" else args[0] * args[1]
    if head == "NEG" and len(e) == 2 and args[0] is not None:
        return -args[0]
    if head == "SQUARE" and len(e) == 2 and args[0] is not None:
        return args[0] * args[0]
    if head == "POW" and len(e) == 3:
        base, k = expr(e[1], env), expr(e[2], env)
        if base is None or k is None or not k.is_const() or k.value().denominator != 1 or not 0 <= k.value() <= MAX_POW:
            return None
        return base.pow(int(k.value()))
    if head == "FLOORDIV" and len(e) == 3:
        num, d = expr(e[1], env), expr(e[2], env)
        if num is None or d is None or not d.is_const() or d.value().denominator != 1 or d.value() <= 0:
            return None
        return _exact_division(num, int(d.value()))
    return None


# -- the class of a lifted function -------------------------------------------------------------------------------
_CMP = {"CMP_LE": "le", "CMP_LT": "lt", "CMP_GE": "ge", "CMP_GT": "gt"}
_FLIP = {"le": "ge", "lt": "gt", "ge": "le", "gt": "lt"}


def _guard(cond, params: set[str]):
    """(param, op, constant) for `param <op> constant` (either order), else None."""
    if not (isinstance(cond, list) and len(cond) == 3 and cond[0] in _CMP):
        return None
    op, a, b = _CMP[cond[0]], cond[1], cond[2]
    if a[:1] == ["int"] and b[:1] == ["var"]:
        a, b, op = b, a, _FLIP[op]
    if a[:1] == ["var"] and a[1] in params and b[:1] == ["int"]:
        return a[1], op, int(b[1])
    return None


def _cut(lo, hi, op: str, c: int):
    """The region the guard takes (lo, hi) and the region left, as inclusive integer bounds (None: unbounded)."""
    take = {"le": (None, c), "lt": (None, c - 1), "ge": (c, None), "gt": (c + 1, None)}[op]
    left = {"le": (c + 1, None), "lt": (c, None), "ge": (None, c - 1), "gt": (None, c)}[op]

    def meet(a, b):
        l = a[0] if b[0] is None else b[0] if a[0] is None else max(a[0], b[0])
        h = a[1] if b[1] is None else b[1] if a[1] is None else min(a[1], b[1])
        return (l, h)
    return meet((lo, hi), take), meet((lo, hi), left)


def _empty(r) -> bool:
    return r[0] is not None and r[1] is not None and r[0] > r[1]


def shape(fn: dict) -> dict:
    """The class of one lifted function: {"ok": True, "n": designated parameter or None, "segments": [{"lo", "hi",
    "kind": "poly"|"cfinite", "poly" | "order", "start", "degrees"}]} or {"ok": False, "why": ...}."""
    params = [p["name"] for p in fn.get("params") or []]
    if any(p.get("type") not in ("int", None) for p in fn.get("params") or []):
        return {"ok": False, "why": "not every input is an integer"}
    pset = set(params)
    env: dict = {p: Poly.var(p) for p in params}
    n, region, segments, loop_seen = None, (None, None), [], False
    body = list(fn.get("body") or [])
    i = 0
    while i < len(body):
        st = body[i]
        k = st.get("k")
        if k == "assign":
            v = expr(st["value"], env)
            if v is None:
                return {"ok": False, "why": f"{st['target']} is not a polynomial"}
            env[st["target"]] = v
        elif k == "if":
            g = _guard(st.get("cond"), pset)
            then = st.get("then") or []
            if g is None or st.get("else") or len(then) != 1 or then[0].get("k") != "return" or loop_seen:
                return {"ok": False, "why": "a branch other than a leading guard on one input"}
            if n is not None and g[0] != n:
                return {"ok": False, "why": "guards on two different inputs"}
            n = g[0]
            v = expr(then[0]["value"], env)
            if v is None:
                return {"ok": False, "why": "a guard returns something other than a polynomial"}
            take, region = _cut(region[0], region[1], g[1], g[2])
            if not _empty(take):
                segments.append({"lo": take[0], "hi": take[1], "kind": "poly", "poly": v})
            if _empty(region):
                return {"ok": True, "n": n, "segments": segments}
        elif k == "for_range":
            if loop_seen:
                return {"ok": False, "why": "more than one loop"}
            loop_seen = True
            r = _loop(st, body[i + 1:], env, pset, n)
            if not r["ok"]:
                return r
            n = r["n"]
            for seg in r["segments"]:
                lo = seg["lo"] if region[0] is None else region[0] if seg["lo"] is None else max(region[0], seg["lo"])
                hi = seg["hi"] if region[1] is None else region[1] if seg["hi"] is None else min(region[1], seg["hi"])
                if not _empty((lo, hi)):
                    segments.append({**seg, "lo": lo, "hi": hi})
            return {"ok": True, "n": n, "segments": segments}
        elif k == "return":
            v = expr(st["value"], env)
            if v is None:
                return {"ok": False, "why": "the result is not a polynomial"}
            segments.append({"lo": region[0], "hi": region[1], "kind": "poly", "poly": v})
            return {"ok": True, "n": n, "segments": segments}
        else:
            return {"ok": False, "why": f"a {k} statement"}
        i += 1
    return {"ok": False, "why": "no return"}


def _loop(st: dict, after: list, env: dict, pset: set[str], n0) -> dict:
    """The counted loop and what follows it: an empty-loop polynomial region and a C-finite region in n."""
    start, stop, step = expr(st.get("start"), env), expr(st.get("stop"), env), expr(st.get("step"), env)
    if start is None or stop is None or step is None or not start.is_const() or step.t != {(): 1}:
        return {"ok": False, "why": "a loop that does not count up by one from a constant"}
    pv = [v for v in stop.vars() if v in pset]
    if len(pv) != 1 or stop.degree(pv[0]) != 1 or stop.affine_in({pv[0]}) is None:
        return {"ok": False, "why": "a loop bound that is not one input plus a constant"}
    n = pv[0]
    coef, rest = stop.affine_in({n})
    if coef.get(n) != 1 or not rest.is_const() or (n0 is not None and n0 != n):
        return {"ok": False, "why": "a loop bound that is not one input plus a constant"}
    kappa = rest.value() - start.value()
    if kappa.denominator != 1:
        return {"ok": False, "why": "a fractional loop bound"}
    kappa = int(kappa)
    assigned = {b.get("target") for b in st.get("body") or [] if b.get("k") == "assign"}
    if n in assigned or st["var"] in assigned:
        return {"ok": False, "why": "a loop body that assigns its bound or its counter"}
    # the state: what the body assigns and had a value before the loop (parameters included); what the body
    # assigns without a value before is a temporary, read only after it is written in the same pass
    state0 = {v: env[v] for v in assigned if isinstance(env.get(v), Poly)}
    if any(n in p.vars() for p in state0.values()):
        return {"ok": False, "why": "a loop whose start state depends on its own bound"}
    sym = {v: Poly.var("σ:" + v) for v in state0}
    fixed = {k: v for k, v in env.items() if isinstance(v, Poly) and k not in assigned}
    benv = {**fixed, **sym, st["var"]: start + Poly.var("ι")}
    for b in st.get("body") or []:
        if b.get("k") != "assign":
            return {"ok": False, "why": "a loop body with more than assignments"}
        v = expr(b["value"], benv)
        if v is None:
            return {"ok": False, "why": f"{b['target']} is not updated by a polynomial"}
        benv[b["target"]] = v
    svars = {"σ:" + v for v in state0}
    order, idx_deg, upd = len(state0), -1, {}
    for v in state0:
        new = benv.get(v, sym[v])
        split = new.affine_in(svars)
        if split is None:
            return {"ok": False, "why": f"{v} is not updated affinely with constant coefficients"}
        coef, add = split
        if n in add.vars():
            return {"ok": False, "why": "a loop body that uses its own bound"}
        upd[v] = (coef, add)
        if add.t:
            idx_deg = max(idx_deg, add.degree("ι"))
    order += idx_deg + 1
    degrees = Counter()
    for v, p0 in state0.items():
        for q in p0.vars():
            degrees[q] = max(degrees[q], p0.degree(q))
        for q in upd[v][1].vars() - {"ι"}:
            degrees[q] = max(degrees[q], upd[v][1].degree(q))
    # after the loop: assignments, then the result, affine in the final state with constant coefficients
    penv = {**fixed, **{v: Poly.var("σ:" + v) for v in state0}}
    result = None
    for a in after:
        if a.get("k") == "assign":
            v = expr(a["value"], penv)
            if v is None:
                return {"ok": False, "why": "what follows the loop is not a polynomial"}
            penv[a["target"]] = v
        elif a.get("k") == "return":
            result = expr(a["value"], penv)
            break
        else:
            return {"ok": False, "why": "what follows the loop is not straight-line"}
    if result is None:
        return {"ok": False, "why": "the result after the loop is not a polynomial"}
    split = result.affine_in(svars)
    if split is None:
        return {"ok": False, "why": "the result is not affine in the loop's state"}
    _, tail = split
    order += tail.degree(n) + 1 if n in tail.vars() else 0
    for q in tail.vars() - {n}:
        degrees[q] = max(degrees[q], tail.degree(q))
    empty = result.subst({"σ:" + v: p for v, p in state0.items()})
    # the loop runs n + kappa times: none while n <= -kappa; from n = -kappa the C-finite form holds
    return {"ok": True, "n": n, "segments": [
        {"lo": None, "hi": -kappa - 1, "kind": "poly", "poly": empty},
        {"lo": -kappa, "hi": None, "kind": "cfinite", "order": order, "start": -kappa,
         "degrees": dict(degrees)}]}


# -- sized witnesses ------------------------------------------------------------------------------------------------
def domain_bounds(pre: str | None, params: list[str]) -> dict[str, list] | None:
    """{param: [lo, hi]} from a precondition of `x >= c` / `x > c` / `x <= c` / `x < c` joined by `and`; None when
    it says something else."""
    out = {p: [None, None] for p in params}
    if not pre:
        return out
    for part in re.split(r"\s+and\s+", pre.strip()):
        m = re.fullmatch(r"\s*([A-Za-z_]\w*)\s*(>=|>|<=|<)\s*(-?\d+)\s*", part)
        if not m or m.group(1) not in out:
            return None
        v, op, c = m.group(1), m.group(2), int(m.group(3))
        lo, hi = out[v]
        if op in (">=", ">"):
            c = c if op == ">=" else c + 1
            out[v][0] = c if lo is None else max(lo, c)
        else:
            c = c if op == "<=" else c - 1
            out[v][1] = c if hi is None else min(hi, c)
    return out


def _poly_degrees(seg: dict, n) -> dict:
    if seg["kind"] == "poly":
        return {q: seg["poly"].degree(q) for q in seg["poly"].vars()}
    return dict(seg["degrees"])


def plan(fa: dict, fb: dict, params_a: list[str], params_b: list[str], bounds: dict) -> dict:
    """The points (argument tuples, by position) that decide fa == fb on the domain, and the theorems used; or
    {"ok": False, "why"}."""
    if not (fa.get("ok") and fb.get("ok")):
        return {"ok": False, "why": fa.get("why") or fb.get("why")}
    pos_a = params_a.index(fa["n"]) if fa["n"] else None
    pos_b = params_b.index(fb["n"]) if fb["n"] else None
    if pos_a is not None and pos_b is not None and pos_a != pos_b:
        return {"ok": False, "why": "the two forms count along different inputs"}
    pos = pos_a if pos_a is not None else pos_b
    names = params_a
    rename_b = dict(zip(params_b, params_a))

    def segs(f, rename):
        out = []
        for s in f["segments"]:
            s = dict(s)
            if s["kind"] == "poly":
                s["poly"] = s["poly"].subst({k: Poly.var(v) for k, v in rename.items() if k != v})
            else:
                s["degrees"] = {rename.get(k, k): d for k, d in s["degrees"].items()}
            out.append(s)
        return out
    sa, sb = segs(fa, {}), segs(fb, rename_b)
    deg = Counter()
    for s in sa + sb:
        for q, d in _poly_degrees(s, None).items():
            if pos is None or q != names[pos]:
                deg[q] = max(deg[q], d)
    others = [p for j, p in enumerate(names) if j != pos]
    grids = []
    for p in others:
        lo, hi = bounds[p]
        base = lo if lo is not None else (hi - deg[p] if hi is not None else 0)
        vals = list(range(base, base + deg[p] + 1))
        if hi is not None and vals[-1] > hi:
            return {"ok": False, "why": f"the domain of {p} is too small for its degree"}
        grids.append(vals)
    theorems = []
    if pos is None:
        pts = list(itertools.product(*grids))
        theorems.append("grid lemma: a polynomial of degree d_i in x_i vanishing on a grid with d_i + 1 values "
                        "per variable is zero")
        return _points(pts, theorems)
    nname = names[pos]
    lo_n, hi_n = bounds[nname]
    cuts = {lo_n} if lo_n is not None else set()
    for s in sa + sb:
        if s["lo"] is not None:
            cuts.add(s["lo"])
        if s["hi"] is not None:
            cuts.add(s["hi"] + 1)
    edges = sorted(c for c in cuts if (lo_n is None or c >= lo_n) and (hi_n is None or c <= hi_n + 1))
    regions, prev = [], lo_n
    for c in edges:
        if prev is None or c > prev:
            regions.append((prev, c - 1))
        prev = c
    regions.append((prev, hi_n))
    regions = [r for r in regions if not _empty(r) and not (r[0] is not None and lo_n is not None and r[0] < lo_n)]

    def covering(ss, r):
        for s in ss:
            if (s["lo"] is None or (r[0] is not None and s["lo"] <= r[0])) and \
                    (s["hi"] is None or (r[1] is not None and s["hi"] >= r[1])):
                return s
        return None
    ns: list[int] = []
    for r in regions:
        a, b = covering(sa, r), covering(sb, r)
        if a is None or b is None:
            return {"ok": False, "why": f"no single class covers n in {r}"}
        if r[0] is not None and r[1] is not None and r[1] - r[0] < BOUNDED_REGION:
            ns += list(range(r[0], r[1] + 1))
            theorems.append(f"every n in [{r[0]}, {r[1]}]")
            continue
        if r[0] is not None:                       # [lo, inf) (or a long bounded stretch): C-finite agreement
            da = a["order"] if a["kind"] == "cfinite" else a["poly"].degree(nname) + 1
            db = b["order"] if b["kind"] == "cfinite" else b["poly"].degree(nname) + 1
            for s in (a, b):
                if s["kind"] == "cfinite" and s["start"] > r[0]:
                    return {"ok": False, "why": "a recurrence that starts after its region"}
            last = r[0] + da + db - 1 if r[1] is None else min(r[1], r[0] + da + db - 1)
            ns += list(range(r[0], last + 1))
            theorems.append(f"C-finite agreement on n >= {r[0]}: orders {da} and {db}, {da + db} terms")
            continue
        if a["kind"] != "poly" or b["kind"] != "poly":
            return {"ok": False, "why": "a recurrence on a left-unbounded region"}
        e = max(a["poly"].degree(nname), b["poly"].degree(nname))
        top = r[1] if r[1] is not None else 0
        ns += list(range(top - e, top + 1))
        theorems.append(f"polynomial of degree {e} in n on n <= {top}: {e + 1} points")
    if others:
        theorems.append("grid lemma in " + ", ".join(f"{p} (degree {deg[p]})" for p in others))
    pts = []
    for nv in sorted(set(ns)):
        for rest in itertools.product(*grids):
            t = list(rest)
            t.insert(pos, nv)
            pts.append(tuple(t))
    return _points(pts, theorems)


def _points(pts: list[tuple], theorems: list[str]) -> dict:
    if len(pts) > MAX_POINTS:
        return {"ok": False, "why": f"{len(pts)} points is more than {MAX_POINTS}"}
    return {"ok": True, "points": pts, "theorems": theorems}


def prove(ctx, card, ref: dict, form: dict, timeout: float = 2.0) -> dict | None:
    """Tier proof for `form == ref` on the card's precondition, when both forms' classes size a witness and every
    point agrees; a refutation when a point disagrees; None when no class applies."""
    from . import values as V
    from . import witness as W
    from .frontend_python import lift_source

    def entry(f):
        lifted = [lf for lf in lift_source(f["code"], ctx.ops) if lf.ok]
        return next((lf.ir for lf in lifted if lf.name == f.get("entry")), lifted[0].ir if lifted else None)
    try:
        fa, fb = entry(ref), entry(form)
    except Exception:  # noqa: BLE001 -- a form the lifter cannot read has no class
        return None
    if fa is None or fb is None:
        return None
    pa, pb = [p["name"] for p in fa.get("params") or []], [p["name"] for p in fb.get("params") or []]
    if len(pa) != len(pb):
        return None
    pre = card.get("precondition")
    bounds = domain_bounds(pre if isinstance(pre, str) else None, pa)
    if bounds is None:
        return None
    pl = plan(shape(fa), shape(fb), pa, pb, bounds)
    if not pl["ok"]:
        return None
    try:
        f_ref, f_form = W.python_callable(ctx, ref, card), W.python_callable(ctx, form, card)
    except Exception:  # noqa: BLE001
        return None
    for args in pl["points"]:
        try:
            with W.time_limit(timeout):
                a, b = f_ref(*args), f_form(*args)
        except Exception:  # noqa: BLE001 -- a point the forms cannot run: no conclusion
            return None
        if not V.same(a, b):
            return {"kind": "witness", "status": "refuted", "tier": "proof", "at": list(args), "values": [a, b]}
    return {"kind": "proof", "status": "proved", "tier": "proof", "by": "method/sized_witness",
            "points": len(pl["points"]), "theorems": pl["theorems"],
            "classes": [_summary(shape(fa)), _summary(shape(fb))]}


def _summary(sh: dict) -> str:
    parts = []
    for s in sh["segments"]:
        where = f"n in [{'-inf' if s['lo'] is None else s['lo']}, {'inf' if s['hi'] is None else s['hi']}]"
        if s["kind"] == "poly":
            parts.append(f"{where}: polynomial")
        else:
            parts.append(f"{where}: C-finite of order <= {s['order']}")
    return (f"along {sh['n']}: " if sh["n"] else "") + "; ".join(parts)


# -- the census ---------------------------------------------------------------------------------------------------
def tier_of(card, store=None) -> str | None:
    """The tier of the claim a card makes, from the evidence the card records; None when it makes no claim."""
    reg = card.registry
    if reg == "theorem":
        ok = card.get("status") == "proved" and any(p.get("ok") for p in card.get("proofs") or [])
        return "proof" if ok else "sample"
    if reg == "rewrite_rule":
        # a rule learned from a theorem is as strong as that theorem's proof
        for dep in card.get("depends_on") or []:
            th = store.get(dep) if store is not None and str(dep).startswith("theorem/") else None
            if th is not None and tier_of(th) == "proof":
                return "proof"
        return "sample"
    if reg == "redefinition":
        # numeric witnesses on seeded points; agreement under sympy is computer algebra, not a kernel's check
        return "sample"
    if reg == "transformation":
        return (card.get("evidence") or {}).get("tier") or "sample"
    return None


def claims(ctx) -> list[tuple[str, str | None]]:
    """(claim, tier) for every claim in the store, read from the cards alone."""
    out = []
    for reg in ("theorem", "rewrite_rule", "redefinition", "transformation"):
        for c in ctx.store.cards(reg):
            out.append((c.qualified, tier_of(c, ctx.store)))
    for d in ctx.store.cards("definition"):
        for i, o in enumerate(d.get("proof_obligations") or []):
            out.append((f"{d.qualified}#{i}", o.get("tier")))
    return out


def census(ctx) -> dict:
    """How many claims sit at each tier, by registry, and which claims carry no tier (law CM46)."""
    by: dict[str, Counter] = {}
    untiered = []
    for q, t in claims(ctx):
        reg = q.split("/", 1)[0]
        by.setdefault(reg, Counter())[t or "none"] += 1
        if t is None and reg == "definition":
            untiered.append(q)
    total = Counter()
    for c in by.values():
        total.update(c)
    return {"by_registry": {k: dict(v) for k, v in by.items()}, "total": dict(total),
            "proof": total.get("proof", 0), "claims": sum(total.values()), "untiered": untiered[:20],
            "untiered_count": len(untiered)}


__all__ = ["MAX_POINTS", "Poly", "TIERS", "census", "claims", "domain_bounds", "expr", "plan", "prove", "shape",
           "tier_of"]
