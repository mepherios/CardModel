# Foreign programs: running another platform's executables natively

The goal: a program built for another machine (the PSP, the PS5, any console or computer) runs on this computer
because the card model understands what it computes, not because someone wrote an emulator for that machine. The
foreign CPU is its instruction cards, the foreign operating system is an `os` card, the file format is a `format`
card, and the program's own code is translated ahead of time into native code of this computer through the same
cards. Adding a platform is adding cards; the pipeline stays the same.

```bash
./bin/cardmodel machine run prog.mips --lift --arg 30            # translate ahead of time, run natively
```

```bash
./bin/cardmodel machine run prog.mips --stdin input.txt          # interpreter (C from the cards)
```

```bash
./bin/cardmodel isa check mips32                                 # every instruction card, every engine
```

## 1. What exists now (the first platform: 32-bit MIPS, the PSP's CPU family)

| layer | cards | what it holds |
|---|---|---|
| ISA | `isa/mips32` + `isa/_pack_mips32.jsonl` (109 cards) | MIPS32 Release 2 little-endian user-mode integer instructions and the Sony **Allegrex** (the PSP's CPU): its own MADD/MSUB/CLZ/CLO/MIN/MAX encodings, WSBW, BITREV, no SPECIAL2. `variant` picks the core; a card of the other core is a reserved instruction. Delay slots and branch-likely are in the cards and the step. |
| OS | `os/linux_mips_o32` | Linux/MIPS o32 system calls as card logic (`syscalls.card`): exit, write, writev, read, brk, mmap/mmap2 (anonymous), munmap, getpid, ioctl, set_thread_area, clock_gettime (machine time, so runs repeat). Every other call answers ENOSYS and is counted. Numbers, errno values, memory layout and the toolchain that builds a program for it are card data. |
| format | `format/elf32` | the ELF header and program-header fields as `[offset, size]`, which ISA card an `e_machine` names and which machine card runs it. |
| machine | `machine/mips_linux`, `machine/mips32_bench` | a user-mode process (flat memory, bus, faults, the run loop) and the one-instruction bench. |
| host | `cardmodel/machine/process.py` | the effect shell: load the ELF, write argc/argv/envp/auxv, feed stdin, run in slices, drain stdout/stderr. Knows no ISA and no OS. |
| translation | `cardmodel/machine/lift_elf.py` | the program's code decoded once by the instruction cards and emitted as card-language blocks that call the cards with constant words; the C card compiles them and the C compiler inlines and folds the cards. |

The dispatch for a mask-decoded ISA is now generic: the ISA card names the bit fields that index its decode table
(`decode.sets.<set>.index_fields`); ARM and Thumb keep their tables.

## 2. Witnesses

* **Per instruction** (`cardmodel isa check mips32`, `verify --only machine`): every card in the reference
  interpreter, Python and C on seeded random words, states and cores; registers stay 32-bit, r0 stays 0, a card of
  the other core changes nothing but the reserved-instruction hook, an instruction that faults writes no register,
  only branches move control; hand-derived vectors (unaligned LWL/LWR/SWL/SWR, overflow, signed division, delay
  slots, branch-likely, the Allegrex encodings).
* **As mathematics** (`machine/symbolic.py`, `check_mips`): every card's meaning as terms over the registers and
  the bytes it reads, evaluated against the bench: all 109 agree.
* **The program itself** (`tests/test_foreign.py`): self-written C samples (`tests/foreign/`) built for MIPS
  Linux by the os card's toolchain and built for this computer by its own compiler must print the same thing and
  exit the same way, interpreted and translated. The translated run must match the interpreter instruction for
  instruction (same count, same registers). A write outside memory stops the process with an address error; an
  unmodelled system call is counted; MIPS32r2 code on the Allegrex core stops at its first SPECIAL2 instruction.

Measured on the cloud container (the `work.c` sample, 30 rounds, 147.5 million MIPS instructions): interpreter
in C about 250 million instructions per second; translated about 1,400-1,700 million; the same source built
natively by gcc -O2 runs in 8 ms, because gcc also optimises across instructions (loop transformations), which the
translation does not do yet.

## 3. What is missing for "any program, any platform" (in order of what unlocks the most)

1. **PSP system software as an os card.** A PSP program does not make Linux system calls: it imports functions
   from system modules by NID through stub tables that the loader patches into `syscall` instructions. The card for
   it holds the module and NID tables of what homebrew uses (from the open PSPSDK headers, never from firmware),
   the PRX/ELF relocations (e_type 0xFFA0 and the `.rel.*`/`.sceStub.text` sections), and the behaviour of each call
   as card logic: threads, semaphores, file I/O on a host folder, the display and controller. Test with homebrew
   built by the open PSPSDK.
2. **FPU (COP1) and the PSP's VFPU.** Single-precision cards need an IR operation that rounds to binary32 (the IR's
   Float is binary64); the VFPU is a 128-register vector unit with its own encodings (opcodes 0x18-0x1B, 0x34-0x37,
   0x3C-0x3F).
3. **The PSP's graphics engine (GE)** as hardware cards, as `nds_3d` did for the DS: the display list commands,
   the rasteriser, textures and the framebuffer.
4. **x86-64 as an ISA card** (the PS5's CPU; also every PC program). Variable-length byte decoding with prefixes
   (the LR35902 path is byte-decoded with one prefix; x86 needs a prefix/ModRM/SIB decoder generated from cards),
   flags computed lazily, 64-bit values: the card language's `Int` is unbounded, but C's int64 is the native
   carrier, so 64-bit unsigned arithmetic needs the same care the 32-bit cards take. `format/elf64` next to
   `format/elf32`.
5. **The PS5's system and GPU.** `docs/ANYPS5.md` already reads AnyPS5 as cards (which exports exist, which are
   derivable from public standards, which only from observation). The os card for the PS5 would be built from that
   knowledge; the GPU side is RDNA shader instructions as an ISA card and the command processor as hardware cards.
6. **Translation quality.** Blocks are per entry point; a next step is functions (registers in locals across a
   function, as the Game Boy lifter does with its register caching), and code found only at run time added to the
   lifted set between runs (the Game Boy lifter's profiles).

## 4. How this fits learning

The instruction cards here are written from the architecture manual, as the LR35902 and ARM cards were, and each
is held to the bench, to vectors and to its terms. The bench is also exactly the data a learner needs: for any
word and any state it gives the state after. A learning engine that builds functions from basic op cards can
propose an instruction's semantics from those pairs and be checked by the same conformance run; a card it learns
that passes replaces nothing until it agrees with every engine. The os card's calls are the same: each one is a
function from the process's state to the state after, observable from a program's run.

## 5. Honest limits

* 32-bit little-endian static ELF executables only; no dynamic loader, threads, signals or FPU.
* Linux/MIPS is the first OS card because self-written programs for it can be built and checked here; the PSP's
  own system software is the next card (section 3.1), not built yet.
* A zero divisor leaves HI and LO unchanged, MUL leaves HI/LO unchanged, EXT/INS with fields past bit 31 leave the
  register unchanged: the manual calls these UNPREDICTABLE, and real cores differ.
* LWL/LWR/SWL/SWR read and write the whole aligned word (a read-merge-write), which matters only for I/O memory.
* Translated code is lifted from the file: code a program generates or rewrites runs in the interpreter (counted).
