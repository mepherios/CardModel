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

## Honest limits (L1)

* Scalars only (`int`, `float`, `bool`), like the Python frontend. Arrays, strings, structs, pointers, closures,
  exceptions and globals are reported with their line, never guessed. Lists come with the IR's list types.
* Unsigned integers and binary32 floats are reported, not approximated.
* Fixed-width sources agree with the IR only where no value overflows. The witness compares only inputs whose IR
  values fit the card's `int_bits`.
* A hand parser covers the IR subset of each language, not the whole grammar. The roadmap's per-language parsers
  (`go/parser`, the JDK tree API, Prism) can replace a dialect later without changing the IR it produces.
* C#, Kotlin, Zig and Julia have no runner card yet, so their lifts are checked only by the spot values in the tests.
