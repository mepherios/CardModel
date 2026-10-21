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
cd tests && python3 -B -m unittest
```

`probe` lists the toolchains found here. `verify --quick` witnesses the kernel, forms, vectors, rules and identities.
`translate` runs Python → C, C++, Rust, Go, Swift, Java, JavaScript, TypeScript, Ruby, Lua and Lean, verified. The
last command runs the test suite.

| Read | For |
|---|---|
| [HANDOVER.md](HANDOVER.md) | how to use, extend and continue it; worked examples (Ting, rea); real vs scaffold; next steps |
| [GOALS.md](GOALS.md) | purpose and measurable goals (goal cards) |
| [ARCHITECTURE.md](ARCHITECTURE.md) | layout, contract, data flow, design decisions, what was ported from where |
| [LAWS.md](LAWS.md) | the laws (generated from `cards/law`) |
| [ROADMAP.md](ROADMAP.md) | done / now / next |
| [COVERAGE.md](COVERAGE.md) | computed coverage and goal values (generated) |
| [docs/PROVENANCE.md](docs/PROVENANCE.md) | sources, commits, and what the witnesses found in them |
