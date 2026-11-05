#!/usr/bin/env python3
"""seed_pipeline — every capability in the main pipeline, at a stated tier (law CM50, engines/pipeline.py).

  capability/*.pipeline   per capability: the tier of the evidence its pipeline run gives (CM46), why that tier,
                          the verify sections and self-run steps that exercise its engine, and, where part of it runs
                          nowhere in the pipeline, the gap with its reason, what would close it and its goal
  card_type/capability    the schema gains ``pipeline`` (required)
  capability/integration  carries CM50, its module and witness test
  law/CM50                every capability runs in the main pipeline
  goal/G_A13              recorded pipeline gaps: 0
  capability/*.godel      per capability: its Gödel verdict (GODEL_AUDIT §2, §4) with what it needs (a-e) or why
                          not (i-v); where a CORE or KEYED capability's code does not call the core yet, the gap with
                          the audit's change as what closes it; the known copies of the core's algebra it holds
  goal/G_A14              recorded Gödel impurities: 0

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

GOAL_G = "goal/G_A14_godel_pure"


def U(row, closes_by):
    """A CORE or KEYED capability whose code does not call the core yet: GODEL_AUDIT §4's row says "Gödel today:
    none", and its "change" column is what closes it."""
    return {"reason": f"GODEL_AUDIT §4 ({row}): Gödel today none; its code does not call engines/godel.py",
            "closes_by": closes_by, "goal": GOAL_G}


OWNER = "the Gödel thread; GODEL_AUDIT §6 follow-up"


def C(at, rule, reason, closes_by):
    """A known copy of the core's algebra outside engines/godel.py, as the integrity check finds it (``rule``). These
    files belong to the owner's Gödel thread: recorded here, not edited, so that integrity passes today and any new
    copy fails; the list only shrinks (tests/test_pipeline.py)."""
    return {"at": at, "rule": rule, "reason": reason, "closes_by": closes_by, "owner": OWNER, "goal": GOAL_G}


# name: (verdict, needs (a-e) or reason (i-v), why, unwired gap or None, copies)
GODEL = {
    "card_store": ("KEYED", "a, b, d, e", "kernel/store.py: every card is stored, cached and shared; identity, content "
                   "and basis columns belong in its index (GODEL_AUDIT §4.3)",
                   U("kernel/store.py", "index columns: identity hash with its relation, basis version, a posting "
                     "table of content read through godel.resolve; by_identity, divides, multiples"), []),
    "honest_limits": ("NO", "ii", "probes start processes and read the host (GODEL_AUDIT §4.3: probes NO)", None, []),
    "witnesses": ("NO", "i", "a witness computes meaning in M (GODEL_AUDIT §4.2: witness NO (i))", None, []),
    "form_selection": ("KEYED", "a", "optimize calibrates the op-cost vector, the c in cost = <content, c>; rewrite "
                       "picks implementations (NO ii) (GODEL_AUDIT §4.2)",
                       U("engines/optimize.py", "key metric rows by the definition's identity so equal functions "
                         "share timings; the calibrated costs as godel.cost's vector"), []),
    "boundaries": ("NO", "ii", "static checks of the program's text (GODEL_AUDIT §4.3: selfcheck, integrity NO)", None,
                   []),
    "learning": ("KEYED", "d", "learn dedupes and names proposals; observe is a CONSUMER (GODEL_AUDIT §4.2)",
                 U("engines/learn.py", "dedupe proposals by alpha-identity and name a suggestion by identity, not "
                   "file:line"), []),
    "translation": ("CORE", "c", "codegen and conformance are the carry map from the op atoms to each language, with "
                    "its gap; translate keys function cards (GODEL_AUDIT §4.1)",
                    U("engines/codegen.py", "carry_map(lang) over the op@rank atoms with its gap; "
                      "gap(module, lang) = support(content) & gap(lang) checked before emitting"), []),
    "rewriting": ("KEYED", "d", "search keys its states by repr (GODEL_AUDIT §4.2)",
                  U("engines/search.py", "key states by identity, not repr; share the deduped rules with the e-graph"),
                  []),
    "law_discovery": ("KEYED", "d", "laws re-witnesses candidates already stored as theorems (GODEL_AUDIT §4.2)",
                      U("engines/laws.py", "skip candidates whose alpha+sort identity is already a stored theorem "
                        "(162 of 3,310)"), []),
    "theorems": ("KEYED", "a, d", "theorem cards have no identity: 87 redundant under alpha (GODEL_AUDIT §4.2)",
                 U("engines/theorems.py", "an identity per statement; dedupe the store; cache Lean results by "
                   "identity"), []),
    "lean": ("CORE", "c", "emitting Lean is a carry map into Lean's signature; lean_import its inverse (KEYED a, c) "
             "(GODEL_AUDIT §4.1)",
             U("emit/lean.py", "delete the private LEAN_INFIX table; read the image from the op cards' emit.lean "
               "through the codegen carry, NotExpressible as its gap"), []),
    "logic": ("NO", "i", "derivation computes meaning over facts; a tuple is already an injective hash-consed name "
              "(GODEL_AUDIT §4.2: logic NO)", None, []),
    "card_language": ("KEYED", "d", "the parser and compiler are syntax (NO ii); lang/run builds function cards "
                      "keyed like translate's (GODEL_AUDIT §4.1)",
                      U("lang/run.py", "the same card builder as translate (identity and content); emit_gaps from "
                        "the codegen gap"), []),
    "self_theory": ("CONSUMER", "", "selflogic reports facts about the store, the ledger among them (GODEL_AUDIT "
                    "§4.2: selflogic CONSUMER)", None, []),
    "function_algebra": ("CORE", "a, b", "a Gödel numbering of behaviours: canonical recurrences, GCD of functions "
                         "(GODEL_AUDIT §4.2: CORE, to be changed)", None,
                         [C("cardmodel/engines/funcalg.py:godel_encode", "prime power",
                            "a positional number of a recurrence composed by hand, prod p_i ** (zig(a_i) + 1) (one "
                            "stored at 672 digits, past CM45's cap, against GM-2)",
                            "identity = the hash of the canonical form; annihilators factored into irreducibles as "
                            "atoms of a behaviour set (GODEL_AUDIT §4.2)")]),
    "redefinitions": ("KEYED", "d", "redefinitions are sampled one by one; 111 cards cover 40 concepts (GODEL_AUDIT "
                      "§4.2)", U("engines/redefs.py", "decide by realnorm.canonical first; group cards by source "
                                 "identity; a one-op left side as the ledger's deprecate trigger"), []),
    "improve": ("KEYED", "d", "the rewrite search repeats on equal subterms (GODEL_AUDIT §4.2); the arena is a "
                "CONSUMER", U("engines/improve.py", "memoize cheapest_rewrite by the subterm's alpha-identity (no "
                              "content lower bound: measured, it prunes 0 of 132)"), []),
    "resources": ("NO", "ii", "the memory and CPU governor runs processes (GODEL_AUDIT §4.3)", None, []),
    "game_design": ("NO", "iv", "an exact simplex over values; moves are frame-data records, not terms (GODEL_AUDIT "
                    "§4.3: game NO (iv))", None, []),
    "world": ("NO", "iv", "Datalog facts about a world's values (GODEL_AUDIT §4.3: game NO (iv))", None, []),
    "machines": ("CONSUMER", "", "isa compiles semantics and could give one handler per identity class; bench's "
                 "per-card data differ between identical terms (GODEL_AUDIT §4.3)", None, []),
    "emulation": ("KEYED", "d", "lifted blocks are cached by ROM and address, not by what they compute; the runtime "
                  "engines are NO (ii) (GODEL_AUDIT §4.3)",
                  U("machine/lift.py", "address emitted functions by structural identity with integer constants as "
                    "parameters; a cross-ROM block cache keyed by it"), []),
    "arcade": ("NO", "ii", "builds, servers, downloads: bytes and card JSON (GODEL_AUDIT §4.3)", None, []),
    "live_hub": ("NO", "ii", "a server of project status (GODEL_AUDIT §4.3: arcade NO (ii))", None, []),
    "anyps5": ("NO", "ii", "observations of a C++ project's text: no terms (GODEL_AUDIT §4.3: NO, no terms)", None, []),
    "godel_model": ("CORE", "a, b, c, d, e", "the core itself: ledger, content, structure, carry; numbering (W-5) and "
                    "codes (W-3) are its numberings and their measurement (GODEL_AUDIT §4.2)", None,
                    [C("cardmodel/engines/numbering.py:Numbering.tokens", "core name",
                       "each set's own copy of the 3k + 1 positional scheme (GODEL_AUDIT §4.3: the second of three)",
                       "godel.tokens with the set's dense ranks (the owner's decision: positional codes by per-set "
                       "dense ranks)"),
                     C("cardmodel/engines/numbering.py:Numbering.encode", "prime power",
                       "composes the positional number from nth_prime by hand", "godel.structural over the set's "
                       "tokens"),
                     C("cardmodel/engines/codes.py:Reader.codes", "tokens",
                       "the Def-27 token codes (3k+1, 3·zig+2, 3j+3) written out again to measure code sizes (W-3)",
                       "godel.tokens over the reader's tree"),
                     C("cardmodel/engines/codes.py:_head_code", "tokens",
                       "a node's Def-27 token code, the same scheme a third time", "godel.tokens of the head"),
                     C("cardmodel/engines/codes.py:built_positional_bits", "prime power",
                       "builds a positional number by hand to measure its size (small codes only)",
                       "godel.structural's bit length")]),
    "self_run": ("KEYED", "a, d", "the cycle keys its steps by JSON hashes of whole registries (GODEL_AUDIT §4.3: "
                 "selfrun KEYED, Gödel today none, runs godel through verify)",
                 U("engines/selfrun.py", "function units keyed by the canonical term's hash, content work by basis "
                   "version, the godel section cached by its input hash; learn dedupes by identity, not name"), []),
    "distillation": ("CORE", "a, d", "the e-graph's semantic_hash is the identity (GODEL_PURITY 1); its rules are "
                     "KEYED (GODEL_AUDIT §4.2)", None, []),
    "integration": ("NO", "ii", "integrity and the pipeline check read names, text and imports (GODEL_AUDIT §4.3: "
                    "integrity NO); they report the Gödel verdicts and check the core is not copied", None, []),
    "symbolic_instructions": ("CORE", "a, c", "instruction terms as definitions with identity and content "
                              "(GODEL_AUDIT §4.3: CORE for the LR35902)", None, []),
    "four_sources": ("CORE", "a, b", "where identity and content are minted (GODEL_AUDIT §4.2: sources CORE)", None,
                     []),
    "witness_tiers": ("KEYED", "d", "proof results are recomputed per claim (GODEL_AUDIT §4.2: tiers KEYED (d))",
                      U("engines/tiers.py", "cache proof results by (identity pair, relation); its Poly on the "
                        "shared type"), []),
    "formal_core": ("CORE", "a, b, c", "the Gödel model's own mathematics in Lean: the ground truth (GODEL_AUDIT "
                    "§4.3: formal/GodelCore CORE)", None, []),
    "unreal_math": ("CORE", "b, c", "canonical forms over the reals, content, and the named -> core carry map "
                    "(GODEL_AUDIT §4.3: unreal/distill CORE, partly a copy of godel.py)", None,
                    [C("cardmodel/unreal/distill.py:number", "prime power",
                       "composes prod p ** e from the ledger's primes by hand (dead code: nothing calls it)",
                       "delete it, or godel.py for the number's digits (CM45: the vector is the exact "
                       "factorization; no integer is stored)")]),
}

LAW = ("CM50_every_capability_runs_in_the_pipeline",
       "Every capability runs in the main pipeline: its card declares the tier of the evidence that run gives (CM46) "
       "and the verify sections or self-run steps that exercise its engine, and the pipeline check holds each "
       "declared stage to the code (it must reach the capability's modules). A capability that no stage runs, or "
       "part of one, is a recorded gap with its reason, what would close it and the goal that counts it; a "
       "capability with neither a run nor a gap fails verify. The smoke check (CM37) does not count as running. "
       "Each card also records its Gödel verdict (GODEL_AUDIT §2: CORE, KEYED, CONSUMER, or NO with its reason i-v): "
       "a CORE or KEYED capability whose code does not call the core, and any code outside engines/godel.py and "
       "godel1931.py that defines primes, content or the zigzag, is a recorded impurity with its goal or fails.",
       ["user requirement 2026-11-05 (every capability in the main pipeline, with its tier and a coverage check)"],
       "tests/test_pipeline.py::test_a_capability_never_run_fails")

GOALS = [("G_A13_pipeline_gaps", "autonomy",
          "Recorded pipeline gaps: capabilities, or parts of them, that no verify section or self-run step exercises "
          "(CM50; `cardmodel pipeline` lists them with their reasons).", "pipeline_gaps", 0, "lower"),
         ("G_A14_godel_pure", "autonomy",
          "Recorded Gödel impurities: CORE or KEYED capabilities whose code does not call the core, and code outside "
          "engines/godel.py that defines primes, content or the zigzag or composes a Gödel number by hand (CM50, "
          "GODEL_AUDIT §2, GODEL_TARGET §7; `cardmodel pipeline`).", "godel_impure", 0, "lower")]

SCHEMA_PIPELINE = {
    "type": "object", "required": ["tier", "tier_reason", "runs"],
    "properties": {"tier": {"type": "string", "enum": ["proof", "probabilistic", "bounded", "sample"]},
                   "tier_reason": {"type": "string"},
                   "runs": {"type": "array", "items": {"type": "object"}},
                   "gap": {"type": "object", "required": ["reason", "closes_by", "goal"],
                           "properties": {"reason": {"type": "string"}, "closes_by": {"type": "string"},
                                          "goal": {"type": "string"}}}}}


GAP_SCHEMA = {"type": "object", "required": ["reason", "closes_by", "goal"],
              "properties": {"reason": {"type": "string"}, "closes_by": {"type": "string"}, "goal": {"type": "string"}}}
SCHEMA_GODEL = {
    "type": "object", "required": ["verdict", "why"],
    "properties": {"verdict": {"type": "string", "enum": ["CORE", "KEYED", "CONSUMER", "NO"]},
                   "needs": {"type": "string"}, "reason": {"type": "string", "enum": ["i", "ii", "iii", "iv", "v"]},
                   "why": {"type": "string"}, "gap": GAP_SCHEMA,
                   "copies": {"type": "array", "items": {"type": "object", "required": ["at", "rule", "reason",
                                                                                         "closes_by", "owner", "goal"]}}}}


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
        verdict, need, gwhy, ggap, copies = GODEL[name]
        card["godel"] = {"verdict": verdict, **({"needs": need} if verdict in ("CORE", "KEYED") else {}),
                         **({"reason": need} if verdict == "NO" else {}), "why": gwhy,
                         **({"gap": ggap} if ggap else {}), **({"copies": copies} if copies else {})}
        if name == "godel_model":
            card["modules"] = list(dict.fromkeys([*(card.get("modules") or []), "cardmodel/engines/numbering.py",
                                                  "cardmodel/engines/codes.py"]))
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
    schema["properties"]["godel"] = SCHEMA_GODEL
    schema["required"] = list(dict.fromkeys([*schema.get("required", []), "pipeline", "godel"]))
    ct["schema"] = schema
    ct["statement"] = ("A core capability: its smoke check must pass in every verify and self-run (CM37), and it "
                       "declares its evidence tier, where the main pipeline runs it and its Gödel verdict (CM50).")
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
