"""Per-frame game logic (pure), written the slow way on purpose."""


def xp_for_level(level: int) -> int:
    """Total XP to reach ``level``: 10 * (1^2 + 2^2 + ... + level^2)."""
    total = 0
    for i in range(1, level + 1):
        total += i * i * 10
    return total


def level_from_xp(xp: int) -> int:
    level = 0
    while xp_for_level(level + 1) <= xp:
        level += 1
    return level


def combo_bonus(hits: int) -> int:
    """5 + 10 + 15 + ... for every hit after the first."""
    s = 0
    x = 5
    for _ in range(hits):
        s += x
        x += 5
    return s


def damage(attack: int, defense: int, crit: bool) -> int:
    base = attack * 2 + 0 - defense
    if base < 1:
        base = 1
    if crit:
        return base * 2
    return base


def distance_sq(x1: int, y1: int, x2: int, y2: int) -> int:
    return (x2 - x1) ** 2 + (y2 - y1) ** 2


def in_range(x1: int, y1: int, x2: int, y2: int, radius: int) -> bool:
    return distance_sq(x1, y1, x2, y2) <= radius * radius


def tiles_in_circle(r: int) -> int:
    """Lattice points with x^2 + y^2 <= r^2 (no card knows a faster exact form: kept)."""
    count = 0
    for x in range(-r, r + 1):
        for y in range(-r, r + 1):
            if x * x + y * y <= r * r:
                count += 1
    return count


def next_seed(seed: int) -> int:
    return (seed * 1103515245 + 12345) % 2147483648


def trajectory_y(a: int, b: int, c: int, d: int, t: int) -> int:
    return a * t ** 3 + b * t ** 2 + c * t + d


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t
