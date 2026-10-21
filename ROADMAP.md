# ROADMAP

Status: 🟢 ready · 🟡 in progress · 🔵 done (dated) · ⚫ dropped. Process law (hub): every request lands here.

## Done (2026-10-21, first build)

* 🔵 Kernel: card contract, registries as directories (+ packs), layers (model/extra/project), types as cards,
  versioning with verified archives, closure.
* 🔵 Card IR, Python frontend and card-driven codegen for every language card with a codegen block (Python,
  JavaScript, TypeScript, C, C++, Rust, Go, Swift, Java, Ruby, Lua, Lean). It is verified by the op × language conformance matrix through the real
  toolchains on this Mac.
* 🔵 Function translation with lift fidelity, inferred domains, overflow-aware comparison, and evidence cards (`xleq`).
* 🔵 Witnesses for forms, known-answer vectors, rules, redefinitions (exact rationals or high precision, + optional sympy) and Lean theorems
  (grind/omega). Anti-vacuity is built into each witness.
* 🔵 Rewrite: cheapest form (domain, availability, measured), suggestions, cost-vector rank and pareto, rewrite search
  (proofs, optimisation).
* 🔵 observe → learn → promote with evidence thresholds. Optimizer: metric cards, calibrated anchors, L4 verdicts.
* 🔵 CLI usable from any folder. Coverage and goals are computed. The self-containment test uses the macOS sandbox.
* 🔵 Consolidation of hub + Pheros + Ting + rea-cards with provenance (`docs/PROVENANCE.md`).
* 🔵 `improve`: whole-program optimization with algorithm cards (exact and affine behavioural matching) and rule
  rewrites. Every substitution is verified against the original, guarded by its precondition, re-checked after
  splicing (reverted on a counterexample), and the effect shell stays byte-identical (CM21, CM22).
* 🔵 Arena: hand-written slow game framework plus a generator of programs of any size with decoys. Scored on
  soundness, recall and speed; runs recorded as cards.
* 🔵 Portability: verify runs under every Python 3.9+ on the machine; METHODOLOGY.md written.

## Done (2026-10-21, second build: knowledge, language, game)

* 🔵 **Logic as cards**: rules (if x, y -> z), stratified negation (with existential `_`), bindings and tests
  through op cards, aggregates, constraints, minimum-height proofs, budgets; Lean certificates of derivations
  (kernel-checked; a forged one is rejected); rule mining from data; the model's own laws as logic
  (`stdlib/self.card`, 0 violations); programs as facts (`logic code`).
* 🔵 **The card language**: functions (to the IR, so to every language card), logic, theorems, tests, cards
  in one file; the Pheros CL v0 function form; `algorithm.` references resolved to the cheapest verified form;
  `run`, `lang check|build|emit`, `repl`.
* 🔵 **Crystallised knowledge**: theorem cards with an evidence ladder (refuted < conjecture < witnessed < proved;
  exhaustive small-value phase, anti-vacuity, proof by exhaustion on finite boxes); law discovery (1,520
  candidates → 161 laws, 90 Lean-proved, 96 simplifying rewrite rules); the Lean core import (1,489 faithful
  readings, 0 semantic mismatches, 930 re-proved by the model's own tactics and rule chains).
* 🔵 **The game foundation**: the Vector Counter System as cards (moves, stances, fighters, design laws,
  precedents), its kernel in the card language (C++/Lean/any target), exact equilibria with certificates,
  8 design laws holding, sensitivity, automated balancing, AIs (equilibrium, vector reader), a systemic world
  with causes and counterfactual impact (`game/DESIGN.md`).

* 🔵 **Bounded resources** (CM30): machine-wide slots for heavy subprocesses, per-group memory caps enforced
  through libproc, a self cap, an integer-size cap, a smaller logic fact budget.
* 🔵 **Function algebra** (CM31): canonical forms from behaviour (annihilating recurrences), Gödel numbers of
  redefinition classes, GCD/LCM of functions (operator and value views), shifts, compositions, cofactor
  identities, fixed divisors, totals; verified fast forms in `improve` without algorithm cards; the lineage
  as cards (Servois 1814 to Gödel 1931).

## Done (2026-10-21, AnyPS5)

* 🔵 **AnyPS5 as cards** (CM36): every declared export, raw-NID alias, assembly export, debt entry, library and
  shader instruction as cards with file and line; the libraries and shader badges reproduced name by name; the
  real coverage ladder; every gap (exports, debt entries, empty modules) classified by rules in
  `stdlib/anyps5.card` with proofs; the module graph's blockers; eight semantics bindings derived from public
  standards, witnessed against AnyPS5's own C++ (docs/ANYPS5.md).
* 🔵 Theorem witnesses sample inside the hypothesis box when it is too large to enumerate (multi-variable
  bounded statements were vacuous before).
## Done (2026-10-21, third build: machines)

* 🔵 **Machine state in the IR and the card language**: globals, byte/int arrays, void functions, call statements,
  switch, constants read from cards, an evaluation-order pass (C computes what Python computes), language cards
  with machine templates and `embed` blocks (Python in-process, C through ctypes), split compilation.
* 🔵 **Instruction cards**: LR35902 (every base and CB opcode) and ARMv5TE/ARMv4T (ARM and Thumb forms), with
  timing and flags as data, semantics, IR, vectors; per-instruction conformance in three engines in `verify` (CM32).
* 🔵 **Game Boy / Game Boy Color from hardware cards**: memory map, MBC1/2/3+RTC/5, timer, interrupts, PPU (DMG and
  CGB), DMA/HDMA, joypad, serial, APU, CGB registers; lazy, exact component syncing; a ROM survey of the user's
  collection (COVERAGE.md).
* 🔵 **Lifting** (REA-style, internal): ROM basic blocks as specialised card IR, compiled natively, frame-for-frame
  identical to the interpreter (CM33).
* 🔵 **Effect shell**: `cardmodel emu` (browser page with audio and gamepads, headless PNG/WAV runs, saves, RTC)
  (CM21, CM34).
* 🔵 **DS prototype**: both CPUs on the ARM cards, memory maps, IPC, timers, DMA, divider, cartridge reads, HLE
  BIOS, direct boot; `cardmodel machine nds` measures coverage; the ARM9's ARM code is lifted through the same
  pipeline (`--lift`), identical to the interpreter in the differential run.

## Done (2026-10-21, fourth build: the arcade)

* 🔵 **Vector Duel**: a complete native game made of cards (data cards + card-language logic on the combat cards and
  kernel), compiled through the C card; arcade ladder, training, versus, options, saves, achievements (CM35).
* 🔵 **Cardmodel Arcade**: a native launcher (store, library, downloads, updates, verify, play time, achievements)
  and the arcade service that builds games from their cards into depots of checked chunks.
* 🔵 **Vector Duel 0.4.0** (shipped as a launcher update): multi-hit strings as chain cards with two design laws
  (GL9 strings end, GL10 every link is answerable), the duel-tree AI (`game/tree.py`: backward induction six
  exchanges deep over abstract states, string sub-games after every connect) as a new stage, the Oracle, and a
  boss whose three phases are written on the game card. Impacts are now judged after both fighters move.
* 🔵 **Your own cartridges in the launcher**: the Game Boy Player (the machine cards plus a card-language player,
  CM40) is installed like a game; every cartridge in the user's folders is a library entry, played where it is,
  with the survey's verdict and a title screen the machine draws; the DS is listed with its coverage.
* 🔵 **Work in progress in the launcher**: a Work tab with every session's branch and its programs; a program's
  version on a branch installs like a beta (built there with that branch's own code); Update falls back to the
  last good build when the cards in progress do not build; every title and datum on the pages opens something.

## Done (2026-10-21, fifth build: the model runs itself)

* 🔵 **Integration**: the AnyPS5, games, OAM and two fix branches merged into main (AnyPS5's law renumbered
  CM36); the rules, the number registry and the log in docs/INTEGRATION.md; the integrity check (CM39) in every
  quick verify.
* 🔵 **The core as cards** (CM37): 26 capability cards carry all the laws; their smoke checks run in every verify
  and self-run; LAWS.md lists them.
* 🔵 **The self-run** (CM38): `cardmodel self run|status|report|capabilities|auto|corpus|adopt`; background cycles
  on use (governed, every 6 h); learning into the self layer, quarantine, findings and a ranked plan
  (docs/AUTONOMY.md); docs/STORE.md lists everything in the store and what the model does for it.

## Done (2026-10-22, the self-run's deep checks and the store end to end)

* 🔵 **Deep checks as self-run steps**: `law_witnesses` runs every law card's witness test in a child process with
  the cycle's seed (G_A9); `store` launches every catalogue item through the store's own protocol (checked
  download, verify, a damaged file repaired, a native headless run; `cardmodel arcade check`, CM42, G_S1);
  `tests` runs the whole suite weekly. Every step runs under a deadline, so a step that does not return is stopped
  and reported instead of holding the cycle.
* 🔵 Fixed on the way: observing the model's own code crashed (`in` inside a conditional expression); a partial
  `verify` erased the sections it did not run from `last_verify.json`; the learning loop called the original source
  before the step-bounded interpreter, so a function that never returns for some inputs (the arena framework's
  `set_bits` on a negative number) hung it; an interrupted `resources.run` left its process group running; the
  named-fraction goal (G_U3) could read an observation of `examples/` instead of the model's own code.
* 🔵 The launcher installs against the main checkout when built from a worktree (`--home` to choose); headless
  `arcade run --frames` never touches the player's save.

## Gödel model: next (GOALS.md "What the card model is")

* 🟢 **The prime ledger**: an append-only pack of atoms with their primes (B₀ from the op cards and logic
  primitives first); a test that compares it with its git history so no prime is ever renumbered.
* 🟢 **Gödel vectors on cards**: content vectors computed from constituents (a function card from its IR's ops),
  beside the structural number funcalg already gives canonical forms.
* 🟢 **The physics set**: SI base units as primes, derived units as cards with exponent vectors, and a dimensional
  analysis witness for equations.
* 🟢 **Homomorphism cards**: maps between sets (language → IR, mathematics → physics) with the product law checked
  on samples, the GCD condition computed, and the residual factor written as the translation gap.

## Self-run: next

* 🟢 **Learn from the user's projects**: add them as corpora (`cardmodel self corpus add PATH`) and adopt what the
  cycles promote after review.
* 🟢 **Adoption with evidence in git**: `self adopt` into a branch of its own, with the cycle's report as the
  commit message, so learned knowledge reaches main through the same gate as code (docs/INTEGRATION.md).
* 🟢 **A plan that learns**: weight the plan by what fixed goals fastest in past cycles (the run records hold the
  history), instead of fixed severity rules.

## Arcade: next

* 🟢 **More of the game**: weapons as move sets, strings inside the exchange model itself, the systemic world as a
  campaign map.
* 🟢 **The Game Boy library in the launcher**: the same native shell runs a machine module (same interface), so
  each ROM in the collection can be a library entry built from the machine cards.
* 🟢 **The players, further**: lifted blocks in the Game Boy Player (built per cartridge on first play), a DS
  player once the DS picture hardware has cards, a CGB player choice for DMG cartridges (compatibility mode).
* 🟢 **Other platforms**: a platform card per OS (a shell and a bundle layout each).

## Machines: now and next

* 🔵 **Hardware test suites**: Blargg, mooneye and acid2 through `cardmodel machine testroms`, the DMG's OAM
  corruption bug included (the timing they pinned down is in docs/MACHINES.md §3; COVERAGE.md has the results).
* 🔵 **The CGB's DMG compatibility mode** (2026-10-21): a DMG cartridge on the CGB model runs as the CGB's boot
  ROM leaves it (KEY0, OPRI, the CGB-mode registers locked, the default compatibility palette as card data, the
  CGB's line-144 STAT timing); mooneye's misc -C tests and dmg-acid2's CGB picture pass (docs/MACHINES.md §3).
* 🟢 **The survey's remaining failures**: MBC7, HuC3 and camera bank controllers as cards; trace the static and
  blank titles.
* 🟢 **PPU accuracy**: a pixel FIFO (mid-line effects, exact mode 3 lengths, the LY=153 quirk); the boot ROM's
  per-title colourisation palettes for Nintendo's DMG games on the CGB (from data, not the boot ROM; the default
  palette is done).
* 🟢 **DS, as its coverage report asks**: SPI (firmware user settings, touchscreen, power), RTC, sound status,
  VRAM banks and the 2D engines (a first picture), then 3D; wait states; Thumb and ARM7 lifting, cheaper guards.
* 🟢 **Lifting further**: superblocks through not-taken branches, a fast path for dynamic WRAM/HRAM accesses,
  register caching across exits.

## Now

* 🟢 **Native path inside improved modules.** Optionally call the C/Rust form of a pure function through
  `ctypes` (stdlib), guarded by the int-width domain the witness established; keep the Python form as the
  fallback.
* 🟢 **More algorithm cards** (each one raises arena recall): sorting/searching once lists exist, matrix kernels,
  geometry (lattice counts), DP recurrences (linear recurrences → matrix power), modular inverses.

* 🟢 **stdin-driven test harness per language.** Today inputs are baked into the program, so every new seed costs one
  compile per language (the full matrix takes 30–250 s, depending on machine load). Read inputs from stdin instead;
  the build cache then hits across seeds. Each language card needs one more template: `read_int` / `read_float` /
  `read_bool`.
* 🟢 **Second frontend: C (or JavaScript) → IR**, reusing the conformance matrix as its witness. Lift-and-run makes
  translation two-way (C → Python and C → Rust, …). The Pheros `translation_gap` cards list which constructs matter
  first.
* 🟢 **Strings and lists in the IR.** Types `str` and `list[int]`, plus op cards for len/index/slice/concat. Each new
  op needs per-language templates and conformance cells. This is the biggest coverage gain for real code; Pheros
  `string_ops` gives the vocabulary.
* 🟡 **Recorded verification in CI form.** The self-run now verifies on every cycle (a full verify daily) and keeps
  the record in `state/self/`; what is left is writing verdicts into the cards (`verify --record`) as part of an
  adoption, so the history of evidence lives in git (hub L18: autonomous by default).

## Next

* 🟢 **Learned call cards with semantics.** Today a learned call card is a name plus evidence of use. Next, harvest
  signatures from the language's own introspection (the Pheros std_library harvest method), then propose `forms` when
  a stdlib function has an op equivalent (`math.gcd` ↔ `op/GCD`).
* 🟢 **Apply suggestions safely.** A surgical-edit tool for `suggestion` cards (hub L3) that runs the project's tests
  before and after the edit (hub L16 breaker pattern) and records the outcome as evidence.
* 🟢 **Measured costs for compiled forms everywhere.** Run `optimize --functions` over all function cards. Compare
  per-language per-call cost and feed `cheapest(lang=...)` for "which target should this run in".
* 🟢 **More proof backends.** Coq or Isabelle as siblings of `emit/lean.py` behind `emit/proofs.py`. Lean with
  Mathlib when a project provides one (probe a `lakefile` with Mathlib).
* 🟢 **Crypto atoms without third-party code.** Pure-Python XChaCha20-Poly1305 (HChaCha20 + ChaCha20-Poly1305) and
  AES-GCM, so each of Ting's atoms has two runnable stdlib forms.

* 🟢 **Game, next design steps.** Weapon move sets, the Unreal module around `game kernel --lang cpp`, and the
  story on the world's factions, memory and standing. (Strings, the duel tree and boss phases shipped in Vector
  Duel 0.4.0.)
* 🟢 **Lean fragment.** `∃`, `Int.gcd`/`emod` lemmas with casts, Bool lemmas; Mathlib projects when present
  (probe a lakefile), which would turn many "witnessed" laws into "proved".
* 🟢 **Logic.** Function symbols (lists, trees as terms) with a depth budget; magic-set rewriting for
  goal-directed queries on large fact bases.

## Later

* 🟢 Language-specific IR lowering passes (expression-only targets: Haskell, OCaml) still selected by card data.
* 🟢 A watch mode (Pheros `pheros-learn watch`) on top of `learn`, with the L103 safety bounds as a card.
* 🟢 Export a project's promoted cards back to the model (`learn --global`) with a review queue card.
* ⚫ GPU/daemon/hub-panel machinery from Pheros: out of scope for a self-contained CLI.
