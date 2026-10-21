# PROVENANCE

The original card-model folders were **read only**: nothing in them was modified. `tools/vendor_import.py` and
`tools/bootstrap.py` are the only code that read them. Neither is imported by the program, and
`tests/test_self_contained.py` runs the program with those folders unreadable. Exact file hashes, commits and counts
for every vendored registry are in each registry's `_category.json` (`provenance`) and in `docs/VENDOR_REPORT.json`.

| Source | Read | Became |
|---|---|---|
| `~/Documents/Claude_Hub` (hub) | `CARD_MODEL.md`, `LAWS.md`, `config/{card_catalog, card_redefinitions, bit_primitives, language_hints, rewrite_engine, rewrite_search, cross_language_equiv, lean_emitter}.py` (Python parsed with `ast`, never imported) | kernel contract; `cards/op` forms + hints; `cards/lib/bit_primitives` (verbatim copy with hash header); `cards/call`, `cards/shape`; rules; engines (see ARCHITECTURE.md) |
| `~/Documents/Pheros_Studio/cards` | `_meta/{card_type, variant_contract, registry_contract, redefinition_contract, primitive_contract, card_versioning}`, `computation/`, `redefinition/`, `cross_language_equivalence/`, `translation_gap/`, `language/`, `tool/v_transpile` (card, README, ir.py), `law/` (statements), `bin/pheros-learn` + its CLI | `cards/pheros_meta` (verbatim); `card_type/*` (ported schemas); packs `computation`, `redefinition_note`; `redefinition` (executable subset); `xleq_observed`, `translation_gap`, `language_semantics`, `tool`; laws consolidated into `cards/law`; `engines/learn.py` |
| `~/Programmering/ting` (commit in `cards/crypto_atom/_category.json`) | `docs/CARD_MODEL_MAPPING.md`, `cards/{crypto_atom, cipher_suite, card_type}`, `core/cardmodel.py`, `core/encoding.py`, `static/app/enc.js`, `tools/build_cards.py`, `tests/py/test_atoms.py`, `tests/js/atoms.test.mjs`, `tests/py/test_cross_language.py` | `cards/crypto_atom` (vectors converted to `{args, out}`; stdlib + node:crypto forms written for the model); `cards/cipher_suite`; `cards/ting_card_type`; `kernel/canon.py`; `tests/test_random_seed.py` |
| `~/Programmering/rea-cards` (commit in `cards/format/_category.json`) | `docs/MAPPING.md`, `runtime/reacards/{probes, dispatch, calibrate, domains, native/strings, native/detect}.py`, `witnesses/coverage.py`, `cards/re_domain`, `cards/re_operation/list_strings` | lessons in `probes.py`, `rewrite.cheapest`, `optimize.py`, `coverage.py`; `cards/format`; `cards/re_operation/{list_strings, detect_format}` |
| `~/Documents/rea-main` | the source tree, observed once to test `observe` on TypeScript | nothing vendored |
| Pheros `cards/_meta/{cl_grammar, cl_ir, cl_compilation_model}`, `language/cl` | read for alignment | the card language accepts CL v0's function form and follows its compilation model; nothing vendored |
| Lean 4 core library (`~/.elan/toolchains/<toolchain>/src/lean/Init/Data/{Nat,Int}`), Apache-2.0, © Microsoft Corporation and contributors | theorem *statements* in the arithmetic fragment (proofs are not copied; each card cites the original declaration, file and toolchain, and its faithfulness is checked by the kernel against the original) | `cards/theorem/_pack_lean_core.jsonl` (`cardmodel lean import --core --save --global`) |

## What the witnesses found in the sources (reproducible with `cardmodel verify --only forms,redefinitions`)

* **Hub `card_redefinitions` domains.** Several forms declared domain `int` but are 32-bit
  (`ADD/SUB/MUL/SQUARE/POW.bit`, `NEG.twos`, the `nand`/`demorgan`/`xor_mask` gates). On unbounded integers they are
  refuted with a counterexample; on `u32` (compared modulo 2**32) they pass.
* **`ABS.branchless`** is exact only for 32-bit signed inputs. The witness refutes the hub's `int` claim at a
  ≥ 2**31 boundary value.
* **`SHIFT_RIGHT.floordiv`.** The hub said it is "only equal for x ≥ 0", but `x // 2**k == x >> k` holds for every
  Python int. The witness passes it on negative `x` too.
* **`FLOORDIV` rust hint `div_euclid`.** The hub note said it "matches Python semantics for negative operands", but
  it differs from floor division when the divisor is negative. It is refuted there and verified for non-negative
  inputs.
* **Pheros redefinitions.**
  * Some were pairs of program names (`cat_original_c → cat_rewritten_rs`): references, not identities, so they were
    moved to `redefinition_note` (count: `docs/VENDOR_REPORT.json`, `name_pair_reference`).
  * Of the executable identities, none is refuted.
  * The float witness used to refute true identities at some seeds: across 2002 seeds it gave 46 false
    refutations on 23 cards, about one `verify` in 45. In 7 rational cards a target divides by a square such as
    `(2*x**2*y - 4*x - 2)**2` that nearly vanishes. In 16 `tan(2x)` cards, squares of `tan(x)` cancel near x = ±pi/2.
    Rational forms are now evaluated exactly, and any other float disagreement is decided again at high precision.
    On the same seeds the result is 0 refutations, with the 31 disagreements on the `tan` cards resolved as
    rounding artefacts.
  * Some auto-generated cards carry examples that bind only some variables (e.g. `x=1` for a form in `x, y`). The
    redefinition witness reports these as `examples.incomplete`, because they made the original L34 check vacuous.
* **Ting vectors.** Every converted RFC/NIST vector passes in both the model's stdlib-Python forms (including
  pure-Python X25519 and Ed25519) and its node:crypto forms.
