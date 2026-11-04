# CardModel master plan: what it does, what it should do, and the order to get there

Written 2026-11-04, from the code on `main` (8bfe8af) and measurements taken in the Linux cloud container that
day. This is the reference the parallel workstreams align with. The dated record of what shipped stays in the
root [ROADMAP.md](../ROADMAP.md); goals live as goal cards and in [GOALS.md](../GOALS.md); the mathematical target
is [MATH_CORE.md](MATH_CORE.md); how big it has to get (up to a whole distribution such as Ubuntu with its drivers),
with multi-core and distributed work, the math spectrum and the interaction model, is [SCALING.md](SCALING.md), a
living plan every workstream checks its design against. When this plan and a goal card disagree, the goal card is the measurement and this
plan is updated.

## 0. The goal, in the user's words

> Make cardmodel self-running and self-optimizing and natively running, so all integrations are self-developing and
> can be transferred to all languages, models, optimizations, through math, target platform and structure, fully
> autonomously. Make sure everything is lifted and all language to all language works, not just Python → code.
> Make it run all on cloud.

Made precise, CardModel is done when, for any program in any language card it knows:

1. **Lift.** The program goes in (source, or a binary for a known ISA) and comes out as core terms: types,
   functions, structure and effects at the boundary. Whatever cannot be lifted is a named gap with its cause, never
   a silent drop.
2. **Understand.** Every lifted function gets a canonical form, a semantic hash and a tier of evidence (sampled,
   witnessed, proved). A function the model has seen before is recognised by lookup.
3. **Carry over.** Every term can be emitted in every language card with codegen, on every platform card, and the
   emission is witnessed by running it against the source on seeded inputs (and, where possible, proved at the IR
   level).
4. **Optimize.** The model picks the cheapest equivalent form and target for the host it runs on, from measured
   costs, with a certificate. It never ships a guessed "equal".
5. **Run itself.** The cycle (verify, learn, measure, rank flaws, fix) runs on its own in the cloud, proposes its
   changes as pull requests with the evidence attached, and the integrity check keeps every law and goal floor.

## 1. Where it stands (measured 2026-11-04, Linux x86-64, Python 3.13)

| area | today | evidence |
|---|---|---|
| store | 24,228 cards in 81 registries, 0 schema or load errors | `verify --quick` kernel section |
| laws, goals, capabilities | 47 laws, 52 goals, 34 capability cards; 32 capabilities pass here, `lean` and `formal_core` unavailable (no Lean in the container) | `verify --quick` |
| translation | Python → IR → 12 codegen language cards. 21 of 22 example functions agree in 9 runtimes here (C, C++, Go, Java, JavaScript, Python, Ruby, Rust, the source); Lean, Lua, Swift and TypeScript are unavailable in the container | `translate examples/algorithms/algos.py` |
| lifting real Python | **140 of 20,879 top-level standard-library functions lift (0.7 %)**, and methods (69,615 more) are never tried, so the true rate is about 0.15 % | sweep in §4.1 |
| math | 74 op cards, 1,650 theorem cards (1,579 Lean-proved), 114 rewrite rules, 111 redefinitions, an e-graph prototype, function algebra (canonical forms, GCD of functions) | `verify`, `cards/` |
| machines | LR35902 512/512 and ARMv5TE 167/167 instruction cards agree in IR, Python and C; Game Boy/Color run lifted; DS prototype | `verify --quick` machine section |
| optimization | `improve` with algorithm cards and rule rewrites; arena sound, recall 0.91, ×16.9 speedup | SELF.md |
| autonomy | the self-run cycle exists and is bounded, but is tuned for one Mac (macOS QoS, libproc memory caps, `sandbox-exec`); no CI, no cloud schedule | `kernel/resources.py`, `engines/selfcheck.py` |
| tests | 364 unit tests on Linux: 3 failures, 2 errors, 31 skipped (506 s). `test_cli` fails through the same verify sections; `test_gb_mappers` (Sachen header) and `test_witness` (builtin forms) fail too | `cd tests && python3 -B -m unittest` |
| portability | `verify --quick` fails 2 sections on Linux: `forms` (`re_operation/list_strings` expects macOS `ls` strings) and `vectors` (`re_operation/detect_format` expects `/bin/ls` to be Mach-O) | `verify --quick` |

The headline: the core is sound and verified, but it is **deep and narrow**. It proves and translates small integer
functions very well, and almost no real-world code reaches it.

## 2. Capability matrix

### 2.1 Languages

"In" is a frontend (source → IR). "Out" is a codegen block on the language card. "Verified here" means the
toolchain is in the cloud container and the conformance matrix runs.

| language | in | out | verified in cloud today | to reach "any → any" |
|---|---|---|---|---|
| Python | ✅ (subset, §4.1) | ✅ | ✅ | widen the frontend (Phase B) |
| card language | ✅ | (it is the IR's surface) | ✅ | none |
| C | ⚠ clang JSON AST, math only (`unreal/clangast.py`) | ✅ | ✅ | general C frontend on the clang path (Phase C) |
| C++ | ⚠ same as C | ✅ | ✅ | same, plus classes and templates later |
| Rust | ❌ | ✅ | ✅ | frontend (Phase C) |
| Go | ❌ | ✅ | ✅ | frontend through `go/parser` (Phase C) |
| Java | ❌ | ✅ | ✅ | frontend through the JDK's tree API (Phase C) |
| JavaScript | ❌ | ✅ | ✅ | frontend (Phase C) |
| TypeScript | ❌ | ✅ | ❌ node 22.23 < 23.6 needed | fix the probe or install, then frontend |
| Ruby | ❌ | ✅ | ✅ | frontend through Ripper/Prism (Phase C) |
| Lua | ❌ | ✅ | ❌ no `lua` | install in cloud env |
| Swift | ❌ | ✅ | ❌ no `swiftc` | install or macOS runner |
| Lean | ✅ theorem import only | ✅ | ❌ no `lean` | install `elan` in cloud env |
| PHP, Perl, shell | ❌ | ❌ | toolchain present | codegen first (cheap), then frontend |
| C#, Kotlin, Haskell, OCaml, Julia, R, Zig | ❌ | ❌ | toolchain absent | codegen + toolchain; Haskell/OCaml need expression-only lowering |
| Machine code (LR35902, ARMv5TE/ARMv4T) | ✅ lifting | ✅ (instruction semantics in IR, Python, C) | ✅ | symbolic execution (MATH_CORE F5) |
| x86-64, ARM64, RISC-V, Wasm, JVM bytecode | ❌ (only `translation_gap` cards) | ❌ | — | ISA cards (Phase F) |

So of 23 language cards: **2 full frontends, 12 targets, 0 language pairs that do not pass through Python.**
"All language to all language" today means "Python to twelve".

### 2.2 Types and structure (the IR)

| structure | IR today | needed for real code |
|---|---|---|
| int (unbounded), float (binary64), bool | ✅ | — |
| fixed-width bit-vectors BV(w) | implicit in machine code | first-class type (MATH_CORE F3) |
| globals, byte/int arrays, void functions, switch | ✅ (machine extension) | — |
| strings | ❌ | `str` + op cards len/index/slice/concat/find/format, per-language templates |
| lists / arrays of any element | ✅ `list[int]`, `list[float]` with value semantics: len, index, store, new, copy, `for x in xs`, comprehensions over `range` ([LISTS.md](LISTS.md)) | other element types, append, slicing |
| tuples, multiple return values | ❌ | `tuple[...]` and destructuring |
| dicts / maps, sets | ❌ | `dict[K,V]`, `set[T]` |
| records / structs / classes, methods | ❌ | record types, methods as functions over a receiver |
| optionals / None, exceptions | ❌ | `Option[T]`, error results; exceptions as an effect at the boundary |
| closures, higher-order functions, lambdas | ❌ | function values (needs a lowering for C) |
| generics | ❌ | monomorphisation at emission |
| iterators, generators, `for x in seq` | `for i in range(...)` and `for x in xs` over a list | iteration over list/str/range/dict |
| async, I/O, network | out of scope for the core | effect shell (CM21, CM34): kept byte-identical |

### 2.3 Mathematics

| area | today | next |
|---|---|---|
| arithmetic, bits, comparison | 74 op cards with per-language templates | bit-vector ops as first-class |
| real analysis (sin, exp, sqrt, …) | op cards exist, but the Python frontend does not resolve `math.sqrt` (§4.1) | map the `math` module to op cards |
| theorems and proofs | evidence ladder, Lean kernel, 1,579 proved | Lean in the cloud; Mathlib when present; Coq/Isabelle backends later |
| equational reasoning | rewrite search, e-graph prototype | saturation in `improve` and translation; Lean proofs from e-graph chains |
| function algebra | recurrences, canonical forms, GCD/LCM of functions | proofs of algorithm-form equality (G_U9) |
| Gödel model | content vectors, 3,409 atoms in 6 sets | prime ledger, homomorphism cards, physics set (GOALS.md) |

### 2.4 Platforms

| platform | today | next |
|---|---|---|
| macOS (the user's Mac) | everything, including sandbox and QoS | keep |
| Linux (cloud container, CI) | runs; 2 verify sections fail on macOS assumptions; resources and sandbox fall back | make `verify` green on Linux (Phase A) |
| Windows | untested | platform card, later |
| browser / Wasm | the emulator's effect shell only | Wasm as an output language |

## 3. Goals

The existing 52 goal cards stay, with their floors (docs/INTEGRATION.md §4a). These are the new measurable goals
this plan adds. They get their `G_` numbers from the registry when adopted.

| proposed goal | metric | today | target |
|---|---|---|---|
| lift rate, Python stdlib (top-level functions) | fraction that lift | 0.007 | 0.25 by Phase B end, 0.5 by Phase D |
| lift rate, Python stdlib (all functions, methods included) | fraction that lift | ~0.0015 | 0.2 |
| lift rate, the user's own projects | fraction that lift | not measured | 0.5 |
| languages with a frontend | count of language cards with `frontend` | 2 | 8 (Phase C), every card with a toolchain (Phase F) |
| languages with codegen | count with `codegen` | 12 | 18 |
| language pairs verified | ordered pairs (A, B) where A → IR → B agrees on the conformance corpus | 12 (all from Python) | every frontend × every target |
| round-trip fidelity | lift(emit_B(lift_A(f))) has the same semantic hash as lift_A(f) | not measured | 1.0 on the corpus |
| verify green on Linux | failing sections in `verify --quick` on the cloud runner | 2 | 0 |
| cloud toolchains | codegen languages runnable in the cloud environment | 8 of 12 | 12 of 12 |
| self-run in the cloud | days since the last scheduled cloud cycle | never | ≤ 1 |
| adoption through PRs | self-run findings that reach main as a PR with evidence | 0 | every adoption |
| optimization coverage | fraction of lifted functions with a measured cheapest form and target | not measured | 0.9 |
| self-contained on the device | external programs a shipped program starts or needs at run time (service, interpreter, compiler, browser, git) | Arcade: 5 (§5 Phase I audit) | 0 |
| lifted purity of shipped programs | share of executed instructions that run as lifted, natively compiled card code, not an interpreter | per cartridge app (Pokemon Crystal 1.0); the Game Boy Player 0 | 1.0 for every shipped program |
| target devices | platform cards on which the whole program runs with no host toolchain | 0 (macOS needs cc and swiftc) | macOS, iPadOS/iOS, Linux, Windows |

## 4. Gaps, ranked by how much real code they block

### 4.1 Lifting (the biggest gap)

The sweep: `lift_source` over every `.py` in the Python 3.13 standard library (tests excluded), counting the first
reason each top-level function fails. Methods inside classes are not passed to the lifter at all.

| first reason | share of 20,879 | fix |
|---|---:|---|
| varargs, defaults or keyword-only parameters | 29.7 % | defaults become a wrapper per call site; keyword-only parameters are positional in the IR; `*args` needs lists |
| type annotation other than int/float/bool | 27.0 % | accept `str`, `list[...]`, `tuple`, `Optional`, user classes once the IR has them; ignore annotations it can infer past |
| decorators | 4.9 % | known decorators (`staticmethod`, `functools.cache`, `lru_cache`, `property`, `dataclass` fields) are transparent or map to a memo card; unknown ones stay a gap |
| statement Expr (docstrings, bare calls) | 4.6 % | skip docstrings; a bare call is a `do` statement |
| call to an unknown function | 3.2 % | resolve module functions and the `math` module to op cards; call cards with semantics |
| constant (str, None, tuple) | 3.2 % | strings and None in the IR |
| name not a parameter or local (module constants, globals) | 2.7 % | read module-level constants as `["int", v]`/globals |
| attribute (`math.pi`, `self.x`) | 2.7 % | `math.pi`, `math.e`, `math.tau` lift as constants; `self.x` waits on record types |
| tuple, list, subscript, dict expressions | ~4.2 % | the structure types of §2.2 |
| try, nested def, import, global, async | ~3.4 % | effects and closures, later phases |

Fixing the first four rows only removes a function's first obstacle; most then hit the missing structure types.
That is why Phase B does the cheap signature fixes and the IR's `str`/`list`/`tuple` together.

### 4.2 Any to any

Every pair goes through the Python frontend, so "Rust → Go" or "Java → C" is impossible today. Frontends are the
gap, not targets. The stdlib-only rule (no third-party packages at runtime) means each frontend uses the
language's own parser, probed like a toolchain and never required:

| language | parser to use |
|---|---|
| C, C++ | `clang -Xclang -ast-dump=json` (already used by `unreal/clangast.py`) |
| Go | a small Go program on `go/parser` printing JSON |
| Java | the JDK's `com.sun.source.tree` API in a single-file Java program |
| JavaScript, TypeScript | the TypeScript compiler's own API when installed; else a hand parser for the IR subset |
| Ruby | `Prism`/`Ripper` from Ruby's standard library |
| Rust | a hand parser for the IR subset (rustc offers no stable AST dump) |
| PHP | `token_get_all` + a subset parser |

Each frontend lowers to the same IR and is witnessed by the existing conformance matrix: a function written in the
source language and the IR's emission must agree on seeded inputs.

### 4.3 Verification

* The matrix is per op × language and per function × language, with Python as the only source. It must become
  per **pair**, plus a round-trip check by semantic hash.
* Every new seed costs a compile per language (inputs are baked in). The stdin harness (root ROADMAP "Now") makes
  the build cache hit across seeds and is a precondition for an N × N matrix in CI time.
* Emission is witnessed by running, never proved (MATH_CORE §3). IR-level transformations should carry Lean
  proofs; emission stays witnessed (MATH_CORE §8 says why).

### 4.4 Optimization

* `improve` matches by behaviour; certificates are samples. The e-graph exists but is not yet used by `improve` or
  `translate`.
* The cheapest *target* is not chosen: costs are measured per op, not per function × language × host.
* No native path from Python modules (ctypes call into the C/Rust form, guarded by the witnessed int-width domain).
* 5 cost anchors disagree with measurement (SELF.md); anchors need re-measuring per host, the cloud runner included.

### 4.5 Autonomy and cloud

* The self-run assumes one Mac: `taskpolicy`, libproc memory accounting, `sandbox-exec`, `~/Applications`. On Linux
  these fall back or are skipped, and two verify sections fail.
* No CI. Nothing runs unless someone runs it.
* Learned knowledge reaches main only by hand (`self adopt`). It should arrive as a PR carrying the cycle's report.

## 5. Phased milestones

Each phase ends when its goals are met on the cloud runner, `verify` is green there, and the integrity check
passes. Phases A and B start now; C and D can overlap B once the IR types land.

### Phase A: green and running in the cloud

* A1. Make `forms` and `vectors` host-independent: the `list_strings` and `detect_format` vectors pick their
  expected binary by platform (ELF on Linux, Mach-O on macOS) or use a checked-in fixture.
* A1b. The `projects` verify section fails on every cloud session branch (`claude/...` with unmerged work that no
  project card lists in `branches`), so parallel sessions trip it by existing. Session branches should be listed
  automatically, or the check should count only branches older than their PR.
* A2. Resources on Linux: memory accounting from `/proc` instead of libproc; `nice`/`ionice` instead of
  `taskpolicy`; the self-containment check through a Linux sandbox (bubblewrap or a read-only mount namespace when
  present, honest "unavailable" otherwise).
* A3. Cloud environment installs the missing toolchains: Lean (elan), Lua, a TypeScript that meets the probe (or a
  probe that accepts `tsc`), and Swift where available. Target: 12 of 12 codegen languages verified.
* A4. CI: a GitHub Actions workflow running `verify --quick` and the unit tests on every PR, the full verify and a
  self-run nightly, with `last_verify.json` and the self report as artifacts.
* A5. Scheduled self-run in the cloud whose findings open a PR (`self adopt` into a branch, report as the PR body).

### Phase B: lift real Python

* B1. Signatures: default values, keyword-only parameters, docstrings, known decorators, module constants.
* B2. `math` and `operator` module calls and attributes mapped to op cards (`math.sqrt` → SQRT, `math.pi`).
* B3. IR types `str`, `list[T]`, `tuple[...]`, `None`/`Option[T]` with op cards and templates in all 12 targets,
  each op with its conformance cells.
* B4. `for x in seq`, comprehensions, `len`, `enumerate`, `zip`, `min/max/sum` over lists.
* B5. Methods: lift classes as records plus functions over a receiver; `self.x` reads and writes.
* B6. The sweep as a tool and a goal: `cardmodel lift-sweep PATH` prints the rate and the reason histogram, and the
  self-run measures it on the stdlib and on the user's corpora. *Tool done (engines/sweep.py, project lift with
  methods and calls across modules); measured 2026-11-04 on the Python 3.13 stdlib without tests: 110 of 11,999
  top-level functions one file at a time, 113 with calls across modules, 296 of 49,743 with methods. 23,968 methods
  stop at `self.x` (B5), 5,495 at non-scalar annotations, 4,611 at defaults/varargs (B1). The self-run goal is still to wire.*

### Phase C: any language in

* C1. A frontend contract: a `frontend` block on the language card (command, parser program, lowering), the same
  shape `cards/language/python` and `cardlang` already have.
* C2. C (clang JSON) by generalising `unreal/clangast.py`; then Go, Java, JavaScript, Ruby; then Rust, TypeScript,
  PHP.
* C3. Codegen for PHP, Perl, shell, C#, Kotlin, Zig, Julia, R; an expression-only lowering for Haskell and OCaml.

### Phase D: every pair verified

* D1. The stdin harness (one template per language: `read_int`, `read_float`, `read_bool`, then `read_str`).
* D2. A pair matrix: every frontend × every target on a shared corpus written once in the card language and
  hand-ported to each source language, results as cards.
* D3. Round-trip by semantic hash: lift(emit_B(f)) canonicalises to the same term as f.
* D4. Translation-gap cards become computed: every construct a pair cannot carry, with its residual factor
  (GOALS.md §4).

### Phase E: optimize from truth

* E1. The e-graph in `improve` and in emission: extract the cheapest term under measured costs, certificate
  attached.
* E2. Per-function × language × host costs; `cheapest(lang=...)` answers "which target should this run in".
* E3. The native path: an improved Python module calls the C or Rust form through ctypes inside its witnessed
  domain, Python as fallback.
* E4. More algorithm cards (sorting and searching once lists exist, matrix kernels, DP recurrences → matrix power).

### Phase F: understand binaries and new targets

* F1. Symbolic execution of the instruction cards (MATH_CORE F5, G_M6), then of lifted code; semantic-hash
  library and instant lookup.
* F2. ISA cards for x86-64, ARM64 and RISC-V, Wasm as an output language.
* F3. Platform cards per OS (a shell and a bundle layout each).

### Phase G: the universal Gödel model

* G1. The prime ledger (append-only, tested against git history).
* G2. Homomorphism cards: language → IR and IR → language as maps with the product law checked and the GCD
  condition computed; the translation gap as the residual factor.
* G3. The physics set: SI base units as primes, dimensional analysis as a witness.

### Phase H (later): the math language designs and optimizes languages

Recorded 2026-11-04, to be done after the phases above. In the user's words: *the math language should also be able
to design and optimize any card model language, so language → math/systems logic system → optimization → output
language / language package / binary, depending on the desired output.*

So far, languages are inputs and outputs that the model translates between. The math language
([MATH_LANGUAGE.md](MATH_LANGUAGE.md)) already reads equations in and emits every codegen language. In this phase it
becomes, together with the card language and the core terms of MATH_CORE §4, the hub that a language is *made* from:

* H1. **A language as a math object.** A language card's grammar, types, operational semantics and codegen are
  described as terms in the math language, with laws (type soundness, determinism, evaluation order) as theorem
  cards. The 23 existing language cards are the first corpus.
* H2. **The pipeline as one path.** Source language → core terms (math / systems logic) → optimization (e-graph,
  measured costs, Phase E) → the output the user asks for: source in another language, a **language package**
  (a language's own toolchain artifacts: a frontend, codegen, runtime library and tests generated from its card),
  or a **binary** for a platform card (Phase F).
* H3. **Designing a language.** Given goals (target platform, performance, safety properties, the domain's
  operations), the model proposes a language card: syntax, types and ops chosen from the math, with its laws
  witnessed and its codegen conformance-checked like any other language card.
* H4. **Optimizing a language.** Measure an existing language card (emitted code cost, lift rate, gaps per
  construct) and propose changes to its ops, types or lowering, each with a certificate that existing programs
  keep their meaning.
* H5. **Self-application.** The card language itself is optimized by the same pipeline, and the change reaches
  main as a PR with its evidence (§7).

Precondition: Phases B–E (a wide IR, frontends, the pair matrix and optimization from truth), since a generated
language is only as good as the core it is built from.

### Phase I: everything runs natively on the target device

Recorded 2026-11-04. In the user's words: *no program should ever rely on a program outside the device. If the
arcade runs one of the games, it can't run a secondary program to run it: it must run the whole program and the
software it requires natively, purely in cards, all contained in the one full card model structure. The arcade
runs things in the emulator, which keeps it from running on an iPad, since the whole program doesn't run
natively.*

The goal: a program the model ships is **one native binary for its target device**. Its logic, data, the machine it
needs and its shell are all compiled from cards. At run time it starts no helper process, compiles nothing, needs
no service on localhost, no interpreter of another CPU, no browser and no Python. The only thing outside the cards
is the device's own operating system, reached through the platform card's boundary cards (CM21, CM34). An iPad
allows exactly this, and nothing more, so the iPad is the test.

**Audit: what a shipped program depends on today** (from `cards/platform/macos`, `cards/app/arcade`,
`cardmodel/arcade/`, docs/ARCADE.md):

| dependency | used by | when | why an iPad can't use it | what replaces it |
|---|---|---|---|---|
| the Python `cardmodel arcade serve` service on 127.0.0.1:8770 | the launcher (catalog, builds, depots, pages) | run time | no Python, no background local server | the launcher's logic in the card language, compiled into the app; the catalogue and depots as card data shipped with it or fetched over HTTPS |
| the launcher's pages run by WebKit (`WKWebView`, HTML/JS in `cards/app/arcade/ui`) | the launcher UI | run time | WebKit exists, but the UI is code the cards don't describe | UI as cards drawn by the same software renderer the games use (or a declared boundary card for native widgets) |
| hand-written Swift shells (`GameShell.swift`, `Launcher.swift`) with AppKit, AVFoundation, GameController | every game and the launcher | build + run | AppKit is macOS only | a platform card per OS whose shell is generated from boundary cards (window, audio, input, files, clock), with UIKit on iPadOS |
| the Game Boy Player's interpreter of the LR35902 cards | every cartridge played from the library | run time | it runs (it's compiled cards), but it's emulation, not the program itself | ahead-of-time lifting of the whole cartridge (`arcade app`, already at 100 % for Pokemon Crystal) for every shipped cartridge, with the interpreter kept only as the witness |
| `relift` after quitting (background build of what the interpreter ran) | cartridge apps | run time | needs `cc` on the device; iOS forbids generating code | all lifting before shipping, on the build host; a cartridge isn't shipped until a walk shows purity 1.0 |
| the C compiler (`cc`/`clang`, the C card → `game.dylib`) | every build | build time | not on the device | the model's own backend: IR → ARM64/x86-64 through ISA cards, plus a Mach-O/ELF writer as cards (Phase F2) |
| `swiftc`, `iconutil`, the linker's ad hoc signing | every macOS build | build time | not on the device | the generated shell (above); icons and bundles written by the model; signing stays the platform's own step |
| `git` and worktrees (branch versions, Work tab) | the launcher | run time | no git on the device | branch builds made on the build host and served as depots like any version |
| the browser page of `cardmodel emu` | the emulator front end | run time | a second program | the arcade's native player |
| Python 3 running `cardmodel` itself | the model | build + run of the model | no Python | self-hosting: the kernel's own logic as cards, emitted to a native binary (I6) |

Toolchains for verification (go, rustc, javac, node, ruby, lua, lean, z3, clang for the Unreal scan) are
different: they're the witnesses that check an emission against a real compiler, not part of any shipped program,
and they stay optional (CM01, probed and never required).

**Milestones:**

* I1. A platform card for iPadOS/iOS (UIKit shell, touch and controllers, the app sandbox's files), checked by
  building Vector Duel for it. (An iPhone/iPad platform is being built in its own session, docs/ARCADE.md §7.)
* I2. Shells generated from boundary cards instead of hand-written Swift, one per platform card.
* I3. The launcher without the service: catalogue, install, verify and play in the card language inside the app;
  the service remains only as the build host's publisher.
* I4. Ship only fully lifted programs: every cartridge app reaches purity 1.0 on a walk its profile didn't see
  before it is packed; no `relift` on the device.
* I5. The model's own native backend (IR → machine code → a loadable binary), so a build needs no `cc`; the C card
  stays as a witness.
* I6. Self-hosting: the kernel, store and runtime parts of CardModel itself expressed in cards and emitted, so the
  model runs on a device with no Python.

Honest limit: the device's OS (window system, audio, input, file system, network) is always outside the cards.
It's reached only through boundary cards, which is what "natively" can mean on a real device.

### Phase J: understand a program the REA way, in the math language

Recorded 2026-11-04. In the user's words: bring the REA way of understanding (rea-cards: facts with provenance,
witnessed flaws, refuse rather than guess, name the first diverging input) into the math language as a structural
analyser that models a program's structure and interaction semantics, checks its logic and math, and detects and
explains behaviour differences across languages, optimization levels and device runners. A latent flaw in the
original code that only shows up after translating or optimizing (integer division, overflow, float or NaN
handling, timing) must be *defined* by the math model and caught, never silently introduced.

The principle: the IR's reference semantics is the program's mathematics (ℤ, binary64, partial ops undefined off
their domain). Every target language, optimization level and device runner is a model of that mathematics that
agrees with it on part of the domain only. The analyser states that part as math and witnesses its edge.

* J1 🔵 (2026-11-04, `cardmodel analyse`, [ANALYSE.md](ANALYSE.md)). Structure facts with provenance (signature
  in math notation, calls, recursion none/tail/general/mutual, loops, partial ops, effects); logic obligations
  for every partial op under its path condition (proved by a guard, implied by the declared domain, sampled, or
  open with the counterexample); 12 divergence laws (`int_width`, `int_div_zero`, `float_div_zero`,
  `float_exception`, `float_to_int`, `shift_count`, `int_pow_negative`, `nan_result`, `deep_recursion`,
  `step_budget`, `eval_order`, `float_assoc`) fired by an instrumented reference on boundary and in-domain
  inputs; every firing run in every available runner, including optimization and checking variants (C at
  -O0/-O2/-ffast-math/UBSan, Rust debug/release, Swift -Onone/-Ounchecked). `cardmodel matrix` failures name the
  law that fires at their first input.
* J2. Laws as cards (`cards/divergence_law/<id>`): the condition in the math language, the per-runner models
  as data, and each runner's prediction checked against its witness (a law whose prediction a runner contradicts
  is itself a flaw, as rea-cards' `re_flaw` cards are).
* J3. Fixed-width semantics as math: BV(w) (MATH_CORE F3) so `int_width` is decided, not sampled: interval
  analysis over the IR proves the domain on which every intermediate fits, and the analyser emits it as a
  `requires` the user can adopt.
* J4. Device runners (with Phase I): the same function run on the iPad/iOS platform card, on ARM64 and x86-64,
  and through the model's own backend (I5), so a difference between devices (division by zero is a trap on x86-64
  and a silent 0 on ARM64) is witnessed per device, not predicted.
* J5. Interaction semantics: effects (globals, arrays, I/O at the boundary cards) as a trace model, so two
  programs that agree on values but differ in the order or number of effects are told apart; event and timing
  models for the arcade's machines. ([SCALING.md](SCALING.md) §4.7's interaction model is what the model itself can
  reach; J5 is what a program does at its boundary.)
* J6. The analyser on itself and on the self-run: every function the cycle adopts carries its analysis, and a
  latent flaw blocks adoption until the domain is declared or the code is changed (Phase A5's PRs carry it).

## 6. Workstreams running now and what each owns

Four sessions work in parallel from this plan. Each owns its files (docs/INTEGRATION.md rule: one owner per file
area) and lands through a PR into main.

| workstream | phases | owns | must not change without coordinating |
|---|---|---|---|
| Lift every language | B, C | `engines/frontend_*.py`, new frontends, `cards/language/*/frontend`, the new IR types in `engines/ir.py` | codegen templates (coordinate with verification) |
| Verify all language pairs | D, A3 | `engines/conformance.py`, `engines/translate.py`, `engines/runners.py`, the stdin harness templates in `cards/language/*/codegen` | the IR's types (owned by lifting) |
| Optimization gaps | E | `engines/improve.py`, `engines/egraph.py`, `engines/optimize.py`, `engines/rewrite.py`, algorithm and metric cards | the frontend |
| Understand the REA way | J | `engines/analyse.py`, `docs/ANALYSE.md`, `tests/test_analyse.py`, the explanation hook in `engines/matrix.py` | runner semantics (`engines/runners.py`, owned by verification) |
| Run fully in the cloud | A | `.github/workflows/`, `kernel/resources.py`, `engines/selfcheck.py`, `engines/selfrun.py` cloud scheduling, the `re_operation` vectors, the environment setup script | verify section semantics |

Shared rules for all four:

* `engines/ir.py` is the contract between lifting, verification and optimization. A new type or statement lands in
  one PR that also adds its op cards, its templates in every codegen language and its conformance cells, so no
  target is ever left unable to emit a valid IR program.
* New laws and goals take numbers from the registry (docs/INTEGRATION.md §2) at merge time, not before.
* No goal floor is lowered; a goal that becomes measurable for the first time records its floor with
  `cardmodel docs`.
* Every PR runs `verify --quick` and the unit tests on Linux once Phase A's CI exists; until then, run them locally
  in the session and paste the summary in the PR.

## 7. What "fully autonomous" means here, and its limits

* The model may find, rank, fix and propose on its own. It reaches main through the same gate as code: a PR with
  the evidence, merged by the user. That gate is how the model already integrates parallel work (docs/INTEGRATION.md, CM39), not a temporary restriction.
* Equivalence of programs is undecidable in general. The model promises three things only: *instant* (a known
  semantic hash), *decided* (bounded bit-vectors, linear recurrences, Presburger) and *search* (e-graph, SMT,
  Lean within a budget). A search can end in "not found", never in a guessed "equal" (MATH_CORE §7).
* Effects (I/O, network, time, randomness) are never translated by guess. They stay in the effect shell, byte-
  identical, and a language pair carries them only through boundary cards.
* Everything the model claims carries its tier (CM46) and traces to a truth (CM44).
