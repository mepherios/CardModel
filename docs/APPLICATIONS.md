# APPLICATIONS: what CardModel can be used for, today and next

Written 2026-11-05. This page lists concrete uses of the model and grades each one by what works **today** and
what is still **needed**. It does not add measurements. Each number is copied from a named source: the functional
assessment run on `main` at `a99bc77` on 2026-11-05 (cited as *assessment*), [TARGETS.md](TARGETS.md) (what the
model is for), [GODEL.md](GODEL.md) and [GODEL_AUDIT.md](GODEL_AUDIT.md) (the Gödel layer),
[MATH_LANGUAGE.md](MATH_LANGUAGE.md), [MACHINES.md](MACHINES.md), [ENVIRONMENTS.md](ENVIRONMENTS.md) and
[ANYPS5.md](ANYPS5.md). The goal floors are the goal cards (`cardmodel status`, `cardmodel cover`). When this page
and a goal card disagree, the goal card wins.

Each claim carries a grade in the sense of law CM46:

* **proven**: a theorem the Lean kernel checked;
* **measured**: a number from a run, at the tier that run had;
* **planned**: a design in a document, with nothing built;
* **conjecture**: follows from the definitions, with no theorem, test or design yet.

The assessment host had no `lean`, so it did not re-check any "proved" count. Those counts are carried over from
the cards.

## Summary

| # | application | today | main blocker |
|---|---|---|---|
| 1 | Verified cross-language porting of numeric code | **works** on small numeric functions (measured) | real code barely lifts: 1 of 149 stdlib functions |
| 2 | Finding duplicate or shared logic | **works** on the arena corpus (measured: 484 → 81) | identity is not stored on cards; `similar` ignores structure |
| 3 | Proven optimization with certificates | **works** on integer modules (measured: ×569, ×772) | crashes on list parameters; float sorts not shown |
| 4 | Math notation as a source language for kernels | **works** on scalar recurrences and piecewise functions (measured: 4/4 round trip) | no list or array parameters in notation |
| 5 | Machine-code lifting and emulation | **works** for LR35902 (measured: 511/512 symbolic); ARMv5TE partial | ARMv5TE has 0/167 symbolic terms |
| 6 | Numeric portability auditing | **partial**: per-device measurements of FMA and FTZ exist (measured) | the laws are not yet applied per sort and device in the e-graph |
| 7 | Dimension checking of physics formulas | **early**: the content algebra fits dimensions (merged #48) | no unit-annotated input format beyond that PR |
| 8 | Console API semantics (AnyPS5) | **partial**: 138 exports witnessed (measured) | most gaps are observation-only or boundary items |

## 1. Verified cross-language porting of numeric libraries

**Who it is for.** Teams that keep the same numeric routine (finance, simulation, geometry, DSP helpers) in
several languages and need the copies to agree.

**What works today (measured, assessment).** `init`, `observe`, `learn --promote` and `translate --to ...` on a fresh
Python file lifted 6 of 8 functions: clamp, triangle, lerp, factorial (recursion), sum_squares (`list[int]`), and a
function that calls another. All 6 agreed when run in all 10 languages: Python, C, C++, Go, Java, JS, Lua, Ruby, Rust
and TS. Small C functions (gcd, a double average) and Go functions (tuple assignment loop) agreed in 5 targets each.
The two functions that did not lift (`str`, `list[str]`/dict) were reported as gaps, with line numbers.

**What blocks wider use.**

* Real-world code barely lifts. On the whole Python 3.14 stdlib without tests (`lift-sweep`, 2026-11-05, main 6920ac6), 223 of 13,300 functions lift (1.68 %; 161, 1.21 %, with no gap). The
  top causes are instance state and records (`self._` 6,487, `self` 1,206), non-numeric defaults (741) and varargs
  and keyword-only parameters (520). An earlier sample, 1 of 149 functions in six unnamed modules (0.67 %), is not
  reproducible.
* The IR has no strings, dicts, tuples, records, classes or closures.
* `emit` to a single file only produces valid output for C among the languages tried. Rust repeats `#![allow]`
  before each function, and Go repeats the `package` clause (assessment §e, bugs 1 and 2).

**Next step that unlocks it.** Add records and tuples to the IR (the largest blocker class), then rerun
`lift-sweep` on the stdlib. Fixing the Rust and Go multi-function emitters is a small change that unblocks
shipping the output as a library.

## 2. Finding duplicate or shared logic across a codebase (Gödel content)

**Who it is for.** Maintainers of polyglot or long-lived codebases who want to find the same function written
twice, or a shared factor between two functions.

**What works today.**

* **Measured** (GODEL_AUDIT.md): on the arena corpus (11 languages × 44 functions), 484 lifted functions collapse to
  245 under α-hash and to **81 under the Merkle identity**, in 0.018 s. 16 of the 44 names present in several
  languages collapse to one hash.
* **Measured** (assessment): `godel factor` passed the γ(t) = γ(C) + Σγ(cᵢ) check on 304 of 304 definition cards it
  factored. 54 of the 359 cards sampled were refused with "no closed term".
* `godel gcd`, `lcm`, `vector` and `similar` run in under a second each.

**What blocks wider use.**

* `similar` uses content only, so it over-matches. `x*x+1` ranks `alg__factorial` at 1.000 because both have the
  multiset {ADD, MUL} (measured).
* The Merkle identity is designed but not stored on function cards (GODEL_AUDIT.md, **planned**).
* Canonical forms exist for 24.6 % of definitions, against goal G_U7's target of 0.9.
* The input has to lift first, so this application has the same limit as application 1 on real code.

**Next step that unlocks it.** Store the identity and γ on each function card, as GODEL_AUDIT.md describes. Then
combine γ with the structural code σ in `similar`, so that equal content alone no longer counts as a match.

## 3. Proven optimization with certificates

**Who it is for.** Anyone who needs a faster routine and an argument for why it still computes the same thing.

**What works today (measured, assessment).** `improve` on an integer-only module turned loops into closed forms:
triangle ×569, slow_sum ×772, clamp_tri ×41, factorial ×1.7. Two rewrites were kept, with an end-to-end check, in
26 s. `distill` simplifies `(x+0)*1 + x*2` to `(x<<1)+x` and proves `x*(y+z) = x*y + x*z`. It names the rule chain
and witnesses 64 inputs.

**What blocks wider use.**

* `improve` crashes with `KeyError 'list[int]'` on any function with a list parameter (assessment bug 3).
* `distill` does not print the sort it decided equality at. `(a+b)+c = a+(b+c)` is reported equal, which is true on
  ℤ but false on binary64, and there is no visible way to ask at the float sort.
* The certificate is a rule chain plus witnessed inputs. It is a Lean proof only where the rules themselves carry
  one, and that was not re-checked on this host.

**Next step that unlocks it.** Fix the `WIDE` lookup for list types in `engines/improve.py`. Make `distill` take
and print the sort. Emit the rule chain as a certificate file next to the optimized code.

## 4. Math notation as a source language for kernels

**Who it is for.** Numerical and ML engineers who want to write a kernel once as equations and get checked code in
each target.

**What works today.**

* **Measured** (assessment): `math translate` of sq, poly, tri (a recurrence) and collatz (a three-way piecewise
  recurrence) agreed in IR, C, Go, Java, JS and Rust. The round trip back to notation passed 4 of 4, and `math run`
  passed 3 of 3 tests.
* [examples/transformer/transformer.math](../examples/transformer/transformer.math) writes matmul, softmax,
  layernorm and GELU in notation (MATH_LANGUAGE.md). The assessment did not run this file, so its status is not
  graded here.

**What blocks wider use.** Notation has no list or array parameters. `Σ_{i=0}^{len(xs)-1} xs_i` is rejected with "len
does not apply to (ℤ)" (measured). Without arrays, real kernels work only as scalar pieces. Float contraction and
rounding are not part of the notation's meaning (see application 6).

**Next step that unlocks it.** Add sequence-typed parameters to the math frontend, reusing the IR's lists. Then make
the transformer example a `math run` test, so it is measured and not just present.

## 5. Machine-code lifting and emulation

**Who it is for.** Emulator authors, preservation projects, and anyone who needs to know what an instruction
does, written as a term.

**What works today (measured, assessment).** `isa check` passes 512/512 for LR35902 and 167/167 for ARMv5TE, in C,
IR and Python. Symbolic LR35902 covers 511 of 512 instructions. The remaining one is the CB prefix dispatch, which
is a decode step and not an operation.

**What blocks wider use.**

* Symbolic ARMv5TE covers 0 of 167 instructions. Every one fails with "unsupported unknown variable op".
* Goal G_M6 (511/679) is unmet.
* The assessment did not run `arcade` or `emu`, because they need ROMs or a display.

**Next step that unlocks it.** Teach the symbolic engine the ARMv5TE variable ops (shifter operand, conditional
execution), then measure against G_M6.

## 6. Numeric portability auditing

**Who it is for.** Teams whose results differ between machines, compilers or flags, for example from fused
multiply-add, flush-to-zero or reassociation.

**What works today.** ENVIRONMENTS.md measures device behaviour on the host. The host lists AVX, FMA and F16C, and
setting FTZ/DAZ in MXCSR changes `5 × 10⁻³¹⁰ × 0.5` to 0 and changes how the input is classified (**measured**).
`MULADD` has a Rust FMA form (E12). PR #57 writes FMA and FTZ as laws; this page does not grade it until it merges.

**What blocks wider use.** These are not yet laws that the e-graph applies at a sort and device, so `distill` and
`improve` cannot say "equal on ℤ, not on binary64 with FTZ" (application 3). There is no tool that scans a lifted
program and reports which of its operations are flag-sensitive (**planned**, ENVIRONMENTS.md).

**Next step that unlocks it.** Land the FMA/FTZ laws with their sorts, then add a report that lists the
flag-sensitive operations of each lifted function, per target.

## 7. Dimension checking of physics formulas

**Who it is for.** Scientists and engineers who want unit errors caught before a formula reaches code.

**What works today.** GODEL.md shows that dimensional analysis is the content algebra with nothing added. For example,
N = kg·m·s⁻², J = kg·m²·s⁻² and gcd(N, J) = N, and dimensional homogeneity is preserved under algebraic manipulation
(a consequence of the definitions in GODEL.md, not a Lean theorem: **conjecture** grade under CM46). Merged PR #48 adds dimension checking. The assessment did
not exercise it, so it carries no measured number here.

**What blocks wider use.** Formulas need unit annotations, and there is no measured corpus of real formulas
checked.

**Next step that unlocks it.** Put units on `.math` parameters, and run the check over a set of published physics
formulas, with seeded unit errors, to produce a measured detection rate.

## 8. Console API semantics (AnyPS5)

**Who it is for.** Console compatibility-layer developers who need each exported function's meaning and an
honest coverage figure.

**What works today (measured, ANYPS5_COVERAGE.md, snapshot of 2026-10-21).** The card model reproduces AnyPS5's own
62.76 % libraries badge with 0 mismatches. By AnyPS5's own records, 2,467 of 6,903 functions (35.74 %) are complete.
138 exports agree with semantics derived from public standards on every input tried. Every one of the 7,278 gap items
has a cause: derivable 316, observation only 4,251, boundary 2,677, performance 34.

**What blocks wider use.** Most of the gap cannot close by construction. Observation-only and boundary items need
behaviour from real hardware or private documentation, which the model does not have and does not invent
(ANYPS5.md).

**Next step that unlocks it.** Close the 316 derivable items first; they are the only gap class the model can
close by itself.

## What this page does not claim

* No application here works on arbitrary real programs today. The real-code lift rate is 1.68 % on the stdlib (measured, §1).
* The assessment did not run full `verify`, the full unit test suite, `self run`, `matrix` or `analyse`.
* `cover` reports 54 goals: 32 met, 6 unmet, and 16 not run yet. The unmet goals are G_C4, G_M6, G_P4, G_U3, G_U7
  and G_U9.
* The task that asked for this page names a `docs/GOALS.md`, but that file is not on `main` at the time of writing.
  The goal cards and `cardmodel status` are used in its place.
