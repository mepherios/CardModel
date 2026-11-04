"""Transformer math in plain Python: the kernels of one attention block, written with lists and loops.

Matrices are row-major lists with their dimensions passed beside them (a is n x k: a[i * k + p]). Every function
lifts to the card IR and is emitted, compiled and run in every codegen language (`cardmodel translate`).
Sums run left to right in every target, so the floating-point results agree to rounding of exp/sqrt/tanh only.
"""
import math


def dot(a: list[float], b: list[float]) -> float:
    s = 0.0
    for i in range(len(a)):
        s += a[i] * b[i]
    return s


def matvec(w: list[float], x: list[float], rows: int, cols: int) -> list[float]:
    y = [0.0] * rows
    for i in range(rows):
        s = 0.0
        for j in range(cols):
            s += w[i * cols + j] * x[j]
        y[i] = s
    return y


def matmul(a: list[float], b: list[float], n: int, k: int, m: int) -> list[float]:
    c = [0.0] * (n * m)
    for i in range(n):
        for j in range(m):
            s = 0.0
            for p in range(k):
                s += a[i * k + p] * b[p * m + j]
            c[i * m + j] = s
    return c


def transpose(a: list[float], n: int, m: int) -> list[float]:
    t = [0.0] * (n * m)
    for i in range(n):
        for j in range(m):
            t[j * n + i] = a[i * m + j]
    return t


def softmax(x: list[float]) -> list[float]:
    n = len(x)
    out = [0.0] * n
    if n == 0:
        return out
    hi = x[0]
    for v in x:
        if v > hi:
            hi = v
    total = 0.0
    for i in range(n):
        out[i] = math.exp(x[i] - hi)
        total += out[i]
    for i in range(n):
        out[i] = out[i] / total
    return out


def layernorm(x: list[float], gamma: list[float], beta: list[float]) -> list[float]:
    n = len(x)
    out = [0.0] * n
    if n == 0:
        return out
    mean = 0.0
    for v in x:
        mean += v
    mean = mean / n
    var = 0.0
    for v in x:
        var += (v - mean) * (v - mean)
    var = var / n
    inv = 1.0 / math.sqrt(var + 1e-5)
    for i in range(n):
        out[i] = (x[i] - mean) * inv * gamma[i] + beta[i]
    return out


def gelu(x: list[float]) -> list[float]:
    c = math.sqrt(2.0 / math.pi)
    return [0.5 * x[i] * (1.0 + math.tanh(c * (x[i] + 0.044715 * x[i] * x[i] * x[i]))) for i in range(len(x))]


def relu(x: list[float]) -> list[float]:
    return [max(x[i], 0.0) for i in range(len(x))]


def add(a: list[float], b: list[float]) -> list[float]:
    return [a[i] + b[i] for i in range(len(a))]


def attention(q: list[float], k: list[float], v: list[float], n: int, d: int) -> list[float]:
    """softmax(q k^T / sqrt(d)) v for one head: q, k, v are n x d."""
    scale = 1.0 / math.sqrt(d)
    out = [0.0] * (n * d)
    row = [0.0] * n
    for i in range(n):
        hi = -1e300
        for j in range(n):
            s = 0.0
            for p in range(d):
                s += q[i * d + p] * k[j * d + p]
            row[j] = s * scale
            if row[j] > hi:
                hi = row[j]
        total = 0.0
        for j in range(n):
            row[j] = math.exp(row[j] - hi)
            total += row[j]
        for p in range(d):
            acc = 0.0
            for j in range(n):
                acc += row[j] / total * v[j * d + p]
            out[i * d + p] = acc
    return out


def feed_forward(x: list[float], w1: list[float], w2: list[float], d: int, h: int) -> list[float]:
    """The MLP of a block: w2 · gelu(w1 · x), with w1 h x d and w2 d x h."""
    return matvec(w2, gelu(matvec(w1, x, h, d)), d, h)


def block(x: list[float], wq: list[float], wk: list[float], wv: list[float], n: int, d: int) -> list[float]:
    """One pre-norm attention sub-block on an n x d sequence: x + attention(xWq, xWk, xWv)."""
    ones = [1.0] * d
    zeros = [0.0] * d
    normed = [0.0] * (n * d)
    for i in range(n):
        r = [x[i * d + p] for p in range(d)]
        nr = layernorm(r, ones, zeros)
        for p in range(d):
            normed[i * d + p] = nr[p]
    q = matmul(normed, wq, n, d, d)
    k = matmul(normed, wk, n, d, d)
    v = matmul(normed, wv, n, d, d)
    return add(x, attention(q, k, v, n, d))


def argmax(x: list[float]) -> int:
    best = 0
    for i in range(len(x)):
        if x[i] > x[best]:
            best = i
    return best
