"""Game loop wiring. Module-level code here is never executed by the optimizer."""
from . import game, mathx


def frame(state):
    state["xp"] += game.damage(state["attack"], 3, False)
    state["level"] = game.level_from_xp(state["xp"])
    state["wave"] = mathx.wave_size(min(state["level"], 25))
    return state


if __name__ == "__main__":
    s = {"xp": 0, "attack": 12, "level": 0, "wave": 0}
    for _ in range(100):
        s = frame(s)
    print(s)
