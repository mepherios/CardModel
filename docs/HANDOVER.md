# HANDOVER (2026-11-05, refreshed 06:45 UTC): state of the work, for the next model

This is a snapshot handover for a model (or person) picking up CardModel cold. It says where main is, what is in
flight on which branch, what was left unfinished, and what only the owner can decide. The long-form operating manual
(how to run, extend and troubleshoot the model) is the root [HANDOVER.md](../HANDOVER.md); read that second. Verify
everything here against `git log origin/main`, the open PRs and the branches before acting: this file is a snapshot.

---

## 0. Read this first: CI is off, and merges go on local tests

**GitHub Actions cannot run on this repository.** Every run since about 02:00 UTC on 2026-11-05 fails in seconds
without starting a job, main included. GitHub's message is "recent account payments have failed or your spending
limit needs to be increased". The daily self-optimize workflow (`.github/workflows/self-optimize.yml`, 03:17 UTC)
has **never completed a run** for the same reason.

**The owner's rule while this lasts:** skip CI and merge on a full local test run. In practice, on the PR branch
merged with current main:

```sh
pip install -e .
python -B -m unittest             # the quick suite, what CI's "quick" jobs run
python -B tools/require_toolchains.py && cardmodel verify   # the full run, needs the target toolchains
```

Say in the merge commit or PR that it was merged on local tests (as #28's merge does: "merged on local tests, CI
unavailable"). PR #42 (`claude/ci-fewer-runs`) cuts CI's minute use (push runs only on main, one run per PR update,
the full every-language job only when a PR is ready for review, self-optimize weekly); merge it before CI comes back.

What CI is when it runs: `.github/workflows/ci.yml` (PR #4) runs a quick job on Python 3.9 and 3.13 and an "Every
language" job that installs every target toolchain (13 languages) and runs verify, translate and the conformance
matrix. There is no auto-merge workflow in the repo.

---

## 1. What CardModel is (in one paragraph)

Everything the model knows is a **card** under `cards/` (about 24,200 cards in 81 registries); everything it can do
is a `cardmodel` command. Programs are lifted from source languages into one typed IR, rewritten to canonical terms,
identified by content, and generated back into every target language, where each translation is **witnessed** by
running it against the source. The mathematics underneath is the **Gödel model**: a definition's content is its
canonical term, numbered as a vector over primes, so that "which known concepts does this contain, and what is left
over" becomes exact arithmetic (factor, gcd, cofactor). The owner's goal: a model that runs and optimizes itself,
runs natively on any platform, and carries every integration to any language, model or target through mathematics,
without hand work.

## 2. Documents, in reading order

| doc | what it gives you |
|---|---|
| [TARGETS.md](TARGETS.md) | where the model can go, the measured state of every layer, ordered steps 0 to 11 with exit measurements, and **§7: the owner's open decisions** |
| [FOUNDATIONS.md](FOUNDATIONS.md) | the rules everything is built on (F*, D*, A*): one model, op cards, canonical content, identities naming their equivalence |
| [GODEL_TARGET.md](GODEL_TARGET.md) | the target design for the Gödel core, its order of work (§6) and progress table (§8). Merged with #28 |
| [GODEL.md](GODEL.md) | walkthrough of the Gödel model's abilities, each graded proven / measured / conjecture |
| [GODEL_AUDIT.md](GODEL_AUDIT.md) | which subsystems should build on the Gödel model and which must not; §6 is the order of call-site work |
| [ENVIRONMENTS.md](ENVIRONMENTS.md) | the running machine (CPU, GPU, memory, numeric model, driver, API) as mathematics; gaps E1 to E24 |
| [SCALING.md](SCALING.md) | the scaling plan, S-A to S-D |
| [ROADMAP.md](ROADMAP.md) | the master plan and capability matrix |
| [../HANDOVER.md](../HANDOVER.md) | operating manual: quickstart, recipes, invariants, troubleshooting (written 2026-10-22, partly dated) |

## 3. Measured numbers worth carrying

* **96.1 % of the owner's own functions do not lift** (254 of 6,576 lift; TRANSLATE_REAL_PROGRAMS.md). The blockers
  are types: 3,863 non-numeric annotations (`str`, `list[float]`, dataclasses, `None`), 954 non-numeric defaults or
  `*args`, tuple targets, subscripts, list literals, `raise`, truthiness. Python 3.13 stdlib: 0.6 % lift.
* **Canonical definitions: 26 %** of 574 definitions have a canonical form (G_U7 = 0.258 against a 0.9 goal).
* **484 lifted arena functions collapse to 81** under identity of canonical content.
* **Gödel numbering check: 85 s to 3.5 s** by decoding positional codes with p-adic valuation (#28, merged); the
  audit had measured the `godel` verify section at 100.7 s of a 224.6 s quick verify.
* **Scale (PR #45, first run, seed 0, Xeon, Python 3.13):** 518 / 572 / 931 µs per function at 10³ / 10⁴ / 10⁵
  functions, **slope 1.80** (goal G_A11 ≤ 2), about **20 KB per function**, **peak 1,988 MB at 10⁵**, lift rate 0.86
  on the synthetic projects.
* Store: loading every card costs 3.5 s and 92 MiB per command; the lazy indexed store (#18, merged) is the fix, but
  most global passes still load everything.
* Proofs: the full verify proves 47 of 114 rewrite rules in Lean; the rest are witnessed only.

## 4. What landed on 2026-11-04 and 11-05

On main (`a336f93`): CI workflows (#4), lazy indexed store (#18), GODEL.md (#20), FOUNDATIONS F2, F4, F5 and the
fixed-width / binary32 subsorts `u8..i32 <= int`, `f32 <= float` (#21 to #24, #29, #30), GODEL_AUDIT.md (#25),
ENVIRONMENTS.md (#27), **the restructured Gödel core and GODEL_TARGET.md (#28)**, and **lists in math notation,
nested loops in constant stack, `tanh` in Lua closing the Lua GELU gap, Swift argument labels and exact integer POW
(#32)**.

## 5. Work streams and where each stands

"Open" PRs below were checked against GitHub at the time of writing. None has run under CI (§0).

### 5.1 Gödel model as the foundation (GODEL_TARGET.md §6)

* Done: step 1 (the design) and step 2 (the core: algebra, cost, Jaccard, `ContentIndex`, `match`, `factor`,
  `expand`, duplicates retired from `unreal/distill`, `funcalg`, `numbering`; identities tested on random terms).
* **Open: PR #46** (`claude/project-thread-jm4iji`, 1 commit on current main): step 3, `cardmodel godel factor |
  similar | cofactor | decode`. `factor` rewrites a term over the definitions it contains with the cofactor and
  the check γ(t) = γ(context) + Σ γ(instance); `similar` ranks by |gcd| / |lcm|; `decode N --vars a,b` returns a
  positional code's term.
* **Queued, no branch yet:** PR 3 physics as a Gödel set (base quantities as atoms with negative exponents, a
  dimension check of equations); PR 4 codegen as a carry map; PR 5 a rank-level carry map; PR 6 onwards, call sites
  in GODEL_AUDIT's ranked order, each with a "same answer with and without" test.
* Owns: `engines/godel.py`, `numbering`, `funcalg`, `codes`, `unreal/distill`.

### 5.2 Ground CardModel in core mathematics (foundations)

* Done: fixed-width and binary32 subsorts with op cards and laws (FOUNDATIONS D1).
* **Open: PR #31** (`claude/project-thread-8z7gnb`, merged with main at 06:02): instruction terms distilled under the
  register sorts, reproducible definition certificates, witnessing the stored canonical terms. Touches
  `machine/symbolic.py`, `engines/verify.py`, the LR35902 definition pack.
* **In progress, not pushed:** a machine-code lifter change that simplifies with the rule cards' unit and absorbing
  laws instead of hand-coded cases.
* **Left:** the rest of the IR type series (fixed-width ints and f32 as real `engines/ir.py` TYPES with codegen
  templates and conformance cells in every language), then `str`, tuple, Option, records, `raise`, truthiness. This
  stream owns `engines/ir.py` TYPES; nothing else should add IR types. It is the main lever on the 96.1 % above.

### 5.3 Independent roadmap prerequisites

1. **Environment card and per-resource budgets: open, PR #44** (`claude/project-thread-41jb89`). `cardmodel env`
   writes the generator's own card (`env_<fingerprint>`): OS, ISA and extensions, cores and SMT, RAM, declared caches,
   plus a C pointer chase and streaming copy for measured cache plateaus and bandwidth; each capability carries its
   evidence tier (D17). Metric cards and verify reports name the card; `resources.budgets()` reads CPU workers,
   compile slots, memory caps from it, or the OS when no card exists.
2. **Scale benchmark: open, PR #45** (`claude/project-thread-c60pvh`). `cardmodel scale bench` builds seeded
   synthetic Python packages, times lift and the cheap per-function stages in a child process per size, records
   `metric/scale__n<N>`, and adds goals G_A11 (scale slope ≤ 2) and G_A12 (memory bound). Numbers in §3.
3. **Stop failed callees from failing callers: in progress, not pushed.** A function that does not lift becomes an
   opaque boundary card with its signature and cause; callers lift with the edge recorded as a gap
   (`frontend_python.close_calls`, `lift_project.py`). Measure the lift rate before and after with PR #45's bench and
   the TRANSLATE_REAL_PROGRAMS sweep. Highest-urgency scaling item: it hides most of the lift rate.

### 5.4 Every capability in the main pipeline (tiers and coverage check)

* **In progress, not pushed:** a pipeline registry where every capability declares its tier, and a coverage check
  that fails when a capability never runs in the main pipeline.

### 5.5 Transformer math in math notation

* Done in #32: transformer functions listed as equations in math notation, the Lua GELU `tanh` gap closed.
* Branch `claude/ci-exact-int-pow` (no PR) is superseded by #32 and can be deleted.

### 5.6 GPU, driver and environment modelling

* Done: ENVIRONMENTS.md (gaps E1 to E24). V-A is PR #44.
* Next per ENVIRONMENTS §6, once #44 lands: V-B numeric-model laws (fp_contract, denormal_flush, reduction_order),
  then V-D a SPIR-V card and lavapipe in CI (also waits on the f32 series).

### 5.7 Older open PRs (drafts, from 11-05 00:00 to 03:00 UTC, each merged cleanly into main at 05:50)

| PR | branch | what |
|---|---|---|
| #42 | ci-fewer-runs | CI minute budget (§0); merge first |
| #41 | stdin-harness | test programs read inputs from stdin, one build per language serves every seed |
| #40 | hopeful-tesla-yvaan1 | `function_card` records the real source language; stacked on #39 |
| #39 | c-frontend | C frontend: C integer semantics, arrays as lists, learning from C trees |
| #38 | ci-csharp-harness | witness C#, Kotlin and Julia with their own toolchains |
| #36 | reproducible-packs | definition pack records every fired equality, sorted (overlaps a commit on #31) |
| #35 | self-report-next | exact forms for four inconclusive cards (G_C4 107 to 111) |
| #34 | gb-mbc | MBC7, HuC3 and the Game Boy camera witnessed across engines |
| #33 | anyps5-blockers | libSceRtc tick arithmetic bound to 12 exports |

None of these has a thread working on it. Each needs: merge main, full local test run (§0), merge.

## 6. Decisions only the owner can make (TARGETS.md §7)

1. **Actions billing**: fix the payment or raise the spending limit so CI and self-optimize can run, then merge #42.
2. **Second target** after A: the native arcade (D) or binaries (B). Steps are shared up to 6.
3. **iPad as the Phase I test device.** It forbids generating code on the device, which is what makes I4 and I5
   necessary.
4. **Gödel decisions**: the Mathlib and Foundation downloads (W-2); proposed laws **GM-1 to GM-9**; GM-2's amendment
   of CM43 (identity is the hash of the canonical term, the positional code a witness).
5. **GODEL_AUDIT decisions**: GM-4 as a law, positional codes by per-set dense ranks (amends CM43's text), minting
   the `LEAN_*` and ARM atoms, adopting Unreal's identities as ledger events.
6. **ENVIRONMENTS decisions**: adopt D15 to D18 and A8 into FOUNDATIONS.md as written; whether the owner's Mac is the
   first device for the transfer judgment.

## 7. Suggested order for the next model

1. Land what is finished, each on a full local test run against current main: #46, #44, #45, #31, then #42, #38,
   #41, #39, #40, #36, #35, #34, #33. Merge main into the branch between merges.
2. Finish the in-progress items that have no branch yet: failed-callee boundary cards (§5.3 item 3), the pipeline
   coverage registry (§5.4), the rule-card lifter change (§5.2).
3. Continue the owned series from their own branches: Gödel PRs 3 to 6 (§5.1), the IR type series (§5.2), then V-B.
4. Keep the rules: every claim carries its tier; content is stored as sparse vectors, never as integers, and no index
   is reused (CM45); the formal core builds with no `sorry`; a goal never gets easier silently; each branch is listed
   on the `cardmodel` project card (CM41).
