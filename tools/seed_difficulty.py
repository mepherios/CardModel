#!/usr/bin/env python3
"""seed_difficulty — Gödel method W-15, the difficulty census (Cap-18, Ph-15, GM-7).

  method      each method card gains ``rank``: the arithmetical rank of the question it decides, and of the general
              question it serves (engines/difficulty.py)
  question    the questions the product asks, each with its rank and whether the product may promise an answer
  finding     the census as a result card, citing the handover's ids, with its tier

Run: ``python3 -B tools/seed_difficulty.py`` (method ranks are always written; other cards are kept unless
``--force``).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_difficulty.py",
        "source": "The Gödel Method: Research and Development Handover (2026-10-22), W-15"}
QUESTION = ("question", "The questions the product asks, each with its arithmetical rank and whether the product "
            "may promise an answer (only decidable ones: Ph-15); the open ones name what is done instead.")

# method: (what it decides, its rank, the general question it serves, that question's rank, why, ids)
METHOD_RANKS = {
    "lift_python": ("the core term of a Python function in the supported subset, and whether it is in the subset",
                    "decidable", "is the term what the Python means", "Π1",
                    "a syntax-directed translation is a total computable function, and the subset is syntactic; "
                    "that the term means what CPython does on every input is a ∀ over inputs",
                    ["Rule-2", "Rule-4", "Ph-15"]),
    "emit": ("the code a language card gives for a core term", "decidable",
             "does the emitted code equal its definition on every input", "Π1",
             "emission is a total translation; equality of two total programs is ∀ over inputs (Rice: undecidable "
             "in general)", ["Rule-17", "Ph-15"]),
    "saturate": ("whether two terms are equal by the rule cards within a budget, and the cheapest term found",
                 "decidable", "are two terms equal in the equational theory of the rules", "Σ1",
                 "a rewrite chain is a finite witness, so equality is ∃ of a decidable check; the word problem is "
                 "undecidable in general (Post and Markov 1947), so 'not found' is never 'unequal'",
                 ["Rule-4", "Ph-15", "GM-3"]),
    "fit_recurrence": ("the shortest linear recurrence of the first N terms (Berlekamp-Massey)", "decidable",
                       "does the function satisfy that recurrence for every n", "Π1",
                       "the fit is a finite computation; 'for every n' is a ∀, refuted by one term and proved only "
                       "when the form's class is read from its code (sized_witness)", ["Rule-21", "Ph-15"]),
    "witness": ("whether two implementations agree on the seeded inputs, each run under a time limit",
                "decidable", "do they agree on every input", "Π1",
                "finitely many runs under a time limit decide; agreement everywhere is a ∀, so a witness can refute "
                "it, never confirm it (tier sample)", ["Ph-15", "GM-7", "Rule-17"]),
    "sized_witness": ("whether two forms in a recognized class (polynomial, C-finite loop or recursion, guarded "
                      "regions) agree on the points their class theorem names", "decidable",
                      "are two integer functions equal on their domain", "Π1",
                      "inside the classes a finite witness is a proof (the grid lemma, C-finite agreement), so the "
                      "∀ collapses to a finite check; outside them the question stays Π1", ["Ph-15", "GM-7", "Cap-18"]),
    "symbolic_execution": ("the terms of a loop-free instruction over symbolic registers, and their agreement with "
                           "the executable semantics on given inputs", "decidable",
                           "do the terms equal the semantics on every 8-bit input", "decidable",
                           "loop-free fixed-width code has a finite input space, so even the general question is a "
                           "finite check (exhaustive, SMT or arithmetized: W-12)", ["Ph-15", "Cap-11"]),
    "lean_kernel": ("whether a given proof term checks against its statement", "decidable",
                    "is the statement provable", "Σ1",
                    "checking a proof is the decidable Proof(y, x) of Def-4; provability Prov(x) = ∃y Proof(y, x) is "
                    "Σ1, confirmed by a proof and never refuted in general (Gödel's first incompleteness theorem)",
                    ["Def-4", "Rule-11", "Ph-15"]),
    "learn": ("whether an observed tree yields candidate cards that pass their checks on the evidence",
              "decidable", "is a promoted card right on every input", "Π1",
              "promotion runs finitely many checks; correctness everywhere is a ∀, so learned cards stay at tier "
              "sample until a proof or a sized witness lifts them", ["Ph-15", "GM-7"]),
    "human_written": ("nothing by itself", "none", "is what a person wrote right", "Π1",
                      "a person's code is checked by the other methods; its correctness is the same ∀ over inputs",
                      ["Ph-15"]),
}

# name: (question, rank, promise, what the product does instead, ids)
QUESTIONS = [
    ("valid_code", "Is n the structural code of a well-formed term?", "decidable", "answered",
     "decode n, then encode the result and compare (the round trip of Rule-2)", ["Rule-1", "Rule-2", "Def-1"]),
    ("ledger_well_formed", "Is the ledger well formed and append-only since the last commit?", "decidable",
     "answered", "godel.check: indices without gaps, each prime the n-th prime, each atom once, a prefix of HEAD",
     ["Rule-18"]),
    ("part_of", "Is one model a part of another (divides), and what do two models share (gcd)?", "decidable",
     "answered", "componentwise comparison of sparse vectors, proved in formal/GodelCore T1",
     ["Rule-19", "Cap-2"]),
    ("carry_preserves_gcd", "Does a carry-over map preserve every gcd?", "decidable", "answered",
     "the disjoint-support test, proved equivalent in formal/GodelCore T2", ["Rule-20", "Cap-4"]),
    ("proof_checks", "Does a given proof check?", "decidable", "answered",
     "Lean's kernel (Def-4's Proof relation)", ["Def-4", "Cap-10"]),
    ("instruction_terms_equal", "Do an instruction's terms equal its executable semantics on every 8-bit input?",
     "decidable", "answered", "a finite check: exhaustive runs, SMT, or polynomial constraints (W-12)",
     ["Cap-11", "Ph-15"]),
    ("classified_forms_equal", "Are two forms of one function equal, when both fall in a recognized class?",
     "decidable", "answered", "sized_witness: the class theorem names finitely many points (engines/tiers.py)",
     ["GM-7", "Ph-15"]),
    ("provable", "Is this statement provable?", "Σ1", "open",
     "search for a proof and let Lean's kernel check what is found; a failed search says nothing (Rule-11)",
     ["Def-4", "Rule-11", "Ph-15"]),
    ("halts", "Does this program halt on this input?", "Σ1", "open",
     "run it under a time limit: halting is confirmed, a timeout decides nothing (Turing 1936)", ["Def-21", "Ph-15"]),
    ("rules_equal", "Are two terms equal under the rule cards?", "Σ1", "open",
     "equality saturation: an equality found is a proof; none found within the budget is not a disproof "
     "(the word problem, Post and Markov 1947)", ["GM-3", "Ph-15"]),
    ("programs_equal", "Do two total programs compute the same function on every input?", "Π1", "open",
     "prove it in a recognized class or in Lean; otherwise sample it, and say so (tier sample, Rice's theorem)",
     ["Rule-17", "Ph-15", "GM-7"]),
    ("consistent", "Is the card model's theory consistent?", "Π1", "open",
     "never certified from inside (second incompleteness); changes are accepted only with Lean's external check "
     "(GM-9)", ["Rule-12", "Rule-10", "GM-9"]),
    ("learned_card_right", "Is a learned card right on every input?", "Π1", "open",
     "keep it at tier sample until a proof or a sized witness lifts it", ["Ph-15", "GM-7"]),
    ("definition_minimal", "Is there no shorter description of this term (its Kolmogorov complexity)?", "Π1", "open",
     "Kolmogorov complexity is uncomputable: minting by description length only ever improves (GM-6)",
     ["GM-6", "Ph-9"]),
    ("total", "Is this program total: does it halt on every input?", "Π2", "open",
     "prove termination for its class (primitive recursion, System T, a decreasing measure), else leave it open "
     "(Cap-16)", ["Cap-16", "Ph-15"]),
    ("rewriting_terminates", "Does the rewrite system terminate on every term?", "Π2", "open",
     "bounded saturation with a budget; termination proofs for the rules that have them", ["Ph-15"]),
    ("true", "Is this arithmetic sentence true?", "beyond", "open",
     "truth has no arithmetical definition inside the system (Tarski): truth cards are checked from outside, by "
     "Lean or by labelled samples", ["Rule-13"]),
    ("basis_complete", "Does the basis settle every question about its own codes?", "Π2", "open",
     "for every sentence a proof of it or of its negation exists: ∀∃, and Gödel's first theorem already answers no "
     "for any consistent basis that contains Q, so the model keeps expanding and marks undecided questions open, "
     "never false", ["Rule-11", "Ph-15"]),
]


FINDINGS = [
    ("W15_difficulty_census", "W-15",
     "Every method decides a decidable question (nine of ten; the tenth, human_written, decides nothing) and serves "
     "a general question of rank decidable (symbolic_execution), Σ1 (saturate, lean_kernel) or Π1 (the other seven). "
     "Of the product's 18 questions, 7 are decidable and promised; 3 are Σ1, 4 Π1, 3 Π2 and 1 beyond the "
     "arithmetical hierarchy, and those 11 are left open, each with what the product does instead.",
     ["Cap-18", "Ph-15", "GM-7", "Def-4", "Rule-11", "Rule-12", "Rule-13", "Rule-17"], "proof",
     "each rank is an upper bound read from the question's logical form (an ∃ or ∀ over a decidable relation); "
     "completeness for the level is cited, not proved", "cardmodel difficulty; tests/test_difficulty.py"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    root = store.layer_root("model")
    d = root / QUESTION[0]
    d.mkdir(parents=True, exist_ok=True)
    f = d / "_category.json"
    if not f.exists() or args.force:
        meta = {"name": QUESTION[0], "description": QUESTION[1], "tier": 0, "defined_by": "tools/seed_difficulty.py"}
        f.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    store.invalidate()
    stats = {"ranked": 0, "written": 0, "kept": 0}
    missing = []
    for m in store.cards("method"):
        if m.name not in METHOD_RANKS:
            missing.append(m.name)
            continue
        decides, rank, general, grank, why, cites = METHOD_RANKS[m.name]
        card = dict(m)
        card["rank"] = {"decides": rank, "question": decides, "general": general, "general_rank": grank,
                        "why": why, "cites": cites}
        _, changed = store.save(card, layer="model")
        stats["ranked"] += changed
    for name, text, rank, promise, instead, cites in QUESTIONS:
        if store.get(f"question/{name}") is not None and not args.force:
            stats["kept"] += 1
            continue
        _, changed = store.save({"name": name, "category": "question", "tier": 0, "statement": text, "rank": rank,
                                 "promise": promise, "instead": instead, "cites": cites, "provenance": PROV},
                                layer="model")
        stats["written" if changed else "kept"] += 1
    for name, ws, statement, cites, tier, limits, evidence in FINDINGS:
        if store.get(f"finding/{name}") is not None and not args.force:
            stats["kept"] += 1
            continue
        _, changed = store.save({"name": name, "category": "finding", "tier": 1, "workstream": ws,
                                 "statement": statement, "cites": cites, "evidence_tier": tier, "limits": limits,
                                 "evidence": evidence, "provenance": PROV}, layer="model")
        stats["written" if changed else "kept"] += 1
    if missing:
        print(f"methods without a rank in this table: {missing}", file=sys.stderr)
    print(json.dumps(stats))
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
