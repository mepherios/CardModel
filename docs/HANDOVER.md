# HANDOVER (2026-11-05): state of the work, for the next model

This is a snapshot handover for a model (or person) picking up CardModel cold. It says where main is, what is in
flight on which branch, what was left unfinished, and what only the owner can decide. The long-form operating manual
(how to run, extend and troubleshoot the model) is the root [HANDOVER.md](../HANDOVER.md); read that second. Verify
everything here against `git log`, the open PRs and the branches before acting: this file is a snapshot and will age.

---

## 0. Read this first: CI is not running

**Every CI run since about 02:00 UTC on 2026-11-05 fails in 3 to 5 seconds, main included** (run 64 on `29b5acd`).
The jobs never start and have no logs (HTTP 404), which is what an exhausted Actions minutes budget looks like on a
private repo. PR #42 says so in its commit message. Consequences:

* No open PR has a meaningful green or red check right now. "Wait for both CI checks" (the rule the prerequisite
  threads were given) cannot be satisfied until minutes are restored.
* PR #42 (`claude/ci-fewer-runs`) is the fix for the budget: CI on push only for main, one run per PR update, the
  full every-language job only when a PR is ready for review (quick jobs on drafts), and the self-optimize cycle
  weekly instead of daily. **Merge it first** once the owner has restored minutes (or raised the spending limit) in
  GitHub billing; without minutes even #42's own checks fail.
* Until then, run checks locally: `pip install -e .`, `python -B -m unittest` for the quick suite, and
  `cardmodel verify` for the full one (needs the toolchains; `tools/require_toolchains.py` lists what is missing).

What CI is, when it runs: `.github/workflows/ci.yml` (from PR #4, merged) runs a quick job on Python 3.9 and 3.13
and an "Every language" job that installs every target toolchain (13 languages) and runs verify, translate and the
conformance matrix. `.github/workflows/self-optimize.yml` runs one full self cycle daily at 03:17 UTC
(`cardmodel self run --force`, then `self adopt`, `docs`, `cover`) and opens or updates one rolling PR when `cards/`
changed. A 06:13 UTC auto-merge was described in the project chat, but there is no such workflow in the repo; if it
exists it is a scheduled agent outside the repo, so check before relying on it.

---

## 1. What CardModel is (in one paragraph)

Everything the model knows is a **card** under `cards/` (about 24,200 cards in 81 registries); everything it can do
is a `cardmodel` command. Programs are lifted from source languages into one typed IR, rewritten to canonical terms,
identified by content, and generated back into every target language, where each translation is **witnessed** by
running it against the source. The mathematics underneath is the **Gödel model**: a definition's content is its
canonical term, numbered so that factor/similar/cofactor questions become arithmetic. The goal set by the owner is a
model that runs and optimizes itself, runs natively on any platform, and can carry every integration to any language,
model or target, through mathematics, without hand work.

## 2. Documents, in reading order

| doc | what it gives you |
|---|---|
| [TARGETS.md](TARGETS.md) | where the model can go, the measured state of every layer, the ordered steps 0 to 11 with exit measurements, and **§7: the owner's open decisions** |
| [FOUNDATIONS.md](FOUNDATIONS.md) | the rules everything is built on (F*, D*, A*): one model, op cards, canonical content, identities naming their equivalence |
| [GODEL.md](GODEL.md) | walkthrough of the Gödel model's abilities, each graded proven / measured / conjecture (PR #20, merged) |
| [GODEL_AUDIT.md](GODEL_AUDIT.md) | which subsystems should build on the Gödel model and which must not; its §6 is the order of work (PR #25, merged today) |
| [ENVIRONMENTS.md](ENVIRONMENTS.md) | the running machine (CPU, GPU, memory, numeric model, driver, API) as mathematics; gap catalogue E1 to E24 (PR #27, merged today) |
| GODEL_TARGET.md | the target design for the restructured Gödel core; **only on branch `claude/project-thread-jm4iji` (PR #28)** |
| [SCALING.md](SCALING.md) | the scaling plan, S-A to S-D |
| [ROADMAP.md](ROADMAP.md) | the master plan and capability matrix |
| [../HANDOVER.md](../HANDOVER.md) | operating manual: quickstart, recipes, invariants, troubleshooting (written 2026-10-22, partly dated) |

The project's shared folder also holds `plans/independent-prerequisites.md`, a survey of which roadmap items can be
built without colliding with work in flight. Its content is summarised in §4.4 below.

## 3. Measured numbers worth carrying

* **96.1 % of the owner's own functions do not lift** (254 of 6,576 lift; TRANSLATE_REAL_PROGRAMS.md). The blockers
  are types: 3,863 non-numeric annotations (`str`, `list[float]`, dataclasses, `None`), 954 non-numeric defaults or
  `*args`, tuple targets, subscripts, list literals, `raise`, truthiness. Python 3.13 stdlib: 0.6 % lift.
* **Canonical definitions: 26 %** of 574 definitions have a canonical form (G_U7 = 0.258 against a 0.9 goal).
* **484 lifted arena functions collapse to 81** under identity of canonical content.
* **Gödel numbering check: 85 s to 3.5 s** by decoding positional codes with p-adic valuation (on PR #28, not yet
  on main; the audit measured the `godel` section at 100.7 s of a 224.6 s quick verify).
* Store: loading every card costs 3.5 s and 92 MiB on every command; the lazy indexed store (PR #18, merged) is the
  fix, but most global passes still "load everything, then loop".
* Proofs: the full verify proves 47 of 114 rewrite rules in Lean; the rest are witnessed only.

## 4. Work streams and where each stopped

Many threads ran in parallel on 2026-11-04 and stopped overnight. Branch names are `claude/...`; "behind" means
behind main at `7bf883a`. Every open PR below merges cleanly into main (checked with `git merge-tree`), but **none
has run under CI** (see §0).

### 4.1 Ground CardModel in core mathematics (fixed-width ints and f32 as real IR types)

* Landed: subsorts `u8..i32 <= int` and `f32 <= float` with their op cards and laws (`c195f01`, FOUNDATIONS.md D1).
* Left: the rest of the multi-PR series (IR TYPES in `cardmodel/engines/ir.py`, codegen templates per language,
  conformance cells, then `str`, tuple, Option, records, `raise`, truthiness). No branch was pushed for the next PR.
  This thread **owns `engines/ir.py` TYPES**; other work must not add IR types.
* Related open PR **#31** (`project-thread-8z7gnb`): instruction terms distilled under the register sorts, plus
  reproducible definition certificates and witnessing stored canonical terms. 4 commits, 5 behind.

### 4.2 Restructure around the Gödel model

* Landed: GODEL.md (#20), canonical content (F4), identities naming their equivalence (F5), one-model rules (F2),
  the audit (#25).
* **PR #28** (`project-thread-jm4iji`, draft): GODEL_TARGET.md and the restructured core, p-adic decoding of
  positional codes, `godel_decode` stopping at the first absent prime. This is "PR 1" of the series.
* Left: PR 2, the `godel factor / similar / cofactor / decode` commands; PR 3, physics as a Gödel set (with a
  dimensional-analysis witness). Neither has a branch. Files owned: `engines/godel.py`, numbering, funcalg, codes,
  `unreal/distill`.

### 4.3 Make every capability run in the main pipeline (tiers and coverage check)

* A pipeline registry where every capability declares its tier and a coverage check fails when a capability never
  runs in the main pipeline. **No branch was pushed**; start from TARGETS.md and `cardmodel cover`.

### 4.4 Independent roadmap prerequisites (plans/independent-prerequisites.md)

Three items were judged buildable now, each as small PRs with self-merge authorised by the owner once CI is green:

1. **Environment card and per-resource budgets** (ENVIRONMENTS V-A: E20, E21, E6; SCALING S-A): an `environment`
   card registry, a host probe (ISA, cores, RAM, measured cache levels, copy bandwidth), its fingerprint on metric
   and witness cards, and `kernel/resources` reading budgets from it.
2. **Stop failed callees from failing callers** (SCALING §3.3): a function that does not lift becomes an opaque
   boundary card; callers lift with the edge recorded as a gap. Files: `frontend_python.py` (`close_calls`),
   `lift_project.py`. Measure lift rate before and after. Highest-urgency item: it hides most of the lift rate.
3. **Scale benchmark** (`cardmodel scale bench`, SCALING §6): seeded synthetic projects of 10^3 to 10^5 functions;
   time and peak memory per function as metric cards; "scale slope" and "memory bound" goal cards.

**No branch for any of the three was pushed.** They are the best cold-start work for a new model, because they touch
nothing another stream owns. The plan's "build later" table lists what must wait and on what.

### 4.5 Transformer math in math notation

* Landed in **#32**: lists in math notation, nested loops in constant stack, `tanh` in Lua (closing the Lua GELU
  tanh gap), fresh loop variables, distinct Greek parameters, Swift argument labels, exact integer POW in the IEEE
  evaluator.
* Left: listing every transformer function as an equation in math notation is partly done; check `docs/LISTS.md`
  and `docs/MATH_LANGUAGE.md` for which ones remain.
* Branch `claude/ci-exact-int-pow` (no PR) is superseded by #32 and can be deleted.

### 4.6 GPU, driver and environment modelling

* Landed today: ENVIRONMENTS.md with the 24-gap catalogue (E1 to E24) and proposed D15 to D18 and A8 for
  FOUNDATIONS.md (adoption is the owner's call, §5).
* Left: everything executable. Order per ENVIRONMENTS §6: V-A (environment card, shared with §4.4 item 1), V-B
  (numeric-model laws: fp_contract, denormal_flush, reduction_order), then V-D (a SPIR-V card and lavapipe in CI).

### 4.7 Other open PRs (all drafts, all mergeable, none CI-verified)

| PR | branch | what | note |
|---|---|---|---|
| #42 | ci-fewer-runs | CI minutes budget | merge first, after minutes are restored |
| #41 | stdin-harness | test programs read inputs from stdin, one build per language serves every seed | the prerequisites plan said wait for the fixed-width series; it was built anyway and merged with #32 |
| #40 | hopeful-tesla-yvaan1 | `function_card` records the real source language (a loop variable shadowed `lang`) | stacked on #39 |
| #39 | c-frontend | C frontend: C integer semantics, arrays as lists, learning from C trees | |
| #38 | ci-csharp-harness | witness C#, Kotlin and Julia with their own toolchains | Swift part deduplicated against #32 |
| #36 | reproducible-packs | definition pack records every fired equality, sorted | overlaps a commit on #31 |
| #35 | self-report-next | exact forms for four inconclusive cards (G_C4 107 to 111) | |
| #34 | gb-mbc | MBC7, HuC3 and the Game Boy camera witnessed across engines | |
| #33 | anyps5-blockers | libSceRtc tick arithmetic bound to 12 exports | |
| #31 | project-thread-8z7gnb | instruction terms under register sorts | §4.1 |
| #28 | project-thread-jm4iji | Gödel target design and restructured core | §4.2 |

Branch `project-thread-3hwg1g` (no PR) differs from main by one line in `cli.py` (lift-sweep in the help
docstring); its other commits are already on main.

## 5. Decisions only the owner can make (TARGETS.md §7)

1. **Second target** after A: the native arcade (D) or binaries (B). Steps are shared up to 6.
2. **iPad as the Phase I test device.** It forbids generating code on the device, which is what makes I4 and I5
   necessary.
3. **Gödel decisions**: the Mathlib and Foundation downloads (W-2); proposed laws **GM-1 to GM-9**; GM-2's amendment
   of CM43 (identity is the hash of the canonical term, the positional code a witness).
4. **GODEL_AUDIT decisions**: GM-4 as a law, positional codes by per-set dense ranks (amends CM43's text), minting
   the `LEAN_*` and ARM atoms, adopting Unreal's identities as ledger events.
5. **ENVIRONMENTS decisions**: adopt D15 to D18 and A8 into FOUNDATIONS.md as written; whether the owner's Mac is
   the first device for the transfer judgment.
6. **Actions minutes** (new, §0): restore them or raise the limit, then merge #42.

## 6. Suggested order for the next model

1. Get CI running (§0), merge #42, then let CI run on every open PR; merge the green ones in this order:
   #38 and #41 (harness), #39 then #40 (C frontend), #36, #35, #34, #33, #31, #28. Rebase on main between merges.
2. Start the three independent prerequisites (§4.4), smallest first: item 2 (opaque callees), then item 3 (scale
   bench), then item 1 (environment card).
3. Continue the owned series only from their own branches: fixed-width IR types (§4.1), Gödel PR 2 and PR 3 (§4.2).
4. Keep the rules: every claim carries its tier; content is stored as sparse vectors, never as integers, and no index
   is reused (CM45); the formal core builds with no `sorry`; a goal never gets easier silently; each branch is listed
   on the `cardmodel` project card (CM41).
