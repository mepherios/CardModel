# MATH_CORE: the card model as mathematics

**Status: approved by the user on 2026-10-22** ("Yes to MATH_CORE.md: start phase 0 and phase 1, and tell the
sessions to stop adding imitation-only paths"). The center of the design is in GOALS.md ("What the card model
is"). Progress:
* phase 0, done:
  * F1 and F2, the prime ledger and content vectors (`engines/godel.py`, CM43);
  * F3, the core types (`cards/core_type`);
  * F4, the e-graph (`engines/egraph.py`, `cardmodel distill`);
  * F5, symbolic instruction terms (`machine/symbolic.py`, `cardmodel symbolic`): the 512 LR35902 cards, 511
    witnessed against their executable semantics, the CB prefix a dispatch. The ARM cards are next.
* phase 1: the four source registries, with definitions for every algorithm and function card, actions,
  transformations and methods (`engines/sources.py`, `cardmodel sources`, CM44).

## 0. The goal, in the user's words

* *"Gödel numbers are fact, but we can have different and infinitely expanding Gödel sets; that is where it
  becomes special. We have basis Gödel numbers, then we use the same logic for programming languages, and math,
  and physics, and we make them carry over infinitely: a universal Gödel expanding model. That is what the card
  model is supposed to be."*
* *"Source of truth, source of action, source of transformation, source of method: we need to define these all
  structurally in our card method and all its mathematical capabilities, optimize for it, and adhere to that as
  truth. Gödel's numbering allows special abilities for definitions of models, of any model, through common factors
  which can decipher common logic: the factor, not the structure, carries, and we can use it infinitely to
  redefine solutions. The goal of my build is to make the foundations strong and universally applicable."*
* *"Our method of actual solving through the card model versus how it is built is very different from what I
  wanted. It is supposed to distill and internally understand everything mathematically, which is how we can
  optimize and solve code from binary itself instantly."*
* *"All code and projects should be mathematically explained and written, and optimized for their solution, as
  definitions. That way we can optimize and redefine infinitely, and unreadable Lean proofs can be written as
  good ones."*

## 1. The center: one expanding Gödel model

GOALS.md states it. In brief:
* atoms get primes in an append-only ledger;
* every domain (programming languages, mathematics, physics, ...) is a Gödel set that extends the basis B₀;
* a concept has two numbers: its **content** (the factorization: constituents with multiplicity, which carries
  between domains) and its **structure** (Gödel's positional number, which is its identity);
* a translation between domains is a homomorphism, fixed by where it sends each prime, and what it cannot send is
  its gap;
* GCD and LCM over the universal ledger find the logic any two things share.

## 2. The four sources, around that center

| source | what it is | cards | its Gödel role |
|---|---|---|---|
| **truth** | a definition: the mathematics of a thing, as a term in the semantic core (section 4), with its canonical form and its proof obligations | `definition` (new); today `op`, `algorithm`, `function`, `theorem` hold pieces of it | an atom takes a prime; a composite has a content vector and a structural number |
| **transformation** | an equivalence between two truths: rewrite, redefinition, law, identity. It is proved (or witnessed, said so) and carries a cost | `transformation` (new); today `rewrite_rule`, `redefinition`, `functional_identity`, `xleq` | an edge between two numbers with equal behaviour; a homomorphism between Gödel sets is a transformation of a whole domain |
| **action** | what is done from a truth: code emitted in a language, an effect at the boundary (I/O, screen, network). Always derived from a truth, with the proof or witness that links them | `action` (new); today the forms on cards, the language cards' templates, builds, the effect shells | an action's content is its truth's content mapped into the language's Gödel set |
| **method** | a procedure the model runs to get from one source to another (distill, extract, symbolically execute, prove, witness), with its complexity and its limits | `method` (new); today the engines, described by the capability cards | methods have numbers too, so the model can reason about its own procedures |

**The law** (proposed, to be numbered from the registry when approved): every artifact traces back to the four
sources. Every action names its truth and its method. Every transformation names its two truths and its proof.
Every truth names its origin (observed, lifted, written, imported). **Optimizing** is finding the cheapest proven
chain truth → transformations → action, produced by a method.

## 3. Audit: what understands and what imitates (2026-10-22)

The user's diagnosis is right. The build went deep on computation (running, emulating, lifting to run faster,
comparing outputs) more than on understanding (terms, canonical forms, proofs). By lines of engine code it is
about even: 10,042 lines that build terms, laws, proofs and canonical forms against 8,349 that run, emulate,
witness or substitute. The artifacts show where the gap is:

| artifact | count | understood (term + canonical form + proof) |
|---|---:|---|
| theorem cards | 1,650 | 1,579 proved by the Lean kernel: understood |
| rewrite rules | 114 | all witnessed, 47 Lean-proved |
| redefinitions | 111 | 91 proved symbolically, 16 numerically, 4 inconclusive |
| algorithm cards | 19 | 5 have a canonical form (Gödel number); none has a proof of its forms' equality |
| function cards (learned, lifted) | 21 | 0 proved: each form is witnessed by running |
| instruction cards (LR35902, ARM) | 679 | exact semantics, executed concretely: 0 symbolic terms |
| lifted ROM code (Game Boy, DS, AnyPS5's lifter) | per run | specialised to run fast: none canonicalized or named |

| subsystem | role today | understands? | the gap |
|---|---|---|---|
| the card IR, op cards (engines/ir.py) | terms over reference semantics | yes | integers are unbounded; there is no first-class fixed-width bit-vector or memory-array type |
| Python frontend | Python → IR terms | yes, for a subset | no strings, lists, classes |
| rewrite search, laws, theorems, Lean | equational reasoning and proofs | yes | rules are applied by search, not saturated; no e-graph |
| function algebra | behaviour classes, Gödel numbers, GCD of functions | yes, from sampled behaviour | forms are found from values and checked on unused terms, not proved |
| redefinitions | identities, verified | partly | numeric checks for 16 |
| card language and logic | representation, derivations with proofs | yes | none here |
| instruction cards | exact per-instruction semantics | yes, but only executed | no symbolic execution |
| lifting (machine/lift.py, lift_arm.py) | IR blocks compiled to run | imitates | the terms exist and are thrown away after compiling |
| emulation, survey, test ROMs, differential runs | running and comparing | imitates | correct as witnesses, wrong as the method |
| improve, arena | substitution by behaviour matching | partly | certificates are samples, not proofs |
| translate, conformance | emission from IR terms | partly | the emission is witnessed by running, never proved |
| observe, learn | counting and naming | no | statistics, not semantics |

## 4. The target: one semantic core everything goes through

* **Terms.** Fixed-width bit-vectors BV(w) with their exact operations, unbounded integers, booleans, arrays
  (memory is an array BV(a) → BV(8)) and tuples. Functions are terms over these. A loop is a fixpoint, and when
  it is a linear recurrence its closed form comes from the function algebra. Effects exist only at the boundary
  cards (CM21, CM34).
* **Into terms.**
  * Python, through the existing frontend, extended.
  * Binary, through *symbolic execution of the instruction cards*: the same card-language semantics, run over
    BV variables instead of values, give each instruction and then each function a term.
  * C, through a frontend still to write.
  * Lean, through the existing import.
* **Distill.** Equality saturation (an e-graph) over the rewrite rules, laws and redefinitions, within a budget.
  The output is the canonical term, its semantic hash, and a certificate (the rewrite chain, which `lean_chain`
  turns into a Lean proof).
* **Know instantly.** A library maps semantic hashes to definition cards. A function already understood is
  recognised by one lookup, from its source or its binary.
* **Optimize.** Extract the cheapest term under the cost vectors measured on this host, with the certificate.
* **Solve.** Closed forms (function algebra), bounded bit-vector equivalence (decided exhaustively for small
  widths), Lean (omega, decide, grind), and an SMT solver when the host has one (probed, never required).
* **Act.** Emit code from the definition through the language cards. Lean proves the IR-level transformations
  and running witnesses the emission (section 8 says why that split remains).
* **Readable proofs.** Proof distillation rewrites an opaque Lean proof into a structured one: a calc chain, named
  `have` steps, one lemma per step, a prose gloss. Lean re-checks it, and readability is measured (steps per
  lemma, names, no unexplained `decide` over large terms).

## 5. Formats

**Definition (truth).**

```json
{
  "name": "triangular", "category": "definition",
  "math": {"text": "T(n) = n(n+1)/2", "latex": "T(n)=\\tfrac{n(n+1)}{2}",
           "term": ["FLOORDIV", ["MUL", "n", ["ADD", "n", 1]], 2], "type": "Nat -> Nat"},
  "explanation": "Markdown: what it means and why the definition is right.",
  "canonical": {"term": ["...the extracted canonical term..."], "hash": "sha256:...",
                "godel": {"structural": "decimal string", "content": {"op/ADD": 1, "op/MUL": 1, "op/FLOORDIV": 1}}},
  "proof_obligations": [{"claim": "T(n+1) = T(n) + n + 1", "status": "proved", "lean": "theorem ..."}],
  "actions": ["action/triangular__c", "action/triangular__python"],
  "transformations": ["transformation/triangular_loop_to_closed_form"],
  "origin": {"kind": "written | lifted | observed | imported", "from": "..."},
  "methods": ["method/distill", "method/extract"]
}
```

**Action**: `{"truth": "definition/...", "lang": "c", "code": "...", "method": "method/emit", "link":
{"kind": "proof | witness", "lean": "...", "seed": 123}}`.
**Transformation**: `{"from": "definition/...", "to": "definition/...", "proof": {...}, "cost": {...}}`.
**Method**: `{"procedure": "engines/...", "complexity": "...", "decides": "...", "limits": "..."}`.

**Project card**: unchanged, law CM41 (docs/INTEGRATION.md section 4b).

## 6. Migration plan

**Phase 0: foundation, adds and changes nothing (may start now)**
* **F1 the prime ledger.** An append-only pack: B₀ from the op cards and logic primitives. A test compares it with
  its git history, so no prime is ever renumbered.
* **F2 content vectors** for op, algorithm and function cards, computed beside funcalg's structural numbers.
* **F3 core types.** BV(w), arrays and tuples as type cards, plus the bit-vector op cards the instruction cards
  already use implicitly.
* **F4 an e-graph prototype** over the existing rule cards. It is measured on the arena and on the learned
  function cards.
* **F5 symbolic execution of the LR35902 cards.** Each instruction's term is checked against its executable
  semantics exhaustively over 8-bit inputs.

**Phase 1: truth (after the yes)**
* The four registries (`definition`, `transformation`, `action`, `method`) with their card types.
* Definition cards for every algorithm and function card.
* The trace-back law with its witness.

**Phase 2: understand binaries.** Symbolic execution of lifted code, distillation, the semantic-hash library, and
instant lookup.

**Phase 3: act from truth.** Emission from definitions with the IR-level proofs, and readable proofs.

**Phase 4: carry over.** The physics set (units, dimensional analysis), homomorphism cards between domains, GCD
and LCM across domains.

**Goals** (proposed, numbered from the registry when approved):

| goal | target |
|---|---|
| fraction of function and algorithm cards with a definition card | 1.0 |
| fraction of definitions with a canonical form and certificate | ≥ 0.9 |
| instruction cards with a symbolic term checked against their semantics | all 679 |
| lookup hit rate on the arena's planted functions | ≥ 0.9 |
| Lean proofs passing the readability lint | ≥ 0.8 |
| actions without a truth | 0 |

**After the yes, for every session:** no new imitation-only path. Every new feature produces or consumes core
terms, and emulation and tests are witnesses, never the method. The project cards (CM41) carry this as each
project's next steps.

## 7. Instant, decided, or search: what can be promised

| kind | what | how |
|---|---|---|
| instant | a function whose canonical form is already in the library | one hash lookup |
| decided | bounded bit-vector equivalence for small widths; linear recurrences; Presburger arithmetic | exhaustive check, Berlekamp–Massey, Lean's omega |
| search | equivalence in general, nonlinear arithmetic, loops without closed forms, proofs | e-graph within a budget, SMT, Lean tactics; the answer can be "not found", never a guessed "equal" |

## 8. Honest limits

* Equivalence of programs is undecidable in general (Rice). The core decides what section 7 says and searches the
  rest.
* Not every loop has a closed form. Some programs are best defined as recurrences or state machines, and their
  definition says so.
* A factor multiset forgets arrangement, so the canonical term (structure) stays the identity and the content
  vector is the carrier.
* Proving emitted code correct for real languages needs formal semantics of those languages, which the model does
  not have. Lean proves the term-level steps, and running witnesses the last step into each language.
* Readability is a heuristic: the lint measures it, and a person judges it.
* Lean and lake are installed (toolchain v4.35.0 under `~/.elan`), so every Lean claim here is kernel-checked, not
  linted. The readability lint is a lint.
