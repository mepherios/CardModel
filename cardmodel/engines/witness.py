"""witness — executable claims are checked by running them (hub L47, Pheros L34/L41).

Four witnesses, all seeded (the seed is returned and printed; pass it back
to reproduce, L17/L28):

  forms    every runnable form of a card against the card's reference form
           on inputs from the FORM's domain (domain cards supply generators
           and reference projections, e.g. u32 compares modulo 2**32).
           Python forms run in-process; forms in other languages ("hints")
           are compiled and run through their language card. A form that
           records the hub's original domain (``hub_domain``) is also run
           on that domain, so an overstated claim shows as refuted.
  vectors  known-answer vectors (``vectors`` inline or a vectors.json
           variant) against every available form: Python in-process,
           JavaScript in Node (call protocol, rich values).
  rules    rewrite rules: lhs and rhs evaluated exactly on seeded ints.
  anti-vacuity  (L41) each witness also checks that it can fail: the
           comparator must reject a perturbed value, and checks that ran
           zero times are reported as vacuous, not as passes.

Honest limits (L1): sampling, not proof; documentation-only forms are
reported as such and never counted as verified.
"""
from __future__ import annotations

import contextlib
import inspect
import json
import math
import random
import signal
import threading
import types

from . import values as V
from .codegen import EmitGap, Emitter
from .context import Ctx
from .exprs import evaluate, parse
from .rewrite import available, forms_of
from .runners import call_node, call_python, run_program

_LIB_CACHE: dict[str, dict] = {}
FORM_TIME_LIMIT_S = 20


class TimeLimit(Exception):
    pass


@contextlib.contextmanager
def time_limit(seconds: float):
    """Best-effort wall-clock budget for in-process checks (L20). Works in the main thread on POSIX;
    a single long C-level operation (e.g. a huge big-int power) finishes before the alarm fires."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        yield
        return

    def _raise(signum, frame):
        raise TimeLimit(f"exceeded {seconds}s")

    old = signal.signal(signal.SIGALRM, _raise)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


def lib_namespace(ctx: Ctx, libs: list[str]) -> dict:
    ns: dict = {math.__name__: math}           # the Python module, named by itself (not the math language card)
    for name in libs or []:
        if name not in _LIB_CACHE:
            card = ctx.store.get(f"lib/{name}")
            if card is None:
                raise KeyError(f"lib card {name!r} missing")
            src = card.read_variant("python.py")
            if src is None:
                raise KeyError(f"lib/{name} has no python.py variant")
            mod = types.ModuleType(f"cardmodel_lib_{name}")
            exec(compile(src, f"<lib {name}>", "exec"), mod.__dict__)  # noqa: S102 -- card code
            exports = {card.get("module_alias", name): mod}
            if card.get("export_names"):
                exports.update({k: v for k, v in mod.__dict__.items() if not k.startswith("__")})
            _LIB_CACHE[name] = exports
        ns.update(_LIB_CACHE[name])
    return ns


def python_callable(ctx: Ctx, form: dict, card=None):
    """A Python form as a callable: an expression (``code``) or a module (``code``/``file`` + ``entry``)."""
    ns = lib_namespace(ctx, form.get("libs") or [])
    ns["__builtins__"] = __builtins__
    if form.get("entry"):
        src = form.get("code")
        if src is None and form.get("file") and card is not None:
            src = card.read_variant(form["file"])
            if card.path is not None:
                ns["__file__"] = str(card.path / form["file"])
        if src is None:
            raise KeyError(f"form {form.get('name')!r}: no code and no readable {form.get('file')!r}")
        ns["__name__"] = f"cardmodel_form_{form.get('name')}"
        exec(compile(src, f"<form {form.get('name')}>", "exec"), ns)  # noqa: S102 -- card code
        return ns[form["entry"]]
    return eval(compile(form["code"], f"<form {form.get('name')}>", "eval"), ns)  # noqa: S307 -- card code


def _projection(ctx: Ctx, domain: str):
    card = ctx.store.get(f"domain/{domain}")
    text = card.get("project_reference") if card else None
    return eval(text, {"__builtins__": {}}) if text else None  # noqa: S307 -- trusted domain card


def _generators(ctx: Ctx, card, form: dict, arity: int, domain: str | None = None) -> list[dict]:
    """Inputs for checking ``form`` on ``domain``: the card's per-domain generators first, then a
    sub-domain's own generator, then the card's generators, then the domain's, then a default."""
    domain = domain or form.get("domain", "any")
    per = (card.get("domain_generators") or {}).get(domain)
    if per:
        return list(per)
    dcard = ctx.store.get(f"domain/{domain}")
    if dcard and dcard.get("generator") and domain not in ("int", "any", "float"):
        return [dcard["generator"]] * arity
    if card.get("generators"):
        return list(card["generators"])
    ir = card.get("ir") or {}
    for key in ("int", "float", "bool"):
        if (ir.get("domain") or {}).get(key):
            return list(ir["domain"][key])
    if dcard and dcard.get("generator"):
        return [dcard["generator"]] * arity
    return [V.DEFAULT_GEN["int"]] * arity


def _arity(card, ref) -> int:
    ir = card.get("ir") or {}
    if ir.get("arity"):
        return int(ir["arity"])
    if card.get("generators"):
        return len(card["generators"])
    try:
        params = inspect.signature(ref).parameters.values()
    except (TypeError, ValueError):
        return 2
    if any(p.kind is p.VAR_POSITIONAL for p in params):
        return 2  # f(*args): no fixed arity; cards should declare generators
    return len(params)


def _reference(card):
    forms = card.get("forms") or []
    name = card.get("reference_form")
    for f in forms:
        if name and f.get("name") == name:
            return f
    for f in forms:
        if f.get("lang", "python") == "python" and f.get("runnable", True) and (f.get("code") or f.get("file")) \
                and not f.get("probe"):
            return f
    return None


def _run_python_form(fn, rows):
    outs = []
    for args in rows:
        try:
            outs.append(("ok", fn(*args)))
        except Exception as exc:  # noqa: BLE001 -- an exception is a result to compare
            outs.append(("err", type(exc).__name__))
    return outs


def _compare(card, ref_rows, outs, project) -> dict:
    checks, bad = 0, None
    for (args, exp), (kind, got) in zip(ref_rows, outs):
        want = project(exp) if project and isinstance(exp, int) and not isinstance(exp, bool) else exp
        checks += 1
        if kind != "ok" or not V.same(want, got):
            bad = {"args": list(args), "expected": want, "got": got if kind == "ok" else f"raised {got}"}
            break
    if checks == 0:
        return {"status": "vacuous", "checks": 0}
    return {"status": "pass", "checks": checks} if bad is None else {"status": "fail", "checks": checks, **bad}


def _ref_rows(ref_fn, gens, n, rng, filt):
    rows = []
    for args in V.inputs(gens, n, rng, filt=filt):
        try:
            out = ref_fn(*args)
        except Exception:  # noqa: BLE001 -- outside the reference's domain
            continue
        if V.finite(out) and out is not None:
            rows.append((args, out))
    return rows


def _raw_form_run(ctx: Ctx, card, form: dict, rows, arg_types: list[str], ret_type: str):
    lang = form["lang"]
    params = [{"name": f"a{i}", "type": t} for i, t in enumerate(arg_types)]
    fn = {"name": "hint_form", "params": params, "returns": ret_type, "locals": {},
          "body": [{"k": "return", "value": ["RAW", lang, form["code"], ret_type,
                                             *[["var", p["name"]] for p in params]]}]}
    lang_card = ctx.language(lang)
    bits = lang_card.get("int_bits")
    usable = [(a, e) for a, e in rows if all(V.fits(x, bits) for x in a) and V.fits(e, bits)]
    src = Emitter(ctx.store, lang, ctx.ops).program({"entry": "hint_form", "functions": [fn]}, [list(a) for a, _ in usable])
    run = run_program(lang_card, src, ctx.state_root)
    if run.status != "ok" or len(run.values) != len(usable):
        return usable, None, (run.detail or run.stderr or run.status)[-500:]
    return usable, [("ok", v) for v in run.values], None


def verify_forms(ctx: Ctx, card, seed: int | None = None, samples: int = 64, include_hub_claims: bool = True) -> dict:
    """Every runnable form vs the reference form. Returns {"seed", "reference", "forms": {name: result}}."""
    seed = V.fresh_seed() if seed is None else seed
    ref = _reference(card)
    if ref is None:
        return {"seed": seed, "reference": None, "forms": {}, "note": "no runnable python reference form"}
    ref_fn = python_callable(ctx, ref, card)
    arity = _arity(card, ref_fn)
    filt = eval(card["filter"], {math.__name__: math, "__builtins__": {}}) if card.get("filter") else None  # noqa: S307
    ir = card.get("ir") or {}
    sig = (ir.get("types") or [["int"] * arity + ["int"]])[0]
    out = {"seed": seed, "reference": ref["name"], "forms": {}}
    for i, f in enumerate(card.get("forms") or []):
        name = f.get("name")
        if f is ref:
            continue
        fv = forms_of({"name": card["name"], "forms": [f]})[0]
        ok, why = available(ctx.store, fv)
        if not fv.runnable:
            out["forms"][name] = {"status": "documentation_only", "reason": why}
            continue
        if not ok:
            out["forms"][name] = {"status": "unavailable", "reason": why}
            continue
        domains = [f.get("domain", "any")]
        if include_hub_claims and f.get("hub_domain"):
            domains.append(f["hub_domain"])
        results = {}
        for j, dom in enumerate(domains):
            rng = random.Random(f"{seed}:{card['name']}:{name}:{dom}")
            gens = _generators(ctx, card, f, arity, dom)
            project = _projection(ctx, dom)
            try:
                with time_limit(FORM_TIME_LIMIT_S):
                    rows = _ref_rows(ref_fn, gens, samples, rng, filt)
                    if f.get("lang", "python") == "python":
                        fn = python_callable(ctx, f, card)
                        outs = _run_python_form(fn, [a for a, _ in rows])
                        res = _compare(card, rows, outs, project)
                    else:
                        usable, outs, err = _raw_form_run(ctx, card, f, rows, list(sig[:-1]), sig[-1])
                        res = {"status": "error", "detail": err} if outs is None else \
                            _compare(card, usable, outs, project)
            except (EmitGap, KeyError, SyntaxError, NameError, TimeLimit) as exc:
                res = {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}
            res["domain"] = dom
            results["declared" if j == 0 else "hub_claim"] = res
        merged = dict(results["declared"])
        if "hub_claim" in results:
            merged["hub_claim"] = {k: v for k, v in results["hub_claim"].items() if k != "domain"} | \
                                  {"domain": f["hub_domain"]}
        out["forms"][name] = merged
    if not out["forms"]:
        out["note"] = "single form: nothing to compare (IR ops are checked by the conformance matrix)"
    out["comparator_rejects_perturbation"] = not V.same(1, 2) and not V.same(1.0, 1.0 + 1e-6)
    return out


def load_vectors(card) -> list[dict]:
    v = card.get("vectors")
    if isinstance(v, list):
        return v
    if isinstance(v, str):
        text = card.read_variant(v)
        if text is None:
            raise FileNotFoundError(f"{card.qualified}: vectors file {v!r} missing")
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError(f"{card.qualified}: {v} must hold a list of vectors")
        return data
    return []


def _decode_args(vec):
    from .runners import decode
    return [decode(a) for a in vec.get("args", [])]


def verify_vectors(ctx: Ctx, card) -> dict:
    """Known-answer vectors against every available form (python in-process, javascript in Node)."""
    from .runners import decode
    vectors = load_vectors(card)
    out = {"vectors": len(vectors), "forms": {}}
    if not vectors:
        out["status"] = "no_vectors"
        return out
    calls = [_decode_args(v) for v in vectors]
    for f in card.get("forms") or []:
        name, lang = f.get("name"), f.get("lang", "python")
        code = f.get("code") if f.get("code") and f.get("entry") else (card.read_variant(f["file"]) if f.get("file") else None)
        if not f.get("entry") or code is None:
            out["forms"][name] = {"status": "documentation_only"}
            continue
        lang_card = ctx.store.get(f"language/{lang}")
        runner = (lang_card or {}).get("call_runner")   # the call protocol is data on the language card
        fv = forms_of({"name": card.name, "forms": [{**f, "code": code}]})[0]
        ok, why = available(ctx.store, fv) if runner == "inprocess" else ctx.available(lang) if lang_card \
            else (False, f"no language card {lang!r}")
        if not ok:
            out["forms"][name] = {"status": "unavailable", "reason": why}
            continue
        try:
            if runner == "inprocess":
                lib = dict(lib_namespace(ctx, f.get("libs") or []))
                if f.get("file") and card.path is not None:
                    lib["__file__"] = str(card.path / f["file"])
                results = call_python(code, f["entry"], calls, lib)
            elif runner == "node":
                results = call_node(code, f["entry"], calls)
            else:
                out["forms"][name] = {"status": "unsupported_lang",
                                      "reason": f"language card {lang!r} declares no call_runner"}
                continue
        except Exception as exc:  # noqa: BLE001 -- reported as the form's status
            out["forms"][name] = {"status": "error", "detail": f"{type(exc).__name__}: {exc}"}
            continue
        bad = None
        for vec, r in zip(vectors, results):
            if vec.get("error"):
                if r.ok:
                    bad = {"vector": vec.get("name"), "expected": "an error", "got": r.value}
                    break
                continue
            if "out_one_of" in vec:
                if not r.ok or not any(V.same(decode(w), r.value) for w in vec["out_one_of"]):
                    bad = {"vector": vec.get("name"), "expected": vec["out_one_of"],
                           "got": r.value if r.ok else f"raised {r.error}"}
                    break
                continue
            want = decode(vec.get("out"))
            if not r.ok or not V.same(want, r.value):
                bad = {"vector": vec.get("name"), "expected": vec.get("out"),
                       "got": (r.value.hex() if isinstance(r.value, bytes) else r.value) if r.ok else f"raised {r.error}"}
                break
        out["forms"][name] = {"status": "pass", "checks": len(vectors)} if bad is None else \
            {"status": "fail", **bad}
    statuses = [r["status"] for r in out["forms"].values()]
    out["status"] = "pass" if "pass" in statuses and "fail" not in statuses and "error" not in statuses else \
        ("fail" if "fail" in statuses or "error" in statuses else "vacuous")
    return out


def verify_rule(card, seed: int | None = None, samples: int = 64) -> dict:
    """lhs == rhs on seeded integers (respecting ``condition``); also checks the witness can fail."""
    seed = V.fresh_seed() if seed is None else seed
    rng = random.Random(f"{seed}:{card['name']}")
    vars_ = card.get("vars") or []
    lhs, rhs = parse(card["lhs"]), parse(card["rhs"])
    cond = parse(card["condition"]) if card.get("condition") else None
    gens = [{"int": [0, 24]} if v in ("k", "n", "e") else {"int": [-60, 60]} for v in vars_]
    checks, bad, perturbed_caught = 0, None, False
    for args in V.inputs(gens, samples, rng):
        env = dict(zip(vars_, args))
        try:
            if cond is not None and not evaluate(cond, env):
                continue
            a, b = evaluate(lhs, env), evaluate(rhs, env)
        except (ArithmeticError, ValueError):
            continue
        checks += 1
        if not V.same(a, b):
            bad = {"env": env, "lhs": a, "rhs": b}
            break
        perturbed_caught = perturbed_caught or not V.same(a, b + 1)
    if checks == 0:
        return {"status": "vacuous", "seed": seed, "checks": 0}
    res = {"status": "pass" if bad is None else "fail", "seed": seed, "checks": checks,
           "witness_can_fail": perturbed_caught}
    if bad:
        res["counterexample"] = bad
    return res
