# Vendored verbatim from the hub: ~/Documents/Claude_Hub/config/bit_primitives.py (2026-10-21).
# sha256 of the original: 61ac91b2da58a2262cb61bdd9b919d454720873f1ec42cd6f25070067fed32a3
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bit_primitives — decomposition rules from high-level cards into the
universal bit-primitive basis.

User insight (2026-04-15): at the lowest level, a computer only needs
AND / OR / XOR / NOT / shifts (or NAND alone, which is universal).
Every higher-level card has a bit-primitive expansion. This module
exposes the expansions so the card method can reason about equivalent
bit-level implementations — and verify them with random inputs.

Complexity: O(1) lookups. Decomposition execution is O(bit_width) for
arithmetic, O(bit_width²) for MUL.

Honest limits (L1)
------------------
* This is the structural map, not a simulator of every CPU op. A real
  HDL synthesiser can produce tighter / different gate-level realisations.
* Decompositions use arbitrary-precision ints (Python native); fixed-
  width behaviour (overflow, carry-out) is NOT modelled yet.
* Each primitive function implements the semantic equivalence, not
  the gate-level count. For cost, use `card_catalog.BIT_PRIMITIVE_CARDS`.
"""
from __future__ import annotations


# Fixed bit width for simulated hardware operations. Python's int is
# arbitrary precision, so negative numbers have infinitely-many leading
# 1s — which makes ripple-carry ADD loop forever. We simulate a 32-bit
# machine with modular wraparound; fire-tests use non-negative inputs
# anyway to keep semantics unambiguous.
BIT_WIDTH = 32
_MASK = (1 << BIT_WIDTH) - 1


def _mask(x: int) -> int:
    """Reduce to BIT_WIDTH bits as an unsigned value."""
    return x & _MASK


# ─── universal basis implementations ──────────────────────────────────

def bit_nand(a: int, b: int) -> int:
    """NAND — universal. Every other gate can be built from NAND alone."""
    return _mask(~(a & b))


def bit_nor(a: int, b: int) -> int:
    """NOR — alternate universal basis."""
    return _mask(~(a | b))


# ─── standard gates as NAND-compositions (for proof) ──────────────────

def nand_not(a: int) -> int:        return bit_nand(a, a)
def nand_and(a: int, b: int) -> int: return nand_not(bit_nand(a, b))
def nand_or(a: int, b: int) -> int:  return bit_nand(nand_not(a), nand_not(b))
def nand_xor(a: int, b: int) -> int:
    t = bit_nand(a, b)
    return bit_nand(bit_nand(a, t), bit_nand(b, t))


# ─── high-level card decompositions ───────────────────────────────────

def add_via_bits(a: int, b: int) -> int:
    """Ripple-carry ADD. Fixed-width; wraps at BIT_WIDTH.
    Terminates in ≤ BIT_WIDTH iterations."""
    a &= _MASK; b &= _MASK
    for _ in range(BIT_WIDTH + 1):
        if b == 0: break
        carry = ((a & b) << 1) & _MASK
        a = (a ^ b) & _MASK
        b = carry
    return a


def sub_via_bits(a: int, b: int) -> int:
    """SUB via two's complement. Fixed-width semantics."""
    return add_via_bits(a, add_via_bits(_mask(~b), 1))


def mul_via_bits(a: int, b: int) -> int:
    """MUL as shift-and-add. Fixed-width; wraps at BIT_WIDTH.
    Complexity O(BIT_WIDTH)."""
    a &= _MASK; b &= _MASK
    result = 0
    for _ in range(BIT_WIDTH):
        if b == 0: break
        if b & 1:
            result = add_via_bits(result, a)
        a = (a << 1) & _MASK
        b >>= 1
    return result


def square_via_bits(x: int) -> int:
    """SQUARE via shift-and-add, same as MUL(x, x)."""
    return mul_via_bits(x, x)


def pow_via_bits(base: int, exp: int) -> int:
    """Square-and-multiply exponentiation.  Positive int exp only."""
    if exp < 0:
        raise ValueError("pow_via_bits needs non-negative exponent")
    result = 1
    while exp:
        if exp & 1:
            result = mul_via_bits(result, base)
        base = mul_via_bits(base, base)
        exp >>= 1
    return result


def shift_left_via_mul(x: int, k: int) -> int:
    """SHL(x, k) ≡ MUL(x, 2**k).  Inverse of the CONST_MUL_POW2 rewrite."""
    return mul_via_bits(x, 1 << k)


# ─── decomposition table (for equivalence tests + future optimiser) ──

DECOMPOSITIONS = {
    "ADD":          add_via_bits,
    "SUB":          sub_via_bits,
    "MUL":          mul_via_bits,
    "SQUARE":       square_via_bits,
    "POW":          pow_via_bits,
    "SHIFT_LEFT":   shift_left_via_mul,
    # NAND-based standard-gate equivalences
    "BIT_NOT":      nand_not,
    "BIT_AND":      nand_and,
    "BIT_OR":       nand_or,
    "BIT_XOR":      nand_xor,
}


if __name__ == "__main__":
    # quick sanity check
    import random
    rng = random.Random(0)
    for name, fn in DECOMPOSITIONS.items():
        print(f"  {name:12s}", end=" ")
        if name == "POW":
            ok = all(fn(rng.randint(0, 100), e) == rng.randint(0, 100) ** e
                     for e in [2, 3, 5])
            print("(exponent-only)")
            continue
        if name in ("BIT_NOT",):
            a = rng.randint(-1000, 1000)
            print(f"NAND-not({a}) = {fn(a)}  vs  ~{a} = {~a}")
            continue
        a = rng.randint(-1000, 1000); b = rng.randint(-1000, 1000)
        print(f"f({a}, {b}) = {fn(a, b)}")
