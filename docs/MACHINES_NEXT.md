# Machines: what to do next

Options for the machine and emulation track, as of 2026-11-05. Sources: docs/MACHINES.md, HANDOVER.md §8
item 5, GODEL_AUDIT §6 step 6 and the `machine/symbolic.py` row, and the PRs #55 (pipeline registry), #60
(lifter sorts), #67 (ARM symbolic), #78 (ARM symbolic memory, open) and #79 (ARM symbolic loops, open).
Each item gives what it is, its cost, what it unlocks and how it is measured. **Recommendation** marks the
ones this document suggests doing; the rest are options.

## Where things stand

| Track | Measured now | Source |
|---|---|---|
| Lifter sorts (LR35902) | masks 138 → 102 on `busy_rom`, 30 frames; the 102 left are needed (SP ± 1 at u16, int locals) | #60 (merged) |
| ARM symbolic terms | 0 → 92/167 pass, 0 fail, 75 unsupported | #67 |
| ... with memory effects | 156/167 pass, 0 fail, 11 unsupported (5 symbolic `banked[]`, 6 loops) | #78 (open, stacks on #67) |
| ... with loops and guarded `banked[]` | 98/167 alone; its 6 loop cards then wait only on #78's effects | #79 (open, stacks on #67) |
| Pipeline registry | 34 of 34 capabilities run, 1 in part: emulation's lifted engine runs on no cartridge (G_A13 = 1) | #55 |
| Game Boy / Color | every runnable hardware test passes; DMG mode uses the default palette only | MACHINES.md §8 |
| DS | Pokemon Diamond plays; ARM lifting covers ARM-state ARM9 code only | MACHINES.md §6, §8 |

## 1. Finish ARM symbolic (167 cards)

#67 left three classes. #78 and #79 cover them between them, but each was measured without the other.

| Class (after #67) | Cards | Option | Cost | Status |
|---|---|---|---|---|
| bus/memory effects (`bus_effect` stubs rd16/rd32/wr16/wr32/swi/undefined_op/cp_*, plus rd8/wr8 not evaluated) | 63 | make the stubs `EFFECTS` with read sorts; evaluate on a mirrored memory the way the bench does; compare the bus trace in order | done on #78 | review and merge |
| symbolic-index `banked[]` stores (MSR, S with Rd=15) | 6 | (a) guarded write to every cell, select on load (#79); (b) enumerate CPU modes and split paths | (a) done on #79; (b) more paths, no gain | (a) |
| loops (LDM/STM/PUSH/POP/LDMIA/STMIA) | 6 | (a) unroll when the bound folds to a constant under the bound `op`, max 64 (#79); (b) a loop term with an invariant | (a) done; (b) large, only needed for a symbolic bound, which no card has | (a) |

* **Recommendation**: merge #67, then #78, then rebase #79 on both and measure the combined result with the
  same seed and samples. Expected 167/167 pass, 0 fail (156 + 5 banked + 6 loops); anything short of that is a
  new class to list. Cost: one rebase (both touch `Executor` statement handling in `symbolic.py`) and a test run
  (`python3 -B -m unittest test_symbolic test_machine`).
* Then raise the sample count past 3: a card's unsupported/pass split depends on which words are sampled (#67).
  Cost: test time only. Measurement: pass/fail/unsupported at 3 and at e.g. 32 samples.
* Unlocks: every ARM card has a term, so it can get a definition with an identity (next section) and the
  ARM lifter's blocks can be checked against terms as the LR35902's are.

## 2. ARM ledger atoms (owner decision)

The ARM cards' terms use effects that are not ledger atoms: rd16, rd32, wr16, wr32, swi, undefined_op,
cp_read, cp_write (GODEL_AUDIT, `machine/symbolic.py` row). Without them the 167 ARM cards have terms but no
stored definitions with a Gödel identity (0 today).

* What: mint the eight atoms (ledger appends), then store ARM definitions the way the LR35902's 512 are.
* Cost: small in code; the decision is the cost: ledger appends are permanent, and minting is the ledger
  writer's call (GODEL_METHOD rule 1; GODEL_AUDIT §6 lists "minting the `LEAN_*` and ARM atoms" for the
  restructure thread).
* Alternative: define rd16/rd32 as compositions of rd8 (rd16 → rd8², rd32 → rd8⁴) and mint only swi,
  undefined_op, cp_read, cp_write. Fewer atoms, but it fixes a byte order and an access width into the term,
  and the DS bus is not byte-composed for every region (palettes and OAM drop byte writes), so the terms would
  no longer match the hardware's bus trace that #78 compares.
* **Recommendation**: mint all eight as atoms, after §1 lands, so the atom set is the one the checked terms
  actually use. This needs the owner's go-ahead.
* Unlocks: 167 ARM definitions, families and identities (the LR35902 gives 512 → 495 identities → 190
  families); the carry in §3. Measurement: definitions stored, distinct identities, families.

## 3. LR35902 → ARM carry and its gap (GODEL_AUDIT §6 step 6)

* What: a carry map from the LR35902's effect atoms to the ARM's. The audit computes it: image {rd8, wr8}; gap
  {idle, idu, rd8_idu, halt, stop, hang, cb_dispatch}; the B0 ops carry by identity. The other direction
  (ARM → GB with rd16 → rd8², rd32 → rd8⁴) shares support, so `preserves_gcd` is False and must be reported
  (T2), not hidden.
* Cost: moderate. Needs §2's atoms and the ISA-generic effects (read the effect names from the ISA interface
  card and the godel_set arities instead of the hard-coded Game Boy bus names in `symbolic.py`). Step 6 in the
  audit also bundles the `arith` memo per α-canonical term (430 s → 63 s) and the lifter's cross-ROM cache by
  structural identity; those are independent and can go first.
* Unlocks: the first carry between two machine ISAs, with its gap as data; a check that the GB families that
  carry land on ARM families with the same identity.
* Measurement: image size, gap size (7 expected), `preserves_gcd` in each direction, families carried.
* **Recommendation**: do the ISA-generic effects now (no owner decision needed, and §1's checker already
  wants them); the carry itself after §2.

## 4. Lifted engine in the pipeline (#55's one recorded gap)

* What: emulation's lifted engine runs on no cartridge in any pipeline stage (G_A13 = 1). Add a stage that
  lifts and runs a small ROM: the Game Boy `busy_rom` (already the #60 benchmark) or the DS `check_image`.
* Cost: small for the Game Boy (a few seconds; quick verify must stay quick), and the stage must reach the
  lifter's modules in `engines/pipeline.py`'s call graph (in PR #50; #55 also has one). A DS run costs more and belongs in full verify only.
* Unlocks: G_A13 → 0 (34 of 34 fully); the lifter's masks and its agreement with the interpreter become a
  checked number every cycle instead of a one-off.
* Measurement: G_A13; the stage's time; lifted vs interpreted state after N frames; `masks_removed`.
* **Recommendation**: do this first. It is the cheapest item here and closes a registered gap.

## 5. DS: the next pieces

The coverage report's order (HANDOVER §8 item 5). Several cards now exist (`nds_spi`, `nds_rtc`, `nds_vram`,
`nds_2d`, `nds_3d`), so what remains is their limits (MACHINES.md §8) and the lifter.

| Piece | What is left | Cost | Unlocks | Measurement |
|---|---|---|---|---|
| SPI | firmware flash is card data, no console's firmware; touch through calibration only | small | games that read more user settings | unmodelled registers touched, per game |
| RTC | alarms stored, not fired | small | games with alarms | same |
| VRAM | two banks on one page do not OR together | small to moderate (the page table holds one bank per page) | games that overlap banks | screen diffs |
| 2D engines | no display capture, no main-memory display FIFO; a line is drawn from the registers as they are at its start | moderate | capture effects (motion blur, 3D on both screens) | screen diffs on titles that use DISPCAPCNT |
| 3D | no edge marking, fog, anti-aliasing, shadow polygons, rear-plane bitmap, translucent Y-sort | moderate each | picture fidelity | screen diffs |
| Thumb lifting | ARM lifting covers ARM-state ARM9 code only; Thumb and the ARM7 are interpreted | moderate to large (a Thumb front end over the same cards; §1's terms check it) | speed on Thumb-heavy code and the ARM7 | `interpreted` share, frames/s |
| Cheaper word guards | guards read through the bus, so RAM code saves the decode, not the fetches | moderate | speed on RAM-resident code | frames/s on Pokemon Diamond (250-320 now) |

* **Recommendation**: Thumb lifting, after §1, since checked ARM/Thumb terms make it testable; the fidelity
  items as games need them, driven by the coverage report rather than by the list above.

## 6. Game Boy: per-title DMG palettes

* What: the boot ROM's compatibility palettes for Nintendo's DMG games in CGB mode, chosen by title checksum
  (and the disambiguation byte), plus the d-pad-selected ones during the logo, as card data (Pan Docs documents
  the selection).
* Cost: small: a table card and the selection in the boot path; the table is data from Pan Docs.
* Unlocks: colourised DMG games as on the console. Only if that is wanted: `--model auto` already runs a DMG
  cartridge on the DMG.
* Measurement: palette chosen per title against Pan Docs' table; a screenshot test for one title per palette.
* Option, not a recommendation: low cost, low value until Game Boy titles are store products.

## 7. Game Boy: survey failures

`cardmodel machine survey` lists them.

* Bank controllers MBC7, HuC3, camera now exist (MACHINES.md §8 names their limits). MMM01, MBC6, HuC1 and
  TAMA5 do not; none is in the surveyed collection. Cost per controller: small to moderate. Add one only when a
  collection needs it.
* The static and blank ones need a trace: `gb.GameBoy(ctx, rom).m.call("step")` and `.m.call("peek", addr)`.
  Cost: per title, unknown until traced.
* The two cheat devices cannot run from these files (MACHINES.md §8); they stay listed with the reason.
* **Recommendation**: re-run the survey on main, record the failure list with a reason per title, and trace
  the static/blank ones one by one. Measurement: titles running / total, failures by reason.

## Suggested order

1. §4 lifted engine in the pipeline (closes G_A13).
2. §1 merge #67, #78, #79 and measure 167/167.
3. §3's ISA-generic effects (no decision needed).
4. §2 ARM atoms (owner decision), then §3's carry.
5. §5 Thumb lifting; §7 survey; §6 and the DS fidelity items as needed.
