# PIPELINE.md: the stage registry

Reference page for `cardmodel/engines/pipeline.py` and the `stage` cards. The live registry is what the command
prints: `cardmodel pipeline stages --verbose`. Law CM50: *Every transformation from an input to its outputs runs every stage whose hypothesis the input satisfies, and its record has one entry per registered stage: ran with its evidence, or skipped, not requested, unavailable or failed with the reason. The set of stages that run is computed from the stage cards, never remembered by a command, and the coverage check fails when a stage function is named by no card, an engine is reached by no stage and named outside the pipeline by no reason, or a stage applies to nothing.*

## Commands and checks

- `cardmodel translate FILE [--to L,...] [--only STAGES] [--deep] [--measure] [--save] [--stages]`: the pipeline on
  every function of a file; `--stages` prints the record of every stage.
- `cardmodel pipeline stages`: the registry in order. `cardmodel pipeline check`: the coverage check (also the
  `pipeline` verify section, the `pipeline` capability and goal `G_A13_pipeline_coverage`).
- `cardmodel pipeline run FILE`: the full record as text or `--json`.

## The record

One entry per stage per function, with a status and, when it did not run, the reason: `ran` (with the stage's
evidence and verdict), `skipped` (the fact or the stage it needed), `not_requested` (the option that asks for it),
`unavailable` (what this host lacks), `failed` (the exception and where). A fact's prefix says what it is: `opt:` an
option, `host:` a probe of this machine, the rest read from the IR by `profile` or set by a stage (`canonical`,
`reduced` by `canon`; `class_known` by `class`; `verified` by `witness_targets`).

## The stages

| order | stage | group | runs when | needs | engines | rests on |
|---|---|---|---|---|---|---|
| 10 | `lift` | terms | always | - | frontend_python.py, frontends.py | D3, A1 |
| 20 | `profile` | terms | lifted | lift | analyse.py, ir.py, sorts.py | D1, D3 |
| 30 | `reference` | terms | lifted | profile | translate.py | D4 |
| 40 | `canon` | identity | lifted, straight_line | reference | egraph.py, exprs.py, search.py | D6, D7, A3 |
| 50 | `identity` | identity | lifted | reference | equivalence.py, exprs.py, numbering.py, sources.py | D7, D9, A4 |
| 60 | `content` | identity | lifted | reference | godel.py | D11, D12 |
| 70 | `real` | identity | lifted, straight_line, int_sorted | reference | exprs.py, realnorm.py | D9 |
| 80 | `behaviour` | identity | lifted, one_int_param | reference | funcalg.py | D9 |
| 90 | `class` | evidence | lifted, int_sorted | reference | tiers.py | D10 |
| 100 | `sized_witness` | evidence | lifted, canonical, reduced, class_known | canon, class | codegen.py, tiers.py | D7, D10 |
| 110 | `divergence` | evidence | lifted, pure_function | reference | analyse.py | D14, A6 |
| 120 | `divergence_witness` | evidence | lifted, pure_function, opt:deep | divergence | analyse.py | D14, A6 |
| 130 | `rewrite` | optimize | lifted, pure_function | reference | improve.py, ir.py | D8, A3 |
| 140 | `algorithm` | optimize | lifted, pure_function, int_sorted | reference | improve.py | A5 |
| 160 | `emit` | targets | lifted | reference | codegen.py | D14 |
| 170 | `witness_targets` | targets | lifted | emit | translate.py | D10, D14 |
| 175 | `measure` | optimize | lifted, opt:measure | witness_targets | optimize.py | D8 |
| 180 | `witness_source` | targets | lifted, not source_is_reference | reference | frontends.py | D3, D14 |
| 190 | `native` | targets | lifted, pure_function, source_is_reference, host:compiler | reference | improve.py, native.py, native.py | D14 |
| 200 | `notation` | targets | lifted, pure_function | reference | mathlang.py | D3 |
| 210 | `round_trip` | targets | lifted, pure_function | emit | matrix.py | D14 |
| 220 | `record` | record | lifted | reference | - | A7 |

## What the coverage check holds

Every card names a stage function and every stage function is named by a card; `needs` point at earlier stages;
every cited definition or rule is in docs/FOUNDATIONS.md; each card's `engines` are exactly what its function
imports; every engine under `cardmodel/engines` is loaded by some stage or named below with its reason; and on the
fixtures (the reference fixture, and the same functions in a second language that needs no toolchain) every entry
has a known status with a reason and every stage applies to at least one function once options and host facts are
granted.

## Engines outside the function pipeline (from `cards/stage/_category.json`)

- `arena.py`: the arena runs card-language programs against each other (`cardmodel arena`): a game loop over whole programs, not a step on one function
- `capabilities.py`: the smoke checks of the core (CM37) call the engines, the pipeline among them, from `verify` and the self-run; a check is not a step of the path it checks
- `codefacts.py`: facts about a whole source tree for `observe` and `learn` (which constructs occur where): a corpus reading, not a transformation of one function
- `codes.py`: the positional and arithmetic codes of whole Gödel sets (`cardmodel godel`): bookkeeping of the ledger, read by the content stage through godel.py
- `conformance.py`: the op x language matrix (CM17) measures the language cards themselves over every op; the targets stages measure one function's forms
- `coverage.py`: the goals' metrics read from the latest verify and self-run; it reads the pipeline's coverage, it is not a stage of it
- `difficulty.py`: difficulty of a whole card set for the self-run's choice of work; no step of one input's path
- `docs.py`: generates LAWS.md, GOALS.md and the floors from the cards (`cardmodel docs`): documentation of the model, not a transformation of an input
- `environment.py`: the machine the model runs on as a card (`cardmodel env`, ENVIRONMENTS.md V-A): a probe of the host written once into the local layer; the stages read the host through their `host:` facts, they do not describe it
- `formal.py`: the formal core in Lean (T1-T6) checks the theory's own theorems; the proofs are of the model, not of one input
- `godel1931.py`: the historical construction (Gödel 1931) as a card set, read by `cardmodel godel`; the content stage uses the model's own ledger (godel.py)
- `integrity.py`: the integrity check of the model's own files and cards (`verify --only integrity`): it checks the registry, it is not a stage of it
- `laws.py`: law discovery over the op cards (`cardmodel laws`) writes rewrite rules the canon and rewrite stages then read; it runs on the signature, not on an input
- `learn.py`: learning over a corpus of files (`cardmodel learn`): proposes and promotes cards from many inputs' observations; the unit here is one function
- `lift_project.py`: lifts a whole project tree (`lift-sweep`): a sweep over files, each function of which is this pipeline's unit
- `logic.py`: the logic engine (rules, queries, proofs of facts) serves `cardmodel logic` and card-language programs; a function has no logic program
- `mine.py`: mines candidate cards from a corpus for the self-run; a corpus reading, not a transformation of one function
- `observe.py`: observes a code base for named cards against fallbacks (`cardmodel observe`): a corpus reading for learning
- `projects.py`: project cards and their layering (`cardmodel status`): where the outputs go, not how an input is transformed
- `redefs.py`: redefinition cards (what a definition was redefined to and why) for `rewrite` over cards, not over functions
- `scale.py`: the scale benchmark (`cardmodel scale bench`, SCALING.md): generates synthetic projects of n functions and times the model on them; a measurement of the pipeline over many inputs, not a step of one input's path
- `selfcheck.py`: the self-containment check (CM13, `verify --only selfcheck`): the program's own files
- `selflogic.py`: the model's own card logic (the self layer) for the self-run; no step of one input's path
- `selfrun.py`: the self-run cycle (CM38) schedules steps over the model, `translate` among them; it calls the pipeline, the pipeline does not call it
- `sweep.py`: sweeps a corpus through `translate` (`cardmodel sweep`): a loop over files, each function of which is this pipeline's unit
- `theorems.py`: theorem cards with their evidence (CM23) are statements about the model's cards; a function's claims are certificates on its card (the evidence group)
- `verify.py`: the verify sections (`cardmodel verify`) run every check of the model, `pipeline` among them
- `witness_runner.py`: runs the law cards' witness tests for the self-run (CM20): tests of the model, not of an input

## Adding a stage

Write the function in `pipeline.py` (`fn(ctx, job, run) -> dict`), add it to `STAGES`, and add its card to
`tools/seed_pipeline.py` (hypothesis, needs, engines, foundations, laws); `cardmodel pipeline check` names what is
missing. The unit is one function of one source; whole trees, card-language programs and ROMs have their own paths,
named above.
