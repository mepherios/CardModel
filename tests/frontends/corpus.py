"""Round-trip corpus: every function lifts from Python, emits into each codegen language, lifts back from that
language's text and must agree with the original IR (tests/test_frontends.py)."""
def gcd(a: int, b: int) -> int:
    while b != 0:
        a, b = b, a % b
    return abs(a)


def collatz(n: int) -> int:
    steps = 0
    while n > 1:
        if n % 2 == 0:
            n = n // 2
        else:
            n = 3 * n + 1
        steps += 1
    return steps


def bits(x: int) -> int:
    x = x & 65535
    c = 0
    while x != 0:
        c += x & 1
        x = x >> 1
    return c


def mix(x: float, k: int) -> float:
    s = 0.0
    for i in range(k):
        s = s + x / (i + 1) if i % 2 == 0 else s - x
    return s


def stepper(n: int) -> int:
    acc = 0
    for i in range(n, 0, -2):
        if i % 3 == 0:
            continue
        if acc > 500:
            break
        acc += i * i
    return acc


def poly(x: float) -> float:
    return 3.0 * x ** 2 - 2.0 * x + 1.0


def ipow(a: int, n: int) -> int:
    return a ** 3 + pow(a, 2) - n


def clamp(x: int, lo: int, hi: int) -> int:
    return max(lo, min(x, hi))


def flags(a: int, b: int) -> bool:
    return (a > b and a % 2 == 0) or not (b < 0)


def xorshift(x: int) -> int:
    x = x ^ (x << 3)
    x = x ^ (x >> 5)
    return x & 4095 | 1


def neg(x: int) -> int:
    return -x + ~x


def fdiv(a: int, b: int) -> float:
    if b == 0:
        return 0.0
    return a / b


def floats(x: float, y: float) -> float:
    return abs(x) + float(int(y)) + min(x, y) * max(x, 1.5)


def trunc_back(x: float) -> int:
    return int(x * 3.0)


def fib(n: int) -> int:
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)


def uses_fib(n: int) -> int:
    return fib(n % 15) + gcd(n, 12)


def nested(n: int) -> int:
    total = 0
    i = 0
    while i < n:
        j = 0
        while j < i:
            if (i + j) % 4 == 0:
                total += 1
            j += 1
        i += 1
    return total
