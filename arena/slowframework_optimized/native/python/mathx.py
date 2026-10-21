def checksum_pow__modpow_square_multiply(a: int, b: int, m: int) -> int:
    r = (1 % m)
    x = (a % m)
    e = b
    while (e > 0):
        if ((e % 2) == 1):
            r = ((r * x) % m)
        x = ((x * x) % m)
        e = (e // 2)
    return r


def checksum_pow__original(a: int, b: int, m: int) -> int:
    r = (1 % m)
    for _ in range(0, b, 1):
        r = ((r * a) % m)
    return r


def checksum_pow(a: int, b: int, m: int) -> int:
    if ((b >= 0) and (m >= 1)):
        return checksum_pow__modpow_square_multiply(a, b, m)
    return checksum_pow__original(a, b, m)


def choose__binomial_multiplicative(n: int, k: int) -> int:
    if ((k < 0) or (k > n)):
        return 0
    k = min(k, (n - k))
    c = 1
    for i in range(0, k, 1):
        c = ((c * (n - i)) // (i + 1))
    return c


def choose__original(n: int, k: int) -> int:
    if ((k < 0) or (k > n)):
        return 0
    a = 1
    for i in range(2, (n + 1), 1):
        a = (a * i)
    b = 1
    for i in range(2, (k + 1), 1):
        b = (b * i)
    c = 1
    for i in range(2, ((n - k) + 1), 1):
        c = (c * i)
    return (a // (b * c))


def choose(n: int, k: int) -> int:
    if (n >= 0):
        return choose__binomial_multiplicative(n, k)
    return choose__original(n, k)


import math
def common_period__lcm_via_gcd(a: int, b: int) -> int:
    a = abs(a)
    b = abs(b)
    if ((a == 0) or (b == 0)):
        return 0
    return ((a // math.gcd(a, b)) * b)


def common_period(a: int, b: int) -> int:
    return common_period__lcm_via_gcd(a, b)


def digit_root__digital_root_closed_form(n: int) -> int:
    n = abs(n)
    if (n == 0):
        return 0
    return (1 + ((n - 1) % 9))


def digit_root(n: int) -> int:
    return digit_root__digital_root_closed_form(n)


def divisor_sum__sum_of_divisors_sqrt_pairs(n: int) -> int:
    if (n <= 0):
        return 0
    s = 0
    d = 1
    while ((d * d) <= n):
        if ((n % d) == 0):
            s = (s + d)
            if ((d * d) != n):
                s = (s + (n // d))
        d = (d + 1)
    return s


def divisor_sum(n: int) -> int:
    return divisor_sum__sum_of_divisors_sqrt_pairs(n)


def int_power__power_square_multiply(base: int, exp: int) -> int:
    r = 1
    x = base
    e = exp
    while (e > 0):
        if ((e % 2) == 1):
            r = (r * x)
        x = (x * x)
        e = (e // 2)
    return r


def int_power__original(base: int, exp: int) -> int:
    r = 1
    for _ in range(0, exp, 1):
        r = (r * base)
    return r


def int_power(base: int, exp: int) -> int:
    if (exp >= 0):
        return int_power__power_square_multiply(base, exp)
    return int_power__original(base, exp)


def is_prime_level__is_prime_wheel_6k(n: int) -> bool:
    if (n < 2):
        return False
    if (n < 4):
        return True
    if (((n % 2) == 0) or ((n % 3) == 0)):
        return False
    d = 5
    while ((d * d) <= n):
        if (((n % d) == 0) or ((n % (d + 2)) == 0)):
            return False
        d = (d + 6)
    return True


def is_prime_level(n: int) -> bool:
    return is_prime_level__is_prime_wheel_6k(n)


def is_texture_size__is_power_of_two_bit_trick(n: int) -> bool:
    return ((n > 0) and ((n & (n - 1)) == 0))


def is_texture_size(n: int) -> bool:
    return is_texture_size__is_power_of_two_bit_trick(n)


def isqrt_slow__isqrt_newton(n: int) -> int:
    if (n < 2):
        return n
    x = n
    y = ((x + 1) // 2)
    while (y < x):
        x = y
        y = ((x + (n // x)) // 2)
    return x


def isqrt_slow__original(n: int) -> int:
    r = 0
    while (((r + 1) * (r + 1)) <= n):
        r = (r + 1)
    return r


def isqrt_slow(n: int) -> int:
    if (n >= 0):
        return isqrt_slow__isqrt_newton(n)
    return isqrt_slow__original(n)


import math
def reduce_ratio__gcd_builtin(a: int, b: int) -> int:
    return math.gcd(a, b)


def reduce_ratio(a: int, b: int) -> int:
    return reduce_ratio__gcd_builtin(a, b)


def set_bits__popcount_kernighan(flags: int) -> int:
    c = 0
    while (flags != 0):
        flags = (flags & (flags - 1))
        c = (c + 1)
    return c


def set_bits__original(flags: int) -> int:
    c = 0
    while (flags != 0):
        c = (c + (flags & 1))
        flags = (flags >> 1)
    return c


def set_bits(flags: int) -> int:
    if (flags >= 0):
        return set_bits__popcount_kernighan(flags)
    return set_bits__original(flags)


def total_points__sum_1_to_n_closed_form(n: int) -> int:
    if (n <= 0):
        return 0
    return ((n * (n + 1)) // 2)


def total_points(n: int) -> int:
    return total_points__sum_1_to_n_closed_form(n)


def wave_size__fibonacci_iterative(n: int) -> int:
    a = 0
    b = 1
    for _ in range(0, n, 1):
        cm_t3 = b
        cm_t4 = (a + b)
        a = cm_t3
        b = cm_t4
    return a


def wave_size__original(n: int) -> int:
    if (n < 2):
        return n
    return (wave_size((n - 1)) + wave_size((n - 2)))


def wave_size(n: int) -> int:
    if (n >= 0):
        return wave_size__fibonacci_iterative(n)
    return wave_size__original(n)

