"""conformance — the op x language matrix, computed by running real toolchains.

For every op card with ``ir`` and every signature in ``ir.types`` a one-line
test function ``return OP(a0, a1, ...)`` is generated; per language, all of
them go into ONE program (one compile, which reads its inputs from stdin, so
the build is reused by every later seed), are called on seeded inputs drawn
from the op's ``ir.domain``, and every printed value is compared with the
op's reference semantics (``ir.eval``). This is how translation coverage
is measured rather than claimed (Pheros L115; hub L21 sampling caveat).

Cell status: pass | fail (with a counterexample) | gap (the language card
or op card declares no template / UNSUPPORTED) | unavailable (probe failed)
| error (compile or runtime failure, with the compiler's message). When a
program fails to compile, each function is retried alone so one bad
template cannot hide the other cells.

Floats compare with ``values.same(signed_zero=True)`` and every float +0.0 input is also tried as -0.0, so a
target that loses the sign of a zero (in a literal, an argument or a result) fails its cell.

Honest limits (L1): sampling, not proof; inputs stay inside each op's
declared domain and, for fixed-width languages, inside the int width.
"""
from __future__ import annotations

import math
import random
from concurrent.futures import ThreadPoolExecutor

from ..kernel import resources

from . import values as V
from .codegen import EmitGap, Emitter
from .context import Ctx
from .ir import Interpreter
from .runners import run_calls

DEFAULT_SAMPLES = 12
TYPE_CODE = {"list[int]": "li", "list[float]": "lf"}


def _domain_key(sig: list[str]) -> str:
    args = sig[:-1]
    for t in args:
        if t != "bool":
            return t
    return "bool"


def op_functions(ops) -> list[dict]:
    fns = []
    for name, spec in sorted(ops.items()):
        for sig in spec.types:
            args = sig[:-1]
            fname = f"t_{name.lower()}_{'_'.join(TYPE_CODE.get(t, t[0]) for t in args)}"
            params = [{"name": f"a{i}", "type": t} for i, t in enumerate(args)]
            fns.append({"op": name, "sig": sig, "fn": {
                "name": fname, "params": params, "returns": sig[-1], "locals": {},
                "body": [{"k": "return", "value": [name, *[["var", p["name"]] for p in params]]}]}})
    return fns


def _cases(ops, fns, rng, samples):
    """Reference outputs per test function: list of (args, expected)."""
    cases = {}
    for item in fns:
        spec = ops[item["op"]]
        dom = (spec.card.get("ir") or {}).get("domain") or {}
        key = _domain_key(item["sig"])
        gens = dom.get(",".join(item["sig"][:-1])) or dom.get(key) or [V.DEFAULT_GEN[t] for t in item["sig"][:-1]]
        interp = Interpreter({"functions": [item["fn"]]}, ops)
        rows = []
        for args in _with_negative_zero(V.inputs(gens, samples, rng)):
            try:
                out = interp.call(item["fn"]["name"], list(args))
            except Exception:  # noqa: BLE001 -- outside the reference domain (e.g. b == 0)
                continue
            if V.finite(out):
                rows.append((list(args), out))
        cases[item["fn"]["name"]] = rows
    return cases


def _with_negative_zero(arg_sets: list[tuple]) -> list[tuple]:
    """``arg_sets`` plus, for each tuple with a float argument +0.0, the same tuple with -0.0 there: a target
    that loses the sign of a zero literal (Go's constant -0.0 is +0) then fails a cell, since cells compare
    zeros by sign."""
    out, seen = list(arg_sets), {repr(t) for t in arg_sets}
    for t in arg_sets:
        if any(type(a) is float and a == 0 and math.copysign(1.0, a) > 0 for a in t):
            neg = tuple(-0.0 if type(a) is float and a == 0 else a for a in t)
            if repr(neg) not in seen:
                seen.add(repr(neg))
                out.append(neg)
    return out


def run_language(ctx: Ctx, lang: str, fns: list[dict], cases: dict) -> dict:
    lang_card = ctx.language(lang)
    ok, why = ctx.available(lang)
    cells: dict[str, dict] = {}
    if not ok:
        return {"available": False, "reason": why, "cells": {f["fn"]["name"]: {"status": "unavailable"} for f in fns}}
    bits = lang_card.get("int_bits")
    emittable = []
    for item in fns:
        name = item["fn"]["name"]
        try:
            Emitter(ctx.store, lang, ctx.ops).program({"entry": name, "functions": [item["fn"]]}, [])
            emittable.append(item)
        except EmitGap as exc:
            cells[name] = {"status": "gap", "reason": str(exc)}
    calls, index = [], []
    for item in emittable:
        name = item["fn"]["name"]
        for args, exp in cases[name]:
            if all(V.fits(a, bits) for a in args) and V.fits(exp, bits):
                calls.append((name, args))
                index.append((name, args, exp))

    def execute(items, calls_):
        module = {"entry": items[0]["fn"]["name"], "functions": [i["fn"] for i in items]}
        return run_calls(Emitter(ctx.store, lang, ctx.ops), lang_card, module, calls_, ctx.state_root,
                         entries=[i["fn"]["name"] for i in items])

    if emittable:
        res = execute(emittable, calls)
        if res.status == "ok" and len(res.values) == len(index):
            per: dict[str, dict] = {}
            for (name, args, exp), got in zip(index, res.values):
                c = per.setdefault(name, {"status": "pass", "checks": 0})
                c["checks"] += 1
                if c["status"] == "pass" and not V.same(exp, got, signed_zero=True):
                    c.update(status="fail", args=args, expected=exp, got=got)
            for item in emittable:
                n = item["fn"]["name"]
                cells[n] = per.get(n, {"status": "pass", "checks": 0, "note": "no in-domain inputs"})
        else:
            # isolate: one program per function, so a single bad template cannot hide the rest
            for item in emittable:
                n = item["fn"]["name"]
                my = [(nm, a) for nm, a in calls if nm == n]
                exp = [e for nm, a, e in index if nm == n]
                r = execute([item], my)
                if r.status != "ok" or len(r.values) != len(exp):
                    cells[n] = {"status": "error", "run": r.status,
                                "detail": (r.detail or r.stderr or f"{len(r.values)}/{len(exp)} values")[-600:]}
                    continue
                bad = next(((a, e, g) for (_, a), e, g in zip(my, exp, r.values) if not V.same(e, g, signed_zero=True)), None)
                cells[n] = {"status": "pass", "checks": len(exp)} if bad is None else \
                    {"status": "fail", "checks": len(exp), "args": bad[0], "expected": bad[1], "got": bad[2]}
    return {"available": True, "probe": why, "cells": cells}


def matrix(ctx: Ctx, langs: list[str] | None = None, seed: int | None = None,
           samples: int = DEFAULT_SAMPLES, ops: list[str] | None = None) -> dict:
    seed = V.fresh_seed() if seed is None else seed
    rng = random.Random(seed)
    fns = [f for f in op_functions(ctx.ops) if not ops or f["op"] in ops]
    cases = _cases(ctx.ops, fns, rng, samples)
    langs = langs or ctx.codegen_languages()
    with ThreadPoolExecutor(max_workers=min(resources.max_parallel(), len(langs) or 1)) as pool:
        results = dict(zip(langs, pool.map(lambda l: run_language(ctx, l, fns, cases), langs)))
    summary = {}
    for lang, r in results.items():
        st = [c["status"] for c in r["cells"].values()]
        summary[lang] = {k: st.count(k) for k in ("pass", "fail", "gap", "error", "unavailable")}
    rep = {"seed": seed, "samples": samples, "functions": [f["fn"]["name"] for f in fns],
           "ops": sorted({f["op"] for f in fns}), "languages": results, "summary": summary}
    return rep


def rate(report: dict) -> tuple[int, int]:
    """(passing cells, cells that count) -- gaps and unavailable languages do not count."""
    good = total = 0
    for r in report.get("languages", {}).values():
        if not r.get("available"):
            continue
        for c in r["cells"].values():
            if c["status"] in ("pass", "fail", "error"):
                total += 1
                good += c["status"] == "pass"
    return good, total
