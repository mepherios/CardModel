# HANDOVER (2026-11-05, refreshed 07:20 UTC): state of the work, for the next model

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

On main (`2781387`, 07:20 UTC): CI workflows (#4), lazy indexed store (#18), GODEL.md (#20), FOUNDATIONS F2, F4, F5
and the subsorts `u8..i32 <= int`, `f32 <= float` (#21 to #24, #29, #30), GODEL_AUDIT.md (#25), ENVIRONMENTS.md
(#27), the restructured Gödel core and GODEL_TARGET.md (#28), lists in math notation and `tanh` in Lua (#32), the
`godel factor | similar | cofactor | decode` commands (#46), LR35902 instruction terms under the register sorts
(#31), the lifter simplifying only by rule-card laws (#49), the environment card and per-resource budgets (#44), the
scale benchmark (#45), opaque boundary cards for failed callees (#51), physics as a Gödel set (#48), and the
foundations stream's own handover (#56). Everything after #28 was merged on local tests (§0).

## 5. Work streams and where each stands

"Open" PRs below were checked against GitHub at 07:20 UTC. None has run under CI (§0).

### 5.1 Gödel model as the foundation (GODEL_TARGET.md §6 and §8)

* Done: the design, the core (#28), cofactor factoring and similarity as commands (#46), physics as a Gödel set
  (#48: SI base quantities as atoms, a dimension model of the signature in `engines/dimensions.py`, thirteen
  `physics_law` cards checked by the godel verify section). GODEL_TARGET.md §8 is the recipe any other non-code
  domain follows to join.
* **Open: PR #53** (`claude/project-thread-jm4iji`): codegen as a carry map; translate and matrix predict a
  language's gap from content.
* **Open: PR #54** (`claude/godel-section-cache`): the godel verify section cached by the hash of its inputs
  (GODEL_AUDIT §6 step 1).
* Left: a rank-level carry map, then call sites in GODEL_AUDIT's ranked order, each with a "same answer with and
  without" test. Owns `engines/godel.py`, `numbering`, `funcalg`, `codes`, `unreal/distill`.

### 5.2 Ground CardModel in core mathematics (foundations)

**This stream's own handover is [FOUNDATIONS.md §7](FOUNDATIONS.md#7-handover-state-of-this-stream-2026-11-05)**
(#56): what merged, and the remaining steps in order. Nothing of this stream is unmerged. In short:

1. register sorts for lifted machine code (`machine/lift.py`, `symbolic.register_sorts`);
2. fixed-width ints and f32 as `engines/ir.py` TYPES, emitted wrap-on-store (this stream owns IR types);
3. conformance cells for the new types in every language;
4. frontends lifting C, Rust, Go, Java and C# fixed-width types to these sorts;
5. then `str`, tuple, Option, records, `raise`, truthiness. This is the main lever on the 96.1 % in §3.

### 5.3 Independent roadmap prerequisites

1. Environment card and per-resource budgets: **merged (#44).** `cardmodel env` writes `env_<fingerprint>`;
   metric cards and verify reports name it; `resources.budgets()` reads from it.
2. Scale benchmark: **merged (#45).** `cardmodel scale bench`; goals G_A11 and G_A12. Numbers in §3.
3. Failed callees no longer fail callers: **merged (#51)**, opaque boundary cards. **Open follow-up: PR #52**
   (`claude/opaque-callees`, draft): host witness and Gödel identity for boundary cards; it needs porting onto #51.
   Still to do: measure the lift rate before and after with the bench and the TRANSLATE_REAL_PROGRAMS sweep.

### 5.4 Every capability in the main pipeline (tiers and coverage check, CM50)

* **Open: PR #50** (`claude/project-thread-vubpxu`): the pipeline as a registry, every applicable stage runs or says
  why.
* **Open: PR #55** (`claude/pipeline-coverage`): tiers, the coverage check and Gödel purity. #50 and #55 overlap, so
  check which supersedes the other before merging.

### 5.5 Transformer math in math notation

* Done in #32. Branch `claude/ci-exact-int-pow` (no PR) is superseded by #32 and can be deleted.

### 5.6 GPU, driver and environment modelling

* Done: ENVIRONMENTS.md (gaps E1 to E24) and V-A (#44).
* **Open: PR #57** (`claude/numeric-model`): V-B, numeric-model laws fp_contract, denormal_flush, reduction_order.
* Next: V-D, a SPIR-V card and lavapipe in CI (also waits on the f32 IR types, §5.2 step 2).

### 5.7 Older open PRs (drafts from 11-05 00:00 to 03:00 UTC; each merged cleanly into main at 05:50)

| PR | branch | what |
|---|---|---|
| #42 | ci-fewer-runs | CI minute budget (§0); merge first |
| #47 | go-negzero | signed zero in every target (Go `-0.0`, C, JS, ceil/floor/trunc, Ruby sqrt) |
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

1. Land what is finished, each on a full local test run against current main: #54, #53, #57, #50 or #55 (decide
   which supersedes), #52 after its port, then #42, #47, #38, #41, #39, #40, #36, #35, #34, #33. Merge main into
   the branch between merges.
2. Foundations: FOUNDATIONS.md §7 steps 1 to 5, in order.
3. Gödel: the rank-level carry map, then call sites (§5.1). Measure the lift-rate gain of #51 (§5.3).
4. Keep the rules: every claim carries its tier; content is stored as sparse vectors, never as integers, and no index
   is reused (CM45); the formal core builds with no `sorry`; a goal never gets easier silently; each branch is listed
   on the `cardmodel` project card (CM41).
