# IR types after the numbers: design options

**Status: proposal for the foundations stream.** Nothing here is merged behaviour. It sets out options for
FOUNDATIONS §7 item 5 (MATH_CORE phase 2): tuples, Option/None, records, `raise`, truthiness and strings. It
builds on two open PRs: #61 (fixed-width ints and f32 as IR types) and #69 (`str` as a sequence of Unicode code
points, 11 op cards). Every option below obeys A1 (a new operation is an op card), A2 (M is the only meaning),
A3 (laws are sorted) and A6 (a target's difference from M is a divergence law, not a codegen patch).

## 0. What each feature must state

For every feature and option this document gives:

* **Σ**: the new sorts (D1) and op cards with their ranks (D2), or the new special form if laziness or control
  needs one (D2 lists AND, OR, IF_EXPR, CALL, LOAD as the only special forms today; adding one is a change to D2).
* **M**: how the model evaluates it (D4), and where it is partial.
* **Emit**, by family: C-like (C, C++, Go, C#, Swift), JVM (Java, Kotlin), JS (JavaScript, TypeScript), Rust, Lua,
  Lean. Python and Ruby emit like JS unless noted.
* **Witness**: the conformance cells (`engines/conformance.py`) that show M_L = M on the domain (D14).
* **Gödel**: the new atoms. Each must be **proposed to the ledger writer** and takes a prime forever (D11, CM43).
  This document only proposes; it never assigns primes.
* **Blockers removed**, from the counts in [TRANSLATE_REAL_PROGRAMS.md](TRANSLATE_REAL_PROGRAMS.md): 3,863
  non-numeric annotations, 954 non-numeric defaults / `*args`, 343 string/None constants, 243 tuple targets, 217
  `raise`, 146 + 65 truthiness. A sample of 149 standard-library functions had instance state in about 65.

## 1. Truthiness

Python's `if n:` and `not x` on numbers. No new sort is needed.

| option | Σ | M | notes |
|---|---|---|---|
| **T1. Desugar in the frontend** (recommended) | none: `if n` lifts to `NE(n, 0)`, `if x` on float to `NE(x, 0.0)`, on a list to `GT(LEN(xs), 0)`, on `str` to `GT(STRLEN(s), 0)` | existing ops | the frontend needs the sort of the scrutinee, which it has after typing |
| T2. A TRUTHY op card per sort | `TRUTHY: [int,bool] [float,bool] [list[int],bool] …` | `eval` per rank | one more atom; a law `truthy_int: TRUTHY(n) = NE(n,0)` makes it removable anyway |

* **Emit:** T1 emits through existing NE/GT templates in every family; Lua and JS no longer meet their own
  truthiness (Lua treats 0 as true, JS treats NaN as false), which is exactly why T1 is safer: target truthiness
  never appears.
* **Witness:** existing NE cells. Add one cell per family on `NaN` and `-0.0` (Python: `bool(-0.0)` is False,
  `bool(nan)` is True; `NE(nan, 0.0)` is true in IEEE, so T1 matches).
* **Gödel:** T1 none; T2 one atom.
* **Blockers:** 146 + 65.

## 2. Tuples

| option | Σ | M | notes |
|---|---|---|---|
| **U1. Product sorts, structural** (recommended) | a sort constructor `tuple[s₁,…,sₙ]`; op cards TUPLE (rank `[s₁,…,sₙ, tuple[s₁…sₙ]]`, one rank schema per arity) and PROJ_i (`[tuple[…], sᵢ]`, index a literal) | Python tuple; total | laws `proj_i(tuple(x₁…xₙ)) = xᵢ` and surjective pairing; tuple targets `a, b = f()` lift to two PROJ |
| U2. Scalar replacement only | no sort: the frontend flattens tuple returns into several out-parameters and tuple targets into several variables | no change to M | cheaper, but a function returning a tuple is no longer one term; breaks D3's "one function, one term" for those functions |
| U3. Tuples as records | a tuple is an anonymous record (§4 R1) with fields `_0.._n` | as records | unifies with §4, at the cost of waiting for it |

* **Emit (U1):** C-like: a generated `struct` per distinct tuple sort (C, C++ `std::tuple` or struct, Go a struct,
  C# `ValueTuple`, Swift native tuples). JVM: a generated `record` (Java 16+) or `final class`. JS: a frozen array.
  Rust: native tuples. Lua: a table `{a, b}` with 1-based PROJ (`t[i+1]`), a template detail, not a divergence.
  Lean: `Prod` nested right (`a × b × c`), PROJ as `.1`, `.2.1`, ….
* **Witness:** cells returning a pair and a triple of mixed sorts (int, float, bool), and a swap `(b, a)`;
  comparison is component-wise, so the matrix's equality on results must learn product sorts.
* **Gödel:** the constructor `tuple` (a type atom) and the two op schemas TUPLE, PROJ. Propose them as schemas
  parameterised by arity and index, so the ledger does not take a prime per arity; the parameter is a literal in
  the term, as WRAPU's width is today.
* **Blockers:** 243 tuple targets, the tuple share of the 3,863 annotations, and multi-value returns generally.
  `*args` (part of the 954) becomes a homogeneous `list[s]` or a tuple of fixed arity at each call site.

## 3. Option / None

| option | Σ | M | notes |
|---|---|---|---|
| **O1. Sum sort `option[s]`** (recommended) | NONE (`[option[s]]`), SOME (`[s, option[s]]`), IS_NONE (`[option[s], bool]`), UNWRAP (`[option[s], s]`, partial: domain `not IS_NONE`) | Python `None` / the value | `x if x is not None else d` lifts to IF_EXPR(IS_NONE…); laws `unwrap(some(x)) = x`, `is_none(none) = true` |
| O2. Sentinel per sort | `None` for `int` lifts to a chosen value plus a flag variable | no new sort | fails when every value of s is legal; violates "a term means one thing" |
| O3. General sums | `sum[s₁,…,sₙ]` with INJ_i / CASE | a tagged value | covers Option and `Union[int, str]`; CASE is lazy, so it is a **new special form** (D2) |

* **Emit (O1):** C-like: C a `struct {bool some; s v;}`, C++ `std::optional`, Go a pointer or `(v, ok)`, C# `s?`,
  Swift `s?`. JVM: `Optional<S>` (or a nullable boxed type; boxing costs, not meaning). JS: `null`. Rust:
  `Option<S>`. Lua: `nil` (a table field set to `nil` vanishes, so `option` inside a list needs a sentinel table:
  a declared divergence law, not a patch). Lean: `Option s`, UNWRAP as `Option.get!` or with the domain as a
  hypothesis.
* **Witness:** cells for `None` passed in, returned, and defaulted; UNWRAP of NONE is outside the domain, so it is
  "not compared", never "unequal" (D7).
* **Gödel:** the type atom `option`, four op cards. O3 adds `sum`, INJ, CASE (and the special form).
* **Blockers:** the `None` share of the 343 constants and of the 954 defaults (`def f(x, k=None)`), and
  `Optional[...]` annotations within the 3,863.

## 4. Records (dataclasses and instance state)

About 65 of 149 sampled stdlib functions read or write `self`. This is the largest semantic step.

| option | Σ | M | notes |
|---|---|---|---|
| **R1. Immutable record sorts** (recommended first) | a nominal sort per `@dataclass(frozen=True)` / NamedTuple, declared by a **record card**; MK_R (`[s₁…sₙ, R]`) and one GET_R_f per field; WITH_R_f (`[R, s_f, R]`) for functional update | product with names | it is U1 with names; laws `get_f(mk(…x_f…)) = x_f`, `get_f(with_g(r, v)) = get_f(r)` for f ≠ g |
| R2. Methods as functions on R1, state threaded | a method `def m(self, …)` that assigns `self.x` lifts to a function returning the new record (and its result as a tuple) | pure | stays in T_Σ(X); aliasing (two names for one object) is rejected by the lifter and reported |
| R3. A heap: references and a store | sorts `ref[R]`; NEW, LOAD_F, STORE_F touching a store σ | a store-passing model | needed for real aliasing and cycles; it extends the special form LOAD and makes the model stateful; large change to D4 |

* **Emit (R1/R2):** C-like: `struct` (C, Go), `struct`/`class` with value semantics (C++, C#, Swift `struct`),
  WITH as copy-and-set. JVM: `record` (Java), `data class` with `copy` (Kotlin). JS: a frozen object literal and
  spread for WITH. Rust: `#[derive(Clone)] struct`, WITH as struct-update syntax. Lua: a table, WITH as a shallow
  copy. Lean: `structure`, WITH as `{ r with f := v }`.
* **Witness:** per family a record of three fields (int, float, list[float]), a constructor, a getter, a WITH and
  an R2 method; equality on results is field-wise.
* **Gödel:** a record is declared by a card, so each record *type* would otherwise be an atom. Propose instead
  three schema atoms (MK, GET, WITH) parameterised by the record card's id, plus the type atom `record`; the
  record card's own content is then its field sorts, and two records with equal field sorts share content (D11)
  while staying distinct nominal sorts. R3 adds `ref`, NEW, LOAD_F, STORE_F.
* **Blockers:** dataclass annotations within the 3,863, and (with R2) most of the 65/149 methods with instance
  state; R3 is needed only for the aliasing remainder, which should be counted before it is built.

## 5. `raise` and exceptions

| option | Σ | M | notes |
|---|---|---|---|
| **E1. Raise as leaving the domain** (recommended first) | an op card RAISE (`[int, s]` per sort s, the int an error code from an exception-class table), with an empty domain | ⟦RAISE(c)⟧ is undefined; a function whose term reaches RAISE is partial there | fits D4 and D7 as they stand: inputs that raise are outside the domain and are compared as "both raise", not as values. No `try`. |
| E2. Error sum `result[s]` | a sum sort (O3) OK/ERR; every op that may raise returns `result`, `try` is CASE | total, explicit | exact Python semantics for `try/except`; every enclosing term is lifted into `result` (a monad), heavy for emit |
| E3. An effect with a handler special form | RAISE plus a special form TRY(body, code, handler) | M extended with an error outcome ⊥_c distinct from "undefined" | `try` without the monadic rewrite; changes D4 (two kinds of bottom) and D2 (one special form) |

* **Emit:** E1: C-like `abort()` / C++ and C# `throw` / Go `panic` / Swift `fatalError`; JVM `throw new
  RuntimeException(code)`; JS `throw`; Rust `panic!`; Lua `error(code)`; Lean: the domain becomes a hypothesis
  (RAISE has no Lean template, and a Lean proof is only on the domain). E2/E3: native exceptions where they exist,
  `Result`/`Either` in Rust and Lean, error returns in C and Go.
* **Witness:** E1: cells where the input is outside the domain check that the target aborts (exit status or
  thrown), and never compare a value. E3 additionally checks the handler runs and the code matches.
* **Gödel:** E1 one atom (RAISE) and an exception-class table proposed as literals, not atoms. E2 reuses O3's
  atoms plus `result`. E3 adds RAISE and the special form TRY.
* **Blockers:** E1 removes the 217 `raise` (guard clauses, almost all of them); `try` stays a reported gap until
  E2 or E3.

## 6. Strings (PR #69, and what follows)

PR #69 takes `str` as a sequence of Unicode code points with 11 op cards. The options here are about what goes
around it.

| option | Σ | M | notes |
|---|---|---|---|
| **S1. Code points, as #69** (recommended) | `str` a sort; length, index and slicing count code points | Python `str` | targets with UTF-16 (JVM, JS, C#) or UTF-8 (Rust, Go, C, Lua) strings emit through code-point helpers on the language card; ASCII-only inputs need none of them, which is a domain fact, not a patch |
| S2. Bytes (`list[u8]` with UTF-8) | a string is `list[u8]` after #61; `str` ops become list ops | bytes | trivially portable, but `len("é")` is 2, so it disagrees with Python: a divergence law on every non-ASCII input |
| S3. Two sorts `str` and `bytes` with ENCODE/DECODE | S1 plus `bytes ≤ list[u8]` | both | needed for the `bytes` constants in the 343; DECODE is partial (invalid UTF-8) |

* **Emit:** S1 as #69: C-like a code-point array or UTF-8 with helpers, JVM `codePoints()`, JS `Array.from(s)`,
  Rust `chars()`, Lua `utf8` library, Lean `String` (already code points).
* **Witness:** #69's cells, plus one non-BMP string (an emoji) per family, which separates code points from UTF-16
  units.
* **Gödel:** `str` and #69's 11 op cards are the atoms to propose; S3 adds `bytes`, ENCODE, DECODE.
* **Blockers:** the `str` share of the 3,863 and the 343 constants; formatting (`f"…"`) needs a FORMAT op per sort
  and is out of this document.

## 7. Recommended order

1. **Truthiness, T1.** No atoms, frontend only, 211 blockers.
2. **Strings, S1** (land #69 after #61), then S3 when `bytes` constants are counted.
3. **Tuples, U1** with arity-parameterised atoms. It is the product every later step reuses.
4. **Option, O1.** Small, and it unblocks `=None` defaults.
5. **`raise`, E1.** One atom, fits D4/D7 unchanged.
6. **Records, R1 then R2.** Built on U1; R2 covers most instance state without a heap.
7. Then decide, with counts: **O3/E2 or E3** for `try` and unions, and **R3** for aliasing. Each changes D2 or D4,
   so each is a FOUNDATIONS amendment, not just new cards.

Each step: add the sort to `TYPES` (this stream owns IR types), op cards with ranks, `eval`, domain and emit
templates on every language card or a declared gap, conformance cells per family, laws as rule cards witnessed in
M, and a list of atoms handed to the ledger writer.
