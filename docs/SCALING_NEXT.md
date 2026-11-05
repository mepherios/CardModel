# SCALING_NEXT: the next scalability options, after the first measurements

A proposal, written 2026-11-05 after the scale benchmark landed (#45). It builds on [SCALING.md](SCALING.md) (phases
S-A to S-D, principles §3, subsystems §4.x) and [GODEL_AUDIT.md](GODEL_AUDIT.md) (the decision rule §2 and the order
of work §6). Nothing here is adopted until it lands as its own PR with its measurement.

## 1. Where we stand (measured)

| what | measured | source |
|---|---|---|
| time per function | 518 / 572 / 931 µs at 10³ / 10⁴ / 10⁵ functions; slope 1.80 against G_A11 ≤ 2; nearly all in `lift` (469 → 860 µs) | #45, `cards/metric/scale__n*` |
| memory | about 20 KB per function, peak 1,988 MB at 10⁵; 10⁶ extrapolates to about 20 GB, so G_A12 (≤ 2 GiB) fails | #45 |
| lift rate (synthetic) | 0.86 without boundaries; 0.92 with opaque boundary cards | #45, #51 (merged), #52 (open) |
| loading the store | 3.5 s and 92 MiB to load every card; the lazy index (#18) serves lookups in about 0.2 s, but most global passes still enumerate and load everything | SCALING §2, §6 S-B |
| `verify`, `godel` section | 15–20 s; 0.06 s when cached by input hash | PR #54 |
| full unittest | about 15–40 min depending on host | local runs |
| resource budgets | per-environment budgets for cores, memory and wall time | #44 |
| CI minutes | a minute budget per run is proposed | #42 |
| identity-keyed work | dedup and memo by `semantic_hash`: e-graph saturation −32 %, 47 % fewer canonicalizations | GODEL_AUDIT §6 step 2 |

The shape: the per-unit work is close to flat, but memory grows with the whole project, every global pass still
loads everything, and the developer loop (tests, verify, CI) re-does work whose inputs did not change.

## 2. The options

Each option lists what it is, the gain with the measurement it rests on, the cost, the Gödel-purity verdict in the
GODEL_AUDIT §2 vocabulary, and the risk. The purity rule for all of them: where a cache, shard or route needs a
key, the key is the unit's `semantic_hash` (α-renamed, relation-tagged) or a hash of its inputs (**KEYED**); a key
never stands in for meaning, and nothing reads a value off a code (exclusion (i)).

### O1. Incremental `verify`, every section keyed by input hash

* **What.** Generalize PR #54: every `verify` section declares its inputs (cards, rules, tool versions), and its
  result card is keyed by the hash of those inputs (SCALING §3.4). A section whose key is unchanged is served from
  its result card.
* **Gain.** Measured on one section: `godel` 15–20 s → 0.06 s. Expected: a no-change `verify` in seconds; a change
  re-runs only the sections that read it.
* **Cost.** Small per section: an input declaration and a result card. A test that the key covers every input
  (change any input, the key changes).
* **Purity.** KEYED: input hash as cache key (audit (a), (d)). The verdict itself is still computed by the section.
* **Risk.** A missed input serves a stale result. Mitigate with a periodic uncached run (nightly) that compares.

### O2. Incremental test suite, keyed by input hash

* **What.** Each test module records the hashes of the source modules and card registries it imports or reads; a
  run skips modules whose input hash matches a passing result card. `--all` forces a full run.
* **Gain.** The full suite is 15–40 min. A typical one-module change touches a few test modules, so the expected
  loop is minutes. To measure: wall time of the suite on the last 20 merged PRs, full vs keyed.
* **Cost.** Medium: an import tracer (stdlib `sys.settrace` or `importlib` hook) and a result store per environment.
* **Purity.** KEYED (input hash). Test logic is unchanged (NO for the tests themselves: process and I/O, (ii)).
* **Risk.** Dynamic reads (files opened by name, environment variables) escape the tracer. Keep a full run in CI
  on merge to `main` and nightly.

### O3. Streaming global passes over the index (finish S-B)

* **What.** Every pass that today enumerates a registry (`ALL`) instead queries `kernel/index.py` and loads card
  bodies on demand; the logic engine evaluates per shard (SCALING §4.1).
* **Gain.** Store load 3.5 s / 92 MiB per command → near the index lookup (0.19–0.23 s measured with 10⁶ extra
  cards, #18). Memory bounded by the shard, not the store.
* **Cost.** Medium to large: one pass at a time, each with its own before/after measurement.
* **Purity.** KEYED: the index is keyed by name and `semantic_hash`; postings come in O5.
* **Risk.** Behaviour drift where a pass relied on iteration order. Merge results in a fixed order (SCALING §3.6).

### O4. Memory bound at 10⁵–10⁶: summaries instead of bodies

* **What.** `lift_project` keeps each function's summary card (signature, effects, gaps, `semantic_hash`) and spills
  the body to the content-addressed store once lifted; callers read summaries only (SCALING §3.1, §3.5). Lift
  per SCC in reverse topological order and drop each SCC's working set when done.
* **Gain.** Today 20 KB per function and 1,988 MB at 10⁵. Target G_A12: ≤ 2 GiB at 10⁶, i.e. ≤ 2 KB resident per
  function. The bench already records peak memory per size, so the gain is measured directly.
* **Cost.** Large: a summary type, a spill path, and SCC-ordered lifting.
* **Purity.** CORE for the summary composition (audit (e): module summary from function summaries); KEYED for the
  spill store (content address).
* **Risk.** Analyses that silently read bodies of callees. Make the body accessor raise inside a summary-only pass.

### O5. Store index with postings over identity (GODEL_AUDIT step 5)

* **What.** Index identity with relation, basis version and postings over resolved vectors; `list --identity /
  --divides / --similar`.
* **Gain.** 47× on divides today (audit §6); it is the S2 blocker for dedup at corpus scale.
* **Cost.** Medium; depends on steps 2 and 4 of the audit.
* **Purity.** KEYED and CORE (part-of queries, audit (b)).
* **Risk.** Basis version changes invalidate postings; key the postings by basis version so a change re-indexes.

### O6. Identity-keyed dedup and memo everywhere (GODEL_AUDIT step 2)

* **What.** One identity key; `egraph.canonical`, `improve.cheapest_rewrite`, `tiers` and `theorems` memoized by it;
  dedup of E, theorems and law candidates.
* **Gain.** Measured: saturation −32 %, 47 % fewer canonicalizations, 484 → 81 functions, 162 Lean proofs not
  repeated.
* **Cost.** Medium, already specified in the audit.
* **Purity.** KEYED via `semantic_hash`. Equality claims wait for canonical content (F4); the memo is safe before.
* **Risk.** A hash that is not α-invariant splits identical terms (loses gain, not correctness); a hash that
  conflates distinct terms is a correctness bug, so collisions are checked by structural equality on hit.

### O7. Parallel and sharded lift by module identity

* **What.** Split `lift_project` by module: each shard is a module (or an SCC of modules) keyed by its Merkle
  identity (`lift_project.identity`); a process pool lifts shards and merges cards in identity order (SCALING §3.6,
  §4.4). Callees across shards are read as summaries or opaque boundaries (#51, #52).
* **Gain.** `lift` is nearly all of the 931 µs per function at 10⁵. On 4 cores, expect close to 3–4× wall time
  in `lift`; on reruns, unchanged modules are skipped by identity. To measure: `scale bench` with `--workers 1,2,4`.
* **Cost.** Medium: pickling-free shard inputs (paths plus summaries), deterministic merge, the budget from #44 for
  the pool size.
* **Purity.** KEYED (shard and skip by identity, audit (d)); the lifting itself is NO (frontend, (ii)).
* **Risk.** Nondeterminism in merge order; the determinism goal (1 worker vs N workers: 0 differing cards) is the
  test. Memory multiplies by workers unless O4 lands first.

### O8. Self-run work queue keyed by identity (GODEL_AUDIT step 7, S-C)

* **What.** Self-run units are work cards keyed by identity; a cycle runs only units whose key changed; leases and
  checkpoints make an interrupted cycle resume.
* **Gain.** The cycle does only changed work (audit §6); combined with step 1 of the audit, −100 s per cycle is
  already measured.
* **Cost.** Large: the queue, leases, checkpoints.
* **Purity.** KEYED.
* **Risk.** Lease expiry under load; bounded by the per-unit budget (SCALING §3.7).

### O9. CI minute budget (#42)

* **What.** CI runs O2's keyed test selection and O1's keyed verify on pull requests, a full run on merge and
  nightly, and `scale bench` at 10³–10⁴ per PR with 10⁵ nightly. Each job records its minutes as a metric card
  against the budget in #42.
* **Gain.** From 15–40 min of tests per push toward minutes; the expected saving is the keyed-skip ratio measured
  in O2.
* **Cost.** Small once O1 and O2 exist.
* **Purity.** KEYED (by input hash) for selection; scheduling itself is NO ((ii)).
* **Risk.** A skipped test hides a regression until the nightly; the nightly full run bounds the delay to a day.

### O10. Budgets per unit (finish #44)

* **What.** Each unit (function, module, verify section) carries its own step, time and memory budget; an
  overrun is recorded with its cause and retried later (SCALING §3.7).
* **Gain.** No single pathological unit stalls a 10⁵ run; makes O7 and O8 safe.
* **Cost.** Small to medium.
* **Purity.** NO for the budget itself (a measurement, (v)); the result is KEYED by unit identity.
* **Risk.** Budgets too tight inflate the gap count; record gaps by cause so it is visible.

## 3. Recommended order

1. **O1 incremental verify** and **O2 incremental tests**: cheapest, already proven on one section (20 s → 0.06 s),
   and they speed up every later PR.
2. **O9 CI minute budget**, on top of O1 and O2.
3. **O6 identity dedup and memo** (audit step 2): measured gains, unblocks O5 and O8.
4. **O4 memory bound** before parallelism, because O7 multiplies resident memory by workers; target G_A12.
5. **O7 sharded lift by module identity**, with **O10 per-unit budgets**; target G_A11 held at 10⁶ and core use
   ≥ 0.8.
6. **O3 streaming passes** and **O5 postings** (finish S-B; audit step 5).
7. **O8 the identity-keyed work queue** (S-C; audit step 7).

Merge #52 (opaque callees) before O7 so that shard boundaries never fail a caller (lift rate 0.86 → 0.92).

## 4. What each step re-measures

Every step re-runs `cardmodel scale bench --record` and updates SCALING §2 and §6: time per function and slope,
peak memory per function, lift rate, and for the developer loop the wall time of `verify` and the test suite with
and without keys.
