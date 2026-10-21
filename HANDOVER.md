# HANDOVER — continuing any software development with the card model

This repository is the card model as one program. Everything it knows is a card under `cards/`. Everything it can do
is a `cardmodel` command. At runtime it needs only this folder (plus the project you point it at and whatever
toolchains are installed). Live numbers are in `COVERAGE.md` (generated) and `cardmodel status`. This document says
what to do, not how many.

---

## 1. Quickstart

```bash
cd ~/Programmering/cardmodel
```

```bash
./bin/cardmodel probe
```

```bash
./bin/cardmodel verify --quick
```

```bash
./bin/cardmodel verify
```

```bash
./bin/cardmodel cover --write COVERAGE.md
```

* `probe` shows which toolchains this machine has (Python, Node, C, C++, Rust, Go, Swift, Java, Ruby, Lua, Lean, …).
* `verify --quick` runs the kernel, forms, vectors, rules and redefinitions (about 1 minute).
* Plain `verify` adds the op × language matrix, the function cards and the Lean proofs (several minutes).
* `cover --write` regenerates the coverage report and the goal values.

To use it from any folder, put the shim on PATH (it resolves symlinks):

```bash
ln -s ~/Programmering/cardmodel/bin/cardmodel /usr/local/bin/cardmodel
```

Or install it: `pip install -e ~/Programmering/cardmodel` (no dependencies).

Tests (standard library `unittest`; `CARDMODEL_SLOW=1` runs the conformance matrix in every language):

```bash
cd ~/Programmering/cardmodel/tests && python3 -B -m unittest
```

Every randomised test prints its seed on failure. `CARDMODEL_TEST_SEED=<n>` reproduces it (L28).

---

## 2. The model in five sentences

1. A **card** is a JSON object with `name` and `category`. Any other field is allowed, and consumers that don't know
   it ignore it.
2. A **registry** is a directory with `_category.json`, and its cards are subdirectories with `card.json` (or lines
   of `_pack.jsonl`). The filesystem is the index: `ALL`, `get`, `all_names`.
3. Cards come in **layers**: `model` (this repo) < `--cards` extras (read-only) < `project` (`.cardmodel/cards` in
   your project). Higher layers override by `category/name`.
4. A card's **forms** are equivalent implementations with a cost, a domain, a language and a probe. `cheapest()` picks
   the cheapest form that is runnable and available here for the requested domain.
5. Every executable claim has a **witness** that runs it with a printed seed and can fail. Nothing counts as verified
   until it has run.

---

## 3. Applying it to a program (the general recipe)

```bash
cd /path/to/your/project
```

```bash
cardmodel init
```

```bash
cardmodel observe . --save
```

```bash
cardmodel learn . --promote
```

```bash
cardmodel translate src/algo.py --to rust,go,c
```

```bash
cardmodel emit --lang swift src/algo.py --out Algo.swift
```

```bash
cardmodel verify --quick
```

```bash
cardmodel cover
```

What each step does:

* `init` creates `.cardmodel/` (the project's own cards; `state/` is a cache).
* `observe` reports named vs fallback cards, which functions lift into the IR, and the frequent unknown calls.
* `learn` proposes call cards, function cards and rewrite suggestions, and promotes only those with evidence.
* `translate` lifts every function, emits it in each language and runs it there; it reports agreement per language.
* `emit` writes one translation to a file.
* `verify --quick` witnesses everything, now including the project's cards.
* `cover` shows the project's coverage and goals.

Unsupported Python constructs are listed with line numbers (`translate`, `emit`), never pasted through. Each one is a
precise translation gap to close (see ROADMAP).

### Worked example A — the algorithms in `examples/algorithms`

```bash
cardmodel translate examples/algorithms/algos.py
```

All functions except `sign_sum` (a `list` parameter, reported as a gap) agree with the Python original in every
language with a toolchain. Lean is the exception for `mean3`: it uses floats, which the Lean card does not emit yet.
`cardmodel learn examples/algorithms --promote --global` stored them as function cards in the model; they are now
part of every `verify`.

### Worked example B — Ting (`~/Programmering/ting`)

Ting's crypto layer is cards: `crypto_atom` with forms and vectors, `cipher_suite` with cost vectors, and `card_type`
as schema-as-cards. The model carries a copy (`cards/crypto_atom`, `cards/cipher_suite`, `cards/ting_card_type`), and
its own forms use only the Python standard library and Node's built-in `node:crypto`. Pure-Python X25519/Ed25519 come
from the RFC algorithms. Ting's RFC vectors witness them:

```bash
cardmodel verify --only vectors
```

```bash
cardmodel rewrite crypto_atom/ed25519_sign --domain python
```

```bash
cardmodel rewrite --rank cipher_suite --weights sig_bytes=1,kem_pk_bytes=1
```

```bash
cardmodel rewrite --pareto cipher_suite --dims kem_pk_bytes,post_quantum
```

* `verify --only vectors` checks every runnable form of every atom against the known answers.
* `rewrite crypto_atom/ed25519_sign` picks the cheapest available form for a runtime domain; the forms are
  `python_stdlib` and `node_crypto`, and Ting's noble/PyNaCl forms stay documentation.
* `rewrite --rank` chooses a suite by weighted cost vector.
* `rewrite --pareto` shows the non-dominated suites.

To continue Ting *with* the model:

1. **Add an atom.** Write `cards/crypto_atom/<name>/` with `vectors.json` (`{args, out|error}`, bytes as
   `{"$bytes": hex}`), plus a `python.py` and/or `javascript.mjs` form exporting the `entry`. Run `cardmodel verify
   --only vectors`.
2. **Copy the forms back into Ting.** They are plain files.
3. **Validate a Ting card body against its type.** `ting_card_type/poll` holds a JSON Schema:
   ```python
   from cardmodel.kernel.schema import validate
   import cardmodel
   errors = validate(body, cardmodel.get("ting_card_type/poll")["schema"])
   ```
4. **Observe Ting's Python code.** Run `cardmodel observe ~/Programmering/ting --save` from a Ting checkout that has
   `.cardmodel/`. `learn` then proposes call cards for Django/crypto calls Ting uses repeatedly.

### Worked example C — rea (`~/Documents/rea-main`, `~/Programmering/rea-cards`)

rea's lesson is *backends as forms of one operation*, chosen by cost and availability, with equivalence checked on
real inputs. The model carries two operations built that way:

```bash
cardmodel rewrite re_operation/list_strings
```

```bash
cardmodel verify --only forms
```

```bash
cardmodel --cards ~/Programmering/rea-cards/cards list
```

* `rewrite re_operation/list_strings` lists its forms: `py_strings` (card-native), `host_strings` (Apple `strings`,
  probed), and `rea_ghidra` (documentation-only).
* `verify --only forms` runs `host_strings` against `py_strings` on `/bin/ls`, `/bin/cat`, … and requires identical
  output.
* `--cards ~/Programmering/rea-cards/cards` loads rea-cards' full registry read-only next to the model (nothing is
  written there).

`detect_format` reads `cards/format/*` (magic bytes as data, ported from rea-cards' `re_domain`). To add a format,
add a card. To add a backend for an operation, add a form with a `probe` (for example `{"kind": "executable", "name":
"rizin"}`), then run `verify --only forms`. rea-cards itself (by another session) is the large application of the same
pattern, covering the whole rea toolkit. See its `docs/MAPPING.md`.

---

## 3b. Making a program faster (improve) and the arena

```bash
cardmodel improve path/to/module_or_package --out path/to/optimized
```

```bash
cardmodel arena --count 300 --out /tmp/arena
```

For each top-level function, `improve` does the following:
* lifts it into the IR (or leaves it alone as effect shell);
* matches it by behaviour against `cards/algorithm`, exactly or as `a·card(x) + b`;
* tries rule rewrites;
* verifies every candidate against the original (domain + wide + structured inputs, matching exceptions);
* measures, and keeps the original unless a candidate is faster beyond noise;
* splices only the winners (surgical), re-checks the whole module with a fresh seed (reverting any refuted
  substitution), and emits native source for every language.

The output directory holds the optimized module (same API), `*.improve.md` / `*.improve.json` and
`native/<lang>/`.

`arena/slowframework` is a hand-written suboptimal game framework. `arena/slowframework_optimized` is its output, and
`online.py` (login, sockets, signed messages) passes through byte-identical. `cardmodel arena` generates programs of
any size with planted slow functions and decoys, and records a scored run in `cards/arena_run/`. Read
`docs/METHODOLOGY.md` for the guarantees and for what this means for games played online.

To raise recall, add an algorithm card: a `signature`, a `precondition`, `generators`, a `reference_form`, and
`forms` (one with `role: suboptimal` lets the arena plant it). Run `cardmodel verify --only forms` to witness the forms
and `cardmodel arena` to score the new card.

## 3c. Logic, the card language, theorems and Lean (second build)

```bash
./bin/cardmodel run examples/lang/family.card              # facts, rules, negation, aggregates, constraints
./bin/cardmodel run examples/lang/math.card --lean         # functions, theorems (witnessed + Lean), tests
./bin/cardmodel logic why examples/lang/grammar.card 's(0, 6)' --lean    # a parse tree, kernel-checked
./bin/cardmodel logic query examples/lang/hierarchy.card 'able(X, fly)'
./bin/cardmodel logic mine examples/lang/family.card        # decipher the rules behind the facts
./bin/cardmodel logic code arena/slowframework               # a code base as facts + stdlib/program.card
./bin/cardmodel logic self                                   # the model's laws as logic over its own store
./bin/cardmodel laws --save --global                         # discover, witness, prove, promote laws
./bin/cardmodel lean import --core --save --global           # Lean's Nat/Int library as theorem cards
./bin/cardmodel lean import MyProofs.lean                    # any Lean file in the fragment
./bin/cardmodel lang emit stdlib/combat.card --lang cpp      # card-language functions in any language card
```

* A new theory is a `.card` file (docs/LANGUAGE.md). `lang build FILE --save` turns it into theory,
  logic_rule, fact (pack), theorem, function and program cards in the project layer. `verify --only functions`
  then checks its functions in every language.
* A new law template is a few lines in `engines/laws.py::candidates`. A new Lean construct is a case in
  `emit/lean_import.Elab` plus its rendering. The kernel's faithfulness check means a wrong case is rejected,
  never imported.
* Evidence rules (CM23): a status rises only with evidence, `verify` re-witnesses every theorem card with a
  fresh seed, and every Lean batch goes through `emit/lean.check_batch` (fail-closed).

## 3d. The game (Vector Counter System)

```bash
./bin/cardmodel game check            # 8 design laws on the exact equilibrium (certificate checked)
./bin/cardmodel game play --vs reader # play; the reader tells you which vector it thinks you lean on
./bin/cardmodel game tournament       # equilibrium, reader, greedy, habit, random
./bin/cardmodel game sensitivity      # which number moves the structure most
./bin/cardmodel game balance          # seeded search over move numbers under the design laws
./bin/cardmodel game world --impact   # the systemic world: ticks, causes, counterfactual impact
./bin/cardmodel game kernel --lang cpp --out Combat.h    # the kernel for an Unreal module
```

A move is a card (`cards/move`), an enemy is a fighter card, a design law is a card naming a check in
`game/analysis.py`, and the kernel is `stdlib/combat.card`. Everything is described in game/DESIGN.md, including
the balancing log of what the laws found.

## 3e. Function algebra and bounded resources

```bash
./bin/cardmodel algebra form algorithm/fibonacci:naive_recursive    # canonical form, Gödel number, fast form
./bin/cardmodel algebra gcd 'expr:n*(n+1)//2' 'expr:n*(n+1)*(2*n+1)//6'
./bin/cardmodel algebra total 'expr:n**3'                            # the running sum, canonical again
./bin/cardmodel algebra scan --write --global                        # identities between algorithm cards
```

`improve` now also gets fast forms from the algebra, so a loop needs no algorithm card to be redefined.
Memory: see docs/METHODOLOGY.md §6 (environment variables `CARDMODEL_MAX_PARALLEL`, `CARDMODEL_CHILD_MB`,
`CARDMODEL_SELF_MB`, `CARDMODEL_MIN_FREE_MB`).

## 3f. AnyPS5 (a real system, read as cards)

```bash
./bin/cardmodel anyps5 scan ~/Documents/AnyPS5-main --parity --save --global   # read-only; badge reproduced
./bin/cardmodel anyps5 witness ~/Documents/AnyPS5-main --global                 # AnyPS5's code vs derived semantics
./bin/cardmodel anyps5 cover --write docs/ANYPS5_COVERAGE.md                    # the ladder and every gap's cause
./bin/cardmodel anyps5 why sceKeyboardGetKey2Char                               # gaps, causes, proofs, witnesses
./bin/cardmodel anyps5 blocks                                                   # pending exports by what they block
```

* The scan is an observation (packs `anyps5_export`, `anyps5_debt`, `anyps5_library`, `anyps5_instruction`):
  rescan after AnyPS5 changes; `verify` reports witnesses that belong to an older scan as stale.
* Knowledge is data: a cause, a library domain or a standard is a card (`tools/seed_anyps5.py` wrote the first
  ones). A new semantics binding is a card in `cards/anyps5_semantics/<name>/` (program, checks, C++ adapters next
  to it) plus its program in `stdlib/ps5_*.card`; run `anyps5 witness` and it counts.
* docs/ANYPS5.md says why the result is not 100 % by construction (observation, boundaries, policy) and what
  would move it.

## 4. How to add things

**A card.** Run `cardmodel new <registry> <name> --statement "..."`, or write `cards/<registry>/<name>/card.json`
yourself, then run `cardmodel verify --only kernel`.
* Required fields are `name` and `category`; the registry's `card_type` adds its own.
* Saving through the store versions the card automatically (`metadata.version`, `_versions/` archive).

**A form** (on an op/call/atom card). Add a `forms` entry with these fields:
* `name` and `cost` (in units where op/ADD native = 1);
* `domain` (a `cards/domain/*` name, e.g. `u32`) and `lang`;
* either `code` (a Python expression or lambda) or `file` + `entry` (a variant file next to `card.json`);
* optional `libs` (lib cards whose `python.py` the form imports), `probe` (when it needs a tool) and `notes`.

A form in another language whose `code` is a template like `"{0}.div_euclid({1})"` has `role: "hint"`. It is verified
by compiling it in that language, and `cheapest()` returns it only when that language is asked for. Run `cardmodel
verify --only forms`.

**A registry.** Make a directory with `_category.json`:
* `name` and `description`;
* optional `card_type` (type names that apply), `category_aliases`, `status_values`, `dimension_direction` (for cost
  vectors) and `references: "external"` (for snapshots whose references point outside).

**A card type.** Add `cards/card_type/<t>/card.json` with `schema` (a JSON Schema; see `kernel/schema.py` for the
supported keywords) and `applies_to: [registry, ...]`.

**An IR operator** (usable by the frontend and every codegen target). Add an op card with these fields:
* `ir.arity`;
* `ir.eval` (a Python lambda: the reference semantics);
* `ir.types` (signatures like `["int", "int", "int"]`);
* `ir.domain` (generators per type);
* `emit`: one template per language or syntax family (`python`, `c_like`, `ruby`, `lua`, `lean`, or a specific
  language). A value may be a dict keyed by operand type, or `"UNSUPPORTED"`.
* `requires`: imports per language (or per type).

If a language needs a helper function, add it to that language card's `codegen.helpers`. Run
`CARDMODEL_SLOW=1 python3 -B -m unittest test_conformance` until every cell passes or is a declared gap. If the
frontend should map Python syntax to it, add a line in `frontend_python.py` (`BINOPS`/`CALLS`).

**A language.** Add a language card with these fields:
* `extensions`, `comments`, `reserved`;
* `probe`: never resolve through an installer proxy (see Lean in troubleshooting);
* `runner` (`file`, `compile`, `run` with `{exe}`, `{src}`, `{bin}`, `{dir}`);
* `codegen` (copy the closest existing card; `extends` inherits a whole card), `int_bits`, and optionally
  `call_runner`.

Then run the conformance matrix for it and fix templates until its row passes. No engine file changes; a test fails
if an engine names a language.

**A rewrite rule.** Add `cards/rewrite_rule/<name>` with `lhs`, `rhs` (Python syntax), `vars`, optional `condition`
and `bidirectional`. `verify` witnesses it numerically and tries Lean (`grind`, then `omega`).

**A law or a goal.**
* A law card needs a `witness` naming a test (`tests/test_x.py::test_y`); run `cardmodel docs` to regenerate LAWS.md.
* A goal card names a `metric`. Add the metric's computation to `engines/coverage.py:_metric` when it is new.

**Known-answer vectors.** Put `vectors: [...]` inline or `vectors: "vectors.json"` on the card. Each vector is
`{"name", "args": [...], "out": ...}`, or `"error": true`, or `"out_one_of": [...]`.

---

## 5. How it learns and optimizes

`cardmodel learn [PATH] [--promote] [--global]`:

1. **observe.** The observation card is written once per content hash and never edited (ground truth).
2. **propose:**
   * **call cards** for frequent fallback calls (method calls are generalised by their tail: `.get`);
   * **function cards** for every liftable function (emitted to every language and run there);
   * **rewrite suggestions** where the rule cards find a cheaper equivalent expression (checked on seeded inputs;
     your source files are never edited).
3. **promote, only with evidence:**
   * calls seen ≥ 3 times in ≥ 2 files;
   * functions whose lift is faithful and which agree in ≥ 3 implementations;
   * suggestions that passed ≥ 3 checks.

   Everything else stays in `proposal/` with the reason. Promoted cards carry `metadata.confidence`,
   `evidence_count` and `provenance.learning_loop_refs`. By default promotion goes to the project layer; `--global`
   puts it in the model itself, so it carries over to every project.

`cardmodel optimize [--card Q] [--functions] [--apply]`:

* Python forms are timed in-process. Compiled function forms use each language's bench harness at two repetition
  counts (the slope; startup cancels). Arguments pass through an *opaque* template, so the compiler cannot fold the
  calls.
* Results become `metric/metric__<card>__<form>` cards with median, MAD, seed, host and input signature.
* `--apply` rewrites form costs in calibrated units (1 = op/ADD native on this host) and keeps `cost_anchor`.
* `cheapest(..., cost="measured")` ranks by measurements when every candidate has one.
* Verdicts: 🟢 the measurement confirms the anchor ordering, 🔴 it contradicts it, ⚪ within noise.

---

## 6. What is real and what is scaffold (honest list)

**Real (each item runs and is witnessed by `cardmodel verify` and the tests):**
* the kernel: contract, registries, packs, layers, types, versioning with verified archives, closure;
* Python → IR → every language card with codegen, with conformance and function translation run through the actual
  toolchains on this Mac;
* the hub's redefinition forms, checked on corrected domains. The hub's overstated domain claims are refuted by
  counterexample (`cardmodel verify --only forms` prints them);
* executable Pheros redefinitions, verified numerically or proved with sympy;
* Ting's crypto vectors, passing in stdlib Python and node:crypto;
* rea-style backends as forms, equal on real binaries;
* rewrite search proofs and optimisation, and Lean proofs of rule cards;
* learning with evidence, measured costs, the self-containment sandbox test.

**Partial:**
* the Python frontend covers int/float/bool functions with control flow, not strings, lists, objects or exceptions;
* observation of non-Python files is token-level;
* learned call cards are names with evidence, not semantics;
* domains for translated functions are inferred heuristically;
* the Lean backend proves ring and linear identities only (no Mathlib).

**Knowledge, not executable:**
* the vendored Pheros computation primitives (`cards/computation`, spec-level; COVERAGE.md counts how many satisfy
  `primitive_contract`);
* `redefinition_note` (prose and other-language translations);
* `translation_gap` and `xleq_observed` (Pheros observations);
* Ting's documentation-only atoms (XChaCha20-Poly1305, Argon2id, ML-KEM, ML-DSA, X-Wing): their vectors are kept for
  future stdlib forms.

**Real since the second build:** logic evaluation with proofs and Lean certificates; the card language (functions
to every language card); theorem cards with the evidence ladder; law discovery promoting rewrite rules; the Lean
core import with kernel-checked faithfulness and re-proofs; rule mining; the model's laws as logic; the combat
engine, exact equilibria, design laws, AIs and the systemic world.

**Partial (second build):** the Lean fragment is arithmetic (Nat/Int/Bool); logic terms are constants (no
function symbols); the game is one-exchange deep (matrix games per state, not a duel-tree search); the world
is a demonstration map; there is no graphics or engine integration yet beyond the C++ kernel.

**Real since the AnyPS5 build:** a C++ code base read as cards with file and line (exports, debt, libraries,
shader instructions); its badge reproduced name by name; every gap classified by rules with proofs; AnyPS5's own
C++ compiled next to card-language semantics and compared on seeded inputs.

**Partial (AnyPS5):** the scan is lexical (no macro expansion); debt causes come from cue words; eight semantics
bindings cover the pure code a public standard fixes, not all of it.

**Not built:** C/JS frontends, string/list IR, a watch daemon, suggestion application, proof backends other than Lean,
a native (ctypes) path inside improved modules (ROADMAP).

---

## 7. Invariants (keep these, or change them deliberately with a law card)

* Standard library only at runtime; optional capabilities are probed (`sympy`, `cryptography`).
* `cardmodel/` never imports `tools/`. `tools/` is build-time consolidation and reads the source folders read-only.
* The original folders (`~/Documents/Claude_Hub`, `~/Documents/Pheros_Studio`, `~/Documents/rea-main`,
  `~/Programmering/ting`, `~/Programmering/rea-cards`) are never written. `tests/test_self_contained.py` proves the
  runtime does not even read them.
* No per-language code in engines (`tests/test_laws.py`).
* Every subprocess has a timeout; every search has a budget.
* LAWS.md and COVERAGE.md are generated (`cardmodel docs`, `cardmodel cover --write COVERAGE.md`).
* Never `git push` from automation; commit locally (hub L13).

---

## 8. Concrete next steps (in order)

1. **stdin harnesses** (ROADMAP Now): add `read_*` templates to every language card, switch the harness, and confirm
   the build cache hits across seeds. Verify then gets several times faster.
2. **Strings and lists in the IR.** Start with `len`, indexing and a `for x in xs` loop on `list[int]`. Each op is a
   card, and the conformance matrix tells you when a language row is green.
3. **A C frontend** (lift C functions into the same IR), which gives C → Python/Rust/Go translation with the same
   witness.
4. **Run `cardmodel learn --promote` on your real projects** (Ting, rea-cards, the hub's config/) and commit the
   project `.cardmodel/` directories. Then use `cardmodel cover` there to pick the next card to write: the top
   fallback calls.
5. **Schedule `cardmodel verify --record`** (cron or launchd), so evidence accumulates in git history.
6. **Games natively (proposed as its own session).** Game Boy / Game Boy Color first, then Nintendo DS. The pieces
   follow the same pattern:
   * an `isa` registry: one op card per CPU instruction (LR35902, later ARMv4T/ARMv5TE), with IR semantics and
     conformance against free test ROMs;
   * a machine-code frontend that lifts ROM basic blocks into the IR (REA-style distillation, kept internal);
   * native emission through the language cards;
   * a launcher.

   The effect shell (input, audio, video, saves, link/online) stays in the runtime unchanged (CM21). ROMs stay local
   test inputs and are never copied into a repository.
7. **AnyPS5: done (section 3f, docs/ANYPS5.md).** What remains there: the pending blockers `anyps5 blocks`
   ranks, host mappings for the standard host functions, the string/list IR for the standard data functions,
   and console observations for the rest (each named with its file, line and debt entry).

---

## 9. Troubleshooting

* **Lean.** The probe only uses toolchains already under `~/.elan/toolchains/*/bin/lean`. Calling the elan proxy
  `lean` can start a network download of a newer toolchain. That happened once while this was built, and the
  download completed: `leanprover--lean4---v4.35.0` is installed beside v4.30.0, and the probe uses it. Every
  proof records its toolchain. Delete that folder if you do not want it. Override with `CARDMODEL_LEAN=/path/to/lean`.
* **Memory.** If the machine gets tight, lower `CARDMODEL_MAX_PARALLEL` (for example to 2) and
  `CARDMODEL_CHILD_MB`, and run one heavy job at a time. A child over its cap shows
  `[cardmodel] killed: … over the … MB cap`; this process stops with `MemoryBudget` past `CARDMODEL_SELF_MB`.
* **Lean batches** set `maxErrors` high and attribute errors by line. A declaration counts as checked only if Lean
  reached it without error (see `emit/lean.check_batch`).
* **A slow full verify** comes from the baked-input compiles (see Now). Use `--quick` or `--langs python,javascript,c`
  while iterating.
* **A conformance cell fails for one language.** The report has the arguments, expected and got. Fix the op card's
  `emit` entry or the language card's helper, never the engine.
* **The sandbox test is skipped:** `sandbox-exec` only exists on macOS. The static self-containment check still runs.
* **`state/`** is a cache (builds, last verify). `cardmodel clean` removes the build cache.
