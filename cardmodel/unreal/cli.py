"""cardmodel unreal ... — Unreal Engine's math as cards (docs/UNREAL.md, law CM49).

  locate [--engine P]                 the engine install, its version, clang, the Core library
  scan [--engine P] [--save] [--seed S] [--no-witness] [--reuse]
                                      build the units, lift every function, distill, witness against the engine's
                                      compiled code; --save writes the cards (and appends the engine's atoms);
                                      --reuse starts from the cached scan
  witness [--seed S] [--missing] [NAME ...]   witness again (all lifted functions, those NAME matches, or
                                      --missing: those with no verdict that settles them)
  show NAME                           a function: its terms, canonical form, Gödel numbers, use, witness
  uses                                the uses: members, lifted, and the logic they share (GCD)
  gcd A B                             the common logic of two functions (GCD of their Gödel content), and the LCM
  emit NAME [--lang L,...] [--check]  the function's definition emitted through the language cards (one function
                                      per output); --check runs each language against the definition
  cover [--write FILE]                the coverage: lifted, witnessed, outside, every gap by cause
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


def _engine(args):
    from . import engine as E
    try:
        return E.locate(args.engine)
    except E.NotFound as exc:
        print(f"unavailable: {exc}", file=sys.stderr)
        return None


def _state(ctx, eng):
    from . import engine as E
    return E.cache(ctx.state_root, eng)


def _load(ctx, eng):
    from . import scan as S
    cache = _state(ctx, eng)
    sc = S.load(cache)
    if sc is None:
        print("no scan yet: run `cardmodel unreal scan`", file=sys.stderr)
    return cache, sc


def _report_path(cache: Path) -> Path:
    return cache / "report.json"


# the engine's own names for its template instantiations (Math/MathFwd.h), so `show FVector.CrossProduct` works
ALIASES = {"FVector": "TVector<double>", "FVector3d": "TVector<double>", "FVector3f": "TVector<float>",
           "FVector2D": "TVector2<double>", "FVector2d": "TVector2<double>", "FVector2f": "TVector2<float>",
           "FVector4": "TVector4<double>", "FVector4d": "TVector4<double>", "FVector4f": "TVector4<float>",
           "FQuat": "TQuat<double>", "FQuat4d": "TQuat<double>", "FQuat4f": "TQuat<float>",
           "FRotator": "TRotator<double>", "FRotator3d": "TRotator<double>", "FRotator3f": "TRotator<float>",
           "FMatrix": "TMatrix<double>", "FMatrix44d": "TMatrix<double>", "FMatrix44f": "TMatrix<float>",
           "FTransform": "TTransform<double>", "FTransform3d": "TTransform<double>",
           "FTransform3f": "TTransform<float>", "FBox": "TBox<double>", "FBox3d": "TBox<double>",
           "FBox3f": "TBox<float>", "FBox2D": "TBox2<double>", "FPlane": "TPlane<double>",
           "FPlane4f": "TPlane<float>", "FSphere": "TSphere<double>", "FSphere3f": "TSphere<float>",
           "FRay": "TRay<double>", "FRay3f": "TRay<float>"}


def _find(sc: dict, text: str) -> list[dict]:
    from . import cards as K
    hits = [f for f in sc["functions"] if K.slug(f) == text or f["qual"] == text]
    if not hits:
        q = text if "::" in text else text.replace(".", "::")
        head, sep, rest = q.partition("::")
        q = ALIASES.get(head, head) + sep + rest
        hits = [f for f in sc["functions"] if text in K.slug(f) or text in f["qual"] or q in f["qual"]]
    return hits


def cmd(args) -> int:
    from .. import cli
    ctx = cli._ctx(args)
    act = args.action
    eng = _engine(args)
    if eng is None:
        return 1
    if act == "locate":
        from . import engine as E
        clang, why = E.clang()
        lib = eng.core_library()
        data = {"version": eng.tag, "changelist": eng.changelist, "branch": eng.version.get("BranchName"),
                "root": str(eng.root), "clang": clang or why, "core_library": str(lib) if lib else None,
                "headers": len(eng.headers()), "sources": len(eng.sources())}
        cli._out(args, data, "\n".join(f"{k}: {v}" for k, v in data.items()))
        return 0
    if act == "scan":
        return _scan(ctx, args, eng)
    cache, sc = _load(ctx, eng)
    if sc is None:
        return 1
    rep = json.loads(_report_path(cache).read_text(encoding="utf-8")) if _report_path(cache).is_file() else {}
    if act == "witness":
        return _witness(ctx, args, eng, cache, sc, rep)
    if act == "show":
        if not args.names:
            print("usage: cardmodel unreal show NAME", file=sys.stderr)
            return 2
        return _show(args, sc, rep, args.names[0])
    if act == "uses":
        uses = rep.get("distill", {}).get("uses") or {}
        rows = sorted(uses.items(), key=lambda kv: -len(kv[1]["members"]))
        text = [f"{'use':24s} {'functions':>9s} {'lifted':>7s}  GCD of all | the logic most share (half or more)"]

        def show(v):
            return ", ".join(f"{a.split('/', 1)[1]}^{e}" if e > 1 else a.split("/", 1)[1]
                             for a, e in sorted(v.items())) or "-"
        for u, info in rows:
            text.append(f"{u:24s} {len(info['members']):9d} {info['lifted']:7d}  {show(info['gcd'])} | "
                        f"{show(info.get('common') or {})}")
        cli._out(args, {u: {k: v for k, v in i.items() if k != "members"} for u, i in rows}, "\n".join(text))
        return 0
    if act == "gcd":
        return _gcd(args, sc, rep)
    if act == "emit":
        if not args.names:
            print("usage: cardmodel unreal emit NAME [--lang L,...] [--check]", file=sys.stderr)
            return 2
        return _emit(ctx, args, sc, args.names[0])
    if act == "cover":
        text = coverage_md(sc, rep)
        if args.write:
            Path(args.write).write_text(text, encoding="utf-8")
            print(f"wrote {args.write}")
        else:
            print(text)
        return 0
    return 2


def _scan(ctx, args, eng) -> int:
    from ..engines import godel as G
    from ..engines import values as V
    from . import cards as K
    from . import distill as D
    from . import engine as E
    from . import scan as S
    from . import witness as W
    cache = _state(ctx, eng)
    seed = V.fresh_seed() if args.seed is None else args.seed
    print(f"Unreal Engine {eng.tag} (changelist {eng.changelist}); seed {seed}")
    sc = S.load(cache) if args.reuse else None
    if sc is None:
        try:
            sc = S.run(eng, cache, log=lambda m: print(m, flush=True))
        except E.NotFound as exc:
            print(f"unavailable: {exc}", file=sys.stderr)
            return 1
    print(f"scan: {sc['counts']} in {sc['seconds']} s")
    idx = G.index_of(ctx.store)
    dist = D.run(sc, idx)
    verdicts = {}
    old = _report_path(cache)
    if args.no_witness and args.reuse and old.is_file():          # keep the verdicts of the last witness
        prev = json.loads(old.read_text(encoding="utf-8"))
        verdicts = prev.get("witness") or {}
        seed = prev.get("seed", seed)
    if not args.no_witness:
        verdicts = W.run_engine(eng, cache, sc["functions"], seed, log=lambda m: print(m, flush=True))
        print(f"witness: {dict(Counter(v['status'] for v in verdicts.values()))}")
    rep = {"seed": seed, "engine": sc["engine"], "counts": sc["counts"],
           "distill": {"identities": dist["identities"], "uses": dist["uses"],
                       "carry": {"image": len(dist["carry"]["image"]), "gap": len(dist["carry"]["gap"]),
                                 "preserves_gcd": dist["carry"]["preserves_gcd"]},
                       "rows": {k: {kk: vv for kk, vv in r.items() if kk not in ("outputs",)}
                                for k, r in dist["rows"].items()}},
           "witness": verdicts, "new_atoms": D.new_atoms(sc, idx)}
    _report_path(cache).write_text(json.dumps(rep, separators=(",", ":"), default=str), encoding="utf-8")
    if rep["new_atoms"]:
        print(f"atoms the ledger lacks (run tools/seed_unreal.py, then scan again): {rep['new_atoms']}")
    if args.save:
        if rep["new_atoms"]:
            print("not saving: the definitions would use atoms outside the ledger", file=sys.stderr)
            return 1
        built = K.build(sc, dist, verdicts, idx, G.ledger(ctx.store))
        print(f"saved: {K.write(ctx, built, sc)}")
    return 0


def _witness(ctx, args, eng, cache, sc, rep) -> int:
    from ..engines import values as V
    from . import witness as W
    seed = V.fresh_seed() if args.seed is None else args.seed
    only = None
    if args.names:
        only = {f["key"] for n in args.names for f in _find(sc, n)}
    elif args.missing:
        done = rep.get("witness") or {}
        only = {f["key"] for f in sc["functions"] if f["status"] == "lifted"
                and (f["key"] not in done or done[f["key"]]["status"] in ("unavailable", "error"))}
        print(f"witnessing {len(only)} functions with no verdict that settles them")
    v = W.run_engine(eng, cache, sc["functions"], seed, only=only, log=lambda m: print(m, flush=True))
    print(f"seed {seed}: {dict(Counter(x['status'] for x in v.values()))}")
    for k, x in v.items():
        if x["status"] == "refuted":
            f = next(f for f in sc["functions"] if f["key"] == k)
            print(f"  refuted {f['qual']} ({f['file']}:{f['line']}): {x.get('output')} engine {x.get('engine')} "
                  f"term {x.get('term')} at {x.get('inputs')}")
    if rep and (only is None or args.missing):
        rep["witness"] = v if only is None else {**(rep.get("witness") or {}), **v}
        rep["seed"] = rep.get("seed", seed) if args.missing else seed
        _report_path(cache).write_text(json.dumps(rep, separators=(",", ":"), default=str), encoding="utf-8")
    return 1 if any(x["status"] == "refuted" for x in v.values()) else 0


def _show(args, sc, rep, name) -> int:
    from .. import cli
    from . import cards as K
    hits = _find(sc, name)
    if not hits:
        print(f"no engine function matches {name!r}", file=sys.stderr)
        return 2
    f = hits[0]
    r = (rep.get("distill", {}).get("rows") or {}).get(f["key"]) or {}
    v = (rep.get("witness") or {}).get(f["key"])
    lines = [f"{f['qual']}  [{f['kind']}]  {f['type']}", f"  {f['file']}:{f['line']}   card unreal_math/{K.slug(f)}",
             f"  status: {f['status']}" + (f" ({f.get('cause')}: {f.get('detail')})" if f["status"] != "lifted" else ""),
             f"  use: {r.get('use')}"]
    if f["status"] == "lifted":
        lines.append(f"  inputs: {', '.join(n for n, _k in f['inputs'])}")
        for o in f["outputs"]:
            lines.append(f"  {o['name']} = {json.dumps(o['term'])[:400]}")
        lines.append(f"  hash {r.get('hash')}   content {r.get('content')}")
        lines.append(f"  Gödel content integer: {r.get('digits')} digits (stored as its sparse vector, CM45)")
        lines.append(f"  witness: {v}")
        if len(hits) > 1:
            lines.append(f"  ({len(hits) - 1} more match: {', '.join(h['qual'] for h in hits[1:4])} ...)")
    cli._out(args, {"function": f, "distilled": r, "witness": v}, "\n".join(lines))
    return 0


def _gcd(args, sc, rep) -> int:
    from .. import cli
    from ..engines import godel as G
    if len(args.names) != 2:
        print("usage: cardmodel unreal gcd A B", file=sys.stderr)
        return 2
    rows = rep.get("distill", {}).get("rows") or {}
    vecs = []
    for n in args.names:
        hits = [f for f in _find(sc, n) if (rows.get(f["key"]) or {}).get("content") is not None]
        if not hits:
            print(f"no lifted engine function matches {n!r}", file=sys.stderr)
            return 2
        vecs.append((hits[0]["qual"], Counter(rows[hits[0]["key"]]["content"])))
    (qa, a), (qb, b) = vecs
    g, lc = G.gcd(a, b), G.lcm(a, b)
    data = {"a": qa, "b": qb, "gcd": dict(g), "lcm": dict(lc), "a_divides_b": G.divides(a, b),
            "b_divides_a": G.divides(b, a)}
    cli._out(args, data, f"gcd({qa}, {qb}) = {dict(g)}\nlcm = {dict(lc)}\n{qa} divides {qb}: {G.divides(a, b)}; "
                         f"the reverse: {G.divides(b, a)}")
    return 0


IR_TYPES = {"f64": "float", "f32": "float", "b": "bool"}


def module_of(f: dict) -> dict:
    """A lifted function as a card-IR module: one function per output, its inputs by position."""
    import re as _re

    from ..engines import realnorm as RN
    from .lift import undefined
    pos = {nm: f"x{i}" for i, (nm, _k) in enumerate(f["inputs"])}
    params = [{"name": f"x{i}", "type": IR_TYPES.get(k, "int")} for i, (_nm, k) in enumerate(f["inputs"])]
    base = _re.sub(r"[^A-Za-z0-9_]", "_", f["name"]).strip("_") or "fn"
    memo: dict = {}

    def defined(t):
        # where C++ is undefined any value refines it: the emitted code takes the IF_EXPR's other side
        if not isinstance(t, list):
            return t
        hit = memo.get(id(t))
        if hit is not None and hit[0] is t:
            return hit[1]
        if t and t[0] == "IF_EXPR" and undefined(t[3]):
            r = defined(t[2])
        elif t and t[0] == "IF_EXPR" and undefined(t[2]):
            r = defined(t[3])
        else:
            r = [defined(x) for x in t]
        memo[id(t)] = (t, r)
        return r
    fns = []
    for j, o in enumerate(f["outputs"]):
        suffix = _re.sub(r"[^A-Za-z0-9_]", "_", o["name"].replace("return", "r")).strip("_")
        fns.append({"name": f"ue_{base}_{suffix}", "params": params, "returns": IR_TYPES.get(o["kind"], "int"),
                    "locals": {}, "body": [{"k": "return", "value": defined(RN.rename(o["term"], pos))}]})
    return {"functions": fns, "entry": fns[0]["name"] if fns else None}


def _emit(ctx, args, sc, name) -> int:
    from ..engines import values as V
    from ..engines.codegen import EmitGap, emit_module
    from ..engines.translate import verify_function
    hits = [f for f in _find(sc, name) if f["status"] == "lifted" and f.get("outputs")]
    if not hits:
        print(f"no lifted engine function matches {name!r}", file=sys.stderr)
        return 2
    f = hits[0]
    mod = module_of(f)
    langs = (args.lang or "python").split(",")
    if not args.check:
        for lang in langs:
            try:
                print(emit_module(ctx.store, ctx.ops, lang, mod))
            except EmitGap as exc:
                print(f"{lang}: gap: {exc}", file=sys.stderr)
                return 1
        return 0
    seed = V.fresh_seed() if args.seed is None else args.seed
    gens = [{"float": [-100.0, 100.0]} if t["type"] == "float" else {"bool": True} if t["type"] == "bool"
            else {"int": [0, 1000]} for t in mod["functions"][0]["params"]]
    print(f"{f['qual']} ({f['file']}:{f['line']}): {len(mod['functions'])} outputs; seed {seed}")
    worst = 0
    for fn in mod["functions"]:
        card = {"ir": {**mod, "entry": fn["name"]}, "generators": gens, "vectors": [],
                "forms": [{"name": l, "lang": l, "generated": True} for l in langs]}
        r = verify_function(ctx, card, langs=langs, seed=seed, samples=16)
        cells = {l: x["status"] for l, x in r["languages"].items()}
        worst = max(worst, sum(1 for x in cells.values() if x in ("fail", "error")))
        print(f"  {fn['name']}: {cells}")
    return 1 if worst else 0


def coverage_md(sc: dict, rep: dict) -> str:
    """The coverage report (`cardmodel unreal cover`; kept local like the cards it counts)."""
    fns = sc["functions"]
    c = Counter(f["status"] for f in fns)
    universe = c["lifted"] + c["gap"]
    verd = rep.get("witness") or {}
    w = Counter(v["status"] for v in verd.values())
    witnessed = w["witnessed"] + w["witnessed_ulp"]
    truth_build = sum(1 for v in verd.values() if v.get("build") == "truth" and v["status"].startswith("witnessed"))
    lines = ["# Unreal Engine's math as cards: coverage", "",
             f"Generated by `cardmodel unreal cover` from the scan of Unreal Engine "
             f"{sc['engine']['version']} (changelist {sc['engine']['changelist']}); witness seed {rep.get('seed')}.",
             "", "| | functions |", "|---|---:|",
             f"| read from the engine's math files | {len(fns)} |",
             f"| outside the math universe (strings, archives, layouts, time) | {c['outside']} |",
             f"| math universe | {universe} |",
             f"| lifted to terms | {c['lifted']} ({c['lifted'] / universe:.1%}) |" if universe else "| lifted | 0 |",
             f"| witnessed against the engine's compiled code | {witnessed} ({w['witnessed']} bit-exact, "
             f"{w['witnessed_ulp']} within a few ulps) |",
             f"| of which on the engine's scalar build, where its shipped NEON path differs | {truth_build} |",
             f"| witness refuted | {w['refuted']} |",
             f"| witness unavailable (not callable from outside, not exported, crashed) | {w['unavailable']} |",
             "", "## Gaps by cause", "", "| cause | functions | what closes it |", "|---|---:|---|"]
    from .cards import CAUSES
    for cause, n in Counter(f.get("cause") for f in fns if f["status"] == "gap").most_common():
        lines.append(f"| {cause} | {n} | {CAUSES.get(cause, 'work on the lifter for this case')} |")
    uses = (rep.get("distill") or {}).get("uses") or {}
    if uses:
        lines += ["", "## Uses", "", "| use | functions | lifted | GCD of all lifted members | the logic half or more "
                  "share |", "|---|---:|---:|---|---|"]
        for u, info in sorted(uses.items(), key=lambda kv: -len(kv[1]["members"])):
            g = ", ".join(sorted(a.split("/", 1)[1] for a in info["gcd"])) or "-"
            cm = ", ".join(f"{a.split('/', 1)[1]}^{e}" if e > 1 else a.split("/", 1)[1]
                           for a, e in sorted((info.get("common") or {}).items())) or "-"
            lines.append(f"| {u} | {len(info['members'])} | {info['lifted']} | {g} | {cm} |")
    byk0 = {f["key"]: f for f in fns}
    diffs = sorted(((v["shipped"].get("max_rel") or v["shipped"].get("rel") or 0, k, v) for k, v in verd.items()
                    if v.get("build") == "truth" and v["status"].startswith("witnessed") and v.get("shipped")),
                   key=lambda x: -x[0])
    if diffs:
        lines += ["", "## Where the shipped NEON path differs from the engine's scalar source", "",
                  "The term matches the scalar build bit for bit; the shipped build (NEON: approximate reciprocal "
                  "square roots, fused multiply-adds) differs by up to:", "", "| function | file | relative difference |",
                  "|---|---|---:|"]
        for rel, k, _v in diffs[:20]:
            f = byk0[k]
            lines.append(f"| `{f['qual']}` | {f['file'].split('/')[-1]}:{f['line']} | {rel:.2e} |")
    ids = (rep.get("distill") or {}).get("identities") or []
    lines += ["", f"## Identities: {len(ids)} classes of functions with one canonical form", ""]
    byk = {f["key"]: f for f in fns}
    for cls in ids[:25]:
        lines.append("* " + " ≡ ".join(f"`{byk[k]['qual']}`" for k in cls["members"][:4])
                     + (f" (+{len(cls['members']) - 4})" if len(cls["members"]) > 4 else ""))
    return "\n".join(lines) + "\n"


def register(sub) -> None:
    s = sub.add_parser("unreal", help="Unreal Engine's math as cards: lifted through clang, canonical over the reals, "
                                      "Gödel-numbered, witnessed against the engine's compiled code")
    s.add_argument("action", choices=["locate", "scan", "witness", "show", "uses", "gcd", "emit", "cover"])
    s.add_argument("names", nargs="*")
    s.add_argument("--engine")
    s.add_argument("--save", action="store_true")
    s.add_argument("--seed", type=int)
    s.add_argument("--no-witness", action="store_true")
    s.add_argument("--reuse", action="store_true", help="scan: distill and witness the cached scan again")
    s.add_argument("--write")
    s.add_argument("--lang")
    s.add_argument("--check", action="store_true")
    s.add_argument("--missing", action="store_true", help="witness: only the functions with no verdict yet")
    s.set_defaults(fn=cmd)


__all__ = ["coverage_md", "register"]
