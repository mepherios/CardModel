"""metrics — the engine's math as numbers computed from its cards (goals G_U10-G_U12, the verify section).

  lifted fraction     lifted (and not refuted) over the math universe (lifted, refuted and gaps)
  witnessed fraction  definitions whose witness against the engine's compiled code passed, over all its
                      definitions
  refuted             subjects whose lifted term the witness refuted

``check`` is the verify section ``unreal``: the cards hold together (every lifted subject has its definition and
action, every atom is in the ledger with the prime the subject card names), the canonical hashes re-derive from the
stored terms (the mathematics is reproducible from the cards alone), and, when the engine and clang are on this
host, a seeded sample is witnessed again against the engine's compiled code. With no scan saved (every checkout
but the machine that holds the engine, docs/INTEGRATION.md rule 8), ``fixture`` runs the same pipeline on the fixture
header, so the section exercises the code on every host with clang (CM50).

Honest limits (L1): definitions whose terms are kept in the cache (past cards.TERM_LIMIT) are counted but their
hashes are not re-derived here; the re-witness is a sample.
"""
from __future__ import annotations

import random
from collections import Counter

from ..engines import realnorm as RN


def _engine_defs(st) -> list:
    return [d for d in st.cards("definition") if (d.get("origin") or {}).get("engine")
            and str((d.get("subject") or "")).startswith("unreal_math/")]


def goal(st, name: str):
    subs = st.cards("unreal_math")
    if not subs:
        return None
    c = Counter(s.get("status") for s in subs)
    if name == "unreal_refuted":
        return c["refuted"]
    if name == "unreal_lifted_fraction":
        universe = c["lifted"] + c["gap"] + c["refuted"]
        return round(c["lifted"] / universe, 4) if universe else None
    defs = _engine_defs(st)
    if not defs:
        return None
    ok = sum(1 for d in defs if (d.get("proof_obligations") or [{}])[0].get("status") == "witnessed")
    return round(ok / len(defs), 4)


def rederive(d) -> dict | None:
    """The canonical outputs recomputed from a definition's stored lifted terms (None when they are in the
    cache)."""
    term = (d.get("math") or {}).get("term") or {}
    if "in_cache" in term:
        return None
    pos = {nm: f"x{i}" for i, (nm, _k) in enumerate((d.get("math") or {}).get("inputs") or [])}
    norm = RN.Normalizer()
    return {name: RN.canonical(RN.rename(t, pos), norm) for name, t in term.items() if t is not None}


def check(ctx, seed: int, rewitness: int = 12) -> dict:
    from ..engines import godel as G
    st = ctx.store
    subs = st.cards("unreal_math")
    if not subs:
        return fixture(seed)
    problems = []
    idx = G.index_of(st)
    defs = {d.name: d for d in _engine_defs(st)}
    acts = {a.name for a in st.cards("action")}
    for s in subs:
        a = s.get("atom")
        if a:
            if a not in idx:
                problems.append(f"unreal_math/{s.name}: its atom {a} is not in the ledger")
            elif s.get("prime") != idx[a]["prime"]:
                problems.append(f"unreal_math/{s.name}: prime {s.get('prime')} but the ledger says {idx[a]['prime']}")
        if s.get("status") == "lifted" and s.get("definition"):
            dn = s["definition"].split("/", 1)[1]
            if dn not in defs:
                problems.append(f"unreal_math/{s.name}: its definition {dn} does not exist")
            elif f"{dn}__engine" not in acts:
                problems.append(f"definition/{dn}: no action for the engine's code")
    rederived, mismatched = 0, []
    for d in sorted(defs.values(), key=lambda d: d.name):
        got = rederive(d)
        stored = (d.get("canonical") or {}).get("outputs") or {}
        if got is None or "in_cache" in stored:
            continue
        if got != stored:
            mismatched.append(d.name)
        rederived += 1
    if mismatched:
        problems.append(f"canonical forms that do not re-derive from their terms: {mismatched[:5]}")
    out = {"status": "fail" if problems else "pass", "problems": problems, "subjects": len(subs),
           "definitions": len(defs), "rederived": rederived,
           "counts": dict(Counter(s.get("status") for s in subs))}
    out.update(_rewitness(ctx, seed, rewitness))
    if out.get("rewitness", {}).get("refuted"):
        out["status"] = "fail"
        problems.append(f"the engine refutes: {out['rewitness']['refuted'][:3]}")
    return out


def fixture(seed: int) -> dict:
    """The pipeline on the fixture header (examples/engine_math, not engine code) when no engine scan is saved, so the
    section exercises the engine-math pipeline on every host with clang: every function lifted through clang's AST
    (or its gap's cause), two spellings of the dot product sharing one canonical form, every lifted function
    witnessed against the compiled header. A refuted term or a lost identification fails."""
    import shutil
    import tempfile
    from pathlib import Path

    from ..kernel import paths
    from . import distill as D
    from . import engine as E
    from . import scan as S
    from . import witness as W
    src = paths.home() / "examples" / "engine_math" / "mini_math.h"
    if E.clang()[0] is None:
        return {"status": "skipped", "mode": "fixture",
                "reason": "no engine scan saved (cardmodel unreal scan --save) and no clang++ for the fixture"}
    if not src.is_file():
        return {"status": "skipped", "mode": "fixture", "reason": f"no engine scan saved and no fixture at {src}"}
    d = Path(tempfile.mkdtemp(prefix="cardmodel_unreal_fixture_"))
    try:
        fns = S.lift_source(src, ["-std=c++20", "-ffp-contract=off", "-x", "c++", f"-I{src.parent}"], d)
        lifted = [f for f in fns if f["status"] == "lifted" and f.get("outputs")]
        hashes = {f["qual"]: D.distill_function(f, {})["hash"] for f in lifted}
        problems = []
        dots = [hashes.get(q) for q in ("Mini::TVec<double>::Dot", "Mini::TVec<double>::DotSwapped")]
        if None in dots or dots[0] != dots[1]:
            problems.append("two spellings of the dot product do not share one canonical form")
        target = W.Target([f'#include "{src.name}"'], ["-std=c++20", "-ffp-contract=off", f"-I{src.parent}"], [], d)
        v = W.run(target, lifted, seed, log=lambda m: None, cases=8)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    c = Counter(x["status"] for x in v.values())
    byk = {f["key"]: f["qual"] for f in lifted}
    refuted = sorted(byk.get(k, k) for k, x in v.items() if x["status"] == "refuted")
    if refuted:
        problems.append(f"the compiled header refutes: {refuted[:3]}")
    if not c["witnessed"]:
        problems.append("no lifted function of the fixture was witnessed")
    return {"status": "fail" if problems else "pass", "mode": "fixture", "problems": problems, "seed": seed,
            "functions": len(fns), "counts": dict(Counter(f["status"] for f in fns)),
            "canonical_forms": len(set(hashes.values())), "witness": dict(c),
            "gaps": {f["qual"]: f.get("cause") for f in fns if f["status"] != "lifted"}}


def _rewitness(ctx, seed: int, n: int) -> dict:
    """A seeded sample of the lifted functions witnessed again against the engine (when it is on this host)."""
    from . import engine as E
    from . import scan as S
    from . import witness as W
    try:
        eng = E.locate()
    except E.NotFound as exc:
        return {"rewitness": {"status": "unavailable", "reason": str(exc)}}
    if E.clang()[0] is None:
        return {"rewitness": {"status": "unavailable", "reason": "no clang++"}}
    cache = E.cache(ctx.state_root, eng)
    # the scan streamed twice (it is too large to hold whole: about a gigabyte as Python objects): every function as
    # the light record the scalar build's grouping needs, then the sample in full
    light = [{"key": f["key"], "qual": f["qual"], "file": f["file"], "status": f["status"], "xcalls": f.get("xcalls"),
              "has_outputs": bool(f.get("outputs"))} for f in S.functions(cache)]
    if not light:
        return {"rewitness": {"status": "unavailable", "reason": "no scan in this checkout's cache"}}
    lifted = [f for f in light if f["status"] == "lifted" and f["has_outputs"]]
    rng = random.Random(seed)
    sample = {f["key"] for f in rng.sample(lifted, min(n, len(lifted)))}
    full = {f["key"]: f for f in S.functions(cache) if f["key"] in sample}
    functions = [full.get(f["key"], {**f, "outputs": []}) for f in light]
    v = W.run_engine(eng, cache, functions, seed, only=sample, log=lambda m: None, cases=8)
    c = Counter(x["status"] for x in v.values())
    byk = {f["key"]: f for f in lifted}
    return {"rewitness": {"status": "fail" if c["refuted"] else "pass", "seed": seed, "counts": dict(c),
                          "refuted": [byk[k]["qual"] for k, x in v.items() if x["status"] == "refuted"]}}


__all__ = ["check", "fixture", "goal", "rederive"]
