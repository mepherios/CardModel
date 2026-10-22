"""asm — an assembler made from the instruction cards (the cards read in the other direction).

Each instruction card's ``mnemonic`` is a template: ``n`` is an 8-bit immediate, ``nn`` a 16-bit one, ``e`` a
signed 8-bit displacement (relative to the next instruction). A program is a list of items:

    ("LD A,n", 0x41)   ("JP nn", "start")   ("JR NZ,e", "loop")   ("label", "loop")   ("db", b"...")

``assemble`` resolves labels in two passes and returns the bytes; ``rom`` wraps code in a 32 KiB cartridge
image with a valid header (title, type, sizes, header checksum) and ``NOP; JP 0x0150`` at the entry point.
Tests use it to build their own ROMs, so no game is ever needed in the repository.

``arm_word`` reads the ARM instruction cards the same way: a word is the card's fixed bits (the match half of its
``encoding``), each named field put where the card's ``fields`` says, and the condition where the ISA card's
decode says (0xE, always, unless given).

Honest limits (L1): no expressions, macros or sections; a label used before its definition must be in the
same assembly; ``e`` targets must be within -128..127 of the next instruction. ``arm_word`` places only the
fields a card names (a branch's offset, which its card leaves unnamed, cannot be given).
"""
from __future__ import annotations

from . import isa as I

_TABLE: dict = {}


def table(store, isa: str = "lr35902") -> dict:
    """{mnemonic: card} for the ISA (cached per store)."""
    key = (id(store), isa)
    if key not in _TABLE:
        _TABLE[key] = {c["mnemonic"]: c for c in I.instructions(store, isa) if not c.get("illegal")
                       and not c.get("prefix_of")}
    return _TABLE[key]


def _operand_kind(mnemonic: str) -> str | None:
    import re
    m = re.search(r"(?<![A-Za-z])(nn|n|e)(?![A-Za-z])", mnemonic)
    return m.group(1) if m else None


def assemble(store, items: list, org: int = 0x0150, isa: str = "lr35902") -> bytes:
    tab = table(store, isa)
    labels: dict = {}

    def encode(item, pc, final):
        if item[0] == "label":
            return b""
        if item[0] == "db":
            return bytes(item[1])
        card = tab.get(item[0])
        if card is None:
            raise ValueError(f"no instruction card with mnemonic {item[0]!r}")
        code = bytes([card["prefix"], card["opcode"]]) if card.get("prefix") is not None else bytes([card["opcode"]])
        kind = _operand_kind(card["mnemonic"])
        size = card["bytes"]
        if kind is None:
            return code
        arg = item[1] if len(item) > 1 else 0
        if isinstance(arg, str):
            if arg not in labels:
                if final:
                    raise ValueError(f"undefined label {arg!r}")
                arg = pc
            else:
                arg = labels[arg]
        if kind == "e":
            d = arg - (pc + size)
            if final and not -128 <= d <= 127:
                raise ValueError(f"{item}: displacement {d} out of range")
            return code + bytes([d & 0xFF])
        if kind == "n":
            return code + bytes([arg & 0xFF])
        return code + bytes([arg & 0xFF, (arg >> 8) & 0xFF])

    for final in (False, True):
        pc = org
        out = bytearray()
        for item in items:
            if item[0] == "label":
                labels[item[1]] = pc
            b = encode(item, pc, final)
            out += b
            pc += len(b)
    return bytes(out)


def rom(store, code_items: list, title: str = "CARDMODEL", cart_type: int = 0x00, cgb: int = 0x00,
        rom_size_code: int = 0, ram_size_code: int = 0, extra: dict | None = None) -> bytes:
    """A cartridge image: header + code at 0x0150 (+ ``extra``: {address: bytes} placed verbatim)."""
    size = 32768 << rom_size_code
    img = bytearray(size)
    img[0x100:0x104] = bytes([0x00, 0xC3, 0x50, 0x01])          # NOP; JP 0x0150
    t = title.encode("ascii")[:15]
    img[0x134:0x134 + len(t)] = t
    img[0x143] = cgb
    img[0x147] = cart_type
    img[0x148] = rom_size_code
    img[0x149] = ram_size_code
    code = assemble(store, code_items, org=0x150)
    img[0x150:0x150 + len(code)] = code
    for addr, data in (extra or {}).items():
        img[addr:addr + len(data)] = data
    chk = 0
    for b in img[0x134:0x14D]:
        chk = (chk - b - 1) & 0xFF
    img[0x14D] = chk
    return bytes(img)


_ARM: dict = {}


def arm_word(store, name: str, cond: int = 0xE, **fields) -> int:
    """One ARM-state instruction word from the instruction card ``name`` (e.g. ``ARM_LDR_imm``)."""
    key = (id(store), name)
    if key not in _ARM:
        _ARM[key] = next((c for c in I.instructions(store, "armv5te") if c.name == name), None)
    card = _ARM[key]
    if card is None:
        raise ValueError(f"no ARM instruction card {name!r}")
    word = int(card["encoding"].split("/")[0], 16)
    for field, value in fields.items():
        if field not in card["fields"]:
            raise ValueError(f"{name} has no field {field!r} (it names {sorted(card['fields'])})")
        hi, lo = card["fields"][field]
        if not 0 <= value < 1 << (hi - lo + 1):
            raise ValueError(f"{name}.{field} = {value} does not fit bits {hi}..{lo}")
        word |= value << lo
    hi, lo = store.get("isa/armv5te")["decode"]["sets"]["arm"]["condition"]
    width = (1 << (hi - lo + 1)) - 1
    return (word & ~(width << lo) & 0xFFFFFFFF) | (cond << lo)


__all__ = ["arm_word", "assemble", "rom", "table"]
