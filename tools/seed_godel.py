#!/usr/bin/env python3
"""seed_godel — the expanding Gödel model's foundation (docs/MATH_CORE.md phase 0).

  core_type      the semantic core's types: Bool, Int, Nat, BV (fixed-width bit-vectors), Array (memory), Tuple,
                 Float; each with the operations that act on it and the laws that make it what it is
  godel_set      the Gödel sets: B0 (the basis) and computation (the op cards beyond the IR's basis)
  godel          the prime ledger, appended through engines/godel.py (never rewritten)
  law/CM43, goal/G_U5

Run: ``python3 -B tools/seed_godel.py`` (cards are kept unless ``--force``; the ledger only ever appends).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.engines import godel as GD  # noqa: E402
from cardmodel.engines.context import Ctx  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_godel.py"}

REGISTRIES = {
    "core_type": "The semantic core's types (docs/MATH_CORE.md section 4): what a term's values are.",
    "godel_set": "Gödel sets: the basis B0 and the domains that extend it; each atom of the ledger names the set it "
                 "entered with.",
    "godel": "The prime ledger of the expanding Gödel model (engines/godel.py): append-only, one atom per prime.",
}

TYPES = [
    ("Bool", "Truth values: true and false.", [], ["AND", "OR", "NOT", "CMP_EQ", "CMP_NE", "CMP_LT", "CMP_LE",
                                                 "CMP_GT", "CMP_GE", "IF_EXPR"],
     ["AND and OR are associative, commutative and idempotent", "NOT NOT p == p", "de Morgan"]),
    ("Int", "Unbounded integers: the IR's integer semantics (floor division, the sign of a modulus follows the "
     "divisor).", [], ["ADD", "SUB", "MUL", "NEG", "ABS", "FLOORDIV", "MOD", "MIN", "MAX", "POW", "GCD", "POW_MOD"],
     ["a ring: ADD and MUL associative and commutative, MUL distributes over ADD",
      "(a // b) * b + a % b == a for b != 0"]),
    ("Nat", "Natural numbers: Int restricted to n >= 0, with Lean's truncated subtraction where it is imported.",
     [], ["ADD", "MUL", "FLOORDIV", "MOD", "MIN", "MAX", "POW", "GCD"], ["a commutative semiring"]),
    ("BV", "Fixed-width bit-vectors BV(w): the integers modulo 2^w, with bitwise operations. The instruction cards "
     "(LR35902: w = 8, 16; ARM: w = 32) compute in it by masking.", ["w"],
     ["ADD", "SUB", "MUL", "BIT_AND", "BIT_OR", "BIT_XOR", "BIT_NOT", "SHIFT_LEFT", "SHIFT_RIGHT"],
     ["every result is taken mod 2^w", "BIT_AND, BIT_OR, BIT_XOR form a Boolean ring", "x << k == x * 2^k mod 2^w"]),
    ("Array", "Total maps from an index type to a value type: memory is Array(BV(a), BV(8)). Reading a cell after "
     "writing it gives what was written; other cells are unchanged.", ["index", "value"], [],
     ["select(store(m, i, v), i) == v", "select(store(m, i, v), j) == select(m, j) for i != j"]),
    ("Tuple", "Finite products of types: a machine state is a tuple of registers, flags and memory.", ["types"], [],
     ["projections of a pair recover its parts"]),
    ("Float", "IEEE 754 binary64: the IR's float semantics; not a field (rounding), so laws hold only as witnessed "
     "within tolerances.", [], ["ADD", "SUB", "MUL", "DIV", "TO_FLOAT", "TRUNC_INT"],
     ["ADD and MUL are commutative but not associative"]),
]

SETS = [
    ("B0", None, "The basis: the core types, the logic primitives and the IR's operations. Every other set extends "
                 "it."),
    ("computation", "B0", "The op cards beyond the IR's basis (squares, modular inverses, elliptic-curve "
                          "operations, ...): atoms of the computing domain, each to be defined over B0 where it can."),
]

LAWS = [
    ("CM43_primes_are_forever", "The Gödel model's atoms take primes in an append-only ledger: an atom keeps its "
     "prime forever, a new atom takes the next unused prime, and no line is renumbered or removed. A concept's "
     "content vector (its factorization over the atoms) and its structural number (Gödel's positional numbering, "
     "the identity) are computed from the ledger; carrying between Gödel sets is a map of atoms, which preserves "
     "every GCD exactly when distinct atoms go to disjoint supports, and whose gap is what it cannot send.",
     ["user requirement 2026-10-22 (a universal Gödel model that keeps expanding)", "Gödel 1931"],
     "tests/test_godel.py::test_ledger_is_append_only"),
]

GOALS = [
    ("G_U5_content_vectors", "understanding", "Fraction of op, function and algorithm cards whose content vector is "
     "computed (their terms read into atoms of the ledger).", "content_vector_coverage", 1.0, "higher"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    root = store.layer_root("model")
    for reg, desc in REGISTRIES.items():
        d = root / reg
        d.mkdir(parents=True, exist_ok=True)
        f = d / "_category.json"
        if not f.exists() or args.force:
            meta = {"name": reg, "description": desc, "tier": 0, "defined_by": "tools/seed_godel.py"}
            f.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    store.invalidate()
    stats = {"written": 0, "kept": 0}

    def put(card):
        if store.get(f"{card['category']}/{card['name']}") is not None and not args.force:
            stats["kept"] += 1
            return
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1

    for name, statement, params, ops, laws in TYPES:
        put({"name": name, "category": "core_type", "tier": 0, "statement": statement, "params": params,
             "operations": [f"op/{o}" for o in ops], "laws": laws, "provenance": PROV})
    for name, extends, statement in SETS:
        put({"name": name, "category": "godel_set", "tier": 0, "statement": statement, "extends": extends,
             "provenance": PROV})
    for name, statement, origins, witness in LAWS:
        put({"name": name, "category": "law", "tier": 0, "statement": statement, "origins": origins,
             "witness": witness, "provenance": PROV})
    for name, axis, statement, metric, target, direction in GOALS:
        put({"name": name, "category": "goal", "tier": 0, "axis": axis, "statement": statement, "metric": metric,
             "target": target, "direction": direction, "provenance": PROV})
    store.invalidate()
    ctx = Ctx(store)
    new = GD.sync(store, GD.basis_atoms(store, ctx.ops), "B0")
    rest = sorted(f"op/{c.name}" for c in store.cards("op") if c.name not in ctx.ops)
    new += GD.sync(store, rest, "computation")
    stats["ledger_appended"] = len(new)
    stats["ledger"] = len(GD.ledger(store))
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
