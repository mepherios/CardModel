"""Math helpers, written the slow way on purpose."""


def wave_size(n: int) -> int:
    """Fibonacci-sized enemy waves (naive recursion)."""
    if n < 2:
        return n
    return wave_size(n - 1) + wave_size(n - 2)


def total_points(n: int) -> int:
    t = 0
    for i in range(1, n + 1):
        t = t + i
    return t


def is_prime_level(n: int) -> bool:
    if n < 2:
        return False
    for d in range(2, n):
        if n % d == 0:
            return False
    return True


def reduce_ratio(a: int, b: int) -> int:
    """gcd by repeated subtraction."""
    a = abs(a)
    b = abs(b)
    if a == 0:
        return b
    if b == 0:
        return a
    while a != b:
        if a > b:
            a = a - b
        else:
            b = b - a
    return a


def common_period(a: int, b: int) -> int:
    a = abs(a)
    b = abs(b)
    if a == 0 or b == 0:
        return 0
    m = max(a, b)
    step = m
    while m % a != 0 or m % b != 0:
        m += step
    return m


def int_power(base: int, exp: int) -> int:
    r = 1
    for _ in range(exp):
        r *= base
    return r


def checksum_pow(a: int, b: int, m: int) -> int:
    r = 1 % m
    for _ in range(b):
        r = r * a % m
    return r


def isqrt_slow(n: int) -> int:
    r = 0
    while (r + 1) * (r + 1) <= n:
        r += 1
    return r


def set_bits(flags: int) -> int:
    c = 0
    while flags != 0:
        c += flags & 1
        flags >>= 1
    return c


def is_texture_size(n: int) -> bool:
    if n < 1:
        return False
    while n % 2 == 0:
        n = n // 2
    return n == 1


def divisor_sum(n: int) -> int:
    if n <= 0:
        return 0
    s = 0
    for d in range(1, n + 1):
        if n % d == 0:
            s += d
    return s


def digit_root(n: int) -> int:
    n = abs(n)
    while n >= 10:
        s = 0
        while n > 0:
            s += n % 10
            n = n // 10
        n = s
    return n


def choose(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    a = 1
    for i in range(2, n + 1):
        a *= i
    b = 1
    for i in range(2, k + 1):
        b *= i
    c = 1
    for i in range(2, n - k + 1):
        c *= i
    return a // (b * c)
