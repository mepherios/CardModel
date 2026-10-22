#!/usr/bin/env python3
"""seed_sources — the four sources (docs/MATH_CORE.md phase 1): truth, transformation, action, method.

  definition, action, transformation, method   the registries and their card types
  method/*        the procedures the model runs between sources, with what each decides and its limits
  law/CM44, goal/G_U6, G_U7, G_A9
  the generated packs: definitions, actions and transformations derived from the algorithm, function and
  functional identity cards (engines/sources.py ``build``); rerun after those cards change

Run: ``python3 -B tools/seed_sources.py [--seed N]`` (directory cards kept unless ``--force``; packs regenerated).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.engines import sources as SO  # noqa: E402
from cardmodel.engines.context import Ctx  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_sources.py"}

REGISTRIES = {
    "definition": "Truth: what a function means, as a term of the semantic core, with its canonical form, its Gödel "
                  "content and number, its proof obligations and its origin (docs/MATH_CORE.md).",
    "action": "Action: an implementation in a language, linked to its definition by a proof or a witness.",
    "transformation": "Transformation: an equivalence between two definitions with its evidence (rewrite rules, "
                      "redefinitions and laws are transformations of terms in their own registries).",
    "method": "Method: a procedure the model runs between the sources, with what it decides and its limits.",
}

CARD_TYPES = {
    "definition": {"required": ["subject", "math", "canonical", "godel", "proof_obligations", "actions", "origin",
                                "methods"],
                   "statement": "A definition (truth): the term, the canonical form, the Gödel numbers, the obligations."},
    "action": {"required": ["truth", "lang", "code", "method", "link"],
               "statement": "An action: code that does what its definition says, linked by a proof or a witness."},
    "transformation": {"required": ["from", "to", "evidence"],
                       "statement": "A transformation: two definitions shown equal, with the evidence."},
    "method": {"required": ["procedure", "decides", "limits", "status"],
               "statement": "A method: a procedure, what it decides, its complexity and its limits."},
}

METHODS = [
    ("lift_python", "cardmodel/engines/frontend_python.py", "a Python function's meaning as a core term, exactly, "
     "for the supported subset", "linear in the source", "no strings, lists or classes yet; unsupported constructs "
     "are reported, never guessed", "built"),
    ("saturate", "cardmodel/engines/egraph.py", "equality of terms reached by the rule cards and discovered laws; the "
     "cheapest term of the class (the canonical form)", "bounded by iterations and nodes", "not shown equal is not "
     "unequal; conditional rules are left out", "built"),
    ("fit_recurrence", "cardmodel/engines/funcalg.py", "the shortest linear recurrence of a one-integer function, its "
     "canonical form and Gödel number", "quadratic in the order", "fitted from values and checked on unused terms, "
     "not proved; no form when the behaviour is not a linear recurrence", "built"),
    ("emit", "cardmodel/engines/codegen.py", "code in any language card from a core term", "linear in the term",
     "a language card without a template for an op is a gap; correctness is witnessed by running, not proved",
     "built"),
    ("witness", "cardmodel/engines/witness.py", "agreement of two implementations on seeded inputs", "one run per "
     "input", "sampling: it can refute, never prove", "built"),
    ("lean_kernel", "cardmodel/emit/lean.py", "a statement, with a proof the Lean kernel accepts",
     "depends on the tactic", "the statement must be expressible in Lean; failing tactics are not a disproof",
     "built"),
    ("human_written", "a person", "nothing by itself: what a person wrote is checked by the other methods",
     "n/a", "everything a person writes is witnessed or proved before it counts", "built"),
    ("learn", "cardmodel/engines/learn.py", "new cards from observed code, promoted only with evidence",
     "linear in the observed tree", "names and statistics, not semantics, for code it cannot lift", "built"),
    ("symbolic_execution", "cardmodel/machine/symbolic.py", "an instruction card's meaning as core terms over "
                           "symbolic registers and memory (MATH_CORE phase 0, F5)", "linear in the semantics",
     "checked against the executable semantics exhaustively on small widths", "planned"),
]

LAWS = [
    ("CM44_everything_traces_to_truth", "Every artifact traces back to the four sources. An action names its truth (a "
     "definition) and the method that made it, and links to it by a proof, a witness or as its source, never "
     "refuted; a transformation names the two truths it relates and its evidence; a definition names its origin and "
     "carries its Gödel content over the ledger's atoms; a method states what it decides and its limits. Code is an "
     "action of a definition, and optimizing is the cheapest proven chain from truth through transformations to an "
     "action.", ["user requirement 2026-10-22 (source of truth, action, transformation and method as the goal)"],
     "tests/test_sources.py::test_every_artifact_traces_back"),
]

GOALS = [
    ("G_U6_definitions", "understanding", "Fraction of algorithm and function cards with a definition card (truth).",
     "definition_coverage", 1.0, "higher"),
    ("G_U7_canonical_definitions", "understanding", "Fraction of definitions with a canonical form (an e-graph's "
     "cheapest term, or a recurrence's canonical form).", "canonical_definitions", 0.9, "higher"),
    ("G_A9_actions_without_truth", "autonomy", "Actions (implementations) that name no definition (CM44).",
     "actions_without_truth", 0, "lower"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--seed", type=int, default=20261022)
    args = ap.parse_args(argv)
    store = open_store(project=False)
    root = store.layer_root("model")
    for reg, desc in REGISTRIES.items():
        d = root / reg
        d.mkdir(parents=True, exist_ok=True)
        f = d / "_category.json"
        if not f.exists() or args.force:
            meta = {"name": reg, "description": desc, "tier": 0, "defined_by": "tools/seed_sources.py",
                    "card_type": reg}
            if reg == "method":
                meta["status_values"] = ["built", "planned"]
            f.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    store.invalidate()
    stats = {"written": 0, "kept": 0}

    def put(card):
        if store.get(f"{card['category']}/{card['name']}") is not None and not args.force:
            stats["kept"] += 1
            return
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1

    for name, spec in CARD_TYPES.items():
        put({"name": name, "category": "card_type", "tier": 0, "applies_to": [name], "statement": spec["statement"],
             "metadata": {"version": "1.0.0"}, "provenance": PROV,
             "schema": {"type": "object", "required": spec["required"], "properties": {}}})
    for name, procedure, decides, complexity, limits, status in METHODS:
        put({"name": name, "category": "method", "tier": 0, "procedure": procedure, "decides": decides,
             "complexity": complexity, "limits": limits, "status": status, "statement": decides, "provenance": PROV})
    for name, statement, origins, witness in LAWS:
        put({"name": name, "category": "law", "tier": 0, "statement": statement, "origins": origins,
             "witness": witness, "provenance": PROV})
    for name, axis, statement, metric, target, direction in GOALS:
        put({"name": name, "category": "goal", "tier": 0, "axis": axis, "statement": statement, "metric": metric,
             "target": target, "direction": direction, "provenance": PROV})
    store.invalidate()
    ctx = Ctx(store)
    built = SO.build(ctx, seed=args.seed)
    stats.update(SO.write(ctx, built))
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
