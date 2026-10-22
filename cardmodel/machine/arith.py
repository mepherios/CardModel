"""arith — the instruction terms as polynomial constraints over a prime field (Gödel method W-12: Cap-11, Ph-11).

  circuit    a term (machine/symbolic.py) compiled to gates over F_p, p = 2^64 - 2^32 + 1 (the Goldilocks prime):
             every value a two's-complement word of W bits, every bit a wire, every gate one constraint of degree
             at most 2 (AND z = xy, XOR z = x + y - 2xy, OR z = x + y - xy, NOT z = 1 - x, MUX z = b + t(a - b));
             on {0, 1} each polynomial is its Boolean gate. Words: ripple-carry addition, two's-complement
             subtraction, shifts by constants (arithmetic to the right, as the evaluator's), comparisons by the sign
             of a difference, IF_EXPR as a MUX on the condition's truth (the OR of its bits).
  checks     ``exhaustive``: the constraints, evaluated on every input of the term's variables at once (bit-sliced),
             against the term evaluated by a compiled copy of the evaluator, where the inputs have at most
             EXHAUSTIVE_BITS bits. ``smt``: z3 decides that no input makes the circuit differ from the term at word
             level (unsat). ``trace``: a Schwartz-Zippel identity over F_p: the constraints over all N rows of an
             instruction's inputs hold exactly when the composition polynomial is divisible by X^N - 1, checked at
             one random point (soundness error at most deg/p). ``mod2w``: the same test over Z/2^w is unsound, as
             2^(w-1)·x vanishes on half of all inputs.

Honest limits (L1): W = 40 bits, enough for every value these terms reach (inputs of 8 and 16 bits, sums and shifts
by 8); a term whose values left that window would be read modulo 2^40. Shift amounts must be constants. The trace
check here evaluates the polynomials itself, so it shows the identity and its soundness bound, not a succinct proof
(no low-degree test, no commitments).
"""
from __future__ import annotations

import json
import random
import shutil
import subprocess

P = 2 ** 64 - 2 ** 32 + 1
W = 40
EXHAUSTIVE_BITS = 16
WIDTHS = {"PC": 16, "SP": 16, "halt_bug": 1, "ime": 1, "ime_delay": 1}
GATE_POLY = {
    "AND": lambda x, y: x * y, "XOR": lambda x, y: x + y - 2 * x * y, "OR": lambda x, y: x + y - x * y,
    "NOT": lambda x: 1 - x, "MUX": lambda t, a, b: b + t * (a - b),
}


class Unsupported(ValueError):
    pass


def width(name: str) -> int:
    return WIDTHS.get(name, 8)


class Circuit:
    """Wires 0 and 1 are the constants; inputs, then gates (op, inputs), shared when equal."""

    def __init__(self):
        self.gates: list[tuple] = []
        self.memo: dict = {}
        self.inputs: dict[str, list[int]] = {}
        self.n = 2

    def _new(self, op, *ins) -> int:
        key = (op, *ins)
        if key in self.memo:
            return self.memo[key]
        w = self.n
        self.n += 1
        self.gates.append((w, op, ins))
        self.memo[key] = w
        return w

    def AND(self, x, y):
        if x == 0 or y == 0:
            return 0
        if x == 1:
            return y
        if y == 1 or x == y:
            return x
        return self._new("AND", *sorted((x, y)))

    def XOR(self, x, y):
        if x == 0:
            return y
        if y == 0:
            return x
        if x == y:
            return 0
        if x == 1:
            return self.NOT(y)
        if y == 1:
            return self.NOT(x)
        return self._new("XOR", *sorted((x, y)))

    def OR(self, x, y):
        if x == 1 or y == 1:
            return 1
        if x == 0:
            return y
        if y == 0 or x == y:
            return x
        return self._new("OR", *sorted((x, y)))

    def NOT(self, x):
        if x in (0, 1):
            return 1 - x
        return self._new("NOT", x)

    def MUX(self, t, a, b):
        if t == 1 or a == b:
            return a
        if t == 0:
            return b
        return self._new("MUX", t, a, b)

    # -- words ----------------------------------------------------------------------------------------------------
    def input(self, name: str) -> list[int]:
        if name not in self.inputs:
            bits = []
            for _ in range(width(name)):
                bits.append(self.n)
                self.n += 1
            self.inputs[name] = bits
        return self.inputs[name] + [0] * (W - width(name))

    @staticmethod
    def const(c: int) -> list[int]:
        c %= 1 << W
        return [(c >> i) & 1 for i in range(W)]

    def add(self, a, b, carry=0):
        out = []
        for x, y in zip(a, b):
            s = self.XOR(x, y)
            out.append(self.XOR(s, carry))
            carry = self.OR(self.AND(x, y), self.AND(carry, s))
        return out

    def sub(self, a, b):
        return self.add(a, [self.NOT(y) for y in b], 1)

    def truth(self, a) -> int:
        t = 0
        for x in a:
            t = self.OR(t, x)
        return t

    def lt(self, a, b) -> int:
        return self.sub(a, b)[W - 1]                     # the sign of a - b; no overflow inside the window

    def eq(self, a, b) -> int:
        t = 1
        for x, y in zip(a, b):
            t = self.AND(t, self.NOT(self.XOR(x, y)))
        return t

    def word(self, t: int) -> list[int]:
        return [t] + [0] * (W - 1)

    def compile(self, term, memo: dict | None = None) -> list[int]:
        memo = {} if memo is None else memo
        key = json.dumps(term)
        if key in memo:
            return memo[key]
        h = term[0]
        if h == "var":
            out = self.input(term[1])
        elif h in ("int", "bool"):
            out = self.const(int(term[1]))
        else:
            args = term[1:]
            if h in ("SHIFT_LEFT", "SHIFT_RIGHT"):
                if args[1][0] != "int":
                    raise Unsupported("a shift by a variable amount")
                a, k = self.compile(args[0], memo), int(args[1][1])
                out = ([0] * k + a)[:W] if h == "SHIFT_LEFT" else (a[k:] + [a[W - 1]] * k)[:W]
            elif h == "IF_EXPR":
                t = self.truth(self.compile(args[0], memo))
                a, b = self.compile(args[1], memo), self.compile(args[2], memo)
                out = [self.MUX(t, x, y) for x, y in zip(a, b)]
            else:
                ws = [self.compile(x, memo) for x in args]
                if h == "ADD":
                    out = self.add(*ws)
                elif h == "SUB":
                    out = self.sub(*ws)
                elif h in ("BIT_AND", "BIT_OR", "BIT_XOR"):
                    f = {"BIT_AND": self.AND, "BIT_OR": self.OR, "BIT_XOR": self.XOR}[h]
                    out = [f(x, y) for x, y in zip(*ws)]
                elif h == "CMP_EQ":
                    out = self.word(self.eq(*ws))
                elif h == "CMP_NE":
                    out = self.word(self.NOT(self.eq(*ws)))
                elif h == "CMP_LT":
                    out = self.word(self.lt(ws[0], ws[1]))
                elif h == "CMP_GT":
                    out = self.word(self.lt(ws[1], ws[0]))
                elif h == "CMP_GE":
                    out = self.word(self.NOT(self.lt(ws[0], ws[1])))
                elif h == "CMP_LE":
                    out = self.word(self.NOT(self.lt(ws[1], ws[0])))
                elif h == "AND":
                    out = self.word(self.AND(self.truth(ws[0]), self.truth(ws[1])))
                elif h == "OR":
                    out = self.word(self.OR(self.truth(ws[0]), self.truth(ws[1])))
                elif h == "NOT":
                    out = self.word(self.NOT(self.truth(ws[0])))
                else:
                    raise Unsupported(f"op {h}")
        memo[key] = out
        return out

    # -- evaluation --------------------------------------------------------------------------------------------------
    def eval_field(self, values: dict[str, int], p: int = P) -> list[int]:
        """Every wire's value over F_p for one input (bits 0/1 for the inputs)."""
        w = [0] * self.n
        w[1] = 1
        for name, bits in self.inputs.items():
            v = values[name]
            for i, b in enumerate(bits):
                w[b] = (v >> i) & 1
        for out, op, ins in self.gates:
            w[out] = GATE_POLY[op](*(w[i] for i in ins)) % p
        return w

    def residuals(self, w: list[int], p: int = P) -> list[int]:
        """The constraints' values on a wire assignment: all 0 exactly when every gate holds."""
        return [(w[out] - GATE_POLY[op](*(w[i] for i in ins))) % p for out, op, ins in self.gates]

    def eval_sliced(self, names: list[str]) -> tuple[list[int], int]:
        """Every wire's bit for every combination of the named inputs at once: bit i of a wire's integer is its value
        on combination i (the inputs' bits taken in order). Returns (wires, combinations)."""
        nbits = sum(width(n) for n in names)
        N = 1 << nbits
        full = (1 << N) - 1
        w = [0] * self.n
        w[1] = full
        j = 0
        for name in names:
            for b in self.inputs.get(name, [None] * width(name)):
                block = ((1 << (1 << j)) - 1) << (1 << j)            # 2^j zeros then 2^j ones
                period = 1 << (j + 1)
                pattern = block
                while period < N:
                    pattern |= pattern << period
                    period <<= 1
                if b is not None:
                    w[b] = pattern & full
                j += 1
        for out, op, ins in self.gates:
            v = [w[i] for i in ins]
            if op == "AND":
                w[out] = v[0] & v[1]
            elif op == "XOR":
                w[out] = v[0] ^ v[1]
            elif op == "OR":
                w[out] = v[0] | v[1]
            elif op == "NOT":
                w[out] = full ^ v[0]
            else:
                w[out] = (v[0] & v[1]) | ((full ^ v[0]) & v[2])
        return w, N


def gate_lemma() -> bool:
    """Each gate polynomial equals its Boolean gate on {0, 1} (the bridge from field to bits)."""
    ref = {"AND": lambda x, y: x & y, "XOR": lambda x, y: x ^ y, "OR": lambda x, y: x | y, "NOT": lambda x: 1 - x,
           "MUX": lambda t, a, b: a if t else b}
    for op, f in GATE_POLY.items():
        k = 3 if op == "MUX" else 1 if op == "NOT" else 2
        for i in range(1 << k):
            xs = [(i >> j) & 1 for j in range(k)]
            if f(*xs) % P != ref[op](*xs):
                return False
    return True


def variables(term, out=None) -> list[str]:
    out = [] if out is None else out
    if isinstance(term, list) and term:
        if term[0] == "var":
            if term[1] not in out:
                out.append(term[1])
        elif term[0] not in ("int", "bool"):
            for a in term[1:]:
                variables(a, out)
    return out


def py_source(term) -> str:
    """The evaluator's semantics (engines/exprs.py) as one Python expression, to run fast on many inputs."""
    h = term[0]
    if h == "var":
        return term[1]
    if h in ("int", "bool"):
        return str(int(term[1]))
    a = [py_source(x) for x in term[1:]]
    binop = {"ADD": "+", "SUB": "-", "BIT_AND": "&", "BIT_OR": "|", "BIT_XOR": "^", "SHIFT_LEFT": "<<",
             "SHIFT_RIGHT": ">>", "CMP_EQ": "==", "CMP_NE": "!=", "CMP_LT": "<", "CMP_GT": ">", "CMP_GE": ">=",
             "CMP_LE": "<="}
    if h in binop:
        return f"({a[0]} {binop[h]} {a[1]})"
    if h == "IF_EXPR":
        return f"({a[1]} if {a[0]} else {a[2]})"
    if h == "AND":
        return f"(bool({a[0]}) and bool({a[1]}))"
    if h == "OR":
        return f"(bool({a[0]}) or bool({a[1]}))"
    if h == "NOT":
        return f"(not {a[0]})"
    raise Unsupported(f"op {h}")


def exhaustive(term) -> dict:
    """Every input of the term's variables: the circuit's word against the term's value, bit for bit."""
    names = variables(term)
    nbits = sum(width(n) for n in names)
    if nbits > EXHAUSTIVE_BITS:
        return {"status": "too_wide", "bits": nbits}
    c = Circuit()
    out = c.compile(term)
    for n in names:
        c.input(n)
    w, N = c.eval_sliced(names)
    fn = eval(compile(f"lambda {', '.join(names) or '_'}: {py_source(term)}", "<term>", "eval"))  # noqa: S307
    shifts, pos = [], 0
    for n in names:
        shifts.append((pos, (1 << width(n)) - 1))
        pos += width(n)
    mismatches = 0
    first = None
    for i in range(N):
        args = [(i >> s) & m for s, m in shifts]
        v = int(fn(*args)) if names else int(fn(0))
        if not -(1 << (W - 2)) <= v < 1 << (W - 2):
            return {"status": "out_of_window", "at": args}
        v %= 1 << W
        for bit in range(W):
            if ((w[out[bit]] >> i) & 1) != ((v >> bit) & 1):
                mismatches += 1
                first = first or {"inputs": dict(zip(names, args)), "bit": bit}
                break
    return {"status": "fail" if mismatches else "pass", "inputs": N, "bits": nbits, "gates": len(c.gates),
            "mismatches": mismatches, "first": first}


# -- SMT -------------------------------------------------------------------------------------------------------------
def z3_exe() -> str | None:
    return shutil.which("z3")


def _smt_term(term, names) -> str:
    h = term[0]
    if h == "var":
        k = width(term[1])
        return f"((_ zero_extend {W - k}) {term[1]})"
    if h in ("int", "bool"):
        return f"(_ bv{int(term[1]) % (1 << W)} {W})"
    a = [_smt_term(x, names) for x in term[1:]]
    one, zero = f"(_ bv1 {W})", f"(_ bv0 {W})"

    def truth(x):
        return f"(not (= {x} {zero}))"
    table = {"ADD": "bvadd", "SUB": "bvsub", "BIT_AND": "bvand", "BIT_OR": "bvor", "BIT_XOR": "bvxor",
             "SHIFT_LEFT": "bvshl", "SHIFT_RIGHT": "bvashr"}
    if h in table:
        return f"({table[h]} {a[0]} {a[1]})"
    cmp = {"CMP_EQ": "=", "CMP_LT": "bvslt", "CMP_GT": "bvsgt", "CMP_GE": "bvsge", "CMP_LE": "bvsle"}
    if h in cmp:
        return f"(ite ({cmp[h]} {a[0]} {a[1]}) {one} {zero})"
    if h == "CMP_NE":
        return f"(ite (= {a[0]} {a[1]}) {zero} {one})"
    if h == "IF_EXPR":
        return f"(ite {truth(a[0])} {a[1]} {a[2]})"
    if h == "AND":
        return f"(ite (and {truth(a[0])} {truth(a[1])}) {one} {zero})"
    if h == "OR":
        return f"(ite (or {truth(a[0])} {truth(a[1])}) {one} {zero})"
    if h == "NOT":
        return f"(ite {truth(a[0])} {zero} {one})"
    raise Unsupported(f"op {h}")


def smt_query(term) -> str:
    """SMT-LIB2: is there an input where the circuit's word differs from the term's? (unsat: they agree on all.)"""
    names = variables(term)
    c = Circuit()
    out = c.compile(term)
    for n in names:
        c.input(n)
    lines = ["(push 1)"]
    lines += [f"(declare-const {n} (_ BitVec {width(n)}))" for n in names]

    def wire(i):
        if i in (0, 1):
            return "true" if i else "false"
        return f"w{i}"
    for n, bits in c.inputs.items():
        for j, b in enumerate(bits):
            lines.append(f"(define-fun w{b} () Bool (= ((_ extract {j} {j}) {n}) #b1))")
    smt_op = {"AND": "and", "OR": "or", "XOR": "xor"}
    for o, op, ins in c.gates:
        if op == "NOT":
            body = f"(not {wire(ins[0])})"
        elif op == "MUX":
            body = f"(ite {wire(ins[0])} {wire(ins[1])} {wire(ins[2])})"
        else:
            body = f"({smt_op[op]} {wire(ins[0])} {wire(ins[1])})"
        lines.append(f"(define-fun w{o} () Bool {body})")
    bits = " ".join(f"(ite {wire(b)} #b1 #b0)" for b in reversed(out))
    lines.append(f"(assert (not (= (concat {bits}) {_smt_term(term, names)})))")
    lines += ["(check-sat)", "(pop 1)"]
    return "\n".join(lines)


def smt(terms: list, timeout: float = 900) -> list[str]:
    """z3's verdict per term (unsat: the circuit equals the term on every input), in one z3 process."""
    exe = z3_exe()
    if exe is None:
        return ["skipped"] * len(terms)
    script = "\n".join(smt_query(t) for t in terms)
    p = subprocess.run([exe, "-in", "-smt2"], input=script, capture_output=True, text=True, timeout=timeout)
    out = [x.strip() for x in p.stdout.splitlines() if x.strip() in ("sat", "unsat", "unknown")]
    return out if len(out) == len(terms) else out + ["error"] * (len(terms) - len(out))


# -- a Schwartz-Zippel identity over F_p ----------------------------------------------------------------------------------
G = 7                                                       # a generator of the multiplicative group of F_p


def _root(n: int) -> int:
    return pow(G, (P - 1) // n, P)


def ntt(a: list[int], invert: bool = False) -> list[int]:
    n = len(a)
    a = list(a)
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j |= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        w = _root(length)
        if invert:
            w = pow(w, P - 2, P)
        for i in range(0, n, length):
            wk = 1
            half = length // 2
            for k in range(half):
                u, v = a[i + k], a[i + k + half] * wk % P
                a[i + k] = (u + v) % P
                a[i + k + half] = (u - v) % P
                wk = wk * w % P
        length <<= 1
    if invert:
        ninv = pow(n, P - 2, P)
        a = [x * ninv % P for x in a]
    return a


def _horner(coeffs: list[int], x: int) -> int:
    v = 0
    for c in reversed(coeffs):
        v = (v * x + c) % P
    return v


def trace(term, rng: random.Random, tamper: bool = False) -> dict:
    """All N rows of the term's inputs as a trace over F_p: each wire a column, interpolated on the N-th roots of
    unity; the random combination of the gate constraints, C(X), vanishes on all N rows exactly when X^N - 1 divides
    it. The prover divides; the verifier checks C(ζ) = (ζ^N - 1)·Q(ζ) at one random ζ (error ≤ 2N/p)."""
    names = variables(term)
    c = Circuit()
    c.compile(term)
    for n in names:
        c.input(n)
    w, N = c.eval_sliced(names)
    cols = [[(w[i] >> r) & 1 for r in range(N)] for i in range(c.n)]
    if tamper:
        if not c.gates:
            raise ValueError("a term without gates has nothing to tamper with")
        g = c.gates[len(c.gates) // 2][0]
        cols[g][rng.randrange(N)] ^= 1                  # one row's gate output flipped
    coef = [ntt(col, invert=True) for col in cols]       # each column as a polynomial of degree < N
    big = 4 * N
    ev = [ntt(cf + [0] * (big - N)) for cf in coef]      # each column on the 4N-th roots of unity
    alphas = [rng.randrange(1, P) for _ in c.gates]
    comp = [0] * big
    for (out, op, ins), al in zip(c.gates, alphas):
        f = GATE_POLY[op]
        for k in range(big):
            comp[k] = (comp[k] + al * (ev[out][k] - f(*(ev[i][k] for i in ins)))) % P
    ccoef = ntt(comp, invert=True)                       # C(X), degree < 4N (at most 2N - 2 for these gates)
    q = [0] * big                                        # divide by X^N - 1: q_k = c_{k+N} + q_{k+N}
    rem = list(ccoef)
    for k in range(big - 1, N - 1, -1):
        q[k - N] = rem[k]
        rem[k - N] = (rem[k - N] + rem[k]) % P
        rem[k] = 0
    divisible = not any(rem[:N])
    zeta = rng.randrange(N + 1, P)
    lhs = _horner(ccoef, zeta)
    rhs = (pow(zeta, N, P) - 1) * _horner(q, zeta) % P
    return {"rows": N, "gates": len(c.gates), "divisible": divisible, "accepted": lhs == rhs,
            "error_bound": f"2N/p = 2^{(2 * N).bit_length() - 1}/p ≈ 2^-{64 - (2 * N).bit_length() + 1}"}


def mod2w_unsound(w: int, trials: int, rng: random.Random) -> dict:
    """The random-point test over Z/2^w accepts the nonzero polynomial 2^(w-1)·x for every even x: half the time."""
    c = 1 << (w - 1)
    ring = sum(1 for _ in range(trials) if (c * rng.randrange(1 << w)) % (1 << w) == 0)
    field = sum(1 for _ in range(trials) if (c * rng.randrange(P)) % P == 0)
    return {"w": w, "trials": trials, "accepted_mod_2w": ring, "accepted_mod_p": field}


def outputs(ctx) -> list[tuple[str, str, list]]:
    """(instruction, output, term) for every register update, bus-effect argument and guard of the LR35902 terms."""
    out = []
    for d in sorted(ctx.store.cards("definition"), key=lambda c: c.name):
        if not d.name.startswith("isa__"):
            continue
        t = (d.get("math") or {}).get("term") or {}
        for reg, term in sorted((t.get("state") or {}).items()):
            out.append((d.name[5:], reg, term))
        for i, e in enumerate(t.get("effects") or []):
            for j, a in enumerate(e.get("args") or []):
                out.append((d.name[5:], f"{e['op']}#{i}.arg{j}", a))
            if e.get("guard") is not None:
                out.append((d.name[5:], f"{e['op']}#{i}.guard", e["guard"]))
    return out


def run(ctx, limit: int | None = None) -> dict:
    """Every output: the circuit's size, z3's verdict, and exhaustive agreement where the inputs allow."""
    import time
    outs = outputs(ctx)[:limit]
    t0 = time.perf_counter()
    verdicts = smt([t for _, _, t in outs])
    t_smt = time.perf_counter() - t0
    rows, t_ex = [], 0.0
    for (ins, name, term), v in zip(outs, verdicts):
        t1 = time.perf_counter()
        ex = exhaustive(term)
        t_ex += time.perf_counter() - t1
        rows.append({"instruction": ins, "output": name, "smt": v, "exhaustive": ex["status"],
                     "bits": ex.get("bits"), "gates": ex.get("gates"), "inputs": ex.get("inputs")})
    from collections import Counter
    return {"outputs": len(rows), "smt": dict(Counter(r["smt"] for r in rows)),
            "exhaustive": dict(Counter(r["exhaustive"] for r in rows)),
            "inputs_checked": sum(r["inputs"] or 0 for r in rows if r["exhaustive"] == "pass"),
            "gates": sum(r["gates"] or 0 for r in rows), "seconds": {"smt": round(t_smt, 1), "exhaustive": round(t_ex, 1)},
            "failures": [r for r in rows if r["smt"] not in ("unsat", "skipped") or r["exhaustive"] == "fail"][:10]}


__all__ = ["Circuit", "EXHAUSTIVE_BITS", "P", "Unsupported", "W", "exhaustive", "gate_lemma", "mod2w_unsound",
           "ntt", "outputs", "py_source", "run", "smt", "smt_query", "trace", "variables", "width", "z3_exe"]
