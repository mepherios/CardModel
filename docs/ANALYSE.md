# Understanding a program the REA way: `cardmodel analyse`

rea-cards (`~/Programmering/rea-cards`) understands a binary by turning it into facts that each name the
observation they came from, records every defect as a flaw that a witness reproduces, refuses what it cannot
reconstruct soundly instead of guessing, and, when two forms differ, names the first input where they do.
`cardmodel analyse` applies the same method to a lifted program, in the math language
([MATH_LANGUAGE.md](MATH_LANGUAGE.md)). Plan: [ROADMAP.md](ROADMAP.md) Phase J.

```
cardmodel analyse FILE...                     # every function: structure, logic, differences across runners
cardmodel analyse algos.py --to c@O0,c@O2,rust@debug,rust@release,java,python
cardmodel analyse algos.py --no-run           # the reference and the laws only; nothing is compiled
cardmodel analyse algos.py --function gcd --all --json
cardmodel analyse --laws                      # the divergence laws and what each runner does there
```

## The idea

The card IR's reference semantics *is* the program's mathematics: `int` is ℤ, `float` is IEEE binary64, and a
partial op (`a mod b`, `log x`, `a << n`) is undefined off its domain. A target language, an optimization level or
a device is a *model* of that mathematics that agrees with it only on part of the domain. C's `int64_t` is ℤ only
inside [−2⁶³, 2⁶³), and only at -O0 does it wrap predictably outside; IEEE division is total where the reference
refuses x / 0; a loop that the reference finishes in a second may not finish on a phone before its watchdog does.
The analyser states that part as math, finds where the source reaches its edge, and runs every runner there.

A difference found inside the function's **declared domain** is a **latent flaw of the source**: the program claims
more than its translations can keep. A Python `int` has no bound, so a Python function's domain is all of ℤ
unless it says otherwise. A card-language or math function declares its domain (`requires`, `for 0 ≤ n ≤ 90`), and a
difference outside it is reported as boundary behaviour, not counted against the program.

## The four parts

1. **Structure.** For every function in the IR module: its signature in math notation (`gcd : ℤ × ℤ → ℤ`), its
   calls, its recursion class (none, tail, general, or mutual through a strongly connected component of the call
   graph), its loops, the partial ops it uses, and its effects (globals read and written, arrays loaded and
   stored, void results). Every fact carries `via`, the rule that produced it, as rea-cards' facts do.
2. **Logic.** Every partial op gets an obligation, with the path condition that reaches it (guards of `if`, loop
   conditions, `for` bounds, short-circuit operands, and the negation of an `if … return` before it):
   `⌊a / b⌋ needs b ≠ 0`. It is **proved** when a fact on the path implies it, **domain** when the declared
   domain does, **open** with a counterexample when a refused input reaches it, and **sampled** otherwise (never
   called proved).
3. **Divergence laws.** Each law states in math when a runner's model of an op leaves the reference, and what each
   runner family does there:

   | law | condition | what runners do |
   |---|---|---|
   | `int_width` | a result ∉ [−2⁶³, 2⁶³) while its operands are inside | C/C++ undefined (wraps at -O0, may be folded at -O2, UBSan stops); Rust debug panics, release wraps; Swift traps; Go, Java, Lua wrap; JavaScript BigInt, Ruby, Python exact |
   | `int_div_zero` | divisor = 0 in ⌊a/b⌋, a mod b | C undefined (SIGFPE on x86-64, 0 on ARM64); panics or exceptions elsewhere |
   | `float_div_zero` | y = 0 in x / y | IEEE gives ±∞ or NaN; the reference refuses |
   | `float_exception` | a float op off its domain or overflowing (log 0, exp 1000) | IEEE NaN or ±∞; the reference refuses |
   | `float_to_int` | NaN, ±∞ or out of range into ℤ | C undefined; Rust and Java saturate; Swift traps |
   | `shift_count` | n < 0 ∨ n ≥ 64 in a << n | C undefined (hardware takes n mod 64); Java mod 64; Rust debug panics |
   | `int_pow_negative` | b < 0 in a^b on ℤ | the generated loop gives 1; Python gives a float |
   | `nan_result` | a NaN is produced and carried on | comparisons false, min/max order-dependent, fast-math assumes none |
   | `deep_recursion` | call depth ≥ 400 | native stacks of 512 KiB (secondary threads) to 8 MiB; Python stops at 1000 |
   | `step_budget` | the reference needs more than 300,000 steps | runners differ by orders of magnitude; timeouts and watchdogs decide |
   | `eval_order` | two effectful calls in one expression | C leaves operand order unspecified |
   | `float_assoc` | a float sum or product of three or more terms | -ffast-math reassociates |

   An instrumented reference interpreter runs each function on its vectors, on seeded in-domain inputs and on
   boundary inputs (the 64-bit limits, 2³¹, 2⁵³ + 1, shift widths, ±0.0, the binary64 overflow thresholds) and
   records which law fires at which term, with the operands.
4. **Witness.** Every firing is run, compiled and executed, in every available runner, each codegen language plus
   optimization and checking variants: `c@O0`, `c@O2`, `c@fastmath`, `c@ubsan`, `rust@debug`, `rust@release`,
   `swift@Onone`, `swift@Ounchecked`. A finding is **witnessed** when some runner differs from the reference (the
   difference is real, and the first input and every runner's answer are shown), **guarded** when every runner
   agrees (the codegen handles it, as `cm_floordiv` does for ⌊a/b⌋ in C), and **predicted** when no runner could
   run it here. Two runners that both refuse an input agree.

`cardmodel matrix` uses the same laws: a failing pair whose first input fires a law says so
(`explained by: int_width at a + b`).

## Example

```
midpoint : ℤ × ℤ → ℤ    (python: latent.py)
  ✓ ⌊(a + b) / 2⌋ needs 2 ≠ 0: proved (a constant)
  ✗ int_width — a + b ∉ [−2⁶³, 2⁶³) while every operand is inside it [witnessed, in domain]
      midpoint(9223372036854775807, 1): reference 4611686018427387904
      differs: c@O0 -4611686018427387904; c@ubsan ⊥ runtime_error: main.c:11:27: runtime error: signed integer
               overflow …; go -4611686018427387904; rust@debug ⊥ runtime_error: thread 'main' panicked at
               main.rs:5:24; rust@release -4611686018427387904; lua -4611686018427387904; swift@Onone ⊥ exit -5;
               swift@Ounchecked -4611686018427387904
      agrees: c@O2, c@fastmath, cpp, javascript, lean, python, ruby, typescript
      fix: declare the domain … or reorder the arithmetic (a + ⌊(b − a)/2⌋ instead of ⌊(a + b)/2⌋)

bits : ℤ × ℤ → ℤ
  ✗ shift_left(a, n) needs n ≥ 0: open (not implied by the path); fails at bits(1, -1) → ⊥ ValueError
  ✗ shift_count — n < 0 ∨ n ≥ 64 in shift_left(a, n) [witnessed, in domain]
      bits(1, -1): reference ⊥ ValueError
      differs: c@O0 -9223372036854775808; c@O2 -2; c@fastmath -2; javascript 0; lua 0; ruby 0; swift@Onone 0 …
      agrees: c@ubsan, go, python, rust@debug          (each refuses the input, as the reference does)
```

Both functions show optimization levels disagreeing about one C source (macOS arm64, Apple clang). In `midpoint`,
-O0 wraps `a + b` and halves the wrapped sum, while -O2 happens to give ℤ's answer, because the overflow is
undefined and the optimizer is free to compute the sum another way. In `bits`, -O0 gives `INT64_MIN` and -O2 gives
`-2` for `1 << -1`. Nothing in the source says which is right, because the source's own answer is "undefined
here". The analyser names the law and the first input, so the difference is defined rather than discovered in the
field.

## On the shared corpus (measured 2026-11-04, macOS arm64, Apple clang, seed 20261104)

`cardmodel analyse examples/matrix/corpus.math examples/algorithms/algos.py --to
c@O0,c@O2,c@ubsan,c@fastmath,rust@debug,rust@release,go,javascript,python,lua` took 10 minutes. The same corpus
passes `cardmodel matrix` with 0 failures, because the matrix checks each target only on inputs that fit its width.

* 49 functions; 23 of them have a difference witnessed **inside their declared domain** (38 latent findings), 2
  outside it, 3 guarded, 9 predicted only.
* Obligations: 30 proved by a guard on the path, 14 sampled, 3 open with a counterexample.
* By law (witnessed): `int_width` 29, `step_budget` 6, `int_div_zero` 3, `float_to_int` 1, `nan_result` 1.

Four of them, each a flaw of the source that a translation or an optimization turns into a different answer:

| function | input | reference | runners |
|---|---|---|---|
| `legendre` (math) | `pow_mod(a, ⌊(p − 1)/2⌋, p)` at p = 0 | ⊥ (undefined) | C at every level returns **0**: the remainder by zero is undefined, and ARM64's divide instruction gives 0 instead of trapping |
| `int_of_float` (math) | `int(x)` at x = 1e308 | a 1024-bit integer | c@O0 9223372036854775807, **c@O2 8255911664**, Rust and Go saturate, UBSan and Lua refuse |
| `lerp` (Python) | `(b − a) · t` at (1e308, −1e308, 0) | NaN (∞ · 0) | **c@fastmath 1e308**, every strict runner NaN |
| `shifts` (math) | `shift_right(a, t) + shift_left(a, t)` at (−2⁶², 1) | −11529215046068469760 | C, Go, Lua, Rust release wrap to 6917529027641081856; Rust debug and UBSan stop |


## Honest limits

* Agreement is sampled on the inputs above, never proved; `proved` is used only for obligations a path fact
  implies.
* A difference no law explains is still witnessed by the matrix, but has no explanation yet; the laws are the
  twelve listed (J2 makes them cards).
* Non-finite floats and integers outside 64 bits cannot be written as literals in fixed-width targets, so they are
  not runner inputs; they still reach ops as intermediates.
* Machine state (globals, arrays, void functions) gets structure and logic, but is not run in the runners yet.
* Runner variants are defined in `engines/analyse.py` (`VARIANTS`); a device runner (an iPad, ARM64 vs x86-64) is
  Phase J4 with Phase I.
