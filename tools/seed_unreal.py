#!/usr/bin/env python3
"""seed_unreal — the cards that make a game engine's math part of the model (docs/UNREAL.md, law CM49).

  op            the atoms the engine's math reaches beyond the IR's basis (cardmodel/unreal/atoms.py): the C
                library's real functions, F32 (binary32 rounding) and the bits of floats; only the atoms the
                latest scan's lifted terms use (``--all`` writes every one)
  godel         their primes, appended to the ledger (sets analysis and bits)
  godel_set     analysis, bits and unreal (the engine's named functions; their atoms are appended by
                ``cardmodel unreal scan --save``)
  method        lift_cpp and normal_form (method/witness and method/human_written exist)
  unreal_math, unreal_use, unreal_cause    their registries and card types
  law/CM49, goals G_U10-G_U12

Run: ``python3 -B tools/seed_unreal.py`` (cards are kept unless ``--force``; the ledger only ever appends).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.engines import godel as GD  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402
from cardmodel.unreal import atoms as A  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_unreal.py"}

REGISTRIES = {
    "unreal_math": ("A game engine's math as observed: one card per function of Unreal Engine's math (its file and "
                    "line, type, use), lifted to a definition, outside the math universe, or a gap with its cause "
                    "(cardmodel/unreal, law CM49).", {"required": ["qual", "file", "status", "use"],
                                                      "properties": {"qual": {"type": "string"},
                                                                     "file": {"type": "string"},
                                                                     "status": {"enum": ["lifted", "gap", "outside",
                                                                                         "refuted"]},
                                                                     "use": {"type": "string"}}}),
    "unreal_use": ("What the engine's math is for: per use its members, and the logic they all share (the GCD of their "
                   "Gödel content) and all need (the LCM).", {"required": ["statement", "members"],
                                                              "properties": {"members": {"type": "integer"}}}),
    "unreal_cause": ("Why an engine function is not lifted, and what would close it.",
                     {"required": ["statement", "closes_by"], "properties": {"closes_by": {"type": "string"}}}),
}

# an engine function's card says what became of it
STATUS_VALUES = {"unreal_math": ["lifted", "gap", "outside", "refuted"]}

SETS = [
    ("analysis", "B0", "Real analysis as the C library computes it: square roots, the trigonometric, exponential and "
     "logarithmic families, rounding to integers, fmod, and F32 (rounding to binary32). Atoms of every program that "
     "computes with floats; Unreal Engine's math reached them first.",
     "core terms over the set's op atoms and those of B0, integer constants and variables"),
    ("bits", "B0", "A float's bits as an integer and back, and bit counting: the atoms of bit-level numeric code "
     "(sign tricks, float packing, integer logarithms).",
     "core terms over the set's op atoms and those of B0, integer constants and variables"),
    ("unreal", "analysis", "Unreal Engine's math: each function of its math universe is an atom (its named "
     "vocabulary). The carry map sends a lifted function to the Gödel content of its canonical form over B0, "
     "analysis and bits; a function that is a gap has no image, and that is the map's gap.",
     "core terms over the engine's functions (each applied to its arguments) and the atoms of analysis and B0, "
     "integer constants and variables"),
]

METHODS = [
    ("lift_cpp", "cardmodel/unreal/lift.py", "a C++ function's meaning as core terms, by symbolic execution of the "
     "typed AST clang builds (templates instantiated, macros expanded, overloads resolved): records as scalar slots, "
     "branches merged as IF_EXPR, calls inlined, the C library as atoms", "linear in the unrolled function; loops "
     "whose condition depends on the inputs, pointer arithmetic, type punning, bitfields and recursion are gaps "
     "with their causes; signed overflow is assumed absent", "loops without a constant bound",
     {"decides": "decidable", "question": "the core terms symbolic execution gives a C++ function within its budgets, "
      "or the cause that stops it", "general": "does the lifted term equal the compiled function on every input",
      "general_rank": "Π1", "why": "the lift is a total procedure with step and size budgets; equality with the "
      "compiled code is a ∀ over the inputs, refuted by one counterexample (the witness), undecidable in general "
      "(Rice)", "cites": ["Ph-15"]}),
    ("normal_form", "cardmodel/engines/realnorm.py", "equality over the reals for the polynomial fragment with "
     "uninterpreted atoms: a canonical polynomial with exact rational coefficients, comparisons and conditions "
     "normalized, odd and even functions signed", "identities between atoms beyond parity (sin² + cos² = 1, "
     "sqrt(x)² = x) are not used, so equal terms may keep different forms; expansion is bounded",
     "polynomial size (MAX_TERMS)",
     {"decides": "decidable", "question": "whether two terms have one canonical form: a polynomial with rational "
      "coefficients over uninterpreted atoms", "general": "are two real functions equal wherever both are defined",
      "general_rank": "Π1", "why": "normalizing is a total computation; equality of real functions built from sin, "
      "exp and the rest is undecidable (Richardson 1968), and a difference is shown by one point, so the general "
      "question is a ∀ (Π1) for continuous functions", "cites": ["Ph-15"]}),
]

LAWS = [
    ("CM49_engine_math_is_distilled", "A game engine's math is read through the real compiler (its typed AST, "
     "templates instantiated, its scalar path) and becomes cards: every function of the math universe is lifted to "
     "terms over the ledger's atoms or carries the cause that stops it; each lifted function has a definition whose "
     "canonical form over the reals, semantic hash, Gödel content, number and structural tokens are computed, and "
     "whose action is the engine's own compiled code, linked by a witness on seeded inputs that a planted wrong "
     "term fails; equal canonical forms are identities, and every function is an atom of the engine's Gödel set, "
     "carried to its definition's content.",
     ["user requirement 2026-10-22 (distill my Unreal Engine's math into the model, by use, with its Gödel logic "
      "carrying)", "CM43", "CM44", "Pheros L41"],
     "tests/test_unreal.py::test_engine_math_is_distilled_and_witnessed"),
]

GOALS = [
    ("G_U10_engine_math_lifted", "understanding", "Fraction of the engine's math universe (functions over numbers) "
     "lifted to definitions.", "unreal_lifted_fraction", 0.9, "higher"),
    ("G_U11_engine_math_witnessed", "understanding", "Fraction of the engine's definitions witnessed against its "
     "compiled code (bit-exact or within a few ulps).", "unreal_witnessed_fraction", 0.9, "higher"),
    ("G_U12_engine_math_refuted", "understanding", "Engine functions whose lifted term the witness refutes (a lifter "
     "error, or a difference between the engine's scalar and shipped paths).", "unreal_refuted", 0, "lower"),
]


def used_atoms(root: Path) -> set[str]:
    """Atoms the latest scan's lifted terms use (state/unreal/*/scan.jsonl), if there is one."""
    from cardmodel.unreal import distill as D
    from cardmodel.unreal import scan as S
    out: set[str] = set()
    for d in sorted(p for p in (root / "state" / "unreal").glob("*") if p.is_dir()):
        for f in S.functions(d):
            for o in f.get("outputs") or []:
                out |= {a.split("/", 1)[1] for a in D.content(o["term"])}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--all", action="store_true", help="write every atom's op card, used or not")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    root = store.layer_root("model")
    stats = {"written": 0, "kept": 0}

    def put(card):
        old = store.get(f"{card['category']}/{card['name']}")
        if old is not None and not args.force:
            merged = {**dict(old), **card}          # the seed's own fields kept current; fields others add are kept
            if merged == dict(old):
                stats["kept"] += 1
                return
            card = merged
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1

    for reg, (desc, schema) in REGISTRIES.items():
        d = root / reg
        d.mkdir(parents=True, exist_ok=True)
        f = d / "_category.json"
        meta = {"name": reg, "description": desc, "tier": 1, "defined_by": "tools/seed_unreal.py", "card_type": reg}
        if reg in STATUS_VALUES:
            meta["status_values"] = STATUS_VALUES[reg]
        text = json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        if not f.exists() or f.read_text(encoding="utf-8") != text:        # generated: kept in step with this file
            f.write_text(text, encoding="utf-8")
        store.invalidate()
        put({"name": reg, "category": "card_type", "tier": 0, "applies_to": [reg], "statement": desc,
             "schema": {"type": "object", **schema}, "provenance": PROV})
    used = used_atoms(ROOT)
    ops = [n for n in A.OPS if args.all or n in used]
    for n in ops:
        put(A.card(n))
    b0 = (store.get("godel_set/B0") or {}).get("numbering") or {}
    for name, extends, statement, objects in SETS:
        numbering = {k: b0[k] for k in ("cites", "code", "conditions", "content", "identity", "provability")
                     if k in b0}
        numbering.update(objects=objects, witness="tests/test_unreal.py::EngineSets::test_the_sets_are_admissible")
        if name == "unreal":
            numbering.update(arities_from="the card's arities, written by `cardmodel unreal scan --save` from each "
                             "function's signature: its parameters, and the object for a non-static member")
        put({"name": name, "category": "godel_set", "tier": 0, "extends": extends, "statement": statement,
             "numbering": numbering, "provenance": PROV})
    for name, proc, decides, limits, complexity, rank in METHODS:
        put({"name": name, "category": "method", "tier": 0, "procedure": proc, "decides": decides, "limits": limits,
             "complexity": complexity, "status": "built", "statement": decides, "rank": rank, "provenance": PROV})
    for name, statement, origins, witness in LAWS:
        put({"name": name, "category": "law", "tier": 0, "statement": statement, "origins": origins,
             "witness": witness, "provenance": PROV})
    for name, axis, statement, metric, target, direction in GOALS:
        put({"name": name, "category": "goal", "tier": 0, "axis": axis, "statement": statement, "metric": metric,
             "target": target, "direction": direction, "provenance": PROV})
    store.invalidate()
    new = []
    for set_name in ("analysis", "bits"):
        new += GD.sync(store, [f"op/{n}" for n in ops if A.OPS[n]["set"] == set_name], set_name)
    print(f"seed_unreal: {stats['written']} written, {stats['kept']} kept; {len(ops)} atoms "
          f"({', '.join(ops)}); {len(new)} appended to the ledger")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
