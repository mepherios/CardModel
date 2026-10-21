# AnyPS5 on the card model

AnyPS5 relinks PS5 executables into native Linux or Windows programs that run against its own
reimplementations of the PS5 system libraries (one `APS5_VABI` C++ function per exported NID), and recompiles
RDNA shaders to SPIR-V. The card model reads a checkout of it **read-only**, expresses it as cards, reproduces
its progress badges, computes what is really complete, gives every gap the cause that keeps it open, and runs
AnyPS5's own pure code next to semantics it derives from public standards.

The numbers are generated: [ANYPS5_COVERAGE.md](ANYPS5_COVERAGE.md) (`cardmodel anyps5 cover --write
docs/ANYPS5_COVERAGE.md`) and the `G_P*` goals in [COVERAGE.md](../COVERAGE.md). This page says what they
mean, why they are what they are, and what would move them.

## The 95 %

AnyPS5 publishes two badges, both computed by its `tools/progress.py` (documented in its
`docs/dev/PROGRESS.md`):

* **libraries**: declared functions whose body never calls `NotImplemented_nid_no_patch` (directly or through
  a wrapper in the same file), over all declared functions;
* **shaders**: RDNA 1/2 instructions the decoder recognises, over AMD's instruction list.

There is no 95 % in the checkout the model read (see `anyps5_snapshot/current`): the libraries badge and the
shader badge are the two figures at the top of ANYPS5_COVERAGE.md. The card model reads the same counting rule
independently (`cardmodel/anyps5/scan.py`) and gets the same result library by library and name by name;
`cardmodel anyps5 scan PATH --parity` runs AnyPS5's own tool and compares (goal `G_P1`).

What the badges cannot see, and the model can:

* functions the badge counts as implemented whose body is only a constant, a bare return or a throw (AnyPS5
  calls them "behaviourally empty" and reports them separately);
* implemented functions that throw, by their own message, for inputs they do not support;
* implemented functions that reach `NotImplemented` through a helper in another file or through another
  export (the badge only follows wrappers in the same file);
* implemented functions a technical-debt entry names: part of their behaviour is assumed, inferred from a
  title, taken from a PS4 reimplementation, or not measured on a PS5;
* the reverse: functions the badge counts as pending although they are implemented except for named,
  unsupported paths (a `NotImplemented("... (case)")` call on one branch);
* the denominator: AnyPS5 counts only what it declares; many modules declare no exports at all, and the
  firmware's real export tables are not read here (that would mean copying firmware: never, by policy);
* for shaders, "decoded" is not "translated correctly": the model separates decoded, named by a translation
  case, and named by an execution test.

## How the model reads AnyPS5

| step | what | where |
|---|---|---|
| scan | every `APS5_VABI` definition, assembly export and raw-NID alias with file and line; every debt bullet; the shader instruction list; the badge's rule reproduced | `cardmodel/anyps5/scan.py` |
| cards | `anyps5_export`, `anyps5_debt`, `anyps5_library`, `anyps5_instruction` (packs), `anyps5_snapshot/current`; observations, never edited by rules (CM15) | `cardmodel/anyps5/cards.py` |
| knowledge | `anyps5_cause` (the taxonomy, what closes each cause, the cue patterns debt text is read with), `anyps5_domain` (what each library is for), `anyps5_standard` (exports a public standard fixes) | `tools/seed_anyps5.py` |
| logic | the module graph as facts; rules derive every gap, every candidate cause, the strongest cause, what blocks what, the packet-size law; constraints: no gap without a cause, no library without a domain | `stdlib/anyps5.card`, `cardmodel/anyps5/classify.py` |
| semantics | card-language programs derived from public standards, with theorems and tests | `stdlib/ps5_*.card` |
| witnesses | AnyPS5's own C++ (the file included, or functions extracted by pattern) compiled next to the semantics, seeded inputs, recorded as `anyps5_witness` cards | `cardmodel/anyps5/witness.py`, `cards/anyps5_semantics/*` |
| report | the coverage ladder, every gap by cause, what closes it, findings | `cardmodel/anyps5/cover.py` |
| verify | section `anyps5`: classification complete, semantics pass, witnesses agree and are current, badge reproduced | `cardmodel verify --quick` |

`cardmodel anyps5 why NAME` prints, for an export or a debt entry, each gap, its cause, what closes it, the
witness evidence, and the proof the logic engine kept (the derivation can be checked like any other).

## Why it is not 100 % by construction

The model derives what a public standard or the model's own structure fixes, and nothing else (law CM32,
after Pheros L102 and AnyPS5's own rule "never return a made-up success"). Every gap falls in one of four
classes, and the class says what can close it:

1. **Derivable.** A public standard (C, POSIX, FreeBSD, ELF, ISO codecs, RFCs, USB HID, FAT, PM4) or the
   model's structure (a GetSize returns the size of the packet its emitter writes; an export blocked by
   another) fixes the semantics.
   * `derivable_closed`, `derivable_packet`: closable in the IR today. AnyPS5 already implements every packet
     size the model can derive, and the model proves those constants (they leave the "behaviourally empty"
     list).
   * `derivable_standard_data`: pure, but over strings, arrays or structs (code-page tables, FFTs, Opus/AAC,
     scanf, H.264/H.265 headers). The card IR is int/float/bool, so these wait for the string/list IR.
   * `derivable_standard_host`: effects on the host (processes, shared memory, kqueue, sockets, file system).
     They belong in AnyPS5's effect shell as host mappings (CM21), witnessed by AnyPS5's own tests on Linux
     and Windows, not in the model's pure core.
   * `derivable_blocked`: derivable once the export they reach is implemented; `cardmodel anyps5 blocks`
     ranks the blockers by how many implemented exports reach them.
2. **Observation only.** The information exists only in the console: an export known only by its NID, a
   signature or result layout nobody has seen, an error code, a constant, a timing, a behaviour AnyPS5 took
   from a PS4 reimplementation or inferred from one title. No derivation produces it; the debt entries say
   so themselves ("not measured on a PS5"). Closing it means observing the console or a title (AnyPS5's
   `Closes when: measured on a PS5`), which this session does not do and which never involves copying
   firmware, keys or dumps.
3. **Boundaries.** Hardware (VR headset, camera, controller haptics and motion, audio devices, GPU execution,
   display), services (PSN), system processes (the shell, launcher, installs, system UI), development-kit
   tooling. These are the effect shell: the model names the boundary and what a host mapping or the device
   would need. DRM and entitlement checks are a boundary by policy: never derived or bypassed.
4. **Performance.** Closed by a measurement on the target machine, not by a derivation.

So a model that is "far superior" in what it can prove still cannot prove what nobody has observed. What it
can do is make every one of those obligations explicit, attach it to its file and line and its debt entry,
order it by what it unblocks, and refuse to count it as done.

## What the model closed and witnessed

Eight semantics bindings over seven programs, each derived from a public standard, each run next to
AnyPS5's code:

| program | standard | AnyPS5 code it runs |
|---|---|---|
| `stdlib/ps5_rtc.card` | proleptic Gregorian calendar, Unix and Win32 epochs, FAT date/time | libSceRtc exports and its `daysFromCivil` / `civilFromDays` |
| `stdlib/ps5_libc.card` | libgcc runtime ABI integer routines; ISO C 7.4 in the "C" locale | libc's compiler builtins (and the console behaviour AnyPS5 recorded outside the ABI's domain), ctype |
| `stdlib/ps5_libm.card` | IEEE 754 exact operations (round to integral, min/max, fdim, scaleB, convert to integer) | libc's Math.cpp and MathExact.cpp in double, float and long double (built for x86-64, the PS5's architecture: on an Apple-silicon Mac it runs under Rosetta) |
| `stdlib/ps5_net.card` | network byte order (RFC 1700, POSIX) | libSceNet's hton/ntoh |
| `stdlib/ps5_agc.card` | AMD PM4 type-3 header | `Agc::Command::Header`, and the size law over every GetSize / emitter pair |
| `stdlib/ps5_keycode.card` | USB HID usage tables, US layout | `UsCharacter`, `sceConvertKeycodeGetCharacter` |
| `stdlib/ps5_mp3.card` | ISO/IEC 11172-3, 13818-3, MPEG-2.5 | both MPEG header readers in libSceAjm (extracted: the rest of the file needs FFmpeg) |

The programs also carry theorems (proved by exhaustion or witnessed), for example that AnyPS5's O(1)
`daysFromCivil` (Hinnant's era algorithm, `days_from_civil_fast`) equals the calendar's definition, that
every FAT field round-trips, and that the PM4 header's fields round-trip. The fast form is the optimized one;
the theorem is why it may be used.

## Findings

These come from the cards and the witnesses (the generated report lists every instance):

* **Implemented, but reaching `NotImplemented`.** Exports the badge counts as implemented call helpers in other
  files that refuse a case, for example `sceKeyboardGetKey2Char` (through `Keyboard::GetKey2Char`) and a
  family of libkernel and libc file operations that refuse files inside a title's archive
  (`RefuseArchivedFile`, `AppArchiveRefuse*`).
* **Pending, but implemented.** The badge counts functions as pending when any branch calls `NotImplemented`,
  even when that branch names one unsupported case and the rest works (most of libSceAjm's batch API).
* **Constants proven.** GetSize exports that AnyPS5 marks behaviourally empty return exactly the bytes of the
  packet their emitter writes (directly or through `Agc::Command::Write*` helpers): the size law holds on
  every pair, so they are not gaps.
* **A documented deviation, measured, then fixed in a copy.** `sceAjmDecMp3ParseFrame` (taken from shadPS4,
  unconfirmed on a PS5) treats every layer as layer III and rejects MPEG-2.5 above 64 kbit/s. Over all 8,192
  combinations of the header fields a parser reads, it differs from the standard on 3,000: 1,992 of the 2,016 valid
  layer I and II headers, the 864 headers with the reserved layer value (which it accepts), and the 144 MPEG-2.5
  layer III headers above 64 kbit/s (which it rejects). AnyPS5's own decoder path (`ParseMp3Frame`) follows the
  standard for layer III and rejects layers I and II. The copy below reads all 8,192 as the standard does; how
  the console reads them is still an observation.
* **Recorded console behaviour, kept apart.** Outside the runtime ABI's domain, AnyPS5's builtins follow what
  it read from a title's `libc.prx` (wrapping `__addv*`, division by zero to 0 in `__udivsi3`, `__clzdi2(0)` =
  32, traps elsewhere). The model encodes those as observations, separate from the derived semantics, and the
  witness checks AnyPS5 implements its own record.
* **A derived layer AnyPS5 lacks.** `sceConvertKeycodeGetCharacter` throws for every state bit it does not
  know. The shifted US layer is derived and tested (`us_shifted_char`); which bit means shift stays an
  observation.

## What it would take (in the order it pays)

1. **The blockers.** Three pending exports are reached by implemented ones (`cardmodel anyps5 blocks`):
   `sceAjmBatchJobRunSplit` (7 callers; pending because a helper in its file refuses a null buffer list with a
   nonzero count, and what the console answers there is unmeasured: observation), `vfscanf` (2) and `vsscanf` (1)
   (ISO C; the open branch is the 16-bit wide conversion on Linux, which waits for the string/list IR). An earlier
   reading that `readlink` blocked 11 exports was an artifact of the scan: it resolved AnyPS5's own host call
   `::readlink("/proc/self/exe")` to the guest export. Calls now resolve by C++ name only (test `Resolving`).
2. **Host mappings for the standard host functions** (`derivable_standard_host`): POSIX/FreeBSD/HTTP behaviour
   is specified; AnyPS5 maps it to the host and its ctest witnesses it. This closes only the branches that ask
   a host question; most open branches ask what the console does (next section).
3. **The string/list IR** (ROADMAP): turns `derivable_standard_data` into programs the model can close with the
   standards' own test vectors (code pages, FFT, scanf, codec headers).
4. **A C/C++ frontend** (ROADMAP): AnyPS5's pure code could then be lifted into the IR directly, so every
   pure function becomes witnessable and `improve`-able without a hand-written binding.
5. **Observation**: the largest class. Each item already names its file, line and debt entry; closing it is a
   console or title measurement recorded as an observation card (ground truth, CM15), after which the rules
   reclassify it.
6. **Boundaries** stay boundaries; the report says what each would need, and DRM stays out by policy.

## What was missing, why, and the fixed copy

The checkout in `~/Documents/AnyPS5-main` stays read-only. Fixes go into a copy, `~/Programmering/AnyPS5-cardmodel`
(its own git repository, imported from AnyPS5-main as downloaded on 2026-10-21). The copy builds and runs without
the card model: a fix is plain C++ in AnyPS5's style with AnyPS5's own tests. The card model reads the copy as a
project (`.cardmodel/` in it): its scan replaces the model's scan of upstream, and `anyps5 cover --compare` sets
the two side by side (`docs/dev/CARDMODEL_COVERAGE.md` in the copy).

| class | gap items | why it is open | fixed in the copy |
|---|---:|---|---|
| derivable | 316 | a standard fixes it, but most items have a branch that names a console fact or a host limit, or the code is string/array work the IR cannot hold yet | the MP3 header reading |
| observation | 4,251 | only the console has the answer | nothing: a guess would break AnyPS5's rule against made-up results |
| boundary | 2,677 | hardware, services, system processes; DRM by policy | nothing |
| performance | 34 | a measurement on the target machine | nothing |

Why the derivable class does not simply close:

* **Host functions** (`derivable_standard_host`) are pending on branches such as fork and exec, absolute
  symlinks, cpuset levels other than WHICH, or the real-time priority of another thread. POSIX says what a host
  does there, not what the console does, so filling them in from the standard would guess.
* **Where AnyPS5 follows the console against the standard**, the standard is the wrong reference: `seed48` and
  `jrand48` reproduce measured PS5 behaviour that differs from POSIX.
* **String and array work** (`derivable_standard_data`: scanf, code pages, codec headers) waits for the
  string/list IR; scanf's open branch (16-bit wide conversion) is partly a host question as well.
* **The one item with code to fix and a standard that settles it** was the MP3 header reading.

**The fix** (copy commit 98c15c4, `fix(libSceAjm): read MP3 frame headers with the standard tables for every
layer`):

* `ParseMp3Header` takes the bitrate from the table of its version and layer (ISO/IEC 11172-3, 13818-3 and
  MPEG-2.5), counts layer I frames in 4-byte slots of 384 samples and layer II frames as 1,152 samples, and rejects
  the reserved layer value.
* Over all 8,192 combinations of the fields a parser reads (40,960 field values, built for x86-64 and run under
  Rosetta), upstream's export differs from the standard on 3,000 and the copy's on none. The copy's sampled witness agrees on all 3,005 inputs it tries;
  upstream needed a separate check for its documented deviation (105 of 165 sampled inputs differed).
* AnyPS5's tests (`core/libs/tests/GuestAjm.cpp`) gain six headers (MPEG-2.5 at 80 and 160 kbit/s, layers I and
  II in MPEG-1 and MPEG-2) and the reserved layer, with values checked against `stdlib/ps5_mp3.card`. Those tests
  need the full build (FFmpeg) and do not run on this Mac; the witness runs the same function.
* The debt entry (libSceAjm.native L10) now says the tables follow the standards, while the signature and result
  layout are still shadPS4's and the console's reading of layers I and II and of MPEG-2.5 above 64 kbit/s is not
  measured.
* The coverage numbers do not move, and should not. The export stays pending by AnyPS5's rule, because its
  original-file-length lookup still refuses the layouts it does not know (L25). It also stays named by debt.

| | upstream | the copy |
|---|---:|---:|
| implemented (AnyPS5's rule) | 4,332 | 4,332 |
| complete by AnyPS5's own records | 2,467 | 2,467 |
| exports agreeing with derived semantics | 138 | 138 |
| MPEG header combinations read differently from the standard (all 8,192) | 3,000 | 0 |
| documented deviations from a standard (sampled inputs) | 105 | 0 |

**Running it.** The relinker builds on this Mac (AnyPS5's relinker-only mode: `cmake -S . -B build-relinker
-DCMAKE_BUILD_TYPE=Release -DANYPS5_RELINKER_ONLY=ON -DBUILD_TESTING=ON`). The result is
`build-relinker/core/relinker/relinker`, an arm64 executable, and 225 of its 226 tests pass. The other test,
`shader_cache_runtime_sources`, configures a sub-build with Ninja, which is not installed here. The system
libraries need AnyPS5's full build (Linux or Windows, submodules, FFmpeg, SDL, Vulkan), which means downloads and
was not done. Their pure functions run in the witnesses instead; libm and the copy's MP3 parser are built for
x86-64, the PS5's architecture, and run under Rosetta. Nothing here runs a title.

## Commands

```bash
cardmodel anyps5 scan ~/Documents/AnyPS5-main --parity --save --global
```

```bash
cardmodel anyps5 witness ~/Documents/AnyPS5-main --global
```

```bash
cardmodel anyps5 cover --write docs/ANYPS5_COVERAGE.md
```

```bash
cardmodel anyps5 gaps --cause derivable_standard_host
```

```bash
cardmodel anyps5 why sceKeyboardGetKey2Char
```

```bash
cardmodel anyps5 blocks
```

In the copy (the project layer):

```bash
cardmodel anyps5 scan . --parity --save
```

```bash
cardmodel anyps5 witness .
```

```bash
cardmodel anyps5 cover --compare --write docs/dev/CARDMODEL_COVERAGE.md
```

## Limits

* The scan is lexical: macros are not expanded and every `#if` branch is seen; calls are resolved by name.
* "Complete" means complete by AnyPS5's own records, not equal to the console: a function nobody wrote a debt
  entry for can still differ from the PS5.
* A debt entry's cause comes from cue words in its text (the cards record which pattern matched); the domain
  table is a judgement recorded in cards.
* Witnesses run AnyPS5's code with this host's compiler and C++ library and sample inputs: evidence, not proof.
* The model never reads firmware, keys or game dumps, and never runs AnyPS5 against a title.
