# LEARNING: the model learns from its basics

> Owner's direction (mepherios, 2026-11-17): CardModel is a public project for understanding all computation on
> computers and in programs. Its core ability is **learning**: understanding inputs and generalising from them, the
> way an ordinary AI model learns, instead of answering from hand-written or memorised knowledge. The whole model
> should learn from its basics. It should never use something complex where something basic is enough, and it
> should never just have its logic written for it. Any method is welcome, AI methods included, as long as the logic
> is learned.

This document says what the basics are, what has been built so far, how to run it, and a map of everything the
model can do today. For each part, the map gives what is still hand-written and how that part can be learned
instead.

## 1. The basics, and nothing else

The basic model is the part that stays written by hand, because everything else is learned *from* it:

| basic | where | why it stays |
|---|---|---|
| the op cards' reference semantics (`ir.eval`, `ir.types`) | `cards/op/*` | the atoms of computation; one line of meaning each |
| the IR and its interpreter | `engines/ir.py` | how atoms compose; the judge of every learned program |
| the card store | `kernel/` | memory: where learned things are kept with their evidence |
| probes and runners | `engines/probes.py`, `engines/runners.py` | the senses: how the model runs a real compiler or program and observes it |
| description length (bits) | `engines/induce.py` | the one preference: the shortest explanation that keeps working is the understanding |

Everything above this line is a candidate for learning. The test for each piece is: *could the model have found
this itself, from the basics and from observed behaviour?* If it could have, the hand-written version is debt.

## 2. What is built: `engines/induce.py`

`induce` learns a computation from **behaviour alone**. It is shown input/output examples, or a black box it may
question, and it has to find a program that explains them and keeps explaining new inputs.

* **Hypotheses are built from the op cards, not stored.** Terms are enumerated bottom-up over every op card with
  scalar semantics (plus IF_EXPR, AND, OR and the concepts learned so far). Two terms that behave the same on every
  example seen count as one hypothesis (observational equivalence).
* **Occam as MDL.** The chosen program minimises the bits to write the program plus the bits to correct its
  mistakes. Memorising costs more bits than the data, so a lookup table is never chosen. A task counts as
  *understood* only when the program is shorter than everything it explains. When two programs are equally long,
  the basic one wins: the cheaper one by the op cards' own costs.
* **Generalisation is measured.** Examples are split into a training part and a held-out part. A black box is
  questioned: fresh inputs are drawn, every counterexample is added to the training set, and the model learns
  again until its program survives a round of questions.
* **Noise is tolerated.** With `--noise`, a short program that explains all but a few examples beats a long one
  that fits every example exactly.
* **Concepts: learning to learn.** A sub-program that recurs across *different* understood tasks is abstracted
  over its variables, or over a whole sub-term (a hole), into a `concept` card. A concept is one node in later
  searches, so tasks that need it become shorter and cheaper to find. Concepts build on concepts.
* **Into the core.** A learned program inlines its concepts into a plain IR function and is re-checked by the IR
  interpreter. From there it is like any lifted function: translate, optimize and laws take it.
* **Run by the model itself.** The self cycle has an `induce` step (`cards/self_step/induce`). It runs every 24
  hours or when the op or concept cards change, keeps the concepts in the self layer, and reports the tasks that
  are not understood yet.

### Measured learning curve (`cardmodel --no-project induce bench --seed 1`)

The 13 built-in black boxes are things like square, clamp, max of three, is-even, squared error and Manhattan
distance. The learner sees only the answers to its own questions.

| round | concepts known | understood | terms searched |
|---|---|---|---|
| 0 | none | 10 / 13 | 26.9 M |
| 1 | 2 (`MUL(x0, x0)`, `ABS(SUB(x0, x1))`) | 11 / 13 | 15.7 M |
| 2 | 3 (adds `SQ(SUB(x0, x1))`, built on the first concept) | 11 / 13 | 13.1 M |

What the curve shows:

* **New concepts make new tasks reachable.** The scaled squared error `k·(a−b)²` is out of reach in round 0 and
  understood in round 1 as `MUL(k, SQDIFF(a, b))`.
* **The same understanding costs half the search.** Round 2 understands what round 0 did with half the terms
  searched.
* **Some programs are found, not given.** The model found `is_even` as `CMP_NE(0, CTZ32(x))`, a bit-level program
  nobody wrote down, and it generalises.
* **Ties go to the basic form.** `(a+b)//2` is learned as `SHIFT_RIGHT(ADD(a, b), 1)` and `x²+1` as `ADD(1, SQ(x))`,
  the cheapest of the equally short programs by the op cards' own costs.
* **Two tasks are still out of reach:** squared distance and Manhattan distance, both 4-variable programs of size 7.
  They need a faster search at the top of the term (§4, item 1), not more hand-written knowledge.

## 3. How to run it

```bash
cardmodel induce bench [--save] [--tasks a,b] [--seed S]      # the learning curve; --save keeps the concepts as cards
cardmodel induce fit examples.json [--noise 0.1]              # learn one computation from a file of examples
cardmodel induce concepts                                     # what the model has abstracted so far
cardmodel self run --only induce                              # the same, as a step of the model's own cycle
```

`examples.json` looks like `{"name": "gap", "params": [["a", "int"], ["b", "int"]], "examples": [[[3, 7], 4], ...]}`.

## 4. Map: everything the model does, and how each part becomes learned

Every capability, with the command that runs it, what is hand-written in it today, and how that logic can be
learned from the basics instead. S, M and L are sizes. "Keep" means the piece is a basic, a policy or a definition,
not logic to learn.

### Core reasoning

| capability | run | hand-written today | learned instead | size |
|---|---|---|---|---|
| learn cards from code | `cardmodel learn PATH --promote` | evidence thresholds (`learn.py:43-45`), call grouping by name | promote by MDL (a card is kept when it compresses the corpus); send unliftable calls through `induce` as black boxes | M |
| law discovery | `cardmodel laws --save` | about 25 law templates as literal shapes (`laws.py:106-172`), the constants table | enumerate equations l = r up to a size with the `induce` enumerator, and keep those that survive evaluation | M |
| proof and optimisation search | `cardmodel rewrite --prove L R`, `--optimize EXPR` | blind BFS with fixed budgets (`search.py:157-233`) | learn which rule to try first from stored proof traces | M |
| form choice | `cardmodel rewrite CARD` | a fixed 5-step selection rule, declared costs | rank by measured cost (metric cards) | S |
| e-graph, canonical identity | `cardmodel distill EXPR` | tie-break order | extraction cost from measurements | S |
| behaviour algebra (Berlekamp–Massey) | `cardmodel algebra form\|gcd\|total` | MAX_ORDER = 8 | choose the order by MDL | S |
| logic mining | `cardmodel logic mine SRC` | 9 rule templates (`mine.py:1-27`) | enumerate rule bodies scored by MDL (the logic-side twin of `induce`) | M |
| theorems, Lean | used by `laws`, `run`, `lean import` | tactic list (`theorems.py:50`), edge inputs | learn the tactic order from the proof cache; edge inputs from past counterexamples | S |
| real normal form | used by `distill` | odd/even/commutative tables (`realnorm.py:31-36`), op facts in `tiers.py:142-185` | read them from the law cards that `laws` already discovers | M |
| float model of runners | used by `analyse`, `matrix` | FMA/FTZ tables per ISA (`numeric.py:63-81`) | measure each runner with the existing probe and store the results | M |
| expression and logic syntax | library | op-to-syntax maps (`exprs.py:27-44`, `logic.py:191-195`) | derive them from the op cards' own forms | S |
| Gödel ledger, codes, Gödel 1931 | `cardmodel godel ...` | definitions | keep (bookkeeping and a reference spec) | – |

### Reading and writing languages

| capability | run | hand-written today | learned instead | size |
|---|---|---|---|---|
| Python lift | `cardmodel translate f.py`, `lift-sweep DIR` | AST-to-op tables (`frontend_python.py:48-61`) | map each library call to an op by running it on probes and matching the outputs to `ir.eval`, or to an `induce` program | S |
| 15-language lift | `cardmodel translate f.c --from c` | precedence, `/` and `%` meaning, int width, library tables (`frontend_text.py:39-328`) | fit each fact by compiling probe programs (`a-b*c`, `-7/2`, overflow) with the real compiler and comparing with `ir.eval` | M–L |
| code generation | `cardmodel emit SRC --lang L` | 93 op `emit` templates, typed by hand into language cards | search small template shapes (`({0} OP {1})`, `f({0},{1})`, ...) and keep the first that conformance verifies | M |
| op × language conformance | `cardmodel verify --only conformance` | test programs | this is already the oracle: turn the "gap" cells into a synthesis loop | S |
| analyse (divergence laws) | `cardmodel analyse F --to c,c@O0` | partiality table and hand-stated laws (`analyse.py:57, 367-466`) | learn partiality from where `ir.eval` raises; learn divergence guards by differential runs and `induce` | M |
| effects of calls | `cardmodel logic code DIR` | name-to-effect table (`codefacts.py:20-27`) | label effects by running functions and watching for nondeterminism and I/O | M |
| opaque boundaries | library | a host interpreter | try `induce` on each opaque function's own input/output to turn partial into lifted | M |
| card language, matrix, runners, probes | `cardmodel run`, `matrix`, `probe` | keywords, harnesses | keep (the language definition and the senses) | – |

### Machines, optimisation, the self cycle and domains

| capability | run | hand-written today | learned instead | size |
|---|---|---|---|---|
| ISA instruction cards (679) | `cardmodel isa build\|check` | the semantics in `tools/gen_lr35902.py` and `tools/gen_armv5te.py` | `induce` on before/after machine states from `machine/bench.py`, checked by `symbolic.py`; the carry logic and the ALU come out as concepts | L |
| ROM lifting, emulation | `cardmodel emu ROM`, `machine lift` | control flow read from mnemonic text (`machine/lift.py:190-215`) | compute the next addresses from each instruction card's PC term | M |
| self cycle plan | `cardmodel self run` | severity table and ranking (`selfrun.py:66`) | rank actions by how much they moved goal values in past runs | M |
| step scheduling | `cards/self_step/*` | fixed intervals | learn each interval from how often the step found something new | S |
| optimise, improve | `cardmodel optimize`, `improve F` | cost anchors, edge inputs (`improve.py:68-72`) | fit a cost model to the measured metric cards; edge inputs from past counterexamples | M |
| arena | `cardmodel arena` | hand-written test programs (`arena.py:37-124`) | generate test programs from learned concepts and inverted laws | M |
| environment | `cardmodel env --measure` | the cache-level ratio | cluster the measured latency curve | S |
| Unreal, AnyPS5 | `cardmodel unreal ...`, `anyps5 ...` | regex tables for uses and causes | classify by Gödel content similarity and by witnessed outcomes | M |
| game AI | `cardmodel game ...` | fixed epsilon and decay | tune them from tournaments (a bandit) | S |
| kernel, integrity, capabilities, docs | `verify`, `docs --check` | policy | keep | – |

## 5. Order of work (most foundational first)

1. **Faster search at the top of a term.** Use the laws the model discovers (for example, that SUB undoes ADD) to
   invert the top operator and meet in the middle. This reaches 4-variable programs of size 7 and beyond, and it is
   learned, because the inverses come from law cards.
2. **Laws by enumeration instead of templates.** Run `laws` on the `induce` enumerator, so the rewrite rules and
   the canonical identity come from what was found, not from 25 shapes.
3. **Languages by probing.** Learn the frontend dialect facts and the `emit` templates from the real compilers,
   with conformance as the oracle.
4. **Machines by tracing.** Learn instruction semantics from execution traces.
5. **Values beyond int and bool.** Lists, strings and floats in `induce`, then loops and recursion through concepts
   (funcalg's recurrences are the first case).
6. **Learned priors.** Weight the search by how often each op and concept was used in understood programs: the
   vocabulary's prior is itself learned.
7. **Measured costs and plans.** Replace cost anchors and the self cycle's ranking with models fitted to the
   model's own measurements.

## 6. Honest limits today

`induce` handles scalar `int` and `bool` values and expression programs. Search is exhaustive by size within a
budget, so "not found" means not found within that budget, not that no program exists. Held-out accuracy and
passed questions are evidence on sampled inputs, not proof. A learned program becomes a theorem only through the
laws engine and Lean, like every other card.
