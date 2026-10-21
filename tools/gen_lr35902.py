"""gen_lr35902 — BUILD-TIME: write the LR35902 instruction cards (cards/isa/_pack_lr35902.jsonl).

The opcode table has a regular structure (x = op >> 6, y = (op >> 3) & 7, z = op & 7, p = y >> 1, q = y & 1),
so the 512 cards (256 base + 256 CB-prefixed) are expanded from the templates below. Each card carries its data
(mnemonic, bytes, T-cycles, M-cycle bus activity, flag effects) and its semantics in the card language; the IR is
compiled afterwards by `cardmodel isa build lr35902` (the cards are then the source of truth: this script only
re-creates them from scratch).

Sources for the data: the Pan Docs opcode tables and Gekkio's "Game Boy: Complete Technical Reference" (cycle
by cycle bus activity), read for this purpose; nothing is copied verbatim.

    python3 -B tools/gen_lr35902.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

R8 = ["B", "C", "D", "E", "H", "L", "(HL)", "A"]
RP = ["BC", "DE", "HL", "SP"]
RP2 = ["BC", "DE", "HL", "AF"]
CC = ["NZ", "Z", "NC", "C"]
CC_FN = {"NZ": "cond_nz()", "Z": "cond_z()", "NC": "cond_nc()", "C": "cond_c()"}
GET16 = {"BC": "bc()", "DE": "de()", "HL": "hl()", "SP": "SP", "AF": "af()"}
SET16 = {"BC": "set_bc({v})", "DE": "set_de({v})", "HL": "set_hl({v})", "SP": "SP = {v}", "AF": "set_af({v})"}
ALU = [("ADD", "ADD A,{s}", "alu_add({v}, 0)", "Z0HC"), ("ADC", "ADC A,{s}", "alu_add({v}, carry())", "Z0HC"),
       ("SUB", "SUB {s}", "alu_sub({v}, 0)", "Z1HC"), ("SBC", "SBC A,{s}", "alu_sub({v}, carry())", "Z1HC"),
       ("AND", "AND {s}", "alu_and({v})", "Z010"), ("XOR", "XOR {s}", "alu_xor({v})", "Z000"),
       ("OR", "OR {s}", "alu_or({v})", "Z000"), ("CP", "CP {s}", "alu_cp({v})", "Z1HC")]
ROT = [("RLC", "rlc({v}, true)"), ("RRC", "rrc({v}, true)"), ("RL", "rl({v}, true)"), ("RR", "rr({v}, true)"),
       ("SLA", "sla({v})"), ("SRA", "sra({v})"), ("SWAP", "swap({v})"), ("SRL", "srl({v})")]
ILLEGAL = {0xD3, 0xDB, 0xDD, 0xE3, 0xE4, 0xEB, 0xEC, 0xED, 0xF4, 0xFC, 0xFD}


def flags(spec: str) -> dict:
    """'Z0HC' style (Pan Docs order Z N H C): a letter = computed, 0/1 = forced, - = unchanged."""
    out = {}
    for name, ch in zip("ZNHC", spec):
        out[name] = "*" if ch.isalpha() else ch
    return out


def card(op: int, mnem: str, group: str, sem: str, mc, fl: str = "----", nbytes: int = 1, prefix=None,
         operands=None, **extra) -> dict:
    name = f"LR35902_CB_{op:02X}" if prefix else f"LR35902_{op:02X}"
    if isinstance(mc, dict):
        cycles = {k: 4 * len(v) for k, v in mc.items()}
    else:
        cycles = 4 * len(mc)
    c = {"name": name, "category": "isa", "kind": "instruction", "isa": "lr35902", "opcode": op,
         "prefix": prefix, "encoding": (f"CB {op:02X}" if prefix else f"{op:02X}"), "mnemonic": mnem,
         "group": group, "bytes": nbytes, "cycles": cycles, "mcycles": mc, "flags": flags(fl),
         "semantics": sem.strip(), "operands": operands or [],
         "provenance": {"origin": "cardmodel tools/gen_lr35902.py",
                        "sources": ["Pan Docs (CPU instruction set, opcode tables)",
                                    "Gekkio, Game Boy: Complete Technical Reference (M-cycle bus activity)"]}}
    c.update(extra)
    return c


def r8_read(r: str) -> tuple[str, list]:
    """(expression, extra M-cycles) to read operand r."""
    if r == "(HL)":
        return "rd8(hl())", ["read:HL"]
    return r, []


def base(op: int) -> dict:
    x, y, z, p, q = op >> 6, (op >> 3) & 7, op & 7, (op >> 3) >> 1 & 3, (op >> 3) & 1
    F = ["fetch:PC"]
    if op in ILLEGAL:
        return card(op, f"ILLEGAL_{op:02X}", "illegal", "hang()", F, illegal=True,
                    statement="an unused opcode: the CPU locks up until reset")
    if x == 0:
        if z == 0:
            if y == 0:
                return card(op, "NOP", "misc", "", F)
            if y == 1:
                return card(op, "LD (nn),SP", "ld16", """
let a = fetch16()
wr8(a, SP & 0xFF)
wr8((a + 1) & 0xFFFF, (SP >> 8) & 0xFF)""", F + ["read:PC+1", "read:PC+2", "write:nn", "write:nn+1"], nbytes=3)
            if y == 2:
                return card(op, "STOP", "misc", "PC = (PC + 1) & 0xFFFF\nstop()", F, nbytes=2,
                            statement="STOP: low-power stop until a button is pressed, or the CGB speed switch "
                                      "when KEY1 bit 0 is set; the second byte is read and ignored",
                            timing_note="the speed switch and stop mode add machine-dependent time (see the "
                                        "machine card)")
            if y == 3:
                return card(op, "JR e", "jump", """
let e = fetch8()
idle()
PC = (PC + sext8(e)) & 0xFFFF""", F + ["read:PC+1", "internal"], nbytes=2)
            cc = CC[y - 4]
            return card(op, f"JR {cc},e", "jump", f"""
let e = fetch8()
if {CC_FN[cc]} {{
  idle()
  PC = (PC + sext8(e)) & 0xFFFF
}}""", {"taken": F + ["read:PC+1", "internal"], "not_taken": F + ["read:PC+1"]}, nbytes=2, condition=cc)
        if z == 1:
            if q == 0:
                return card(op, f"LD {RP[p]},nn", "ld16", SET16[RP[p]].format(v="fetch16()"),
                            F + ["read:PC+1", "read:PC+2"], nbytes=3)
            return card(op, f"ADD HL,{RP[p]}", "alu16", f"add_hl({GET16[RP[p]]})\nidle()", F + ["internal"],
                        "-0HC")
        if z == 2:
            target = ["BC", "DE", "HL", "HL"][p]
            addr = GET16[target]
            post = {2: "\nset_hl((hl() + 1) & 0xFFFF)", 3: "\nset_hl((hl() - 1) & 0xFFFF)"}.get(p, "")
            ptxt = ["(BC)", "(DE)", "(HL+)", "(HL-)"][p]
            if q == 0:
                return card(op, f"LD {ptxt},A", "ld8", f"wr8({addr}, A){post}", F + [f"write:{target}"])
            return card(op, f"LD A,{ptxt}", "ld8", f"A = rd8({addr}){post}", F + [f"read:{target}"])
        if z == 3:
            r = RP[p]
            if q == 0:
                return card(op, f"INC {r}", "alu16", SET16[r].format(v=f"({GET16[r]} + 1) & 0xFFFF") + "\nidle()",
                            F + ["internal"])
            return card(op, f"DEC {r}", "alu16", SET16[r].format(v=f"({GET16[r]} - 1) & 0xFFFF") + "\nidle()",
                        F + ["internal"])
        if z in (4, 5):
            fn, mn, fl = ("inc8", "INC", "Z0H-") if z == 4 else ("dec8", "DEC", "Z1H-")
            r = R8[y]
            if r == "(HL)":
                return card(op, f"{mn} (HL)", "alu8", f"let v = rd8(hl())\nwr8(hl(), {fn}(v))",
                            F + ["read:HL", "write:HL"], fl)
            return card(op, f"{mn} {r}", "alu8", f"{r} = {fn}({r})", F, fl)
        if z == 6:
            r = R8[y]
            if r == "(HL)":
                return card(op, "LD (HL),n", "ld8", "let n = fetch8()\nwr8(hl(), n)",
                            F + ["read:PC+1", "write:HL"], nbytes=2)
            return card(op, f"LD {r},n", "ld8", f"{r} = fetch8()", F + ["read:PC+1"], nbytes=2)
        if z == 7:
            table = [("RLCA", "A = rlc(A, false)", "000C"), ("RRCA", "A = rrc(A, false)", "000C"),
                     ("RLA", "A = rl(A, false)", "000C"), ("RRA", "A = rr(A, false)", "000C"),
                     ("DAA", "daa()", "Z-0C"), ("CPL", "A = A ^ 0xFF\nF = F | FN | FH", "-11-"),
                     ("SCF", "F = (F & FZ) | FC", "-001"), ("CCF", "F = (F & FZ) | ((F & FC) ^ FC)", "-00C")]
            mn, sem, fl = table[y]
            return card(op, mn, "rot" if y < 4 else "misc", sem, F, fl)
    if x == 1:
        if op == 0x76:
            return card(op, "HALT", "misc", "halt()", F,
                        statement="HALT: wait for an interrupt; with IME = 0 and an interrupt already pending the "
                                  "CPU does not halt and the next byte is fetched twice (the HALT bug)")
        dst, src = R8[y], R8[z]
        if src == "(HL)":
            return card(op, f"LD {dst},(HL)", "ld8", f"{dst} = rd8(hl())", F + ["read:HL"])
        if dst == "(HL)":
            return card(op, f"LD (HL),{src}", "ld8", f"wr8(hl(), {src})", F + ["write:HL"])
        return card(op, f"LD {dst},{src}", "ld8", "" if dst == src else f"{dst} = {src}", F)
    if x == 2:
        _, mn, sem, fl = ALU[y]
        v, extra = r8_read(R8[z])
        return card(op, mn.format(s=R8[z]), "alu8", sem.format(v=v), F + extra, fl)
    # x == 3
    if z == 0:
        if y < 4:
            cc = CC[y]
            return card(op, f"RET {cc}", "ret", f"""
idle()
if {CC_FN[cc]} {{
  PC = pop16()
  idle()
}}""", {"taken": F + ["internal", "read:SP", "read:SP+1", "internal"], "not_taken": F + ["internal"]},
                        condition=cc)
        if y == 4:
            return card(op, "LDH (n),A", "ld8", "let n = fetch8()\nwr8(0xFF00 | n, A)",
                        F + ["read:PC+1", "write:FF00+n"], nbytes=2)
        if y == 5:
            return card(op, "ADD SP,e", "alu16", "let e = fetch8()\nSP = add_sp(e)\nidle()\nidle()",
                        F + ["read:PC+1", "internal", "internal"], "00HC", nbytes=2)
        if y == 6:
            return card(op, "LDH A,(n)", "ld8", "let n = fetch8()\nA = rd8(0xFF00 | n)",
                        F + ["read:PC+1", "read:FF00+n"], nbytes=2)
        return card(op, "LD HL,SP+e", "ld16", "let e = fetch8()\nset_hl(add_sp(e))\nidle()",
                    F + ["read:PC+1", "internal"], "00HC", nbytes=2)
    if z == 1:
        if q == 0:
            r = RP2[p]
            return card(op, f"POP {r}", "stack", SET16[r].format(v="pop16()"), F + ["read:SP", "read:SP+1"],
                        "ZNHC" if r == "AF" else "----")
        if p == 0:
            return card(op, "RET", "ret", "PC = pop16()\nidle()", F + ["read:SP", "read:SP+1", "internal"])
        if p == 1:
            return card(op, "RETI", "ret", "PC = pop16()\nidle()\nime = 1\nime_delay = 0",
                        F + ["read:SP", "read:SP+1", "internal"])
        if p == 2:
            return card(op, "JP HL", "jump", "PC = hl()", F)
        return card(op, "LD SP,HL", "ld16", "SP = hl()\nidle()", F + ["internal"])
    if z == 2:
        if y < 4:
            cc = CC[y]
            return card(op, f"JP {cc},nn", "jump", f"""
let a = fetch16()
if {CC_FN[cc]} {{
  idle()
  PC = a
}}""", {"taken": F + ["read:PC+1", "read:PC+2", "internal"], "not_taken": F + ["read:PC+1", "read:PC+2"]},
                        nbytes=3, condition=cc)
        if y == 4:
            return card(op, "LD (C),A", "ld8", "wr8(0xFF00 | C, A)", F + ["write:FF00+C"])
        if y == 5:
            return card(op, "LD (nn),A", "ld8", "let a = fetch16()\nwr8(a, A)",
                        F + ["read:PC+1", "read:PC+2", "write:nn"], nbytes=3)
        if y == 6:
            return card(op, "LD A,(C)", "ld8", "A = rd8(0xFF00 | C)", F + ["read:FF00+C"])
        return card(op, "LD A,(nn)", "ld8", "let a = fetch16()\nA = rd8(a)",
                    F + ["read:PC+1", "read:PC+2", "read:nn"], nbytes=3)
    if z == 3:
        if y == 0:
            return card(op, "JP nn", "jump", "let a = fetch16()\nidle()\nPC = a",
                        F + ["read:PC+1", "read:PC+2", "internal"], nbytes=3)
        if y == 1:
            return card(op, "PREFIX CB", "prefix", "cb_dispatch(fetch8())", F, nbytes=2,
                        statement="the CB prefix: the next byte selects one of the 256 LR35902_CB_* cards, whose "
                                  "cycles and mcycles include this prefix byte's fetch", prefix_of="cb")
        if y == 6:
            return card(op, "DI", "misc", "ime = 0\nime_delay = 0", F)
        return card(op, "EI", "misc", "if ime == 0 and ime_delay == 0 {\n  ime_delay = 2\n}", F,
                    statement="EI: IME turns on after the next instruction; an EI while that is pending (or IME is "
                              "on) changes nothing, so a run of EIs lets an interrupt in after the second (EI; DI "
                              "never does)")
    if z == 4:
        cc = CC[y]
        return card(op, f"CALL {cc},nn", "call", f"""
let a = fetch16()
if {CC_FN[cc]} {{
  idle()
  push16(PC)
  PC = a
}}""", {"taken": F + ["read:PC+1", "read:PC+2", "internal", "write:SP-1", "write:SP-2"],
        "not_taken": F + ["read:PC+1", "read:PC+2"]}, nbytes=3, condition=cc)
    if z == 5:
        if q == 0:
            r = RP2[p]
            return card(op, f"PUSH {r}", "stack", f"idle()\npush16({GET16[r]})",
                        F + ["internal", "write:SP-1", "write:SP-2"])
        return card(op, "CALL nn", "call", "let a = fetch16()\nidle()\npush16(PC)\nPC = a",
                    F + ["read:PC+1", "read:PC+2", "internal", "write:SP-1", "write:SP-2"], nbytes=3)
    if z == 6:
        _, mn, sem, fl = ALU[y]
        return card(op, mn.format(s="n"), "alu8", sem.format(v="fetch8()"), F + ["read:PC+1"], fl, nbytes=2)
    return card(op, f"RST {y * 8:02X}h", "call", f"idle()\npush16(PC)\nPC = 0x{y * 8:02X}",
                F + ["internal", "write:SP-1", "write:SP-2"])


def cb(op: int) -> dict:
    x, y, z = op >> 6, (op >> 3) & 7, op & 7
    r = R8[z]
    F = ["fetch:PC", "fetch:PC+1"]
    v, rd = r8_read(r)
    if x == 0:
        mn, fn = ROT[y]
        fl = "Z00C" if mn != "SWAP" else "Z000"
        if r == "(HL)":
            return card(op, f"{mn} (HL)", "cb_rot", f"let v = rd8(hl())\nwr8(hl(), {fn.format(v='v')})",
                        F + ["read:HL", "write:HL"], fl, nbytes=2, prefix=0xCB)
        return card(op, f"{mn} {r}", "cb_rot", f"{r} = {fn.format(v=r)}", F, fl, nbytes=2, prefix=0xCB)
    if x == 1:
        return card(op, f"BIT {y},{r}", "cb_bit", f"bit_test({y}, {v})", F + rd, "Z01-", nbytes=2, prefix=0xCB)
    mn, expr = ("RES", f"{{v}} & 0x{0xFF ^ (1 << y):02X}") if x == 2 else ("SET", f"{{v}} | 0x{1 << y:02X}")
    if r == "(HL)":
        return card(op, f"{mn} {y},(HL)", "cb_bit", f"let v = rd8(hl())\nwr8(hl(), {expr.format(v='v')})",
                    F + ["read:HL", "write:HL"], nbytes=2, prefix=0xCB)
    return card(op, f"{mn} {y},{r}", "cb_bit", f"{r} = {expr.format(v=r)}", F, nbytes=2, prefix=0xCB)


# Known answers, worked out by hand from the flag rules (PC = 0xC000, SP = 0xD000 unless given; "mem" bytes are
# placed before the run, "mem_out" bytes are expected after it).
VECTORS = {
    (None, 0x27): [
        {"name": "daa after add 0x45+0x38", "in": {"A": 0x7D, "F": 0x00}, "out": {"A": 0x83, "F": 0x00}},
        {"name": "daa wraps to zero", "in": {"A": 0x9A, "F": 0x00}, "out": {"A": 0x00, "F": 0x90}},
        {"name": "daa after sub with half borrow", "in": {"A": 0x0F, "F": 0x60}, "out": {"A": 0x09, "F": 0x40}},
        {"name": "daa after sub with borrow", "in": {"A": 0x00, "F": 0x50}, "out": {"A": 0xA0, "F": 0x50}}],
    (None, 0xE8): [
        {"name": "add sp,+1 carries both", "in": {"SP": 0x00FF}, "mem": {"0xC001": 0x01},
         "out": {"SP": 0x0100, "F": 0x30}},
        {"name": "add sp,-1 no carries", "in": {"SP": 0x1000}, "mem": {"0xC001": 0xFF}, "out": {"SP": 0x0FFF, "F": 0x00}},
        {"name": "add sp,-1 to zero, Z stays 0", "in": {"SP": 0x0001, "F": 0x80}, "mem": {"0xC001": 0xFF},
         "out": {"SP": 0x0000, "F": 0x30}}],
    (None, 0xF8): [{"name": "ld hl,sp+2", "in": {"SP": 0xFFF8}, "mem": {"0xC001": 0x02},
                    "out": {"H": 0xFF, "L": 0xFA, "F": 0x00, "SP": 0xFFF8}}],
    (None, 0x98): [{"name": "sbc borrows through zero", "in": {"A": 0x10, "B": 0x0F, "F": 0x10},
                    "out": {"A": 0x00, "F": 0xE0}}],
    (None, 0x88): [{"name": "adc half carry from carry-in", "in": {"A": 0x0F, "B": 0x00, "F": 0x10},
                    "out": {"A": 0x10, "F": 0x20}},
                   {"name": "adc wraps", "in": {"A": 0xFF, "B": 0x00, "F": 0x10}, "out": {"A": 0x00, "F": 0xB0}}],
    (None, 0x1F): [{"name": "rra out", "in": {"A": 0x01, "F": 0x00}, "out": {"A": 0x00, "F": 0x10}},
                   {"name": "rra in", "in": {"A": 0x00, "F": 0x10}, "out": {"A": 0x80, "F": 0x00}}],
    (None, 0x2F): [{"name": "cpl", "in": {"A": 0x35, "F": 0x90}, "out": {"A": 0xCA, "F": 0xF0}}],
    (None, 0x3F): [{"name": "ccf clears", "in": {"F": 0xF0}, "out": {"F": 0x80}},
                   {"name": "ccf sets", "in": {"F": 0x00}, "out": {"F": 0x10}}],
    (None, 0x37): [{"name": "scf", "in": {"F": 0xE0}, "out": {"F": 0x90}}],
    (None, 0x34): [{"name": "inc (hl) half carry", "in": {"H": 0xC1, "L": 0x00, "F": 0x10},
                    "mem": {"0xC100": 0x0F}, "mem_out": {"0xC100": 0x10}, "out": {"F": 0x30}}],
    (None, 0x05): [{"name": "dec b half borrow", "in": {"B": 0x10, "F": 0x00}, "out": {"B": 0x0F, "F": 0x60}},
                   {"name": "dec b to zero", "in": {"B": 0x01, "F": 0x00}, "out": {"B": 0x00, "F": 0xC0}}],
    (None, 0xFE): [{"name": "cp half borrow", "in": {"A": 0x3C}, "mem": {"0xC001": 0x2F},
                    "out": {"A": 0x3C, "F": 0x60}},
                   {"name": "cp equal", "in": {"A": 0x3C}, "mem": {"0xC001": 0x3C}, "out": {"F": 0xC0}},
                   {"name": "cp borrow", "in": {"A": 0x3C}, "mem": {"0xC001": 0x40}, "out": {"F": 0x50}}],
    (0xCB, 0x37): [{"name": "swap a", "in": {"A": 0xF0}, "out": {"A": 0x0F, "F": 0x00}},
                   {"name": "swap zero", "in": {"A": 0x00, "F": 0x30}, "out": {"F": 0x80}}],
    (0xCB, 0x7C): [{"name": "bit 7,h set", "in": {"H": 0x80, "F": 0x10}, "out": {"F": 0x30}},
                   {"name": "bit 7,h clear", "in": {"H": 0x00, "F": 0x00}, "out": {"F": 0xA0}}],
    (0xCB, 0x2F): [{"name": "sra keeps bit 7", "in": {"A": 0x81}, "out": {"A": 0xC0, "F": 0x10}}],
    (0xCB, 0x11): [{"name": "rl c to zero", "in": {"C": 0x80, "F": 0x00}, "out": {"C": 0x00, "F": 0x90}}],
    (None, 0xF1): [{"name": "pop af masks F", "in": {"SP": 0xD000}, "mem": {"0xD000": 0xFF, "0xD001": 0x12},
                    "out": {"A": 0x12, "F": 0xF0, "SP": 0xD002}}],
    (None, 0xC5): [{"name": "push bc", "in": {"B": 0x12, "C": 0x34},
                    "mem_out": {"0xCFFF": 0x12, "0xCFFE": 0x34}, "out": {"SP": 0xCFFE}}],
    (None, 0x18): [{"name": "jr -2 loops", "mem": {"0xC001": 0xFE}, "out": {"PC": 0xC000, "now": 12}}],
    (None, 0x29): [{"name": "add hl,hl carry", "in": {"H": 0x80, "L": 0x00, "F": 0x80},
                    "out": {"H": 0x00, "L": 0x00, "F": 0x90}}],
    (None, 0xFF): [{"name": "rst 38", "mem_out": {"0xCFFF": 0xC0, "0xCFFE": 0x01}, "out": {"PC": 0x38, "SP": 0xCFFE}}],
    (None, 0xCD): [{"name": "call nn", "mem": {"0xC001": 0x34, "0xC002": 0x12},
                    "mem_out": {"0xCFFF": 0xC0, "0xCFFE": 0x03}, "out": {"PC": 0x1234, "SP": 0xCFFE, "now": 24}}],
    (None, 0xC9): [{"name": "ret", "in": {"SP": 0xCFFE}, "mem": {"0xCFFE": 0x03, "0xCFFF": 0xC0},
                    "out": {"PC": 0xC003, "SP": 0xD000, "now": 16}}],
    (None, 0x08): [{"name": "ld (nn),sp", "in": {"SP": 0xABCD}, "mem": {"0xC001": 0x00, "0xC002": 0xC1},
                    "mem_out": {"0xC100": 0xCD, "0xC101": 0xAB}}],
    (None, 0x2A): [{"name": "ld a,(hl+)", "in": {"H": 0xC0, "L": 0xFF}, "mem": {"0xC0FF": 0x5A},
                    "out": {"A": 0x5A, "H": 0xC1, "L": 0x00}}],
}


def main() -> int:
    cards = [base(op) for op in range(256)] + [cb(op) for op in range(256)]
    for c in cards:
        vs = VECTORS.get((c["prefix"], c["opcode"]))
        if vs:
            c["vectors"] = vs
    names = [c["name"] for c in cards]
    assert len(set(names)) == 512
    out = ROOT / "cards" / "isa" / "_pack_lr35902.jsonl"
    old = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                old[d["name"]] = d
    lines = []
    for c in cards:
        if c["name"] in old and "ir" in old[c["name"]] and old[c["name"]].get("semantics") == c["semantics"]:
            c["ir"] = old[c["name"]]["ir"]          # keep compiled IR when the semantics did not change
        lines.append(json.dumps(c, sort_keys=True, ensure_ascii=False))
    out.write_text("\n".join(sorted(lines)) + "\n", encoding="utf-8")      # the order store.save_pack writes
    print(f"wrote {len(lines)} cards to {out.relative_to(ROOT)}; now run: cardmodel isa build lr35902")
    return 0


if __name__ == "__main__":
    sys.exit(main())
