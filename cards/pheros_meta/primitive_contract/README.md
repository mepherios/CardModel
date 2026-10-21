# primitive_contract

What every primitive computational card MUST carry.

A primitive is the unit at the bottom of the composition stack — the
smallest computational claim the studio is willing to attribute a
contract to. Examples: `add_u64`, `xorshift32`, `mmap`, `parse_int`,
`matmul_blas`, `dijkstra`.

## Required fields

Every `cards/computation/<cat>/<name>/card.json` MUST contain:

| field | meaning |
|---|---|
| `name` | snake_case identifier, unique within the studio |
| `category` | one of the 18 in `computation_taxonomy` |
| `statement` | one-paragraph plain-language claim |
| `contract.inputs` | named, typed inputs |
| `contract.outputs` | named, typed outputs |
| `contract.preconditions` | what must hold before invocation |
| `contract.postconditions` | what holds after, if preconditions held |
| `contract.side_effects` | effect tags (none, io, alloc, time, ...) |
| `complexity.time` | big-O or operational bound |
| `complexity.space` | big-O or absolute bytes |
| `complexity.energy` | optional energy claim |
| `alternatives` | other cards solving the same problem |
| `composes_with` | cards this one commonly stacks with |
| `witnesses` | mechanical checkers of the above |
| `variants` | at least one language/format variant present |

The full machine-readable schema is in `schema.json`.

## Why these specific fields

- **contract** lets a composition tool decide whether two cards plug
  together without reading their bodies.
- **complexity** is enforced by `L24_complexity_declared`; without it
  the card has no quantitative claim and cannot participate in
  performance reasoning.
- **alternatives** + **composes_with** are the graph edges the
  reverse-index tool walks when answering "what else could I use here?"
- **witnesses** is the bridge to L1 — a primitive's claim has to be
  mechanically checkable, not just asserted in prose.

## Failure modes

- A card under `cards/computation/` missing any of the required
  top-level keys surfaces as `lacking: incomplete_primitive`.
- A card whose `complexity.time` or `complexity.space` is missing
  fails the `L24_complexity_declared` witness.
- A card whose `category` is not one of the 18 fails the
  `computation_taxonomy` schema and the `L23_computation_completeness`
  witness.
