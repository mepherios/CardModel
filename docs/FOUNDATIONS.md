# FOUNDATIONS: the mathematics every subsystem derives from

The user (2026-11-04): *"Ensure the card model is based on the underlying mathematics of the card model which grants
its strengths, not just a set of random functionality built on it; make use of the math model properly."*

GOALS.md says what the model is meant to be, and MATH_CORE.md has the plan and its progress. This document states
the mathematics exactly, as a small number of definitions. It then gives the rules that every subsystem follows,
and an audit of where the code met them on 2026-11-04 and where it did not. When a subsystem and this document
disagree, the subsystem is wrong, or this document needs a reviewed change.

## 1. The model in one paragraph

CardModel is a **many-sorted equational theory with one intended model**, numbered twice. The op cards are a
*signature* Σ. The card IR is the *term algebra* T_Σ(X) over Σ. The op cards' reference semantics are the *model*
M, a Σ-algebra. Every law, rule, redefinition and theorem is an *equation* that M satisfies, and every equation
carries the *tier* of its evidence. Reasoning is *congruence closure* under those equations, which is what the
e-graph computes. Distilling is choosing the cheapest representative of a term's class. Optimizing is the same
choice under measured costs, together with the chain of equations that justifies it. A language, a compiler flag,
a CPU or Lean is *another* Σ-algebra, and emitting code means reading a term in that algebra. The Gödel numberings
put a number on every term in two ways. Content is a homomorphism into the free abelian group on the primes, and
GCD, LCM and carry-over between domains happen there. Structure is an injective code, and it is the term's
identity. Every strength the model claims follows from one of these facts. Each one is in §3, next to the
condition it needs.

## 2. Definitions

**D1. Sorts.** The base sorts are `int`, `float` and `bool`: ℤ unbounded, IEEE binary64, and the booleans. The
sorts are *order-sorted* (`engines/sorts.py`). The fixed-width integers `u8`, `u16`, `u32`, `i8`, `i16` and `i32`
are subsorts of `int`, each the set of integers in its range. `f32`, the values a binary32 holds, is a subsort of
`float`. s ≤ t when every value of s is a value of t, so u8 ≤ u16 ≤ u32 ≤ int and u8 ≤ i16. The op cards WRAPU and
WRAPS (x mod 2^w, unsigned and two's complement) and F32 (rounding to binary32) produce these subsorts. Each card
names the sort of its result (`"sort": "u{w}"`). An operation keeps the ranks of its base sorts, and a law that
holds on a sort holds on all its subsorts (D6). Arrays BV(a) → BV(8) and tuples are the planned extension
(MATH_CORE §4). `nat` is not a sort. It is `int` with the hypothesis n ≥ 0. ℝ appears only as the declared model of
`realnorm` (D9), never as a sort of the IR.

**D2. Signature.** Σ is the set of op cards with an `ir` block. The rank of an op is its `ir.types` list: each
entry `[s₁, …, sₙ, s]` says the op takes sorts s₁ … sₙ to sort s. An op can have several ranks (ADD on int and on
float), and each rank is its own operation of the many-sorted signature. The special forms AND, OR, IF_EXPR, CALL
and LOAD are fixed by the IR (`engines/ir.py`), because they are lazy or touch state. Nothing else is an operation.

**D3. Terms.** T_Σ(X) is the set of IR expressions: leaves `["var", x]` (x has a sort), literals `["int", n]`,
`["float", r]`, `["bool", b]`, and applications `[op, t₁, …, tₙ]` that are well-sorted under some rank of the op.
A function is a system of recursive equations over terms. Its statements are notation for that system: a loop is
a least fixpoint, which `mathlang` writes out explicitly. The math language, the card language and every frontend
are concrete syntaxes for T_Σ(X), and none of them adds meaning.

**D4. The model M.** M interprets each sort as its carrier and each op as its card's `ir.eval`, compiled once by
`ir.op_table`. A partial op (division, mod, shifts, log) is undefined outside the `domain` on its card. For an
assignment ρ of the variables, the value ⟦t⟧ρ is defined by structural recursion. **M is the only meaning a term
has.** `ir.Interpreter` and `logic.eval_expr` both compute ⟦·⟧ from `op_table`, and they are the two sanctioned
evaluators.

**D5. Laws.** A law is a sorted conditional equation ∀x̄ : s̄. H(x̄) → l = r, with l, r ∈ T_Σ(X). It is *valid* when
M ⊨ it, meaning that for every ρ that respects the sorts and satisfies H, both sides are defined and ⟦l⟧ρ = ⟦r⟧ρ.
Laws are stored as `theorem` cards (with `vars` and their types), as `rewrite_rule` cards (with `domain` as the sort
of their variables), and as `redefinition` and `functional_identity` cards. E is the set of laws whose evidence
reaches the tier a step requires (D10).

**D6. Equational consequence.** ≈_E is the smallest congruence on T_Σ(X) that contains every *sort-correct*
instance of E. An e-graph (`engines/egraph.py`) represents a finite part of T_Σ(X)/≈_E. Its classes are
equivalence classes, its union-find with rebuilding is congruence closure, and saturation is the fixpoint of
instantiating E. **Soundness (Birkhoff):** if every law in E is valid in M, then t ≈_E u implies ⟦t⟧ = ⟦u⟧ in M.
This holds only when a law is instantiated at the sorts it was proved for. Associativity of `+` is valid on `int`
and false on `float`.

**D7. Canonical form and identity.** Take a cost c : Σ → ℝ≥0, extended additively to terms, and a fixed total
order to break ties. canon_E(t) is the minimum of c over the e-class of t, and the identity is
`semantic_hash(canon_E(t))`. Equal hashes mean ≈_E-equal, and so equal in M when E is sound. Different hashes mean
only "not shown equal" (Rice). canon is the only representative that has an identity.

**D8. Optimization.** Optimizing is canon under the costs measured on the host (CM09). The result comes with the
laws that fired, which is its *certificate*. A substitution that no law justifies (an algorithm swap, native code
called through ctypes) is a separate kind of claim. It is witnessed and labelled with its tier (CM46), and it is
never presented as a rewrite.

**D9. Other equivalences, each named.** The model uses these equivalence relations. Each identity record names
the one it was taken under in `identity.under`, using the key in the first column (`engines/equivalence.py`), and
`sources check` refuses an identity that names none:

| key | relation | decided by | what it identifies |
|---|---|---|---|
| `laws` | ≈_E | e-graph saturation, `search.prove` chains | terms equal under the sorted laws |
| `real` | ≡_ℝ (polynomial identity over a field) | `realnorm.canonical` | terms equal as real rational functions. This is sound for `int` polynomials (the finite-grid theorem in `tiers`), but **not** for `float` |
| `behaviour` | ≡_beh | `funcalg` (Berlekamp–Massey, checked on unused terms) and the `tiers` finite witnesses | functions ℕ → ℤ with the same recurrence and initial terms |
| `alpha` | ≡_α (renaming) | `numbering.canonical` | terms equal up to the names of their variables |
| `syntax` | = | nothing | the same term, with no reasoning applied |

**D10. Tiers.** The evidence for a claim is one of proof (Lean's kernel, or a finite witness whose size a theorem
fixes for the claim's class), probabilistic, bounded or sample (CM46). A step's conclusion inherits the weakest
tier among the laws it used.

**D11. Gödel content.** The ledger assigns a prime p(a) to each atom a (op cards, logic primitives, types), and
does so forever (CM43). Content is the map γ : T_Σ(X) → ℤ^(ℕ), the free abelian group on the primes, which counts
op occurrences: γ([f, t₁, …, tₙ]) = e_f + Σ γ(tᵢ). The order of divisibility makes it a lattice in which gcd is
the meet and lcm is the join (formal/GodelCore T1). It is stored sparse (CM45). γ forgets arrangement, so it is
**not** invariant under ≈_E: γ(a·(b+c)) ≠ γ(a·b + a·c). The content of a concept is therefore γ(canon_E(t)), read
from the canonical term, and never from the raw lifted term.

**D12. Gödel structure.** Gödel's positional code is injective on terms and decodes exactly
(`godel1931`, `funcalg`). It is the identity of a *syntactic* object. For a concept, D7's hash plays that role, and
the hash is computed on the canonical term.

**D13. Carry-over.** A map between two Gödel sets, or between two signatures, is fixed by the image of each atom.
On content it is a group homomorphism. It preserves gcd exactly when distinct atoms map to vectors with disjoint
supports (GodelCore T2). The atoms with no image form the *gap* of the translation.

**D14. Targets are models too.** A language L (with its compiler, flags and device) is a Σ-algebra M_L. The op
card's `emit` template for L is how L writes the op. codegen is the homomorphism T_Σ(X) → text_L, and a translation
is correct on the domain D where M_L agrees with M. The places where they disagree (fixed-width overflow,
truncating division, float contraction) are *divergence laws* of the form "M_L(op) ≠ M(op) iff cond", and they
belong to `analyse`. A frontend is a partial inverse of codegen, and the matrix checks samples of
lift ∘ emit_L ≈ id.

## 3. What the model can therefore do, and the condition each needs

| strength | the fact behind it | the condition |
|---|---|---|
| one function, every language | D3 and D14: one term, emitted by a homomorphism into each M_L | M_L = M on the domain, with divergence laws listed |
| knowing a function instantly | D7: a hash lookup on canon_E | E is sorted and sound, and canon is deterministic |
| proven optimization | D6 and D8: the cheapest e-class member, with its certificate | laws are applied only at their sorts |
| laws that carry into rewriting | D5: discovered laws become E | each law keeps the sorts of its variables |
| GCD and shared logic across code | D11: lattice operations on γ | γ is read from canonical terms |
| carry-over to new domains | D13: a homomorphism on content | images of distinct atoms are coprime, or the gap is reported |
| honest limits | D7 and D10: "not shown" is never "unequal", and every claim has a tier | no untiered claim exists |

## 4. Architectural rules (binding on every session)

These are the rules the audit checks. They are proposed as laws to be numbered from the registry.

* **A1. One signature.** Every operation an engine builds or matches is an op card, or one of the IR's special
  forms. A new operation means a new op card, with its ranks, `eval`, domain and emit templates.
* **A2. One model.** The value of a term comes from `ir.op_table`, through `ir.Interpreter` or `logic.eval_expr`.
  An engine that needs a different semantics (Lean's truncated Nat, C's float, ℚ, ℝ) declares it as a *named
  model*, with op cards of its own (as `theorems` does for Lean with LEAN_* ops), or as one of the named
  equivalences in D9. It never writes a private table of what ADD means.
* **A3. Laws are sorted.** A law records the sorts of its variables. Every rewriting engine (`egraph`, `search`,
  `improve`, `learn`) instantiates a law only when the classes its variables bind are of those sorts.
* **A4. Identity is canonical.** An identity hash or a content vector is computed on canon_E of the term, and the
  hash records the relation it is canonical under (D9).
* **A5. Optimizations are rewrites or labelled substitutions.** A change justified by laws carries its certificate.
  Any other change carries a witness and its tier. A change with neither does not ship.
* **A6. Targets are models.** A difference between a language and M is a divergence law in `analyse`, or a
  translation gap. Codegen never contains a per-language patch that silently changes meaning (CM16).
* **A7. New work produces or consumes terms.** This is MATH_CORE's rule. A feature that runs and compares without
  producing terms is a witness, not a method.

## 5. Audit (2026-11-04)

| subsystem | its place in the math | follows | departs (finding) | status |
|---|---|---|---|---|
| op cards, `ir.py` | Σ and M (D2, D4) | A1, A2 | none | reference |
| frontends (`frontend_python`, `frontend_text`, `lang`, `mathlang`) | concrete syntaxes onto T_Σ(X) (D3) | each language's `/` and `%` map to distinct ops (TRUNCDIV, REM, FLOORDIV, MOD), so meaning is kept | none found | ok |
| codegen, translate, matrix | homomorphisms into M_L, checked by sampling (D14) | A1, A6: templates live on cards | the matrix checks behaviour by sampling and not by a law. This is honest and labelled (tier sample) | ok |
| analyse | divergence laws M_L ≠ M (D14) | A6 | none | ok |
| **egraph** | ≈_E and canon_E (D6, D7) | congruence closure, extraction | **F1: laws are applied without sorts.** `rules_from_cards` drops each rule's `domain` and each theorem's variable types. Saturation therefore merges `(x+y)+z` with `x+(y+z)` when x, y, z are binary64, which is a false equality (0.1+0.2+0.3). The identities that `sources` builds for float terms inherited this: `lerp`'s identity came from distributing MUL over SUB on binary64, and `mean3`'s from reassociating a float sum | fixed: `engines/sorts.py`; the e-graph and `search` instantiate a law only at its sorts. Float laws that do hold (commutativity of ADD and MUL) are left to be stated as float-sorted theorems |
| **exprs** | a second evaluator | none | **F2: a private semantics table.** `exprs.evaluate` defines ADD, DIV, MOD and the rest by hand. Its `DIV` is exact over ℚ, where M's is binary64. Rule witnesses (`witness.verify_rule`), `egraph.witness`, redefinitions and `learn`'s rewrite checks are evaluated there and not in M Also **A1**: `exprs.parse` read `gcd(a, b)` in a rule card as a call `FN gcd`, not as the op GCD, so the five GCD rules never matched an IR term | fixed: `verify` and the capability checks witness rules in M (`verify_rule(ops=...)`, `egraph.witness(ops=...)`); `exprs.resolve_ops` turns a call of an op card's name into that op, and `load_rules` applies it; a test pins `exprs`'s integer mode to the op cards on their domains. The ℚ and ℝ modes stay, as the named model for redefinitions (D9) |
| search vs egraph | two rewrite engines over one E | same rules | F3: two engines. `search` finds explicit chains (proofs) and `egraph` finds classes (canon). That division is legitimate, but both must apply A3 | A3 in both (done) |
| godel content (`godel.card_content`, `sources`) | γ (D11) | ledger and storage laws | **F4: content is read from the raw lifted term**, not canon_E, so equal functions written differently have different content, and GCD measures syntax | fixed: a definition whose canonical term is the whole definition reads content and structure from it (`read_from: its canonical term`); `distance_sq`'s content is now that of `(a-b)·(a-b)` |
| realnorm, funcalg, numbering, tiers | named equivalences (D9) | each states its limits | F5: `realnorm`'s ≡_ℝ is applied to unreal's float32 math, where it is an approximation. It is labelled there as such. Its hash carried no tag naming the relation | fixed: every identity names its relation (`identity.under`), and `sources check` enforces it |
| unreal/witness | the C/IEEE target model M_C (D14): binary64 and binary32 arithmetic, the platform's libm, a float divided by zero is ±inf | declares IEEE semantics | F6: it had its own evaluator, never compared with M | resolved as a target model: a test pins it to every op card's value on that card's domain (55 ops, no disagreement), and it differs from M only where M is undefined. `f32` is now a subsort of `float` (D1), the sort of F32's results, with its laws (`f32(a) = a` for a of sort f32) |
| improve | D8 | rewrites are verified and re-verified; substitutions are tiered | rewrites are restricted to int-typed expressions, which is the right workaround for F1 | ok after F1 |
| learn, observe | evidence gathering | CM04, CM15 | statistics, not semantics, which is acceptable for observation. Its rewrite proposals go through F2's evaluator | F2 |
| machine (lift, symbolic, absint) | instruction cards as terms (MATH_CORE F5) | `symbolic` produces terms checked against the executable semantics, distilled to canonical terms under the register sorts (u8, u16) | `lift.py` folded constants through the op cards but simplified with hand-written identities (A3, A5) | fixed: the lifter's simplifications are the rule cards' unit and absorbing laws (`lift.unit_laws`), and nothing else |
| card store, kernel | storage of cards, content hash of JSON (CM02) | its identity is the hash of a card's JSON, which is a different object from D7's hash of a term | none | ok |
| self, selfrun | the model checking its own laws (CM27) | logic over the store | none | ok |

## 6. Order of work

1. This document (no behaviour change).
2. **Sorted e-graph** (F1, A3). Rules carry the sorts of their variables, each e-class carries a sort analysis, and
   a rule fires only on classes of its sorts. The planted float-associativity case is refused, and every existing
   int and bool proof still goes through.
3. **One model** (F2, A2). Rule witnesses and the e-graph's witness are evaluated in M through `op_table`. A test
   pins `exprs`'s int mode to the op cards on their domains, so the two cannot drift apart.
4. **Canonical content** (F4, A4). Definition cards read γ from canon_E when distillation reached one, and record
   which term was read.
5. Then F5 and F6 (hash tags, and F32 or BV(w) as sorts), with MATH_CORE phase 2.

## 7. Handover: state of this stream (2026-11-05)

Merged on main: this document (#16); sorted e-graph and search (#19, F1, A3); one model (#21, F2, A2); canonical
content (#22, F4); identities naming their relation (#23, F5); the Unreal evaluator as a target model (F6); the
subsorts `u8..i32 <= int`, `f32 <= float` with the WRAPU and WRAPS op cards and 21 laws (#30, D1); LR35902
instruction terms distilled under the register sorts (#31); the lifter simplifying only by the rule cards' unit and
absorbing laws (#49). Every row of the audit in §5 is fixed or pinned. No branch of this stream holds unmerged work
(`claude/project-thread-8z7gnb` equals main after #49).

Remaining, in order:

1. **Sorts for lifted machine code.** `machine/lift.py` folds machine terms without sorts. Give the lifter the ISA
   card's register widths (`symbolic.register_sorts`: A..L are u8, PC and SP are u16, read bytes u8) and run
   `egraph.canonical` with those `var_sorts` on each lifted block's register assignments, as `symbolic.distill`
   does. Then `x & 0xFF` on a u8 register folds away through `wrapu8_of_u8`. Bump `lift.LIFTER`. Witness:
   `test_machine.Lifting` (lifted blocks agree with the interpreter frame by frame) and a count of masks removed.
2. **Fixed-width ints and f32 as IR types.** Add `u8, u16, u32, i8, i16, i32, f32` to `engines/ir.py` `TYPES` (this
   stream owns IR types; nothing else adds them). The sort of each is already defined in `engines/sorts.py`. Each
   language card needs a type template per new type and each op card's `ir.types` the ranks at the new sorts, or a
   gap. Emit as wrap-on-store: a store to a u8 variable is `WRAPU(v, 8)`, and an f32 store is `F32(v)`.
3. **Conformance cells** for the new types in every language (`engines/conformance.py`): u8 and i8 overflow, u32
   multiplication, f32 rounding against `F32`. A language without a native width emits the WRAP template, so it is
   a cell that passes, never a skip.
4. **Frontends:** lift C `uint8_t`/`int32_t`/`float`, Rust `u8`/`i32`/`f32`, Go, Java and C# fixed-width types to
   these sorts instead of `int` or `float`.
5. Then `str`, tuple, Option, records, `raise` and truthiness, per MATH_CORE phase 2.

Rules to keep: a law fires only at its sorts (A3); every new simplification is a rule card witnessed in M
(`test_witness.Rules`); regenerate the definition packs with `python3 -B tools/seed_sources.py` and keep
`cardmodel sources check` passing. CI is out of Actions minutes. Merge on a full local `python -B -m unittest`
from `tests/` (about 40 minutes); V approved this.
