"""cli_ext — commands for the card language, logic, laws and Lean (registered by cli.build_parser).

  cardmodel run FILE.card [--lean] [--deep] [--seed N] [--call FN ARG...]
  cardmodel lang check|build|emit FILE.card [--save] [--lang L]
  cardmodel logic query SOURCE 'ancestor(alice, X)' | why SOURCE 'atom' [--lean] | mine SOURCE [--save] | self
  cardmodel logic code PATH ['query'] [--facts]     a Python code base as facts + stdlib/program.card rules
  cardmodel laws [--save] [--no-lean] [--deep] [--seed N]
  cardmodel lean import FILE.lean ... | --core [--save] [--limit N] [--no-reprove]   ·   lean check FILE.lean
  cardmodel repl

SOURCE is a .card file or the name of a theory card.
"""
from __future__ import annotations


import sys
from pathlib import Path


def _cli():
    from . import cli
    return cli


def _load_module(ctx, path: str):
    from .lang.compile import CompileError, compile_file
    from .lang.syntax import CardSyntaxError
    try:
        return compile_file(path, ctx.ops, ctx.store), None
    except (CompileError, CardSyntaxError) as exc:
        return None, str(exc)
    except FileNotFoundError:
        return None, f"no such file: {path}"


def cmd_run(args) -> int:
    from .lang import run as R
    cli = _cli()
    ctx = cli._ctx(args)
    mod, err = _load_module(ctx, args.file)
    if err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    if args.call:
        from .engines.ir import Interpreter
        fn = args.call[0]
        if fn not in mod.functions:
            print(f"error: no function {fn} in {args.file} (have: {', '.join(sorted(mod.functions))})", file=sys.stderr)
            return 2
        params = mod.functions[fn]["params"]
        raw = args.call[1:]
        if len(raw) != len(params):
            print(f"error: {fn} takes {len(params)} argument(s)", file=sys.stderr)
            return 2
        conv = {"int": int, "float": float, "bool": lambda s: s.lower() in ("1", "true", "yes")}
        vals = [conv[p["type"]](a) for p, a in zip(params, raw)]
        out = Interpreter(mod.ir_module(fn), ctx.ops, step_limit=50_000_000).call(fn, vals)
        cli._out(args, {"function": fn, "args": vals, "result": out}, str(out))
        return 0
    rep = R.run(ctx, mod, seed=args.seed, lean=args.lean, deep=args.deep)
    cli._out(args, {k: v for k, v in rep.items()}, R.report_text(rep, verbose=args.verbose))
    return 0 if rep["status"] == "pass" else 1


def cmd_lang(args) -> int:
    from .lang import run as R
    cli = _cli()
    ctx = cli._ctx(args)
    mod, err = _load_module(ctx, args.file)
    if err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    if args.action == "check":
        s = mod.summary()
        problems = mod.program.check()
        text = (f"{args.file}: ok — module {s['module']}: functions {', '.join(s['functions']) or '-'}; "
                f"{s['facts']} facts, {s['rules']} rules, {s['constraints']} constraints; "
                f"theorems {', '.join(t.split('.', 1)[-1] for t in s['theorems']) or '-'}; {s['tests']} tests; "
                f"{len(s['cards'])} cards")
        cli._out(args, {"summary": s, "problems": problems}, text)
        return 0 if not problems else 1
    if args.action == "emit":
        if not args.lang:
            print("error: --lang L (one of the language cards with codegen)", file=sys.stderr)
            return 2
        from .engines.codegen import EmitGap
        try:
            code = R.emit(ctx, mod, args.lang, [args.function] if args.function else None)
        except EmitGap as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.out:
            Path(args.out).write_text(code, encoding="utf-8")
            print(f"wrote {args.out}")
        else:
            print(code)
        return 0
    rep = R.run(ctx, mod, seed=args.seed, lean=args.lean)
    cards = R.build_cards(ctx, mod, rep)
    counts = {k: len(v) for k, v in cards.items() if v}
    data = {"run": rep["status"], "cards": counts}
    if args.save:
        if rep["status"] != "pass" and not args.force:
            print(f"not saving: the module does not pass ({rep['counts']}); fix it or pass --force", file=sys.stderr)
            return 1
        layer = cli._layer(ctx, args)
        data["written"] = R.save_cards(ctx, cards, layer)
        data["layer"] = layer
    text = (f"{args.file}: {rep['status']} · cards " + ", ".join(f"{k} {v}" for k, v in counts.items()) +
            (f" · saved to the {data['layer']} layer ({data['written']})" if args.save else " (dry run: --save writes them)"))
    cli._out(args, data, text)
    return 0 if rep["status"] == "pass" else 1


def _program(ctx, source: str):
    from .engines import logic as L
    if source.endswith(".card") or Path(source).is_file():
        mod, err = _load_module(ctx, source)
        if err:
            raise ValueError(err)
        from .lang.run import _caller
        call, _ = _caller(ctx, mod)
        return mod.program, call
    return L.program_from_store(ctx.store, source), None


def cmd_logic(args) -> int:
    from .engines import logic as L
    cli = _cli()
    ctx = cli._ctx(args)
    if args.action == "code":
        from .engines import codefacts
        from .kernel import paths
        if not args.source:
            print("error: logic code PATH", file=sys.stderr)
            return 2
        facts = codefacts.facts_for(args.source)
        if args.facts:
            print(codefacts.as_card_source(facts), end="")
            return 0
        rules, err = _load_module(ctx, str(paths.home() / "stdlib" / "program.card"))
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
        facts.rules.extend(rules.program.rules)
        facts.facts.extend(rules.program.facts)
        model = L.evaluate(facts, ctx.ops)
        fns = sorted(t[0] for t in model.db.rel.get("function", ()))
        pure = {t[0] for t in model.db.rel.get("pure", ())}
        opt = {t[0] for t in model.db.rel.get("optimizable", ())}
        rec = {t[0] for t in model.db.rel.get("recursive", ())}
        blast = sorted(model.db.rel.get("blast", ()), key=lambda t: -t[1])
        lines = [f"{len(fns)} functions · {len(pure)} pure · {len(fns) - len(pure)} effectful (directly or through "
                 f"calls) · {len(opt)} in the optimizable pure core · {len(rec)} recursive · "
                 f"{len(model.violations)} violation(s) of the lifter/effect consistency rule"]
        for g, n in blast[:8]:
            lines.append(f"  effect at {g} taints {n} caller(s)")
        if args.text:
            from .lang.compile import Compiler, LogicCompiler
            from .lang.syntax import parse_body
            lits = [LogicCompiler(Compiler(ctx.ops, ctx.store)).literal(x) for x in parse_body(args.text)]
            ans = model.query(lits, limit=args.limit)
            lines.append(f"?- {args.text}")
            lines += ["  " + ", ".join(f"{k} = {L.term_text(v)}" for k, v in a.items()) for a in ans] or ["  no"]
        cli._out(args, {"functions": len(fns), "pure": sorted(pure), "optimizable": sorted(opt),
                        "recursive": sorted(rec), "violations": model.violations}, "\n".join(lines))
        return 0 if not model.violations else 1
    if args.action == "self":
        from .engines import selflogic
        r = selflogic.evaluate_self(ctx)
        lines = [f"self theory: {r['stats']['given']} facts about {len(ctx.store.ALL)} cards, {r['rules']} rules, "
                 f"{r['stats']['derived']} derived · {r['violation_count']} violation(s) · {r['status']}"]
        for v in r["violations"][:20]:
            lines.append(f"  VIOLATED {v['rule']} with {v['bindings']}")
        if r["cyclic"]:
            lines.append(f"  dependency cycles through: {', '.join(r['cyclic'])}")
        r.pop("model")
        cli._out(args, r, "\n".join(lines))
        return 0 if r["status"] == "pass" else 1
    try:
        prog, call = _program(ctx, args.source)
    except (ValueError, L.LogicError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    model = L.evaluate(prog, ctx.ops, call=call)
    if args.action == "query":
        from .lang.compile import Compiler, LogicCompiler
        from .lang.syntax import CardSyntaxError, parse_body
        try:
            comp = Compiler(ctx.ops, ctx.store)
            comp.module = None
            lits = [LogicCompiler(comp).literal(x) for x in parse_body(args.text)]
        except CardSyntaxError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        answers = model.query(lits, limit=args.limit)
        if not answers:
            text = "no"
        elif not answers[0]:
            text = "yes"
        else:
            text = "\n".join(", ".join(f"{k} = {L.term_text(v)}" for k, v in a.items()) for a in answers)
        cli._out(args, {"answers": answers}, text)
        return 0 if answers else 1
    if args.action == "why":
        from .lang.compile import Compiler, LogicCompiler
        from .lang.syntax import parse_body
        lits = [LogicCompiler(Compiler(ctx.ops, ctx.store)).literal(x) for x in parse_body(args.text)]
        atom = lits[0]
        if not isinstance(atom, L.Atom) or not atom.ground():
            print("error: `why` takes one ground atom, e.g. 'ancestor(alice, dave)'", file=sys.stderr)
            return 2
        if not model.holds(atom.pred, atom.args):
            cli._out(args, {"holds": False}, f"{atom} does not follow from the theory")
            return 1
        proof = model.proof(atom.pred, atom.args)
        data = {"holds": True, "proof": proof, "stats": L.proof_stats(proof)}
        text = L.proof_text(proof)
        if args.lean:
            from .emit.lean_logic import certify
            cert = certify(model, [(atom.pred, tuple(atom.args))])
            data["lean"] = {k: v for k, v in cert.items() if k != "source"}
            th = (cert.get("theorems") or [{}])[0]
            text += f"\nLean kernel: {th.get('status', cert['status'])}" + (f" ({th['detail']})" if th.get("detail") else "")
            if args.out and cert.get("source"):
                Path(args.out).write_text(cert["source"], encoding="utf-8")
                text += f" · certificate written to {args.out}"
        cli._out(args, data, text)
        return 0
    if args.action == "mine":
        from .engines import mine as M
        res = M.mine(M.relations(model), min_support=args.min_support)
        lines = [f"{res['candidates']} candidate rules over {len(res['relations'])} relations · "
                 f"{len(res['laws'])} exact laws (confidence 1, support >= {res['min_support']}) · "
                 f"{len(res['tendencies'])} tendencies"]
        for f in res["laws"][:args.limit]:
            lines.append(f"  law       {f['text']:<55} support {f['support']}")
        for f in res["tendencies"][:args.limit]:
            lines.append(f"  tendency  {f['text']:<55} confidence {f['confidence']} "
                         f"(e.g. not for {f['counterexamples'][:1]})")
        if args.save:
            cards = M.rule_cards(res, prog.name, args.source)
            layer = cli._layer(ctx, args)
            for c in cards:
                ctx.store.save(c, layer=layer)
            lines.append(f"saved {len(cards)} logic_rule cards (learned, with evidence) to the {layer} layer")
        cli._out(args, res, "\n".join(lines))
        return 0
    return 2


def cmd_laws(args) -> int:
    from .engines import laws
    cli = _cli()
    ctx = cli._ctx(args)
    rep = laws.discover(ctx, seed=args.seed, samples=args.samples, lean=not args.no_lean, deep=args.deep)
    lines = [f"seed {rep['seed']}: {rep['candidates']} candidate laws over the op cards -> {rep['refuted']} refuted "
             f"(counterexample), {rep['vacuous']} vacuous, {rep['witnessed'] + rep['proved']} hold: "
             f"{rep['proved']} proved by Lean ({rep['toolchain'] or 'no toolchain'}), {rep['witnessed']} witnessed",
             "by template: " + ", ".join(f"{k} {v}" for k, v in sorted(rep["by_template"].items()))]
    if args.verbose:
        for c in rep["laws"]:
            how = ", ".join(p["method"] for p in c.get("proofs") or [] if p.get("ok"))
            lines.append(f"  {c['status']:<9} {c['name']:<40} {c['statement']}  {how}")
    lines.append(f"{len(rep['rules'])} simplifying laws become rewrite rules (optimizer)")
    if args.save:
        layer = cli._layer(ctx, args)
        ctx.store.save_pack("theorem", "laws", rep["laws"], layer=layer)
        ctx.store.save_pack("rewrite_rule", "laws", rep["rules"], layer=layer)
        lines.append(f"saved {len(rep['laws'])} theorem cards and {len(rep['rules'])} rewrite_rule cards "
                     f"(packs _pack_laws.jsonl) to the {layer} layer")
    cli._out(args, {k: v for k, v in rep.items() if k != "laws"} | {"laws": [c["name"] for c in rep["laws"]]},
             "\n".join(lines))
    return 0


def cmd_lean(args) -> int:
    from .emit import lean as LE
    from .emit import lean_import as LI
    cli = _cli()
    ctx = cli._ctx(args)
    exe = LE.lean_exe()
    if args.action == "check":
        if exe is None:
            print("error: no Lean toolchain found", file=sys.stderr)
            return 2
        ok, log = LE.check_source(Path(args.files[0]).read_text(encoding="utf-8"), exe)
        cli._out(args, {"ok": ok, "log": log}, f"{args.files[0]}: {'accepted by the Lean kernel' if ok else 'rejected'}"
                 + ("" if ok else "\n" + log))
        return 0 if ok else 1
    sources = []
    if args.core:
        root = LI.core_root(exe)
        if root is None:
            print("error: no Lean toolchain with sources found", file=sys.stderr)
            return 2
        for f in LI.CORE_FILES:
            if (root / f).is_file():
                sources.append((f, (root / f).read_text(encoding="utf-8"),
                                {"kind": "lean_core", "file": f, "toolchain": LI.T.toolchain_version(exe),
                                 "license": "Apache-2.0 (Lean 4 core library)"}))
    for f in args.files or []:
        sources.append((f, Path(f).read_text(encoding="utf-8"), {"kind": "lean_file", "file": Path(f).name}))
    if not sources:
        print("error: give .lean files or --core", file=sys.stderr)
        return 2
    total = {"declarations": 0, "in_fragment": 0, "faithful": 0, "witnessed": 0, "reproved": 0}
    lines, all_cards, refuted = [], [], []
    for label, text, origin in sources:
        rep = LI.import_source(ctx, text, origin, seed=args.seed, reprove_tactics=False if args.no_reprove else None,
                               limit=args.limit)
        for k in total:
            total[k] += rep.get(k, 0) or 0
        refuted += rep.get("witness_refuted", [])
        all_cards += rep["cards"]
        lines.append(f"  {label}: {rep['declarations']} theorems, {rep['in_fragment']} in the fragment, "
                     f"{rep.get('faithful', '?')} faithful, {rep['witnessed']} witnessed, "
                     f"{rep.get('reproved', '-')} re-proved by cardmodel tactics")
    head = (f"{total['declarations']} Lean theorems scanned · {total['in_fragment']} in the fragment · "
            f"{total['faithful']} read faithfully (the kernel accepts our reading as the original) · "
            f"{total['witnessed']} witnessed under Lean semantics · {total['reproved']} re-proved without "
            f"the original proof · {len(refuted)} semantic mismatches")
    out = [head, *lines]
    if refuted:
        out.append("MISMATCH (card semantics disagree with a Lean-proved statement): " + ", ".join(refuted[:10]))
    if args.save:
        layer = cli._layer(ctx, args)
        pack = "lean_core" if args.core and not args.files else "lean_" + "_".join(Path(f).stem for f in args.files)[:60]
        path = ctx.store.save_pack("theorem", pack, all_cards, layer=layer)
        out.append(f"saved {len(all_cards)} theorem cards to {path}")
    cli._out(args, total | {"refuted": refuted}, "\n".join(out))
    return 0 if not refuted else 1


def cmd_repl(args) -> int:
    """A line-at-a-time session: declarations accumulate; an expression is evaluated; ?- queries; :help."""
    from .engines import logic as L
    from .lang.compile import CompileError, Compiler, LogicCompiler, compile_source
    from .lang.run import _caller
    from .lang.syntax import CardSyntaxError, Parser
    cli = _cli()
    ctx = cli._ctx(args)
    buf: list[str] = []
    print("card language — declarations accumulate; `?- goal` queries; an expression prints its value; :quit")
    while True:
        try:
            line = input("card> ")
        except EOFError:
            print()
            return 0
        s = line.strip()
        if not s:
            continue
        if s in (":q", ":quit", "exit"):
            return 0
        if s == ":show":
            print("\n".join(buf) or "(empty)")
            continue
        if s == ":help":
            print("fn f(x: Int) -> Int = x * x · parent(a, b). · anc(X, Y) <- parent(X, Y). · ?- anc(a, W) · f(3) + 1")
            continue
        try:
            if s.startswith("?-") or s.startswith("?"):
                mod = compile_source("\n".join(buf), ctx.ops, ctx.store, name="repl")
                call, _ = _caller(ctx, mod)
                model = L.evaluate(mod.program, ctx.ops, call=call)
                from .lang.syntax import parse_body
                lits = [LogicCompiler(Compiler(ctx.ops, ctx.store)).literal(x) for x in parse_body(s.lstrip("?-").strip())]
                ans = model.query(lits, limit=20)
                print("no" if not ans else "yes" if not ans[0] else
                      "\n".join(", ".join(f"{k} = {L.term_text(v)}" for k, v in a.items()) for a in ans))
                continue
            try:
                Parser(s).program()
                compile_source("\n".join(buf + [s]), ctx.ops, ctx.store, name="repl")
                buf.append(s)
                print("ok")
                continue
            except (CardSyntaxError, CompileError) as decl_err:
                try:
                    mod = compile_source("\n".join(buf), ctx.ops, ctx.store, name="repl")
                    comp = Compiler(ctx.ops, ctx.store)
                    comp.sigs = {n: {"params": [p["type"] for p in f["params"]], "returns": f["returns"]}
                                 for n, f in mod.functions.items()}
                    expr = Parser(s).expr(ctx="logic")
                    ir = LogicCompiler(comp).expr(expr, 1)
                    call, _ = _caller(ctx, mod)
                    print(L.eval_expr(ir, {}, ctx.ops, call))
                except Exception:  # noqa: BLE001 -- show the declaration error, which is the likelier intent
                    print(f"error: {decl_err}")
        except (CardSyntaxError, CompileError, L.LogicError) as exc:
            print(f"error: {exc}")


def register(sub) -> None:
    s = sub.add_parser("run", help="run a .card program: tests, queries, theorems, constraints")
    s.add_argument("file"); s.add_argument("--seed", type=int); s.add_argument("--lean", action="store_true")
    s.add_argument("--deep", action="store_true"); s.add_argument("--verbose", action="store_true")
    s.add_argument("--call", nargs="+", metavar=("FN", "ARG")); s.set_defaults(fn=cmd_run)
    s = sub.add_parser("lang", help="check, build (cards) or emit (native code) a .card module")
    s.add_argument("action", choices=["check", "build", "emit"]); s.add_argument("file")
    s.add_argument("--save", action="store_true"); s.add_argument("--force", action="store_true")
    s.add_argument("--global", dest="global_", action="store_true"); s.add_argument("--lean", action="store_true")
    s.add_argument("--lang"); s.add_argument("--function"); s.add_argument("--out"); s.add_argument("--seed", type=int)
    s.set_defaults(fn=cmd_lang)
    s = sub.add_parser("logic", help="query, explain (with a Lean proof), mine rules, or check the model's own laws")
    s.add_argument("action", choices=["query", "why", "mine", "self", "code"]); s.add_argument("source", nargs="?")
    s.add_argument("--facts", action="store_true", help="code: print the facts as card-language source")
    s.add_argument("text", nargs="?"); s.add_argument("--lean", action="store_true"); s.add_argument("--out")
    s.add_argument("--limit", type=int, default=50); s.add_argument("--min-support", type=int, default=3)
    s.add_argument("--save", action="store_true"); s.add_argument("--global", dest="global_", action="store_true")
    s.set_defaults(fn=cmd_logic)
    s = sub.add_parser("laws", help="discover the laws the op cards obey; witness, prove (Lean), promote")
    s.add_argument("--seed", type=int); s.add_argument("--samples", type=int, default=200)
    s.add_argument("--no-lean", action="store_true"); s.add_argument("--deep", action="store_true")
    s.add_argument("--save", action="store_true"); s.add_argument("--global", dest="global_", action="store_true")
    s.add_argument("--verbose", action="store_true"); s.set_defaults(fn=cmd_laws)
    s = sub.add_parser("lean", help="import Lean theorems as cards (faithfulness, witness, re-proof) or check a file")
    s.add_argument("action", choices=["import", "check"]); s.add_argument("files", nargs="*")
    s.add_argument("--core", action="store_true"); s.add_argument("--save", action="store_true")
    s.add_argument("--global", dest="global_", action="store_true"); s.add_argument("--limit", type=int)
    s.add_argument("--no-reprove", action="store_true"); s.add_argument("--seed", type=int)
    s.set_defaults(fn=cmd_lean)
    s = sub.add_parser("repl", help="interactive card language")
    s.set_defaults(fn=cmd_repl)
    from .game import cli as game_cli
    game_cli.register(sub)


__all__ = ["register"]

