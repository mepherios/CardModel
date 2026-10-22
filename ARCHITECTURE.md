# ARCHITECTURE

```
cardmodel/                      the repository IS the model (its home)
├── bin/cardmodel               shell shim: runs the program from any directory (no install)
├── cardmodel/                  the program (Python standard library only)
│   ├── kernel/                 the universal card contract
│   │   ├── card.py             Card = dict + load facts (path, registry, layer, source)
│   │   ├── registry.py         a directory with _category.json is a registry; ALL/get/all_names
│   │   ├── store.py            layers (model < extra read-only < local < self read-only < project), merged
│   │   │                       views, writes (the local layer only when a writer names it)
│   │   ├── schema.py           dependency-free JSON-Schema subset validator
│   │   ├── types.py            card types are cards; validation; closure (L45)
│   │   ├── versioning.py       semver bump + archive + verify-before-overwrite
│   │   ├── resources.py        bounded resources: machine-wide slots, child memory caps, self cap, background
│   │   │                       spawns (CM30)
│   │   ├── canon.py            canonical JSON (Ting) + card content hash
│   │   └── paths.py            home, project discovery (.cardmodel/, like .git), the self layer (state/self/cards),
│   │                           the local layer (state/local/cards: data that stays on this machine, INTEGRATION rule 8)
│   ├── engines/
│   │   ├── probes.py           capability probes as data (rea-cards lesson)
│   │   ├── ir.py               the card IR: functions as trees of op cards + reference interpreter
│   │   ├── frontend_python.py  Python -> IR (precise unsupported-construct reports)
│   │   ├── codegen.py          IR -> any language card (syntax as data; no per-language code)
│   │   ├── runners.py          compile/run with cache and timeouts; call protocol (python, node)
│   │   ├── conformance.py      op x language matrix through real toolchains
│   │   ├── translate.py        Python function -> function card -> verified forms in every language
│   │   ├── rewrite.py          cheapest form (domain, availability, measured), suggestions, cost vectors
│   │   ├── search.py           rewrite search: proofs (meet in the middle), cost-directed optimisation
│   │   ├── exprs.py            expression strings <-> op trees, exact/real evaluation
│   │   ├── witness.py          forms vs reference, known-answer vectors, rule witnesses, anti-vacuity
│   │   ├── redefs.py           executable redefinitions: seeded checks, exact or high precision (+ sympy)
│   │   ├── observe.py          source tree -> observation card (ast for Python, tokens elsewhere)
│   │   ├── learn.py            observe -> propose -> verify -> promote
│   │   ├── optimize.py         measurements -> metric cards -> calibrated cost anchors
│   │   ├── improve.py          whole-program optimization: algorithm/affine substitution, rewrites, recheck
│   │   ├── arena.py            generated suboptimal programs + soundness/recall/speed score
│   │   ├── verify.py           all witnesses with one seed; records verdicts
│   │   ├── coverage.py         computed coverage + goal metrics
│   │   ├── selfcheck.py        self-containment: static scan + macOS sandbox run
│   │   ├── docs.py             LAWS.md generated from law cards
│   │   ├── values.py           seeded generators, value comparison
│   │   ├── context.py          Ctx = store + op table + state directory
│   │   ├── logic.py            rules as cards: stratified fixpoint, negation, aggregates, proofs, budgets
│   │   ├── theorems.py         theorem cards: witness (exhaustive + seeded), Lean statements, tactic portfolio
│   │   ├── laws.py             law discovery over op cards; simplifying laws -> rewrite rules
│   │   ├── mine.py             decipher rules from facts (support, confidence, counterexamples)
│   │   ├── selflogic.py        the store as facts + stdlib/self.card (the model's laws as logic)
│   │   ├── codefacts.py        a Python code base as facts (calls, effects, liftable) for stdlib/program.card
│   │   ├── funcalg.py          functions as algebra: canonical forms, Gödel numbers, GCD of functions (CM31)
│   │   ├── capabilities.py     the core as cards: one smoke check per capability card (CM37)
│   │   ├── integrity.py        one program: numbers, carried laws, described commands/sections/docs (CM39)
│   │   └── selfrun.py          the model runs itself: self_step cycle, self layer, findings, plan (CM38)
│   ├── lang/                   the card language: syntax.py (lexer, parser), compile.py (IR, logic, theorems,
│   │                           cards, algorithm resolution), run.py (tests, queries, theorems, build, emit)
│   ├── game/                   the Vector Counter System: combat.py (engine on the card-language kernel),
│   │                           analysis.py (exact equilibria, design laws, sensitivity, balance), tree.py (the
│   │                           duel tree by backward induction), ai.py, world.py
│   ├── anyps5/                 AnyPS5 as cards: scan.py (a checkout, read-only, the badge's rule reproduced),
│   │                           cards.py (packs with file and line), classify.py (facts + stdlib/anyps5.card: every
│   │                           gap's cause), cover.py (the ladder, causes, findings), witness.py (AnyPS5's C++ next
│   │                           to card-language semantics), cli.py
│   ├── unreal/                 a game engine's math as cards (docs/UNREAL.md): engine.py (the install, the truth and
│   │                           shipped builds), units.py (the generated header unit, the engine's .cpp units),
│   │                           clangast.py (clang's typed AST, streamed), lift.py (symbolic execution into core
│   │                           terms), scan.py, distill.py (canonical forms, hashes, Gödel content, uses, carry),
│   │                           witness.py (the engine's compiled code against the terms), atoms.py, cards.py,
│   │                           metrics.py, cli.py; engines/realnorm.py is the normal form over the reals
│   ├── emit/                   lean.py (theorems, fail-closed batch checker, lint), lean_logic.py (derivations
│   │                           as Lean terms), lean_import.py (Lean theorems as cards, faithfulness), lean_chain.py
│   │                           (rule-card chains as calc proofs), proofs.py, hints.py
│   ├── machine/                machines as cards: isa.py (instruction cards: IR, decode tables), build.py (a machine
│   │                           card -> one IR module), native.py (engines: ir, host, cabi via ctypes), bench.py
│   │                           (per-instruction conformance), asm.py (an assembler from the cards), gb.py, nds.py
│   │                           (hosts for the Game Boy and the DS prototype), lift.py (ROM blocks -> specialised IR ->
│   │                           native), diff.py, survey.py, testroms.py, shell.py (the effect shell), cli.py
│   ├── arcade/                 games as cards: gen.py (data cards -> tables, exact equilibria), game.py (a game
│   │                           card -> one IR module; headless runs), build.py (native package, store media, depot),
│   │                           server.py (the content service), cli.py (`cardmodel arcade`)
│   ├── cli_ext.py              run, lang, logic, laws, lean, repl, algebra (+ game, anyps5, machine, arcade CLIs)
│   └── cli.py                  init observe verify cover rewrite emit learn optimize translate status self ...
├── stdlib/                     card-language sources the program runs: self.card (its laws), program.card,
│                               combat.card (the combat kernel), world.card (the systemic world),
│                               algebra.card (identities between algorithm cards, generated), anyps5.card (AnyPS5's
│                               gaps and causes as rules), ps5_*.card (semantics derived from public standards)
├── game/DESIGN.md              the game design, every claim computed
├── examples/lang/              card-language programs: family, math, hierarchy, grammar
├── cards/                      the model's own registries (the knowledge; see COVERAGE.md for counts)
├── arena/                      optimization test environment: slowframework/ (+ its optimized output)
├── tests/                      unittest suites (stdlib), incl. the sandboxed self-containment test
├── tools/                      BUILD-TIME ONLY: bootstrap.py (own cards), vendor_import.py (consolidation)
└── docs/                       PROVENANCE.md, VENDOR_REPORT.json
```

## The card contract (kernel)

A card is a JSON object with `name` and `category`. The universal fields are listed in `cards/card_type/card` (the
schema is data). The kernel requires only `name` and `category`. Everything else is optional. Unknown fields are kept
when a card is saved and ignored by consumers that do not know them. This is the infinite-extension guarantee of the
hub's CARD_MODEL.md (CM03). Two meanings of "variants" coexisted in the sources. Here they are separated:

* `forms`: equivalent implementations of one claim (hub `card_redefinitions`, Ting atoms, rea backends). Each form has
  `name`, `cost`, `domain`/`domains`, `lang`, `code`|`file`+`entry`, `probe`, `runnable`, `libs` and `role`.
* `variants`: filename-keyed artifacts (Pheros `variant_contract`). Files next to `card.json` are variants too.

**Registries are directories.** A directory holding `_category.json` is a registry, and its cards are subdirectories
with `card.json`. The bulk *packed* form `_pack*.jsonl` (one card per line) keeps vendored snapshots compact. A
directory card wins over a packed card of the same name. Registries may nest. `_versions/` and other `_`/`.`
directories are never registries.

**Layers.** `model` (this repository) < `extraN` (other card trees passed with `--cards`, always read-only) < `project`
(`<project>/.cardmodel/cards`). A card in a higher layer overrides the same `category/name` below it. Writes go to the
highest writable layer, or to `model` with `--global`. This way a project can specialise the model (for example
measured costs on its own machine) without editing it, and the model can learn globally.

**Types.** `cards/card_type/<t>` carries a JSON Schema and `applies_to`. Validation applies `card` (universal) plus
every type that applies to the card's registry, and adds kernel checks:

* `category` matches the registry or one of its `category_aliases`;
* `status` is in the registry's `status_values`, or `healthy|suspect|broken|quarantined` by default;
* types can be pinned by version.

Vendored registries record the vocabulary they actually use (aliases, status values, `references: external`) instead
of being rejected.

**Versioning.** Saving a changed card archives the previous bytes in `cards/_versions/<cat>/<name>/<ver>__<hash>.json`.
It re-reads the archive and checks its hash before overwriting (hub L35), then bumps semver:

* MAJOR: a field was removed or retyped;
* MINOR: a field was added or a semantic field changed;
* PATCH: anything else.

The bump records `previous_content_hash`.

## Data flow

```
              ┌────────────── cards/ (language, op, domain, rule, law, goal, call, shape, ...) ─────────────┐
              │                                                                                           │
source tree ──► observe ──► observation card (ground truth) ──► learn ──► proposal/ ──(evidence)──► promoted cards
                  │                                               │
                  └─► frontend_python ──► IR (op trees) ──► codegen(language card) ──► runners ──► witness
                                                │                                                    │
                                     interpreter (op.ir.eval) ──────── reference ───────────────────┘
rewrite/search ◄── op costs, rule cards       optimize ──► metric cards ──► cheapest(cost="measured")
program.py ──► improve: lift ─► match algorithm cards (exact/affine) + rule rewrites ─► verify ─► measure
                        ─► splice (shell byte-identical) ─► recheck (revert on counterexample) ─► natives
verify ──► state/last_verify.json ──► coverage / goals ──► COVERAGE.md
```

## Design decisions (L22 reasoned preferences, with reconsideration triggers)

* **Languages are cards; codegen holds no language knowledge.** Syntax, types, literals, helpers, harnesses, probes
  and comment syntax live on `cards/language/*`. Operator spellings live on `cards/op/*` under `emit`, keyed by
  language or syntax family. `tests/test_laws.py` fails if an engine contains a language name. *Reconsider* if a
  language needs control-flow lowering that templates cannot express (an ML-family target with no statements). That
  would need a lowering pass that is still selected by card data.
* **Python is the reference semantics.** `int` is unbounded with floor division, as in the observed language. Targets
  with fixed-width integers are compared only where every intermediate fits (the interpreter reports the widest
  value), so an overflow is reported as out-of-width rather than as a semantic bug. *Reconsider* when a second
  frontend lands (for example C as a source), since that brings C semantics.
* **Inputs baked into programs.** Every language needs only a print template, not a parser. The cost: a new seed
  means a new compile (about 30–250 s for the full matrix, depending on load). *Reconsider*: stdin-driven harnesses
  (ROADMAP).
* **The hub's "any" request semantics kept.** A request for domain `any` accepts every form, as in the hub
  `rewrite_engine.cheapest` and rea-cards. Forms with `role: hint` (another language's spelling) are excluded unless
  asked for, so `cheapest()` never returns code the caller cannot run.
* **Bump rule differs from Pheros.** Adding a field is MINOR, not MAJOR, because unknown fields never break consumers
  here.
* **Vendored snapshots are not normalised** beyond three mechanical, recorded transforms:
  * illegal harvested names are encoded (`_xHH`) with `original_name` kept;
  * duplicate names get a suffix;
  * Ting atoms are split per entry point (`x25519_kem` → `x25519_public` + `x25519_dh`).

## What was ported, from where, and how it changed

| Source | Became | Change |
|---|---|---|
| hub `CARD_MODEL.md`, Pheros `_meta/card_type` | `kernel/card.py`, `card_type/card` | one contract; forms vs variants separated |
| Pheros `registry_contract`, Ting `core/cardmodel.py` | `kernel/registry.py`, `store.py` | layers, packs, nested registries, fail-loud errors |
| Pheros `card_versioning` | `kernel/versioning.py` | implemented (Pheros only documented it) |
| hub `card_redefinitions.py`, `bit_primitives.py` | `cards/op/*` forms, `cards/lib/bit_primitives` | forms are data; domains corrected where the witness refutes the hub's |
| hub `card_catalog.py` | `cards/op` matchers, `cards/call`, `cards/shape`, `observe.py` | walker is card-driven; hub-project-specific symbols left out |
| hub `language_hints.py` | `hints` on op/call cards; `emit` templates | hints kept; runnable templates added and verified |
| hub `rewrite_engine.py` | `engines/rewrite.py` | + availability, lang, measured costs, cost vectors |
| hub `rewrite_search.py` | `engines/search.py`, `cards/rewrite_rule` | rules are cards; meet-in-the-middle; optimise |
| hub `cross_language_equiv.py` | `conformance.py`, `translate.py`, `witness.py` | its scaffold targets now run, in every language card with codegen |
| hub `lean_emitter.py` | `emit/lean.py` | real `lean` checks (grind/omega); lint kept as fallback |
| Pheros `redefinition/` | `cards/redefinition` (executable), `cards/redefinition_note` (knowledge) | verified/proved per card |
| Pheros `computation/`, `translation_gap/`, `cross_language_equivalence/`, `language/` | packed/dir registries | vendored with provenance; std_library names feed `observe` |
| Pheros `tool/v_transpile` | `cards/tool/v_transpile` (card, README, IR spec) | design reference; the expression-level IR replaces its string IR |
| Pheros `bin/pheros-learn` | `engines/learn.py`, `cardmodel learn` | same loop; promotion thresholds; observations are ground truth |
| Ting `crypto_atom`, `cipher_suite`, `card_type` | `cards/crypto_atom` (+ stdlib/node forms), `cipher_suite`, `ting_card_type` | Ting's vectors witness stdlib-only forms |
| Ting `canon_json` twins, `test_cross_language.py` | `kernel/canon.py`, `crypto_atom/canon_json`, `tests/test_random_seed.py` | same algorithm and test |
| rea-cards probes, dispatch, calibrate, coverage | `probes.py`, `rewrite.cheapest`, `optimize.py`, `coverage.py` | ported as lessons; `format/` + `re_operation/` as worked example |

## The knowledge layer and the language (second build)

```
.card source --lang/syntax--> declarations --lang/compile--> IR functions ----codegen----> every language card
                                                         \--> logic Program --engines/logic--> model + proofs
                                                         \--> theorem cards --engines/theorems--> witness / Lean
                                                         \--> cards (any registry)
op cards --engines/laws (templates)--> theorem cards --simplifying--> rewrite_rule cards --> optimize / improve
Lean file --emit/lean_import--> theorem cards (lean semantics) --kernel: faithful? witness? re-prove? chains?
proof tree --emit/lean_logic--> Lean inductive encoding + constructor term --kernel checks the derivation
store --engines/selflogic--> facts + stdlib/self.card --> the model's laws as logic (0 violations)
AnyPS5 checkout --anyps5/scan (read-only)--> anyps5_* cards --anyps5/classify + stdlib/anyps5.card--> gaps, causes,
    proofs --anyps5/cover--> docs/ANYPS5_COVERAGE.md;  stdlib/ps5_*.card + AnyPS5's C++ --anyps5/witness--> anyps5_witness
move cards + stdlib/combat.card --game/combat--> exchanges --game/analysis--> exact equilibria, design laws
```

Every Lean check goes through `emit/lean.check_batch`, which attributes errors by line and fails closed. A
declaration counts as checked only if Lean processed it without an error, and anything Lean did not reach
(maxErrors, a crash, a timeout) is re-checked or reported unchecked. That rule exists because Lean stops after
100 errors by default, and a batch that silently skipped the rest would otherwise have counted as passed.

Ported for the language: the Pheros CL v0 compilation model (parse → typecheck → resolve → emit, with card
references as atoms and `algorithm.NAME` resolved to the cheapest verified form) and its function form
(`name : T -> T = match p with | ...`), which the card language accepts unchanged. Nothing was vendored; the
grammar was read for alignment.

## Machines (third build)

```
isa/<isa> (core.card, interface.card) + isa/_pack_<isa>.jsonl (instruction cards: data + semantics + IR)
hardware/<component> (registers and timing as data + logic .card)   machine/<name> (components + main loop)
      --machine/build--> one card-IR module --codegen (language card)--> Python (exec) | C (shared library, ctypes)
ROM --interpreter profile--> leaders --machine/lift (cards' IR, constant bytes, inline, fold, cache, DCE)--> blocks
      --codegen split_sources--> per-bank compile units --> one library per ROM --> run_block hook in the machine
shell (browser page, headless, saves, clock) <--> machine module (pure: state + buttons -> state, frame, audio)
```

Design decisions:

* **Lazy, exact syncing.** Components advance only when touched or when `now` passes `next_event`, the earliest
  moment one of them can raise an interrupt; the interpreter's results do not depend on how often they sync
  (tested). *Reconsider* for effects that land mid-instruction (write conflicts), which need sub-M-cycle events.
* **Blocks bounded by events.** A lifted block runs only if it ends before `next_event`, so it cannot miss an
  interrupt; writes that may move the event end it early. *Reconsider* if superblocks need the condition per
  iteration.
* **Two CPUs on one core.** The DS's ARM9 and ARM7 take turns on one set of ARM card globals (registers saved and
  restored per turn) rather than two copies of the module. *Reconsider* when the per-turn cost matters more than
  the simplicity.
* **Engines are embed blocks.** How a host loads emitted code is card data (`embed.kind`), so the machine package
  names no language.

## The model runs itself (fifth build)

```
any command --selfrun.maybe_start (due? lock free? memory?)--> detached `cardmodel self run --auto`
      (background QoS, one slot, 2 GB cap)
self_step cards, in order, when due --> capabilities (capability cards -> engines/capabilities.CHECKS)
      --> integrity --> verify (quick; full daily) --> learn (changed trees) --> laws / algebra (on change)
      --> arena (daily) --> optimize (weekly) --> goals (merged section results)
      --> findings (flaw / weakness / strength + evidence + action) --> plan (ranked) --> trend
      --> state/self/{last.json, runs/, SELF.md}
learned cards --> state/self/cards (the self layer: read-only for every command; quarantined if it breaks verify;
      `self adopt` --> cards/ for a commit)
```

Design decisions:

* **A layer, not the tracked tree.** Background cycles write only the untracked self layer, so they can never
  collide with a session's commit; adoption into `cards/` is a deliberate step. *Reconsider* if the model runs
  where nobody adopts: then a cycle could open its own branch.
* **No daemon.** Cycles start on use, rate-limited, so nothing runs while the model is idle and nothing needs
  installing. *Reconsider* if the user wants evidence to accumulate while idle (a launchd job running
  `cardmodel self run --auto`).
* **Capabilities carry laws.** A law is kept alive by a check that runs, not by its text: the integrity check and
  the self theory both fail on a law that no capability carries.
* **Deep checks are steps.** A capability's smoke check takes seconds; what takes minutes runs as a self-run step
  on its own schedule: every law's witness test in a child process (`law_witnesses`, through
  `engines/witness_runner.py`), every catalogue item launched through the store's own protocol (`store`,
  `arcade/client.py`, CM42), the whole suite (`tests`, weekly). Each step runs under a deadline, so a step that
  does not return is stopped and reported instead of holding the cycle.

## What was not carried over

* **Hub laws about the hub itself:** GUI conventions, hub reachability, hub folder budgets, autopilot, impact tree,
  diary. **Pheros laws about its waves, daemons, panels and agent locks.** They govern those programs' own tooling.
  `LAWS.md` keeps the laws that govern a card-model program (each one with its origins).
* **The hub's auto-scraped project symbols (V7)** and the domain-specific call tables (algebra, physics,
  substrate...). They name the hub's own code and would inflate the named fraction on other code.
* **v_transpile's regex frontends and string-IR backends.** They could not be verified by execution, so the IR here is
  expression-level instead.
* **Ting's noble / cryptography / PyNaCl forms.** They are third-party, so they are listed as documentation-only forms
  that point at Ting's files.
