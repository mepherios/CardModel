#!/usr/bin/env python3
"""seed_pipeline — every capability in the main pipeline, at a stated tier (law CM50, engines/pipeline.py).

  capability/*.pipeline   per capability: the tier of the evidence its pipeline run gives (CM46), why that tier,
                          the verify sections and self-run steps that exercise its engine, and, where part of it runs
                          nowhere in the pipeline, the gap with its reason, what would close it and its goal
  card_type/capability    the schema gains ``pipeline`` (required)
  capability/integration  carries CM50, its module and witness test
  law/CM50                every capability runs in the main pipeline
  goal/G_A13              recorded pipeline gaps: 0

The declarations are checked against the code by the ``pipeline`` verify section (a declared run whose stage does
not reach the capability's code fails), so editing them here is not enough to make a capability run. The
tier is the weakest the pipeline run guarantees for the capability's claims: a run that proves some claims and
samples others is ``sample``.

Run: ``python3 -B tools/seed_pipeline.py`` (writes through the store, so every changed card is versioned, CM14).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_pipeline.py"}
GOAL = "goal/G_A13_pipeline_gaps"


def V(*sections):
    return [{"verify": s} for s in sections]


def S(*steps):
    return [{"self_step": s} for s in steps]


# name: (tier, why that tier, runs, gap or None)
PIPELINE = {
    "card_store": ("bounded", "the kernel section validates every card of the store against its type's schema, every "
                   "load error and every reference: exhaustive over the store as loaded",
                   V("kernel"), None),
    "honest_limits": ("bounded", "a probe is a direct observation of this host; the sections that depend on one "
                      "report unavailable or inconclusive with its reason: exhaustive over the tools this host has",
                      V("redefinitions", "conformance"), None),
    "witnesses": ("sample", "every op, call and rule card is witnessed on seeded inputs (the known-answer vectors are "
                  "fixed samples): agreement on the inputs run, not for all inputs",
                  V("forms", "vectors", "rules"), None),
    "form_selection": ("sample", "the forms chosen are the available ones, witnessed and timed on seeded inputs on "
                       "this host; costs are measurements, not bounds",
                       V("forms") + S("optimize"), None),
    "boundaries": ("bounded", "the program's text is scanned whole for source-folder references and publishing "
                   "calls: exhaustive over the files, blind to what they compute",
                   V("integrity", "selfcheck"), None),
    "learning": ("sample", "learned functions are promoted only when every language they ran in agreed on seeded "
                 "inputs", S("learn", "observe_self"), None),
    "translation": ("sample", "emission into a real language is witnessed by running against the source, never "
                    "proved (MATH_CORE §8)", V("conformance", "functions"), None),
    "rewriting": ("sample", "rewrites are justified by rules witnessed on seeded inputs; the arena checks each "
                  "optimized program by running it", S("learn", "arena"), None),
    "law_discovery": ("sample", "candidates are witnessed on seeded inputs; those Lean proves are at tier proof, the "
                      "rest stay samples, so the step guarantees sample", S("laws"), None),
    "theorems": ("sample", "every theorem card is re-witnessed with the run's seed; Lean-imported ones are proofs, "
                 "the rest samples", V("theorems"), None),
    "lean": ("proof", "the proofs section has Lean's kernel check every rule theorem it emits (skipped, with its "
             "reason, on a host with no Lean toolchain); the theorems section holds Lean-imported cards to it",
             V("theorems", "proofs"), None),
    "logic": ("bounded", "the self theory is evaluated to its fixpoint over every fact of the store, within the "
              "logic budget: exhaustive within those bounds", V("logic"), None),
    "card_language": ("sample", "every program under examples/lang and stdlib is compiled and run: its tests are "
                      "fixed inputs", V("lang"), None),
    "self_theory": ("bounded", "the model's laws as logic (stdlib/self.card) evaluated over the whole store: zero "
                    "violations is exhaustive over the store", V("logic"), None),
    "function_algebra": ("sample", "canonical forms and identities are found from and checked on computed terms of "
                         "each algorithm; no order bound turns them into a proof here", S("algebra"), None),
    "redefinitions": ("sample", "executable identities are checked numerically on seeded points (symbolically when "
                      "sympy is present)", V("redefinitions"), None),
    "improve": ("sample", "the arena's optimized programs are run against the originals on seeded inputs",
                S("arena"), None),
    "resources": ("sample", "the governor's limits are what the runs under it measured on this host",
                  V("conformance") + S("store"), None),
    "game_design": ("proof", "the design laws are checked on the exact equilibrium (rational simplex) with its "
                    "certificate checked: a finite witness sized by LP duality", V("game"), None),
    "world": ("sample", "the world is run for a fixed number of ticks from fixed seeds and its carry, cause and "
              "impact rules checked on that run", V("game"), None),
    "machines": ("sample", "every instruction card runs on seeded states in every engine and the results agree",
                 V("machine"), None),
    "emulation": ("sample", "the store step runs every listed cartridge in its player and compares the picture with "
                  "what the system's cards compute for the same bytes, frame by frame",
                  S("store"),
                  {"reason": "the pipeline runs cartridges interpreted or native; lifted ROM code (machine/lift.py, "
                             "CM33: lifted code is the cards) runs only in the smoke check (8 frames of an assembled "
                             "ROM) and in `cardmodel machine diff`, never on the library's cartridges",
                   "closes_by": "the machine section (or the store step) runs the lifted engine on each system's check "
                                "cartridge and requires its frames to equal the interpreter's",
                   "goal": GOAL}),
    "arcade": ("sample", "every catalogue item is installed, verified, repaired and played through the store for a "
               "fixed number of frames", S("store"), None),
    "live_hub": ("bounded", "the projects section computes every project card's status through the hub: exhaustive "
                 "over the project cards", V("projects") + S("store"), None),
    "anyps5": ("bounded", "every gap of the saved scan is classified and its semantics programs run (skipped, with "
               "its reason, when no scan is in the store)", V("anyps5"), None),
    "godel_model": ("bounded", "the prime ledger and every content vector are checked whole against the storage "
                    "rules and the last commit", V("godel", "sources"), None),
    "self_run": ("sample", "a cycle is one run on this host: its findings and plan are what that run measured",
                 [{"cycle": "self run"}] + S("goals"), None),
    "distillation": ("sample", "the arena's rewrites go through equality saturation over witnessed rules; the result "
                     "is run against the original", S("arena"), None),
    "integration": ("bounded", "the integrity and pipeline checks read every law, goal, capability, command, "
                    "section and doc: exhaustive over names and text, blind to meaning", V("integrity", "pipeline"),
                    None),
    "symbolic_instructions": ("sample", "each instruction's terms are evaluated against the bench's run of its "
                              "executable semantics on seeded states (MATH_CORE phase 0 names the proof as next)",
                              V("machine"), None),
    "four_sources": ("bounded", "every definition, action, transformation and method is traced: exhaustive over the "
                     "four registries; the links themselves carry their own tiers", V("sources"), None),
    "witness_tiers": ("bounded", "the census reads the tier of every claim in the store and fails on one without: "
                      "exhaustive over the store", V("tiers"), None),
    "formal_core": ("proof", "formal/GodelCore is built by Lean's kernel with no sorry and only the standard axioms "
                    "(skipped, with its reason, on a host with no Lean toolchain)", V("formal"), None),
    "unreal_math": ("sample", "lifted terms are witnessed against the compiled code on seeded cases (the engine's "
                    "sample where its scan is saved, every fixture function otherwise)", V("unreal"), None),
}

LAW = ("CM50_every_capability_runs_in_the_pipeline",
       "Every capability runs in the main pipeline: its card declares the tier of the evidence that run gives (CM46) "
       "and the verify sections or self-run steps that exercise its engine, and the pipeline check holds each "
       "declared stage to the code (it must reach the capability's modules). A capability that no stage runs, or "
       "part of one, is a recorded gap with its reason, what would close it and the goal that counts it; a "
       "capability with neither a run nor a gap fails verify. The smoke check (CM37) does not count as running.",
       ["user requirement 2026-11-05 (every capability in the main pipeline, with its tier and a coverage check)"],
       "tests/test_pipeline.py::test_a_capability_never_run_fails")

GOALS = [("G_A13_pipeline_gaps", "autonomy",
          "Recorded pipeline gaps: capabilities, or parts of them, that no verify section or self-run step exercises "
          "(CM50; `cardmodel pipeline` lists them with their reasons).", "pipeline_gaps", 0, "lower")]

SCHEMA_PIPELINE = {
    "type": "object", "required": ["tier", "tier_reason", "runs"],
    "properties": {"tier": {"type": "string", "enum": ["proof", "probabilistic", "bounded", "sample"]},
                   "tier_reason": {"type": "string"},
                   "runs": {"type": "array", "items": {"type": "object"}},
                   "gap": {"type": "object", "required": ["reason", "closes_by", "goal"],
                           "properties": {"reason": {"type": "string"}, "closes_by": {"type": "string"},
                                          "goal": {"type": "string"}}}}}


def main(argv=None) -> int:
    store = open_store(project=False)
    stats = {"written": 0, "kept": 0}

    def put(card):
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1

    caps = {c.name: c for c in store.cards("capability")}
    missing = sorted(set(caps) - set(PIPELINE))
    if missing:
        print(f"no pipeline declaration for: {missing}", file=sys.stderr)
        return 1
    for name, (tier, why, runs, gap) in PIPELINE.items():
        card = dict(caps[name])
        card["pipeline"] = {"tier": tier, "tier_reason": why, "runs": runs, **({"gap": gap} if gap else {})}
        if name == "integration":
            law = f"law/{LAW[0]}"
            card["laws"] = sorted(set(card.get("laws") or []) | {law})
            card["modules"] = sorted(set(card.get("modules") or []) | {"cardmodel/engines/pipeline.py"})
            card["tests"] = list(dict.fromkeys([*(card.get("tests") or []), LAW[3]]))
            card["commands"] = list(dict.fromkeys([*(card.get("commands") or []), "cardmodel pipeline"]))
        put(card)
    ct = dict(store.get("card_type/capability"))
    schema = json.loads(json.dumps(ct["schema"]))
    schema["properties"]["pipeline"] = SCHEMA_PIPELINE
    schema["required"] = list(dict.fromkeys([*schema.get("required", []), "pipeline"]))
    ct["schema"] = schema
    ct["statement"] = ("A core capability: its smoke check must pass in every verify and self-run (CM37), and it "
                       "declares its evidence tier and where the main pipeline runs it (CM50).")
    put(ct)
    name, statement, origins, witness = LAW
    put({"name": name, "category": "law", "tier": 0, "statement": statement, "origins": origins, "witness": witness,
         "provenance": PROV})
    for name, axis, statement, metric, target, direction in GOALS:
        put({"name": name, "category": "goal", "tier": 0, "axis": axis, "statement": statement, "metric": metric,
             "target": target, "direction": direction, "provenance": PROV})
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
