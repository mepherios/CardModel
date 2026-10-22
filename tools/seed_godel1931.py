#!/usr/bin/env python3
"""seed_godel1931 — Gödel method W-1: Gödel's 46 definitions (1931) as cards, each with its Python and Lean forms,
and the findings, computed from a run (CM01).

  godel1931   one card per definition: its number, name (Hirzel's translation), meaning, card-model counterpart (the
              handover's table), its bound, whether it is primitive recursive, its forms and its witnesses
  finding     W1_definitions_run, W1_proof_checker, W1_literal_searches, W1_code_growth

Run: ``python3 -B tools/seed_godel1931.py`` (needs the Lean executable: ``lake build`` in formal/).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.engines import godel1931 as G  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_godel1931.py",
        "source": "Gödel 1931, section 2, in Martin Hirzel's translation; The Gödel Method handover, W-1"}
REGISTRY = ("godel1931", "Gödel's 46 definitions (1931), each a card with its Python and Lean forms: system P's "
            "proof checking as arithmetic on codes (Gödel method W-1).")

# number: (meaning, card-model counterpart, explicit bound of its search or None)
MEANING = {
    1: ("x is divisible by y", "divides on content vectors", "z ≤ x"),
    2: ("x is a prime", "the ledger's primes", "z ≤ x"),
    3: ("the n-th prime factor of x, by size", "reading a code's support", "y ≤ x"),
    4: ("the factorial", "the bound that keeps definition 5 finite", None),
    5: ("the n-th prime", "nth_prime", "y ≤ nthPrime(n-1)! + 1 (Euclid's bound)"),
    6: ("the n-th entry of the sequence x codes", "decode; e_b(m) for content", "y ≤ x"),
    7: ("how many entries x codes", "the token count", "y ≤ x"),
    8: ("concatenation of two sequences", "composing structure; for content, the product",
        "z ≤ nthPrime(length(x) + length(y))^(x + y)"),
    9: ("the one-entry sequence (x)", "one token", None),
    10: ("x wrapped in ( and )", "grouping", None),
    11: ("x is a variable of type n: z^n for a prime z > 13", "typed variables, the core types", "z ≤ x"),
    12: ("x is a variable", "the variable token class", "n ≤ x"),
    13: ("negation", "atom logic/not", None), 14: ("disjunction", "atom logic/or", None),
    15: ("generalization of y over the variable x", "atom logic/forall", None),
    16: ("succ written n times in front of x", "numerals", None), 17: ("the numeral for n", "integer constants", None),
    18: ("x is a sign of type 1", "type checking", "m, n ≤ x"), 19: ("x is a sign of type n", "type checking", "v ≤ x"),
    20: ("x is an elementary formula a(b)", "atomic formulas", "y, z, n ≤ x"),
    21: ("x is ¬y, y ∨ z, or a generalization of y", "formula constructors", "v ≤ x"),
    22: ("x is a formula-building sequence", "a construction certificate", None),
    23: ("x is a formula", "well-formedness", "n ≤ nthPrime(length(x)²)^(x·length(x)²)"),
    24: ("v is bound at position n of x", "binding analysis", "a, b, c ≤ x"),
    25: ("v is free at position n of x", "free-variable analysis", None),
    26: ("v occurs free in x", "free variables", "n ≤ length(x)"),
    27: ("x with its n-th entry replaced by the sequence y", "a rewrite at one position",
         "z ≤ nthPrime(length(x) + length(y))^(x + y)"),
    28: ("the (k+1)-th free place of v, counted from the end", "substitution bookkeeping", "n ≤ length(x)"),
    29: ("how many places v is free in x", "substitution bookkeeping", "n ≤ length(x)"),
    30: ("y substituted at the first k free places of v", "substitution in steps", None),
    31: ("y substituted for every free v in x", "instantiating a rule", None),
    32: ("the defined connectives imp, and, equiv, exists", "atoms logic/implies, and, iff, exists", None),
    33: ("every variable's type raised by n", "reuse of one statement at higher types", "y ≤ x^(x^n)"),
    34: ("x is one of the three Peano axioms", "law cards", None),
    35: ("x instantiates propositional schema 1 (2, 3 or 4)", "schema instances", "y ≤ x"),
    36: ("x instantiates one of the propositional schemas", "schema instances", None),
    37: ("substituting z for v in y captures none of z's variables", "capture-avoiding substitution",
         "n ≤ length(y), m ≤ length(z), w ≤ z"),
    38: ("x instantiates ∀v.a ⇒ a[v := z] under that condition", "quantifier rules", "v, y, z, n ≤ x"),
    39: ("x instantiates ∀v(p ∨ q) ⇒ p ∨ ∀v.q, v not free in p", "quantifier rules", "v, q, p ≤ x"),
    40: ("x instantiates the reducibility (comprehension) axiom", "set formation", "u, v, y, n ≤ x"),
    41: ("x is a type-lift of the extensionality axiom", "set equality", "n ≤ x"),
    42: ("x is an axiom", "membership in the law registry", None),
    43: ("x follows from y and z by modus ponens, or from y by generalization", "one inference or rewrite step", "v ≤ x"),
    44: ("x is a list of formulas, each an axiom or an immediate consequence of earlier ones",
         "a certificate: a checked rewrite chain", None),
    45: ("x is a proof of y", "proof checking, which is decidable", None),
    46: ("some y is a proof of x", "proof search: semi-decidable, the one definition that is not primitive recursive",
         "none: an unbounded search"),
}
PY_NAME = {1: "divides", 2: "is_prime", 3: "pr_factor", 4: "factorial", 5: "nth_prime", 6: "item", 7: "length",
           8: "concat", 9: "seq", 10: "paren", 11: "vtype", 12: "is_var", 13: "neg", 14: "disj", 15: "forall",
           16: "succ_n", 17: "number", 18: "stype1", 19: "stype", 20: "el_fm", 21: "op", 22: "fm_seq", 23: "is_fm",
           24: "bound", 25: "free_at", 26: "free", 27: "insert", 28: "free_place", 29: "n_free_places",
           30: "subst_k", 31: "subst", 32: "imp", 33: "type_lift", 34: "peano_axiom", 35: "prop1_axiom",
           36: "prop_axiom", 37: "quantor1_axiom_condition", 38: "quantor1_axiom", 39: "quantor2_axiom",
           40: "redu_axiom", 41: "set_axiom", 42: "is_axiom", 43: "imm_conseq", 44: "is_proof_figure",
           45: "proof_for", 46: "provable"}
LEAN_NAME = {13: "neg", 14: "disj", 15: "all", 32: "imp", 35: "prop1Axiom"}
LITERAL = {1: "divides", 2: "is_prime", 3: "pr_factor", 5: "nth_prime", 6: "item", 7: "length", 11: "vtype",
           12: "is_var"}
CALL = {1: "divides", 2: "isPrime", 3: "prFactor", 4: "factorial", 5: "nthPrime", 6: "item", 7: "length", 8: "concat",
        9: "seq", 10: "paren", 11: "vtype", 12: "isVar", 13: "not", 14: "or", 15: "forall", 16: "succN", 17: "number",
        18: "stype1", 19: "stype", 20: "elFm", 21: "op", 22: "fmSeq", 23: "isFm", 24: "bound", 25: "freeAt",
        26: "free", 27: "insert", 28: "freePlace", 29: "nFreePlaces", 30: "substK", 31: "subst", 32: "imp",
        33: "typeLift", 34: "peanoAxiom", 35: "prop1Axiom", 36: "propAxiom", 37: "quantor1AxiomCondition",
        38: "quantor1Axiom", 39: "quantor2Axiom", 40: "reduAxiom", 41: "setAxiom", 42: "isAxiom", 43: "immConseq",
        44: "isProofFigure", 45: "proofFor"}


def main() -> int:
    store = open_store(project=False)
    root = store.layer_root("model")
    d = root / REGISTRY[0]
    d.mkdir(parents=True, exist_ok=True)
    (d / "_category.json").write_text(json.dumps({"name": REGISTRY[0], "description": REGISTRY[1], "tier": 0,
                                                  "defined_by": "tools/seed_godel1931.py"}, indent=2,
                                                 ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    store.invalidate()
    seed = 20261022
    agree = G.agree(seed, k=4)
    lit = G.literal_agreement()
    trips = G.round_trips(seed)
    proof, target = G.p_implies_p()
    corrupt = {"f2 and f4 swapped": [proof[0], proof[3], proof[2], proof[1], proof[4]],
               "f2 dropped": [proof[0], proof[2], proof[3], proof[4]],
               "the last formula changed": proof[:4] + [G.disj(G.neg(G.el(G.X2, [G.Y1])), G.el(G.X2, [G.X1]))],
               "an axiom replaced by a non-axiom": [G.imp(G.el(G.X2, [G.X1]), G.el(G.Y2, [G.X1]))] + proof[1:]}
    rejected = {k: not G.proof_for(v, target) for k, v in corrupt.items()}
    accepted = G.proof_for(proof, target)
    stats = {"written": 0, "kept": 0}

    def save(card):
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1
    for num, name, notation, _fn in G.DEFINITIONS:
        meaning, counterpart, bnd = MEANING[num]
        call = CALL.get(num)
        forms = [{"name": "python", "lang": "python", "entry": f"cardmodel.engines.godel1931:{PY_NAME[num]}"},
                 {"name": "lean", "lang": "lean", "entry": f"Godel1931.{LEAN_NAME.get(num, name)}",
                  "file": "formal/Godel1931/Defs.lean"}]
        if num in LITERAL:
            forms.append({"lang": "python", "name": "literal", "entry": f"cardmodel.engines.godel1931:literal.{LITERAL[num]}",
                          "note": "the paper's bounded search itself, runnable on small numbers"})
        save({"name": f"D{num:02d}_{name}", "category": REGISTRY[0], "tier": 1, "number": num, "notation": notation,
              "statement": meaning, "counterpart": counterpart, "bound": bnd, "primitive_recursive": num <= 45,
              "forms": forms, "agreement": {"calls": (agree.get("per_definition") or {}).get(call, 0) if call else 0,
                                            "status": agree["status"] if call else "not computable (Σ1)"},
              "cites": ["Def-2", "Def-9", "Rule-4"] + (["Def-4"] if num >= 44 else []), "evidence_tier": "sample",
              "provenance": PROV})
    findings = [
        ("W1_definitions_run", f"All 46 of Gödel's definitions run as cards. The 45 primitive recursive ones have a "
         f"Python and a Lean form, which agree on all {agree['calls']} generated calls ({agree['status']}); "
         f"{trips['formulas']} generated formulas round-trip (code, decode, parse; {trips['status']}); and the direct "
         f"forms equal the paper's own bounded searches on all {lit['checked']} small inputs those searches can finish "
         f"({lit['status']}). Definition 46, provable, is a Σ1 proposition in Lean and a search over given candidates in "
         f"Python.", ["Def-2", "Def-4", "Def-9", "Rule-2", "Rule-4", "Cap-1"], "sample",
         "the Lean forms are executable (partial definitions for the searches), not proofs that they equal the paper's "
         "definitions; agreement is on seeded generated codes",
         {"agreement": {k: agree[k] for k in ("status", "calls")}, "round_trips": trips["status"],
          "literal": {k: lit[k] for k in ("status", "checked")}}),
        ("W1_proof_checker", f"The checker of definitions 44 and 45 accepts a five-step proof of p ⇒ p in system P "
         f"(p the elementary formula x2(x1), from the propositional schemas and modus ponens): "
         f"{'accepted' if accepted else 'REJECTED'}; and it rejects all {sum(rejected.values())} of "
         f"{len(rejected)} corruptions ({', '.join(rejected)}). The Peano axioms and the set axiom are the formulas "
         f"with = expanded as in P.", ["Def-4", "Cap-10", "Rule-4"], "bounded",
         "one known proof and four corruptions; a proof is read as the sequence of its formulas' codes, never as its "
         "own Gödel number", {"accepted": accepted, "rejected": rejected}),
        ("W1_literal_searches", "Read literally, prFactor (definition 3) does not stop at the last prime factor: past "
         "it gives 0 and then starts again from the smallest, with period the number of factors plus one, and item "
         "(definition 6) follows. Both forms keep that behaviour, and agree with the paper's searches on every small "
         "input.", ["Def-2", "Rule-4"], "bounded", "found by comparing with the literal searches on inputs below 60", {}),
        ("W1_code_growth", f"Gödel's codes explode exactly where Ph-2 and Ph-3 say: the set axiom has "
         f"{G.SA.bit_length()} bits; lifted one type it has {round(G.lift_bits(1))} and two types "
         f"{round(G.lift_bits(2))} (a type-5 variable's sign code is 17^5 = 1,419,857, in an exponent); a proof's own "
         f"number, 2^Φ(f1)·3^Φ(f2)···, would have about Φ(f1) bits, astronomically many, so it is never built. "
         f"Definition 41 is decided from the size formula with one comparison, never by factoring.",
         ["Ph-2", "Ph-3", "Def-9", "GM-8"], "proof", "the sizes are the exact formula Σ c_i·log2 p_i (W-3)",
         {"sa_bits": G.SA.bit_length(), "lift1_bits": round(G.lift_bits(1)), "lift2_bits": round(G.lift_bits(2))}),
    ]
    for name, statement, cites, tier, limits, data in findings:
        save({"name": name, "category": "finding", "tier": 1, "workstream": "W-1", "statement": statement,
              "cites": cites, "evidence_tier": tier, "limits": limits,
              "evidence": "tests/test_godel1931.py; cardmodel/engines/godel1931.py; formal/Godel1931", "data": data,
              "provenance": PROV})
    print(json.dumps({**stats, "agreement": agree["status"], "calls": agree["calls"], "literal": lit["status"],
                      "round_trips": trips["status"], "accepted": accepted, "rejected": rejected}))
    return 0 if agree["status"] == "pass" and lit["status"] == "pass" and accepted and all(rejected.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
