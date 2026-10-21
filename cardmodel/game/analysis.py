"""analysis — is the design superior, computably? Exact equilibria, design laws, and the vector that moves it.

* ``matrix``: the value of every (row move, column move) exchange from a state (zero-sum).
* ``solve``: the exact equilibrium of a zero-sum matrix game by the simplex method over fractions, with a
  certificate (every column against the row mix, every row against the column mix) checked exactly.
* ``check``: the design_law cards (dominance, best-response coverage, answers per attack, no universal
  answer, risk vs reward, forced stances exit, equilibrium richness, every answer can be punished).
* ``sensitivity``: perturb every number on every move card; the change that makes the old equilibrium
  most exploitable is "the specific vector that modified the total structure".

Honest limits (L1): one exchange at a time (the matrix game of a state, not the whole duel tree); the
equilibrium is one of possibly many (sensitivity therefore measures exploitability, which does not depend
on which equilibrium the solver returns).
"""
from __future__ import annotations

from fractions import Fraction

from .combat import Combat, State


def matrix(game: Combat, state: State, rows=None, cols=None) -> tuple[list, list, list]:
    rows = rows or game.options(state, "a")
    cols = cols or game.options(state, "b")
    m = []
    for ra in rows:
        line = []
        for cb in cols:
            after, _ = game.resolve(state, ra, cb)
            line.append(game.value(state, after, "a"))
        m.append(line)
    return rows, cols, m


def _frac(x) -> Fraction:
    return x if isinstance(x, Fraction) else Fraction(str(round(float(x), 6)))


def solve(M, exact: bool = True) -> dict:
    """Equilibrium of the zero-sum game M (row player maximises). Returns value, row mix p, column mix q."""
    num = _frac if exact else float
    A = [[num(x) for x in row] for row in M]
    m, n = len(A), len(A[0])
    lo = min(min(r) for r in A)
    shift = (num(1) - lo) if lo <= 0 else num(0)
    P = [[x + shift for x in row] for row in A]
    # maximise sum(y) s.t. P y <= 1, y >= 0  (column player's LP); duals give the row mix
    T = [[*P[i], *[num(1) if k == i else num(0) for k in range(m)], num(1)] for i in range(m)]
    obj = [num(-1)] * n + [num(0)] * m + [num(0)]
    basis = [n + i for i in range(m)]
    eps = 0 if exact else 1e-12
    for _ in range(10000):
        col = next((j for j in range(n + m) if obj[j] < -eps), None)          # Bland: smallest index
        if col is None:
            break
        best, row = None, None
        for i in range(m):
            if T[i][col] > eps:
                r = T[i][-1] / T[i][col]
                if best is None or r < best or (r == best and basis[i] < basis[row]):
                    best, row = r, i
        if row is None:
            raise ValueError("unbounded LP (cannot happen for a shifted positive game)")
        piv = T[row][col]
        T[row] = [x / piv for x in T[row]]
        for i in range(m):
            if i != row and T[i][col] != 0:
                f = T[i][col]
                T[i] = [a - f * b for a, b in zip(T[i], T[row])]
        f = obj[col]
        obj = [a - f * b for a, b in zip(obj, T[row])]
        basis[row] = col
    y = [num(0)] * n
    for i, b in enumerate(basis):
        if b < n:
            y[b] = T[i][-1]
    total = sum(y)
    u = [obj[n + i] for i in range(m)]
    q = [v / total for v in y]
    su = sum(u)
    p = [v / su for v in u]
    value = 1 / total - shift
    cert = certificate(A, p, q, value, exact)
    return {"value": value, "p": p, "q": q, "certificate": cert}


def certificate(A, p, q, v, exact=True) -> dict:
    """The row mix guarantees >= v against every column; the column mix concedes <= v against every row."""
    m, n = len(A), len(A[0])
    col_pay = [sum(p[i] * A[i][j] for i in range(m)) for j in range(n)]
    row_pay = [sum(q[j] * A[i][j] for j in range(n)) for i in range(m)]
    tol = 0 if exact else 1e-9
    ok = min(col_pay) >= v - tol and max(row_pay) <= v + tol and all(x >= 0 for x in p) and all(x >= 0 for x in q)
    return {"ok": bool(ok), "row_guarantee": min(col_pay), "column_concession": max(row_pay)}


def dominated_by_mix(M, i, rows_alive, cols_alive) -> bool:
    """Row i is strictly dominated by some mix of the other live rows: the game D[k][j] = M[k][j] - M[i][j]
    (k != i) has a positive value."""
    others = [k for k in rows_alive if k != i]
    if not others:
        return False
    D = [[M[k][j] - M[i][j] for j in cols_alive] for k in others]
    return solve(D, exact=False)["value"] > 1e-9


def survivors(M) -> tuple[set, set]:
    """Iterated elimination of strictly dominated options (by mixes), rows and columns (zero-sum)."""
    rows, cols = set(range(len(M))), set(range(len(M[0])))
    MT = [[-M[i][j] for i in range(len(M))] for j in range(len(M[0]))]
    changed = True
    while changed:
        changed = False
        for i in sorted(rows):
            if len(rows) > 1 and dominated_by_mix(M, i, sorted(rows), sorted(cols)):
                rows.discard(i)
                changed = True
        for j in sorted(cols):
            if len(cols) > 1 and dominated_by_mix(MT, j, sorted(cols), sorted(rows)):
                cols.discard(j)
                changed = True
    return rows, cols


def representative_states(game: Combat) -> list:
    base = game.start()
    from dataclasses import replace
    return [replace(base, distance=d, advantage=a) for d in (0, 1, 2) for a in (0,)] + \
        [replace(base, advantage=6), replace(base, advantage=-6)]


def kinds(game: Combat, names):
    return [game.moves[n]["kind"] for n in names]


def check(game: Combat, state: State | None = None) -> dict:
    """Evaluate every design_law card on the neutral exchange (or ``state``)."""
    state = state or game.start()
    rows, cols, M = matrix(game, state)
    sol = solve(M)
    n = len(rows)
    out = {}
    k = kinds(game, rows)
    attacks = [j for j, c in enumerate(cols) if game.moves[c]["kind"] in ("attack", "feint", "grab")]
    defensive = [i for i, r in enumerate(rows) if game.moves[r]["kind"] in ("guard", "evade", "catch", "step")]
    for law in sorted(game.ctx.store.cards("design_law"), key=lambda c: c.name):
        chk, thr = law["check"], law.get("threshold")
        if chk == "dominance":
            dom = [rows[i] for i in range(n) if all(all(M[i][c] >= M[j][c] for c in range(len(cols)))
                                                     for j in range(n) if j != i)]
            dominated = sorted({rows[j] for j in range(n) for i in range(n) if i != j and
                                all(M[i][c] >= M[j][c] for c in range(len(cols))) and
                                any(M[i][c] > M[j][c] for c in range(len(cols)))})
            res = {"ok": not dom, "dominant": dom, "weakly_dominated": dominated}
        elif chk == "best_response_coverage":
            alive: dict[str, list] = {}
            for st in representative_states(game):
                r2, _c2, M2 = matrix(game, st)
                keep, _ = survivors(M2)
                for i in keep:
                    alive.setdefault(r2[i], []).append(f"d{st.distance}a{st.advantage:+d}")
            dead = sorted(set(rows) - set(alive))
            cov = 1 - len(dead) / n
            res = {"ok": cov >= thr, "coverage": round(cov, 3), "dead": dead,
                   "alive_in": {k: v for k, v in sorted(alive.items())}}
        elif chk == "answers_per_attack":
            per = {}
            for c in attacks:
                answer_kinds = {k[i] for i in range(n) if -M[i][c] <= 0 and rows[i] != cols[c]}
                per[cols[c]] = sorted(answer_kinds)
            weak = {a: v for a, v in per.items() if len(v) < thr}
            res = {"ok": not weak, "answers": per, "too_few": weak}
        elif chk == "universal_answers":
            uni = [rows[i] for i in defensive if all(M[i][c] >= 0 for c in attacks)]
            res = {"ok": len(uni) <= thr, "universal": uni}
        elif chk == "risk_reward":
            atk = [m for m in game.moves.values() if m["kind"] == "attack"]
            rho = _spearman([m["damage"] for m in atk], [m["recovery"] for m in atk])
            res = {"ok": rho >= thr, "spearman": round(rho, 3)}
        elif chk == "forced_exits":
            bad = []
            for st in game.ctx.store.cards("stance"):
                if st.get("forced") and not (st.get("exits_to") and (st.get("max_exchanges") or 99) <= thr):
                    bad.append(st.name)
            from dataclasses import replace
            s_broken = replace(state, a=replace(state.a, stance="broken"))
            after, _ = game.resolve(s_broken, "endure", game.options(s_broken, "b")[0])
            if after.a.stance == "broken":
                bad.append("broken does not exit")
            res = {"ok": not bad, "stuck": bad}
        elif chk == "equilibrium_support":
            support = [rows[i] for i, x in enumerate(sol["p"]) if x > 0]
            res = {"ok": len(support) >= thr and sol["value"] == 0 and sol["certificate"]["ok"],
                   "support": support, "value": str(sol["value"]), "certificate": sol["certificate"]["ok"]}
        elif chk == "answer_risk":
            safe = [rows[i] for i in defensive if all(M[i][c] >= 0 for c in attacks)]
            res = {"ok": len(safe) < thr, "never_punished": safe}
        else:
            res = {"ok": False, "error": f"unknown check {chk}"}
        out[law.name] = {"statement": law["statement"], **res}
    return {"laws": out, "passed": sum(1 for r in out.values() if r["ok"]), "total": len(out),
            "equilibrium": {"value": str(sol["value"]),
                            "row_mix": {rows[i]: str(x) for i, x in enumerate(sol["p"]) if x > 0},
                            "certificate": sol["certificate"]["ok"]},
            "moves": len(rows)}


def _spearman(xs, ys) -> float:
    def ranks(v):
        order = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2
            i = j + 1
        return r
    rx, ry = ranks(xs), ranks(ys)
    n = len(xs)
    mx, my = sum(rx) / n, sum(ry) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sx = sum((a - mx) ** 2 for a in rx) ** 0.5
    sy = sum((b - my) ** 2 for b in ry) ** 0.5
    return cov / (sx * sy) if sx and sy else 0.0


PARAMS = {"attack": ("startup", "recovery", "damage", "posture", "momentum", "poise"),
          "feint": ("startup",), "guard": ("perfect", "good", "recovery"), "evade": ("recovery",),
          "catch": ("recovery",), "grab": ("startup", "damage", "posture"), "step": ("recovery",)}


def sensitivity(game: Combat, state: State | None = None, top: int = 12) -> dict:
    """Which single number on which card most changes the game: the exploitability of the old equilibrium."""
    state = state or game.start()
    rows, cols, M0 = matrix(game, state)
    base = solve(M0, exact=False)
    p0 = base["p"]
    results = []
    original = {n: dict(m) for n, m in game.moves.items()}
    for name, mv in original.items():
        for prm in PARAMS.get(mv["kind"], ()):
            v = mv.get(prm)
            if not isinstance(v, int):
                continue
            step = max(1, round(abs(v) * 0.15))
            for delta in (-step, step):
                nv = v + delta
                if nv < (1 if prm in ("startup",) else 0):
                    continue
                game.moves[name] = {**mv, prm: nv}
                try:
                    _, _, M1 = matrix(game, state, rows, cols)
                finally:
                    game.moves[name] = original[name]
                col_pay = [sum(p0[i] * M1[i][j] for i in range(len(rows))) for j in range(len(cols))]
                worst = min(range(len(cols)), key=lambda j: col_pay[j])
                results.append({"card": f"move/{name}", "param": prm, "from": v, "to": nv,
                                "exploitability": round(-col_pay[worst], 3), "exploited_by": cols[worst]})
    results.sort(key=lambda r: -r["exploitability"])
    return {"base_value": round(base["value"], 6), "perturbations": len(results), "top": results[:top]}


TUNABLE = {"attack": ("startup", "recovery", "damage", "posture", "momentum", "poise", "lunge"),
           "feint": ("startup", "stamina"), "guard": ("perfect", "good", "recovery", "stamina"),
           "evade": ("recovery", "stamina", "bank_div"), "catch": ("recovery",), "grab": ("startup", "recovery", "damage",
                                                                                      "posture", "lunge"),
           "step": ("startup", "recovery", "stamina")}
BOUNDS = {"lunge": (0, 1), "bank_div": (0, 4), "poise": (0, 20), "perfect": (1, 8), "good": (3, 16), "startup": (1, 40)}


def score(game: Combat) -> tuple:
    """Lower is better: (failed design laws, dead options, -equilibrium support)."""
    r = check(game)
    dead = len(r["laws"].get("GL2_no_dead_options", {}).get("dead", []))
    return (r["total"] - r["passed"], dead, -len(r["equilibrium"]["row_mix"])), r


def balance(game: Combat, budget: int = 120, seed: int = 0, log=None) -> dict:
    """Seeded local search over move-card numbers until every design law holds (or the budget ends).
    Returns the accepted changes with the score after each one: tuning as evidence, not by hand."""
    import random
    rng = random.Random(seed)
    best, rep = score(game)
    start = best
    accepted = []
    tried = 0
    while tried < budget and best[:2] != (0, 0):
        dead = rep["laws"].get("GL2_no_dead_options", {}).get("dead", [])
        names = list(dead) if dead and rng.random() < 0.7 else list(game.moves)
        name = rng.choice(names)
        mv = game.moves[name]
        prms = [p for p in TUNABLE.get(mv["kind"], ()) if isinstance(mv.get(p, 0), int)]
        if not prms:
            tried += 1
            continue
        prm = rng.choice(prms)
        v = mv.get(prm, 0)
        lo, hi = BOUNDS.get(prm, (0, max(4, v * 2)))
        step = max(1, round(abs(v) * 0.15)) if prm not in ("lunge", "bank_div") else 1
        nv = min(hi, max(lo, v + rng.choice((-step, step))))
        tried += 1
        if nv == v:
            continue
        game.moves[name] = {**mv, prm: nv}
        cand, crep = score(game)
        if cand < best:
            accepted.append({"card": f"move/{name}", "param": prm, "from": v, "to": nv, "score": list(cand)})
            best, rep = cand, crep
            if log:
                log(f"  {name}.{prm}: {v} -> {nv}   score {cand}")
        else:
            game.moves[name] = mv
    return {"start": list(start), "end": list(best), "tried": tried, "accepted": accepted, "report": rep}


__all__ = ["balance", "certificate", "check", "matrix", "score", "sensitivity", "solve"]
