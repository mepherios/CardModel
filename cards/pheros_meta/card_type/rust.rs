// rust.rs — Rust variant of the Card type — STUB.
// Tracked as `lacking:rust_variant_for_card_type` until expanded.
// The schema in schema.json is normative; this file is one variant.

use std::collections::HashMap;

#[derive(Debug, Clone)]
pub struct Card {
    pub name: String,
    pub category: String,
    pub tier: u32,
    // (remaining fields to be added; see schema.json)
}
