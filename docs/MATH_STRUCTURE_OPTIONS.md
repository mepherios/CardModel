# MATH_STRUCTURE_OPTIONS: putting more of CardModel's structure into its mathematics

**Status: proposal.** It is for the owner and for the Gödel and foundations threads to accept, amend or refuse.
Nothing here is a law, and nothing here changes the ledger. Written 2026-11-05 from `main` at 2781387.

[FOUNDATIONS.md](FOUNDATIONS.md) states the mathematics (D1–D14): a many-sorted equational theory whose signature Σ
is the op cards, one model M, the e-graph as congruence closure, canon_E and its hash as identity, Gödel content γ
in the free abelian group on the primes, and carry maps between signatures. Much of the model's *structure* still
sits outside that mathematics: the store is a directory of files, the five named equivalences are five different
code paths, codegen is a table of templates, loops are statements, products and sums are not sorts, and most laws
are witnessed rather than proved. Each option below moves one of these into the mathematics. For each it gives the
math, what changes in code and data, what it buys, the risk, and the tier of evidence (D10) the claim rests on today.

The decision rule of [GODEL_AUDIT.md](GODEL_AUDIT.md) §2 applies throughout: an option builds on the Gödel core
only for (a) permanent names, (b) part-of questions, (c) translations with a gap, (d) keys, or (e) composing
summaries. None of them uses the core to compute meaning (i), handle syntax or I/O (ii), read content from a
non-canonical term (iii), answer a question about values (iv), or carry a property that is not closed (v).

## 1. The card store as a quotient

**Math.** The store is a set of terms modulo the named equivalences: a card *is* an element of T_Σ(X)/≈_R for the
relation R its identity names (D9), keyed by `semantic_hash(canon_E(t))` (D7). The index is a map from content
vectors γ(canon_E(t)) (D11) to postings, so the divisibility order of the lattice becomes a query: "which stored
concepts contain this one" is "which vectors are ≥ this one".

**Code and data.** This is audit step 5 on top of step 2. Each identity record carries `(hash, under, basis
version)`; the store index keeps postings per prime over resolved vectors; `list --identity`, `--divides` and
`--similar` read it; the coverage denominator counts identities, not files. File names and the JSON content hash
stay as they are: they name *files* (decision rule ii), and the index maps them to identities.

**Buys.** Dedup by meaning rather than by bytes; the 47× speedup on divides queries measured in the audit; the
index that SCALING.md's S2 rung needs (10⁵–10⁶ functions cannot be scanned per query); a T5 transport query
(a closed property holds of everything above or below a concept).

**Risk.** A wrong law in E merges two cards that are not equal. The relation tag and the tier on each identity
contain this: a merge under `laws` inherits the weakest tier of the laws used (D10), and a merge below the tier a
consumer asks for is not shown to it. Identities are not stable across basis versions, so the index must rebuild
per version.

**Evidence.** Soundness of identity is Birkhoff (D6), proof tier given sound E. The 47× figure is a measurement.

## 2. One lattice type for all named equivalences; `resolve` as `carry`

**Math.** Each relation in D9 (`laws`, `real`, `behaviour`, `alpha`, `syntax`) is a congruence, and they are
ordered by inclusion: syntax ⊆ alpha ⊆ laws, and laws ⊆ real on `int` (finite-grid theorem) but not on `float`.
Each quotient map T_Σ(X) → T_Σ(X)/≈_R is a carry map in the sense of D13, and its image in content is a lattice.
`resolve` (from a lifted or redefined atom to its definition) is the carry map that sends an atom to the content of
its definition; it is a homomorphism, and its gap is the set of atoms without a definition.

**Code and data.** Audit step 4: one `Lattice` type with meet, join, order and `carry`; `realnorm`, `tiers` and
`funcalg` produce elements of it rather than their own records; `resolve` is implemented as `carry`; the `godel`
command gains `merge`, `deprecate`, `resolve`, `carry`, `decode`. Each identity names its relation (already
enforced by `sources check`).

**Buys.** One implementation of meet, join and transport instead of five; the inclusion order between relations
becomes checkable (a `laws` identity implies an `alpha` one, so a cache under the coarser key is reusable); the gap
of a resolve is reported, not silent.

**Risk.** Treating `real` as included in `laws` on `float` would be unsound; the inclusions must be stated per sort
and tested. GodelCore T2 (gcd preserved only for disjoint supports) limits which carries keep meets.

**Evidence.** The lattice laws are Lean-proved (GodelCore T1, T2). The relation inclusions are partly proved
(finite-grid theorem) and partly witnessed (`behaviour` via Berlekamp–Massey on unused terms: probabilistic tier).

## 3. Languages and targets as Σ-algebras; codegen as a carry map with a computed gap

**Math.** D14 already says a target L is a Σ-algebra M_L and codegen is the homomorphism T_Σ(X) → text_L. The
option makes that literal: the `emit` templates are the image of each atom under a carry map (D13), the atoms with
no template are its gap, and the divergence laws ("M_L(op) ≠ M(op) iff cond") are the defect of M_L against M on
each atom's support. A translation is correct on the domain D where the defect is empty.

**Code and data.** Audit step 3 and issue #53: codegen produces a carry map object with an explicit gap;
`conformance` cells become its verified image; `emit/lean.py`'s private table is removed in favour of the op
cards; `matrix.translation_gaps` and `lean_import`'s gap are computed from it; `analyse` divergence laws carry
per-atom supports. New atoms for a target (`LEAN_*`, ARM) are *proposal* cards; only the ledger writer mints them.

**Buys.** "Can program P be emitted to L, and where is it wrong" becomes a set computation: γ(canon_E(P)) against
the gap and the divergence supports. 137 of 153 Lean gaps (audit §6) become visible as data. The same construction
covers machines (step 6: LR35902 → ARM) and physics (GODEL_TARGET §8).

**Risk.** A template that is syntactically present but semantically wrong is not in the gap; the gap is only an
upper bound on what is missing. The matrix's lift ∘ emit_L ≈ id samples remain the check.

**Evidence.** The homomorphism property is by construction. Correctness on D is sample tier (matrix) or proof tier
where a divergence law is Lean-proved.

## 4. Programs as systems of recursive equations; loops distil to closed forms

**Math.** D3 already defines a function as a system of recursive equations whose loops are least fixpoints. The
option makes the system the stored object: a function is a tuple of equations x_i = F_i(x̄) over T_Σ(X), its
meaning is the least fixpoint in M (Kleene, on the flat domain of each sort), and distillation is solving the system
by known closed forms: linear recurrences (`funcalg`, Berlekamp–Massey), sums of polynomials, folds over ranges as
catamorphisms. A solved system has a canonical term, so it gets an identity and a content vector (D7, D11).

**Code and data.** Lifting emits the equation system rather than a statement list; `mathlang` already writes the
fixpoint out and is the reference. A solver pass tries recurrence, polynomial-sum and fold patterns, each producing
a closed form plus the law that justifies it. Unsolved systems keep the fixpoint as their canonical form, tagged
as such, so they still get an identity (under `syntax` or `alpha`, not `laws`).

**Buys.** Today a minority of definitions reach a canonical form (24.6% in the foundations thread's latest count;
re-measure before relying on it), because loops block canon_E. Most loop bodies in the corpus are counted loops,
accumulations and linear recurrences, which have closed forms; the target is to approach 90%. Every point gained
there feeds options 1–3, since content is only read from canonical terms (rule iii).

**Risk.** Termination is not closed (rule v): a closed form proved for the terminating case says nothing where the
loop diverges, so the solver must carry the loop's domain as a hypothesis H (D5). `behaviour` identities found by
Berlekamp–Massey are probabilistic until a degree bound makes them a finite witness (proof tier, D10).

**Evidence.** Kleene's theorem: proof. Each closed form: proof when the recurrence's order is bounded and the
witness count meets that bound, otherwise probabilistic. The 90% target is an estimate, not a measurement.

## 5. Products and sums as sorts (initial algebras)

**Math.** Extend the order-sorted signature (D1) with sort constructors: s × t, s + t, Option s = 1 + s, records as
labelled products, and arrays BV(a) → BV(8) (MATH_CORE §4). Each is the initial algebra of its constructors, so its
projections, injections and case analysis come with their laws (β and η for products and sums) for free, and
structural recursion over them is the unique homomorphism out of the initial algebra.

**Code and data.** `engines/sorts.py` gains sort constructors and subsorting through them (s ≤ s' implies
s × t ≤ s' × t); `ir` gains `TUPLE`, `PROJ`, `INJ`, `CASE` as special forms or op cards with ranks; the β/η laws are
rewrite rules with sort-parametric domains; frontends lift tuples, `Option`, and structs to them instead of to
opaque calls. New type atoms are proposals for the ledger.

**Buys.** Functions that return several values or an optional value become terms with a canonical form instead of
opaque, which raises the canonical fraction of option 4 directly. Records give the systems-code work of SCALING.md
(device registers, structs) a sort.

**Risk.** Sort-parametric laws must be instantiated per sort (the float-associativity lesson of D6); the sorted
e-graph needs sort analysis on constructed sorts. Aliasing and mutation are not products: structs passed by pointer
stay in the `LOAD` world until a memory model exists.

**Evidence.** Initial-algebra laws: proof (standard, and cheap to state in Lean). Lifting coverage gain: to be
measured.

## 6. Proofs: witnessed laws to Lean-proved

**Math.** Nothing new; it raises the tier of E. Of 114 rewrite rules, 47 are Lean-proved and the rest are
witnessed (MATH_CORE). Soundness of every identity under `laws` (D6) is only as strong as the weakest law that fired.

**Code and data.** For each witnessed rule, state it in Lean at its sorts, prove it (most are ring or bit-vector
identities `omega`, `ring`, `bv_decide` close), and record the proof on the card. Prioritise by how often a rule
fires in canonicalisations of stored cards (the identity index of option 1 gives that count).

**Buys.** Identities, dedups and merges at proof tier rather than witness tier; the merges of option 1 can then be
shown to consumers that require proof.

**Risk.** Low. A rule that fails to prove may be false at some sort; that is a finding, and the rule is narrowed.

**Evidence.** Proof, by definition, for each rule moved.

## 7. A category-level view: functors between Gödel sets

**Math.** Gödel sets with carry maps form a category; the quotient maps of option 2, the codegen maps of option 3
and the machine translations of step 6 are its morphisms, and composition of translations is composition of
carries, with gap(g ∘ f) ⊆ gap(f) ∪ f⁻¹(gap(g)). Models of a signature are functors from its syntactic category.

**Code and data.** At most a `compose` on carry maps that computes the composite gap, and a check that the
square lift ∘ emit_L commutes up to ≈ on samples.

**Buys.** Translation chains (C → IR → ARM, LR35902 → IR → Lean) get their gap from their parts without re-running.
Beyond that, little that options 1–3 do not already give.

**Risk.** Abstraction without a measurement. Do this only if a composed translation is needed and its gap is wrong
or slow when computed directly.

**Evidence.** The gap inclusion is a short proof; the payoff is unmeasured.

## Recommended order

| order | option | why here | depends on |
|---|---|---|---|
| 1 | 6 proofs | low risk, raises the tier of everything after it, can run in parallel | nothing |
| 2 | 2 one lattice, `resolve` as `carry` | audit step 4; gives the type the others use | audit step 2 |
| 3 | 1 store as quotient | audit step 5; the S2 blocker | 2, audit step 2 |
| 4 | 3 targets as algebras, codegen as carry | audit step 3, #53; can start in parallel with 2 | audit step 2 for caches |
| 5 | 4 recursive equations, closed forms | the largest gain in canonical coverage, feeds 1–3 | sorted e-graph (landed) |
| 6 | 5 products and sums | widens what 4 can canonicalise | 4, MATH_CORE phase 2 |
| 7 | 7 category view | only if a composed translation needs it | 3 |

Each step lands as its own PR with its measurement and keeps every test green, as GODEL_AUDIT §6 requires.

**Decisions for the owner** (law or ledger changes): new type atoms for products and sums; target atoms
(`LEAN_*`, ARM) as minted by the ledger writer; whether the store's canonical key replaces file identity in
user-facing commands; whether a `behaviour` identity at probabilistic tier may merge cards.
