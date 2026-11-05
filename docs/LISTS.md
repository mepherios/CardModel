# Lists and transformer math

The IR has two list types, `list[int]` and `list[float]`. They are enough to write the linear algebra of a
transformer as plain loops over flat row-major matrices, lift it from Python, emit it in every codegen language,
and check each target against the original numerically.

```
cardmodel translate examples/transformer/transformer.py      # 13 kernels, every available language
```

| kernel | what it computes |
|---|---|
| `dot`, `matvec`, `matmul`, `transpose`, `add` | linear algebra on flat row-major matrices passed with their sizes |
| `softmax` | the numerically stable form (subtract the maximum first) |
| `layernorm` | mean and variance per vector, eps 1e-5, then scale and shift |
| `gelu`, `relu` | activations (gelu is the tanh approximation) |
| `attention` | softmax(q kᵀ / √d) v for one head |
| `feed_forward`, `block` | gelu(x W1) W2, and a pre-norm attention block with its residual |
| `argmax` | the index of the largest logit |

Every kernel agrees with the Python original in C, C++, Go, Java, JavaScript, Lua, Python, Ruby and Rust. Lua's
standard library has no `tanh`, so its card language defines one (`cm_tanh`: a Taylor series below 0.05, the exp
form above, within 2e-15 of libm). Swift and TypeScript are emitted but need their toolchains to run. Lean has no
list templates.

The same kernels in mathematical notation are in
[examples/transformer/transformer.math](../examples/transformer/transformer.math), and every Python kernel also
round-trips through math: `cardmodel math emit examples/transformer/transformer.py` writes them as equations, and
`cardmodel math translate` on that output runs them in every target again.

## Semantics

Lists are values. A function never changes a list it was given, and two names never share one list. The frontend
enforces this (`ir.check_lists`) and reports anything else as unsupported:

* a list parameter is never written or re-bound, and is never returned as itself;
* `ys = xs` is rejected, because it would share one list under two names. Write `ys = list(xs)` or `xs[:]`;
* a local list is built fresh: `[0.0] * n`, `[e for i in range(n)]`, `[a, b, c]`, `list(xs)`, `xs.copy()`.

Because of these rules every target can pass a list as a pointer, slice or array reference without copying, and
the results still match Python's.

| IR | Python | meaning |
|---|---|---|
| `["LEN", xs]` | `len(xs)` | the length, as int |
| `["GET", xs, i]` | `xs[i]` | an element. An index outside `0 ≤ i < len` is an error in every target (no wrap-around) |
| `["LIST_NEW", n, v]` | `[v] * n` | a new list of n copies of v (n < 0 is an error) |
| `["LIST_COPY", xs]` | `list(xs)` | a new list with the same elements |
| `{"k": "set", "target": xs, "index": i, "value": v}` | `xs[i] = v` | write one element of a local list |

`for x in xs` lowers to a loop over the indices. A comprehension `[e for i in range(n)]` gets its own loop
variable, as in Python.

## Verification

Generators for list parameters are inferred like the others. A list's length can be free (`"len": [lo, hi]`),
the product of one or two int parameters (`"len_of": [i, j]`, a matrix passed with its dimensions), or the length
of an earlier list (`"len_like": i`). Domain inference tries the dimension-tied shapes first and keeps the shape
under which the function nearly always runs (`translate._list_shapes`).

A list result is printed as `l:<n>` followed by its n elements, and compared element by element with the same
tolerance as scalars.

## Not yet

* `sum`, `max` and `min` over a list are not lifted. Python 3.12 and later compensate a float `sum`, so a plain
  loop in another language would not match it. Write the loop.
* No append, slicing other than `xs[:]`, negative indices, nested lists or other element types.
* Lean has no list templates (an `EmitGap`).
