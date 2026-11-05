# GENERAL_COMPILER: one compiler for anything computational, learned from the languages themselves

**Status: goals adopted by the owner (2026-11-05): G_C6–G_C8; the doors' order and the remaining goals are proposals.** Nothing here is built unless it names an existing command or card.
It answers the owner's request of 2026-11-05: replace the non-goal "a general compiler for arbitrary Python" with
a goal for *a general compiler for arbitrary programming languages, drivers and anything computational*, so the
model can be optimized for its most efficient practical use. It builds on TARGETS.md §4 (the six product targets),
UNIVERSAL_UNDERSTANDER.md (what "understanding" a framework means) and IR_TYPES_OPTIONS.md (the IR's next sorts).

## 1. The principle: learn the language, never the function

A function is a term over its language's constructs. The meaning of a term is computed construct by construct
(FOUNDATIONS D3/D4: the model is a Σ-algebra and evaluation is the unique homomorphism from the term algebra), so
**if every construct agrees with the language's own implementation, every function built from them agrees too.**
Correctness is witnessed per construct (against the real compiler or interpreter, on generated inputs), not per
function. When something breaks, the failure names one construct, and fixing it fixes every function that uses
it. This is the "fix 1 or 10 problems instead of defining 13,000 functions" property.

The measurement already shows it (lift-sweep over the Python 3.14 stdlib, main 6920ac6): 223 of 13,300 functions
lift, and three constructs (`self`/records 7,693, non-numeric defaults 741, varargs/keyword-only 520) block about
two thirds of the rest. Coverage grows by closing constructs, ranked by how many functions each one blocks.

What is *not* possible, stated so no goal overclaims: running and translating any program faithfully is
achievable (an interpreter is exactly that); deciding every semantic property of arbitrary code is not (Rice's
theorem). So "understood" stays tiered (CM46): **lifted** (runs as cards, exact) → **witnessed** → **proved** →
**canonical**. Code that reflects on itself (`eval`, attributes by computed name, monkeypatching), foreign code
and I/O stay **opaque boundaries** (#52), named and witnessed by running the real thing, never guessed.

## 2. The core: learn programming once, then each language is a map into it

Programming languages differ in surface, not in kind. Every mainstream language has been given a small **core
calculus** that its full semantics desugars into: Python into λπ (Politz et al., "Python: The Full Monty", 2013),
JavaScript into λJS (Guha et al., "The Essence of JavaScript", 2010), Haskell into GHC Core, Racket into a dozen
fully-expanded forms; and SSA, the form of LLVM IR and of this model's IR, is a first-order functional language
(Appel, "SSA is Functional Programming", 1998). Whole languages (C, Java, Python, JavaScript) have also been
defined executably in one framework, the K Framework, from one shared set of semantic building blocks.

So the model can learn **the core once**, as cards, and treat each language as a **carry map** into it (the
same kind of map #53 already uses to make a language a carry map out of the IR). The core, with what the model
already has:

| # | core construct | covers in languages | in the model today |
|---|---|---|---|
| 1 | values of sorts: Int, BV(w), Float(w), Bool | every literal and arithmetic op | **yes**: core_type Int, Nat, BV, Float, Bool; op cards; fixed widths (#61) |
| 2 | names and binding (`let`, assignment as rebinding) | variables, SSA values | **yes**: the IR |
| 3 | first-order functions, calls, recursion | functions, procedures, methods without dispatch | **yes** |
| 4 | branch, and loops as fixpoints | `if`, `while`, `for`, `goto` in structured form | **yes**; closed forms by the function algebra |
| 5 | memory: addresses, load, store over an array sort | pointers, arrays, mutable objects, the heap | **partly**: core_type Array; the ARM memory model (#78); list[int]/list[float] |
| 6 | products and sums: tuples, records, variants | structs, classes' fields, enums, `None`/Option, tagged unions | **partly**: core_type Tuple; strings (#69); no records or variants |
| 7 | functions as values: closures | lambdas, callbacks, objects (a record of closures), virtual/dynamic dispatch, iterators | **no** |
| 8 | control as effects: one handler construct (Plotkin & Pretnar's effect handlers) | exceptions, `return`/`break` from inside, generators/`yield`, `async`/`await`, early exit | **no** (break/continue only) |
| 9 | effects at the boundary: I/O, clock, syscalls, MMIO | files, network, drivers' registers | **the principle** (CM21, CM34) and the arcade's effect shell |
| 10 | concurrency: threads, atomics, interrupts | threads, async runtimes, drivers, the DS's two CPUs | **no** |

Five of ten are in, two are half in; **three new constructs (records/variants, closures, effect handlers) plus
finishing memory would make the core complete for sequential programs.** Every language feature that blocks the
stdlib today reduces to one of them: `self` is a record in memory (5, 6), non-numeric defaults are values of
sorts the core lacks (6), varargs and keyword-only parameters are records of arguments (6), `raise`/`try` are
handlers (8), nested defs are closures (7).

**How a language is then learned "natively", without per-function definitions:**

1. *The language's own toolchain is the oracle.* A construct's map into the core is proposed (from the grammar
   card, or from what the language's compiler emits for it) and witnessed by running generated programs through
   the real compiler or interpreter and through the core (differential, seeded; tier `sample`, raised to `proof`
   where the map is checked symbolically).
2. *A map that witnesses joins the language card;* one that fails names the construct and its first input. A
   language is covered when its constructs are, and every function in it lifts by composition (§1).
3. *Compiled forms are pre-desugared.* A compiler has already reduced a language to an instruction set (LLVM IR,
   CPython bytecode, WASM, a CPU's ISA). Learning that set's map into the core once covers every language that
   compiles to it (§3's doors), which is why the doors are the cheapest way to fill the core with languages.

This changes the plan's order: **the core first (constructs 5–8), then the doors that fill it** (§8).

## 3. The doors: where code comes in

A general compiler needs one IR in the middle and as few doors in as possible, each a **finite instruction set
distilled from its specification as cards** (the way `isa/armv5te` and `isa/lr35902` already are). Each door
below is graded by what it reaches, its size, and what the model already has.

| door | reaches | size of the set | have today | missing |
|---|---|---|---|---|
| **S. Source frontends** (today's route) | 18 languages through `frontend_text` + Python's AST | grammar per language, unbounded constructs | the 12×18 matrix, round trips 715/715 | every construct by hand; low real-code rates (1.68 % stdlib) |
| **L. LLVM IR** | C, C++, Rust, Swift, Zig, Julia, (Haskell, Kotlin/Native): most compiled code, **and most drivers** (C) | ~68 instructions, a small type system, explicit memory | clang 21, LLVM 21/23 on this Mac; the Unreal clang reader | a memory sort, pointers, structs, calls through pointers |
| **V. VM bytecode** | CPython (154 opcodes in 3.14), JVM (~200, Java/Kotlin/Scala), .NET CIL (~220, C#/F#), WASM (~200, anything that targets the web) | one set per VM | the ISA pipeline (cards → IR → symbolic terms → bench) | a heap of objects (dicts, attributes, dispatch); exceptions |
| **M. Machine code** | anything that runs, with or without source: binaries, firmware, drivers, ROMs | ARM64 ~1,000 encodings, x86-64 many more; ARMv5 and LR35902 done | ARMv5TE 167/167, LR35902 512/512, the memory model (#78), loop unrolling (#79), the ROM lifter | ARM64 and x86-64 cards; recovering structure (loops, calls, types) from flat code |

The doors are complementary, not competing: **L** is the widest single door for compiled code and for drivers;
**V** is the only faithful door for dynamic languages (Python's meaning *is* its bytecode plus its object model);
**M** is the floor that catches everything else, including code with no source. **S** stays for readability,
round trips and teaching, but stops being the route coverage depends on.

## 4. The exits: where code goes out

| exit | today | for |
|---|---|---|
| source in 12 languages (codegen cards) | done, witnessed | translation, readable output |
| C card → native library | done (the arcade's games and players) | native speed on any platform with a C compiler |
| ISA cards + a binary writer (Mach-O/ELF) | planned (TARGETS I5, F2) | no outside compiler at all: Phase I, the iPad as one binary |
| GPU (SPIR-V/Metal) | cells run in ENVIRONMENTS | numeric kernels |

## 5. The shared core every door needs (the same list as §2, as IR sorts)

Whatever door is chosen first, the IR needs the same missing sorts, in this order (IR_TYPES_OPTIONS.md):

1. **memory and pointers** (an array sort with load/store, which #78 began for ARM): needed by L, V and M;
2. **records/structs and tuples**: L's structs, V's objects, Python's `self` (the largest blocker);
3. **calls through values** (function pointers, virtual dispatch, closures);
4. **exceptions / unwinding** (CPython's exception table, C++'s landing pads);
5. **effects as boundary cards** (I/O, clocks, syscalls, MMIO for drivers);
6. **concurrency** (threads, interrupts; the DS's two CPUs; drivers).

Each is one construct family, witnessed once, and unblocks every door at the same time.

## 6. Candidate goals (each computed by the model, none typed in)

**Adopted:** G_C6_core_forms (the core constructs the IR has, of the ten `core_form` cards, target 10), G_C7_stdlib_lift and G_C8_doors_witnessed, computed in `engines/compiler_goals.py`. The other rows are proposals.

| id (proposed) | axis | metric | target | measured today |
|---|---|---|---|---|
| door coverage → **G_C8_doors_witnessed** (adopted, counted per door) | compiler | per door: fraction of its instruction set with a card whose semantics is witnessed against the real implementation | ≥ 0.95 per adopted door | M: ARMv5TE 1.0, LR35902 1.0; L, V: 0 |
| corpus lift → **G_C7_stdlib_lift** (adopted, on the Python stdlib first) | compiler | fraction of functions in reference corpora that lift with no gap (the stdlib of each language, the user's projects, one driver tree) | ≥ 0.9 | Python stdlib 0.0121 closed, 0.0168 lifted |
| fix leverage (proposed) | compiler | functions unblocked per construct fixed, from the sweep's histogram before and after | reported per fix | — |
| round trip (proposed) | compiler | lift → emit → run agrees with the source's own toolchain, per door × exit | = 1.0 on every lifted function | 715/715 (S) |
| native exit (proposed) | compiler | shipped programs that run with no outside program (Phase I audit rows at zero) | all catalogue items | 0 (the C card's compiler is outside) |
| certified optimization (proposed) | optimization | speedup with a certificate (a proof or tiered witness that the optimized term means the source term) on lifted real code, per door | ≥ 1.0 always, median reported | on the IR subset only |

Corpus lift (G_C7) is the one that answers "can it compile anything": the others say why it can or cannot yet. The non-goal
line in GOALS.md would become: *"Not a goal: understanding without evidence. Every lifted function is witnessed
against its own toolchain; code that reflects on itself stays an opaque boundary."*

## 7. The options, ranked by practical value

| option | first door | reaches first | effort (rough) | why choose it | risk |
|---|---|---|---|---|---|
| **1. LLVM IR first** | L | C, C++, Rust, Swift, Zig, Julia, drivers | medium: 68 instructions, but memory and structs first | one door, the widest reach; drivers and engines (Unreal, AnyPS5's C) come with it; LLVM is installed | IR from `-O0` is verbose; recovering high-level structure needs the e-graph |
| **2. CPython bytecode first** | V | all of Python, the model's own code (self-hosting) | medium-large: 154 opcodes and the object model | your own language, the model's own source, the stdlib corpus already measured | the object model is the hard part; dynamic features stay opaque |
| **3. Machine code first (ARM64/x86-64)** | M | every binary on the Mac, the iPad's own ISA | large: ARM64 is ~1,000 encodings | the pipeline exists and is proven twice; also gives the native exit (Phase I) | structure recovery from flat code; scale |
| **4. Source frontends, construct by construct** | S | Python first, then the other 17 | small per step, unbounded in total | fastest visible gain on the current numbers (records → defaults → varargs) | stays per language and per construct: the route the owner wants to leave |
| **5. WASM first** | V | anything compiled to the web; a small, formally specified set | small-medium | the cleanest spec, already a mechanized semantics exists; a portable exit too | few real programs ship as WASM on this Mac |

**Recommendation (a judgement, not a measurement):** **Option 1 (LLVM IR) as the first door, built on the shared
core of §2, with option 4's first step (records) done in passing because the core needs records anyway.** LLVM IR
gives the widest reach per instruction learned (most compiled languages and most drivers through one set), the
toolchain is already on this Mac, and its explicit memory model is the same memory sort that M (machine code)
and V (bytecode) need next. Then **V (CPython bytecode)**, which reuses the memory and record sorts and brings
Python and the model's own code; then **M (ARM64)**, which closes Phase I on the iPad with the binary-writer exit.

## 8. The plan

Each phase ends with a measured number, not a claim.

| phase | work | exit measurement |
|---|---|---|
| 0 | **done 2026-11-05**: the owner adopted the goals; GOALS.md lists G_C6–G_C8 and the non-goal is replaced; `core_form` cards (tools/seed_core_forms.py) | G_C6 = 5 of 10, G_C7 = 0.0121 (161 of 13,300), G_C8 = 2 (ARMv5TE, LR35902) |
| 1 | the core (§2), constructs 5–8: finish memory, add records/variants, closures and one effect-handler construct, each a core_type or op family witnessed against M and Lean where it can be | a `core_form` registry at 10/10 sequential constructs with witnesses; the Python stdlib sweep's top blockers shrink |
| 2 | door L: `llvm_ir` as an instruction-set registry like `isa/*` (cards distilled from the LangRef and witnessed against `lli`/clang on generated inputs); a reader from `clang -S -emit-llvm` | G_C1(L) ≥ 0.95; G_C2 on a C corpus (a small libc subset, one driver tree) |
| 3 | the e-graph lifts structure out of LLVM IR (loops, calls, canonical forms) so `-O0` and `-O2` output canonize alike | canonical identity rate on the C corpus |
| 4 | language maps learned against their toolchains (§2 steps 1–2) for the source languages the doors do not cover well (Python source, JS, Lua, Ruby) | per-language construct coverage; G_C2 on their standard libraries |
| 5 | door V: CPython bytecode registry + object model on the memory/record sorts | G_C1(V, CPython) ≥ 0.95; G_C2 on the stdlib ≥ 0.5 |
| 6 | door M: ARM64 cards (generated from the architecture's machine-readable spec, as `tools/gen_armv5te.py` does) and the Mach-O writer | G_C5: the arcade's games on the iPad with no outside compiler |
| 7 | optimization on lifted real code with certificates, chosen by measured cost on the environment card | G_C6 median speedup, per door |

What each phase leaves for the next is a sort or a registry, never per-function definitions.

## 9. Decisions that are the owner's

1. ~~Adopt the goals~~ adopted 2026-11-05 (G_C6–G_C8); the proposed rows of §6 remain open.
2. The first door: 1 (LLVM IR, recommended), 2 (CPython bytecode), 3 (machine code), or 5 (WASM).
3. The reference corpora G_C2 is measured on (proposed: each language's standard library, the user's projects
   under ~/Programmering, and one open driver tree).
