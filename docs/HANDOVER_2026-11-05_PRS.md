# Open PRs handover, 2026-11-05

This is a snapshot of every open PR as of about 07:35 UTC on 2026-11-05, written for the next model. The facts come from the GitHub REST API (the PR list and each PR body). The root `HANDOVER.md` is still the operating manual. #43 adds `docs/HANDOVER.md`, an earlier snapshot taken at 06:45.

## Ground rules

- **CI is blocked.** GitHub Actions has run out of billing minutes, so every check fails at once and prints nothing. A red check tells you nothing about the code.
- **Merge rule (owner):** a PR merges only after the full local `python -B -m unittest` passes when run from `tests/`. Targeted test runs are not enough. Below, "Not run" means that full run has not been done.
- Almost every PR from this session is a **draft**, and its test state is whatever its body says. None of these PRs had the full suite run on their final head, except #55 (503 OK, 33 skipped).
- Most runs were held back because the shared heavy lock was busy with other agents' jobs.

## 1. FOUNDATIONS §7 (sorts and fixed widths)

| PR | Branch | Purpose | Tests run | Not run |
|---|---|---|---|---|
| #60 | `claude/lifter-sorts` | §7 item 1. Lifted machine code gets sorts: registers, byte reads and block locals (u8/u16). Masks fold only at their sorts. `LIFTER` goes 6 to 8. Masks on `busy_rom` drop from 138 to 102. | `test_machine test_symbolic` (47 OK); `verify --only machine` passes | Full suite, full verify |
| #61 | `claude/ir-fixed-width` | §7.2–3. Adds the IR types u8..i32 and f32, wrap-on-store lowering in the interpreter and every emitter, type templates on the language cards, and fixed-width conformance cells | `verify --only conformance` 2081/2081; 73 targeted tests OK; `sources check` passes | Full suite. Swift templates were never run. Lean cells would be gaps, because WRAPU/WRAPS/F32 are unsupported for Lean. Native-width templates are not done. |
| #62 | `claude/frontend-widths` | §7.4, frontend side. The Rust, Go, Java and C# fixed-width types lift to sorts (`Lifted.sorts`, `Lifted.divergences`). Rust overflow is recorded as a divergence, and Rust `wrapping_*` wraps. | `test_frontends` 20 OK. The real Go, Java and Rust toolchains agree with the lifts. C# is checked by lift shape only. | Full suite |

- **strings-ir:** no open PR. The next free ledger indices come after #48's atoms (see Owner decisions).
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
| #50 | `claude/project-thread-vubpxu` | **Another thread's PR.** The pipeline becomes a registry of `stage` cards (CM50, G_A13), and `translate` runs through it. | `verify --only integrity,capabilities,pipeline`. A full run before the rebase had 7 failures, all of them pre-existing. The rebased full run was "in progress". | — |

- **Gödel follow-ups:** no separate PR exists. #48 (the thread's physics Gödel set, ledger atoms 3418–3424) has **merged**.
- **Conflicts:**
  - **#55 and #50** both claim CM50 and G_A13, and both add `engines/pipeline.py`, `tests/test_pipeline.py` and `tools/seed_pipeline.py`. Expect a heavy conflict. The two designs need reconciling before either one lands.
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

**ARM symbolic:** no open PR exists.

## Known conflicts

- **`cards/project/cardmodel/card.json` `branches`:** many PRs append their branch to this list (CM41). Resolve each conflict by keeping the union of the lists.
- **#47 vs #41** both edit the Go, C and JS language cards. Expect a conflict in the JS `harness.print` block.
- **#61 vs #41 and #47:** #61 adds type templates to the same language cards (c, go, javascript, ...). Merge them one at a time and re-save the cards through `kernel.versioning.save`.
- **#55 vs #50:** the pipeline and CM50 conflict described in section 2.
- **#40** contains #39's diff until #39 lands.

## Owner decisions

1. **#48's 7 ledger atoms are permanent.** `quantity/*` sits at ledger indices 3418–3424, and the ledger is append-only. strings-ir and any later atoms must take the next free indices after them. Do not renumber.
2. **Who lands the queue.** Two sessions landing PRs today collided. The owner should pick one session (or themselves) to merge, one PR at a time, with the full local suite before each merge.
3. **#54 adds `check_key` to `engines/godel.py`.** That file belongs to the Gödel thread. The owner (or that thread) should approve the change, or move the key next to `verify`.
4. **CI billing.** Actions stays dead until billing or the spending limit is fixed. #42 reduces minute use once CI runs again.
5. Carried over from the PR bodies:
   - Lean templates for #61's fixed-width ops (the LEAN atoms).
   - #48's per-set dense rank for positional codes (it amends GM-4).
   - Where to track #58's branch.

---
Generated by Claude Code, session https://claude.ai/code/session_01TJ9eGEoapmESo2jc935j5m
