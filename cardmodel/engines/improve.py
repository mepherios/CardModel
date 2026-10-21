"""improve — make a program faster without changing what it does (pure core, effect shell).

Methodology (docs/METHODOLOGY.md), per top-level function of a Python module:

  1. lift      frontend_python -> IR. A function that does not lift (I/O, sockets, login,
               clocks, classes, globals, ...) belongs to the effect shell and is preserved
               byte for byte; so is every other top-level statement (CM21).
  2. domain    the function's domain is inferred and the ORIGINAL Python is the reference.
  3. candidates
       algorithm   behavioural match against cards/algorithm: same signature, same outputs on
                   probe inputs (and at least 3 distinct outputs, so a constant function
                   matches nothing). Every non-suboptimal form of a matched card is a candidate,
                   guarded by the card's precondition; the original code still runs for every
                   input outside it.
       rewrite     search.optimize over every int-typed expression with the rule cards;
                   the function is re-emitted from IR.
  4. verify    each candidate against the original on seeded inputs (plus edges); any
               mismatch rejects it.
  5. measure   the original and every verified candidate, in-process, on the same inputs
               (budgeted); the fastest wins only if it beats the original by more than NOISE
               (hub L4); otherwise the function is kept.
  6. emit      only the chosen functions are replaced in the module text (surgical, hub L3);
               the result is re-verified end to end (fresh seed); native translations of the
               chosen versions are emitted for every language card with codegen.

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
from .ir import Interpreter, StepLimit, walk_stmts
from .search import expr_cost, load_rules, op_costs, optimize
from .translate import infer_domain
from .witness import TimeLimit, time_limit

NOISE = 0.10
MIN_MATCH = 8
MIN_DISTINCT = 3
CALL_BUDGET_S = 0.25
STEP_BUDGET = 400_000


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
    """The module with every top-level statement except imports and function definitions removed:
    safe to execute (module-level code never runs here)."""
    tree = ast.parse(source)
    keep = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.Import, ast.ImportFrom))]
    return ast.unparse(ast.Module(body=keep, type_ignores=[]))


def _load(source: str) -> dict:
    ns: dict = {"__name__": "cardmodel_improve", "math": math}
    exec(compile(_functions_only(source), "<improve>", "exec"), ns)  # noqa: S102 -- the user's own functions
    return ns


# -- verification and timing --------------------------------------------------------------------
def _agree(ref, cand, inputs) -> tuple[int, dict | None]:
    checks = 0
    for args in inputs:
        try:
            want = ref(*args)
        except Exception:  # noqa: BLE001 -- outside the original's domain: not compared
            continue
        try:
            got = cand(*args)
        except Exception as exc:  # noqa: BLE001 -- a candidate that raises where the original does not fails
            return checks, {"args": list(args), "expected": want, "got": f"raised {type(exc).__name__}"}
        checks += 1
        if not V.same(want, got):
            return checks, {"args": list(args), "expected": want, "got": got}
    return checks, None


def _time(fn, inputs, budget_s: float = 1.0) -> float:
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


def _cheap_inputs(fn, inputs, per_call_s: float = CALL_BUDGET_S) -> list:
    """Inputs on which ``fn`` finishes quickly (the slow original sets the measurement set)."""
    out = []
    for a in inputs:
        t0 = time.perf_counter()
        try:
            with time_limit(max(per_call_s * 4, 1.0)):
                fn(*a)
        except TimeLimit:
            continue
        except Exception:  # noqa: BLE001 -- not part of the comparable domain
            continue
        if time.perf_counter() - t0 <= per_call_s:
            out.append(a)
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
        agree, outs = 0, set()
        mismatch = False
        for args in inputs:
            try:
                if filt is not None and not filt(*args):
                    continue
                want = ref(*args)
            except Exception:  # noqa: BLE001
                continue
            try:
                with time_limit(2):
                    got = card_fn(*args)
            except Exception:  # noqa: BLE001
                mismatch = True
                break
            if not V.same(want, got):
                mismatch = True
                break
            agree += 1
            outs.add(repr(want))
        if mismatch or agree < MIN_MATCH or len(outs) < MIN_DISTINCT:
            continue
        cparams = [p["name"] for p in sig["params"]]
        pre = card.get("precondition")
        for form in card["forms"]:
            if form.get("role") == "suboptimal":
                continue
            fast_name = f"{fn_ir['name']}__{card.name}_{form['name']}"
            fast_src = rename(form["code"], {form["entry"]: fast_name, **dict(zip(cparams, params))})
            out.append({"kind": "algorithm", "card": card.qualified, "form": form["name"],
                        "complexity": form.get("complexity"), "fast_name": fast_name, "fast_src": fast_src,
                        "precondition": rename(pre, dict(zip(cparams, params))) if pre else None,
                        "needs_math": "math." in form["code"]})
    return out


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


def rewrite_candidate(ctx: Ctx, fn_ir: dict, rules, costs) -> tuple[dict | None, list]:
    """The function with every int-typed expression replaced by its cheapest equivalent under the rule cards."""
    import copy
    fn = copy.deepcopy(fn_ir)
    types = {p["name"]: p["type"] for p in fn["params"]}
    types.update(fn.get("locals") or {})
    changes = []

    def visit(e):
        if not isinstance(e, list) or not e or e[0] in ("var", "int", "float", "bool"):
            return e
        if _int_typed(e, types) and 3 <= len(repr(e)) and e[0] not in ("CALL",):
            res = optimize(e, rules, costs, max_depth=3, max_nodes=300)
            if res["best_cost"] < expr_cost(e, costs):
                changes.append((res["input"], res["best"], [s for s, _ in res["steps"][1:]]))
                return res["best_tree"]
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
                   native: bool = True) -> dict:
    seed = V.fresh_seed() if seed is None else seed
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)
    lifted = lift_source(source, ctx.ops)
    by_name = {lf.name: lf for lf in lifted}
    rules = load_rules(ctx.store)
    costs = op_costs(ctx.store)
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
        raw_inputs = [tuple(a) for a in V.inputs(gens, samples, rng)]
        interp = Interpreter(module, ctx.ops, step_limit=STEP_BUDGET)
        inputs = []
        for a in raw_inputs:
            try:
                interp.call(node.name, list(a))
                inputs.append(a)
            except StepLimit:
                continue
            except Exception:  # noqa: BLE001 -- outside the domain
                continue
        inputs = _cheap_inputs(ref, inputs)
        entry["generators"] = gens
        entry["inputs"] = len(inputs)
        if len(inputs) < 4:
            entry.update(action="kept", reason="too few quick in-domain inputs to compare")
            continue
        fn_ir = next(f for f in module["functions"] if f["name"] == node.name)
        orig_src = "".join(lines[node.lineno - 1 - len(node.decorator_list): node.end_lineno])
        cands = []
        for c in algorithm_candidates(ctx, fn_ir, ref, inputs):
            params = ", ".join(f"{p['name']}: {p['type']}" for p in fn_ir["params"])
            call = ", ".join(p["name"] for p in fn_ir["params"])
            if c["precondition"]:
                orig_name = f"{node.name}__original"
                orig_body = rename(orig_src, {}).replace(f"def {node.name}(", f"def {orig_name}(", 1)
                src = (f"def {node.name}({params}) -> {fn_ir['returns']}:\n"
                       f"    if {c['precondition']}:\n        return {c['fast_name']}({call})\n"
                       f"    return {orig_name}({call})\n\n\n{c['fast_src']}\n\n\n{orig_body}\n")
            else:
                src = (f"def {node.name}({params}) -> {fn_ir['returns']}:\n"
                       f"    return {c['fast_name']}({call})\n\n\n{c['fast_src']}\n")
            cands.append({**c, "src": src})
        rw_ir, changes = rewrite_candidate(ctx, fn_ir, rules, costs)
        if rw_ir is not None:
            try:
                rw_src = emit_module(ctx.store, ctx.ops, "python", {"entry": node.name, "functions": [rw_ir]})
                cands.append({"kind": "rewrite", "card": "rewrite_rule/*", "form": "rules", "src": rw_src,
                              "changes": changes, "needs_math": "math." in rw_src})
            except EmitGap as exc:
                entry["rewrite_gap"] = str(exc)
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
        t_orig = _time(ref, inputs)
        best, best_t = None, t_orig
        for c in verified:
            c["seconds"] = _time(c["fn"], inputs)
            if c["seconds"] < best_t:
                best, best_t = c, c["seconds"]
        entry["candidates"] = [{k: v for k, v in c.items() if k in ("kind", "card", "form", "complexity", "checks",
                                                                    "seconds", "rejected", "changes")}
                               for c in cands]
        entry["original_seconds"] = t_orig
        if best is not None and t_orig / best_t > 1 + NOISE:
            entry.update(action=f"{best['kind']}:{best['card']}#{best['form']}", speedup=round(t_orig / best_t, 2),
                         checks=best["checks"], new_source=best["src"])
            replacements[node.name] = best["src"]
            needs_math = needs_math or best.get("needs_math", False)
        else:
            entry.update(action="kept", reason="no verified candidate faster than the original beyond noise"
                         if verified else "no verified candidate")

    optimized = _splice(source, tree, replacements, needs_math)
    report["optimized_source"] = optimized
    report["changed"] = sorted(replacements)
    report["effect_shell_identical"] = shell_identical(source, optimized, set(replacements))
    report["end_to_end"] = end_to_end(ctx, source, optimized, sorted(replacements), seed)
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
        inputs = _cheap_inputs(orig[name], [tuple(a) for a in V.inputs(gens, 24, random.Random(seed + 1))])
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
            module["functions"] = [f for f in module["functions"] if f["name"] not in seen]
            if not module["functions"]:
                continue
            try:
                texts.append(Emitter(ctx.store, lang, ctx.ops).module_source(module))
                seen.update(f["name"] for f in module["functions"])
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
    slim = {k: v for k, v in report.items() if k not in ("optimized_source", "native")}
    slim["native_gaps"] = {lang: nat["gaps"] for lang, nat in (report.get("native") or {}).items()}
    (out_dir / f"{stem}.improve.json").write_text(json.dumps(slim, indent=1, default=str, sort_keys=True) + "\n",
                                                  encoding="utf-8")
    (out_dir / f"{stem}.improve.md").write_text(markdown(report), encoding="utf-8")
    written += [out_dir / f"{stem}.improve.json", out_dir / f"{stem}.improve.md"]
    return written


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]
