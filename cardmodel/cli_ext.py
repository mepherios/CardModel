"""cli_ext — commands for the card language, logic, laws and Lean (registered by cli.build_parser).

  cardmodel run FILE.card [--lean] [--deep] [--seed N] [--call FN ARG...]
  cardmodel lang check|build|emit FILE.card [--save] [--lang L]
  cardmodel logic query SOURCE 'ancestor(alice, X)' | why SOURCE 'atom' [--lean] | mine SOURCE [--save] | self
  cardmodel logic code PATH ['query'] [--facts]     a Python code base as facts + stdlib/program.card rules
  cardmodel laws [--save] [--no-lean] [--deep] [--seed N]
  cardmodel lean import FILE.lean ... | --core [--save] [--limit N] [--no-reprove]   ·   lean check FILE.lean
  cardmodel algebra form|gcd|total F [G] | scan [--write] | godel SEQ   functions as algebra (engines/funcalg.py)
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


def _algebra_fn(ctx, spec: str):
    """A one-integer function from: algorithm/NAME[:FORM], FILE.py:FUNC, FILE.card:FUNC or expr:EXPRESSION in n."""
    if spec.startswith("expr:"):
        from .engines.exprs import evaluate, parse
        tree = parse(spec[5:])
        return lambda n: evaluate(tree, {"n": n}, mode="int")
    if spec.startswith("algorithm/"):
        from .engines.witness import python_callable
        name, _, form_name = spec[len("algorithm/"):].partition(":")
        card = ctx.store.get(f"algorithm/{name}")
        if card is None:
            raise ValueError(f"no algorithm card {name}")
        form = next((f for f in card["forms"] if f["name"] == (form_name or card.get("reference_form"))), None)
        if form is None:
            raise ValueError(f"algorithm/{name} has no form {form_name!r}")
        return python_callable(ctx, form, card)
    path, _, fn = spec.rpartition(":")
    if path.endswith(".card"):
        from .engines.ir import Interpreter
        mod, err = _load_module(ctx, path)
        if err:
            raise ValueError(err)
        interp = Interpreter(mod.ir_module(fn), ctx.ops, step_limit=5_000_000)
        return lambda n: interp.call(fn, [n])
    if path.endswith(".py"):
        from .engines.improve import _functions_only, _load
        ns = _load(_functions_only(Path(path).read_text(encoding="utf-8")))
        if fn not in ns:
            raise ValueError(f"no function {fn} in {path}")
        return ns[fn]
    raise ValueError("a function is algorithm/NAME[:FORM], FILE.py:FUNC, FILE.card:FUNC or expr:EXPRESSION")


def _short_number(n: int) -> str:
    t = str(n)
    return t if len(t) <= 40 else f"{t[:18]}…{t[-12:]} ({len(t)} digits)"


def cmd_algebra(args) -> int:
    from .engines import funcalg as FA
    cli = _cli()
    ctx = cli._ctx(args)
    try:
        if args.action == "godel":
            seq = [int(x) for x in args.targets[0].replace(",", " ").split()] if args.targets else []
            if args.number:
                dec = FA.godel_decode(int(args.number))
                cli._out(args, {"decoded": dec}, f"{args.number} -> {dec}")
                return 0
            num = FA.godel_encode(seq)
            cli._out(args, {"number": str(num), "decoded": FA.godel_decode(num)},
                     f"{seq} -> {num}\ndecodes back to {FA.godel_decode(num)}")
            return 0
        if args.action == "scan":
            r = FA.scan_algorithms(ctx)
            lines = [f"{len(r['forms'])} one-integer algorithm cards with a canonical form; "
                     f"{sum(len(i['forms']) for i in r['forms'].values())} forms, each card's forms share one "
                     f"Gödel number{' EXCEPT: ' + '; '.join(r['problems']) if r['problems'] else ''}"]
            for n, i in r["forms"].items():
                lines.append(f"  {n:<16} {i['kind']:<32} {i['canonical']}   #{_short_number(int(i['godel']))}")
            for c in r["classes"]:
                lines.append(f"  same function: {', '.join(c)}")
            for rel in r["relations"]:
                parts = [rel[k] for k in ("shift", "composition", "composition_rev", "cross_identity", "basis_change")
                         if k in rel]
                lines.append(f"  {rel['f']} ~ {rel['g']}: " + " | ".join(parts)
                             + (f"  [shared operator {rel['shared_operator']}]" if rel.get("shared_operator") else ""))
            for n, d in r["fixed_divisors"].items():
                lines.append(f"  every value of {n} is divisible by {d}")
            if args.write:
                from .kernel import paths
                out = paths.home() / "stdlib" / "algebra.card"
                out.write_text(FA.card_source(r), encoding="utf-8")
                layer = cli._layer(ctx, args)
                cards = FA.identity_cards(r)
                path = ctx.store.save_pack("functional_identity", "algorithms", cards, layer=layer,
                                           description="Identities between functions found from their behaviour "
                                           "(engines/funcalg.py): canonical forms with Gödel numbers, shifts, "
                                           "compositions, cofactor identities, shared operators.")
                lines.append(f"wrote {out} and {len(cards)} functional_identity cards to {path}")
            r.pop("_forms", None)
            cli._out(args, r, "\n".join(lines))
            return 0
        fns = [_algebra_fn(ctx, t) for t in args.targets]
        if args.action in ("form", "total"):
            f = FA.fit(fns[0], args.start)
            if f is None:
                cli._out(args, {"form": None}, f"{args.targets[0]}: no linear recurrence of order <= {FA.MAX_ORDER} "
                         "fits its behaviour (no canonical form here)")
                return 1
            if args.action == "total":
                f = FA.total(f)
            src = FA.python_source(f, "fast", "n")
            text = (f"{args.targets[0]}{' (running total)' if args.action == 'total' else ''}: {f.kind()}\n"
                    f"  {f.describe()}\n  annihilator {f.annihilator().text('E')}   checked on {f.checked} unused terms\n"
                    f"  Gödel number {_short_number(f.godel())}"
                    + (f"\n  fixed divisor {FA.fixed_divisor(f)}" if f.poly is not None else "")
                    + (f"\n  fast form:\n{src}" if src else ""))
            cli._out(args, {"kind": f.kind(), "canonical": f.describe(), "godel": str(f.godel()), "fast": src}, text)
            return 0
        if args.action == "gcd":
            if len(fns) != 2:
                print("error: algebra gcd F G", file=sys.stderr)
                return 2
            fa, fb = FA.fit(fns[0], args.start), FA.fit(fns[1], args.start)
            if fa is None or fb is None:
                print("error: one of the functions has no canonical form here", file=sys.stderr)
                return 1
            r = FA.gcd_functions(fa, fb)
            lines = [f"f = {args.targets[0]}: {r['f']}", f"g = {args.targets[1]}: {r['g']}",
                     f"operators: gcd {r['operators']['gcd']}  lcm {r['operators']['lcm']}  "
                     f"(cofactors {r['operators']['cofactor_f']} | {r['operators']['cofactor_g']})"]
            for k in ("shift", "basis_change", "composition", "composition_rev"):
                if r.get(k):
                    lines.append(f"{k.replace('_', ' ')}: {r[k]}")
            if r.get("values"):
                v = r["values"]
                lines.append(f"values: common factor {v['common_factor']}, cofactors {v['cofactor_f']} | "
                             f"{v['cofactor_g']}" + (f"; {v['cross_identity']}" if v.get("cross_identity") else ""))
            if r.get("fixed_divisors"):
                lines.append(f"fixed divisors: {r['fixed_divisors']}")
            cli._out(args, r, "\n".join(lines))
            return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 2


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


def cmd_godel(args) -> int:
    from collections import Counter

    from .engines import godel as GD
    cli = _cli()
    ctx = cli._ctx(args)
    idx = GD.index_of(ctx.store)
    if args.action == "sizes":
        from .engines import codes as CO
        m = CO.measure(ctx)
        sm = m["summary"]
        lines = [f"{sm['cards']} terms {sm['by_kind']}; bits (median, p95, max):"]
        for code in ("positional", "content", "cantor", "szudzik", "base_k", "hash"):
            v = sm.get(code) or {}
            lines.append(f"  {code:<11} {v.get('median', 0):>14.0f} {v.get('p95', 0):>16.0f} {v.get('max', 0):>18.0f}")
        fb = sm["formula_vs_built"]
        lines.append(f"formulas vs built integers: positional {fb['positional']['checked']} within "
                     f"{fb['positional']['max_bits_off']} bit, content {fb['content']['checked']} within "
                     f"{fb['content']['max_bits_off']} bit; pairing estimate vs built: {sm.get('model_cantor')}")
        lines.append(f"positional code within a bound: {sm['positional_under']}; larger than content for "
                     f"{sm['positional_over_content']:.0%}")
        for r in sorted(m["rows"], key=lambda r: -r["positional"])[:args.limit]:
            lines.append(f"  {r['card']}: {r['tokens']} tokens, depth {r['depth']}, largest constant "
                         f"{r['max_const']}: positional {r['positional']:.0f} bits, content {r['content']:.0f}")
        cli._out(args, sm, "\n".join(lines))
        return 0
    if args.action == "ledger":
        rows = GD.ledger(ctx.store)
        sets = Counter(e["set"] for e in rows)
        text = [f"{len(rows)} atoms ({', '.join(f'{k}: {v}' for k, v in sets.items())}); problems: "
                f"{GD.problems(rows) or 'none'}"]
        text += [f"  {e['index']:>4}  {e['prime']:>6}  {e['set']:<12} {e['atom']}" for e in rows[-args.limit:]]
        cli._out(args, rows, "\n".join(text))
        return 0
    vecs = []
    for q in args.cards:
        card = ctx.store.get(q)
        if card is None:
            print(f"error: no card {q!r}", file=sys.stderr)
            return 2
        v, why = GD.card_content(ctx, card)
        if v is None:
            print(f"error: {q}: {why}", file=sys.stderr)
            return 1
        vecs.append((q, v, why))
    if args.action == "vector":
        entries = GD.ledger(ctx.store)
        recs = {q: GD.stored(v, why, entries) for q, v, why in vecs}
        lines = [f"{q} ({r['read_from']}): {r['content']} -> vector {r.get('vector')} over basis version {r['basis']}"
                 + (f"; atoms not in the ledger: {r['missing_atoms']}" if r.get("missing_atoms") else "")
                 for q, r in recs.items()]
        cli._out(args, recs, "\n".join(lines))
        return 0
    if args.action in ("gcd", "lcm"):
        if len(vecs) != 2:
            print("error: gcd and lcm take two cards", file=sys.stderr)
            return 2
        a, b = vecs[0][1], vecs[1][1]
        r = GD.gcd(a, b) if args.action == "gcd" else GD.lcm(a, b)
        vec, _ = GD.to_vector(r, idx)
        cli._out(args, {"result": dict(r), "vector": vec, "a_divides_b": GD.divides(a, b), "b_divides_a": GD.divides(b, a)},
                 f"{args.action}: {dict(r)} (vector {vec}); {vecs[0][0]} divides {vecs[1][0]}: {GD.divides(a, b)}; "
                 f"the reverse: {GD.divides(b, a)}")
        return 0
    return 2


def cmd_distill(args) -> int:
    from .engines import egraph as E
    from .engines import search
    from .engines import values as V
    from .engines.exprs import parse, to_text
    cli = _cli()
    ctx = cli._ctx(args)
    rules, costs = E.rules_from_cards(ctx.store), search.op_costs(ctx.store)
    budget = {"max_iter": args.iterations, "max_nodes": args.nodes}
    if args.measure:
        r = E.measure(ctx)
        cli._out(args, r, f"{r['terms']} function-card terms through {r['rules']} equalities: {r['reduced']} reduced, "
                          f"{r['saturated']} saturated, {len(r['shared'])} canonical terms shared by several cards")
        return 0
    if not args.exprs or len(args.exprs) > 2:
        print("usage: cardmodel distill EXPR [EXPR2] | --measure", file=sys.stderr)
        return 2
    terms = [parse(e) for e in args.exprs]
    if len(terms) == 1:
        r = E.canonical(terms[0], rules, costs, **budget)
        cli._out(args, r, f"{to_text(r['term'])}   cost {r['cost']}   {r['hash']}\n"
                          f"{r['iterations']} iterations, {r['nodes']} nodes, {'saturated' if r['saturated'] else 'budget spent'}; "
                          f"equalities used: {', '.join(list(r['fired'])[:8]) or 'none'}")
        return 0
    r = E.equal(terms[0], terms[1], rules, **budget)
    w = E.witness(terms[0], terms[1], V.fresh_seed() if args.seed is None else args.seed, ops=ctx.ops)
    verdict = "equal" if r["equal"] else "not shown equal (within the budget; not a disproof)"
    cli._out(args, {**r, "witness": w}, f"{verdict}; witness {w['status']} on {w['checks']} inputs "
                                        f"(seed {w.get('seed')}); equalities used: {', '.join(list(r['fired'])[:8]) or 'none'}")
    return 0 if r["equal"] else 1


def cmd_sources(args) -> int:
    from .engines import sources as SO
    cli = _cli()
    ctx = cli._ctx(args)
    if args.action == "build":
        built = SO.build(ctx, seed=args.seed)
        counts = SO.write(ctx, built) if args.write else {k: len(built[k]) for k in ("definitions", "actions",
                                                                                     "transformations")}
        cli._out(args, counts, f"{'wrote' if args.write else 'built (not written; --write saves the packs)'}: "
                               f"{counts['definitions']} definitions, {counts['actions']} actions, "
                               f"{counts['transformations']} transformations")
        return 0
    r = SO.check(ctx)
    lines = [f"{r['status']}: {r['definitions']} definitions (coverage {r['coverage']}, canonical {r['canonical']}), "
             f"{r['actions']} actions, {r['transformations']} transformations, {r['methods']} methods"]
    lines += [f"  {p}" for p in r["problems"][:20]]
    cli._out(args, r, "\n".join(lines))
    return 1 if r["status"] == "fail" else 0


def cmd_tiers(args) -> int:
    from .engines import tiers as T
    from .engines.frontend_python import lift_source
    cli = _cli()
    ctx = cli._ctx(args)
    if args.action == "census":
        c = T.census(ctx)
        lines = [f"{c['claims']} claims, {c['proof']} at tier proof: {c['total']}"]
        lines += [f"  {reg:<16} {dict(sorted(t.items()))}" for reg, t in sorted(c["by_registry"].items())]
        if c["untiered_count"]:
            lines.append(f"  without a tier (CM46): {c['untiered'][:10]}")
        cli._out(args, c, "\n".join(lines))
        return 1 if c["untiered_count"] else 0
    card = ctx.store.get(f"algorithm/{args.algorithm}") if args.algorithm else None
    if card is None:
        print("usage: cardmodel tiers prove ALGORITHM (a card in cards/algorithm)", file=sys.stderr)
        return 2
    forms = [f for f in card.get("forms") or [] if f.get("lang") == "python" and f.get("code")]
    ref = next((f for f in forms if f["name"] == card.get("reference_form")), forms[0] if forms else None)
    out, lines = {}, []
    for f in forms:
        if f is ref:
            continue
        r = T.prove(ctx, card, ref, f)
        out[f["name"]] = r
        if r is None:
            lifted = [lf.ir for lf in lift_source(f["code"], ctx.ops) if lf.ok]
            why = T.shape(lifted[0]).get("why") if lifted else "it does not lift"
            lines.append(f"{f['name']}: no class sizes a witness ({why or 'the two forms differ in class'}); "
                         f"it stays sampled")
        elif r["status"] == "refuted":
            lines.append(f"{f['name']}: REFUTED at {r['at']}: {r['values']}")
        else:
            lines.append(f"{f['name']}: proved on {r['points']} points; " + "; ".join(r["theorems"]))
    cli._out(args, out, "\n".join(lines) or "no other Python forms")
    return 1 if any(r and r.get("status") == "refuted" for r in out.values()) else 0


def cmd_difficulty(args) -> int:
    from .engines import difficulty as D
    cli = _cli()
    ctx = cli._ctx(args)
    r = D.check(ctx)
    lines = [f"{r['status']}: {r['methods']} methods by the rank of what they decide {r['methods_by_rank']}; "
             f"{r['questions']} questions {r['questions_by_rank']}"]
    for m in sorted(ctx.store.cards("method"), key=lambda c: c.name):
        rk = m.get("rank") or {}
        lines.append(f"  {m.name:<20} {rk.get('decides', '?'):<10} serves: {rk.get('general', '')} "
                     f"({rk.get('general_rank', '?')})")
    lines.append("left open (the product says what it does instead):")
    for q in sorted(ctx.store.cards("question"), key=lambda c: (D.RANKS.index(c.get("rank")) if c.get("rank") in
                                                                   D.RANKS else 9, c.name)):
        if q.get("promise") != "answered":
            lines.append(f"  [{q.get('rank')}] {q.get('statement')}  -> {q.get('instead')}")
    lines += [f"  problem: {p}" for p in r["problems"]]
    cli._out(args, r, "\n".join(lines))
    return 1 if r["status"] == "fail" else 0


def cmd_symbolic(args) -> int:
    from .engines import values as V
    from .engines.exprs import to_text
    from .machine import symbolic as SY
    cli = _cli()
    ctx = cli._ctx(args)
    seed = V.fresh_seed() if args.seed is None else args.seed
    only = args.cards or None
    r = SY.check(ctx, args.isa, seed=seed, samples=args.samples, only=only)
    lines = [f"seed {seed}: {r['counts']} ({sum(c.get('runs', 0) for c in r['cards'].values())} runs against the "
             f"executable semantics)"]
    for name, row in r["cards"].items():
        if only or row["status"] not in ("pass",):
            lines.append(f"  {name}: {row['status']} {row.get('problems') or row.get('reason') or ''}")
        if only and name in r["results"]:
            res = r["results"][name]
            for k, t in res["state"].items():
                lines.append(f"      {k} = {to_text(t)}")
            for e in res["effects"]:
                g = f" if {to_text(e['guard'])}" if e["guard"] is not None else ""
                lines.append(f"      {e['op']}({', '.join(to_text(a) for a in e['args'])}){g}")
    r.pop("results", None)
    cli._out(args, r, "\n".join(lines))
    return 1 if r["status"] == "fail" else 0


def register(sub) -> None:
    from . import math_cli
    math_cli.register(sub)
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
    s = sub.add_parser("algebra", help="functions as algebra: canonical forms, GCD of functions, totals, Gödel numbers")
    s.add_argument("action", choices=["form", "gcd", "total", "scan", "godel"]); s.add_argument("targets", nargs="*")
    s.add_argument("--start", type=int, default=0); s.add_argument("--write", action="store_true")
    s.add_argument("--number"); s.add_argument("--global", dest="global_", action="store_true")
    s.set_defaults(fn=cmd_algebra)
    s = sub.add_parser("distill", help="equality saturation: a term's canonical form and semantic hash, or whether "
                                       "two terms are equal")
    s.add_argument("exprs", nargs="*"); s.add_argument("--measure", action="store_true")
    s.add_argument("--iterations", type=int, default=8); s.add_argument("--nodes", type=int, default=4000)
    s.add_argument("--seed", type=int); s.set_defaults(fn=cmd_distill)
    s = sub.add_parser("symbolic", help="instruction cards as terms: symbolic execution, checked against their "
                                        "executable semantics")
    s.add_argument("isa", nargs="?", default="lr35902"); s.add_argument("cards", nargs="*")
    s.add_argument("--samples", type=int, default=4); s.add_argument("--seed", type=int); s.set_defaults(fn=cmd_symbolic)
    s = sub.add_parser("difficulty", help="the arithmetical rank of every method and question: what the product "
                                          "can decide and what it must leave open (Gödel method W-15)")
    s.set_defaults(fn=cmd_difficulty)
    s = sub.add_parser("tiers", help="what each claim's evidence is worth: census, or prove an algorithm's forms "
                                     "by sized witnesses")
    s.add_argument("action", choices=["census", "prove"]); s.add_argument("algorithm", nargs="?")
    s.set_defaults(fn=cmd_tiers)
    s = sub.add_parser("sources", help="the four sources: definitions (truth), actions, transformations, methods")
    s.add_argument("action", choices=["check", "build"]); s.add_argument("--write", action="store_true")
    s.add_argument("--seed", type=int); s.set_defaults(fn=cmd_sources)
    s = sub.add_parser("godel", help="the expanding Gödel model: the prime ledger, content vectors, GCD and LCM")
    s.add_argument("action", choices=["ledger", "vector", "gcd", "lcm", "sizes"]); s.add_argument("cards", nargs="*")
    s.add_argument("--limit", type=int, default=20); s.set_defaults(fn=cmd_godel)
    from .game import cli as game_cli
    game_cli.register(sub)
    from .anyps5 import cli as anyps5_cli
    anyps5_cli.register(sub)
    from .unreal import cli as unreal_cli
    unreal_cli.register(sub)
    from .machine import cli as machine_cli
    machine_cli.register(sub)
    from .arcade import cli as arcade_cli
    arcade_cli.register(sub)


__all__ = ["register"]

