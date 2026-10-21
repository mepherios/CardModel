"""translate — Python function -> function card -> verified native forms in every language.

Pipeline (observe -> express as cards -> verify -> translate):
  1. lift: frontend_python turns each top-level function into card IR
     (unsupported constructs are listed, never pasted through);
  2. domain: generators are inferred per parameter and narrowed until the
     reference terminates quickly (IR interpreter step budget);
  3. vectors: known-answer vectors come from running the ORIGINAL Python
     source; the IR interpreter must reproduce them (lift fidelity);
  4. forms: codegen emits the function in every language card that has a
     codegen block; each form is compiled and run on the vectors plus fresh
     seeded inputs and compared with the reference.

For fixed-width targets an input is compared only when every intermediate
value of the reference fits the language's int width (the interpreter
records the widest intermediate), so overflow is reported as out-of-width,
not as a semantic mismatch.

Honest limits (L1): equivalence is sampled (seed printed); domains are
heuristic until a person or a learned card narrows them; only the
frontend's subset lifts (see frontend_python).
"""
from __future__ import annotations

import hashlib
import random
from concurrent.futures import ThreadPoolExecutor

from ..kernel import resources

from . import values as V
from .codegen import EmitGap, Emitter, emit_module
from .context import Ctx
from .frontend_python import Lifted, lift_source, module_for
from .ir import Interpreter, StepLimit
from .runners import run_program

COUNT_LIKE = {"n", "k", "m", "count", "size", "length", "steps", "depth", "times", "exp", "e", "i", "j",
              "num", "limit", "rounds", "iterations", "power", "places", "digits", "width", "height"}
STEP_BUDGET = 200_000


def _gen_for(name: str, typ: str, narrow: int = 0) -> dict:
    if typ == "bool":
        return {"bool": True}
    if typ == "float":
        return {"float": [-100.0, 100.0] if not narrow else [-10.0, 10.0]}
    if name.lower() in COUNT_LIKE:
        return {"int": [0, (30, 12, 6)[min(narrow, 2)]]}
    return {"int": [(-50, -12, 0)[min(narrow, 2)], (50, 12, 12)[min(narrow, 2)]]}


def python_reference(module: dict, lifted: list[Lifted]):
    """The original source of the module's functions, executed (ground truth)."""
    by = {lf.name: lf for lf in lifted}
    src = "import math\n\n" + "\n\n".join(by[f["name"]].source for f in module["functions"])
    ns: dict = {"__name__": "cardmodel_reference"}
    exec(compile(src, "<reference>", "exec"), ns)  # noqa: S102 -- the user's own source, being observed
    return ns[module["entry"]], src


def infer_domain(ctx: Ctx, module: dict, ref, want: int = 24, seed: int = 0) -> tuple[list[dict], list]:
    """Pick generators under which the reference terminates within the step budget."""
    entry = next(f for f in module["functions"] if f["name"] == module["entry"])
    rng = random.Random(seed)
    interp = Interpreter(module, ctx.ops, step_limit=STEP_BUDGET)
    best: tuple[list[dict], list] = ([], [])
    for narrow in range(3):
        gens = [_gen_for(p["name"], p["type"], narrow) for p in entry["params"]]
        ok = []
        for args in V.inputs(gens, want, rng):
            try:
                interp.call(entry["name"], list(args))
                out = ref(*args)
            except (StepLimit, RecursionError):
                continue
            except Exception:  # noqa: BLE001 -- outside the function's domain (e.g. division by zero)
                continue
            if V.finite(out):
                ok.append(list(args))
        if len(ok) >= want // 2:
            return gens, ok
        if len(ok) > len(best[1]):
            best = (gens, ok)
    return best


def reference_rows(ctx: Ctx, module: dict, ref, inputs: list) -> list[dict]:
    """[{args, out, bits}] for inputs where the Python source and the IR interpreter both succeed."""
    entry = module["entry"]
    interp = Interpreter(module, ctx.ops, step_limit=STEP_BUDGET)
    rows = []
    for args in inputs:
        try:
            out = ref(*args)
        except Exception:  # noqa: BLE001 -- not in the reference domain
            continue
        try:
            got = interp.call(entry, list(args))
        except (StepLimit, RecursionError):
            continue
        rows.append({"args": list(args), "out": out, "ir_out": got, "bits": interp.max_bits})
    return rows


def lift_file_source(ctx: Ctx, source: str, names: list[str] | None = None) -> list[Lifted]:
    return lift_source(source, ctx.ops, only=None if names is None else None)


def function_card(ctx: Ctx, name: str, lifted: list[Lifted], source_label: str, seed: int,
                  samples: int = 24) -> dict:
    module = module_for(name, lifted)
    ref, ref_src = python_reference(module, lifted)
    gens, _ = infer_domain(ctx, module, ref, want=samples, seed=seed)
    rng = random.Random(seed)
    rows = reference_rows(ctx, module, ref, V.inputs(gens, samples, rng))
    mismatched = [r for r in rows if not V.same(r["out"], r["ir_out"])]
    entry = next(f for f in module["functions"] if f["name"] == name)
    forms = [{"name": "python_source", "lang": "python", "entry": name, "cost": 1.0, "runnable": True,
              "code": ref_src, "notes": "the observed original"}]
    gaps = {}
    for lang in ctx.codegen_languages():
        try:
            code = emit_module(ctx.store, ctx.ops, lang, module)
            forms.append({"name": lang, "lang": lang, "entry": name, "cost": 1.0, "runnable": True,
                          "code": code, "generated": True})
        except EmitGap as exc:
            gaps[lang] = str(exc)
    digest = hashlib.sha256(ref_src.encode()).hexdigest()[:12]
    return {
        "name": f"fn_{name}_{digest}", "category": "function", "tier": 2,
        "statement": f"{name}({', '.join(p['name'] + ': ' + p['type'] for p in entry['params'])}) -> {entry['returns']}"
                     f" lifted from {source_label}",
        "signature": {"params": entry["params"], "returns": entry["returns"]},
        "ir": module, "generators": gens,
        "vectors": [{"args": r["args"], "out": r["out"]} for r in rows if V.same(r["out"], r["ir_out"])],
        "forms": forms, "emit_gaps": gaps,
        "depends_on": sorted({f"op/{o}" for f in module["functions"] for o in _ops_in(f)}),
        "status": "suspect",
        "verification": {"lift_fidelity": {"checked": len(rows), "mismatched": len(mismatched),
                                           **({"example": mismatched[0]} if mismatched else {})}},
        "provenance": {"origin": source_label, "source_sha256_12": digest, "seed": seed},
    }


def _ops_in(fn) -> set[str]:
    from .ir import ops_used
    return {o for o in ops_used(fn) if o not in ("CALL",)}


def verify_function(ctx: Ctx, card: dict, langs: list[str] | None = None, seed: int | None = None,
                    samples: int = 16) -> dict:
    """Run every generated form on the vectors plus fresh seeded inputs; compare with the reference."""
    seed = V.fresh_seed() if seed is None else seed
    module = card["ir"]
    entry = module["entry"]
    ref_form = next((f for f in card["forms"] if f["name"] == "python_source"), None)
    if ref_form is None:                      # card-language functions: the IR itself is the reference
        interp = Interpreter(module, ctx.ops, step_limit=STEP_BUDGET)

        def ref(*args):
            return interp.call(entry, list(args))
    else:
        ns: dict = {"__name__": "cardmodel_reference"}
        exec(compile(ref_form["code"], "<reference>", "exec"), ns)  # noqa: S102
        ref = ns[entry]
    rng = random.Random(seed)
    fresh = V.inputs(card.get("generators") or [], samples, rng, edge=False)
    inputs = [v["args"] for v in card.get("vectors", [])] + [list(a) for a in fresh]
    rows = reference_rows(ctx, module, ref, inputs)
    lift_bad = [r for r in rows if not V.same(r["out"], r["ir_out"])]
    langs = langs or [f["lang"] for f in card["forms"] if f.get("generated")]
    results = {"seed": seed, "inputs": len(rows), "lift_mismatches": len(lift_bad), "languages": {}}
    if lift_bad:
        results["lift_example"] = lift_bad[0]

    def one(lang: str) -> tuple[str, dict]:
        lang_card = ctx.language(lang)
        ok, why = ctx.available(lang)
        if not ok:
            return lang, {"status": "unavailable", "reason": why}
        bits = lang_card.get("int_bits")
        usable = [r for r in rows if (bits is None or r["bits"] < bits - 1) and V.fits(r["out"], bits)
                  and all(V.fits(a, bits) for a in r["args"])]
        skipped = len(rows) - len(usable)
        if not usable:
            return lang, {"status": "no_inputs", "out_of_width": skipped}
        try:
            src = Emitter(ctx.store, lang, ctx.ops).program(module, [r["args"] for r in usable])
        except EmitGap as exc:
            return lang, {"status": "gap", "reason": str(exc)}
        run = run_program(lang_card, src, ctx.state_root)
        if run.status != "ok" or len(run.values) != len(usable):
            return lang, {"status": "error", "run": run.status,
                          "detail": (run.detail or run.stderr or f"{len(run.values)}/{len(usable)} values")[-600:]}
        bad = next(((r["args"], r["out"], g) for r, g in zip(usable, run.values) if not V.same(r["out"], g)), None)
        res = {"status": "pass" if bad is None else "fail", "checks": len(usable), "out_of_width": skipped,
               "compile_ms": round(run.compile_ms, 1), "run_ms": round(run.run_ms, 1)}
        if bad:
            res.update(args=bad[0], expected=bad[1], got=bad[2])
        return lang, res

    with ThreadPoolExecutor(max_workers=min(resources.max_parallel(), max(1, len(langs)))) as pool:
        for lang, res in pool.map(one, langs):
            results["languages"][lang] = res
    passed = sorted(l for l, r in results["languages"].items() if r["status"] == "pass")
    results["agreeing_languages"] = ["python_source" if ref_form is not None else "ir", *passed]
    return results
