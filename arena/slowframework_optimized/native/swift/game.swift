import Foundation

func cm_floordiv(_ a: Int, _ b: Int) -> Int { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { return q - 1 }; return q }
func combo_bonus__sum_1_to_n_closed_form(_ hits: Int) -> Int {
    if (hits <= (0)) {
        return (0)
    }
    return cm_floordiv((hits * (hits + (1))), (2))
}

func combo_bonus(_ hits: Int) -> Int {
    return ((5) * combo_bonus__sum_1_to_n_closed_form(hits))
}

import Foundation

func damage(_ attack: Int, _ defense: Int, _ crit: Bool) -> Int {
    var base: Int = 0
    base = (((attack * (2)) + (0)) - defense)
    if (base < (1)) {
        base = (1)
    }
    if crit {
        return (base * (2))
    }
    return base
}

import Foundation

func distance_sq(_ x1: Int, _ y1: Int, _ x2: Int, _ y2: Int) -> Int {
    return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)))
}

import Foundation

func in_range(_ x1: Int, _ y1: Int, _ x2: Int, _ y2: Int, _ radius: Int) -> Bool {
    return (distance_sq(x1, y1, x2, y2) <= (radius * radius))
}

import Foundation

func lerp(_ a: Double, _ b: Double, _ t: Double) -> Double {
    return (a + ((b - a) * t))
}

import Foundation

func cm_floordiv(_ a: Int, _ b: Int) -> Int { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { return q - 1 }; return q }
func xp_for_level__sum_of_squares_closed_form(_ level: Int) -> Int {
    if (level <= (0)) {
        return (0)
    }
    return cm_floordiv(((level * (level + (1))) * (((2) * level) + (1))), (6))
}

func xp_for_level(_ level: Int) -> Int {
    return ((10) * xp_for_level__sum_of_squares_closed_form(level))
}

func level_from_xp(_ xp: Int) -> Int {
    var level: Int = 0
    level = (0)
    while (xp_for_level((level + (1))) <= xp) {
        level = (level + (1))
    }
    return level
}

import Foundation

func cm_floormod(_ a: Int, _ b: Int) -> Int { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { return r + b }; return r }
func next_seed(_ seed: Int) -> Int {
    return cm_floormod(((seed * (1103515245)) + (12345)), (2147483648))
}

import Foundation

func tiles_in_circle(_ r: Int) -> Int {
    var count: Int = 0
    var x: Int = 0
    var cm_it1: Int = 0
    var cm_stop2: Int = 0
    var y: Int = 0
    var cm_it3: Int = 0
    var cm_stop4: Int = 0
    count = (0)
    cm_it1 = (-r)
    cm_stop2 = (r + (1))
    while (cm_it1 < cm_stop2) {
        x = cm_it1
        cm_it1 = (cm_it1 + (1))
        cm_it3 = (-r)
        cm_stop4 = (r + (1))
        while (cm_it3 < cm_stop4) {
            y = cm_it3
            cm_it3 = (cm_it3 + (1))
            if (((x * x) + (y * y)) <= (r * r)) {
                count = (count + (1))
            }
        }
    }
    return count
}

import Foundation

func cm_ipow(_ a0: Int, _ b0: Int) -> Int { var r = 1; var a = a0; var b = b0; while b > 0 { if (b & 1) == 1 { r = r &* a }; b >>= 1; if b > 0 { a = a &* a } }; return r }
func trajectory_y(_ a: Int, _ b: Int, _ c: Int, _ d: Int, _ t: Int) -> Int {
    return ((((a * cm_ipow(t, (3))) + (b * cm_ipow(t, (2)))) + (c * t)) + d)
}
