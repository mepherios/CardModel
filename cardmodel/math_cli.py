"""cardmodel math — mathematical notation as a source and a target language (engines/mathlang.py).

  cardmodel math emit SOURCE [--function F] [--latex] [--out FILE]
                                    any liftable function (.py, .card, .math, or a function card) as equations
  cardmodel math lift FILE.math     the card IR of a .math file (JSON)
  cardmodel math run FILE.math      run its tests
  cardmodel math translate FILE.math [--to L1,L2] [--seed N]
                                    lift, emit in every codegen language, compile, run, compare; plus the round
                                    trip through math itself
  cardmodel math roundtrip SOURCE [--seed N]
                                    the math target's witness: lift(emit_math(f)) behaves like f, for every
                                    function of SOURCE (any frontend)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _cli():
    from . import cli
    return cli


def function_cards(ctx, path: Path, seed: int) -> tuple[list[dict], dict]:
    """Function cards from any source the model reads: .py, .card or .math (vectors included)."""
    from .engines import mathlang, translate
    if path.suffix == ".math":
        return mathlang.function_cards(ctx, path, seed)
    if path.suffix == ".card":
        from .lang.compile import CompileError, compile_file
        from .lang.run import function_cards as card_cards
        from .lang.syntax import CardSyntaxError
        try:
            mod = compile_file(str(path), ctx.ops, ctx.store)
        except (CompileError, CardSyntaxError) as exc:
            return [], {path.name: [str(exc)]}
        return card_cards(ctx, mod, seed), {}
    from .engines.frontend_python import lift_source
    lifted = lift_source(path.read_text(encoding="utf-8"), ctx.ops)
    cards, gaps = [], {}
    for lf in lifted:
        if not lf.ok:
            gaps[lf.name] = lf.reasons
            continue
        cards.append(translate.function_card(ctx, lf.name, lifted, path.name, seed=seed))
    return cards, gaps


def _modules(ctx, source: str) -> tuple[list[dict], dict]:
    """IR modules (one per function, callees included) from a file or a function card."""
    card = ctx.store.get(source) if not Path(source).exists() else None
    if card is not None:
        return [card["ir"]], {}
    p = Path(source)
    if p.suffix == ".math":
        from .engines import mathlang
        module = mathlang.lift_file(ctx, p)
        return [{"entry": f["name"], "functions": module["functions"]} for f in module["functions"]], {}
    if p.suffix == ".card":
        from .lang.compile import compile_file
        mod = compile_file(str(p), ctx.ops, ctx.store)
        return [mod.ir_module(n) for n in mod.functions if not (n.startswith("alg_") and "__" in n)], {}
    from .engines.frontend_python import lift_source, module_for
    lifted = lift_source(p.read_text(encoding="utf-8"), ctx.ops)
    return ([module_for(lf.name, lifted) for lf in lifted if lf.ok],
            {lf.name: lf.reasons for lf in lifted if not lf.ok})


def cmd_math(args) -> int:
    from .engines import mathlang
    from .engines import values as V
    from .engines.codegen import EmitGap
    cli = _cli()
    ctx = cli._ctx(args)
    seed = V.fresh_seed() if getattr(args, "seed", None) is None else args.seed
    try:
        if args.action == "emit":
            modules, gaps = _modules(ctx, args.source)
            done, parts = set(), []
            for m in modules:
                if args.function and m["entry"] != args.function:
                    continue
                todo = [f["name"] for f in m["functions"] if f["name"] not in done]
                done.update(todo)
                if not todo:
                    continue
                try:
                    parts.append(mathlang.emit_module(m, latex=args.latex, only=todo).strip())
                except EmitGap as exc:
                    parts.append(f"-- {m['entry']}: {exc}")
            for name, reasons in gaps.items():
                parts.append(f"-- {name}: not lifted: {'; '.join(reasons)}")
            text = "\n\n".join(parts) + "\n"
            if args.out:
                Path(args.out).write_text(text, encoding="utf-8")
                print(f"wrote {args.out}")
            else:
                print(text, end="")
            return 0
        if args.action == "lift":
            module = mathlang.lift_file(ctx, Path(args.source))
            print(json.dumps(module, indent=1, ensure_ascii=False))
            return 0
        if args.action == "run":
            module = mathlang.lift_file(ctx, Path(args.source))
            res = mathlang.run_tests(module, ctx.ops)
            lines = [f"{len(module['functions'])} functions, {sum(r['ok'] for r in res)}/{len(res)} tests pass"]
            lines += [f"  line {r['line']}: {'ok  ' if r['ok'] else 'FAIL'} {r['test']}"
                      + ("" if r["ok"] else f"  ({r.get('error') or r.get('value')})") for r in res]
            cli._out(args, {"functions": [f["name"] for f in module["functions"]], "tests": res}, "\n".join(lines))
            return 0 if all(r["ok"] for r in res) else 1
        if args.action == "translate":
            from .engines import translate
            cards, gaps = mathlang.function_cards(ctx, Path(args.source), seed)
            langs = args.to.split(",") if args.to else None
            results, lines, failed = {}, [f"seed {seed}"], []
            for name, reasons in gaps.items():
                lines.append(f"  {name}: not lifted: {'; '.join(reasons)}")
                failed.append(name)
            for card in cards:
                entry = card["ir"]["entry"]
                rep = translate.verify_function(ctx, card, langs=langs, seed=seed)
                rt = mathlang.round_trip(ctx, card)
                rt.pop("math", None)
                results[entry] = {"report": rep, "round_trip": rt}
                bad = {k: v["status"] for k, v in rep["languages"].items() if v["status"] != "pass"}
                lines.append(f"  {entry:<22} agrees in {len(rep['agreeing_languages'])}: "
                             f"{', '.join(rep['agreeing_languages'])} · math round trip {rt['status']}"
                             + (f"  | other: {', '.join(f'{k}={v}' for k, v in bad.items())}" if bad else ""))
                if any(v in ("fail", "error") for v in bad.values()) or rt["status"] not in ("pass", "no_inputs"):
                    failed.append(entry)
            cli._out(args, {"seed": seed, "functions": results, "not_lifted": gaps}, "\n".join(lines))
            return 1 if failed else 0
        if args.action == "roundtrip":
            p = Path(args.source)
            cards, gaps = function_cards(ctx, p, seed)
            rows, lines = {}, [f"seed {seed} · lift(emit_math(f)) == f, on each function's vectors"]
            for card in cards:
                entry = card["ir"]["entry"]
                rt = mathlang.round_trip(ctx, card)
                rt.pop("math", None)
                rows[entry] = rt
                lines.append(f"  {entry:<24} {rt['status']}" + (f" ({rt['checked']} inputs)" if "checked" in rt else
                                                                f": {rt.get('reason', '')}"))
            ok = sum(1 for r in rows.values() if r["status"] in ("pass", "no_inputs"))
            gap = sum(1 for r in rows.values() if r["status"] == "gap")
            lines.append(f"{ok}/{len(rows) - gap} round trips agree; {gap} functions have no notation (gap); "
                         f"{len(gaps)} functions not lifted by the source frontend")
            cli._out(args, {"seed": seed, "functions": rows, "not_lifted": gaps}, "\n".join(lines))
            return 0 if ok == len(rows) - gap else 1
    except mathlang.MathError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


def register(sub) -> None:
    s = sub.add_parser("math", help="mathematical notation (Unicode or LaTeX) as a source and a target language")
    s.add_argument("action", choices=["emit", "lift", "run", "translate", "roundtrip"])
    s.add_argument("source"); s.add_argument("--function"); s.add_argument("--latex", action="store_true")
    s.add_argument("--out"); s.add_argument("--to"); s.add_argument("--seed", type=int)
    s.set_defaults(fn=cmd_math)
