# NEXT_BUILD: what to build next, and the options

An ordered plan for the next sessions (2026-11-05). It does not replace TARGETS.md §3 (the dependency order, steps 0
to 11); it picks the next moves inside it, gives two or three options per track, and says which measurement each
option moves. Every number below is quoted from a measurement or a document named beside it; nothing here is a new
measurement. Lines marked **Recommendation** are this document's judgment, not a decision; decisions stay the user's
(TARGETS.md §7).

## 1. Where we are (measured)

On main `a99bc77` (after #51), Linux, 4 cores, `CARDMODEL_SELF=0`, from the session assessment of 2026-11-05 and
TARGETS.md §6:

| measurement | value | source |
|---|---|---|
| `verify --quick` | 17 of 17 sections pass in 146 s; 24,285 cards, 0 errors | assessment (a) |
| real code that lifts | 254 of 6,576 of the user's functions (96.1 % do not lift); 1 of 149 functions in six stdlib modules (0.67 %) | TARGETS.md §6; assessment (a) |
| canonical definitions (G_U7) | 0.2462 of 577 definitions, target 0.9 | assessment (a) |
| ARMv5TE symbolic terms | 0 of 167 on main; 92/167 in #67, 98/167 with #79, 156/167 with #78 (PR titles, not re-measured here) | assessment (a); open PRs |
| goals | 54 goals: 32 met, 6 unmet (G_C4, G_M6, G_P4, G_U3, G_U7, G_U9), 16 not run yet | assessment (a), (c) |

What works end to end today: small numeric Python, C and Go functions and Unicode math are lifted, translated to up to
10 languages and witnessed by running (6 of 6 eligible functions agreed in all 10). What does not: strings, tuples,
records, classes and closures are not in the IR; `emit` to one file compiles only for C among those tried; `improve`
crashes on list parameters; ARM has no symbolic terms on main; Lean is absent in the container, so proof counts are
carried, not re-checked.

## 2. Land first: the open PRs, grouped

Open PRs as listed by the GitHub API on 2026-11-05. Within a group, land in the order given; a PR named in
"needs" must land (or be rebased onto) first.

| group | PRs, in order | needs |
|---|---|---|
| **CI and harness** | #42 CI budget runner; #41 stdin harnesses | #42 first, so the rest run under it (TARGETS.md §7 asks for CI first) |
| **bug fixes from the assessment** | #63 multi-function emit headers, `improve` on list params, `godel decode` usage; #64 distill parse errors and sorts | none |
| **fixed-width sorts (FOUNDATIONS §7 items 1 to 4)** | #60 lift sorts; #61 IR fixed-width ints and f32; #62 frontends to u8..i32/f32 | #61 before #62 |
| **real-code lift** | #75 element type of bare lists; #69 strings in the IR; #52 opaque callees | #52 needs a port onto #51 (its title says so); #69 proposes ledger atoms not minted (a user decision) |
| **frontends and translate** | #39 C integer semantics; #40 function_card source language; #38 C#/Kotlin/Julia witnesses; #47 signed zero; #53 codegen as a carry map; #71 math-notation signature hint | #53 is GODEL_AUDIT step 3 and wants step 2's identity key |
| **Gödel** | #54 section cached by input hash (step 1); #58 search via godel.match; #68 codes via the core; #77 `number(tokens)`; #66 `FILE.py:FUNC` for factor/similar/cofactor; #70 purity follow-ups (proposal) | #54 first; #68 and #77 touch the same numbering code, land together |
| **machines** | #67 ARM terms 0 to 92; #79 constant-bound loops, banked writes (to 98); #78 bus effects and memory model (to 156); #34 MBC7/HuC3/camera; #33 anyps5 tick arithmetic | #67 then #79 then #78 (stacked by their numbers) |
| **pipeline** | #50 the pipeline as a registry; #55 every capability in the pipeline | #50 before #55 |
| **definitions** | #36 reproducible definition pack; #35 redefinitions 107 to 111 (G_C4) | #36 before #35, since #35 regenerates the pack |
| **environments** | #57 numeric-model laws (V-B) | none |
| **docs** | #43 HANDOVER; #65 handover of open PRs; #72 TARGETS measured state; #73 open Gödel proposals; #74 ENVIRONMENTS status; #76 pending owner decisions; #59 showcase | land after the code they describe, or rebase their numbers |

**Recommendation:** the CI pair and the assessment bug fixes first (small, they unblock trustworthy merges), then
the ARM stack and the fixed-width series (each is a straight line), then the rest. Without CI minutes, each merge
rests on a full local `python -B -m unittest` (FOUNDATIONS §7, about 40 minutes), so batching merges matters.

## 3. Next build tracks, with options

Each option: what, why, cost (relative, not measured), what it unlocks, which measurement moves.

### 3.1 Real-code lift (the 96 % blocker; TARGETS step 2, MATH_CORE phase 2)

The first blockers in the user's code are non-numeric annotations (3,863), non-numeric defaults or `*args` (954),
string or `None` constants (343), tuple targets, subscripts and list literals, `raise` (217) and truthiness
(146 + 65); in the stdlib, 23,968 methods stop at `self.x` (TARGETS.md §6).

* **A. Tuples and Option/None first.** Add `tuple` and `Option` to `engines/ir.py` with op cards, templates in every
  codegen language and conformance cells. Why: tuple targets and `None` constants are cheap, frequent and need no
  heap model. Cost: medium (every language card gets templates). Unlocks: multiple return values, sentinel returns.
  Moves: lift rate on the user's code (from 3.9 %).
* **B. Truthiness and `raise` as an effect.** Truthiness as `!= 0` / non-empty on the existing types; `raise` as an
  effect with its gap card where a target has no exceptions. Why: TARGETS.md calls truthiness cheap; `raise` stops
  217 functions. Cost: low for truthiness, medium for `raise`. Moves: lift rate; stdlib top-level fraction.
* **C. Records with methods over a receiver, plus opaque callees.** `self.x` as a record field, methods as functions
  of the receiver; land #52 (opaque callees as boundary cards with a host witness) so calls into unlifted code no
  longer stop the caller. Why: the largest single stdlib blocker. Cost: high (records touch every target and the
  store). Unlocks: methods, classes, the stdlib sweep of SCALING S-A. Moves: stdlib with methods (296 of 49,743).

**Recommendation:** B (truthiness part) and A in that order, then #69 strings, then C. C is the biggest gain but
the most expensive; #52 can land on its own earlier.

### 3.2 Canonical definitions (G_U7 0.2462 → 0.9; TARGETS step 1)

TARGETS.md §6 names the lever: loop canonicalization, not hashing; 11 of 577 definitions have a closed term
(GODEL_TARGET §9).

* **A. Loop distillation to closed forms.** Recognize accumulation loops (sums, products, linear recurrences) and
  distill them to the closed or recurrence form `improve` already finds (×500 to ×770 on triangle and slow_sum).
  Why: most definitions are loops. Cost: medium. Unlocks: `godel factor` over more definitions; more cofactors.
  Moves: G_U7; closed-term count.
* **B. Canonical recurrence form without a closed term.** Make a normalized recurrence (initial values, step term in
  canonical form) count as canonical when no closed term exists. Why: not every loop has a closed form. Cost: low to
  medium; needs a definition of "canonical" for recurrences (a law change, so the user's). Moves: G_U7 directly.
* **C. Structural similarity.** Make `godel similar` weigh structure, not only the content multiset (`x*x+1` ranks
  factorial at 1.000 today). Why: content-only similarity over-matches. Cost: low. Moves: no goal directly; quality of
  factor and dedup.

**Recommendation:** A, with B decided by the user alongside; C is a small follow-up.

### 3.3 Gödel steps 2 to 8 (GODEL_AUDIT §6; TARGETS step 9)

Step 1 is #54. The rest are in dependency order: 2 (one identity key) → 3 (codegen as a carry map, #53) → 4 (one
lattice type, `deprecate`) → 5 (store index) → 6 (machine) → 7 (work queue) → 8 (Unreal events).

* **A. Step 2, the identity key.** α-renamed, relation-tagged `semantic_hash`; one function-card builder; dedup and
  memo by it. Why: steps 3 to 7 depend on it. Cost: medium. Moves: saturation −32 %, 484 → 81 arena functions
  (GODEL_AUDIT's measured gains).
* **B. Step 4, one lattice type and `deprecate`.** Why: 61 of 111 redefinitions to proof tier; the ledger has 0 merge
  or deprecate events. Cost: medium; needs 2. Moves: G_C4 tier counts; first ledger events.
* **C. Step 5, the store index.** Why: 47× on divides; the S2 blocker for SCALING. Cost: medium-high; needs 2 and 4.

**Recommendation:** A now; it is a prerequisite for almost everything else in this track and for SCALING S-B.

### 3.4 Machines (ARM 92/167 → 167, then the other ISAs; TARGETS step 6)

* **A. Finish ARMv5TE.** Land #67 → #79 → #78, then close the last 11 of 167 named by #78's gap list. Cost: low after
  the stack. Moves: G_M6 (511 of 679 on main).
* **B. GODEL_AUDIT step 6 for machines.** `arith` memo per α-canonical term, ISA-generic effects, ARM definitions.
  Why: 430 s → 63 s on arith; 167 ARM cards get definitions. Needs Gödel step 2.
* **C. DS (two ARM cores).** The DS reuses ARMv5TE (ARM9) and adds ARMv4T (ARM7). Why: the arcade's next platform;
  ARM terms carry over. Cost: high (new ISA card set, a second core, the DS memory map). Unlocks: TARGETS §4.2 D.

**Recommendation:** A, then B; C waits for the user's choice of second target (TARGETS.md §7: arcade D or binaries B).

### 3.5 Environments V-D (SPIR-V; ENVIRONMENTS §6 step 4)

* **A. SPIR-V language card witnessed by lavapipe in CI.** Why: GPU conformance cells with no hardware. Cost:
  medium; needs CI back. Unlocks: V-E kernels.
* **B. T_dev op cards and the Vulkan/Metal API cards first, unwitnessed.** Why: the theory before the runner. Cost:
  low-medium. Risk: cards with no witness sit at a low tier.
* **C. Defer V-D until V-B (#57) lands and fixed-width types (#61) are in**, since V-E kernels are over BV(32) (the
  † steps in ENVIRONMENTS §6).

**Recommendation:** C, then A. V-D is not on the path to the 96 % blocker.

### 3.6 Autonomy (self-run, CI back; TARGETS steps 0 and 8)

* **A. CI back.** Land #42 (one run per PR, full job when ready, weekly self cycle). Why: every merge today rests on a
  40-minute local suite. Cost: low; Actions minutes are a budget question for the user.
* **B. One witnessed `self run`.** `self report` says "no cycle has run yet"; run one cycle and record its report.
  Why: 16 goals are "not run yet" because they need a full verify or self run. Cost: the heavy lock and wall time.
  Moves: the 16 unrun goals get values.
* **C. The work queue (SCALING S-C, Gödel step 7).** Work cards, leases, the cycle doing only changed work. Needs
  Gödel steps 2 and 5. Cost: high.

**Recommendation:** A and B now; C after Gödel step 5.

## 4. Recommended order, with reasons

1. **Land the CI pair and the bug fixes** (#42, #41, #63, #64). Reason: cheap, and every later merge is safer.
2. **Run one full verify and one `self run`** on the result. Reason: 16 goals have no value; the plan should be
   re-ranked on measured numbers, not on PR titles.
3. **Land the straight-line stacks:** ARM (#67, #79, #78), fixed-width (#60, #61, #62), definitions (#36, #35),
   Gödel step 1 (#54). Reason: each is already built; together they move G_M6 and G_C4.
4. **Gödel step 2, the identity key.** Reason: the prerequisite for steps 3 to 7, the store index and the work queue.
5. **Real-code lift: truthiness, tuples, Option/None, then strings (#69), then records with #52.** Reason: the 96 %
   blocker, the user's stated goal; cheapest blockers first.
6. **Loop distillation for G_U7.** Reason: the largest unmet goal gap (0.2462 against 0.9); can run beside 5.
7. **Then** Gödel steps 3 to 5, ARM to 167 and its definitions, V-D, the work queue.

All of this is a recommendation. The user's decisions that change it: the second target (D or B), the ledger atoms
for #69 and ARM, GM-1 to GM-9, a canonical-recurrence definition, and the Actions budget.

## 5. Sources

TARGETS.md §3, §6, §7; FOUNDATIONS.md §7; GODEL_TARGET.md §6, §9; GODEL_AUDIT.md §6; SCALING.md §6; ENVIRONMENTS.md
§6; the functional assessment of main `a99bc77` run on 2026-11-05 (not in the repository); the open PR list from the
GitHub API on 2026-11-05.
