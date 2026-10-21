# The cycle: the model running, checking and improving itself as one unit

The model has many parts: the kernel and its laws, the witnesses (`verify`), the learning loop, the language
cards and their conformance matrix, verified optimisation (`improve`, the arena), the goals, the machines and the
arcade with its store. Before the cycle each part ran when someone remembered to run it. Now one bounded loop runs
them all together, keeps the evidence, compares it with the last run and says what got worse, what is weak and
what to do next (law **CM38**). The core the model must never lose is a ledger that every `verify` and every cycle
checks (law **CM37**). The store is part of the loop: every game it lists must launch through it (law **CM39**).

```bash
./bin/cardmodel cycle run                      # the standard profile (about 5 minutes on this Mac)
```

```bash
./bin/cardmodel cycle report                   # the last weakness report
```

```bash
./bin/cardmodel cycle status                   # recent cycles, a running one, when the next automatic one is due
```

```bash
./bin/cardmodel cycle run --profile full --record   # everything, the unit tests included; write lasting evidence
```

## 1. When it runs

* **Whenever the model is used.** After any `cardmodel` command, the CLI checks whether a cycle is due and, if so,
  starts `cardmodel cycle run --auto` in the background (detached, at a lower priority, its output in
  `state/cycle/auto.log`) and returns at once. A cycle is due when the last automatic start is at least
  `auto.min_interval_s` old (an hour); the background run itself returns at once when nothing changed since the
  last completed cycle (a fingerprint of the code, cards, stdlib, tests, examples and arena) and that cycle is
  younger than `auto.max_interval_s` (a day).
* It does **not** start: in a cardmodel process started by another cardmodel process; while another cycle runs
  anywhere on the machine; with less than `auto.min_free_mb` (3 GB) free or a load above `auto.max_load_per_cpu`
  per CPU; for the commands in `auto.skip_commands` (the emulator, the arcade service, the REPL, the cycle itself);
  in a linked git worktree unless `CARDMODEL_AUTO_CYCLE=1`; with `CARDMODEL_AUTO_CYCLE=0` or after
  `cardmodel cycle auto off`. The tests set `CARDMODEL_AUTO_CYCLE=0`.
* On a terminal, the next command prints one line when the last cycle found critical or high problems.
* **On a schedule**, if you want it: `cardmodel cycle schedule` prints a launchd agent (macOS) that runs a profile
  every N hours or at a time of day; `--install` loads it, `--uninstall` removes it. Elsewhere it prints a cron line.
  Nothing is installed unless asked.

## 2. What one cycle runs

The profiles, budgets and settings are a card, `cards/cycle/default` (edit the card to change them).

| stage | what it does | quick | standard | full |
|---|---|:---:|:---:|:---:|
| `core` | the core ledger: nothing lost, changed or weakened (CM37) | ✓ | ✓ | ✓ |
| `verify` | every witness: verify's quick sections or all of them, per section, with the details the report needs | quick | all | all |
| `laws` | the witness test of every law card, in a child process with the cycle's seed (CM20) | | ✓ | ✓ |
| `learn` | the model observing its own code (named fraction, unnamed calls, liftable functions); the learning loop on the card's targets; what each language card can and cannot express yet | | ✓ | ✓ |
| `optimize` | a seeded arena (soundness, recall, speed) and the cost anchors measured on this host | | ✓ | ✓ |
| `store` | every catalogue item launched through the arcade's store (CM39); full also compiles the launcher | ✓ | ✓ | ✓ |
| `goals` | every goal card's metric against its target | ✓ | ✓ | ✓ |
| `docs` | LAWS.md, GOALS.md, COVERAGE.md and the arcade inventory against the cards | ✓ | ✓ | ✓ |
| `tests` | the whole unit suite, test by test | | | ✓ |

Every stage runs under the resource governor (CM30): children take the machine-wide slots and memory caps, the
cycle's own process stops with `MemoryBudget` before the machine runs short, the remaining budget caps each
child's timeout, and one cycle at a time runs per machine (a lock in the system's temporary folder). Every stage
also has a deadline (the remaining budget, or `stage_limits_s` in the card when shorter): a stage that does not
return in time is interrupted, its child processes are killed, and it is recorded as an error. A stage that
raises is recorded as an error and the next stage still runs; a `MemoryBudget` stops the cycle.

## 3. Self-learning, across languages

* **Its own code.** Each cycle observes `cardmodel/` (the model's own source) and records the named fraction, the
  most frequent calls no card names, and the functions that lift into the IR. The `named_fraction` goal (G_U3)
  reads the newest of this and the last observation card. Learning call names from its own helpers would only
  flatter that number, so the cycle never promotes the model's own calls into the model; it reports how many the
  loop would promote.
* **Other code.** The learning loop runs on the card's targets (`examples`, `arena/slowframework`): in a sandbox
  project under `state/cycle/sandbox` unless the cycle records, and with `--record` it promotes function cards
  with evidence (faithful lift, ≥ 3 agreeing implementations) into the model, never rewriting cards it already has.
* **Other languages.** Verify's conformance matrix and function cards are the model's knowledge of the languages:
  the report lists, per language card, which op templates are declared unsupported (what that language cannot
  express in the model yet) and which languages have no toolchain on this machine.

## 4. Self-optimisation

The `optimize` stage runs a seeded arena (generated programs with planted slow functions and decoys, improved and
re-checked) and measures the op cards' Python forms against their cost anchors. An unsound arena run is a
critical finding; a planted function not improved and an anchor the measurement contradicts are findings with the
command that would address them. Arena runs and measurements stay in the cycle's state (no card per run).

## 5. The core ledger (CM37)

`cards/ledger/core` names every law (a hash of its statement and its witness test), every goal (metric, direction,
target), every registry, every command with its actions, and every verify section. `verify` (section `ledger`, in
the quick set too) and every cycle fail when one is **lost**, **changed** or a goal **weakened** (its target moved
the easy way). Growth (a new law, goal, command) passes and is recorded.

```bash
./bin/cardmodel cycle ledger                                        # what is protected, what changed
```

```bash
./bin/cardmodel cycle ledger --accept --reason "why this law changed"   # a deliberate change, with its reason
```

`--accept` archives the previous ledger (CM14) and appends one amendment per lost, changed or weakened item with
the reason; `--additions` accepts growth only (a recording cycle does that by itself). A loss always needs a
person and a reason.

## 6. The weakness report

`state/cycle/report.md` (and `WEAKNESSES.md` when recording or with `--write`) lists, most severe first:

* **critical**: a lost or changed core item, a law whose witness fails or is missing, an unsound optimisation;
* **high**: a failing verify section, test or stage, a store item that does not launch, a regression;
* **medium**: vacuous witnesses (a check that ran on nothing, CM07), unmet goals with what would move them, a
  number that slipped against the last run, stale LAWS.md or GOALS.md;
* **low**: goals not measured in this checkout (machine evidence lives outside the model), languages without a
  toolchain, language gaps, contradicted cost anchors, stale generated documents;
* **better since the last run**, **strengths** (what passes, with numbers), the **next actions** the cycle chooses
  (deduplicated, most severe first, marked when the cycle runs them itself while recording), and **where
  development falls short**: every engine's own declared limits and the ROADMAP's open items.

A critical or high finding makes the cycle fail (exit status 1). Regressions compare each stage, verify section,
goal, law witness, test and store item with the previous run; seeded counts are compared only where the metric is
deterministic.

## 7. What a cycle writes

* Always: `state/cycle/` (`last.json`, `runs/` with the last 30 runs, `history.jsonl`, `report.md`, `auto.json`)
  and the numbers the goals read (`state/cycle_summary.json`, `state/cycle_self_observation.json`). State is a
  cache and is never committed.
* `--record`: ledger growth, learned function cards from the targets, LAWS.md / COVERAGE.md / the arcade inventory
  when they drifted, and `WEAKNESSES.md`. `--record-verdicts` also writes verify's per-card verdicts (as
  `verify --record` does; that rewrites a few hundred cards per run).
* `--commit` (with `--record`): one local commit of exactly what the cycle changed under `cards/`, `docs/` and the
  generated top-level documents, and only when the tree was clean before the cycle started, so nobody's work is
  swept in. Nothing is ever pushed.

## 8. Honest limits

* A stage's deadline is a timer signal: it interrupts Python code, not one long operation inside C (a single huge
  integer operation finishes first), and it needs the main thread.
* "Nothing changed" is a fingerprint of file sizes and times; an edit that keeps both is seen after a day.
* The ledger sees names, statements and targets, not behaviour; the `laws` stage runs every witness for that.
* Regressions are against the previous run only, not a trend; `cardmodel cycle status` and `history.jsonl` show the
  trend.
* The background cycle runs at a lower priority but still uses CPU and memory while you work: turn it off with
  `cardmodel cycle auto off` or `CARDMODEL_AUTO_CYCLE=0`.
