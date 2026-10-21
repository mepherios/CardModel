# cardmodel

The card model as one self-contained program. Every structure is a card: languages, operators, rules, laws, goals,
observations, learned functions and measurements. Each card lives in a filesystem registry. From any project folder,
`cardmodel` can:

* **observe** code and express it as cards;
* **verify** every executable claim by running it (seeded, reproducible, able to fail);
* **translate** functions to other languages through a card IR, checking each translation with the real compiler or
  interpreter;
* **learn** new cards from evidence;
* **optimize**: pick the cheapest form, find cheaper equivalent expressions, and measure real costs.

It uses only Python's standard library, plus whatever toolchains the machine has (it probes them). It never needs
another folder at runtime.

```bash
./bin/cardmodel probe
```

```bash
./bin/cardmodel verify --quick
```

```bash
./bin/cardmodel translate examples/algorithms/algos.py
```

```bash
./bin/cardmodel improve arena/slowframework --out /tmp/fast
```

```bash
./bin/cardmodel arena --count 300
```

```bash
./bin/cardmodel run examples/lang/math.card --lean
```

```bash
./bin/cardmodel logic why examples/lang/grammar.card 's(0, 6)' --lean
```

```bash
./bin/cardmodel lean import --core
```

```bash
./bin/cardmodel algebra gcd 'expr:n*(n+1)//2' 'expr:n*(n+1)*(2*n+1)//6'
```

```bash
./bin/cardmodel game check
```

```bash
./bin/cardmodel game play --vs reader
```

```bash
./bin/cardmodel emu "~/Downloads/GB_GBC/Game Boy/Tetris (World) (Rev A).zip"
```

```bash
./bin/cardmodel machine nds "~/Downloads/Pokemon Diamond/Pokemon Diamond.nds"
```

```bash
cd tests && python3 -B -m unittest
```

`probe` lists the toolchains found here. `verify --quick` witnesses the kernel, forms, vectors, rules and identities.
`translate` runs Python → C, C++, Rust, Go, Swift, Java, JavaScript, TypeScript, Ruby, Lua and Lean, verified.
`run` executes a program in the card language (functions, logic rules, theorems, tests and cards in one file):
the theorems are witnessed and sent to Lean. `logic why` explains a derived fact and has the Lean kernel check
the derivation (here, a parse tree). `lean import --core` reads Lean's own Nat/Int library into theorem cards,
checks with the kernel that each reading is the original proposition, witnesses it, and re-proves it with the
model's own tactics and rule chains. `algebra gcd` compares two functions by behaviour (common factor, cofactor
identity, shared dynamics, Gödel number of each canonical form). `game check` computes the combat design's laws on an exact equilibrium,
and `game play` lets you fight the AI that reads your vectors.
`emu` runs a Game Boy or Game Boy Color game through the card model: its CPU is instruction cards, its hardware
is hardware cards, its own code is lifted into the card IR and compiled natively, and the browser page around it
is the effect shell (video, audio, keys, saves). `machine nds` boots a DS game on the ARM instruction cards and
reports what runs and what is not modelled yet.
`improve` makes a whole program faster with verified substitutions and leaves I/O, network and login code
byte-identical. `arena` generates a suboptimal program of any size and scores how well it is fixed. The last
command runs the test suite.

| Read | For |
|---|---|
| [HANDOVER.md](HANDOVER.md) | how to use, extend and continue it; worked examples (Ting, rea); real vs scaffold; next steps |
| [GOALS.md](GOALS.md) | purpose and measurable goals (goal cards) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | layout, contract, data flow, design decisions, what was ported from where |
| [LAWS.md](LAWS.md) | the laws (generated from `cards/law`) |
| [ROADMAP.md](ROADMAP.md) | done / now / next |
| [COVERAGE.md](COVERAGE.md) | computed coverage and goal values (generated) |
| [docs/PROVENANCE.md](docs/PROVENANCE.md) | sources, commits, and what the witnesses found in them |
| [docs/METHODOLOGY.md](docs/METHODOLOGY.md) | pure core / effect shell, the optimization pipeline, guarantees, online play |
| [arena/](arena/README.md) | the optimization test environment (hand-written slow framework + generator) |
| [docs/LANGUAGE.md](docs/LANGUAGE.md) | the card language: functions, logic, theorems, tests and cards in one file |
| [docs/KNOWLEDGE.md](docs/KNOWLEDGE.md) | crystallised knowledge: logic, theorem cards, discovered laws, Lean import and re-proofs |
| [game/DESIGN.md](game/DESIGN.md) | the game design (Vector Counter System): pillars, kernel, design laws, AIs, world |
| [docs/MACHINES.md](docs/MACHINES.md) | machines as cards: instruction cards, hardware cards, lifting, the effect shell, the DS prototype |
