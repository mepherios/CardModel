# examples/algorithms

Plain Python functions used to demonstrate and witness translation:

```bash
cardmodel translate examples/algorithms/algos.py
```

That command lifts every function into the card IR, emits it in every language card, and checks every emitted form
against the original on seeded inputs. `sign_sum` (a `list` parameter) is reported as a translation gap, never pasted
through. `cardmodel learn examples/algorithms --promote --global` stored the agreeing ones as `function` cards in the
model, so `cardmodel verify` re-checks them on every run.
