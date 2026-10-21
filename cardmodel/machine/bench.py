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


__all__ = ["check_data", "conformance", "run_case"]
