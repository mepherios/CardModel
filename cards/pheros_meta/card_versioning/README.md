# card_versioning

Edits to card.json files should preserve history.

## Protocol
- Every card MAY carry `metadata.version` (semver: `MAJOR.MINOR.PATCH`).
- Every card MAY carry `metadata.previous_content_hash` (sha256 of the previous card.json bytes).
- Bump rule:
  - MAJOR: schema-incompatible change (field added/removed/retyped)
  - MINOR: semantic change (statement/rationale changed)
  - PATCH: typo / formatting / metadata-only

## Archive
When `tool_create_card` overwrites an existing card, it should write the prior version to `cards/version/<name>/v<MAJOR.MINOR.PATCH>/card.json` before committing the new one.

## Current state
The protocol is defined here. `tool_create_card` does not yet honor it — that work is tracked as the partial-supersession in this card's `flaws` list.
