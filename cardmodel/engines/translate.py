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

from . import godel as G
from . import values as V
from .codegen import EmitGap, Emitter, emit_module, predicted_gap, ranked_content
from .context import Ctx
from .frontend_python import Lifted, lift_source, module_for
from .ir import Interpreter, StepLimit, elem_type
from .runners import run_calls

COUNT_LIKE = {"n", "k", "m", "count", "size", "length", "steps", "depth", "times", "exp", "e", "i", "j",
              "num", "limit", "rounds", "iterations", "power", "places", "digits", "width", "height",
              "d", "rows", "cols", "dim", "seq", "heads"}
STEP_BUDGET = 200_000
PREDICT_GAPS = True      # refuse a language from the term's content (its gap, GODEL_TARGET G11) before emitting


def _gen_for(name: str, typ: str, narrow: int = 0) -> dict:
    et = elem_type(typ)
    if et is not None:
        elem = {"float": [-10.0, 10.0] if not narrow else [-3.0, 3.0]} if et == "float" else \
            {"int": [-50, 50] if not narrow else [-12, 12]}
        return {"list": elem, "len": [0, (8, 6, 4)[min(narrow, 2)]]}
    if typ == "str":
        # the full alphabet first (non-ASCII, escapes), then a small one where equal pieces are likely, then
        # decimal digits (a function that parses its argument runs on nothing else)
        return ({"str": [0, 8]}, {"str": [0, 5], "alphabet": "ab ,-1\u00e9\U0001f600"},
                {"str": [1, 6], "alphabet": "0123456789"})[min(narrow, 2)]
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
    # the frontend lifts bare gcd(a, b) as math.gcd, so the reference must define it too (else every input
    # raises NameError, is dropped as "outside the domain" and the function is verified on nothing)
    entry = by[module["entry"]]
    src = "import math\nfrom math import gcd\n" + getattr(entry, "preamble", "") + "\n" + \
        "\n\n".join(by[f["name"]].source for f in module["functions"])
    ns: dict = {"__name__": "cardmodel_reference"}
    exec(compile(src, "<reference>", "exec"), ns)  # noqa: S102 -- the user's own source, being observed
    return ns[module["entry"]], src


def infer_domain(ctx: Ctx, module: dict, ref, want: int = 24, seed: int = 0) -> tuple[list[dict], list]:
    """Pick generators under which the reference terminates within the step budget."""
    entry = next(f for f in module["functions"] if f["name"] == module["entry"])
    rng = random.Random(seed)
    interp = Interpreter(module, ctx.ops, step_limit=STEP_BUDGET)
    best: tuple[list[dict], list] = ([], [])
    shapes = _list_shapes(entry["params"])
    # without lists, half the inputs running is enough; with lists a wrong shape still runs on some inputs (a
    # matrix as a vector when a dimension is 1, an n x m list read as n x k while k <= m), so a list shape is taken
    # at once only when every input runs, else the shape that ran the most inputs wins
    lists = shapes != [{}]
    for narrow, shape in ((n, sh) for sh in shapes for n in range(3)):
        gens = [_gen_for(p["name"], p["type"], narrow) for p in entry["params"]]
        for i, spec in shape.items():
            gens[i] = {**{k: v for k, v in gens[i].items() if k != "len"}, **spec}
        ok = []
        tried = V.inputs(gens, want, rng)
        for args in tried:
            try:
                interp.call(entry["name"], list(args))
                out = ref(*args)
            except (StepLimit, RecursionError):
                continue
            except Exception:  # noqa: BLE001 -- outside the function's domain (e.g. division by zero)
                continue
            if V.finite(out):
                ok.append(list(args))
        if len(ok) >= want // 2 and (not lists or len(ok) == len(tried)):
            return gens, ok
        if len(ok) > len(best[1]):
            best = (gens, ok)
    return best


def _list_shapes(params: list[dict], cap: int = 48) -> list[dict]:
    """Candidate lengths for the list parameters: free, or the product of one or two int parameters (a vector of
    length n, an n x k matrix passed with its dimensions). The first shape under which the function runs wins."""
    lists = [i for i, p in enumerate(params) if elem_type(p["type"]) is not None]
    if not lists:
        return [{}]
    ints = [i for i, p in enumerate(params) if p["type"] == "int"]
    options = [{"len": [0, 8]}] + [{"len_of": [j]} for j in ints] + \
        [{"len_of": [j, k]} for a, j in enumerate(ints) for k in ints[a:]]
    shapes: list[dict] = [{}]
    for n_, i in enumerate(lists):
        mine = options + [{"len_like": j} for j in lists[:n_]]
        shapes = [{**sh, i: o} for sh in shapes for o in mine]
        if len(shapes) > cap * 8:
            break
    # dimension-tied shapes first: a function that indexes a matrix fails on random lengths
    # then two-dimension products (matrices passed with their sizes), then shapes where the lists agree
    def rank(sh):
        tied = sum("len" not in o for o in sh.values())
        dims2 = sum(len(o.get("len_of", ())) == 2 for o in sh.values())
        kinds = len({repr(o) for o in sh.values() if "len_like" not in o})
        return (-tied, -dims2, kinds) if len(lists) > 1 else (0, 0, 0)
    shapes.sort(key=rank)
    return shapes[:cap]


def reference_rows(ctx: Ctx, module: dict, ref, inputs: list) -> list[dict]:
    """[{args, out, bits}] for inputs where the Python source and the IR interpreter both succeed.

    The step-bounded interpreter runs first: the original source has no bound, so an input on which it never
    returns (``while n != 0: n >>= 1`` for a negative n) must be dropped before the source is called."""
    entry = module["entry"]
    interp = Interpreter(module, ctx.ops, step_limit=STEP_BUDGET)
    rows = []
    for args in inputs:
        failed = None
        try:
            got = interp.call(entry, list(args))
        except (StepLimit, RecursionError):
            continue
        except Exception as exc:  # noqa: BLE001 -- decided below, by whether the source fails too
            failed = exc
        try:
            out = ref(*args)
        except Exception:  # noqa: BLE001 -- not in the reference domain
            continue
        if isinstance(out, complex):   # left the reals (negative base ** fraction): outside the real domain
            continue
        if failed is not None:
            raise failed
        rows.append({"args": list(args), "out": out, "ir_out": got, "bits": interp.max_bits})
    return rows


def lift_file_source(ctx: Ctx, source: str, names: list[str] | None = None) -> list[Lifted]:
    return lift_source(source, ctx.ops, only=None if names is None else None)


def ir_reference(ctx: Ctx, module: dict, lifted: list):
    """For a source that is not Python: the IR interpreter is the reference (frontends.witness_source checks it
    against the original source run by its own toolchain), and the original text is kept as the source form."""
    by = {lf.name: lf for lf in lifted}
    src = "\n\n".join(by[f["name"]].source for f in module["functions"] if f["name"] in by)
    interp = Interpreter(module, ctx.ops, step_limit=STEP_BUDGET)

    def ref(*args):
        return interp.call(module["entry"], list(args))
    return ref, src


def function_card(ctx: Ctx, name: str, lifted: list[Lifted], source_label: str, seed: int,
                  samples: int = 24, lang: str = "python") -> dict:
    module = module_for(name, lifted)
    if lang == "python":
        ref, ref_src = python_reference(module, lifted)
    else:
        ref, ref_src = ir_reference(ctx, module, lifted)
    gens, _ = infer_domain(ctx, module, ref, want=samples, seed=seed)
    rng = random.Random(seed)
    rows = reference_rows(ctx, module, ref, V.inputs(gens, samples, rng))
    mismatched = [r for r in rows if not V.same(r["out"], r["ir_out"])]
    entry = next(f for f in module["functions"] if f["name"] == name)
    forms = [{"name": "python_source", "lang": "python", "entry": name, "cost": 1.0, "runnable": True,
              "code": ref_src, "notes": "the observed original"}] if lang == "python" else \
        [{"name": f"{lang}_source", "lang": lang, "entry": name, "cost": 1.0, "runnable": True, "original": True,
          "code": ref_src, "notes": "the observed original (witnessed by frontends.witness_source)"}]
    content = G.module_content(module, ctx.ops)
    ranked = ranked_content(ctx.ops, module)        # the same content at rank level: a gap at one rank is seen too
    gaps, predicted = {}, {}
    for lang in ctx.codegen_languages():
        missing = predicted_gap(ranked, ctx.language_gap(lang)) if PREDICT_GAPS else []
        if missing:                        # known from the content: the language has no template for these atoms
            predicted[lang] = missing
            gaps[lang] = f"{lang}: no template for {', '.join(missing)} (predicted from the content)"
            continue
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
        "forms": forms, "emit_gaps": gaps, "predicted_gaps": predicted,
        "godel": {"content": dict(content), "ranks": dict(ranked), "read_from": "its IR"},
        "depends_on": sorted(G.support(content)),
        "status": "suspect",
        "verification": {"lift_fidelity": {"checked": len(rows), "mismatched": len(mismatched),
                                           **({"example": mismatched[0]} if mismatched else {})}},
        "provenance": {"origin": source_label, "source_sha256_12": digest, "seed": seed, "source_lang": lang},
    }


def verify_function(ctx: Ctx, card: dict, langs: list[str] | None = None, seed: int | None = None,
                    samples: int = 16) -> dict:
    """Run every generated form on the vectors plus fresh seeded inputs; compare with the reference."""
    seed = V.fresh_seed() if seed is None else seed
    module = card["ir"]
    entry = module["entry"]
    content = G.module_content(module, ctx.ops)
    ranked = ranked_content(ctx.ops, module)        # the same content at rank level: a gap at one rank is seen too
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
        missing = predicted_gap(ranked, ctx.language_gap(lang)) if PREDICT_GAPS else []
        if missing:
            return lang, {"status": "gap", "reason": f"{lang}: no template for {', '.join(missing)} (predicted "
                                                     f"from the content)"}
        try:
            run = run_calls(Emitter(ctx.store, lang, ctx.ops), lang_card, module, [r["args"] for r in usable],
                            ctx.state_root)
        except EmitGap as exc:
            return lang, {"status": "gap", "reason": str(exc)}
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
