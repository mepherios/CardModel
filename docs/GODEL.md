# GODEL: what the Gödel card model can do

The user (2026-11-04): *"Make a full walkthrough of all the Gödel model can do, like redefining structures by their
cofactors, redefine structures etc, all of its inherent abilities and possible usable features we can't replicate
without using and building on the structure … so it's universally scalable from anything from math, code and
physics; it's supposed to be able to learn or use anything and use our structure and logic for any system that can
be defined. Code is just one thing we want it for."*

[FOUNDATIONS.md](FOUNDATIONS.md) states the mathematics (D1 to D14) and the rules (A1 to A7). [GOALS.md](../GOALS.md)
says what the model is for. This document walks through the **abilities** the mathematics grants: for each one, what
it is, why it cannot be had without building on the structure, a worked example from the model as it runs today,
how it applies beyond code, and whether it is **proven** (a theorem in `formal/GodelCore`, kernel-checked, no
`sorry`), **measured** (a finding or test on the real store, tier bounded or sample), or a **conjecture** (follows
from the definitions in a way that nobody has written down as a theorem or test yet). Nothing here is claimed at a
higher grade than its evidence; that is law CM46.

Two sibling efforts use this document: the audit of which functions should be built on the Gödel model, and the
restructuring of the model around it. §7 is written for them.

## 0. The model in one picture

```
   atoms  ──ledger──▶  primes          (op/ADD ↦ 19, op/MUL ↦ 38, … : append-only, T3)
   term t ──γ───────▶  content  γ(t)   (exponent vector: ADD² · MUL¹  : a lattice, T1)
   term t ──σ───────▶  structure σ(t)  (Gödel's positional code       : injective, decodes, W-5)
   term t ──canon_E─▶  identity  h(t)  (sha256 of the cheapest ≈_E-equal term : D7)
   set S₁ ──carry───▶  set S₂          (a homomorphism fixed on atoms; gcd kept iff images disjoint, T2)
```

Everything below is a consequence of these five arrows and of the facts that make them work: unique factorization
of integers (so the content vector *is* a number and divisibility *is* part-of), the infinitude of primes (so the
ledger never runs out), and Gödel's 1931 observation that syntax can be arithmetic (so structure, proofs and
provability become numbers that the model can compute on).

The one honest limit that governs all of it, stated once (D11, `godel.py` L1): **content forgets arrangement, and it
is only as canonical as the term it is read from.** γ(a·(b+c)) ≠ γ(a·b + a·c). So every content-based ability reads
γ from canon_E(t), never from a raw lifted term. Where the code does not do that yet (FOUNDATIONS F4), the ability
is weaker than the theorem says, and the walkthrough says so each time.

## 1. Atoms take primes, forever: identity that survives growth

**What it is.** The ledger (`cards/godel/_pack_ledger.jsonl`, `engines/godel.py`) gives every atomic concept the
next unused prime, and only ever appends. Today: 3,411 atoms in six sets (B0 50, computation 13, machines 9,
analysis 20, bits 9, unreal 3,310); the latest, `op/REM`, is index 3411, prime 31723.

**Why it needs the structure.** A hash or a database id also identifies a thing. What a *prime* gives, and a hash
cannot, is that the identity composes: a product of atoms is a number, a product of products is still a number,
and the number of a composite can be read back to its atoms by factoring. That is unique factorization, and it
needs the atoms to be primes (or, equivalently, basis vectors of a free commutative monoid). Append-only is what
makes the identity permanent: once an atom has a prime, every content vector ever stored keeps meaning it.

**Proven.** `formal/GodelCore/T3Ledger.lean`: appending never moves an atom (`pos_append`); growing the ledger does
not change the reading of anything written before (`enc_append`); the reading is a homomorphism of products, gcd and
lcm, and preserves and reflects divisibility (`enc_mul`, `enc_gcd`, `enc_lcm`, `enc_dvd_iff`); it is injective on
contents written in the ledger's atoms (`enc_injective`); and along any append-only history the readings agree
(`enc_chain`). `cardmodel verify` fails if the ledger changed a line the last commit had (CM43).

**Worked example.** `cardmodel godel ledger --limit 5`:

```
3411 atoms (B0: 50, computation: 13, machines: 9, analysis: 20, bits: 9, unreal: 3310); problems: none
  3410   31721  B0  op/TRUNCDIV
  3411   31723  B0  op/REM
```

`op/TRUNCDIV` and `op/REM` were added after the unreal set's 3,310 atoms (FOUNDATIONS: each language's `/` and `%`
map to distinct ops). They took the next two primes. No unreal content vector changed.

**Beyond code.** Any domain whose vocabulary is a set of named primitives: SI base units, the generators of a group,
the symbols of a formal theory, the species in a reaction network, the fields of a Lagrangian. The ledger is the
rule "name it once, number it once, never renumber". GOALS.md item 2 says every such domain is a Gödel set
extending B0.

## 2. Content is a number: part-of, shared logic and combined logic are gcd, lcm and divisibility

**What it is.** γ(t) counts the atoms of a term with multiplicity (D11). Stored sparse, it is the exponent vector of
∏ p(a)^{e_a}; never stored as that integer (CM45). On these vectors `divides` is ≤ per coordinate, `gcd` is the
per-coordinate minimum and `lcm` the maximum (`godel.py: gcd, lcm, divides`).

**Why it needs the structure.** "Shared logic" between two programs is usually answered by diffing, by clone
detection, or by embedding and a cosine. None of those is an *operation with laws*. With content as a number, the
shared part of two things is their gcd, the smallest thing containing both is their lcm, "a is part of b" is a | b,
and these obey a distributive lattice: gcd and lcm distribute over each other, gcd · lcm = the product, and
multiplication cancels. Those laws are what let the model reason, not just compare.

**Proven.** `T1Lattice.lean`: the divisibility order is a lattice with gcd as meet and lcm as join (`dvd_gcd`,
`lcm_dvd`), distributive both ways (`gcd_lcm_distrib`, `lcm_gcd_distrib`), `mul_gcd_lcm`, `mul_left_cancel`.

**Worked example.** `cardmodel godel vector` and `godel gcd` on the algorithm cards:

```
algorithm/sum_of_squares (loop form): {ADD: 2, MUL: 1}  -> vector {19: 2, 38: 1}
algorithm/sum_of_cubes   (loop form): {ADD: 2, MUL: 2}  -> vector {19: 2, 38: 2}
gcd: {ADD: 2, MUL: 1}; sum_of_squares divides sum_of_cubes: True; the reverse: False

algorithm/gcd (euclid):  {ABS: 2, CMP_NE: 1, MOD: 1}
algorithm/lcm (via_gcd): {ABS: 2, OR: 1, CMP_EQ: 2, MUL: 1, FLOORDIV: 1, GCD: 1}
gcd: {ABS: 2}   lcm: {ABS: 2, CMP_NE: 1, MUL: 1, FLOORDIV: 1, GCD: 1, OR: 1, MOD: 1, CMP_EQ: 2}
```

The first pair says, in one lattice operation, that the sum of cubes contains the sum of squares as a factor (one
more multiplication). The second says Euclid's gcd and the lcm share only their two `ABS` calls: the lcm card
*calls* `op/GCD` as an atom rather than inlining Euclid, so the model sees them as nearly coprime. That is a true
statement about these cards, and it is also exactly the limit of §0: content sees the atoms a term is written in.
Deprecating `op/GCD` as the product of Euclid's atoms (§3) would make the shared factor appear.

**Measured.** `tests/test_godel.py`; the `godel` section of `cardmodel verify` reads content for every op, function
and algorithm card and reports coverage. Content is read from the lifted term today, not from canon_E (F4, open).

**Beyond code.** Physics is the cleanest witness (GOALS.md item 3): base units are atoms, a derived quantity is a
product, and dimensional analysis is this algebra with nothing added. N = kg·m·s⁻² and J = kg·m²·s⁻²: gcd(N, J) = N,
and J / N = m is the cofactor, which is "a joule is a newton moved a metre". With negative exponents allowed the
vectors form the free abelian group on the primes, which is the positive rationals under multiplication.
*Conjecture, as far as the formal core goes:* `GodelCore.Vec` is `Nat → Nat` (a monoid), so the group with inverses
is not yet in Lean, and the physics set is not yet a card set (ROADMAP G3). In mathematics: a monomial is a content
vector over the variables, and the gcd of two monomials is their common factor; the same lattice. In any system
with a finite vocabulary of parts: a recipe, a proof, a circuit, a molecule, the "has in common" question has this
one answer.

## 3. Redefining structures by their cofactors

**What it is.** The theorem behind the user's phrase is `dvd_iff_exists_mul` (T1): **u | v exactly when v = u · w
for some w.** The cofactor w is what v adds to u. So any structure v can be *redefined* relative to a part u as
"u, and then w", and because the monoid is cancellative (`mul_left_cancel`) the cofactor is unique. The model uses
this in three places:

1. **Cofactors of content.** Given γ(f) | γ(g), the cofactor γ(g) − γ(f) is the exact extra logic of g. In the
   example of §2, sum_of_cubes = sum_of_squares · MUL.
2. **Cofactors of functions** (`engines/funcalg.py`, CM31). Two integer functions have a gcd in two views:
   as *operators*, the gcd of their annihilating polynomials in the shift E (Servois 1814): the dynamics they
   share, with cofactors saying what each adds; as *values*, for polynomial functions, the gcd h in ℚ[n] with
   cofactors p, q so that f = p·h and g = q·h, which yields the integer **cross identity** q'·f = p'·g.
3. **Deprecation** (`godel.py: deprecate`, `resolve`). When an atom is found to be a product of others, the ledger
   appends an event "index i is read as this product". Every stored vector that mentions i is then *read through*
   the event: the atom is redefined by its factorization, and nothing stored has to change. A merge event is the
   degenerate case (two atoms name one concept).

**Why it needs the structure.** A cofactor only exists where division is exact and unique, which is unique
factorization again. "What does g do beyond f" asked of two source files has no canonical answer; asked of two
content vectors it has exactly one, and asked of two annihilators it has one up to a unit. And redefining by
reading-through (3) is only sound because the reading is a homomorphism (T3c): the product of the parts equals the
whole, so a vector read through a deprecation is the same number as before.

**Proven.** `dvd_iff_exists_mul`, `mul_left_cancel` (T1); `merge_mul`, `gen_basis_iff`, `merge_image` (T4: merging
keeps the factor layer free); `enc_mul` (T3c).

**Worked example.** `cardmodel algebra gcd algorithm/sum_of_squares algorithm/triangular`:

```
f = sum_of_squares: f(n) = 1/3 n³ + 1/2 n² + 1/6 n
g = triangular:     g(n) = 1/2 n² − 1/2 n
operators: gcd (E−1)³   lcm (E−1)⁴   (cofactors E−1 | 1)
values:    common factor n, cofactors 1/3 n² + 1/2 n + 1/6 | 1/2 n − 1/2
           (3n − 3) · f(n) == (2n² + 3n + 1) · g(n)
```

The last line is a theorem about two programs, produced from their *behaviour*, not their text: the triangular
numbers and the sum of squares are redefined in terms of their common factor n and two cofactors, and the cross
identity is the cofactors swapped. With `sum_of_cubes` and `triangular` the same command finds
`(2n − 2)·f(n) == (n³ + 2n² + n)·g(n)` and, when a polynomial composition exists, finds it (sum of cubes = triangular
squared). `cardmodel algebra scan --write` writes these as `theorem` cards with `requires n <= 500`.

**Measured, tier bounded.** The identities are found by exact rational algebra on the fitted forms and checked on
unused terms (`tests/test_funcalg.py::test_canonical_forms_carry_between_functions`); the written theorem cards are
bounded to n ≤ 500 and say so. For polynomial functions the equality of the fitted form and the program is tier
*proof* through the finite-grid theorem in `engines/tiers.py`.

**Beyond code.** This is the ability the user named first, and it is the one most directly general. In mathematics
the gcd of two polynomials and the resulting Bézout and cross identities are the entire theory of resultants and
elimination; the operator view is the theory of linear recurrences (and, with E replaced by the derivative D, of
linear ODEs: the same algebra, since Servois' point was that commuting linear operators obey the algebra of
numbers). In physics, two quantities with a common dimensional factor are related by a dimensionless cofactor
ratio: that is the Buckingham π theorem read as gcd and cofactors. In any definable system: given two things with a
common part, "the part and what each adds" is a canonical redefinition of both, and a product equation between the
cofactors is a law of the system that nobody had to write down.

## 4. Carry-over between domains is a homomorphism, with its gap

**What it is.** A map between two Gödel sets is fixed by the image of each atom (D13). On content it is
`carry` (`godel.py`): the image of ∏ aᵢ^{eᵢ} is ∏ img(aᵢ)^{eᵢ}, and the atoms without an image form the **gap**,
returned as a residual factor beside the image. `preserves_gcd` decides whether the map keeps every gcd.

**Why it needs the structure.** A translator between two languages is a program; its correctness is a Π1 question
(W-15) and cannot be checked in general. A translator *between Gödel sets* is a homomorphism of free monoids, and
homomorphisms are fixed by their values on generators. So: (a) a translation is a finite table, atom → vector;
(b) it preserves products for free (`carry_mul`); (c) whether it preserves shared logic (gcd) is decided by one
check on the table (T2), not by testing on programs; (d) what it cannot say is exactly the residual factor, so a
translation is never "mostly works", it is "works on this image, and here is the gap"; (e) maps compose, so a chain
of translations (language → IR → another language; mathematics → physics) is one map, and the gap of the chain is
computable from the gaps of the links.

**Proven.** `T2Carry.lean`: `carry_mul`, `carry_one`, and **`preservesGcd_iff_disjoint`**: a carry-over preserves
every gcd if and only if no two distinct atoms share a target atom. `carry_basis_eq_of_same_image` gives the kernel:
two atoms with the same image become indistinguishable.

**Worked example.** The unreal set (`cards/godel_set/unreal`, 3,310 atoms, one per function of Unreal Engine's
math universe) carries to B0 ∪ analysis ∪ bits: "each lifted function's atom goes to its definition's content; a
function that is a gap has no image, and that is the map's gap" (`cardmodel/unreal/distill.py`, the `carry`
summary with its `preserves_gcd` verdict). A recorded version of the set has `preserves_gcd: false`, which is the
theorem doing its job: two distinct engine functions lifted to overlapping op content share a target atom, so the
gcd of two engine functions need not carry to the gcd of their images. The map is still a homomorphism of
products; it just does not reflect shared logic exactly, and the card says which.

Language pairs with no map yet are `translation_gap` cards (`cards/translation_gap/c__to__arm64_macho` and its
siblings), each naming the blockers.

**Measured.** `tests/test_godel.py` (carry and gcd preservation on built mappings); `cardmodel unreal` writes the
carry summary. The homomorphism *cards* of ROADMAP G2 (language → IR and IR → language as first-class maps with the
product law sampled) are not built yet.

**Beyond code.** Mathematics → physics: send each mathematical quantity's atom to its unit vector; dimensional
homogeneity of an equation is "both sides carry to the same vector". A model → another model (a lattice QCD
discretization, a numerical scheme): the gap is the list of continuum concepts with no discrete image, stated before
any run. Between two formal theories: an interpretation is a carry map on symbols, and T2 says when it preserves
"shared axioms". Between two natural-language ontologies: the same, with the honest gap in place of a fuzzy
alignment score. *Conjecture:* composition of carry maps with gap accounting (gap of f∘g from the gaps of f and g)
is a two-line corollary of `carry_mul` and has no theorem or test yet.

## 5. Properties transport along divisibility (proven once, true everywhere)

**What it is.** T5 (`T5Transport.lean`): a property that is **upward closed** (if it holds of n and n | m then it
holds of m) proven of one factor holds of every model that contains the factor; a **downward closed** property
proven of a whole holds of every part. Examples that are proven to be of each kind: "contains the factor f" is
upward closed (`contains_upClosed`); "uses only atoms from the fragment F" and "the exponent of atom i is at most
k" are downward closed (`fragment_downClosed`, `bounded_downClosed`); and the gcd keeps any downward-closed
property of either argument while the lcm keeps any upward-closed one (`gcd_keeps_down`, `lcm_keeps_up`). The
complement of an upward-closed property is downward closed; both kinds are closed under ∧ and ∨.

**Why it needs the structure.** Without part-of as an order there is no "transport": each program has to be checked
on its own. With divisibility, a whole class of facts is proven on the smallest term that has them and inherited by
divisibility alone, with no further proof, and *which* facts those are is decided by the shape of the property,
not by the program. "Calls the network", "contains a hash function", "touches floating point" (occurrence
properties) go up; "stays in the constant-time fragment", "uses no division", "has at most k multiplications" go
down. "Terminates" and "is fast" are neither, and T5 says so: those need the structure layer and a proof per term.

**Proven.** All of `T5Transport.lean`.

**Worked example.** Take F = the ops of B0 without `op/MOD`, `op/FLOORDIV`, `op/TRUNCDIV`, `op/REM` (a
division-free fragment). `algorithm/sum_of_cubes` has content {ADD: 2, MUL: 2} ⊆ F, so by `fragment_downClosed`
every term whose content divides it (sum_of_squares, triangular, sum_1_to_n) is division-free too, and so is the
gcd of any of them with anything. In the other direction, `algorithm/gcd` contains `op/MOD`; by
`contains_upClosed`, every term whose content is a multiple (including the lcm computed in §2) contains `op/MOD`.
None of this ran a program.

**Not yet in the engines.** T5 exists as a theorem and a `formal_theorem` card; no engine queries "which cards
inherit property P" through the lattice today. This is the clearest cheap win for the restructuring thread (§7).

**Beyond code.** Physics: "has dimension of energy" is an occurrence-style property of a product, and conservation
of a quantity is inherited by any system that contains the subsystem's generators (upward). Chemistry: "contains
carbon" goes up, "uses only elements from this set" goes down. Any definable system: a safety fragment (what may
appear) is downward closed, a hazard (what must not appear) is upward closed, and the lattice decides membership
without inspecting structure.

## 6. Rewrite invariants: refuse an impossible search before it starts

**What it is.** T6 (`T6Invariants.lean`): terms are trees of symbols, a rule l → r is **balanced** when every
variable occurs equally often on both sides, and a weight w (one integer per atom) is **orthogonal** to a rule
when w · γ(l) = w · γ(r). Then w · γ is unchanged by any sequence of rewrites with balanced, w-orthogonal rules, in
any context, under any substitution (`invariant`). So if w · γ(A) ≠ w · γ(B), no rewrite sequence turns A into B,
and the e-graph does not need to look.

**Why it needs the structure.** This is a conservation law for rewriting, and conservation laws need a quantity
that composes additively under the operation. Content is that quantity: it is additive under substitution
(`content_subst`) and under plugging into a context (`balanced_step`). Without content there is nothing to be
conserved.

**Proven.** All of `T6Invariants.lean`, with the stated restriction: rules that copy or drop a variable
(distributivity) are not balanced and are outside the theorem. Commutativity, associativity, and the identities
x + 0 = x and x · 1 = x with 0 and 1 as atoms are balanced.

**Worked example (by hand, over the theorem's own term type).** Rules: commutativity and associativity of ADD and
MUL (balanced; each rule has the same multiset of symbols on both sides, so *every* weight is orthogonal to it).
Terms: A = MUL(x, ADD(y, z)) with γ(A) = ADD¹·MUL¹, and B = ADD(MUL(x, y), MUL(x, z)) with γ(B) = ADD¹·MUL². With
w = (ADD: 0, MUL: 1): w·γ(A) = 1 ≠ 2 = w·γ(B). So under commutativity and associativity alone A and B are not
equal, decided in constant time. The e-graph today (`cardmodel distill "a*(b+c)" "a*b+a*c"`) does find them equal,
because distributivity is in E and is not balanced; T6 is exactly the tool that tells which rule set a cheap
refusal is sound for.

**Not yet in the engines.** `engines/egraph.py` does not use T6; `cardmodel distill "(x+0)*1 + x"` spends its full
budget (7 iterations, 4,002 nodes) on a term a weight check could help prune. *Conjecture:* partitioning E into its
balanced part E_b and the rest, and refusing an equality whenever some weight separates the two terms under E_b and
no unbalanced rule can change that weight, is a sound pre-check; its soundness for the mixed case is not proven.

**Beyond code.** This is Noether's observation in miniature: a symmetry of the rules (balance) gives a conserved
quantity (a weight on content). In chemistry it is atom balance: no sequence of balanced reactions turns H₂O into
something with a different element count. In physics it is dimensional homogeneity under algebraic manipulation.
In a formal theory it is a degree or rank invariant that refutes a derivation without searching for one.

## 7. The factor layer is free, and must stay free

**What it is.** T4 (`T4Free.lean`): merging two atoms that name one concept keeps the content monoid free
(`gen_basis_iff`, `merge_image`: the merged vectors are exactly the vectors without the merged atom, which form the
free monoid on the rest). An **equation between products**, a · b = c · d with four distinct atoms, does not: the
four stay distinct atoms, yet a · b and c · d become one element (`two_factorizations`), so unique factorization is
gone, while in the free monoid a product of two atoms has one factorization (`basis_pair_unique`).

**Why it matters.** Everything in §1 to §6 rests on unique factorization. So the model has two layers: the
**factor layer** (the ledger and content), where only merges and deprecations are allowed, and the
**transformation layer** (rules, redefinitions, laws, each with a proof or witness), where a · b ≈ c · d lives as a
rewrite with a certificate. `godel.py` enforces it: `merge` and `deprecate` are the only events, and the module's
docstring refuses product equations by citing T4.

**Proven.** All of `T4Free.lean`. **Enforced.** `godel.problems` on every ledger write.

**Beyond code.** This is the general rule for building a Gödel set over any system: *the atoms are free; every
relation between them is a transformation with evidence, never a change to the atoms.* A physics set keeps its base
units free and puts c = 1 or ħ = 1 in the transformation layer as a map, not as a merge. A mathematical structure
with relations (a group presentation) keeps the generators as atoms and the relations as rules.

## 8. Structure is an exact code: syntax, proofs and provability become arithmetic

**What it is.** Gödel's positional code σ(t) = ∏ pᵢ^{code(tokenᵢ)} over the prefix token sequence of a term
(`godel.py: structural, decode`; `engines/numbering.py`). It is injective and decodes exactly given the atoms'
arities. A numbering is **admissible** (W-5) when it is injective, effective, has a decidable image, starts codes
at 1, makes proper parts smaller (and their content divide the whole's), and leaves provability as a plain ∃ of the
decidable proof relation (no deviant clause, after Feferman 1960 and Grabmayr 2021). Each `godel_set` card states
its numbering and has a witness test.

**Why it needs the structure.** Content forgets arrangement; structure keeps it. Only an injective code lets the
model treat *a term, a proof, a derivation* as one number that it can compute on, compare, and decode back. And
only an admissible numbering keeps Gödel's theorems meaning what they say: with a deviant provability predicate a
theory can "prove its own consistency", and the model's honesty (Rule-12: consistency is never certified from
inside) would be a lie.

**Measured and tested.** `tests/test_numbering.py` (one witness per set on generated objects, corrupted codes and
random integers; all three sets pass after two arity gaps were fixed, finding `W5_arity_gaps`). The 46 definitions
of Gödel 1931 run as cards in Python and Lean with the two forms agreeing on 237 seeded calls, including the proof
checker for system P (`cards/godel1931`, `engines/godel1931.py`, `formal/Godel1931`, W-1). The size model (W-3):
the positional code costs Σ cᵢ·log₂ pᵢ bits, the content code Σ e·log₂ p_k, within one bit of the built integer;
median 400 vs 8 bits over 2,308 terms, worst 51,888,784 vs 898. So the decision record GM-2: identity is the sha256
of the canonical term, the positional code is a decodable witness computed on demand for terms up to 4,096 bits,
and pairing codes are never identities.

**Worked example.** `cardmodel algebra form algorithm/fibonacci`:

```
linear recurrence of order 2: f(n) = f(n−1) + f(n−2); f(0..1) = [0, 1]
annihilator E² − E − 1   checked on 20 unused terms
Gödel number 2108316175082635384223106750
```

The number is ∏ pᵢ^{zig(aᵢ)+1} over the short integer sequence (order, coefficients, initial terms) and decodes
back to it (`funcalg.godel_decode`). Any loop, recursion or closed form with the same behaviour gets the same
number: that is a redefinition class, CM31.

**Beyond code.** This is the part of the model that is literally Gödel's: any formal system with a decidable
syntax and a decidable proof relation gets a numbering, and then its provability is Σ1, its consistency Π1, and
the difficulty census (W-15, `engines/difficulty.py`, `cardmodel difficulty`) can be run on *its* questions. Of the
product's 18 questions, 7 are decidable and promised; 11 are open at a named rank. That census applies unchanged
to a physics theory written as cards, or to a legal rule system, or to a game's rules.

## 9. Canonical identity: knowing a thing instantly

**What it is.** D7: the identity of a concept is the sha256 of canon_E(t), the cheapest term in its ≈_E class under
measured costs. Two concepts with equal hashes are equal in M (Birkhoff soundness, D6); different hashes mean only
"not shown equal" (Rice). The e-graph (`engines/egraph.py`, `cardmodel distill`) computes the class, extracts the
cheapest member, and returns the **certificate**: the laws that fired.

**Why it needs the structure.** A hash of source text identifies spellings. A hash of a canonical form identifies
*meanings*, up to the laws the model knows, and the certificate says which laws. That turns "is this function
already known" into a dictionary lookup, and "is this optimization correct" into "here is the chain of valid
equations" (D8). The Gödel model's content and structure numbers then read off the canonical term, so every
ability of §2 to §6 inherits canonicity from this one step.

**Measured.** `tests/test_egraph.py`; `cardmodel distill "a*(b+c)" "a*b+a*c"` answers *equal* with the three rules
used and a 64-input witness. **Open (FOUNDATIONS F1, F4):** laws are instantiated without their sorts, so float
associativity can fire; and definition cards read content from the lifted term. Both are in FOUNDATIONS §6's order
of work; until then identities on float terms and content vectors are weaker than D7 and D11 state.

**Beyond code.** Equality saturation is domain-agnostic: give it a signature and sorted laws and it canonicalizes
physics expressions (units as sorts), algebraic identities, logical formulas. The condition is the one FOUNDATIONS
states: laws are applied only at the sorts they were proved for.

## 10. Behaviour has a canonical form too (`funcalg`, `tiers`)

**What it is.** For an integer function of one variable, sample it and find the shortest linear recurrence
(Berlekamp–Massey over ℚ); the annihilator with the initial terms is the function's canonical form, Gödel-numbered
(§8). From it: the exact closed form of a polynomial (Newton's forward differences), the fixed divisor (gcd of all
values = gcd of the Newton coefficients, a divisibility law that carries to every multiple), the running total
(annihilator (E−1)·p(E)), a basis change when two functions share an annihilator (Lucas = 2F(n+1) − F(n)), and a
fast form (closed form, or d×d matrix powering) that `improve` can verify, time and splice, and every language card
can emit.

**Why it needs the structure.** The algebra of operators (Servois) is a Euclidean domain, so gcd, lcm and
cofactors exist and are unique up to units: §3's abilities for *behaviour*, not just for content.

**Measured, with a proof tier where a theorem sizes the witness.** `engines/tiers.py` recognizes polynomial
straight-line forms, C-finite counted loops and linear recursions from the lifted IR, and sizes the witness by the
finite-grid theorem (degree + 1 points per variable) or by "two C-finite sequences of orders D1, D2 agreeing on
D1 + D2 terms agree forever". Eight algorithm claims are proved that way, not sampled; the census is 2,667 claims,
1,628 at tier proof. The theorems are cited from the literature; their Lean proofs (handover T7) are not in
`formal/GodelCore` yet. **Honest limit:** one integer variable, order ≤ 8 on the sampled range; machine integers
are not ℤ and get nothing from these witnesses.

**Beyond code.** Linear recurrences and their operator algebra are the discrete half of linear differential
equations; the same gcd/cofactor machinery with D in place of E is the theory of linear ODEs with constant
coefficients, which is most of introductory physics. Fitting a canonical form to a sampled behaviour is what a
physicist does with a time series; the fixed divisor is a divisibility law found from data.

## 11. Honesty is built in: tiers, ranks and the two kinds of "not equal"

Every claim carries a tier (CM46: proof, probabilistic with its bound, bounded, sample), and a conclusion inherits
the weakest tier of what it used (D10). Every method and question carries an arithmetical rank (W-15). "Not shown
equal" is never "unequal" (D7). W-12 shows the model telling the truth about its own probabilistic method: the
random-point identity test over F_p has error ≤ 2N/p and passed every honest trace while catching one flipped
gate; over ℤ/2^w the same test accepted a nonzero polynomial in 1,991 of 4,000 trials, so the bound fails there and
the card says so. This is not an ability *of* the Gödel structure but a condition for using it: a content gcd at
tier sample must not be presented as a proven shared factor.

## 12. Summary table: proven, measured, conjecture

| ability | theorem / finding | grade | wired into an engine |
|---|---|---|---|
| atoms numbered once, forever; readings stable under growth | T3a–d | proven | yes (`godel.sync`, `problems`, verify) |
| content is a distributive lattice: gcd, lcm, divides | T1 | proven | yes (`godel.gcd/lcm/divides`, `godel gcd/lcm`) |
| redefinition by cofactor: u ∣ v ⇔ v = u·w, w unique | T1 `dvd_iff_exists_mul`, `mul_left_cancel` | proven | partly (deprecation events read through; cofactor of content not a command yet) |
| cofactors and cross identities of functions | `funcalg.gcd_functions` | measured (bounded; proof tier for polynomial forms via `tiers`) | yes (`algebra gcd/scan`) |
| carry-over is a homomorphism; gcd kept iff images disjoint; gap as residual | T2 | proven | yes (`godel.carry`, `preserves_gcd`; unreal carry summary) |
| homomorphism cards per language pair, with sampled product law | ROADMAP G2 | not built | no |
| composition of carry maps with gap accounting | corollary of `carry_mul` | conjecture (no theorem, no test) | no |
| property transport up and down the lattice | T5 | proven | no |
| rewrite invariants refuse impossible equalities | T6 | proven (balanced rules only) | no |
| pruning the e-graph with T6 on a mixed rule set | — | conjecture | no |
| merges keep freeness; product equations break it | T4 | proven | yes (event kinds enforced) |
| structure code injective, decodable; admissible numberings | W-5, `numbering.check` | measured (tests on three sets) | yes |
| Gödel's 46 definitions and proof checker as cards | W-1 | measured (237 seeded agreements, Python = Lean) | yes |
| size model of codes; identity = sha256 of canonical term | W-3, GM-2 | measured | yes (CM45) |
| difficulty census: which questions are decidable | W-15 | proven for the upper bounds | yes (`difficulty`) |
| canonical identity with certificate | D6–D8, `egraph` | measured; soundness needs sorted laws (F1 open) | yes (`distill`, `sources`) |
| content read from canon_E, not the raw term | D11, A4 | required; F4 open | partly |
| behaviour canonical forms with Gödel numbers | CM31 | measured; proof tier where `tiers` sizes the witness | yes (`algebra`) |
| arithmetized execution over F_p with a stated error bound | W-12 | proven agreement (z3, exhaustive); probabilistic trace check | yes (`machine/arith.py`) |
| content with negative exponents (physics units) | GOALS item 3 | conjecture in the formal core (Vec is Nat → Nat); set not built (G3) | no |
| physics set, dimensional analysis witness | ROADMAP G3 | not built | no |

## 13. For the audit and the restructuring: where the structure should be underneath, and where not

The decisive test is FOUNDATIONS A7 and §0 of this document: **a function belongs on the Gödel structure when it
produces or consumes terms, and when its question is one the lattice, the code or a carry map answers.** It does
not belong there when its subject is a *value* rather than a *term* (constants and variables are not atoms, Rule-23),
or when its question is neither upward nor downward closed and has no canonical form (termination, speed), where
T5 says a proof per term is needed anyway.

Should be built on it (and mostly is): the ledger and content (`godel`), definitions and identities (`sources`),
canonical forms (`egraph`, `funcalg`, `realnorm`, `numbering`), translation and its gaps (`translate`, `matrix`,
`unreal`), the formal core (`formal`), the difficulty and tier census (`difficulty`, `tiers`), redefinitions and
laws (`redefs`, `laws`, `theorems`), the machine lifters that produce instruction terms (`machine/symbolic`,
`machine/arith`).

Should use it and does not yet (the cheap wins, in order): (1) read content from canon_E (F4); (2) a `godel
cofactor A B` command and cofactor-based redefinition cards, since the theorem is there and the user asked for it by
name; (3) T5 queries: "every card that inherits P" by divisibility, for fragment and occurrence properties, which
`analyse` and `coverage` currently answer by walking terms; (4) T6 as a pre-check in `egraph.equal` for the
balanced subset of E; (5) carry maps as cards with composition (G2), so a chain of translations has one computed
gap; (6) the physics set (G3) as the first non-code domain, which also forces negative exponents into the core.

Should not be forced onto it: runners, emulators, the arcade and build tooling (they execute; they are witnesses,
A7), observation statistics (`observe`, `learn`'s counting), the card store's JSON content hash (a different object
from D7's hash, FOUNDATIONS §5), and anything whose claim is about a measured time or a device.

## 14. The recipe for any definable system

To put a new system on the Gödel model, in the order the mathematics requires:

1. **Name the atoms** and make a `godel_set` card extending B0 (or another set). State each atom's arity. The
   ledger mints the primes (T3). Keep the atoms free: relations go in step 4 (T4).
2. **State the sorts and the model**: what the carriers are and what each atom computes (D1, D4, A2). If the
   system has no computation (a pure vocabulary like units), the model is the free monoid itself.
3. **Give the numbering** on the card: objects, code, content, identity, the six admissibility conditions, the
   provability form, and a witness test (W-5).
4. **Write the laws as sorted equations with evidence** (D5, A3, CM46). Mark which are balanced (T6).
5. **Define the carry maps** to and from existing sets, atom by atom; record `preserves_gcd` and the gap (T2).
6. Then everything in §1 to §11 applies: gcd and lcm of the system's objects, redefinition by cofactor, transport
   of properties, canonical identities with certificates, the difficulty census of its questions, and the honest
   tier on each answer.

The unreal set (3,310 atoms, one per engine function, with its carry map and gap) is the proof that steps 1 to 5
work on a large real vocabulary that is not the model's own. The physics set is the next one to run the recipe on,
and the first where the content group needs inverses.
