#!/usr/bin/env python3
"""seed_self — the cards that keep the model whole and running itself.

  capability      the core: one card per capability, with the laws it carries, its smoke check
                  (engines/capabilities.py), its witness tests, docs and commands (law CM37)
  self_step       the steps of a self-run cycle and when each is due (engines/selfrun.py, law CM38)
  card_type/*     schemas for both registries
  law/CM37-CM39   the core is never lost; the model runs itself; one program
  goal/G_A4-G_A7  capabilities failing, integrity problems, laws carried by nothing, self-run freshness

Run once: ``python3 -B tools/seed_self.py`` (``--force`` rewrites, with versioning). Reads nothing outside the
repository. Law numbers are allocated in docs/INTEGRATION.md.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_self.py"}

REGISTRIES = {
    "capability": ("The model's core: what it can do, the laws each capability carries, a smoke check of the real "
                   "engine (engines/capabilities.py) that runs in every verify and self-run, its witness tests, "
                   "docs and commands (CM37).", 0),
    "self_step": ("The steps of a self-run cycle (engines/selfrun.py): what each does and when it is due "
                  "(every_hours, on_change registries) (CM38).", 0),
}

CARD_TYPES = {
    "capability": {"required": ["statement", "check", "laws", "tests", "core"],
                   "properties": {"check": {"type": "string"}, "laws": {"type": "array", "items": {"type": "string"}},
                                  "tests": {"type": "array", "items": {"type": "string"}},
                                  "docs": {"type": "array", "items": {"type": "string"}},
                                  "commands": {"type": "array", "items": {"type": "string"}},
                                  "modules": {"type": "array", "items": {"type": "string"}},
                                  "core": {"type": "boolean"}, "order": {"type": "integer"},
                                  "usefulness": {"type": "string"}},
                   "statement": "A core capability: its smoke check must pass in every verify and self-run (CM37)."},
    "self_step": {"required": ["statement", "run", "order"],
                  "properties": {"run": {"type": "string"}, "order": {"type": "integer"},
                                 "every_hours": {"type": ["number", "null"]},
                                 "on_change": {"type": "array", "items": {"type": "string"}},
                                 "auto": {"type": "boolean"}, "measures": {"type": "string"}},
                  "statement": "A step of the self-run cycle: the function it runs and when it is due (CM38)."},
}


def L(*names):
    return [f"law/{n}" for n in names]


CAPABILITIES = [
    ("card_store", "Everything is a card: registries of JSON cards in layers (model, self, project), a schema per "
     "card type, unknown fields kept, every write versioned, malformed and dangling cards reported.",
     L("CM02_everything_is_a_card", "CM03_unknown_fields_survive", "CM10_fail_loud", "CM11_closure_under_definition",
       "CM14_versioned_writes"),
     ["tests/test_kernel.py::test_registry_contract", "tests/test_kernel.py::test_unknown_fields_round_trip",
      "tests/test_kernel.py::test_versioning_archives_previous", "tests/test_kernel.py::test_malformed_card_is_reported",
      "tests/test_kernel.py::test_builtin_closure"],
     ["ARCHITECTURE.md"], ["cardmodel list", "cardmodel show", "cardmodel new", "cardmodel status"],
     ["cardmodel/kernel/store.py", "cardmodel/kernel/schema.py", "cardmodel/kernel/types.py"],
     "One place for everything the model knows, with history: an update never loses the old version, and fields "
     "another tool adds survive."),
    ("honest_limits", "Honest limits: what cannot run here is reported with its reason, a check with nothing to "
     "check is vacuous (never a pass), and every engine that claims something states its limits.",
     L("CM01_honest_limits", "CM07_no_vacuous_success", "CM12_capabilities_are_probed"),
     ["tests/test_laws.py::test_engines_state_honest_limits", "tests/test_probes.py::test_unavailable_is_reported"],
     ["docs/METHODOLOGY.md"], ["cardmodel probe"], ["cardmodel/engines/probes.py"],
     "A pass can be trusted: the model never reports a success it did not check."),
    ("witnesses", "Executable claims have witnesses: seeded runs reproduce exactly, and a wrong form is caught at "
     "its counterexample.", L("CM06_random_seeds", "CM08_executable_claims_have_witnesses"),
     ["tests/test_witness.py::test_wrong_form_is_caught", "tests/test_witness.py::test_builtin_runnable_forms_are_witnessed",
      "tests/test_laws.py::test_verify_prints_and_accepts_seed"],
     ["docs/METHODOLOGY.md"], ["cardmodel verify"], ["cardmodel/engines/witness.py", "cardmodel/engines/verify.py"],
     "Every claim the model makes about code is a run you can repeat with the printed seed."),
    ("form_selection", "The cheapest available form serves each domain, and costs are measured on this host before "
     "they are claimed.", L("CM05_cheapest_available_form", "CM09_measure_before_claiming"),
     ["tests/test_rewrite.py::test_cheapest_respects_domain_and_availability",
      "tests/test_optimize.py::test_measure_writes_metric_cards"],
     ["docs/METHODOLOGY.md"], ["cardmodel rewrite", "cardmodel optimize"],
     ["cardmodel/engines/rewrite.py", "cardmodel/engines/optimize.py"],
     "Picks the fastest correct implementation that actually runs on your machine."),
    ("boundaries", "Self-contained and private by default: the runtime needs no source folder, and nothing "
     "publishes (no push, no upload) unless asked.", L("CM13_self_contained", "CM19_never_publish_unasked"),
     ["tests/test_self_contained.py::test_sources_unreachable", "tests/test_laws.py::test_no_publishing_calls"],
     ["ARCHITECTURE.md"], ["cardmodel verify --only selfcheck"],
     ["cardmodel/engines/selfcheck.py", "cardmodel/engines/integrity.py"],
     "The program is one folder you own; it never sends your work anywhere by itself."),
    ("learning", "Learning from code in any recognised language: observe (named cards vs fallbacks), propose, "
     "verify, promote only with evidence; learned cards cite their observation.",
     L("CM04_compose_with_evidence", "CM15_observations_are_ground_truth"),
     ["tests/test_learn.py::test_promotion_needs_evidence", "tests/test_learn.py::test_learned_cards_cite_evidence"],
     ["HANDOVER.md", "docs/AUTONOMY.md"], ["cardmodel observe", "cardmodel learn", "cardmodel self corpus"],
     ["cardmodel/engines/observe.py", "cardmodel/engines/learn.py"],
     "The model grows from the code it reads, and only keeps what it could check."),
    ("translation", "One function, every language: lift to the card IR, emit through the language cards, compile, "
     "run and agree with the original; the op x language matrix is measured.",
     L("CM16_languages_are_cards", "CM17_translation_coverage_is_measured"),
     ["tests/test_translate.py::test_functions_agree_across_languages", "tests/test_conformance.py::test_conformance_matrix",
      "tests/test_laws.py::test_engines_have_no_language_branches"],
     ["docs/METHODOLOGY.md"], ["cardmodel translate", "cardmodel emit"],
     ["cardmodel/engines/translate.py", "cardmodel/engines/codegen.py", "cardmodel/engines/conformance.py"],
     "Write a function once; get it checked in every language this machine can run."),
    ("rewriting", "Rules rewrite and prove: rewrite rule cards simplify expressions to their cheapest equivalent "
     "and chain into proofs of equalities.", L("CM25_laws_carry_into_optimization"),
     ["tests/test_rewrite.py::test_optimize_finds_cheaper", "tests/test_rewrite.py::test_proves_hub_identities"],
     ["docs/KNOWLEDGE.md"], ["cardmodel rewrite --optimize", "cardmodel rewrite --prove"],
     ["cardmodel/engines/search.py"], "Algebra the model knows turns into faster code automatically."),
    ("law_discovery", "Laws are discovered from the op cards: templates witnessed, proved in Lean, and the "
     "simplifying ones promoted to rewrite rules.", L("CM25_laws_carry_into_optimization"),
     ["tests/test_laws_discovery.py::test_simplifying_laws_become_rules"], ["docs/KNOWLEDGE.md"], ["cardmodel laws"],
     ["cardmodel/engines/laws.py"], "New operations bring their own algebra with them."),
    ("theorems", "Crystallised knowledge: a statement carries its evidence (refuted < conjecture < witnessed < "
     "proved), and a proof never overrides a counterexample.", L("CM23_crystallised_knowledge"),
     ["tests/test_theorems.py::test_status_follows_evidence"], ["docs/KNOWLEDGE.md"],
     ["cardmodel run", "cardmodel verify --only theorems"], ["cardmodel/engines/theorems.py"],
     "You always know how sure the model is of a statement, and why."),
    ("lean", "Lean is the proof kernel: theorems, logic derivations and imported statements are checked by Lean, "
     "fail-closed.", L("CM23_crystallised_knowledge", "CM24_logic_carries"),
     ["tests/test_lean_import.py::test_faithful_and_witnessed", "tests/test_logic.py::test_derivations_are_kernel_checked"],
     ["docs/KNOWLEDGE.md"], ["cardmodel lean", "cardmodel run --lean", "cardmodel logic why --lean"],
     ["cardmodel/emit/lean.py", "cardmodel/emit/lean_import.py", "cardmodel/emit/lean_logic.py"],
     "Proofs written in Lean become the model's knowledge, and the model's derivations become Lean proofs."),
    ("logic", "Logic as cards: rules with recursion, negation, aggregates and constraints derive facts, each with "
     "a minimum-height proof.", L("CM24_logic_carries"),
     ["tests/test_logic.py::test_proofs_have_minimum_height", "tests/test_logic.py::test_constraint_violation_carries_a_proof"],
     ["docs/LANGUAGE.md"], ["cardmodel logic query", "cardmodel logic why"], ["cardmodel/engines/logic.py"],
     "If x and y then z, written once, explained every time."),
    ("card_language", "One language: functions, logic, theorems, tests and cards in one .card file, compiled to the "
     "card IR and from there to every language card.", L("CM26_one_language"),
     ["tests/test_lang.py::test_function_cards_verify_in_languages", "tests/test_lang.py::test_run_passes"],
     ["docs/LANGUAGE.md"], ["cardmodel run", "cardmodel lang", "cardmodel repl"], ["cardmodel/lang"],
     "One file says what a thing is, how it behaves and why it is right."),
    ("self_theory", "The model checks itself: its laws as logic over its own store, with zero violations.",
     L("CM27_the_model_checks_itself"), ["tests/test_logic.py::test_self_theory_holds_and_catches_breaks"],
     ["docs/KNOWLEDGE.md"], ["cardmodel logic self"], ["cardmodel/engines/selflogic.py", "stdlib/self.card"],
     "A broken rule of the model shows up with a proof of where."),
    ("function_algebra", "Behaviour is numbered: canonical forms (annihilator and initial terms), Gödel numbers, the "
     "GCD of functions and the identities that carry between them.", L("CM31_behaviour_is_numbered"),
     ["tests/test_funcalg.py::test_canonical_forms_carry_between_functions"], ["docs/KNOWLEDGE.md"],
     ["cardmodel algebra"], ["cardmodel/engines/funcalg.py"],
     "Two functions that behave alike are recognised as one, whatever their code, and the faster one is used."),
    ("redefinitions", "Redefinitions (identities carried from the Pheros work) are verified numerically or "
     "symbolically; none is refuted.", L("CM08_executable_claims_have_witnesses"),
     ["tests/test_witness.py::test_vendored_redefinitions_hold", "tests/test_witness.py::test_planted_false_identities_are_still_refuted"],
     ["docs/PROVENANCE.md"], ["cardmodel verify --only redefinitions"], ["cardmodel/engines/redefs.py"],
     "Every alternative definition of a function is checked to mean the same thing."),
    ("improve", "Programs made faster: verified algorithm substitutions and rewrites, effectful code byte-identical, "
     "a refuted substitution reverted.", L("CM21_effects_are_boundaries", "CM22_optimizations_self_correct"),
     ["tests/test_improve.py::test_effect_shell_is_byte_identical", "tests/test_improve.py::test_refuted_substitution_is_reverted",
      "tests/test_arena.py::test_arena_run_is_sound_and_improves"],
     ["docs/METHODOLOGY.md"], ["cardmodel improve", "cardmodel arena"],
     ["cardmodel/engines/improve.py", "cardmodel/engines/arena.py"],
     "Faster code with the same behaviour, and file, network and login code left exactly as written."),
    ("resources", "Bounded work: machine-wide slots for heavy work, memory caps for children and for this process, "
     "a timeout on every subprocess.", L("CM18_bounded_work", "CM30_resources_are_bounded"),
     ["tests/test_resources.py::test_child_over_its_cap_is_killed", "tests/test_laws.py::test_subprocesses_have_timeouts"],
     ["docs/METHODOLOGY.md"], ["cardmodel verify"], ["cardmodel/kernel/resources.py"],
     "The model works hard without taking your Mac down."),
    ("game_design", "Design is computed: the combat's design laws hold on the exact equilibrium of the exchange "
     "(rational simplex with a checked certificate).", L("CM28_design_is_computed"),
     ["tests/test_game.py::test_design_laws_hold_and_catch_imbalance"], ["game/DESIGN.md"],
     ["cardmodel game check"], ["cardmodel/game/analysis.py", "cardmodel/game/combat.py"],
     "Balance is a theorem, not a feeling: an imbalance is caught before anyone plays."),
    ("world", "Everything carries: the systemic world's facts carry between ticks, every event explains its causes "
     "and every action's impact is measured.", L("CM29_everything_carries"),
     ["tests/test_game.py::test_world_effects_carry_and_explain"], ["game/DESIGN.md"], ["cardmodel game world"],
     ["cardmodel/game/world.py"], "What you do in the world stays done, and the world can say why."),
    ("machines", "Machines are cards: instruction cards conform in every engine (reference IR, host, native), "
     "cycles and flags included.", L("CM32_machines_are_cards"),
     ["tests/test_machine.py::test_instruction_cards_conform_in_every_engine"], ["docs/MACHINES.md"],
     ["cardmodel isa"], ["cardmodel/machine/isa.py", "cardmodel/machine/bench.py"],
     "A CPU described once runs the same in every engine."),
    ("emulation", "Lifted ROM code is the cards and the shell is the only effect: a ROM runs lifted, frame for frame "
     "equal to the interpreter.", L("CM33_lifted_code_is_the_cards", "CM34_emulation_effects_are_the_shell"),
     ["tests/test_machine.py::test_lifted_blocks_match_the_interpreter", "tests/test_machine.py::test_shell_is_the_only_effect"],
     ["docs/MACHINES.md"], ["cardmodel emu", "cardmodel machine"],
     ["cardmodel/machine/lift.py", "cardmodel/machine/shell.py", "cardmodel/machine/gb.py"],
     "Your Game Boy / Color games run through the model, natively."),
    ("arcade", "Games are cards: a game's tables, rules and logic compile into a native module that the store builds, "
     "serves and launches.", L("CM35_games_are_cards"),
     ["tests/test_arcade.py::test_a_timed_guard_redirects"], ["docs/ARCADE.md", "docs/STORE.md"],
     ["cardmodel arcade"], ["cardmodel/arcade"], "Games made from the model's cards ship through Cardmodel Arcade."),
    ("live_hub", "The store follows everything in progress: project cards say what to watch and keep their owner's "
     "detail current (CM41); the hub computes each one's phase, branches, uncommitted work, metrics and builds from "
     "git and the model's records, read-only, gathers what waits on the user, and pushes changes to the launcher as "
     "they happen; early-access builds install beside the release.",
     L("CM01_honest_limits", "CM35_games_are_cards", "CM41_projects_keep_their_cards_current"),
     ["tests/test_hub.py::test_status_is_computed_from_git_and_state", "tests/test_hub.py::test_git_reads_never_write",
      "tests/test_hub.py::test_changes_are_pushed", "tests/test_hub.py::test_early_access_is_separate_and_installable",
      "tests/test_projects.py::test_missing_or_stale_project_cards_fail"],
     ["docs/STORE.md"], ["cardmodel arcade serve (the In progress page)"], ["cardmodel/arcade/hub.py"],
     "One live page shows what is being built, where, by which branch, how far along, and lets you play it early."),
    ("godel_model", "The expanding Gödel model's foundation: atoms take primes in an append-only ledger; a concept's "
     "content vector (its factorization), GCD, LCM and divisibility; Gödel's positional structural numbers decoded "
     "exactly; maps between Gödel sets with their gaps.", L("CM43_primes_are_forever", "CM31_behaviour_is_numbered"),
     ["tests/test_godel.py::test_ledger_is_append_only", "tests/test_godel.py::test_content_algebra_and_carry",
      "tests/test_godel.py::test_structural_numbers_decode_exactly"],
     ["GOALS.md", "docs/MATH_CORE.md"], ["cardmodel godel"], ["cardmodel/engines/godel.py"],
     "Every concept gets a number that never changes, and two concepts' common factor shows the logic they share."),
    ("anyps5", "AnyPS5 as cards: every gap classified by what would close it; an unknown is an observation "
     "obligation, never a made-up success.", L("CM36_unknowns_are_observation_obligations"),
     ["tests/test_anyps.py::test_unknown_gaps_are_observation_obligations"], ["docs/ANYPS5.md"],
     ["cardmodel anyps5"], ["cardmodel/anyps5"], "The real coverage of AnyPS5, and the cause of every gap."),
    ("self_run", "The model runs itself: cycles of checks, learning and optimization with findings and a ranked plan; "
     "the core is never lost.", L("CM37_core_is_never_lost", "CM38_the_model_runs_itself"),
     ["tests/test_self.py::test_core_capabilities_are_never_lost",
      "tests/test_self.py::test_self_run_finds_flaws_and_ranks_them"],
     ["docs/AUTONOMY.md"], ["cardmodel self"], ["cardmodel/engines/selfrun.py", "cardmodel/engines/capabilities.py"],
     "Every use makes the model check and improve itself, and tell you where it falls short."),
    ("integration", "One program: unique law and goal numbers, every law carried by a capability, every command, "
     "section and doc described, generated docs in sync.", L("CM20_laws_are_cards", "CM39_one_program"),
     ["tests/test_laws.py::test_laws_md_in_sync", "tests/test_self.py::test_one_program_integrity"],
     ["docs/INTEGRATION.md"], ["cardmodel verify --only integrity", "cardmodel docs"],
     ["cardmodel/engines/integrity.py"], "Parallel work lands as one working program, never as pieces."),
]

STEPS = [
    ("capabilities", 10, 0, [], True, "the core capability smoke checks (CM37)", "capabilities_failing"),
    ("integrity", 20, 0, [], True, "one program: numbers, carried laws, described commands, sections, docs (CM39)",
     "integrity_problems"),
    ("verify", 30, 0, [], True, "verify --quick; quarantines the self layer if it breaks a section", "verify sections"),
    ("verify_full", 40, 24, [], True, "every verify section, the toolchain-heavy ones too (writes last_verify)",
     "conformance, functions, proofs, portability"),
    ("learn", 50, 0, [], True, "learn from changed source trees in every recognised language into the self layer",
     "learned_cards, named_fraction"),
    ("laws", 60, None, ["op"], True, "rediscover laws when the op cards change (witness, Lean, rules)",
     "theorems_proved"),
    ("algebra", 70, None, ["algorithm"], True, "canonical forms and identities when the algorithm cards change",
     "functional_identities"),
    ("arena", 80, 24, [], True, "a small arena run: soundness, recall and speed of the optimizer",
     "arena_unsound_runs, arena_recall, arena_geomean_speedup"),
    ("optimize", 90, 168, [], True, "measure the op cards' forms on this host (metric cards)", "measured_forms"),
    ("goals", 100, 0, [], True, "every goal from the latest result of each verify section; trend", "all goals"),
]

LAWS = [
    ("CM37_core_is_never_lost", "The model's core is a set of capability cards, each naming the laws it carries, a "
     "smoke check of the real engine, its witness tests and its docs. Every verify and every self-run runs the "
     "checks, and a core capability that stops behaving fails verify. Every law is carried by at least one "
     "capability, so no law is only words. New knowledge comes in as cards, and reframings (redefinitions, "
     "rewrites, learned cards) must keep every check passing; removing a capability is a visible change to its "
     "card and its test.",
     ["user requirement 2026-10-21 (core model features never lost or forgotten, as laws)", "hub L1", "Pheros L41"],
     "tests/test_self.py::test_core_capabilities_are_never_lost"),
    ("CM38_the_model_runs_itself", "Using the model runs the model: a cycle of self_step cards checks the "
     "capabilities and the program's integrity, verifies, learns from source trees in every recognised language, "
     "rediscovers laws and identities when their cards change, measures the optimizer and the forms, and computes "
     "every goal; it turns the results into strengths, weaknesses and flaws with evidence and ranks what to improve "
     "next. Any command starts a cycle in the background when one is due, under the resource governor; what it "
     "learns lands in the self layer (untracked, read by every command), never in the tracked cards or the code.",
     ["user requirement 2026-10-21 (self-ran rules, self-determinism, self-optimization and self-learning; the "
      "whole model runs as one unit)"],
     "tests/test_self.py::test_self_run_finds_flaws_and_ranks_them"),
    ("CM39_one_program", "Parallel work lands as one program: law numbers and goal ids are unique and allocated in "
     "docs/INTEGRATION.md, every law is carried by a capability, every command is in the CLI help, every verify "
     "section and doc is described, generated docs are in sync and no merge markers remain; a branch is merged into "
     "main only when the tests, verify and this integrity check pass, and every integration is logged.",
     ["user requirement 2026-10-21 (one software, one working module; document all work so nothing interferes)"],
     "tests/test_self.py::test_one_program_integrity"),
]

GOALS = [
    ("G_A4_capabilities_failing", "autonomy", "Core capabilities whose smoke check fails (latest verify or self-run).",
     "capabilities_failing", 0, "lower"),
    ("G_A5_integrity_problems", "autonomy", "Integrity problems: duplicate law or goal numbers, laws no capability "
     "carries, undescribed commands, sections or docs, drifted generated docs, merge markers.",
     "integrity_problems", 0, "lower"),
    ("G_A6_laws_carried", "autonomy", "Laws that no capability card carries (a law nothing runs can be forgotten).",
     "laws_uncarried", 0, "lower"),
    ("G_A7_self_run_fresh", "autonomy", "Hours since the last self-run cycle finished.", "self_run_age_hours", 24,
     "lower"),
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
    for reg, (desc, tier) in REGISTRIES.items():
        d = root / reg
        d.mkdir(parents=True, exist_ok=True)
        f = d / "_category.json"
        if not f.exists() or args.force:
            meta = {"name": reg, "description": desc, "tier": tier, "defined_by": "tools/seed_self.py",
                    "card_type": reg}
            f.write_text(json.dumps(meta, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    store.invalidate()
    for name, spec in CARD_TYPES.items():
        put(store, {"name": name, "category": "card_type", "tier": 0, "applies_to": [name],
                    "statement": spec["statement"], "metadata": {"version": "1.0.0"},
                    "schema": {"type": "object", "required": spec["required"], "properties": spec["properties"]},
                    "provenance": PROV}, args.force, stats)
    for i, (name, statement, laws, tests, docs, commands, modules, use) in enumerate(CAPABILITIES):
        put(store, {"name": name, "category": "capability", "tier": 0, "core": True, "order": i + 1,
                    "statement": statement, "check": name, "laws": laws, "tests": tests, "docs": docs,
                    "commands": commands, "modules": modules, "usefulness": use, "provenance": PROV},
            args.force, stats)
    for name, order, every, on_change, auto, statement, measures in STEPS:
        put(store, {"name": name, "category": "self_step", "tier": 0, "run": name, "order": order,
                    "every_hours": every, "on_change": on_change, "auto": auto, "statement": statement,
                    "measures": measures, "provenance": PROV}, args.force, stats)
    for name, statement, origins, witness in LAWS:
        put(store, {"name": name, "category": "law", "tier": 0, "statement": statement, "origins": origins,
                    "witness": witness, "provenance": PROV}, args.force, stats)
    for name, axis, statement, metric, target, direction in GOALS:
        put(store, {"name": name, "category": "goal", "tier": 0, "axis": axis, "statement": statement,
                    "metric": metric, "target": target, "direction": direction, "provenance": PROV},
            args.force, stats)
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
