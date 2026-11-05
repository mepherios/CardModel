# GODEL_TARGET: the Gödel model as the foundation of CardModel

The user (2026-11-04): *"Make it so all of the model is based inherently on this structure and understanding and
forced everywhere it's useful for it and increases scalability and where it can be optimized … universally scalable
from anything from math, code and physics etc. Code is just one thing we want it for."*

This document is the target design. [FOUNDATIONS.md](FOUNDATIONS.md) states the mathematics (D1–D14) and the rules
(A1–A7); this document takes D11–D13, the Gödel part, and says what it must become to carry the rest of the model:
which abilities follow from it and nothing else, which functions must be built on it, which must not, and the order
of work. The walkthrough of everything the model can do is [GODEL.md](GODEL.md); the function-by-function audit is
[GODEL_AUDIT.md](GODEL_AUDIT.md). Where they and this document disagree, the audit's table of call sites wins and
this document is corrected.

## 1. The structure in one paragraph

Any system that can be defined is a set of **atoms** (the things it is built from) and **terms** (the ways they are
put together). For code the atoms are op cards; for mathematics they are operations and logical primitives; for
physics they are base quantities (length, mass, time, …); for a machine, instructions and effects. The Gödel model
gives every atom a prime, forever (the ledger, CM43), and reads every term twice. **Content** γ(t) counts the atoms
of t: a vector in ℤ^(ℕ), the free abelian group on the primes, stored sparse (CM45). **Structure** is Gödel's
positional code: injective, decodable, the term's syntactic identity. Nothing in this is about code. A domain joins
the model by declaring its atoms as a Gödel set (a `godel_set` card with an admissible numbering, W-5), and from that
moment every ability in §2 works on it without new code.

## 2. What the structure gives, and why nothing else gives it

Each ability below is a theorem about the free abelian group or the positional code, with the condition it needs.
"Unique factorization" means: two contents are equal exactly when their exponent vectors are equal, and every content
factors one way into atoms (formal/GodelCore T1–T4).

| # | ability | the fact | condition | what it replaces |
|---|---|---|---|---|
| G1 | **shared logic** of two concepts | gcd = per-atom min; lattice meet (T1) | content read from canon_E (D11) | pairwise tree diff, O(n·m) |
| G2 | **union** of two concepts | lcm = per-atom max; lattice join | same | — |
| G3 | **part-of, refuted instantly** | p a subterm of t, or t an instance of a pattern p ⇒ γ(p) ∣ γ(t), because substitution only adds content | variables and constants are not atoms (Rule-23) | trying every match |
| G4 | **cofactor**: what is left of t after a known concept c is factored out | γ(t) − γ(c) when γ(c) ∣ γ(t); the residual's atoms are exactly the context C in t = C[c] | G3 confirmed by a structural match | — |
| G5 | **redefinition by cofactors** | t = C[c₁, …, cₖ] with γ(t) = γ(C) + Σ γ(cᵢ): a term rewritten over the concepts the model already knows, checked by the equation on vectors | each cᵢ is a matched library term | hand-written library recognition |
| G6 | **cost without the term** | an additive cost is linear: cost(t) = ⟨γ(t), c⟩ (D7) | the cost is additive per op (egraph.extract, search.expr_cost) | walking the term |
| G7 | **composition is addition** | γ is a homomorphism: a module's content is the sum of its functions', a package's the sum of its modules' | — | recomputing a summary from bodies |
| G8 | **incremental change** | a change's delta is γ(new) − γ(old); the package's content is updated by one vector addition | G7 | recomputing everything |
| G9 | **order-free parallel merge** | vector addition is commutative and associative: summaries from any number of workers merge to the same result | G7 | ordered reductions |
| G10 | **similarity and clustering** | \|gcd\| / \|lcm\| (multiset Jaccard) is a metric-derived score on contents | content from canon_E | embeddings with no proof |
| G11 | **carry-over to another domain** | a map of atoms is a group homomorphism; it preserves every gcd iff distinct atoms map to disjoint supports (T2); what has no image is the gap | the images are stated per atom | per-pair translators |
| G12 | **redefining the basis** | merge (one atom is another) and deprecate (an atom is a product of others) are ledger events; every stored vector is re-read through them (`resolve`) and never rewritten | the ledger only appends (CM43) | migrations of stored data |
| G13 | **ratios and units** | ℤ^(ℕ) has inverses: negative exponents. Physical dimension is exactly this group over the base quantities (m·s⁻² is {m: 1, s: −2}); dimensional consistency of an equation is equality of contents | a domain's atoms declared as a set | a units library |
| G14 | **identity and decoding** | the positional code is injective and decodes exactly (W-1, W-5) | terms of ≤ 4096 bits; past that, the hash of the canonical term (GM-2) | — |
| G15 | **size known before building** | code sizes follow log formulas (W-3) | — | building huge integers |
| G16 | **a sublinear index** | an inverted index atom → concepts answers "which known concepts can divide this content" by touching only the postings of t's atoms | — | scanning every card |

G3–G5 and G16 together are what the user called *redefining structures by their cofactors*: given any term, the
model finds the known concepts that can occur in it (G16, G3: a divisibility test, never a failed match), confirms
them by matching, and rewrites the term as a context applied to them, with the cofactor as the part that is new. The
same operation over a library of physics laws factors an expression into known laws; over the op cards' own
definitions it finds redefinitions; over a codebase it finds duplicated logic.

## 3. What the structure must not be used for

| not for | why |
|---|---|
| deciding equality of behaviour | γ is not invariant under ≈_E: γ(a·(b+c)) ≠ γ(a·b + a·c) (D11). Equal content is necessary for equal canonical terms, never sufficient for equal functions |
| reading content from a raw lifted term when a canonical one exists | the same function written two ways has two contents (F4); every caller reads γ(canon_E(t)) and records `read_from` |
| evaluation, semantics, correctness | M is the only meaning (A2); content forgets arrangement and values |
| constants and variables | they are not atoms (Rule-23); content counts operations, so it is blind to `x + 1` vs `x + 2` |
| identity of large terms | positional codes explode (Ph-2, Ph-3); identity is the hash of the canonical term (GM-2) |
| storing the content integer ∏ p^e | it grows with every factor; the sparse vector with its basis version is stored (CM45) |

## 4. The core, as code

One module, `engines/godel.py`, owns the algebra; every other module calls it instead of re-implementing it.

| operation | function | cost |
|---|---|---|
| content of a term | `term_content(t, ops, holes=())`: iterative, a shared subterm computed once and counted per reference | O(\|t\|) |
| lattice | `gcd`, `lcm`, `divides`, `cofactor(whole, part)` (exact, or None) | O(support) |
| group | `add(*vectors)`, `sub` (signed), `scale`, `norm`, `support` | O(support) |
| cost | `cost(content, costs)` = ⟨γ, c⟩ | O(support) |
| similarity | `jaccard(a, b)` = \|gcd\| / \|lcm\| | O(support) |
| index | `ContentIndex.add/remove`, `.divisors(c)`, `.multiples(c)`, `.similar(c, k)` | postings of c's atoms |
| matching | `match(pattern, term)`: first-order, a variable binds the same subterm wherever it repeats; `substitute`, `variables` | O(\|pattern\|) |
| cofactor factoring | `factor(term, library, ops, index, exclude)` → the term with each instance of a library concept as a `CALL` to it, the cofactor, and the vector check; `expand` unfolds it back | one index query per subterm, one match per surviving candidate |
| carry-over | `carry` (image and gap), `preserves_gcd` | O(support) |
| structure | `tokens`, `structural`, `exponents`, `from_tokens`, `decode` (all iterative); the identity hash via `egraph.semantic_hash` | O(\|t\|) |
| primes | `primes(n)`, `nth_prime(n)` (one sieve for the whole model), `zig`, `unzig` | amortized |

Every duplicate is retired into it: `unreal/distill.content` and `unreal/distill.tokens` (a second content walk and a
second positional token scheme), `funcalg._primes` and `_zig` (a second prime sieve and zigzag), the private `_zig`
in `codes` and `numbering`, and the private `_content` in `numbering`. A test keeps it so: no module outside
`godel.py` (and `godel1931.py`, Gödel's own definitions) may define primes, content or the zigzag.

## 5. Which functions are built on it

The audit ([GODEL_AUDIT.md](GODEL_AUDIT.md)) lists every call site. The rule it applies:

* **Must use the Gödel core** when a function compares, indexes, aggregates, costs, ranks, translates the atoms of,
  or identifies terms: library recognition, duplicate detection, rule prefiltering (G3 before a match is tried),
  summaries over modules and packages (SCALING §3.1), incremental updates (SCALING §3.3), parallel merges
  (SCALING §3.6), cost estimates for extraction, carry-over between Gödel sets and between languages (the gap of a
  translation is the atoms with no emit template), and any new domain (physics, a new ISA, a new formal system).
* **Must not** when a function evaluates, decides behavioural equality, or needs constants: `ir`, `logic`,
  `witness`, `conformance`, `analyse`'s divergence laws, `realnorm`, `funcalg`'s recurrences. These may *report*
  content beside their result, never derive their result from it.
* **May** (only as a prefilter that never changes the answer): e-graph rule matching and `search`'s rule selection.
  A prefilter is admissible only when a test shows the answer is identical with and without it, and only when it
  pays: the audit measured a content prefilter on e-graph rule matching at 2 % or less, so that one is not done.

## 6. Order of work

1. This document.
2. **The core** (`engines/godel.py`): the group operations, cost, Jaccard, `ContentIndex`, `match`, `factor`; an
   iterative `term_content`; the duplicates in `unreal/distill`, `funcalg` and `numbering` call it. Tests pin every
   identity in §2 on random terms (G3: γ(σ(p)) ≥ γ(p) for every substitution; G6: ⟨γ, c⟩ equals `expr_cost`; G7;
   G9; G11).
3. **Cofactor factoring as a command**: `cardmodel godel factor CARD|EXPR` rewrites a term over the definition and
   function cards whose terms divide it, and `cardmodel godel similar CARD` ranks concepts by G10 through the index.
4. **Physics as a Gödel set** (G13): base quantities as atoms with negative exponents allowed, a dimension check of
   equations, to show a non-code domain joining without new algebra.
5. **Call sites** in the order the audit ranks them, each its own PR, each with the "same answer with and without"
   test where the core is used as a prefilter. The canonical-content change (F4) is the "Ground CardModel in its core
   mathematics" thread's; `sources` passes the canonical term to `term_content`.

## 7. How we know the target is met

* No module outside `engines/godel.py` computes primes, content or positional tokens (a grep in the integrity check).
* Every identity in §2 has a test that can fail on random terms.
* `cardmodel godel factor` factors every definition card's canonical term over the others, and the vector equation
  γ(t) = γ(C) + Σ γ(cᵢ) holds for every result.
* A non-code domain (physics) uses the same functions with no domain-specific algebra.
* `verify`, `matrix` and `analyse` are unchanged by the restructuring, and the test suite passes.

## 8. A non-code domain joins: physics

The recipe any definable system follows, as physics did (`tools/seed_physics.py`, `engines/dimensions.py`):

1. **Atoms.** The SI base quantities (`quantity/length`, `quantity/mass`, `quantity/time`, `quantity/current`,
   `quantity/temperature`, `quantity/amount`, `quantity/luminosity`) enter the ledger as the set `physics`, each
   with its prime forever (CM43). Their arity is 0: a quantity is a leaf of a term.
2. **The set card.** `godel_set/physics` extends B0, states the arities and the numbering (B0's scheme), and the
   same six admissibility conditions are witnessed on its generated objects by the same checker (W-5,
   `numbering.check_set`); the quantities appear as leaves of those objects.
3. **A model of the signature.** The IR's ops act on dimensions through the `model` block of the set card, a
   Σ-algebra whose carrier is the content group (D14): MUL adds, DIV subtracts, POW scales, FSQRT halves, ADD and
   SUB need one dimension and keep it, a comparison needs one and gives none, EXP and LOG need none. The group
   operations are `godel.add`, `sub` and `scale`; the module adds no algebra. The ops' numeric meaning is untouched
   (A2): this is a second, named model (D9), read from the card.
4. **Carry-over.** The derived quantities (force, energy, power, pressure, voltage, …) are a carry map from their
   names to base content on the card (`derived`). It does not preserve gcd (T2): their supports overlap, so the
   base quantities are the free generators and a derived one is a product, which is what `deprecate` records.
5. **Laws as cards.** A `physics_law` card is an equation between two terms over variables with stated
   dimensions. It is consistent exactly when its sides have one content (G13). Thirteen laws (Newton's second,
   gravitation, Coulomb, the ideal gas, Ohm, Planck, the pendulum period, mass–energy, …) are checked by
   `dimensions.check`, which the godel verify section runs, and by `cardmodel godel dimension LAW... | --expr E
   --dims m=mass,a=length/time^2`.

What came for free: the ledger, the sparse vectors, gcd, lcm and cofactors over dimensions, the index, the
admissibility witness, and the equation check. What the domain brought: seven atoms, one table of how its ops act,
and its laws. A late atom's positional code is large (a quantity's token code is about 10,240, so one physics
object codes to about 200,000 bits); the set witnesses admissibility on 20 generated objects for that reason,
stated on the card, until positional codes take per-set dense ranks, which is the user's decision (the audit).

## 9. Progress

| step | status |
|---|---|
| 1. this document | done 2026-11-04 |
| 2. the core | done 2026-11-04: the algebra, `cost`, `jaccard`, `ContentIndex`, `match`, `factor`, `expand`, the iterative walks, the duplicates retired; every identity of §2 tested on random terms (`tests/test_godel.py`, class `Algebra`) |
| 3. cofactor factoring and similarity as commands | done 2026-11-04: `cardmodel godel factor CARD... | --expr E` (a term over the definitions it contains, with the cofactor and the vector check), `similar` (by |gcd| / |lcm| through the index), `cofactor WHOLE PART`, `decode N --vars`. Today 11 of 577 definitions have a closed term (the rest wait for distillation), so the library is small; it grows with every canonical term |
| 4. physics as a Gödel set | done 2026-11-04: `godel_set/physics` (the SI base quantities as atoms of arity 0, the dimension model on the card, the derived quantities as a carry map), 13 `physics_law` cards, `engines/dimensions.py`, `cardmodel godel dimension`; §8 |
| 5. call sites | waiting on the audit's ranking |

**Open proposals (2026-11-05).** Pull requests on GitHub that touch this thread, listed from their titles and bodies. Except for #48, they are proposals waiting for the Gödel thread's review and are not counted as done here.

- #48 *physics as a Gödel set: dimensions as signed content, laws as cards*: **merged** 2026-11-05T07:16:44Z (step 4 of GODEL_TARGET §9).
- #53 *codegen: a language is a carry map; translate and matrix predict its gap from content*: the Gödel thread's codegen-as-carry-map PR (GODEL_TARGET §5, GODEL_AUDIT §6 step 3). Open.
- #54 *Gödel section cached by the hash of its inputs*: the second half of GODEL_AUDIT §6 step 1 (`godel.check_key`). The first half, valuation by squaring, landed with #28. Open.
- #55 *Every capability in the main pipeline: tiers, coverage check and Gödel purity (CM50)*: the pipeline coverage check, with Gödel purity as a checked property (G_A14). Conflicts with #50. Open.
- #58 *search: match/instantiate via godel.match/substitute (Gödel purity A6)*: search calls the core's matcher instead of its own. Open.
- #66 *godel factor|similar|cofactor: accept FILE.py:FUNC*: the `godel` commands lift a source function to its canonical term. Open.
- #68 *codes: read Def-27 tokens through the Gödel core*: `engines/codes.py` reads tokens through the core. Its body calls it a proposal for the Gödel thread, which owns that file. Open.
- #70 *Proposal for the Gödel thread: purity follow-ups (dead number(), Numbering.tokens via core, rational scale)*: open. Its current body describes FOUNDATIONS §7 fixed-width IR types, not the title. Check the diff before reviewing.

No other open PR has godel or token-list in its title.
