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


def semantics_source(cards, param: str | None = None) -> str:
    """Every instruction's semantics as one card-language function per card (named after the card); ISAs that
    decode by bit masks pass the instruction word as ``param``."""
    parts = []
    sig = f"{param}: Int" if param else ""
    for c in cards:
        body = "\n".join("  " + ln for ln in (c.get("semantics") or "").splitlines())
        parts.append(f"fn {c.name}({sig}) {{\n{body}\n}}\n")
    return "\n".join(parts)


def compile_semantics(ctx, isa: str) -> dict:
    """{card name: IR function} for every instruction card of the ISA (compiled against core + interface)."""
    ic = isa_card(ctx.store, isa)
    cards = instructions(ctx.store, isa)
    sources = [(library_text(ic, "core"), f"isa/{isa}/{ic.get('core')}"),
               (library_text(ic, "interface"), f"isa/{isa}/{ic.get('interface')}"),
               (semantics_source(cards, ic.get("operand_param")), f"isa/_pack_{isa}.jsonl")]
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


def _mask_chain(cards, fixed_mask: int, fixed_val: int, param: str, indent: str) -> tuple[str, list]:
    """The decision for one decode index: candidates in priority order, each checked on the bits the index
    does not fix; the first candidate fully decided by the index ends the chain; nothing left is undefined."""
    cand = [c for c in cards if (c["mask"] & fixed_mask & (c["match"] ^ fixed_val)) == 0]
    cand.sort(key=lambda c: (-c.get("priority", bin(c["mask"]).count("1")), c.name))
    lines, used = [], []
    opened = 0
    for c in cand:
        rmask = c["mask"] & ~fixed_mask
        rmatch = c["match"] & rmask
        used.append(c.name)
        if rmask == 0:
            lines.append(f"{indent}{'  ' * opened}{c.name}({param})")
            break
        lines.append(f"{indent}{'  ' * opened}if ({param} & {rmask:#x}) == {rmatch:#x} {{")
        lines.append(f"{indent}{'  ' * opened}  {c.name}({param})")
        lines.append(f"{indent}{'  ' * opened}}} else {{")
        opened += 1
    else:
        lines.append(f"{indent}{'  ' * opened}undefined_op({param})")
    for k in range(opened, 0, -1):
        lines.append(f"{indent}{'  ' * (k - 1)}}}")
    return "\n".join(lines), used


def _index_fields(fields: list, param: str):
    """A decode index made of bit fields of the word (card data: ``decode.sets.<set>.index_fields``, high field
    first): (table size, the bits it fixes, index -> those bits, the index expression)."""
    widths = [hi - lo + 1 for hi, lo in fields]
    total = sum(widths)
    fmask = 0
    for hi, lo in fields:
        fmask |= ((1 << (hi - lo + 1)) - 1) << lo

    def fixed(i: int) -> int:
        v, at = 0, total
        for (hi, lo), wd in zip(fields, widths):
            at -= wd
            v |= ((i >> at) & ((1 << wd) - 1)) << lo
        return v

    parts, at = [], total
    for (hi, lo), wd in zip(fields, widths):
        at -= wd
        part = f"(({param} >> {lo}) & {(1 << wd) - 1:#x})"
        parts.append(f"({part} << {at})" if at else part)
    return 1 << total, fmask, fixed, " | ".join(parts)


def mask_dispatch_source(store, isa: str) -> str:
    """Decode tables and dispatch functions for an ISA decoded by masks (ARM: a 12-bit index from bits 27-20 and
    7-4; Thumb: the top 10 bits; any other set: the ``index_fields`` its ISA card names, e.g. MIPS's opcode and
    function fields), generated from the instruction cards' mask/match and priority."""
    ic = isa_card(store, isa)
    names = ic.get("dispatch") or {}
    param = ic.get("operand_param", "op")
    cards = instructions(store, isa)
    out = []
    for key, fname in names.items():
        if key == "arm_uncond":
            cs = [c for c in cards if c.get("set") == "arm" and c.get("unconditional")]
            body, _ = _mask_chain(cs, 0, 0, param, "  ")
            out.append(f"fn {fname}({param}: Int) {{\n{body}\n}}\n")
            continue
        cs = [c for c in cards if c.get("set") == key and not c.get("unconditional")]
        spec = ((ic.get("decode") or {}).get("sets") or {}).get(key) or {}
        if spec.get("index_fields"):
            n, fmask, fixed, index = _index_fields(spec["index_fields"], param)
        elif key == "arm":
            n, fmask = 4096, 0x0FF000F0
            fixed = lambda i: (((i >> 4) & 0xFF) << 20) | ((i & 0xF) << 4)      # noqa: E731
            index = f"(({param} >> 16) & 0xFF0) | (({param} >> 4) & 0xF)"
        else:
            n, fmask = 1024, 0xFFC0
            fixed = lambda i: i << 6                                           # noqa: E731
            index = f"{param} >> 6"
        groups: dict = {}
        table = []
        for i in range(n):
            body, _ = _mask_chain(cs, fmask, fixed(i), param, "      ")
            gid = groups.setdefault(body, len(groups))
            table.append(gid)
        cases = "\n".join(f"    case {gid} {{\n{body}\n    }}" for body, gid in groups.items())
        out.append(f"array {fname}_dec: Int[{n}] = [{', '.join(map(str, table))}]\n")
        out.append(f"fn {fname}({param}: Int) {{\n  let g = {fname}_dec[{index}]\n  switch g {{\n{cases}\n  }}\n}}\n")
    return "\n".join(out)


def dispatch_source(store, isa: str) -> str:
    """One switch function per prefix (``isa.dispatch``: {"" -> base function, "<byte>" -> prefixed})."""
    ic = isa_card(store, isa)
    if (ic.get("decode") or {}).get("kind") == "mask":
        return mask_dispatch_source(store, isa)
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

