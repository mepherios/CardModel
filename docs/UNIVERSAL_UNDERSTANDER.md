# UNIVERSAL_UNDERSTANDER: learning any framework as a mathematical object

> **Status: PROPOSAL for the owner (2026-11-05).** Nothing in this document is built yet unless it names an
> existing command or engine. It is a design that composes pieces the model already has. Every claim it would
> make follows FOUNDATIONS A1–A7, and every redesign it proposes ships only with a certificate or a tiered
> witness (D8, D10). Content is never treated as meaning (GODEL_TARGET §3).

The owner asked for a "universal understander": a card model, used by the overlaying model, that learns any
framework or codebase and builds an *understood model* of its mathematical design, so the framework can be
optimized mathematically and its functional structures redesigned.

## 1. Definition: what "understanding a framework F" means

Understanding F means producing five objects, each in the vocabulary of FOUNDATIONS §2:

| object | meaning | made of | foundation |
|---|---|---|---|
| **Σ_F**, the signature | the operations and types F exposes | op cards (with `ir` ranks) and sort cards; F's public API surface, typed | D1, D2 |
| **M_F**, the model | the semantics of Σ_F | `ir.eval` where the op lifts; otherwise F itself, *run* as the witness (a black-box algebra) | D4, D14 |
| **E_F**, the laws | the equations F satisfies | `theorem` / `rewrite_rule` / `functional_identity` cards, each sorted and each with a tier (proof, probabilistic, bounded, sample: CM46) | D5, D10 |
| **T_F**, the terms | F's functions, lifted into the IR | terms in T_Σ(X); a callee that does not lift stays an **opaque** `CALL` boundary (#51, #52) and is listed, never guessed | D3 |
| **G_F**, Gödel content and structure | identity and shape of every concept | identity = `semantic_hash(canon_E(t))`; content γ(canon_E(t)) over ledger atoms; an atom F needs that the ledger lacks is a **proposal to the ledger writer** (CM43), never a self-assigned prime | D7, D11, D12 |

F is *understood to degree d* where d is measured, not asserted (§4): the fraction of F that is in T_F rather than
opaque, the fraction whose identity is canonical, and the number of laws per tier.

## 2. Pipeline, from existing pieces

```
observe → lift_project → learn → law discovery → e-graph canon_E → Gödel factor/similar/cofactor
        → carry maps to targets → improve/optimize (certificates) → redesign proposals
```

1. **observe** (`cardmodel observe PATH --save`, HANDOVER §3): inventory files, languages, entry points; this
   seeds Σ_F with candidate ops and sorts.
2. **lift_project**: cross-file lift into T_F. Callees that do not lift become opaque `CALL` nodes with their
   qualified names (#51, #52); the opaque set is the first measured gap.
3. **learn** (`cardmodel learn PATH --promote`): call, function and rewrite cards from the lifted terms.
4. **law discovery**: candidate equations over Σ_F, checked against M (or against running F, for opaque ops) and
   stored with their tier. A law on `float` is never promoted from an `int` witness (D6, A3).
5. **e-graph canon_E** (`engines/egraph.py`): saturate under E_F ∪ E, extract canon; identity becomes the D7 hash.
6. **Gödel**: `factor` (shared structure = gcd of contents), `similar` (near duplicates), `cofactor` (part-of).
   Uses are restricted to the GODEL_AUDIT decision rule: only **CORE** and **KEYED** uses; anything whose
   verdict is "not Gödel" uses ordinary data structures. Content is read from canon only (D11).
7. **carry maps** to targets (D13, D14; GODEL_AUDIT `carry_map(lang)`): the gap of F in language L is
   support(γ(F)) ∩ gap(L). The gap is the exact list of what cannot be expressed there.
8. **improve / optimize**: canon under measured host costs (D8, CM09). Each change carries the laws that fired;
   a substitution no law justifies is a labelled, tiered witness, never a rewrite.
9. **redesign proposals** (§3): written as cards, each with its evidence.

## 3. Mathematical redesign: what the model can propose

| proposal | how it is found | what makes it shippable |
|---|---|---|
| **Factor shared structure into a library concept** | `cofactor` / gcd of canonical contents across functions; Merkle identity in `lift_project` (GODEL_AUDIT: 484 arena functions → 81 identities) | the extracted concept, substituted back, is ≈_E-equal per call site: rewrite certificate |
| **Canonical form replaces equivalent variants** | functions with equal D7 hash, or shown equal by `search.prove` | equal hash under `laws` (certificate); under `behaviour` or `real` the record names the relation (D9) and its tier |
| **Closed forms for loops** | `funcalg` (Berlekamp–Massey, checked on unused terms) | tier of the `behaviour` witness, or a proof when a theorem fixes the witness size (D10) |
| **Algebraic restructuring under a cost model** | canon_E with measured costs (D8) | the certificate (laws fired), at the sorts they were proved for |
| **Interface (signature) minimization** | ops of Σ_F definable from others by laws in E_F (a derived op is a term) | each removed op has a defining law with tier ≥ the step's requirement; callers rewritten with certificates |
| **Dimensional / sort consistency** | order-sorted checking (D1): fixed-width sorts (WRAPU/WRAPS/F32), physics set (GODEL_TARGET §8) | a sort error is a finite counterexample (witness); a fix is a rewrite or a sort annotation checked by `sources check` |

Never shippable: a proposal justified only by content similarity (γ forgets arrangement and is not ≈_E-invariant,
D11), or by a hash difference (which means only "not shown equal", D7).

## 4. The understander as cards

* **`framework` card** (registry): name, source path and revision, Σ_F (refs to op/sort cards), E_F (refs to
  law cards), opaque boundary list, measured coverage, date measured.
* **`understanding` metrics** (recorded per run, like SELF.md rows):
  - lift rate: functions in T_F / functions observed;
  - canonical fraction: functions whose identity is computed on a canon (not a raw term);
  - law count by tier (proof / probabilistic / bounded / sample);
  - gap atoms: atoms with no ledger prime (pending proposals) and per-target carry gaps.
* **goals** (GOALS.md style): e.g. "lift rate of F ≥ x", "canonical fraction ≥ y"; each goal checked by a command.
* **CLI sketch**:

```bash
cardmodel understand PATH            # observe → … → report (metrics + proposals), writes the framework card
```

```bash
cardmodel understand PATH --propose  # also writes redesign proposal cards with their evidence
```

* **Self-application**: `cardmodel understand .` on CardModel itself. The first report is the baseline the
  understander must improve on; its proposals about CardModel go through the same review as any other.

## 5. Honest limits today, and the build order

Measured numbers this proposal starts from (reported in this session's stream, to be re-measured by the first
`understand` run):

* **1.68 %** lift rate on the Python 3.14 stdlib (223 of 13,300 functions, 6920ac6): most real code does not lift into T_Σ(X) yet.
* **24.6 %** of definitions have a canonical identity; the rest are identified on raw or α-normal terms.
* **Types are the blocker**: no arrays, tuples or records as sorts yet (D1 lists them as planned, MATH_CORE §4);
  the 16 Lean carry misses in GODEL_AUDIT are type and rank atoms.

Build order:

1. IR types: arrays BV(a) → BV(8), tuples, records as sorts (MATH_CORE §4; the NEXT_BUILD / IR types work).
   Without these the lift rate cannot rise.
2. Merkle identity in `lift_project` and `carry_map(lang)` (GODEL_AUDIT, KEYED and CORE rows).
3. Law discovery with tiers over Σ_F, including black-box witnesses for opaque ops.
4. The `framework` card and `understanding` metrics, then `cardmodel understand` (report only).
5. Redesign proposals (§3), each emitted only with its evidence.
6. Self-application on CardModel as the standing acceptance test.

## 6. Equality measurer: graded sameness of structures and functions

> Proposal. Nothing here is built unless it names an existing engine. Tiers are those of CM46 (proof,
> probabilistic, bounded, sample).

Given two structures or functions s, t (terms in T_F, or an opaque boundary run as a witness), the measurer
returns the **strongest level it can establish**, the evidence, and the tier. Levels are ordered; each implies the
ones below it for the relation it names (D9).

| level | relation | how it is decided | evidence | tier (CM46) |
|---|---|---|---|---|
| **syntactic** | same canonical term: `semantic_hash(canon_E(s)) = semantic_hash(canon_E(t))` (D7) | `engines/egraph.py` `canonical` then `semantic_hash`; α-renamed per GODEL_AUDIT row for `egraph.py` | the shared hash and the relation tag `under` | proof (equal canon is an identity; a *different* hash means only "not shown equal", D7) |
| **equational** | s ≈_E t: equal under e-graph congruence closure with the card laws E_F ∪ E | saturate both in one e-graph (`saturate`), test same e-class; or `search.prove` | the certificate: the laws that fired, at the sorts they were proved for | proof when every law fired is proof tier; otherwise the weakest tier among the laws used |
| **observational** | same results on witnesses or tests | run both on seeded witnesses (`ir.eval`, or F itself for opaque ops); `redefs.verify`-style exact then high-precision checks | the witness set, its generator seed and its sort | bounded when the witness set covers a finite domain exhaustively; probabilistic when a theorem bounds the error (D10); sample otherwise |
| **up to refinement** | s refines t (or s is a quotient of t): an abstraction map α with α(s(x)) = t(α(x)) | α given as a card; the commuting square checked equationally where it lifts, else observationally | α, plus the evidence of the square at its own level | the tier of the square's evidence |

Rules:

* **Gödel content similarity is never proof of equality.** γ forgets arrangement and is not ≈_E-invariant (D11);
  under GODEL_AUDIT a `similar` / `factor` hit is at most a **candidate for review** that the measurer then tries
  to decide at one of the four levels above. Tier: proof (it is a property of γ, GODEL_AUDIT).
* The answer may be **"not established"**; it is never a guessed "equal" (MATH_CORE search row). Tier: design rule.
* An observational result on one sort is not carried to another (a law on `float` is not promoted from an `int`
  witness, D6, A3). Tier: design rule.
* Every result is recorded with its relation (≈_syn, ≈_E, ≈_obs, ⊑_α), never as a bare "equal". Tier: design rule.

## 7. Structure optimizer: redesign under a cost model

> Proposal. It extends §3's "algebraic restructuring under a cost model" and the existing `improve` / `extract`
> path (D8, CM09). No measured numbers are given here; each row of the table below is to be measured.

### 7.1 Cost model

A cost is a tuple **(time class, memory class, constant factor)**, compared lexicographically by default:

* **time class**: asymptotic class (O(1), O(log n), O(n), O(n log n), O(n²), …). Measured, where possible, by
  deriving a recurrence from the lifted term and solving it (closed form, or a master-theorem style bound), or by
  `funcalg` closed forms for loops. Tier: proof when the recurrence is derived and solved; sample when it is
  fitted from timings at several n.
* **memory class**: the same, for peak live storage.
* **constant factor**: measured host cost (D8), as today's `improve` / CM09 do. Tier: sample.

### 7.2 Attaching a cost to an op card

Each op card gains a `cost` field per (rank, sort, target): a time class and memory class as functions of the
argument sizes, plus a measured constant with its host and date. A missing cost is **unknown**, not zero, and an
unknown-cost op blocks a "cheaper" claim for any term containing it. Opaque `CALL` nodes carry only a measured
(sample-tier) cost. Tier: design.

### 7.3 Rewrite search picks a cheaper equal term

Saturate the term in the e-graph under E_F ∪ E, then **extract** under the cost function (`egraph.py` `extract`
is additive today, GODEL_AUDIT; asymptotic classes need a non-additive extractor that composes sizes through
sub-terms). Every extracted term is in the same e-class, so it is ≈_E-equal by construction, with the laws fired
as its certificate. Tier: proof of equality at the laws' tier; the cost win is a separate claim (7.5).

### 7.4 Data-structure substitution as a refinement

Some wins are not equations over one signature but a change of representation: list → array, association list →
hash map, recomputation → memo table, repeated scans → prefix sums. Each is a **refinement** (§6, level 4):

* the concrete structure C, the abstract A, and an abstraction map α : C → A;
* **proof obligation**: for each op f used, α(f_C(x)) = f_A(α(x)) (the square commutes), and any invariant of C
  (e.g. a memo table only holds f's true values; f is pure) is preserved by every op;
* the obligation is discharged equationally where it lifts (proof), otherwise it stays a tiered witness and the
  substitution is labelled as such, never a rewrite (§2 step 8).

### 7.5 The shipping guarantee

A redesign ships only when **both** hold:

1. equality between old and new is established at the **equational level or better** (§6), or at the refinement
   level with its square discharged equationally; observational equality alone is not enough;
2. a **measured cost win** on the 7.1 model: a lower time or memory class with its derivation, or, at equal classes,
   a measured constant-factor win with its host and witness set.

Otherwise it is a proposal card with its evidence, not a change. Tier: design rule.

### 7.6 Examples

Illustrative only; no row has been measured, and each class claim must be derived by the optimizer before use.

| before | after | kind | equality needed | expected cost change (to be measured) |
|---|---|---|---|---|
| naive recursive Fibonacci | linear loop, or closed form via `funcalg` | rewrite / closed form | equational (or proof from a theorem fixing the witness size, D10) | time class: exponential → linear |
| recompute f(x) on repeated x | memo table keyed by x | refinement (recomputation → memo) | refinement; obligation: f pure, table holds only f's values | time class may drop; memory class rises |
| list with indexed access in a loop | array | refinement (list → array) | refinement; obligation: α = to_list commutes with get / set / len | indexed access: O(n) → O(1) |
| repeated range sums over a fixed array | prefix-sum array | refinement | refinement; obligation: sum(a[i:j]) = P[j] − P[i] | per query: O(n) → O(1), plus O(n) setup |
| `x * 2` on WRAPU | `x << 1` | rewrite under a law | equational (law proved at WRAPU) | constant factor only |
