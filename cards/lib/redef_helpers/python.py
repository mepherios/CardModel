"""redef_helpers -- helper functions the hub's card_redefinitions forms call.

Ported verbatim from the hub's config/card_redefinitions.py (_xgcd,
_const_pow_chain), 2026-10-21. Forms that list "redef_helpers" in ``libs``
see these names as globals.
"""


def _xgcd(a: int, b: int) -> tuple[int, int, int]:
    """Extended Euclidean -- returns (gcd, x, y) with a*x + b*y = gcd."""
    if b == 0:
        return (a, 1, 0)
    g, x1, y1 = _xgcd(b, a % b)
    return (g, y1, x1 - (a // b) * y1)


def _const_pow_chain(x: int, n: int) -> int:
    if n == 0:
        return 1
    if n == 1:
        return x
    if n == 2:
        return x * x
    if n == 3:
        return x * x * x
    if n == 4:
        y = x * x
        return y * y
    return x ** n
