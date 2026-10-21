"""isa — instruction cards: load them, compile their semantics to IR, generate the interpreter's dispatch.

An ISA card (``isa/<isa>``, ``kind: isa``) names the semantic helper library (``core``, a card-language file
next to its card.json) and the bus contract (``interface``: stubs with the right effects). An instruction card
(``kind: instruction``, ``isa: <isa>``) holds its encoding, its data (bytes, cycles, mcycles, flags) and its
``semantics`` (card-language statements); ``ir`` is the compiled function, named after the card.

``build`` compiles every instruction's semantics against core + interface in one module and stores the IR on
the cards (the pack is rewritten whole). ``in_sync`` recompiles and compares, so the stored IR never drifts
from the source. ``dispatch_source`` writes the opcode switches (one per prefix) that the interpreter uses.

Honest limits (L1): decode by opcode byte (+ prefix byte) only; ISAs decoded by bit masks (ARM) use
``mask_dispatch_source``. The stored IR is what every engine runs; the semantics text is its source.
"""
from __future__ import annotations

import copy

from ..lang.compile import compile_sources


def isa_card(store, isa: str):
    card = store.get(f"isa/{isa}")
    if card is None or card.get("kind") != "isa":
        raise KeyError(f"no ISA card isa/{isa}")
    return card


def instructions(store, isa: str) -> list:
    out = [c for c in store.cards("isa") if c.get("kind") == "instruction" and c.get("isa") == isa]
    return sorted(out, key=lambda c: c.name)


def library_text(card, key: str) -> str:
    rel = card.get(key)
    if not rel:
        return ""
    if card.path is None:
        raise ValueError(f"{card.qualified}: {key} file needs a directory card")
    return (card.path / rel).read_text(encoding="utf-8")


def semantics_source(cards) -> str:
    """Every instruction's semantics as one card-language function per card (named after the card)."""
    parts = []
    for c in cards:
        body = "\n".join("  " + ln for ln in (c.get("semantics") or "").splitlines())
        parts.append(f"fn {c.name}() {{\n{body}\n}}\n")
    return "\n".join(parts)


def compile_semantics(ctx, isa: str) -> dict:
    """{card name: IR function} for every instruction card of the ISA (compiled against core + interface)."""
    ic = isa_card(ctx.store, isa)
    cards = instructions(ctx.store, isa)
    sources = [(library_text(ic, "core"), f"isa/{isa}/{ic.get('core')}"),
               (library_text(ic, "interface"), f"isa/{isa}/{ic.get('interface')}"),
               (semantics_source(cards), f"isa/_pack_{isa}.jsonl")]
    mod = compile_sources(sources, ctx.ops, ctx.store, name=f"isa_{isa}")
    return {c.name: mod.functions[c.name] for c in cards}


def build(ctx, isa: str) -> dict:
    """Compile every instruction card's semantics and store the IR on the card (rewrites the pack)."""
    irs = compile_semantics(ctx, isa)
    cards = instructions(ctx.store, isa)
    packs = {c.source for c in cards}
    if packs != {f"pack:_pack_{isa}.jsonl"}:
        raise ValueError(f"the {isa} instruction cards must all live in cards/isa/_pack_{isa}.jsonl (found {packs})")
    changed = 0
    out = []
    for c in cards:
        d = dict(c)
        if d.get("ir") != irs[c.name]:
            changed += 1
        d["ir"] = irs[c.name]
        out.append(d)
    ctx.store.save_pack("isa", isa, out, layer="model")
    return {"isa": isa, "cards": len(out), "ir_changed": changed}


def in_sync(ctx, isa: str) -> dict:
    """Recompile and compare with the stored IR (a card whose IR drifted from its semantics is reported)."""
    irs = compile_semantics(ctx, isa)
    drift = [c.name for c in instructions(ctx.store, isa) if c.get("ir") != irs[c.name]]
    return {"cards": len(irs), "drifted": drift, "status": "pass" if not drift else "fail"}


def externs(store, isa: str) -> dict:
    """The stored IR of every instruction card: {name: function} (deep copies)."""
    out = {}
    for c in instructions(store, isa):
        if not c.get("ir"):
            raise ValueError(f"{c.qualified} has no compiled ir: run `cardmodel isa build {isa}`")
        out[c.name] = copy.deepcopy(c["ir"])
    return out


def dispatch_source(store, isa: str) -> str:
    """One switch function per prefix (``isa.dispatch``: {"" -> base function, "<byte>" -> prefixed})."""
    ic = isa_card(store, isa)
    table = ic.get("dispatch") or {}
    by_prefix: dict = {}
    for c in instructions(store, isa):
        key = "" if c.get("prefix") is None else str(c["prefix"])
        by_prefix.setdefault(key, []).append(c)
    parts = []
    for key, fname in table.items():
        cases = "\n".join(f"    case 0x{c['opcode']:02X} {{ {c.name}() }}"
                          for c in sorted(by_prefix.get(key, []), key=lambda c: c["opcode"]))
        parts.append(f"fn {fname}(op: Int) {{\n  switch op {{\n{cases}\n  }}\n}}\n")
    base = {c["opcode"]: c["bytes"] for c in by_prefix.get("", [])}
    if base:
        # instruction length by first byte (a prefixed instruction's length is its prefix card's): data from the cards
        lens = ", ".join(str(base.get(op, 1)) for op in range(256))
        parts.append(f"array op_bytes: Byte[256] = [{lens}]\n")
    return "\n".join(parts)


def decode_table(store, isa: str) -> dict:
    """{(prefix or None, opcode): card} for byte-decoded ISAs."""
    return {(c.get("prefix"), c["opcode"]): c for c in instructions(store, isa)}


def summary(store, isa: str) -> dict:
    cards = instructions(store, isa)
    groups: dict = {}
    for c in cards:
        groups[c.get("group", "?")] = groups.get(c.get("group", "?"), 0) + 1
    return {"isa": isa, "instructions": len(cards), "with_ir": sum(1 for c in cards if c.get("ir")),
            "illegal": sum(1 for c in cards if c.get("illegal")), "groups": dict(sorted(groups.items())),
            "conditional": sum(1 for c in cards if isinstance(c.get("cycles"), dict))}


__all__ = ["build", "compile_semantics", "decode_table", "dispatch_source", "externs", "in_sync", "instructions",
           "isa_card", "library_text", "semantics_source", "summary"]

