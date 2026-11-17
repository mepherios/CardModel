"""bench — per-instruction conformance of an ISA's cards, in every engine.

For each instruction card and each seeded random state (registers, 64 KiB of RAM, the instruction's bytes at
PC; both outcomes of a condition), the bench machine (``machine/<isa>_bench``) runs exactly one instruction:

* **engines agree**: the reference interpreter, every requested engine (Python, C, ...) must end in the same
  registers, flags, interrupt state, time, M-cycle trace and memory;
* **timing data holds**: the number of M-cycles equals the card's ``cycles`` (per outcome), and the trace's
  bus activity (fetch/read, write, internal, with addresses) equals the card's ``mcycles``;
* **flag data holds**: a flag marked ``-`` never changes, ``0``/``1`` always end 0/1 (``*``: computed);
* **known answers**: a card's ``vectors`` (input registers -> output registers) hold.

A deliberately wrong card must be caught (tests plant one: CM07).

Honest limits (L1): this checks the cards against their own data and against each other's engines, plus the
hand-derived vectors; it is not an independent oracle of the real CPU. Test ROMs (cpu_instrs, mooneye) are.
"""
from __future__ import annotations

import hashlib
import random
import re

from ..kernel import resources
from . import build as Bd
from . import isa as I
from . import native as N

REGS8 = ("A", "F", "B", "C", "D", "E", "H", "L")
STATE = (*REGS8, "SP", "PC", "ime", "ime_delay", "halted", "halt_bug", "locked", "halt_calls", "stop_calls", "now",
         "ntrace")
KIND = {"fetch": 1, "read": 1, "write": 2, "internal": 3}
FLAG_BIT = {"Z": 0x80, "N": 0x40, "H": 0x20, "C": 0x10}
COND_SET = {"NZ": (0x80, 0), "Z": (0x80, 0x80), "NC": (0x10, 0), "C": (0x10, 0x10)}   # mask, value when taken


def _case_state(rng: random.Random, card, outcome: str | None) -> dict:
    st = {r: rng.randrange(256) for r in REGS8}
    st["F"] &= 0xF0
    st.update(SP=rng.randrange(0x10000), PC=rng.randrange(0x10000), ime=rng.randrange(2), ime_delay=0, halted=0,
              halt_bug=0, locked=0, halt_calls=0, stop_calls=0, now=0, ntrace=0)
    if outcome is not None:
        mask, val = COND_SET[card["condition"]]
        taken = val if outcome == "taken" else val ^ mask
        st["F"] = (st["F"] & ~mask & 0xF0) | taken
    return st


def _code(card) -> list[int]:
    return [card["prefix"], card["opcode"]] if card.get("prefix") is not None else [card["opcode"]]


def run_case(m: N.Machine, card, st: dict, ram: bytes) -> dict:
    """Set the state, place the instruction at PC, run one instruction, read everything back."""
    ram = bytearray(ram)
    for i, b in enumerate(_code(card)):
        ram[(st["PC"] + i) & 0xFFFF] = b
    m.write("ram", bytes(ram))
    for k, v in st.items():
        m.set(k, v)
    m.call("run_one")
    out = {k: m.get(k) for k in STATE}
    n = min(out["ntrace"], 64)
    tk, ta, tv = m.array("trace_kind"), m.array("trace_addr"), m.array("trace_val")
    out["trace"] = [(tk[i], ta[i], tv[i]) for i in range(n)]
    after = m.read("ram")
    writes = {a for k, a, _ in out["trace"] if k == 2}
    expect = bytearray(ram)
    for a in writes:
        expect[a] = after[a]
    out["ram_changes"] = sorted((a, after[a]) for a in writes if after[a] != ram[a])
    out["ram_outside_trace"] = bytes(expect) != after
    out["ram_hash"] = hashlib.sha1(after).hexdigest()
    out["_ram_in"] = ram
    return out


def _addr(token: str, st: dict, ram: bytearray) -> int | None:
    pc, sp = st["PC"], st["SP"]
    pairs = {"HL": (st["H"] << 8) | st["L"], "BC": (st["B"] << 8) | st["C"], "DE": (st["D"] << 8) | st["E"]}
    nn = ram[(pc + 1) & 0xFFFF] | (ram[(pc + 2) & 0xFFFF] << 8)
    table = {"PC": pc, "PC+1": pc + 1, "PC+2": pc + 2, "SP": sp, "SP+1": sp + 1, "SP-1": sp - 1, "SP-2": sp - 2,
             "nn": nn, "nn+1": nn + 1, "FF00+n": 0xFF00 | ram[(pc + 1) & 0xFFFF], "FF00+C": 0xFF00 | st["C"], **pairs}
    v = table.get(token)
    return None if v is None else v & 0xFFFF


def check_data(card, st: dict, out: dict, outcome: str | None) -> list[str]:
    """The card's cycles / mcycles / flags against what one run did."""
    problems = []
    cyc = card["cycles"][outcome] if outcome else card["cycles"]
    mcs = card["mcycles"][outcome] if outcome else card["mcycles"]
    if card.get("prefix_of") or card.get("illegal"):
        return problems
    if out["now"] != cyc:
        problems.append(f"cycles: ran {out['now']}, card says {cyc}")
    kinds = [KIND[t.split(":")[0]] for t in mcs]
    got = [k for k, _, _ in out["trace"]]
    if kinds != got:
        problems.append(f"mcycles: trace {got}, card {kinds} ({mcs})")
    else:
        for t, (k, a, _) in zip(mcs, out["trace"]):
            if ":" in t and k in (1, 2):
                want = _addr(t.split(":", 1)[1], st, out["_ram_in"])
                if want is not None and want != a:
                    problems.append(f"mcycles: {t} accessed {a:#06x}, expected {want:#06x}")
    for flag, code in card["flags"].items():
        bit = FLAG_BIT[flag]
        before, after = st["F"] & bit, out["F"] & bit
        if code == "-" and before != after:
            problems.append(f"flag {flag} marked '-' changed")
        if code == "0" and after:
            problems.append(f"flag {flag} marked '0' is set")
        if code == "1" and not after:
            problems.append(f"flag {flag} marked '1' is clear")
    if out["F"] & 0x0F:
        problems.append("F low nibble is not zero")
    if out["ram_outside_trace"]:
        problems.append("memory changed outside the traced writes")
    return problems


def check_vectors(m: N.Machine, card) -> list[str]:
    problems = []
    for v in card.get("vectors") or []:
        st = {r: 0 for r in REGS8}
        st.update(SP=0xD000, PC=0xC000, ime=0, ime_delay=0, halted=0, halt_bug=0, locked=0, halt_calls=0,
                  stop_calls=0, now=0, ntrace=0)
        st.update(v.get("in") or {})
        ram = bytearray(0x10000)
        for a, b in (v.get("mem") or {}).items():
            ram[int(a, 0)] = b
        out = run_case(m, card, st, bytes(ram))
        for k, want in (v.get("out") or {}).items():
            if out.get(k) != want:
                problems.append(f"vector {v.get('name')}: {k} = {out.get(k)!r}, expected {want!r}")
        after = m.read("ram")
        for a, want in (v.get("mem_out") or {}).items():
            if after[int(a, 0)] != want:
                problems.append(f"vector {v.get('name')}: mem[{a}] = {after[int(a, 0)]:#04x}, expected {want:#04x}")
    return problems


def _compare(a: dict, b: dict) -> list[str]:
    keys = [*STATE, "trace", "ram_changes", "ram_hash"]
    return [f"{k}: {a[k]!r} vs {b[k]!r}" for k in keys if a[k] != b[k]]


def conformance(ctx, isa: str = "lr35902", engines: list[str] | None = None, seed: int | None = None,
                samples: int = 8, only: list[str] | None = None) -> dict:
    """Run every instruction card of the ISA on the bench in each engine; report per card and per engine."""
    if ((I.isa_card(ctx.store, isa).get("decode") or {}).get("kind")) == "mask":
        return mask_conformance(ctx, isa, engines, seed, samples, only)
    seed = random.SystemRandom().randrange(2**32) if seed is None else seed
    ir = Bd.module(ctx, f"{isa}_bench")
    engines = engines or ["ir", "host", "native"]
    machines, unavailable = {}, {}
    for e in engines:
        try:
            lang = N.resolve_engine(ctx, e)
            machines[lang] = N.load(ctx, ir, lang)
        except N.EngineError as exc:
            unavailable[e] = str(exc)
    ref = "ir" if "ir" in machines else next(iter(machines))
    cards = [c for c in I.instructions(ctx.store, isa) if only is None or c.name in only]
    rng = random.Random(seed)
    per_card = {}
    for card in cards:
        resources.guard("isa conformance")
        outcomes = ["taken", "not_taken"] if isinstance(card.get("cycles"), dict) else [None]
        problems: list[str] = []
        runs = 0
        flag_seen = {f: set() for f in "ZNHC"}
        for s in range(samples):
            for outcome in outcomes:
                st = _case_state(rng, card, outcome)
                ram = rng.randbytes(0x10000)
                outs = {lang: run_case(m, card, st, ram) for lang, m in machines.items()}
                runs += 1
                base = outs[ref]
                for lang, o in outs.items():
                    if lang != ref:
                        for p in _compare(base, o)[:3]:
                            problems.append(f"{lang} vs {ref}: {p}")
                for p in check_data(card, st, base, outcome):
                    problems.append(p)
                for f in "ZNHC":
                    flag_seen[f].add(bool(base["F"] & FLAG_BIT[f]))
        if card.get("vectors") and ref in machines:
            problems += check_vectors(machines[ref], card)
            for lang, m in machines.items():
                if lang != ref:
                    problems += [f"{lang}: {p}" for p in check_vectors(m, card)]
        per_card[card.name] = {"mnemonic": card["mnemonic"], "runs": runs, "status": "fail" if problems else "pass",
                               "problems": sorted(set(problems))[:8],
                               "computed_flags_constant": sorted(f for f, c in card["flags"].items()
                                                                 if c == "*" and len(flag_seen[f]) < 2)}
    st = [r["status"] for r in per_card.values()]
    return {"isa": isa, "seed": seed, "samples": samples, "engines": sorted(machines), "unavailable": unavailable,
            "reference": ref, "cards": len(per_card), "passed": st.count("pass"), "failed": st.count("fail"),
            "status": "pass" if per_card and "fail" not in st and len(machines) >= 2 else
            ("fail" if "fail" in st else "vacuous"),
            "runs": sum(r["runs"] for r in per_card.values()), "per_card": per_card}


__all__ = ["check_data", "conformance", "mips_conformance", "run_case", "run_mips_case"]


# -- ISAs decoded by masks (ARM / Thumb) ----------------------------------------------------------------------
MODES = (0x10, 0x11, 0x12, 0x13, 0x17, 0x1B, 0x1F)
_REG_KEY = re.compile(r"r(\d+)")                       # vector keys r0..r15
ARM_STATE = ("pc", "cpsr", "spsr", "ntrace", "swi_calls", "swi_last", "undef_calls", "cp_last", "cp_value")


def decoded_by(cards, op: int, iset: str):
    """The card the generated decoder picks for a word: every card whose mask/match fits, highest priority."""
    uncond = iset == "arm" and (op >> 28) == 0xF
    cand = [c for c in cards if c.get("set") == iset and bool(c.get("unconditional")) == uncond
            and (op & c["mask"]) == c["match"]]
    cand.sort(key=lambda c: (-c.get("priority", bin(c["mask"]).count("1")), c.name))
    return cand[0] if cand else None


def _word(rng, card) -> int:
    bits = 32 if card["set"] == "arm" else 16
    w = rng.getrandbits(bits)
    op = (w & ~card["mask"] & ((1 << bits) - 1)) | card["match"]
    if card["set"] == "arm" and not card.get("unconditional"):
        op = (op & 0x0FFFFFFF) | (rng.choice([14, 14, 14, rng.randrange(15)]) << 28)
    return op


def _arm_state(rng, card) -> dict:
    regs = [rng.getrandbits(32) for _ in range(16)]
    mode = rng.choice(MODES)
    cpsr = (rng.getrandbits(5) << 27) | (rng.getrandbits(2) << 6) | mode | (0x20 if card["set"] == "thumb" else 0)
    pc = rng.getrandbits(16) & (0xFFFC if card["set"] == "arm" else 0xFFFE)
    return {"regs": regs, "banked": [rng.getrandbits(32) for _ in range(48)], "cpsr": cpsr,
            "spsr": rng.getrandbits(32), "pc": pc}


def run_arm_case(m, st: dict, op: int, ram: bytes) -> dict:
    m.write("mem", ram)
    ra, ba = m.array("regs"), m.array("banked")
    for i, v in enumerate(st["regs"]):
        ra[i] = v
    for i, v in enumerate(st["banked"]):
        ba[i] = v
    for k in ("cpsr", "spsr", "pc"):
        m.set(k, st[k])
    for k, v in (("ntrace", 0), ("swi_calls", 0), ("swi_last", -1), ("undef_calls", 0), ("cp_last", -1), ("cp_value", 0x1234)):
        m.set(k, v)
    m.call("run_one", op)
    out = {k: m.get(k) for k in ARM_STATE}
    out["regs"] = [ra[i] for i in range(16)]
    out["banked"] = [ba[i] for i in range(48)]
    n = min(out["ntrace"], 64)
    tk, ta, tv = m.array("trace_kind"), m.array("trace_addr"), m.array("trace_val")
    out["trace"] = [(tk[i], ta[i], tv[i]) for i in range(n)]
    out["mem_hash"] = hashlib.sha1(m.read("mem")).hexdigest()
    return out


def check_arm_data(card, st: dict, out: dict, op: int) -> list[str]:
    problems = []
    size = 4 if card["set"] == "arm" else 2
    if any(not (0 <= v <= 0xFFFFFFFF) for v in out["regs"]):
        problems.append("a register left the 32-bit range")
    branched = out["pc"] != ((st["pc"] + size) & 0xFFFFFFFF)
    mode_changed = (out["cpsr"] & 0x1F) != (st["cpsr"] & 0x1F)
    if branched and card["group"] in ("data_processing", "block", "psr") or mode_changed:
        return problems
    sbit = (op >> 20) & 1 if card["set"] == "arm" else 1
    for i, f in enumerate("NZCV"):
        code = card["flags"][f]
        bit = 1 << (31 - i)
        if code == "-" or (code == "S" and not sbit):
            if (st["cpsr"] ^ out["cpsr"]) & bit:
                problems.append(f"flag {f} marked {code!r} changed")
    return problems


def check_arm_vectors(m, card) -> list[str]:
    problems = []
    for v in card.get("vectors") or []:
        st = {"regs": [0] * 16, "banked": [0] * 48, "cpsr": 0x13 if card["set"] == "arm" else 0x33, "spsr": 0,
              "pc": 0x1000}
        for k, val in (v.get("in") or {}).items():
            reg = _REG_KEY.fullmatch(k)
            if reg:
                st["regs"][int(reg.group(1))] = val
            else:
                st[k] = val
        ram = bytearray(0x10000)
        for a, w in (v.get("mem") or {}).items():
            ram[int(a, 0):int(a, 0) + 4] = (w & 0xFFFFFFFF).to_bytes(4, "little")
        out = run_arm_case(m, st, v["op"], bytes(ram))
        for k, want in (v.get("out") or {}).items():
            if k == "next_pc":
                got = out["pc"]
            elif _REG_KEY.fullmatch(k):
                got = out["regs"][int(k[1:])]
            else:
                got = out.get(k)
            if got != want:
                problems.append(f"vector {v.get('name')}: {k} = {got!r:}, expected {want:#x}")
        after = m.read("mem")
        for a, want in (v.get("mem_out") or {}).items():
            got = int.from_bytes(after[int(a, 0):int(a, 0) + 4], "little")
            if got != want:
                problems.append(f"vector {v.get('name')}: mem[{a}] = {got:#x}, expected {want:#x}")
    return problems


def mask_conformance(ctx, isa: str, engines=None, seed=None, samples: int = 8, only=None) -> dict:
    if I.isa_card(ctx.store, isa).get("bench_state") == "mips":
        return mips_conformance(ctx, isa, engines, seed, samples, only)
    seed = random.SystemRandom().randrange(2**32) if seed is None else seed
    ir = Bd.module(ctx, f"{isa}_bench")
    engines = engines or ["ir", "host", "native"]
    machines, unavailable = {}, {}
    for e in engines:
        try:
            lang = N.resolve_engine(ctx, e)
            machines[lang] = N.load(ctx, ir, lang)
        except N.EngineError as exc:
            unavailable[e] = str(exc)
    ref = "ir" if "ir" in machines else next(iter(machines))
    allc = I.instructions(ctx.store, isa)
    cards = [c for c in allc if only is None or c.name in only]
    rng = random.Random(seed)
    per_card = {}
    for card in cards:
        resources.guard("isa conformance")
        problems, runs, misses = [], 0, 0
        for _ in range(samples):
            op = None
            for _try in range(24):
                w = _word(rng, card)
                d = decoded_by(allc, w, card["set"])
                if d is not None and d.name == card.name:
                    op = w
                    break
            if op is None:
                misses += 1
                continue
            st = _arm_state(rng, card)
            ram = rng.randbytes(0x10000)
            outs = {lang: run_arm_case(m, st, op, ram) for lang, m in machines.items()}
            runs += 1
            base = outs[ref]
            for lang, o in outs.items():
                if lang != ref:
                    for k in (*ARM_STATE, "regs", "banked", "trace", "mem_hash"):
                        if o[k] != base[k]:
                            problems.append(f"{lang} vs {ref} on {op:#010x}: {k} {o[k]!r:.80} vs {base[k]!r:.80}")
                            break
            problems += [f"{op:#010x}: {p}" for p in check_arm_data(card, st, base, op)]
        if card.get("vectors"):
            for lang, m in machines.items():
                problems += [f"{lang}: {p}" for p in check_arm_vectors(m, card)]
        status = "fail" if problems else ("pass" if runs else "vacuous")
        per_card[card.name] = {"mnemonic": card["mnemonic"], "runs": runs, "status": status,
                               "problems": sorted(set(problems))[:8], "decode_misses": misses}
    st = [r["status"] for r in per_card.values()]
    return {"isa": isa, "seed": seed, "samples": samples, "engines": sorted(machines), "unavailable": unavailable,
            "reference": ref, "cards": len(per_card), "passed": st.count("pass"), "failed": st.count("fail"),
            "vacuous": st.count("vacuous"),
            "status": "pass" if per_card and "fail" not in st and len(machines) >= 2 else ("fail" if "fail" in st else "vacuous"),
            "runs": sum(r["runs"] for r in per_card.values()), "per_card": per_card}


# -- MIPS (no flags; delay slots; two cores: MIPS32r2 and the PSP's Allegrex) ----------------------------------
MIPS_STATE = ("pc", "hi", "lo", "in_slot", "slot_target", "bpending", "variant", "llbit", "ntrace", "sys_calls",
              "sys_last", "brk_calls", "exc_calls", "exc_last", "exc_info", "undef_calls")


def _mips_state(rng, card, variants: dict) -> dict:
    regs = [0] + [rng.choice([rng.getrandbits(32), rng.getrandbits(16), 0xFFFFFFFF - rng.getrandbits(8),
                              0x80000000 | rng.getrandbits(8), 0x7FFFFFFF - rng.getrandbits(4)]) for _ in range(31)]
    variant = variants.get(card.get("arch"), rng.randrange(len(variants)))
    if rng.randrange(8) == 0:                         # sometimes the other core: the card must be reserved there
        variant ^= 1
    return {"regs": regs, "hi": rng.getrandbits(32), "lo": rng.getrandbits(32), "pc": rng.getrandbits(16) & 0xFFFC,
            "variant": variant, "llbit": rng.randrange(2)}


def run_mips_case(m, st: dict, op: int, ram: bytes) -> dict:
    m.write("mem", ram)
    ra = m.array("regs")
    for i, v in enumerate(st["regs"]):
        ra[i] = v
    defaults = {"in_slot": 0, "slot_target": 0, "bpending": 0, "ntrace": 0, "sys_calls": 0, "sys_last": -1,
                "brk_calls": 0, "exc_calls": 0, "exc_last": -1, "exc_info": 0, "undef_calls": 0}
    for k in MIPS_STATE:
        m.set(k, st.get(k, defaults.get(k, 0)))
    m.call("run_one", op)
    out = {k: m.get(k) for k in MIPS_STATE}
    out["regs"] = [ra[i] for i in range(32)]
    n = min(out["ntrace"], 64)
    tk, ta, tv = m.array("trace_kind"), m.array("trace_addr"), m.array("trace_val")
    out["trace"] = [(tk[i], ta[i], tv[i]) for i in range(n)]
    out["mem_hash"] = hashlib.sha1(m.read("mem")).hexdigest()
    return out


def check_mips_data(card, st: dict, out: dict, op: int, variants: dict) -> list[str]:
    """What holds for every MIPS card: registers stay 32-bit words, r0 reads 0, a card of the other core is a
    reserved instruction that changes nothing else, and only branches move control past the next word."""
    problems = []
    if any(not (0 <= v <= 0xFFFFFFFF) for v in (*out["regs"], out["hi"], out["lo"], out["pc"])):
        problems.append("a register left the 32-bit range")
    if out["regs"][0] != 0:
        problems.append("r0 is not zero")
    own = variants.get(card.get("arch"))
    if own is not None and st["variant"] != own:
        if out["undef_calls"] != 1 or out["regs"] != st["regs"] or out["ntrace"]:
            problems.append(f"not reserved on variant {st['variant']}")
        return problems
    if out["undef_calls"]:
        problems.append("raised a reserved-instruction exception on its own core")
    if card["group"] != "branch" and (out["in_slot"] or out["pc"] != (st["pc"] + 4) & 0xFFFFFFFF):
        problems.append("a non-branch moved control")
    if out["exc_calls"] and any(a != b for i, (a, b) in enumerate(zip(st["regs"], out["regs"]))):
        problems.append("an instruction that raised an exception wrote a register")
    return problems


def check_mips_vectors(m, card) -> list[str]:
    problems = []
    for v in card.get("vectors") or []:
        st = {"regs": [0] * 32, "hi": 0, "lo": 0, "pc": 0x1000, "variant": 0, "llbit": 0}
        for k, val in (v.get("in") or {}).items():
            reg = _REG_KEY.fullmatch(k)
            if reg:
                st["regs"][int(reg.group(1))] = val
            else:
                st[k] = val
        ram = bytearray(0x10000)
        for a, w in (v.get("mem") or {}).items():
            ram[int(a, 0):int(a, 0) + 4] = (w & 0xFFFFFFFF).to_bytes(4, "little")
        out = run_mips_case(m, st, v["op"], bytes(ram))
        for k, want in (v.get("out") or {}).items():
            got = out["regs"][int(k[1:])] if _REG_KEY.fullmatch(k) else out.get(k)
            if got != want:
                problems.append(f"vector {v.get('name')}: {k} = {got!r}, expected {want:#x}")
        after = m.read("mem")
        for a, want in (v.get("mem_out") or {}).items():
            got = int.from_bytes(after[int(a, 0):int(a, 0) + 4], "little")
            if got != want:
                problems.append(f"vector {v.get('name')}: mem[{a}] = {got:#x}, expected {want:#x}")
    return problems


def mips_conformance(ctx, isa: str, engines=None, seed=None, samples: int = 8, only=None) -> dict:
    seed = random.SystemRandom().randrange(2**32) if seed is None else seed
    ir = Bd.module(ctx, f"{isa}_bench")
    engines = engines or ["ir", "host", "native"]
    machines, unavailable = {}, {}
    for e in engines:
        try:
            lang = N.resolve_engine(ctx, e)
            machines[lang] = N.load(ctx, ir, lang)
        except N.EngineError as exc:
            unavailable[e] = str(exc)
    ref = "ir" if "ir" in machines else next(iter(machines))
    allc = I.instructions(ctx.store, isa)
    variants = I.isa_card(ctx.store, isa).get("variants") or {}
    cards = [c for c in allc if only is None or c.name in only]
    rng = random.Random(seed)
    per_card = {}
    for card in cards:
        resources.guard("isa conformance")
        problems, runs, misses = [], 0, 0
        for _ in range(samples):
            op = None
            for _try in range(24):
                w = _word(rng, card)
                d = decoded_by(allc, w, card["set"])
                if d is not None and d.name == card.name:
                    op = w
                    break
            if op is None:
                misses += 1
                continue
            st = _mips_state(rng, card, variants)
            ram = rng.randbytes(0x10000)
            outs = {lang: run_mips_case(mm, st, op, ram) for lang, mm in machines.items()}
            runs += 1
            base = outs[ref]
            for lang, o in outs.items():
                if lang != ref:
                    for k in (*MIPS_STATE, "regs", "trace", "mem_hash"):
                        if o[k] != base[k]:
                            problems.append(f"{lang} vs {ref} on {op:#010x}: {k} {o[k]!r:.80} vs {base[k]!r:.80}")
                            break
            problems += [f"{op:#010x}: {p}" for p in check_mips_data(card, st, base, op, variants)]
        if card.get("vectors"):
            for lang, mm in machines.items():
                problems += [f"{lang}: {p}" for p in check_mips_vectors(mm, card)]
        status = "fail" if problems else ("pass" if runs else "vacuous")
        per_card[card.name] = {"mnemonic": card["mnemonic"], "runs": runs, "status": status,
                               "problems": sorted(set(problems))[:8], "decode_misses": misses}
    sts = [r["status"] for r in per_card.values()]
    return {"isa": isa, "seed": seed, "samples": samples, "engines": sorted(machines), "unavailable": unavailable,
            "reference": ref, "cards": len(per_card), "passed": sts.count("pass"), "failed": sts.count("fail"),
            "vacuous": sts.count("vacuous"),
            "status": "pass" if per_card and "fail" not in sts and len(machines) >= 2 else ("fail" if "fail" in sts else "vacuous"),
            "runs": sum(r["runs"] for r in per_card.values()), "per_card": per_card}
