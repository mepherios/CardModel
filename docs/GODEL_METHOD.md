# The Gödel method research program

The program comes from the Claude Doc "The Gödel Method: Research and Development Handover" (2026-10-22). Its ids
(Def-, Rule-, Cap-, Ph-, GM- and W-) are cited by every result here. The user's words, relayed by the Ting session
and checked in its transcript: "Yes, send the Gödel method handover to the card-model session and have it start the
wave-1 workstreams (W-1, W-2, W-3, W-5, W-12, W-15) under its coordination rules."

The proposed laws GM-1 to GM-9 are proposals: adopting one needs the user's yes, GM-2 in particular because it amends
CM43. Wave 1 produces evidence, not law changes.

## Coordination rules (from the handover)

1. This session is the only writer of `cards/godel/_pack_ledger.jsonl`. Workstreams propose atoms as proposal cards
   with their evidence, and this session mints them.
2. One branch per workstream, `claude/godel-w<n>-<slug>`; it merges after `cardmodel verify` passes.
3. Results are cards (`cards/finding`), each citing the ids it tests or builds and stating its tier.
4. `~/Documents/Claude_Hub` and `~/Documents/Pheros_Studio` stay read-only; their Python runs only with `python3 -B`.
5. Each workstream keeps its project card current with every commit (CM41): `cards/project/godel_w*`.
6. Wave 2 (W-4, W-10, W-11, W-13, W-16) waits for wave 1; wave 3 (W-6 to W-9, W-14) waits for W-4's Gödel record.

## Wave 1

The workstreams run in this session one after another, each on its own branch (parallel sessions would compete for
memory on this machine, and a session started by another session's message cannot start sessions itself).

| W | question | branch | status |
|---|---|---|---|
| W-15 | which of the product's questions are decidable? | `claude/godel-w15-difficulty` | done |
| W-3 | which code should identify a card? | `claude/godel-w3-identity` | done |
| W-5 | what makes a numbering admissible in each domain? | `claude/godel-w5-numberings` | done |
| W-1 | can every 1931 definition run as a card? | `claude/godel-w1-definitions` | waiting |
| W-12 | can instruction terms become polynomial constraints over a prime field? | `claude/godel-w12-arithmetized` | waiting |
| W-2 | can the content algebra and carry-over be kernel-checked on Mathlib? | `claude/godel-w2-mathlib` | blocked: the Mathlib and Foundation downloads need the user's yes |

The parts of W-2 that need no download are already on main: `formal/GodelCore` proves Rule-19, Rule-20 and the
freeness behind GM-3 in plain Lean (T1 to T4 of the research handover).

## Results

Each workstream adds its section here when it merges.

### W-15: the difficulty census (Cap-18, Ph-15, GM-7)

Every method card now carries `rank`: the arithmetical rank of the question it decides, and of the general question
it serves (`cardmodel difficulty`, `engines/difficulty.py`). A rank is an upper bound read from the question's
logical form: an ∃ over a decidable relation is Σ1, a ∀ is Π1, ∀∃ is Π2 (tier proof for the bound; completeness for
the level is cited from the literature).

| method | decides (rank) | serves (rank) |
|---|---|---|
| lift_python, emit, learn, witness, fit_recurrence | a finite translation or finitely many checks (decidable) | equality with the meaning on every input (Π1) |
| sized_witness | equality inside a recognized class (decidable) | equality of two integer functions (Π1) |
| saturate | equality within a budget (decidable) | equality under the rules: the word problem (Σ1) |
| lean_kernel | whether a given proof checks (decidable) | provability (Σ1, Def-4) |
| symbolic_execution | terms of loop-free fixed-width code (decidable) | their equality with the semantics on every 8-bit input (decidable: a finite domain) |
| human_written | nothing by itself | its correctness (Π1) |

Of the 18 questions the product asks (`cards/question`), 7 are decidable and promised: a valid code, a well-formed
ledger, part-of and gcd, gcd preservation under a carry map, a proof checks, instruction terms on 8-bit inputs, and
forms in a recognized class. 11 are left open, each card stating what the product does instead:

* Σ1, confirmed by a witness and never refuted in general: provable, halts, equal under the rule cards.
* Π1, refuted by one counterexample and never confirmed by finitely many checks: two total programs equal, the
  model consistent (never certified from inside, Rule-12), a learned card right, a term's shortest description.
* Π2: a program total, the rewrite system terminating, the basis complete (Gödel's first theorem already says no
  for a consistent basis containing Q).
* Beyond the arithmetical hierarchy: whether an arithmetic sentence is true (Tarski, Rule-13).

GM-7 as a law (verify fails on a method or claim without its rank or tier) is the user's decision; the tiers half is
law CM46 already.

### W-3: identity and size (Def-9 to Def-16, Ph-2, Ph-3, GM-2, GM-8)

`cardmodel godel sizes` (`engines/codes.py`) measures six codes for every card with a term: 2308 terms
(40 definition, 504 instruction, 114 rule, 1650 theorem). Bits, from the run that wrote the finding cards:

| code | median | 95th percentile | largest |
|---|---|---|---|
| positional | 400 | 43702 | 51888784 |
| content | 8 | 101 | 898 |
| cantor | 2405 | 9006904 | 48655110121721 |
| szudzik (built ones) | 2770 | 185411 | 1418119 |
| base_k | 132 | 576 | 4836 |
| sha256 | 256 | 256 | 256 |

* **The size model.** Nothing has to be built to know a code's size: the positional and content codes follow
  their logarithmic formulas (Σ c_i·log2 p_i and Σ e·log2 p_k), within one bit of the built integer on every term
  small enough to build; the Cantor tree code follows a log2 recurrence up the tree, exact on every built code.
  The handover's example holds: 10 tokens over atoms near index 10^6 cost about 9.8·10^7 bits as a positional code
  and about 239 as a content code (finding `W3_size_model`).
* **Ph-2 measured.** The positional code is larger than the content code for every term in the store; the largest
  are the CALL instructions, whose 16-bit constants have token codes near 400,000 (Rule-23: constants are not
  atoms, so the content code does not see them).
* **Ph-3 measured.** Pairing tree codes double with every level: the largest Cantor code, of a depth-13 instruction term, has
  about 4.9e+13 bits. They are not identities.

**Decision record for GM-2 (and the bound GM-8 needs).** The identity of a card is the sha256 of its canonical term
(CM45 already stores it as `identity.hash`). Gödel's positional code stays a decodable witness, computed on demand
for terms of at most 4096 bits (86% of
today's terms), never stored, and never nested inside another code. Pairing codes are not used to identify
anything. Today the definitions store the positional number as a decimal string up to 200 digits (CM45); GM-8 would
drop that storage. Adopting GM-2 amends CM43, whose text calls the structural number the identity: that is the
user's decision (finding `W3_gm2_decision`).

### W-5: admissible numberings (GM-4, Rule-1 to Rule-6, Def-1, Def-4, Ph-6)

A numbering is admissible here when it meets six conditions, drawn from Def-1, the design rules and the work of
Feferman (1960, doi:10.4064/fm-49-1-35-92) and Grabmayr (2021, arXiv:1803.08392) on how Gödel's second theorem
depends on the numbering (`engines/numbering.py`):

| condition | statement | why it holds |
|---|---|---|
| injective (Rule-1) | distinct objects get distinct codes | unique factorization, and the tokens parse one way given the arities |
| effective (Rule-2) | encoding and decoding are computable, and decode(encode(x)) = x | both are total programs |
| decidable image (Rule-2) | whether a number codes an object is decidable | `is_code` divides out the consecutive primes, checks each token and parses: it stops on every input |
| codes start at 1 (Rule-3) | every token code is at least 1 | 3k + 1, 3·zig(c) + 2 and 3j + 3 |
| parts smaller (Rule-5) | a proper part has a smaller code, and its content divides the whole's | a part's tokens sit at later positions (larger primes, same exponents) beside other factors |
| natural provability (Rule-6) | provability is ∃ of the decidable proof relation, with no further clause | Feferman's deviant predicates add a clause (a consistency check below the proof) and can make a theory "prove its own consistency"; the natural one keeps Rule-12's meaning |

Every `godel_set` card now states its numbering (objects, code, content, identity, the conditions, provability as
∃ of Lean's kernel check) and its witness test (`tests/test_numbering.py`, one per set: B0, computation, machines).
All three pass on generated objects, corrupted codes and random integers.

Two numberings were not admissible as stored (finding `W5_arity_gaps`): the computation set's atoms are not IR
ops, so nothing stated their arities, and the machines set's effects had an optional guard. Codes over them could
not be parsed back. Each set card now states its `arities` (read from the op cards' Python forms; stated for
EC_ADD, EC_SCALAR_MUL and BIT_NOR), and an effect's guard slot holds `logic/true` when the effect always happens.
The `godel` verify section reports every set's numbering; GM-4 as a law (verify fails on a set without an
admissible numbering) is the user's decision.

