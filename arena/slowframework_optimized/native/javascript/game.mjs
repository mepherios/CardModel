function cm_floordiv(a, b) { const q = a / b; return ((a % b !== 0n) && ((a < 0n) !== (b < 0n))) ? q - 1n : q; }
function combo_bonus__sum_1_to_n_closed_form(hits) {
    if ((hits <= (0n))) {
        return (0n);
    }
    return cm_floordiv((hits * (hits + (1n))), (2n));
}

function combo_bonus(hits) {
    return ((5n) * combo_bonus__sum_1_to_n_closed_form(hits));
}

function damage(attack, defense, crit) {
    let base = 0n;
    base = (((attack * (2n)) + (0n)) - defense);
    if ((base < (1n))) {
        base = (1n);
    }
    if (crit) {
        return (base * (2n));
    }
    return base;
}

function distance_sq(x1, y1, x2, y2) {
    return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)));
}

function in_range(x1, y1, x2, y2, radius) {
    return (distance_sq(x1, y1, x2, y2) <= (radius * radius));
}

function lerp(a, b, t) {
    return (a + ((b - a) * t));
}

function cm_floordiv(a, b) { const q = a / b; return ((a % b !== 0n) && ((a < 0n) !== (b < 0n))) ? q - 1n : q; }
function xp_for_level__sum_of_squares_closed_form(level) {
    if ((level <= (0n))) {
        return (0n);
    }
    return cm_floordiv(((level * (level + (1n))) * (((2n) * level) + (1n))), (6n));
}

function xp_for_level(level) {
    return ((10n) * xp_for_level__sum_of_squares_closed_form(level));
}

function level_from_xp(xp) {
    let level = 0n;
    level = (0n);
    while ((xp_for_level((level + (1n))) <= xp)) {
        level = (level + (1n));
    }
    return level;
}

function cm_floormod(a, b) { const r = a % b; return (r !== 0n && ((r < 0n) !== (b < 0n))) ? r + b : r; }
function next_seed(seed) {
    return cm_floormod(((seed * (1103515245n)) + (12345n)), (2147483648n));
}

function tiles_in_circle(r) {
    let count = 0n;
    let x = 0n;
    let cm_it1 = 0n;
    let cm_stop2 = 0n;
    let y = 0n;
    let cm_it3 = 0n;
    let cm_stop4 = 0n;
    count = (0n);
    cm_it1 = (-r);
    cm_stop2 = (r + (1n));
    while ((cm_it1 < cm_stop2)) {
        x = cm_it1;
        cm_it1 = (cm_it1 + (1n));
        cm_it3 = (-r);
        cm_stop4 = (r + (1n));
        while ((cm_it3 < cm_stop4)) {
            y = cm_it3;
            cm_it3 = (cm_it3 + (1n));
            if ((((x * x) + (y * y)) <= (r * r))) {
                count = (count + (1n));
            }
        }
    }
    return count;
}

function trajectory_y(a, b, c, d, t) {
    return ((((a * (t ** (3n))) + (b * (t ** (2n)))) + (c * t)) + d);
}
