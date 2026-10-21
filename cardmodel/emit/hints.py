"""hints — per-language spellings of a card (hub language_hints, extended with the runnable templates).

Two kinds of entry, both read from the card:
  emit   the template codegen actually uses for the IR op (verified by the
         conformance matrix);
  hints  the hub's idiomatic snippets (documentation: some are verified as
         ``role: hint`` forms, the rest need libraries that are not here).
"""
from __future__ import annotations

from ..engines.codegen import EmitGap, Emitter


def hints_for(ctx, card) -> dict:
    out = {"card": card.qualified, "emit": {}, "hints": dict(card.get("hints") or {})}
    ir = card.get("ir") or {}
    if ir.get("types"):
        sig = ir["types"][0]
        for lang in ctx.codegen_languages():
            try:
                tpl = Emitter(ctx.store, lang, ctx.ops).op_template(card.name, list(sig[:-1]))
                out["emit"][lang] = tpl.format(*[f"a{i}" for i in range(len(sig) - 1)], type=sig[-1],
                                               tc=sig[0][0], **{f"t{i}": t for i, t in enumerate(sig[:-1])})
            except EmitGap as exc:
                out["emit"][lang] = f"(gap: {exc})"
            except (IndexError, KeyError):
                out["emit"][lang] = tpl
    return out
