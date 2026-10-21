import math


def gcd(a: int, b: int) -> int:
    while b != 0:
        a, b = b, a % b
    return abs(a)


def fib(n: int) -> int:
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def is_prime(n: int) -> bool:
    if n < 2:
        return False
    i = 2
    while i * i <= n:
        if n % i == 0:
            return False
        i += 1
    return True


def collatz_steps(n: int) -> int:
    steps = 0
    while n > 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        steps += 1
    return steps


def digit_sum(n: int) -> int:
    n = abs(n)
    s = 0
    while n > 0:
        s += n % 10
        n //= 10
    return s


def isqrt_newton(n: int) -> int:
    if n < 2:
        return n
    x = n
    y = (x + 1) // 2
    while y < x:
        x = y
        y = (x + n // x) // 2
    return x


def count_primes(limit: int) -> int:
    c = 0
    for k in range(2, limit):
        if is_prime(k):
            c += 1
    return c


def mean3(a: float, b: float, c: float) -> float:
    return (a + b + c) / 3


def clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(x, hi))


def sign_sum(xs: list) -> int:
    return sum(xs)


def tri(n: int) -> int:
    total = 0
    for i in range(n, 0, -1):
        if i % 3 == 0:
            continue
        total += i
    return total


def power_mod(base: int, exp: int, m: int) -> int:
    result = 1 % m
    base = base % m
    while exp > 0:
        if exp % 2 == 1:
            result = result * base % m
        base = base * base % m
        exp //= 2
    return result


def binomial(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    k = min(k, n - k)
    c = 1
    for i in range(k):
        c = c * (n - i) // (i + 1)
    return c


def popcount(x: int) -> int:
    x = abs(x)
    c = 0
    while x != 0:
        c += x & 1
        x >>= 1
    return c


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def hypot_int(a: int, b: int) -> int:
    s = a * a + b * b
    r = s
    while r * r > s:
        r = (r + s // r) // 2
    return r


def triangle_kind(a: int, b: int, c: int) -> int:
    if a <= 0 or b <= 0 or c <= 0 or a + b <= c or a + c <= b or b + c <= a:
        return 0
    if a == b and b == c:
        return 3
    if a == b or b == c or a == c:
        return 2
    return 1


def sum_of_divisors(n: int) -> int:
    if n <= 0:
        return 0
    total = 0
    d = 1
    while d * d <= n:
        if n % d == 0:
            total += d
            if d * d != n:
                total += n // d
        d += 1
    return total


def lcm_iter(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return abs(a * b) // gcd(a, b)


def digital_root(n: int) -> int:
    n = abs(n)
    while n >= 10:
        n = digit_sum(n)
    return n


def ackermann_small(m: int, n: int) -> int:
    if m == 0:
        return n + 1
    if n == 0:
        return ackermann_small(m - 1, 1)
    return ackermann_small(m - 1, ackermann_small(m, n - 1))
