# User guide: using CardModel today

Task-oriented recipes that work on `main`. Every command, output and limit here was run and measured on a Linux
container (4 cores, `CARDMODEL_SELF=0`) on 2026-11-05. Outputs are abbreviated. Where something is broken on `main`
the guide says so and names the PR that fixes it. For the model itself see [HANDOVER.md](../HANDOVER.md) §1–§3.

## 1. Install

```bash
git clone <this repository> cardmodel && cd cardmodel
./bin/cardmodel probe
```

There are no dependencies beyond Python 3. To use it from any folder, either symlink the shim
(`ln -s "$PWD/bin/cardmodel" /usr/local/bin/cardmodel`) or `pip install -e .`. Set `CARDMODEL_SELF=0` if you do not
want commands to trigger the model's own self-cycle work.

## 2. Check health

```bash
cardmodel probe            # which toolchains this machine has (~3 s)
cardmodel verify --quick   # whole-store health check (~2.5 min)
cardmodel docs --check     # LAWS.md and goal floors in sync (<1 s)
```

**Success looks like:** `probe` lists each language with `✓` (found) or `·` (missing), for example
`✓ rust codegen /root/.cargo/bin/rustc` and `· lean codegen lean not found`. `verify --quick` exits 0 with every
section passing; measured: kernel 24,285 cards, 0 errors; capabilities 32 pass / 2 unavailable (formal_core, lean
when Lean is absent); lang 16/16; machine lr35902 512/512, armv5te 167/167; rules 135/135.

**Limits:** without `lean` installed, proof counts are carried from the cards, not re-checked. Full `verify` (adds the
op × language matrix and Lean) takes several minutes. `verify --quick` and `env` write cache files into the checkout
(`state/`, gitignored).

## 3. Translate a Python, C or Go function to other languages, with witnesses

```bash
cd /path/to/your/project
cardmodel init                    # creates .cardmodel/
cardmodel observe . --save        # what lifts, what does not
cardmodel learn . --promote       # promote function cards that have evidence
cardmodel translate mathy.py      # every language with a toolchain
cardmodel translate mathy.py --to rust,go,c
cardmodel translate small.c       # C and Go sources work the same way
cardmodel translate small.go
```

**Success looks like:** one line per function, naming the languages in which the emitted code was *run* and agreed
with the original:

```
  clamp        agrees in 10: python_source, c, cpp, go, java, javascript, lua, ruby, rust, typescript
  fact         agrees in 10: ...
  sum_squares  agrees in 10: ...
  count_char   not lifted: line 28: type annotation 'str' (only int/float/bool, list[int], list[float])
```

Measured: 6 of 8 fresh Python functions (clamp, triangle, lerp, recursive fact, `list[int]` sum_squares, a function
calling another) agreed in all 10 languages; small C (`while` loop, `double`) and Go (tuple assignment) functions
agreed in every target. Gaps are reported with line numbers, never pasted through.

To write one translation to a file: `cardmodel emit --lang c mathy.py --out mathy.c`.

**Limits:**

* Parameters must be `int`, `float`, `bool`, `list[int]` or `list[float]`. `str`, `list[str]`, `dict`, tuples,
  classes, records and closures do not lift yet.
* Real-world code lifts poorly: 223 of 13,300 functions in the Python 3.14 stdlib (1.68 %, `lift-sweep`, 6920ac6;
  instance state, non-numeric defaults, varargs and keyword-only parameters are the main blockers). Aim it at small numeric functions.
* `emit --lang rust` and `emit --lang go` of a file with two or more functions produce code that does not compile on
  `main` (repeated `#![allow]` / one `package` clause per function). Fixed in PR #63. `emit --lang c` compiles.
  `translate` (which runs each function separately) is not affected.

## 4. Write equations in math notation

```
-- m.math
sq(x) = x · x
poly(x) = 3x² + 2x + 1
tri(n) = n + tri(n − 1)   if n > 0
       = 0                otherwise
collatz(n) = 0                       if n ≤ 1
           = 1 + collatz(⌊n/2⌋)      if n mod 2 = 0
           = 1 + collatz(3n + 1)     otherwise
test poly(2) = 17
test tri(4) = 10
test collatz(6) = 8
```

```bash
cardmodel math run m.math          # the test lines
cardmodel math translate m.math    # every codegen language, plus the round trip through math
cardmodel math emit mathy.py       # Python as equations (--latex for LaTeX)
cardmodel math roundtrip mathy.py  # lift(emit_math(f)) == f
```

**Success looks like:** `math run` 3/3 tests; `math translate` shows sq, poly, tri, collatz agreeing in ir, c, go,
java, js, rust, with round trip 4/4.

**Lists need a signature line.** Without one, variables are scalars, and `len(xs)` fails with
`len does not apply to (ℤ)`. Declare the list type:

```
dot : [ℝ] × [ℝ] → ℝ
dot(a, b) = Σ_{i=0}^{len(a) − 1} a[i] · b[i]
test dot([1.0, 2.0], [3.0, 4.0]) = 11.0
```

**Limits:** `/` is real division, so `n / 2` on an integer is rejected; write `⌊n/2⌋`. Full syntax (Σ, Π, cases,
`where`, domains, LaTeX) is in [MATH_LANGUAGE.md](MATH_LANGUAGE.md); lists in [LISTS.md](LISTS.md).

## 5. Prove or simplify with distill and rewrite

```bash
cardmodel distill '(x+0)*1 + x*2'            # simplify
cardmodel distill 'x*(y+z)' 'x*y+x*z'        # are they equal?
cardmodel rewrite crypto_atom/ed25519_sign --domain python   # cheapest form of an operation
```

**Success looks like:**

```
((x << 1) + x)   cost 2.0   sha256:1d24a6bf...
6 iterations, 4001 nodes, budget spent; equalities used: rewrite_rule/rule_distrib_left_MUL_ADD, ...

equal; witness witnessed on 64 inputs (seed 2681830258); equalities used: rewrite_rule/commutative_mul, ...
```

The rule chain is named and equalities are also checked on random inputs.

**Limits:** variables are integers; `distill` does not print the sort, so `(a+b)+c` = `a+(b+c)` is reported equal
(true over ℤ, not for floats). Do not use the `expr:` prefix (it gives a raw traceback). Simplification of large
expressions stops at its node budget (`--nodes`, `--iterations`).

## 6. Gödel: factor, similar, cofactor

```bash
cardmodel godel ledger                          # the atom ledger (3,417 atoms)
cardmodel godel vector definition/alg__fibonacci
cardmodel godel factor --expr 'a*b+a*c'
cardmodel godel factor definition/alg__factorial
cardmodel godel similar --expr 'x*x+1'
cardmodel godel cofactor WHOLE_CARD PART_CARD
```

**Success looks like:**

```
a*b + a*c (the expression): ((a * b) + (a * c))
  cofactor (what no concept covers): {'op/ADD': 1, 'op/MUL': 2}; γ(t) = γ(context) + Σ γ(instance): True

x*x + 1 (the expression): {'op/ADD': 1, 'op/MUL': 1}
  1.000  definition/alg__factorial: shares {'op/ADD': 1, 'op/MUL': 1}
```

Measured: `factor` over 359 definition cards gave 304 factorings with the γ check True, 0 False, 54 refused.

**Limits:**

* On `main` the CLI takes a card name or `--expr`; it does not read a Python function directly. PR #66 adds
  `FILE.py:FUNC`.
* Definitions without a closed term (loops, multi-statement bodies) are refused with `no closed term`; `cofactor`
  needs two such cards (the whole, then the part).
* `similar` compares content only (the multiset of operations), so unrelated structures can score 1.000.
* `godel decode` without a number prints `list index out of range` instead of usage; pass a number
  (`godel decode 360 --vars x`).

## 7. Machines: check instruction sets

```bash
cardmodel isa check lr35902    # Game Boy CPU
cardmodel isa check armv5te
```

**Success looks like:**
`lr35902: 512/512 instruction cards pass in c, ir, python (4224 one-instruction runs, 8 samples each); IR in sync: pass`
(armv5te: 167/167). A seed is printed for reproduction (`--seed`).

**Limits:** symbolic terms exist for LR35902 (511 + 1 CB-prefix dispatch of 512) but not for ARMv5TE (0/167).
Running games (`arcade`, `emu`) needs ROMs and a display. See [MACHINES.md](MACHINES.md).

## 8. Environment card

```bash
cardmodel env
```

**Success looks like:** an environment card id and measured machine facts (cache levels by pointer chase from 4K to
64M, memory latency, copy bandwidth) plus the budgets derived from them, for example
`budgets: cpu_workers 4, compile_slots 2, child_mb 3072`. About 5 s. See [ENVIRONMENTS.md](ENVIRONMENTS.md).

## 9. Reading goals with cover

```bash
cardmodel cover                    # print
cardmodel cover --write COVERAGE.md
cardmodel status
```

**Success looks like:** a table of goals with axis, metric, value, target and met (`yes`, `no` or `—`). Measured: 54
goals, 32 met, 6 unmet, 16 `not run yet`. `not run yet` means the metric comes from a full `verify` or `self run`
that has not happened on this machine; it is not a failure.

## 10. Making a numeric module faster (improve)

```bash
cardmodel improve mathy.py --out mathy_fast.py
```

On int-only modules it finds real speedups (loop to closed form: ×569, ×772 measured) and checks the result end to
end. **On `main` it crashes with `KeyError: 'list[int]'` if any function has a list parameter**; fixed in PR #63.

## 11. Examples

* `examples/algorithms`, `examples/math`, `examples/lang`, `examples/transformer` (lists, matmul, softmax).
* `examples/showcase` (a guided tour of the recipes above) is not on `main` yet; it arrives with PR #59.
