"""godel1931 — Gödel's 46 definitions (1931, section 2), as runnable functions on codes (Gödel method W-1).

  system P   signs 0 -> 1, succ -> 3, ¬ -> 5, ∨ -> 7, ∀ -> 9, ( -> 11, ) -> 13; a variable of type n is p^n for a prime
             p > 13; a sequence n1 ... nk is 2^n1 · 3^n2 · ... · p_k^nk. Names follow Martin Hirzel's translation.
  forms      ``DEFINITIONS`` lists the 46 with their number and name. Each Python function computes Gödel's function
             (relation) on its codes: the bounded searches of definitions 1 to 45 are replaced by direct computations
             of the same value (``literal`` keeps the searches themselves, runnable on small codes, so the two can be
             compared). Bounded minimization is 0 when nothing below the bound qualifies, as in the paper.
  levels     a formula is a sequence of signs, coded as one integer. A sequence of formulas (definitions 22, 44, 45)
             is coded one level up, 2^Φ(f1) · 3^Φ(f2) · ...: its exponents are formula codes, so it has about Φ(f1)
             bits (Ph-3). Such a sequence is never built: it is handled as the list of its items, which is exactly
             what item(n, x) and length(x) read from it.
  equality   P writes x = y as ∀x2 (x2(x) ⇒ x2(y)) one type up (Gödel, footnote to section 2.1); the Peano axioms
             pa1 to pa3 and the set axiom sa are the codes of the formulas so expanded (``PA``, ``SA``).

Honest limits (L1): factoring a code divides out its prime factors in order, so it is fast for codes of sequences
(they are smooth) and refuses a number with a prime factor past the 20,000th prime. ``provable`` (definition 46)
is not primitive recursive: it is a Σ1 search, and here it only checks the candidate proofs it is given.
"""
from __future__ import annotations

from functools import lru_cache

ZERO, SUCC, NOT, OR, FORALL, LP, RP = 1, 3, 5, 7, 9, 11, 13
_PRIMES: list[int] = [2]
PRIME_LIMIT = 20000


def _prime(i: int) -> int:
    """The i-th prime, 1-based."""
    c = _PRIMES[-1] + 1
    while len(_PRIMES) < i:
        if all(c % p for p in _PRIMES if p * p <= c):
            _PRIMES.append(c)
        c += 1
    return _PRIMES[i - 1]


def _valuation(x: int, p: int) -> tuple[int, int]:
    """(e, x / p^e) with p^e the largest power of p dividing x: by repeated squaring, so a code whose exponent is
    itself a large sign code (a type-lifted variable: 17^5 = 1,419,857) costs about log2(e) divisions, not e."""
    if x % p:
        return 0, x
    powers = [p]
    while x % (powers[-1] * powers[-1]) == 0:
        powers.append(powers[-1] * powers[-1])
    e = 0
    for i in range(len(powers) - 1, -1, -1):
        if x % powers[i] == 0:
            x //= powers[i]
            e += 1 << i
    while x % p == 0:
        x //= p
        e += 1
    return e, x


@lru_cache(maxsize=4096)
def _factor(x: int) -> tuple:
    """((prime, exponent), ...) by size, for x >= 1; dividing out primes in order."""
    if x < 1:
        raise ValueError("factor of 0")
    out, i = [], 1
    while x > 1:
        p = _prime(i)
        if p * p > x:
            out.append((x, 1))
            break
        if i > PRIME_LIMIT:
            raise ValueError("a prime factor past the factoring limit")
        e, x = _valuation(x, p)
        if e:
            out.append((p, e))
        i += 1
    return tuple(out)


# -- 1 to 9: numbers and sequences ----------------------------------------------------------------------------------
def divides(y: int, x: int) -> bool:                        # 1: y | x  <=>  ∃z ≤ x. x = y·z
    return x == 0 or (y != 0 and x % y == 0)


def is_prime(x: int) -> bool:                               # 2
    return x > 1 and all(x % d for d in range(2, int(x ** 0.5) + 1)) if x < 1 << 40 else _is_prime_big(x)


def _is_prime_big(x: int) -> bool:
    f = _factor(x)
    return len(f) == 1 and f[0][1] == 1


def pr_factor(n: int, x: int) -> int:                       # 3: the n-th prime factor of x by size
    """As the recursion is written: the smallest prime factor above prFactor(n-1, x), 0 when there is none, so past
    the last factor it gives 0 and then starts again from the smallest (period: the number of factors plus one)."""
    if n == 0 or x == 0:
        return 0
    f = _factor(x)
    m = n % (len(f) + 1)
    return f[m - 1][0] if m else 0


def factorial(n: int) -> int:                               # 4
    out = 1
    for k in range(2, n + 1):
        out *= k
    return out


def nth_prime(n: int) -> int:                               # 5: nthPrime(0) = 0, nthPrime(1) = 2
    return 0 if n == 0 else _prime(n)


def item(n: int, x: int) -> int:                            # 6: the exponent of the n-th prime factor
    if x == 0:
        return 0
    p = pr_factor(n, x)
    if p == 0:
        return 0
    return dict(_factor(x))[p]


def length(x: int) -> int:                                  # 7: how many distinct prime factors
    return 0 if x < 2 else len(_factor(x))


def items(x: int) -> list[int]:
    """item(1, x) ... item(length(x), x)."""
    return [e for _, e in _factor(x)] if x >= 2 else []


def code(signs: list[int]) -> int:
    """2^s1 · 3^s2 · ...: the number of a sequence (every entry at least 1)."""
    n = 1
    for i, s in enumerate(signs, start=1):
        n *= _prime(i) ** s
    return n


def is_sequence(x: int) -> bool:
    """x codes a sequence: its prime factors are the first length(x) primes."""
    return x >= 2 and all(p == _prime(i) for i, (p, _) in enumerate(_factor(x), start=1))


def concat(x: int, y: int) -> int:                          # 8: x ∘ y
    return code(items(x) + items(y))


def seq(x: int) -> int:                                     # 9: the one-entry sequence (x)
    return 2 ** x


# -- 10 to 21: signs, types and formulas -----------------------------------------------------------------------------
def paren(x: int) -> int:                                   # 10
    return code([LP] + items(x) + [RP])


def vtype(n: int, x: int) -> bool:                          # 11: x = z^n, z a prime > 13, n ≠ 0
    if n == 0 or x < 17:
        return False
    f = _factor(x)
    return len(f) == 1 and f[0][0] > 13 and f[0][1] == n


def is_var(x: int) -> bool:                                 # 12
    if x < 17:
        return False
    f = _factor(x)
    return len(f) == 1 and f[0][0] > 13


def var_type(x: int) -> int:
    return _factor(x)[0][1] if is_var(x) else 0


def neg(x: int) -> int:                                     # 13: not(x)
    return code([NOT, LP] + items(x) + [RP])


def disj(x: int, y: int) -> int:                            # 14: or(x, y)
    return code([LP] + items(x) + [RP, OR, LP] + items(y) + [RP])


def forall(x: int, y: int) -> int:                          # 15
    return code([FORALL, x, LP] + items(y) + [RP])


def succ_n(n: int, x: int) -> int:                          # 16: 'succ' written n times in front of x
    return code([SUCC] * n + items(x))


def number(n: int) -> int:                                  # 17: the numeral of n
    return succ_n(n, seq(ZERO))


def _stype1_signs(s: list[int]) -> bool:
    if not s:
        return False
    k = 0
    while k < len(s) and s[k] == SUCC:
        k += 1
    return k == len(s) - 1 and (s[-1] == ZERO or (is_var(s[-1]) and var_type(s[-1]) == 1))


def stype1(x: int) -> bool:                                 # 18: a sign of type 1
    return is_sequence(x) and _stype1_signs(items(x))


def _stype_signs(n: int, s: list[int]) -> bool:
    if n == 1:
        return _stype1_signs(s)
    return n > 1 and len(s) == 1 and is_var(s[0]) and var_type(s[0]) == n


def stype(n: int, x: int) -> bool:                          # 19: a sign of type n
    return is_sequence(x) and _stype_signs(n, items(x))


def _el_fm_signs(s: list[int]) -> bool:
    if len(s) < 4 or s[1] != LP or s[-1] != RP or not is_var(s[0]):
        return False
    n = var_type(s[0]) - 1
    return n >= 1 and _stype_signs(n, s[2:-1])


def el_fm(x: int) -> bool:                                  # 20: an elementary formula a(b)
    return is_sequence(x) and _el_fm_signs(items(x))


def op(x: int, y: int, z: int) -> bool:                     # 21: x is ¬y, y ∨ z, or ∀v.y
    if not is_sequence(x):
        return False
    if x == neg(y) or x == disj(y, z):
        return True
    s = items(x)
    return len(s) >= 2 and s[0] == FORALL and is_var(s[1]) and x == forall(s[1], y)


# -- parsing: the formula tree a code stands for -------------------------------------------------------------------
def _group(s: list[int], i: int) -> int | None:
    """The index just past the parenthesized group opening at s[i]."""
    if i >= len(s) or s[i] != LP:
        return None
    depth = 0
    for j in range(i, len(s)):
        depth += s[j] == LP
        depth -= s[j] == RP
        if depth == 0:
            return j + 1
    return None


@lru_cache(maxsize=8192)
def parse(signs: tuple) -> tuple | None:
    """('el', signs) | ('not', a) | ('or', a, b) | ('all', v, a); None when the signs are no formula."""
    s = list(signs)
    if not s:
        return None
    if s[0] == NOT:
        end = _group(s, 1)
        if end == len(s):
            a = parse(tuple(s[2:-1]))
            return ("not", a) if a else None
        return None
    if s[0] == FORALL:
        if len(s) < 2 or not is_var(s[1]):
            return None
        end = _group(s, 2)
        if end == len(s):
            a = parse(tuple(s[3:-1]))
            return ("all", s[1], a) if a else None
        return None
    if s[0] == LP:
        mid = _group(s, 0)
        if mid is None or mid >= len(s) or s[mid] != OR or _group(s, mid + 1) != len(s):
            return None
        a, b = parse(tuple(s[1:mid - 1])), parse(tuple(s[mid + 2:-1]))
        return ("or", a, b) if a and b else None
    return ("el", tuple(s)) if _el_fm_signs(s) else None


def signs_of(tree) -> list[int]:
    k = tree[0]
    if k == "el":
        return list(tree[1])
    if k == "not":
        return [NOT, LP] + signs_of(tree[1]) + [RP]
    if k == "or":
        return [LP] + signs_of(tree[1]) + [RP, OR, LP] + signs_of(tree[2]) + [RP]
    return [FORALL, tree[1], LP] + signs_of(tree[2]) + [RP]


# -- 22 to 33: formulas, variables, substitution -------------------------------------------------------------------
def fm_seq(xs: list[int]) -> bool:                          # 22: a formula-building sequence (given by its items)
    if not xs:
        return False
    for n, x in enumerate(xs):
        if el_fm(x):
            continue
        if not any(op(x, xs[p], xs[q]) for p in range(n) for q in range(n)):
            return False
    return True


def is_fm(x: int) -> bool:                                  # 23: x is a formula
    return is_sequence(x) and parse(tuple(items(x))) is not None


def _bound_positions(s: list[int], v: int) -> set[int]:
    """1-based positions of s lying inside a subformula ∀v(b) (b a formula)."""
    out = set()
    for a in range(len(s)):
        if s[a] == FORALL and a + 1 < len(s) and s[a + 1] == v:
            end = _group(s, a + 2)
            if end is not None and parse(tuple(s[a + 3:end - 1])) is not None:
                out.update(range(a + 1, end + 1))
    return out


def bound(v: int, n: int, x: int) -> bool:                  # 24: v is bound in x at position n
    if not (is_var(v) and is_fm(x)):
        return False
    return n in _bound_positions(items(x), v)


def free_at(v: int, n: int, x: int) -> bool:                # 25: v is free in x at position n
    if not (is_var(v) and is_fm(x)):
        return False
    s = items(x)
    return 1 <= n <= len(s) and s[n - 1] == v and n not in _bound_positions(s, v)


def free(v: int, x: int) -> bool:                           # 26: v occurs free in x
    return any(free_at(v, n, x) for n in range(1, length(x) + 1))


def insert(x: int, n: int, y: int) -> int:                  # 27: x with its n-th item replaced by the sequence y
    s = items(x)
    if not 1 <= n <= len(s):
        return 0
    return code(s[:n - 1] + items(y) + s[n:])


def _free_places(v: int, x: int) -> list[int]:
    if not (is_var(v) and is_fm(x)):
        return []
    s = items(x)
    b = _bound_positions(s, v)
    return [n for n in range(1, len(s) + 1) if s[n - 1] == v and n not in b]


def free_place(k: int, v: int, x: int) -> int:              # 28: the (k+1)-th free place from the end, 0 if none
    places = _free_places(v, x)
    return places[-1 - k] if k < len(places) else 0


def n_free_places(v: int, x: int) -> int:                   # 29
    return len(_free_places(v, x))


def subst_k(k: int, x: int, v: int, y: int) -> int:         # 30: subst'(k, x, v, y)
    out = x
    for j in range(k):
        out = insert(out, free_place(j, v, x), y)
    return out


def subst(x: int, v: int, y: int) -> int:                   # 31: y for every free v in x
    return subst_k(n_free_places(v, x), x, v, y)


def imp(x: int, y: int) -> int:                             # 32: the defined connectives
    return disj(neg(x), y)


def conj(x: int, y: int) -> int:
    return neg(disj(neg(x), neg(y)))


def equiv(x: int, y: int) -> int:
    return conj(imp(x, y), imp(y, x))


def exists(v: int, y: int) -> int:
    return neg(forall(v, neg(y)))


def type_lift(n: int, x: int) -> int:                       # 33: every variable's type raised by n
    return code([s if s <= 13 else s * pr_factor(1, s) ** n for s in items(x)])


# -- 34 to 46: axioms, consequence, proofs -------------------------------------------------------------------------
def var(name: str, typ: int) -> int:
    """The variable code: x, y, z, ... on the primes 17, 19, 23, ... to the power of the type."""
    return _prime(7 + "xyzuvw".index(name)) ** typ


def el(fun: int, arg_signs: list[int]) -> int:
    """The elementary formula fun(arg), fun a variable one type above the sign arg."""
    return code([fun, LP] + arg_signs + [RP])


def eq(a: list[int], b: list[int], typ: int) -> int:
    """a = b for signs of type ``typ``: ∀x(typ+1) (x(a) ⇒ x(b))."""
    z = var("x", typ + 1)
    return forall(z, imp(el(z, a), el(z, b)))


X1, Y1, X2, Y2 = var("x", 1), var("y", 1), var("x", 2), var("y", 2)
PA = (
    neg(eq([SUCC, X1], [ZERO], 1)),                                                     # I.1 ¬(succ(x1) = 0)
    imp(eq([SUCC, X1], [SUCC, Y1], 1), eq([X1], [Y1], 1)),                              # I.2
    imp(conj(el(X2, [ZERO]), forall(X1, imp(el(X2, [X1]), el(X2, [SUCC, X1])))),     # I.3 induction
        forall(X1, el(X2, [X1]))),
)
SA = imp(forall(X1, equiv(el(X2, [X1]), el(Y2, [X1]))), eq([X2], [Y2], 2))           # V.1 extensionality


def peano_axiom(x: int) -> bool:                            # 34
    return x in PA


def _imp_parts(x: int):
    """(a, b) when x = imp(a, b) = (¬(a)) ∨ (b), as codes."""
    t = parse(tuple(items(x))) if is_sequence(x) else None
    if t and t[0] == "or" and t[1][0] == "not":
        return code(signs_of(t[1][1])), code(signs_of(t[2]))
    return None


def _or_parts(x: int):
    t = parse(tuple(items(x))) if is_sequence(x) else None
    if t and t[0] == "or":
        return code(signs_of(t[1])), code(signs_of(t[2]))
    return None


def prop1_axiom(x: int) -> bool:                            # 35: p ∨ p ⇒ p
    ab = _imp_parts(x)
    if not ab:
        return False
    o = _or_parts(ab[0])
    return bool(o) and o[0] == o[1] == ab[1] and is_fm(ab[1])


def prop2_axiom(x: int) -> bool:                            # p ⇒ p ∨ q
    ab = _imp_parts(x)
    o = _or_parts(ab[1]) if ab else None
    return bool(o) and o[0] == ab[0] and is_fm(o[0]) and is_fm(o[1])


def prop3_axiom(x: int) -> bool:                            # p ∨ q ⇒ q ∨ p
    ab = _imp_parts(x)
    if not ab:
        return False
    o1, o2 = _or_parts(ab[0]), _or_parts(ab[1])
    return bool(o1 and o2) and o1 == (o2[1], o2[0]) and is_fm(o1[0]) and is_fm(o1[1])


def prop4_axiom(x: int) -> bool:                            # (p ⇒ q) ⇒ (r ∨ p ⇒ r ∨ q)
    ab = _imp_parts(x)
    if not ab:
        return False
    pq, rr = _imp_parts(ab[0]), _imp_parts(ab[1])
    if not (pq and rr):
        return False
    rp, rq = _or_parts(rr[0]), _or_parts(rr[1])
    return bool(rp and rq) and rp[0] == rq[0] and rp[1] == pq[0] and rq[1] == pq[1] and \
        all(is_fm(f) for f in (pq[0], pq[1], rp[0]))


def prop_axiom(x: int) -> bool:                             # 36
    return prop1_axiom(x) or prop2_axiom(x) or prop3_axiom(x) or prop4_axiom(x)


def quantor1_axiom_condition(z: int, y: int, v: int) -> bool:   # 37: substituting z for v in y captures nothing
    zs = items(z)
    ys = items(y)
    for n in range(1, len(ys) + 1):
        if not free_at(v, n, y):
            continue
        for w in zs:
            if is_var(w) and n in _bound_positions(ys, w):
                return False
    return True


def quantor1_axiom(x: int) -> bool:                         # 38: ∀v.a ⇒ subst(a, v, c)
    ab = _imp_parts(x)
    if not ab:
        return False
    t = parse(tuple(items(ab[0])))
    if not t or t[0] != "all":
        return False
    v, y = t[1], code(signs_of(t[2]))
    target = items(ab[1])
    # c is a sign of v's type; find the c that makes subst(y, v, c) the consequent
    places = _free_places(v, y)
    if not places:
        return ab[1] == y                                       # nothing to replace: any c of v's type, v itself
    ys = items(y)
    first = places[0]
    k = len(target) - (len(ys) - len(places))
    if k <= 0 or k % len(places):
        return False
    width = k // len(places)
    c = code(target[first - 1:first - 1 + width])
    return stype(var_type(v), c) and quantor1_axiom_condition(c, y, v) and subst(y, v, c) == ab[1]


def quantor2_axiom(x: int) -> bool:                         # 39: ∀v(p ∨ q) ⇒ p ∨ ∀v.q, v not free in p
    ab = _imp_parts(x)
    if not ab:
        return False
    t = parse(tuple(items(ab[0])))
    if not t or t[0] != "all" or t[2][0] != "or":
        return False
    v, p, q = t[1], code(signs_of(t[2][1])), code(signs_of(t[2][2]))
    return not free(v, p) and ab[1] == disj(p, forall(v, q))


def redu_axiom(x: int) -> bool:                             # 40: ∃u ∀v (u(v) ⇔ y), u not free in y
    if not is_fm(x):
        return False
    t = parse(tuple(items(x)))
    # exists(u, A) = ¬(∀u(¬(A)))
    if not (t[0] == "not" and t[1][0] == "all" and t[1][2][0] == "not"):
        return False
    u = t[1][1]
    inner = t[1][2][1]
    if inner[0] != "all":
        return False
    v = inner[1]
    body = code(signs_of(inner[2]))
    for y_tree in _equiv_right(body, el(u, [v])):
        y = code(signs_of(y_tree))
        if var_type(u) == var_type(v) + 1 and not free(u, y) and x == exists(u, forall(v, equiv(el(u, [v]), y))):
            return True
    return False


def _equiv_right(x: int, left: int):
    """The trees y with x = equiv(left, y)."""
    t = parse(tuple(items(x)))
    # equiv(a, b) = conj(imp(a, b), imp(b, a)) = ¬((¬(imp(a,b))) ∨ (¬(imp(b,a))))
    try:
        if t[0] == "not" and t[1][0] == "or":
            first = code(signs_of(t[1][1][1]))
            ab = _imp_parts(first)
            if ab and ab[0] == left:
                yield parse(tuple(items(ab[1])))
    except (IndexError, TypeError):
        return


SA_SIGNS = None


def _sa_signs() -> list[int]:
    global SA_SIGNS
    if SA_SIGNS is None:
        SA_SIGNS = items(SA)
    return SA_SIGNS


def lift_bits(n: int) -> float:
    """The bit length of typeLift(n, sa), from its signs, without building it: Σ c_i·log2 p_i."""
    import math
    total = 0.0
    for i, c in enumerate(_sa_signs(), start=1):
        lifted = c * pr_factor(1, c) ** n if c > 13 else c
        total += lifted * math.log2(_prime(i))
    return total


def set_axiom(x: int) -> bool:                              # 41: x = typeLift(n, sa) for some n ≤ x
    """The lifts grow strictly with n, so at most one n has x's size: it is found from the size formula and compared
    once. The integer x is never factored (typeLift(2, sa) alone has about 40 million bits)."""
    if x < SA:
        return False
    bits = x.bit_length()
    for n in range(0, 64):
        b = lift_bits(n)
        if b > bits + 2:
            return False
        if abs(b - bits) <= 2 and type_lift(n, SA) == x:
            return True
    return False


def is_axiom(x: int) -> bool:                               # 42
    return peano_axiom(x) or prop_axiom(x) or quantor1_axiom(x) or quantor2_axiom(x) or redu_axiom(x) or \
        set_axiom(x)


def imm_conseq(x: int, y: int, z: int) -> bool:             # 43: x from y and z by modus ponens, or x = ∀v.y
    if y == imp(z, x):
        return True
    s = items(x)
    return len(s) >= 2 and s[0] == FORALL and is_var(s[1]) and x == forall(s[1], y)


def is_proof_figure(xs: list[int]) -> bool:                 # 44: every item an axiom or a consequence of earlier ones
    if not xs:
        return False
    for n, x in enumerate(xs):
        if is_axiom(x):
            continue
        if not any(imm_conseq(x, xs[p], xs[q]) for p in range(n) for q in range(n)):
            return False
    return True


def proof_for(xs: list[int], y: int) -> bool:               # 45
    return is_proof_figure(xs) and bool(xs) and xs[-1] == y


def provable(x: int, candidates) -> bool | None:            # 46: Σ1, confirmed by a proof among the candidates
    return True if any(proof_for(list(c), x) for c in candidates) else None


DEFINITIONS = [
    (1, "divides", "y ∣ x", divides), (2, "isPrime", "isPrime(x)", is_prime),
    (3, "prFactor", "prFactor(n, x)", pr_factor), (4, "factorial", "n!", factorial),
    (5, "nthPrime", "nthPrime(n)", nth_prime), (6, "item", "item(n, x)", item), (7, "length", "length(x)", length),
    (8, "concat", "x ∘ y", concat), (9, "seq", "seq(x)", seq), (10, "paren", "paren(x)", paren),
    (11, "vtype", "vtype(n, x)", vtype), (12, "isVar", "isVar(x)", is_var), (13, "not", "not(x)", neg),
    (14, "or", "or(x, y)", disj), (15, "forall", "forall(x, y)", forall), (16, "succN", "succ_n(n, x)", succ_n),
    (17, "number", "number(n)", number), (18, "stype1", "stype1(x)", stype1), (19, "stype", "stype(n, x)", stype),
    (20, "elFm", "elFm(x)", el_fm), (21, "op", "op(x, y, z)", op), (22, "fmSeq", "fmSeq(x)", fm_seq),
    (23, "isFm", "isFm(x)", is_fm), (24, "bound", "bound(v, n, x)", bound),
    (25, "freeAt", "free(v, n, x)", free_at), (26, "free", "free(v, x)", free),
    (27, "insert", "insert(x, n, y)", insert), (28, "freePlace", "freePlace(k, v, x)", free_place),
    (29, "nFreePlaces", "nFreePlaces(v, x)", n_free_places), (30, "substK", "subst′(k, x, v, y)", subst_k),
    (31, "subst", "subst(x, v, y)", subst), (32, "connectives", "imp, and, equiv, exists", imp),
    (33, "typeLift", "typeLift(n, x)", type_lift), (34, "peanoAxiom", "peanoAxiom(x)", peano_axiom),
    (35, "prop1Axiom", "prop1Axiom(x) to prop4Axiom(x)", prop1_axiom), (36, "propAxiom", "propAxiom(x)", prop_axiom),
    (37, "quantor1AxiomCondition", "quantor1AxiomCondition(z, y, v)", quantor1_axiom_condition),
    (38, "quantor1Axiom", "quantor1Axiom(x)", quantor1_axiom), (39, "quantor2Axiom", "quantor2Axiom(x)", quantor2_axiom),
    (40, "reduAxiom", "reduAxiom(x)", redu_axiom), (41, "setAxiom", "setAxiom(x)", set_axiom),
    (42, "isAxiom", "isAxiom(x)", is_axiom), (43, "immConseq", "immConseq(x, y, z)", imm_conseq),
    (44, "isProofFigure", "isProofFigure(x)", is_proof_figure), (45, "proofFor", "proofFor(x, y)", proof_for),
    (46, "provable", "provable(x)", provable),
]


def p_implies_p() -> tuple[list[int], int]:
    """A proof of p ⇒ p from the propositional schemas (p the elementary formula x2(x1)), and its last formula."""
    p = el(X2, [X1])
    pp = disj(p, p)
    f1 = imp(imp(pp, p), imp(disj(neg(p), pp), disj(neg(p), p)))    # II.4 with p := p ∨ p, q := p, r := ¬p
    f2 = imp(pp, p)                                                  # II.1
    f3 = imp(disj(neg(p), pp), disj(neg(p), p))                      # from f1 and f2
    f4 = imp(p, pp)                                                  # II.2 with q := p, which is ¬p ∨ (p ∨ p)
    f5 = disj(neg(p), p)                                             # from f3 and f4: p ⇒ p
    return [f1, f2, f3, f4, f5], imp(p, p)


# -- the searches themselves, for small codes -------------------------------------------------------------------------
class literal:
    """Definitions 1 to 12 and 16 to 18 exactly as the paper writes them, bounded searches and all; usable only on
    small numbers, to check the direct computations against."""

    @staticmethod
    def argmin(bound: int, pred) -> int:
        return next((y for y in range(bound + 1) if pred(y)), 0)

    @staticmethod
    def divides(y, x):
        return any(x == y * z for z in range(x + 1))

    @staticmethod
    def is_prime(x):
        return not any(z != 1 and z != x and literal.divides(z, x) for z in range(x + 1)) and x > 1

    @staticmethod
    def pr_factor(n, x):
        if n == 0:
            return 0
        prev = literal.pr_factor(n - 1, x)
        return literal.argmin(x, lambda y: literal.is_prime(y) and literal.divides(y, x) and y > prev)

    @staticmethod
    def nth_prime(n):
        if n == 0:
            return 0
        prev = literal.nth_prime(n - 1)
        return literal.argmin(factorial(prev) + 1, lambda y: literal.is_prime(y) and y > prev)

    @staticmethod
    def item(n, x):
        p = literal.pr_factor(n, x)
        return literal.argmin(x, lambda y: literal.divides(p ** y, x) and not literal.divides(p ** (y + 1), x))

    @staticmethod
    def length(x):
        return literal.argmin(x, lambda y: literal.pr_factor(y, x) > 0 and literal.pr_factor(y + 1, x) == 0)

    @staticmethod
    def vtype(n, x):
        return any(literal.is_prime(z) and x == z ** n for z in range(14, x + 1)) and n != 0

    @staticmethod
    def is_var(x):
        return any(literal.vtype(n, x) for n in range(x + 1))


# -- witnesses: generated codes, the Lean forms, the literal searches ----------------------------------------------
LEAN_NAMES = {"neg": "not", "disj": "or", "conj": "and"}


def random_sign(rng, typ: int) -> list[int]:
    """A sign of type ``typ``: succ^k of 0 or of a type-1 variable; a variable for higher types."""
    if typ == 1:
        base = ZERO if rng.random() < 0.4 else var(rng.choice("xyz"), 1)
        return [SUCC] * rng.randint(0, 2) + [base]
    return [var(rng.choice("xyz"), typ)]


def random_tree(rng, depth: int = 3, max_type: int = 2):
    """A formula of P, as a tree."""
    if depth == 0 or rng.random() < 0.3:
        n = rng.randint(1, max_type)
        return ("el", tuple([var(rng.choice("xyz"), n + 1), LP] + random_sign(rng, n) + [RP]))
    k = rng.random()
    if k < 0.33:
        return ("not", random_tree(rng, depth - 1, max_type))
    if k < 0.66:
        return ("or", random_tree(rng, depth - 1, max_type), random_tree(rng, depth - 1, max_type))
    return ("all", var(rng.choice("xyz"), rng.randint(1, max_type)), random_tree(rng, depth - 1, max_type))


def cases(rng, k: int = 12) -> list[tuple[str, list]]:
    """Calls covering definitions 1 to 45 on generated codes, small numbers and corrupted codes."""
    out: list[tuple[str, list]] = []
    fms = [code(signs_of(random_tree(rng))) for _ in range(k)]
    proof, target = p_implies_p()
    vars_ = [var(c, t) for c in "xyz" for t in (1, 2, 3)]
    for _ in range(k):
        a, b, n = rng.randint(0, 400), rng.randint(0, 400), rng.randint(0, 6)
        out += [("divides", [n, a]), ("isPrime", [a]), ("prFactor", [n, a]), ("factorial", [n]),
                ("nthPrime", [n]), ("item", [n, a]), ("length", [a]), ("seq", [n]), ("number", [n]),
                ("vtype", [n % 3 + 1, rng.choice(vars_ + [a])]), ("isVar", [rng.choice(vars_ + [a, b])])]
    for f in fms:
        g = rng.choice(fms)
        v = rng.choice(vars_)
        signs = items(f)
        pos = rng.randint(1, len(signs))
        sign1 = code(random_sign(rng, 1))
        out += [("item", [pos, f]), ("length", [f]), ("concat", [f, g]), ("paren", [f]), ("not", [f]),
                ("or", [f, g]), ("forall", [v, f]), ("succN", [2, sign1]), ("stype1", [sign1]),
                ("stype", [var_type(v), code([v])]), ("elFm", [f]), ("elFm", [code(signs[: max(1, len(signs) - 1)])]),
                ("op", [neg(f), f, g]), ("op", [disj(f, g), f, g]), ("op", [f, g, f]), ("fmSeq", [[f, neg(f), disj(f, g)]]),
                ("fmSeq", [[neg(f)]]), ("isFm", [f]), ("isFm", [f * 7 if f % 7 else f * 11]), ("bound", [v, pos, forall(v, f)]),
                ("freeAt", [v, pos, f]), ("free", [v, f]), ("insert", [f, pos, code(random_sign(rng, 1))]),
                ("freePlace", [0, v, f]), ("nFreePlaces", [v, f]), ("substK", [1, f, v, code(random_sign(rng, var_type(v)))]),
                ("subst", [f, v, code(random_sign(rng, var_type(v)))]), ("imp", [f, g]), ("and", [f, g]),
                ("equiv", [f, g]), ("exists", [v, f]), ("typeLift", [1, f]), ("peanoAxiom", [f]),
                ("prop1Axiom", [imp(disj(f, f), f)]), ("prop2Axiom", [imp(f, disj(f, g))]),
                ("prop3Axiom", [imp(disj(f, g), disj(g, f))]), ("prop4Axiom", [imp(imp(f, g), imp(disj(f, f), disj(f, g)))]),
                ("propAxiom", [imp(f, g)]), ("quantor1AxiomCondition", [code(random_sign(rng, 1)), f, v]),
                ("quantor1Axiom", [imp(forall(v, f), subst(f, v, code(random_sign(rng, var_type(v)))))]),
                ("quantor2Axiom", [imp(forall(v, disj(f, g)), disj(f, forall(v, g)))]),
                ("reduAxiom", [exists(var("u", 3), forall(var("v", 2), equiv(el(var("u", 3), [var("v", 2)]), f)))]),
                ("setAxiom", [f]), ("isAxiom", [f]), ("immConseq", [g, imp(f, g), f]), ("immConseq", [forall(v, f), f, g])]
    out += [("peanoAxiom", [x]) for x in PA] + [("setAxiom", [SA]), ("isAxiom", [SA]),
                                                 ("isProofFigure", [proof]), ("proofFor", [proof, target]),
                                                 ("isProofFigure", [proof[1:]]), ("proofFor", [proof[:-1], target])]
    return out


PY = {"divides": divides, "isPrime": is_prime, "prFactor": pr_factor, "factorial": factorial, "nthPrime": nth_prime,
      "item": item, "length": length, "concat": concat, "seq": seq, "paren": paren, "vtype": vtype, "isVar": is_var,
      "not": neg, "or": disj, "forall": forall, "succN": succ_n, "number": number, "stype1": stype1, "stype": stype,
      "elFm": el_fm, "op": op, "fmSeq": fm_seq, "isFm": is_fm, "bound": bound, "freeAt": free_at, "free": free,
      "insert": insert, "freePlace": free_place, "nFreePlaces": n_free_places, "substK": subst_k, "subst": subst,
      "imp": imp, "and": conj, "equiv": equiv, "exists": exists, "typeLift": type_lift, "peanoAxiom": peano_axiom,
      "prop1Axiom": prop1_axiom, "prop2Axiom": prop2_axiom, "prop3Axiom": prop3_axiom, "prop4Axiom": prop4_axiom,
      "propAxiom": prop_axiom, "quantor1AxiomCondition": quantor1_axiom_condition, "quantor1Axiom": quantor1_axiom,
      "quantor2Axiom": quantor2_axiom, "reduAxiom": redu_axiom, "setAxiom": set_axiom, "isAxiom": is_axiom,
      "immConseq": imm_conseq, "isProofFigure": is_proof_figure, "proofFor": proof_for}


P1, P2 = 2 ** 61 - 1, 2305843009213693921


def _show(v) -> str:
    """As the Lean executable prints: booleans, numbers below 2^64, and larger numbers by fingerprint."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if v < 1 << 64:
        return str(v)
    return f"N{v.bit_length()}:{v % P1}:{v % P2}"


def _arg(a) -> str:
    """An argument for the Lean executable: a sign sequence's code as its signs, so no huge number is printed."""
    if isinstance(a, list):
        return "L" + ";".join(".".join(map(str, items(x))) for x in a)
    if a >= 1 << 64 and is_sequence(a):
        return "S" + ".".join(map(str, items(a)))
    return str(a)


def run_python(calls: list[tuple[str, list]]) -> list[str]:
    import sys
    sys.set_int_max_str_digits(0)                       # codes have tens of thousands of digits
    return [_show(PY[name](*args)) for name, args in calls]


def lean_exe():
    from . import formal as F
    exe = F.root() / ".lake" / "build" / "bin" / "godel1931"
    return exe if exe.is_file() else None


def run_lean(calls: list[tuple[str, list]], timeout: float = 600) -> list[str] | None:
    """The Lean forms' answers to the same calls, from formal/Godel1931's executable; None when it is not built."""
    import subprocess
    import sys
    exe = lean_exe()
    if exe is None:
        return None
    sys.set_int_max_str_digits(0)
    lines = [" ".join([name] + [_arg(a) for a in args]) for name, args in calls]
    p = subprocess.run([str(exe)], input="\n".join(lines) + "\n", capture_output=True, text=True, timeout=timeout)
    return p.stdout.splitlines()


def agree(seed: int, k: int = 12) -> dict:
    """The Python and Lean forms on the same generated calls: how many calls per definition, and any disagreement."""
    import random
    from collections import Counter
    calls = cases(random.Random(seed), k)
    py = run_python(calls)
    ln = run_lean(calls)
    per = Counter(name for name, _ in calls)
    if ln is None:
        return {"status": "skipped", "reason": "the Lean executable is not built (lake build in formal/)",
                "calls": len(calls), "per_definition": dict(per)}
    bad = [{"call": name, "python": a[:80], "lean": b[:80]} for (name, _), a, b in zip(calls, py, ln) if a != b]
    if len(ln) != len(py):
        bad.append({"call": "*", "python": f"{len(py)} answers", "lean": f"{len(ln)} answers"})
    return {"status": "fail" if bad else "pass", "calls": len(calls), "per_definition": dict(per),
            "disagreements": bad[:20]}


def round_trips(seed: int, k: int = 60) -> dict:
    """Generated formulas: decode(code(signs)) = signs, parse(signs) = tree, and every formula is a formula."""
    import random
    rng = random.Random(seed)
    bad = []
    for _ in range(k):
        t = random_tree(rng)
        s = signs_of(t)
        x = code(s)
        if items(x) != s or parse(tuple(s)) != t or not is_fm(x) or length(x) != len(s):
            bad.append(t)
    return {"status": "fail" if bad else "pass", "formulas": k, "failures": bad[:3]}


def literal_agreement(limit: int = 60) -> dict:
    """The direct forms against the paper's own bounded searches, on every small input the searches can finish."""
    bad = []
    checked = 0
    for x in range(limit):
        for n in range(4):
            for name, a, b in (("prFactor", literal.pr_factor(n, x), pr_factor(n, x)),
                               ("item", literal.item(n, x), item(n, x))):
                checked += 1
                if a != b:
                    bad.append((name, n, x, a, b))
        for name, a, b in (("length", literal.length(x), length(x)), ("isPrime", literal.is_prime(x), is_prime(x)),
                           ("divides", literal.divides(3, x), divides(3, x)),
                           ("divides0", literal.divides(0, x), divides(0, x))):
            checked += 1
            if a != b:
                bad.append((name, x, a, b))
    for x in range(40):
        checked += 1
        if literal.is_var(x) != is_var(x):
            bad.append(("isVar", x))
    for n in range(6):
        checked += 1
        if literal.nth_prime(n) != nth_prime(n):
            bad.append(("nthPrime", n))
    return {"status": "fail" if bad else "pass", "checked": checked, "mismatches": bad[:10]}


__all__ = ["DEFINITIONS", "FORALL", "LP", "NOT", "OR", "PA", "RP", "SA", "SUCC", "ZERO", "code", "conj", "disj",
           "el", "eq", "equiv", "exists", "forall", "imp", "is_proof_figure", "items", "literal", "neg", "p_implies_p",
           "parse", "proof_for", "provable", "signs_of", "var", "agree", "cases", "literal_agreement", "round_trips",
           "run_lean", "run_python"]
