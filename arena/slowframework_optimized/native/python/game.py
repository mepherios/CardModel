def combo_bonus__sum_1_to_n_closed_form(hits: int) -> int:
    if (hits <= 0):
        return 0
    return ((hits * (hits + 1)) // 2)


def combo_bonus(hits: int) -> int:
    return (5 * combo_bonus__sum_1_to_n_closed_form(hits))


def damage(attack: int, defense: int, crit: bool) -> int:
    base = (((attack * 2) + 0) - defense)
    if (base < 1):
        base = 1
    if crit:
        return (base * 2)
    return base


def distance_sq(x1: int, y1: int, x2: int, y2: int) -> int:
    return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)))


def in_range(x1: int, y1: int, x2: int, y2: int, radius: int) -> bool:
    return (distance_sq(x1, y1, x2, y2) <= (radius * radius))


def lerp(a: float, b: float, t: float) -> float:
    return (a + ((b - a) * t))


def xp_for_level__sum_of_squares_closed_form(level: int) -> int:
    if (level <= 0):
        return 0
    return (((level * (level + 1)) * ((2 * level) + 1)) // 6)


def xp_for_level(level: int) -> int:
    return (10 * xp_for_level__sum_of_squares_closed_form(level))


def level_from_xp(xp: int) -> int:
    level = 0
    while (xp_for_level((level + 1)) <= xp):
        level = (level + 1)
    return level


def next_seed(seed: int) -> int:
    return (((seed * 1103515245) + 12345) % 2147483648)


def tiles_in_circle(r: int) -> int:
    count = 0
    for x in range((-r), (r + 1), 1):
        for y in range((-r), (r + 1), 1):
            if (((x * x) + (y * y)) <= (r * r)):
                count = (count + 1)
    return count


def trajectory_y(a: int, b: int, c: int, d: int, t: int) -> int:
    return ((((a * (t ** 3)) + (b * (t ** 2))) + (c * t)) + d)

