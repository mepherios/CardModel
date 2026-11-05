# Autonomy: the model runs itself, keeps its core, and says where it falls short

Three laws (LAWS.md):

* **CM37 the core is never lost.** The model's core features are `capability` cards. Each names the laws it
  carries, a smoke check of the real engine (`cardmodel/engines/capabilities.py`), its witness tests and its
  docs. Every `cardmodel verify` and every self-run runs the checks. Every law is carried by at least one
  capability, so no law is only words. The table of capabilities is generated into LAWS.md.
* **CM38 the model runs itself.** Using the model runs the model: any command can start a background cycle
  that checks, learns, optimizes and measures, then turns the results into strengths, weaknesses and flaws and
  ranks what to improve next.
* **CM39 one program.** Parallel work lands as one program: unique numbers, everything carried and described,
  generated docs in sync (docs/INTEGRATION.md has the procedure and the log).

```bash
./bin/cardmodel self run                       # one cycle now, in the foreground (steps that are due)
```

```bash
./bin/cardmodel self run --force               # every step, due or not
```

```bash
./bin/cardmodel self report                    # the last cycle: next steps, flaws, weaknesses, strengths, goals
```

```bash
./bin/cardmodel self status                    # auto on/off, last cycle, what is due, the top of the plan
```

```bash
./bin/cardmodel self capabilities              # the core capability checks alone (also: verify --only capabilities)
```

## 1. When it runs

* **On use.** Every command except the self-maintenance ones (`self`, `verify`, `cover`, `docs`, `learn`,
  `laws`, `arena`, `optimize`, `improve`, `lean`, `clean`) calls `selfrun.maybe_start`. A cycle starts when
  `CARDMODEL_SELF` is not `0`, automatic cycles are on (`cardmodel self auto on|off`, kept in
  `state/self/config.json`) and the last automatic start was more than `interval_hours` ago (6 by default).
  The command you ran is never delayed: the cycle is a detached process.
* **Bounded** (CM30). The cycle runs in the background (macOS background QoS through `taskpolicy -b`, niceness
  15). Its own subprocesses get one machine-wide slot (`CARDMODEL_MAX_PARALLEL=1`) and the process stops itself
  past 2 GB (`CARDMODEL_SELF_MB=2048`). No cycle starts while available memory is under twice the governor's
  floor. A cycle stops early when memory runs short or its time budget (45 minutes) is spent, and lists the
  steps it left.
* **One at a time.** A lock (`state/self/run.lock`) means a second cycle reports `busy` and does nothing.
* **Off switches.** `CARDMODEL_SELF=0` turns off the self layer and automatic cycles for that process and its
  children. The test helpers set it, so tests see only the model's tracked cards. `cardmodel self auto off`
  keeps the self layer but stops automatic cycles.

## 2. The cycle

The steps are `self_step` cards (cards/self_step). Each names its function in `engines/selfrun.py` and when it
is due:

| step | due | what it does |
|---|---|---|
| capabilities | every cycle | the core capability smoke checks (CM37) |
| integrity | every cycle | one program: unique law and goal numbers, every law carried, commands, sections and docs described, LAWS.md and GOALS.md in sync, no merge markers, no publishing calls (CM39) |
| verify | every cycle | `verify --quick`; never overwrites `state/last_verify.json` with a partial record |
| verify_full | every 24 h | every section, the toolchain-heavy ones too; replaces the quick run when both are due and writes `last_verify.json` |
| learn | every cycle, per changed tree | learns from source trees: the model's `examples/`, the arena's slow framework and the corpora you add (`cardmodel self corpus add PATH`). It observes code in every recognised language (which constructs are named cards, which are fallbacks, and the calls each language makes), lifts Python functions into function cards checked in every language this host runs, and promotes only what has evidence. A tree is re-learned only when its files change. Lifting other languages' functions waits on their frontends (HANDOVER.md section 8) |
| laws | when the op cards change | rediscovers laws (witness, Lean, simplifying rules) |
| algebra | when the algorithm cards change | canonical forms, Gödel numbers and identities between algorithms |
| arena | every 24 h | a small arena run: is the optimizer sound, what fraction of planted slow functions does it fix, how much faster |
| law_witnesses | every 24 h | every law card's witness test, run test by test in a child process with the cycle's seed: a law whose witness fails is a critical flaw (CM20; goal G_A10) |
| observe_self | every cycle | the model observes its own code (`cardmodel/`); a new observation goes to the self layer, so the named-fraction goal (G_U3) measures the code it is made of, not a corpus it learned from |
| store | every cycle | every catalogue item launched through the store exactly as the launcher does it: a download with every chunk checked, verify, a damaged file repaired, a native headless run that draws a frame (CM42, goal G_S1; `cardmodel arcade check`) |
| optimize | every 168 h | measures the op cards' forms on this host (metric cards); flags cost anchors that measurement contradicts |
| tests | every 168 h | the whole unit suite, test by test, in a child process; a failing test is a flaw |
| goals | every cycle | every goal from the latest result of each verify section, against the previous cycle |

A step that watches registries records a baseline the first time it sees them, and runs when they change. Every
step runs under a deadline (what is left of the cycle's budget, `resources.deadline`): a step that does not return
is stopped and reported as crashed, and the cycle goes on.

## 3. What a cycle produces

* **Findings**: each is a *flaw* (something is broken), a *weakness* (something falls short) or a *strength*.
  Each has a severity, its evidence and the command that acts on it. Sources: lost capabilities (critical),
  failing verify sections (critical), integrity problems, skipped or vacuous sections (a missing toolchain is
  named), unmet and unmeasured goals (by the size of the gap), goals that stopped being met since the last cycle and unmet ones that got worse,
  crashed steps, an unsound arena run, cost anchors that measurements contradict, proposals that lack evidence,
  and things outside the repository that depend on it (for example, an installed launcher that runs another
  checkout).
* **The plan** (self-determinism): non-strength findings ranked by severity, flaws before weaknesses. The top
  of the plan is what to improve next.
* **The trend**: goals that reached their target, stopped being met, or (while unmet) moved closer or further, against the previous cycle. A move that stays within a met target is not reported: seeds and timings vary between cycles.
* **The record**: `state/self/last.json` and `state/self/runs/*.json` (the last 60 cycles), and
  `state/self/SELF.md` (`cardmodel self report`; `--write SELF.md` snapshots it into the repository for a
  commit).

## 4. Where learning goes: the self layer

Everything a cycle learns (promoted cards, rediscovered laws and rules, identities, arena runs, metrics) is
written to the **self layer**, `state/self/cards`. It is untracked: background cycles never change files that
git tracks, so they cannot collide with anyone's commit. Every command loads the self layer read-only above
the model's cards, so every use benefits from what was learned. Only a cycle writes it.

* **Quarantine** (CM22). When verify fails with the self layer but passes without it, the learned cards are the
  cause. The whole layer moves to `state/self/quarantine/<time>/` with the failing sections, and the cycle reports
  a flaw.
* **Adopt.** `cardmodel self adopt [--dry-run]` moves the self layer into `cards/` (versioned saves; packs
  replaced whole) so a session can review and commit it (docs/INTEGRATION.md). The adopted copy is kept in
  `state/self/adopted/<time>/`.

## 5. Extending it

* **A new core capability**: add the card in `tools/seed_self.py` (laws it carries, tests, docs), a check
  function in `CHECKS` (`engines/capabilities.py`), and its name to `CORE` in `tests/test_self.py`. Then run
  `python3 -B tools/seed_self.py` and `cardmodel docs`. A check must run the real engine on a small fixed
  example, finish in seconds, write nothing tracked, and raise `Unavailable` (never pass) when the host
  lacks what it needs.
* **A new law**: take the next free number from docs/INTEGRATION.md and give the law a witness test. A
  capability must carry it: the integrity check and the self theory (`stdlib/self.card`) both fail until one
  does.
* **A new step**: a `self_step` card (order, `every_hours` and/or `on_change`) and a function in `STEPS`.

## 6. In the cloud

The same cycle runs on GitHub's runners, with every target language's toolchain installed
(`.github/actions/toolchains`, which uses `tools/install_toolchains.sh` for Lua 5.4 and the Lean pinned in
`formal/lean-toolchain`).

* **CI** (`.github/workflows/ci.yml`, pull requests, pushes to main and on demand): `verify --quick` on the
  oldest and newest supported Python; then, once a pull request is ready for review (drafts skip it), with every
  toolchain, `tools/require_toolchains.py` (every codegen language must be
  runnable, so no check passes because a language was skipped), `docs --check`, the full `verify`,
  `translate examples/algorithms/algos.py`, the `examples/lang` programs and the unit suite with
  `CARDMODEL_SLOW=1`. CI sets `CARDMODEL_SELF=0`: it checks the tracked cards only.
* **The scheduled cycle** (`.github/workflows/self-optimize.yml`, weekly on Mondays and on demand): `self run --force`, then
  `self adopt`, `docs`, `cover --write COVERAGE.md`. When `cards/` changed and the adopted cards pass `verify`,
  `docs --check` and the unit suite, it opens (or updates) one pull request from the branch
  `self-optimize/cycle` with the cycle's report as its body. Merging it is a person's decision. The program
  itself still never publishes (CM19): the workflow opens the pull request, not `cardmodel`.
* **Claude cloud sessions**: the environment's setup script runs `pip install -e .` and
  `tools/install_toolchains.sh`, and turns automatic cycles off (a session is short-lived; run `self run`
  explicitly).

## 7. Honest limits

* The plan ranks by rules written in `selfrun.findings` (severity, kind, the size of a goal's gap), not by a
  learned model of what matters.
* Learning promotes cards with evidence. It never edits the program's code. Improving the code is still
  development work, which the plan points at.
* A smoke check is a canary: it shows a capability is present and behaves on its example. The witness tests and
  verify sections go deep.
* Automatic cycles need some command to be used. Nothing runs while the model is not used, by design: there is
  no daemon.
