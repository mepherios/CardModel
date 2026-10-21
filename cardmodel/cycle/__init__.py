"""cycle — the model as one unit that runs, checks and improves itself (docs/CYCLE.md, laws CM37 and CM38).

* ``ledger``:  the core the model must never silently lose: every law, goal, registry, command and verify section,
               with the statement, witness or target each had (``cards/ledger/core``).
* ``stages``:  what one cycle runs: the core ledger, every witness (verify), every law's witness test, the
               learning loop on the model's own code and across the language cards, verified optimisation
               (arena, measured costs), the goals, the arcade's catalogue launched through its own store, the
               generated documents, and the whole test suite.
* ``report``:  the evidence turned into findings: regressions against the last run, failing and vacuous
               witnesses, unmet goals and what would move them, stale evidence, where development falls short,
               the strengths to lean on, and the next actions the cycle chooses for itself.
* ``run``:     one bounded cycle: a machine-wide lock, a time budget, the resource governor, state under
               ``state/cycle`` and, with ``--record``, the evidence written into the cards.
* ``hook``:    using the model starts a cycle in the background when one is due; a schedule (launchd/cron)
               can run the full profile.

The cycle's own settings are a card (``cards/cycle/default``): profiles, budgets, learning targets, intervals.
"""
