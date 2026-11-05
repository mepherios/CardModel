#!/usr/bin/env python3
"""seed_core_forms — the core of programming as cards (docs/GENERAL_COMPILER.md §2).

Every mainstream language desugars into a small core calculus; the model learns that core once and treats each
language as a map into it. One ``core_form`` card per construct names what the IR must have for it (types, special
forms, ops, statement kinds); ``engines/compiler_goals.py`` checks those names against the IR itself, so goal
G_C6 counts the constructs the IR really has, never a typed-in list.

Run: ``python3 -B tools/seed_core_forms.py`` (cards are kept unless ``--force``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_core_forms.py"}
REGISTRY = "core_form"

# (name, statement, what it covers in languages, what the IR must have: types / special forms / ops / statements)
FORMS = [
    ("values", "Values of sorts: unbounded integers, bit-vectors of a width, floats, booleans.",
     ["literals", "arithmetic", "comparison", "fixed-width integers"],
     {"types": ["int", "float", "bool", "u32", "f32"], "ops": ["ADD", "MUL", "CMP_LT", "WRAPU"]}),
    ("binding", "Names bound to values; assignment is rebinding (SSA's values).",
     ["variables", "let", "assignment"], {"leaves": ["var"], "statements": ["assign"]}),
    ("functions", "First-order functions, calls and recursion.",
     ["functions", "procedures", "methods without dispatch", "recursion"],
     {"special": ["CALL"], "statements": ["return"]}),
    ("control", "Branches, and loops as fixpoints.",
     ["if", "while", "for", "switch", "break", "continue"],
     {"special": ["IF_EXPR"], "statements": ["if", "while", "for_range", "switch", "break", "continue"]}),
    ("memory", "Addresses, load and store over an array sort, with references that alias.",
     ["pointers", "arrays", "mutable objects", "the heap"],
     {"types": ["ref"], "special": ["LOAD"], "statements": ["store"]}),
    ("records", "Products and sums of sorts: tuples, records, variants.",
     ["structs", "class fields", "enums", "None/Option", "tagged unions", "argument records (varargs, keywords)"],
     {"types": ["record", "variant"]}),
    ("closures", "Functions as values: a function with its captured variables, called indirectly.",
     ["lambdas", "callbacks", "objects (a record of closures)", "dynamic dispatch", "iterators", "nested defs"],
     {"special": ["CLOSURE", "CALL_INDIRECT"]}),
    ("handlers", "Control as effects: one handler construct for non-local exits.",
     ["exceptions (raise/try)", "early return from inside", "generators/yield", "async/await"],
     {"statements": ["raise", "try"]}),
    ("boundary", "Effects at the boundary: a call the model does not lift, made to the real implementation and "
     "witnessed (opaque boundary cards, CM21, CM34).", ["I/O", "clock", "syscalls", "MMIO", "foreign code"],
     {"special": ["CALL"], "modules": ["cardmodel.engines.opaque"]}),
    ("concurrency", "Threads, atomics and interrupts.", ["threads", "async runtimes", "drivers", "two CPUs"],
     {"special": ["SPAWN"], "ops": ["ATOMIC_CAS"]}),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    store.ensure_registry(REGISTRY, "model", description="The core of programming (docs/GENERAL_COMPILER.md §2): "
                          "one card per construct every language desugars into, naming what the IR must have for "
                          "it.", tier=0)
    stats = {"written": 0, "kept": 0}
    for i, (name, statement, covers, requires) in enumerate(FORMS, 1):
        card = {"name": name, "category": REGISTRY, "tier": 0, "order": i, "statement": statement,
                "covers": covers, "requires": requires, "provenance": PROV}
        if store.get(f"{REGISTRY}/{name}") is not None and not args.force:
            stats["kept"] += 1
            continue
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1
    print(stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
