"""theorems — mathematical statements as cards: witnessed by running them, proved by Lean, never overstated.

A theorem card states ``for all vars: hyp1 and ... and hypN implies concl``:

    {"name": "add_comm", "category": "theorem",
     "vars": [{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
     "hyps": [], "concl": ["eq", ["ADD", ["var", "a"], ["var", "b"]], ["ADD", ["var", "b"], ["var", "a"]]],
     "semantics": "card", "status": "proved", "evidence": {...}, "proofs": [...]}

Propositions are lists with lower-case heads -- eq ne lt le gt ge (on
terms), and or not imp iff, true false, and ``["bool", term]`` (a Bool term
is true). Terms are IR expressions (op cards). Variable types: ``int``,
``nat`` (an int >= 0), ``bool``, ``float``.

Two semantics, so a statement always means what its source meant:

* ``card``: the IR's reference semantics (Python integers; ``//`` floors).
  Rendered to Lean over ``Int`` with ``0 <= n`` hypotheses for nat
  variables, so the Lean statement is the same statement.
* ``lean``: statements imported from Lean keep Lean's operators as op cards
  with Lean's semantics (truncated Nat subtraction, Euclidean Int division,
  ``x / 0 = 0``); rendered back to Lean with ``Nat``/``Int`` binders.

Status ladder (crystallised knowledge, CM23): ``refuted`` (a counterexample,
shown) < ``conjecture`` (not checked) < ``witnessed`` (seeded checks
passed, anti-vacuity: enough inputs satisfied the hypotheses) < ``proved``
(the Lean kernel accepted a proof, or -- method ``exhaustive`` -- the
hypotheses bound every variable to a finite box of at most EXHAUSTIVE_MAX
points and every point was checked). A status is only raised by evidence.

Honest limits (L1): witnesses sample; they do not prove. Lean proofs use
core tactics only (decide, omega, grind, simp; no Mathlib), so nonlinear
or inductive facts may stay ``witnessed``. Statements calling card-language
functions are witnessed but not sent to Lean (codegen emits ``partial
def``, which proofs cannot unfold).
"""
from __future__ import annotations

import random
import re

from . import values as V
from .codegen import EmitGap, Emitter
from .logic import eval_expr

PROP_HEADS = ("eq", "ne", "lt", "le", "gt", "ge", "and", "or", "not", "imp", "iff", "true", "false", "bool", "dvd")
REL = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
LEAN_REL = {"eq": "=", "ne": "≠", "lt": "<", "le": "≤", "gt": ">", "ge": "≥"}
TACTICS = ("decide", "omega", "grind", "simp",
           "grind [Int.fmod_add_fdiv_mul, Int.fmod_nonneg_of_pos, Int.fmod_lt_of_pos, Int.fmod_def]")
DEEP_TACTICS = ("exact?", "refine ⟨?_, ?_⟩ <;> exact?")      # library search: slow, so only on request
HEARTBEATS = 100000
MIN_CHECKS = 30


class Undefined(ArithmeticError):
    pass


class TooBig(ArithmeticError):
    """An input whose evaluation would be astronomically large (e.g. 2 ** 2**40): skipped, not a counterexample."""


MAX_BITS = 1 << 16


def _guard_pow(fn):
    def g(a, b, *rest):
        if isinstance(b, int) and not isinstance(b, bool) and b > 0 and isinstance(a, int) and abs(a) > 1 \
                and b * abs(a).bit_length() > MAX_BITS:
            raise TooBig("power too large to evaluate")
        return fn(a, b, *rest)
    return g


def _guard_shift(fn):
    def g(a, b):
        if isinstance(b, int) and b > MAX_BITS:
            raise TooBig("shift too large to evaluate")
        return fn(a, b)
    return g


def guarded(ops: dict) -> dict:
    """The op table with cost guards on the ops that can explode (POW, SHIFT_LEFT and Lean's power)."""
    from dataclasses import replace
    out = dict(ops)
    for name in ("POW", "LEAN_POW"):
        if name in out and out[name].fn is not None:
            out[name] = replace(out[name], fn=_guard_pow(out[name].fn))
    if "SHIFT_LEFT" in out and out["SHIFT_LEFT"].fn is not None:
        out["SHIFT_LEFT"] = replace(out["SHIFT_LEFT"], fn=_guard_shift(out["SHIFT_LEFT"].fn))
    return out


# -- evaluation -----------------------------------------------------------------------------------
def eval_term(t, env, ops, call=None):
    return eval_expr(t, env, ops, call)


def eval_prop(p, env: dict, ops: dict, call=None) -> bool:
    h = p[0]
    if h in REL:
        a, b = eval_term(p[1], env, ops, call), eval_term(p[2], env, ops, call)
        if h == "eq":
            return V.same(a, b) if isinstance(a, float) or isinstance(b, float) else a == b
        if h == "ne":
            return a != b
        return {"lt": a < b, "le": a <= b, "gt": a > b, "ge": a >= b}[h]
    if h == "and":
        return eval_prop(p[1], env, ops, call) and eval_prop(p[2], env, ops, call)
    if h == "or":
        return eval_prop(p[1], env, ops, call) or eval_prop(p[2], env, ops, call)
    if h == "not":
        return not eval_prop(p[1], env, ops, call)
    if h == "imp":
        return (not eval_prop(p[1], env, ops, call)) or eval_prop(p[2], env, ops, call)
    if h == "iff":
        return eval_prop(p[1], env, ops, call) == eval_prop(p[2], env, ops, call)
    if h == "true":
        return True
    if h == "false":
        return False
    if h == "bool":
        return bool(eval_term(p[1], env, ops, call))
    if h == "dvd":
        a, b = eval_term(p[1], env, ops, call), eval_term(p[2], env, ops, call)
        return b == 0 if a == 0 else b % a == 0
    raise ValueError(f"unknown proposition head {h!r}")


# -- text --------------------------------------------------------------------------------------------
def term_text(t) -> str:
    from .logic import expr_text
    return expr_text(t)


def _sub(p) -> str:
    t = prop_text(p)
    return f"({t})" if p[0] in ("and", "or", "imp", "iff") else t


def _side(t) -> str:
    text = term_text(t)
    return text if isinstance(t, list) and t and t[0] in ("AND", "OR", "NOT", "IF_EXPR") else _strip(text)


def prop_text(p) -> str:
    h = p[0]
    if h in REL:
        return f"{_side(p[1])} {REL[h]} {_side(p[2])}"
    if h in ("and", "or"):
        return f"{_sub(p[1])} {h} {_sub(p[2])}"
    if h == "not":
        return f"not {_sub(p[1])}"
    if h == "imp":
        return f"{_sub(p[1])} ==> {_sub(p[2])}"
    if h == "iff":
        return f"{_sub(p[1])} <=> {_sub(p[2])}"
    if h in ("true", "false"):
        return h
    if h == "bool":
        return _strip(term_text(p[1]))
    if h == "dvd":
        return f"{_strip(term_text(p[1]))} divides {_strip(term_text(p[2]))}"
    return str(p)


def _strip(s: str) -> str:
    return s[1:-1] if s.startswith("(") and s.endswith(")") and _balanced(s[1:-1]) else s


def _balanced(s: str) -> bool:
    d = 0
    for c in s:
        d += c == "("
        d -= c == ")"
        if d < 0:
            return False
    return d == 0


def statement(card) -> str:
    vs = card.get("vars") or []
    groups: list[tuple[str, list[str]]] = []
    for v in vs:
        if groups and groups[-1][0] == v["type"]:
            groups[-1][1].append(v["name"])
        else:
            groups.append((v["type"], [v["name"]]))
    binder = " ".join(f"({' '.join(ns)} : {t.capitalize()})" for t, ns in groups)
    hyps = card.get("hyps") or []
    body = prop_text(card["concl"])
    if hyps:
        body = " and ".join(_sub(h) for h in hyps) + " ==> " + body
    return f"forall {binder}, {body}" if binder else body


# -- inputs ---------------------------------------------------------------------------------------
INT_EDGES = [0, 1, -1, 2, -2, 3, -3, 7, -7, 10, -10, 64, -64, 255, 256, -256, 1000, -1000, 65536, 2**31 - 1, -(2**31)]


def _draw(t: str, rng: random.Random):
    if t == "bool":
        return rng.random() < 0.5
    if t == "float":
        r = rng.random()
        if r < 0.15:
            return rng.choice([0.0, 1.0, -1.0, 0.5, -0.5, 2.0])
        return rng.uniform(-1e3, 1e3)
    r = rng.random()
    if r < 0.3:
        v = rng.choice(INT_EDGES)
    elif r < 0.6:
        v = rng.randint(-20, 20)
    elif r < 0.85:
        v = rng.randint(-10**6, 10**6)
    else:
        v = rng.randint(-2**40, 2**40)
    return abs(v) if t == "nat" else v


def _exhaustive(vs) -> list[dict] | None:
    if vs and all(v["type"] == "bool" for v in vs) and len(vs) <= 10:
        out = []
        for bits in range(2 ** len(vs)):
            out.append({v["name"]: bool(bits >> i & 1) for i, v in enumerate(vs)})
        return out
    return None


SMALL_CUBE = 3000       # exhaustive small-value phase: every combination in [-R, R]^k up to this many


def _small_cube(vs) -> list[dict]:
    """Every assignment of small values (|x| <= R, R as large as fits SMALL_CUBE): the smallest counterexample
    is found first, and look-alike laws that only fail on small values cannot slip past the random phase."""
    if not vs or any(v["type"] not in ("int", "nat", "bool") for v in vs):
        return []
    r = 1
    while True:
        size = 1
        for v in vs:
            size *= 2 if v["type"] == "bool" else (r + 2 if v["type"] == "nat" else 2 * r + 3)
        if size > SMALL_CUBE or r > 64:
            break
        r += 1
    r -= 1
    if r < 1:
        return []
    axes = [[False, True] if v["type"] == "bool" else (list(range(0, r + 1)) if v["type"] == "nat"
                                                         else list(range(-r, r + 1))) for v in vs]
    import itertools
    combos = sorted(itertools.product(*axes), key=lambda c: (sum(abs(int(x)) for x in c), c))
    return [{v["name"]: x for v, x in zip(vs, c)} for c in combos]


EXHAUSTIVE_MAX = 20000   # a hypothesis box at most this large is checked at every point: proof by exhaustion


def hypothesis_box(card) -> dict | None:
    """{var: (lo, hi)} when the hypotheses bound every int/nat variable by literals (bools: both values)."""
    lo: dict = {}
    hi: dict = {}
    vs = card.get("vars") or []
    for v in vs:
        if v["type"] == "nat":
            lo[v["name"]] = 0

    def visit(p):
        if p[0] == "and":
            visit(p[1])
            visit(p[2])
            return
        if p[0] not in ("le", "lt", "ge", "gt", "eq"):
            return
        a, b, op = p[1], p[2], p[0]
        if a[0] == "int" and b[0] == "var":
            a, b = b, a
            op = {"le": "ge", "lt": "gt", "ge": "le", "gt": "lt", "eq": "eq"}[op]
        if a[0] != "var" or b[0] != "int":
            return
        n, k = a[1], b[1]
        if op in ("le", "eq"):
            hi[n] = min(hi.get(n, k), k)
        if op == "lt":
            hi[n] = min(hi.get(n, k - 1), k - 1)
        if op in ("ge", "eq"):
            lo[n] = max(lo.get(n, k), k)
        if op == "gt":
            lo[n] = max(lo.get(n, k + 1), k + 1)

    for h in card.get("hyps") or []:
        visit(h)
    box = {}
    for v in vs:
        if v["type"] == "bool":
            box[v["name"]] = (0, 1)
        elif v["type"] in ("int", "nat") and v["name"] in lo and v["name"] in hi:
            box[v["name"]] = (lo[v["name"]], hi[v["name"]])
        else:
            return None
    return box


def _box_points(card, box) -> list[dict] | None:
    import itertools
    size = 1
    for a, b in box.values():
        size *= max(0, b - a + 1)
    if size > EXHAUSTIVE_MAX:
        return None
    vs = card.get("vars") or []
    axes = [[False, True] if v["type"] == "bool" else list(range(box[v["name"]][0], box[v["name"]][1] + 1))
            for v in vs]
    return [{v["name"]: x for v, x in zip(vs, c)} for c in itertools.product(*axes)]


def witness(card, ops: dict, seed: int | None = None, samples: int = 400, call=None) -> dict:
    """Seeded check of a theorem card: an exhaustive small-value phase, then seeded random values (edges
    included). Fails loud on a counterexample; 'vacuous' when the hypotheses rarely hold or pin a variable
    to a single value (a law about one point is not a law)."""
    seed = V.fresh_seed() if seed is None else seed
    rng = random.Random(f"{seed}:{card.get('name')}")
    ops = guarded(ops)
    too_big = 0
    vs = card.get("vars") or []
    hyps = card.get("hyps") or []
    concl = card["concl"]
    envs = _exhaustive(vs)
    box = hypothesis_box(card) if envs is None else None
    every = _box_points(card, box) if box else None
    if every is not None:
        envs = every                                    # the whole (finite) domain: proof by exhaustion
    small = [] if envs is not None else _small_cube(vs)
    budget = samples if envs is None else len(envs)
    checks = tried = undefined = 0
    first_undefined = None
    seen_values: dict[str, set] = {v["name"]: set() for v in vs}
    k = 0
    limit = budget * 20 if envs is None else budget
    plan = envs if envs is not None else small
    while True:
        if k < len(plan):
            env = plan[k]
        elif envs is not None or checks - len(plan) >= budget or tried >= limit + len(plan):
            break
        else:
            env = {v["name"]: _draw(v["type"], rng) for v in vs}
        k += 1
        tried += 1
        try:
            if not all(eval_prop(h, env, ops, call) for h in hyps):
                continue
            ok = eval_prop(concl, env, ops, call)
        except TooBig:
            too_big += 1
            continue
        except (ArithmeticError, ValueError, TypeError, RecursionError) as exc:
            undefined += 1
            if first_undefined is None:
                first_undefined = {"at": _show(env), "error": f"{type(exc).__name__}: {exc}"}
            continue
        checks += 1
        for name, val in env.items():
            if len(seen_values[name]) < 3:
                seen_values[name].add(val)
        if not ok:
            return {"status": "refuted", "seed": seed, "checks": checks, "counterexample": _show(env),
                    "statement": statement(card)}
    if undefined and not card.get("partial_ok"):
        return {"status": "refuted", "seed": seed, "checks": checks, "undefined": undefined,
                "counterexample": first_undefined["at"], "reason": "undefined: " + first_undefined["error"] +
                " (add a `requires` hypothesis that excludes it)", "statement": statement(card)}
    need = min(MIN_CHECKS, budget)
    if checks < need:
        return {"status": "vacuous", "seed": seed, "checks": checks, "tried": tried,
                "reason": f"only {checks} of {tried} inputs satisfied the hypotheses (need {need})"}
    pinned = sorted(n for n, vals in seen_values.items() if len(vals) < 2)
    if pinned:
        return {"status": "vacuous", "seed": seed, "checks": checks, "tried": tried,
                "reason": f"the hypotheses pin {', '.join(pinned)} to a single value"}
    exhaustive = envs is not None and not undefined and not too_big and k >= len(envs)
    return {"status": "witnessed", "seed": seed, "checks": checks, "tried": tried,
            **({"exhaustive": True, "domain_points": len(envs)} if exhaustive else {}),
            **({"undefined": undefined} if undefined else {}), **({"too_big_skipped": too_big} if too_big else {})}


def _show(env: dict) -> dict:
    return {k: (V.short(v) if isinstance(v, int) and not isinstance(v, bool) else v) for k, v in env.items()}


def imported(card) -> bool:
    """A statement imported from a proof assistant (its proof lives in the source; card semantics must agree)."""
    return (card.get("origin") or {}).get("kind", "") in ("lean_core", "lean_file")


def witness_card(card, ops: dict, seed: int, samples: int) -> dict:
    """Witness a theorem card under its own semantics (``card``: the IR; ``lean``: Lean's operators)."""
    if card.get("semantics", "card") != "card":
        from ..emit import lean_import as LI
        return LI._witness(dict(card), LI.lean_ops(ops), seed, max(30, samples // 2), 200)
    return witness(dict(card), ops, seed=seed, samples=samples)


# -- Lean ---------------------------------------------------------------------------------------------
class NotLean(ValueError):
    pass


def _uses_calls(e) -> bool:
    if isinstance(e, list) and e:
        if e[0] == "CALL":
            return True
        return any(_uses_calls(a) for a in e[1:] if isinstance(a, list))
    return False


def lean_term(em: Emitter, t, types: dict) -> tuple[str, str]:
    if _uses_calls(t):
        raise NotLean("calls a card-language function (emitted as partial def: proofs cannot unfold it)")
    try:
        return em.expr(t, types)
    except (EmitGap, KeyError) as exc:
        raise NotLean(str(exc)) from None


def lean_prop(em: Emitter, p, types: dict) -> str:
    h = p[0]
    if h in REL:
        a, ta = lean_term(em, p[1], types)
        b, tb = lean_term(em, p[2], types)
        if "float" in (ta, tb):
            raise NotLean("Float statements have no Lean proofs in core")
        if h in ("lt", "le", "gt", "ge") and "bool" in (ta, tb):
            raise NotLean("order on Bool")
        return f"{a} {LEAN_REL[h]} {b}"
    if h == "and":
        return f"({lean_prop(em, p[1], types)}) ∧ ({lean_prop(em, p[2], types)})"
    if h == "or":
        return f"({lean_prop(em, p[1], types)}) ∨ ({lean_prop(em, p[2], types)})"
    if h == "not":
        return f"¬ ({lean_prop(em, p[1], types)})"
    if h == "imp":
        return f"({lean_prop(em, p[1], types)}) → ({lean_prop(em, p[2], types)})"
    if h == "iff":
        return f"({lean_prop(em, p[1], types)}) ↔ ({lean_prop(em, p[2], types)})"
    if h == "true":
        return "True"
    if h == "false":
        return "False"
    if h == "bool":
        a, ta = lean_term(em, p[1], types)
        if ta != "bool":
            raise NotLean("a non-Bool term used as a proposition")
        return f"{a} = true"
    if h == "dvd":
        a, _ = lean_term(em, p[1], types)
        b, _ = lean_term(em, p[2], types)
        return f"{a} ∣ {b}"
    raise NotLean(f"proposition {h}")


def lean_name(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]", "_", name)
    return "cm_" + safe


def lean_theorem(card, store, ops, tactic: str, name: str | None = None) -> str:
    """``theorem <name> (binders) (hyps) : concl := by <tactic>`` -- the card's exact statement in Lean."""
    sem = card.get("semantics", "card")
    em = Emitter(store, "lean", ops)
    em.fn_returns = {}
    vs = card.get("vars") or []
    types = {}
    binders = []
    extra_hyps = []
    for v in vs:
        t = v["type"]
        if t == "float":
            raise NotLean("Float variables")
        lname = em.ident(v["name"])
        if sem == "lean":
            binders.append(f"({lname} : {'Nat' if t == 'nat' else 'Int' if t == 'int' else 'Bool'})")
            types[v["name"]] = "nat" if t == "nat" else t
        else:
            binders.append(f"({lname} : {'Bool' if t == 'bool' else 'Int'})")
            types[v["name"]] = "bool" if t == "bool" else "int"
            if t == "nat":
                extra_hyps.append(f"(h_{lname}_nonneg : 0 ≤ {lname})")
    hyps = [f"(h{i} : {lean_prop(em, h, types)})" for i, h in enumerate(card.get("hyps") or [])]
    concl = lean_prop(em, card["concl"], types)
    helpers = em.helpers_for(concl + " ".join(hyps))
    if helpers.strip():
        raise NotLean("needs helper definitions (partial defs cannot be unfolded)")
    head = " ".join([*binders, *extra_hyps, *hyps])
    return f"theorem {name or lean_name(card['name'])}{(' ' + head) if head else ''} : {concl} := by {tactic}"


def prove(cards, store, ops, tactics=TACTICS, timeout_s: int = 600, deep: bool = False) -> dict:
    """Try each tactic on every card's Lean statement (one file per round; failures mapped back by line).
    ``deep`` adds Lean's library search (exact?), which re-derives a proof from core lemmas."""
    tactics = tuple(tactics) + (DEEP_TACTICS if deep else ())
    from ..emit import lean as L
    exe = L.lean_exe()
    out: dict[str, dict] = {}
    pending = []
    for card in cards:
        try:
            lean_theorem(card, store, ops, "sorry")
            pending.append(card)
        except NotLean as exc:
            out[card["name"]] = {"status": "not_expressible", "detail": str(exc)}
    if exe is None:
        for card in pending:
            out[card["name"]] = {"status": "no_toolchain"}
        return {"toolchain": None, "results": out}
    for tactic in tactics:
        if not pending:
            break
        items = [(card["name"], lean_theorem(card, store, ops, tactic)) for card in pending]
        verdict = L.check_batch(exe, items, header=[f"set_option maxHeartbeats {HEARTBEATS}"], timeout_s=timeout_s)
        still = []
        for card in pending:
            v = verdict.get(card["name"], "unchecked")
            if v == "ok":
                out[card["name"]] = {"status": "proved", "tactic": tactic,
                                     "lean": lean_theorem(card, store, ops, tactic)}
            elif v.startswith("unchecked"):
                out[card["name"]] = {"status": "unchecked", "detail": v}
            else:
                still.append(card)
        pending = still
    for card in pending:
        out[card["name"]] = {"status": "unproved", "tried": list(tactics),
                             "lean": lean_theorem(card, store, ops, "sorry")}
    return {"toolchain": exe, "results": out}


def toolchain_version(exe: str | None) -> str | None:
    if not exe:
        return None
    m = re.search(r"toolchains/([^/]+)/bin", exe)
    return m.group(1) if m else exe.rsplit("/", 1)[-1]


def settle(card: dict, witness_result: dict | None, proof_result: dict | None, exe: str | None) -> dict:
    """Write evidence into a theorem card dict and raise its status only as far as the evidence goes."""
    card = dict(card)
    proofs = [p for p in card.get("proofs") or [] if not str(p.get("method", "")).startswith("lean:")]
    status = "conjecture"
    if witness_result is not None:
        card["evidence"] = {k: witness_result[k] for k in ("status", "seed", "checks", "counterexample", "reason",
                                                           "exhaustive", "domain_points") if k in witness_result}
        if witness_result["status"] == "refuted":
            status = "refuted"
        elif witness_result["status"] == "witnessed":
            status = "witnessed"
            if witness_result.get("exhaustive"):
                proofs = [p for p in proofs if p.get("method") != "exhaustive"]
                proofs.append({"method": "exhaustive", "ok": True, "points": witness_result["domain_points"],
                               "semantics": card.get("semantics", "card")})
    if proof_result is not None and status != "refuted":
        if proof_result.get("status") == "proved":
            proofs.append({"method": f"lean:{proof_result['tactic']}", "ok": True,
                           "toolchain": toolchain_version(exe), "lean": proof_result["lean"]})
            status = "proved"
        elif proof_result.get("status") in ("unproved", "not_expressible"):
            card["lean_status"] = {k: v for k, v in proof_result.items() if k != "lean"}
    if any(p.get("ok") for p in proofs) and status in ("witnessed", "conjecture"):
        status = "proved"
    card["proofs"] = proofs
    card["status"] = status
    card["statement"] = statement(card)
    return card


__all__ = ["NotLean", "TACTICS", "eval_prop", "lean_prop", "lean_term", "lean_theorem", "prop_text", "prove",
           "settle", "statement", "toolchain_version", "witness"]
