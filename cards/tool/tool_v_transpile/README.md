# tool_v_transpile

Any-source -> any-target transpilation via a minimal IR.

## Architecture

```
   source_text
       |
       v
  frontends/<lang>.py    (parse to IR)
       |
       v
       IR  (JSON, see ir.py)
       |
       v
  emit_python.py         (emit Python from IR)
       |
       v
  V_Framework/lib/transpilers/python_to_<target>.py
       |
       v
   target_text
```

Each frontend exposes `parse(source: str) -> dict`. The IR shape is:

```json
{
  "functions": [
    {"name": "...", "params": [{"name": "...", "type": "..."}],
     "return_type": "...", "body": [...]}
  ],
  "imports": [...],
  "constants": [...]
}
```

Statement kinds: `assign | return | if | while | for | call | expr | raw`.
Anything we can't normalise becomes a `raw` node carrying the verbatim
source; emitters surface it as a `# unsupported construct, pasted verbatim`
comment in Python (which V_Framework then translates to the target's
comment style).

## Usage

```
# explicit --from / --to
pheros transpile --from rust --to python --file foo.rs
pheros transpile --from c    --to all    --file foo.c

# default --from is python (back-compat with the old monolingual CLI)
echo 'def square(n): return n*n' | pheros transpile --to javascript

# discoverability
pheros transpile --list
```

## Supported source languages

`python` (re-uses Python's `ast`), `c`, `cpp`, `rust`, `javascript`,
`typescript`, `go`. Each frontend lives in `frontends/<lang>.py`.

## Supported target languages

Discovered at runtime from `vendored/V_Framework/lib/transpilers/python_to_*.py`.
Currently: `c`, `cpp`, `go`, `html`, `javascript`, `rust`, plus `python`
(identity / IR-roundtrip).

The card's `statement` lists the 12 nominal targets from the README
(c, cpp, javascript, typescript, java, csharp, ruby, rust, go, lean, coq,
python). Targets beyond the 6 modules currently shipped fall back to the
V_Framework V-IR pivot when present.

## Smoke matrix

See `outputs/agent_w2_matrix.md` for the latest 7 sources x 12 targets
pass/fail table.
