# Crystallised knowledge: logic, theorems, laws and Lean

A statement in the card model is only as strong as its evidence (law CM23):

| status | meaning |
|---|---|
| refuted | a counterexample, shown (the smallest the exhaustive phase finds) |
| conjecture | not yet checked |
| vacuous | the hypotheses rarely hold, or pin a variable to one value: a "law" about a point is no law |
| witnessed | an exhaustive small-value phase and seeded random values (edges included) all agree |
| proved | the Lean kernel accepted a proof, or every point of a finite hypothesis box was checked (`exhaustive`) |

The ladder only moves up with evidence. A proof never overrides a counterexample. `cardmodel verify`
re-witnesses every theorem card with a fresh seed, and fails if any card claims more than its evidence.

## Four sources of theorem cards

1. **Discovered laws** (`cardmodel laws`). Templates are instantiated over every op card: commutative,
   associative, idempotent, identity, absorbing, self-cancel, distributive, absorption, involution,
   homomorphism, duality (De Morgan), pull-through, monotone and antitone, bounds, and the properties of
   relations. Partial operators carry their definedness as hypotheses.
   * A run with seed 20261021 tested 1,520 candidates: 1,336 refuted, 23 vacuous, 161 hold, 90 of them
     proved by Lean. One look-alike, `a % max(b, c) == max(a % b, a % c)`, is refuted at a = −3, b = −3, c = −2.
   * The 96 laws that simplify became rewrite rules (`cards/rewrite_rule/_pack_laws.jsonl`), each citing its
     theorem card. So the knowledge carries into `rewrite --optimize` and `improve` (CM25).
2. **Card-language theorems**: `theorem name(params) requires hyps: statement` in any `.card` file.
3. **Lean files** (`cardmodel lean import FILE.lean`, or `--core` for Lean's own `Init/Data/{Nat,Int}`).
   Each theorem in the arithmetic fragment goes through four steps:
   1. **Read with Lean's semantics.** Truncated `Nat` subtraction, Euclidean `Int` division with `x / 0 = 0`
      and `x % 0 = x`, and coercions at the leaves of an operator tree as Lean's `binop%` elaborator places
      them.
   2. **Check the reading is faithful.** The reading is rendered back to Lean, and the kernel must accept
      `example : <our reading> := @Original`. A misreading is rejected, as a test demonstrates.
   3. **Witness** under those semantics. A counterexample to a Lean-proved statement would be a bug in the
      card semantics.
   4. **Re-prove** with the card model's own tactics (`omega`, `grind`, `simp`, `decide`) and with chains of
      its own rule cards (below).

   The core import (`cards/theorem/_pack_lean_core.jsonl`): 2,293 theorems scanned in 14 files, 1,511 in the
   fragment, 1,489 read faithfully, 1,440 witnessed, 930 re-proved without the original proof, and 0
   semantic mismatches.
4. **Rule chains** (`emit/lean_chain.py`). For an integer equation, the rewrite search over the rule cards
   finds `lhs = e1 = … = rhs`. Each step becomes a kernel-checked `calc` step, either the rule's own theorem
   or that theorem lifted into context with `congrArg`. The card model thereby re-derives, for example,
   `a + b + c = a + c + b` from `associative_add` and `commutative_add`, and Lean checks the derivation.

## Logic (`engines/logic.py`, CM24)

**Rules are cards.** The engine evaluates facts and rules, with stratified negation, bindings and tests
through op cards, aggregates and constraints, to a fixpoint (semi-naive, indexed, with a budget).

**Every derived fact keeps a proof of minimum height.**

* `cardmodel logic why SOURCE 'atom' --lean` encodes the theory in Lean: symbols as one finite type,
  fact-only predicates as decidable lists, derived predicates as inductive propositions with one constructor
  per rule.
* The proof tree becomes a constructor term, and the kernel checks it.
* A forged derivation is rejected (a test plants one).
* Aggregates and negation of derived predicates are reported as not exportable.

**The model's own laws are logic too.** `stdlib/self.card` reads the store as facts: cards, registries,
dependencies, laws and their witnesses, goals and their metrics, theorem statuses and their evidence, op
semantics. It must hold with 0 violations, and a planted dangling reference is caught (CM27).

**Deciphering rules from data.** `cardmodel logic mine` tests rule templates against any relations:
symmetric, transitive, inverse, implies, compose, functional, irreflexive, antisymmetric, domain and range.
* Exact laws (confidence 1, support ≥ 3) become learned rule cards with their evidence.
* From raw parent/grandparent facts it recovers `grandparent(X, Z) <- parent(X, Y), parent(Y, Z)`.

**Programs as logic.** `cardmodel logic code PATH` turns a Python tree into facts: functions, calls,
effects, and whether the IR frontend lifts each function. `stdlib/program.card` then derives what is pure,
what is effectful through its calls, what is recursive, and how far each effect taints its callers. It also
checks the optimizer's pure-core/effect-shell split (CM21) against the effect analysis.

## Limits

* Witnesses sample: "witnessed" is evidence, not proof.
* Core Lean has no Mathlib, so nonlinear facts often stay witnessed.
* The Lean fragment is arithmetic over Nat, Int and Bool. `∃`, structures, lists and instances are outside it
  and are skipped with a reason.
* Rule chains are bounded searches.
* Proof by exhaustion holds under the IR's reference semantics, which the conformance matrix ties to every
  language.
