"""run — execute a card-language module: tests, queries, theorems, constraints; build its cards; emit natively.

``run`` evaluates the module's logic to a fixpoint (functions are callable
from rules), runs every ``test`` (a function test must be true; a logic test
must be provable, or unprovable for ``not``), answers every ``query``,
witnesses every ``theorem`` with a seed (``lean=True`` also asks the Lean
kernel) and reports constraint violations with their proofs.

``build`` turns the module into cards: a ``program`` card, a ``theory`` card,
one ``logic_rule`` card per rule, a ``fact`` pack, ``theorem`` cards with
their evidence, ``function`` cards (IR + generated forms for every language
card, verified by ``cardmodel verify --only functions``) and the module's own
``card`` declarations.

Honest limits (L1): function verification inputs come from the ``requires``
contract (bounds on parameters) or a small default range; tests and queries
see the closed world of the module (and the modules it ``use``s).
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path

from ..engines import logic as L
from ..engines import theorems as T
from ..engines import values as V
from ..engines.codegen import EmitGap, emit_module
from ..engines.ir import Interpreter, IRError, StepLimit
from .compile import Module

DEFAULT_RANGE = (-50, 50)


def _caller(ctx, mod: Module):
    if not mod.functions:
        return None, None
    interp = Interpreter(mod.ir_module(), ctx.ops, step_limit=5_000_000)

    def call(name, args):
        if name not in interp.funcs:
            raise L.LogicError(f"unknown function {name}()")
        return interp._call(name, list(args), 0)

    return call, interp


def run(ctx, mod: Module, seed: int | None = None, lean: bool = False, samples: int = 300,
        query_limit: int = 50, deep: bool = False) -> dict:
    seed = V.fresh_seed() if seed is None else seed
    call, _ = _caller(ctx, mod)
    rep = {"module": mod.name, "path": mod.path, "seed": seed, "summary": mod.summary(), "tests": [],
           "queries": [], "theorems": [], "violations": [], "logic": None}
    model = None
    if mod.program.facts or mod.program.rules:
        model = L.evaluate(mod.program, ctx.ops, call=call)
        rep["logic"] = model.stats
        rep["violations"] = model.violations
    for t in mod.tests:
        rep["tests"].append(_run_test(ctx, t, model, call))
    for q in mod.queries:
        text = ", ".join(str(x) for x in q["literals"])
        if model is None:
            rep["queries"].append({"line": q["line"], "query": text, "error": "the module has no facts or rules"})
            continue
        answers = model.query(q["literals"], limit=query_limit + 1)
        rep["queries"].append({"line": q["line"], "query": text, "answers": answers[:query_limit],
                               "more": len(answers) > query_limit,
                               "holds": bool(answers)})
    settled = []
    for card in mod.theorems:
        w = T.witness(card, ctx.ops, seed=seed, samples=samples, call=call)
        settled.append((card, w))
    proofs, exe = {}, None
    if lean:
        provable = [c for c, w in settled if w["status"] == "witnessed"]
        if provable:
            res = T.prove(provable, ctx.store, ctx.ops, deep=deep)
            proofs, exe = res["results"], res["toolchain"]
    for card, w in settled:
        rep["theorems"].append(T.settle(card, w, proofs.get(card["name"]), exe))
    failed_tests = [t for t in rep["tests"] if t["status"] != "pass"]
    refuted = [t for t in rep["theorems"] if t["status"] == "refuted" or t.get("evidence", {}).get("status") == "vacuous"]
    rep["status"] = "fail" if failed_tests or refuted or rep["violations"] else "pass"
    rep["counts"] = {"tests": len(rep["tests"]), "tests_failed": len(failed_tests),
                     "theorems": {s: sum(1 for t in rep["theorems"] if t["status"] == s)
                                  for s in sorted({t["status"] for t in rep["theorems"]})},
                     "violations": len(rep["violations"]), "queries": len(rep["queries"])}
    return rep


def _run_test(ctx, t: dict, model, call) -> dict:
    out = {"line": t["line"]}
    try:
        if t["kind"] == "expr":
            out["test"] = L.expr_text(t["expr"])
            v = L.eval_expr(t["expr"], {}, ctx.ops, call)
            out["value"] = v if isinstance(v, (bool, int, float, str)) else repr(v)
            out["status"] = "pass" if L._truth(v) else "fail"
            return out
        lits = t["literals"]
        out["test"] = ", ".join(str(x) for x in lits)
        if model is None:
            out.update(status="fail", reason="the module has no facts or rules")
            return out
        sols = model.query(lits, limit=1)
        out["status"] = "pass" if sols else "fail"
        if sols and sols[0]:
            out["witness"] = sols[0]
        first = lits[0]
        if sols and isinstance(first, L.Atom):
            args = [sols[0].get(a.name) if isinstance(a, L.Var) else a for a in first.args]
            try:
                out["proof"] = L.proof_stats(model.proof(first.pred, args))
            except L.LogicError:
                pass
        if not sols:
            out["reason"] = "not provable from the module's facts and rules"
    except (L.LogicError, IRError, StepLimit, ArithmeticError, ValueError, TypeError) as exc:
        out.update(status="error", reason=f"{type(exc).__name__}: {exc}")
    return out


# -- text report ----------------------------------------------------------------------------------------
def report_text(rep: dict, verbose: bool = False) -> str:
    s = rep["summary"]
    lines = [f"module {rep['module']} (seed {rep['seed']}): {len(s['functions'])} function(s), {s['facts']} fact(s), "
             f"{s['rules']} rule(s), {s['constraints']} constraint(s), {len(s['theorems'])} theorem(s)"]
    if s.get("resolved"):
        for k, v in s["resolved"].items():
            lines.append(f"  resolved {k} -> form {v['form']} ({v.get('complexity') or 'cost ' + str(v.get('cost'))};"
                         f" precondition {v.get('precondition') or 'none'})")
    if rep.get("logic"):
        lg = rep["logic"]
        lines.append(f"  logic: {lg['facts']} facts ({lg['derived']} derived) in {lg['rounds']} rounds, "
                     f"{lg['strata']} strata")
    for t in rep["tests"]:
        mark = "ok  " if t["status"] == "pass" else "FAIL"
        extra = ""
        if t.get("proof"):
            extra = f"   [proof: {t['proof']['steps']} step(s), height {t['proof']['height']}]"
        if t["status"] != "pass":
            extra = f"   <- {t.get('reason') or 'got ' + repr(t.get('value'))}"
        lines.append(f"  {mark} test  line {t['line']}: {t.get('test')}{extra}")
    for q in rep["queries"]:
        if "error" in q:
            lines.append(f"  ?- {q['query']}: {q['error']}")
            continue
        if q["answers"] and q["answers"][0]:
            shown = "; ".join(", ".join(f"{k} = {L.term_text(v)}" for k, v in a.items()) for a in q["answers"][:12])
            more = f"  (+{len(q['answers']) - 12} more)" if len(q["answers"]) > 12 else ""
            lines.append(f"  ?- {q['query']}\n     {shown}{more}")
        else:
            lines.append(f"  ?- {q['query']}\n     {'yes' if q['holds'] else 'no'}")
    for th in rep["theorems"]:
        ev = th.get("evidence") or {}
        how = ", ".join(p["method"] for p in th.get("proofs") or [] if p.get("ok"))
        detail = f"{ev.get('checks', 0)} checks" + (f"; {how}" if how else "")
        if th["status"] == "refuted":
            detail = f"counterexample {ev.get('counterexample')}" + (f" ({ev['reason']})" if ev.get("reason") else "")
        elif ev.get("status") == "vacuous":
            detail = ev.get("reason", "")
        elif th.get("lean_status") and verbose:
            detail += f"; Lean: {th['lean_status'].get('status')} {th['lean_status'].get('detail', '')}"
        lines.append(f"  {th['status']:<10} theorem {th.get('label', th['name'])}: {th['statement']}   [{detail}]")
    for v in rep["violations"]:
        lines.append(f"  VIOLATED {v['rule']} with {v['bindings']}")
    lines.append(f"{rep['status']}: {rep['counts']['tests'] - rep['counts']['tests_failed']}/{rep['counts']['tests']} "
                 f"tests, theorems {rep['counts']['theorems'] or '{}'}, {rep['counts']['violations']} violation(s)")
    return "\n".join(lines)


# -- build: module -> cards --------------------------------------------------------------------------------
def _bounds(fn: dict) -> list[dict]:
    """Generators from the ``requires`` contract: literal bounds on parameters, else a small default range."""
    lo = {p["name"]: None for p in fn["params"]}
    hi = {p["name"]: None for p in fn["params"]}
    for p in fn.get("nat_params") or []:
        lo[p] = 0

    def visit(c):
        if c[0] == "AND":
            visit(c[1])
            visit(c[2])
            return
        if c[0] not in ("CMP_LE", "CMP_LT", "CMP_GE", "CMP_GT") or len(c) != 3:
            return
        a, b = c[1], c[2]
        op = c[0]
        if a[0] == "int" and b[0] == "var":
            a, b = b, a
            op = {"CMP_LE": "CMP_GE", "CMP_LT": "CMP_GT", "CMP_GE": "CMP_LE", "CMP_GT": "CMP_LT"}[op]
        if a[0] == "var" and b[0] == "int" and a[1] in lo:
            v = b[1]
            if op == "CMP_LE":
                hi[a[1]] = v if hi[a[1]] is None else min(hi[a[1]], v)
            elif op == "CMP_LT":
                hi[a[1]] = v - 1 if hi[a[1]] is None else min(hi[a[1]], v - 1)
            elif op == "CMP_GE":
                lo[a[1]] = v if lo[a[1]] is None else max(lo[a[1]], v)
            elif op == "CMP_GT":
                lo[a[1]] = v + 1 if lo[a[1]] is None else max(lo[a[1]], v + 1)

    for c in fn.get("requires") or []:
        visit(c)
    gens = []
    for p in fn["params"]:
        if p["type"] == "bool":
            gens.append({"bool": True})
        elif p["type"] == "float":
            gens.append({"float": [float(lo[p["name"]] if lo[p["name"]] is not None else -100.0),
                                   float(hi[p["name"]] if hi[p["name"]] is not None else 100.0)]})
        else:
            a = lo[p["name"]] if lo[p["name"]] is not None else DEFAULT_RANGE[0]
            b = hi[p["name"]] if hi[p["name"]] is not None else max(a, DEFAULT_RANGE[1])
            gens.append({"int": [a, b]})
    return gens


def function_cards(ctx, mod: Module, seed: int, samples: int = 24) -> list[dict]:
    """One function card per module function (callees included in its IR module), verified forms generated."""
    from ..engines.frontend_python import _exprs_of, _stmts
    out = []
    rng = random.Random(seed)
    for name, fn in mod.functions.items():
        if name.startswith("alg_") and "__" in name:
            continue
        need, order = [name], []
        while need:
            n = need.pop()
            if n in order:
                continue
            order.append(n)
            for s in _stmts(mod.functions[n]["body"]):
                for e in _exprs_of(s):
                    if e[0] == "CALL" and e[1] not in order:
                        need.append(e[1])
        module = {"entry": name, "functions": [mod.functions[n] for n in order]}
        gens = _bounds(fn)
        interp = Interpreter(module, ctx.ops, step_limit=200_000)
        vectors = []
        for args in V.inputs(gens, samples * 3, rng):
            env = {p["name"]: a for p, a in zip(fn["params"], args)}
            try:
                if not all(L._truth(L.eval_expr(c, env, ctx.ops)) for c in fn.get("requires") or []):
                    continue
                vectors.append({"args": list(args), "out": interp.call(name, list(args))})
            except (IRError, StepLimit, ArithmeticError, ValueError, RecursionError):
                continue
            if len(vectors) >= samples:
                break
        forms, gaps = [], {}
        for lang in ctx.codegen_languages():
            try:
                forms.append({"name": lang, "lang": lang, "entry": name, "cost": 1.0, "runnable": True,
                              "code": emit_module(ctx.store, ctx.ops, lang, module), "generated": True})
            except EmitGap as exc:
                gaps[lang] = str(exc)
        digest = hashlib.sha256(json.dumps(module, sort_keys=True).encode()).hexdigest()[:12]
        sig = ", ".join(f"{p['name']}: {p['type']}" for p in fn["params"])
        out.append({
            "name": f"{mod.name}.{name}", "category": "function", "tier": 2,
            "statement": f"{name}({sig}) -> {fn['returns']} from the card language ({Path(mod.path or 'source').name})",
            "signature": {"params": fn["params"], "returns": fn["returns"]}, "ir": module, "generators": gens,
            "vectors": vectors, "forms": forms, "emit_gaps": gaps, "reference": "ir",
            "depends_on": sorted({f"op/{e[0]}" for f2 in module["functions"] for s in _stmts(f2["body"])
                                  for e in _exprs_of(s) if e[0] not in ("CALL", "var", "int", "float", "bool",
                                                                       "AND", "OR", "IF_EXPR")}),
            "status": "suspect",
            "provenance": {"origin": f"card source {Path(mod.path or 'source').name}", "module": mod.name,
                           "ir_sha256_12": digest, "seed": seed},
        })
    return out


def build_cards(ctx, mod: Module, rep: dict | None = None, seed: int | None = None) -> dict:
    """Every card the module defines (not yet saved): {category: [cards]} plus the fact pack."""
    seed = rep["seed"] if rep else (V.fresh_seed() if seed is None else seed)
    label = Path(mod.path).name if mod.path else "source"
    theory = mod.program.name
    preds = mod.program.predicates()
    idb = mod.program.idb()
    cards: dict[str, list] = {"program": [], "theory": [], "logic_rule": [], "theorem": [], "function": [],
                              "fact": []}
    cards["program"].append({"name": mod.name, "category": "program", "language": "card", "source": label,
                             "source_sha256_12": mod.source_sha, "statement": f"card-language module {mod.name}",
                             "summary": mod.summary(), "uses": mod.uses})
    if preds:
        cards["theory"].append({"name": theory, "category": "theory", "statement": f"logic of module {mod.name}",
                                "source": label, "imports": [],
                                "predicates": {p: {"arity": n, "kind": "idb" if p in idb else "edb"}
                                               for p, n in sorted(preds.items())},
                                **({"stats": rep["logic"]} if rep and rep.get("logic") else {})})
    for r in mod.program.rules:
        cards["logic_rule"].append({"name": f"{theory}.{r.name}", "category": "logic_rule", "theory": theory,
                                    "label": r.name, **L.rule_json(r), "source": f"{label}:{r.line}",
                                    "kind": "constraint" if r.head is None else "rule"})
    for pred, args, source in mod.program.facts:
        h = hashlib.sha256(json.dumps([pred, list(args)], sort_keys=True, default=str).encode()).hexdigest()[:12]
        cards["fact"].append({"name": f"{theory}.{pred}.{h}", "category": "fact", "theory": theory, "pred": pred,
                              "args": list(args), "source": source})
    thms = rep["theorems"] if rep else mod.theorems
    for t in thms:
        cards["theorem"].append({k: v for k, v in t.items()})
    cards["function"] = function_cards(ctx, mod, seed)
    for c in mod.cards:
        cards.setdefault(c["category"], []).append(c)
    return cards


def save_cards(ctx, cards: dict, layer: str) -> dict:
    """Save directory cards with versioning; facts go to one pack per theory (bulk data, rewritten whole)."""
    store = ctx.store
    written = {}
    for cat, items in cards.items():
        if not items:
            continue
        if cat == "fact":
            by_theory: dict[str, list] = {}
            for c in items:
                by_theory.setdefault(c["theory"], []).append(c)
            for th, facts in by_theory.items():
                store.save_pack("fact", th, facts, layer=layer)
            written["fact"] = len(items)
            continue
        store.ensure_registry(cat, layer=layer, description=REG_DESC.get(cat, f"Cards of category {cat} written by "
                                                                                 "the card language."), tier=1)
        n = 0
        for c in items:
            _, changed = store.save(c, layer=layer)
            n += bool(changed)
        written[cat] = n
    return written


REG_DESC = {
    "program": "Card-language modules: source hash, what they declare, what they use.",
    "theory": "Logic theories: which facts and rules belong together, predicates and their arities.",
    "logic_rule": "Logic rules (if body then head) and constraints, one card each, with their source line.",
    "theorem": "Mathematical statements with evidence: refuted, conjecture, witnessed or proved (Lean).",
    "function": "Functions as cards: IR, signature, domain, vectors and generated forms in every language.",
}


def emit(ctx, mod: Module, lang: str, only: list[str] | None = None) -> str:
    return emit_module(ctx.store, ctx.ops, lang, mod.ir_module(), only)


__all__ = ["build_cards", "emit", "function_cards", "report_text", "run", "save_cards"]
