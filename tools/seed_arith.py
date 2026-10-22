#!/usr/bin/env python3
"""seed_arith — Gödel method W-12, arithmetized execution: the findings, computed from a run over every LR35902
output term (machine/arith.py), never typed by hand (CM01).

Run: ``python3 -B tools/seed_arith.py`` (about six minutes), or ``--from RUN.json`` to use a saved ``arith.run``.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.engines.context import Ctx  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402
from cardmodel.machine import arith as A  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_arith.py",
        "source": "The Gödel Method: Research and Development Handover (2026-10-22), W-12"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--from", dest="src")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    ctx = Ctx(store)
    run = json.loads(Path(args.src).read_text()) if args.src else A.run(ctx)
    rng = random.Random(20261022)
    demo = []
    t0 = time.perf_counter()
    for i, o, t in A.outputs(ctx):
        if i in ("LR35902_CB_37", "LR35902_CB_07", "LR35902_CB_17") and o == "F":
            honest, bad = A.trace(t, rng), A.trace(t, rng, tamper=True)
            demo.append({"instruction": i, "output": o, "rows": honest["rows"], "gates": honest["gates"],
                         "honest": honest["accepted"] and honest["divisible"],
                         "tampered_rejected": not (bad["accepted"] or bad["divisible"]),
                         "error_bound": honest["error_bound"]})
    t_trace = time.perf_counter() - t0
    ring = A.mod2w_unsound(8, 4000, rng)
    findings = [
        ("W12_constraints_agree",
         f"Every LR35902 output term ({run['outputs']}: register updates, bus-effect arguments and guards) compiles to "
         f"gates of degree at most 2 over the Goldilocks field ({run['gates']} gates in all), and the constraints agree "
         f"with the terms on every input: z3 proves it for all of them ({run['smt']}), and exhaustive evaluation "
         f"confirms it wherever the inputs have at most {A.EXHAUSTIVE_BITS} bits ({run['exhaustive']}; "
         f"{run['inputs_checked']:,} inputs).",
         ["Cap-11", "Ph-11", "Rule-2"], "proof",
         "z3 is a decision procedure for bit-vectors, trusted as such; exhaustive evaluation covers every input of the "
         "narrower outputs; values stay inside a 40-bit two's-complement window", run),
        ("W12_schwartz_zippel_trace",
         f"Over F_p the trace identity decides a whole instruction at once: on {len(demo)} instructions, all rows of "
         f"the honest trace satisfy the constraints exactly when X^N - 1 divides the composition polynomial, checked "
         f"at one random point ({sum(d['honest'] for d in demo)} accepted); one flipped gate output in one row breaks "
         f"divisibility and is rejected ({sum(d['tampered_rejected'] for d in demo)} of {len(demo)}). Error bound 2N/p.",
         ["Cap-11", "Ph-11"], "probabilistic",
         "the verifier evaluates the polynomials itself: the identity and its bound, not a succinct proof",
         {"demo": demo, "seconds": round(t_trace, 1)}),
        ("W12_mod_2w_fails",
         f"Schwartz-Zippel's bound needs an integral domain: over Z/2^8 the random-point test accepted the nonzero "
         f"polynomial 2^7·x in {ring['accepted_mod_2w']} of {ring['trials']} trials (every even x), and over F_p in "
         f"{ring['accepted_mod_p']}.", ["Cap-11"], "sample", "a demonstration of the counterexample the handover names",
         ring),
        ("W12_methods_compared",
         f"Three ways to decide that the constraints equal the terms: exhaustive evaluation (proof over a finite "
         f"domain; {run['seconds']['exhaustive']} s for the outputs with at most {A.EXHAUSTIVE_BITS} input bits, and it "
         f"cannot reach wider ones), SMT (proof by a decision procedure; {run['seconds']['smt']} s for all "
         f"{run['outputs']}), and the Schwartz-Zippel trace identity (probabilistic proof with error 2N/p, one check per "
         f"instruction, the basis of succinct proofs that code ran correctly).", ["Cap-11", "GM-7", "Ph-15"], "bounded",
         "times on this machine for this run", {"seconds": run["seconds"], "trace_seconds": round(t_trace, 1)}),
    ]
    stats = {"written": 0, "kept": 0}
    for name, statement, cites, tier, limits, data in findings:
        _, changed = store.save({"name": name, "category": "finding", "tier": 1, "workstream": "W-12",
                                 "statement": statement, "cites": cites, "evidence_tier": tier, "limits": limits,
                                 "evidence": "tests/test_arith.py; cardmodel/machine/arith.py", "data": data,
                                 "provenance": PROV}, layer="model")
        stats["written" if changed else "kept"] += 1
    ok = set(run["smt"]) <= {"unsat"} and "fail" not in run["exhaustive"] and all(
        d["honest"] and d["tampered_rejected"] for d in demo)
    print(json.dumps({**stats, "ok": ok}))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
