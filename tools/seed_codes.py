#!/usr/bin/env python3
"""seed_codes — Gödel method W-3, identity and size: the findings, computed from a measurement of every card with a
term (engines/codes.py), never typed by hand (CM01).

  finding   W3_code_sizes (the sizes of six codes), W3_size_model (the formulas against the built integers and the
            handover's example), W3_gm2_decision (the decision record for GM-2 and the bound for GM-8)

Run: ``python3 -B tools/seed_codes.py`` (findings are rewritten from a fresh measurement).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.engines import codes as C  # noqa: E402
from cardmodel.engines.context import Ctx  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_codes.py",
        "source": "The Gödel Method: Research and Development Handover (2026-10-22), W-3"}
BOUND_BITS = 4096


def main() -> int:
    store = open_store(project=False)
    m = C.measure(Ctx(store))
    sm = m["summary"]
    ex = C.worst_case(10, 10 ** 6)
    med = {k: round((sm.get(k) or {}).get("median", 0)) for k in ("positional", "content", "cantor", "base_k")}
    p95 = {k: round((sm.get(k) or {}).get("p95", 0)) for k in ("positional", "content", "cantor", "base_k")}
    mx = {k: round((sm.get(k) or {}).get("max", 0)) for k in ("positional", "content", "cantor", "base_k")}
    fb = sm["formula_vs_built"]
    findings = [
        ("W3_code_sizes", f"Over the store's {sm['cards']} terms ({sm['by_kind']}), in bits (median, 95th percentile, "
         f"largest): positional {med['positional']}, {p95['positional']}, {mx['positional']}; content "
         f"{med['content']}, {p95['content']}, {mx['content']}; Cantor tree code {med['cantor']}, {p95['cantor']}, "
         f"{mx['cantor']}; bijective base-16 {med['base_k']}, {p95['base_k']}, {mx['base_k']}; sha256 256. The "
         f"positional code is larger than the content code for {sm['positional_over_content']:.0%} of terms, and "
         f"pairing codes explode with nesting.", ["Def-9", "Def-10", "Def-11", "Def-12", "Def-15", "Def-16", "Ph-2",
                                                  "Ph-3"], "bounded",
         "every card with a term in this store, at this commit; multi-statement bodies are read as their expressions",
         sm),
        ("W3_size_model", f"The sizes are predicted without building any integer: the positional and content codes by "
         f"their logarithmic formulas, within {fb['positional']['max_bits_off']} and "
         f"{fb['content']['max_bits_off']} bit of the built integer on all {fb['positional']['checked']} and "
         f"{fb['content']['checked']} terms small enough to build; the Cantor tree code by carrying log2 up the "
         f"tree, exact on all {sm['model_cantor']['checked']} terms whose code was built. The handover's example, "
         f"10 tokens over atoms near index 10^6, needs about {ex['positional']:.3g} bits as a positional code and "
         f"{ex['content']:.0f} as a content code.", ["Def-9", "Def-10", "Def-11", "Ph-2"], "bounded",
         "the formulas are exact identities of the codes' definitions; the check builds every integer up to "
         "2^16 bits; the example uses the prime number theorem's estimate of the millionth prime",
         {"formula_vs_built": fb, "model_cantor": sm["model_cantor"], "example": ex}),
        ("W3_gm2_decision", f"Decision record for GM-2 and GM-8: the identity is the sha256 of the canonical term "
         f"(as CM45 already stores); Gödel's positional code is computed on demand only for terms of at most "
         f"{BOUND_BITS} bits ({sm['positional_under'][str(BOUND_BITS)]:.0%} of today's terms), never stored, never "
         f"nested; pairing tree codes are not used as identities. Adopting GM-2 amends CM43 and needs the user's yes.",
         ["GM-2", "GM-8", "Ph-2", "Ph-3", "Rule-23"], "bounded",
         "a decision from this store's measurement; the bound keeps any on-demand code under half a kilobyte",
         {"bound_bits": BOUND_BITS, "positional_under": sm["positional_under"]}),
    ]
    stats = {"written": 0, "kept": 0}
    for name, statement, cites, tier, limits, data in findings:
        _, changed = store.save({"name": name, "category": "finding", "tier": 1, "workstream": "W-3",
                                 "statement": statement, "cites": cites, "evidence_tier": tier, "limits": limits,
                                 "evidence": "cardmodel godel sizes; tests/test_codes.py", "data": data,
                                 "provenance": PROV}, layer="model")
        stats["written" if changed else "kept"] += 1
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
