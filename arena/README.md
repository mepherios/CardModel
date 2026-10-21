# arena — a test environment for optimization

Two subjects, one method (`cardmodel improve`, see docs/METHODOLOGY.md):

* `slowframework/`: a hand-written, deliberately suboptimal mini game framework.
  * `mathx.py` and `game.py`: pure game math, written slowly on purpose.
  * `online.py`: the effect shell (login, sockets, signed session messages). It must stay byte-identical.
  * `app.py`: wiring; module-level code is never executed by the optimizer.

  Optimize it with:

  ```bash
  cardmodel improve arena/slowframework --out arena/slowframework_optimized
  ```

  The output holds the optimized modules (same API), per-file reports and native translations of every pure
  function in every language card.
* **generated programs** of any size, with planted slow functions, look-alike decoys, already-optimal code,
  rewrite candidates and effectful functions:

  ```bash
  cardmodel arena --count 300 --seed 777 --out /tmp/arena300
  ```

  Every run is recorded as `cards/arena_run/arena_<seed>_<count>` and scored on three things.
  * **soundness** (all must hold): the end-to-end recheck passes, the effect shell is identical, no decoy
    is substituted, and the shell is preserved;
  * **recall**: planted functions improved;
  * **speed**: geometric-mean measured speedup.
