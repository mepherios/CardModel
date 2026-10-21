"""cardmodel anyps5 ... — AnyPS5 (a PS5 executable relinker and its system libraries) as cards.

  scan PATH [--parity] [--save] [--global]   read a checkout (read-only) into cards; --parity also runs AnyPS5's
                                             own tools/progress.py --json and compares, name by name
  cover [--write FILE]                       the real coverage: the badge, the ladder, every gap by cause
  gaps [--cause C] [--library L] [--kind K]  list gap items with their cause and file:line
  why NAME                                   an export's or debt entry's gaps, causes and the proof of each
  blocks                                     pending exports ranked by the implemented exports that reach them
  witness PATH [--semantics N] [--seed S]    compile AnyPS5's own code next to the model's derived semantics
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _progress_json(root: Path) -> dict | None:
    """AnyPS5's own counting, from its own tool (it only reads the tree and prints JSON)."""
    from ..kernel import resources
    tool = root / "tools" / "progress.py"
    if not tool.is_file():
        return None
    p = resources.run([sys.executable, "-B", "-I", str(tool), "--json"], timeout=300, heavy=False,
                      cwd=root, stdin=subprocess.DEVNULL)
    if p.returncode != 0:
        raise RuntimeError(f"tools/progress.py failed: {(p.stderr or '')[-400:]}")
    return json.loads(p.stdout)


def _name(ctx, text: str) -> tuple[str, str] | None:
    """Resolve NAME to (registry, card name): an export (library.definition or a unique symbol) or a debt entry."""
    st = ctx.store
    for reg in ("anyps5_export", "anyps5_debt"):
        if st.get(f"{reg}/{text}") is not None:
            return reg, text
    from .cards import symbol_of
    hits = [c.name for c in st.cards("anyps5_export") if c.get("kind") == "function"
            and (symbol_of(c) == text or c.name.endswith("." + text))]
    return ("anyps5_export", hits[0]) if len(hits) == 1 else None


def cmd(args) -> int:
    from .. import cli
    ctx = cli._ctx(args)
    act = args.action
    if act == "scan":
        from . import cards as C
        from . import scan as S
        root = Path(args.target or ".").expanduser()
        sc = S.Scan(root)
        par = None
        if args.parity:
            prog = _progress_json(sc.root)
            par = S.parity(sc, prog) if prog else None
        built = C.build(sc, par)
        lines = [f"{sc.root}: {len(sc.libraries)} libraries, {sum(len(l.defs) for l in sc.libraries)} definitions, "
                 f"{len(sc.debt)} debt entries, {len(built['anyps5_instruction'])} shader instructions",
                 f"libraries badge (AnyPS5's rule): {sc.badge()['done']}/{sc.badge()['total']} = {sc.badge()['percent']}%",
                 f"shader badge: {sc.shader_badge().get('done')}/{sc.shader_badge().get('total')} = "
                 f"{sc.shader_badge().get('percent')}%"]
        if par is not None:
            lines.append(f"parity with AnyPS5's tools/progress.py: {'agrees' if par['agree'] else 'DIFFERS'} "
                         f"({len(par['mismatches'])} mismatches)")
        if args.save:
            layer = cli._layer(ctx, args)
            counts = C.save(ctx.store, built, layer=layer)
            lines.append(f"saved to the {layer} layer: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
        cli._out(args, {"badge": sc.badge(), "shader_badge": sc.shader_badge(), "parity": par,
                        "sha256": sc.sha256}, "\n".join(lines))
        return 0 if par is None or par["agree"] else 1
    if act == "witness":
        from . import witness as W
        root = Path(args.target or ".").expanduser()
        names = args.semantics.split(",") if args.semantics else None
        res = W.run(ctx, root, names=names, seed=args.seed, samples=args.samples, save=not args.no_save,
                    layer=cli._layer(ctx, args))
        lines = []
        for r in res:
            n = sum(c["inputs"] for c in r["checks"])
            lines.append(f"{r['name']:<24} {r['status']:<9} {n} calls, seed {r['seed']}"
                         + (f": {r['reason'][:300]}" if r.get("reason") else ""))
            for c in r["checks"]:
                if not c["ok"] or c["expect"] == "differs":
                    lines.append(f"    {'ok ' if c['ok'] else 'BAD'} {c['expect']:<7} {c.get('export') or c.get('note')}: "
                                 f"{c['disagree']} of {c['inputs']} differ, e.g. {c['examples'][:2]}")
        cli._out(args, res, "\n".join(lines))
        return 0 if all(r["status"] == "agree" for r in res) else 1
    from . import classify as K
    from . import cover as V
    cls = K.classify(ctx)
    if not cls.exports:
        print("no anyps5 cards: run `cardmodel anyps5 scan PATH --save` first", file=sys.stderr)
        return 2
    if act == "cover":
        rep = V.report(ctx, cls)
        md = V.markdown(rep)
        if args.write:
            Path(args.write).write_text(md, encoding="utf-8")
        cli._out(args, rep, md if not args.write else f"wrote {args.write}")
        return 0 if rep["unclassified"] == 0 else 1
    if act == "gaps":
        rows = []
        for e, k, c in sorted(cls.rel("cause")):
            card = cls.exports[e]
            if (args.cause and c != args.cause) or (args.library and card["library"] != args.library) or \
                    (args.kind and k != args.kind):
                continue
            rows.append({"export": e, "kind": k, "cause": c, "at": V._at(card)})
        if args.debt:
            rows = [{"debt": d, "cause": c, "at": f"{cls.debt[d]['provenance']['file']}:{cls.debt[d]['provenance']['line']}"}
                    for d, c in sorted(cls.rel("debt_cause")) if not args.cause or c == args.cause]
        text = "\n".join(f"{r.get('export') or r.get('debt'):<70} {r.get('kind', 'debt'):<13} {r['cause']:<30} {r['at']}"
                         for r in rows[:args.limit])
        text += f"\n{len(rows)} item(s)" + (f", first {args.limit} shown" if len(rows) > args.limit else "")
        cli._out(args, rows, text)
        return 0
    if act == "why":
        hit = _name(ctx, args.target or "")
        if hit is None:
            print(f"error: no unique export or debt entry named {args.target!r}", file=sys.stderr)
            return 2
        reg, name = hit
        causes = {c.name: c for c in ctx.store.cards("anyps5_cause")}
        lines = []
        if reg == "anyps5_debt":
            d = cls.debt[name]
            lines.append(f"{name} ({d['provenance']['file']}:{d['provenance']['line']}): {d.get('text', '')[:300]}")
            for dd, c in cls.rel("debt_cause"):
                if dd == name:
                    lines += [f"cause: {c} ({causes[c]['class']}); closes with: {causes[c]['closes_with']}",
                              f"cues: {cls.cue_hits.get(name)}", cls.why("debt_cause", (name, c))]
        else:
            card = cls.exports.get(name) or ctx.store.get(f"anyps5_export/{name}")
            lines.append(f"{name}: {card['state']} at {V._at(card)}")
            mine = sorted((k, c) for e, k, c in cls.rel("cause") if e == name)
            for w in ctx.store.cards("anyps5_witness"):
                r = (w.get("exports") or {}).get(name)
                if r:
                    lines.append(f"witness anyps5_witness/{w.name}: {r['checks']} calls of AnyPS5's code, "
                                 f"{'all agree' if r['agree'] else str(r['disagree']) + ' disagree'} with "
                                 f"{w['program']} (seed {w['seed']}, {w.get('toolchain')})")
            if not mine:
                lines.append("complete by AnyPS5's own records" +
                             (" and witnessed against derived semantics" if cls.model.holds("witnessed", (name,)) else ""))
                lines.append(cls.why("complete", (name,)))
            for k, c in mine:
                lines += [f"gap {k}: cause {c} ({causes[c]['class']}); closes with: {causes[c]['closes_with']}",
                          cls.why("cause", (name, k, c))]
        cli._out(args, {"name": name, "registry": reg}, "\n".join(lines))
        return 0
    if act == "blocks":
        rep = V.report(ctx, cls)
        lines = ["pending exports that implemented exports reach (closing one completes its callers' paths):"]
        lines += [f"  {b['export']:<70} blocks {b['blocks']}" for b in rep["blocks"]]
        if rep["unblocks"]:
            lines.append("pending exports whose GetSize waits for them:")
            lines += [f"  {b['export']:<70} unblocks {b['unblocks']}" for b in rep["unblocks"]]
        cli._out(args, {"blocks": rep["blocks"], "unblocks": rep["unblocks"]}, "\n".join(lines))
        return 0
    return 2


def register(sub) -> None:
    s = sub.add_parser("anyps5", help="AnyPS5 as cards: scan a checkout, the real coverage, every gap's cause, witnesses")
    s.add_argument("action", choices=["scan", "cover", "gaps", "why", "blocks", "witness"])
    s.add_argument("target", nargs="?", help="scan / witness: the AnyPS5 checkout; why: an export or debt entry")
    s.add_argument("--save", action="store_true"); s.add_argument("--parity", action="store_true")
    s.add_argument("--global", dest="global_", action="store_true"); s.add_argument("--write")
    s.add_argument("--cause"); s.add_argument("--library"); s.add_argument("--kind")
    s.add_argument("--debt", action="store_true", help="gaps: list debt entries instead of exports")
    s.add_argument("--limit", type=int, default=60); s.add_argument("--semantics")
    s.add_argument("--seed", type=int); s.add_argument("--samples", type=int, default=300)
    s.add_argument("--no-save", action="store_true")
    s.set_defaults(fn=cmd)


__all__ = ["cmd", "register"]
