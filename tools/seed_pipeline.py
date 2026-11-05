#!/usr/bin/env python3
"""seed_pipeline — the stage registry: every step of the input-to-output path as a card (law CM50).

  stage           one card per stage of the pipeline (engines/pipeline.py): its group, order, hypothesis (the facts
                  of an input's profile it needs, and the ones that exclude it), the stages it needs, the engines
                  its function reaches, and the definitions and rules of docs/FOUNDATIONS.md it rests on
  card_type/stage the schema
  law/CM50        every applicable stage runs, or the record says why not
  capability/pipeline, goal/G_A13_pipeline_coverage

Run once: ``python3 -B tools/seed_pipeline.py`` (``--force`` rewrites, with versioning). Reads nothing outside the
repository. Law numbers are allocated in docs/INTEGRATION.md. The engines that no stage reaches are named in
``cards/stage/_category.json`` under ``outside`` with the reason each is not a step of this path; the coverage check
(``cardmodel pipeline check``) fails when an engine is neither reached nor named there.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_pipeline.py"}
E = "cardmodel/engines/"

DESCRIPTION = ("The stages of the pipeline from an input to its outputs (engines/pipeline.py): each a conditional over "
               "the input's profile, so the set of stages that run on an input is computed from these cards and every "
               "one that applies runs or says why not (CM50). `outside` names the engines that are no step of this "
               "path, with the reason.")

# engines that are no stage of the function pipeline, each with its reason (the coverage check reads this map)
OUTSIDE = {
    E + "arena.py": "the arena runs card-language programs against each other (`cardmodel arena`): a game loop over "
                    "whole programs, not a step on one function",
    E + "capabilities.py": "the smoke checks of the core (CM37) call the engines, the pipeline among them, from "
                           "`verify` and the self-run; a check is not a step of the path it checks",
    E + "codefacts.py": "facts about a whole source tree for `observe` and `learn` (which constructs occur where): a "
                        "corpus reading, not a transformation of one function",
    E + "codes.py": "the positional and arithmetic codes of whole Gödel sets (`cardmodel godel`): bookkeeping of the "
                    "ledger, read by the content stage through godel.py",
    E + "conformance.py": "the op x language matrix (CM17) measures the language cards themselves over every op; the "
                          "targets stages measure one function's forms",
    E + "coverage.py": "the goals' metrics read from the latest verify and self-run; it reads the pipeline's coverage, "
                       "it is not a stage of it",
    E + "difficulty.py": "difficulty of a whole card set for the self-run's choice of work; no step of one input's path",
    E + "docs.py": "generates LAWS.md, GOALS.md and the floors from the cards (`cardmodel docs`): documentation of "
                   "the model, not a transformation of an input",
    E + "formal.py": "the formal core in Lean (T1-T6) checks the theory's own theorems; the proofs are of the model, "
                     "not of one input",
    E + "godel1931.py": "the historical construction (Gödel 1931) as a card set, read by `cardmodel godel`; the "
                        "content stage uses the model's own ledger (godel.py)",
    E + "integrity.py": "the integrity check of the model's own files and cards (`verify --only integrity`): it checks "
                        "the registry, it is not a stage of it",
    E + "laws.py": "law discovery over the op cards (`cardmodel laws`) writes rewrite rules the canon and rewrite "
                   "stages then read; it runs on the signature, not on an input",
    E + "learn.py": "learning over a corpus of files (`cardmodel learn`): proposes and promotes cards from many "
                    "inputs' observations; the unit here is one function",
    E + "lift_project.py": "lifts a whole project tree (`lift-sweep`): a sweep over files, each function of which is "
                           "this pipeline's unit",
    E + "logic.py": "the logic engine (rules, queries, proofs of facts) serves `cardmodel logic` and card-language "
                    "programs; a function has no logic program",
    E + "mine.py": "mines candidate cards from a corpus for the self-run; a corpus reading, not a transformation of "
                   "one function",
    E + "observe.py": "observes a code base for named cards against fallbacks (`cardmodel observe`): a corpus "
                      "reading for learning",
    E + "projects.py": "project cards and their layering (`cardmodel status`): where the outputs go, not how an input "
                       "is transformed",
    E + "redefs.py": "redefinition cards (what a definition was redefined to and why) for `rewrite` over cards, not "
                     "over functions",
    E + "selfcheck.py": "the self-containment check (CM13, `verify --only selfcheck`): the program's own files",
    E + "selflogic.py": "the model's own card logic (the self layer) for the self-run; no step of one input's path",
    E + "selfrun.py": "the self-run cycle (CM38) schedules steps over the model, `translate` among them; it calls the "
                      "pipeline, the pipeline does not call it",
    E + "sweep.py": "sweeps a corpus through `translate` (`cardmodel sweep`): a loop over files, each function of "
                    "which is this pipeline's unit",
    E + "theorems.py": "theorem cards with their evidence (CM23) are statements about the model's cards; a function's "
                       "claims are certificates on its card (the evidence group)",
    E + "verify.py": "the verify sections (`cardmodel verify`) run every check of the model, `pipeline` among them",
    E + "witness_runner.py": "runs the law cards' witness tests for the self-run (CM20): tests of the model, not of "
                             "an input",
}

CARD_TYPE = {
    "required": ["statement", "run", "group", "order", "when"],
    "properties": {
        "run": {"type": "string"},
        "group": {"enum": ["terms", "identity", "evidence", "optimize", "targets", "record"]},
        "order": {"type": "integer"},
        "when": {"type": "array", "items": {"type": "string"}},
        "unless": {"type": "array", "items": {"type": "string"}},
        "needs": {"type": "array", "items": {"type": "string"}},
        "engines": {"type": "array", "items": {"type": "string"}},
        "foundations": {"type": "array", "items": {"type": "string"}},
        "laws": {"type": "array", "items": {"type": "string"}},
        "scope": {"enum": ["function", "file"]},
        "produces": {"type": "string"},
    },
    "statement": ("A stage of the pipeline: the function of engines/pipeline.py that runs it, the facts of an input's "
                  "profile under which it applies (`when`, `unless`), the stages it needs, the engines it reaches and "
                  "the foundations it rests on (CM50)."),
}


def L(*names):
    return [f"law/{n}" for n in names]


# name, group, order, when, unless, needs, engines, foundations, laws, statement
STAGES = [
    ("lift", "terms", 10, [], [], [], [E + "frontend_python.py", E + "frontends.py"], ["D3", "A1"],
     L("CM16_languages_are_cards"),
     "The function becomes a term of T_Σ(X) through its language card's frontend, or the gap is named with its "
     "reasons; every input starts here."),
    ("profile", "terms", 20, ["lifted"], [], ["lift"], [E + "analyse.py", E + "ir.py", E + "sorts.py"], ["D1", "D3"],
     [],
     "The facts every later hypothesis reads: the sorts that occur, whether the body is one term, has loops, "
     "recursion, calls, partial ops, and whether the source is the reference language."),
    ("reference", "terms", 30, ["lifted"], [], ["profile"], [E + "translate.py"], ["D4"],
     L("CM06_random_seeds", "CM08_executable_claims_have_witnesses"),
     "The function's value in the model M on seeded inputs: generators narrowed until the reference terminates, "
     "known-answer vectors, and the function card that carries them with a form per language card."),
    ("canon", "identity", 40, ["lifted", "straight_line"], [], ["reference"],
     [E + "egraph.py", E + "exprs.py", E + "search.py"], ["D6", "D7", "A3"], L("CM20_laws_are_cards"),
     "canon_E of a single-term function by equality saturation at its sorts: the cheapest member of its class, the "
     "laws that fired as its certificate, and its semantic hash."),
    ("identity", "identity", 50, ["lifted"], [], ["reference"],
     [E + "equivalence.py", E + "exprs.py", E + "numbering.py", E + "sources.py"], ["D7", "D9", "A4"],
     L("CM44_everything_traces_to_truth"),
     "The function's identity under a named relation: the hash of its canonical term under the laws when "
     "saturation reached one, else of its term or IR under syntax; beside it the alpha-renamed form."),
    ("content", "identity", 60, ["lifted"], [], ["reference"], [E + "godel.py"], ["D11", "D12"],
     L("CM45_content_is_a_sparse_vector"),
     "The Gödel record: content read from the canonical term where there is one, else from the IR with `read_from` "
     "saying so; a sparse vector over the ledger and the positional code when it is small."),
    ("real", "identity", 70, ["lifted", "straight_line", "int_sorted"], [], ["reference"],
     [E + "exprs.py", E + "realnorm.py"], ["D9"], [],
     "The term's normal form over ℝ: equal normal forms are equal rational functions, sound for integer "
     "polynomials, so it runs on int-sorted single-term functions."),
    ("behaviour", "identity", 80, ["lifted", "one_int_param"], [], ["reference"], [E + "funcalg.py"], ["D9"],
     L("CM31_behaviour_is_numbered"),
     "The behaviour form of a one-integer function: the linear recurrence it satisfies, checked on unused terms, "
     "its canonical description and Gödel number."),
    ("class", "evidence", 90, ["lifted", "int_sorted"], [], ["reference"], [E + "tiers.py"], ["D10"],
     L("CM46_every_claim_carries_its_tier"),
     "The function's class read from its IR (polynomial, C-finite along one input, guarded regions): the class "
     "names the theorem that sizes a finite witness, so claims about it can reach tier proof."),
    ("sized_witness", "evidence", 100, ["lifted", "canonical", "reduced", "class_known"], [], ["canon", "class"],
     [E + "codegen.py", E + "tiers.py"], ["D7", "D10"], L("CM46_every_claim_carries_its_tier"),
     "The canonical term equals the lifted term at tier proof: both forms' classes size the witness and every "
     "point agrees; a disagreement refutes the laws that fired and is a finding."),
    ("divergence", "evidence", 110, ["lifted", "pure_function"], [], ["reference"], [E + "analyse.py"],
     ["D14", "A6"], L("CM01_honest_limits"),
     "The obligations of every partial op under its path condition and the divergence laws of the targets on the "
     "reference's instrumented runs: proved by a guard, discharged by the domain, sampled, or open."),
    ("divergence_witness", "evidence", 120, ["lifted", "pure_function", "opt:deep"], [], ["divergence"],
     [E + "analyse.py"], ["D14", "A6"], L("CM01_honest_limits"),
     "Every predicted divergence run in every available runner and compared with the reference: witnessed, "
     "guarded or still predicted (on request: --deep)."),
    ("rewrite", "optimize", 130, ["lifted", "pure_function"], [], ["reference"], [E + "improve.py", E + "ir.py"],
     ["D8", "A3"], L("CM25_laws_carry_into_optimization"),
     "Every int-sorted expression replaced by its cheapest equivalent under the rule cards and saturation, the "
     "chain of laws as the certificate, the result verified against the vectors in M."),
    ("algorithm", "optimize", 140, ["lifted", "pure_function", "int_sorted"], [], ["reference"], [E + "improve.py"],
     ["A5"], [],
     "Labelled substitutions: algorithm cards whose reference form agrees with the function on probe inputs, and a "
     "closed or matrix-power form from its own recurrence; each with its tier and precondition, never a rewrite."),
    ("measure", "optimize", 175, ["lifted", "opt:measure"], [], ["witness_targets"], [E + "optimize.py"], ["D8"],
     L("CM09_measure_before_claiming"),
     "Costs measured on this host: every available generated form run on the vectors, the per-call time from the "
     "slope of two run lengths, the fastest target and each one's factor (on request: --measure)."),
    ("emit", "targets", 160, ["lifted"], [], ["reference"], [E + "codegen.py"], ["D14"],
     L("CM16_languages_are_cards"),
     "The term read in every language card with codegen: one form per card, and the gap (an op the card has no "
     "template for) named per language instead of patched."),
    ("witness_targets", "targets", 170, ["lifted"], [], ["emit"], [E + "translate.py"], ["D10", "D14"],
     L("CM17_translation_coverage_is_measured"),
     "Every generated form compiled and run on the vectors plus fresh seeded inputs and compared with the "
     "reference (tier sample); fixed-width targets only on inputs that fit."),
    ("witness_source", "targets", 180, ["lifted"], ["source_is_reference"], ["reference"], [E + "frontends.py"],
     ["D3", "D14"], L("CM17_translation_coverage_is_measured"),
     "The lift itself witnessed: the original source run by its own toolchain on the vectors and seeded inputs "
     "against the IR in M; unavailable, never silent, when the toolchain is missing."),
    ("native", "targets", 190, ["lifted", "pure_function", "source_is_reference", "host:compiler"], [],
     ["reference"], [E + "improve.py", E + "native.py", "cardmodel/machine/native.py"], ["D14"], [],
     "The native path: the function's compiled form called through ctypes inside the box of verified inputs, the "
     "original outside it; the wrapper run on the vectors and compared with the reference."),
    ("notation", "targets", 200, ["lifted", "pure_function"], [], ["reference"], [E + "mathlang.py", E + "matrix.py"],
     ["D3"], [],
     "Mathematical notation as a target: the function written as equations, read back, and compared with the IR "
     "on the vectors."),
    ("round_trip", "targets", 210, ["lifted", "pure_function"], [], ["emit"], [E + "matrix.py"], ["D14"], [],
     "lift ∘ emit_L ≈ id on the vectors for every target that also has a frontend: the frontends read the emitted "
     "text, no toolchain is needed."),
    ("record", "record", 220, ["lifted"], [], ["reference"], [], ["A7"], L("CM44_everything_traces_to_truth"),
     "The function card with everything this run found: identity, Gödel record, class, certificates and the stage "
     "record; healthy when three or more models agree and the lift is faithful; saved on request (--save)."),
]

LAWS = [
    ("CM50_every_applicable_stage_runs",
     "Every transformation from an input to its outputs runs every stage whose hypothesis the input satisfies, and "
     "its record has one entry per registered stage: ran with its evidence, or skipped, not requested, unavailable "
     "or failed with the reason. The set of stages that run is computed from the stage cards, never remembered by "
     "a command, and the coverage check fails when a stage function is named by no card, an engine is reached by "
     "no stage and named outside the pipeline by no reason, or a stage applies to nothing.",
     ["user requirement 2026-11-04 (for any transformation from input to output, every functionality we want is "
      "used properly, so nothing is overlooked in the main function; tiers of modules and submodules, all run where "
      "needed)", "docs/FOUNDATIONS.md D5 (a law is a conditional) and A1 (everything is a card)", "CM37", "CM38"],
     "tests/test_pipeline.py::test_every_applicable_stage_runs_or_says_why"),
]

CAPABILITIES = [
    ("pipeline", "The main path is a registry: every stage of the input-to-output pipeline is a card with the facts "
     "under which it applies, the runner computes which stages apply to each input and runs all of them, and the "
     "coverage check fails when an engine is unreachable from the path without a stated reason.",
     L("CM50_every_applicable_stage_runs"),
     ["tests/test_pipeline.py::test_every_applicable_stage_runs_or_says_why",
      "tests/test_pipeline.py::test_coverage_catches_an_unnamed_stage_function",
      "tests/test_pipeline.py::test_coverage_catches_a_dead_hypothesis"],
     ["docs/PIPELINE.md"], ["cardmodel translate", "cardmodel pipeline"], ["cardmodel/engines/pipeline.py"],
     "Nothing the model can do is left out of a translation by oversight: each step either runs or says why not."),
]

GOALS = [
    ("G_A13_pipeline_coverage", "autonomy", "Problems the pipeline coverage check reports (a stage function no card "
     "names, an engine no stage reaches without a reason, a stage that applies to nothing, an entry without a "
     "reason) in the latest verify (CM50).", "pipeline_coverage_problems", 0, "lower"),
]


def put(store, card: dict, force: bool, stats: dict) -> None:
    q = f"{card['category']}/{card['name']}"
    if store.get(q) is not None and not force:
        stats["kept"] += 1
        return
    _, changed = store.save(card, layer="model")
    stats["written" if changed else "kept"] += 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    stats = {"written": 0, "kept": 0}
    root = store.layer_root("model")
    d = root / "stage"
    d.mkdir(parents=True, exist_ok=True)
    f = d / "_category.json"
    if not f.exists() or args.force:
        meta = {"name": "stage", "description": DESCRIPTION, "tier": 0, "defined_by": "tools/seed_pipeline.py",
                "card_type": "stage", "outside": OUTSIDE}
        f.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    store.invalidate()
    put(store, {"name": "stage", "category": "card_type", "tier": 0, "applies_to": ["stage"],
                "statement": CARD_TYPE["statement"], "metadata": {"version": "1.0.0"},
                "schema": {"type": "object", "required": CARD_TYPE["required"], "properties": CARD_TYPE["properties"]},
                "provenance": PROV}, args.force, stats)
    for name, group, order, when, unless, needs, engines, foundations, laws, statement in STAGES:
        put(store, {"name": name, "category": "stage", "tier": 0, "run": name, "group": group, "order": order,
                    "when": when, "unless": unless, "needs": needs, "engines": engines, "foundations": foundations,
                    "laws": laws, "scope": "function", "statement": statement, "provenance": PROV},
            args.force, stats)
    for name, statement, origins, witness in LAWS:
        put(store, {"name": name, "category": "law", "tier": 0, "statement": statement, "origins": origins,
                    "witness": witness, "provenance": PROV}, args.force, stats)
    n0 = len(store.cards("capability"))
    for i, (name, statement, laws, tests, docs, commands, modules, use) in enumerate(CAPABILITIES):
        put(store, {"name": name, "category": "capability", "tier": 0, "core": True, "order": n0 + i + 1,
                    "statement": statement, "check": name, "laws": laws, "tests": tests, "docs": docs,
                    "commands": commands, "modules": modules, "usefulness": use, "provenance": PROV},
            args.force, stats)
    for name, axis, statement, metric, target, direction in GOALS:
        put(store, {"name": name, "category": "goal", "tier": 0, "axis": axis, "statement": statement,
                    "metric": metric, "target": target, "direction": direction, "provenance": PROV},
            args.force, stats)
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
