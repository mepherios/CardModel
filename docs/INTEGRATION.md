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
   ROM folders). ROM bytes, firmware and keys are never copied into the repository.

## 2. Number registry

A law's number is its identity (LAWS.md is generated from the cards). Take the next free number here, and add the
range to this table in the same commit.

| laws | owner | what |
|---|---|---|
| CM01–CM31 | main | the consolidation, the knowledge layer, the card language, the game design, resources, function algebra |
| CM32–CM35 | games (`claude/sad-sanderson-482207`) | machines are cards; lifted code is the cards; emulation effects are the shell; games are cards |
| CM36 | AnyPS5 (`claude/recursing-williams-ecc80a`) | unknowns are observation obligations (merged as CM32, renumbered CM36 at integration) |
| CM37–CM39 | main (self-run) | the core is never lost; the model runs itself; one program |
| CM40 | games (`claude/sad-sanderson-482207`, from the OAM session's cartridge work) | players are cards (`CM36_players_are_cards` on `claude/festive-margulis-43fde7`, renumbered when the games branch merges it) |
| CM41 | main | projects keep their cards current |
| CM42 | self-running-improvement (`claude/jolly-liskov-2d97a8`), announced | the store runs what it lists |
| CM43 | main (MATH_CORE phase 0) | primes are forever |
| CM44 | main (MATH_CORE phase 1) | everything traces back to the four sources |
| **CM45 onward** | free | take the next one |

Goal ids are `G_<axis letter><n>`. Taken: G_C1–C5, G_U1–U7, G_L1, G_O1–O4, G_A1–A9, G_K1–K6, G_D1–D2, G_P1–P5
(AnyPS5), G_M1–M5 (machines); reserved: G_M6 (main, MATH_CORE), G_S1 (self-running-improvement). The next free one is the axis's next number (G_A10, G_U8, G_C6, G_K7, G_M6, G_P6 ...).

Two sessions that take the same number find out at the merge: `cardmodel verify --only integrity` reports
"law number CMnn is used twice". The branch that merges second renumbers (rule 3). On 2026-10-21 this happened
twice: AnyPS5's CM32 became CM36, and the uncommitted work on `claude/jolly-liskov-2d97a8` used CM37–CM39 and
G_A4–G_A6. That session was told to move to CM41+ and G_A8+.

Verify sections (`engines/verify.py` SECTIONS; each is described in its docstring): kernel, integrity,
capabilities, logic, lang, theorems, game (main); anyps5 (AnyPS5); machine (games); forms, vectors, rules,
redefinitions, conformance, functions, proofs, selfcheck, portability (main).

## 3. Who works where

| session | branch / worktree | area (files it owns) | on main |
|---|---|---|---|
| integrating session | `main`, the repository folder | kernel, engines, lang, emit, game, docs, the self-run (`engines/selfrun.py`, `capabilities.py`, `integrity.py`) | — |
| cardmodel-games | `claude/sad-sanderson-482207` | `cardmodel/machine`, `cardmodel/arcade`, `cards/{isa,hardware,machine,app,game,platform,asset}`, docs/MACHINES.md, docs/ARCADE.md, tests/test_machine.py, tests/test_arcade.py | up to 032dc88 (merge ab76427); still active (a Game Boy Player store entry) |
| cardmodel-anyps5 | `claude/recursing-williams-ecc80a` | `cardmodel/anyps5`, `stdlib/ps5_*.card`, `cards/anyps5_*`, docs/ANYPS5*.md, tests/test_anyps.py, tools/seed_anyps5.py | up to 10c688f (merge 65a059c) |
| model-the-dmg-oam-corrup | `claude/festive-margulis-43fde7` | the DMG OAM corruption bug (machine and hardware cards), then cartridges and players (538f29c) | d4fb3c9 (merge 9469e58); 538f29c goes to main through the games branch |
| game-boy-cgb-dmg-compati | `claude/strange-dewdney-f8f39d` | the CGB's DMG compatibility mode | 05178e1 (merge 7e4323a) |
| self-running-improvement | `claude/jolly-liskov-2d97a8` | the same request as main's self-run, built in parallel (`cardmodel/cycle`, store inventory and launch checks); asked to build on `cardmodel self` | nothing yet (uncommitted when main's self-run landed) |
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

Each merge was followed by the full test suite and a full verify on the merged code: 168 tests and 16 of 16
sections after 9469e58; 182 tests and 18 of 18 sections after 7e4323a.
