# ARCHITECTURE

```
cardmodel/                      the repository IS the model (its home)
├── bin/cardmodel               shell shim: runs the program from any directory (no install)
├── cardmodel/                  the program (Python standard library only)
│   ├── kernel/                 the universal card contract
│   │   ├── card.py             Card = dict + load facts (path, registry, layer, source)
│   │   ├── registry.py         a directory with _category.json is a registry; ALL/get/all_names
│   │   ├── store.py            layers (model < extra read-only < project), merged views, writes
│   │   ├── schema.py           dependency-free JSON-Schema subset validator
│   │   ├── types.py            card types are cards; validation; closure (L45)
│   │   ├── versioning.py       semver bump + archive + verify-before-overwrite
│   │   ├── canon.py            canonical JSON (Ting) + card content hash
│   │   └── paths.py            home and project discovery (.cardmodel/, like .git)
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
│   │   ├── redefs.py           executable redefinitions: seeded numeric checks (+ sympy if present)
│   │   ├── observe.py          source tree -> observation card (ast for Python, tokens elsewhere)
│   │   ├── learn.py            observe -> propose -> verify -> promote
│   │   ├── optimize.py         measurements -> metric cards -> calibrated cost anchors
│   │   ├── verify.py           all witnesses with one seed; records verdicts
│   │   ├── coverage.py         computed coverage + goal metrics
│   │   ├── selfcheck.py        self-containment: static scan + macOS sandbox run
│   │   ├── docs.py             LAWS.md generated from law cards
│   │   ├── values.py           seeded generators, value comparison
│   │   └── context.py          Ctx = store + op table + state directory
│   ├── emit/                   lean.py (theorems + lint), proofs.py (backend choice), hints.py
│   └── cli.py                  init observe verify cover rewrite emit learn optimize translate status ...
├── cards/                      the model's own registries (the knowledge; see COVERAGE.md for counts)
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
