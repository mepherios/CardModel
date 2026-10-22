# Machines as cards: Game Boy, Game Boy Color, and a Nintendo DS prototype

A CPU is its instruction cards. A console is its hardware cards. A ROM's own code is lifted into the same card
IR. Nothing else defines the machine: the emulator *is* the card model (law CM32). Live numbers (conformance,
the ROM survey, differential runs, DS coverage) are in `COVERAGE.md` and come from the commands below.

```bash
./bin/cardmodel emu "path/to/game.zip"                       # play in the browser: video, audio, keys, saves
```

```bash
./bin/cardmodel emu game.gbc --headless --frames 900 --input "300:start,306:-" --png shot.png --wav sound.wav
```

```bash
./bin/cardmodel isa check lr35902                            # every instruction card, every engine
```

```bash
./bin/cardmodel machine survey ~/Downloads/GB_GBC            # boot every ROM, classify honestly
```

```bash
./bin/cardmodel emu "path/to/dmg-game.zip" --model cgb       # a DMG game on the CGB, in DMG compatibility mode
```

```bash
./bin/cardmodel machine diff game.gb --frames 3000          # lifted code vs the interpreter, frame by frame
```

```bash
./bin/cardmodel machine testroms ~/Downloads/gb-test-suites   # Blargg, mooneye, acid2: their own verdicts
```

```bash
./bin/cardmodel machine nds "Pokemon Diamond.nds" --frames 300   # the DS prototype and its coverage
```

ROMs are read where they are (zips in memory). No ROM byte is ever copied into the repository; lifted code and
execution profiles live in the state cache (`state/emu/`, gitignored); saves go to `saves/` (gitignored) or
`--save-dir`.

## 1. The layers

| layer | cards | what it holds |
|---|---|---|
| ISA | `isa/lr35902`, `isa/armv5te` (kind `isa`) | registers, flag layout, decode structure, the semantic helper library (`core.card`) and the bus contract (`interface.card`) |
| instructions | `isa/_pack_lr35902.jsonl`, `isa/_pack_armv5te.jsonl` | one card per instruction: encoding, bytes, timing, flags as data, `semantics` (card language), `ir` (compiled), vectors |
| hardware | `hardware/gb_*`, `hardware/nds_*` | registers (addresses, read masks, post-boot values), timing constants, behaviour as card-language files next to card.json |
| machine | `machine/gameboy`, `machine/nds`, `machine/*_bench` | which ISA and hardware cards make the machine, its main loop, post-boot state, how the host talks to it |

Everything compiles into **one card-IR module** per machine (`cardmodel/machine/build.py`): globals, byte/int
arrays, functions. The instruction cards' stored IR is linked in; the interpreter's dispatch (`exec_op` for the
LR35902, mask-decoded `arm_exec`/`thumb_exec` tables for ARM) is generated from the cards.

### The IR and language extensions this needed

* IR (`engines/ir.py`, `engines/codegen.py`): module `globals` and `arrays`, `store`, `do` (a call as a
  statement), `switch`, `LOAD`, void functions; language cards gained the templates (C, Python) and an `embed`
  block that says how a host loads the module (`python`: exec in this process; `cabi`: a shared library through
  ctypes). Split compilation (`split_sources`) emits a big module as several compile units.
* Card language (`lang/`): `const` (which may read card fields: `card.<registry>.<name>.<field>`), `global`,
  `array`, `export`, array indexing and stores, call statements, `switch`. An **evaluation-order pass** gives
  every effectful call its own statement in Python's left-to-right order, so C (which leaves operand order
  unspecified) computes exactly what Python and the reference interpreter compute.

### Engines

| engine | what runs | use |
|---|---|---|
| `ir` | the reference interpreter over the module | the semantics; the bench's reference |
| `host` | the module emitted through the Python card | the interpreter fallback; slow |
| `native` | the module emitted through the C card, a shared library via ctypes | the interpreter, fast |
| `lifted` | `native` + the ROM's lifted blocks | the default for `cardmodel emu` |

No engine names a language: the choice is card data (`embed` blocks), checked by `tests/test_laws.py`.

## 2. Witnesses

* **Per-instruction conformance** (`machine/bench.py`, `verify --only machine`): every instruction card runs on
  its ISA's bench machine (flat memory, an access trace) with seeded random states, in every engine. The runs must
  agree; the card's `cycles` and `mcycles` must match the trace (LR35902: M-cycle bus activity with addresses);
  flags marked `-`, `0`, `1` (or ARM `S`) must hold; hand-derived `vectors` must hold. A planted wrong
  instruction is caught (CM07).
* **Synthetic ROMs** (`machine/asm.py`: an assembler made from the instruction cards' mnemonics): the tests build
  their own cartridges (serial output, graphics, MBC banking, battery RAM, V-blank handlers, EI;HALT) and a tiny
  two-CPU DS image, so no game is ever needed in the repository.
* **The ROM survey** (`machine/survey.py`): boot every ROM in a folder headless with a scripted input and
  classify: `runs` (drawn and changing), `static`, `blank`, `locked` (illegal opcode), and whether the bank
  controller is modelled. "Runs" is evidence of booting, not of correctness.
* **Differential runs** (`machine/diff.py`): lifted engine vs interpreter on the same input, state hash (registers,
  time, frame, WRAM, HRAM) compared after every frame (CM33).
* **Test ROMs** (`machine/testroms.py`): the freely licensed suites, read where they are (the user downloaded
  them outside the repository). Blargg's report over serial and at 0xA000; mooneye leaves 3 5 8 13 21 34 in
  B..L; dmg-acid2 and cgb-acid2 must draw their reference image pixel for pixel (DMG shades mapped through the
  PPU card's shade table). Each test runs on the model whose hardware revision its name gives (mooneye's
  `-dmgABC`, `-GS`, `-C`... against the machine card's `revisions`); a DMG cartridge for a CGB revision runs in
  the CGB's DMG compatibility mode, and a DMG screen test whose suite also has the CGB's picture (dmg-acid2's
  `reference-cgb.png`) runs on both models. A test for other hardware, or one that is not self-checking, is
  reported as skipped and not counted. So is a single ROM that cannot report on any
  accurate machine, with the evidence in the runner (`CANNOT_REPORT`): Blargg's oam_bug 7-timing_effect.gb logs
  about 10 KB of OAM dumps into 8 KiB of cartridge RAM and the overflow lands on its own code in WRAM; the same
  test passes inside the combined oam_bug.gb, and passes alone with the log switched off.

## 3. The Game Boy machine

* **Time**: `now` counts dots (4.194304 MHz); an M-cycle is 4 dots, 2 in CGB double speed. Components advance
  lazily and are synced before their registers or memory are touched, and at instruction boundaries once `now`
  passes `next_event`, the earliest dot at which any component can raise an interrupt (PPU: only the transitions
  that can interrupt; timer: the next overflow; serial; the frame deadline). The interpreter's behaviour is
  independent of how often components sync (tested by forcing extra syncs).
* **CPU**: the LR35902 cards; interrupt dispatch in 5 M-cycles with the vector chosen after the high push;
  HALT, the HALT bug (and its meeting with a dispatch after EI), EI's delay, STOP and the CGB speed switch.
* **Hardware**: memory map, MBC1/2/3 (+RTC)/5, timer (falling edges, the 4-cycle reload, DIV/TAC quirks), PPU
  (modes, STAT edge, LY=LYC, a scanline renderer with window, 10 sprites a line, DMG and CGB priority, CGB
  palettes and VRAM bank), OAM DMA and HDMA, joypad, serial (logged), APU (4 channels, frame sequencer, mixer,
  output capacitor).
* **Boot**: no boot ROM (it is not ours to ship); the documented post-boot state, DMG or CGB per the header; the
  CGB hands over in V-blank (games touch VRAM at once), the DMG at the start of line 0.
* **DMG compatibility mode**: a DMG cartridge (header byte 0x143 without bit 7) on the CGB model
  (`--model cgb`) runs as the CGB's boot ROM leaves it. KEY0 = 0x04 and OPRI = 1 (objects by X coordinate);
  the default compatibility palette is card data (`hardware/gb_cgb`, `dmg_compat.palettes`: BG 7FFF 1BEF 6180
  0000, OBJ0 = OBJ1 7FFF 421F 1CF2 0000), written to BG 0 and OBJ 0/1 the way the boot ROM writes it (BCPS left
  at 8, OCPS at 16); A=11 F=80 B=the title checksum (Nintendo-licensed cartridges, else 00) C=00 D=00 E=08,
  HL=007C (991A when B is 43 or 58); the system counter 0x2678; P1 reads 0xFF. The CGB-mode registers lock as
  each register's `dmg_compat` field says: KEY1, HDMA1-5, BCPD, OCPD, OPRI, SVBK and FF74 read 0xFF and ignore
  writes, VBK reads its bank (0) and ignores writes, BCPS, OCPS, FF72, FF73, FF75 and PCM12/34 work, and SC's
  fast-clock bit reads 1 as on the DMG. The PPU draws the DMG way (no attributes, VRAM bank 0, LCDC bit 0
  blanks the background) with BGP/OBP0/OBP1 picking colours of the CGB palettes. What stays the CGB's: the
  APU, the unusable FEA0-FEFF range, no OAM corruption bug, the hand-over in V-blank. In the cards `cgb` is the
  console and `cgb_mode` its CGB features (`cgb_boot_mode` in `hardware/gb_cgb`). `machine survey --model cgb`
  and `machine diff --model cgb` run a collection or a game this way: in the user's collection every DMG
  cartridge classifies as it does on the DMG, and the lifted code stays identical to the interpreter.
* **What the test suites pinned down** (each a card, each witnessed by the tests named in it): OAM DMA blocks
  OAM from its first transfer through the M-cycle of the last, and a restart keeps it blocked; a run of EIs
  enables IME after the second; a running CPU takes a PPU interrupt raised exactly at an instruction boundary at
  the next one; the CPU sees PPU mode changes a dot late (STAT, VRAM and OAM access), writes land later in their
  M-cycle than reads, the first line after LCD enable is 4 dots short and starts in mode 0; line 144 also raises
  the mode 2 STAT source; LY=LYC is held while the LCD is off; objects lengthen mode 3 by Pan Docs' rule; a TIMA
  write in the reload M-cycle is lost and a TMA write there is what TIMA gets; the serial clock is a bit of the
  system counter; the APU's length, sweep, power-off and wave-RAM quirks; MBC1 multicarts; P1 reads 0xCF after
  boot; the DMG's OAM corruption bug: during the OAM scan (dots 4-79 of a line, row = dot / 4), an OAM access or
  the IDU putting an address in FE00-FEFF on the bus (INC/DEC rr, PUSH, CALL, RST, LD A,(HL+/-), POP's reads)
  rewrites the scanned row from the one before by Pan Docs' write, read and read-increase patterns, and the
  unusable FEA0-FEFF range reads 0xFF and corrupts while OAM is blocked. The IDU is part of the LR35902 bus
  contract (`idu`, `rd8_idu` in `isa/lr35902/interface.card`). The CGB raises line 144's mode 2 STAT source one
  M-cycle (4 dots) before V-blank, the DMG with it (mooneye vblank_stat_intr-C and -GS). DMG compatibility
  mode's registers, I/O values and locks (boot_regs-cgb, boot_hwio-C, unused_hwio-C), its system counter
  (boot_div-cgbABCDE pins it to 0x2678-0x267B, one M-cycle) and its palette (dmg-acid2's CGB picture, pixel for
  pixel).

## 4. Lifting ROM code (REA-style, kept internal)

`machine/lift.py`. The interpreter records an execution profile (an opcode bitmap and an "entered other than by
falling through" bitmap). Leaders come from recursive descent through bank 0 from the vectors, the profile's
entries, and static successors. A **block** is one IR function made of its instruction cards' IR with every fetch
replaced by the byte it would read; it is then specialised:

1. inlining of the instruction semantics, the CPU helpers and the bus; a constant address goes through the
   machine's own bus logic and folds (an HRAM read becomes an array load);
2. constant propagation (immediates, PC, addresses) and folding of conditions;
3. register caching in locals when no remaining call reads them, written back at every exit;
4. dead code (flags overwritten before use).

A block runs whole only when it can finish before `next_event`, so nothing can raise an interrupt inside it
except the CPU's own writes; after any instruction that may move `next_event` it checks and leaves. **Every
instruction start is also lifted on its own** (`ins_K`: the instruction specialised to its bytes, then what the
interpreter does after every instruction, EI's delay counted down): a block whose next event is too close, a step
right after EI or once the frame is done, and an entry into the middle of a block (where an interrupt returns)
run these, one instruction per step; `run_block` switches over every instruction start, to the block it leads or
to the instruction. HALT, STOP and EI are only lifted on their own. **Code in RAM** (the OAM DMA routine every
game copies to HRAM, routines copied to work RAM) is lifted one instruction at a time from the bytes the profile
saw it run with (`ram_seen`, `ram_code`); each lifted RAM instruction first checks that RAM still holds those
bytes, and during OAM DMA that it is in HRAM, else the interpreter runs it (`run_ram`).

**Code found by reasoning** (`machine/absint.py`): recursive descent follows only jumps whose target is written in
the instruction, so a far call (a bank and an address in registers, a trampoline that switches the bank and jumps
through HL), a call after a bank switch and a jump table (an index into a table of addresses) are found only
when a profile saw them. The abstract run executes the machine's own cards from the start of every block that
ends in a call or a jump or holds a JP HL or a bank write: each instruction's card IR, through the bus and
cartridge cards (functions without loops run; the hardware's catch-up, with loops, is opaque), over values that
are constants or unknown, starting from the hardware as power-on leaves it. The ROM's bytes are constants, so are
the cartridge's bank registers once the code writes a constant to them, and memory the run wrote at constant
addresses; calls and returns use the run's own stack. A jump to a constant address in a known bank is a new
leader; at a JP HL, a table's entries are read word by word while each is the address of code. On Pokemon
Crystal it adds 1,163 leaders (916 far-call targets, 532 table entries) to the 10,301 its profile found, in
2.5 minutes. `arcade app` runs it once per cartridge.

So the ROM's code that was found runs as lifted card IR; the machine counts what still went through the
instruction-at-a-time interpreter (`interpreted`, `interpreted_ram`). Pokemon Crystal, after a 31,800-frame
profile (the survey's presses, then a seeded walk), on a run with another seed: 98.4 % of 15.6 million
instructions ran lifted, none from RAM through the interpreter, frame-identical to the interpreter.

Blocks are cached per ROM, machine and lifter version, emitted through the C card in per-bank parts, linked into
one library. The profile grows with each session (the shell saves the new entries at exit, and an app made for
one cartridge keeps them beside its save: docs/ARCADE.md section 5); a launch re-lifts when it grew enough.

## 5. The effect shell (CM21, CM34)

`machine/shell.py`. The machine module performs no I/O. The shell does: a stdlib HTTP + WebSocket server and a
page (canvas, Web Audio, keyboard, gamepads), headless runs (PNG, WAV, frame hash, input scripts), battery saves
(every few seconds when changed, and at exit) with the MBC3 clock in the common 48-byte trailer and the wall-clock
time since the save added to it. Keys: arrows, X = A, Z = B, Enter = Start, Shift = Select.

## 6. The DS prototype

* **ISA**: `isa/armv5te`: ARM and Thumb instruction forms with masks, fields, ISA level (`v4t` / `v5te`),
  nominal ARM946E-S cycles, flags as data, semantics and vectors; the decoder tables are generated from them.
  The same cards run the ARM9 (arch 5) and the ARM7 (arch 4), which take turns on the core's registers.
* **Machine**: `machine/nds` with `nds_memory` (both maps, TCMs via CP15, WRAMCNT), `nds_io` (interrupts,
  IPC sync and FIFOs, timers, DMA, divider and square root, the cartridge bus serving reads from the image),
  `nds_bios` (HLE BIOS calls, CP15, our own IRQ dispatcher words at the vector). Direct boot as the firmware
  leaves it.
* **What it is for now**: measured coverage. `cardmodel machine nds ROM` reports per CPU the instructions run,
  distinct addresses, which instruction cards the code used, undecodable instructions, BIOS calls (modelled or
  not), and every hardware block the game touched that no card models. That list is the work queue.
* **The same pipeline for ARM code** (`machine/lift_arm.py`, `cardmodel machine nds ROM --lift`): an ARM card is a
  function of its instruction word, so a block is the cards' IR with constant words: fields fold, register-list
  loops unroll, pure helpers are evaluated at lift time, the condition becomes one flag test, registers live in
  locals. DS code is in RAM and overlays replace it, so a block first checks that its words are still there; it
  leaves after a branch and wherever the interpreter would check for interrupts, halts or a CPSR change. The
  differential run compares both CPUs' registers and every RAM after each frame.
* **Nothing is decrypted**: an image whose secure area is encrypted is refused.

## 7. Adding things

* **An instruction**: edit the generator (`tools/gen_lr35902.py`, `tools/gen_armv5te.py`) or the pack, then
  `cardmodel isa build ISA` and `cardmodel isa check ISA`.
* **A new ISA**: an ISA card with `core.card` and `interface.card`, instruction cards (opcode-byte or mask
  decode), a `<isa>_bench` machine; the bench and `verify` pick it up.
* **A hardware component**: `cards/hardware/<name>/card.json` (registers, timing as data) + its `.card` logic;
  list it in a machine card's `components`.
* **A bank controller**: a case in `gb_cartridge/cart.card` and an entry in the card's `types` table.

## 8. Honest limits

* PPU: a scanline renderer (mid-mode-3 changes apply to the whole line); the window's exact mode-3 cost, the
  LY=153 quirk and the blank first frame after LCD enable are not modelled.
* APU: point sampled (no band limiting); the noise channel's LFSR only steps while samples are made.
* No MMM01, MBC6, MBC7, HuC1/HuC3, TAMA5, camera, or unlicensed multicart mappers.
* DMG compatibility mode gives every cartridge the boot ROM's default palette: the per-title palettes the boot
  ROM picks for Nintendo's own games (by title checksum) and the hand-picked ones (a d-pad combination during
  the logo) are not modelled. `--model auto` runs a DMG cartridge on the DMG.
* What no test pins in DMG compatibility mode follows SameBoy: VBK and the palette data registers ignore writes;
  the hand-over is in V-blank as in CGB mode (LY, STAT and LCDC after the boot depend on the header and are not
  tested). The CGB's early line-144 STAT source is measured in single speed; in double speed it is the same 4
  dots, unverified.
* Lifting: code no profile, static successor or abstract run reached, RAM code whose bytes changed since it was
  profiled, code in video or cartridge RAM, illegal opcodes and the instruction after a HALT bug run in the
  interpreter (counted in `interpreted`). The abstract run knows only the constants its own path set (a value
  loaded from memory it did not write is unknown); a table's length is found by its entries, so a table that runs
  into another adds code that may never run (harmless); each run is bounded.
* DS: no 2D/3D graphics, sound, touch, SPI devices, RTC or Wi-Fi yet; no wait states; flat VRAM. ARM lifting
  covers ARM-state ARM9 code only; its word guards read through the bus, so it saves the decode but not the
  fetches (little speed-up for RAM-resident code).
