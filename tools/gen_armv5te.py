"""gen_armv5te — BUILD-TIME: write the ARMv5TE / ARMv4T instruction cards (cards/isa/_pack_armv5te.jsonl).

One card per instruction form of the ARM and Thumb sets: an encoding (mask/match, field layout), the ISA level
(v4t, or v5te for the ARMv5TE additions), nominal ARM946E-S cycles, flag effects as data (N Z C V: '*' computed,
'S' computed when the S bit is set, '-' unchanged), card-language semantics (the instruction word is the
parameter `op`) and hand-derived vectors. The IR is compiled by `cardmodel isa build armv5te`.

Sources read for the data: the ARM Architecture Reference Manual (ARMv5TE), the ARM946E-S and ARM7TDMI
Technical Reference Manuals (cycle counts, nominal), GBATEK (the DS/GBA view of the same cores).

    python3 -B tools/gen_armv5te.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DP = ["AND", "EOR", "SUB", "RSB", "ADD", "ADC", "SBC", "RSC", "TST", "TEQ", "CMP", "CMN", "ORR", "MOV", "BIC", "MVN"]
SRC = ["ARM Architecture Reference Manual (ARMv5TE)", "ARM946E-S / ARM7TDMI Technical Reference Manuals",
       "GBATEK (Nintendo DS technical information)"]


def card(name, iset, mask, match, mnem, group, sem, arch="v4t", flags="----", cycles=1, fields=None, **extra):
    fl = {k: c for k, c in zip("NZCV", flags)}
    c = {"name": name, "category": "isa", "kind": "instruction", "isa": "armv5te", "set": iset, "mask": mask,
         "match": match, "encoding": f"{match:#010x}/{mask:#010x}" if iset == "arm" else f"{match:#06x}/{mask:#06x}",
         "mnemonic": mnem, "group": group, "arch": arch, "flags": fl, "cycles": cycles,
         "bytes": 4 if iset == "arm" else 2, "semantics": sem.strip(), "fields": fields or {},
         "provenance": {"origin": "cardmodel tools/gen_armv5te.py", "sources": SRC}}
    c.update(extra)
    return c


def v5(sem: str) -> str:
    return "if arch < 5 {\n  undefined_op(op)\n  return\n}\n" + sem.strip()


# -- ARM ---------------------------------------------------------------------------------------------------
def dp_sem(o: int, form: str) -> str:
    name = DP[o]
    lines = ["let rd = (op >> 12) & 0xF", "let rn = (op >> 16) & 0xF", "let s = ((op >> 20) & 1) != 0"]
    if form == "imm":
        lines.append("let b = op2_imm(op)")
        lines.append("let a = rr(rn)")
    else:
        lines.append("let b = op2_reg(op)")
        lines.append("var a = rr(rn)")
        if form == "rsr":
            lines.append("if rn == 15 {\n  a = (a + 4) & MASK32\n}")
    fl = "s and rd != 15"
    expr = {
        "AND": f"a & b", "EOR": f"a ^ b", "ORR": "a | b", "BIC": "a & (b ^ MASK32)", "MOV": "b",
        "MVN": "b ^ MASK32"}
    if name in expr:
        lines.append(f"let res = {expr[name]}")
        lines.append(f"logic_flags(res, {fl})")
    elif name in ("TST", "TEQ"):
        lines.append(f"logic_flags({'a & b' if name == 'TST' else 'a ^ b'}, true)")
        return "\n".join(lines)
    elif name in ("CMP", "CMN"):
        lines.append(f"let res = {'subs(a, b, 1, true)' if name == 'CMP' else 'adds(a, b, 0, true)'}")
        return "\n".join(lines)
    else:
        call = {"SUB": "subs(a, b, 1, {f})", "RSB": "subs(b, a, 1, {f})", "ADD": "adds(a, b, 0, {f})",
                "ADC": "adds(a, b, flag_c(), {f})", "SBC": "subs(a, b, flag_c(), {f})",
                "RSC": "subs(b, a, flag_c(), {f})"}[name]
        lines.append("let cin = flag_c()" if "flag_c" in call else "")
        lines.append(f"let res = {call.replace('flag_c()', 'cin').format(f=fl)}")
    lines.append("if rd == 15 and s {\n  restore_cpsr()\n  branch(res)\n} else {\n  wr(rd, res)\n}")
    return "\n".join(x for x in lines if x)


def arm_cards() -> list:
    out = []
    for o, name in enumerate(DP):
        cmp = 8 <= o <= 11
        sbit = 1 << 20 if cmp else 0
        flags = "***-" if name in ("AND", "EOR", "ORR", "BIC", "MOV", "MVN") else "****"
        if cmp:
            flags = "***-" if name in ("TST", "TEQ") else "****"
        else:
            flags = flags.replace("*", "S")
        for form, mask, match, cyc, mn in (
                ("imm", 0x0FE00000 | sbit, 0x02000000 | (o << 21) | sbit, 1, f"{name}{{cond}}{{S}} Rd, Rn, #imm"),
                ("rsi", 0x0FE00010 | sbit, (o << 21) | sbit, 1, f"{name}{{cond}}{{S}} Rd, Rn, Rm, shift #n"),
                ("rsr", 0x0FE00090 | sbit, 0x00000010 | (o << 21) | sbit, 2, f"{name}{{cond}}{{S}} Rd, Rn, Rm, shift Rs")):
            out.append(card(f"ARM_{name}_{form}", "arm", mask, match, mn, "data_processing", dp_sem(o, form),
                            flags=flags, cycles=cyc,
                            fields={"cond": [31, 28], "opcode": [24, 21], "S": [20, 20], "Rn": [19, 16], "Rd": [15, 12],
                                    "operand2": [11, 0]},
                            note="Rd = R15 adds 2 cycles (a branch); with S it also copies SPSR to CPSR"))
    out.append(card("ARM_MRS", "arm", 0x0FBF0FFF, 0x010F0000, "MRS{cond} Rd, CPSR|SPSR", "psr", """
let rd = (op >> 12) & 0xF
if ((op >> 22) & 1) != 0 {
  wr(rd, spsr)
} else {
  wr(rd, cpsr)
}""", cycles=2))
    msr = """
let fm = (op >> 16) & 0xF
var m = 0
if (fm & 1) != 0 {
  m = m | 0xFF
}
if (fm & 2) != 0 {
  m = m | 0xFF00
}
if (fm & 4) != 0 {
  m = m | 0xFF0000
}
if (fm & 8) != 0 {
  m = m | 0xFF000000
}
if ((op >> 22) & 1) != 0 {
  spsr = (spsr & (MASK32 ^ m)) | (v & m)
} else {
  if (cpsr & 0x1F) == M_USR {
    m = m & 0xFF000000
  }
  set_cpsr((cpsr & (MASK32 ^ m)) | (v & m))
}"""
    out.append(card("ARM_MSR_imm", "arm", 0x0FB0F000, 0x0320F000, "MSR{cond} CPSR|SPSR_fields, #imm", "psr",
                    "let v = op2_imm(op)" + msr, flags="****", cycles=1,
                    note="flags change only when the f field is written"))
    out.append(card("ARM_MSR_reg", "arm", 0x0FB0FFF0, 0x0120F000, "MSR{cond} CPSR|SPSR_fields, Rm", "psr",
                    "let v = rr(op & 0xF)" + msr, flags="****", cycles=1))
    out.append(card("ARM_BX", "arm", 0x0FFFFFF0, 0x012FFF10, "BX{cond} Rm", "branch", "bx(rr(op & 0xF))", cycles=3))
    out.append(card("ARM_BLX_reg", "arm", 0x0FFFFFF0, 0x012FFF30, "BLX{cond} Rm", "branch", v5("""
let t = rr(op & 0xF)
regs[14] = (pc + 4) & MASK32
bx(t)"""), arch="v5te", cycles=3))
    out.append(card("ARM_CLZ", "arm", 0x0FFF0FF0, 0x016F0F10, "CLZ{cond} Rd, Rm", "misc", v5("""
var v = rr(op & 0xF)
var n = 0
if v == 0 {
  n = 32
} else {
  if (v & 0xFFFF0000) == 0 {
    n += 16
    v = (v << 16) & MASK32
  }
  if (v & 0xFF000000) == 0 {
    n += 8
    v = (v << 8) & MASK32
  }
  if (v & 0xF0000000) == 0 {
    n += 4
    v = (v << 4) & MASK32
  }
  if (v & 0xC0000000) == 0 {
    n += 2
    v = (v << 2) & MASK32
  }
  if (v & 0x80000000) == 0 {
    n += 1
  }
}
wr((op >> 12) & 0xF, n)"""), arch="v5te"))
    for i, (name, expr) in enumerate((("QADD", "sat32(s32(a) + s32(b))"), ("QSUB", "sat32(s32(a) - s32(b))"),
                                      ("QDADD", "sat32(s32(a) + s32(sat32(2 * s32(b))))"),
                                      ("QDSUB", "sat32(s32(a) - s32(sat32(2 * s32(b))))"))):
        out.append(card(f"ARM_{name}", "arm", 0x0FF00FF0, 0x01000050 | (i << 21), f"{name}{{cond}} Rd, Rm, Rn",
                        "saturating", v5(f"""
let a = rr(op & 0xF)
let b = rr((op >> 16) & 0xF)
wr((op >> 12) & 0xF, {expr})"""), arch="v5te", note="sets the sticky Q flag on saturation"))
    out.append(card("ARM_BKPT", "arm", 0xFFF000F0, 0xE1200070, "BKPT #imm", "misc", v5("undefined_op(op)"),
                    arch="v5te", note="a prefetch abort (a debugger breakpoint); here: undefined_op"))
    out.append(card("ARM_SMLAxy", "arm", 0x0FF00090, 0x01000080, "SMLA<x><y>{cond} Rd, Rm, Rs, Rn", "dsp_multiply", v5("""
let p = half(rr(op & 0xF), (op >> 5) & 1) * half(rr((op >> 8) & 0xF), (op >> 6) & 1)
let res = p + s32(rr((op >> 12) & 0xF))
if res > 0x7FFFFFFF or res < -0x80000000 {
  cpsr = cpsr | FLAG_Q
}
wr((op >> 16) & 0xF, res & MASK32)"""), arch="v5te"))
    out.append(card("ARM_SMLAWy", "arm", 0x0FF000B0, 0x01200080, "SMLAW<y>{cond} Rd, Rm, Rs, Rn", "dsp_multiply", v5("""
let p = (s32(rr(op & 0xF)) * half(rr((op >> 8) & 0xF), (op >> 6) & 1)) >> 16
let res = p + s32(rr((op >> 12) & 0xF))
if res > 0x7FFFFFFF or res < -0x80000000 {
  cpsr = cpsr | FLAG_Q
}
wr((op >> 16) & 0xF, res & MASK32)"""), arch="v5te"))
    out.append(card("ARM_SMULWy", "arm", 0x0FF000B0, 0x012000A0, "SMULW<y>{cond} Rd, Rm, Rs", "dsp_multiply", v5("""
let p = (s32(rr(op & 0xF)) * half(rr((op >> 8) & 0xF), (op >> 6) & 1)) >> 16
wr((op >> 16) & 0xF, p & MASK32)"""), arch="v5te"))
    out.append(card("ARM_SMLALxy", "arm", 0x0FF00090, 0x01400080, "SMLAL<x><y>{cond} RdLo, RdHi, Rm, Rs",
                    "dsp_multiply", v5("""
let p = half(rr(op & 0xF), (op >> 5) & 1) * half(rr((op >> 8) & 0xF), (op >> 6) & 1)
let lo_i = (op >> 12) & 0xF
let hi_i = (op >> 16) & 0xF
let lo = regs[lo_i] + (p & MASK32)
let hi = regs[hi_i] + (if p < 0 then MASK32 else 0) + (lo >> 32)
regs[lo_i] = lo & MASK32
regs[hi_i] = hi & MASK32"""), arch="v5te", cycles=2))
    out.append(card("ARM_SMULxy", "arm", 0x0FF00090, 0x01600080, "SMUL<x><y>{cond} Rd, Rm, Rs", "dsp_multiply", v5("""
let p = half(rr(op & 0xF), (op >> 5) & 1) * half(rr((op >> 8) & 0xF), (op >> 6) & 1)
wr((op >> 16) & 0xF, p & MASK32)"""), arch="v5te"))
    mul_fields = {"S": [20, 20], "Rd": [19, 16], "Rn": [15, 12], "Rs": [11, 8], "Rm": [3, 0]}
    out.append(card("ARM_MUL", "arm", 0x0FE000F0, 0x00000090, "MUL{cond}{S} Rd, Rm, Rs", "multiply", """
let res = mul_lo(rr(op & 0xF), rr((op >> 8) & 0xF))
wr((op >> 16) & 0xF, res)
if ((op >> 20) & 1) != 0 {
  set_nz(res)
}""", flags="SS--", cycles=2, fields=mul_fields))
    out.append(card("ARM_MLA", "arm", 0x0FE000F0, 0x00200090, "MLA{cond}{S} Rd, Rm, Rs, Rn", "multiply", """
let res = (mul_lo(rr(op & 0xF), rr((op >> 8) & 0xF)) + rr((op >> 12) & 0xF)) & MASK32
wr((op >> 16) & 0xF, res)
if ((op >> 20) & 1) != 0 {
  set_nz(res)
}""", flags="SS--", cycles=2, fields=mul_fields))
    for name, match, hi_fn, acc in (("UMULL", 0x00800090, "umul_hi", False), ("UMLAL", 0x00A00090, "umul_hi", True),
                                    ("SMULL", 0x00C00090, "smul_hi", False), ("SMLAL", 0x00E00090, "smul_hi", True)):
        body = f"""
let a = rr(op & 0xF)
let b = rr((op >> 8) & 0xF)
let lo_i = (op >> 12) & 0xF
let hi_i = (op >> 16) & 0xF
var lo = mul_lo(a, b)
var hi = {hi_fn}(a, b)
"""
        if acc:
            body += """let sum = lo + regs[lo_i]
lo = sum & MASK32
hi = (hi + regs[hi_i] + (sum >> 32)) & MASK32
"""
        body += """regs[lo_i] = lo
regs[hi_i] = hi
if ((op >> 20) & 1) != 0 {
  set_nz(hi)
  if lo != 0 {
    cpsr = cpsr & (MASK32 ^ FLAG_Z)
  }
}"""
        out.append(card(f"ARM_{name}", "arm", 0x0FE000F0, match, f"{name}{{cond}}{{S}} RdLo, RdHi, Rm, Rs",
                        "multiply", body, flags="SS--", cycles=3,
                        fields={"S": [20, 20], "RdHi": [19, 16], "RdLo": [15, 12], "Rs": [11, 8], "Rm": [3, 0]}))
    for name, b in (("SWP", 0), ("SWPB", 1)):
        out.append(card(f"ARM_{name}", "arm", 0x0FF00FF0, 0x01000090 | (b << 22), f"{name}{{cond}} Rd, Rm, [Rn]",
                        "swap", f"""
let a = rr((op >> 16) & 0xF)
let v = rr(op & 0xF)
{'let t = rd8(a)' if b else 'let t = load32_rot(a)'}
{'wr8(a, v & 0xFF)' if b else 'wr32(a & 0xFFFFFFFC, v)'}
wr((op >> 12) & 0xF, t)""", cycles=2))
    # halfword / signed / doubleword transfers
    for name, lbit, sh, kind in (("STRH", 0, 1, "st16"), ("LDRH", 1, 1, "ld16"), ("LDRSB", 1, 2, "lds8"),
                                 ("LDRSH", 1, 3, "lds16"), ("LDRD", 0, 2, "ldd"), ("STRD", 0, 3, "std")):
        for form, ibit in (("imm", 1), ("reg", 0)):
            off = "((op >> 4) & 0xF0) | (op & 0xF)" if ibit else "rr(op & 0xF)"
            sem = f"""
let rn = (op >> 16) & 0xF
let rd = (op >> 12) & 0xF
let p = ((op >> 24) & 1) != 0
let u = ((op >> 23) & 1) != 0
let w = ((op >> 21) & 1) != 0
let off = {off}
let base = rr(rn)
let addr = if u then (base + off) & MASK32 else (base - off) & MASK32
let ea = if p then addr else base
"""
            if kind == "st16":
                sem += "wr16(ea & 0xFFFFFFFE, rr(rd) & 0xFFFF)\nif not p or w {\n  wr(rn, addr)\n}"
            elif kind == "std":
                sem += ("wr32(ea & 0xFFFFFFFC, rr(rd & 14))\nwr32((ea + 4) & 0xFFFFFFFC, rr((rd & 14) + 1))\n"
                        "if not p or w {\n  wr(rn, addr)\n}")
            else:
                load = {"ld16": "var v = rd16(ea & 0xFFFFFFFE)\nif arch < 5 and (ea & 1) != 0 {\n  v = ror32(v, 8)\n}",
                        "lds8": "let v = sext(rd8(ea), 8) & MASK32",
                        "lds16": "var v = sext(rd16(ea & 0xFFFFFFFE), 16) & MASK32\nif arch < 5 and (ea & 1) != 0 {\n  v = sext(rd8(ea), 8) & MASK32\n}",
                        "ldd": "let v = rd32(ea & 0xFFFFFFFC)\nlet v2 = rd32((ea + 4) & 0xFFFFFFFC)"}[kind]
                sem += load + "\nif (not p or w) and rn != rd {\n  wr(rn, addr)\n}\n"
                if kind == "ldd":
                    sem += "regs[rd & 14] = v\nwr((rd & 14) + 1, v2)"
                else:
                    sem += "wr(rd, v)"
            if kind in ("ldd", "std"):
                sem = v5(sem)
            out.append(card(f"ARM_{name}_{form}", "arm", 0x0E5000F0, (lbit << 20) | (ibit << 22) | 0x90 | (sh << 5),
                            f"{name}{{cond}} Rd, [Rn, {'#off' if ibit else 'Rm'}]{{!}}", "load_store_extra", sem,
                            arch="v5te" if kind in ("ldd", "std") else "v4t", cycles=1 if kind[0] == "s" else 2,
                            fields={"P": [24, 24], "U": [23, 23], "I": [22, 22], "W": [21, 21], "L": [20, 20],
                                    "Rn": [19, 16], "Rd": [15, 12]}))
    # single data transfer
    for name, lbit, bbit in (("STR", 0, 0), ("LDR", 1, 0), ("STRB", 0, 1), ("LDRB", 1, 1)):
        for form, ibit in (("imm", 0), ("reg", 1)):
            off = "op & 0xFFF" if not ibit else "shift_imm(rr(op & 0xF), (op >> 5) & 3, (op >> 7) & 0x1F)"
            sem = f"""
let rn = (op >> 16) & 0xF
let rd = (op >> 12) & 0xF
let p = ((op >> 24) & 1) != 0
let u = ((op >> 23) & 1) != 0
let w = ((op >> 21) & 1) != 0
let off = {off}
let base = rr(rn)
let addr = if u then (base + off) & MASK32 else (base - off) & MASK32
let ea = if p then addr else base
"""
            if lbit:
                sem += ("let v = rd8(ea)" if bbit else "let v = load32_rot(ea)") + \
                    "\nif (not p or w) and rn != rd {\n  wr(rn, addr)\n}\nif rd == 15 {\n  load_pc(v)\n} else {\n  wr(rd, v)\n}"
            else:
                sem += "var v = rr(rd)\nif rd == 15 {\n  v = (v + 4) & MASK32\n}\n" + \
                    ("wr8(ea, v & 0xFF)" if bbit else "wr32(ea & 0xFFFFFFFC, v)") + \
                    "\nif not p or w {\n  wr(rn, addr)\n}"
            out.append(card(f"ARM_{name}_{form}", "arm", 0x0E500010 if ibit else 0x0E500000,
                            0x04000000 | (ibit << 25) | (bbit << 22) | (lbit << 20),
                            f"{name}{{cond}} Rd, [Rn, {'Rm, shift' if ibit else '#off'}]{{!}}", "load_store", sem,
                            cycles=1 if not lbit else 2,
                            fields={"P": [24, 24], "U": [23, 23], "B": [22, 22], "W": [21, 21], "L": [20, 20],
                                    "Rn": [19, 16], "Rd": [15, 12], "offset": [11, 0]},
                            note="a load into R15 adds 4 cycles and (ARMv5) interworks"))
    block = """
let rn = (op >> 16) & 0xF
let lst = op & 0xFFFF
let p = ((op >> 24) & 1) != 0
let u = ((op >> 23) & 1) != 0
let sb = ((op >> 22) & 1) != 0
let w = ((op >> 21) & 1) != 0
let n = popcount16(lst)
let base = rr(rn)
var size = n * 4
if n == 0 {
  size = 0x40
}
var a = base
if u {
  if p {
    a = (base + 4) & MASK32
  }
} else {
  if p {
    a = (base - size) & MASK32
  } else {
    a = (base - size + 4) & MASK32
  }
}
let newbase = if u then (base + size) & MASK32 else (base - size) & MASK32
"""
    ldm = block + """let user = sb and (lst & 0x8000) == 0
if w and (lst & (1 << rn)) == 0 {
  regs[rn] = newbase
}
for i in 0 .. 16 {
  if ((lst >> i) & 1) != 0 {
    let v = rd32(a & 0xFFFFFFFC)
    if i == 15 {
      if sb {
        restore_cpsr()
      }
      load_pc(v)
    } elif user {
      set_user_reg(i, v)
    } else {
      regs[i] = v
    }
    a = (a + 4) & MASK32
  }
}"""
    stm = block + """for i in 0 .. 16 {
  if ((lst >> i) & 1) != 0 {
    var v = rr(i)
    if sb {
      v = user_reg(i)
    }
    if i == 15 {
      v = (v + 4) & MASK32
    }
    wr32(a & 0xFFFFFFFC, v)
    a = (a + 4) & MASK32
  }
}
if w {
  regs[rn] = newbase
}"""
    out.append(card("ARM_LDM", "arm", 0x0E100000, 0x08100000, "LDM{cond}{IA|IB|DA|DB} Rn{!}, {list}{^}", "block", ldm,
                    cycles=2, note="cycles: n + 1 (+ 2 when PC is loaded); with the S bit and no PC in the list the "
                                   "registers are the user bank's; with PC, CPSR = SPSR",
                    fields={"P": [24, 24], "U": [23, 23], "S": [22, 22], "W": [21, 21], "Rn": [19, 16], "list": [15, 0]}))
    out.append(card("ARM_STM", "arm", 0x0E100000, 0x08000000, "STM{cond}{IA|IB|DA|DB} Rn{!}, {list}{^}", "block", stm,
                    cycles=2, note="cycles: n; with the S bit the user bank's registers are stored",
                    fields={"P": [24, 24], "U": [23, 23], "S": [22, 22], "W": [21, 21], "Rn": [19, 16], "list": [15, 0]}))
    out.append(card("ARM_B", "arm", 0x0F000000, 0x0A000000, "B{cond} target", "branch",
                    "branch((rr(15) + sext(op & 0xFFFFFF, 24) * 4) & MASK32)", cycles=3))
    out.append(card("ARM_BL", "arm", 0x0F000000, 0x0B000000, "BL{cond} target", "branch", """
let t = (rr(15) + sext(op & 0xFFFFFF, 24) * 4) & MASK32
regs[14] = (pc + 4) & MASK32
branch(t)""", cycles=3))
    out.append(card("ARM_BLX_imm", "arm", 0xFE000000, 0xFA000000, "BLX target", "branch", v5("""
let t = (rr(15) + sext(op & 0xFFFFFF, 24) * 4 + ((op >> 24) & 1) * 2) & MASK32
regs[14] = (pc + 4) & MASK32
cpsr = cpsr | FLAG_T
next_pc = t"""), arch="v5te", cycles=3, unconditional=True))
    out.append(card("ARM_PLD", "arm", 0xFD70F000, 0xF550F000, "PLD [Rn, #off]", "misc", v5(""), arch="v5te",
                    unconditional=True, note="a cache hint: no architectural effect"))
    out.append(card("ARM_MRC", "arm", 0x0F100010, 0x0E100010, "MRC{cond} p#, op1, Rd, CRn, CRm, op2", "coprocessor", """
let rd = (op >> 12) & 0xF
let v = cp_read(op)
if rd == 15 {
  cpsr = (cpsr & 0x0FFFFFFF) | (v & 0xF0000000)
} else {
  wr(rd, v)
}""", flags="****", cycles=2, note="CP15 (system control) on the ARM9; other coprocessors are the machine's call; "
                                       "with Rd = R15 the top four bits set N Z C V"))
    out.append(card("ARM_MCR", "arm", 0x0F100010, 0x0E000010, "MCR{cond} p#, op1, Rd, CRn, CRm, op2", "coprocessor",
                    "cp_write(op, rr((op >> 12) & 0xF))", cycles=2))
    out.append(card("ARM_CDP", "arm", 0x0F000010, 0x0E000000, "CDP{cond} ...", "coprocessor", "undefined_op(op)",
                    note="no coprocessor data operations on the DS"))
    out.append(card("ARM_LDC_STC", "arm", 0x0E000000, 0x0C000000, "LDC/STC{cond} ...", "coprocessor",
                    "undefined_op(op)", note="no coprocessor transfers on the DS"))
    out.append(card("ARM_SWI", "arm", 0x0F000000, 0x0F000000, "SWI{cond} #imm24", "exception",
                    "swi(op & 0xFFFFFF)", cycles=3, note="the BIOS call number is bits 23-16 on the DS"))
    return out


# -- Thumb -------------------------------------------------------------------------------------------------
def thumb_cards() -> list:
    out = []
    t = lambda *a, **k: out.append(card(*a, **k))         # noqa: E731
    for i, name in enumerate(("LSL", "LSR", "ASR")):
        t(f"THUMB_{name}_imm", "thumb", 0xF800, i << 11, f"{name}S Rd, Rs, #n", "shift", f"""
let rd = op & 7
let res = shift_imm(regs[(op >> 3) & 7], {i}, (op >> 6) & 0x1F)
set_nz(res)
set_c(sh_c)
regs[rd] = res""", flags="***-")
    for i, (name, operand, fn) in enumerate((("ADD_reg", "regs[(op >> 6) & 7]", "adds(a, b, 0, true)"),
                                              ("SUB_reg", "regs[(op >> 6) & 7]", "subs(a, b, 1, true)"),
                                              ("ADD_imm3", "(op >> 6) & 7", "adds(a, b, 0, true)"),
                                              ("SUB_imm3", "(op >> 6) & 7", "subs(a, b, 1, true)"))):
        t(f"THUMB_{name}", "thumb", 0xFE00, 0x1800 | (i << 9), name.replace("_", " "), "add_sub", f"""
let a = regs[(op >> 3) & 7]
let b = {operand}
regs[op & 7] = {fn}""", flags="****")
    for i, (name, body, fl) in enumerate((
            ("MOV", "regs[rd] = v\nset_nz(v)", "**--"), ("CMP", "let x = subs(regs[rd], v, 1, true)", "****"),
            ("ADD", "regs[rd] = adds(regs[rd], v, 0, true)", "****"), ("SUB", "regs[rd] = subs(regs[rd], v, 1, true)", "****"))):
        t(f"THUMB_{name}_imm8", "thumb", 0xF800, 0x2000 | (i << 11), f"{name} Rd, #imm8", "imm8",
          f"let rd = (op >> 8) & 7\nlet v = op & 0xFF\n{body}", flags=fl)
    alu = ["AND", "EOR", "LSL", "LSR", "ASR", "ADC", "SBC", "ROR", "TST", "NEG", "CMP", "CMN", "ORR", "MUL", "BIC", "MVN"]
    for i, name in enumerate(alu):
        a, b = "regs[rd]", "regs[(op >> 3) & 7]"
        body = {
            "AND": f"let res = {a} & {b}\nregs[rd] = res\nset_nz(res)", "EOR": f"let res = {a} ^ {b}\nregs[rd] = res\nset_nz(res)",
            "LSL": f"let res = shift_reg({a}, 0, {b})\nregs[rd] = res\nset_nz(res)\nset_c(sh_c)",
            "LSR": f"let res = shift_reg({a}, 1, {b})\nregs[rd] = res\nset_nz(res)\nset_c(sh_c)",
            "ASR": f"let res = shift_reg({a}, 2, {b})\nregs[rd] = res\nset_nz(res)\nset_c(sh_c)",
            "ADC": f"let cin = flag_c()\nregs[rd] = adds({a}, {b}, cin, true)",
            "SBC": f"let cin = flag_c()\nregs[rd] = subs({a}, {b}, cin, true)",
            "ROR": f"let res = shift_reg({a}, 3, {b})\nregs[rd] = res\nset_nz(res)\nset_c(sh_c)",
            "TST": f"set_nz({a} & {b})", "NEG": f"regs[rd] = subs(0, {b}, 1, true)",
            "CMP": f"let x = subs({a}, {b}, 1, true)", "CMN": f"let x = adds({a}, {b}, 0, true)",
            "ORR": f"let res = {a} | {b}\nregs[rd] = res\nset_nz(res)",
            "MUL": f"let res = mul_lo({a}, {b})\nregs[rd] = res\nset_nz(res)",
            "BIC": f"let res = {a} & ({b} ^ MASK32)\nregs[rd] = res\nset_nz(res)",
            "MVN": f"let res = {b} ^ MASK32\nregs[rd] = res\nset_nz(res)"}[name]
        fl = {"AND": "**--", "EOR": "**--", "TST": "**--", "ORR": "**--", "BIC": "**--", "MVN": "**--", "MUL": "**--",
              "LSL": "***-", "LSR": "***-", "ASR": "***-", "ROR": "***-"}.get(name, "****")
        t(f"THUMB_ALU_{name}", "thumb", 0xFFC0, 0x4000 | (i << 6), f"{name} Rd, Rs", "alu",
          f"let rd = op & 7\n{body}", flags=fl, cycles=2 if name == "MUL" else 1)
    hi = "let rd = (op & 7) | ((op >> 4) & 8)\nlet rs = (op >> 3) & 15\n"
    t("THUMB_ADD_hi", "thumb", 0xFF00, 0x4400, "ADD Rd, Rs (high registers)", "hi_reg",
      hi + "wr(rd, (rr(rd) + rr(rs)) & MASK32)")
    t("THUMB_CMP_hi", "thumb", 0xFF00, 0x4500, "CMP Rd, Rs (high registers)", "hi_reg",
      hi + "let x = subs(rr(rd), rr(rs), 1, true)", flags="****")
    t("THUMB_MOV_hi", "thumb", 0xFF00, 0x4600, "MOV Rd, Rs (high registers)", "hi_reg", hi + "wr(rd, rr(rs))")
    t("THUMB_BX", "thumb", 0xFF80, 0x4700, "BX Rs", "branch", "bx(rr((op >> 3) & 15))", cycles=3)
    t("THUMB_BLX_reg", "thumb", 0xFF80, 0x4780, "BLX Rs", "branch", v5("""
let target = rr((op >> 3) & 15)
regs[14] = (pc + 2) | 1
bx(target)"""), arch="v5te", cycles=3)
    t("THUMB_LDR_pc", "thumb", 0xF800, 0x4800, "LDR Rd, [PC, #imm8*4]", "load_store",
      "regs[(op >> 8) & 7] = rd32((((pc + 4) & 0xFFFFFFFC) + (op & 0xFF) * 4) & MASK32)", cycles=2)
    for i, (name, body) in enumerate((("STR", "wr32(a & 0xFFFFFFFC, regs[rd])"), ("STRH", "wr16(a & 0xFFFFFFFE, regs[rd] & 0xFFFF)"),
                                      ("STRB", "wr8(a, regs[rd] & 0xFF)"), ("LDRSB", "regs[rd] = sext(rd8(a), 8) & MASK32"),
                                      ("LDR", "regs[rd] = load32_rot(a)"),
                                      ("LDRH", "var v = rd16(a & 0xFFFFFFFE)\nif arch < 5 and (a & 1) != 0 {\n  v = ror32(v, 8)\n}\nregs[rd] = v"),
                                      ("LDRB", "regs[rd] = rd8(a)"),
                                      ("LDRSH", "var v = sext(rd16(a & 0xFFFFFFFE), 16) & MASK32\nif arch < 5 and (a & 1) != 0 {\n  v = sext(rd8(a), 8) & MASK32\n}\nregs[rd] = v"))):
        t(f"THUMB_{name}_reg", "thumb", 0xFE00, 0x5000 | (i << 9), f"{name} Rd, [Rb, Ro]", "load_store",
          f"let rd = op & 7\nlet a = (regs[(op >> 3) & 7] + regs[(op >> 6) & 7]) & MASK32\n{body}",
          cycles=1 if name.startswith("STR") else 2)
    for name, match, scale, body in (("STR", 0x6000, 4, "wr32(a & 0xFFFFFFFC, regs[rd])"), ("LDR", 0x6800, 4, "regs[rd] = load32_rot(a)"),
                                     ("STRB", 0x7000, 1, "wr8(a, regs[rd] & 0xFF)"), ("LDRB", 0x7800, 1, "regs[rd] = rd8(a)"),
                                     ("STRH", 0x8000, 2, "wr16(a & 0xFFFFFFFE, regs[rd] & 0xFFFF)"),
                                     ("LDRH", 0x8800, 2, "var v = rd16(a & 0xFFFFFFFE)\nif arch < 5 and (a & 1) != 0 {\n  v = ror32(v, 8)\n}\nregs[rd] = v")):
        t(f"THUMB_{name}_imm5", "thumb", 0xF800, match, f"{name} Rd, [Rb, #imm5*{scale}]", "load_store",
          f"let rd = op & 7\nlet a = (regs[(op >> 3) & 7] + ((op >> 6) & 0x1F) * {scale}) & MASK32\n{body}",
          cycles=1 if name.startswith("STR") else 2)
    t("THUMB_STR_sp", "thumb", 0xF800, 0x9000, "STR Rd, [SP, #imm8*4]", "load_store",
      "wr32((regs[13] + (op & 0xFF) * 4) & 0xFFFFFFFC, regs[(op >> 8) & 7])")
    t("THUMB_LDR_sp", "thumb", 0xF800, 0x9800, "LDR Rd, [SP, #imm8*4]", "load_store",
      "regs[(op >> 8) & 7] = load32_rot((regs[13] + (op & 0xFF) * 4) & MASK32)", cycles=2)
    t("THUMB_ADD_pc", "thumb", 0xF800, 0xA000, "ADD Rd, PC, #imm8*4", "address",
      "regs[(op >> 8) & 7] = (((pc + 4) & 0xFFFFFFFC) + (op & 0xFF) * 4) & MASK32")
    t("THUMB_ADD_sp", "thumb", 0xF800, 0xA800, "ADD Rd, SP, #imm8*4", "address",
      "regs[(op >> 8) & 7] = (regs[13] + (op & 0xFF) * 4) & MASK32")
    t("THUMB_ADD_sp_imm7", "thumb", 0xFF00, 0xB000, "ADD SP, #+-imm7*4", "address", """
let k = (op & 0x7F) * 4
if (op & 0x80) != 0 {
  regs[13] = (regs[13] - k) & MASK32
} else {
  regs[13] = (regs[13] + k) & MASK32
}""")
    t("THUMB_PUSH", "thumb", 0xFE00, 0xB400, "PUSH {list, LR}", "block", """
let lst = (op & 0xFF) | (((op >> 8) & 1) << 14)
let n = popcount16(lst)
var a = (regs[13] - n * 4) & MASK32
regs[13] = a
for i in 0 .. 15 {
  if ((lst >> i) & 1) != 0 {
    wr32(a & 0xFFFFFFFC, regs[i])
    a = (a + 4) & MASK32
  }
}""", cycles=2)
    t("THUMB_POP", "thumb", 0xFE00, 0xBC00, "POP {list, PC}", "block", """
let lst = (op & 0xFF) | (((op >> 8) & 1) << 15)
var a = regs[13]
for i in 0 .. 16 {
  if ((lst >> i) & 1) != 0 {
    let v = rd32(a & 0xFFFFFFFC)
    if i == 15 {
      load_pc(v)
    } else {
      regs[i] = v
    }
    a = (a + 4) & MASK32
  }
}
regs[13] = a""", cycles=2, note="POP {PC} interworks on ARMv5 (it is a branch to ARM state when bit 0 is clear)")
    t("THUMB_STMIA", "thumb", 0xF800, 0xC000, "STMIA Rb!, {list}", "block", """
let rb = (op >> 8) & 7
let lst = op & 0xFF
var a = regs[rb]
for i in 0 .. 8 {
  if ((lst >> i) & 1) != 0 {
    wr32(a & 0xFFFFFFFC, regs[i])
    a = (a + 4) & MASK32
  }
}
if lst == 0 {
  a = (a + 0x40) & MASK32
}
regs[rb] = a""", cycles=2)
    t("THUMB_LDMIA", "thumb", 0xF800, 0xC800, "LDMIA Rb!, {list}", "block", """
let rb = (op >> 8) & 7
let lst = op & 0xFF
var a = regs[rb]
for i in 0 .. 8 {
  if ((lst >> i) & 1) != 0 {
    regs[i] = rd32(a & 0xFFFFFFFC)
    a = (a + 4) & MASK32
  }
}
if lst == 0 {
  a = (a + 0x40) & MASK32
}
if ((lst >> rb) & 1) == 0 {
  regs[rb] = a
}""", cycles=2)
    t("THUMB_UNDEF_DE", "thumb", 0xFF00, 0xDE00, "(undefined, B cond 1110)", "exception", "undefined_op(op)")
    t("THUMB_SWI", "thumb", 0xFF00, 0xDF00, "SWI #imm8", "exception", "swi(op & 0xFF)", cycles=3)
    t("THUMB_B_cond", "thumb", 0xF000, 0xD000, "B<cond> target", "branch", """
if cond_ok((op >> 8) & 0xF) {
  branch((pc + 4 + sext(op & 0xFF, 8) * 2) & MASK32)
}""", cycles=1, note="3 cycles when taken")
    t("THUMB_BKPT", "thumb", 0xFF00, 0xBE00, "BKPT #imm8", "exception", v5("undefined_op(op)"), arch="v5te")
    t("THUMB_B", "thumb", 0xF800, 0xE000, "B target", "branch", "branch((pc + 4 + sext(op & 0x7FF, 11) * 2) & MASK32)",
      cycles=3)
    t("THUMB_BL_prefix", "thumb", 0xF800, 0xF000, "BL (first half)", "branch",
      "regs[14] = (pc + 4 + sext(op & 0x7FF, 11) * 4096) & MASK32")
    t("THUMB_BL_suffix", "thumb", 0xF800, 0xF800, "BL (second half)", "branch", """
let target = (regs[14] + (op & 0x7FF) * 2) & MASK32
regs[14] = (pc + 2) | 1
branch(target)""", cycles=3)
    t("THUMB_BLX_suffix", "thumb", 0xF801, 0xE800, "BLX (second half)", "branch", v5("""
let target = (regs[14] + (op & 0x7FF) * 2) & 0xFFFFFFFC
regs[14] = (pc + 2) | 1
cpsr = cpsr & (MASK32 ^ FLAG_T)
next_pc = target"""), arch="v5te", cycles=3)
    return out


def regs(**kw):
    return {f"r{k[1:]}" if k.startswith("r") and k[1:].isdigit() else k: v for k, v in kw.items()}


# vectors: "op" is the instruction word; registers r0..r15 as "r0".., cpsr/spsr; mem {address: word}
VECTORS = {
    "ARM_ADD_rsi": [
        {"name": "adds overflow", "op": 0xE0910002, "in": {"r1": 0x7FFFFFFF, "r2": 1, "cpsr": 0x13},
         "out": {"r0": 0x80000000, "cpsr": 0x90000013}},
        {"name": "adds carry to zero", "op": 0xE0910002, "in": {"r1": 0xFFFFFFFF, "r2": 1, "cpsr": 0x13},
         "out": {"r0": 0, "cpsr": 0x60000013}}],
    "ARM_SUB_rsi": [{"name": "subs borrow", "op": 0xE0510002, "in": {"r1": 0, "r2": 1, "cpsr": 0x13},
                     "out": {"r0": 0xFFFFFFFF, "cpsr": 0x80000013}}],
    "ARM_CMP_rsi": [{"name": "cmp equal", "op": 0xE1510002, "in": {"r1": 5, "r2": 5, "cpsr": 0x13},
                     "out": {"cpsr": 0x60000013}}],
    "ARM_MOV_rsi": [
        {"name": "movs lsr #32", "op": 0xE1B00021, "in": {"r1": 0x80000000, "cpsr": 0x13}, "out": {"r0": 0, "cpsr": 0x60000013}},
        {"name": "movs rrx", "op": 0xE1B00061, "in": {"r1": 3, "cpsr": 0x20000013}, "out": {"r0": 0x80000001, "cpsr": 0xA0000013}},
        {"name": "mov pc reads +8", "op": 0xE1A0000F, "in": {"pc": 0x1000, "cpsr": 0x13}, "out": {"r0": 0x1008}}],
    "ARM_MOV_rsr": [{"name": "lsl by 33 clears carry", "op": 0xE1B00211, "in": {"r1": 0xFFFFFFFF, "r2": 33, "cpsr": 0x20000013},
                     "out": {"r0": 0, "cpsr": 0x40000013}}],
    "ARM_UMULL": [{"name": "umull max", "op": 0xE0810392, "in": {"r2": 0xFFFFFFFF, "r3": 0xFFFFFFFF, "cpsr": 0x13},
                   "out": {"r0": 1, "r1": 0xFFFFFFFE}}],
    "ARM_SMULL": [{"name": "smull -2*3", "op": 0xE0C10392, "in": {"r2": 0xFFFFFFFE, "r3": 3, "cpsr": 0x13},
                   "out": {"r0": 0xFFFFFFFA, "r1": 0xFFFFFFFF}}],
    "ARM_CLZ": [{"name": "clz 0x10000", "op": 0xE16F0F11, "in": {"r1": 0x10000}, "out": {"r0": 15}},
                {"name": "clz 0", "op": 0xE16F0F11, "in": {"r1": 0}, "out": {"r0": 32}}],
    "ARM_QADD": [{"name": "qadd saturates", "op": 0xE1020051, "in": {"r1": 0x7FFFFFFF, "r2": 1, "cpsr": 0x13},
                  "out": {"r0": 0x7FFFFFFF, "cpsr": 0x08000013}}],
    "ARM_LDR_imm": [{"name": "ldr rotates unaligned", "op": 0xE5910001, "in": {"r1": 0x100}, "mem": {"0x100": 0x11223344},
                     "out": {"r0": 0x44112233}}],
    "ARM_LDM": [{"name": "ldmia r0!, {r1, r2}", "op": 0xE8B00006, "in": {"r0": 0x300}, "mem": {"0x300": 5, "0x304": 6},
                 "out": {"r0": 0x308, "r1": 5, "r2": 6}},
                {"name": "ldmia r0, {r13, r14}^ in SVC loads the user bank", "op": 0xE8D06000,
                 "in": {"r0": 0x300, "r13": 0x111, "r14": 0x222, "cpsr": 0x13}, "mem": {"0x300": 0xAAA, "0x304": 0xBBB},
                 "out": {"r13": 0x111, "r14": 0x222}}],
    "ARM_STM": [{"name": "stmdb sp!, {r0, r1}", "op": 0xE92D0003, "in": {"r0": 7, "r1": 9, "r13": 0x200},
                 "out": {"r13": 0x1F8}, "mem_out": {"0x1f8": 7, "0x1fc": 9}},
                {"name": "stmia r0, {r13}^ in SVC stores the user r13", "op": 0xE8C02000,
                 "in": {"r0": 0x300, "r13": 0x111, "cpsr": 0x13}, "mem_out": {"0x300": 0}}],
    "ARM_BL": [{"name": "bl +8", "op": 0xEB000002, "in": {"pc": 0x1000}, "out": {"r14": 0x1004, "next_pc": 0x1010}}],
    "THUMB_LSL_imm": [{"name": "lsls #0 keeps carry", "op": 0x0008, "in": {"r1": 5, "cpsr": 0x20000033},
                       "out": {"r0": 5, "cpsr": 0x20000033}}],
    "THUMB_ALU_NEG": [{"name": "neg 1", "op": 0x4248, "in": {"r1": 1, "cpsr": 0x33}, "out": {"r0": 0xFFFFFFFF, "cpsr": 0x80000033}}],
    "THUMB_BL_prefix": [{"name": "bl prefix", "op": 0xF000, "in": {"pc": 0x2000, "cpsr": 0x33}, "out": {"r14": 0x2004}}],
    "THUMB_BL_suffix": [{"name": "bl suffix", "op": 0xF804, "in": {"pc": 0x2002, "r14": 0x2004, "cpsr": 0x33},
                         "out": {"r14": 0x2005, "next_pc": 0x200C}}],
    "THUMB_PUSH": [{"name": "push {r0, lr}", "op": 0xB501, "in": {"r0": 1, "r14": 2, "r13": 0x400, "cpsr": 0x33},
                    "out": {"r13": 0x3F8}, "mem_out": {"0x3f8": 1, "0x3fc": 2}}],
}


def main() -> int:
    cards = arm_cards() + thumb_cards()
    names = [c["name"] for c in cards]
    assert len(set(names)) == len(names), [n for n in names if names.count(n) > 1]
    for c in cards:
        if c["name"] in VECTORS:
            c["vectors"] = VECTORS[c["name"]]
        c["priority"] = bin(c["mask"]).count("1")
    out = ROOT / "cards" / "isa" / "_pack_armv5te.jsonl"
    old = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                old[d["name"]] = d
    lines = []
    for c in cards:
        if c["name"] in old and "ir" in old[c["name"]] and old[c["name"]].get("semantics") == c["semantics"]:
            c["ir"] = old[c["name"]]["ir"]
        lines.append(json.dumps(c, sort_keys=True, ensure_ascii=False))
    out.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")
    arm = sum(1 for c in cards if c["set"] == "arm")
    print(f"wrote {len(cards)} cards ({arm} ARM, {len(cards) - arm} Thumb) to {out.relative_to(ROOT)}; "
          f"now run: cardmodel isa build armv5te")
    return 0


if __name__ == "__main__":
    sys.exit(main())
