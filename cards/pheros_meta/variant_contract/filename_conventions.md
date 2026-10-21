# Variant filename conventions

Each card directory may contain any of the following files. None are required; presence indicates the card supports that variant.

| filename        | meaning                                                  |
|-----------------|----------------------------------------------------------|
| `card.json`     | the card record itself (REQUIRED)                        |
| `README.md`     | human-readable summary (REQUIRED for cards/, optional in _meta) |
| `schema.json`   | JSON Schema for cards whose claim IS a schema            |
| `python.py`     | Python implementation variant                            |
| `lean.lean`     | Lean 4 specification/proof variant                       |
| `rust.rs`       | Rust implementation variant                              |
| `typescript.ts` | TypeScript implementation variant                        |
| `<lang>.<ext>`  | any other language variant by its file extension         |
| `witness.py`    | Python witness predicate (or `witness.<lang>` in another language) |
| `gui.html`      | HTML rendering of this card for the hub                  |
| `mcp.json`      | MCP tool definition exposing this card to AI agents      |
| `tests/`        | per-variant tests                                        |
| `examples/`     | usage examples                                           |

New filename conventions are added by writing a card in `cards/_meta/` whose `interacts_with` includes `variant_contract`. The kernel does not need to be edited — the convention's existence is what makes it legal.
