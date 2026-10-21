# GOALS

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
| `G_U3_named_fraction` | understanding | named-card fraction of the last observation (hub card_coverage) | ≥ 0.6 |
| `G_U4_valid_cards` | understanding | cards failing their card-type schema | = 0 |
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
| `G_D1_design_laws` | design | design laws failing on the neutral exchange | = 0 |
| `G_D2_equilibrium_support` | design | options the exact neutral equilibrium mixes | ≥ 8 |

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

## Non-goals (and why)

* **A general compiler for arbitrary Python.** The IR covers a verified subset: integer, float and bool functions with
  control flow. Anything outside it is reported construct by construct, never pasted through (Pheros v_transpile's
  `raw` nodes made "translated" ambiguous).
* **Third-party dependencies.** Python's standard library and the host's own toolchains only. `sympy` and
  `cryptography` are optional capabilities that are probed when present and never required.
* **Editing user source files.** Rewrites are suggestions with evidence (hub L3: surgical edits are a human or agent
  decision).
