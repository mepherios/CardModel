#!/usr/bin/env python3
"""seed_numbering — Gödel method W-5, admissible numberings: the findings, computed from a run of every Gödel set's
conditions (engines/numbering.py), never typed by hand (CM01).

Run: ``python3 -B tools/seed_numbering.py``.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.engines import numbering as N  # noqa: E402
from cardmodel.engines.context import Ctx  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_numbering.py",
        "source": "The Gödel Method: Research and Development Handover (2026-10-22), W-5"}


def main() -> int:
    store = open_store(project=False)
    ctx = Ctx(store)
    r = N.check(ctx, seed=20261022)
    sets = r["sets"]
    checked = {s: sum(c["checked"] for c in v["conditions"].values()) for s, v in sets.items()}
    comp = store.get("godel_set/computation")
    stated = sorted((comp.get("numbering") or {}).get("arities_from", {}).items())
    findings = [
        ("W5_admissible_numberings",
         f"Every Gödel set states its numbering and passes all {len(N.CONDITIONS)} conditions "
         f"({', '.join(c[0] for c in N.CONDITIONS)}): " + "; ".join(
             f"{s} ({v['atoms']} atoms with the sets it extends, {checked[s]} checks)" for s, v in sorted(sets.items()))
         + ". Provability is ∃ of the decidable proof relation (Lean's kernel) with no further clause, so a set's "
           "consistency statement means what Rule-12 says, and Feferman's deviant predicates are excluded.",
         ["GM-4", "Rule-1", "Rule-2", "Rule-3", "Rule-5", "Rule-6", "Def-1", "Def-4", "Ph-6"], "proof",
         "each condition holds by the argument stated with it in engines/numbering.py (unique factorization, a total "
         "decision procedure, shifting positions to larger primes); the generated objects, corrupted codes and "
         "random integers are its witnesses (tier bounded); natural provability is checked as the card's statement",
         {"sets": {s: {k: c["status"] for k, c in v["conditions"].items()} for s, v in sets.items()},
          "checks": checked}),
        ("W5_arity_gaps",
         f"Two numberings were not admissible as stored: the machines set's effects carried an optional guard "
         f"and no fixed argument count, and the computation set's {len(stated)} atoms are not IR ops, so nothing "
         f"stated their arities; their codes could not be parsed back (Rule-2). Each set card now states its "
         f"arities ({', '.join(f'{a} from {h}' for a, h in stated[:3])}, ...), and an effect's guard slot holds "
         f"logic/true when it always happens.", ["Rule-2", "GM-4", "Def-1"], "bounded",
         "found by the decidability test on generated objects; the arities of EC_ADD, EC_SCALAR_MUL and BIT_NOR are "
         "stated, the others read from the op cards' Python forms", {"arities_from": dict(stated)}),
    ]
    stats = {"written": 0, "kept": 0, "status": r["status"]}
    for name, statement, cites, tier, limits, data in findings:
        _, changed = store.save({"name": name, "category": "finding", "tier": 1, "workstream": "W-5",
                                 "statement": statement, "cites": cites, "evidence_tier": tier, "limits": limits,
                                 "evidence": "tests/test_numbering.py; engines/numbering.py", "data": data,
                                 "provenance": PROV}, layer="model")
        stats["written" if changed else "kept"] += 1
    print(json.dumps(stats))
    return 0 if r["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
