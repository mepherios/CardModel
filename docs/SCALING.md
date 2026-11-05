# Scaling: from one file to a whole operating system

A living plan, first written 2026-11-04 from `main` at 907d619. It changes as the model's capability grows, and §8
says how. [ROADMAP.md](ROADMAP.md) lists *what* the model should do. This document covers *how big* it has to get, and
what in today's design breaks on the way.

## 0. The goal, in the user's words

> Make the card model able to structure infinitely large projects, even Ubuntu and drivers, and optimize and
> redefine all of it to be better. The project design functionality, timers and so on must scale perfectly. Keep in
> mind multi-core processing, multi-threading, the full computational spectrum and math spectrum, and the
> interaction model for what is accessible. The plan will evolve as the project, the interaction and the capability
> of the model increase.

Made precise:

1. **No size limit by design.** Every part of the model works on a stream of bounded units (a function, a module, a
   package) and composes their results. Nothing needs the whole project in memory or in one process.
2. **Cost grows no faster than the project.** Time and memory per function stay flat as the project grows: at most
   n log n overall, measured (§6).
3. **Only change costs work.** A result is keyed by the hash of everything it was computed from. A change recomputes
   what depends on it and nothing else.
4. **Every core, every machine.** Work runs in parallel on every core of a host and across hosts (cloud workers).
   The result is the same whatever the number of workers (seeded and deterministic).
5. **Systems code is in scope.** Concurrency, memory models, interrupts, device registers and build configurations
   are things the model lifts, reasons about and emits. They aren't reasons to give up.
6. **The model knows what it can use.** The hardware, toolchains, devices and permissions it can reach are cards. It
   plans its work, and the programs it emits, against them.

## 1. The scale ladder

Each rung is a size of project the model must handle end to end: lift, understand, optimize, emit and verify. The
sizes are orders of magnitude, used to set targets, not measurements.

| rung | example | functions | source lines | status |
|---|---|---:|---:|---|
| S0 file | `examples/algorithms/algos.py` | 10–100 | 10³ | works today |
| S1 project | CardModel itself, a typical app | 10³–10⁴ | 10⁴–10⁵ | partly: about 1 % of functions lift (ROADMAP §4.1) |
| S2 large codebase | the Python stdlib, the Linux kernel | 10⁵–10⁶ | 10⁶–10⁷ | breaks (§2) |
| S3 distribution | Ubuntu: thousands of source packages, drivers, build configs | 10⁷–10⁸ | 10⁸–10⁹ | breaks (§2) |

Each rung changes the design. S1 fits in memory. S2 needs indexing, incrementality and process parallelism. S3 needs
a content-addressed store outside git, distributed workers, and lifting of build systems and configurations.

## 2. Measured today (Linux, 4 cores, 15 GiB, Python 3.13)

| what | measured | at S3 (10⁸ functions) | where |
|---|---|---|---|
| loading the store | 24,233 cards in 3.5 s, peak 92 MiB (about 3.8 KB and 0.14 ms per card), on **every** command | about 380 GB and 4 hours before the first command does anything | `kernel/store.py` walks every registry and reads every card eagerly |
| the store on disk | 34 MB: 1,243 `card.json` files plus 22,990 pack lines | git can't hold 10⁸ cards | `cards/`, one git repository |
| lifting one file | linear on independent functions: 4,000 in 0.52 s | ~4 h of one core per 10⁸ | `frontend_python.lift_source` |
| the lift closure (a caller of a failed function fails) | **linear** since the worklist (`frontend_python.close_calls`): a 2,000-function chain with a failed root takes 0.21 s (it took 3.06 s with the old `while changed` loop) | — | one pass over the reverse call graph of the whole project |
| call resolution | across files and modules with `engines/lift_project.py` (Python follows its imports; text languages link by unique name, `Other.f` for class-per-file languages); single-file `lift_source` stays same-file | no build-system or header resolution yet (§4.2) | `lift_project`, `frontend_*.lift_*(externs=)` |
| translating and verifying | 22 functions × 9 runtimes in 46 s: one compile per function per language | about one core-year per language | `translate`, `conformance`, `matrix` |
| parallelism | threads over subprocesses, capped at `min(4, cores/2, RAM/4 GiB)` machine-wide; all Python-side work is one process (the GIL) | 3 of 4 cores idle in Python stages, and a 64-core host still runs 4 compiles at once | `kernel/resources.max_parallel` |
| logic evaluation | 56,818 facts about the store in 0.33 s, in memory, budget 400,000 facts | the facts of a large codebase exceed the budget | `engines/logic.evaluate(max_facts=400_000)` |
| e-graph | per term, at most 8 iterations and 4,000 nodes | fine per function, not across a program | `engines/egraph.saturate` |
| the self-run "timer" | one cycle at a time machine-wide, every 6 h, 45-minute budget, 15 step cards | an S2 corpus doesn't fit one cycle, and an interrupted step starts over | `engines/selfrun.py` |
| IR types | int, float, bool, plus fixed machine arrays of u8/int | no strings, lists, records or pointers, and **no concurrency** | `engines/ir.py` `TYPES` |

The headline: the model is correct and bounded at S0–S1, and every one of its global passes is "load everything,
then loop". That design ends at S2.

## 3. Principles every component follows

1. **Units, summaries, composition.** The unit of work is a function (or block, for machine code). Each unit gets a
   *summary card*: its signature, effects, purity, termination evidence, cost, canonical form, semantic hash and
   gaps. A module's summary is computed from its functions' summaries, a package's from its modules', and so on. A
   caller reads a callee's summary, never its body.
2. **Bottom-up over the call graph's strongly connected components.** Analyses run once per SCC in reverse
   topological order (Tarjan, linear time). Recursion inside an SCC is solved as one fixpoint. This replaces every
   "loop until nothing changes over all functions".
3. **Partial, not poisoned.** A function that doesn't lift becomes an *opaque boundary card* with its signature and
   observed behaviour. Its callers still lift, and only the edge is a gap (built: `frontend_python.close_calls`,
   `ProjectLift.boundaries`; observed behaviour is not recorded yet).
4. **Content addressing everywhere.** Every result card names the hashes of its inputs (source, cards, rules, tool
   versions), the way arcade build ids already do. Equal inputs mean equal results, so a result computed once on any
   machine is reused everywhere.
5. **Stream, index, never load all.** The store is queried through an index. Cards load on demand. A pass streams
   units, and memory is bounded by the unit plus its summaries.
6. **Deterministic parallelism.** Work is split by content hash. Results are merged in a fixed order. The seed comes
   from the unit's hash, so one worker and a thousand produce the same cards.
7. **Budgets per unit, not per run.** Every unit has its own step, time and memory budget. A unit that exceeds it is
   recorded with its cause (L1, honest limits) and retried with a bigger budget later. It never stalls the run.

## 4. Subsystems

### 4.1 The store at scale

* **Three tiers.** *Model cards* (laws, ops, languages: thousands) stay in git. *Project cards* (structure, plans)
  stay in the project's `.cardmodel/`. *Corpus cards* (millions of lifted functions, summaries, evidence) go into a
  content-addressed object store (`objects/ab/cdef…`, packed) with an index. Git holds only that store's manifests
  and the ledger.
* **An index in SQLite** (in Python's standard library, so the model still needs no third-party package): name → hash, category,
  semantic hash, summary fields, and call edges. `store.get` stays the API, and enumeration becomes a query.
* **Lazy loading.** A command touches the registries it uses. The integrity check and `verify` read the index
  first and load card bodies only for what they check.
* **Logic over the index.** The logic engine evaluates rules against indexed facts, shard by shard (stratified
  rules are evaluated per SCC of the predicate graph), so the 400,000-fact budget becomes per shard.

### 4.2 Project structure: from a folder to a distribution

* **Hierarchy as cards.** distribution → package → build target → module → function, with the same summary at
  every level (§3.1). A project card (CM41) becomes the root of that tree.
* **Build systems are languages.** Makefiles, Kconfig, CMake, Meson, Cargo, go.mod, `pyproject.toml` and Debian
  `control`/`rules` are lifted into structure cards: targets, inputs, flags, dependencies and configurations. That's
  how the model learns which files form one program and how they're compiled.
* **Configurations are a dimension.** One driver source is many programs (Kconfig options, `#ifdef`, target
  architecture). A unit's card holds its variants as a set of configurations with shared summaries, not as copies.
* **The C preprocessor** is lifted (macros as functions where they're expressions, `#ifdef` as configuration),
  using `compile_commands.json` or the build-system cards to get the real flags.

### 4.3 The timer: scheduling work at any size

The self-run's single cycle becomes a **persistent work queue**:

* A *work card* is one unit of work: kind (lift, summarize, verify, optimize, emit), input hashes, priority, budget,
  attempts and status. Its key is its input hash, so a queued item that already has a result is free.
* **Timers are cards** (interval, budget, due condition, owner), like the self-step cards today. A timer enqueues
  work, and the queue decides what runs.
* **Leases and checkpoints.** A worker leases an item with a deadline. A worker that dies loses the lease and the item
  returns to the queue. A long item checkpoints, so an interrupted step resumes instead of starting over.
* **Priority from the plan.** The ranked plan (SELF.md) and the goal gaps set priorities. Changed inputs first, then
  the units that unblock the most callers (§3.2), then breadth.
* **Workers anywhere.** The same queue is served by local processes, by cloud sessions and by CI jobs (the cloud
  workstream's scheduled cycle). Results come back as content-addressed packs, and adoption into main stays a PR
  (ROADMAP §7).

### 4.4 Multi-core and multi-machine processing

* **Processes for the Python side.** Lifting, summarizing, logic shards and the e-graph run in a process pool, one
  worker per core by default. Threads stay for waiting on subprocesses.
* **Separate budgets per resource** replace the single `max_parallel` cap: CPU workers (cores), compile slots
  (memory per toolchain), I/O, and network. Each resource is a card measured on the host (§4.7).
* **Batching for toolchains.** One compile per *module* per language, not per function. The stdin harness (ROADMAP
  D1) makes one build serve every seed. Builds are cached by content hash across runs and machines.
* **Sharding across machines.** The pair matrix and corpus sweeps shard by hash across CI jobs or cloud workers.
  Each shard's result is a pack, and packs merge deterministically.

### 4.5 Concurrency in what the model lifts and emits

Drivers and operating systems are concurrent programs, so the core needs concurrency as terms, not only as a way to
run faster:

* **Lift:** threads, atomics with their memory orderings, locks, interrupts and their handlers, per-CPU data,
  `volatile` and memory-mapped I/O registers, DMA. Each is an effect at a boundary card. The ordering rules are a
  *memory-model card* (C11, the Linux kernel memory model, the ISA's own model).
* **Reason:** race freedom and lock order as logic rules over the call graph's summaries. A data race is a gap with
  its cause, never an optimization opportunity.
* **Emit:** parallel-for, task graphs, SIMD and atomics as IR constructs, with templates per language card (threads
  in C/C++/Rust/Go/Java, workers in JavaScript). The optimizer chooses a parallel form only with a certificate:
  independence proved, or race freedom witnessed under a seeded scheduler.
* **Cost model per core count.** A parallel form's cost is measured on the host's cores (§4.7), so "faster" means
  faster on the device it runs on.

### 4.6 The computational and math spectrum

Each area enters the same way: types, op cards with reference semantics, laws as theorem cards, templates in every
codegen language, and conformance cells.

| area | today | needed |
|---|---|---|
| integers | unbounded int, bit ops | fixed-width BV(w) signed and unsigned with wrap/trap/saturate (MATH_CORE F3) |
| floating point | binary64, F32 via op cards | f16, bf16, f32 and f128 as types; rounding modes; fused ops; error bounds |
| exact numbers | (in witnesses only) | rationals, decimals, fixed point, big floats |
| complex, intervals | none | complex numbers; interval arithmetic for certified numerics |
| linear algebra | none | vectors, matrices, tensors; BLAS-level kernels as algorithm cards |
| polynomials and recurrences | function algebra (canonical forms, GCD of functions) | multivariate polynomials, Gröbner bases where needed |
| finite fields, crypto | EC ops, modular arithmetic | GF(2ⁿ), lattices (ML-KEM, ML-DSA atoms already as vectors) |
| discrete structures | none in the IR | strings, lists, maps, sets, graphs, trees (ROADMAP §2.2) |
| automata and text | none | regular expressions, grammars (the card language's grammar cards) |
| logic and solving | Datalog with proofs, Lean, z3 when present | SAT/SMT as a probed backend, Presburger by omega, bounded model checking |
| optimization | an exact simplex (game), cost-vector search | LP/ILP, convex optimization, scheduling |
| probability and statistics | seeded sampling in witnesses | distributions, estimators, confidence for sampled claims (CM46 tiers) |
| numerics | none | ODE/PDE solvers, quadrature, with error certificates |
| physics | planned (GOALS.md: units as primes) | dimensional analysis as a witness |

### 4.7 The interaction model: what the model can reach

The model already probes toolchains. It should know everything it can use, as cards:

* **Host cards:** CPU (cores, ISA, SIMD extensions, caches), memory, storage, GPUs and accelerators, OS and version,
  measured once per host and kept with the cost anchors.
* **Device and platform cards:** the target devices of ROADMAP Phase I (iPad, Mac, Linux, Windows), each with its
  ISA, OS APIs, sandbox rules and what a program there may do.
* **Capability cards:** what a program, or the model itself, is allowed to touch (files, network, devices, other
  processes). The effect shell checks them, and emitted programs declare them.
* **Reach cards:** the services it can use (cloud workers, CI, connectors), with their quotas. The scheduler (§4.3)
  plans against them.
* Planning uses all of this. The optimizer's cost vector includes the host's cores and SIMD, and the scheduler's
  worker count comes from the host card.

### 4.8 Understanding and optimizing at scale

* **Summaries first.** Effects, purity, termination and cost per function are computed bottom-up (§3.2), so a
  whole-program question ("is this pure?", "what does this module touch?") is a lookup over summaries.
* **The semantic-hash library** (MATH_CORE §4) is the scale lever. In a distribution most functions are copies or
  near-copies (vendored libraries, generated code, driver families). A function already understood costs one hash
  lookup.
* **Local e-graphs, global plans.** Saturation stays per function (bounded). Whole-program optimization works on
  summaries: inlining, specialization per configuration, and choosing targets and parallel forms.
* **Redefine to be better** means proposing a replacement unit, verified against the original unit's summary and
  witnesses, landing through the same gate as code (a PR with evidence).

## 5. Review of the current designs against this plan

These are the other workstreams' designs on `main` (2026-11-04) and the open cloud branch, checked against §3. Each
row is a recommendation for that workstream, not a change made here.

| component (workstream) | concern at scale | recommendation | urgency |
|---|---|---|---|
| `frontend_python.lift_source` closure (lifting) | done: worklist over a reverse call graph, linear (2,000-deep chain: 3.06 s → 0.21 s) | — | done |
| failure propagation (lifting) | one unliftable callee fails every caller | opaque boundary cards for the failed callee (§3.3) | high: it hides most of the lift rate |
| `frontend_text` call resolution (lifting) | same-file only, no includes or preprocessor | module/link resolution from build-system cards, `compile_commands.json` for C (§4.2) | before S2 |
| new IR types such as lists and strings (lifting) | must not assume in-memory, single-threaded semantics | element types generic; length symbolic; aliasing and mutation explicit, so the memory model (§4.5) can attach later | design now |
| `translate`, `conformance`, `matrix` (verification) | one compile per function per language; at most 4 parallel | batch per module, stdin harness, content-hash build cache, shard the matrix across CI jobs (§4.4) | before the matrix grows past S1 |
| `egraph` in `improve` (optimization) | bounded per term (8 iterations, 4,000 nodes): right locally | keep it per function; index rules by head op as the rule set grows; whole-program choices on summaries (§4.8) | fine now |
| `improve` (optimization) | one whole-program pass in one process | per-module, incremental by input hash, parallel | before S2 |
| `kernel/store` (shared) | eager load of every card on every command | SQLite index plus lazy loading, corpus cards in a content-addressed store (§4.1) | the first S2 blocker |
| `logic.evaluate` (shared) | in memory, 400,000-fact budget | evaluate per shard over the index (§4.1) | before S2 |
| `selfrun` (cloud) | one cycle per machine, 45 minutes, restarts interrupted steps | the work queue with leases and checkpoints (§4.3) | when corpora are added |
| `resources.max_parallel` (cloud) | one cap of at most 4 for everything | per-resource budgets from the host card (§4.4, §4.7) | small change, large gain |
| CI with every toolchain and the scheduled self cycle (cloud branch, open) | a single job per run | shard the matrix and sweeps across jobs; make the cycle a queue worker (§4.3) | after it lands |

## 6. Phases

Each phase ends when its scale benchmark passes on the cloud runner. The benchmark is **`cardmodel scale bench`**
(to build in S-A). It generates synthetic projects of 10³, 10⁴, 10⁵ and 10⁶ functions, like the arena's generator,
with call chains, recursion, failures and modules. It runs lift, summarize, verify and optimize, then records time
and peak memory per function, so the slope is a goal card.

* **S-A: measure and fix the shape (S1 solid).** The scale benchmark. The linear lift closure. Opaque boundary
  cards. Per-resource budgets. A process pool for lifting and summarizing. Goal: time per function flat from 10³ to
  10⁵ on synthetic projects.
  *Status (2026-11-05):* the benchmark is in (`engines/scale.py`, `cardmodel scale bench [--sizes ...] [--record]`,
  goals G_A11 scale slope and G_A12 memory bound). It writes a seeded package of leaf, loop, chain, cross-module,
  recursive, tail, mutual, failing and failing-caller functions (100 per module), and times `lift_project`,
  `analyse.structure`, `analyse.obligations` and a reference run of every lifted function, each size in its own
  child process. First run (Linux, Xeon 2.8 GHz, Python 3.13, seed 0; `cards/metric/scale__n*`): 518, 572 and
  931 µs per function at 10³, 10⁴ and 10⁵ (slope 1.80, nearly all of it in `lift`: 469 → 860 µs); 20 KB per
  function, peak 1,988 MB at 10⁵, so 10⁶ would need about 20 GB and G_A12 fails there today. The lift rate is
  0.86: every deliberate failure's callers fail with it until opaque boundary cards land. Summarize, verify across
  languages and optimize are not timed yet.
* **S-B: the indexed store and summaries (S2 ready).** A SQLite index, lazy loading, a content-addressed corpus
  store. Summary cards and the SCC-ordered analyses. Logic per shard. Goal: start-up time independent of store size;
  the whole Python stdlib swept (methods included) in under an hour on 4 cores.
  *Status (2026-11-04):* the SQLite index and lazy loading are in (`kernel/index.py`). A lookup by name, a
  registry's names and its size come from the index and read one card or none. Each registry's entry is keyed by
  a fingerprint of its files, so an edit re-indexes that registry and nothing is ever served stale. Measured with
  `tools/bench_store.py` on a Mac: `cardmodel show ADD` (a bare name) took 0.42 s with the 24k model cards,
  0.84 s with 10⁵ more and 4.23 s with 10⁶ more; with the index it takes 0.19, 0.23 and 0.23 s. Building the index
  once for 10⁶ new cards costs 6.7 s. Enumerating a whole registry (`ALL`) still reads it.
  The content-addressed corpus store, summaries and logic per shard are still to do.
* **S-C: the work queue and distributed workers.** Work cards, timers as cards, leases, checkpoints, cloud and CI
  workers, packs merged deterministically. Goal: the same cards from 1 and from N workers; an interrupted sweep
  resumes.
* **S-D: systems code (S2 for C).** Build-system and preprocessor lifting, configurations as a dimension,
  concurrency and memory-model cards, MMIO and interrupts at boundary cards. Goal: one Linux driver family lifted
  with its configurations, its summaries, and its gaps named.
* **S-E: a distribution (S3).** Package-level structure from Debian sources, the semantic-hash library across
  packages, redefinitions proposed per unit with evidence. Goal: a full source-package sweep with time per function
  still flat, and the count of near-duplicate functions the library recognizes.
* **Alongside all phases:** the math spectrum (§4.6) and the interaction model (§4.7) grow area by area, each as
  types, op cards, laws and templates.

Proposed goals (numbered from the registry at adoption):

| goal | metric | target |
|---|---|---|
| scale slope | time per function at 10⁶ ÷ at 10³ (synthetic) | ≤ 2 |
| memory bound | peak memory at 10⁶ functions | ≤ 2 GiB |
| start-up | `cardmodel` start-up time with a 10⁷-card corpus | ≤ 1 s |
| determinism | cards differing between a 1-worker and an N-worker sweep | 0 |
| resumability | work lost when a worker is killed mid-sweep | ≤ one unit per worker |
| core use | CPU utilization across all host cores during a sweep | ≥ 0.8 |

## 7. Honest limits

* Program equivalence is undecidable, so at any scale the model promises *instant*, *decided* or *search*, and a
  search can end in "not found" (MATH_CORE §7). Scale makes this matter more, not less.
* Concurrency adds nondeterminism. A witness under a seeded scheduler shows behaviour on the schedules it tried. A
  proof of race freedom is needed for "always".
* Hardware outside the model (a device's silicon, firmware, timing) is reached through boundary cards and measured.
  It can't be derived.
* A distribution changes daily. Incrementality bounds the work per change, but "all of Ubuntu understood" is a state
  the model keeps up with, not one it finishes.

## 8. How this plan evolves

* **The numbers in §2 are re-measured** whenever a phase lands, and by the scale benchmark once it exists, which the
  CI schedule runs weekly. Each row keeps the date and commit it was measured at.
* **A new capability adds a row.** A new IR type, op family, frontend, platform or host resource gets a row in §4.6,
  §4.7 or §5 in the PR that adds it, with its scale behaviour (linear? bounded? per unit?).
* **A design review is a row in §5.** When a workstream lands a design (a new pass, a store change, a scheduler
  change), it checks it against §3 and records the result here.
* **Rungs move.** When a rung's goal is met on the cloud runner, the ladder (§1) says so with the date, and the next
  rung's blockers move to the top of §5.
* This file is the plan, and goal cards are the measurements. When they disagree, the goal card wins and this file is
  corrected (the same rule as ROADMAP.md).
