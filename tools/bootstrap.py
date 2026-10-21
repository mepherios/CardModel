#!/usr/bin/env python3
"""bootstrap — write the model's own built-in cards (languages, ops, domains, types, laws, goals, rules).

Run once on a fresh tree: ``python3 -B tools/bootstrap.py``. It only creates
cards that do not exist yet (``--force`` rewrites them, with versioning).
After bootstrap the cards are the source of truth: edit them (or let
``cardmodel learn`` / ``optimize`` update them), not this script.
This script reads nothing outside the repository; vendored cards from the
original card-model folders come from ``tools/vendor_import.py``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from cardmodel.kernel.store import open_store  # noqa: E402
import seed_algorithms as SA  # noqa: E402
import seed_languages as SL  # noqa: E402
import seed_ops as SO  # noqa: E402

PROV = {"origin": "cardmodel bootstrap", "tool": "tools/bootstrap.py"}

REGISTRIES = {
    "card_type": ("Card types as cards: JSON Schemas that cards are validated against (schema-as-data).", 0),
    "language": ("Programming languages as cards: toolchain probe, runner, comment syntax and codegen syntax as data.", 0),
    "op": ("Computation atoms: reference semantics (ir.eval), signatures, per-language emit templates, "
           "equivalent forms with costs (redefinitions), hints and observe matchers.", 0),
    "domain": ("Input domains: generators, sub-domain parents and reference projections (e.g. u32 = mod 2**32).", 0),
    "lib": ("Libraries that forms import (variant files next to card.json).", 0),
    "rewrite_rule": ("Rewrite rules (identities) used by rewrite search and the optimizer; each is witnessed "
                     "numerically and emitted to Lean.", 1),
    "law": ("The model's laws, consolidated from the hub and Pheros law sets; each names its witness test.", 0),
    "goal": ("Measurable goals: a metric the program computes, a target and a direction.", 0),
    "algorithm": ("Algorithm-level redefinitions: one mathematical function, several implementations of very "
                  "different cost (all in the liftable subset); improve substitutes verified faster forms.", 1),
}

DOMAINS = [
    {"name": "any", "statement": "No restriction (requests for 'any' accept every form).", "parents": []},
    {"name": "int", "statement": "Python integers (unbounded).", "parents": ["any"],
     "generator": {"int": [-1000000, 1000000]}},
    {"name": "i32", "statement": "Signed 32-bit integers.", "parents": ["int"],
     "generator": {"int": [-2147483648, 2147483647]}},
    {"name": "u32", "statement": "Unsigned 32-bit integers; results compared modulo 2**32.", "parents": ["int"],
     "generator": {"int": [0, 4294967295]}, "project_reference": "lambda r: r & 0xFFFFFFFF"},
    {"name": "nonneg_int", "statement": "Integers >= 0.", "parents": ["int"], "generator": {"int": [0, 1000000]}},
    {"name": "small_int", "statement": "Small integers >= 0: where exponential or linear-time reference forms "
     "still finish quickly.", "parents": ["nonneg_int"], "generator": {"int": [0, 20]}},
    {"name": "modular", "statement": "Modular arithmetic inputs (generators come from the card).", "parents": ["int"]},
    {"name": "coprime_mod", "statement": "(a, n) with gcd(a, n) = 1.", "parents": ["modular"]},
    {"name": "prime_mod", "statement": "(a, p) with p prime and p not dividing a.", "parents": ["modular"]},
    {"name": "float", "statement": "IEEE-754 binary64; compared with rel_tol 1e-12.", "parents": ["any"],
     "generator": {"float": [-1000.0, 1000.0]}},
    {"name": "ec", "statement": "Elliptic-curve points (needs sage; documentation-only here).", "parents": ["any"]},
    {"name": "python", "statement": "Runtime domain: the Python interpreter (Ting's 'python' forms).", "parents": ["any"]},
    {"name": "browser", "statement": "Runtime domain: a JavaScript engine (Ting's 'browser' forms; Node here).",
     "parents": ["any"]},
]

FORM_SCHEMA = {"type": "object", "required": ["name"],
               "properties": {"name": {"type": "string"}, "cost": {"type": "number"},
                              "domain": {"type": "string"}, "domains": {"type": "array", "items": {"type": "string"}},
                              "lang": {"type": "string"}, "runnable": {"type": "boolean"},
                              "code": {"type": "string"}, "file": {"type": "string"}, "entry": {"type": "string"},
                              "cost_vector": {"type": "object", "additionalProperties": {"type": "number"}},
                              "probe": {"type": "object"}, "libs": {"type": "array", "items": {"type": "string"}}}}

CARD_TYPES = [
    {"name": "card", "applies_to": ["*"],
     "statement": "The universal card contract (hub CARD_MODEL.md + Pheros _meta/card_type). Unknown fields are "
                  "allowed and ignored by consumers that do not know them. Names may contain '.' and '-' (vendored "
                  "Pheros std_library names and Ting type names do); status must be healthy|suspect|broken|"
                  "quarantined unless the registry declares its own status_values (checked by the kernel).",
     "schema": {"type": "object", "required": ["name", "category"],
                "properties": {
                    "name": {"type": "string", "pattern": "^[A-Za-z_][A-Za-z0-9_.\\-]*$"},
                    "category": {"type": "string", "pattern": "^[a-z][a-z0-9_]*$"},
                    "tier": {"type": "integer", "minimum": 0},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "depends": {"type": "array", "items": {"type": "string"}},
                    "cost": {"type": ["number", "object", "null"]},
                    "cost_vector": {"type": "object", "additionalProperties": {"type": "number"}},
                    "dimension_direction": {"type": "object", "additionalProperties": {"enum": ["lower", "higher"]}},
                    "forms": {"type": "array", "items": {"$ref": "#/definitions/form"}},
                    "variants": {"type": "object"},
                    "metadata": {"type": "object", "properties": {
                        "version": {"type": "string", "pattern": "^\\d+\\.\\d+\\.\\d+$"},
                        "previous_content_hash": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}},
                    "status": {"type": "string"},
                    "statement": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "interacts_with": {"type": "array", "items": {"type": "string"}},
                    "flaws": {"type": "array", "items": {"type": "string"}},
                    "provenance": {"type": ["object", "string"]}},
                "definitions": {"form": FORM_SCHEMA}},
     "metadata": {"version": "1.0.0", "ported_from": ["hub CARD_MODEL.md", "Pheros cards/_meta/card_type/schema.json",
                                                     "Pheros cards/_meta/card_versioning/schema.json"]}},
    {"name": "registry", "applies_to": [],
     "statement": "Shape of a registry's _category.json (Pheros registry_contract).",
     "schema": {"type": "object", "required": ["name", "description"],
                "properties": {"name": {"type": "string", "pattern": "^[a-z][a-z0-9_.]*$"},
                               "description": {"type": "string", "minLength": 10},
                               "tier": {"type": "integer", "minimum": 0},
                               "card_type": {"type": ["string", "array"]},
                               "category_aliases": {"type": "array", "items": {"type": "string"}},
                               "dimension_direction": {"type": "object"},
                               "max_cards": {"type": ["integer", "null"]},
                               "status_values": {"type": "array", "items": {"type": "string"}},
                               "references": {"enum": ["internal", "external"]}}}},
    {"name": "op", "applies_to": ["op"], "statement": "A computation atom.",
     "schema": {"type": "object", "required": ["statement"],
                "properties": {"ir": {"type": "object", "required": ["arity", "types"],
                                      "properties": {"arity": {"type": "integer", "minimum": 1},
                                                     "eval": {"type": "string"},
                                                     "types": {"type": "array", "minItems": 1,
                                                               "items": {"type": "array", "items": {"enum": ["int", "float", "bool"]}}}}},
                               "emit": {"type": "object"}, "forms": {"type": "array", "minItems": 1}}}},
    {"name": "language", "applies_to": ["language"], "statement": "A programming language as a card.",
     "schema": {"type": "object", "required": ["extensions"],
                "properties": {"extensions": {"type": "array", "items": {"type": "string", "pattern": "^\\."}},
                               "probe": {"type": "object"}, "runner": {"type": "object"},
                               "codegen": {"type": "object"}, "comments": {"type": "object"},
                               "extends": {"type": "string"}}}},
    {"name": "domain", "applies_to": ["domain"], "statement": "An input domain.",
     "schema": {"type": "object", "required": ["statement", "parents"],
                "properties": {"parents": {"type": "array", "items": {"type": "string"}},
                               "generator": {"type": "object"}, "project_reference": {"type": "string"}}}},
    {"name": "redefinition", "applies_to": ["redefinition"],
     "statement": "An executable identity source_form == target_form (Pheros redefinition_contract; domain enum "
                  "extended with the model's domains). Prose redefinitions live in redefinition_note.",
     "schema": {"type": "object", "required": ["source_form", "target_form", "domain", "witness_kind"],
                "properties": {"source_form": {"type": "string"}, "target_form": {"type": "string"},
                               "domain": {"enum": ["real", "complex", "fp32", "fp64", "bitvec64", "modular_n",
                                                   "positive_real", "integer", "symbolic_real", "nonneg_integer"]},
                               "condition": {"type": ["string", "null"]},
                               "cost_score": {"type": "number", "minimum": 1, "maximum": 100},
                               "witness_kind": {"enum": ["symbolic", "numerical", "exhaustive", "axiomatic"]},
                               "examples": {"type": "array"},
                               "verification": {"type": "object"}}},
     "metadata": {"version": "1.0.0", "ported_from": ["Pheros cards/_meta/redefinition_contract"]}},
    {"name": "redefinition_note", "applies_to": ["redefinition_note"],
     "statement": "A redefinition whose forms are prose or code in other languages: knowledge, not executable here.",
     "schema": {"type": "object", "properties": {"source_form": {"type": ["string", "object", "array", "null"]},
                                                 "target_form": {"type": ["string", "object", "array", "null"]}}}},
    {"name": "primitive", "applies_to": [],
     "statement": "Pheros primitive_contract: opt-in type for computation primitives (contract, complexity, "
                  "alternatives, composes_with, witnesses, variants). Coverage reports how many cards satisfy it.",
     "schema": {"type": "object",
                "required": ["statement", "contract", "complexity", "alternatives", "composes_with", "witnesses", "variants"],
                "properties": {"contract": {"type": "object", "required": ["inputs", "outputs", "preconditions",
                                                                           "postconditions", "side_effects"]},
                               "complexity": {"type": "object", "required": ["time", "space"]},
                               "alternatives": {"type": "array"}, "composes_with": {"type": "array"},
                               "witnesses": {"type": "array"}, "variants": {"type": "object", "minProperties": 1}}},
     "metadata": {"version": "1.0.0", "ported_from": ["Pheros cards/_meta/primitive_contract/schema.json"]}},
    {"name": "function", "applies_to": ["function"],
     "statement": "A function lifted into the card IR, with its forms in many languages and its known-answer vectors.",
     "schema": {"type": "object", "required": ["ir", "signature", "forms"],
                "properties": {"ir": {"type": "object", "required": ["entry", "functions"]},
                               "signature": {"type": "object", "required": ["params", "returns"]},
                               "vectors": {"type": "array"}, "generators": {"type": "array"},
                               "verification": {"type": "object"}}}},
    {"name": "xleq", "applies_to": ["xleq"],
     "statement": "Cross-language equivalence evidence (Pheros cross_language_equivalence + L56: 'established' "
                  "needs evidence_count >= 3).",
     "schema": {"type": "object", "required": ["subject", "languages", "confidence", "evidence_count"],
                "properties": {"languages": {"type": "array", "minItems": 2},
                               "evidence_count": {"type": "integer", "minimum": 0}},
                "anyOf": [{"properties": {"confidence": {"const": "established"},
                                          "evidence_count": {"type": "integer", "minimum": 3}}},
                          {"properties": {"confidence": {"enum": ["tentative", "refuted", "hypothesized"]}}}]}},
    {"name": "algorithm", "applies_to": ["algorithm"],
     "statement": "One mathematical function with implementations of different cost; forms are liftable Python.",
     "schema": {"type": "object", "required": ["statement", "signature", "forms", "reference_form", "generators"],
                "properties": {"signature": {"type": "object", "required": ["params", "returns"]},
                               "precondition": {"type": ["string", "null"]},
                               "forms": {"type": "array", "minItems": 2,
                                         "items": {"type": "object", "required": ["name", "code", "entry", "complexity"]}}}}},
    {"name": "law", "applies_to": ["law"], "statement": "A law of the model.",
     "schema": {"type": "object", "required": ["statement", "origins", "witness"],
                "properties": {"origins": {"type": "array", "minItems": 1},
                               "witness": {"type": "string", "pattern": "^tests/test_[a-z_]+\\.py::"}}}},
    {"name": "goal", "applies_to": ["goal"], "statement": "A measurable goal.",
     "schema": {"type": "object", "required": ["statement", "metric", "target", "direction", "axis"],
                "properties": {"direction": {"enum": ["higher", "lower"]},
                               "axis": {"enum": ["computation", "understanding", "learning", "optimization", "autonomy"]},
                               "target": {"type": "number"}}}},
    {"name": "rewrite_rule", "applies_to": ["rewrite_rule"], "statement": "An identity usable as a rewrite.",
     "schema": {"type": "object", "required": ["lhs", "rhs", "vars"],
                "properties": {"lhs": {"type": "string"}, "rhs": {"type": "string"},
                               "vars": {"type": "array", "items": {"type": "string"}},
                               "domain": {"type": "string"}, "condition": {"type": ["string", "null"]},
                               "bidirectional": {"type": "boolean"}}}},
    {"name": "crypto_atom", "applies_to": ["crypto_atom"],
     "statement": "Ting's cryptographic atom: forms per runtime and known-answer vectors.",
     "schema": {"type": "object", "required": ["operation", "forms"],
                "properties": {"vectors": {"type": ["string", "array"]}, "purity": {"type": "string"}}}},
    {"name": "cipher_suite", "applies_to": ["cipher_suite"],
     "statement": "Ting's cipher suite: depends_on atoms; cost_vector with dimension_direction.",
     "schema": {"type": "object", "required": ["depends_on", "cost_vector", "dimension_direction"]}},
    {"name": "metric", "applies_to": ["metric"],
     "statement": "A host measurement (L28 optimization axis / L59 reproducibility).",
     "schema": {"type": "object", "required": ["target_card", "form", "median_ns", "samples", "host"],
                "properties": {"median_ns": {"type": "number", "minimum": 0},
                               "samples": {"type": "integer", "minimum": 1}, "host": {"type": "object"}}}},
    {"name": "observation", "applies_to": ["observation"],
     "statement": "What the observer saw in a source tree: ground truth, never edited by rules (Pheros L102).",
     "schema": {"type": "object", "required": ["root", "files", "totals"]}},
    {"name": "translation_gap", "applies_to": ["translation_gap"],
     "statement": "source -> target language coverage with supported/unsupported constructs (Pheros L115).",
     "schema": {"type": "object", "required": ["source_language", "target_language"]}},
]

for t in CARD_TYPES:
    t.setdefault("metadata", {"version": "1.0.0"})

LAWS = [
    ("CM01_honest_limits", "Honest about what is mechanized: every engine states its limits, and every count, "
     "percentage or 'verified' in output or docs is computed from cards or runs, never typed by hand.",
     ["hub L1", "hub L21", "hub L38", "Pheros L41"], "tests/test_laws.py::test_engines_state_honest_limits"),
    ("CM02_everything_is_a_card", "Every structure is a card in a registry; a registry is a directory with "
     "_category.json; the filesystem is the index (ALL/get/all_names).",
     ["hub L25", "hub CARD_MODEL.md", "Pheros registry_contract", "Pheros L113"],
     "tests/test_kernel.py::test_registry_contract"),
    ("CM03_unknown_fields_survive", "Unknown fields are kept on save and ignored by consumers that do not know "
     "them (the infinite-extension guarantee).", ["hub CARD_MODEL.md", "Ting CARD_MODEL_MAPPING"],
     "tests/test_kernel.py::test_unknown_fields_round_trip"),
    ("CM04_compose_with_evidence", "Compose from existing cards first; a new card enters through the learning "
     "loop with evidence (>= 3 observations or a passing witness), never as a bare declaration.",
     ["hub L26", "Pheros L100", "Pheros L22"], "tests/test_learn.py::test_promotion_needs_evidence"),
    ("CM05_cheapest_available_form", "A choice between equivalent forms goes through cheapest(): domain match, "
     "runnable, available on this host, minimum cost; never 'first in list'.",
     ["hub L27", "hub rewrite_engine.cheapest", "rea-cards dispatch"], "tests/test_rewrite.py::test_cheapest_respects_domain_and_availability"),
    ("CM06_random_seeds", "Randomised checks pick a fresh seed, print it, and accept --seed to reproduce.",
     ["hub L17", "hub L28", "Ting test_cross_language"], "tests/test_laws.py::test_verify_prints_and_accepts_seed"),
    ("CM07_no_vacuous_success", "A witness that cannot fail is not a witness: every check runs a differential "
     "probe, and a deliberately wrong form must be caught.", ["Pheros L41", "Pheros L45", "Pheros L46", "Pheros L50"],
     "tests/test_witness.py::test_wrong_form_is_caught"),
    ("CM08_executable_claims_have_witnesses", "Every runnable form, rewrite rule and executable redefinition has a "
     "witness that pins inputs to outputs (vectors or seeded equivalence).",
     ["hub L47", "Pheros L34", "Pheros L38"], "tests/test_witness.py::test_builtin_runnable_forms_are_witnessed"),
    ("CM09_measure_before_claiming", "Speed claims cite a metric card measured on this host (median, samples, "
     "seed, host fingerprint); cost anchors change only from measurements.", ["hub L4", "Pheros L28", "Pheros L59",
                                                                               "rea-cards calibrate"],
     "tests/test_optimize.py::test_measure_writes_metric_cards"),
    ("CM10_fail_loud", "Malformed cards and schema drift are reported, never silently skipped; broad excepts log "
     "what they caught.", ["hub L36", "hub L39"], "tests/test_kernel.py::test_malformed_card_is_reported"),
    ("CM11_closure_under_definition", "Every depends_on reference resolves to a card; a gap is reported at the "
     "reference site.", ["hub L45", "Pheros L14"], "tests/test_kernel.py::test_builtin_closure"),
    ("CM12_capabilities_are_probed", "Toolchains and backends are used only after a probe passes on this host; "
     "an unavailable form is reported with its reason, never skipped silently.",
     ["rea-cards probes", "Pheros pheros-learn adapters"], "tests/test_probes.py::test_unavailable_is_reported"),
    ("CM13_self_contained", "The program needs no folder outside its own tree and the project it works on; "
     "committed content carries no user paths.", ["user requirement 2026-10-21", "hub L49", "hub L50", "Pheros L01",
                                                  "Pheros L03"], "tests/test_self_contained.py::test_sources_unreachable"),
    ("CM14_versioned_writes", "Overwriting a card archives the previous version first and verifies the archive "
     "(semver bump + previous_content_hash).", ["hub L35", "Pheros card_versioning", "Pheros L94"],
     "tests/test_kernel.py::test_versioning_archives_previous"),
    ("CM15_observations_are_ground_truth", "Observations are never edited by rules; learned cards cite the "
     "observations and runs they came from, with confidence and evidence_count.", ["Pheros L102", "Pheros L56"],
     "tests/test_learn.py::test_learned_cards_cite_evidence"),
    ("CM16_languages_are_cards", "Languages, operators and backends are cards: the codegen and runners contain "
     "no per-language branches; adding one is adding a card.", ["Pheros L01", "Pheros L26", "rea-cards forms"],
     "tests/test_laws.py::test_engines_have_no_language_branches"),
    ("CM17_translation_coverage_is_measured", "Translation coverage is the op-by-language conformance matrix and "
     "per-construct gaps, computed by running real toolchains.", ["Pheros L115", "Pheros translation_gap"],
     "tests/test_conformance.py::test_conformance_matrix"),
    ("CM18_bounded_work", "Every subprocess has a timeout, every search a node budget; independent work runs in "
     "parallel.", ["hub L20", "hub L32"], "tests/test_laws.py::test_subprocesses_have_timeouts"),
    ("CM19_never_publish_unasked", "Nothing is pushed or published without an explicit request; the program only "
     "writes inside its own tree and the project's .cardmodel/.", ["hub L13", "hub L76"],
     "tests/test_laws.py::test_no_publishing_calls"),
    ("CM20_laws_are_cards", "Laws are cards with a witness test; LAWS.md is generated from them and a test fails "
     "when it drifts.", ["Pheros L63", "hub L19", "hub L38"], "tests/test_laws.py::test_laws_md_in_sync"),
    ("CM21_effects_are_boundaries", "Optimization rewrites only the pure core (functions that lift into the IR); "
     "every other line -- I/O, sockets, login, clocks, module-level code -- stays byte-identical and is never "
     "executed by the optimizer, so protocols and authentication behave exactly as before.",
     ["user requirement 2026-10-21 (play online unchanged)", "hub L3", "Pheros L46"],
     "tests/test_improve.py::test_effect_shell_is_byte_identical"),
    ("CM22_optimizations_self_correct", "A substitution is verified against the original, then re-verified in the "
     "spliced program with a fresh seed and more inputs; any counterexample reverts it to the original before the "
     "output is written.", ["hub L4", "hub L17", "Pheros L41"],
     "tests/test_improve.py::test_refuted_substitution_is_reverted"),
]

GOALS = [
    ("G_C1_languages_verified", "computation", "Codegen target languages available here whose op-conformance "
     "row passes completely.", "languages_fully_conformant", 10, "higher"),
    ("G_C2_op_conformance", "computation", "Share of (op signature x available language) cells that pass, "
     "excluding cells a language card declares UNSUPPORTED.", "op_conformance_rate", 1.0, "higher"),
    ("G_C3_forms_witnessed", "computation", "Share of runnable Python forms of op cards that agree with their "
     "reference on seeded inputs.", "forms_witnessed_rate", 1.0, "higher"),
    ("G_C4_redefinitions_verified", "computation", "Executable redefinitions verified numerically on seeded "
     "points (or proved symbolically when sympy is present).",
     "redefinitions_verified", 111, "higher"),
    ("G_C5_functions_translated", "computation", "Function cards whose forms agree in at least 3 languages.",
     "functions_translated", 20, "higher"),
    ("G_U1_closure", "understanding", "Unresolved depends_on references across all registries.",
     "unresolved_references", 0, "lower"),
    ("G_U2_rules_witnessed", "understanding", "Rewrite rules with a passing numeric witness.", "rules_witnessed", 12,
     "higher"),
    ("G_U3_named_fraction", "understanding", "Named-card fraction on the last observation (card_coverage).",
     "named_fraction", 0.6, "higher"),
    ("G_U4_valid_cards", "understanding", "Cards that fail their card type schema.", "schema_errors", 0, "lower"),
    ("G_L1_learned_cards", "learning", "Cards promoted by the learning loop with cited evidence.", "learned_cards",
     10, "higher"),
    ("G_O1_measured_forms", "optimization", "Runnable forms with a host measurement (metric card).",
     "measured_forms", 30, "higher"),
    ("G_A1_self_contained", "autonomy", "Source folders the program needs at runtime.", "external_dependencies", 0,
     "lower"),
    ("G_A2_runs_on_every_python", "autonomy", "Python interpreters found on this machine that fail to run the "
     "program (portability check in verify).", "python_failures", 0, "lower"),
    ("G_O2_arena_sound", "optimization", "Recorded arena runs that were not sound (end-to-end recheck, effect shell, "
     "decoys).", "arena_unsound_runs", 0, "lower"),
    ("G_O3_arena_recall", "optimization", "Planted suboptimal functions improved in the latest arena run.",
     "arena_recall", 0.9, "higher"),
    ("G_O4_arena_speedup", "optimization", "Geometric-mean measured speedup over improved functions in the latest "
     "arena run.", "arena_geomean_speedup", 10, "higher"),
]

RULES = [
    ("binomial_square_expand", "(a + b) ** 2", "a ** 2 + 2 * (a * b) + b ** 2", ["a", "b"], True, "hub rewrite_search BINOMIAL_SQUARE_EXPAND"),
    ("difference_of_squares", "a ** 2 - b ** 2", "(a + b) * (a - b)", ["a", "b"], True, "hub DIFFERENCE_OF_SQUARES"),
    ("distributivity_left", "a * (b + c)", "a * b + a * c", ["a", "b", "c"], True, "hub DISTRIBUTIVITY_LEFT"),
    ("commutative_add", "a + b", "b + a", ["a", "b"], False, "hub COMMUTATIVE_ADD"),
    ("commutative_mul", "a * b", "b * a", ["a", "b"], False, "hub COMMUTATIVE_MUL"),
    ("additive_identity", "a + 0", "a", ["a"], True, "hub ADDITIVE_IDENTITY"),
    ("multiplicative_identity", "a * 1", "a", ["a"], True, "hub MULTIPLICATIVE_IDENTITY"),
    ("associative_add", "(a + b) + c", "a + (b + c)", ["a", "b", "c"], True, "cardmodel"),
    ("associative_mul", "(a * b) * c", "a * (b * c)", ["a", "b", "c"], True, "cardmodel (MUL_associativity instance in hub cross_language_equiv)"),
    ("square_as_mul", "a ** 2", "a * a", ["a"], True, "Pheros redefinition square_naive"),
    ("double_as_shift", "a * 2", "a << 1", ["a"], True, "hub CONST_MUL_POW2"),
    ("mul_pow2_as_shift", "a * (1 << k)", "a << k", ["a", "k"], True, "hub SHIFT_LEFT.mul_pow2", "k >= 0"),
    ("sub_self", "a - a", "0", ["a"], True, "cardmodel"),
    ("mul_zero", "a * 0", "0", ["a"], True, "cardmodel"),
    ("neg_neg", "-(-a)", "a", ["a"], True, "cardmodel"),
    ("xor_as_or_minus_and", "a ^ b", "(a | b) - (a & b)", ["a", "b"], True, "hub BIT_XOR.add_sub"),
    ("floordiv_pow2_as_shift", "a // (1 << k)", "a >> k", ["a", "k"], True, "hub SHIFT_RIGHT.floordiv", "k >= 0"),
    ("mod_pow2_as_mask", "a % (1 << k)", "a & ((1 << k) - 1)", ["a", "k"], True, "hub MOD.pow2_bit", "k >= 0"),
]

REDEF_HELPERS = '''"""redef_helpers -- helper functions the hub's card_redefinitions forms call.

Ported verbatim from the hub's config/card_redefinitions.py (_xgcd,
_const_pow_chain), 2026-10-21. Forms that list "redef_helpers" in ``libs``
see these names as globals.
"""


def _xgcd(a: int, b: int) -> tuple[int, int, int]:
    """Extended Euclidean -- returns (gcd, x, y) with a*x + b*y = gcd."""
    if b == 0:
        return (a, 1, 0)
    g, x1, y1 = _xgcd(b, a % b)
    return (g, y1, x1 - (a // b) * y1)


def _const_pow_chain(x: int, n: int) -> int:
    if n == 0:
        return 1
    if n == 1:
        return x
    if n == 2:
        return x * x
    if n == 3:
        return x * x * x
    if n == 4:
        y = x * x
        return y * y
    return x ** n
'''


def put(store, card: dict, force: bool, stats: dict) -> None:
    existing = store.get(f"{card['category']}/{card['name']}")
    if existing is not None and not force:
        stats["kept"] += 1
        return
    _, changed = store.save(card, layer="model")
    stats["written" if changed else "kept"] += 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--force", action="store_true", help="rewrite existing built-in cards (versioned)")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    stats = {"written": 0, "kept": 0}
    for name, (desc, tier) in REGISTRIES.items():
        store.ensure_registry(name, layer="model", description=desc, tier=tier, defined_by="tools/bootstrap.py")

    for t in CARD_TYPES:
        put(store, {"category": "card_type", "tier": 0, "provenance": PROV, **t}, args.force, stats)
    for d in DOMAINS:
        put(store, {"category": "domain", "tier": 0, "provenance": PROV, **d}, args.force, stats)
    for lang in SL.LANGUAGES:
        put(store, {"category": "language", "provenance": PROV, **lang}, args.force, stats)
    for lang in SL.OBSERVE_ONLY:
        put(store, {"category": "language", "tier": 2, "provenance": PROV,
                    "statement": f"{lang['name']}: recognised by the observer; no codegen block yet.", **lang},
            args.force, stats)
    hub_prov = {"origin": "hub", "files": ["config/card_redefinitions.py", "config/card_catalog.py",
                                            "config/language_hints.py"], "read_on": "2026-10-21"}
    for op in SO.OPS:
        card = {"category": "op", "provenance": {**hub_prov, **PROV} if op.get("forms") else PROV, **op}
        hints = SO.HINTS.get(op["name"])
        if hints:
            card["hints"] = {lang: {"snippet": h[0], **({"notes": h[1]} if len(h) > 1 and h[1] else {}),
                                    **({"imports": h[2]} if len(h) > 2 else {})} for lang, h in hints.items()}
        put(store, card, args.force, stats)
    for r in RULES:
        name, lhs, rhs, vars_, bidi, origin = r[:6]
        cond = r[6] if len(r) > 6 else None
        put(store, {"name": name, "category": "rewrite_rule", "tier": 1, "lhs": lhs, "rhs": rhs, "vars": vars_,
                    "domain": "int", "condition": cond, "bidirectional": bidi,
                    "statement": f"{lhs} == {rhs}" + (f" when {cond}" if cond else ""),
                    "provenance": {"origin": origin, **PROV}}, args.force, stats)
    for name, statement, origins, witness in LAWS:
        put(store, {"name": name, "category": "law", "tier": 0, "statement": statement, "origins": origins,
                    "witness": witness, "provenance": PROV}, args.force, stats)
    for name, axis, statement, metric, target, direction in GOALS:
        put(store, {"name": name, "category": "goal", "tier": 0, "axis": axis, "statement": statement,
                    "metric": metric, "target": target, "direction": direction, "provenance": PROV}, args.force, stats)
    for a in SA.ALGORITHMS:
        put(store, {"category": "algorithm", "provenance": PROV, **a}, args.force, stats)
    # library: redef_helpers (bit_primitives is vendored from the hub by tools/vendor_import.py)
    put(store, {"name": "redef_helpers", "category": "lib", "tier": 0, "module_alias": "rh", "export_names": True,
                "statement": "Helpers used by ported card_redefinitions forms (_xgcd, _const_pow_chain).",
                "variants": {"python.py": {"kind": "file"}}, "provenance": hub_prov}, args.force, stats)
    lib_dir = store.layer_root("model") / "lib" / "redef_helpers"
    (lib_dir / "python.py").write_text(REDEF_HELPERS, encoding="utf-8")
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
