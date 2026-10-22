# A game engine's math as cards: Unreal Engine (law CM49)

The card model reads Unreal Engine's math, understands every function as mathematics, and keeps it as cards:
what each function computes (a definition: truth), the engine's own code for it (an action, linked by a witness),
the identities between functions (transformations), and what the math is for (uses). Every function is an atom of
the engine's Gödel set, carried to the Gödel content of its definition over the model's basis. Everything lifted
from the engine's source stays on this machine (section 5); `cardmodel unreal cover` prints the live numbers, and this
page says how it works.

```bash
./bin/cardmodel unreal locate
```

```bash
./bin/cardmodel unreal scan --save
```

```bash
./bin/cardmodel unreal show FVector.CrossProduct
```

```bash
./bin/cardmodel unreal uses
```

```bash
./bin/cardmodel unreal gcd "FQuat.operator*" "FVector.CrossProduct"
```

```bash
./bin/cardmodel verify --only unreal
```

## 1. The pipeline

| step | module | what it does |
|---|---|---|
| find the engine | `unreal/engine.py` | `--engine PATH`, `CARDMODEL_UNREAL`, or the Epic launcher's own record of what it installed (`LauncherInstalled.dat`); the version from `Engine/Build/Build.version`. Nothing in the install is written. |
| two builds | `unreal/engine.py` | **truth**: the engine's scalar path (vector intrinsics off, so its SIMD registers read as the engine's own FPU fallback, `UnrealMathFPU.h`); **shipped**: as the engine runs on this Mac (NEON), with `-ffp-contract=off` as UnrealBuildTool compiles for Mac, plus the engine's Core library for what it compiles out of line. Checks and ensures are compiled out (diagnostics, not math). |
| units | `unreal/units.py` | one generated unit that includes every math header and instantiates every class template of `UE::Math` (double, or int32 for integer templates) and calls every function template of `FMath` and the platform math (what clang rejects is left out with clang's reason), plus the engine's own math `.cpp` files, each as the engine compiles it |
| frontend | `unreal/clangast.py` | the real compiler: `clang++ -Xclang -ast-dump=json` gives the typed AST (templates instantiated, macros expanded, overloads resolved); about a gigabyte per unit, read as a stream, keeping only the math files' declarations |
| lift | `unreal/lift.py` | symbolic execution of each function's AST into core terms (below) |
| scan | `unreal/scan.py` | every function with a body in the math files, written by the engine's programmers (not compiler-generated), concrete (an instantiation, not a template's pattern), identified by its mangled name; constants the `.cpp` files define (`FVector3d::ZeroVector`) are evaluated and shared; a call into another unit is resolved by inlining the callee's lifted term |
| distill | `unreal/distill.py`, `engines/realnorm.py` | the canonical form over the reals, the semantic hash, the Gödel content, the use, the identities, the carry map |
| witness | `unreal/witness.py` | the engine's code against every lifted term on seeded inputs |
| cards | `unreal/cards.py` | the packs below, and the engine's atoms appended to the prime ledger |

## 2. Lifting: a function as terms

A value is a list of scalar **slots**: a record is its slots in layout order (bases first, then fields; an array
expands; a union overlays its members, which must agree slot by slot, and a member read as other bits goes through
the bits atoms); a scalar is one slot of kind `f64`, `f32`, `b` or an integer kind. Memory is cells; a reference or
a pointer is a cell, an offset and a shape, so writes through references and out-parameters land where C++ puts
them.

* A condition that folds to a constant takes one side. A condition on the inputs runs both sides and merges every
  slot that differs as `IF_EXPR`; a `return` on one side makes the rest of the function conditional on not having
  returned. A loop runs while its condition folds (unrolled within a budget). A `switch` on the inputs becomes a
  chain of conditions.
* A call with a body is inlined; a call into another unit becomes the callee's term once both are lifted. A C
  library call is an **atom**: `FSQRT`, `SIN`, `COS`, `ATAN2`, `FLOOR`, `FMOD`, ... (`cards/op`, the Gödel set
  `analysis`). Bit-level code (`BitCast`, `memcpy` between floats and integers, reinterpreting casts) reads through
  `F32_BITS`, `BITS_F32`, `F64_BITS`, `BITS_F64` (the set `bits`).
* A read `A[i]` with `i` on the inputs is `IF_EXPR` over every element of the object `i` can name; an index outside
  it is undefined in C++ and leads to the leaf `<undefined: an index outside the object>`. A shift by a count on the
  inputs is guarded by the operand's width the same way (`<undefined: a shift count outside the operand's width>`).
  The witness never runs the engine's code there, and since any value refines undefined behaviour, emitted code
  takes the other side. A write through such an index is a gap (`array index`), and so is a read into a pointer
  parameter's array, whose length is the caller's.
* Conversions are explicit: double to float is `F32` (round to binary32), float to double is exact, int to float is
  `TO_FLOAT`, float to int is `TRUNC_INT`, unsigned arithmetic wraps (`BIT_AND` with the mask), C's truncating
  division and remainder are written over `FLOORDIV` and `MOD`. Arithmetic in `float` is done in double and rounded,
  which is exact for `+ - * /` and `sqrt`.
* A void call with no body that can write nothing of ours (a logging or error-report function) is an **effect** at
  the boundary, recorded on the card, never part of the value (CM21).
* What cannot be lifted is a **gap with its cause** (`unreal_cause` cards say what would close each one): a loop
  whose trip count depends on the inputs, a write through an index the inputs choose, type punning, bitfields, the C
  library's random state, a static, a term past the size budget, and the rest.

The **math universe** is every function over numbers: a function whose signature (or body) is about strings,
archives, names, memory images, type layouts, time, logging or tests is *outside* it, counted as such, not as a gap.
A function over containers (`TArray` of curve keys) is in the universe, and a gap (`container`) until the IR has
lists.

A write after a conditional `return` is itself conditional (`IF_EXPR(returned, old, new)`) only where it can be
seen once the frame has returned: the function's outputs and the caller's cells. A local is dead after the return,
so its writes stay plain; this keeps early-return code (the engine's `Atan2`, `GetSafeNormal`) from growing its
terms on every write.

## 3. The mathematics: canonical forms, identities, Gödel numbers

**Real view.** Over the reals `F32` and `TO_FLOAT` are the identity. **Canonical form** (`engines/realnorm.py`): a
polynomial with exact rational coefficients over atoms (variables, and every other operation applied to arguments
already in normal form); `ADD`, `SUB`, `NEG`, `MUL` expand and collect, division by a monomial is a negative exponent,
comparisons become `p REL 0` with `p` monic, odd and even functions take their sign out. Inputs are renamed by
position (`x0`, `x1`, ...), so the form belongs to the function, not to its parameter names. Equal canonical forms
mean equal functions wherever both are defined; this decides equality for the polynomial fragment with
uninterpreted atoms and is sound beyond it.

**Semantic hash** of the canonical outputs: the function's identity. Two engine functions with one hash are one
function (a static `DotProduct` and the member `operator|`; a float and a double instantiation); each class is a
chain of `transformation` cards.

**Gödel content** (CM43, CM45): the canonical outputs' operations with multiplicity, stored as the sparse vector over
ledger indices with the basis version it was read against (never as the product of primes, which only has its digit
count on the card); Gödel's positional tokens for small outputs. **GCD and LCM** of contents give the logic two
functions share and everything they need together (`cardmodel unreal gcd A B`); per use, the GCD of all members is
the use's common logic (`cardmodel unreal uses`).

**Gödel sets.** `analysis` and `bits` extend the basis B0 with the atoms above. `unreal` is the engine's own
vocabulary: every function of the math universe is an atom (appended to the ledger, never renumbered, CM43). The
**carry map** sends each lifted function's atom to its definition's content over B0, `analysis` and `bits`; a gap
has no image, and those atoms are the map's gap. A function's *named* content (the engine functions it calls) maps
through the carry to its computed content.

**Uses.** What a function is for is read from the engine's own organisation (its type: `TQuat` is rotation, `TBox`
bounds, `FLinearColor` color, ...) and, for `FMath`, its name (interpolation, trigonometry, geometry, rounding,
powers, bits, random, ...): `unreal_use` cards, one per use, with the members' GCD and LCM.

## 4. Evidence and tiers (CM46)

Every claim on a definition carries its tier:

| claim | tier | evidence |
|---|---|---|
| the term equals the engine's compiled code | sample | a harness compiled from the engine's headers with its shipped flags and linked to its Core library (access control opened by the preprocessor, so private members are set and read as the lift reads them) sets every input slot from seeded bits (the first two cases are edges: an unsigned value's maximum and its top bit), calls the function and prints every output's bits; the term is evaluated with IEEE semantics on the same bits, its C library atoms by the platform's own C library (a float call such as `acosf` by the float function: Apple's `acosf(-1)` is the float just below π, which flips the sign of `sin` in a slerp). Inputs where C++ is undefined are never run. Where the shipped (NEON) build is not bit-exact or cannot be compiled, the engine's scalar build decides, compiled from the headers and from every `.cpp` file the term reaches (out-of-line callees such as `TRotator::Quaternion` included, so none of it runs as the library's NEON code): a term that matches it is right, and the shipped distance (approximate reciprocal square roots, fused multiply-adds in the vector paths) is recorded as the engine's own. `witnessed`: bit-exact, or within a few ulps, the largest distance recorded. A planted wrong term is refuted (`tests/test_unreal.py`); the witness found a real lifter error this way (a same-width unsigned-to-signed conversion read as value-preserving). |
| the canonical outputs equal the lifted terms over the reals | proof, where every output is a polynomial | the difference has degree at most `d_v` in each variable `v`, so agreeing on the grid of `d_v + 1` values per variable in exact rationals proves it zero; outside the polynomial class it rests on the normal form's rules and says so (sample) |
| an identity between two functions | the weaker of the two members' canonical claims | equal semantic hashes |

## 5. The cards, and where they are kept

Terms lifted from Unreal Engine's source, and everything computed from them, stay on this machine
(docs/INTEGRATION.md rule 8, the user's "Keep UE-derived data local"): `cardmodel unreal scan --save` writes those
cards to the **local layer**, `state/local/cards` (untracked, like the rest of `state/`). Every store of this checkout
reads it, above the model layer; nothing writes it unless it names it. The tracked tree keeps what the rule allows:
the code, the registries and card types, the new C library atoms (generic, not the engine's), the engine's atoms in
the ledger (its function names) and their arities on the set card (from the signatures). Another checkout has the
registries and the ledger but no engine cards until it scans the engine itself.

| registry | layer | holds |
|---|---|---|
| `unreal_math` | local | every function read: qualified name, kind, type, file and line in the engine (relative to its root), use, status, inputs and outputs, atom and prime, witness verdict, the gap's cause |
| `definition` | local | truth for every lifted function the witness did not refute; terms past 600 nodes are kept in the cache with their hash and size |
| `action` | local | the engine's code, by its programmers (`method/human_written`), linked by the witness |
| `transformation` | local | identities |
| `unreal_use`, `unreal_cause` | local | uses (with their GCD and LCM), causes (with counts) |
| `godel` | model (tracked) | the engine's atoms (set `unreal`: names) and the new op atoms (`analysis`, `bits`) |
| `godel_set` | model (tracked) | the sets `analysis`, `bits` and `unreal`, each with its numbering; `unreal` with each atom's arity |
| `op` | model (tracked) | the new atoms, each with its reference semantics and a template per language card, checked by the conformance matrix like every op |

## 6. Honest limits

* The witness samples; it is not a proof that the engine computes the term everywhere. The proof tier covers the
  canonical form of polynomial functions, not the floating-point code.
* The universe is what the units instantiate: class templates for one type each (double, or int32), function
  templates for double; float instantiations appear where the engine's own code uses them.
* A unit clang cannot dump (Apple clang's JSON dumper crashes on some units now and then; a crash is retried) is
  reported, and its functions are read from the other units where they are visible.
* Signed integer overflow is undefined in C++ and assumed absent; a union read as other bits of the same width goes
  through the bits atoms, other punning is a gap.
* The harness opens access control with `#define private public` after the standard headers; a class whose layout
  changes with its members' access (tail padding of a non-POD base) would be read wrongly there, and the witness would
  refute it rather than pass it.
* The derived cards come from Epic's source code under the Unreal Engine EULA: they stay in this repository, which is
  never published (CM19).

## 7. Extending it

* A gap's cause names what closes it (`unreal_cause` cards; `cardmodel unreal cover`). Most are lifter work in
  `unreal/lift.py`; a new atom is an entry in `unreal/atoms.py`, then `python3 -B tools/seed_unreal.py` (op card,
  ledger) and `cardmodel unreal scan --reuse --save`.
* Another engine version: `cardmodel unreal scan --engine PATH --save` (its atoms append; nothing is renumbered).
* Another C++ code base: `unreal/scan.py::lift_source` lifts any header or source file with any flags; the
  witness takes any `witness.Target` (includes, flags, link arguments). `examples/engine_math/mini_math.h` is the
  fixture the tests and the capability check run on without an engine.
