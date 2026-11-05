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

* **0.67 %** lift rate on a stdlib sample: most real code does not lift into T_Σ(X) yet.
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
