# variant_contract

A variant is a file inside a card's directory whose name selects the language or format. The variant's contents are an alternative expression of the card. All variants of one card express the same claim; the witness verifies cross-variant equivalence where possible.

## Rationale

The variant contract is what makes L1 mechanical. Adding a new language to the system means: drop one file with the language's extension into each card directory that should support it. No central registration. The kernel discovers variants by reading directory contents.
