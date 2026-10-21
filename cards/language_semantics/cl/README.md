# cl — Card Language

CL is the substrate's first-class card-native language. A CL program
is a typed expression whose atoms are **card references**; the
compiler resolves those references to concrete code at emit time.

## One-paragraph mental model

A CL program names *what to compute* by composing cards. It does not
name *how to compute it*. The compiler picks the "how" — Python vs.
Rust vs. CUDA vs. QASM — based on a `ResolveContext` (target
language, optimisation axis, hardware). That separation is what lets
the same CL program emit a Python orchestrator on a laptop and a
Rust hot-loop on an HPC node, without source changes.

## Files in this card

- `card.json` — the canonical CL language card.
- `interpreter.json` — the calling-convention contract every CL
  toolchain implementation must satisfy.
- `README.md` — this file.

The grammar lives in `cards/_meta/cl_grammar/grammar.ebnf`; the IR
schema lives in `cards/_meta/cl_ir/schema.json`; the compiler
pipeline lives in `cards/_meta/cl_compilation_model/`.

## Sample programs

### Factorial

```cl
factorial : Int -> Int =
  match n with
  | 0 -> compute.alu.constant_one
  | n -> compute.alu.multiply(n, factorial(compute.alu.decrement(n)))
```

### Quantum Bell state

```cl
bell : Unit -> QState =
  let q0 = compute.quantum.qubit_zero in
  let q1 = compute.quantum.qubit_zero in
  let q0h = compute.quantum.hadamard(q0) in
  compute.quantum.cnot(q0h, q1)
```

### Image-pipeline (resolves to Python + Rust + CUDA from one source)

```cl
pipeline : Path -> Path =
  let img  = io.image.load(input) in
  let blur = compute.image.gaussian_blur(img, 1.5) in
  let tm   = compute.image.tonemap(blur) in
  io.image.save(tm, output)
```

## Invoking the compiler

```bash
# emit Python
python3 cards/tool/cl_compile/python.py examples/factorial.cl --target python

# typecheck only
python3 cards/tool/cl_compile/python.py examples/factorial.cl --check

# emit QASM for a 5-qubit backend
python3 cards/tool/cl_compile/python.py examples/bell.cl \
  --target qasm \
  --hardware hw_5qubit.json
```

See `interpreter.json` for the full argument and exit-code list.

## Why CL exists

- **Card-native source.** Every program in the studio expressed as
  cards (not raw target code) MUST be expressible in CL — that's
  **L25**. CL is the surface form of the substrate's programs.
- **Multi-target without forking.** One CL source, many emitted
  languages. The studio can pivot hardware, OS, or language target
  without re-authoring source.
- **Additive-only extensibility.** New primitives are new cards.
  New target languages are new cards. The compiler is closed for
  modification but open for extension via the substrate — that's
  **L26**.
- **Witness-friendly.** A CL program *is* a typed DAG of card
  references; the substrate can audit it (does every referenced
  card exist? does the resolver find a variant for every node?
  does the emitted code re-typecheck?) without needing to parse
  the target language.

## Status (day 1)

- `cl_grammar`, `cl_ir`, `cl_compilation_model` — written (this
  agent).
- `cards/tool/cl_compile/python.py` — Agent D, in flight.
- Sample programs (`cards/computation/examples/cl/...`) — Agent D.
- Lean reference semantics — deferred to v3.
- Rust port — deferred to v2.

## Known flaws

- **monolingual.** Day-1 compiler is Python only. Lifting plan:
  Rust port at v2 (post self-hosting bootstrap), Lean reference
  semantics at v3.
- **lacking: tool_cl_compile.** Compiler tool card is not on disk
  yet; tracked as Agent D's deliverable.
