# Frontends: any language in

Every language card that names a `frontend` is a source language. `cardmodel translate FILE`, `cardmodel emit
--lang L FILE` and `cardmodel matrix` pick the frontend from the file's extension (or `--from LANG`).

| frontend | languages |
|---|---|
| `engines/frontend_python.py` | Python |
| `cardmodel.lang` | the card language |
| `engines/frontend_text.py` | C, C++, C#, Java, Kotlin, Go, Rust, Swift, Zig, JavaScript, TypeScript, PHP, Ruby, Lua, Julia |

So every codegen target except Lean can also be translated *from*.

## How the text frontend works

One tokenizer, one Pratt expression parser and two statement grammars (brace-delimited and `end`-delimited). A
`Dialect` holds what differs between languages: operator precedence, the type names, whether newlines end
statements, whether the last expression is the value, and what `/` and `%` mean on integers. The language's own
semantics decide every op:

| source | int `/` | int `%` |
|---|---|---|
| C, C++, C#, Java, Kotlin, Go, Rust, Swift, Zig (`@divTrunc`), JS BigInt | `TRUNCDIV` | `REM` |
| Ruby | `FLOORDIV` | `MOD` |
| Lua, PHP, Julia | float `DIV` | `MOD` (Lua), `REM` (PHP, Julia) |

`TRUNCDIV` and `REM` are op cards like any other (conformance cells, a prime in the Gödel ledger, templates in
every codegen language except Lean).

A call resolves to a function of the same file, then the dialect's library table (`Math.floorMod`, `fabs`,
`x.abs()`, `math.floor`, `Int(x)`), then the op cards' own call-shaped `emit` templates read backwards. So codegen's
helpers (`cm_floormod(a, b)`, `cm_ipow`) lift back to their ops, and a new op card with a call-shaped template is
liftable with no code change.

Untyped parameters (Ruby, Lua, JavaScript, PHP, Julia) are inferred by retrying: a parameter starts as `int`
(JavaScript: `float` unless the function uses BigInt) and is retyped when its use says otherwise. Used in a
condition it becomes `bool`, passed to `x.to_i` or `math.floor` it becomes `float`, and passed to a typed function
or helper it takes that type. Such lifts are marked `inferred_types`.

## Every lift is witnessed

`frontends.witness_source` runs the **original** source through its own toolchain on seeded inputs, in a harness
built from the language card (`frontend_harness`: renaming the source's `main`, Go's package line, Java's class,
argument casts), and compares each output with the IR interpreter. `translate` prints it as `<lang> source: pass (N
checks)`. A language with no toolchain on the host reports `unavailable` or `no_harness`, never pass.
`tests/test_frontends.py` also checks that a wrong lift (C's `/` read as floor division) fails the witness.

## Measured (Linux cloud container, 2026-11-04)

* Round trip, `lift_L(emit_L(f)) == f` for every codegen language L: 715 of 715 on `examples/matrix/corpus.py`,
  `examples/algorithms/algos.py` and `tests/frontends/corpus.py`.
* Idiomatic hand-written sources in all 15 languages (`tests/frontends/`): every function lifts. Every one whose
  toolchain is installed agrees with its own compiler or interpreter (C, C++, Java, Go, Rust, JavaScript, PHP and
  Ruby here).

## Whole projects (`engines/lift_project.py`, `cardmodel lift-sweep PATH`)

A project lift reads every file first for signatures, then lifts each file with the other files' functions as
externs. Python follows its imports (`from a.b import f as g`, relative imports, `import a.b as m`, static methods of
an imported class); the text languages link by unique name like a C linker, and a language whose card says
`"frontend_link": "class_per_file"` (Java, C#, Kotlin) also resolves `Other.f(x)`. Python methods lift as
`Class_method` when `self`/`cls` is used only to call other methods; `self.x` is reported (it needs record types).
Functions are named `<module>::<name>`; `ProjectLift.module_for(qual)` gives back one ordinary IR module, renaming
only where two files define the same name. The closure is one linear pass over the project's reverse call graph.

Python 3.13 stdlib without its tests (3,183 files): 110 of 11,999 top-level functions lift one file at a time; 113
with calls across modules (most callees fail for their own reasons first); 296 of 49,743 with methods. The first
reasons are `self.x` (23,968 methods), non-scalar annotations (5,495) and defaults/varargs (4,611).

## C: fixed-width integers and arrays

C lifts with its own integer semantics, not the IR's unbounded int. Every C integer type has a kind (signed,
bits): `int`/`int32_t` (i32), `short`, `int8_t`, `long`/`int64_t`, and the unsigned `uint8_t`, `uint16_t`,
`uint32_t`/`unsigned`. Expressions take C's kinds (integer promotion, the usual arithmetic conversions, the types of
`017`, `0xFFFFFFFF` and `31u`), and wherever C reduces a value modulo 2^w the lift writes the op card that does it,
`WRAPU(x, w)` or `WRAPS(x, w)` (the u8..i32 subsorts, FOUNDATIONS.md D1):

| C | IR |
|---|---|
| `uint32_t` `+ - * <<`, `-x`, `~x` | `WRAPU(..., 32)` around the op |
| `-1 < 1u`, `a / b` with `int a, unsigned b` | the signed operand converted first: `WRAPU(a, 32)` |
| `uint8_t c = x;` `return x;` from a `uint16_t` function, `(int8_t)x`, `c++` | `WRAPU` / `WRAPS` on the conversion |
| a `uint8_t`, `uint16_t`, `uint32_t`, `int8_t` or `int16_t` parameter | wrapped on entry, as C converts the argument |
| `int64_t` from `uint32_t` arithmetic, `uint8_t + uint8_t` (an `int`) | nothing: the value already fits |

Signed overflow is undefined in C, so signed arithmetic stays exact; `uint64_t`, `size_t` and `unsigned long` are
reported (their wrap at 2^64 is beyond the targets' signed 64-bit int).

Arrays read as lists. A `const T *xs` or `T xs[]` parameter is a `list[int]` or `list[float]` that the function
only reads, passed with its length as another parameter (domain inference ties the list's length to it); a local
`T a[n];`, `T a[n] = {0};` or `T a[] = {1, 2, 3};` is a new list (`LIST_NEW`, then `set`); `xs[i]` is `GET` and
`a[i] op= v` a `set`. Elements of `uint8_t`/`uint16_t`/`uint32_t` arrays are converted as C reads them. Writing
through a parameter, `*p`, pointer arithmetic, pointers to pointers, multi-dimensional arrays and designated
initialisers are reported with their line.

The C witness passes an array as a compound literal of the source's own element type (`frontend_harness.list_lit`
on the C card: `((uint8_t[]){200, 13, 7})`), samples arguments across the 8/16/32-bit boundaries when the lift
wraps, and leaves out arguments an `int` parameter cannot hold. `examples/c/` is a small C tree (hashes and
checksums, statistics over arrays, calls across files): every function lifts (`use.c`'s through the project lift
of `observe`/`learn`) and agrees with gcc in Python, Rust, Go, Java, JavaScript, Ruby, C and C++ (`tests/test_c_frontend.py` also checks that the IR without its wraps fails
the witness).

## Learning from any tree

`observe` lifts the functions of every file a frontend reads, as one project per language (`lift_project`: a call
into another file resolves as a linker resolves it), so `learn` proposes function cards from C, Go, Rust, Java and
the others as it does from Python. A function card learned from another language is promoted only when its lift
also passed the source witness (the original, compiled or run by its own toolchain, against the IR); a function
that calls into other C files is witnessed as one program of its module's functions under the file's own
`#include` lines.

## Honest limits (L1)

* Scalars only (`int`, `float`, `bool`), like the Python frontend, plus C arrays as lists. Strings, structs,
  pointers (other than read-only arrays in C), closures, exceptions and globals are reported with their line, never
  guessed.
* Unsigned integers outside C, C's 64-bit unsigned integers, and binary32 floats are reported, not approximated.
* Fixed-width sources agree with the IR only where no value overflows (C's unsigned and narrow types excepted:
  they wrap as C does). The witness compares only inputs whose IR values fit the card's `int_bits`, and in C only
  arguments the parameter's type holds.
* A hand parser covers the IR subset of each language, not the whole grammar. The roadmap's per-language parsers
  (`go/parser`, the JDK tree API, Prism) can replace a dialect later without changing the IR it produces.
* C#, Kotlin, Zig and Julia have no runner card yet, so their lifts are checked only by the spot values in the tests.
