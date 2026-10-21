# redefinition_contract

Every card in `cards/redefinition/<name>/card.json` MUST match the JSON
schema in `schema.json`. The required fields are:

| field         | type                                  | meaning                                                       |
|---------------|---------------------------------------|---------------------------------------------------------------|
| `name`        | `snake_case` string                   | unique identifier under `cards/redefinition/`                 |
| `category`    | literal `"redefinition"`              | category tag                                                  |
| `source_form` | sympy-parseable string                | LHS of the identity                                           |
| `target_form` | sympy-parseable string                | RHS of the identity                                           |
| `domain`      | enum                                  | one of `real`, `complex`, `fp32`, `fp64`, `bitvec64`, `modular_n`, `positive_real`, `integer` |
| `condition`   | sympy predicate string or `null`      | side condition; identity holds only when this evaluates to True |
| `cost_score`  | integer 1–100                         | relative cost (lower wins)                                    |
| `proof_ref`   | math card name, `"axiomatic"`, or `null` | justification                                              |
| `witness_kind`| enum                                  | one of `symbolic`, `numerical`, `exhaustive`, `axiomatic`     |
| `examples`    | non-empty list                        | each entry: `{ input: {var: value}, source_eval, target_eval }` |
| `tags`        | list of strings                       | free-form labels                                              |

The contract pairs with **L34_redefinition_witness_required**: this card
defines the *shape* of a redefinition card; L34 defines the *semantic*
obligation (a witness must exist and at least one example must hold).

## Worked example (verbatim)

```json
{
  "name": "square_naive",
  "category": "redefinition",
  "source_form": "x**2",
  "target_form": "x*x",
  "domain": "integer",
  "condition": null,
  "cost_score": 1,
  "proof_ref": "axiomatic",
  "witness_kind": "symbolic",
  "examples": [
    {"input": {"x": 3}, "source_eval": 9, "target_eval": 9},
    {"input": {"x": -5}, "source_eval": 25, "target_eval": 25}
  ],
  "tags": ["square", "monomial", "tier1"]
}
```

## Discovery loop reference

The contract is the data side of the discovery loop documented in
`cards/process/redefinition_theory/markdown.md`:

```
propose -> verify -> cost -> catalog -> optimise
```

`propose` produces a draft card; `verify` runs the witness defined by
`witness_kind`; `cost` populates `cost_score`; `catalog` writes the file
under `cards/redefinition/<name>/`; `optimise` is the solver consuming
the catalog.
