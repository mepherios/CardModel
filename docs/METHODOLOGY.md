# METHODOLOGY — pure runtime, effect shell, verified optimization

## 1. All is code and runtime

Every program is split into two parts:

* **The pure core** maps values to values: math, physics, scoring, AI decisions computed from state. The card model
  represents it as cards. A function becomes a tree of op cards (the IR), with reference semantics on every op
  (`ir.eval`). This is the *pure runtime*: a description of the computation that does not belong to any language.
  Any language card can execute it, and every language row is checked against the same semantics (the op × language
  conformance matrix).
* **The effect shell** is everything that touches the world: files, sockets, login, clocks, randomness, GPU, input,
  and module-level code. The optimizer never rewrites it and never executes it. It stays in its original runtime,
  byte for byte (law CM21).

The split is not declared by hand. It falls out of construction: a function belongs to the pure core exactly when the
frontend can lift it into the IR, and the frontend fails closed on anything with effects.

## 2. Runs on anything

* **The program.** Python standard library only. `cardmodel verify --only portability` runs the kernel and rule
  witnesses under every Python 3.9+ interpreter found on the machine (goal `G_A2`).
* **The pure core.** Any language card with codegen: C11, C++17, Rust, Go, Swift, Java, JavaScript, TypeScript, Ruby,
  Lua, Lean 4, Python. Every op is checked in every language on every full `verify`.
* **Choosing the runtime.** `cardmodel optimize --functions` measures the same function card in every language
  (per-call slope; startup cancels). `cheapest(..., cost="measured")` then picks the fastest runtime this machine
  actually has.

## 3. The optimization pipeline (`cardmodel improve`)

| step | what | guarantee |
|---|---|---|
| lift | each top-level function → IR; failures are the effect shell | shell untouched (CM21) |
| domain | infer a domain; the **original** is the reference | — |
| candidates | **algorithm cards**: behavioural match, exact or affine (`a·card(x) + b`), every faster form guarded by the card's precondition. **Rule rewrites**: cheapest equivalent expression under the rule cards | the original still runs outside the precondition |
| verify | candidate vs original on: the inferred domain, wide random values, and a structured set (exhaustive small ranges, prime products, Carmichael numbers, powers of two ± 1). Exceptions must match by type; recursion limits and timeouts are never compared | any mismatch rejects |
| measure | original vs every verified candidate, in-process, same inputs, time-budgeted | kept unless faster beyond 10% noise (hub L4) |
| splice | replace only the chosen functions, by line range (hub L3) | every other byte identical |
| recheck | the spliced module, a fresh seed and more inputs | a counterexample reverts the substitution, and the recheck repeats (CM22) |
| emit | native source of every pure function for every language card | gaps are listed per language |

Math optimization sources:

* **Algorithm cards** (`cards/algorithm`):
  * closed forms for series;
  * fast doubling for Fibonacci;
  * square-and-multiply for powers;
  * √n bounds and a 6k±1 wheel for primality;
  * Newton's method for integer square roots;
  * Kernighan's bit count;
  * Horner's rule for polynomials.
* **Affine matching**: user code that is a scaled or shifted version of a card.
* **Rewrite rules** (`cards/rewrite_rule`): identities witnessed numerically and, where core Lean can, proved.

## 4. What is guaranteed, what is evidence, what is not covered

* **By construction:**
  * effect-shell bytes are identical;
  * module-level code and imports are never executed;
  * outside a card's precondition the original code runs;
  * outputs are written only after the recheck passes.
* **Evidence, not proof:**
  * equivalence of a substitution is sampled (seeded and reproducible, with a structured set that targets
    look-alikes);
  * an algorithm card's own identities are witnessed, and sympy- or Lean-proved where possible.
* **Measured:** speedups are in-process timings on this machine. The arena records them, so a regression shows.
* **Not covered:**
  * the effect shell's own performance;
  * concurrency and timing-sensitive behaviour;
  * floats (compared with relative tolerance 1e-12);
  * code outside the liftable subset (no strings, lists or objects yet: see ROADMAP).

## 5. Games and online play

The pipeline optimizes a game's pure logic (damage, XP curves, physics steps, procedural generation, AI scoring) and
leaves the effect shell (networking, login, session signing, anti-tamper, save formats) exactly as it was.
`arena/slowframework/online.py` shows this: four network and login functions pass through `improve` unchanged, while
the game math beside them gets orders of magnitude faster (`arena/slowframework_optimized/*.improve.md`).

Two honest boundaries:

1. **The protocol stays the same; the client binary does not.** Messages and logins are produced by the original
   code, but the program you run is modified. Online services can detect or forbid modified clients (anti-cheat,
   terms of service). `cardmodel` does not hide modifications and does not bypass anti-cheat or DRM, and it will not
   be extended to. The safe uses are your own games and code, single-player or offline builds, and services whose
   rules allow it.
2. **Compiled games are not liftable yet.** Today the frontend lifts Python. Large native games need the planned
   second frontend (machine code or C → IR), plus string/array support, before this pipeline applies to them. Those
   are the separate game sessions proposed in HANDOVER.md.

## 6. Bounded resources (law CM30)

Nothing cardmodel runs may take the machine down. `kernel/resources.py` sets the policy:

* **Machine-wide slots.** Every heavy subprocess (compilers, runtimes, Lean, sandboxed self-checks) takes one of
  `CARDMODEL_MAX_PARALLEL` slots: a file lock in the system temp folder, shared by every cardmodel process,
  including tests, CLI runs and other checkouts. Default: min(4, cpus/2, RAM GiB/4).
* **Per-child memory cap.** Each child runs at lower priority in its own process group. A watchdog reads the
  group's resident memory through macOS `libproc` (macOS does not enforce `RLIMIT_AS`) and kills the group past
  `CARDMODEL_CHILD_MB`. Default: 40% of RAM shared by the slots. A Lean batch that hits the cap is split and
  re-checked.
* **This process.** It stops itself with `MemoryBudget` past `CARDMODEL_SELF_MB`. The IR interpreter caps
  integers at 4 Mbit. The logic engine has a fact budget (400,000) and checks memory every round.
* **Waiting for memory.** Heavy work waits up to a minute while the machine's available memory is below
  `CARDMODEL_MIN_FREE_MB`.
* **Running one heavy job at a time** (the full tests, then a verify) is still the right habit: the slots
  bound compilers, not two Python suites.

## 7. Scaling it: the arena

`cardmodel arena --count N` generates a program of any size. It contains planted slow functions, look-alike decoys
that must *not* be substituted, already-optimal code, rewrite candidates and effectful functions. It runs the whole
pipeline and scores it:

* **soundness**: all of end-to-end, shell, decoys and preservation must hold;
* **recall**: planted functions improved;
* **speed**: geometric-mean speedup.

Every run is a card in `cards/arena_run/`. Goals `G_O2`–`G_O4` track soundness, recall ≥ 0.9 and speedup ≥ ×10.
Adding an algorithm card raises recall. Adding a decoy template makes the soundness test stricter.

## 8. Derivation and observation (law CM32)

A gap in a reimplementation of someone else's system (AnyPS5 reimplementing the PS5's libraries is the worked
example, docs/ANYPS5.md) closes in one of two ways, and the model keeps them apart:

* **Derivation.** A public standard (C, POSIX, IEEE 754, an RFC, an ISO codec, a hardware packet format) or the
  model's own structure fixes the behaviour. The model writes it as a card-language program with theorems, runs
  the reimplementation's own code next to it on seeded inputs, and records the run as a witness card.
* **Observation.** The behaviour exists only in the original system: names, signatures, layouts, error codes,
  constants, timing. Nothing derives it. The model classifies the gap with what observation would close it,
  attaches it to its file, line and debt entry, and never fills it with a made-up success. An observation, once
  recorded, is ground truth (CM15) and the rules reclassify the gap.

Hardware, services and policy (DRM) are named as boundaries of the effect shell (CM21), with what a host mapping
or the device would need. Rules decide every gap's cause (`stdlib/anyps5.card`), so each cause comes with the
proof of how it was reached, and a constraint fails the verify when a gap has none.
