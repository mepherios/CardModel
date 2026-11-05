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

```bash
./bin/cardmodel machine nds "Pokemon Diamond.nds" --frames 2400 --input "1500:start,1506:-" --png both.png --shots shots/ --every 120
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
  controller is modelled. A `static` or `blank` ROM gets a second run with no input and counts as running when
  that one animates (`input: none` in its row): START pauses some games, and the scripted taps can keep one
  paused. A ROM without the Nintendo logo that no board explains is reported as a pass-through device. "Runs" is
  evidence of booting, not of correctness.
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
* **Hardware**: memory map, MBC1/2/3 (+RTC)/5/7, HuC3, the Game Boy Camera, two unlicensed boards (below), timer (falling edges, the 4-cycle reload, DIV/TAC quirks), PPU
  (modes, STAT edge, LY=LYC, a scanline renderer with window, 10 sprites a line, DMG and CGB priority, CGB
  palettes and VRAM bank), OAM DMA and HDMA, joypad, serial (logged), APU (4 channels, frame sequencer, mixer,
  output capacitor).
* **Cartridge boards** (`hardware/gb_cartridge`: `cart.card`, `mbc7.card`, `huc3.card`, `camera.card`; tests in
  `tests/test_gb_mappers.py`, each on a cartridge the assembler builds; MBC7, HuC3 and the camera's cartridges
  leave the same work RAM, cartridge RAM and state in the C build, the Python build and the reference
  interpreter, and the survey counts their type bytes 0x22, 0xFE and 0xFC as supported):
  * **MBC7** (Kirby Tilt 'n' Tumble): banks, the accelerometer latch (0x55 erases to 0x8000, then 0xAA latches,
    centred on 0x81D0, 1 g = 0x70) and the 93LC56 EEPROM by its data sheet (start bit, opcode, 8 address bits; a
    dummy 0 then 16 bits MSB first; EWEN/EWDS, WRITE, ERASE, ERAL, WRAL). The EEPROM is the first 256 bytes of the
    cartridge RAM image (high byte first), so the save every host keeps for a RAM cartridge whose header gives no
    size (8 KiB, the player's too) carries it. There is no tilt sensor, so the d-pad tilts the cartridge by 1 g
    the way it points (right lowers X, up raises Y; measured on Kirby's levels: Kirby rolls the way the pad
    points); a stick on the shell's page drives the d-pad, and a shell with a real tilt source can add it in
    `tilt_x` / `tilt_y`.
  * **HuC3** (Robopon): banks, RAM read-only (mode 0) and read/write (mode 0xA), the clock chip's commands the
    way Robopon sends them (command in mode 0xB, 0xFE to the semaphore in mode 0xD, the answer's low nibble in
    mode 0xC: read/write a nibble and move on, set the address, copy the clock to nibbles 00-05 and back), and
    the infrared port (sees no light: 0xC0). The clock keeps its minutes of the day and 12-bit day count in the
    MBC3 clock's registers, so it runs in machine time, is saved in the same 48-byte trailer and catches up the
    same way, in every host.
  * **Game Boy Camera**: 6-bit ROM banks, 16 RAM banks (always readable), the sensor's registers at A000 when bit
    4 of the RAM bank register is set; a capture takes 32446 M-cycles, 512 more without N, 16 per unit of the
    exposure time, then the picture is in RAM bank 0 at 0x100 (16 x 14 tiles). No sensor: the light is a
    synthetic scene (a face that sways a little from one capture to the next) that the exposure time and gain
    scale, edge enhancement sharpens, I inverts and the game's 4 x 4 threshold matrix cuts into four shades. The
    camera boots to its menus and takes and saves pictures of that scene (its battery RAM keeps them).
  * **Wisdom Tree** (Spiritual Warfare, Exodus, Joshua, the Bibles): a write to 0000-3FFF selects the 32 KiB bank
    in the low byte of its address. **Sachen** (Jurassic Boy II + Thunder Blast Man, Jurassic Boy 2, 4 in 1 + 8 in
    1): base, ROM bank and mask registers, and the header page (0x0100-0x01FF) stored scrambled (A0/A6 and A1/A4
    swapped), so the CPU reads it in order. The header names neither: `cart_power_on` recognises them by where the
    Nintendo logo is, through the logo's CRC-32 (card data; the logo itself is not stored): Sachen when the logo is
    only where a locked board shows it (A7 forced high, lines swapped), Wisdom Tree for a ROM-only type with the
    logo in place and more than 32 KiB. Lifted code never covers a Sachen board's scrambled page (the interpreter
    reads it through the board). Every new board's lifted code is frame-identical to the interpreter (`machine
    diff`, 1500 frames each).
* **Boot**: no boot ROM (it is not ours to ship); the documented post-boot state, DMG or CGB per the header (read
  through the cartridge's board, which powers on first); the CGB hands over in V-blank (games touch VRAM at once),
  the DMG at the start of line 0. A CGB game gets BCPS at 0x80, auto-increment from index 0, where the boot ROM's
  last 64-byte BG palette load leaves it (SameBoy's open-source boot ROM): Jurassic Boy 2 writes its BG palettes
  without setting BCPS and showed no background before.
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
replaced by the byte it would read, PC set where the card's IR finds it in the interpreter (past the opcode, a
prefix and the bytes its fetches take: STOP's IR skips its second byte itself); it is then specialised:

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
game copies to HRAM, routines copied to work RAM) is lifted one instruction at a time, from every encoding the
profiles saw an instruction start with at each address (`ram_ops`, `ram_cb`: 256 bits per address from C000,
merged by OR like the ROM's bitmaps): one case per encoding, chosen by the opcode RAM holds when it runs, with the
operands read from RAM then. So routines copied over each other at one address and code that patches its own
operands run lifted (Pokemon Puzzle Challenge does both); during OAM DMA only HRAM's code runs lifted, and an
encoding no profile saw there runs in the interpreter (`run_ram`).

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
instruction-at-a-time interpreter (`interpreted`, `interpreted_ram`). Recursive descent follows the fall-through
of every conditional jump, call and return (`conditional`: a `RET Z` falls through as a `JP NZ,nn` does; missing
it had left the code after every conditional return to profiles). Pokemon Crystal, after a 31,800-frame profile
(the survey's presses, then a seeded walk) and the abstract run, on a run with another seed: every one of its
instructions ran as lifted card IR (0 interpreted, none from RAM), frame-identical to the interpreter.

Blocks are cached per ROM, machine and lifter version (the profile per ROM and machine: a new lifter keeps it),
emitted through the C card in per-bank parts, linked into one library. The profile grows with each session (the shell saves the new entries at exit, and an app made for
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
* **Machine**: `machine/nds` with `nds_memory` (both maps, TCMs via CP15, WRAMCNT; palettes and OAM drop byte
  writes), `nds_io` (interrupts, IPC sync and FIFOs, timers, DMA, divider and square root, the cartridge bus
  serving reads from the image, and the dispatch to the cards below), `nds_bios` (HLE BIOS calls, the ARM7's
  sine/pitch/volume tables computed from their definitions, CP15, our own IRQ dispatcher words at the vector),
  and the video and peripherals:

  | card | what it is |
  |---|---|
  | `nds_vram` | the nine VRAM banks in one array, placed by VRAMCNT into the LCDC window, engine A/B BG and OBJ, the extended palette, texture and texture palette slots or the ARM7's window; an 8 KiB page table rebuilt at every VRAMCNT write |
  | `nds_2d` | engines A and B, drawn line by line into two 256x192 screens: display modes, BG modes 0-6 (text, affine, extended map, 256-colour and direct-colour bitmaps, large bitmap), 4/8 bpp, extended palettes, 128 OBJs per engine (tiled 1D/2D, bitmap, affine, double size, semi-transparent, OBJ window), windows, blending, brightness, mosaic on text BGs, master brightness, POWCNT1's screen swap |
  | `nds_3d` | the 3D engine: a geometry card (GXFIFO packed commands and the command ports, matrix modes and stacks, vertex formats, lighting, triangle/quad lists and strips, facing, clipping in homogeneous space, the viewport, box/position/vector tests, two polygon RAMs swapped at V-blank) and a rendering card (rear plane, Z or W depth test, Gouraud shading, perspective-correct texturing in all seven formats, modulation, decal and toon, translucency and the alpha test); engine A shows the picture as BG0 |
  | `nds_spi` | the ARM7's SPI bus: power management, a firmware flash made from the card's data (header, Wi-Fi block, user settings with CRC; no console's firmware), the touch screen controller through the firmware's calibration |
  | `nds_backup` | the save chip on the auxiliary SPI bus: serial flash commands; which chip a game has is data by game code |
  | `nds_rtc` | the real-time clock on three bit-banged wires: status, date and time in BCD, alarms stored; it runs on machine time from what the host sets |
  | `nds_wifi` | the ARM7's wireless hardware as far as a game's wireless driver needs it to come up and stay idle: the 16-bit register file (the driver tests it by writing and reading back), the baseband and RF chips' registers, power-up with its wake-up interrupt, the microsecond counter with the beacon, pre- and post-beacon interrupts, the RX/TX ports into the Wi-Fi RAM, TX slots that complete; nothing is ever received |
  | `nds_sound` | the sixteen channels mixed into stereo samples: PCM8, PCM16 and IMA-ADPCM from memory, PSG square waves and noise, each at its timer's rate, with volume, divider, panning and the master volume; one-shot channels stop and clear their busy bits when their samples run out, looping ones return to their loop start |

  A frame is 263 lines: per line the line events (at line 192 a waiting SWAP_BUFFERS hands the filled polygon RAM
  to the rendering engine, which draws it for the next frame), the 2D engines draw a visible line from the registers
  as they are, the CPUs run the drawing part of the line, H-blank (flag, interrupt, H-blank DMA), the rest of the
  line, then timers, sound and the geometry FIFO interrupt advance. The cartridge bus starts its DMAs again for every ready word,
  so NitroSDK's 1-word repeating card DMA moves whole blocks.
* **Direct boot** is a card as well (`machine/nds` boot.card, `load_image`): from the image in `cart` and card data
  alone it leaves what the BIOS and firmware would: the ARM9 and ARM7 binaries where the header says, the header
  and the chip ID where the firmware puts them, a firmware flash with its header, Wi-Fi block and two copies of the
  user settings with their CRCs (`nds_spi`'s data), the user settings in main RAM, and the save chip the game code
  names (`nds_backup`'s table), erased. An image whose secure area is still encrypted is refused (`boot_refused`).
  The host and the arcade player both boot through it.
* **The host** (`machine/nds.py`): `DS(ctx, rom, clock=..., save=...)` copies an image in and boots it (a save chip's bytes and a
  start time for the clock are inputs; the default clock is fixed so runs repeat), `screens()` returns both
  screens, `png_screens` stacks them as on the console, `drain_audio()` the sound mixed since the last call,
  `set_buttons` / `touch` are the inputs, `save_bytes()` the save chip, `machine=` reuses a loaded machine for
  another image.
* **Headless** (`cardmodel machine nds ROM`): `--input` holds buttons from a frame on, `--png` saves both screens
  after the run, `--shots DIR --every K` every K frames, `--wav` the sound; the report says when each screen first
  showed a picture. Pokemon Diamond draws its copyright and ESRB screens after frame 51, plays its intro (the Game Freak
  logo, the Pokemon logo, the 3D flight over Sinnoh's towns), shows its title screen with the 3D Dialga and,
  with START and A, starts a new game (Professor Rowan's introduction); buttons and touch-screen taps reach it.
* **The arcade player** (`system/nds`, its player.card on the machine card): the DS in Cardmodel Arcade, built like
  the Game Boy player (`arcade/system.py`). `player_load` is `load_image`; each `player_frame` runs one machine
  frame and presents both screens as one 256x388 RGBA picture (top, a 4-line gap, bottom); the buttons go to
  KEYINPUT and EXTKEYIN in the card's bit order and the pointer over the bottom screen (`pointer.area`) to the
  touch screen controller; the sound runs at the rate that leaves exactly the shell's 1/60 s of samples per
  machine frame (47,860 Hz for 48 kHz: the console's 59.83 Hz shown at 60); the save chip goes into the save a
  second after it last changed and at quit; the clock is set from the shell's Unix time plus `player_clock_offset`
  (0, so UTC, until the shell writes it). Pokemon Diamond runs at 250-320 frames per second natively and plays
  from a new game (the touch-screen tutorial, naming, the TV report) into its 3D world: walking, the menu, and an
  in-game save that lands in the player's save file; a later boot continues it (the main menu first starts the
  wireless driver, which tests the Wi-Fi registers, powers the radio up and scans three channels: `nds_wifi`). The
  card names no cartridge tables card and has a `pointer`. Its `check_cartridge` (for `arcade check`) is a DS
  image `nds.check_image` builds, its ARM9 words read off the instruction cards (`asm.arm_word`): it draws on
  both screens and writes one byte to the save chip.
* **Measured coverage**: per CPU the instructions run, distinct addresses, which instruction cards the code used,
  undefined instructions (counted as they run; code overwritten after it ran is reported apart), BIOS calls
  (modelled or not), every hardware register the game touched that no card models, and what the screens show.
  That list is the work queue.
* **The same pipeline for ARM code** (`machine/lift_arm.py`, `cardmodel machine nds ROM --lift`): an ARM card is a
  function of its instruction word, so a block is the cards' IR with constant words: fields fold, register-list
  loops unroll, pure helpers are evaluated at lift time, the condition becomes one flag test, registers live in
  locals. DS code is in RAM and overlays replace it, so a block first checks that its words are still there; it
  leaves after a branch and wherever the interpreter would check for interrupts, halts or a CPSR change. The
  differential run compares both CPUs' registers and every RAM after each frame.
* **Witnesses** (`tests/test_nds.py`): a synthetic image whose ARM9 code maps banks and draws on both screens;
  each 2D feature pixel by pixel through the bus; VRAM banks; the save chip, firmware, touch screen, power
  management, clock, sound busy bits, the per-word cartridge DMA; the 3D engine through its command ports
  (position, facing, depth, translation and the matrix stack, a direct-colour texture, packed FIFO commands, the
  box test, BG0 as the 3D layer); the Wi-Fi hardware (the baseband's registers, power-up and its interrupt, the
  microsecond counter and the beacon interrupt, a TX slot completing, the RAM ports); region 4 beyond the
  registers; the arcade player (both screens and the gap, buttons and the pen through the bus, the sound rate,
  the save chip packed and restored, the clock, a refused image); and, when the image is on
  the machine (`CARDMODEL_DS_ROM`), Pokemon Diamond's first screens and its title screen's 3D Dialga.
* **Nothing is decrypted**: an image whose secure area is encrypted is refused.

## 7. Adding things

* **An instruction**: edit the generator (`tools/gen_lr35902.py`, `tools/gen_armv5te.py`) or the pack, then
  `cardmodel isa build ISA` and `cardmodel isa check ISA`.
* **A new ISA**: an ISA card with `core.card` and `interface.card`, instruction cards (opcode-byte or mask
  decode), a `<isa>_bench` machine; the bench and `verify` pick it up.
* **A hardware component**: `cards/hardware/<name>/card.json` (registers, timing as data) + its `.card` logic;
  list it in a machine card's `components`.
* **A bank controller**: a case in `gb_cartridge/cart.card` (or its own logic file, listed in the card's `logic`),
  an entry in the card's `types` and `mbc_kind` tables, and a test in `tests/test_gb_mappers.py`. A board the
  header does not name is recognised in `cart_power_on` (and the same rule in `machine/gb.py`'s `unlicensed`).

## 8. Honest limits

* PPU: a scanline renderer (mid-mode-3 changes apply to the whole line); the window's exact mode-3 cost, the
  LY=153 quirk and the blank first frame after LCD enable are not modelled.
* APU: point sampled (no band limiting); the noise channel's LFSR only steps while samples are made.
* No MMM01, MBC6, HuC1 or TAMA5 (none is in the surveyed collection). The camera's picture is synthetic, and its
  sensor's voltage and offset registers (V, Z, O) are not modelled. MBC7's tilt is the d-pad's, 1 g at a time.
  HuC3's infrared port never sees light (so infrared trading needs a second machine, which there is not), and its
  alarm and tone generator are not modelled. The Sachen multicart's second game (Thunder Blaster, its upper 256
  KiB) would be mapped by the base and mask registers (tested on an assembled cartridge), but what makes the
  cartridge select it was not found: it boots into Jurassic Boy II, which plays.
* **Two cheat devices do not run, and cannot from these files** (the survey still lists them, with the reason):
  * *GameShark (USA)*: the file is not the whole device. Datel's cartridge switches its own ROM banks with a
    register at 0x7FE1 (inferred from its firmware and the GameShark Online's) and has RAM at 6000-7FFF (the file's
    6000-7FFF is power-on garbage repeating every 4 KiB); whoever dumped it switched banks MBC1's way, which the
    device ignores, so the file is bank 0 plus one 16 KiB view repeated seven times. The firmware selects bank 2 at boot (`LD A,2 / LD (7FE1),A`), calls into it (0x5947 lands mid-
    function in the dumped bank) and copies its font from 0x50A0 there, which in the file is code: its menu has no
    font to draw.
  * *GameShark Online* (Action Replay V4.01): the file is whole (ten 8 KiB banks), but Datel's hardware is not
    documented anywhere we could find. Inferred from the firmware: banks of 8 KiB at 4000-5FFF selected by 0x7FE1
    (2, 3, 8, 9), RAM at 6000-7FFF holding its stack (SP = 0x7FC0), registers at 0x7FE0-0x7FEF, and a status bit
    (0x7FEE bit 0) that decides between its menu and "Manual Upgrade" (waiting for a PC). With only that modelled
    it shows its logo and loops back to it; the rest depends on registers whose behaviour is unknown.
  * Both are pass-through devices: the boot ROM reads the Nintendo logo of the game in their slot (neither file
    has one), and their purpose, patching a running game, needs that game. A model of them would plug a second
    cartridge from the library into the first; that is not built.
* Jeopardy! Platinum Edition and Teen Tournament run (the menu, the name entry); START pauses them even on the
  publisher's screen and the unpause waits about 1.5 s, which the survey's taps every 1.5 s kept re-pausing, so they
  count as running from their run without input.
* DMG compatibility mode gives every cartridge the boot ROM's default palette: the per-title palettes the boot
  ROM picks for Nintendo's own games (by title checksum) and the hand-picked ones (a d-pad combination during
  the logo) are not modelled. `--model auto` runs a DMG cartridge on the DMG.
* What no test pins in DMG compatibility mode follows SameBoy: VBK and the palette data registers ignore writes;
  the hand-over is in V-blank as in CGB mode (LY, STAT and LCDC after the boot depend on the header and are not
  tested). The CGB's early line-144 STAT source is measured in single speed; in double speed it is the same 4
  dots, unverified.
* Lifting: code no profile, static successor or abstract run reached, RAM code with an encoding no profile saw
  at its address, code in video or cartridge RAM, illegal opcodes and the instruction after a HALT bug run in the
  interpreter (counted in `interpreted`). The abstract run knows only the constants its own path set (a value
  loaded from memory it did not write is unknown); a table's length is found by its entries, so a table that runs
  into another adds code that may never run (harmless); each run is bounded.
* DS: no display capture or main-memory display FIFO; the Wi-Fi hardware answers a game's driver but
  nothing is ever received; sound is mixed without interpolation and the capture
  units write no memory; 3D has no edge marking, fog,
  anti-aliasing, shadow polygons, rear-plane bitmap or Y-sorting of translucent polygons; no wait states (a nominal
  instructions-per-line budget); a 2D line is drawn from the registers as they are when it starts; two VRAM
  banks on one page do not OR together; the save chip is serial flash only. ARM lifting covers ARM-state ARM9
  code only (Thumb and the ARM7 stay interpreted); its word guards read through the bus, so it saves the decode
  but not the fetches (little speed-up for RAM-resident code).
