"""Stress corpus for the language-pair matrix: every construct the Python frontend lifts, at its edges.

Each function targets one semantic trap where languages differ (floor vs truncating division, sign of
modulo, shifts of negatives, float formatting, int/float mixing, short-circuit, pow, gcd of negatives).
"""
import math


def floordiv_neg(a: int, b: int) -> int:
    if b == 0:
        return 0
    return a // b


def mod_neg(a: int, b: int) -> int:
    if b == 0:
        return 0
    return a % b


def true_div(a: int, b: int) -> float:
    if b == 0:
        return 0.0
    return a / b


def float_floordiv(x: float, y: float) -> float:
    if y == 0.0:
        return 0.0
    return x // y


def float_mod(x: float, y: float) -> float:
    if y == 0.0:
        return 0.0
    return x % y


def shifts(a: int, s: int) -> int:
    s = s % 8
    return (a >> s) + (a << s)


def bit_ops(a: int, b: int) -> int:
    return (a & b) ^ (a | ~b)


def powmod3(a: int, e: int, m: int) -> int:
    if m <= 1:
        return 0
    return pow(a, abs(e), m)


def legendre(a: int, p: int) -> int:
    p = abs(p) % 50
    if p < 3 or p % 2 == 0:
        return 0
    d = 3
    while d * d <= p:
        if p % d == 0:
            return 0
        d += 2
    r = pow(a, (p - 1) // 2, p)
    if r == p - 1:
        return -1
    return r


def gcd_neg(a: int, b: int) -> int:
    return math.gcd(a, b)


def int_of_float(x: float) -> int:
    return int(x)


def mixed(a: int, x: float) -> float:
    return a * x + a / 3 - float(a) * 0.5


def cube(a: int) -> int:
    return a ** 3


def fpow(x: float) -> float:
    return x ** 2 + abs(x) ** 0.5


def chain_cmp(a: int, b: int, c: int) -> bool:
    return a < b <= c


def short_circuit(a: int, b: int) -> bool:
    return b != 0 and a % b == 0 or a == b


def ternary(a: int, b: int) -> int:
    return a if a > b else -b


def minmax(a: int, b: int, x: float) -> float:
    return min(a, b) + max(x, 1.5)


def loop_step(n: int) -> int:
    total = 0
    for i in range(n, -n, -3):
        total += i * i
    return total


def nested_loops(n: int) -> int:
    count = 0
    for i in range(n):
        for j in range(i):
            if (i + j) % 3 == 0:
                continue
            if j > 7:
                break
            count += i ^ j
    return count


def not_bool(a: int, flag: bool) -> bool:
    return not flag or a > 0


def bool_arith(p: bool, q: bool) -> int:
    t = 0
    if p:
        t += 1
    if q:
        t += 2
    return t


def neg_zero(x: float) -> float:
    return -x * 0.0


def float_eq(x: float) -> bool:
    return x * 3.0 / 3.0 == x


def big_product(a: int, b: int) -> int:
    return a * b * 1000003


def abs_min_int(a: int) -> int:
    return abs(a) - abs(-a) + abs(a - 7)


def swap_loop(n: int) -> int:
    a, b = 0, 1
    i = 0
    while i < n:
        a, b = b, a + b
        i += 1
    return a % 1000


def helper(x: int) -> int:
    return x * 2 + 1


def calls_helper(n: int) -> int:
    return helper(helper(n)) - helper(-n)


def recur(n: int) -> int:
    if n <= 0:
        return 0
    return n + recur(n - 2)
