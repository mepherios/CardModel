# Open PRs handover, 2026-11-05

This is a snapshot of every open PR as of about 07:48 UTC on 2026-11-05 (refreshed; the first version was written at 07:35 and #64–#87 have opened since), written for the next model. The facts come from the GitHub REST API (the PR list and each PR body). The root `HANDOVER.md` is still the operating manual. #43 adds `docs/HANDOVER.md`, an earlier snapshot taken at 06:45.

## Next session: launch checklist

Added at about 07:50 UTC on 2026-11-05. All facts come from the REST API (`pulls?state=open` plus `pulls/N` for `mergeable`/`mergeable_state`). 48 PRs are open. Three conflict with main: #39, #40 and #54. Every other PR reports `mergeable: true`; its state is `unstable` only because CI is red. "Kind" is docs when every changed file is under `docs/` or is a `.md` file.

**#88 bundles the docs PRs #72–#74, #76 and #80–#87.** Land #88 and close those twelve.

### Merge table

| PR | Branch | Conflicts with main | Kind |
|---|---|---|---|
| #33 | `claude/anyps5-blockers` | no | code |
| #34 | `claude/gb-mbc` | no | code |
| #35 | `claude/self-report-next` | no | code |
| #36 | `claude/reproducible-packs` | no | code |
| #38 | `claude/ci-csharp-harness` | no | code |
| #39 | `claude/c-frontend` | **yes** | code |
| #40 | `claude/hopeful-tesla-yvaan1` | **yes** | code |
| #41 | `claude/stdin-harness` | no | code |
| #42 | `claude/ci-fewer-runs` | no | code |
| #43 | `claude/project-thread-v2w0a1` | no | docs |
| #47 | `claude/go-negzero` | no | code |
| #50 | `claude/project-thread-vubpxu` | no | code |
| #52 | `claude/opaque-callees` | no | code |
| #53 | `claude/project-thread-jm4iji` | no | code |
| #54 | `claude/godel-section-cache` | **yes** | code |
| #55 | `claude/pipeline-coverage` | no | code |
| #57 | `claude/numeric-model` | no | code |
| #58 | `claude/search-uses-godel-match` | no | code |
| #59 | `claude/showcase-godel` | no | code |
| #60 | `claude/lifter-sorts` | no | code |
| #61 | `claude/ir-fixed-width` | no | code |
| #62 | `claude/frontend-widths` | no | code |
| #63 | `claude/emit-improve-fixes` | no | code |
| #64 | `claude/distill-ux` | no | code |
| #65 | `claude/handover-0505-session` | no | docs |
| #66 | `claude/godel-cli-source` | no | code |
| #67 | `claude/arm-symbolic` | no | code |
| #68 | `claude/codes-uses-core` | no | code |
| #69 | `claude/strings-ir` | no | code |
| #70 | `claude/godel-followups` | no | code |
| #71 | `claude/math-len` | no | code |
| #72 | `claude/targets-measured-0505` | no | docs |
| #73 | `claude/godel-progress-0505` | no | docs |
| #74 | `claude/environments-status-0505` | no | docs |
| #75 | `claude/bare-list-annotation` | no | code |
| #76 | `claude/owner-decisions-0505` | no | docs |
| #77 | `claude/godel-number-tokens` | no | code |
| #78 | `claude/arm-symbolic-memory` | no | code |
| #79 | `claude/arm-symbolic-loops` | no | code |
| #80 | `claude/doc-user-guide` | no | docs |
| #81 | `claude/doc-machines-next` | no | docs |
| #82 | `claude/doc-next-build` | no | docs |
| #83 | `claude/doc-applications` | no | docs |
| #84 | `claude/doc-ir-types-options` | no | docs |
| #85 | `claude/doc-scaling-next` | no | docs |
| #86 | `claude/doc-math-structure` | no | docs |
| #87 | `claude/doc-universal-understander` | no | docs |
| #88 | `claude/docs-bundle-0505` | no | docs (+2 non-doc files) |

### Launch steps

1. **Environment setup script.** It failed in this session (exit 1). The owner must fix it in the environment settings: either add the repo as a source, or clone it before the script's `cd`.
2. **Git fetch.** The clone is single-branch, so add the refspec before fetching PR branches:
   `git config --add remote.origin.fetch '+refs/heads/claude/*:refs/remotes/origin/claude/*'`
3. **CI is blocked on GitHub billing.** Until the owner fixes it, the merge rule is: a full local `python -B -m unittest` run from `tests/` passes, and `cardmodel verify` passes.
4. **Use the REST API only** (`gh api repos/...`). GraphQL is blocked, so `gh pr list/view` and similar commands fail.
5. **Suggested landing order:**
   1. The docs bundle #88 (then close #72–#74, #76, #80–#87).
   2. #50, which now carries #55's purity check if the port landed. #55 was still open at 07:50; check whether the port is in #50, and close #55 if it is.
   3. The ARM PRs in order: #67 → #78 → #79.
   4. The rest. The conflicting PRs #39, #40 and #54 need a rebase first.
6. **Owner decisions:**
   - GitHub billing (unblocks CI).
   - The `str` ledger atoms (#69): 11 atoms proposed to take the next free indices from 3425.
   - The ARM atoms (#67, #78, #79).
   - Whether to delete the branches `claude/ci-exact-int-pow` and `claude/project-thread-3hwg1g`.
   - The stray `/addranks.py` at the repo root.

## Ground rules

- **CI is blocked.** GitHub Actions has run out of billing minutes, so every check fails at once and prints nothing. A red check tells you nothing about the code.
- **Merge rule (owner):** a PR merges only after the full local `python -B -m unittest` passes when run from `tests/`. Targeted test runs are not enough. Below, "Not run" means that full run has not been done.
- Almost every PR from this session is a **draft**, and its test state is whatever its body says. Only #55 has a full local unittest run (head d44786d: 503 OK, 33 skipped). No other PR, old or new, had the full suite run on its final head.
- Most runs were held back because the shared heavy lock was busy with other agents' jobs.

## 1. FOUNDATIONS §7 (sorts and fixed widths)

| PR | Branch | Purpose | Tests run | Not run |
|---|---|---|---|---|
| #60 | `claude/lifter-sorts` | §7 item 1. Lifted machine code gets sorts: registers, byte reads and block locals (u8/u16). Masks fold only at their sorts. `LIFTER` goes 6 to 8. Masks on `busy_rom` drop from 138 to 102. | `test_machine test_symbolic` (47 OK); `verify --only machine` passes | Full suite, full verify |
| #61 | `claude/ir-fixed-width` | §7.2–3. Adds the IR types u8..i32 and f32, wrap-on-store lowering in the interpreter and every emitter, type templates on the language cards, and fixed-width conformance cells | `verify --only conformance` 2081/2081; 73 targeted tests OK; `sources check` passes | Full suite. Swift templates were never run. Lean cells would be gaps, because WRAPU/WRAPS/F32 are unsupported for Lean. Native-width templates are not done. |
| #62 | `claude/frontend-widths` | §7.4, frontend side. The Rust, Go, Java and C# fixed-width types lift to sorts (`Lifted.sorts`, `Lifted.divergences`). Rust overflow is recorded as a divergence, and Rust `wrapping_*` wraps. | `test_frontends` 20 OK. The real Go, Java and Rust toolchains agree with the lifts. C# is checked by lift shape only. | Full suite |

| #69 | `claude/strings-ir` | §7.5 input. `str` as code points and eleven `STR_*` op cards with templates; all pass conformance in 10 languages, 15 example functions agree. The ledger is untouched: the 11 atoms are only proposed (`cards/proposal/prop_godel_str_ops`), to take the next free indices from **3425** once approved. | `test_lang test_lists test_conformance test_godel` (39 OK); `docs --check` | Full suite. Lean has no string templates. |
| #71 | `claude/math-len` | Math notation: when `len`/`xs[i]` hits an unsigned parameter, the error names the signature to add (`s : [ℤ] → ℤ`) | `test_mathlang test_lists` | Full suite |
| #75 | `claude/bare-list-annotation` | A bare `list` annotation infers `list[int]` or `list[float]` from the body, witnessed against the source; else a clear message | `test_lists test_translate test_frontends` | Full suite |
- **Dependencies:**
  - #62 does not depend on #61. Once #61 lands, #62's `Lifted.sorts` can feed #61's IR types.
  - #62 leaves C to #39.

## 2. Gödel

| PR | Branch | Purpose | Tests run | Not run |
|---|---|---|---|---|
| #54 | `claude/godel-section-cache` | GODEL_AUDIT §6 step 1. The `godel` verify section is cached by `godel.check_key(ctx)`, a hash of the cards, the ledger and the engine source. The section takes 0.03–0.06 s when cached, against 15–20 s when computed. | `test_godel test_numbering` (28 OK); `docs --check` clean | Full suite, `verify --quick` |
| #55 | `claude/pipeline-coverage` | Every capability card gets a `pipeline` tier and a `godel` verdict. `engines/pipeline.py` adds a verify section (CM50, G_A13/G_A14). Integrity enforces GODEL_TARGET §7 and lists the 7 copies already on main. | **Full suite on head d44786d: 503 OK (33 skipped)**; `verify --only kernel,integrity,pipeline` passes | Full verify (conformance, functions, proofs) |
| #58 | `claude/search-uses-godel-match` | Purity A6: `search.match`/`instantiate` call `godel.match`/`godel.substitute`. The old matcher is kept as the test oracle. | 36 targeted tests OK; `verify --only rules,redefinitions` passes | Full suite |
| #53 | `claude/project-thread-jm4iji` | **The Gödel thread's PR.** Codegen becomes a carry map, so translate and matrix can predict a language's gap from content. | `test_translate test_matrix test_godel`; `verify --only integrity,godel` | Full suite |
| #66 | `claude/godel-cli-source` | `godel factor/similar/cofactor` accept `FILE.py:FUNC` (lift, then canonical term). Verdict CONSUMER. May overlap the Gödel thread in `cli_ext.py`. | `test_godel` (21 OK) | Full suite |
| #68 | `claude/codes-uses-core` | Proposal: `codes.py` reads Def-27 tokens through `G.tokens`/`G.structural`; old scheme kept as test oracle. Forest roots still build ∏p^c locally. | `test_codes test_godel` (26 OK); `godel sizes` byte-identical | Full suite |
| #70 | `claude/godel-followups` | Proposal: delete dead `distill.number()`, `Numbering.tokens` via `G.tokens`, `godel.scale` takes an exact `Fraction`, FSQRT via `G.scale` | `test_godel test_numbering test_codes` (34 OK), `test_dimensions`; `verify --only godel` | Full suite, `test_unreal` |
| #77 | `claude/godel-number-tokens` | **Stacked on #68.** `godel.number(tokens)` for a token list; `codes.py` uses it, removing its last hand-built prime product | `test_godel test_codes test_numbering`; `godel sizes` byte-identical | Full suite |
| #50 | `claude/project-thread-vubpxu` | **Another thread's PR.** The pipeline becomes a registry of `stage` cards (CM50, G_A13), and `translate` runs through it. | `verify --only integrity,capabilities,pipeline`. A full run before the rebase had 7 failures, all of them pre-existing. The rebased full run was "in progress". | — |

- **Gödel follow-ups** are #70, #68 and #77 (merge #68 before #77). #48 (the thread's physics Gödel set, ledger atoms 3418–3424) has **merged**.
- If #55 lands, its known-copies list shrinks by what #68, #70 and #77 retire.
- **Conflicts:**
  - **#55 and #50** both claim CM50 and G_A13, and both add `engines/pipeline.py`, `tests/test_pipeline.py` and `tools/seed_pipeline.py`. Expect a heavy conflict. **The owner must pick one.** Suggestion: keep #50 (the other thread's registry design) and port #55's purity integrity check and G_A14 onto it.
  - #58 also adds its branch to `cards/project/godel_functions/card.json`.

## 3. Scaling and environments

| PR | Branch | Purpose | Tests run | Not run |
|---|---|---|---|---|
| #52 | `claude/opaque-callees` | Ported onto #51 (merged): the witness-only `partial` status, full boundary cards with an opaque identity (`egraph.semantic_hash`), `opaque` gap edges, and the new sweep/scale counts | 55 targeted tests OK; `docs --check` | Full suite, `scale bench`, stdlib sweep. The lift-rate numbers were measured before the port. |
| #57 | `claude/numeric-model` | ENVIRONMENTS V-B: numeric-model laws `fp_contract`, `denormal_flush` and `reduction_order` (E12–E14), with declared and measured models per runner. `analyse` picks bit-exact or tolerant comparison. | 55 targeted tests OK; `docs --check` | Full suite, `verify --quick` (stopped at the deadline) |

- #57 leaves signed zero to #47, and leaves the conformance matrix's comparison untouched so as not to conflict with #47.

## 4. Bugs and showcase

| PR | Branch | Purpose | Tests run | Not run |
|---|---|---|---|---|
| #47 | `claude/go-negzero` | Signed zero in every target: Go `-0.0`, C `(--x)`, JS `-0` print, ceil/floor/trunc, Ruby `sqrt(-0.0)`. The matrix compares zeros by sign. | Matrix 821/821 cells, seeds 1–3, in 10 languages; `test_float_literals` (5) | Full suite; Swift |
| #59 | `claude/showcase-godel` | `examples/showcase/` (new files only): one numeric module goes through translate, algebra, e-graph, Gödel and math notation | All 14 `run.sh` steps run | Full suite (new example files only) |
| #64 | `claude/distill-ux` | `distill`: clean parse errors (exit 2, optional `expr:` prefix); passes and reports `var_sorts` (`--sort`, `--var NAME:SORT`). The random witness still samples ints only. | `test_cli` new test; `test_egraph` | Full suite |
| #63 | `claude/emit-improve-fixes` | Fixes four bugs: multi-function `emit` (Rust/Go/Java/C headers now come from one `emit_module`), `improve` on a list parameter, and `godel decode` usage | `test_emit_file test_improve test_godel test_translate` (45 OK). The new tests fail on main. | Full suite |

## 5. Older queue

| PR | Branch | Purpose | Tests run (per body) |
|---|---|---|---|
| #33 | `claude/anyps5-blockers` | AnyPS5: derives libSceRtc's tick arithmetic and binds it to 12 exports | `run stdlib/ps5_rtc.card` 21/21; test_anyps, test_projects, test_self_contained, test_lang |
| #34 | `claude/gb-mbc` | MBC7, HuC3 and the camera are witnessed across engines; the docs no longer call them missing | test_gb_mappers 13/13; machine/arcade/projects OK |
| #35 | `claude/self-report-next` | Exact forms for the four inconclusive redefinitions (G_C4 107 to 111) | 56 targeted tests OK; Redefinitions passes under 8 seeds |
| #36 | `claude/reproducible-packs` | Reproducible definition pack: fired equalities are recorded sorted, so the packs no longer depend on the hash seed | test_sources, test_egraph (8 OK) |
| #38 | `claude/ci-csharp-harness` | Witnesses C#, Kotlin and Julia sources with their own toolchains; Swift argument labels (fixes the red CI) | `CARDMODEL_SLOW=1` frontends/matrix/translate/lang OK |
| #39 | `claude/c-frontend` | C frontend: C's integer semantics (WRAPU/WRAPS), arrays as lists, `learn` from C trees | 76 targeted tests OK |
| #40 | `claude/hopeful-tesla-yvaan1` | `function_card` records the real source language. **Stacked on #32 (merged) and #39. Merge after #39.** | test_translate, test_learn, test_c_frontend (25 OK) |
| #41 | `claude/stdin-harness` | stdin harnesses: test programs read their inputs, so one build serves every seed | Unit suite run module by module: all pass except `test_unreal` (POW, from main) |
| #42 | `claude/ci-fewer-runs` | CI budget: one run per PR, the full job only when the PR is ready, a weekly self cycle | Workflow change only |
| #43 | `claude/project-thread-v2w0a1` | `docs/HANDOVER.md` snapshot (docs only) | Docs only |

None of these PRs has a recorded full-suite run on its current head.

## 6. ARM symbolic (machine track)

| PR | Branch | Purpose | Tests run | Not run |
|---|---|---|---|---|
| #67 | `claude/arm-symbolic` | ARMv5TE/Thumb terms checked against the bench: binds `op`, constant-index array cells, path splitting; `check_arm` and a verify `machine` entry. **0 → 92/167 pass, 0 fail** (89–96 by seed). More CLI/verify wiring was being pushed at snapshot time. LR35902 unchanged (511/512). | `test_symbolic test_machine` 47 OK in 3 of 4 runs (one failure during a parallel verify, not captured); `verify --only machine` | Full suite |
| #78 | `claude/arm-symbolic-memory` | **Stacked on #67.** Bus effects (rd/wr16/32, swi, undefined, cp) and a 64 KiB memory model: 92 → **156/167**, 0 fail | `test_symbolic test_machine` 47 OK | Full suite |
| #79 | `claude/arm-symbolic-loops` | **Stacked on #67.** Constant-bound loop unrolling and guarded `banked[]` writes: 92 → **98/167**, 0 fail; 6 loop cards then wait on #78's memory effects | `test_symbolic test_machine` 47 OK | Full suite |

- Order: #67, then #78, then #79 rebased (the combined result is not measured). The ARM ledger atoms are an owner decision.

## 7. Docs-only PRs opened today

None changes code. Each body says `docs --check` passes.

| PR | Branch | Adds or changes |
|---|---|---|
| #65 | `claude/handover-0505-session` | This file |
| #72 | `claude/targets-measured-0505` | `TARGETS.md` §1.2 measured on main a99bc77 (verify --quick 17/17 in 146 s, goals 32/6/16, canonical defs 24.6 %, ARM 0/167) and a CI billing decision |
| #73 | `claude/godel-progress-0505` | Open Gödel proposals noted in GODEL_TARGET §9 and GODEL_AUDIT §6 |
| #74 | `claude/environments-status-0505` | ENVIRONMENTS §6 status: V-A landed (#44), V-B is #57, V-D waits on #61 |
| #76 | `claude/owner-decisions-0505` | `docs/DECISIONS_PENDING.md`: the 16 owner decisions in one table |
| #80 | `claude/doc-user-guide` | `docs/USER_GUIDE.md`: recipes that work on main |
| #81 | `claude/doc-machines-next` | `docs/MACHINES_NEXT.md`: machine track options |
| #82 | `claude/doc-next-build` | `docs/NEXT_BUILD.md`: what to build next |
| #83 | `claude/doc-applications` | `docs/APPLICATIONS.md`: applications graded per CM46 |
| #84 | `claude/doc-ir-types-options` | `docs/IR_TYPES_OPTIONS.md`: options for tuples, Option, records, raise, truthiness, strings |
| #85 | `claude/doc-scaling-next` | `docs/SCALING_NEXT.md`: ten scalability options |
| #86 | `claude/doc-math-structure` | `docs/MATH_STRUCTURE_OPTIONS.md`: seven options (proposal) |
| #87 | `claude/doc-universal-understander` | `docs/UNIVERSAL_UNDERSTANDER.md`: proposal |

## Known conflicts

- **`cards/project/cardmodel/card.json` `branches`:** many PRs append their branch to this list (CM41). Resolve each conflict by keeping the union of the lists.
- **#47 vs #41** both edit the Go, C and JS language cards. Expect a conflict in the JS `harness.print` block.
- **#61 vs #41 and #47:** #61 adds type templates to the same language cards (c, go, javascript, ...). Merge them one at a time and re-save the cards through `kernel.versioning.save`.
- **#55 vs #50:** the pipeline and CM50 conflict described in section 2.
- **#77 on #68, #78 and #79 on #67:** each stacked PR shows its base's commit until the base lands.
- **#70 and #77** both edit `engines/godel.py`, in different functions.
- **#40** contains #39's diff until #39 lands.

## Owner decisions

1. **#48's 7 ledger atoms are permanent.** `quantity/*` sits at ledger indices 3418–3424, and the ledger is append-only. The next free ledger index is **3425**; strings-ir (#69) proposes its 11 atoms from there. Do not renumber.
2. **#50 or #55** (section 2): pick one. Suggested: keep #50, port #55's purity integrity check and G_A14 onto it.
3. **Who lands the queue.** Two sessions landing PRs today collided. The owner should pick one session (or themselves) to merge, one PR at a time, with the full local suite before each merge.
4. **#54 adds `check_key` to `engines/godel.py`.** That file belongs to the Gödel thread. The owner (or that thread) should approve the change, or move the key next to `verify`.
5. **CI billing.** Actions stays dead until billing or the spending limit is fixed. #42 reduces minute use once CI runs again.
6. Carried over from the PR bodies:
   - Lean templates for #61's fixed-width ops (the LEAN atoms).
   - #48's per-set dense rank for positional codes (it amends GM-4).
   - Where to track #58's branch.
   - ARM ledger atoms for #67/#78; the STR atoms of #69.

## Housekeeping

- A stray empty file `/addranks.py` sits in the container root (outside the repo). It is harmless.

---
Generated by Claude Code, session https://claude.ai/code/session_01TJ9eGEoapmESo2jc935j5m
