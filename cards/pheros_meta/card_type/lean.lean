-- Lean 4 variant of the Card type — STUB.
-- Tracked as `lacking:lean_variant_for_card_type` until expanded.
-- The schema in schema.json is normative; this file is one variant.

structure Card where
  name           : String
  category       : String
  tier           : Nat
  -- (remaining fields to be added; see schema.json)
  deriving Repr
