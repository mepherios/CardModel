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
or helper it takes that type. Such lifts are marked `inferred_types`. A parameter annotated with bare `list` gets its element type the same way: `list[int]`, then `list[float]`, the first whose lift lifts and agrees with the source on seeded inputs; when neither does, the reason says `annotate as list[int] or list[float]`.

## Every lift is witnessed

`frontends.witness_source` runs the **original** source through its own toolchain on seeded inputs, in a harness
built from the language card (`frontend_harness`: renaming the source's `main`, Go's package line, Java's class,
C#'s private statics, argument casts), and compares each output with the IR interpreter. `translate` prints it as
`<lang> source: pass (N checks)`. A language with no toolchain on the host reports `unavailable` or `no_harness`,
never pass. With `CARDMODEL_SLOW=1` the test witnesses every language whose toolchain probes available, so a frontend
language that CI's runner image has (C#, Kotlin and Julia are preinstalled there) needs a `frontend_harness` and a
`runner`.
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
The closure is partial, not poisoned (SCALING.md §3.3): a function whose own body does not lift becomes an opaque
boundary card (its declared signature when it types, and its cause), and its callers still lift with each such call
edge recorded as a gap (`Lifted.gaps`, `ProjectLift.boundaries()`). `ok` means *closed*: the function and everything
it calls lifted, so it runs and translates alone. `lift-sweep` reports both rates and counts gap edges by cause.

Python 3.13 stdlib without its tests, methods included (3,279 files, 49,684 functions, 2026-11-05): 579 lift
(1.17 %), 300 of them closed and 279 with gaps; before boundary cards those 279 counted as failures (300, 0.60 %).
1,302 of the 49,105 boundary cards carry a typed signature, and they leave 276 call edges as gaps (most: `self.x`).
Earlier, Python 3.13 stdlib without its tests (3,183 files): 110 of 11,999 top-level functions lift one file at a time; 113
with calls across modules (most callees fail for their own reasons first); 296 of 49,743 with methods. The first
reasons are `self.x` (23,968 methods), non-scalar annotations (5,495) and defaults/varargs (4,611).

## Honest limits (L1)

* Scalars only (`int`, `float`, `bool`), like the Python frontend. Arrays, strings, structs, pointers, closures,
  exceptions and globals are reported with their line, never guessed. Lists come with the IR's list types.
* Fixed-width types lift to the sorts of `engines/sorts.py` (FOUNDATIONS.md §7 item 4): Rust `u8`..`i32`/`f32`,
  Go `uint8`/`byte`..`int32`/`float32`, Java `byte`/`short`/`int`/`float`, C# `byte`/`sbyte`/`short`/`ushort`/
  `int`/`uint`/`float`. Each lifted function records them in `Lifted.sorts` (parameter or local -> sort). Go, Java
  and C# wrap, so every result that can leave its sort (`+ - * << ~`, negation, compound assignment, signed `/`
  except in C#, which throws) gets `WRAPU`/`WRAPS`; Java and C# promote narrow operands to `int` first, so
  `(byte)(a + b)` is `WRAPS(WRAPS(a + b, 32), 8)`. Rust overflow panics in a debug build and wraps only in
  release, so a Rust lift stays exact and lists the possible overflow in `Lifted.divergences` (its domain is "no
  overflow"); Rust's `as u8` truncates in every build and lifts as `WRAPU`. `float32` results are `F32`
  (binary32 rounding), and a Go/Rust untyped constant beside a float32 is rounded too. Float-to-narrow-int casts
  (saturating in Rust and Java) are reported. C's integer rules are PR #39's; 64-bit unsigned types are reported.
* Fixed-width sources agree with the IR only where no value overflows. The witness compares only inputs whose IR
  values fit the card's `int_bits`.
* A hand parser covers the IR subset of each language, not the whole grammar. The roadmap's per-language parsers
  (`go/parser`, the JDK tree API, Prism) can replace a dialect later without changing the IR it produces.
* C# (`dotnet build`), Kotlin (`kotlinc`, run on `java`) and Julia are runners for the witness only, with no codegen
  block; Zig has no runner yet, so its lifts are checked only by the spot values in the tests.
