# The Gödel method research program

The program comes from the Claude Doc "The Gödel Method: Research and Development Handover" (2026-10-22). Its ids
(Def-, Rule-, Cap-, Ph-, GM- and W-) are cited by every result here. The user's words, relayed by the Ting session
and checked in its transcript: "Yes, send the Gödel method handover to the card-model session and have it start the
wave-1 workstreams (W-1, W-2, W-3, W-5, W-12, W-15) under its coordination rules."

The proposed laws GM-1 to GM-9 are proposals: adopting one needs the user's yes, GM-2 in particular because it amends
CM43. Wave 1 produces evidence, not law changes.

## Coordination rules (from the handover)

1. This session is the only writer of `cards/godel/_pack_ledger.jsonl`. Workstreams propose atoms as proposal cards
   with their evidence, and this session mints them.
2. One branch per workstream, `claude/godel-w<n>-<slug>`; it merges after `cardmodel verify` passes.
3. Results are cards (`cards/finding`), each citing the ids it tests or builds and stating its tier.
4. `~/Documents/Claude_Hub` and `~/Documents/Pheros_Studio` stay read-only; their Python runs only with `python3 -B`.
5. Each workstream keeps its project card current with every commit (CM41): `cards/project/godel_w*`.
6. Wave 2 (W-4, W-10, W-11, W-13, W-16) waits for wave 1; wave 3 (W-6 to W-9, W-14) waits for W-4's Gödel record.

## Wave 1

The workstreams run in this session one after another, each on its own branch (parallel sessions would compete for
memory on this machine, and a session started by another session's message cannot start sessions itself).

| W | question | branch | status |
|---|---|---|---|
| W-15 | which of the product's questions are decidable? | `claude/godel-w15-difficulty` | started |
| W-3 | which code should identify a card? | `claude/godel-w3-identity` | waiting |
| W-5 | what makes a numbering admissible in each domain? | `claude/godel-w5-numberings` | waiting |
| W-1 | can every 1931 definition run as a card? | `claude/godel-w1-definitions` | waiting |
| W-12 | can instruction terms become polynomial constraints over a prime field? | `claude/godel-w12-arithmetized` | waiting |
| W-2 | can the content algebra and carry-over be kernel-checked on Mathlib? | `claude/godel-w2-mathlib` | blocked: the Mathlib and Foundation downloads need the user's yes |

The parts of W-2 that need no download are already on main: `formal/GodelCore` proves Rule-19, Rule-20 and the
freeness behind GM-3 in plain Lean (T1 to T4 of the research handover).

## Results

Each workstream adds its section here when it merges.
