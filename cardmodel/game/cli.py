"""cardmodel game ... — the Vector Counter System from the command line.

  check                     every design_law card on the neutral exchange
  matrix [--distance D]     the exact equilibrium of an exchange (row mix, value, certificate)
  sensitivity               which number on which card most changes the game
  balance [--budget N]      seeded local search over move numbers until the design laws hold
  duel A B [--trace]        two AIs (random, greedy, equilibrium, reader, habit)
  tournament [--duels N]    every AI against every other
  play [--vs reader]        you against an AI, one exchange at a time
  world [--impact]          the systemic world: ticks, events, causes, the action that changed the most
  kernel --lang L           the combat kernel (stdlib/combat.card) in any language card (cpp for Unreal)
"""
from __future__ import annotations

import sys


def _game(ctx, args):
    from .combat import Combat
    return Combat(ctx, getattr(args, "a_fighter", None) or "warden", getattr(args, "b_fighter", None) or "warden")


def cmd(args) -> int:
    from .. import cli
    ctx = cli._ctx(args)
    act = args.action
    if act == "kernel":
        from ..lang.compile import compile_file
        from ..lang.run import emit
        from ..kernel import paths
        mod = compile_file(paths.home() / "stdlib" / "combat.card", ctx.ops, ctx.store)
        code = emit(ctx, mod, args.lang or "cpp")
        if args.out:
            open(args.out, "w", encoding="utf-8").write(code)
            print(f"wrote {args.out}")
        else:
            print(code)
        return 0
    if act == "world":
        from . import world as W
        r = W.run(ctx)
        lines = []
        for h in r["history"]:
            burning = ", ".join(f"{f[1]}({f[2]})" for f in h["state"] if f[0] == "burning") or "-"
            ash = ", ".join(f[1] for f in h["state"] if f[0] == "ash") or "-"
            guards = ", ".join(f"{f[1]}@{f[2]}" for f in h["state"] if f[0] == "guard")
            act_s = ", ".join(f"{a} {b}" for a, b in h["actions"]) or ""
            lines.append(f"  t{h['tick']:<2} {('player: ' + act_s) if act_s else '':<24} burning {burning:<34} ash {ash:<18} {guards}")
        final = [f for f in r["final"] if f[0] in ("ash", "suspects", "standing", "alert")]
        lines.append("  end: " + ", ".join(W._fmt(f) for f in final))
        fact = tuple(args.explain.replace("(", " ").replace(")", " ").replace(",", " ").split()) if args.explain \
            else ("ash", "tavern")
        lines.append(f"why {W._fmt(fact)}?")
        lines += ["  " + x for x in W.explain(r, fact, r["ticks"])]
        if args.impact:
            lines.append("which action changed the world most (counterfactual: run without it):")
            for x in W.impact(ctx):
                lines.append(f"  {x['action']}: {x['changed']} facts differ; only with it: {', '.join(x['only_with_it'][:6])}")
        print("\n".join(lines))
        return 0
    from . import ai
    from . import analysis as A
    g = _game(ctx, args)
    if act == "check":
        r = A.check(g)
        lines = [f"{r['passed']} of {r['total']} design laws hold on the neutral exchange ({r['moves']} options); "
                 f"equilibrium value {r['equilibrium']['value']} (certificate {'ok' if r['equilibrium']['certificate'] else 'FAILED'})"]
        for name, law in r["laws"].items():
            detail = {k: v for k, v in law.items() if k not in ("statement", "ok", "answers", "alive_in")}
            lines.append(f"  {'ok  ' if law['ok'] else 'FAIL'} {name}: {detail}")
        lines.append("  equilibrium mix: " + ", ".join(f"{k} {float(eval(v)):.3f}" for k, v in r["equilibrium"]["row_mix"].items()))  # noqa: S307
        cli._out(args, r, "\n".join(lines))
        return 0 if r["passed"] == r["total"] else 1
    if act == "matrix":
        from dataclasses import replace
        st = replace(g.start(), distance=args.distance, advantage=args.advantage)
        rows, cols, M = A.matrix(g, st)
        sol = A.solve(M)
        mix = sorted(((rows[i], float(x)) for i, x in enumerate(sol["p"]) if x > 0), key=lambda kv: -kv[1])
        lines = [f"distance {args.distance}, advantage {args.advantage:+d}: {len(rows)}x{len(cols)} exchange, value "
                 f"{float(sol['value']):.3f} (exact {sol['value']}), certificate {'ok' if sol['certificate']['ok'] else 'FAILED'}",
                 "  mix: " + ", ".join(f"{n} {p:.3f}" for n, p in mix)]
        cli._out(args, {"value": str(sol["value"]), "mix": dict(mix)}, "\n".join(lines))
        return 0
    if act == "sensitivity":
        r = A.sensitivity(g)
        lines = [f"{r['perturbations']} single-number changes; the ones that move the structure most "
                 "(how much the current equilibrium loses afterwards, per exchange):"]
        for x in r["top"]:
            lines.append(f"  {x['card']}.{x['param']} {x['from']} -> {x['to']}: exploitable by {x['exploitability']} "
                         f"via {x['exploited_by']}")
        cli._out(args, r, "\n".join(lines))
        return 0
    if act == "balance":
        r = A.balance(g, budget=args.budget, seed=args.seed or 0, log=print)
        lines = [f"score {r['start']} -> {r['end']} after {r['tried']} tries (failed laws, dead options, -support)"]
        for c in r["accepted"]:
            lines.append(f"  {c['card']}.{c['param']}: {c['from']} -> {c['to']}")
        if args.apply and r["accepted"]:
            layer = cli._layer(ctx, args)
            for c in {c["card"] for c in r["accepted"]}:
                card = dict(ctx.store.get(c))
                card.update({k: v for k, v in g.moves[c.split('/', 1)[1]].items() if k in card or k in A.TUNABLE.get(card["kind"], ())})
                ctx.store.save(card, layer=layer)
            lines.append(f"applied to the {layer} layer (versioned)")
        cli._out(args, r | {"report": None}, "\n".join(lines))
        return 0
    if act == "duel":
        r = ai.duel(g, ai.AGENTS[args.agents[0]](), ai.AGENTS[args.agents[1]](), seed=args.seed or 0, trace=True)
        lines = []
        for e in r["log"]:
            lines.append(f"  #{e['exchange']:<2} {e['a']:>15} vs {e['b']:<15} hp {e['hp'][0]:>4}/{e['hp'][1]:<4} "
                         f"adv {e['advantage']:+3d} | " + "; ".join(e["text"]))
        lines.append(f"winner: {r['winner']} ({args.agents[0]} is a, {args.agents[1]} is b) after {r['exchanges']} exchanges")
        cli._out(args, r, "\n".join(lines if args.trace else lines[-1:]))
        return 0
    if act == "tournament":
        names = args.agents or ["random", "greedy", "equilibrium", "reader", "habit"]
        r = ai.tournament(g, names, duels=args.duels, seed=args.seed or 0)
        lines = [f"{args.duels} duels per pair (sides alternate), seed {r['seed']}:"]
        for a, sc in r["score"].items():
            lines.append(f"  {a:<12} {sc:>5}   " + "  ".join(f"vs {b}: {w}-{l}" + (f"-{d}" if d else "")
                                                         for b, (w, l, d) in r["table"][a].items() if b != a))
        cli._out(args, r, "\n".join(lines))
        return 0
    if act == "play":
        return play(g, args)
    print(f"unknown game action {act}", file=sys.stderr)
    return 2


def play(g, args) -> int:
    import random
    from . import ai
    rng = random.Random(args.seed or 0)
    opponent = ai.AGENTS[args.vs]()
    state = g.start()
    print(f"You are the warden (a), against the {args.vs} AI (b). Type a move name (or its number), ? for details, q to quit.")
    while not g.over(state):
        opts = g.options(state, "a")
        print(f"\n#{state.exchange}  you hp {state.a.hp} posture {state.a.posture} stamina {state.a.stamina} "
              f"bank {state.a.bank} [{state.a.stance}]   |   them hp {state.b.hp} posture {state.b.posture} "
              f"[{state.b.stance}]   distance {state.distance}   advantage {state.advantage:+d}")
        print("  " + "  ".join(f"{i}:{m}" for i, m in enumerate(opts)))
        try:
            pick = input("move> ").strip()
        except EOFError:
            return 0
        if pick in ("q", "quit"):
            return 0
        if pick.startswith("?"):
            name = pick[1:].strip() or opts[0]
            mv = g.moves.get(name, {})
            print(f"  {name}: {mv.get('statement', '')}")
            continue
        move = opts[int(pick)] if pick.isdigit() and int(pick) < len(opts) else pick
        if move not in opts:
            print("  not allowed from your stance")
            continue
        them = opponent.choose(g, state, "b", rng)
        state2, ev = g.resolve(state, move, them)
        opponent.observe(g, them, move)
        print(f"  you: {move}   them: {them}")
        for t in ev.text:
            print("   - " + t)
        if isinstance(opponent, ai.ReaderAgent) and opponent.weights:
            print("   (the reader thinks you lean on: " + ", ".join(f"{k}" for k, _ in opponent.focus()) + ")")
        state = state2
    print("you win" if state.b.hp <= 0 < state.a.hp else "you lose" if state.a.hp <= 0 < state.b.hp else "draw")
    return 0


def register(sub) -> None:
    s = sub.add_parser("game", help="the Vector Counter System: design laws, equilibria, AIs, play, world, kernel")
    s.add_argument("action", choices=["check", "matrix", "sensitivity", "balance", "duel", "tournament", "play",
                                      "world", "kernel"])
    s.add_argument("agents", nargs="*", help="duel: two agent names; tournament: optional subset")
    s.add_argument("--seed", type=int); s.add_argument("--trace", action="store_true")
    s.add_argument("--duels", type=int, default=6); s.add_argument("--budget", type=int, default=120)
    s.add_argument("--apply", action="store_true"); s.add_argument("--global", dest="global_", action="store_true")
    s.add_argument("--distance", type=int, default=1); s.add_argument("--advantage", type=int, default=0)
    s.add_argument("--vs", default="reader"); s.add_argument("--lang"); s.add_argument("--out")
    s.add_argument("--explain"); s.add_argument("--impact", action="store_true")
    s.add_argument("--a-fighter", dest="a_fighter"); s.add_argument("--b-fighter", dest="b_fighter")
    s.set_defaults(fn=cmd)


__all__ = ["register"]
