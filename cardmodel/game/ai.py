"""ai — agents for the Vector Counter System, and duels/tournaments to measure them.

* random        uniform over the allowed moves
* greedy        best one-step value against a uniformly random opponent
* equilibrium   samples the exact-game equilibrium of the current exchange (unexploitable per exchange)
* reader        the vector reader: tracks which *vector features* the opponent leans on (kind, direction,
                height, tags), with decay; predicts the opponent's next move from those features, best-responds
                to the prediction, and mixes in the equilibrium (epsilon) so it cannot be farmed. It is focused
                on the specific vector that moves the opponent's play, not on move names.

Honest limits (L1): one-exchange lookahead (no search over the duel tree); seeded, so a run is reproducible.
"""
from __future__ import annotations

import math
import random

from . import analysis as A
from .combat import Combat, State


def side_matrix(game: Combat, state: State, side: str):
    """Rows: this side's options; columns: the opponent's; values from this side's perspective."""
    mine = game.options(state, side)
    theirs = game.options(state, "b" if side == "a" else "a")
    M = []
    for m in mine:
        row = []
        for t in theirs:
            after, _ = game.resolve(state, m, t) if side == "a" else game.resolve(state, t, m)
            row.append(game.value(state, after, side))
        M.append(row)
    return mine, theirs, M


class Agent:
    name = "agent"

    def choose(self, game: Combat, state: State, side: str, rng: random.Random) -> str:
        raise NotImplementedError

    def observe(self, game: Combat, my_move: str, their_move: str) -> None:
        pass


class RandomAgent(Agent):
    name = "random"

    def choose(self, game, state, side, rng):
        return rng.choice(game.options(state, side))


class GreedyAgent(Agent):
    name = "greedy"

    def choose(self, game, state, side, rng):
        mine, theirs, M = side_matrix(game, state, side)
        scores = [sum(r) / len(r) for r in M]
        best = max(scores)
        return rng.choice([m for m, s in zip(mine, scores) if s == best])


class EquilibriumAgent(Agent):
    name = "equilibrium"

    def __init__(self):
        self.cache: dict = {}

    def mix(self, game, state, side):
        mine, theirs, M = side_matrix(game, state, side)
        key = (tuple(mine), tuple(theirs), tuple(tuple(round(x, 3) for x in r) for r in M))
        if key not in self.cache:
            sol = A.solve(M, exact=False)
            self.cache[key] = [max(0.0, x) for x in sol["p"]]
        return mine, theirs, M, self.cache[key]

    def choose(self, game, state, side, rng):
        mine, _, _, p = self.mix(game, state, side)
        return rng.choices(mine, weights=p)[0] if sum(p) > 0 else rng.choice(mine)


class ReaderAgent(EquilibriumAgent):
    """Learns the opponent's vector habits and exploits them, epsilon-safely."""
    name = "reader"

    def __init__(self, epsilon: float = 0.25, decay: float = 0.92):
        super().__init__()
        self.epsilon = epsilon
        self.decay = decay
        self.weights: dict[str, float] = {}

    @staticmethod
    def features(game: Combat, move: str) -> list[str]:
        mv = game.moves.get(move, {})
        out = [f"kind:{mv.get('kind')}"]
        if mv.get("dir") is not None:
            out.append(f"dir:{mv['dir']}")
        if mv.get("guard_dir") is not None:
            out.append(f"guard:{mv['guard_dir']}")
        if mv.get("height"):
            out.append(f"height:{mv['height']}")
        out += [f"tag:{t}" for t in mv.get("tags", [])]
        return out

    def observe(self, game, my_move, their_move):
        for k in list(self.weights):
            self.weights[k] *= self.decay
        for f in self.features(game, their_move):
            self.weights[f] = self.weights.get(f, 0.0) + 1.0

    def predict(self, game, theirs) -> list[float]:
        if not self.weights:
            return [1.0 / len(theirs)] * len(theirs)
        total = sum(self.weights.values())
        scores = []
        for t in theirs:
            fs = self.features(game, t)
            scores.append(math.exp(sum(math.log((self.weights.get(f, 0.0) + 0.5) / (total + 1.0)) for f in fs) / len(fs)))
        z = sum(scores)
        return [s / z for s in scores]

    def focus(self, top: int = 3) -> list[tuple[str, float]]:
        """The vector features this agent currently believes the opponent leans on."""
        return sorted(((k, round(v, 2)) for k, v in self.weights.items()), key=lambda kv: -kv[1])[:top]

    def choose(self, game, state, side, rng):
        mine, theirs, M, p = self.mix(game, state, side)
        if rng.random() < self.epsilon:
            return rng.choices(mine, weights=p)[0] if sum(p) > 0 else rng.choice(mine)
        q = self.predict(game, theirs)
        ev = [sum(qj * M[i][j] for j, qj in enumerate(q)) for i in range(len(mine))]
        best = max(ev)
        return rng.choice([m for m, e in zip(mine, ev) if e >= best - 1e-9])


class HabitAgent(Agent):
    """A predictable opponent (a habit): mostly overheads and high guards -- for showing what a reader exploits."""
    name = "habit"

    def choose(self, game, state, side, rng):
        opts = game.options(state, side)
        for pref in ("overhead", "heavy_overhead", "guard_high"):
            if pref in opts and rng.random() < 0.6:
                return pref
        return rng.choice(opts)


AGENTS = {"random": RandomAgent, "greedy": GreedyAgent, "equilibrium": EquilibriumAgent, "reader": ReaderAgent,
          "habit": HabitAgent}


def duel(game: Combat, agent_a: Agent, agent_b: Agent, seed: int, max_exchanges: int = 80,
         trace: bool = False) -> dict:
    rng = random.Random(seed)
    state = game.start()
    log = []
    while not game.over(state) and state.exchange < max_exchanges:
        ma = agent_a.choose(game, state, "a", rng)
        mb = agent_b.choose(game, state, "b", rng)
        nxt, ev = game.resolve(state, ma, mb)
        agent_a.observe(game, ma, mb)
        agent_b.observe(game, mb, ma)
        if trace:
            log.append({"exchange": state.exchange, "a": ma, "b": mb, "text": ev.text, "hp": (nxt.a.hp, nxt.b.hp),
                        "posture": (nxt.a.posture, nxt.b.posture), "advantage": nxt.advantage,
                        "distance": nxt.distance})
        state = nxt
    fa, fb = game.fighters[game.names[0]], game.fighters[game.names[1]]
    ra, rb = state.a.hp / fa["hp"], state.b.hp / fb["hp"]
    winner = "a" if state.b.hp <= 0 < state.a.hp or (state.a.hp > 0 and state.b.hp > 0 and ra > rb) else \
        "b" if state.a.hp <= 0 < state.b.hp or (state.a.hp > 0 and state.b.hp > 0 and rb > ra) else "draw"
    return {"winner": winner, "exchanges": state.exchange, "hp": (state.a.hp, state.b.hp), "log": log}


def tournament(game: Combat, names: list[str], duels: int = 6, seed: int = 0) -> dict:
    table = {a: {b: [0, 0, 0] for b in names} for a in names}      # wins, losses, draws for the row agent
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            for k in range(duels):
                first, second = (a, b) if k % 2 == 0 else (b, a)
                r = duel(game, AGENTS[first](), AGENTS[second](), seed=seed * 1000 + i * 100 + k)
                w = r["winner"]
                win = first if w == "a" else second if w == "b" else None
                for x, y in ((a, b), (b, a)):
                    if win is None:
                        table[x][y][2] += 1
                    elif win == x:
                        table[x][y][0] += 1
                    else:
                        table[x][y][1] += 1
    score = {a: sum(v[0] + 0.5 * v[2] for b, v in row.items() if b != a) for a, row in table.items()}
    return {"table": table, "score": dict(sorted(score.items(), key=lambda kv: -kv[1])), "duels_per_pair": duels,
            "seed": seed}


__all__ = ["AGENTS", "Agent", "EquilibriumAgent", "GreedyAgent", "HabitAgent", "RandomAgent", "ReaderAgent", "duel",
           "side_matrix", "tournament"]
