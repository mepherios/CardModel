"""cardmodel — the card model as one program. Run it from any project folder.

  cardmodel init [PATH]                 make PATH a project (.cardmodel/ with its own cards)
  cardmodel status                      registries, languages on this host, goals
  cardmodel observe PATH [--save]       express a source tree as cards (named vs fallback, liftable functions)
  cardmodel verify [--seed N] [--quick] run every witness; prints the seed; --record writes verdicts into cards
  cardmodel cover [--write FILE]        computed coverage (forms, conformance matrix, witnesses, goals)
  cardmodel rewrite CARD | --all | --prove L R | --optimize EXPR | --rank REG --weights k=v,...
  cardmodel emit --lang L FILE.py       translate liftable functions (or --rules for Lean theorems, --hints CARD)
  cardmodel learn [PATH] [--promote]    observe -> propose -> verify -> promote (cards with evidence)
  cardmodel optimize [--card Q] [--apply]  measure real costs -> metric cards -> cost anchors
  cardmodel translate FILE.py [--to ...]   lift + emit + verify every function, report per language
  cardmodel improve PATH [--out DIR]       make a module/package faster: verified algorithm substitutions and
                                           rewrites; effectful code byte-identical; native forms for every language
  cardmodel arena [--count N] [--seed S]   generate a suboptimal program, improve it, score soundness/recall/speed
  cardmodel show CARD | list [REGISTRY] | probe | new REGISTRY NAME | docs [--check] | clean

  the card language, logic and proofs (cli_ext.py):
  cardmodel run FILE.card [--lean]       run a program: tests, queries, theorems (witnessed, Lean-proved)
  cardmodel lang check|build|emit FILE   check it, turn it into cards (--save), or emit it (--lang rust)
  cardmodel logic query|why|mine|self    ask a theory, explain a fact (--lean: kernel-checked), decipher rules
  cardmodel laws [--save]                discover the laws the op cards obey; prove them; promote to rules
  cardmodel lean import F.lean | --core  Lean theorems as cards: faithful reading, witness, re-proof
  cardmodel repl                         interactive card language
  cardmodel algebra form|gcd|total|scan|godel   functions as algebra: canonical forms, GCD of functions, totals
  cardmodel game check|matrix|sensitivity|balance|duel|tournament|play|world|kernel   the combat design (game/)

Global: --json (machine output), --project PATH, --no-project, --cards PATH (extra read-only card tree).
Exit status: 0 ok, 1 a check failed, 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .kernel import paths
from .kernel.store import open_store


def _out(args, data, text: str | None = None) -> None:
    if args.json:
        print(json.dumps(data, indent=1, sort_keys=True, default=str))
    else:
        print(text if text is not None else json.dumps(data, indent=1, default=str))


def _ctx(args):
    from .engines.context import Ctx
    extra = args.cards or []
    if args.no_project:
        store = open_store(project=False, extra=extra)
    elif args.project:
        store = open_store(project=args.project, extra=extra)
    else:
        store = open_store(project=True, extra=extra)
    return Ctx(store)


def _layer(ctx, args) -> str:
    if getattr(args, "global_", False):
        return "model"
    return ctx.store.writable_layer()


# -- commands ---------------------------------------------------------------------------
def cmd_init(args) -> int:
    root = Path(args.path or os.getcwd()).resolve()
    d = root / paths.PROJECT_DIR
    (d / "cards").mkdir(parents=True, exist_ok=True)
    cfg = d / "config.json"
    if not cfg.exists():
        cfg.write_text(json.dumps({"name": root.name, "created": datetime.now(timezone.utc).date().isoformat(),
                                   "cardmodel": "0.1.0"}, indent=2) + "\n", encoding="utf-8")
    (d / ".gitignore").write_text("state/\n", encoding="utf-8")
    (d / "README.md").write_text(
        "# .cardmodel\n\nThis project's cards (observations, learned call cards, function cards, metrics, "
        "proposals). The model's built-in cards live in the cardmodel repository; project cards override them "
        "by name. `state/` is a rebuildable cache.\n", encoding="utf-8")
    _out(args, {"project": str(d)}, f"initialised {d}")
    return 0


def cmd_status(args) -> int:
    from .engines import coverage
    ctx = _ctx(args)
    rep = coverage.compute(ctx)
    data = {"home": str(paths.home()), "layers": [(n, str(p)) for n, p in ctx.store.layers],
            "cards": rep["total_cards"], "registries": len(rep["registries"]),
            "languages": {k: v["available"] for k, v in rep["languages"].items() if v["codegen"]},
            "goals": rep["goals"], "last_verify": rep.get("verify_started")}
    lines = [f"cardmodel home   {data['home']}",
             "layers           " + "  ".join(f"{n}={p}" for n, p in data["layers"]),
             f"cards            {data['cards']} in {data['registries']} registries",
             "codegen targets  " + " ".join(f"{k}{'' if v else '(missing)'}" for k, v in data["languages"].items()),
             f"last verify      {data['last_verify'] or 'never (run cardmodel verify)'}", "", "goals:"]
    for g in rep["goals"]:
        mark = "·" if g["met"] is None else ("✓" if g["met"] else "✗")
        val = "not run yet" if g["value"] is None else g["value"]
        lines.append(f"  {mark} {g['goal']:<28} {val} ({g['direction']} {g['target']})")
    _out(args, data, "\n".join(lines))
    return 0


def cmd_observe(args) -> int:
    from .engines.observe import observe
    ctx = _ctx(args)
    try:
        obs = observe(ctx, args.path)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.save:
        if ctx.store.get(f"observation/{obs['name']}") is None:
            ctx.store.save(obs, category="observation")
    t = obs["totals"]
    lines = [f"observed {t['files']} files {t['by_language']}",
             f"cards fired {t['cards_fired']}, named {t['named']} ({t['named_fraction']:.1%}), "
             f"functions {t['functions']} (liftable to IR: {t['functions_liftable']})",
             "top cards: " + ", ".join(f"{k}×{v}" for k, v in list(obs["top_cards"].items())[:10]),
             "top fallback calls: " + ", ".join(f"{k}×{v}" for k, v in list(obs["top_fallback_calls"].items())[:10])]
    if args.save:
        lines.append(f"saved observation/{obs['name']}")
    _out(args, obs, "\n".join(lines))
    return 0


def cmd_verify(args) -> int:
    from .engines import verify
    ctx = _ctx(args)
    only = args.only.split(",") if args.only else None
    if args.quick and not only:
        only = list(verify.QUICK)
    langs = args.langs.split(",") if args.langs else None
    rep = verify.run(ctx, seed=args.seed, only=only, langs=langs, samples=args.samples, record=args.record)
    lines = [f"seed {rep['seed']} (reproduce with --seed {rep['seed']})"]
    for sec, r in rep["sections"].items():
        extra = r.get("counts") or r.get("rate") or r.get("summary") or ""
        if sec == "kernel":
            extra = (f"{r['cards']} cards, {r['schema_error_cards']} schema errors, {len(r['load_errors'])} load "
                     f"errors, {len(r['unresolved_references'])} unresolved refs, {len(r['registry_errors'])} registry errors")
        if sec == "portability":
            extra = ", ".join(f"{x['version']} {x['status']}" for x in r.get("runs", []))
        if sec == "selfcheck":
            sb = r.get("sandbox") or {}
            extra = (f"static problems {len(r['static_problems'])}; sandbox "
                     f"{'ok' if sb.get('ok') else sb.get('reason') or 'FAILED'} with {len(r['denied'])} source folders denied")
        if sec == "proofs":
            extra = (f"{r.get('proved')} of {r.get('total')} rules proved ({r.get('backend')})" if r.get("total")
                     else r.get("reason", ""))
        if sec == "logic":
            extra = (f"{(r.get('stats') or {}).get('given')} facts about the store, {r.get('rules')} rules, "
                     f"{r.get('violation_count')} violations")
        if sec == "lang":
            extra = f"programs {r.get('counts')}"
        if sec == "theorems":
            extra = f"{r.get('cards')} theorem cards {r.get('counts')}; {len(r.get('problems') or {})} problems"
        if sec == "game" and r.get("laws_total"):
            extra = (f"{r['laws_passed']}/{r['laws_total']} design laws, equilibrium value {r['equilibrium']['value']} "
                     f"over {len(r['equilibrium']['row_mix'])} options (certificate "
                     f"{'ok' if r['equilibrium']['certificate'] else 'FAILED'})")
        if sec == "forms" and r.get("hub_claims"):
            extra = f"{r['counts']} · hub's original domain claims: {r['hub_claims']}"
        lines.append(f"  {sec:<14} {r.get('status', '?'):<8} {extra}  [{rep['timings_s'].get(sec)}s]")
    for sec, r in rep["sections"].items():
        if r.get("status") == "fail":
            lines.append(f"FAIL {sec}: " + json.dumps(_failures(sec, r), default=str)[:1500])
    lines.append(f"overall {rep['status']} — details in {ctx.state_root / 'last_verify.json'}")
    _out(args, rep, "\n".join(lines))
    return 0 if rep["status"] == "pass" else 1


def _failures(sec: str, r: dict):
    if sec == "kernel":
        return {k: r[k] for k in ("load_errors", "schema_errors", "unresolved_references", "registry_errors") if r[k]}
    if sec == "machine":
        return {k: {"drifted": v.get("drifted"), "failing": v.get("failing")} for k, v in r["isas"].items()
                if v["status"] == "fail"}
    if sec == "conformance":
        return {lang: {n: c for n, c in lr["cells"].items() if c["status"] in ("fail", "error")}
                for lang, lr in r["languages"].items()}
    if sec == "logic":
        return r.get("violations")
    if sec == "lang":
        return {n: p for n, p in r["programs"].items() if p["status"] != "pass"}
    if sec == "theorems":
        return r.get("problems")
    cards = r.get("cards", {})
    bad = {}
    for q, c in cards.items():
        if c.get("status") in ("fail", "error") or c.get("verdict") == "refuted":
            bad[q] = c
        elif "forms" in c and isinstance(c["forms"], dict):
            f = {k: v for k, v in c["forms"].items() if v.get("status") in ("fail", "error")}
            if f:
                bad[q] = f
        elif "languages" in c:
            f = {k: v for k, v in c["languages"].items() if v.get("status") in ("fail", "error")}
            if f or c.get("lift_mismatches"):
                bad[q] = f or {"lift_mismatches": c["lift_mismatches"]}
    return bad


def cmd_cover(args) -> int:
    from .engines import coverage
    ctx = _ctx(args)
    rep = coverage.compute(ctx)
    md = coverage.markdown(rep)
    if args.write:
        Path(args.write).write_text(md, encoding="utf-8")
    _out(args, rep, md if not args.write else f"wrote {args.write}")
    return 0


def cmd_rewrite(args) -> int:
    from .engines import rewrite, search
    ctx = _ctx(args)
    st = ctx.store
    if args.prove:
        rules = search.load_rules(st)
        res = search.prove(args.prove[0], args.prove[1], rules, max_depth=args.depth)
        if res is None:
            _out(args, {"proved": False}, f"no proof within depth {args.depth} (not a disproof)")
            return 1
        from .engines.exprs import to_text
        steps = [(r, to_text(e)) for r, e in res["steps"]]
        _out(args, {"proved": True, "steps": steps, "nodes": res["nodes"]},
             "\n".join(f"  [{r}] {e}" for r, e in steps) + f"\n({res['nodes']} nodes)")
        return 0
    if args.optimize:
        res = search.optimize(args.optimize, search.load_rules(st), search.op_costs(st), max_depth=args.depth)
        res.pop("best_tree", None)
        _out(args, res, f"{res['input']} (cost {res['input_cost']}) -> {res['best']} (cost {res['best_cost']})\n" +
             "\n".join(f"  [{r}] {e}" for r, e in res["steps"]))
        return 0
    if args.rank or args.pareto:
        reg = args.rank or args.pareto
        cards = st.cards(reg)
        if args.rank:
            weights = {k: float(v) for k, v in (kv.split("=") for kv in args.weights.split(","))}
            ranked = rewrite.rank(st, cards, weights)
            _out(args, [(s, c.name) for s, c in ranked], "\n".join(f"  {s:.3f}  {c.name}" for s, c in ranked))
        else:
            front = rewrite.pareto(st, cards, args.dims.split(","))
            _out(args, [c.name for c in front], "pareto front: " + ", ".join(c.name for c in front))
        return 0
    if args.all:
        rs = rewrite.all_rewrites(st, domain=args.domain)
        _out(args, rs, f"{len(rs)} suggested rewrites (domain={args.domain}):\n" + "\n".join(
            f"  {r['card']:<16} {r['from']} -> {r['to']:<14} x{r['speedup']}  {r['notes']}" for r in rs))
        return 0
    if not args.card:
        print("error: give a CARD, --all, --prove, --optimize, --rank or --pareto", file=sys.stderr)
        return 2
    card = st.get(args.card)
    if card is None:
        print(f"error: no card {args.card!r}", file=sys.stderr)
        return 2
    best = rewrite.cheapest(st, card, domain=args.domain, lang=args.lang,
                            cost="measured" if args.measured else "anchor")
    rows = rewrite.enumerate_forms(st, card)
    sugg = rewrite.suggest_rewrite(st, card, args.from_form, args.domain) if args.from_form else None
    data = {"card": card.qualified, "cheapest": best.name if best else None, "forms": rows, "suggestion": sugg}
    lines = [f"{card.qualified}: cheapest for domain={args.domain}" + (f", lang={args.lang}" if args.lang else "") +
             f" -> {best.name if best else 'none'}"]
    for r in rows:
        mark = "✓" if r["available"] else "·"
        ms = f" measured {r['measured_ns']:.0f}ns" if r.get("measured_ns") else ""
        lines.append(f"  {mark} {r['form']:<20} cost {r['cost']:<8} {r['domain']:<12} {r['lang']:<10}{ms} "
                     f"{'' if r['available'] else '(' + r['reason'] + ')'}")
    if sugg:
        lines.append(f"suggest: {sugg['from']} -> {sugg['to']} (x{sugg['speedup']})")
    _out(args, data, "\n".join(lines))
    return 0


def cmd_emit(args) -> int:
    ctx = _ctx(args)
    if args.hints:
        from .emit.hints import hints_for
        card = ctx.store.get(args.hints)
        if card is None:
            print(f"error: no card {args.hints!r}", file=sys.stderr)
            return 2
        h = hints_for(ctx, card)
        _out(args, h, "\n".join([f"{h['card']} emit templates:"] + [f"  {k:<11} {v}" for k, v in h["emit"].items()] +
                                ["hints:"] + [f"  {k:<11} {v}" for k, v in h["hints"].items()]))
        return 0
    if args.rules:
        from .emit import lean
        if args.check:
            res = lean.check_rules(ctx)
            _out(args, res, "\n".join(f"  {r['status']:<15} {q}" for q, r in res["rules"].items()))
            return 0
        print(lean.emit_rules(ctx), end="")
        return 0
    if not args.lang or not args.source:
        print("error: emit needs --lang and a source file or function card", file=sys.stderr)
        return 2
    from .engines.codegen import EmitGap, emit_module
    from .engines.frontend_python import lift_source, module_for
    card = ctx.store.get(args.source) if "/" in args.source or not args.source.endswith(".py") else None
    texts = []
    if card is not None:
        texts.append(emit_module(ctx.store, ctx.ops, args.lang, card["ir"]))
    else:
        src = Path(args.source).read_text(encoding="utf-8")
        lifted = lift_source(src, ctx.ops)
        names = [args.function] if args.function else [lf.name for lf in lifted if lf.ok]
        for lf in lifted:
            if not lf.ok and (not args.function or lf.name == args.function):
                texts.append(f"/* {lf.name}: not lifted: {'; '.join(lf.reasons)} */")
        seen = set()
        for n in names:
            module = module_for(n, lifted)
            todo = [f["name"] for f in module["functions"] if f["name"] not in seen]
            seen.update(todo)
            if todo:
                try:
                    texts.append(emit_module(ctx.store, ctx.ops, args.lang, module, only=todo))
                except EmitGap as exc:
                    texts.append(f"/* {n}: {exc} */")
    text = "\n".join(texts)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_translate(args) -> int:
    from .engines import translate
    from .engines.frontend_python import lift_source
    ctx = _ctx(args)
    src = Path(args.file).read_text(encoding="utf-8")
    lifted = lift_source(src, ctx.ops)
    langs = args.to.split(",") if args.to else None
    seed = args.seed
    from .engines import values as V
    seed = V.fresh_seed() if seed is None else seed
    results = {}
    lines = [f"seed {seed}"]
    for lf in lifted:
        if not lf.ok:
            results[lf.name] = {"lifted": False, "reasons": lf.reasons}
            lines.append(f"  {lf.name:<22} not lifted: {'; '.join(lf.reasons)}")
            continue
        card = translate.function_card(ctx, lf.name, lifted, Path(args.file).name, seed=seed)
        rep = translate.verify_function(ctx, card, langs=langs, seed=seed)
        results[lf.name] = {"card": card["name"], "report": rep}
        bad = {k: v for k, v in rep["languages"].items() if v["status"] not in ("pass",)}
        other = ", ".join(f"{k}={v['status']}" for k, v in bad.items())
        lines.append(f"  {lf.name:<22} agrees in {len(rep['agreeing_languages'])}: "
                     f"{', '.join(rep['agreeing_languages'])}" + (f"  | other: {other}" if bad else ""))
        if args.save:
            card["verification"]["run"] = {k: v for k, v in rep.items() if k != "languages"}
            card["status"] = "healthy" if len(rep["agreeing_languages"]) >= 3 and not rep["lift_mismatches"] else "suspect"
            ctx.store.save(card, category="function")
    _out(args, results, "\n".join(lines))
    failed = [n for n, r in results.items() if "report" in r and any(
        lr["status"] in ("fail", "error") for lr in r["report"]["languages"].values())]
    return 1 if failed else 0   # functions that did not lift are reported gaps, not failures


def cmd_improve(args) -> int:
    from .engines import improve
    from .engines import values as V
    ctx = _ctx(args)
    src_path = Path(args.path)
    if not src_path.exists():
        print(f"error: {src_path} does not exist", file=sys.stderr)
        return 2
    files = [src_path] if src_path.is_file() else sorted(p for p in src_path.rglob("*.py")
                                                         if "__pycache__" not in p.parts)
    seed = V.fresh_seed() if args.seed is None else args.seed
    base = src_path.parent if src_path.is_file() else src_path
    out_root = Path(args.out) if args.out else base.parent / f"{base.name}_optimized"
    if src_path.is_file() and not args.out:
        out_root = src_path.parent / f"{src_path.stem}_optimized"
    summary, failed = [], []
    for f in files:
        rel = f.relative_to(base) if src_path.is_dir() else Path(f.name)
        rep = improve.improve_source(ctx, f.read_text(encoding="utf-8"), str(rel), seed=seed,
                                     native=not args.no_native)
        improve.write_outputs(rep, out_root / rel.parent, rel.stem)
        changed = [(n, x.get("speedup")) for n, x in rep["functions"].items() if x.get("speedup")]
        if rep["end_to_end"].get("status") == "fail" or not rep["effect_shell_identical"]:
            failed.append(str(rel))
        summary.append({"file": str(rel), "changed": changed, "kept": len(rep["functions"]) - len(changed),
                        "effect_shell": len(rep["effect_shell"]), "end_to_end": rep["end_to_end"].get("status"),
                        "shell_identical": rep["effect_shell_identical"]})
    lines = [f"seed {seed} · output {out_root}"]
    for s_ in summary:
        ch = ", ".join(f"{n} x{sp}" for n, sp in s_["changed"]) or "nothing faster found"
        lines.append(f"  {s_['file']}: {ch} · kept {s_['kept']} · effect shell {s_['effect_shell']} "
                     f"(identical: {s_['shell_identical']}) · end-to-end {s_['end_to_end']}")
    _out(args, {"seed": seed, "out": str(out_root), "files": summary, "failed": failed}, "\n".join(lines))
    return 1 if failed else 0


def cmd_arena(args) -> int:
    from .engines import arena
    ctx = _ctx(args)
    res = arena.run(ctx, count=args.count, seed=args.seed, samples=args.samples)
    sc = res["score"]
    name = arena.record(ctx, res, layer=_layer(ctx, args))
    if args.out:
        from .engines import improve
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        (out / "suboptimal.py").write_text(res["source"], encoding="utf-8")
        improve.write_outputs(res["report"], out, "optimized")
        (out / "score.json").write_text(json.dumps(sc, indent=1, default=str) + "\n", encoding="utf-8")
    lines = [f"seed {sc['seed']} · {sc['functions']} functions · recorded {name}",
             f"  sound: {sc['sound']} (end-to-end {sc['end_to_end']} with {sc['end_to_end_checks']} checks, "
             f"effect shell identical {sc['effect_shell_identical']}, decoys wrongly substituted "
             f"{len(sc['decoys_wrongly_substituted'])}, shell preserved {sc['shell_preserved']})",
             f"  recall: {sc['planted_improved']}/{sc['planted']} planted suboptimal functions improved",
             f"  speed: geomean x{sc['geomean_speedup']} over {sc['improved_total']} improved functions "
             f"(max x{sc['max_speedup']})"]
    _out(args, sc, "\n".join(lines))
    return 0 if sc["sound"] else 1


def cmd_learn(args) -> int:
    from .engines.learn import learn
    ctx = _ctx(args)
    langs = args.langs.split(",") if args.langs else None
    rep = learn(ctx, args.path or os.getcwd(), promote=args.promote, layer=_layer(ctx, args), seed=args.seed,
                max_functions=args.max_functions, langs=langs)
    lines = [f"seed {rep['seed']} · observation {rep['observation']} · layer {rep['layer']}",
             f"proposals {dict(rep['proposals'])}, ready {dict(rep['ready'])}",
             f"promoted {len(rep['promoted'])}" + (": " + ", ".join(rep["promoted"][:12]) if rep["promoted"] else ""),
             f"pending {rep['pending']} (see registry proposal/)" + ("" if args.promote else
                                                                   " -- rerun with --promote to promote ready ones")]
    _out(args, rep, "\n".join(lines))
    return 0


def cmd_optimize(args) -> int:
    from .engines import optimize
    from .engines import values as V
    ctx = _ctx(args)
    seed = V.fresh_seed() if args.seed is None else args.seed
    rows = []
    if args.card:
        card = ctx.store.get(args.card)
        if card is None:
            print(f"error: no card {args.card!r}", file=sys.stderr)
            return 2
        rows += optimize.measure_function(ctx, card, seed=seed) if card.registry == "function" else \
            optimize.measure_python_forms(ctx, card, seed)
    else:
        for card in ctx.store.cards("op"):
            rows += optimize.measure_python_forms(ctx, card, seed)
        if args.functions:
            for card in ctx.store.cards("function"):
                rows += optimize.measure_function(ctx, card, seed=seed)
    names = optimize.write_metrics(ctx, rows, layer=_layer(ctx, args))
    vs = optimize.verdicts(rows)
    applied = optimize.apply_costs(ctx, rows, layer=None) if args.apply else []
    mark = {"green": "🟢", "white": "⚪", "red": "🔴"}
    lines = [f"seed {seed} · {len(names)} metric cards written"]
    for v in vs:
        lines.append(f"  {mark[v['verdict']]} {v['card']:<22} anchor picks {v['anchor_pick']}, measured picks "
                     f"{v['measured_pick']}  {v['measured_ns']}")
    if applied:
        lines.append(f"cost anchors updated (versioned) on {len(applied)} cards: {', '.join(applied[:10])}")
    _out(args, {"seed": seed, "metrics": names, "verdicts": vs, "applied": applied}, "\n".join(lines))
    return 0


def cmd_show(args) -> int:
    ctx = _ctx(args)
    card = ctx.store.get(args.card)
    if card is None:
        print(f"error: no card {args.card!r}", file=sys.stderr)
        return 2
    data = dict(card)
    data["_location"] = {"registry": card.registry, "layer": card.layer, "source": card.source,
                         "path": str(card.path) if card.path else None, "variants": sorted(card.variant_files())}
    _out(args, data, json.dumps(data, indent=1, ensure_ascii=False, default=str))
    return 0


def cmd_list(args) -> int:
    ctx = _ctx(args)
    if args.registry:
        v = ctx.store.registry(args.registry)
        if v is None:
            print(f"error: no registry {args.registry!r}", file=sys.stderr)
            return 2
        names = sorted(v.ALL)
        _out(args, names, "\n".join(names))
        return 0
    rows = {n: len(v) for n, v in ctx.store.views.items()}
    _out(args, rows, "\n".join(f"{n:<22} {k}" for n, k in rows.items()))
    return 0


def cmd_probe(args) -> int:
    ctx = _ctx(args)
    rows = {}
    for card in ctx.store.cards("language"):
        ok, why = ctx.available(card.name) if card.get("probe") else (False, "no probe")
        rows[card.name] = {"available": ok, "detail": why, "codegen": card.get("codegen") is not None}
    _out(args, rows, "\n".join(f"  {'✓' if r['available'] else '·'} {n:<11} {'codegen ' if r['codegen'] else '        '}"
                               f"{r['detail']}" for n, r in sorted(rows.items())))
    return 0


def cmd_new(args) -> int:
    ctx = _ctx(args)
    card = {"name": args.name, "category": args.registry, "tier": 3, "statement": args.statement or "TODO: what this card claims",
            "forms": [], "metadata": {"created_by": "cardmodel new"}}
    if ctx.store.get(f"{args.registry}/{args.name}") is not None:
        print(f"error: {args.registry}/{args.name} exists", file=sys.stderr)
        return 2
    saved, _ = ctx.store.save(card, layer=_layer(ctx, args))
    _out(args, {"created": str(saved.path)}, f"created {saved.path / 'card.json'}")
    return 0


def cmd_docs(args) -> int:
    from .engines.docs import laws_md
    ctx = _ctx(args)
    text = laws_md(ctx.store)
    target = paths.home() / "LAWS.md"
    if args.check:
        same = target.exists() and target.read_text(encoding="utf-8") == text
        print("LAWS.md in sync" if same else "LAWS.md is stale: run `cardmodel docs`")
        return 0 if same else 1
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}")
    return 0


def cmd_clean(args) -> int:
    from .engines.runners import clean_build
    ctx = _ctx(args)
    freed = clean_build(ctx.state_root)
    print(f"removed build cache ({freed} bytes)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cardmodel", description=__doc__.splitlines()[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--json", action="store_true")
    p.add_argument("--project")
    p.add_argument("--no-project", action="store_true")
    p.add_argument("--cards", action="append", metavar="PATH",
                   help="also load another card tree read-only (repeatable), e.g. another program's cards/")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("init"); s.add_argument("path", nargs="?"); s.set_defaults(fn=cmd_init)
    s = sub.add_parser("status"); s.set_defaults(fn=cmd_status)
    s = sub.add_parser("observe"); s.add_argument("path"); s.add_argument("--save", action="store_true")
    s.set_defaults(fn=cmd_observe)
    s = sub.add_parser("verify")
    s.add_argument("--seed", type=int); s.add_argument("--only"); s.add_argument("--langs")
    s.add_argument("--quick", action="store_true"); s.add_argument("--record", action="store_true")
    s.add_argument("--samples", type=int, default=48); s.set_defaults(fn=cmd_verify)
    s = sub.add_parser("cover"); s.add_argument("--write"); s.set_defaults(fn=cmd_cover)
    s = sub.add_parser("rewrite")
    s.add_argument("card", nargs="?"); s.add_argument("--domain", default="any"); s.add_argument("--lang")
    s.add_argument("--from", dest="from_form"); s.add_argument("--measured", action="store_true")
    s.add_argument("--all", action="store_true"); s.add_argument("--prove", nargs=2, metavar=("LHS", "RHS"))
    s.add_argument("--optimize", metavar="EXPR"); s.add_argument("--depth", type=int, default=5)
    s.add_argument("--rank", metavar="REGISTRY"); s.add_argument("--weights", default="")
    s.add_argument("--pareto", metavar="REGISTRY"); s.add_argument("--dims", default="")
    s.set_defaults(fn=cmd_rewrite)
    s = sub.add_parser("emit")
    s.add_argument("source", nargs="?"); s.add_argument("--lang"); s.add_argument("--function")
    s.add_argument("--out"); s.add_argument("--rules", action="store_true"); s.add_argument("--check", action="store_true")
    s.add_argument("--hints", metavar="CARD"); s.set_defaults(fn=cmd_emit)
    s = sub.add_parser("translate"); s.add_argument("file"); s.add_argument("--to"); s.add_argument("--seed", type=int)
    s.add_argument("--save", action="store_true"); s.set_defaults(fn=cmd_translate)
    s = sub.add_parser("learn")
    s.add_argument("path", nargs="?"); s.add_argument("--promote", action="store_true")
    s.add_argument("--global", dest="global_", action="store_true"); s.add_argument("--seed", type=int)
    s.add_argument("--max-functions", type=int, default=25); s.add_argument("--langs"); s.set_defaults(fn=cmd_learn)
    s = sub.add_parser("optimize")
    s.add_argument("--card"); s.add_argument("--functions", action="store_true"); s.add_argument("--apply", action="store_true")
    s.add_argument("--seed", type=int); s.add_argument("--global", dest="global_", action="store_true")
    s.set_defaults(fn=cmd_optimize)
    s = sub.add_parser("improve"); s.add_argument("path"); s.add_argument("--out"); s.add_argument("--seed", type=int)
    s.add_argument("--no-native", action="store_true"); s.set_defaults(fn=cmd_improve)
    s = sub.add_parser("arena"); s.add_argument("--count", type=int, default=60); s.add_argument("--seed", type=int)
    s.add_argument("--samples", type=int, default=24); s.add_argument("--out")
    s.add_argument("--global", dest="global_", action="store_true"); s.set_defaults(fn=cmd_arena)
    s = sub.add_parser("show"); s.add_argument("card"); s.set_defaults(fn=cmd_show)
    s = sub.add_parser("list"); s.add_argument("registry", nargs="?"); s.set_defaults(fn=cmd_list)
    s = sub.add_parser("probe"); s.set_defaults(fn=cmd_probe)
    s = sub.add_parser("new"); s.add_argument("registry"); s.add_argument("name"); s.add_argument("--statement")
    s.add_argument("--global", dest="global_", action="store_true"); s.set_defaults(fn=cmd_new)
    s = sub.add_parser("docs"); s.add_argument("--check", action="store_true"); s.set_defaults(fn=cmd_docs)
    s = sub.add_parser("clean"); s.set_defaults(fn=cmd_clean)
    from . import cli_ext
    cli_ext.register(sub)
    return p


def main(argv=None) -> int:
    sys.dont_write_bytecode = True
    args = build_parser().parse_args(argv)
    return args.fn(args)
