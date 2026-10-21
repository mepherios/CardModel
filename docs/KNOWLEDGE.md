# Crystallised knowledge: logic, theorems, laws and Lean

A statement in the card model is only as strong as its evidence (law CM23):

| status | meaning |
|---|---|
| refuted | a counterexample, shown (the smallest the exhaustive phase finds) |
| conjecture | not yet checked |
| vacuous | the hypotheses rarely hold, or pin a variable to one value: a "law" about a point is no law |
| witnessed | an exhaustive small-value phase and seeded random values (edges included; inside the hypothesis box when the hypotheses bound every variable) all agree |
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

## Function algebra: the GCD of functions, Gödel numbers, redefinition classes

`cardmodel algebra` (`engines/funcalg.py`) treats integer functions of one variable as algebra. This is
Servois's 1814 calculus of operations made computable.

* **Canonical form, from behaviour not code.** Sample f(0), f(1), …, find the shortest linear recurrence
  (Berlekamp–Massey over Q) and check it on terms it did not use. The form is the *annihilator* p(E), a
  polynomial in the shift operator E, together with the initial terms.
  * A loop, a recursion and a closed form with the same behaviour have the same canonical form.
  * Polynomials are exactly the annihilators (E − 1)ᵏ, and get an exact closed form from Newton's forward
    differences.
* **Gödel number.** The canonical form is a short integer sequence. Its Gödel number ∏ pᵢ^(z(aᵢ)+1) names
  the function's redefinition class and decodes back exactly. Every form of every algorithm card must share
  one number; `algebra scan` checks this.
* **GCD of functions**, in two views:
  * **operators**: gcd and lcm of annihilators give the shared dynamics. Equal annihilators mean one
    function is a fixed combination of the other's shifts (Lucas = 2F(n+1) − F(n));
  * **values**, for polynomial functions: the common factor and cofactors give the integer cross identity.
    For example (2n+1)·T(n) = 3·S(n) for the triangular numbers T and the sums of squares S.
  * Also: shifts (triangular(n) = sum_1_to_n(n−1)), compositions (sum of cubes = T²), and fixed divisors
    (every n(n+1)(n+2) is divisible by 6).
* **Totals.** The running sum of a canonical form is canonical again, with annihilator (E − 1)·p(E).
* **Redefinitions carry into the optimizer.** A polynomial becomes an exact integer closed form. A recurrence
  of order d becomes d×d matrix powering. Both are in the liftable subset, so `improve` verifies, times and
  splices them without any algorithm card. Examples: a double-loop tetrahedral sum ×4,579, Pell numbers by
  matrix powering.
* **The identities between the algorithm cards** are in `stdlib/algebra.card`, generated by
  `algebra scan --write`. Each is a theorem witnessed on every run (proved by exhaustion on its stated range).
  They are also stored as `functional_identity` cards.

## Lineage (cards in `cards/lineage`)

| work | what it established | in the model |
|---|---|---|
| Servois 1814 | the distributive and commutative properties of operators; commuting linear operators obey algebra, so identities carry (the calculus of operations as a proof method) | law templates in `engines/laws.py`; operator algebra in `engines/funcalg.py` |
| Peacock 1830/1833 | the permanence of equivalent forms | canonical forms and redefinition classes; rewrite rules carrying identities |
| Boole 1847 | logic as an algebra of operations | `engines/logic.py` |
| Hankel 1867 | the permanence of formal laws when number systems extend | law templates re-checked on every new operator, Lean-semantic ones included |
| Gödel 1931 | numbering syntax so structure becomes arithmetic | Gödel numbers of canonical forms; card content hashes |

## Limits

* Witnesses sample: "witnessed" is evidence, not proof.
* Core Lean has no Mathlib, so nonlinear facts often stay witnessed.
* The Lean fragment is arithmetic over Nat, Int and Bool. `∃`, structures, lists and instances are outside it
  and are skipped with a reason.
* Rule chains are bounded searches.
* Proof by exhaustion holds under the IR's reference semantics, which the conformance matrix ties to every
  language.
* The function algebra covers integer functions of one variable whose behaviour is a linear recurrence of
  order ≤ 8 on the sampled range. Other behaviours have no canonical form here.
