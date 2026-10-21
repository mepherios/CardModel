"""seed_algorithms — bootstrap data for cards/algorithm/* (algorithm-level redefinitions).

An algorithm card is one mathematical function with several implementations (forms) of very different cost:
naive recursion vs iteration vs fast doubling, a loop vs its closed form, trial division to n vs to sqrt(n)...
Every form is plain Python in the IR's liftable subset, so each one also translates to every language card.

Roles:  ``suboptimal`` forms are what slow code typically looks like (the arena generates programs from them);
        the other forms are candidates the improve engine may substitute, after it has verified them against
        the user's own function on the user's own domain.
``precondition`` is a Python expression over the parameters (the domain where every non-suboptimal form is
valid); improve guards a substitution with it and keeps the original code for every other input.
"""

S = "suboptimal"


def form(name, code, complexity, cost, role=None, domain="nonneg_int", notes=""):
    entry = code.split("def ", 1)[1].split("(", 1)[0]
    f = {"name": name, "lang": "python", "entry": entry, "code": code.strip() + "\n", "complexity": complexity,
         "cost": cost, "domain": domain, "runnable": True}
    if role:
        f["role"] = role
    if notes:
        f["notes"] = notes
    return f


def algo(name, statement, params, returns, precondition, gens, reference, forms, tags, small=None):
    card = {"name": name, "statement": statement, "tier": 1,
            "signature": {"params": [{"name": p, "type": t} for p, t in params], "returns": returns},
            "precondition": precondition, "generators": gens, "reference_form": reference, "forms": forms,
            "tags": tags}
    if precondition:
        card["filter"] = f"lambda {', '.join(p for p, _ in params)}: {precondition}"
    if small:
        card["domain_generators"] = {"small_int": small}
    return card


N = {"int": [0, 60]}

ALGORITHMS = [
    algo("fibonacci", "F(0)=0, F(1)=1, F(n)=F(n-1)+F(n-2)", [("n", "int")], "int", "n >= 0", [N], "iterative", [
        form("naive_recursive", """
def fib_naive(n: int) -> int:
    if n < 2:
        return n
    return fib_naive(n - 1) + fib_naive(n - 2)""", "O(phi^n)", 1000.0, S, "small_int"),
        form("iterative", """
def fib_iter(n: int) -> int:
    a = 0
    b = 1
    for _ in range(n):
        a, b = b, a + b
    return a""", "O(n)", 10.0),
        form("fast_doubling", """
def fib_doubling(n: int) -> int:
    a = 0
    b = 1
    bit = 1
    while bit <= n:
        bit = bit * 2
    bit = bit // 2
    while bit > 0:
        c = a * (2 * b - a)
        d = a * a + b * b
        if n & bit != 0:
            a = d
            b = c + d
        else:
            a = c
            b = d
        bit = bit // 2
    return a""", "O(log n)", 3.0)], ["sequence", "math"], small=[{"int": [0, 20]}]),

    algo("triangular", "sum of i for 0 <= i < n (0 when n <= 0)", [("n", "int")], "int", None,
         [{"int": [-50, 100000]}], "loop", [
        form("loop", """
def tri_loop(n: int) -> int:
    t = 0
    for i in range(n):
        t += i
    return t""", "O(n)", 10.0, S, "int"),
        form("recursive", """
def tri_rec(n: int) -> int:
    if n <= 0:
        return 0
    return (n - 1) + tri_rec(n - 1)""", "O(n) stack", 30.0, S, "small_int"),
        form("closed_form", """
def tri_closed(n: int) -> int:
    if n <= 0:
        return 0
    return n * (n - 1) // 2""", "O(1)", 1.0, domain="int")], ["series", "math"], small=[{"int": [0, 400]}]),

    algo("sum_1_to_n", "1 + 2 + ... + n (0 when n <= 0)", [("n", "int")], "int", None, [{"int": [-50, 100000]}],
         "loop", [
        form("loop", """
def sum_loop(n: int) -> int:
    s = 0
    for i in range(1, n + 1):
        s += i
    return s""", "O(n)", 10.0, S, "int"),
        form("closed_form", """
def sum_closed(n: int) -> int:
    if n <= 0:
        return 0
    return n * (n + 1) // 2""", "O(1)", 1.0, domain="int")], ["series", "math"]),

    algo("sum_of_squares", "1^2 + 2^2 + ... + n^2", [("n", "int")], "int", None, [{"int": [-20, 50000]}], "loop", [
        form("loop", """
def sq_loop(n: int) -> int:
    s = 0
    for i in range(1, n + 1):
        s += i * i
    return s""", "O(n)", 12.0, S, "int"),
        form("closed_form", """
def sq_closed(n: int) -> int:
    if n <= 0:
        return 0
    return n * (n + 1) * (2 * n + 1) // 6""", "O(1)", 2.0, domain="int")], ["series", "math"]),

    algo("sum_of_cubes", "1^3 + ... + n^3 = (n(n+1)/2)^2", [("n", "int")], "int", None, [{"int": [-20, 20000]}],
         "loop", [
        form("loop", """
def cube_loop(n: int) -> int:
    s = 0
    for i in range(1, n + 1):
        s += i * i * i
    return s""", "O(n)", 14.0, S, "int"),
        form("closed_form", """
def cube_closed(n: int) -> int:
    if n <= 0:
        return 0
    t = n * (n + 1) // 2
    return t * t""", "O(1)", 2.0, domain="int")], ["series", "math"]),

    algo("arithmetic_series", "a + (a+d) + ... (k terms, 0 when k <= 0)", [("a", "int"), ("d", "int"), ("k", "int")],
         "int", None, [{"int": [-1000, 1000]}, {"int": [-50, 50]}, {"int": [-5, 20000]}], "loop", [
        form("loop", """
def ar_loop(a: int, d: int, k: int) -> int:
    s = 0
    x = a
    for _ in range(k):
        s += x
        x += d
    return s""", "O(k)", 12.0, S, "int"),
        form("closed_form", """
def ar_closed(a: int, d: int, k: int) -> int:
    if k <= 0:
        return 0
    return k * a + d * (k * (k - 1) // 2)""", "O(1)", 2.0, domain="int")], ["series", "math"]),

    algo("power", "a^b for b >= 0", [("a", "int"), ("b", "int")], "int", "b >= 0",
         [{"int": [-9, 9]}, {"int": [0, 60]}], "square_multiply", [
        form("loop", """
def pow_loop(a: int, b: int) -> int:
    r = 1
    for _ in range(b):
        r *= a
    return r""", "O(b)", 10.0, S, "int"),
        form("square_multiply", """
def pow_sq(a: int, b: int) -> int:
    r = 1
    x = a
    e = b
    while e > 0:
        if e % 2 == 1:
            r = r * x
        x = x * x
        e = e // 2
    return r""", "O(log b)", 3.0)], ["math"]),

    algo("modpow", "a^b mod m for b >= 0, m >= 1", [("a", "int"), ("b", "int"), ("m", "int")], "int",
         "b >= 0 and m >= 1", [{"int": [-1000, 1000]}, {"int": [0, 5000]}, {"int": [1, 100000]}], "builtin", [
        form("loop", """
def mp_loop(a: int, b: int, m: int) -> int:
    r = 1 % m
    for _ in range(b):
        r = r * a % m
    return r""", "O(b)", 10.0, S, "int"),
        form("square_multiply", """
def mp_sq(a: int, b: int, m: int) -> int:
    r = 1 % m
    x = a % m
    e = b
    while e > 0:
        if e % 2 == 1:
            r = r * x % m
        x = x * x % m
        e = e // 2
    return r""", "O(log b)", 3.0),
        form("builtin", """
def mp_builtin(a: int, b: int, m: int) -> int:
    return pow(a, b, m)""", "O(log b) native", 1.0)], ["math", "number_theory"]),

    algo("gcd", "greatest common divisor of |a| and |b| (gcd(0,0) = 0)", [("a", "int"), ("b", "int")], "int", None,
         [{"int": [-5000, 5000]}, {"int": [-5000, 5000]}], "euclid", [
        form("subtraction", """
def gcd_sub(a: int, b: int) -> int:
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
    return a""", "O(max(a,b))", 50.0, S, "int"),
        form("euclid", """
def gcd_euclid(a: int, b: int) -> int:
    a = abs(a)
    b = abs(b)
    while b != 0:
        a, b = b, a % b
    return a""", "O(log min)", 5.0, domain="int"),
        form("builtin", """
def gcd_builtin(a: int, b: int) -> int:
    return math.gcd(a, b)""", "O(log min) native", 1.0, domain="int")], ["math", "number_theory"]),

    algo("lcm", "least common multiple of |a| and |b| (0 if either is 0)", [("a", "int"), ("b", "int")], "int", None,
         [{"int": [-300, 300]}, {"int": [-300, 300]}], "via_gcd", [
        form("search", """
def lcm_search(a: int, b: int) -> int:
    a = abs(a)
    b = abs(b)
    if a == 0 or b == 0:
        return 0
    m = max(a, b)
    step = m
    while m % a != 0 or m % b != 0:
        m += step
    return m""", "O(lcm/max)", 40.0, S, "int"),
        form("via_gcd", """
def lcm_gcd(a: int, b: int) -> int:
    a = abs(a)
    b = abs(b)
    if a == 0 or b == 0:
        return 0
    return a // math.gcd(a, b) * b""", "O(log min)", 2.0, domain="int")], ["math", "number_theory"]),

    algo("is_prime", "n is prime", [("n", "int")], "bool", None, [{"int": [-10, 200000]}], "trial_sqrt", [
        form("trial_all", """
def prime_all(n: int) -> bool:
    if n < 2:
        return False
    for d in range(2, n):
        if n % d == 0:
            return False
    return True""", "O(n)", 100.0, S, "int"),
        form("trial_sqrt", """
def prime_sqrt(n: int) -> bool:
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True""", "O(sqrt n)", 10.0, domain="int"),
        form("wheel_6k", """
def prime_6k(n: int) -> bool:
    if n < 2:
        return False
    if n < 4:
        return True
    if n % 2 == 0 or n % 3 == 0:
        return False
    d = 5
    while d * d <= n:
        if n % d == 0 or n % (d + 2) == 0:
            return False
        d += 6
    return True""", "O(sqrt n / 3)", 4.0, domain="int")], ["math", "number_theory"]),

    algo("factorial", "n! (1 for n <= 0 in the loop form's convention)", [("n", "int")], "int", "n >= 0",
         [{"int": [0, 300]}], "loop", [
        form("recursive", """
def fact_rec(n: int) -> int:
    if n <= 1:
        return 1
    return n * fact_rec(n - 1)""", "O(n) stack", 15.0, S, "small_int"),
        form("loop", """
def fact_loop(n: int) -> int:
    r = 1
    for i in range(2, n + 1):
        r *= i
    return r""", "O(n)", 10.0)], ["math"], small=[{"int": [0, 200]}]),

    algo("binomial", "C(n, k) (0 when k < 0 or k > n)", [("n", "int"), ("k", "int")], "int", "n >= 0",
         [{"int": [0, 400]}, {"int": [-5, 400]}], "multiplicative", [
        form("via_factorials", """
def binom_fact(n: int, k: int) -> int:
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
    return a // (b * c)""", "O(n) big-int", 30.0, S),
        form("multiplicative", """
def binom_mult(n: int, k: int) -> int:
    if k < 0 or k > n:
        return 0
    k = min(k, n - k)
    c = 1
    for i in range(k):
        c = c * (n - i) // (i + 1)
    return c""", "O(min(k, n-k))", 5.0)], ["math", "combinatorics"]),

    algo("popcount", "number of set bits of n >= 0", [("n", "int")], "int", "n >= 0", [{"int": [0, 2**40]}],
         "kernighan", [
        form("shift_loop", """
def pop_shift(n: int) -> int:
    c = 0
    while n != 0:
        c += n & 1
        n >>= 1
    return c""", "O(bits)", 10.0, S),
        form("kernighan", """
def pop_kernighan(n: int) -> int:
    c = 0
    while n != 0:
        n = n & (n - 1)
        c += 1
    return c""", "O(set bits)", 5.0)], ["bits"]),

    algo("is_power_of_two", "n is a power of two", [("n", "int")], "bool", None, [{"int": [-100, 2**40]}],
         "bit_trick", [
        form("divide_loop", """
def pow2_loop(n: int) -> bool:
    if n < 1:
        return False
    while n % 2 == 0:
        n = n // 2
    return n == 1""", "O(log n)", 10.0, S, "int"),
        form("bit_trick", """
def pow2_bits(n: int) -> bool:
    return n > 0 and (n & (n - 1)) == 0""", "O(1)", 1.0, domain="int")], ["bits"]),

    algo("isqrt", "floor(sqrt(n)) for n >= 0", [("n", "int")], "int", "n >= 0", [{"int": [0, 10**12]}], "newton", [
        form("linear", """
def isqrt_linear(n: int) -> int:
    r = 0
    while (r + 1) * (r + 1) <= n:
        r += 1
    return r""", "O(sqrt n)", 100.0, S, "small_int"),
        form("binary_search", """
def isqrt_bisect(n: int) -> int:
    lo = 0
    hi = n + 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if mid * mid <= n:
            lo = mid
        else:
            hi = mid
    return lo""", "O(log n)", 8.0),
        form("newton", """
def isqrt_newton(n: int) -> int:
    if n < 2:
        return n
    x = n
    y = (x + 1) // 2
    while y < x:
        x = y
        y = (x + n // x) // 2
    return x""", "O(log log n)", 4.0)], ["math"], small=[{"int": [0, 100000]}]),

    algo("sum_of_divisors", "sum of positive divisors of n (0 for n <= 0)", [("n", "int")], "int", None,
         [{"int": [-10, 200000]}], "sqrt_pairs", [
        form("linear", """
def sigma_linear(n: int) -> int:
    if n <= 0:
        return 0
    s = 0
    for d in range(1, n + 1):
        if n % d == 0:
            s += d
    return s""", "O(n)", 100.0, S, "int"),
        form("sqrt_pairs", """
def sigma_sqrt(n: int) -> int:
    if n <= 0:
        return 0
    s = 0
    d = 1
    while d * d <= n:
        if n % d == 0:
            s += d
            if d * d != n:
                s += n // d
        d += 1
    return s""", "O(sqrt n)", 10.0, domain="int")], ["math", "number_theory"]),

    algo("digital_root", "repeated digit sum of |n| down to one digit", [("n", "int")], "int", None,
         [{"int": [-10**9, 10**9]}], "closed_form", [
        form("iterate", """
def droot_loop(n: int) -> int:
    n = abs(n)
    while n >= 10:
        s = 0
        while n > 0:
            s += n % 10
            n = n // 10
        n = s
    return n""", "O(digits)", 10.0, S, "int"),
        form("closed_form", """
def droot_closed(n: int) -> int:
    n = abs(n)
    if n == 0:
        return 0
    return 1 + (n - 1) % 9""", "O(1)", 1.0, domain="int")], ["math", "digits"]),

    algo("cubic_eval", "a*x^3 + b*x^2 + c*x + d (integers)", [("a", "int"), ("b", "int"), ("c", "int"), ("d", "int"),
                                                             ("x", "int")], "int", None,
         [{"int": [-100, 100]}] * 5, "horner", [
        form("powers", """
def cubic_pow(a: int, b: int, c: int, d: int, x: int) -> int:
    return a * x ** 3 + b * x ** 2 + c * x + d""", "3 POW + 3 MUL", 70.0, S, "int"),
        form("horner", """
def cubic_horner(a: int, b: int, c: int, d: int, x: int) -> int:
    return ((a * x + b) * x + c) * x + d""", "3 MUL + 3 ADD", 6.0, domain="int")], ["math", "polynomial"]),
]
