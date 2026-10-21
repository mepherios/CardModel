# The card language

One source file holds functions, logic, theorems, tests and cards, and everything in it becomes cards.

* **Functions** compile to the card IR, the same IR the Python frontend produces. So every language card can
  emit them (C, C++, Rust, Go, Swift, Java, JavaScript, TypeScript, Ruby, Lua, Lean, Python), and the
  conformance matrix checks every operator they use.
* **Logic** compiles to rule and fact cards (`engines/logic.py`).
* **Theorems** compile to theorem cards (`engines/theorems.py`).

Commands:

* `cardmodel run FILE.card` runs a file.
* `cardmodel lang build FILE.card --save` turns it into cards.
* `cardmodel lang emit FILE.card --lang rust` emits its functions.
* `cardmodel repl` is the interactive language.

## A file

```
module numbers                              -- optional; defaults to the file name
use geometry                                -- another .card file in the same folder

fn fib(n: Int) -> Int requires 0 <= n, n <= 90 {   -- `requires`: the domain contract (verification inputs)
  var a = 0
  var b = 1
  for i in 0 .. n { (a, b) = (b, a + b) }
  return a
}
fn sq(x: Int) -> Int = x * x                -- expression body
factorial : Int -> Int = match n with       -- the Pheros CL v0 form, accepted as-is
  | 0 -> 1
  | k -> k * factorial(k - 1)
fn fast(n: Int) -> Int = algorithm.fibonacci(n)   -- a card reference, resolved to the cheapest verified form

parent(alice, bob).                         -- a fact (`fact` keyword optional)
rule step: ancestor(X, Z) <- parent(X, Y), ancestor(Y, Z).   -- a labelled rule (`:-` also works)
root(X) <- parent(X, _), not parent(_, X).  -- negation; `_` under `not` means "for no value"
gap(P, C, G) <- parent(P, C), born(P, A), born(C, B), G = B - A.   -- bindings use op cards
size(X, N) <- root(X), N = count { ancestor(X, _) }.               -- count / sum V / min V / max V { ... }
big(N) <- num(N), sq(N) > 100.              -- rules may call functions
never: ancestor(X, X).                      -- a constraint (`constraint name: ...` to label it)
query ancestor(alice, Who)?                 -- printed by `cardmodel run`

theorem add_comm(a: Int, b: Int): a + b == b + a
theorem pred_lt(n: Nat) requires n > 0: n - 1 < n           -- hypotheses; `==>` and `<=>` inside statements

test fib(10) == 55                          -- a function test (must be true)
test ancestor(alice, dave) and not ancestor(dave, alice)    -- a logic test (provable / not provable)

card blade : item { damage: 12, tags: [steel, slash] }      -- any card, in any registry
```

## Lexical rules

* Comments are `--` or `#` to the end of the line, or `(* ... *)`, as in CL.
* Newlines end declarations and statements, except inside `( )` and `[ ]`. Logic clauses run until their
  final `.`, so they can span lines.
* Numbers: `42`, `0x2a`, `0b101`, `1_000`, `2.5`, `1e9`. Strings are `"..."` with the usual escapes.
* In logic, a name that starts with an upper-case letter or `_` is a variable. Any other name is a symbol.
  `_` on its own is a fresh anonymous variable. Quote a symbol that starts with an upper-case letter:
  `"Bob"`.
* `op.ADD(x, y)` (or `@ADD(x, y)`) calls an op card directly. `algorithm.NAME(...)` calls an algorithm card.

## Types and semantics

* **Types** are `Int` (mathematical integer, unbounded, the IR's reference semantics), `Float` (binary64),
  `Bool` and `Nat`. `Nat` is a domain annotation: an `Int` that is ≥ 0. It does not truncate subtraction.
  Theorems over `Nat` are sent to Lean as `Int` with `0 ≤ n` hypotheses, so they mean the same thing there.
* **Operators**:
  * arithmetic `+ - * / // % **`: `/` on integers is float division, `//` and `%` floor as in Python, and
    `Int ** Int` needs a literal exponent ≥ 0;
  * comparison `== != < <= > >=`, which can be chained;
  * bitwise `& | ^ ~ << >>`;
  * logical `and or not` (also `&& || !`), and `if c then a else b`.
* **Built-ins**: `abs min max gcd float int pow(a, b[, m])`.
* **Statements**: `let`/`var`, assignment and `+= -= *= //= %=`, the parallel assignment `(a, b) = (b, a)`,
  `if/elif/else`, `while`, `for i in a .. b [by k]`, `return`, `break` and `continue`.

## What `cardmodel run` checks

* **Tests**: a function test must be true; a logic test must be provable, or not provable for `not`.
* **Queries** are answered.
* **Constraints** must never fire. A violation comes with its proof.
* **Theorems** are witnessed. The witness has an exhaustive small-value phase, then seeded random values,
  with anti-vacuity: enough inputs must satisfy the hypotheses, and no variable may be pinned to one value.
  * A theorem whose hypotheses bound every variable to a box of at most 20,000 points is checked at every
    point. That is proof by exhaustion.
  * `--lean` sends the rest to the Lean kernel (core tactics `decide`, `omega`, `grind`, `simp`).
  * `--deep` adds library search (`exact?`).

## Compilation

1. parse (`lang/syntax.py`);
2. check and compile (`lang/compile.py`): types, safe rules (every variable bound by a positive literal or
   a binding), stratified negation, and resolution of `algorithm.` references;
3. evaluate or emit (`lang/run.py`, `engines/codegen.py`).

This is the Pheros CL compilation model (parse, typecheck, resolve, emit), with a logic and a theorem
layer on top.

## Limits

* No strings, lists, user types or closures inside functions. The IR is int/float/bool (see ROADMAP).
* Logic terms are constants: there are no function symbols.
* Rule evaluation has a fact budget.
