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

## Now

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

## Later

* 🟢 Language-specific IR lowering passes (expression-only targets: Haskell, OCaml) still selected by card data.
* 🟢 A watch mode (Pheros `pheros-learn watch`) on top of `learn`, with the L103 safety bounds as a card.
* 🟢 Export a project's promoted cards back to the model (`learn --global`) with a review queue card.
* ⚫ GPU/daemon/hub-panel machinery from Pheros: out of scope for a self-contained CLI.
