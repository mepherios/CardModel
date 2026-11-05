# GOALS

## What the card model is: a universal Gödel model that keeps expanding

In the user's words (2026-10-22): *Gödel numbers are fact, but we can have different and infinitely expanding Gödel
sets; that is where it becomes special. We have basis Gödel numbers, then we use the same logic for programming
languages, and math, and physics, and we make them carry over infinitely: a universal Gödel expanding model. That is
what the card model is supposed to be.* Made precise:

1. **Atoms get primes, forever.** A basis set B₀ numbers the primitive concepts (logic, equality, arithmetic, bit
   operations). Each atom gets a prime that is never renumbered or reused: the ledger only grows.
2. **Every domain is a Gödel set extending B₀**: programming languages, mathematics, physics, and any domain to
   come. A new atomic concept (a card) takes the next unused prime. There are infinitely many primes (Euclid), so
   every set expands without limit.
3. **Two numberings, two jobs.**
   * *Content* is a concept's factorization: the product of its constituents, with multiplicity (an exponent
     vector). With negative exponents allowed, products have inverses: the positive rationals, i.e. the free abelian
     group on the primes. Physics is the cleanest witness. The base units (s, m, kg, A, K, mol, cd) are primes and a
     derived quantity is a product (N = kg·m·s⁻²), so dimensional analysis is exactly this algebra. GCD and LCM are
     the shared and the combined content of two concepts.
   * *Structure* is Gödel's own positional numbering (∏ pᵢ^code(symbolᵢ), nested for trees). It keeps order and
     arrangement and decodes exactly, so a concept's identity is its structural number. Content forgets arrangement:
     f(g(x)) and g(f(x)) have the same factors.
4. **Carry-over is a homomorphism.** A map between two sets is fixed by where it sends each prime. It preserves
   products and divisibility, and maps compose, so knowledge carries along any chain (a language to the IR to
   another language; mathematics to physics). A map preserves every GCD exactly when it sends distinct primes to
   coprime images. The source primes a map cannot send are that translation's gap: a concept splits into the part
   that carries and a residual factor. Every set embeds in one universal ledger (the direct limit), where GCD and
   LCM find the logic any domains share.
5. **Laws, each with a witness, when built:**
   * the ledger is append-only;
   * every card carries its Gödel vector in each set it belongs to;
   * every translation is a homomorphism card, checked to preserve products, with its GCD condition computed;
   * a translation's correctness is still witnessed by behaviour (equal outputs on seeded inputs);
   * a `translation_gap` card is the residual factor a map leaves.

**Already in the model:**
* positional Gödel numbers of canonical forms, with exact decoding (CM31, `engines/funcalg.py`);
* the GCD of functions (shared annihilators, common factors);
* translation-gap cards per language pair;
* cross-language equivalence cards from learning;
* op cards as the atoms of computation;
* content hashes as every card's identity.

**Not built yet:**
* the prime ledger;
* Gödel vectors on every card;
* homomorphism cards;
* the physics set (units, dimensional analysis).

ROADMAP "Gödel model" has the steps.

**Honest limits.** A factor multiset forgets arrangement, so the structural number stays the identity. GCD carries
over only under the coprimality condition above. What a factor means depends on canonicalization: two equivalent
constructions share factors only once both reduce to the same atoms (canonical forms and rewrite rules do that
for functions).

## Purpose

**cardmodel** is the card model as one self-contained program. Every structure is a card: languages, operators, rules,
laws, goals, the observations it makes, the functions it learns and the measurements it takes. Each card lives in a
filesystem registry. The program takes part in software development in any project folder. It can:

1. **observe** code and express what the code does as cards;
2. **verify** every executable claim by running it (seeded, reproducible, with anti-vacuity checks);
3. **translate** functions into other languages through the card IR, and prove each translation by running it;
4. **learn** new cards from what it observes, promoting them only with evidence;
5. **optimize**: pick the cheapest equivalent form, find cheaper equivalent expressions, and measure real costs;
6. **improve** whole programs: substitute verified faster algorithms (including scaled/shifted matches) in the pure
   core, leave the effect shell (I/O, network, login) byte-identical, and re-check the result. See
   docs/METHODOLOGY.md and the arena.

7. **reason**: rules are cards (if x, y -> z) with proofs the Lean kernel checks; the model's own laws are
   logic over its store; rules can be deciphered from data and from code;
8. **know**: theorem cards climb an evidence ladder (refuted < conjecture < witnessed < proved), from discovered
   laws, card-language theorems and Lean's own library (faithfully read, witnessed, re-proved), and the
   simplifying laws carry into optimization (docs/KNOWLEDGE.md);
9. **speak one language**: functions, logic, theorems, tests and cards in one source language that compiles to
   cards and to every language card (docs/LANGUAGE.md);
10. **design a game**: the Vector Counter System, whose design laws are computed on exact equilibria and whose
    world carries every consequence with its cause (game/DESIGN.md).
11. **account for a real system**: AnyPS5 (a PS5 relinker and its reimplemented system libraries) read as cards,
    its badge reproduced, its real coverage computed, every gap given the cause that keeps it open, and its pure
    code witnessed against semantics derived from public standards (docs/ANYPS5.md).
12. **run machines**: a CPU is its instruction cards and a console is its hardware cards; their card-language
    semantics compile to the card IR, run in every engine, and a ROM's own code is lifted into the same IR and
    emitted natively, behind an effect shell for video, audio, input and saves (docs/MACHINES.md); games made of
    cards ship through the Cardmodel Arcade store (docs/ARCADE.md, docs/STORE.md).
13. **run itself as one unit**: every use can start a cycle that checks the core capabilities and the program's
    integrity, verifies, learns, rediscovers, measures and computes every goal, then ranks its own flaws and
    weaknesses; the core capabilities are cards that carry every law, so none is lost (docs/AUTONOMY.md).

At runtime it needs only its own folder and the project it is pointed at. That is a goal with a test
(`tests/test_self_contained.py`), not just a hope.

## Axes and measurable goals

The hub's `PLAN_UNIVERSAL_MATH.md` named two axes: *computation* and *understanding*. This program adds three
operational axes: *learning*, *optimization* and *autonomy*. Every goal is a card in `cards/goal/`. Each card names a
metric that the program computes (`cardmodel status`, `cardmodel cover`). The current values are in the generated
`COVERAGE.md` and are never typed here (L38).

| goal card | axis | metric (computed) | target |
|---|---|---|---|
| `G_C1_languages_verified` | computation | codegen languages available here whose op-conformance row passes completely | ≥ 10 |
| `G_C2_op_conformance` | computation | passing (op signature × available language) cells / all cells that count | = 1.0 |
| `G_C3_forms_witnessed` | computation | runnable op forms agreeing with their reference on seeded inputs | = 1.0 |
| `G_C4_redefinitions_verified` | computation | executable redefinitions verified numerically (or proved with sympy) | ≥ 111 |
| `G_C5_functions_translated` | computation | function cards whose forms agree in ≥ 3 implementations | ≥ 20 |
| `G_U1_closure` | understanding | unresolved `depends_on` references (L45) | = 0 |
| `G_U2_rules_witnessed` | understanding | rewrite rules with a passing numeric witness | ≥ 12 |
| `G_U3_named_fraction` | understanding | named-card fraction of the model's own code (`cardmodel/`), newest observation of it (hub card_coverage) | ≥ 0.6 |
| `G_U4_valid_cards` | understanding | cards failing their card-type schema | = 0 |
| `G_U5_content_vectors` | understanding | fraction of op, function and algorithm cards whose content vector is computed (CM43) | ≥ 1.0 |
| `G_U6_definitions` | understanding | fraction of algorithm and function cards with a definition card (truth, CM44) | ≥ 1.0 |
| `G_U7_canonical_definitions` | understanding | fraction of definitions with a canonical form (e-graph or recurrence) | ≥ 0.9 |
| `G_U8_formal_core` | understanding | problems in the formal core: a theorem card whose Lean theorem is missing or rests on more than the standard axioms, any sorry, a failed build (handover R1) | = 0 |
| `G_U10_engine_math_lifted` | understanding | fraction of a game engine's math universe (Unreal Engine's functions over numbers) lifted to definitions (CM49) | ≥ 0.9 |
| `G_U11_engine_math_witnessed` | understanding | fraction of the engine's definitions witnessed against its own compiled code, bit-exact or within a few ulps (CM49) | ≥ 0.9 |
| `G_U12_engine_math_refuted` | understanding | engine functions whose lifted term the witness refutes (CM49) | = 0 |
| `G_U9_algorithm_forms_proved` | understanding | fraction of the algorithm cards' other Python forms proved equal to their definition (a sized witness or a kernel proof), not sampled (handover R3) | ≥ 0.5 |
| `G_L1_learned_cards` | learning | cards promoted by the learning loop with cited evidence | ≥ 10 |
| `G_O1_measured_forms` | optimization | forms with a host measurement (metric card) | ≥ 30 |
| `G_A1_self_contained` | autonomy | source folders needed at runtime (sandbox check) | = 0 |
| `G_A2_runs_on_every_python` | autonomy | Python 3.9+ interpreters on this machine that fail to run the program | = 0 |
| `G_O2_arena_sound` | optimization | recorded arena runs that were not sound | = 0 |
| `G_O3_arena_recall` | optimization | planted suboptimal functions improved in the latest arena run | ≥ 0.9 |
| `G_O4_arena_speedup` | optimization | geometric-mean measured speedup in the latest arena run | ≥ 10 |
| `G_K1_theorems_proved` | knowledge | theorem cards with a proof (Lean kernel or exhaustive) | ≥ 150 |
| `G_K2_lean_imported` | knowledge | Lean core theorems read faithfully (kernel-checked reading) | ≥ 300 |
| `G_K3_lean_mismatches` | knowledge | imported Lean-proved statements the card semantics refute | = 0 |
| `G_K4_self_violations` | knowledge | violations of the model's own laws as logic (stdlib/self.card) | = 0 |
| `G_K5_programs_pass` | knowledge | card-language programs (examples/lang, stdlib) that pass | ≥ 6 |
| `G_K6_functional_identities` | knowledge | identities between functions found from behaviour | ≥ 5 |
| `G_A3_memory_bounded` | autonomy | peak memory of the cardmodel process in the last verify (MB) | ≤ 1024 |
| `G_A4_capabilities_failing` | autonomy | core capabilities whose smoke check fails (CM37) | = 0 |
| `G_A5_integrity_problems` | autonomy | integrity problems: duplicate numbers, uncarried laws, undescribed commands, sections or docs, drift (CM39) | = 0 |
| `G_A6_laws_carried` | autonomy | laws that no capability card carries | = 0 |
| `G_A7_self_run_fresh` | autonomy | hours since the last self-run cycle finished (CM38) | ≤ 24 |
| `G_A8_project_cards_current` | autonomy | project cards missing detail, stale, or missing for a branch with unmerged work (CM41) | = 0 |
| `G_A9_actions_without_truth` | autonomy | actions (implementations) that name no definition (CM44) | = 0 |
| `G_D1_design_laws` | design | design laws failing on the neutral exchange | = 0 |
| `G_D2_equilibrium_support` | design | options the exact neutral equilibrium mixes | ≥ 8 |
| `G_P1_anyps5_badge_reproduced` | computation | libraries where the model's reading of AnyPS5's counting rule differs from AnyPS5's own tool | = 0 |
| `G_P2_anyps5_gaps_unclassified` | understanding | AnyPS5 gaps (exports, debt entries, empty modules) without a cause | = 0 |
| `G_P3_anyps5_closable_open` | computation | AnyPS5 gaps the model can derive and express in the IR now but has not closed with a passing witness | = 0 |
| `G_P4_anyps5_complete_fraction` | computation | AnyPS5's declared exports complete by its own records (implemented, not empty, total, no stub reached, no open debt) | ≥ 1.0 |
| `G_P5_anyps5_witness_disagreements` | computation | inputs where AnyPS5's code and the model's derived semantics disagree in the latest witness runs | = 0 |
| `G_M1_isa_conformance` | machines | instruction cards failing per-instruction conformance (engines, cycles, flags, vectors) | = 0 |
| `G_M2_roms_boot` | machines | fraction of surveyed ROMs that boot and animate in the native engine | ≥ 0.95 |
| `G_M3_lifted_identical` | machines | differential runs where lifted code and the interpreter disagree | = 0 |
| `G_M4_test_roms` | machines | fraction of hardware test ROMs (Blargg, mooneye, acid2) passing | = 1.0 |
| `G_M5_ds_decoded` | machines | DS instructions executed that no ARM/Thumb card decodes | = 0 |
| `G_M6_symbolic_instructions` | machines | instruction cards whose symbolic terms agree with their executable semantics (LR35902 and ARM) | ≥ 679 |
| `G_A10_law_witnesses_pass` | autonomy | law cards whose witness test fails, errs or is missing in the last self-run's `law_witnesses` step (CM20, CM38) | = 0 |
| `G_A11_scale_slope` | autonomy | time per function at the largest size of the newest `cardmodel scale bench --record` ÷ at 10³ (synthetic projects; SCALING.md §6) | ≤ 2 |
| `G_A12_scale_memory_bound` | autonomy | peak memory (MB) of the child that measured the largest size of the newest scale bench (SCALING.md §6: at 10⁶) | ≤ 2048 |
| `G_A13_pipeline_gaps` | autonomy | recorded pipeline gaps: capabilities, or parts of them, that no verify section or self-run step exercises (CM50; `cardmodel pipeline`) | = 0 |
| `G_A14_godel_pure` | autonomy | recorded Gödel impurities: CORE or KEYED capabilities whose code does not call the core, and copies of its algebra outside engines/godel.py (CM50; `cardmodel pipeline`) | = 0 |
| `G_S1_store_launches` | products | catalogue items that do not install, verify, repair and launch through the arcade's store in the last check (CM42) | = 0 |

### What "done" would mean on each axis

* **Computation.** Any function in the liftable subset can be translated into every language card. Every op template
  is checked in every language on every run of `cardmodel verify`. Every translation shows its evidence: the seed, the
  number of checks and the counterexample when one fails.
* **Understanding.** Every card resolves its references and validates against its type. Identities are witnessed
  numerically, and proved formally where a toolchain allows. Vendored knowledge (Pheros computation primitives,
  redefinition notes, translation gaps) keeps its provenance, and each item is marked as executable or knowledge-only.
* **Learning.** Running `cardmodel learn` on a codebase raises the named fraction and adds function cards. Nothing is
  promoted without evidence.
* **Optimization.** Cost anchors converge to host measurements, and every speed claim cites a metric card. The
  arena stays sound at any size, and recall and speedup rise as algorithm cards are added.
* **Autonomy.** Copy the folder to another machine with Python 3.10+, and the program runs, verifies itself and reports
  which toolchains it found there.
* **A real system (AnyPS5).** Every declared export complete, or its gap closed with a witness, or its gap named with
  the observation, boundary or measurement that would close it. `G_P4` stays below its target as long as the console's
  undocumented behaviour, its hardware and its services are part of what AnyPS5 must reproduce: that part closes by
  observation (Pheros L102), not by construction (docs/ANYPS5.md says exactly what remains and why).
* **Autonomy, as one unit.** Every law's witness test passes in every self-run that runs them.
* **Products.** Every game in the store's catalogue builds from its cards and launches through the store.
* **Machines.** Every instruction card agrees with its own data and across engines; the hardware test suites pass;
  every game in a collection boots, and lifted code is frame-for-frame identical to the interpreter; for the DS,
  every executed instruction decodes and the unmodelled hardware the games touch shrinks to nothing.

## Non-goals (and why)

* **A general compiler for arbitrary Python.** The IR covers a verified subset: integer, float and bool functions with
  control flow. Anything outside it is reported construct by construct, never pasted through (Pheros v_transpile's
  `raw` nodes made "translated" ambiguous).
* **Third-party dependencies.** Python's standard library and the host's own toolchains only. `sympy` and
  `cryptography` are optional capabilities that are probed when present and never required.
* **Editing user source files.** Rewrites are suggestions with evidence (hub L3: surgical edits are a human or agent
  decision).
