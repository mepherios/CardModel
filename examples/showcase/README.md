# Showcase: one small Python module through the card model

`showcase.py` holds seven plain numeric functions: `poly` (3x²+2x+1), `sum_to` (a loop 1+…+n), `triangle`
(n(n+1)/2, the closed form of the same thing), `gcd` (Euclid), `isqrt` (integer square root by counting), `clamp`
and `mean` (over a `list[int]`). `run.sh` runs real `cardmodel` commands on it; nothing below is hand-written
output. Run it yourself:

```bash
examples/showcase/run.sh
```

Outputs are trimmed (long rule lists cut with `…`). Seeds print on every witnessed step; `--seed 7` reproduces.

## 1. Translate to six languages, witnessed

```
$ cardmodel translate showcase.py --to rust,go,c,javascript,ruby,lua --seed 7
seed 7
  poly                   agrees in 7: python_source, c, go, javascript, lua, ruby, rust
  sum_to                 agrees in 7: python_source, c, go, javascript, lua, ruby, rust
  triangle               agrees in 7: python_source, c, go, javascript, lua, ruby, rust
  gcd                    agrees in 7: python_source, c, go, javascript, lua, ruby, rust
  isqrt                  agrees in 7: python_source, c, go, javascript, lua, ruby, rust
  clamp                  agrees in 7: python_source, c, go, javascript, lua, ruby, rust
  mean                   agrees in 7: python_source, c, go, javascript, lua, ruby, rust
```

**Proves:** every function lifts into the IR, is emitted in each language, compiled/run there, and gives the same
result as the Python original on the same seeded inputs. "Agrees" is a witness (it ran and could have failed), not a
proof for all inputs.

## 2. Two implementations collapse to one identity

```
$ cardmodel algebra form showcase.py:sum_to
showcase.py:sum_to: polynomial of degree 2
  f(n) = 1/2*n^2 + 1/2*n
  annihilator E^3 - 3*E^2 + 3*E - 1   checked on 18 unused terms
  Gödel number 201493532663944988…725323906250 (60 digits)
$ cardmodel algebra form showcase.py:triangle
showcase.py:triangle: polynomial of degree 2
  f(n) = 1/2*n^2 + 1/2*n
  annihilator E^3 - 3*E^2 + 3*E - 1   checked on 18 unused terms
  Gödel number 201493532663944988…725323906250 (60 digits)
$ cardmodel algebra gcd showcase.py:sum_to showcase.py:triangle
operators: gcd E^3 - 3*E^2 + 3*E - 1  lcm E^3 - 3*E^2 + 3*E - 1  (cofactors 1 | 1)
composition: g = Q(f) with Q(x) = x
values: common factor n^2 + n, cofactors 1/2 | 1/2; (1) * f(n) == (1) * g(n)
```

**Proves:** the loop and the closed form have the same canonical behaviour (the same polynomial, the same annihilating
recurrence operator, the same Gödel number of that canonical form); their GCD as functions has cofactors 1 | 1, i.e.
they are one function. The recurrence is fitted and then checked on 18 terms not used to fit it (a measured claim,
not a symbolic proof of the loop).

## 3. E-graph: canonical forms and equality

```
$ cardmodel distill "3*x*x+2*x+1"
((((3 * x) + 2) * x) + 1)   cost 8.0   sha256:8cf3305ce141769aa01324dd
4 iterations, 36 nodes, saturated; equalities used: …
$ cardmodel distill "x*(2+3*x)+1" "3*x*x+2*x+1"
equal; witness witnessed on 64 inputs (seed …); equalities used: …
$ cardmodel distill "n*(n+1)/2" "(n*n+n)/2"
equal; witness witnessed on 64 inputs (seed …); equalities used: …
$ cardmodel rewrite --prove "a*(b+c)" "a*b+a*c"
  [start] (a * (b + c))
  [distributivity_left] ((a * b) + (a * c))
```

**Proves:** equality saturation extracts `poly`'s cheapest form (Horner, cost 8) and a semantic hash for it; two
spellings of `poly` and two of `triangle` land in the same e-class (equal by the named rewrite rules, each of which is
a witnessed card), double-checked on 64 random inputs. `rewrite --prove` prints the rule chain.

## 4. Gödel structure on canonical terms

The terms here are the canonical forms from step 3 (`poly`) and the canonical form the model already holds for
clamp (`MAX(MIN(hi, x), lo)`, card `definition/fn__fn_clamp_…`).

```
$ cardmodel godel similar --expr "((((3 * x) + 2) * x) + 1)" --limit 3
((((3 * x) + 2) * x) + 1) (the expression): {'op/ADD': 2, 'op/MUL': 2}
  1.000  definition/alg__sum_of_cubes: shares {'op/ADD': 2, 'op/MUL': 2}
  1.000  definition/fn__fn_xp_for_level_0634eac7a068: shares {'op/ADD': 2, 'op/MUL': 2}
  0.750  definition/alg__sum_of_squares: shares {'op/ADD': 2, 'op/MUL': 1}

$ cardmodel godel cofactor definition/alg__cubic_eval --expr "((((3 * x) + 2) * x) + 1)"
definition/alg__cubic_eval (canonical term): {'op/ADD': 3, 'op/MUL': 3}
((((3 * x) + 2) * x) + 1) (the expression): {'op/ADD': 2, 'op/MUL': 2}
cofactor definition/alg__cubic_eval / ((((3 * x) + 2) * x) + 1): {'op/ADD': 1, 'op/MUL': 1}

$ cardmodel godel similar --expr "max(min(hi, x), lo)" --limit 3
max(min(hi, x), lo) (the expression): {'op/MAX': 1, 'op/MIN': 1}
  1.000  definition/fn__fn_clamp_429484c35431: shares {'op/MIN': 1, 'op/MAX': 1}
  0.100  definition/alg__binomial: shares {'op/MIN': 1}

$ cardmodel godel factor --expr "(max(min(h, y), l) - a) * (max(min(h, y), l) - a)"
  = ((CALL(definition/fn__fn_clamp_429484c35431, h, y, l) - a) * (CALL(definition/fn__fn_clamp_429484c35431, h, y, l) - a))
  uses definition/fn__fn_clamp_429484c35431 (canonical term) at [0, 0]: hi := h, x := y, lo := l
  uses definition/fn__fn_clamp_429484c35431 (canonical term) at [1, 0]: hi := h, x := y, lo := l
  cofactor (what no concept covers): {'op/MUL': 1, 'op/SUB': 2}; γ(t) = γ(context) + Σ γ(instance): True
```

**Proves:** content γ is a sparse map op→count (gcd = shared logic, Jaccard ranks part-of neighbours). The Horner
cubic's content is divisible by `poly`'s (cofactor one ADD and one MUL: a cubic is a quadratic plus one Horner step).
`factor` rewrites a term over the definitions it contains (two clamps found by matching, with bindings) and the
additivity check γ(t) = γ(context) + Σ γ(instance) holds. **Does not prove** behavioural equality: content is a
structural key, not invariant under ≈_E (docs/GODEL.md §11); equality is step 3's job. The two 1.000 neighbours of
`poly` share its op counts but are different functions.

## 5. Mathematical notation round trip

```
$ cardmodel math emit showcase.py --function sum_to
sum_to : ℤ → ℤ
sum_to(n) = sum_to_loop1(0, 1, n + 1)

sum_to_loop1 : ℤ × ℤ × ℤ → ℤ
sum_to_loop1(s, it, stop) = sum_to_loop1(s + it, it + 1, stop)   if it < stop
                          = s   otherwise
$ cardmodel math roundtrip showcase.py --seed 7
seed 7 · lift(emit_math(f)) == f, on each function's vectors
  poly                     pass (29 inputs)
  …
  mean                     pass (23 inputs)
7/7 round trips agree; 0 functions have no notation (gap); 0 functions not lifted by the source frontend
```

**Proves:** each function is written as mathematics (loops become recursive equations), lifted back from that
notation, and the result agrees with the original on its witness vectors.

## Not yet

* `mean(xs: list)` (bare `list`) does not lift: `not lifted: line 40: type annotation 'list' (only int/float/bool,
  list[int], list[float])`. The module uses `list[int]`, which lifts.
* The `godel` commands do not take a source function directly: `cardmodel godel factor showcase.py:poly` gives
  `error: no card 'showcase.py:poly'` (only cards or `--expr`). Step 4 therefore passes the canonical term from step 3
  as `--expr`.
* `godel cofactor` needs closed terms on both sides: `cardmodel godel cofactor definition/alg__sum_of_squares --expr
  "n*(n+1)"` gives `error: definition/alg__sum_of_squares: no closed term (a loop, several statements, or an
  instruction)`. Loop definitions such as `sum_to` have no closed term for the Gödel layer even though step 2 finds
  their polynomial.
* `godel factor --expr "((((3 * x) + 2) * x) + 1)"` finds no stored concept inside `poly` (cofactor is the whole
  term); `godel cofactor alg__cubic_eval` reports content divisibility but `0 uses` (the cubic's term does not match
  `poly` structurally, since the coefficients differ).
