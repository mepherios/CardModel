"""tree — the duel several exchanges deep: backward induction over abstract states (game/DESIGN.md).

An exchange (``Combat.resolve``) leaves the fighters at a distance, with a frame advantage, a posture and a
stance each. The tree abstracts that to a finite state -- the distance band, the advantage bucket (nearest of
the centres) and a status per fighter (open with low posture, open with high posture, recoil, broken) -- and
solves the zero-sum duel by backward induction. At depth 1 an exchange is worth what ``Combat.value`` says
(what it changed plus where it left the fighters), so the depth-1 tree at a neutral state is the exchange
matrix ``analysis.matrix`` solves. At depth k it is worth what it changed plus the discounted depth-(k-1)
value of the abstract state it leads to. Every state's matrix game is solved by the simplex
(``analysis.solve``) and its certificate checked, so each policy is an equilibrium of its abstract game.

Strings enter as a sub-game: after an attack connects, the attacker picks among its links (chain cards; each
started early by the recovery it cancels, prorated) and its ordinary options (started after the recovery),
against the defender's options, who is free after the kernel's hit-stun (or, after a block, the guard's
recovery). Its continuation is the tree's value.

Honest limits (L1): the abstraction drops hit points, stamina, the momentum bank and flow (the representative
fighter of a status has full stamina, no bank, no residual momentum); the advantage is bucketed; the tree is
depth-limited and discounted, not solved to the end of the duel; the simplex runs in floating point here
(certificates checked to 1e-9; where rounding spoils one, the exact simplex over fractions solves that state).
"""
from __future__ import annotations

import copy

from . import analysis as A
from .combat import Combat, Fighter, State

STATUSES = ("low", "high", "recoil", "broken")
CENTRES = (-14, -7, 0, 7, 14)


def cuts(centres) -> list[int]:
    """Integer cut points between neighbouring centres: an advantage a falls in bucket #(cuts below a)."""
    return [(a + b) // 2 for a, b in zip(centres, centres[1:])]


def bucket(adv: int, cut: list[int]) -> int:
    return sum(1 for c in cut if c < adv)


def status(game: Combat, f: Fighter) -> int:
    if f.stance == "broken":
        return 3
    if f.stance == "recoil":
        return 2
    return 1 if 2 * f.posture >= game.fighters[f.name]["posture_max"] else 0


def fighter_at(game: Combat, name: str, st: int) -> Fighter:
    """The representative fighter of a status: low posture 1/5, high 3/4, recoil 2/5, broken full."""
    fc = game.fighters[name]
    pm = fc["posture_max"]
    posture, stance = ((pm // 5, "neutral"), (pm * 3 // 4, "neutral"), (pm * 2 // 5, "recoil"), (pm, "broken"))[st]
    return Fighter(name, fc["hp"], posture=posture, stamina=fc["stamina_max"], stance=stance)


def _solve(M) -> dict:
    """The floating-point simplex, and the exact one (fractions) when rounding spoils its certificate."""
    try:
        sol = A.solve(M, exact=False)
        if sol["certificate"]["ok"]:
            return sol
    except ValueError:
        pass
    sol = A.solve(M)
    if not sol["certificate"]["ok"]:
        raise ArithmeticError("no certificate")
    return {**sol, "value": float(sol["value"])}


def _mix(p) -> list[float]:
    """A floating-point mix with the simplex's rounding dust (|x| < 1e-12) cleared, renormalised."""
    q = [float(x) if float(x) > 1e-12 else 0.0 for x in p]
    t = sum(q)
    return [x / t for x in q]


class Tree:
    """The duel tree of fighter ``a`` (rows, maximising) against ``b``."""

    def __init__(self, ctx, a: str, b: str, centres=CENTRES):
        self.g = Combat(ctx, a, b)
        self.centres = list(centres)
        if self.centres != sorted(-c for c in self.centres):
            raise ValueError("advantage centres must be symmetric around 0")
        self.cut = cuts(self.centres)
        self.na = len(self.centres)
        self.n = 3 * self.na * 16
        self.V: list[float] = []
        self.P: list[list[float]] = []
        self.Q: list[list[float]] = []

    # -- states ------------------------------------------------------------------------------------------------
    def index(self, d: int, ai: int, sa: int, sb: int) -> int:
        return ((d * self.na + ai) * 4 + sa) * 4 + sb

    def parts(self, k: int) -> tuple[int, int, int, int]:
        return k // (16 * self.na), k // 16 % self.na, k // 4 % 4, k % 4

    def state(self, k: int) -> State:
        d, ai, sa, sb = self.parts(k)
        g = self.g
        return State(fighter_at(g, g.names[0], sa), fighter_at(g, g.names[1], sb), distance=d,
                     advantage=self.centres[ai])

    def abstract(self, s: State) -> int:
        return self.index(s.distance, bucket(s.advantage, self.cut), status(self.g, s.a), status(self.g, s.b))

    def mirror(self, k: int) -> int:
        """The same state seen from the other fighter: advantage negated, statuses swapped."""
        d, ai, sa, sb = self.parts(k)
        return self.index(d, self.na - 1 - ai, sb, sa)

    # -- backward induction --------------------------------------------------------------------------------------
    def expand(self) -> None:
        """Every exchange from every abstract state, once: what it changed, its full value, where it leads."""
        g = self.g
        self.rows, self.cols, self.change, self.leaf, self.next = [], [], [], [], []
        for k in range(self.n):
            s = self.state(k)
            rows, cols = g.options(s, "a"), g.options(s, "b")
            ch, lf, nx = [], [], []
            for ra in rows:
                c_, l_, n_ = [], [], []
                for cb in cols:
                    after, _ = g.resolve(s, ra, cb)
                    v = g.value(s, after, "a")
                    c_.append(v - g.position(after, "a"))
                    l_.append(v)
                    n_.append(self.abstract(after))
                ch.append(c_)
                lf.append(l_)
                nx.append(n_)
            self.rows.append(rows)
            self.cols.append(cols)
            self.change.append(ch)
            self.leaf.append(lf)
            self.next.append(nx)

    def solve(self, depth: int = 3, discount: float = 0.75) -> dict:
        if not hasattr(self, "rows"):
            self.expand()
        V: list[float] = []
        delta = None
        for k in range(1, depth + 1):
            nV, P, Q = [], [], []
            for s in range(self.n):
                if k == 1:
                    M = self.leaf[s]
                else:
                    M = [[c + discount * V[x] for c, x in zip(cr, xr)] for cr, xr in zip(self.change[s], self.next[s])]
                sol = _solve(M)
                nV.append(float(sol["value"]))
                P.append(_mix(sol["p"]))
                Q.append(_mix(sol["q"]))
            if V:
                delta = max(abs(x - y) for x, y in zip(nV, V))
            V = nV
            self.P, self.Q = P, Q
        self.V = V
        self.depth, self.discount = depth, discount
        return {"fighters": list(self.g.names), "depth": depth, "discount": discount, "states": self.n,
                "last_change": delta}

    def policy(self, k: int, side: str = "a") -> dict[str, float]:
        """The equilibrium mix at abstract state k (from a's view) of side a, or of side b."""
        names, mix = (self.rows[k], self.P[k]) if side == "a" else (self.cols[k], self.Q[k])
        return {m: p for m, p in zip(names, mix) if p > 0}

    def value_of(self, k: int, side: str = "a") -> float:
        """The tree's value of abstract state k for side a (k from a's view), or for side b (k from b's view)."""
        return self.V[k] if side == "a" else -self.V[self.mirror(k)]

    # -- strings ---------------------------------------------------------------------------------------------------
    def string_mix(self, attacker: str, frm: str, outcome: str, distance: int) -> dict[str, float]:
        """After ``frm`` by ``attacker`` ("a" or "b") connected (``outcome`` "hit" or "block") at ``distance``:
        the equilibrium weight of each link (chain card name) in the string sub-game; the rest of the
        attacker's mass is spent on stopping (its ordinary options after the recovery)."""
        side = attacker
        base = self.g
        att_name, def_name = (base.names[0], base.names[1]) if side == "a" else (base.names[1], base.names[0])
        x = base.moves[frm]
        links = [c for c in sorted(base.chains.values(), key=lambda c: c["name"])
                 if c["from"] == frm and c["to"] in base.fighters[att_name]["moves"]]
        if not links:
            return {}
        k = base.k
        guard_recovery = min(m.get("recovery", 0) for m in base.moves.values() if m["kind"] == "guard")
        free = k["hit_stun"](x.get("damage", 0)) if outcome == "hit" else guard_recovery
        g = Combat.__new__(Combat)
        g.__dict__.update(base.__dict__)
        g.names = (att_name, def_name)                 # the attacker plays the rows
        fc = g.fighters[att_name]
        att = Fighter(att_name, fc["hp"], posture=fc["posture_max"] // 5, stamina=fc["stamina_max"], stance="flow",
                      residual=x.get("momentum", 0) // 2, last_dir=x.get("dir", 9))
        dfd = fighter_at(g, def_name, 0)
        stop = State(att, dfd, distance=distance, advantage=free - (x.get("active", 3) + x.get("recovery", 10)))
        rows = [("link", c) for c in links] + [("stop", m) for m in g.options(stop, "a")]
        cols = g.options(stop, "b")
        M = []
        for kind, r in rows:
            if kind == "link":
                gl = copy.copy(g)
                y = g.moves[r["to"]]
                gl.moves = {**g.moves, r["to"]: {**y, "damage": y.get("damage", 0) * r.get("damage_pct", 100) // 100}}
                s = State(att, dfd, distance=distance, advantage=free - (x.get("active", 3) + r["window"][0]))
                move = r["to"]
            else:
                gl, s, move = g, stop, r
            line = []
            for cb in cols:
                after, _ = gl.resolve(s, move, cb)
                v = gl.value(s, after, "a")
                if self.V and self.depth > 1:
                    v = v - gl.position(after, "a") + self.discount * self._value_from(side, after)
                line.append(v)
            M.append(line)
        sol = _solve(M)
        return {r["name"]: p for (kind, r), p in zip(rows, _mix(sol["p"])) if kind == "link"}

    def _value_from(self, side: str, after: State) -> float:
        """The tree's value of a state built with the attacker as fighter a (whichever side it is here)."""
        if side == "a":
            return self.V[self.abstract(after)]
        flipped = State(after.b, after.a, after.distance, -after.advantage, after.exchange)
        return -self.V[self.abstract(flipped)]


__all__ = ["CENTRES", "STATUSES", "Tree", "bucket", "cuts", "fighter_at", "status"]
