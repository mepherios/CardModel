# GODEL_AUDIT: which functions build on the Gödel model, and which must not

The user (2026-11-04): *"Make it so all of the model is based inherently on this structure and understanding and
forced everywhere it's useful for it and increases scalability and where it can be optimized; make a full walkthrough
of which functions should have it as their underlying functionality and which shouldn't."*

This is that walkthrough. [FOUNDATIONS.md](FOUNDATIONS.md) states the mathematics (D1 to D14) and the rules A1 to A7,
and its §5 audit found where subsystems bypass the model (F1 to F6). This document asks a different question of every
subsystem and command: **should the Gödel model be its underlying functionality**, and if so, where does that make it
scale or let it be optimized. GODEL.md (a sibling thread) walks through what the model can do; GODEL_TARGET.md (the
restructure thread) is the design that acts on these verdicts. Every measurement here says what was run.

## 1. What only the Gödel model gives

The Gödel model is `engines/godel.py` with `numbering.py`, `codes.py`, `funcalg.py`, `godel1931.py` and
`machine/arith.py`, proved in `formal/GodelCore`. Each primitive below gives one ability that nothing else in the
model can replicate; the verdicts in §4 are about which subsystems need which ability.

| primitive | where | the ability only it gives |
|---|---|---|
| **the ledger** (CM43): every atom has a prime, forever, and the ledger only appends | `godel.sync`, `ledger`, `basis_version`; T3Ledger.lean (`enc_append`) | *names that compose across machines and time.* A vector read against basis version n reads the same in every later version, so a result computed on any worker at any date combines with any other without renaming. This is what makes a content-addressed, distributed store (SCALING §4.1, §4.4) sound. |
| **content** γ: the exponent vector of a term's atoms, a homomorphism into the free abelian group on the primes | `term_content`, `module_content`, `to_vector`; `gcd`, `lcm`, `divides` | *part-of and shared-structure questions decided in the size of the support* (W-15: decidable, promised), and *compositional summaries*: γ(module) = Σ γ(function). A package's content is the sum of its modules' without re-reading them, which is SCALING §3.1's summary principle as arithmetic. |
| **redefinition by cofactors**: an atom is a product of other atoms, or two atoms are one | `deprecate`, `merge`, `resolve`; T4Free.lean | *rewriting the basis without rewriting the data.* Every stored vector is read through the events, so a concept redefined as a product is recounted everywhere at once. Freeness is kept (an equation between products is refused), which is what keeps gcd a meet. |
| **structure**: Gödel's injective positional code, and the hash of the canonical term as identity (W-3, GM-2) | `structural`, `decode`, `codes.py`; `egraph.semantic_hash` | *one name per concept, with a decodable witness.* Equal hashes mean ≈_E-equal (D7). This is the key for every cache, index, dedup and library lookup. |
| **carry**: a map between signatures sends each atom to a content vector | `carry`, `preserves_gcd`; T2 in GodelCore | *translation as a homomorphism with a measured gap.* A language, a model, a platform or an ISA is an image of each atom; what has no image is the gap, computed without running anything. gcd survives exactly when images have disjoint support. |
| **admissible numberings** (W-5): six conditions a domain's numbering must meet | `numbering.CONDITIONS`, `check_set` | *a test for whether a new domain can enter the model at all.* Give a system a signature with arities and the conditions hold; the model is then usable on it, which is the user's "any system that can be defined". |
| **behaviour numbers** (funcalg): the Gödel number of a recurrence's canonical form | `funcalg` | *equal numbers mean identical behaviour* for the recognized class (≡_beh, D9), and GCD of functions with cofactors f = p·h, g = q·h gives the cross identity q'·f = p'·g. |
| **arithmetized execution** (W-12) | `machine/arith.py` | *one probabilistic check for a whole instruction*: terms become constraints over F_p, and a trace is one polynomial identity (Schwartz–Zippel), the basis of succinct proofs that code ran correctly. |
| **Gödel's 1931 definitions** (W-1) | `godel1931.py`, `formal/Godel1931` | *proof checking is primitive recursive and provability is ∃ of it* (Def-4): the model's own honesty about what it can decide (W-15) rests here. |
| **transport along divisibility** (T5) | `formal/GodelCore/T5Transport.lean`: `up_transport`, `down_transport`, `gcd_keeps_down`, `lcm_keeps_up`; **wired into no engine** | *a property proved once is inherited.* An upward-closed property (contains this factor) proved of a part holds of every model containing it; a downward-closed one (stays inside a fragment, an exponent bound) proved of a whole holds of every part; gcd keeps the downward-closed properties and lcm the upward-closed. "Which cards inherit P" is one `divides` scan over the index, not a proof per card. |
| **balanced-rule invariants** (T6) | `T6Invariants.lean`: `balanced_step`, `dot_step`; **wired into no engine** | *a rule's effect on content is a constant.* A balanced rule l → r (each variable as often on both sides), applied in any context under any substitution, moves γ by exactly ψ(r) − ψ(l), and any weight w with w·(ψ(r) − ψ(l)) = 0 is invariant under it. A linear cost w·γ therefore changes by a known amount per rule *before* the rule fires, and a content-preserving rule set keeps γ as an invariant of rewriting. |

Two limits bound every verdict. γ forgets arrangement, so it is read only from canonical terms (D11, F4), and it is
a *necessary* condition for equality, never a sufficient one. The positional code grows with the atom index (Ph-2),
so at today's ledger size it is a witness computed on demand, never an identity (GM-2).

## 2. The decision rule

A subsystem **should build on the Gödel model** when it needs one of these, and the verdict says which:

* **(a) a permanent, composable name** for what it produces (anything stored, cached, shared between workers or kept
  across versions);
* **(b) a part-of or shared-structure question** (what do these share, is this inside that, what is the common
  factor);
* **(c) a translation between signatures** (a language, a machine, a model of a theory, a physical system) whose
  gap must be known;
* **(d) a key** to dedupe, index, route or skip work by identity;
* **(e) a summary that composes** (a module from its functions, a package from its modules).

A subsystem **should not** build on it when its job is one of these:

* **(i) computing meaning.** The value of a term comes from M through `ir.op_table` (A2). Codes are names, not
  meanings; a Gödel number of a term says nothing about ⟦t⟧.
* **(ii) concrete syntax, I/O, processes and scheduling.** A frontend parses text into terms and codegen prints
  terms as text (A7); a runner starts processes; the store reads files. Their *outputs* get Gödel names, their
  internals do not.
* **(iii) reading content from a term that is not canonical** (F4). Until a term reaches canon_E, its content is
  syntax and must be labelled as such.
* **(iv) a question about values, not terms.** Constants and variables are not atoms (Rule-23), so whether an input
  overflows or what a call returns is M's question, not the lattice's.
* **(v) a property that is neither upward- nor downward-closed and has no canonical form** (termination, speed, a
  measured cost). T5 transports only closed properties, so these need a proof or a measurement per term, and the
  Gödel model can at most key the result.

GODEL.md §13 states the same rule from the theorems' side (produce or consume terms, A7, and ask a question the
lattice, the code or a carry map answers), and names the same exclusions: runners, emulators, arcade and build
tooling are witnesses; `observe` and `learn` are statistics; the store's JSON content hash is a different object from
D7's hash.

The four verdicts: **CORE** (its main data structure or algorithm is a Gödel construct), **KEYED** (it keys, caches,
dedupes, shards or routes by Gödel identity or content; this is where "forced everywhere it's useful" applies, because
it is where the model scales), **CONSUMER** (reports Gödel data), **NO** (with the reason from (i) to (v)).

## 3. Headline measurements (main at c6ecdc0, 2026-11-04)

Commands: `cardmodel godel ledger`, `cardmodel sources check`, and a census over `store.cards("definition")`
(`canonical.status`, `identity.of`, `godel.read_from`, `godel.structural`).

| fact | number | what it means for the verdicts |
|---|---|---|
| ledger size and shape | 3,411 atoms: B0 50, computation 13, machines 9, analysis 20, bits 9, **unreal 3,310**; loads in 0.41 s | 97% of the ledger is one domain's atoms. Atom index k enters every positional token as 3k + 1, so the structure code of any term touching a late atom is thousands of digits. GM-2 is not optional at this size. |
| positional numbers stored | 3 of 577 definitions | the structure code is already a witness, not an identity (W-3 decision confirmed in the data) |
| `structural(TRUNCDIV(a, b))` against `structural(ADD(a, b))` | 3,086 digits (index 3410, not stored) against 24 (index 19) | the ledger's order, not the term's size, decides a code's size; see §4.3 |
| the `godel` section of a quick verify | 100.7 s of 224.6 s; `numbering.check` 101.3 s on its own (re-run), all six sets pass | the model's most expensive self-check is decoding positional codes by trial division, and it cannot fail the section (GM-4 is a proposal). A valuation by squaring makes it 4.2 s (§4.3) |
| definitions by canonical status | 577 total: 512 `symbolic` (instruction terms), 11 `canonical` (e-graph), 5 `recurrence` (funcalg), 49 `pending` (a loop or several statements) | of the 65 *code* definitions, **16 (25%) have a canonical identity** and 49 hash their lifted term. FOUNDATIONS §3's "knowing a function instantly" and SCALING §4.8's semantic-hash library apply to a quarter of code definitions today. The scale lever is blocked by loop canonicalization, not by hashing. |
| identity hashes shared by several definitions | 2 hashes, 19 definitions | the identity already finds duplicates the names hide (instruction terms) |
| distinct content vectors | 158 over 577 definitions; 51 empty (moves: the unit) | for instruction terms over the 9 machine atoms content is coarse; part-of questions on machine code need structure, not content |
| content read from | 512 symbolic terms, 43 function IR, 22 algorithm forms (named per form: "its loop form", "its horner form", ...) | the F4 finding in numbers: 22 definitions' content is the content of one chosen implementation |
| `cardmodel godel gcd algorithm/gcd algorithm/lcm` | `{op/ABS: 2}`; neither divides the other. `lcm`'s content is `{ABS 2, OR 1, CMP_EQ 2, MUL 1, FLOORDIV 1, GCD 1}`: it holds `op/GCD` as one atom | the shared structure is invisible until `op/GCD` is *deprecated* as the product of Euclid's atoms. That is the ledger's cofactor mechanism (§1), and no engine calls `deprecate` today: the ledger has 0 events. Redefinition by cofactors is built and unused. |

Since c6ecdc0, main has appended 6 B0 atoms (the list ops of #13, `WRAPS` and `WRAPU` of #30): 3,417 atoms,
B0 56, 81 `op/` atoms, still 0 events; TRUNCDIV and REM stay at 3410 and 3411.

## 4. The walkthrough

Three passes, one per group, each run by its own audit agent with its measurements re-run here. Line numbers are at
main b137860 (the measurements stay at c6ecdc0). The scratch scripts named under "measured" live outside the repo;
each measurement says what it ran on.

### 4.1 Lifting and emission

Nothing in this group imports `godel` today. The nearest things to it: `translate.py:207` and `lang/run.py` build
`depends_on`, which is the support of γ computed ad hoc, and `frontend_text.emit_patterns` (`:1923`) derives parse
patterns from the op cards' `emit` templates, which is already an inverse carry map. Every identity hash in the group
is a digest of text or JSON (`translate.py:198` the source text, `lang/run.py:260` the module JSON, `runners.py:200`
and `native.py:67` the emitted text). None is D7's canonical hash, so no two of them agree on when two functions are
the same.

| module | does now | Gödel today | verdict | change | gain | risk |
|---|---|---|---|---|---|---|
| `engines/codegen.py` | `Emitter` (`:74`) reads each op's `emit` template; `EmitGap` is raised at about 20 sites; `supported_ops` (`:667`) is op → bool per language | none. `supported_ops` *is* the per-atom image of a carry map, and nothing calls it (only `__all__` names it) | **CORE** (rule c) | `carry_map(lang)` → {atom@rank: template} with its gap, over the op@rank atoms, the `core_type/*` atoms and the statement kinds; `gap(module, lang)` = support(γ(module)) ∩ gap(lang), checked before emitting; the map stored on the language card | a language's coverage is a set intersection, not a run of every function. Measured: it predicts 137 of 153 Lean emit gaps with 0 false positives; the 16 misses (15 "no type for float", 1 POW on float×float) are type and rank atoms the map lacks today | low. Syntactic gaps only; semantic divergence stays with `analyse` and `conformance` |
| `engines/conformance.py` | per op and rank, a one-line `return OP(a…)` runs in every language (`op_functions :43`, `run_language :77`) | none, though it already tests one atom of the carry at a time | **CORE** (c) | each cell (atom@rank, lang) → pass, fail or gap is the *verified* image in `carry_map`; a failing atom joins the language's semantic gap | one run per atom checks the carry for every function built from those atoms (a homomorphism): a function's risk is support(γ) ∩ failing atoms, with no run per function | the cells are samples (tier sample), and the carry must say so |
| `emit/lean.py` | `to_lean` (`:37`) prints from a private table `LEAN_INFIX` (`:28`) | none | **CORE** (c) | delete the table; read the image from the op cards' `emit.lean` through the codegen carry, with `NotExpressible` as the gap | one carry instead of two (A1, A6). Today they disagree on POW: `to_lean` wants a literal exponent, the card emits `({0} ^ ({1}).toNat)` | proofs written by `check_rules` may change form; re-run the `lean` checks |
| `engines/lift_project.py` | `ProjectLift.functions` keyed by qualified name (`:42`); `module_for` mangles names (`:47`); `CALL` holds file-qualified callee paths | none | **KEYED** (a, d) | `identity(qual)`: a Merkle hash in which each `CALL` target is replaced by the callee's identity (an SCC gets a stable placeholder for recursion), on the α-normalised function, with expressions canonicalised where `egraph.canonical` reaches a canon | the file paths inside `CALL` make one function look different in every language today. Measured on the arena: 484 functions, 245 distinct by α-hash, **81 by Merkle identity** (0.018 s); 16 of the 44 names present in several languages collapse to one hash | a cycle placeholder by *name* merges unrelated recursive functions; use the SCC's hash |
| `engines/sweep.py` (`lift-sweep`) | counts and first reasons only (`sweep :52`) | none | **KEYED** (d) | report distinct functions by identity, the duplicate clusters and the per-atom γ histogram; cache lift results by file sha | shows how much of a tree is new work (arena: 83% redundant); every later step (translate, matrix, analyse) can run once per class | low: reporting |
| `engines/translate.py` | `function_card` (`:174`, provenance = source sha `:198`); `verify_function` (`:220`) emits, runs and compares per language | `depends_on` ≈ support(γ) (`:207`) | **KEYED** (a, d) | put the identity (D7) and the stored γ (`godel.stored`) on the card; before verifying, look up (identity, lang, toolchain) and reuse; skip languages whose `gap()` is non-empty without emitting | skips the reference rows, the emission and the runs for duplicates: 484 → 81 on the arena. The runner's text cache already catches 484 → 88, but only at compile time | the cache key must include the toolchain versions and the seed policy |
| `engines/matrix.py` | `run` (`:200`); `cross_source` (`:142`) runs every pair of ports by name; `translation_gaps` (`:298`) counts emit failures from runs | none | **KEYED** (b, d) | `cross_source`: equal identity ⇒ equal (D7), skip the run, and run only pairs "not shown equal"; `translation_gaps` from `codegen.gap` before running; results cached by (identity, target) | single-return functions on the arena: 330 of 880 cross-language pairs are decided by hash with no run; the gaps are known without emitting | equal hashes prove equality only when E is sound (F1, the sorted e-graph); keep a sample witness beside the hash |
| `engines/analyse.py` | `LAWS` (`:363`) has per-language text per law; `Instrumented._expr` (`:470`) hardcodes which ops trigger which law (`FLOORDIV`, `MOD`, `TRUNCDIV`, `REM`, …) | none | **KEYED** (per atom; b) | each divergence law gets a `support` (its op atoms) and the table moves to the op cards as `diverges[lang]`; a static screen: laws that can fire = support(γ(fn)) ∩ law supports; skip the instrumented run when the screen is empty (the step, recursion and evaluation-order laws stay structural) | 170 of 684 corpus functions (25%) touch no op-triggered law. A language's divergence profile becomes card data (A6) | the budget, deep-recursion and eval-order laws are not per atom |
| `lang/run.py` | `function_cards` (`:221`) tries emission per language to fill `emit_gaps`; digest = raw module JSON (`:260`) | `depends_on` = op support | **KEYED** (d) | the same card builder as `translate` (identity and γ); `emit_gaps` from `codegen.gap` | one builder instead of three (`translate`, `lang/run`, `mathlang`); dedup against the store | low |
| `math_cli.py`, `engines/mathlang.py` (`math`) | parser `:366`; lowering `:801`, `:1115`; `simplify` (`:1726`) is equation housekeeping (dead parameters, forwarders, inlining), not laws; `_Emit` (`:1370`) prints math text | none | **NO** (ii) for the syntax; **KEYED** for its cards | route `math_cli.function_cards` through the shared builder; the parser stays | the same dedup | none |
| `engines/frontend_python.py`, `frontend_text.py`, `frontends.py` | concrete syntax → T_Σ(X) (`lift_source :737` / `:2944`; dispatch `frontends.lift :52`) | `emit_patterns` (`:1923`) inverts the op cards' templates | **NO** (ii), with one KEYED hook | leave parsing alone; optionally report a dialect's *lift* gap statically as the atoms with no call pattern (the inverse carry) | lift coverage per language without running | lowering is syntax-specific; γ inside it brings nothing |
| `lang/compile.py`, `lang/syntax.py` (`lang`, `repl`) | lexer, parser, compiler to IR | none | **NO** (ii) | — | — | — |
| `engines/observe.py` | `walk_python` (`:124`), `walk_tokens` (`:221`) count op and stdlib usage; `observe` (`:265`) hashes files | none | **CONSUMER** | report Σγ of lifted functions per atom, ledger-indexed, beside the AST counts | usage in the ledger's coordinates, which can guide what to mint or deprecate | none |
| `engines/runners.py` | compile and run; build cache keyed by sha(lang, source text) (`:183`) | none | **NO** (ii) | keep: the compiler sees text, so a text key is right here; dedup belongs upstream, by identity | — | — |
| `engines/native.py` | a C `.so` substitution (D8, labelled), cached by source digest (`:67`) | none | **NO** (ii); optionally KEYED | key the `.so` by (identity, compiler, flags) | marginal | it is a substitution, not a rewrite; it keeps its tier |
| `emit/lean_logic.py` | `Encoder` (`:53`) turns the logic model into Lean | none | **CONSUMER** | its coverage is the carry gap over the `logic/*` atoms (10 in the ledger) | — | low |
| `emit/lean_import.py` (`lean`) | Lean declarations → theorem cards (`import_source :924`); `lean_ops` (`:603`) builds private `LEAN_*` OpSpecs | none: the `LEAN_*` ops are neither op cards nor ledger atoms (the ledger has 75 `op/`, 7 `core_type/`, 10 `logic/`, 0 `LEAN_*`) | **KEYED** (inverse carry; a, c) | mint the `LEAN_*` atoms as cards (A1, A2: Lean is a named model); dedup imported theorems by canonical identity against the 1,650 stored theorem terms; unmapped Lean constants are the import gap | imported theorems get γ and an identity, so they join the GCD and carry machinery | minting is the ledger writer's call (GODEL_METHOD rule 1) |

**Measured** (scripts `dedup.py`, `diff.py`, `merkle.py`, `emitdup.py`, `canon.py`, `gap.py`, `gapfn.py`, `laws.py`;
the Merkle run was repeated for this document):

* *Dedup.* `arena/slowframework_optimized/native` (11 languages × 44 functions): 484 lifted; 246 distinct by raw hash
  with the name removed, 245 by α-hash (parameters and locals renamed), 39 by γ. Of 2,420 same-name cross-language
  pairs, the α-hash agrees on 1,207 (50%) and γ on 2,340 (97%): content is the loose necessary condition, structure
  the strict one. `tests/frontends` (15 languages): 85 lifted, 64 distinct by α, 56 by γ. `examples`: 115 of 138
  lift, 87 distinct by α, 73 by γ. The repo's own source lifts 19 of 2,475 functions, so it is not a corpus yet.
* *Why identical functions hash apart.* In every case printed (`combo_bonus`, `in_range`, `xp_for_level`) the only
  difference is the file-qualified `CALL` target: `"c/game.c::distance_sq"` against `"rust/game.rs::distance_sq"`.
  Hence the Merkle identity: 484 → 245 (α) → 81 (Merkle-α) in 0.018 s.
* *The runner's text cache.* The 484 arena functions emit 88 distinct C sources, so compile-level dedup already
  happens; identity keying adds the skips before it (lift-verify, reference rows) and the cross-language equality.
* *Canonicalisation on this corpus.* `egraph.canonical` on the α-normalised single-return bodies: 176 arena terms in
  0.04 s, 116 distinct both before and after; `examples` 32 → 31. The Merkle step matters more than the e-graph on
  ported code; the e-graph matters on code written differently.
* *A language's gap as a carry gap* (684 functions × 12 languages): the static prediction (γ(module) touches an op
  with no template) finds 137 of Lean's 153 emit gaps with 0 false positives; the 16 misses are type and rank atoms.
  The other 11 languages have 0 gaps on the corpus; their 4 to 14 unsupported ops never occur in it. Cost: about 0 s
  per language statically, against 2.51 s to emit every module.
* *The analyse screen:* of 684 functions, 170 (25%) have content outside every op-triggered divergence law; per law,
  490 hit `int_width`, 235 `int_div_zero`, 59 the float laws, 18 `shift_count`.

**The three changes in this group, by value:**

1. **One identity for lifted functions** (`lift_project.identity`: Merkle over callees, α-normalised, canonicalised
   where canon is reached), used by `sweep`, `translate`, `matrix`, `lang/run` and `math_cli`. One key then serves
   dedup, the cache (identity, lang, toolchain) and cross-source equality by hash. 484 → 81 on the arena.
2. **Codegen as an explicit carry map with a gap** (`codegen.carry_map`, `gap`), verified cell by cell by
   `conformance`, read by `emit/lean.py`, `matrix.translation_gaps` and `analyse`. Coverage becomes a set
   intersection on γ, and the second Lean carry (which disagrees with the cards on POW) goes away.
3. **Divergence laws keyed per atom** (`analyse`: a `support` per law, `diverges[lang]` on the op cards). A static
   screen clears 25% of functions without instrumented runs, and a language's semantic profile becomes data (A6).

### 4.2 The reasoning core

This group holds the model's three equivalence deciders (the e-graph for ≈_E, `realnorm` for ≡_ℝ, `funcalg` for
≡_beh) and the laws they run on. The finding that organizes the verdicts: **cost is already a linear functional on
content.** `search.expr_cost(t)` equals Σ_a γ(t)_a · cost(a) on 1,440 of 1,440 theorem sides, and `egraph.extract`
is additive in the same way, so extraction is minimizing ⟨γ, c⟩ over the e-class and T6 applies to it directly (a
balanced rule changes the cost by the constant ⟨ψ(r) − ψ(l), c⟩). The second finding: three modules carry their own
copy of the content group. `realnorm.Poly` (`:42`, monomials as sorted (atom, exponent) tuples, `_mono_mul :97`
adds exponents), `funcalg.Poly` (`:53`) and `tiers.Poly` (`:51`) are each ℤ^(ℕ) with +, gcd and lcm written again.

| module | does now | Gödel today | verdict | change | gain | risk |
|---|---|---|---|---|---|---|
| `engines/ir.py` | Σ and M: `op_table :111`, `Interpreter :196`, `ops_used :161` | `ops_used` returns the support of γ | **NO** (i) | none: meaning comes from M (A2); a code is not a meaning | — | — |
| `engines/exprs.py` | `parse :49`, `evaluate :164` (the private semantics, F2), `size :154` | none | **NO** (i, ii) | stays a parser; F2 is fixed (#21): rules are witnessed in M, and `exprs` keeps its ℚ and ℝ modes as a named model | — | — |
| `engines/egraph.py` (`distill`) | `rules_from_cards :80`; hash-consing of e-nodes in `_new`/`add_node :132–167`; `union :169`; `saturate :236` indexes candidate classes by the root head; `extract :265` (additive cost); `semantic_hash :291` hashes the JSON of the term *with its variable names* and no relation tag (since #23 the identity record beside it names one, `under`); `canonical :295` | `semantic_hash` only | **CORE** (identity; a, d) and **KEYED** (rules) | (1) dedup E by the α+sort identity of (lhs, rhs); (2) memo `canonical` across terms by the α-identity of the input; (3) `semantic_hash` = sha256 of the α-renamed canonical term (`numbering.canonical`), tagged with its relation (≈_E). Do **not** hash-cons e-nodes by Gödel number: the tuple key is already an injective structural code, and Gödel numbers grow without bound (W-3) | measured: saturation −32% with identical results on 600 of 600 terms; 47% fewer canonicalizations on theorem sides | low |
| `engines/rewrite.py` (`rewrite`) | picks a card's cheapest *form* by domain, language and availability (`candidates :130`, `cheapest :150`) | none | **NO** (ii) | it selects implementations, not terms | — | — |
| `engines/search.py` | `load_rules :34`, `rewrites :100`, `prove :136` (bidirectional BFS), `expr_cost :204`, `optimize :212` (one-sided BFS); states keyed by `repr` (`:83`) | none | **KEYED** (d) | share the deduped E with the e-graph; key states by identity, not `repr`; a content-distance heuristic only as a tie-break in the one-sided `optimize`; fix the cost of a named-function call (5.0 at `:207`, 1.0 in the e-graph's `FN:` heads) | modest | low |
| `engines/optimize.py` (`optimize`) | times forms on the host and writes metric cards (`measure_python_forms :85` … `apply_costs :310`) | none | **CONSUMER**, **KEYED** (a) | the op-cost vector it calibrates *is* the c in cost = ⟨γ, c⟩; key metric rows by the definition's identity so equal functions share timings | small | low |
| `engines/improve.py` (`improve`) | `algebra_candidates :295` (stores `form.godel()` `:326`); `cheapest_rewrite :375` runs search and `E.canonical` (`:387`) on every subterm; `rewrite_candidate :400` | funcalg's Gödel number, as a label | **KEYED** (d) | memo `cheapest_rewrite` by the subterm's α-identity. Do **not** add a content lower bound for pruning: measured, it prunes 0 of 132 | memo hits | low |
| `engines/realnorm.py` | `Poly :42`, `canonical :311`, `digest :427`; atoms interned (`_intern :191`) | none in name; **structurally it is the content group** over variables and opaque atoms | **CORE** (rule e) | build `Poly` on the one sparse-vector lattice type that godel content uses (one implementation of +, gcd, lcm, divides); tag `digest` with ≡_ℝ (F5) | one algebra instead of three `Poly` copies; monomial gcd for free | medium: it touches the normal form, so the ≡_ℝ tests must stay green |
| `engines/funcalg.py` (`algebra`) | `Poly`/`pgcd`/`plcm :53–170`; `Form.godel :264` → `godel_encode :344` (the positional code of the recurrence); `gcd_functions :455` (annihilator gcd with cofactors); `scan_algorithms :562` (pairwise, O(n²), classes keyed by the positional integer `:589`) | yes: a Gödel numbering of behaviours | **CORE, to be changed** (a, b) | identity = sha256 of `code()`: a `functional_identity` card stores a **672-digit** positional number today, over CM45's 200-digit cap and against the GM-2 decision (1 of the 11 cards; 5 carry a number). Factor each annihilator into irreducibles over ℚ[E], make each irreducible an atom of a *behaviour* Gödel set, and an annihilator is a content vector: gcd, lcm and the cofactors become the D11 lattice operations, and the pairwise scan becomes an inverted index on support | one mechanism for all cofactor questions; a sub-quadratic scan | medium |
| `engines/numbering.py` | each set's numbering and admissibility; `canonical :200` (≡_α) | yes | **CORE** | `canonical` feeds every identity hash (e-graph, theorems, laws, learn) | — | — |
| `engines/codes.py` (`godel sizes`) | measures six codes per term | yes | **CORE** (as measurement) | none | — | — |
| `engines/godel1931.py` | Gödel's 46 definitions and a proof checker for system P | yes | **CORE as a reference library; NO as a runtime dependency** | no engine computes with its codes (the set axiom one type up is about 40 M bits, W-1) | — | — |
| `engines/tiers.py` (`tiers`) | a third `Poly :51`; `shape :217`, `plan :453`, `prove :562` | none | **KEYED** (d) | cache proof results by (identity pair, relation); its `Poly` on the shared type | small | low |
| `engines/laws.py` (`laws`) | `candidates :105` (3,310 of them), `discover :233` witnesses every candidate and then proves in Lean, `rule_card :202` | none | **KEYED** (d) | skip candidates whose α+sort identity is already a stored theorem: 162 of 3,310 are, which is about all of the 161 laws found before, so each run witnesses and re-proves them in Lean. Content cannot prune validity: γ is not ≈_E-invariant and only 27 of 176 laws keep it | an incremental `laws` run with no repeated Lean proofs | low |
| `engines/theorems.py` | `witness :335`, `prove :521`, `settle :568` | none | **KEYED** (a, d) | an identity per statement (variable sorts, α-canonical hypotheses and conclusion); dedup the store (63 redundant cards by exact statement, 87 under α, among 1,650); cache Lean results by identity | less storage, fewer proofs | low, if evidence is merged across duplicates and no proof is dropped |
| `engines/redefs.py` | `verify :563` (seeded points, exact then 30 to 240 digits), `_sympy_check :635` | none | **KEYED** (d), with a link to the ledger | decide by `realnorm.canonical` first: it proves 61 of 111 cards equal under ≡_ℝ (proof tier) before any sampling; group cards by source identity (111 cards cover 40 concepts, 18 with more than one card). A redefinition whose left side is one op over distinct variables is the *only* valid trigger for the ledger's `deprecate` | 55% of redefinitions move to proof tier; dedup | low |
| `engines/witness.py`, `witness_runner.py` | `verify_forms :217`, `verify_rule :360` (in M with `ops`, since F2's fix, #21); a unittest runner | none | **NO** (i); optionally a result cache keyed by (identity, seed) | evaluation belongs to M | — | — |
| `engines/logic.py`, `selflogic.py` (`logic`) | `DB :625` (tuple-hash indices), `evaluate :875`, `proof :810`; `store_facts :24` | none | logic **NO**; selflogic **CONSUMER** | a Python tuple is already an injective, hash-consed key, and Gödel numbers would only add size. `selflogic` should emit ledger facts (atom, prime, set, the merge and deprecate events, content-divides) so CM43 and CM45 can be stated as self-laws | CM43/CM45 checkable in logic | low |
| `engines/learn.py`, `mine.py` (`learn`) | `propose_rewrites :140` (dedup by `repr :163`, `search.optimize :167`), `check_rewrite :194` (through `exprs`, F2); `mine` is statistics over relations | none | learn **KEYED** (d); mine **NO** | dedup proposals by α-identity; name a suggestion by identity rather than by file:line (`:175`), so its name survives the code moving | fewer proposals | low |
| `engines/difficulty.py` (`difficulty`) | `check :25`: the rank of each question | reports on the Gödel questions | **CONSUMER** | none | — | — |
| `engines/sources.py` (`sources`) | `_godel :49` reads content from the canonical term when it is the whole definition and from the raw term otherwise (F4, #22), `identity :62` (tagged with its relation since #23), `_canonical :79`, `build :118` | yes: this is where identity and content are minted | **CORE** | read γ from the canonical term in the remaining cases; α-normalize the identity hash | — | — |
| `engines/values.py` | generators, `same :109`, `key :148` | none | **NO** (iv) | values are meanings, not codes | — | — |
| `engines/codefacts.py` | `facts_for :39`: the Python call graph as facts | none | **NO**; optionally a `pure_core` fact carrying the definition's identity | — | — | — |
| the `godel` command (`cli_ext.py:525`) | `sizes`, `ledger`, `vector`, `gcd`, `lcm` | yes | **CONSUMER** | there is no command for `merge`, `deprecate`, `resolve`, `carry`, `structural` or `decode`; `gcd` and `lcm` read raw lifted content (F4) | the cofactor features become usable | low |

**"Redefining structures by their cofactors" is one algebra written three times.** Each of these is the gcd, lcm,
divides lattice of a unique-factorization domain:

* the ledger's `deprecate` (`godel.py:156`) on content. Its reader `resolve` (`:179`) is `carry` (`:406`) with the
  mapping {atom: product}, the identity elsewhere and no gap, iterated to a fixpoint; it should be implemented as
  `carry`. The ledger has **0 events** among 3,411 atoms, and only **one** law in E is definitional (an op over
  distinct variables equal to a term over other ops): `xor_as_or_minus_and`. Nothing in the store triggers
  `deprecate` today, which is why `gcd(algorithm/gcd, algorithm/lcm)` in §3 sees nothing;
* `funcalg`'s cofactors, the same lattice over ℚ[E] and ℚ[n]. Once annihilators are factored into irreducibles
  registered as atoms, they are content vectors and the cofactors are quotients in the lattice;
* redefinition cards, which are equations (laws), not cofactor events. Only a *definitional* redefinition,
  f(x̄) = t with f not in t, should produce a `deprecate`; every other one belongs in E, the transformation layer
  that `godel.py`'s own docstring names.

The recommendation is one sparse exponent-vector type with gcd, lcm, divides and carry, shared by godel content,
the `realnorm` and `tiers` monomials and `funcalg`'s annihilator factors, with the *carriers* kept apart: content
is not invariant under ≈_E, polynomial normal forms are invariant under ≡_ℝ, and the hash of each says which.

**Measured** (scripts `m1.py` to `m10.py`, against the live store through `Ctx`; the E dedup and the stored
positional numbers were re-run for this document):

1. *What content says about the laws.* `rules_from_cards` gives 241 rules (89 from rewrite-rule cards, 152 from
   theorems; 65 are reversals). Of the 176 unreversed: γ(l) = γ(r) for **27**, the right side's content divides the
   left's (a shrinking rule) for 104, the left's divides the right's for 27, incomparable for 18 (De Morgan, the
   dualities, `square_as_mul`, `double_as_shift`, `xor_as_or_minus_and`, `difference_of_squares`). Equal content is
   a necessary condition for 27 of 176 laws, so content cannot prune law discovery.
2. *Duplicates.* E's 241 rules are 155 distinct by the pass's α-identity of (lhs, rhs) (86 redundant, 36%; the
   re-run with `numbering.canonical` on the ordered pair finds 165 distinct, 76 redundant), e.g.
   `rule_absorb_left_MUL_0` beside `law_absorb_left_MUL_0`. The 1,650 theorems hold 61 groups with 63 redundant
   cards by the exact statement with sorts, 81 groups with 87 redundant under α; 18 groups pair a discovered `law_*`
   with a `lean.Int.*` theorem.
3. *Saturation* (600 terms: 60 random int terms of depth ≤ 4 and the theorem sides; `max_iter=5`,
   `max_nodes=1500`): baseline 5.86 s; **E deduped by identity 3.99 s (−32%)**, the same canonical hash on 600 of
   600; an LHS-content prefilter 5.74 s (−2%) with global support and 5.85 s (0%) per class; both together 3.85 s.
   The 8 function-card terms: 0.16 s → 0.11 s. The prefilter does not pay because `saturate` already indexes
   candidates by the root head, and cProfile puts 11.5 of 21.8 s in `ematch` on matches that *succeed*.
4. *Memo by identity.* The 948 equation sides of hypothesis-free theorems have 595 distinct raw forms and 499
   distinct α-forms: memoizing `canonical` by α-identity saves 47% of the calls.
5. *A content lower bound for pruning rewrites.* The naive bound ("no rule explicitly decreases these atoms") would
   skip 29 of 132 function-body expressions but is **unsound**: absorb, idempotence and self-cancel rules drop
   variables and so delete whole subterms. The sound version (support closure, then whether any shrinking rule
   applies) prunes 0 of 132. Not worth building.
6. *Content distance as a search heuristic* (80 goals, each a theorem side with 3 random rewrites applied, 94
   unconditional rules): bidirectional BFS (`prove`) solves 80 of 80 with 6,689 nodes in 0.23 s. One-sided search:
   uniform cost solves 69 with 723k nodes in 37 s; weight 1 on the content L1 distance solves 79 with 169k nodes in
   5.8 s (4.3× fewer nodes); weight 4 solves 53. Keep bidirectional BFS for `prove`; the heuristic helps only the
   one-sided `optimize`, and it is not admissible (rules that drop variables break the per-step bound).
7. *Redefinitions.* Of 111 cards, `realnorm.canonical` proves 61 equal and leaves 50 undecided; the sources reduce
   to 40 canonical concepts, 18 of them with several cards.
8. *Laws re-run.* 162 of the 3,310 candidates already exist as stored theorems under the α+sort identity. A witness
   costs about 1.3 ms per candidate, so the real cost of a re-run is the repeated Lean proofs.

**The three changes in this group, by value:**

1. **One identity key for every law**: dedup E, the theorems and the law candidates by the α-canonical statement with
   its variable sorts (the same key A3 and A4 need). −32% saturation with identical results; 76 to 86 redundant
   rules, 63 to 87 redundant theorems, 162 candidates whose Lean proofs `laws` repeats on every run.
2. **Canonical identity as the memo key everywhere**: `egraph.canonical`, `improve.cheapest_rewrite`, `sources`,
   `learn`, and the `tiers` and `theorems` proof caches. `semantic_hash` becomes α-renamed (`numbering.canonical`)
   and tagged with its relation (≈_E, ≡_ℝ, ≡_beh, ≡_α). 47% fewer canonicalizations on theorem sides.
3. **One content lattice type, with `carry` as the single mechanism for "redefine by cofactors"**: `resolve`
   becomes `carry`; `realnorm`, `tiers` and `funcalg`'s factors are built on the type; `funcalg`'s identity becomes
   the sha256 of its code (which ends the 672-digit numbers that break CM45); only definitional redefinitions emit
   `deprecate`; `redefs` decides by `realnorm.canonical` first (61 of 111 to proof tier); the `godel` command gains
   `merge`, `deprecate`, `resolve`, `carry` and `decode`.

**Not worth doing, measured:** an LHS-content rule prefilter (≤ 2%), a content lower bound on cost (prunes 0 of
132), hash-consing e-nodes by Gödel number, and Gödel keys for logic facts.

### 4.3 Kernel, self-run and domains

The finding that organizes this group: **the Gödel check is the most expensive thing the model runs on itself, and
almost none of that cost is the Gödel model.** A quick verify (`verify.run(only=QUICK)`, seed 1) takes 224.6 s, of
which the `godel` section is 100.7 s; the self cycle's quick verify is about 132 s, of which `godel` is 76%, re-run
every cycle on unchanged inputs. Inside the section, `numbering.check` is 101.3 s (re-run for this document) and
`Numbering._codes` alone 100.4 s over 8,640 decodes; everything else in `godel.check` is 0.43 s, and reading the
content of every op, function and algorithm card is 0.004 s. The decode is slow for one reason: `unreal/cards.py`
synced 3,310 named atoms, so the core ops TRUNCDIV and REM, added later, sit at ledger indices 3410 and 3411. Their
positional token is 3k + 1 ≈ 10,231, B0's sample codes reach 56,807 bits, and trial division once per exponent is
quadratic. `structural(TRUNCDIV(a, b))` has 3,086 digits where `ADD(a, b)` has 24. A p-adic valuation by repeated
squaring (prototyped in scratch, not in the repo) takes 40 B0 codes from 1.02 s to 0.05 s and the whole
`numbering.check` from 101.6 s to 4.17 s with every set passing and identical results on the sets compared. Then
the cause: positional codes from per-set dense ranks derived from the append-only ledger, so a core term never gets
a thousand-digit code (this amends how CM43 and GM-4 number positions, which is the user's decision; old codes keep
decoding by their basis version).

| module | does now | Gödel today | verdict | change | gain | risk |
|---|---|---|---|---|---|---|
| `kernel/store.py` | registries load lazily through a SQLite *location* index (`kernel/index.py`, #18: name → card directory or pack offset, no hashes); `save`/`save_pack` (`:185–216`) | none | **KEYED** (a, b, d, e) | extend that index toward SCALING §4.1 with columns card JSON hash, identity hash **with the relation it is canonical under** (A4, F5), basis version; a posting table (atom, exponent, card) built from vectors read through `godel.resolve`; API `by_identity`, `divides(v)`, `multiples(v)`, `top_k_gcd(v)` | measured on today's 577 vectors (in-memory SQLite): "ADD·MUL divides v" 4.2 ms by scan, 0.09 ms through the index (47×), the same 25 answers; no full load; T5 transport becomes a query | rows go stale unless keyed by the card hash and rebuilt on save; untagged hashes would merge ≡_ℝ and ≈_E identities; vectors not resolved through events read wrong after a `deprecate` |
| `kernel/registry.py` | loads card dirs and `_pack*.jsonl` | none | **NO** (ii) | file I/O; it can feed index rows in the same pass | — | — |
| `kernel/canon.py` | canonical JSON, `card_hash` (`:92–94`) | none | **NO** | the card JSON hash (CM02) is a different object from a term's identity (FOUNDATIONS §5, "card store"); both stay, as separate columns | — | — |
| `kernel/card`, `schema`, `types`, `paths`, `versioning` | the card object, validation, closure, paths, semver | none | **NO** | optional: a schema for the `godel` record; today only `sources.py:258` checks its shape (`vector_problems`) | — | — |
| `kernel/resources.py` | the memory and CPU governor, subprocesses | none | **NO** (ii) | the shard key belongs to the work queue, not here | — | — |
| `engines/context.py` | `Ctx`, `ops` cached (`:15–21`) | none | **CONSUMER** | cache `ledger`, `index_of` and `events` beside `ops` (`godel.py:450` rebuilds the atom set once per card) | small: `ledger()` is 0.06 s cold, about 1 ms warm | stale after `sync` unless invalidated |
| `engines/integrity.py` | law and goal ids, wiring, docs, merge markers | none | **NO** | text and structure checks; `godel.check` already checks the ledger's shape | — | — |
| `engines/verify.py` (`verify`) | runs the sections; `godel` calls `godel.check` (`:302–304`) | runs it | **KEYED** (d) | cache each deterministic section's result under the hash of its inputs; for `godel`: the ledger pack, the HEAD ledger blob and the godel_set, op, function and algorithm registry hashes (numbering uses seed 0). Note that `numbering.check` is 98% of the section and *cannot fail it* ("GM-4 is a proposal", `godel.py:456`) | 100.7 of 224.6 s | a key that misses an input (git HEAD) gives a stale pass |
| `engines/coverage.py` (`cover`) | inventory and metrics; `content_vector_coverage` = `godel.check`'s coverage (`:283–285`) | reads | **CONSUMER** | fix the denominator: it is 1.0 over 140 cards (op 75, function 43, algorithm 22); uncounted are theorems (1,628 of 1,650 readable), definitions (577 stored, but `card_content` has no `definition` rule, `godel.py:237–261`), 114 rewrite rules and 111 redefinitions | an honest metric | the metric drops, so the floor needs an `amended` note |
| `engines/capabilities.py` | smoke checks; `godel_model` (`:584–615`) covers sync, gcd, divides, structural/decode, stored, carry | uses | **CONSUMER** | add a merge → deprecate → resolve round trip in its temp store: `resolve` has no production caller and events are tested only in `tests/test_godel.py:162–177` | "redefine by cofactors" becomes a guarded core capability (CM37) | none |
| `engines/projects.py` (`init`, `status`), `docs.py`, `probes.py`, `selfcheck.py`, `clean`, `install` | project cards and git state; LAWS.md; toolchain probes; static checks; cache and PATH | none | **NO** (ii) | — | — | — |
| `engines/arena.py` (`arena`) | plants renamed suboptimal forms (`:137–145`), runs `improve`, scores recall | none | **CONSUMER** | score *identity recall*: does a planted copy hash to its card's canonical identity? renamed variables must collide under the structural code | measures D7 ("knowing a function instantly") directly | F4: content is read from raw terms, so misses are expected; label the tier |
| `engines/selfrun.py` (`self`) | step cards; a step runs when its timer is due or its registries' JSON hashes changed (`:203–207`, `:580–597`); `learn` per corpus by tree hash and input hashes (`:346–373`); the verify step every cycle (`:276–297`) | none (runs `godel` through verify) | **KEYED** (a, d) | the SCALING §4.3 work queue with function units keyed by the canonical term's hash, content work keyed by basis version, and the `godel` section cached as in verify. `learn` dedupes by *name* (`learn.py:253`, `:260`): dedupe by identity, and emit a `merge` proposal when two names hash equal | the cycle's quick verify is about 132 s with `godel` 76% of it, re-run on unchanged inputs | a different hash must never be read as "different function" (F4) |
| `cli show` (`cli.py:653`), `list` (`:666`), `new` (`:692–701`) | raw card JSON; names per registry; a stub card | none | **CONSUMER** | `show`: a `_godel` view (content resolved through events, identity with its relation, index and prime when the card is an atom); `list --identity H`, `--divides X`, `--similar X` (top k by gcd size) over the index; `new op` makes the next verify fail ("atoms not in the ledger", `godel.py:450–452`), so it should write a ledger *proposal* card (GODEL_METHOD rule 1: one writer) | — | `list` needs the index first |
| `machine/symbolic.py` (`symbolic`) | symbolic execution of instruction IR into terms; definitions with identity and a godel record (`:238–289`) | **CORE, for the LR35902 only** | **CORE** (a, c) | the effects are hard-coded to Game Boy bus names (`:28–30`): read them from the ISA interface card and the godel_set arities; add the ARM atoms (rd16, rd32, wr16, wr32, swi, undefined_op, cp_read, cp_write) so the 167 ARM cards get definitions (0 today); hash identity on canon_E, not on raw terms (`:271–273`, A4); a family identity modulo register renaming | 512 definitions → 495 identities (11 illegal-opcode hangs, 8 NOP-equivalents such as `LD r,r`) → 190 families (the largest 42: `LD r,r'`). Only 103 distinct content vectors: content is too coarse to tell instructions apart. The carry LR35902 → ARM has image {rd8, wr8} and gap {idle, idu, rd8_idu, halt, stop, hang, cb_dispatch}; the B0 ops carry by identity | ARM → GB with rd16 → rd8², rd32 → rd8⁴ shares support, so `preserves_gcd` is False and must be reported (T2); ledger appends are permanent |
| `machine/arith.py` | W-12: circuits over F_p; exhaustive, z3 and trace checks (`:515–556`) | consumes terms | **KEYED** (d) | memoize per α-canonical term, keeping each variable's width (`arith.width`) | 1,075 outputs → 588 distinct → 157 up to width-preserving renaming; `arith.run(limit=120)` is 47.95 s (0.40 s per output), so about 430 s → about 63 s (6.8×, estimated) | a renaming that drops widths makes the check wrong |
| `machine/lift.py`, `lift_arm.py` | ROM → blocks → specialised IR, cached by (ROM sha1, machine hash, block key) (`:861–948`); the module hash is sha256 of JSON (`:971`); the private fold table is FOUNDATIONS' open A2 row | none | **KEYED** (d) | address emitted functions by structural identity with integer constants turned into parameters (positional tokens with int holes); a cross-ROM block cache keyed by it | one cached ROM (311 entries): 32 blocks, all distinct even with constants abstracted; 279 single-instruction functions, 249 identical up to the PC constant; 33 content vectors | that ROM is mostly NOP padding, so atypical; parameters stop the C compiler folding constants; the module hash must still cover every body |
| `machine/absint.py` | abstract run over constants and unknowns for far calls and jump tables | none | **NO** (iv) | its lattice is constants and its outputs are addresses | — | — |
| `machine/native.py`, `gb.py`, `nds.py`, `shell.py`, `asm`, `build`, `diff`, `survey`, `testroms`, `cli` (`emu`, `machine`) | runtime engines (shared-library cache by sha256 of source, `native.py:150`), host plumbing, the effect shell (CM21), assembler, module build (input-hash cache, `build.py:64`), differential runs, surveys | none | **NO** (ii) | emitted bytes are the right key | — | — |
| `machine/bench.py` | per-card conformance (6.7 s in verify) | none | **NO** | per-card data (cycles, flags) differ even between identical terms; dedup would save at most 17 of 512 runs | — | — |
| `machine/isa.py` (`isa`) | compiles semantics, `in_sync`, generates dispatch | none | **CONSUMER** | one handler per identity class (17 fewer); declare the ISA's effect atoms | — | — |
| `game/` (`game`) | the only terms are the `stdlib/combat.card` kernel functions (`combat.py:31`); moves are frame-data records whose "vector" is a direction 0..8; analysis is an exact simplex over ℚ; the world is Datalog facts | none | **NO** (iv) | no Gödel identity or content answers a game question; the kernel functions get content through the ordinary function path if ever wanted | — | — |
| `unreal/distill.py` | canonical forms over ℝ, content, tokens, gcd and lcm per use, the named → core carry map (`:97–316`) | **CORE, partly a copy of `godel.py`** | **CORE** (b, c) | call `godel.py` instead of copying it: `_disjoint` (`:309–316`) is `preserves_gcd` (`godel.py:418`); the inline gcd and lcm (`:270–271`) are `godel.gcd`/`lcm`; `tokens` (`:120–145`) is the **third** copy of the 3k + 1 scheme (with `godel._tokens :333` and `numbering.tokens :101`); `content` (`:97`) is a DAG-memoized `term_content` (move the memo into `godel`); `number` (`:151–161`) is dead code that computes the content integer CM45 forbids. Write its identity classes as `merge` events and its witnessed lifted atoms as `deprecate(atom, content)` events, tagged ≡_ℝ; today the carry image is computed on every scan and only counts are stored (`cards.py:236–241`) | one implementation; "redefine by cofactors" becomes real, with Unreal as its first user | ≡_ℝ is not f32 or f64 (F5, F6): gate each event by witness tier and tag the relation; events are permanent |
| `unreal/cards.py` | writes the cards; `G.sync` of 3,310 named atoms (`:173–197`, `:256–283`) | the ledger's largest writer | **CORE** | positional codes from per-set dense ranks (above), so that one domain's atoms never inflate every core term's code; 3,310 atoms pushed TRUNCDIV and REM to 3410 and 3411 | core terms keep usable positional numbers; decode drops from 100 s | amends GM-4/CM43 (the user's decision); old codes still decode by basis version |
| `unreal/metrics.py`, `unreal/cli.py` (`unreal`) | prime-vs-ledger check, re-derivation; `unreal gcd` uses `godel.gcd`/`lcm`/`divides` (`cli.py:240–260`) | reads | **CONSUMER** | — | — | — |
| `unreal/lift`, `clangast`, `scan`, `units`, `engine`, `atoms`, `witness` | the clang frontend, the scan, cached units (sha256, `units.py:35`), op data, the f32 witness (F6, known) | none | **NO** (ii) | — | — | — |
| `anyps5/` (`anyps5`) | observations of a C++ project: 7,257 exports, 2,398 debt entries, 354 libraries, 1,166 RDNA instructions; Datalog causes; badge parity | none | **NO** (no terms) | the text `body_sha` (`scan.py:395`) is the right dedupe. Future CORE: an RDNA Gödel set, once shader semantics are lifted | — | — |
| `arcade/` (`arcade`) | builds, the launcher, servers, chunked downloads (sha256, `client.py:57`, `:138–162`), builds by sha256 of card JSON (`cli.py:109`, `gen.py:76`, `system.py:273`) | none | **NO** (ii) | bytes and card JSON are the right objects; Gödel identity is about terms | — | — |
| `formal/GodelCore`, `Godel1931` | the Lean proofs T1 to T6 | **CORE** (the ground truth) | **CORE** | missing: `deprecate`/`resolve` as a corollary of T2 (carry with identity images elsewhere); injectivity of the positional code, which `numbering.check_set` only samples; and a Python consumer for T5 and T6 | T5 as an index query, T6 as a rule's known cost delta | the formal section is skipped on hosts without a lake toolchain |

**Measured** (scripts `m1.py` to `m12.py`, through the Python API in fresh processes; the full `numbering.check`,
the structural digit counts and the prototype's identical results were re-run for this document):

* *Store load:* `default_store().ALL` loads 24,246 cards in 1.39 s; the godel registry alone (3,411 atoms) 0.06 s;
  the definition registry 0.02 s.
* *`godel.check` under cProfile:* 102.05 s, of which `numbering.check` 101.6 s and `Numbering._codes` 100.4 s over
  8,640 decodes; per set B0 34.6 s, machines 22.5, computation 19.5, unreal 15.0, bits 7.4, analysis 3.9; ledger
  `problems` 0.30 s; `card_content` 0.003 s for 22 algorithms, 0.001 s for 43 functions, 0.000 s for 75 ops.
* *Quick verify* (seed 1): 224.6 s, peak 634 MB: godel 100.71 s, capabilities 91.25 (likely first-run cache
  building; the slowest single capability on a standalone rerun was 7.35 s, `improve`), machine 6.70, lang 6.63,
  forms 5.10, theorems 3.80, anyps5 3.04, kernel 2.88, the rest under 1.3 s each. The sections that failed were
  unrelated to Gödel: projects (a stale project card), forms (1), vectors (1, `re_operation/detect_format`).
* *Gödel data in the store:* only the 577 definitions store a godel record and identity; theorem content is readable
  for 1,628 of 1,650 cards but has only 239 distinct vectors; `card_content` returns None for definitions; 0 ledger
  events, and `resolve` is called only inside `problems`.
* *Index prototype* (in-memory SQLite, 577 vectors): "ADD·MUL divides v" 4.2 ms by scan, 0.09 ms indexed, the same
  25 answers.
* *LR35902 terms:* 512 definitions, 495 identity hashes (11 hangs, 8 NOP-equivalents), 103 content vectors, 190
  families up to register renaming; the 167 ARM cards have 0 definitions.
* *arith:* 1,075 outputs, 588 distinct, 157 up to width-preserving renaming; 0.40 s per output.
* *One lifted ROM cache* (`state/emu/…/blocks-l5.json`, 311 entries): 32 blocks all distinct with constants
  abstracted; 279 single-instruction functions, 249 identical up to the PC constant; 33 content vectors.

**The three changes in this group, by value:**

1. **Make the Gödel check cheap**: valuation by squaring in `numbering._codes` and `godel.decode`, and the `godel`
   section cached under its input hash in verify and selfrun. Quick verify 224.6 s → about 128 s (−43%); the self
   cycle's quick verify about 132 s → about 32 s; a cache hit about 0 s. Then per-set dense ranks so the cause goes
   away.
2. **A store index keyed by relation-tagged identity, with posting lists over resolved content vectors.** The S2
   blocker of SCALING §5. It gives `list --divides`/`--similar`, identity dedupe in `learn` and `selfrun` with
   `merge` proposals, T5 transport, and an honest coverage denominator; 47× faster today and the only workable
   option at S2 and S3.
3. **Key machine work by identity**: `arith` memoized per α-canonical term (1,075 → 157 terms, about 430 s → 63 s),
   `symbolic` families (512 → 190), an ISA-generic machines set so ARM gets definitions, and the LR35902 → ARM carry
   reported with its gap.

Next after these: write Unreal's identities and witnessed lifted atoms as `merge` and `deprecate` events, gated by
tier and tagged ≡_ℝ, and delete its copies of `godel.py`. That is what makes "redefine by cofactors" work in
practice; today there are 0 events and `resolve` has no production caller.

## 5. The target: the Gödel card model

The verdicts of §4 converge on one structure. Every module is either part of it, keyed by it, or outside it for a
reason from §2.

1. **One lattice type.** A sparse exponent vector with +, gcd, lcm, divides and `carry`, and `resolve` as `carry`
   with the mapping {atom: product}. It is used by godel content, by the `realnorm` and `tiers` monomials, by
   `funcalg`'s annihilator factors and by `unreal/distill`, which today are four copies. The carriers stay apart
   (content is not ≈_E-invariant; polynomial normal forms are ≡_ℝ-invariant), and every hash says which relation it
   is canonical under (A4, F5).
2. **One identity, minted once.** The sha256 of the α-renamed canonical term (`numbering.canonical`), tagged with its
   relation; for a function, a Merkle hash over its callees' identities (an SCC gets the SCC's hash). It is minted by
   one builder (`sources` for definitions, `lift_project.identity` for lifted functions, the same key for
   theorems, rules, instruction terms and behaviours) and stored on every card that has a term. It is the key of
   the store index; of every cache (`translate`, `matrix`, `lean`, `tiers`, `theorems`, `arith`, `improve`,
   `egraph.canonical`); of every dedup (E, theorems, law candidates, `learn` proposals, `sweep`); of equality by
   lookup (`matrix.cross_source`); and of every work unit (`selfrun`). Equal keys mean equal only as far as E is
   sound; E is sorted since #19 (F1), and the sample witness stays beside the hash.
3. **Every map between signatures is a carry map with a gap.** A codegen language is {atom@rank: template}, verified
   cell by cell by `conformance`; Lean's two carries (`emit/lean`, `lean_import`) are one, with `LEAN_*` as named
   atoms; an ISA pair (LR35902 → ARM) is a carry with its gap; Unreal's named → core map is a carry whose witnessed
   images become ledger events; a definitional redefinition is a `deprecate`. Coverage is a set intersection on γ,
   computed before anything runs, and gcd preservation is reported from the supports (T2).
4. **Summaries compose.** γ is computed per unit on its canonical term and added up the hierarchy (function → module
   → package → distribution) as SCALING §3.1 asks, stored resolved through the ledger's events, and indexed by
   posting lists. "Which cards inherit P" is a `divides` scan (T5), and a rule's effect on a linear cost is a
   constant known before it fires (T6).
5. **The ledger is the one place a concept is renamed or redefined.** `merge` and `deprecate` events, produced by
   definitional laws, by witnessed carry images and by `learn` finding two names with one identity, each gated by
   its tier and tagged with its relation; `new op` writes a proposal, and one writer mints. Positional codes come
   from per-set dense ranks, and decoding is by valuation, so a code is cheap to build and to check at any ledger
   size.
6. **What stays outside, and why.** M (`ir.op_table`) computes meaning (i); frontends, codegen's printing, runners,
   the store's files, the effect shell and the arcade move bytes (ii); `values`, `absint`, the game and the anyps5
   observations are about values and records, not terms (iv); termination, speed and measured costs are results the
   model keys and never derives (v). Each of these produces or consumes terms (A7) and is addressed by the identity
   of what it produced, and nothing more.

**What this buys at scale.** The first S2 blocker (SCALING §5, `kernel/store`) is the index of item 1 and 2. Dedup
across a distribution is a lookup (484 → 81 on the arena, item 2), and SCALING §4.8's semantic-hash library is item
2 with the e-graph canon on top. Verification of a translation is one run per *atom* per language times a support
check per function (item 3), not one run per function per language. The self cycle becomes work units keyed by
identity with cached sections (item 2 and §4.3), so an unchanged corpus costs nothing.

**What this buys beyond code.** A domain enters the model as a Gödel set: atoms with arities (W-5's six conditions
make the numbering admissible), a carry map to and from B0 with its gap, and the name of the relation its equality
is decided under. Code is one such set (B0), machine instructions another (machines, soon ISA-generic), a game
engine's real-valued math another (unreal, ≡_ℝ), behaviours another (`funcalg`'s annihilator factors, ≡_beh), and
physics the planned one (units as primes, GOALS.md). The lattice, the identity, carry and transport are the same for
all of them, which is the sense in which the model is universal: nothing in items 1 to 5 mentions code.

## 6. Order of work, and what goes to the restructure thread

In dependency order. Each step keeps every existing test green and lands as its own PR with its measurement.

| step | change | from | depends on | measured gain |
|---|---|---|---|---|
| 0 | F1 sorted e-graph, F2 one model, F4 canonical content | the foundations thread (landed: #19, #21, #22) | — | identity means equality; content means structure |
| 1 | valuation by squaring in `numbering._codes` and `godel.decode`; the `godel` section cached by input hash in verify and selfrun | §4.3 (1) | nothing | −97 s per quick verify, −100 s per self cycle; no law change |
| 2 | one identity key: `semantic_hash` α-renamed and relation-tagged; `lift_project.identity` (Merkle); one function-card builder for `translate`, `lang/run`, `math_cli`; E, theorems, law candidates and `learn` proposals deduped by it; `egraph.canonical`, `improve.cheapest_rewrite`, `tiers` and `theorems` memoized by it | §4.1 (1), §4.2 (1, 2) | 0 (for equality claims; the dedup and memo are safe before it) | saturation −32%, 47% fewer canonicalizations, 484 → 81 functions, 162 Lean proofs not repeated |
| 3 | codegen as a carry map with a gap; `conformance` cells as its verified image; `emit/lean.py`'s table removed; `matrix.translation_gaps` and `lean_import`'s gap from it; `analyse` laws with per-atom supports | §4.1 (2, 3) | 2 for the identity-keyed caches, otherwise nothing | 137 of 153 Lean gaps with no emission; 25% of functions cleared of instrumented runs |
| 4 | one lattice type; `resolve` as `carry`; `realnorm`, `tiers`, `funcalg` on it; `funcalg` identity = sha256 of its code; definitional redefinitions → `deprecate`; `redefs` decides by `realnorm.canonical` first; the `godel` command gains `merge`, `deprecate`, `resolve`, `carry`, `decode`; `unreal/distill` calls `godel.py` | §4.2 (3), §4.3 (next) | 2 (identity), 0 (F4) | 61 of 111 redefinitions to proof tier; the 672-digit number gone; cofactors usable |
| 5 | the store index: identity with relation, basis version, postings over resolved vectors; `list --identity/--divides/--similar`; the coverage denominator; a T5 transport query | §4.3 (2) | 2, 4 | 47× on divides today; the S2 blocker |
| 6 | machine: `arith` memo per α-canonical term; `symbolic` families and ISA-generic effects; ARM definitions; the LR35902 → ARM carry with its gap; `lift` cross-ROM cache by structural identity | §4.3 (3) | 2, 3 | 430 s → 63 s on arith; 167 ARM cards get definitions |
| 7 | the self-run work queue with units keyed by identity; `learn` dedup by identity with `merge` proposals; `arena` identity recall | §4.3 | 2, 5 | the cycle does only changed work |
| 8 | Unreal's identities and lifted atoms as `merge`/`deprecate` events, tier-gated and ≡_ℝ-tagged; per-set dense ranks for positional codes | §4.3 | 4, and the user's decisions below | the first real use of redefinition by cofactors |

**Progress.** Step 1 is done (2026-11-05): the valuation by squaring landed with #28, and the `godel` section is
cached in verify (`verify.godel_section`) and so in the self-run's verify step, keyed by `godel.check_key` (the
card hashes of the registries `godel.check` reads, the committed and current ledger, and the source of the engines
it runs). On a shared 4-core host the section took 14.65 s computed and 0.03 s from the cache (the valuation had
already taken it from 100.7 s to 15 to 18 s); the cached result equals a fresh one, and any changed input recomputes
it (`tests/test_godel.py`, `SectionCache`).

**Decisions that are the user's, not the threads'** (each is a law or a permanent ledger change): adopting GM-2 as
written (identity is the hash; already the practice, §3); GM-4 as a law; positional codes by per-set dense ranks
(amends CM43's text on numbering); minting the `LEAN_*` and ARM atoms; adopting Unreal's events into the ledger.

**For the restructure thread.** Steps 1 to 7 are the sequence, and the verdict tables in §4 are the module-level
spec. Two conflicts to avoid: the foundations thread owned how rules are *applied* (`egraph`, `search`) and how
witnesses are *evaluated* (`exprs`, `witness`) until F1, F2 and F4 landed (#19, #21, #22), so the identity work
of step 2 sits on top of the sorted e-graph rather than inside it; and only the ledger writer mints atoms or events
(GODEL_METHOD rule 1), so steps 3, 6 and 8 produce *proposal* cards. Measured as not worth doing, so not in the sequence: an
LHS-content prefilter for rules (≤ 2%), a content lower bound on cost (prunes 0 of 132), hash-consing e-nodes by
Gödel number, Gödel keys for logic facts, and dedup of `machine/bench` runs (at most 17 of 512).

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
