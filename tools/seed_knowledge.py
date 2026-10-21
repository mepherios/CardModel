"""seed_knowledge — registries, card types, laws and goals for logic, theorems, the card language and the game.

Imported by tools/bootstrap.py (build time only). Kept separate so the knowledge layer reads as one unit.
"""
from __future__ import annotations

REGISTRIES = {
    "theory": ("Logic theories: which facts and rules belong together, their predicates and arities.", 1),
    "logic_rule": ("Logic rules (if body then head) and constraints (never: body), one card each; learned ones "
                   "carry their evidence (support, confidence).", 1),
    "fact": ("Ground facts of logic theories, one pack per theory (_pack_<theory>.jsonl).", 1),
    "theorem": ("Mathematical statements with evidence. Status: refuted < conjecture < witnessed < proved "
                "(Lean kernel). Discovered laws, card-language theorems and imported Lean theorems.", 1),
    "program": ("Card-language modules: source hash, what they declare, what they use.", 1),
}
STATUS_VALUES = {"theorem": ["conjecture", "witnessed", "proved", "refuted", "vacuous"]}

PROP = {"type": "array", "minItems": 1, "items": {}}
CARD_TYPES = [
    {"name": "theory", "applies_to": ["theory"], "statement": "A logic theory: a named set of facts and rules.",
     "schema": {"type": "object", "required": ["statement"],
                "properties": {"imports": {"type": "array", "items": {"type": "string"}},
                               "predicates": {"type": "object"}, "source": {"type": "string"}}}},
    {"name": "logic_rule", "applies_to": ["logic_rule"],
     "statement": "A rule (head <- body) or a constraint (never: body) of a theory, in the JSON literal form of "
                  "engines/logic.py; ``text`` is its card-language rendering.",
     "schema": {"type": "object", "required": ["theory", "body", "text"],
                "properties": {"theory": {"type": "string"}, "head": {"type": ["object", "null"]},
                               "body": {"type": "array"}, "text": {"type": "string"},
                               "kind": {"enum": ["rule", "constraint"]}, "evidence": {"type": "object"}}}},
    {"name": "fact", "applies_to": ["fact"], "statement": "A ground atom of a theory.",
     "schema": {"type": "object", "required": ["theory", "pred", "args"],
                "properties": {"theory": {"type": "string"}, "pred": {"type": "string"},
                               "args": {"type": "array", "items": {"type": ["string", "integer", "number"]}}}}},
    {"name": "theorem", "applies_to": ["theorem"],
     "statement": "for all vars: hyps ==> concl. Terms are IR op trees; propositions have lower-case heads. "
                  "``semantics`` card = IR reference semantics, lean = Lean's operators (imported statements).",
     "schema": {"type": "object", "required": ["vars", "concl", "semantics", "status"],
                "properties": {"vars": {"type": "array", "items": {"type": "object", "required": ["name", "type"],
                                                                     "properties": {"type": {"enum": ["int", "nat", "bool", "float"]}}}},
                               "hyps": {"type": "array"}, "concl": PROP,
                               "semantics": {"enum": ["card", "lean"]},
                               "status": {"enum": STATUS_VALUES["theorem"]},
                               "evidence": {"type": "object"}, "proofs": {"type": "array"}}}},
    {"name": "program", "applies_to": ["program"], "statement": "A card-language module.",
     "schema": {"type": "object", "required": ["source", "summary"]}},
]

LAWS = [
    ("CM23_crystallised_knowledge", "A statement is only as strong as its evidence: refuted (counterexample "
     "shown) < conjecture < witnessed (an exhaustive small-value phase plus seeded random values; the hypotheses "
     "must hold on enough inputs and must not pin a variable to one value) < proved (accepted by the Lean kernel). "
     "An imported Lean statement is kept only when the kernel accepts our reading as the original proposition.",
     ["user requirement 2026-10-21 (crystallised knowledge, never disobey true proof)", "hub L1", "Pheros L41"],
     "tests/test_theorems.py::test_status_follows_evidence"),
    ("CM24_logic_carries", "Rules are cards. Every derived fact carries a proof of minimum height (rule, "
     "bindings, premises) that exports to a Lean term the kernel checks; unsafe or unstratifiable rules are "
     "reported, never evaluated; evaluation is bounded (L20).",
     ["user requirement 2026-10-21 (if x, y -> z)", "hub L45", "Pheros L41"],
     "tests/test_logic.py::test_derivations_are_kernel_checked"),
    ("CM25_laws_carry_into_optimization", "The laws the op cards obey are discovered from templates, refuted or "
     "witnessed, and proved where Lean can; a law that simplifies becomes a rewrite rule that cites its theorem "
     "card, so knowledge carries into rewrite --optimize and improve.",
     ["user requirement 2026-10-21 (find the logic that carries, optimize it)", "hub L27"],
     "tests/test_laws_discovery.py::test_simplifying_laws_become_rules"),
    ("CM26_one_language", "Functions, rules, constraints, theorems, tests and cards share one source language; "
     "a module compiles to cards, and its functions compile to the same IR every language card emits and the "
     "conformance matrix checks.", ["user requirement 2026-10-21 (a real programming language)", "Pheros CL v0"],
     "tests/test_lang.py::test_function_cards_verify_in_languages"),
    ("CM27_the_model_checks_itself", "The model's own laws are logic over its card store (stdlib/self.card); "
     "they hold with zero violations, and a planted break is caught.", ["user requirement 2026-10-21 (my card law "
                                                                         "carries it)", "Pheros L63"],
     "tests/test_logic.py::test_self_theory_holds_and_catches_breaks"),
]

LAWS += [
    ("CM28_design_is_computed", "Combat design claims are computed, not asserted: every design_law card holds on the "
     "exact equilibrium of the exchange (rational simplex with a checked certificate), a planted imbalance is "
     "caught, and the combat kernel's invariants are theorems of stdlib/combat.card.",
     ["user requirement 2026-10-21 (superior counteraction design)", "hub L1", "Pheros L41"],
     "tests/test_game.py::test_design_laws_hold_and_catch_imbalance"),
    ("CM29_everything_carries", "Effects carry instead of resetting: frame advantage, momentum (flow, bank, recoil), "
     "posture and stamina carry between exchanges; world facts carry between ticks; every world event has a cause "
     "chain back to the actions that made it, and each action's counterfactual impact is measured.",
     ["user requirement 2026-10-21 (if you do something in our world it carries)"],
     "tests/test_game.py::test_world_effects_carry_and_explain"),
]

GOALS = [
    ("G_K1_theorems_proved", "knowledge", "Theorem cards whose statement the Lean kernel accepted with a proof.",
     "theorems_proved", 150, "higher"),
    ("G_K2_lean_imported", "knowledge", "Lean core theorems imported with a faithful reading (the kernel accepts "
     "our statement as the original).", "lean_imported", 300, "higher"),
    ("G_K3_lean_mismatches", "knowledge", "Imported Lean-proved statements that the card semantics refute.",
     "lean_mismatches", 0, "lower"),
    ("G_K4_self_violations", "knowledge", "Violations of the model's own laws as logic (stdlib/self.card).",
     "self_violations", 0, "lower"),
    ("G_K5_programs_pass", "knowledge", "Card-language programs (examples/lang, stdlib) that pass.",
     "card_programs_passing", 6, "higher"),
    ("G_D1_design_laws", "design", "Design laws (design_law cards) that fail on the neutral exchange.",
     "design_laws_failing", 0, "lower"),
    ("G_D2_equilibrium_support", "design", "Options the exact neutral equilibrium mixes (richness of play).",
     "equilibrium_support", 8, "higher"),
]

CARD_LANGUAGE = {
    "name": "cardlang", "category": "language", "tier": 0, "extensions": [".card"],
    "statement": "The card language: functions, logic (facts, rules, constraints, queries), theorems, tests and "
                 "cards in one source file (cardmodel/lang). Functions compile to the card IR; the rest compiles "
                 "to cards. Accepts the Pheros CL v0 function form (name : T -> T = match ...).",
    "comments": {"line": ["--", "#"], "block": [["(*", "*)"]]},
    "frontend": "cardmodel.lang",
    "grammar": "cardmodel/lang/syntax.py (module docstring) and docs/LANGUAGE.md",
}
