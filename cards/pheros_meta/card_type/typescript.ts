// typescript.ts — TypeScript variant of the Card type — STUB.
// Tracked as `lacking:ts_variant_for_card_type` until expanded.
// The schema in schema.json is normative; this file is one variant.

export interface Card {
  name: string;
  category: string;
  tier?: number;
  cost?: number | Record<string, number>;
  statement?: string;
  rationale?: string;
  problem?: string;
  solution?: string;
  location?: string;
  file_refs?: string[];
  depends_on?: string[];
  supersedes?: string[];
  interacts_with?: string[];
  tags?: string[];
  status?: "healthy" | "suspect" | "broken" | "quarantined";
  flaws?: string[];
  witness?: string | null;
  variants?: Record<string, string>;
  metadata?: Record<string, unknown>;
}
