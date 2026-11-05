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

```bash
./bin/cardmodel self run
```

* `probe` shows which toolchains this machine has (Python, Node, C, C++, Rust, Go, Swift, Java, Ruby, Lua, Lean, …).
* `verify --quick` runs the kernel, forms, vectors, rules and redefinitions (about 1 minute).
* Plain `verify` adds the op × language matrix, the function cards and the Lean proofs (several minutes).
* `cover --write` regenerates the coverage report and the goal values.
* `self run` runs one cycle of the model on itself (§3i): its core capabilities, integrity, verify, learning, every
  law's witness test, the store, measurements and every goal, then its flaws, weaknesses and a ranked plan.

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
* A checkout with fixes is a card-model project of its own: `cardmodel init` in it, then `anyps5 scan . --parity
  --save` and `anyps5 witness .` write to its `.cardmodel/`. A scan in a higher layer replaces the model's scan of
  upstream instead of mixing with it (`scan_cards`), and `anyps5 cover --compare` sets the two side by side.
  ~/Programmering/AnyPS5-cardmodel is such a copy (its own git repository: the MP3 header fix, the relinker build,
  `docs/dev/CARDMODEL.md`).
## 3g. Machines: Game Boy, Game Boy Color, and the DS prototype (third build)

```bash
./bin/cardmodel emu "~/Downloads/GB_GBC/Game Boy/Tetris (World) (Rev A).zip"     # opens the browser page
```

```bash
./bin/cardmodel emu game.gbc --headless --frames 900 --input "300:start,306:-" --png shot.png --wav sound.wav
```

```bash
./bin/cardmodel isa check lr35902
```

```bash
./bin/cardmodel machine survey ~/Downloads/GB_GBC
```

```bash
./bin/cardmodel machine diff game.gb --frames 3000
```

```bash
./bin/cardmodel machine nds "~/Downloads/Pokemon Diamond/Pokemon Diamond.nds" --frames 600
```

* A CPU is its **instruction cards** (`cards/isa`), a console its **hardware cards** (`cards/hardware`), and a
  **machine card** (`cards/machine`) composes them into one card-IR module. docs/MACHINES.md describes all of it.
* `emu` runs the ROM's **lifted** code (its basic blocks as card IR, specialised, compiled through the C card) with
  the native interpreter as fallback. The first launch of a ROM profiles 1800 frames headless and compiles (a few
  seconds); later launches start at once. `--engine native` skips lifting; `--engine host` is the Python
  fallback (slow); `--engine ir` the reference interpreter (very slow).
* The page: arrows, X = A, Z = B, Enter = Start, Shift = Select, gamepads. Click once for sound. Ctrl-C stops and
  saves.
* Saves: `saves/<game>.sav` in this folder (gitignored), or `--save-dir`. MBC3 clocks are saved in the common
  48-byte trailer and catch up with the wall clock.
* Caches: `state/emu/<rom>-<machine>/` holds the profile, the lifted blocks and the library (ROM-derived, never in
  git). `cardmodel clean` does not touch saves.
* To extend: an instruction is a card (edit `tools/gen_lr35902.py` or `tools/gen_armv5te.py`, then
  `cardmodel isa build ISA`); a hardware component is a directory card with registers and timing as data and a
  `.card` logic file; a bank controller is a case in `gb_cartridge/cart.card` plus an entry in its `types` table.
  `verify` checks every instruction card in every engine; `machine diff` checks lifting; `machine survey` the
  collection.

## 3h. The arcade: a native game built from cards, and its launcher (fourth build)

```bash
./bin/cardmodel arcade launcher --install
```

```bash
./bin/cardmodel arcade build vector_duel
```

* **Vector Duel** (`cards/game/vector_duel`): the game card holds the data (strings, music, ladder, arenas, the
  boss's phases, the duel tree's depth, achievements, store text, versions); its eight `.card` files are the whole
  game (frame loop, software renderer, duel on the move cards, chain cards and the combat kernel, AIs, drawing,
  screens, synth, save). `arcade/gen.py` turns the data cards into tables, solves the exact equilibria the
  equilibrium AI samples and the duel tree the Oracle plays (`game/tree.py`, cached by a hash of its inputs).
  docs/ARCADE.md describes it.
* **The pipeline** (`arcade/build.py`): module -> C card -> `game.dylib`; the platform card's Swift effect shell;
  store pictures drawn by the game; a bundle; a depot of SHA-256 chunks. **The service** (`arcade serve`) builds
  on demand when the cards change and serves catalog, manifests, chunks, pictures and the launcher's pages.
* **The launcher** (`cards/app/arcade`): downloads with every chunk checked, delta updates, verify, play time,
  achievements from the save. It lives in ~/Applications and keeps its data in
  ~/Library/Application Support/Cardmodel Arcade.
* **Shipping an update**: change the game's cards, bump `version` and add a `changelog` entry in its card.json; the
  launcher shows Update with the notes, and the service compiles the new build when the player asks for it.
* **Your own cartridges** (`cards/system/gameboy`, `system/nds`; docs/ARCADE.md section 5): the Game Boy Player is
  the gameboy machine card plus `player.card`, built and installed like a game; the library lists every cartridge
  in the user's folders (`arcade library --add DIR`, kept in library.json beside the saves) where it is, with the
  survey's verdict and a title screen the machine draws; Play starts the player on the file. The DS is listed,
  not playable yet. A cartridge is titled by its No-Intro file name, else by its header. `arcade check` (CM42)
  installs the player through the store, plays it on the system card's check cartridge (assembled from the
  instruction cards), then starts every listed cartridge in it as the launcher does and compares the picture with
  the one the cards compute (`--cartridges N` for the first N; about 0.2 s a cartridge). Tests point the library
  at their own empty file (`CARDMODEL_LIBRARY`, tests/helpers.py) and use only synthetic cartridges.
* **Work in progress in the launcher** (`arcade/work.py`, docs/ARCADE.md section 3): the *Every branch* section
  of the IN PROGRESS tab (once a WORK tab of its own) with every
  worktree (branch, last commit, commits not on main and their files, uncommitted changes, areas, programs), and a
  Versions and branches card per program: a branch's version installs like a beta, built in that worktree by its
  own `bin/cardmodel`. When the cards in progress do not build, Update installs the last good build and the page
  shows the error (remembered in `state/arcade/build-errors.json`). Every title and datum on the pages opens
  something. `CARDMODEL_BRANCHES=0` keeps the service to its own checkout (the tests set it).
* **A cartridge as its own app** (`arcade/cartapp.py`, `cardmodel arcade app ROM --install`): the Game Boy
  Player with the cartridge's code lifted into card IR, witnessed against the plain player, packed as
  `~/Applications/Cardmodel Games/<title>.app`. The lifter (`machine/lift.py`, docs/MACHINES.md section 4) now
  lifts every instruction start on its own besides the blocks (near events, after EI, mid-block entries), lifts
  HALT, STOP and EI, and lifts the code a cartridge copies into RAM behind byte guards; the machine counts what
  still runs in the interpreter (`interpreted`). `machine/absint.py` finds more code by an abstract run of the
  machine's cards (far calls through bank-switching trampolines, jump tables); `arcade app` runs it once per
  cartridge. Recursive descent now follows conditional returns' fall-through (the last gap). Pokemon Crystal:
  100 % lifted on an unseen run (0 instructions interpreted); an app that ever interprets code keeps it beside the
  save and rebuilds itself in the background when you quit.
* Witnesses: `tests/test_arcade.py` (CM35, CM42), `tests/test_arcade_systems.py` (CM40), `tests/test_arcade_work.py`,
  `tests/test_cartapp.py`.
* What is in the store and what the model does for each piece: docs/STORE.md. Install the launcher from this
  checkout (`main`), not from a worktree: the app records the checkout it was installed from. Run from a linked
  worktree, `arcade launcher --install` now points the app at the main checkout anyway (`--home PATH` chooses
  another).
* **Checking the store end to end** (CM42): `cardmodel arcade check` launches every catalogue item through the
  service exactly as the launcher does (a download with every chunk's and file's SHA-256 checked, verify, a damaged
  file repaired with only that file fetched again, a headless native run that must draw a frame); `--launcher` also
  compiles the launcher. The self-run's `store` step runs it on every cycle. Headless runs (`arcade run --frames N`)
  use a temporary save folder, never the player's save.

## 3i. The model runs itself (fifth build)

```bash
./bin/cardmodel self run
```

```bash
./bin/cardmodel self report
```

* **The core is cards** (CM37): 26 `capability` cards, each with the laws it carries, a smoke check of the real
  engine (`engines/capabilities.py`), its witness tests and docs. `verify` runs the checks (sections
  `capabilities` and `integrity`, both in `--quick`); LAWS.md lists them under the laws; every law is carried by
  at least one (the integrity check and `stdlib/self.card` both enforce it).
* **The cycle** (CM38, `engines/selfrun.py`, the `self_step` cards): capabilities, integrity, verify (full every
  24 h), learning from changed source trees (`cardmodel self corpus add PATH` adds yours), laws and identities
  when their cards change, the arena (daily), measurements (weekly) and every goal, then findings (flaws,
  weaknesses, strengths) and a ranked plan in `state/self/SELF.md`. Any other command starts one in the
  background when one is due (every 6 h), under the resource governor; `CARDMODEL_SELF=0` or `self auto off`
  stops that.
* **The self layer**: what cycles learn goes to `state/self/cards` (untracked; loaded read-only by every
  command); a layer that breaks verify is quarantined; `cardmodel self adopt` moves it into `cards/` for a commit.
* **One program** (CM39, `engines/integrity.py`, docs/INTEGRATION.md): unique law and goal numbers (the registry is
  in docs/INTEGRATION.md), every command in the help, every section and doc described, generated docs in sync,
  no merge markers, no publishing calls. docs/INTEGRATION.md also has the merge procedure and the integration
  log.
* **Deep checks as steps**: `law_witnesses` runs every law card's witness test in a child process with the cycle's
  seed (daily); `store` launches the catalogue through the store (every cycle); `tests` runs the whole suite
  (weekly). Each step runs under a deadline, so one that does not return is stopped and reported.
* Witnesses: `tests/test_self.py`, `tests/test_self_steps.py`. How it works and how to extend it: docs/AUTONOMY.md.

## 3j. A game engine's math (Unreal Engine)

```bash
./bin/cardmodel unreal scan --save
```

```bash
./bin/cardmodel unreal show FVector.CrossProduct
```

```bash
./bin/cardmodel unreal cover
```

* `scan` finds the engine through the Epic launcher's record (or `--engine PATH`), builds its math units in
  `state/unreal/<version>/` (clang's AST dumps run to gigabytes; the cache keeps the compact pickles), lifts every
  function, distills it, witnesses every term against the engine's compiled code, and with `--save` writes the
  cards to the untracked local layer (`state/local/cards`: UE-derived data stays local, docs/INTEGRATION.md rule 8)
  and appends the engine's atoms (names) to the tracked ledger. `--reuse` starts from the cached scan; a scan takes minutes,
  the witness longer. `witness --missing` witnesses again only what has no settling verdict, and
  `scan --reuse --no-witness --save` rewrites the cards from the cached scan and the last verdicts.
* A new C library atom: an entry in `cardmodel/unreal/atoms.py`, then `python3 -B tools/seed_unreal.py` (op card,
  ledger), then `scan --reuse --save`. Closing a gap: `cover` lists every cause with what closes it; the lifter is
  `cardmodel/unreal/lift.py`. Any other C++ code base: `unreal/scan.py::lift_source` and `witness.Target`.
* Witnesses: `tests/test_unreal.py` (on `examples/engine_math/mini_math.h`, no engine needed); verify section
  `unreal`. docs/UNREAL.md has the whole method and its limits.

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
* the Python frontend covers int/float/bool/str functions and int/float lists with control flow, not objects,
  dicts or exceptions;
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
function symbols); the game was one-exchange deep (matrix games per state; the duel tree came with Vector Duel
0.4.0, over abstract states); the world
is a demonstration map; there is no graphics or engine integration yet beyond the C++ kernel.

**Real since the AnyPS5 build:** a C++ code base read as cards with file and line (exports, debt, libraries,
shader instructions); its badge reproduced name by name; every gap classified by rules with proofs; AnyPS5's own
C++ compiled next to card-language semantics and compared on seeded inputs.

**Partial (AnyPS5):** the scan is lexical (no macro expansion); debt causes come from cue words; eight semantics
bindings cover the pure code a public standard fixes, not all of it.
**Real since the third build (machines):** the IR and the card language carry machine state (globals, arrays, void
functions, switch, an evaluation-order pass); the LR35902 and ARMv5TE/ARMv4T instruction cards with per-instruction
conformance in three engines (reference interpreter, Python, C) and their timing/flag data checked; the Game Boy /
Color machine from hardware cards (a DMG cartridge on the CGB runs in DMG compatibility mode); ROM code lifted
into card IR and run natively, frame-for-frame identical to the interpreter in the differential runs; the effect
shell (browser page, headless runs, saves, the RTC); the ROM survey; a DS machine prototype that direct-boots and
reports its coverage.

**Partial (third build):** the PPU is a scanline renderer and the APU point-sampled; DMG compatibility mode has the
boot ROM's default palette only (not its per-title ones); MMM01, MBC6/7, HuC1/3, TAMA5, the camera and unlicensed
multicart mappers are missing; the hardware test suites (Blargg, mooneye, acid2) all pass except what is skipped:
tests for other hardware revisions and one Blargg single that overflows its own log (docs/MACHINES.md section 2);
the DS has no graphics, sound, SPI devices, RTC or Wi-Fi, and only its ARM-state ARM9 code is lifted (COVERAGE.md
has the numbers).

**Real since the self-run's deep checks:** every law's witness test runs in the self-run (`law_witnesses`); the
store's catalogue is launched through the store's own protocol on every cycle (`store`); a partial `verify` keeps
the sections it did not run.

**Partial (the self-run's deep checks):** the store check replays the launcher's protocol in Python and compiles
the launcher, but does not drive its window; a step's deadline cannot interrupt one long C-level operation.

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
* No ROM byte in the repository: ROMs are read where they are (zips in memory); lifted code and profiles live in
  `state/emu/`, saves in `saves/` (both gitignored). Nothing decrypts or patches DRM or anti-cheat; a DS image with
  an encrypted secure area is refused.
* A machine module performs no I/O; everything that touches the world is `machine/shell.py` (CM21, CM34).
* Background self-run cycles write only under `state/self/` (CM38); tests run with `CARDMODEL_SELF=0`
  (`tests/helpers.py`), so they see the tracked cards only.
* Law and goal numbers come from the registry in docs/INTEGRATION.md; every law is carried by a capability (CM37).
* A goal never gets easier silently: `floor/goals` holds every goal's hardest target, and lowering one, changing what
  it measures or removing it needs a written reason (docs/INTEGRATION.md section 4a; `cardmodel docs` records it).

---

## 8. Concrete next steps (in order)

Start with `cardmodel self report`: the model's own ranked list of its flaws and weaknesses, with the command for
each. The mathematics has its own plan: docs/MATH_CORE.md (phases and progress) and the research handover's agenda
(R1-R10). Its rules for anyone continuing: content is stored as sparse vectors, never as integers, and no index is
reused (CM45); every claim carries its tier (CM46, `cardmodel tiers census`); the formal core in `formal/` builds
with no `sorry` (`cardmodel verify --only formal`). Beyond that:

1. **stdin harnesses** (ROADMAP Now): add `read_*` templates to every language card, switch the harness, and confirm
   the build cache hits across seeds. Verify then gets several times faster.
2. **Strings and lists in the IR.** Lists are in (docs/LISTS.md), and so is `str` (docs/STRINGS.md): code points,
   eleven op cards (len, index, chr/ord, concat, equality, order, slice, find, int/str conversion), green in the
   conformance matrix in every installed codegen language. Python's `str` functions lift
   (`cardmodel translate examples/strings/strings.py`). Next: AnyPS5's standard data functions (`vsscanf`,
   `vfscanf`) on these scanning primitives (`scan_int` in the example is `%d`), then the game's text; Lean string
   templates, formatting and a `bytes` sort for C's `char *`.
3. **A C frontend** (lift C functions into the same IR), which gives C -> Python/Rust/Go translation with the same
   witness, and lets the learning step learn from C trees, not only observe them.
4. **Learn from your real projects**: `cardmodel self corpus add ~/Programmering/ting` (and the others you want);
   the self-run learns from a tree whenever it changes. Review what it learned with `cardmodel list` and
   `cardmodel self adopt --dry-run`, then adopt and commit.
5. **Games natively: the next pieces** (the machine model is built; docs/MACHINES.md, ROADMAP "Machines").
   * The hardware test suites are in `~/Downloads/gb-test-suites` (downloaded with the user's go-ahead; run
     `cardmodel machine testroms ~/Downloads/gb-test-suites`). Every runnable test passes, the CGB's DMG
     compatibility mode included (mooneye's misc -C tests, dmg-acid2's CGB picture); what is skipped is for
     other hardware revisions (dmg0, mgb, sgb, cgb0, agb) or not self-checking. Next there: the boot ROM's
     per-title compatibility palettes for Nintendo's DMG games, as card data (Pan Docs documents how they are
     chosen), if colourised DMG games are wanted.
   * Close the survey's remaining failures (`cardmodel machine survey` lists them): the missing bank controllers
     (MBC7, HuC3, camera) are cards to add; the static and blank ones need a trace (the gameboy machine card
     exports `step` and `peek`: `gb.GameBoy(ctx, rom).m.call("step")`, `.m.call("peek", addr)`).
   * The DS, in the order its coverage report asks for it: SPI devices (firmware user settings, touchscreen,
     power), RTC, sound channel status, VRAM banks and the 2D engines (a first picture), then 3D. ARM9 blocks are
     already lifted (`machine nds ROM --lift`); Thumb, the ARM7 and cheaper word guards are next there.
   * Game Boy / Color titles as store products (the games session's Game Boy Player, on its branch).
6. **AnyPS5** (section 3f, docs/ANYPS5.md): the pending blockers `anyps5 blocks` ranks, host mappings for the
   standard host functions, the string/list IR for the standard data functions, and console observations for
   the rest (each named with its file, line and debt entry). Fixes go into the copy ~/Programmering/AnyPS5-cardmodel,
   never into ~/Documents/AnyPS5-main.
7. **Proofs**: the full verify proves 47 of 114 rewrite rules in Lean; the rest are witnessed only. Each one
   proved moves knowledge up the ladder (CM23).

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
* **`cardmodel emu`** prints the page's URL; if the browser does not open, open it yourself. No sound until you click
  the page once (browsers block autoplay). A port in use: `--port 0` picks a free one. The first launch of a ROM
  compiles its lifted code (a few seconds, one compile unit per ROM bank, through the resource governor); use
  `--engine native` to start at once.
* **A game misbehaves**: compare engines (`--engine native` vs lifted: `cardmodel machine diff ROM`), then look
  at `cardmodel machine survey`'s classification. A lifted/interpreter difference is a lifter bug (CM33); an
  interpreter problem is a hardware-card or instruction-card bug: write a synthetic ROM that shows it
  (`machine/asm.py`) and add it to `tests/test_machine.py`.
