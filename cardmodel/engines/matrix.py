"""matrix — every source language x every target language, verified by running (ROADMAP Phase D2, D3).

For each corpus file the frontend registered for its extension lifts every function to the card IR; then:

  1. pair cells (D2): each lifted function is emitted in every codegen target, compiled, run on the source's
     vectors plus fresh seeded inputs and compared with the source's reference (translate.verify_function).
     A cell (source, target) counts functions passed / functions checked;
  2. cross-source agreement: when one function is written in several source languages (the shared corpus is
     written once in the card language and hand-ported), the lifted IRs of every pair of ports must agree on
     the union of their vectors, so "Python's legendre" and "the card language's legendre" are one function;
  3. round trip (D3): for every target that also has a frontend, and for mathematical notation (engines/mathlang.py,
     a target without a compiler), lift(emit_T(f)) must behave like f on f's
     vectors (sampled, seed printed; the IR has loops, so the check is behavioural, not a semantic hash).

New frontends join with ``register(Frontend(...))``: the matrix grows a row (and, for targets with a frontend, a
round-trip column) with no other change.

Honest limits (L1): equivalence is sampled; a target whose toolchain is missing is "unavailable", never
counted as passed; only functions a frontend lifts enter the matrix (the rest are listed with their reasons).
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import godel as G
from . import translate
from . import values as V
from .codegen import EmitGap, emit_module, predicted_gap
from .context import Ctx
from .ir import Interpreter, IRError, StepLimit

STEP_BUDGET = translate.STEP_BUDGET


@dataclass
class Frontend:
    """A source language: function cards from a file, and (optionally) IR modules from source text."""
    lang: str
    exts: tuple[str, ...]
    cards: Callable[[Ctx, Path, int], tuple[list[dict], dict[str, list[str]]]]
    lift_text: Callable[[Ctx, str], dict[str, dict]] | None = None


FRONTENDS: dict[str, Frontend] = {}


def register(fe: Frontend) -> None:
    FRONTENDS[fe.lang] = fe


def frontend_for(path: Path) -> Frontend | None:
    return next((fe for fe in FRONTENDS.values() if path.suffix in fe.exts), None)


# ---- the frontends on main -------------------------------------------------------------------------------------

def _python_cards(ctx: Ctx, path: Path, seed: int):
    from .frontend_python import lift_source
    lifted = lift_source(path.read_text(encoding="utf-8"), ctx.ops)
    cards, gaps = [], {}
    for lf in lifted:
        if not lf.ok:
            gaps[lf.name] = lf.reasons
            continue
        cards.append(translate.function_card(ctx, lf.name, lifted, path.name, seed=seed))
    return cards, gaps


def _python_lift_text(ctx: Ctx, text: str) -> dict[str, dict]:
    from .frontend_python import lift_source, module_for
    lifted = lift_source(text, ctx.ops)
    return {lf.name: module_for(lf.name, lifted) for lf in lifted if lf.ok}


def _card_cards(ctx: Ctx, path: Path, seed: int):
    from ..lang.compile import CompileError, compile_file
    from ..lang.run import function_cards
    from ..lang.syntax import CardSyntaxError
    try:
        mod = compile_file(str(path), ctx.ops, ctx.store)
    except (CompileError, CardSyntaxError) as exc:
        return [], {path.name: [str(exc)]}
    return function_cards(ctx, mod, seed), {}


register(Frontend("python", (".py",), _python_cards, _python_lift_text))
register(Frontend("cardlang", (".card",), _card_cards))


def _math_cards(ctx: Ctx, path: Path, seed: int):
    from . import mathlang
    return mathlang.function_cards(ctx, path, seed)


def _math_lift_text(ctx: Ctx, text: str) -> dict[str, dict]:
    from . import mathlang
    module = mathlang.lift_text(text, ctx.ops)
    return {f["name"]: {"entry": f["name"], "functions": module["functions"]} for f in module["functions"]}


register(Frontend("math", (".math",), _math_cards, _math_lift_text))


def _register_text_frontends() -> None:
    import sys
    from . import frontends
    frontends.register_matrix(sys.modules[__name__])


_register_text_frontends()


# ---- checks ----------------------------------------------------------------------------------------------------

def _entry(card: dict) -> str:
    return card["ir"]["entry"]


def _run_ir(ctx: Ctx, module: dict, args: list):
    try:
        return True, Interpreter(module, ctx.ops, step_limit=STEP_BUDGET).call(module["entry"], list(args))
    except (StepLimit, RecursionError, IRError, ArithmeticError, ValueError, OverflowError):
        return False, None


def _compare(ctx: Ctx, a: dict, b: dict, inputs: list) -> dict:
    """Run two IR modules on the same inputs; inputs either side cannot evaluate are skipped, not counted."""
    checked = 0
    for args in inputs:
        ok_a, out_a = _run_ir(ctx, a, args)
        ok_b, out_b = _run_ir(ctx, b, args)
        if not (ok_a and ok_b):
            continue
        checked += 1
        if not V.same(out_a, out_b):
            return {"status": "fail", "checked": checked, "args": list(args), "out_a": out_a, "out_b": out_b}
    return {"status": "pass" if checked else "no_inputs", "checked": checked}


def cross_source(ctx: Ctx, ports: dict[str, dict[str, dict[str, dict]]], seed: int) -> list[dict]:
    """Ports of one function in two source languages must agree (on both sides' vectors plus fresh inputs).

    ``ports``: {group: {source language: {function: card}}}. A group is one folder and file stem
    (examples/matrix/corpus.card, corpus.py, corpus.math), so only files written as ports of each other are
    compared; an unrelated function that happens to share a name in another corpus is not."""
    out = []
    for group, by_source in sorted(ports.items()):
        names = sorted({n for cards in by_source.values() for n in cards})
        srcs = sorted(by_source)
        for name in names:
            have = [s for s in srcs if name in by_source[s]]
            for i, a in enumerate(have):
                for b in have[i + 1:]:
                    ca, cb = by_source[a][name], by_source[b][name]
                    rng = random.Random(seed)
                    gens = cb.get("generators") or ca.get("generators") or []
                    inputs = ([v["args"] for v in ca.get("vectors", [])] + [v["args"] for v in cb.get("vectors", [])]
                              + [list(x) for x in V.inputs(gens, 16, rng, edge=False)])
                    out.append({"group": group, "function": name, "a": a, "b": b,
                                **_compare(ctx, ca["ir"], cb["ir"], inputs)})
    return out


def round_trip(ctx: Ctx, card: dict, target: str) -> dict:
    """lift_target(emit_target(f)) behaves like f on f's vectors."""
    fe = FRONTENDS.get(target)
    if fe is None or fe.lift_text is None:
        return {"status": "no_frontend"}
    missing = predicted_gap(G.module_content(card["ir"], ctx.ops), ctx.language_gap(target)) \
        if translate.PREDICT_GAPS else []
    if missing:
        return {"status": "gap", "reason": f"{target}: no template for {', '.join(missing)} (predicted from the content)"}
    try:
        code = emit_module(ctx.store, ctx.ops, target, card["ir"])
    except EmitGap as exc:
        return {"status": "gap", "reason": str(exc)}
    back = fe.lift_text(ctx, code).get(_entry(card))
    if back is None:
        return {"status": "not_lifted", "reason": f"the {target} frontend does not lift the emitted {_entry(card)}"}
    return _compare(ctx, card["ir"], back, [v["args"] for v in card.get("vectors", [])])


def math_round_trip(ctx: Ctx, card: dict) -> dict:
    """lift_math(emit_math(f)) behaves like f on f's vectors (math is a target with no compiler: its witness)."""
    from . import mathlang
    r = mathlang.round_trip(ctx, card)
    r.pop("math", None)
    return r


# ---- the matrix ------------------------------------------------------------------------------------------------

def default_corpus(root: Path) -> list[Path]:
    files = []
    for d in ("examples/matrix", "examples/algorithms", "tests/frontends"):   # tests/frontends: all 15 text languages
        p = root / d
        if p.is_dir():
            files += sorted(f for f in p.iterdir() if frontend_for(f) is not None)
    return files


def run(ctx: Ctx, files: list[Path], targets: list[str] | None = None, seed: int | None = None,
        progress: Callable[[str], None] | None = None) -> dict:
    seed = V.fresh_seed() if seed is None else seed
    targets = targets or ctx.codegen_languages()
    avail = {t: ctx.available(t) for t in targets}
    functions, not_lifted = [], []
    by_source: dict[str, dict[str, dict]] = {}
    ports: dict[str, dict[str, dict[str, dict]]] = {}
    for path in files:
        fe = frontend_for(path)
        if fe is None:
            not_lifted.append({"file": str(path), "function": None, "reasons": ["no frontend for this extension"]})
            continue
        cards, gaps = fe.cards(ctx, path, seed)
        not_lifted += [{"file": str(path), "source": fe.lang, "function": n, "reasons": r} for n, r in gaps.items()]
        for card in cards:
            name = _entry(card)
            if progress:
                progress(f"{fe.lang}:{name}")
            rep = translate.verify_function(ctx, card, langs=[t for t in targets if avail[t][0]], seed=seed)
            cells = {t: (rep["languages"].get(t) or {"status": "unavailable", "reason": avail[t][1]})
                     for t in targets}
            for t, gap in (card.get("emit_gaps") or {}).items():
                if t in cells and cells[t]["status"] == "unavailable":
                    cells[t] = {"status": "gap", "reason": gap}
            rt = {t: round_trip(ctx, card, t) for t in targets if t in FRONTENDS and FRONTENDS[t].lift_text}
            rt["math"] = math_round_trip(ctx, card)      # mathematical notation as a target (engines/mathlang.py)
            functions.append({"file": str(path), "source": fe.lang, "function": name, "inputs": rep["inputs"],
                              "lift_mismatches": rep["lift_mismatches"], "targets": cells, "round_trip": rt,
                              "source_witness": (card.get("verification") or {}).get("source_witness")})
            by_source.setdefault(fe.lang, {})[name] = card
            ports.setdefault(str(path.with_suffix("")), {}).setdefault(fe.lang, {})[name] = card
    cross = cross_source(ctx, ports, seed)
    fails = failures(functions, cross)
    explain_failures(ctx, fails, by_source)
    return {"seed": seed, "targets": targets,
            "unavailable": {t: why for t, (ok, why) in avail.items() if not ok},
            "sources": sorted(by_source), "functions": functions, "not_lifted": not_lifted,
            "cross_source": cross, "pairs": pair_table(functions, targets), "failures": fails}


def explain_failures(ctx: Ctx, fails: list[dict], by_source: dict[str, dict[str, dict]]) -> None:
    """Name the divergence law (engines/analyse.py) that fires at a failing pair's first input, when one does:
    a wrong answer from a target is then explained in math (overflow at a + b, a float exception …), not just shown."""
    from .analyse import explain
    for f in fails:
        args = (f.get("detail") or {}).get("args") if isinstance(f.get("detail"), dict) else None
        card = by_source.get(f.get("source"), {}).get(f["function"])
        if args is None or card is None:
            continue
        try:
            why = explain(ctx, card["ir"], list(args))
        except Exception:        # noqa: BLE001 -- an explanation is extra; the failure stands without one
            continue
        if why:
            f["explanation"] = [f"{w['law']} at {w['term']}" for w in why]


def pair_table(functions: list[dict], targets: list[str]) -> dict:
    """{source: {target: {"pass": n, "checked": n, "fail": n, "gap": n, "unavailable": n}}}"""
    table: dict[str, dict[str, dict]] = {}
    for f in functions:
        row = table.setdefault(f["source"], {t: {"pass": 0, "fail": 0, "gap": 0, "unavailable": 0, "other": 0}
                                             for t in targets})
        for t, c in f["targets"].items():
            st = c["status"]
            key = st if st in ("pass", "gap", "unavailable") else ("fail" if st in ("fail", "error") else "other")
            row[t][key] += 1
    return table


def failures(functions: list[dict], cross: list[dict]) -> list[dict]:
    out = []
    for f in functions:
        if not f["inputs"]:
            out.append({"kind": "unverified", "source": f["source"], "function": f["function"],
                        "detail": "no input where the source reference and the lifted IR both evaluate"})
        if f["lift_mismatches"]:
            out.append({"kind": "lift", "source": f["source"], "function": f["function"],
                        "detail": f"{f['lift_mismatches']} inputs where the lifted IR and the source differ"})
        sw = f.get("source_witness") or {}
        if sw.get("status") in ("fail", "error"):        # the original, run by its own toolchain, disagrees with the lift
            out.append({"kind": "source_witness", "source": f["source"], "function": f["function"], "detail": sw})
        for t, c in f["targets"].items():
            if c["status"] in ("fail", "error"):
                out.append({"kind": "pair", "source": f["source"], "target": t, "function": f["function"],
                            "detail": c})
        for t, c in f["round_trip"].items():
            # a gap (target cannot emit it) or not_lifted (the target's frontend cannot read the emitted code back,
            # e.g. a helper it has no construct for) is a translation gap, counted in the report, not a failure
            if c["status"] not in ("pass", "no_inputs", "gap", "not_lifted"):
                out.append({"kind": "round_trip", "source": f["source"], "target": t, "function": f["function"],
                            "detail": c})
    out += [{"kind": "cross_source", "function": c["function"], "source": c["a"], "target": c["b"], "detail": c}
            for c in cross if c["status"] == "fail"]
    return out


def translation_gaps(rep: dict) -> dict[str, dict[str, int]]:
    """D4: every construct a target cannot emit, counted over the corpus: {target: {reason: functions}}."""
    out: dict[str, dict[str, int]] = {}
    for f in rep["functions"]:
        for t, c in f["targets"].items():
            if c["status"] == "gap":
                why = c.get("reason", "?").split(": ", 1)[-1]
                out.setdefault(t, {}).setdefault(why, 0)
                out[t][why] += 1
    return {t: dict(sorted(rs.items(), key=lambda kv: -kv[1])) for t, rs in sorted(out.items())}


def report_text(rep: dict) -> str:
    t = rep["targets"]
    w = max(8, *(len(s) for s in rep["sources"])) if rep["sources"] else 8
    lines = [f"seed {rep['seed']} · sources {', '.join(rep['sources']) or '-'} · {len(rep['functions'])} functions",
             "", f"{'source':<{w}}  " + "  ".join(f"{x[:10]:>10}" for x in t)]
    for src, row in sorted(rep["pairs"].items()):
        cells = []
        for x in t:
            c = row[x]
            n = c["pass"] + c["fail"] + c["other"]
            cells.append("—" if not n else f"{c['pass']}/{n}" + ("!" if c["fail"] else ""))
        lines.append(f"{src:<{w}}  " + "  ".join(f"{c:>10}" for c in cells))
    if rep["unavailable"]:
        lines.append("")
        lines.append("unavailable: " + "; ".join(f"{k} ({v})" for k, v in sorted(rep["unavailable"].items())))
    rts = [(f["source"], t, c["status"]) for f in rep["functions"] for t, c in f["round_trip"].items()]
    if rts:
        ok = sum(1 for *_, s in rts if s in ("pass", "no_inputs"))
        nl = sum(1 for *_, s in rts if s in ("gap", "not_lifted"))
        lines.append(f"round trip lift(emit_T(f)) == f: {ok}/{len(rts)}" + (f" ({nl} gaps: not emitted or not read back)"
                                                                         if nl else ""))
    sws = [f["source_witness"]["status"] for f in rep["functions"] if f.get("source_witness")]
    if sws:
        lines.append(f"source witness (the original, run by its own toolchain, == the lift): "
                     f"{sws.count('pass')}/{len(sws)} pass, {len(sws) - sws.count('pass')} not runnable here or failing")
    cr = rep["cross_source"]
    if cr:
        ok = sum(1 for c in cr if c["status"] == "pass")
        lines.append(f"cross-source ports agree: {ok}/{len(cr)}")
    if rep["not_lifted"]:
        lines.append(f"not lifted ({len(rep['not_lifted'])}): " + "; ".join(
            f"{x.get('source', '?')}:{x['function']} ({x['reasons'][0] if x['reasons'] else '?'})"
            for x in rep["not_lifted"][:8]))
    gaps = translation_gaps(rep)
    if gaps:
        lines.append("translation gaps (constructs a target cannot carry yet): " + "; ".join(
            f"{t}: {', '.join(f'{r} ×{n}' for r, n in rs.items())}" for t, rs in gaps.items()))
    if rep["failures"]:
        lines.append(f"FAILURES ({len(rep['failures'])}):")
        for f in rep["failures"][:20]:
            lines.append(f"  {f['kind']:<12} {f.get('source', '')}->{f.get('target', '')} {f['function']}: "
                         f"{str(f['detail'])[:200]}")
            if f.get("explanation"):
                lines.append(f"  {'':<12} explained by: {'; '.join(f['explanation'])} (cardmodel analyse)")
    else:
        lines.append("no failures")
    return "\n".join(lines)


def markdown(rep: dict) -> str:
    t = rep["targets"]
    out = ["# Language pair matrix (generated by `cardmodel matrix --write`; do not edit)", "",
           f"Seed {rep['seed']}. Each cell is functions passed / functions run for (source row, target column); "
           "every pass compiled, ran and matched the source on its vectors plus fresh seeded inputs. "
           "`—` means the target's toolchain was not on this machine.", "",
           "| source \\ target | " + " | ".join(t) + " |", "|---|" + "---:|" * len(t)]
    for src, row in sorted(rep["pairs"].items()):
        cells = []
        for x in t:
            c = row[x]
            n = c["pass"] + c["fail"] + c["other"]
            cells.append("—" if not n else f"{c['pass']}/{n}")
        out.append(f"| {src} | " + " | ".join(cells) + " |")
    rts = [s for f in rep["functions"] for s in (c["status"] for c in f["round_trip"].values())]
    cr = rep["cross_source"]
    out += ["", f"* Round trip lift(emit_T(f)) behaves like f: {sum(s in ('pass', 'no_inputs') for s in rts)}"
                f"/{len(rts)} (targets that also have a frontend).",
            f"* Ports of one function in different source languages agree: "
            f"{sum(c['status'] == 'pass' for c in cr)}/{len(cr)}.",
            f"* Functions a frontend does not lift (gaps, not failures): {len(rep['not_lifted'])}."]
    if rep["not_lifted"]:
        out += [f"  * {x.get('source', '?')} `{x['function']}`: {'; '.join(x['reasons'])}" for x in rep["not_lifted"]]
    if rep["unavailable"]:
        out.append("* Unavailable here: " + "; ".join(f"{k} ({v})" for k, v in sorted(rep["unavailable"].items())))
    gaps = translation_gaps(rep)
    if gaps:
        out.append("* Translation gaps (constructs a target cannot emit yet; the function is not run there):")
        out += [f"  * {t}: " + "; ".join(f"{r} (×{n})" for r, n in rs.items()) for t, rs in gaps.items()]
    out.append(f"* Failures: {len(rep['failures'])}.")
    out += [f"  * {f['kind']} {f.get('source', '')} → {f.get('target', '')} `{f['function']}`" for f in rep["failures"]]
    return "\n".join(out) + "\n"


__all__ = ["FRONTENDS", "Frontend", "cross_source", "default_corpus", "markdown", "register", "report_text",
           "round_trip", "run", "translation_gaps"]
