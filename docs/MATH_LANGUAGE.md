# Mathematics as a language

CardModel reads and writes mathematical notation like any other language card (`cards/language/math`). A `.math`
file lifts to the card IR, so it is emitted, compiled and run in every codegen language. Any IR function without
machine state can also be written back as equations. That output is checked the same way the other targets are:
lift it again and compare it with the original on the function's inputs.

```
cardmodel math run examples/math/basics.math            # its tests
cardmodel math translate examples/math/basics.math      # every codegen language, plus the round trip through math
cardmodel math emit examples/algorithms/algos.py        # Python (or .card, .math, a function card) as equations
cardmodel math emit examples/algorithms/algos.py --latex
cardmodel math roundtrip examples/algorithms/algos.py   # lift(emit_math(f)) == f for every function
```

## Writing math

```
T : ℕ → ℕ                                   -- signature (optional): ℤ ℕ ℝ 𝔹 or Int Nat Real Bool, × and →
T(n) = ⌊n(n + 1)/2⌋                         -- n(n + 1) is a product: n is not a function

gcd(a, b) = |a|                if b = 0     -- cases, one per line, ending with `otherwise`
          = gcd(b, a mod b)    otherwise

fact(0) = 1                                 -- pattern equations
fact(n) = n · fact(n − 1)

s(n) = Σ_{i=1}^{n} i²                       -- Σ and Π (bounds inclusive) and n!
h(x) = y² + 1  where y = x + 1              -- where-bindings, read in order
f(x) = { x if x ≥ 0; −x otherwise }         -- inline cases; also `if c then a else b` and `let y = e in b`
fib(n) = fibk(n, 0, 1)
  for 0 ≤ n ≤ 90                            -- the domain: verification draws its inputs from it
test T(4) = 10                              -- checked by `cardmodel math run`
```

Lists (`[ℤ]`, `[ℝ]`; the IR's `list[int]` and `list[float]`, see [LISTS.md](LISTS.md)):

```
dot : [ℝ] × [ℝ] → ℝ
dot(a, b) = Σ_{i=0}^{len(a) − 1} a[i] · b[i]          -- xs[i] indexes from 0, len(xs) is the length
relu(x) = [max(x[i], 0.0) | i < len(x)]              -- [e | i < n]: the list of e for i = 0, …, n − 1
bump(xs, i) = xs[i ↦ xs[i] + 1]                      -- a new list with element i replaced
test dot([1.0, 2.0], [3.0, 4.0]) = 11.0              -- literals; list_new(n, v) and list_copy(xs) by name
```

[examples/transformer/transformer.math](../examples/transformer/transformer.math) writes matmul, softmax, layernorm,
GELU and the rest this way.

A list parameter needs a signature (`s : [ℤ] → ℤ`): without one every parameter is read as ℤ, and
`len(xs)` or `xs[i]` is rejected with a message that names the signature to add.

LaTeX works too, and can be mixed with Unicode: `\frac{a}{b}`, `\sqrt{x}`, `\cdot`, `\le`, `\sum_{i=1}^{n}`,
`\lfloor … \rfloor`, `\begin{cases} 1 & n = 0 \\ n \cdot q(n-1) & \text{otherwise} \end{cases}`,
`\operatorname{name}`, `\mathbb{N}`, `\bmod`, `\pi`. The emitter's own LaTeX output reads back exactly.

## What the symbols mean

The IR's semantics apply, and the notation does not change them:

| notation | meaning |
|---|---|
| ℤ | unbounded integer (fixed-width targets agree inside their width, as for every source) |
| ℝ | IEEE binary64. It is called ℝ because a reader expects that name, but the arithmetic is floating point |
| ℕ | ℤ with the domain n ≥ 0 (a `requires`, not a truncating type) |
| `a / b` | real division, so `n(n+1)/2` is ℝ. Write `⌊a/b⌋`, `a ÷ b` or `a // b` for floor division |
| `a mod b` | the remainder with the sign of b, as in Python; defined on ℤ only |
| `x^k` | integer power on ℤ, binary64 `pow` otherwise |
| `=` | definition at the head of an equation, equality inside an expression |
| `sqrt exp log sin … gcd min max` | op cards; any op card is also callable by its lower-case name (`bit_xor(a, b)`) |
| `π`, `e` | binary64 constants (`e` only when nothing named e is in scope) |

Equations that call each other only in tail position (`fibk` and `gcd` above, or the equations of a loop nest) are
lowered to one loop, so they run in constant stack in every target. Other recursion stays recursion.

Lists are values: `xs[i ↦ v]` is a new list and never changes `xs`. When nothing reads the old list again
(`xs = xs[i ↦ v]` as the last binding before a tail call), the update is done in place, and a parameter that is
updated is copied once on entry. So a loop that fills a list costs what the imperative loop costs.

## Code as math

The emitter turns an imperative function into a system of equations. Straight-line code becomes where-bindings,
an `if` becomes cases, and each loop becomes a recursive equation over the variables it carries (a loop is a
fixpoint). The equations are then simplified, and every rewrite keeps the meaning exactly. Unread parameters are
dropped through a fixpoint over the calls. A binding read once is substituted, unless its value could fail or
one of its variables is re-bound first. Trivial equations are inlined.

```
collatz_steps : ℤ → ℤ
collatz_steps(n) = collatz_steps_loop1(n, 0)

collatz_steps_loop1 : ℤ × ℤ → ℤ
collatz_steps_loop1(n, steps) = let n = { ⌊n / 2⌋ if n mod 2 = 0; 3 · n + 1 otherwise } in collatz_steps_loop1(n, steps + 1)   if n > 1
                              = steps   otherwise
```

## Limits

* Lists hold ℤ or ℝ, one level deep (no nested lists, no strings). Matrices are flat row-major lists with their
  sizes, as in the IR.
* An emitted list loop reads as recursive equations over its state, not as Σ or `[e | i < n]`: the emitter does not
  yet recognise a reduction or a tabulation in the loops it is given.
* Machine state (globals, arrays, stores, switch, void functions) is not emitted as math. It is reported as an
  `EmitGap`.
* A Σ of floats adds left to right, as the IR does. Binary64 addition is not associative, so a reordered sum is
  a different function.
* The LaTeX reader covers the subset above. It is not TeX.
