#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floordiv(a: i64, b: i64) -> i64 { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q } }
fn combo_bonus__sum_1_to_n_closed_form(hits: i64) -> i64 {
    if (hits <= (0i64)) {
        return (0i64);
    }
    return cm_floordiv((hits * (hits + (1i64))), (2i64));
}

fn combo_bonus(hits: i64) -> i64 {
    return ((5i64) * combo_bonus__sum_1_to_n_closed_form(hits));
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn damage(attack: i64, defense: i64, crit: bool) -> i64 {
    let mut base: i64 = 0;
    base = (((attack * (2i64)) + (0i64)) - defense);
    if (base < (1i64)) {
        base = (1i64);
    }
    if crit {
        return (base * (2i64));
    }
    return base;
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn distance_sq(x1: i64, y1: i64, x2: i64, y2: i64) -> i64 {
    return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)));
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn in_range(x1: i64, y1: i64, x2: i64, y2: i64, radius: i64) -> bool {
    return (distance_sq(x1, y1, x2, y2) <= (radius * radius));
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn lerp(a: f64, b: f64, t: f64) -> f64 {
    return (a + ((b - a) * t));
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floordiv(a: i64, b: i64) -> i64 { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q } }
fn xp_for_level__sum_of_squares_closed_form(level: i64) -> i64 {
    if (level <= (0i64)) {
        return (0i64);
    }
    return cm_floordiv(((level * (level + (1i64))) * (((2i64) * level) + (1i64))), (6i64));
}

fn xp_for_level(level: i64) -> i64 {
    return ((10i64) * xp_for_level__sum_of_squares_closed_form(level));
}

fn level_from_xp(xp: i64) -> i64 {
    let mut level: i64 = 0;
    level = (0i64);
    while (xp_for_level((level + (1i64))) <= xp) {
        level = (level + (1i64));
    }
    return level;
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floormod(a: i64, b: i64) -> i64 { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { r + b } else { r } }
fn next_seed(seed: i64) -> i64 {
    return cm_floormod(((seed * (1103515245i64)) + (12345i64)), (2147483648i64));
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn tiles_in_circle(r: i64) -> i64 {
    let mut count: i64 = 0;
    let mut x: i64 = 0;
    let mut cm_it1: i64 = 0;
    let mut cm_stop2: i64 = 0;
    let mut y: i64 = 0;
    let mut cm_it3: i64 = 0;
    let mut cm_stop4: i64 = 0;
    count = (0i64);
    cm_it1 = (-r);
    cm_stop2 = (r + (1i64));
    while (cm_it1 < cm_stop2) {
        x = cm_it1;
        cm_it1 = (cm_it1 + (1i64));
        cm_it3 = (-r);
        cm_stop4 = (r + (1i64));
        while (cm_it3 < cm_stop4) {
            y = cm_it3;
            cm_it3 = (cm_it3 + (1i64));
            if (((x * x) + (y * y)) <= (r * r)) {
                count = (count + (1i64));
            }
        }
    }
    return count;
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_ipow(a: i64, b: i64) -> i64 { let mut r: i64 = 1; let mut a = a; let mut b = b; while b > 0 { if (b & 1) == 1 { r = r.wrapping_mul(a); } b >>= 1; if b > 0 { a = a.wrapping_mul(a); } } r }
fn trajectory_y(a: i64, b: i64, c: i64, d: i64, t: i64) -> i64 {
    return ((((a * cm_ipow(t, (3i64))) + (b * cm_ipow(t, (2i64)))) + (c * t)) + d);
}
