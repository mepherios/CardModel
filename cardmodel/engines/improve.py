"""improve — make a program faster without changing what it does (pure core, effect shell).

Methodology (docs/METHODOLOGY.md), per top-level function of a Python module:

  1. lift      frontend_python -> IR. A function that does not lift (I/O, sockets, login,
               clocks, classes, globals, ...) belongs to the effect shell and is preserved
               byte for byte; so is every other top-level statement (CM21).
  2. domain    the function's domain is inferred and the ORIGINAL Python is the reference.
  3. candidates
       algorithm   behavioural match against cards/algorithm: same signature and the same
                   outputs on probe inputs, or (int results) outputs that are an exact affine
                   function a*card(x) + b of the card's (e.g. an XP curve that is 10 x a sum of
                   squares). At least 3 distinct card outputs are required, so a constant
                   function matches nothing. Every non-suboptimal form of a matched card is a
                   candidate, guarded by the card's precondition; the original code still runs
                   for every input outside it.
       rewrite     search.optimize over every int-typed expression with the rule cards, and
                   equality saturation (egraph) over the unconditional rules and discovered laws;
                   one candidate from the rule search alone, one from the cheaper of the two per
                   expression (both verified and measured); the function is re-emitted from IR.
       native      (native_call) the function's C form compiled to a shared library and called
                   through ctypes inside the box of verified inputs, the original outside it (native.py).
  4. verify    each candidate against the original on seeded inputs (plus edges); any
               mismatch rejects it.
  5. measure   the original and every verified candidate, in-process, on the same inputs
               (budgeted); the fastest wins only if it beats the original by more than NOISE
               (hub L4); otherwise the function is kept.
  6. emit      only the chosen functions are replaced in the module text (surgical, hub L3);
               the result is re-verified end to end with a fresh seed and more inputs; a
               substitution the recheck refutes is reverted (the original is kept) and the
               check repeats until it passes. Native translations of the chosen versions are
               emitted for every language card with codegen.

Comparison inputs = the inferred domain + wide random values + a structured set (exhaustive small
ranges, prime products, Carmichael numbers, powers of two and neighbours), smallest first, each
within a time budget for the ORIGINAL; recursion limits and timeouts are never compared, ordinary
exceptions must match by type.

Honest limits (L1): equivalence is sampled, not proven; behavioural matching only finds
algorithms that have a card; timing is in-process Python on this machine; module-level code
is never executed (only function definitions are, to test them).
"""
from __future__ import annotations

import ast
import hashlib
import math
import random
import time
from pathlib import Path

from . import values as V
from .codegen import EmitGap, Emitter, emit_module
from .context import Ctx
from .frontend_python import lift_source, module_for
from .ir import walk_stmts
from .search import expr_cost, load_rules, op_costs, optimize
from .translate import infer_domain
from .witness import TimeLimit, time_limit

NOISE = 0.10
MIN_MATCH = 8
CALL_BUDGET_S = 0.02
WIDE = {"int": {"int": [-10000, 10000], "edges": [2, -2, 10, 100, 1000, -1000, 99999, 10**6]},
        "float": {"float": [-1e6, 1e6]}, "bool": {"bool": True}}
# values that separate look-alike integer functions: prime products and squares (trial division
# decoys), Carmichael numbers, powers of two and their neighbours, digit boundaries
INTERESTING_INTS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 15, 16, 17, 25, 31, 32, 33, 49, 63, 64, 65, 97, 99,
                    100, 101, 121, 127, 128, 143, 169, 221, 255, 256, 257, 289, 323, 361, 437, 529, 561, 899, 961,
                    999, 1000, 1001, 1023, 1024, 1025, 1105, 1681, 1729, 2047, 2048, 2465, 2641, 2821, 4093, 4096,
                    6601, 8191, 9999, 10007, 10403, 65535, 65536, 65537, 99991, 1000003]
INTERESTING_FLOATS = [0.0, -0.0, 0.5, -0.5, 1.0, -1.0, 2.0, 3.0, 0.1, 1e-9, -1e-9, 1e9, 123.456, -987.25]


# -- small AST helpers ----------------------------------------------------------------------
class _Rename(ast.NodeTransformer):
    def __init__(self, mapping: dict[str, str]):
        self.mapping = mapping

    def visit_Name(self, node):
        if node.id in self.mapping:
            return ast.copy_location(ast.Name(id=self.mapping[node.id], ctx=node.ctx), node)
        return node

    def visit_FunctionDef(self, node):
        self.generic_visit(node)
        if node.name in self.mapping:
            node.name = self.mapping[node.name]
        return node

    def visit_arg(self, node):
        if node.arg in self.mapping:
            node.arg = self.mapping[node.arg]
        return node


def rename(code: str, mapping: dict[str, str]) -> str:
    tree = _Rename(mapping).visit(ast.parse(code))
    return ast.unparse(ast.fix_missing_locations(tree))


def _functions_only(source: str) -> str:
    """Only the module's function definitions: safe to execute. Module-level code and imports never
    run here (an import could execute another module's top level); liftable functions need nothing but
    ``math``, which the namespace provides, and shell functions are only defined, never called."""
    tree = ast.parse(source)
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef)]
    return ast.unparse(ast.Module(body=keep, type_ignores=[]))


def _load(source: str) -> dict:
    ns: dict = {"__name__": "cardmodel_improve", "math": math}
    exec(compile(_functions_only(source), "<improve>", "exec"), ns)  # noqa: S102 -- the user's own functions
    return ns


# -- verification and timing --------------------------------------------------------------------
def _outcome(fn, args):
    """("ok", value) | ("raise", ExceptionType name) | ("skip", reason): recursion limits and time budgets are
    limits of this run, not semantics, so they are never compared."""
    try:
        with time_limit(2):
            return "ok", fn(*args)
    except (RecursionError, TimeLimit) as exc:
        return "skip", type(exc).__name__
    except Exception as exc:  # noqa: BLE001 -- an exception is observable behaviour and is compared by type
        return "raise", type(exc).__name__


def _agree(ref, cand, inputs) -> tuple[int, dict | None]:
    checks = 0
    for args in inputs:
        k1, want = _outcome(ref, args)
        if k1 == "skip":
            continue
        k2, got = _outcome(cand, args)
        if k2 == "skip":
            continue
        checks += 1
        if k1 != k2 or (k1 == "ok" and not V.same(want, got)) or (k1 == "raise" and want != got):
            return checks, {"args": V.short(list(args)), "expected": V.short(want) if k1 == "ok" else f"raised {want}",
                            "got": V.short(got) if k2 == "ok" else f"raised {got}"}
    return checks, None


def _returning(fn, inputs) -> list:
    """The inputs on which ``fn`` returns normally (timing runs only these)."""
    out = []
    for a in inputs:
        try:
            fn(*a)
            out.append(a)
        except Exception:  # noqa: BLE001 -- a raising input is compared for parity, not timed
            continue
    return out


def _time(fn, inputs, budget_s: float = 0.3) -> float:
    """Median-of-repeats seconds for one pass over ``inputs`` (at least 3 repeats, within the budget)."""
    samples = []
    spent = 0.0
    while len(samples) < 3 or (spent < budget_s and len(samples) < 15):
        t0 = time.perf_counter()
        for a in inputs:
            fn(*a)
        dt = time.perf_counter() - t0
        samples.append(dt)
        spent += dt
        if dt > budget_s and len(samples) >= 1:
            break
    samples.sort()
    return samples[len(samples) // 2]


def _cheap_inputs(fn, inputs, per_call_s: float = CALL_BUDGET_S, give_up_after: int = 4) -> list:
    """Inputs on which ``fn`` finishes (with a value or an ordinary exception) within ``per_call_s``.
    Inputs are tried smallest first; after ``give_up_after`` consecutive slow inputs the larger ones are
    skipped (the slow original decides the comparison set)."""
    out = []
    slow = 0
    for a in sorted(inputs, key=_magnitude):
        if slow >= give_up_after:
            break
        t0 = time.perf_counter()
        try:
            with time_limit(max(per_call_s * 2, 0.01)):
                fn(*a)
        except (TimeLimit, RecursionError):
            slow += 1
            continue
        except Exception:  # noqa: BLE001 -- a raising input stays: the candidate must raise the same way
            pass
        if time.perf_counter() - t0 <= per_call_s:
            out.append(a)
            slow = 0
        else:
            slow += 1
    return out


def structured_inputs(param_types: list[str], rng: random.Random, cap: int = 900) -> list[tuple]:
    """Exhaustive small domains and interesting values (deterministic part of every comparison set)."""
    import itertools
    base = {"int": list(range(-64, 129)) + INTERESTING_INTS + [-v for v in INTERESTING_INTS[:40]],
            "float": INTERESTING_FLOATS, "bool": [False, True]}
    small = {"int": list(range(-6, 21)) + [31, 32, 64, 97, 100, 143, 255, 256, 561, 1000, 1024],
             "float": INTERESTING_FLOATS[:8], "bool": [False, True]}
    if len(param_types) == 1:
        rows = [(v,) for v in base[param_types[0]]]
    elif len(param_types) == 2:
        rows = list(itertools.product(small[param_types[0]], small[param_types[1]]))
    else:
        pools = [small[t] for t in param_types]
        rows = [tuple(rng.choice(p) for p in pools) for _ in range(cap)]
    if len(rows) > cap:
        rows = rng.sample(rows, cap)
    return rows


def _magnitude(row) -> float:
    total = 0.0
    for v in row:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            total += min(abs(float(v)), 1e300)
    return total


def _unique(rows):
    seen, out = set(), []
    for r in rows:
        k = repr(r)
        if k not in seen:
            seen.add(k)
            out.append(tuple(r))
    return out


# -- candidates ------------------------------------------------------------------------------------
def _signature_types(fn_ir: dict) -> tuple[list[str], str]:
    return [p["type"] for p in fn_ir["params"]], fn_ir["returns"]


def algorithm_candidates(ctx: Ctx, fn_ir: dict, ref, inputs: list) -> list[dict]:
    from .witness import python_callable
    ptypes, rtype = _signature_types(fn_ir)
    params = [p["name"] for p in fn_ir["params"]]
    out = []
    for card in ctx.store.cards("algorithm"):
        sig = card.get("signature") or {}
        if [p["type"] for p in sig.get("params", [])] != ptypes or sig.get("returns") != rtype:
            continue
        ref_form = next((f for f in card["forms"] if f["name"] == card.get("reference_form")), None)
        if ref_form is None:
            continue
        try:
            card_fn = python_callable(ctx, ref_form, card)
        except Exception:  # noqa: BLE001 -- a broken card is skipped here and reported by verify
            continue
        filt = None
        if card.get("filter"):
            filt = eval(card["filter"], {"__builtins__": {}, "math": math})  # noqa: S307 -- trusted card data
        pairs = []   # (user value, card value) on inputs where both return normally
        for args in inputs:
            try:
                if filt is not None and not filt(*args):
                    continue
            except Exception:  # noqa: BLE001 -- precondition not evaluable here: not compared
                continue
            k1, want = _outcome(ref, args)
            if k1 != "ok":
                continue
            k2, got = _outcome(card_fn, args)
            if k2 != "ok":
                continue
            pairs.append((want, got))
        affine = _fit_affine(pairs, rtype)
        if affine is None:
            continue
        scale, shift = affine
        cparams = [p["name"] for p in sig["params"]]
        pre = card.get("precondition")
        for form in card["forms"]:
            if form.get("role") == "suboptimal":
                continue
            fast_name = f"{fn_ir['name']}__{card.name}_{form['name']}"
            fast_src = rename(form["code"], {form["entry"]: fast_name, **dict(zip(cparams, params))})
            out.append({"kind": "algorithm" if (scale, shift) == (1, 0) else "algorithm_affine",
                        "card": card.qualified, "form": form["name"], "scale": scale, "shift": shift,
                        "complexity": form.get("complexity"), "fast_name": fast_name, "fast_src": fast_src,
                        "precondition": rename(pre, dict(zip(cparams, params))) if pre else None,
                        "needs_math": "math." in form["code"]})
    return out


def algebra_candidates(ctx: Ctx, fn_ir: dict, ref) -> list[dict]:
    """Redefinitions from the function's own behaviour (engines/funcalg.py), with no algorithm card needed: a
    polynomial becomes its exact integer closed form, a linear recurrence becomes matrix powering. The form
    holds from the start it was fitted at (checked on unused terms); below that the original runs."""
    from . import funcalg as FA
    ptypes, rtype = _signature_types(fn_ir)
    if ptypes != ["int"] or rtype != "int":
        return []
    param = fn_ir["params"][0]["name"]
    for start in (0, 1):
        form = FA.fit(ref, start)
        if form is None or form.order == 0:
            continue
        fast_name = f"{fn_ir['name']}__algebra"
        src = FA.python_source(form, fast_name, param)
        if src is None:
            continue
        pre = f"{param} >= {start}"
        if form.poly is not None:                    # the closed form may hold for negative inputs too
            agree = True
            for k in range(1, 9):
                kind, v = _outcome(ref, (-k,))
                if kind != "ok" or v != form.value(-k):
                    agree = False
                    break
            if agree:
                pre = None
        return [{"kind": "algebra", "card": "algebra/" + ("polynomial" if form.poly is not None else "recurrence"),
                 "form": "closed_form" if form.poly is not None else "matrix_power", "scale": 1, "shift": 0,
                 "complexity": "O(1)" if form.poly is not None else f"O({form.order}^3 log n)",
                 "fast_name": fast_name, "fast_src": src, "precondition": pre, "needs_math": False,
                 "canonical": form.describe(), "godel": str(form.godel())}]
    return []


def _fit_affine(pairs: list, rtype: str):
    """(1, 0) when the user's outputs equal the card's; for int results also (a, b) with
    user == a * card + b exactly on every pair (a != 0, integers). None when neither holds or the
    evidence is too thin (>= MIN_MATCH pairs; >= 3 distinct card values, 2 for bool)."""
    if len(pairs) < MIN_MATCH:
        return None
    distinct = {V.key(g) for _, g in pairs}
    if len(distinct) < (2 if rtype == "bool" else 3):
        return None
    if all(V.same(u, g) for u, g in pairs):
        return 1, 0
    if rtype != "int":
        return None
    ints = [(u, g) for u, g in pairs if isinstance(u, int) and isinstance(g, int)
            and not isinstance(u, bool) and not isinstance(g, bool)]
    if len(ints) != len(pairs):
        return None
    (u1, g1) = ints[0]
    other = next(((u, g) for u, g in ints if g != g1), None)
    if other is None:
        return None
    u2, g2 = other
    if (u1 - u2) % (g1 - g2) != 0:
        return None
    a = (u1 - u2) // (g1 - g2)
    b = u1 - a * g1
    if a == 0 or not all(u == a * g + b for u, g in ints):
        return None
    return a, b


def _int_typed(e, types: dict[str, str]) -> bool:
    if not isinstance(e, list):
        return False
    head = e[0]
    if head == "var":
        return types.get(e[1]) == "int"
    if head == "int":
        return True
    if head in ("float", "bool", "CALL", "IF_EXPR", "AND", "OR", "NOT") or head.startswith("CMP_") or head in (
            "DIV", "TO_FLOAT"):
        return False
    return all(_int_typed(a, types) for a in e[1:])


def cheapest_rewrite(e, rules, costs, egraph_rules=None) -> tuple | None:
    """The cheapest equivalent of ``e`` found by the bounded rewrite search and, when ``egraph_rules`` are given,
    by equality saturation (which reaches forms the depth-3 search does not, such as Horner-like regroupings and
    chains of identities). Returns (input text, best text, best tree, steps) or None when nothing is cheaper.
    Both searches use the same op costs; ties go to the smaller term, then to the search result."""
    from .exprs import size, to_text
    res = optimize(e, rules, costs, max_depth=3, max_nodes=300)
    start = expr_cost(e, costs)
    best = (res["best_cost"], size(res["best_tree"]), res["best_tree"], [s for s, _ in res["steps"][1:]])
    if egraph_rules:
        from . import egraph as E
        try:
            got = E.canonical(e, egraph_rules, costs, max_iter=6, max_nodes=800)
        except (ValueError, KeyError, TypeError):
            got = None
        if got and got["term"] is not None:
            cand = (expr_cost(got["term"], costs), size(got["term"]), got["term"],
                    ["egraph:" + o for o in got["fired"]])
            if cand[:2] < best[:2]:
                best = cand
    if best[0] >= start:
        return None
    return res["input"], to_text(best[2]), best[2], best[3]


def rewrite_candidate(ctx: Ctx, fn_ir: dict, rules, costs, egraph_rules=None) -> tuple[dict | None, list]:
    """The function with every int-typed expression replaced by its cheapest equivalent under the rule cards
    (and the e-graph's equalities when ``egraph_rules`` are given). Every candidate is still verified against
    the original before it can be chosen."""
    import copy
    fn = copy.deepcopy(fn_ir)
    types = {p["name"]: p["type"] for p in fn["params"]}
    types.update(fn.get("locals") or {})
    changes = []

    def visit(e):
        if not isinstance(e, list) or not e or e[0] in ("var", "int", "float", "bool"):
            return e
        if _int_typed(e, types) and 3 <= len(repr(e)) and e[0] not in ("CALL",):
            got = cheapest_rewrite(e, rules, costs, egraph_rules)
            if got is not None:
                changes.append((got[0], got[1], got[3]))
                return got[2]
        start = 2 if e[0] == "CALL" else 1
        return [e[0], *e[1:start], *[visit(a) for a in e[start:]]][: len(e)] if start == 2 else \
            [e[0], *[visit(a) for a in e[1:]]]

    for s in walk_stmts(fn["body"]):
        for key in ("value", "cond"):
            if isinstance(s.get(key), list):
                s[key] = visit(s[key])
    return (fn if changes else None), changes


# -- the engine ----------------------------------------------------------------------------------
def improve_source(ctx: Ctx, source: str, label: str = "<module>", seed: int | None = None, samples: int = 32,
                   native: bool = True, native_call: bool | None = None) -> dict:
    """``native`` emits the result in every codegen language; ``native_call`` (default: as ``native``) adds a
    candidate per function that calls its compiled C form through ctypes inside the verified domain (native.py)."""
    native_call = native if native_call is None else native_call
    seed = V.fresh_seed() if seed is None else seed
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    lifted = lift_source(source, ctx.ops)
    by_name = {lf.name: lf for lf in lifted}
    rules = load_rules(ctx.store)
    costs = op_costs(ctx.store)
    from .egraph import rules_from_cards
    egraph_rules = rules_from_cards(ctx.store)
    original_ns = _load(source)
    report: dict = {"label": label, "seed": seed, "functions": {}, "effect_shell": []}
    replacements: dict[str, str] = {}
    needs_math = False

    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        lf = by_name.get(node.name)
        if lf is None or not lf.ok:
            report["effect_shell"].append({"name": node.name, "line": node.lineno,
                                           "reason": (lf.reasons[0] if lf and lf.reasons else "not liftable")})
            continue
        entry = report["functions"].setdefault(node.name, {"line": node.lineno})
        module = module_for(node.name, lifted)
        ref = original_ns[node.name]
        gens, _ = infer_domain(ctx, module, ref, want=samples, seed=seed)
        rng = random.Random(f"{seed}:{label}:{node.name}")
        fn_ir = next(f for f in module["functions"] if f["name"] == node.name)
        ptypes = [p["type"] for p in fn_ir["params"]]
        wide = [WIDE[t] for t in ptypes]
        inputs = _cheap_inputs(ref, _unique(V.inputs(gens, samples, rng) + V.inputs(wide, samples, rng)
                                            + structured_inputs(ptypes, rng)))
        entry["generators"] = gens
        entry["inputs"] = len(inputs)
        if len(inputs) < 4:
            entry.update(action="kept", reason="too few quick in-domain inputs to compare")
            continue
        orig_src = "".join(lines[node.lineno - 1 - len(node.decorator_list): node.end_lineno])
        cands = []
        for c in algorithm_candidates(ctx, fn_ir, ref, inputs) + algebra_candidates(ctx, fn_ir, ref):
            params = ", ".join(f"{p['name']}: {p['type']}" for p in fn_ir["params"])
            call = ", ".join(p["name"] for p in fn_ir["params"])
            fast_call = f"{c['fast_name']}({call})"
            if (c["scale"], c["shift"]) != (1, 0):
                fast_call = f"{c['scale']} * {fast_call}" + (f" + {c['shift']}" if c["shift"] else "")
            if c["precondition"]:
                orig_name = f"{node.name}__original"
                orig_body = rename(orig_src, {}).replace(f"def {node.name}(", f"def {orig_name}(", 1)
                src = (f"def {node.name}({params}) -> {fn_ir['returns']}:\n"
                       f"    if {c['precondition']}:\n        return {fast_call}\n"
                       f"    return {orig_name}({call})\n\n\n{c['fast_src']}\n\n\n{orig_body}\n")
            else:
                src = (f"def {node.name}({params}) -> {fn_ir['returns']}:\n"
                       f"    return {fast_call}\n\n\n{c['fast_src']}\n")
            cands.append({**c, "src": src})
        # two rewrite candidates: the rule search alone, and the cheaper of it and the e-graph per expression;
        # cost units are estimates, so both are verified and measured and the faster one wins
        seen_src = set()
        for form, eg in (("rules", None), ("egraph", egraph_rules)):
            rw_ir, changes = rewrite_candidate(ctx, fn_ir, rules, costs, eg)
            if rw_ir is None:
                continue
            try:
                callees = [f for f in module["functions"] if f["name"] != node.name]
                rw_src = emit_module(ctx.store, ctx.ops, "python",
                                     {"entry": node.name, "functions": [rw_ir, *callees]}, only=[node.name])
            except EmitGap as exc:
                entry["rewrite_gap"] = str(exc)
                continue
            if rw_src in seen_src:
                continue
            seen_src.add(rw_src)
            cands.append({"kind": "rewrite", "card": "rewrite_rule/*", "form": form, "src": rw_src,
                          "changes": changes, "needs_math": "math." in rw_src})
        if native_call:
            from . import native as NV
            nc, why = NV.candidate(ctx, fn_ir, module, inputs, orig_src, rename)
            if nc is not None:
                cands.append(nc)
            else:
                entry["native_gap"] = why
        verified = []
        for c in cands:
            ns = _load(source)
            try:
                exec(compile(c["src"], f"<candidate {node.name}>", "exec"), ns)  # noqa: S102
                with time_limit(30):
                    checks, bad = _agree(ref, ns[node.name], inputs)
            except (TimeLimit, SyntaxError, NameError, RecursionError) as exc:
                checks, bad = 0, {"error": f"{type(exc).__name__}: {exc}"}
            c["checks"] = checks
            if bad is None and checks >= 4:
                c["fn"] = ns[node.name]
                verified.append(c)
            else:
                c["rejected"] = bad or "too few checks"
        timed = _returning(ref, inputs)
        if not timed:
            entry.update(action="kept", reason="the original returns normally on none of the inputs")
            continue
        t_orig = _time(ref, timed)
        best, best_t = None, t_orig
        for c in verified:
            c["seconds"] = _time(c["fn"], timed)
            if c["seconds"] < best_t:
                best, best_t = c, c["seconds"]
        entry["candidates"] = [{k: v for k, v in c.items() if k in ("kind", "card", "form", "complexity", "checks",
                                                                    "seconds", "rejected", "changes", "scale",
                                                                    "shift", "canonical", "box")}
                               for c in cands]
        entry["original_seconds"] = t_orig
        if best is not None and t_orig / best_t > 1 + NOISE:
            entry.update(action=f"{best['kind']}:{best['card']}#{best['form']}", speedup=round(t_orig / best_t, 2),
                         checks=best["checks"], new_source=best["src"])
            if best.get("lib"):
                entry.update(native_lib=best["lib"], native_domain=best["box"])
            replacements[node.name] = best["src"]
            needs_math = needs_math or best.get("needs_math", False)
        else:
            entry.update(action="kept", reason="no verified candidate faster than the original beyond noise"
                         if verified else "no verified candidate")

    reverted = {}
    while True:
        optimized = _splice(source, tree, replacements, needs_math)
        e2e = end_to_end(ctx, source, optimized, sorted(replacements), seed)
        if e2e.get("status") != "fail":
            break
        for name, why in e2e["mismatches"].items():   # a recheck refuted it: keep the original instead
            replacements.pop(name, None)
            reverted[name] = why
            f = report["functions"][name]
            f.update(action="kept", reason="reverted: the end-to-end recheck found a counterexample",
                     counterexample=why, reverted_from=f.get("action"))
            f.pop("speedup", None)
            f.pop("new_source", None)
    report["optimized_source"] = optimized
    report["changed"] = sorted(replacements)
    report["reverted"] = reverted
    report["effect_shell_identical"] = shell_identical(source, optimized, set(replacements))
    report["end_to_end"] = e2e
    if native:
        report["native"] = native_forms(ctx, optimized, sorted(report["functions"]))
    return report


def _splice(source: str, tree: ast.Module, replacements: dict[str, str], needs_math: bool) -> str:
    """Replace whole function definitions by line range; every other byte stays as it was."""
    lines = source.splitlines(keepends=True)
    spans = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in replacements:
            spans.append((node.lineno - 1 - len(node.decorator_list), node.end_lineno, node.name))
    for start, end, name in sorted(spans, reverse=True):
        text = replacements[name].rstrip("\n") + "\n"
        lines[start:end] = [text]
    out = "".join(lines)
    if needs_math and not any(isinstance(n, ast.Import) and any(a.name == "math" for a in n.names) for n in tree.body):
        head = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "__future__"]
        at = head[-1].end_lineno if head else (1 if ast.get_docstring(tree) and tree.body else 0)
        if ast.get_docstring(tree) and not head:
            at = tree.body[0].end_lineno
        parts = out.splitlines(keepends=True)
        parts[at:at] = ["import math  # added by cardmodel improve (used by a substituted form)\n"]
        out = "".join(parts)
    return out


def shell_identical(source: str, optimized: str, changed: set[str]) -> bool:
    """Every top-level statement that was not replaced is present in the optimized module, byte for byte."""
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in changed:
            continue
        seg = "".join(lines[node.lineno - 1 - len(getattr(node, "decorator_list", [])): node.end_lineno])
        if seg not in optimized:
            return False
    return True


def end_to_end(ctx: Ctx, source: str, optimized: str, changed: list[str], seed: int) -> dict:
    """Re-verify every changed function in the spliced module (fresh seed), next to the original."""
    if not changed:
        return {"status": "nothing_changed"}
    orig = _load(source)
    new = _load(optimized)
    lifted = lift_source(source, ctx.ops)
    total, bad = 0, {}
    for name in changed:
        module = module_for(name, lifted)
        gens, _ = infer_domain(ctx, module, orig[name], want=24, seed=seed + 1)
        fn_ir = next(f for f in module["functions"] if f["name"] == name)
        rng = random.Random(seed + 1)
        ptypes = [p["type"] for p in fn_ir["params"]]
        wide = [WIDE[t] for t in ptypes]
        inputs = _cheap_inputs(orig[name], _unique(V.inputs(gens, 48, rng) + V.inputs(wide, 96, rng)
                                                   + structured_inputs(ptypes, rng)))
        checks, mismatch = _agree(orig[name], new[name], inputs)
        total += checks
        if mismatch:
            bad[name] = mismatch
    return {"status": "pass" if not bad else "fail", "checks": total, "mismatches": bad}


def native_forms(ctx: Ctx, optimized: str, names: list[str]) -> dict:
    """Emit the (optimized) pure functions in every codegen language; record gaps."""
    lifted = lift_source(optimized, ctx.ops)
    ok = {lf.name for lf in lifted if lf.ok}
    out: dict = {}
    for lang in ctx.codegen_languages():
        texts, gaps = [], []
        seen: set[str] = set()
        for name in names:
            if name not in ok:
                gaps.append(name)
                continue
            module = module_for(name, lifted)
            todo = [f["name"] for f in module["functions"] if f["name"] not in seen]
            if not todo:
                continue
            try:
                texts.append(Emitter(ctx.store, lang, ctx.ops).module_source(module, only=todo))
                seen.update(todo)
            except EmitGap:
                gaps.append(name)
        out[lang] = {"source": "\n".join(texts), "gaps": gaps}
    return out


def markdown(report: dict) -> str:
    L = [f"# improve report — {report['label']}", "",
         f"seed {report['seed']} · end-to-end re-check: {report['end_to_end'].get('status')} "
         f"({report['end_to_end'].get('checks', 0)} checks) · effect shell byte-identical: "
         f"{report['effect_shell_identical']}", "",
         "| function | action | speedup | checks | inputs |", "|---|---|---:|---:|---:|"]
    for name, f in report["functions"].items():
        L.append(f"| {name} | {f.get('action')} | {f.get('speedup', '—')} | {f.get('checks', '—')} | "
                 f"{f.get('inputs', '—')} |")
    if report["effect_shell"]:
        L += ["", "Effect shell (preserved byte for byte):", ""]
        L += [f"* `{e['name']}` (line {e['line']}): {e['reason']}" for e in report["effect_shell"]]
    return "\n".join(L) + "\n"


def write_outputs(report: dict, out_dir: Path, stem: str) -> list[Path]:
    import json
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    p = out_dir / f"{stem}.py"
    p.write_text(report["optimized_source"], encoding="utf-8")
    written.append(p)
    exts = {"python": ".py", "javascript": ".mjs", "typescript": ".ts", "c": ".c", "cpp": ".cpp", "rust": ".rs",
            "go": ".go", "swift": ".swift", "java": ".java", "ruby": ".rb", "lua": ".lua", "lean": ".lean"}
    for lang, nat in (report.get("native") or {}).items():
        if nat["source"].strip():
            q = out_dir / "native" / lang / f"{stem}{exts.get(lang, '.' + lang)}"
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_text(nat["source"], encoding="utf-8")
            written.append(q)
    import shutil
    for f in report["functions"].values():      # the libraries the module calls, next to it (it looks there first)
        if f.get("native_lib") and Path(f["native_lib"]).is_file():
            q = out_dir / "native" / "c" / Path(f["native_lib"]).name
            q.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f["native_lib"], q)
            written.append(q)
    slim = {k: v for k, v in report.items() if k not in ("optimized_source", "native")}
    slim["native_gaps"] = {lang: nat["gaps"] for lang, nat in (report.get("native") or {}).items()}
    (out_dir / f"{stem}.improve.json").write_text(json.dumps(slim, indent=1, default=str, sort_keys=True) + "\n",
                                                  encoding="utf-8")
    (out_dir / f"{stem}.improve.md").write_text(markdown(report), encoding="utf-8")
    written += [out_dir / f"{stem}.improve.json", out_dir / f"{stem}.improve.md"]
    return written


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]
