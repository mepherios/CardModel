# Integration: how parallel work becomes one program

Several Claude Code sessions build this repository at once, each in its own git worktree. This page is the
contract that keeps their work from interfering (law CM39): who works where, which numbers are taken, how a
branch reaches `main`, and a log of every integration. `cardmodel verify --only integrity` (also in every
quick verify and every self-run) checks the mechanical part.

## 1. Rules

1. **`main` is the program.** Each side session works in its own worktree (`.claude/worktrees/<name>`) on its own
   branch (`claude/<name>`), commits there and never pushes. Nothing in this repository is pushed anywhere.
2. **Only the integrating session merges into `main`**, and only after the user says so:
   `git merge --no-ff refs/heads/claude/<name>` (full ref, so a tag of the same name cannot win).
3. **Before the merge commit**, in this order:
   * no merge markers anywhere (`cardmodel verify --only integrity` finds them in code, docs and card sources);
   * a renumbering if two branches took the same law or goal number (section 2): rename the card directory and
     its `name`, and fix every reference (`grep -rn CMnn_`);
   * conflicts in the shared files (section 4) resolved as a union of both sides, never by dropping one side;
     generated files are regenerated, never hand-merged;
   * `python3 -B tools/seed_self.py` (and any other seed tool whose cards changed), then `cardmodel docs`;
   * the fast gate: `cardmodel verify --only integrity,capabilities`;
   * then, one heavy job at a time: the test suite (`cd tests && python3 -B -m unittest`) and the full
     `cardmodel verify`.
4. **After the merge**: `cardmodel cover --write COVERAGE.md` after a full verify, and a line in the log
   (section 5). Tell the sessions still working that `main` moved and which numbers are now taken.
5. **A branch catches up** by merging `main` into itself (`git merge main` in its worktree) before its next commit
   after `main` moved. Never rebase a branch someone else may be reading. Never stash, reset or switch branches
   in a checkout another session uses.
6. **Background cycles never write tracked files.** The self-run writes only under `state/self/`. A session
   adopts what it learned deliberately (`cardmodel self adopt`), reviews it and commits it (docs/AUTONOMY.md).
7. **State is per checkout.** Each worktree has its own `state/` (gitignored): ROM surveys, builds, depots, the
   self layer. Anything installed outside the repository (the Cardmodel Arcade app in `~/Applications`) records
   the checkout it was installed from. Install it from `main`. The self-run flags an installed app that runs
   another checkout.
8. **Sessions only read** the user's source folders (`~/Documents/Claude_Hub`, `~/Documents/Pheros_Studio`,
   `~/Documents/rea-main`, `~/Programmering/ting`, `~/Programmering/rea-cards`, `~/Documents/AnyPS5-main`, the
   ROM folders). ROM bytes, firmware and keys are never copied into the repository. Terms lifted from Unreal
   Engine's source (UE-derived data) stay in untracked local storage (`state/`), never in tracked packs or in a
   merged branch's history: the user, 2026-10-22, "Keep UE-derived data local: lifted Unreal terms go to untracked
   local storage, not tracked packs." Names, paths and line numbers may be tracked.

## 2. Number registry

A law's number is its identity (LAWS.md is generated from the cards). Take the next free number here, and add the
range to this table in the same commit.

| laws | owner | what |
|---|---|---|
| CM01–CM31 | main | the consolidation, the knowledge layer, the card language, the game design, resources, function algebra |
| CM32–CM35 | games (`claude/sad-sanderson-482207`) | machines are cards; lifted code is the cards; emulation effects are the shell; games are cards |
| CM36 | AnyPS5 (`claude/recursing-williams-ecc80a`) | unknowns are observation obligations (merged as CM32, renumbered CM36 at integration) |
| CM37–CM39 | main (self-run) | the core is never lost; the model runs itself; one program |
| CM40 | cartridges (`claude/festive-margulis-43fde7`) | players are cards (written as CM36 on that branch, renumbered CM40 when it caught up with main) |
| CM41 | main | projects keep their cards current |
| CM42 | self-running-improvement (`claude/jolly-liskov-2d97a8`) | the store runs what it lists (CM39 on that branch before the fold) |
| CM43 | main (MATH_CORE phase 0) | primes are forever |
| CM44 | main (MATH_CORE phase 1) | everything traces back to the four sources |
| CM45–CM46 | main (the research handover's phase 0) | content is a sparse vector; every claim carries its tier |
| CM47 | world game (`claude/heuristic-ptolemy-2e6700`), reserved | written as CM45 on that branch; renumber before merging |
| CM48 | universalization (`worktree-universal-domains`), reserved | "every domain is a Gödel set", written as CM45 on that branch; renumber before merging |
| CM49 | unreal-distill (`claude/unreal-math`, merged daf4923) | a game engine's math is distilled (Unreal Engine as cards, docs/UNREAL.md); written as CM47 on the branch, renumbered before merging |
| **CM50 onward** | free | take the next one |

Goal ids are `G_<axis letter><n>`. Taken: G_C1–C5, G_U1–U12 (G_U10–U12: unreal-distill), G_L1, G_O1–O4, G_A1–A10, G_K1–K6, G_D1–D2, G_P1–P5
(AnyPS5), G_M1–M6 (machines; G_M6 is MATH_CORE's), G_S1 (products: the store, `claude/jolly-liskov-2d97a8`).
G_A10 is that branch's law-witness goal, written G_A9 there and renumbered where it met MATH_CORE's G_A9
(`claude/frosty-lumiere-98e2b7`). The next free one is the axis's next number (G_A11, G_U13, G_C6, G_K7, G_M7,
G_P6, G_S2 ...).

Two sessions that take the same number find out at the merge: `cardmodel verify --only integrity` reports
"law number CMnn is used twice". The branch that merges second renumbers (rule 3). On 2026-10-21 this happened
twice: AnyPS5's CM32 became CM36, and the uncommitted work on `claude/jolly-liskov-2d97a8` used CM37–CM39 and
G_A4–G_A6. That session was told to move to CM41+ and G_A8+.

Verify sections (`engines/verify.py` SECTIONS; each is described in its docstring): kernel, integrity,
capabilities, logic, lang, theorems, game (main); anyps5 (AnyPS5); machine (games); forms, vectors, rules,
redefinitions, conformance, functions, proofs, selfcheck, portability (main); projects, godel, sources, tiers, formal
(main).

## 3. Who works where

| session | branch / worktree | area (files it owns) | on main |
|---|---|---|---|
| unreal-distill | `claude/unreal-math` (the work of `claude/unreal-distill` as one commit: that branch's history held engine-derived packs, rule 8) | `cardmodel/unreal`, `cardmodel/engines/realnorm.py`, the registries `unreal_math`, `unreal_use`, `unreal_cause` (their cards in the local layer `state/local/cards`, rule 8), the analysis and bits op cards, `tools/seed_unreal.py`, `examples/engine_math`, docs/UNREAL*.md, tests/test_unreal.py; verify section `unreal` | c18209b (merge daf4923, with the user's approval); the engine's cards stay in the local layer of the checkout that scanned it |
| integrating session | `main`, the repository folder | kernel, engines, lang, emit, game, docs, the self-run (`engines/selfrun.py`, `capabilities.py`, `integrity.py`) | — |
| cardmodel-games | `claude/sad-sanderson-482207` | `cardmodel/machine`, `cardmodel/arcade`, `cards/{isa,hardware,machine,app,game,platform,asset}`, docs/MACHINES.md, docs/ARCADE.md, tests/test_machine.py, tests/test_arcade.py | up to 85909ec (merge c1bf07f) |
| cardmodel-anyps5 | `claude/recursing-williams-ecc80a` | `cardmodel/anyps5`, `stdlib/ps5_*.card`, `cards/anyps5_*`, docs/ANYPS5*.md, tests/test_anyps.py, tools/seed_anyps5.py | up to 10c688f (merge 65a059c) |
| model-the-dmg-oam-corrup | `claude/festive-margulis-43fde7` | the DMG OAM corruption bug (machine and hardware cards), then cartridges and players (538f29c) | up to 11284a6 (merge f25e82a): cartridges, players, per-cartridge apps, the lifter, the static pass, DS touch input |
| game-boy-cgb-dmg-compati | `claude/strange-dewdney-f8f39d` | the CGB's DMG compatibility mode | 05178e1 (merge 7e4323a) |
| self-running-improvement | `claude/jolly-liskov-2d97a8` | folded into `cardmodel self`: the `law_witnesses`, `observe_self`, `store` and `tests` steps (`engines/selfrun.py`, `engines/witness_runner.py`), step deadlines (`kernel/resources.deadline`), the store's end-to-end check (`arcade/client.py`, `arcade check`, CM42, G_A10, G_S1), goal floors in the integrity check (§4a), fixes in translate, exprs, coverage and verify | up to 984fc7a (merged 2026-10-22 with the user's approval); its goal floors replaced main's dccedca |
| game-boy-library | `claude/frosty-lumiere-98e2b7` | the Game Boy library (header titles, the system card's check cartridge, a player reused cartridge after cartridge) and the store check over every listed cartridge (`arcade/client.py` check_cartridges and Reference, `arcade check --cartridges N`) | up to b15b527 (merged 2026-10-22 with the user's approval); its console-player check replaced main's test_cartridge |
| ds-a-first-picture-of-po | `claude/blissful-easley-814fa6` | the DS: VRAM, the 2D and 3D engines, sound, Wi-Fi as hardware cards, the DS player and its check cartridge (`system/nds`, docs/MACHINES.md DS) | up to 0fcb468 (merge 9269eee) |
| game-boy-the-10-cartridg | `claude/sad-clarke-108d42` | the last bank controllers as cards (MBC7, HuC3, Game Boy Camera, Wisdom Tree, Sachen) | up to ea14439 (merge 593fe5c) |
| fix-flaky-arena-test-dec | `claude/sharp-goldwasser-8b0d81` | the arena's triangular decoy | d9e2ba3 (merge 05c54ea) |
| fix-flaky-numeric-check | `claude/brave-montalcini-19f1b8` | float rounding in the redefinition witness | 60e72ca (merge cf775f2) |

## 4. Shared and generated files

* **Shared** (several sessions edit them; on a conflict keep both sides): README.md, GOALS.md, HANDOVER.md,
  ROADMAP.md, ARCHITECTURE.md, docs/METHODOLOGY.md, `cardmodel/cli.py`, `cardmodel/cli_ext.py`,
  `cardmodel/engines/verify.py` (SECTIONS and QUICK: the union, in one definition), `tests/test_laws.py`
  (the CLAIMING and NO_LANGUAGE_BRANCHES lists: the union), `tools/bootstrap.py`, `.gitignore`.
* **Generated** (regenerate, never merge by hand): LAWS.md (`cardmodel docs`), COVERAGE.md
  (`cardmodel cover --write COVERAGE.md`), docs/ANYPS5_COVERAGE.md (`cardmodel anyps5 cover --write docs/ANYPS5_COVERAGE.md`),
  stdlib/algebra.card (`cardmodel algebra scan --write`), the `_pack_*.jsonl` card packs (their tools).

## 4a. Goal floors

A goal's target is a promise: lowering it quietly is a way to lose part of the core. `floor/goals` records the floor
of every goal (the hardest target it has had, its metric and its direction). `cardmodel docs` writes it: a new goal
or a harder target raises the floor; nothing else does. The integrity check (every quick verify and self-run) fails
when a goal is easier than its floor, has another metric or direction, or has gone, unless the reason is written
down:

* to make a goal easier or change what it measures, give its card
  `"amended": {"from": <the goal's entry in floor/goals>, "reason": "why"}`, then run `cardmodel docs`: the floor
  moves to the new target and `floor/goals` keeps the change in its `history` (from, to, reason, date);
* to retire a goal, add `{"goal": "G_...", "reason": "why", "date": "..."}` to `retired` in `floor/goals` before
  removing its card; `cardmodel docs` then drops its floor.

## 4b. Project cards (law CM41)

Every project in progress keeps a detailed card, and its owning session keeps it current. The store's In progress
page and its "Waiting on you" list are built from these cards (`cardmodel/arcade/hub.py`, `engines/projects.py`),
and `cardmodel verify` (section `projects`) fails when one is missing or stale.

* **Where.** Projects in this repository: `cards/project/<name>/card.json`. Revise it on your branch in the same
  commit as the work, or within a day of it. A project in another repository keeps its detail there, committed, in
  `.cardmodel/project.json`. The hub reads that with `git show HEAD:...` and never writes it, and it overrides the
  card here.
* **Fields** (the card's what-to-watch fields `repo`, `paths`, `games`, `metrics`, `docs` stay as they are):

```json
{
  "goal": "one sentence: what the project is for",
  "standing": "one sentence: where it stands now (`status` is every card's lifecycle field)",
  "done": ["finished pieces"],
  "in_progress": ["what is being worked on"],
  "left": ["what remains"],
  "blockers": ["what stops it, if anything"],
  "next_steps": ["the next concrete steps"],
  "user_actions": [{"action": "what the user must do or decide", "why": "why it matters",
                    "unblocks": ["what it unblocks"]}],
  "owner": {"session": "local_<id>", "name": "the owning session's short name"},
  "branches": ["claude/<your-branch>*"],
  "updated": "2026-10-22T00:30:00+02:00"
}
```

* **Stale.** A commit that touches the project's `paths` (in another repository, any commit) more than 24 hours
  after `updated` makes the card stale.
* **Missing.** On main, every branch with unmerged commits from the last week must be listed in some card's
  `branches`. On a branch, that branch must be listed.
* **Computed, not written.** The phase, the last commits, ahead/behind counts, uncommitted work, metrics (with
  the checkout that measured them) and builds are computed by the hub. Never type them into the card.

## 5. Integration log

| date | commit | what landed |
|---|---|---|
| 2026-10-21 | 05c54ea | `claude/sharp-goldwasser-8b0d81`: the arena's triangular decoy was triangular + 1, not a decoy |
| 2026-10-21 | cf775f2 | `claude/brave-montalcini-19f1b8`: the redefinition witness's float rounding |
| 2026-10-21 | 65a059c | `claude/recursing-williams-ecc80a`: AnyPS5 as cards (scan, classification, coverage, witnesses), verify section `anyps5`, goals G_P1–G_P5 |
| 2026-10-21 | ab76427 | `claude/sad-sanderson-482207`: machines as cards, lifted ROM code and the effect shell, the DS prototype, hardware test suites, Vector Duel and Cardmodel Arcade; verify section `machine`; AnyPS5's law renumbered CM32 -> CM36 |
| 2026-10-21 | 9469e58 | `claude/festive-margulis-43fde7`: the DMG's OAM corruption bug; every runnable hardware test ROM passes |
| 2026-10-21 | f38dce7 | main: core capabilities as cards (CM37), the self-run (CM38), the integrity check (CM39), docs/AUTONOMY.md, docs/STORE.md, this page |
| 2026-10-21 | 7e4323a | `claude/strange-dewdney-f8f39d`: the CGB's DMG compatibility mode (05178e1); HANDOVER.md merged as a union, COVERAGE.md regenerated |
| 2026-10-22 | bb480fb | main: the store's live In progress page (cards/project, arcade/hub.py, early access); main took over port 8770 and the installed launcher, agreed with the games session |
| 2026-10-22 | c8aeb4c | main: law CM41, detailed and current project cards, the Waiting on you list |
| 2026-10-22 | de22b52 | main: docs/MATH_CORE.md, a proposal awaiting the user's yes |
| 2026-10-22 | e86a84b | main: project cards revised honestly; a timing race out of `test_affine_match` |
| 2026-10-22 | 99242f5 | main: the hub re-reads the cards when anything moved, so a revised project card shows at once |
| 2026-10-22 | e0eca75 | `claude/sad-sanderson-482207`: Vector Duel 0.4.0 is the release (the user's "Yes: merge claude/sad-sanderson-482207 into main so Vector Duel 0.4.0 is the release") |
| 2026-10-22 | b75a6d2 | main: Vector Duel 0.4.0 released from main's cards; early access only from branches with unmerged work |
| 2026-10-22 | 03b1c6e | main: MATH_CORE phase 0 F1–F3 (the user's "Yes to MATH_CORE.md: start phase 0 and phase 1"): the prime ledger, content vectors, structural numbers, core types; law CM43 |
| 2026-10-22 | 51a70b2 | main: MATH_CORE phase 0 F4: equality saturation (an e-graph) over the rule cards and discovered laws |
| 2026-10-22 | bcdbdde | main: MATH_CORE phase 1: the four sources (definition, action, transformation, method); law CM44 |
| 2026-10-22 | 8dbd200 | main: MATH_CORE phase 0 F5: the LR35902 instruction cards as symbolic terms (511 of 512 agree with the bench) |
| 2026-10-22 | 4d9d755 | `claude/festive-margulis-43fde7` at 11e2560 (the user's "approved", in the OAM session): the Game Boy Player as cards, the cartridge library, every session's branch in the launcher; launcher reinstalled from main, 8770 restarted |
| 2026-10-22 | a5ed2d5 | main: one store mechanism for work in progress: early access is the branch versions, the WORK tab is In progress's Every branch section |
| 2026-10-22 | baa785a | main: the live_hub capability's witness follows the new test |
| 2026-10-22 | 7d4da20 | main: MATH_CORE phase 0 by the research handover (the user's "Yes, send the research handover to the card-model session so its phase 0 work follows the agenda and the storage rules"): storage rules (CM45), witness tiers (CM46), the formal core in Lean (T1–T6), verify sections tiers and formal |
| 2026-10-22 | ccad4bc | main: witness tiers: linear recursions with constant coefficients are C-finite (8 of 25 algorithm forms proved) |
| 2026-10-22 | e549b1d | main: the Gödel method research program, wave 1 (the user's "Yes, send the Gödel method handover to the card-model session and have it start the wave-1 workstreams (W-1, W-2, W-3, W-5, W-12, W-15) under its coordination rules"): a project card per workstream, the finding registry |
| 2026-10-22 | 3b7798b | `claude/godel-w15-difficulty`: the difficulty census (W-15): a rank on every method, 18 question cards |
| 2026-10-22 | 48d496a | `claude/godel-w3-identity`: identity and size of codes (W-3): six codes measured, the size model, the GM-2 decision record |
| 2026-10-22 | 7c588e6 | `claude/godel-w5-numberings`: admissible numberings (W-5): six conditions, every Gödel set passes, arities stated |
| 2026-10-22 | 1c6f08a | main: tests no longer depend on other sessions' branches (CM41's check honours CARDMODEL_BRANCHES=0) |
| 2026-10-22 | 8be8819 | `claude/godel-w1-definitions`: Gödel's 46 definitions as cards with Python and Lean forms (W-1), the proof checker |
| 2026-10-22 | 9d68e93 | main: CM47 and CM48 reserved for the two branches that wrote CM45 |
| 2026-10-22 | dd7840e | `claude/godel-w12-arithmetized`: the instruction terms as constraints over a prime field (W-12); formal.build stages its targets |
| 2026-10-22 | dccedca | `claude/integrity-goal-floors`: no goal's target made easier without an amendment (asked for by the self-running-improvement session) |
| 2026-10-22 | f25e82a | `claude/festive-margulis-43fde7` up to 11284a6 (the user's "Yes: merge claude/festive-margulis-43fde7 (e8def41 ...) into main" and "Yes: include 11284a6 ..."): per-cartridge apps, the lifter at 100 %, the static pass, relift, DS touch input |
| 2026-10-22 | e72fa77 | `claude/jolly-liskov-2d97a8` at 984fc7a (the user's "Yes: approve merging claude/jolly-liskov-2d97a8 (head 984fc7a) into main"): law witnesses, observe_self, the store's end-to-end check (CM42, G_A10, G_S1); its goal floors (§4a) replace dccedca's |
| 2026-10-22 | 32f5f58 | `claude/frosty-lumiere-98e2b7` at b15b527 (the user's "Yes: merge claude/frosty-lumiere-98e2b7 into main ..."): the Game Boy library's titles and check cartridge; `arcade check` launches every listed cartridge (its player check replaced main's test_cartridge) |
| 2026-10-22 | 9269eee | `claude/blissful-easley-814fa6` at 0fcb468 (the user's "Yes: merge claude/blissful-easley-814fa6 (the DS player), ea14439 (the 10 cartridges), the STOP fix 73e6220 and 85909ec into main"): the DS player, the Wi-Fi card, the DS check cartridge |
| 2026-10-22 | 593fe5c | `claude/sad-clarke-108d42` at ea14439 (the same approval): MBC7, HuC3, the Game Boy Camera, Wisdom Tree, Sachen as cards |
| 2026-10-22 | 16ea9fc | 73e6220 from `claude/festive-margulis-43fde7` (the same approval; only that commit): a lifted STOP skips one byte |
| 2026-10-22 | c1bf07f | `claude/sad-sanderson-482207` at 85909ec (the same approval): the Vector Duel project card's next steps |
| 2026-10-22 | daf4923 | `claude/unreal-math` at c18209b (the user's "Merge claude/unreal-distill into main yourself in the main checkout, following docs/INTEGRATION.md rule 3."): Unreal Engine's math as cards (CM49, G_U10–U12), the store's local layer for UE-derived data (rule 8); the work of `claude/unreal-distill` as one commit, since that branch's history held engine-derived packs. 357 tests and every verify section passed on the identical tree before the merge; on main every section passes and `unreal` skips (no engine cards in this checkout). COVERAGE.md's G_A10 = 46 is the self-run's law-witness step of 14:29, which hit its 1800 s deadline under load before this merge |

Each merge was followed by the full test suite and a full verify on the merged code: 168 tests and 16 of 16
sections after 9469e58; 182 tests and 18 of 18 sections after 7e4323a; 206 tests after 8dbd200; 218 tests and 21
of 21 sections after 4d9d755; 231 tests and 23 of 23 sections after the research handover's phase 0; 260 tests after
Gödel method wave 1 (dd7840e), and every workstream branch passed a full verify before it merged.
