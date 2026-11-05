"""A small numeric module for the cardmodel showcase (examples/showcase/run.sh)."""


def poly(x: int) -> int:
    return 3 * x * x + 2 * x + 1


def sum_to(n: int) -> int:
    s = 0
    for i in range(1, n + 1):
        s = s + i
    return s


def triangle(n: int) -> int:
    return n * (n + 1) // 2


def gcd(a: int, b: int) -> int:
    while b != 0:
        a, b = b, a % b
    return a


def isqrt(n: int) -> int:
    r = 0
    while (r + 1) * (r + 1) <= n:
        r = r + 1
    return r


def clamp(x: int, lo: int, hi: int) -> int:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def mean(xs: list[int]) -> float:
    total = 0
    for v in xs:
        total = total + v
    return total / len(xs)
