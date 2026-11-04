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

A function whose only self-calls are tail calls (`fibk`, `gcd` above) is lowered to a loop, so it runs in constant
stack in every target. Other recursion stays recursion.

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

* No lists or strings in the notation yet. The IR has `list[int]` and `list[float]` ([LISTS.md](LISTS.md)), and
  the transformer kernels (matrices, softmax, layernorm, attention) lift from Python and verify in every target, but a
  function with a list parameter is not emitted as equations: it is reported as an `EmitGap`.
* Machine state (globals, arrays, stores, switch, void functions) is not emitted as math. It is reported as an
  `EmitGap`.
* A Σ of floats adds left to right, as the IR does. Binary64 addition is not associative, so a reordered sum is
  a different function.
* The LaTeX reader covers the subset above. It is not TeX.
