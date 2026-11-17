"""gen_mips32 — BUILD-TIME: write the MIPS32r2 / Allegrex instruction cards (cards/isa/_pack_mips32.jsonl).

One card per instruction of the user-mode integer set of MIPS32 Release 2 (little-endian) and of the Sony
Allegrex, the PlayStation Portable's CPU: an encoding (mask/match, field layout), the core it exists on
(``arch``: ``mips32`` on both, ``mips32r2`` or ``allegrex`` on one), nominal cycles, card-language semantics
(the instruction word is the parameter ``op``) and hand-derived vectors. MIPS has no flags. The IR is compiled
by ``cardmodel isa build mips32``.

Sources read for the data: MIPS32 Architecture for Programmers Volume II (Release 2), the o32 ABI, and public
listings of the Allegrex's own encodings (MADD/MADDU/MSUB/MSUBU, CLZ/CLO and MIN/MAX in SPECIAL; WSBW and
BITREV in SPECIAL3's BSHFL; no SPECIAL2).

    python3 -B tools/gen_mips32.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ["MIPS32 Architecture for Programmers Volume II (Release 2)", "MIPS o32 ABI",
       "public Allegrex (PSP CPU) instruction listings"]
VARIANT = {"mips32r2": 0, "allegrex": 1}

F_R = {"opcode": [31, 26], "rs": [25, 21], "rt": [20, 16], "rd": [15, 11], "sa": [10, 6], "funct": [5, 0]}
F_I = {"opcode": [31, 26], "rs": [25, 21], "rt": [20, 16], "imm": [15, 0]}
F_J = {"opcode": [31, 26], "target": [25, 0]}


def card(name, mask, match, mnem, group, sem, arch="mips32", cycles=1, fields=None, **extra):
    if arch in VARIANT:
        sem = f"if variant != {VARIANT[arch]} {{\n  undefined_op(op)\n  return\n}}\n" + sem.strip()
    c = {"name": name, "category": "isa", "kind": "instruction", "isa": "mips32", "set": "mips", "mask": mask,
         "match": match, "encoding": f"{match:#010x}/{mask:#010x}", "mnemonic": mnem, "group": group,
         "arch": arch, "flags": {}, "cycles": cycles, "bytes": 4, "semantics": sem.strip(),
         "fields": fields or {}, "provenance": {"origin": "cardmodel tools/gen_mips32.py", "sources": SRC}}
    c.update(extra)
    return c


def special(name, funct, mnem, group, sem, mask=0xFC00003F, extra_match=0, **kw):
    return card(name, mask, funct | extra_match, mnem, group, sem, fields=F_R, **kw)


def itype(name, opc, mnem, group, sem, **kw):
    return card(name, 0xFC000000, opc << 26, mnem, group, sem, fields=F_I, **kw)


def regimm(name, rt, mnem, group, sem, **kw):
    return card(name, 0xFC1F0000, (1 << 26) | (rt << 16), mnem, group, sem, fields=F_I, **kw)


RD_RS_RT = "let a = gpr(f_rs(op))\nlet b = gpr(f_rt(op))\n"


def cards() -> list:
    out = []
    # -- shifts ---------------------------------------------------------------------------------------------
    out.append(special("MIPS_SLL", 0x00, "SLL rd, rt, sa", "shift", "wr(f_rd(op), gpr(f_rt(op)) << f_sa(op))",
                       mask=0xFFE0003F, note="SLL r0, r0, 0 is NOP"))
    out.append(special("MIPS_SRL", 0x02, "SRL rd, rt, sa", "shift", "wr(f_rd(op), gpr(f_rt(op)) >> f_sa(op))",
                       mask=0xFFE0003F))
    out.append(special("MIPS_ROTR", 0x02, "ROTR rd, rt, sa", "shift",
                       "wr(f_rd(op), rotr32(gpr(f_rt(op)), f_sa(op)))", mask=0xFFE0003F, extra_match=1 << 21))
    out.append(special("MIPS_SRA", 0x03, "SRA rd, rt, sa", "shift", "wr(f_rd(op), s32(gpr(f_rt(op))) >> f_sa(op))",
                       mask=0xFFE0003F))
    out.append(special("MIPS_SLLV", 0x04, "SLLV rd, rt, rs", "shift",
                       "wr(f_rd(op), gpr(f_rt(op)) << (gpr(f_rs(op)) & 31))", mask=0xFC0007FF))
    out.append(special("MIPS_SRLV", 0x06, "SRLV rd, rt, rs", "shift",
                       "wr(f_rd(op), gpr(f_rt(op)) >> (gpr(f_rs(op)) & 31))", mask=0xFC0007FF))
    out.append(special("MIPS_ROTRV", 0x06, "ROTRV rd, rt, rs", "shift",
                       "wr(f_rd(op), rotr32(gpr(f_rt(op)), gpr(f_rs(op)) & 31))", mask=0xFC0007FF,
                       extra_match=1 << 6))
    out.append(special("MIPS_SRAV", 0x07, "SRAV rd, rt, rs", "shift",
                       "wr(f_rd(op), s32(gpr(f_rt(op))) >> (gpr(f_rs(op)) & 31))", mask=0xFC0007FF))
    # -- jumps through registers, conditional moves, system ----------------------------------------------------
    out.append(special("MIPS_JR", 0x08, "JR rs", "branch", "branch(gpr(f_rs(op)))", mask=0xFC1FF83F, cycles=1))
    out.append(special("MIPS_JALR", 0x09, "JALR rd, rs", "branch", """
let t = gpr(f_rs(op))
link(f_rd(op))
branch(t)""", mask=0xFC1F003F, note="the target is read before the link register is written"))
    out.append(special("MIPS_MOVZ", 0x0A, "MOVZ rd, rs, rt", "move", """
if gpr(f_rt(op)) == 0 {
  wr(f_rd(op), gpr(f_rs(op)))
}""", mask=0xFC0007FF))
    out.append(special("MIPS_MOVN", 0x0B, "MOVN rd, rs, rt", "move", """
if gpr(f_rt(op)) != 0 {
  wr(f_rd(op), gpr(f_rs(op)))
}""", mask=0xFC0007FF))
    out.append(special("MIPS_SYSCALL", 0x0C, "SYSCALL code", "system", "syscall_op((op >> 6) & 0xFFFFF)"))
    out.append(special("MIPS_BREAK", 0x0D, "BREAK code", "system", "break_op((op >> 6) & 0xFFFFF)"))
    out.append(special("MIPS_SYNC", 0x0F, "SYNC", "system", "let k = f_sa(op)", mask=0xFFFFF83F,
                       note="memory ordering: a no-op on a single in-order core"))
    # -- HI/LO -------------------------------------------------------------------------------------------------
    out.append(special("MIPS_MFHI", 0x10, "MFHI rd", "hilo", "wr(f_rd(op), hi)", mask=0xFFFF07FF))
    out.append(special("MIPS_MTHI", 0x11, "MTHI rs", "hilo", "hi = gpr(f_rs(op))", mask=0xFC1FFFFF))
    out.append(special("MIPS_MFLO", 0x12, "MFLO rd", "hilo", "wr(f_rd(op), lo)", mask=0xFFFF07FF))
    out.append(special("MIPS_MTLO", 0x13, "MTLO rs", "hilo", "lo = gpr(f_rs(op))", mask=0xFC1FFFFF))
    out.append(special("MIPS_MULT", 0x18, "MULT rs, rt", "multiply", RD_RS_RT + "lo = mul_lo(a, b)\nhi = smul_hi(a, b)",
                       mask=0xFC00FFFF, cycles=5))
    out.append(special("MIPS_MULTU", 0x19, "MULTU rs, rt", "multiply", RD_RS_RT + "lo = mul_lo(a, b)\nhi = umul_hi(a, b)",
                       mask=0xFC00FFFF, cycles=5))
    out.append(special("MIPS_DIV", 0x1A, "DIV rs, rt", "divide", RD_RS_RT + "div_signed(a, b)", mask=0xFC00FFFF,
                       cycles=36, note="a zero divisor leaves HI and LO unchanged here (UNPREDICTABLE)"))
    out.append(special("MIPS_DIVU", 0x1B, "DIVU rs, rt", "divide", RD_RS_RT + "div_unsigned(a, b)", mask=0xFC00FFFF,
                       cycles=36, note="a zero divisor leaves HI and LO unchanged here (UNPREDICTABLE)"))
    # -- three-register ALU -----------------------------------------------------------------------------------
    alu = {"ADD": (0x20, "add_ov(a, b, f_rd(op))"), "ADDU": (0x21, "wr(f_rd(op), a + b)"),
           "SUB": (0x22, "sub_ov(a, b, f_rd(op))"), "SUBU": (0x23, "wr(f_rd(op), a - b)"),
           "AND": (0x24, "wr(f_rd(op), a & b)"), "OR": (0x25, "wr(f_rd(op), a | b)"),
           "XOR": (0x26, "wr(f_rd(op), a ^ b)"), "NOR": (0x27, "wr(f_rd(op), (a | b) ^ MASK32)"),
           "SLT": (0x2A, "wr(f_rd(op), if s32(a) < s32(b) then 1 else 0)"),
           "SLTU": (0x2B, "wr(f_rd(op), if a < b then 1 else 0)")}
    for name, (f, expr) in alu.items():
        out.append(special(f"MIPS_{name}", f, f"{name} rd, rs, rt", "alu", RD_RS_RT + expr, mask=0xFC0007FF,
                           **({"note": "signed overflow raises Ov and leaves rd unchanged"} if name in ("ADD", "SUB") else {})))
    traps = {"TGE": (0x30, "s32(a) >= s32(b)"), "TGEU": (0x31, "a >= b"), "TLT": (0x32, "s32(a) < s32(b)"),
             "TLTU": (0x33, "a < b"), "TEQ": (0x34, "a == b"), "TNE": (0x36, "a != b")}
    for name, (f, cond) in traps.items():
        out.append(special(f"MIPS_{name}", f, f"{name} rs, rt", "trap", RD_RS_RT + f"trap_if({cond})"))
    # -- Allegrex's own SPECIAL encodings ------------------------------------------------------------------------
    out.append(special("ALLEGREX_CLZ", 0x16, "CLZ rd, rs", "bits", "wr(f_rd(op), clz32(gpr(f_rs(op))))",
                       mask=0xFC1F07FF, arch="allegrex"))
    out.append(special("ALLEGREX_CLO", 0x17, "CLO rd, rs", "bits", "wr(f_rd(op), clz32(gpr(f_rs(op)) ^ MASK32))",
                       mask=0xFC1F07FF, arch="allegrex"))
    for name, f, body in (("MADD", 0x1C, "acc_add(smul_hi(a, b), mul_lo(a, b))"),
                          ("MADDU", 0x1D, "acc_add(umul_hi(a, b), mul_lo(a, b))"),
                          ("MSUB", 0x2E, "acc_sub(smul_hi(a, b), mul_lo(a, b))"),
                          ("MSUBU", 0x2F, "acc_sub(umul_hi(a, b), mul_lo(a, b))")):
        out.append(special(f"ALLEGREX_{name}", f, f"{name} rs, rt", "multiply", RD_RS_RT + body, mask=0xFC00FFFF,
                           arch="allegrex", cycles=5))
    out.append(special("ALLEGREX_MAX", 0x2C, "MAX rd, rs, rt", "alu",
                       RD_RS_RT + "wr(f_rd(op), if s32(a) > s32(b) then a else b)", mask=0xFC0007FF, arch="allegrex"))
    out.append(special("ALLEGREX_MIN", 0x2D, "MIN rd, rs, rt", "alu",
                       RD_RS_RT + "wr(f_rd(op), if s32(a) < s32(b) then a else b)", mask=0xFC0007FF, arch="allegrex"))
    # -- REGIMM branches and traps --------------------------------------------------------------------------------
    for name, rt, cond, likely, lnk in (("BLTZ", 0, "s32(a) < 0", False, False), ("BGEZ", 1, "s32(a) >= 0", False, False),
                                        ("BLTZL", 2, "s32(a) < 0", True, False), ("BGEZL", 3, "s32(a) >= 0", True, False),
                                        ("BLTZAL", 0x10, "s32(a) < 0", False, True),
                                        ("BGEZAL", 0x11, "s32(a) >= 0", False, True),
                                        ("BLTZALL", 0x12, "s32(a) < 0", True, True),
                                        ("BGEZALL", 0x13, "s32(a) >= 0", True, True)):
        out.append(regimm(f"MIPS_{name}", rt, f"{name} rs, offset", "branch", _branch(cond, likely, lnk)))
    for name, rt, cond in (("TGEI", 8, "s32(a) >= s32(b)"), ("TGEIU", 9, "a >= b"), ("TLTI", 0xA, "s32(a) < s32(b)"),
                           ("TLTIU", 0xB, "a < b"), ("TEQI", 0xC, "a == b"), ("TNEI", 0xE, "a != b")):
        out.append(regimm(f"MIPS_{name}", rt, f"{name} rs, imm", "trap",
                          f"let a = gpr(f_rs(op))\nlet b = simm(op)\ntrap_if({cond})"))
    # -- jumps -----------------------------------------------------------------------------------------------------
    jt = "((pc + 4) & 0xF0000000) | ((op & 0x3FFFFFF) << 2)"
    out.append(card("MIPS_J", 0xFC000000, 2 << 26, "J target", "branch", f"branch({jt})", fields=F_J))
    out.append(card("MIPS_JAL", 0xFC000000, 3 << 26, "JAL target", "branch", f"link(31)\nbranch({jt})", fields=F_J))
    # -- branches -----------------------------------------------------------------------------------------------
    for name, opc, cond, likely in (("BEQ", 4, "a == b", False), ("BNE", 5, "a != b", False),
                                    ("BLEZ", 6, "s32(a) <= 0", False), ("BGTZ", 7, "s32(a) > 0", False),
                                    ("BEQL", 0x14, "a == b", True), ("BNEL", 0x15, "a != b", True),
                                    ("BLEZL", 0x16, "s32(a) <= 0", True), ("BGTZL", 0x17, "s32(a) > 0", True)):
        two = name.startswith(("BEQ", "BNE"))
        mask = 0xFC000000 if two else 0xFC1F0000
        out.append(card(f"MIPS_{name}", mask, opc << 26, f"{name} rs, {'rt, ' if two else ''}offset", "branch",
                        _branch(cond, likely, False, two), fields=F_I))
    # -- immediates ---------------------------------------------------------------------------------------------
    imm = {"ADDI": (8, "add_ov(a, simm(op), f_rt(op))"), "ADDIU": (9, "wr(f_rt(op), a + simm(op))"),
           "SLTI": (0xA, "wr(f_rt(op), if s32(a) < s32(simm(op)) then 1 else 0)"),
           "SLTIU": (0xB, "wr(f_rt(op), if a < simm(op) then 1 else 0)"),
           "ANDI": (0xC, "wr(f_rt(op), a & (op & 0xFFFF))"), "ORI": (0xD, "wr(f_rt(op), a | (op & 0xFFFF))"),
           "XORI": (0xE, "wr(f_rt(op), a ^ (op & 0xFFFF))")}
    for name, (opc, expr) in imm.items():
        out.append(itype(f"MIPS_{name}", opc, f"{name} rt, rs, imm", "alu", "let a = gpr(f_rs(op))\n" + expr))
    out.append(card("MIPS_LUI", 0xFFE00000, 0xF << 26, "LUI rt, imm", "alu", "wr(f_rt(op), (op & 0xFFFF) << 16)",
                    fields=F_I))
    # -- SPECIAL2 (MIPS32 only: the Allegrex has its own encodings above) ----------------------------------------
    sp2 = 0x1C << 26
    for name, f, body in (("MADD", 0, "acc_add(smul_hi(a, b), mul_lo(a, b))"),
                          ("MADDU", 1, "acc_add(umul_hi(a, b), mul_lo(a, b))"),
                          ("MSUB", 4, "acc_sub(smul_hi(a, b), mul_lo(a, b))"),
                          ("MSUBU", 5, "acc_sub(umul_hi(a, b), mul_lo(a, b))")):
        out.append(card(f"MIPS_{name}", 0xFC00FFFF, sp2 | f, f"{name} rs, rt", "multiply", RD_RS_RT + body,
                        arch="mips32r2", cycles=5, fields=F_R))
    out.append(card("MIPS_MUL", 0xFC0007FF, sp2 | 2, "MUL rd, rs, rt", "multiply",
                    RD_RS_RT + "wr(f_rd(op), mul_lo(a, b))", arch="mips32r2", cycles=5, fields=F_R,
                    note="HI and LO are UNPREDICTABLE after MUL; here they are left unchanged"))
    out.append(card("MIPS_CLZ", 0xFC0007FF, sp2 | 0x20, "CLZ rd, rs", "bits", "wr(f_rd(op), clz32(gpr(f_rs(op))))",
                    arch="mips32r2", fields=F_R, note="rt must equal rd; not checked"))
    out.append(card("MIPS_CLO", 0xFC0007FF, sp2 | 0x21, "CLO rd, rs", "bits",
                    "wr(f_rd(op), clz32(gpr(f_rs(op)) ^ MASK32))", arch="mips32r2", fields=F_R))
    # -- SPECIAL3: bit fields and byte shuffles --------------------------------------------------------------------
    sp3 = 0x1F << 26
    out.append(card("MIPS_EXT", 0xFC00003F, sp3 | 0, "EXT rt, rs, pos, size", "bits", """
let pos = f_sa(op)
let size = f_rd(op) + 1
if pos + size <= 32 {
  wr(f_rt(op), (gpr(f_rs(op)) >> pos) & ((1 << size) - 1))
}""", fields={**F_R, "msbd": [15, 11], "lsb": [10, 6]}, note="pos + size > 32 is UNPREDICTABLE: rt unchanged here"))
    out.append(card("MIPS_INS", 0xFC00003F, sp3 | 4, "INS rt, rs, pos, size", "bits", """
let lsb = f_sa(op)
let msb = f_rd(op)
if msb >= lsb {
  let m = (((1 << (msb - lsb + 1)) - 1) << lsb) & MASK32
  let t = f_rt(op)
  wr(t, (gpr(t) & (m ^ MASK32)) | ((gpr(f_rs(op)) << lsb) & m))
}""", fields={**F_R, "msb": [15, 11], "lsb": [10, 6]}, note="msb < lsb is UNPREDICTABLE: rt unchanged here"))
    bsh = sp3 | 0x20
    for name, sa, expr, arch in (("WSBH", 2, "((v & 0x00FF00FF) << 8) | ((v >> 8) & 0x00FF00FF)", "mips32"),
                                 ("SEB", 0x10, "sx8(v)", "mips32"), ("SEH", 0x18, "sx16(v)", "mips32"),
                                 ("WSBW", 3, "bswap32(v)", "allegrex"), ("BITREV", 0x14, "bitrev32(v)", "allegrex")):
        prefix = "ALLEGREX" if arch == "allegrex" else "MIPS"
        out.append(card(f"{prefix}_{name}", 0xFFE007FF, bsh | (sa << 6), f"{name} rd, rt", "bits",
                        f"let v = gpr(f_rt(op))\nwr(f_rd(op), {expr})", arch=arch, fields=F_R))
    # -- loads and stores ---------------------------------------------------------------------------------------
    def align(n, code):
        return f"let a = ea(op)\nif (a & {n}) != 0 {{\n  exception({code}, a)\n}} else {{\n"

    out.append(itype("MIPS_LB", 0x20, "LB rt, offset(rs)", "load", "wr(f_rt(op), sx8(rd8(ea(op))))", cycles=2))
    out.append(itype("MIPS_LBU", 0x24, "LBU rt, offset(rs)", "load", "wr(f_rt(op), rd8(ea(op)))", cycles=2))
    out.append(itype("MIPS_LH", 0x21, "LH rt, offset(rs)", "load", align(1, "EXC_ADEL") + "  wr(f_rt(op), sx16(rd16(a)))\n}", cycles=2))
    out.append(itype("MIPS_LHU", 0x25, "LHU rt, offset(rs)", "load", align(1, "EXC_ADEL") + "  wr(f_rt(op), rd16(a))\n}", cycles=2))
    out.append(itype("MIPS_LW", 0x23, "LW rt, offset(rs)", "load", align(3, "EXC_ADEL") + "  wr(f_rt(op), rd32(a))\n}", cycles=2))
    out.append(itype("MIPS_LL", 0x30, "LL rt, offset(rs)", "load",
                     align(3, "EXC_ADEL") + "  wr(f_rt(op), rd32(a))\n  llbit = 1\n}", cycles=2))
    out.append(itype("MIPS_SB", 0x28, "SB rt, offset(rs)", "store", "wr8(ea(op), gpr(f_rt(op)) & 0xFF)"))
    out.append(itype("MIPS_SH", 0x29, "SH rt, offset(rs)", "store", align(1, "EXC_ADES") + "  wr16(a, gpr(f_rt(op)) & 0xFFFF)\n}"))
    out.append(itype("MIPS_SW", 0x2B, "SW rt, offset(rs)", "store", align(3, "EXC_ADES") + "  wr32(a, gpr(f_rt(op)))\n}"))
    out.append(itype("MIPS_SC", 0x38, "SC rt, offset(rs)", "store", align(3, "EXC_ADES") + """  let t = f_rt(op)
  if llbit != 0 {
    wr32(a, gpr(t))
    wr(t, 1)
  } else {
    wr(t, 0)
  }
  llbit = 0
}""", note="one core and no interrupts between LL and SC here: SC succeeds whenever LL ran"))
    # unaligned word access, little-endian: LWL/SWL take the high-order bytes, LWR/SWR the low-order ones
    out.append(itype("MIPS_LWL", 0x22, "LWL rt, offset(rs)", "load", """
let a = ea(op)
let k = a & 3
let w = rd32(a - k)
let t = f_rt(op)
wr(t, (gpr(t) & (MASK32 >> (8 * (k + 1)))) | ((w << (8 * (3 - k))) & MASK32))""", cycles=2))
    out.append(itype("MIPS_LWR", 0x26, "LWR rt, offset(rs)", "load", """
let a = ea(op)
let k = a & 3
let w = rd32(a - k)
let t = f_rt(op)
wr(t, (gpr(t) & (MASK32 ^ (MASK32 >> (8 * k)))) | (w >> (8 * k)))""", cycles=2))
    out.append(itype("MIPS_SWL", 0x2A, "SWL rt, offset(rs)", "store", """
let a = ea(op)
let k = a & 3
let w = rd32(a - k)
wr32(a - k, (w & (MASK32 ^ (MASK32 >> (8 * (3 - k))))) | (gpr(f_rt(op)) >> (8 * (3 - k))))""",
                     note="read-merge-write of the aligned word"))
    out.append(itype("MIPS_SWR", 0x2E, "SWR rt, offset(rs)", "store", """
let a = ea(op)
let k = a & 3
let w = rd32(a - k)
let m = (MASK32 << (8 * k)) & MASK32
wr32(a - k, (w & (m ^ MASK32)) | ((gpr(f_rt(op)) << (8 * k)) & m))""", note="read-merge-write of the aligned word"))
    out.append(itype("MIPS_CACHE", 0x2F, "CACHE op, offset(rs)", "system", "let a = ea(op)",
                     note="no cache is modelled: a no-op"))
    out.append(itype("MIPS_PREF", 0x33, "PREF hint, offset(rs)", "system", "let a = ea(op)", arch="mips32r2",
                     note="a hint: a no-op"))
    return out


def _branch(cond: str, likely: bool, lnk: bool, two: bool = False) -> str:
    lines = ["let a = gpr(f_rs(op))"]
    if two:
        lines.append("let b = gpr(f_rt(op))")
    if lnk:
        lines.append("link(31)")
    lines.append(f"if {cond} {{\n  branch_rel(op)\n}}" + (" else {\n  skip_slot()\n}" if likely else ""))
    return "\n".join(lines)


def w(opc=0, rs=0, rt=0, rd=0, sa=0, funct=0) -> int:
    return (opc << 26) | (rs << 21) | (rt << 16) | (rd << 11) | (sa << 6) | funct


def iw(opc, rs, rt, imm) -> int:
    return (opc << 26) | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


# hand-derived known answers (registers in, registers out; mem words little-endian; slot_target after a branch)
VECTORS = {
    "MIPS_ADDU": [{"name": "addu wraps", "op": w(rs=4, rt=5, rd=2, funct=0x21), "in": {"r4": 0xFFFFFFFF, "r5": 2},
                   "out": {"r2": 1}}],
    "MIPS_ADD": [{"name": "add overflows: rd unchanged, Ov raised", "op": w(rs=4, rt=5, rd=2, funct=0x20),
                  "in": {"r4": 0x7FFFFFFF, "r5": 1, "r2": 7}, "out": {"r2": 7, "exc_last": 12}}],
    "MIPS_SUBU": [{"name": "subu 0 - 1", "op": w(rs=0, rt=5, rd=2, funct=0x23), "in": {"r5": 1}, "out": {"r2": 0xFFFFFFFF}}],
    "MIPS_SLT": [{"name": "slt -1 < 1", "op": w(rs=4, rt=5, rd=2, funct=0x2A), "in": {"r4": 0xFFFFFFFF, "r5": 1},
                  "out": {"r2": 1}}],
    "MIPS_SLTU": [{"name": "sltu 0xFFFFFFFF < 1 is false", "op": w(rs=4, rt=5, rd=2, funct=0x2B),
                   "in": {"r4": 0xFFFFFFFF, "r5": 1}, "out": {"r2": 0}}],
    "MIPS_SLTIU": [{"name": "sltiu compares with the sign-extended immediate", "op": iw(0xB, 4, 2, 0xFFFF),
                    "in": {"r4": 5}, "out": {"r2": 1}}],
    "MIPS_SRA": [{"name": "sra keeps the sign", "op": w(rt=4, rd=2, sa=4, funct=3), "in": {"r4": 0x80000000},
                  "out": {"r2": 0xF8000000}}],
    "MIPS_ROTR": [{"name": "rotr 8", "op": w(rs=1, rt=4, rd=2, sa=8, funct=2), "in": {"r4": 0x12345678},
                   "out": {"r2": 0x78123456}}],
    "MIPS_LUI": [{"name": "lui", "op": iw(0xF, 0, 2, 0x8001), "out": {"r2": 0x80010000}}],
    "MIPS_ADDIU": [{"name": "addiu -1", "op": iw(9, 4, 2, 0xFFFF), "in": {"r4": 0}, "out": {"r2": 0xFFFFFFFF}},
                   {"name": "r0 stays zero", "op": iw(9, 4, 0, 1), "in": {"r4": 5}, "out": {"r0": 0}}],
    "MIPS_MULT": [{"name": "mult -2 * 3", "op": w(rs=4, rt=5, funct=0x18), "in": {"r4": 0xFFFFFFFE, "r5": 3},
                   "out": {"lo": 0xFFFFFFFA, "hi": 0xFFFFFFFF}}],
    "MIPS_MULTU": [{"name": "multu max", "op": w(rs=4, rt=5, funct=0x19), "in": {"r4": 0xFFFFFFFF, "r5": 0xFFFFFFFF},
                    "out": {"lo": 1, "hi": 0xFFFFFFFE}}],
    "MIPS_DIV": [{"name": "div -7 / 2 truncates", "op": w(rs=4, rt=5, funct=0x1A), "in": {"r4": 0xFFFFFFF9, "r5": 2},
                  "out": {"lo": 0xFFFFFFFD, "hi": 0xFFFFFFFF}},
                 {"name": "div min / -1", "op": w(rs=4, rt=5, funct=0x1A), "in": {"r4": 0x80000000, "r5": 0xFFFFFFFF},
                  "out": {"lo": 0x80000000, "hi": 0}}],
    "MIPS_DIVU": [{"name": "divu 7 / 2", "op": w(rs=4, rt=5, funct=0x1B), "in": {"r4": 7, "r5": 2},
                   "out": {"lo": 3, "hi": 1}}],
    "MIPS_MADD": [{"name": "madd carries into hi", "op": w(0x1C, 4, 5), "in": {"r4": 1, "r5": 1, "lo": 0xFFFFFFFF, "variant": 0},
                   "out": {"lo": 0, "hi": 1}}],
    "ALLEGREX_MADD": [{"name": "allegrex madd", "op": w(rs=4, rt=5, funct=0x1C), "in": {"r4": 2, "r5": 3, "variant": 1},
                       "out": {"lo": 6, "hi": 0}},
                      {"name": "reserved on MIPS32r2", "op": w(rs=4, rt=5, funct=0x1C), "in": {"r4": 2, "r5": 3, "variant": 0},
                       "out": {"lo": 0, "undef_calls": 1}}],
    "MIPS_MSUBU": [{"name": "msubu borrows", "op": w(0x1C, 4, 5, funct=5), "in": {"r4": 1, "r5": 1, "variant": 0},
                    "out": {"lo": 0xFFFFFFFF, "hi": 0xFFFFFFFF}}],
    "MIPS_MUL": [{"name": "mul", "op": w(0x1C, 4, 5, 2, funct=2), "in": {"r4": 0x10001, "r5": 0x10001, "variant": 0},
                  "out": {"r2": 0x20001}}],
    "MIPS_CLZ": [{"name": "clz 1", "op": w(0x1C, 4, 2, 2, funct=0x20), "in": {"r4": 1, "variant": 0}, "out": {"r2": 31}}],
    "ALLEGREX_MAX": [{"name": "max signed", "op": w(rs=4, rt=5, rd=2, funct=0x2C), "in": {"r4": 0xFFFFFFFF, "r5": 1, "variant": 1},
                      "out": {"r2": 1}}],
    "ALLEGREX_BITREV": [{"name": "bitrev 1", "op": w(0x1F, 0, 4, 2, 0x14, 0x20), "in": {"r4": 1, "variant": 1},
                         "out": {"r2": 0x80000000}}],
    "ALLEGREX_WSBW": [{"name": "wsbw", "op": w(0x1F, 0, 4, 2, 3, 0x20), "in": {"r4": 0x11223344, "variant": 1},
                       "out": {"r2": 0x44332211}}],
    "MIPS_WSBH": [{"name": "wsbh", "op": w(0x1F, 0, 4, 2, 2, 0x20), "in": {"r4": 0x11223344}, "out": {"r2": 0x22114433}}],
    "MIPS_SEB": [{"name": "seb", "op": w(0x1F, 0, 4, 2, 0x10, 0x20), "in": {"r4": 0x180}, "out": {"r2": 0xFFFFFF80}}],
    "MIPS_EXT": [{"name": "ext bits 4..11", "op": w(0x1F, 4, 2, 7, 4, 0), "in": {"r4": 0xABCD}, "out": {"r2": 0xBC}}],
    "MIPS_INS": [{"name": "ins 8 bits at 8", "op": w(0x1F, 4, 2, 15, 8, 4), "in": {"r4": 0xAB, "r2": 0x11223344},
                  "out": {"r2": 0x1122AB44}}],
    "MIPS_LW": [{"name": "lw", "op": iw(0x23, 4, 2, 4), "in": {"r4": 0x100}, "mem": {"0x104": 0xDEADBEEF},
                 "out": {"r2": 0xDEADBEEF}},
                {"name": "lw unaligned raises AdEL", "op": iw(0x23, 4, 2, 1), "in": {"r4": 0x100, "r2": 9},
                 "out": {"r2": 9, "exc_last": 4}}],
    "MIPS_LB": [{"name": "lb sign-extends", "op": iw(0x20, 4, 2, 0), "in": {"r4": 0x100}, "mem": {"0x100": 0x80},
                 "out": {"r2": 0xFFFFFF80}}],
    "MIPS_LWL": [{"name": "lwl k=1 (little-endian)", "op": iw(0x22, 4, 2, 1), "in": {"r4": 0x100, "r2": 0xAABBCCDD},
                  "mem": {"0x100": 0x44332211}, "out": {"r2": 0x2211CCDD}}],
    "MIPS_LWR": [{"name": "lwr k=1 (little-endian)", "op": iw(0x26, 4, 2, 1), "in": {"r4": 0x100, "r2": 0xAABBCCDD},
                  "mem": {"0x100": 0x44332211}, "out": {"r2": 0xAA443322}}],
    "MIPS_SWL": [{"name": "swl k=1", "op": iw(0x2A, 4, 2, 1), "in": {"r4": 0x100, "r2": 0xAABBCCDD},
                  "mem": {"0x100": 0x44332211}, "mem_out": {"0x100": 0x4433AABB}}],
    "MIPS_SWR": [{"name": "swr k=1", "op": iw(0x2E, 4, 2, 1), "in": {"r4": 0x100, "r2": 0xAABBCCDD},
                  "mem": {"0x100": 0x44332211}, "mem_out": {"0x100": 0xBBCCDD11}}],
    "MIPS_SW": [{"name": "sw", "op": iw(0x2B, 4, 2, 8), "in": {"r4": 0x200, "r2": 0x01020304},
                 "mem_out": {"0x208": 0x01020304}}],
    "MIPS_BEQ": [{"name": "beq taken: the slot runs, then the target", "op": iw(4, 4, 5, 3), "in": {"pc": 0x1000, "r4": 1, "r5": 1},
                  "out": {"pc": 0x1004, "in_slot": 1, "slot_target": 0x1010}},
                 {"name": "beq backwards", "op": iw(4, 0, 0, 0xFFFF), "in": {"pc": 0x1000}, "out": {"slot_target": 0x1000}}],
    "MIPS_BNEL": [{"name": "bnel not taken skips its slot", "op": iw(0x15, 4, 5, 3), "in": {"pc": 0x1000, "r4": 1, "r5": 1},
                   "out": {"pc": 0x1008, "in_slot": 0}}],
    "MIPS_BGEZAL": [{"name": "bal links pc+8", "op": (1 << 26) | (0x11 << 16) | 4, "in": {"pc": 0x1000},
                     "out": {"r31": 0x1008, "slot_target": 0x1014}}],
    "MIPS_JAL": [{"name": "jal", "op": (3 << 26) | (0x2000 >> 2), "in": {"pc": 0x10001000},
                  "out": {"r31": 0x10001008, "slot_target": 0x10002000}}],
    "MIPS_JALR": [{"name": "jalr rd = rs reads the target first", "op": w(rs=31, rd=31, funct=9),
                   "in": {"pc": 0x1000, "r31": 0x4000}, "out": {"r31": 0x1008, "slot_target": 0x4000}}],
    "MIPS_SYSCALL": [{"name": "syscall code", "op": (5 << 6) | 0xC, "out": {"sys_last": 5}}],
}


def main() -> int:
    cs = cards()
    names = [c["name"] for c in cs]
    assert len(set(names)) == len(names), [n for n in names if names.count(n) > 1]
    missing = set(VECTORS) - set(names)
    assert not missing, missing
    for c in cs:
        if c["name"] in VECTORS:
            c["vectors"] = VECTORS[c["name"]]
        c["priority"] = bin(c["mask"]).count("1")
    out = ROOT / "cards" / "isa" / "_pack_mips32.jsonl"
    old = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                old[d["name"]] = d
    lines = []
    for c in cs:
        if c["name"] in old and "ir" in old[c["name"]] and old[c["name"]].get("semantics") == c["semantics"]:
            c["ir"] = old[c["name"]]["ir"]
        lines.append(json.dumps(c, sort_keys=True, ensure_ascii=False))
    out.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    print(f"wrote {len(cs)} cards to {out.relative_to(ROOT)}; now run: cardmodel isa build mips32")
    return 0


if __name__ == "__main__":
    sys.exit(main())
