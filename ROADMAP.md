# ROADMAP

Status: 🟢 ready · 🟡 in progress · 🔵 done (dated) · ⚫ dropped. Process law (hub): every request lands here.

## Done (2026-10-21, first build)

* 🔵 Kernel: card contract, registries as directories (+ packs), layers (model/extra/project), types as cards,
  versioning with verified archives, closure.
* 🔵 Card IR, Python frontend and card-driven codegen for every language card with a codegen block (Python,
  JavaScript, TypeScript, C, C++, Rust, Go, Swift, Java, Ruby, Lua, Lean). It is verified by the op × language conformance matrix through the real
  toolchains on this Mac.
* 🔵 Function translation with lift fidelity, inferred domains, overflow-aware comparison, and evidence cards (`xleq`).
* 🔵 Witnesses for forms, known-answer vectors, rules, redefinitions (numeric + optional sympy) and Lean theorems
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

## Machines: now and next

* 🟡 **Hardware test suites**: Blargg and mooneye through `cardmodel machine testroms` (needs the user's go-ahead
  to download them).
* 🟢 **The survey's remaining failures**: MBC7, HuC3 and camera bank controllers as cards; trace the static and
  blank titles.
* 🟢 **PPU accuracy**: a pixel FIFO (mid-line effects, exact mode 3 lengths, the LY=153 quirk); DMG colourisation
  palettes for DMG games on the CGB (from data, not the boot ROM).
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
* 🟢 **Recorded verification in CI form.** Run `cardmodel verify --record --seed $(date +%s)` on a schedule. Commit
  the changed `verification` fields so the history of evidence lives in git (hub L18: autonomous by default).

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

* 🟢 **Game, next design steps.** Multi-hit strings (cancel windows as move-card edges), weapon move sets,
  bosses as fighter cards with phase stances, a duel-tree AI (several exchanges deep), the Unreal module around
  `game kernel --lang cpp`, and the story on the world's factions, memory and standing.
* 🟢 **Lean fragment.** `∃`, `Int.gcd`/`emod` lemmas with casts, Bool lemmas; Mathlib projects when present
  (probe a lakefile), which would turn many "witnessed" laws into "proved".
* 🟢 **Logic.** Function symbols (lists, trees as terms) with a depth budget; magic-set rewriting for
  goal-directed queries on large fact bases.

## Later

* 🟢 Language-specific IR lowering passes (expression-only targets: Haskell, OCaml) still selected by card data.
* 🟢 A watch mode (Pheros `pheros-learn watch`) on top of `learn`, with the L103 safety bounds as a card.
* 🟢 Export a project's promoted cards back to the model (`learn --global`) with a review queue card.
* ⚫ GPU/daemon/hub-panel machinery from Pheros: out of scope for a self-contained CLI.
