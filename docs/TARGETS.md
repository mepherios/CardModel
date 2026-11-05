# TARGETS: where CardModel can go, what it is for, and what is missing

Written 2026-11-04 from `main` at 1f9f50d (after PRs #16 to #24) and the open PRs #4 (CI), #13 (lists; merged as
4a8fab8 while this was written), #18 (lazy store), #20 (GODEL.md), #25 (GODEL_AUDIT.md) and #27 (ENVIRONMENTS.md).
The user asked for one place that takes *the math, our current structure and what our model can build in the future,
what target our model can achieve and what steps we need to get there, what would
be useful and different targets and requirements for the generality and our special target-case method, our
current model for full individual card model reframing of programs and program structuring and running natively
on any platform, and what we are missing*. That is the order of the sections.

Every number here is copied from a dated measurement in another document or counted from the files on `main`; the
source is named beside it, and nothing was re-measured for this page. Each claim about the future carries one of
four grades, in the sense of law CM46: **proven** (a theorem the Lean kernel checked), **measured** (a number from a
run, at the tier that run had), **planned** (a design in a document, with nothing built), **conjecture** (follows
from the definitions, with no theorem, test or design yet). The other documents stay the reference for their
subjects: [FOUNDATIONS.md](FOUNDATIONS.md) for the mathematics, PR #20's GODEL.md for the Gödel abilities, PR #25's
GODEL_AUDIT.md for which subsystems build on it, PR #27's ENVIRONMENTS.md for the running machine as a model,
[ROADMAP.md](ROADMAP.md) for the phases, [SCALING.md](SCALING.md) for size, [MATH_CORE.md](MATH_CORE.md) for the
semantic core, [ANALYSE.md](ANALYSE.md) and [TRANSLATE_REAL_PROGRAMS.md](TRANSLATE_REAL_PROGRAMS.md) for what
happened on real code. When this page and a goal card disagree, the goal card is the measurement.

## 1. The mathematics and the structure today

### 1.1 The mathematics, in one paragraph

FOUNDATIONS.md states it as fourteen definitions and seven rules, and the whole model is their consequence. CardModel
is a **many-sorted equational theory with one intended model**. The op cards are the signature Σ (75 op cards on
`main`), the card IR is the term algebra T_Σ(X) over them, and the op cards' `ir.eval` is the one model M that
gives a term its value. A law is a sorted conditional equation with the tier of its evidence; reasoning is
congruence closure under the laws (the e-graph), which is sound by Birkhoff's theorem exactly when each law is
applied at the sorts it holds at (associativity of `+` is true on `int` and false on binary64). A concept's identity
is the hash of its cheapest ≈_E-equal term, so "known" is a lookup and "optimized" is the same choice under measured
costs with the chain of laws as its certificate. A target language, a compiler flag or a device is another
Σ-algebra M_L; emitting code is reading a term there, and where M_L disagrees with M is a divergence law, never a
patch. On top of that, every term is numbered twice: its **content** γ(t) is a homomorphism into the free abelian
group on the primes (atoms take primes forever, so gcd, lcm and "part of" are lattice operations), and its
**structure** σ(t) is Gödel's injective positional code. A translation between two Gödel sets is a homomorphism fixed
by the image of each atom; it preserves gcd exactly when distinct atoms map to disjoint images, and the atoms with
no image are its gap. In one picture (PR #20):

```
   atoms  ──ledger──▶  primes          (op/ADD ↦ 19, op/MUL ↦ 38, … : append-only, T3)
   term t ──γ───────▶  content  γ(t)   (exponent vector: ADD² · MUL¹  : a lattice, T1)
   term t ──σ───────▶  structure σ(t)  (Gödel's positional code       : injective, decodes, W-5)
   term t ──canon_E─▶  identity  h(t)  (sha256 of the cheapest ≈_E-equal term : D7)
   set S₁ ──carry───▶  set S₂          (a homomorphism fixed on atoms; gcd kept iff images disjoint, T2)
```

What is **proven** of this, kernel-checked in plain Lean 4 with no Mathlib and no `sorry` (`formal/GodelCore`,
MATH_CORE R1): T1 the content lattice (gcd meet, lcm join, distributive both ways, cancellation, `u ∣ v ⇔ v = u·w`),
T2 carry-over (a homomorphism; gcd preserved iff images disjoint), T3 the ledger (appending moves nothing, readings
stable under growth, injective), T4 freeness (merges keep the factor layer free, product equations break it), T5
transport (upward-closed properties go up the lattice, downward-closed ones go down), T6 rewrite invariants (a weight
orthogonal to balanced rules is conserved by any rewrite). What is **measured**: everything in §1.2. What is still
**conjecture** inside the formal core: content with negative exponents (the physics group; `GodelCore.Vec` is
`Nat → Nat`), composition of carry maps with gap accounting, and T6 as a pre-check on a mixed rule set.

### 1.2 The structure: the layers, and the measured state of each

| layer | what it is | measured on `main` (date, source) |
|---|---|---|
| store and kernel | every structure is a card in a registry; identity is the content hash of its JSON (CM02); layers model < extras < project | about 24,200 cards in 81 registries, 0 schema or load errors (ROADMAP §1, 11-04); loading all of them takes 3.5 s and 92 MiB on **every** command (SCALING §2); the SQLite index that reads one card at a time is PR #18, open |
| signature and model | 75 op cards with `eval`, ranks, domains and per-language `emit` templates; `ir.op_table` is the one model (A2) | op × language conformance 794 of 794 cells across 12 codegen languages (COVERAGE.md, 10-22); every rule witness and e-graph witness now evaluates in M (PR #21) |
| terms | the IR: `int` (ℤ), `float` (binary64), `bool`; the machine extension adds globals, `u8`/`int` arrays, `switch`, `store`, void functions | lists (`list[int]`, `list[float]`, four ops, 13 transformer kernels agreeing in 8 languages) landed with PR #13; no strings, tuples, records, options, closures (ROADMAP §2.2) |
| frontends | Python, the card language, the math language, and 15 languages through one text frontend with per-language dialects | round trip `lift(emit(f)) = f` 715 of 715 (FRONTENDS.md, 11-04); the pair matrix runs 18 sources × 12 targets with 0 failures and 2,267 of 2,280 round trips (MATRIX.md); each lift is witnessed by the source language's own toolchain |
| targets | 12 language cards with codegen (C, C++, Rust, Go, Swift, Java, JavaScript, TypeScript, Ruby, Lua, Lean, Python); 1 platform card (macOS); 28 vendored `translation_gap` cards | emission is **witnessed by running, never proved** (MATH_CORE §8); Lean emits 25 of 78 op signatures (COVERAGE.md); the only notion of a runner is `language@variant` on the host the model runs on, and the metric cards' host fingerprint records no cores, SIMD, caches, GPU or driver (ENVIRONMENTS.md, PR #27) |
| reasoning | sorted e-graph (PR #19), rewrite search, the logic engine (Datalog with kernel-checked certificates), theorem cards with an evidence ladder, Lean import and re-proof, witness tiers, difficulty ranks | 114 rewrite rules (47 Lean-proved), 1,650 theorem cards (1,579 Lean-proved), 111 redefinitions (107 verified); 2,667 tiered claims, 1,628 at tier proof (MATH_CORE); of 18 product questions 7 are decidable and promised (GODEL_METHOD W-15) |
| Gödel layer | the prime ledger, content vectors, structural codes, admissible numberings, definitions, identities, carry maps | 3,411 atoms in six sets (B0 50, computation 13, machines 9, analysis 20, bits 9, unreal 3,310; PR #20); content vectors on every op, function and algorithm card (G_U5 = 1.0); 574 definition cards; **26 % of definitions have a canonical form** (G_U7 = 0.258 against 0.9, COVERAGE.md); content is read from the canonical term where one exists (PR #22) and every identity names its equivalence (PR #23); of the 65 *code* definitions, 16 (25 %) have a canonical identity and 49 hash their lifted term; the ledger has 0 merge or deprecate events, so redefinition by cofactors is built and unused; the `godel` verify section costs 100.7 s of a 224.6 s quick verify (GODEL_AUDIT.md §3, PR #25) |
| analysis | `cardmodel analyse`: structure facts with provenance, logic obligations under path conditions, 12 divergence laws, every firing run in every runner | on the 49-function shared corpus, 23 functions have a difference witnessed inside their declared domain (38 findings); 30 obligations proved by a guard, 14 sampled, 3 open with a counterexample (ANALYSE.md, 11-04, macOS) |
| machines | a CPU is its instruction cards, a console its hardware cards, both compiled into one IR module; ROM code lifted into blocks and compiled natively | 512 LR35902 and 167 ARMv5TE instruction cards agree in the IR, Python and C engines (COVERAGE.md); 511 of 679 have symbolic terms (G_M6); Pokemon Crystal runs with 0 interpreted instructions on an unseen run, frame-identical to the interpreter (MACHINES.md §4); all 1,075 LR35902 outputs proven equal to their terms by z3 over a prime field (W-12) |
| optimization | `improve` (algorithm cards, affine matches, rule rewrites, the e-graph as a second candidate since PR #10, a ctypes native path and per-host costs since PR #15), the arena | arena sound, recall 0.91, ×16.9 geometric-mean speedup (SELF.md); certificates for substitutions are samples, for rewrites the laws that fired |
| real systems as cards | AnyPS5 (exports, debt, causes, derived semantics, witnesses); Unreal Engine's math (lifted, canonical over ℝ, witnessed against the engine's own code) | AnyPS5: 7,257 exports classified, complete fraction 0.357 (G_P4); Unreal 5.8.4: 2,852 of 3,310 functions lifted, 2,708 witnessed, 0 refuted (ROADMAP root) |
| autonomy | 47 laws, 52 goals with floors, 34 capability cards; the self-run cycle of 14 steps; the integrity check | the cycle runs and is bounded, on one Mac; CI with every toolchain and a daily cloud cycle that opens PRs is PR #4, open with conflicts against `main`; no scheduled cloud cycle has run yet (ROADMAP §4.5) |

Two sizes for orientation (counted on `main`): `cardmodel/engines/` is 24,281 lines, and the machine, emit, arcade,
unreal and language modules together are 20,474. MATH_CORE's audit of 10-22 counted 10,042 lines that build terms,
laws and canonical forms against 8,349 that run, emulate, witness or substitute, and the user's diagnosis then
("the build went deep on computation more than on understanding") is what FOUNDATIONS and PRs #19 to #24 answered.

### 1.3 Where the code still departs from the mathematics (after PRs #19 to #24)

* `machine/lift.py` constant-folds with its own small op table (rule A2; FOUNDATIONS §5, open).
* binary32 and fixed-width BV(w) are not sorts: `F32` rounds binary64, and machine integers are ℤ with a width
  check at the edge (F6; MATH_CORE phase 2). The foundations thread is adding an `f32` type.
* Content is canonical only where distillation reached a canonical term: 26 % of definitions (G_U7).
* T5 and T6 are proven and **unwired**: no engine asks "which cards inherit property P" through the lattice, and the
  e-graph does not refuse an impossible equality before searching (GODEL.md §5, §6, §12).
* No `godel cofactor` command, no homomorphism cards (ROADMAP G2), no physics set (G3), no negative exponents.
* Emission into a real language is witnessed, never proved, because the model has no formal semantics of C, Rust
  or the rest (MATH_CORE §8). Lean proves IR-level steps; running proves nothing and witnesses the last step.
* Behaviour canonical forms (`funcalg`) cover one integer variable, order ≤ 8 (GODEL.md §10).
* Proposed laws GM-1 to GM-9 (GODEL_METHOD.md) and the Mathlib download (W-2) wait for the user's yes; T7 and T8
  are cited from the literature, not proved in `formal/`.
* The running machine is implicit in D14: a target is `c@O2` on the host. ENVIRONMENTS.md (PR #27) proposes D15 to
  D18 and rule A8 (an environment is a model; capability cards are hypotheses of the conditional laws; a transfer
  judgment `carry(t, G, R)` from the generator to a runner yields a transfer card with the gap, the divergence
  laws firing, the certificate laws whose hypotheses fail, and the predicted cost with its tier) and catalogues 24
  gaps E1 to E24. Four of its probes were measured on the cloud host: a declared 260 MiB L3 the pointer chase
  never sees, gcc's default FMA contraction changing a result by one bit at 2⁻⁵⁴, FTZ/DAZ under `-Ofast` turning
  5 × 10⁻³¹⁰ × 0.5 into 0, and a binary32 sum whose answer depends on the runner's lane count. E6 says D7's
  additive cost model is wrong for anything that touches arrays.
* GODEL_AUDIT.md (PR #25) gives every subsystem a verdict on whether the Gödel model should be its underlying
  functionality (the rule: a permanent composable name, a part-of question, a translation with a gap, a key, or a
  composing summary; never meaning, syntax, I/O or values), and measures that four copies of the lattice type exist
  (`godel`, `realnorm`, `tiers`, `funcalg`) and that one identity key would cut saturation 32 % and dedupe the
  arena's 484 functions to 81.

## 2. What the model can build in the future

Each row is an ability the mathematics grants, what exists of it today, and what still has to be built. The grade
is of the *claim that the ability follows*, not of the engineering.

| ability | the fact behind it | today (measured) | to build | grade |
|---|---|---|---|---|
| any language to any language, with the gap computed, not guessed | D3, D14: one term, one homomorphism into each M_L; D13: the residual factor of a carry map | 18 sources → 12 targets through one IR, 0 failures on the corpus; 28 vendored gap cards | frontends on the languages' own parsers (Phase C); homomorphism cards per pair with the gap as a residual factor (G2, D4); round trip by semantic hash (D3) | proven for content (T2), measured for behaviour |
| knowing a function instantly, from source or binary | D7: a hash lookup on canon_E | hashes on definitions and Unreal's 2,852 terms; 26 % of definitions canonical | canon for every lifted function; the semantic-hash library and a lookup hit-rate goal (MATH_CORE phase 2) | measured; soundness proven given sorted laws (D6) |
| optimization with a certificate instead of a benchmark | D8; T6 | the e-graph's rule chain; `lean_chain` turns a chain into a Lean proof; substitutions are sampled | the e-graph in emission (E1); per-function × language × host costs (E2); T6 pruning | proven for rewrites, sampled for substitutions |
| understanding binaries as mathematics | MATH_CORE §4: symbolic execution of instruction cards gives each block a term | 511 of 679 instruction terms; W-12's 1,075 outputs proven; ROM blocks lifted and run natively (Pokemon Crystal 100 %) | the remaining ARM terms (G_M6); symbolic execution of lifted blocks, canon and lookup (F1); ISA cards for x86-64, ARM64, RISC-V (F2) | measured on two ISAs; the rest planned |
| a program that is one native binary on its device | Phase I: logic, data, machine and shell all compiled from cards; the OS reached only through boundary cards | the C card → shared library path, the macOS `.app` bundle, AOT lifting at purity 1.0 for one cartridge | the model's own backend IR → machine code (I5), a Mach-O/ELF writer (F2), shells generated from boundary cards (I2), the launcher without its service (I3), self-hosting (I6) | planned; the audit in §5.3 |
| new domains by one recipe: physics, mathematics, any definable system | GODEL.md §14: atoms, sorts and model, numbering, sorted laws, carry maps; then every ability applies | the unreal set (3,310 atoms) ran the recipe on a vocabulary that is not the model's own | the physics set with dimensional analysis as the witness (G3), which forces inverses into the content group; polynomial and ODE algebra through the operator view | proven for the lattice and carry; the physics group is conjecture in Lean |
| a program carried from the generator to any runner (CPU, GPU, memory hierarchy, numeric model, driver, API, OS) with every difference named | D15 to D18, A8 (proposed): an environment is a model; capability cards are hypotheses; `carry(t, G, R)` outputs a transfer card | runners are `language@variant` on the host; four numeric and memory probes measured (ENVIRONMENTS.md §4) | the environment card and probes (V-A), numeric-model laws (V-B), the device theory with SPIR-V witnessed by Mesa's lavapipe in CI so GPU conformance cells run without hardware (V-D), `cardmodel carry` (V-F) | planned; the four probes measured |
| properties proven once and inherited by divisibility | T5 | the theorem and its `formal_theorem` card | T5 queries in `analyse` and `coverage` (GODEL.md §13 item 3) | proven, unwired |
| redefinition by cofactor, for content and for behaviour | T1 `dvd_iff_exists_mul`; `funcalg` cross identities | `algebra gcd` finds `(3n − 3)·f(n) = (2n² + 3n + 1)·g(n)` from behaviour; deprecation events read through | `godel cofactor A B` and cofactor-based redefinition cards | proven for content, bounded for behaviour |
| languages designed and optimized from the math | Phase H: a language card as a term, with laws as theorem cards | the math language reads equations in and emits every codegen language (MATH_LANGUAGE.md) | H1 to H5, after a wide IR, frontends and the pair matrix | planned |
| a model that develops itself through the same gate as code | CM38, CM39, CM44: the cycle, the integrity check, the trace-back law | a 14-step cycle with findings and a ranked plan; adoption by hand (`self adopt`) | CI and the daily cloud cycle that opens a PR with its report (PR #4, A5); the work queue (S-C) | measured for the cycle; the PR path is built and unmerged |
| whole systems: a distribution with its drivers | SCALING §3: units, summaries, SCC order, content addressing, deterministic parallelism | S0 works, S1 partly (about 1 % of functions lift), S2 and S3 break | S-A to S-E; concurrency and memory-model cards | planned |

## 3. The achievable target, and the ordered steps to it

**The target**, as ROADMAP §0 makes the user's goal precise: for any program in any language card it knows, the
model *lifts* it to terms (or names the gap with its cause), *understands* each function (canonical form, semantic
hash, tier), *carries it over* to every language and platform card with a witness, *optimizes* it with a certificate
from measured costs, and *runs itself* in the cloud, proposing its changes as pull requests. Three limits bound what
"achievable" can mean, and they are theorems rather than engineering debts: equivalence of programs is undecidable
(Rice), so the model promises *instant* (a known hash), *decided* (bounded bit-vectors, linear recurrences,
Presburger) or *search* within a budget that may end in "not found" (MATH_CORE §7); emission into a real language is
witnessed until that language has a formal semantics in the model; and a device's operating system is always outside
the cards and reached through boundary cards. Inside those limits the target is achievable, and the order below is
the dependency order, not the workstream order. Each step names its exit measurement, which becomes a goal card
with a floor when it is adopted (INTEGRATION.md §4a).

| # | step | depends on | exit measurement | where it is designed |
|---|---|---|---|---|
| 0 | **land what is open**: CI (#4, after resolving its conflicts), lists (#13), the lazy store (#18), GODEL.md (#20) | — | CI green on `main`; every later PR runs it; `cardmodel` start-up independent of store size | ROADMAP Phase A; SCALING S-B |
| 1 | **finish the foundations audit**: `lift.py` on `op_table` (A2); `f32` and BV(w) as sorts; canonical content everywhere | 0 | FOUNDATIONS §5 every row "ok"; G_U7 ≥ 0.9 | FOUNDATIONS §6; MATH_CORE phase 2 |
| 1e | **the environment card and the numeric-model laws**: the generator's own card (ISA extensions, caches by the pointer chase, numeric model) on every metric and witness card; `fp_contract`, `denormal_flush` and `reduction_order` as laws in ANALYSE's family, witnessed by the probes made into cards; the e-graph reads the float laws it may fire from the target's numeric-model card | 0 | every metric card carries a full fingerprint; the three laws fire where the probes showed them (ENVIRONMENTS.md V-A, V-B, measurable now) | ENVIRONMENTS.md §6 |
| 2 | **widen the IR**: `str`, `tuple`, `Option`/`None`, records with methods over a receiver (`self.x`), `raise` as an effect, truthiness; each type lands with its op cards, templates in every codegen language and conformance cells | 0 (#13) | lift rate on the user's own code from 3.9 % to 0.5; stdlib top-level from under 1 % to 0.25 (ROADMAP §3) | ROADMAP Phase B, §4.1; TRANSLATE_REAL_PROGRAMS.md |
| 3 | **structure at scale**: summary cards per unit, opaque boundary cards for what does not lift, SCC-ordered analyses, per-resource budgets, a process pool | 0 | time per function flat from 10³ to 10⁵ synthetic functions; the Python stdlib swept in under an hour on 4 cores | SCALING S-A, S-B |
| 4 | **every pair verified**: the stdin harness, the pair matrix in CI, round trip by semantic hash, gap cards computed per pair | 0, 2 | pairs verified = frontends × targets; round-trip fidelity 1.0 on the corpus; 0 hand-written gap cards | ROADMAP Phase D |
| 5 | **optimize from truth**: the e-graph in emission, costs per function × language × host, Lean proofs from rule chains, T6 as a pre-check | 1, 4 | optimization coverage ≥ 0.9 of lifted functions; every int-sorted rewrite certificate at tier proof | ROADMAP Phase E; GODEL.md §13 |
| 6 | **understand binaries**: symbolic terms for all 679 instruction cards, symbolic execution of lifted blocks, the hash library | 1, 5 | G_M6 = 679; lookup hit rate ≥ 0.9 on the arena's planted functions (MATH_CORE §6 goals) | ROADMAP Phase F1; MATH_CORE phase 2 |
| 7 | **the native backend and platform cards**: ISA cards for ARM64 and x86-64, a Mach-O/ELF writer, shells generated from boundary cards, the launcher without its service, ship only fully lifted programs | 6 | a build with no `cc`; the Phase I dependency count 10 → 0; target devices with no host toolchain ≥ 1 (an iPad) | ROADMAP Phase I, F2, F3 |
| 7e | **devices as models**: the device theory and API cards (Vulkan, Metal) with their carry map and gap, a SPIR-V language card witnessed by lavapipe in CI, kernels over BV(32) with their independence obligations, then `cardmodel carry` and the transfer card over every environment in reach (the user's Mac through J4, then iPadOS with Phase I) | 1, 1e, 7 | GPU conformance cells run in CI with no hardware; a transfer card for every shipped program, with its verdict carried, predicted or refused | ENVIRONMENTS.md V-C to V-G |
| 8 | **the work queue and the cloud cycle**: work cards, leases, checkpoints, CI and cloud workers, adoption as PRs | 0, 3 | the same cards from 1 and from N workers; every adoption a PR with the cycle's report | SCALING S-C; ROADMAP A5 |
| 9 | **complete the Gödel layer**: one lattice type and one identity key minted once (the store index, every cache and dedup keyed by it), codegen and Lean as carry maps with computed gaps, `deprecate` driven by definitional redefinitions (`godel cofactor`), T5 queries, the physics set, inverses in the formal core | 1 | GODEL_AUDIT.md §6 steps 1 to 8 landed with their measured gains (−97 s per quick verify, 484 → 81 arena functions, 61 more redefinitions at proof tier); GODEL.md §12 every row "wired"; a dimensional-analysis witness on a physics equation | GODEL_AUDIT.md §5, §6; ROADMAP Phase G; GODEL.md §13 |
| 10 | **languages from the math, and self-hosting**: a language card as a term, the pipeline source → terms → optimization → source, package or binary; the kernel and runtime as cards | 2, 4, 5, 7 | a generated language package whose conformance passes; `cardmodel` running on a device with no Python | ROADMAP Phases H, I6 |
| 11 | **systems code and a distribution**: build systems and the preprocessor as languages, configurations as a dimension, concurrency and memory-model cards, a Debian source sweep | 3, 8 | one Linux driver family lifted with its configurations and gaps; time per function still flat at 10⁷ | SCALING S-D, S-E |

Steps 1e, 2, 3 and 4 can run in parallel once 0 is done, which is how the workstreams are already cut (ROADMAP §6);
step 9's first half (the identity key and the store index) is what GODEL_AUDIT.md names as the first S2 blocker, so
it belongs beside step 3 rather than after step 8.
Step 7 is the user's special case (§4), and it sits on 6, which sits on 5 and 1: a native binary made by the
model's own backend is only trustworthy when the terms it is made from are canonical and the ISA cards it uses have
symbolic terms checked against their semantics.

## 4. Alternative targets, and the general case against the special case

### 4.1 The two cases side by side

The **general case** is what GOALS.md and GODEL.md §14 describe: any definable system (code, mathematics, physics)
put on the structure by the recipe, so that its objects have content and identity, its laws are sorted equations
with tiers, and its translations are carry maps with gaps. The **special case** the user wants and needs is Phase I:
a program the model ships is one native binary on its target device, with no reliance on any program outside the
device (no emulator, interpreter, compiler, service or browser), inside one card-model structure. The requirements
differ in what each must contain, and the second needs the first underneath it.

| requirement | general case: any definable system | special case: self-contained native execution |
|---|---|---|
| atoms, sorts, the one model M | yes: the recipe's steps 1 and 2; for a vocabulary with no computation (units) the model is the free monoid | yes, and the sorts must include BV(w), `f32` and memory arrays, because the device computes in them (step 1) |
| sorted laws with tiers; canonical identity | yes: the whole point | yes, for the certificate that a lifted block or an optimized term still means what the source meant |
| the ledger, content, structure, carry maps | yes: gcd, cofactors, transport, gaps | useful, not required: a binary can be correct without content vectors; the gap computation says what a port to a new ISA cannot carry |
| proofs (Lean), the formal core | yes, where a claim can be a theorem | optional: witnesses against the device are the evidence that matters, tiered honestly |
| frontends for many languages | yes, one per language card | only the languages the shipped programs are written in (the card language, Python for the model's own logic, C++ for engine math) |
| codegen into many languages | yes | one backend per target ISA, plus the C card as a witness |
| ISA cards with symbolic terms; a binary writer | not needed | required: IR → ARM64/x86-64 through ISA cards, Mach-O/ELF written by the model (I5, F2) |
| platform cards and boundary cards | not needed beyond "a target is a model" (D14) | required per device: window, audio, input, files, clock, network as boundary cards; the shell generated from them (I2) |
| device runners, divergence per device | useful for the analyser (J4) | required: the same term witnessed on the device, and `int_div_zero` on ARM64 is a different answer than on x86-64; the transfer judgment of D18 is what "runs on this device" means |
| environment cards (the generator's and the runner's), capability hypotheses | the generator's card, so costs are dated and fingerprinted | required for every runner: the laws a certificate used must hold under the runner's capabilities (D17), or the optimization was a rewrite on G and is not one on R |
| no outside program at run time | not a requirement | the definition: every row of the Phase I audit at zero |
| ahead-of-time lifting at purity 1.0 | not needed | required for a shipped machine program: no interpreter and no `relift` on the device (I4) |
| the semantic-hash library | the "instant" promise | useful: a block already understood costs one lookup |
| effects and concurrency as terms | needed for systems code (S-D) | needed as soon as a shipped program has threads or interrupts (the DS has two CPUs) |
| self-hosting | not needed | the last step: the model's kernel and runtime as cards, so a device with no Python can run the model (I6) |
| scale | S2, S3 for distributions | S1 is enough for a game or an app; S2 for an operating system |
| honesty | every claim tiered (CM46) | the same, plus "runs on this device" is measured, never derived (SCALING §7) |

The difference in one sentence: the general case needs terms, laws, numbers and maps, and nothing about devices;
the special case needs ISA cards, platform cards, a binary writer and generated shells, and needs the general
case's core so that what it compiles is what the source meant.

### 4.2 Useful alternative targets

Each is a product the model could be aimed at, what it needs beyond today, what it gives, and when it is the right
choice. None excludes the others; they order the steps of §3 differently.

| target | what it is | needs (steps of §3) | gives | right when |
|---|---|---|---|---|
| **A. The verified translator and analyser** | any source in, any language out, every translation witnessed, every latent flaw named by its law and first input (`translate`, `matrix`, `analyse`) | 0, 2, 4; then J2 to J4 | the thing closest to done; useful today on the user's math code (firstlaw, pheros, ting's number theory) and useless on tooling until step 2 | the user wants value from the model on real code soonest |
| **B. Program understanding from binaries** | the REA lineage: a binary in, facts with provenance, terms per block, canonical forms, lookups, flaws witnessed; the AnyPS5 and machine work generalized | 1, 5, 6, then F2 | "solve code from binary", the user's 10-22 goal, on the ISAs that have cards | the targets are consoles, drivers or engines whose source is not available |
| **C. The mathematical knowledge system** | the math language, theorem cards, Lean, the Gödel layer, the physics set: a system that reads equations, proves, numbers, carries over between domains | 1, 9, Mathlib (W-2), T7/T8 in Lean | the general case's flagship; a model usable for mathematics and physics with no program in sight | the user wants the universal model before the product |
| **D. The native arcade on every device** | Phase I: games, players and the launcher as one binary per device, the iPad as the test | 1, 1e, 6, 7, 7e | the special case | the user wants something that runs on an iPad, built purely from cards |
| **E. The self-developing model** | the cycle in the cloud, findings as PRs with evidence, the analyser on every adoption, the model optimizing its own language | 0, 3, 8, then H5, J6 | autonomy as the user defined it: every integration self-developing, landing through the gate | the user wants the model to carry the other targets forward without hand work |
| **F. The distribution-scale optimizer** | Ubuntu and its drivers lifted, understood, redefined (SCALING) | 2, 3, 8, 11 | the largest claim; nothing today is within two rungs of it | after D or B have proven the core on one real system |

Recommendation (a judgement, not a measurement): **A first, because every other target sits on its core and it is
the only one that pays off within step 2; then D and B in parallel, since they share steps 1, 5 and 6 and the
special case is what the user needs; E as soon as step 0 lands, because it makes the rest cheaper; C and F after.**
The choice between D and B as the second target is the user's.

## 5. The current model for reframing programs, structuring them and running them natively

### 5.1 Reframing one program as cards (what exists)

The pipeline on `main`, for a function the frontends accept:

1. **Lift.** A frontend reads the source into an IR module: functions as systems of equations over terms, loops as
   least fixpoints, with the module's globals and arrays. The Python frontend, the text frontend (15 languages), the
   card language and the math language all produce the same T_Σ(X), and each lift is witnessed by running the
   original through its own toolchain (FRONTENDS.md). What does not lift is reported construct by construct with a
   line, never pasted through (GOALS.md non-goals).
2. **Understand.** The e-graph saturates the term under the sorted laws within a budget (8 iterations, 4,000 nodes)
   and extracts canon_E with the laws that fired; `tiers` recognizes polynomial, C-finite and linear-recursive forms
   and sizes a witness that reaches tier proof; `funcalg` fits a behaviour canonical form; `realnorm` gives the
   canonical form over ℝ for engine math; `numbering` and `godel` give structure and content.
3. **Record as the four sources** (MATH_CORE §2, CM44): a `definition` card (truth: the term, its canonical form,
   identity under a named equivalence, content vector, proof obligations), `action` cards (what is done from it: an
   emission per language, each linked by its witness or proof), `transformation` cards (identities, redefinitions,
   laws, each with a proof or a witness and a cost) and `method` cards (the procedure, with its complexity, rank
   and limits). Every function and algorithm card has a definition (G_U6 = 1.0); no action is without a truth
   (G_A9 = 0).
4. **Emit and witness.** Each language card's templates read the term in M_L; the emission is run on seeded inputs
   against the source, and `analyse` runs each divergence law's firing in every runner. Translation gaps are listed
   per language.
5. **Optimize.** `improve` substitutes verified faster forms in the pure core, re-checks after splicing, and leaves
   the effect shell byte-identical (CM21, CM22); the ctypes native path calls the C form inside its witnessed box.

How much of a real program reaches step 1 is the honest number of §6: 3.9 % of the user's own functions.

### 5.2 Structuring a program

* **The split is by construction** (METHODOLOGY.md §1): a function is in the pure core exactly when it lifts; the
  effect shell (files, sockets, login, clocks, GPU, input, module-level code) is never rewritten or executed.
* **Projects as cards** (CM41): a project card records branches, next steps and state; `lift_project` reads a whole
  tree, resolves calls across files and modules (Python follows its imports; text languages link by unique name;
  class-per-file languages resolve `Other.f`), lifts methods as `Class_method` when `self` is used only to call,
  and closes the call graph in one linear pass (0.21 s for a 2,000-deep chain).
* **What is designed and not built** (SCALING §3, §4.2): a summary card per unit (signature, effects, purity,
  termination evidence, cost, canonical form, hash, gaps) composed bottom-up over the call graph's SCCs; opaque
  boundary cards so one failed callee no longer fails every caller; the hierarchy distribution → package → build
  target → module → function; build systems and the preprocessor as languages; configurations as a dimension of a
  unit; interaction semantics as a trace model at the boundary (J5).

### 5.3 Running natively on any platform: the three routes today, and the audit

| route | how it runs | what it needs on the host | status |
|---|---|---|---|
| **translate / emit** | IR → a language card's source → that language's compiler or interpreter | the target language's toolchain (probed, never required) | 12 targets; witnessed |
| **the native path inside a Python program** (E3) | the C form of a pure function compiled to a shared library and called through ctypes inside its witnessed box, Python as the fallback | `cc` at build time | PR #15; int, float and bool only |
| **machines and the arcade** | instruction cards + hardware cards + a ROM's lifted blocks → one IR module → the C card → a shared library (`embed: cabi`) → the effect shell (the browser page, or the Swift `GameShell` in a macOS `.app` built by `arcade`) | `cc`, `swiftc`, `iconutil`, the Python service, WebKit for the launcher's pages, `git` for the Work tab | Game Boy and Color play lifted; Pokemon Crystal at purity 1.0; the Game Boy Player interprets by default; the DS is a prototype |

The Phase I audit (ROADMAP §5) lists **ten things a shipped program depends on** that are not cards: the Python
service on `127.0.0.1:8770`, the launcher's HTML/JS pages in WebKit, the hand-written Swift shells on AppKit, the
Game Boy Player's interpreter, `relift` after quitting (needs `cc` on the device), the C compiler at build time,
`swiftc` and `iconutil`, `git`, the browser page of `cardmodel emu`, and Python running the model itself. The
proposed goal "self-contained on the device" counts the external programs a shipped program starts or needs at run
time (service, interpreter, compiler, browser, git): 5 today, target 0. The count of target devices on which the
whole program runs with no host toolchain is **0** (macOS needs `cc` and `swiftc`). There is one platform card
(`cards/platform/macos`), two ISAs with cards (LR35902, ARMv5TE), and no ISA card for the CPUs the model's own
programs run on (x86-64, ARM64): the `translation_gap` cards `c__to__arm64_macho`,
`binary_x86_64__to__ir` and their siblings name the blockers, and that is all that exists of that path.

So "one card-model structure" today means: the logic, the data and the machine are cards, and the model's own
Python engines plus the platform's compilers turn them into a program. The target (steps 6 and 7 of §3) means: the
cards, the model's own backend through ISA cards, a binary writer, and shells generated from boundary cards, with
the device's operating system as the only thing outside, reached through those boundary cards. That last clause
is a limit, not a gap: it is what "natively" can mean on a real device (ROADMAP Phase I, honest limit).

## 6. What is missing, honestly

| area | measured today | what closes it | step |
|---|---|---|---|
| **lifting real code** | **96.1 % of the user's own functions do not lift** (254 of 6,576; TRANSLATE_REAL_PROGRAMS.md, 11-04); Python 3.13 stdlib: 110 of 11,999 top-level functions one file at a time, 296 of 49,743 with methods (0.6 %; FRONTENDS.md). First blockers in the user's code: 3,863 non-numeric annotations (`str`, `list[float]`, dataclasses, `None`), 954 non-numeric defaults or `*args`, 343 string or `None` constants, 243 + 227 + 210 tuple targets, subscripts and list literals, 217 `raise`, 204 non-constant names, 146 + 65 truthiness; in the stdlib 23,968 methods stop at `self.x` | the IR types of step 2, each with templates and conformance cells; records and methods; `raise` as an effect; truthiness as `!= 0` (cheap) | 2 |
| **the IR** | `int`, `float`, `bool` and fixed machine arrays; lists in PR #13; no `str`, tuple, record, option, closure, generic, iterator beyond `range`; no BV(w) or `f32` sort; no concurrency | step 2; MATH_CORE phase 2 for the sorts; SCALING §4.5 for concurrency | 1, 2, 11 |
| **any to any** | 18 sources, but through hand parsers of the IR subset of each language; C and C++ through clang only for Unreal's math; no Rust, Go, Java parser path; the 28 gap cards are vendored, not computed | frontends on the languages' own parsers (C2); gap cards as residual factors (D4) | 4 |
| **binaries** | ISA cards for 2 ISAs; 511 of 679 symbolic terms; lifted blocks are compiled and run, never canonicalized or looked up; no x86-64, ARM64, RISC-V, Wasm, JVM | step 6; F2 | 6 |
| **native execution** | 1 platform card; 0 devices without a host toolchain; 10 outside dependencies in the Phase I audit, 5 at run time; no backend from IR to machine code; no Mach-O/ELF writer; the Game Boy Player interprets by default; the iPad platform is being built in its own session | I1 to I6, F2, F3 | 7 |
| **environments** | a runner is `language@variant` on the host; no environment card, no capability cards, no device theory, no GPU (the cloud host has none; the user's Mac has an Apple GPU reached only through Metal); 24 gaps E1 to E24 across execution models, memory models, numeric models, drivers and APIs, and device cards; four probes measured on the cloud host (ENVIRONMENTS.md §4) | V-A to V-G; the cheapest big win is E17, SPIR-V as a language card witnessed by lavapipe in CI | 1e, 7e |
| **proof against witness** | emission never proved; substitutions sampled; only commutativity holds as a float law; behaviour forms one variable, order ≤ 8; G_U9 algorithm forms proved 0.32 against 0.5; G_C4 redefinitions 107 against 111; 4 redefinitions inconclusive | Lean proofs from chains (E1); float-sorted theorems; `tiers` theorems T7/T8 in Lean | 1, 5 |
| **the Gödel layer** | G_U7 canonical definitions 0.258 against 0.9 (16 of 65 code definitions have a canonical identity; the lever is loop canonicalization, not hashing); 0 ledger events, so cofactor redefinition is unused; four copies of the lattice type; the `godel` section is the most expensive self-check (100.7 s) and cannot fail; T5 and T6 unwired; no homomorphism cards; no physics set; no inverses in `GodelCore.Vec`; GM-1 to GM-9 pending; Mathlib not downloaded (GODEL_AUDIT.md §3) | step 9; the user's decisions in §7 | 1, 9 |
| **scale** | every global pass is "load everything, then loop": 3.5 s and 92 MiB of store per command; at most 4 parallel subprocesses machine-wide; logic budget 400,000 facts in memory; e-graph bounded per term; one 45-minute self cycle every 6 h; S2 (10⁵ to 10⁶ functions) breaks (SCALING §2) | PR #18; S-A to S-C | 0, 3, 8 |
| **autonomy and cloud** | CI exists only in PR #4 (open, conflicts); PRs #20 and #24 show no check runs; no scheduled cloud cycle has ever run; adoption is by hand; the cycle assumes macOS (`taskpolicy`, libproc, `sandbox-exec`); on Linux on 11-04 the unit suite had 3 failures and 2 errors of 364 and `verify --quick` failed 2 sections (ROADMAP §1; PR #4 fixes these) | merge #4, then A5 and S-C | 0, 8 |
| **divergence and devices** | 12 divergence laws as code, not cards; `int_width` sampled, not decided; no device runner; machine state (globals, arrays, void functions) analysed but not run in the runners | J2, J3 (interval analysis over BV(w)), J4 with Phase I | 1, 7 |
| **effects and interaction** | effects only as boundary cards; no trace model, no event or timing model, no memory-model cards; a shipped program's shell is hand-written per platform | J5; SCALING §4.5; I2 | 7, 11 |
| **measurements never taken** | G_M2 to G_M5 (ROM boot fraction, lifted identical, test ROMs, DS decoded), G_S1 (store launches), G_U10 to G_U12 (Unreal) are "not run yet" in COVERAGE.md of 10-22; the lift rate on the user's projects and optimization coverage have no goal card; COVERAGE.md itself predates PRs #2 to #24 | run the commands each goal names, on the cloud runner once it exists; adopt the proposed goals of ROADMAP §3 | 0 |

## 7. Decisions that are the user's

* Which target of §4.2 is second after A: the native arcade (D) or binaries (B). The steps are shared up to 6.
* Whether the iPad stays the test device for Phase I (ROADMAP says so; it forbids generating code on the device,
  which is what makes I4 and I5 necessary rather than convenient).
* The pending Gödel decisions: the Mathlib and Foundation downloads (W-2), the proposed laws GM-1 to GM-9, and
  GM-2's amendment of CM43 (identity is the hash of the canonical term, the positional code a witness).
* GODEL_AUDIT.md's decisions: GM-4 as a law, positional codes by per-set dense ranks (which amends CM43's text),
  minting the `LEAN_*` and ARM atoms, and adopting Unreal's identities as ledger events.
* Whether ENVIRONMENTS.md's D15 to D18 and A8 are adopted into FOUNDATIONS.md as written, and whether the user's
  Mac is the first device in reach for the transfer judgment.
* All pending owner decisions are tabulated in [DECISIONS_PENDING.md](DECISIONS_PENDING.md).
* The merge order of the open PRs: #4 brings CI and should go first so that #18, #20, #25 and #27 run under it.

## 8. Sources

FOUNDATIONS.md (the mathematics, rules A1 to A7, the 11-04 audit and PRs #19 to #24); PR #20 docs/GODEL.md (the
eleven abilities, graded); GODEL_METHOD.md (wave 1: W-1, W-3, W-5, W-12, W-15); MATH_CORE.md (the four sources, the
10-22 audit, phases 0 to 4, instant/decided/search); ROADMAP.md (the measured state of 11-04, the capability
matrix, Phases A to J, the Phase I audit); SCALING.md (the measured breakpoints, the principles, S-A to S-E);
ANALYSE.md (the laws and the corpus run); TRANSLATE_REAL_PROGRAMS.md (the sweep of the user's projects);
FRONTENDS.md and MATRIX.md (frontends and the pair matrix); MACHINES.md and ARCADE.md (lifting, the engines, the
shells, the honest limits); COVERAGE.md and SELF.md (goal values of 10-22 and 10-21); PR #25's GODEL_AUDIT.md (the
verdicts, the headline measurements of 11-04, the target structure and its order of work); PR #27's ENVIRONMENTS.md
(D15 to D18, A8, the gaps E1 to E24, the four probes of 11-04, the order V-A to V-G); the open PRs #4, #18, #20,
#25 and #27 and the merged #13; counts of files on `main` at 1f9f50d (op, law, goal and capability cards; lines of
engine code).
