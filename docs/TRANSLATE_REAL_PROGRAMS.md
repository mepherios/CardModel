# Translating real programs: where CardModel fell short (2026-11-04)

Input: every Python file under 60 KB in ting, firstlaw, SageScripts, re-tools, rea-cards and AnyPS5-cardmodel
(1,337 files, 9,966 top-level functions; vendored code such as sympy, mbedtls scripts and Ghidra included).
Each file went through `cardmodel translate` into 12 targets (C, C++, Go, Java, JavaScript, TypeScript, Lua,
Python, Ruby, Rust, Swift, Lean), each compiled, run and compared with the original Python.

| | before | after |
|---|---|---|
| functions that lift | 163 (1.6%) | 268 (2.7%) |
| ... in V's own code (vendored excluded) | 150 of 6,576 (2.3%) | 254 (3.9%) |
| lifted functions with a failing or crashing target | 30 | 0 |
| files that crash the CLI (Python 2 syntax) | 7 tracebacks | clean `error:` line, exit 2 |

## Failures, ranked by impact, and what was fixed

1. **Wrong answers: `pow(a, b, m)` with b < 0** (Python's modular inverse). C, C++, Go, Rust, Java,
   JavaScript, TypeScript, Lua, Swift and Lean returned `1 % m` silently; Ruby crashed. Hit number-theory
   code (firstlaw `legendre`, pheros `legendre_symbol`). Fixed: a `cm_modinv` helper per language
   (extended Euclid, error if not invertible); `cm_powmod` inverts first; Ruby now uses the helper.
2. **Ruby crashed on capitalized names** (`N`, `R_final`, `M_solar` are constants in Ruby): physics and
   epidemiology functions (about 25). Fixed: `codegen.lowercase_idents` on the Ruby card renames them `cm_<Name>`.
3. **A user function named like a platform function** (`tanh` in pheros neural): C and C++ refused to
   compile, Swift recursed forever. Fixed: names the op cards' emit templates call get the `_cm` suffix.
4. **Complex results**: `x ** 2.5` with x < 0 is complex in Python and NaN elsewhere, so every target
   "failed". Fixed: such inputs are outside the real domain and are dropped.
5. **Int results accepted as floats**: the comparison passed a float from a target when the reference was
   an int (in a test, Lua turned an over-wide constant into a float and still passed). Fixed: an int reference
   needs an int back. Over-wide integer constants are now an emit gap on 64-bit targets, not a compile error.
6. **Lift blockers in numeric code** (now lifted): numeric parameter defaults and keyword arguments
   between module functions; module-level numeric constants (`P = 2**61 - 1`, assigned once, never
   `global`); `math.sqrt exp log sin cos tan asin acos atan atan2 sinh cosh tanh fabs floor ceil trunc fmod
   copysign isnan` and `math.pi e tau` (all op cards already existed); `@cache` / `@lru_cache`.

## Remaining gaps (by count of first blocker, after the fixes)

| count | blocker | what it would take |
|---|---|---|
| 3,863 | non-numeric type annotations (`str`, `list[float]`, dataclasses, `None`) | strings, lists, tuples and records in the IR: the real next step |
| 954 | non-numeric defaults / `*args`, `**kwargs` | follows from the above |
| 343 | string / bytes / None constants | strings in the IR |
| 243 + 227 + 210 | tuple targets, subscripts, list literals | lists and tuples in the IR |
| 217 | `raise` | an error effect in the IR (targets would abort/throw) |
| 204 | names that are not constants (mutable globals, imports) | out of scope for pure functions |
| 146 + 65 | truthiness of numbers (`if n:`, `not x`) | easy: lift as `!= 0` |
| — | class methods are not looked at at all | lift `@staticmethod`s and report methods instead of skipping them |

Most of these projects are tooling (paths, JSON, subprocess), which the pure-numeric subset can never
translate; the code that does translate is the math (firstlaw, pheros configs, ting's number theory).
Honest note: Lua has no `tanh` template (Lua 5.4 lacks `math.tanh`), so it stays a gap there.
