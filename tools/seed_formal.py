#!/usr/bin/env python3
"""seed_formal — MATH_CORE phase 0 by the research handover's agenda and storage rules (R1-R3).

  formal_theorem   one card per theorem of the formal core (formal/GodelCore, Lean), naming the Lean theorems that
                   prove it (the handover's T1-T6)
  method           sized_witness: a finite witness sized by the class of both forms (engines/tiers.py)
  law/CM45, CM46   content is stored as sparse vectors; every claim carries its tier
  goal/G_U8, G_U9  the formal core proved; algorithm forms proved by sized witnesses

Run: ``python3 -B tools/seed_formal.py`` (cards are kept unless ``--force``).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_formal.py",
        "source": "Card Model Research Handover (2026-10-22), sections 8, 11 and the theorems the formal core needs"}
REGISTRY = ("formal_theorem", "Theorems of the Gödel model's formal core, proved in Lean (formal/GodelCore): each "
            "card names the Lean theorems; `cardmodel verify --only formal` builds them and checks their axioms.")

THEOREMS = [
    ("T1_divisibility_lattice", "T1", "gcd and lcm are the meet and join of divisibility on exponent vectors over any "
     "basis, the lattice is distributive, divisibility is having a cofactor, gcd times lcm is the product, and "
     "multiplication cancels.", "formal/GodelCore/T1Lattice.lean",
     ["GodelCore.dvd_gcd", "GodelCore.gcd_dvd_left", "GodelCore.gcd_dvd_right", "GodelCore.lcm_dvd",
      "GodelCore.dvd_lcm_left", "GodelCore.dvd_lcm_right", "GodelCore.dvd_antisymm", "GodelCore.gcd_lcm_distrib",
      "GodelCore.lcm_gcd_distrib", "GodelCore.dvd_iff_exists_mul", "GodelCore.mul_gcd_lcm",
      "GodelCore.mul_left_cancel"]),
    ("T2_carry_preserves_gcd", "T2", "A carry-over (each concept sent to a model of the target set) preserves "
     "products always, and every gcd exactly when distinct concepts go to disjoint supports; concepts with one image "
     "cannot be told apart (the translation gap).", "formal/GodelCore/T2Carry.lean",
     ["GodelCore.preservesGcd_iff_disjoint", "GodelCore.carry_mul", "GodelCore.carry_basis_eq_of_same_image"]),
    ("T3_append_only_ledger", "T3", "Appending to the ledger never moves an atom; reading a content through the "
     "ledger is an injective homomorphism of products, gcd, lcm and divisibility; the reading does not change as the "
     "ledger grows, and agrees along any chain of versions (the directed union).", "formal/GodelCore/T3Ledger.lean",
     ["GodelCore.pos_append", "GodelCore.enc_append", "GodelCore.enc_mul", "GodelCore.enc_gcd", "GodelCore.enc_lcm",
      "GodelCore.enc_dvd_iff", "GodelCore.enc_injective", "GodelCore.enc_chain"]),
    ("T4_free_factor_layer", "T4", "Merging two concepts keeps the factor layer free: congruence under a = b is "
     "agreement after the merge, whose image is the free monoid on the remaining concepts. An equation between "
     "products, a·b = c·d over four distinct concepts, leaves four distinct atoms with two factorizations of one "
     "element, while in a free monoid a product of two atoms factors one way.", "formal/GodelCore/T4Free.lean",
     ["GodelCore.gen_basis_iff", "GodelCore.merge_image", "GodelCore.two_factorizations",
      "GodelCore.basis_pair_unique"]),
    ("T5_property_transport", "T5", "Upward-closed properties transport to multiples and downward-closed ones to "
     "divisors; containing a factor is upward closed, staying inside a fragment downward closed; gcd keeps "
     "downward-closed properties and lcm upward-closed ones.", "formal/GodelCore/T5Transport.lean",
     ["GodelCore.up_transport", "GodelCore.down_transport", "GodelCore.contains_upClosed",
      "GodelCore.fragment_downClosed", "GodelCore.gcd_keeps_down", "GodelCore.lcm_keeps_up"]),
    ("T6_rewrite_invariants", "T6", "A balanced rule applied anywhere under any substitution moves a term's content "
     "by exactly its delta, so a weight orthogonal to every rule's delta is the same at both ends of every rewrite "
     "sequence: a different weight proves no rewrite exists.", "formal/GodelCore/T6Invariants.lean",
     ["GodelCore.balanced_step", "GodelCore.dot_step", "GodelCore.invariant"]),
]

METHODS = [
    ("sized_witness", "Read both forms' classes from their lifted IR (polynomial, C-finite in one counted loop, "
     "regions cut by leading guards), size the witness by the theorems for those classes, and run both forms on it "
     "with exact integers.", "equality of two integer functions on their domain, when both forms fall in a class "
     "with a finite-witness theorem", "points: the product of (degree + 1) per input times the sum of the recurrence "
     "orders",
     "only straight-line polynomials and single counted loops with constant-coefficient affine updates; the lifter's "
     "faithfulness is assumed; machine integers are not covered", "built"),
]

LAWS = [
    ("CM45_content_is_a_sparse_vector", "A model's content is stored as the sparse map from ledger index to exponent, "
     "with the basis version it was read against, never as the content integer (the product of primes), and its "
     "identity is the hash of its structure; Gödel's positional number is kept for small terms only. The factor "
     "layer holds no relations: two indices that name one concept are merged and a concept found to be a product is "
     "deprecated into it, both as appended events; an equation between products is a transformation with a proof.",
     ["Card Model Research Handover, storage rules (2026-10-22)", "formal/GodelCore T3, T4"],
     "tests/test_godel.py::test_stored_records_follow_the_rules"),
    ("CM46_every_claim_carries_its_tier", "Every claim carries the tier of its evidence: proof (checked by Lean's "
     "kernel, or a finite witness sized by a theorem for the claim's class, the class read from the code and never "
     "assumed), probabilistic proof (with its bound), bounded check (exhaustive within stated bounds), or sample.",
     ["Card Model Research Handover, part 8 and its rules (2026-10-22)", "Rice 1953"],
     "tests/test_tiers.py::test_every_claim_carries_a_tier"),
]

GOALS = [
    ("G_U8_formal_core", "understanding", "Problems in the formal core: a formal_theorem card whose Lean theorem is "
     "missing or rests on more than Lean's standard axioms, any sorry, or a failed build (agenda R1).",
     "formal_core_problems", 0, "lower"),
    ("G_U9_algorithm_forms_proved", "understanding", "Fraction of the algorithm cards' other Python forms whose "
     "equality with the definition is proved (a sized witness or a kernel proof), not sampled (agenda R3).",
     "algorithm_forms_proved", 0.5, "higher"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    root = store.layer_root("model")
    d = root / REGISTRY[0]
    d.mkdir(parents=True, exist_ok=True)
    f = d / "_category.json"
    if not f.exists() or args.force:
        meta = {"name": REGISTRY[0], "description": REGISTRY[1], "tier": 0, "defined_by": "tools/seed_formal.py"}
        f.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    store.invalidate()
    stats = {"written": 0, "kept": 0}

    def put(card):
        if store.get(f"{card['category']}/{card['name']}") is not None and not args.force:
            stats["kept"] += 1
            return
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1

    for name, ref, statement, file, lean in THEOREMS:
        put({"name": name, "category": REGISTRY[0], "tier": 0, "handover": ref, "statement": statement, "file": file,
             "lean": lean, "evidence_tier": "proof", "provenance": PROV})
    for name, procedure, decides, complexity, limits, status in METHODS:
        put({"name": name, "category": "method", "tier": 0, "procedure": procedure, "decides": decides,
             "complexity": complexity, "limits": limits, "status": status, "statement": decides, "provenance": PROV})
    for name, statement, origins, witness in LAWS:
        put({"name": name, "category": "law", "tier": 0, "statement": statement, "origins": origins,
             "witness": witness, "provenance": PROV})
    for name, axis, statement, metric, target, direction in GOALS:
        put({"name": name, "category": "goal", "tier": 0, "axis": axis, "statement": statement, "metric": metric,
             "target": target, "direction": direction, "provenance": PROV})
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
