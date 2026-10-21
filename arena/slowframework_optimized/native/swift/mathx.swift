import Foundation

func cm_floordiv(_ a: Int, _ b: Int) -> Int { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { return q - 1 }; return q }
func cm_floormod(_ a: Int, _ b: Int) -> Int { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { return r + b }; return r }
func checksum_pow__modpow_square_multiply(_ a: Int, _ b: Int, _ m: Int) -> Int {
    var r: Int = 0
    var x: Int = 0
    var e: Int = 0
    r = cm_floormod((1), m)
    x = cm_floormod(a, m)
    e = b
    while (e > (0)) {
        if (cm_floormod(e, (2)) == (1)) {
            r = cm_floormod((r * x), m)
        }
        x = cm_floormod((x * x), m)
        e = cm_floordiv(e, (2))
    }
    return r
}

func checksum_pow__original(_ a: Int, _ b: Int, _ m: Int) -> Int {
    var r: Int = 0
    var cm_u: Int = 0
    var cm_it1: Int = 0
    var cm_stop2: Int = 0
    r = cm_floormod((1), m)
    cm_it1 = (0)
    cm_stop2 = b
    while (cm_it1 < cm_stop2) {
        cm_u = cm_it1
        cm_it1 = (cm_it1 + (1))
        r = cm_floormod((r * a), m)
    }
    return r
}

func checksum_pow(_ a: Int, _ b: Int, _ m: Int) -> Int {
    if ((b >= (0)) && (m >= (1))) {
        return checksum_pow__modpow_square_multiply(a, b, m)
    }
    return checksum_pow__original(a, b, m)
}

import Foundation

func cm_floordiv(_ a: Int, _ b: Int) -> Int { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { return q - 1 }; return q }
func cm_min_i(_ a: Int, _ b: Int) -> Int { return b < a ? b : a }
func choose__binomial_multiplicative(_ n: Int, _ k: Int) -> Int {
    var k: Int = k
    var c: Int = 0
    var i: Int = 0
    var cm_it1: Int = 0
    var cm_stop2: Int = 0
    if ((k < (0)) || (k > n)) {
        return (0)
    }
    k = cm_min_i(k, (n - k))
    c = (1)
    cm_it1 = (0)
    cm_stop2 = k
    while (cm_it1 < cm_stop2) {
        i = cm_it1
        cm_it1 = (cm_it1 + (1))
        c = cm_floordiv((c * (n - i)), (i + (1)))
    }
    return c
}

func choose__original(_ n: Int, _ k: Int) -> Int {
    var a: Int = 0
    var i: Int = 0
    var cm_it1: Int = 0
    var cm_stop2: Int = 0
    var b: Int = 0
    var cm_it3: Int = 0
    var cm_stop4: Int = 0
    var c: Int = 0
    var cm_it5: Int = 0
    var cm_stop6: Int = 0
    if ((k < (0)) || (k > n)) {
        return (0)
    }
    a = (1)
    cm_it1 = (2)
    cm_stop2 = (n + (1))
    while (cm_it1 < cm_stop2) {
        i = cm_it1
        cm_it1 = (cm_it1 + (1))
        a = (a * i)
    }
    b = (1)
    cm_it3 = (2)
    cm_stop4 = (k + (1))
    while (cm_it3 < cm_stop4) {
        i = cm_it3
        cm_it3 = (cm_it3 + (1))
        b = (b * i)
    }
    c = (1)
    cm_it5 = (2)
    cm_stop6 = ((n - k) + (1))
    while (cm_it5 < cm_stop6) {
        i = cm_it5
        cm_it5 = (cm_it5 + (1))
        c = (c * i)
    }
    return cm_floordiv(a, (b * c))
}

func choose(_ n: Int, _ k: Int) -> Int {
    if (n >= (0)) {
        return choose__binomial_multiplicative(n, k)
    }
    return choose__original(n, k)
}

import Foundation

func cm_floordiv(_ a: Int, _ b: Int) -> Int { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { return q - 1 }; return q }
func cm_gcd(_ a0: Int, _ b0: Int) -> Int { var a = a0 < 0 ? -a0 : a0; var b = b0 < 0 ? -b0 : b0; while b != 0 { let t = a % b; a = b; b = t }; return a }
func common_period__lcm_via_gcd(_ a: Int, _ b: Int) -> Int {
    var a: Int = a
    var b: Int = b
    a = abs(a)
    b = abs(b)
    if ((a == (0)) || (b == (0))) {
        return (0)
    }
    return (cm_floordiv(a, cm_gcd(a, b)) * b)
}

func common_period(_ a: Int, _ b: Int) -> Int {
    return common_period__lcm_via_gcd(a, b)
}

import Foundation

func cm_floormod(_ a: Int, _ b: Int) -> Int { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { return r + b }; return r }
func digit_root__digital_root_closed_form(_ n: Int) -> Int {
    var n: Int = n
    n = abs(n)
    if (n == (0)) {
        return (0)
    }
    return ((1) + cm_floormod((n - (1)), (9)))
}

func digit_root(_ n: Int) -> Int {
    return digit_root__digital_root_closed_form(n)
}

import Foundation

func cm_floordiv(_ a: Int, _ b: Int) -> Int { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { return q - 1 }; return q }
func cm_floormod(_ a: Int, _ b: Int) -> Int { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { return r + b }; return r }
func divisor_sum__sum_of_divisors_sqrt_pairs(_ n: Int) -> Int {
    var s: Int = 0
    var d: Int = 0
    if (n <= (0)) {
        return (0)
    }
    s = (0)
    d = (1)
    while ((d * d) <= n) {
        if (cm_floormod(n, d) == (0)) {
            s = (s + d)
            if ((d * d) != n) {
                s = (s + cm_floordiv(n, d))
            }
        }
        d = (d + (1))
    }
    return s
}

func divisor_sum(_ n: Int) -> Int {
    return divisor_sum__sum_of_divisors_sqrt_pairs(n)
}

import Foundation

func cm_floordiv(_ a: Int, _ b: Int) -> Int { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { return q - 1 }; return q }
func cm_floormod(_ a: Int, _ b: Int) -> Int { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { return r + b }; return r }
func int_power__power_square_multiply(_ base: Int, _ exp: Int) -> Int {
    var r: Int = 0
    var x: Int = 0
    var e: Int = 0
    r = (1)
    x = base
    e = exp
    while (e > (0)) {
        if (cm_floormod(e, (2)) == (1)) {
            r = (r * x)
        }
        x = (x * x)
        e = cm_floordiv(e, (2))
    }
    return r
}

func int_power__original(_ base: Int, _ exp: Int) -> Int {
    var r: Int = 0
    var cm_u: Int = 0
    var cm_it1: Int = 0
    var cm_stop2: Int = 0
    r = (1)
    cm_it1 = (0)
    cm_stop2 = exp
    while (cm_it1 < cm_stop2) {
        cm_u = cm_it1
        cm_it1 = (cm_it1 + (1))
        r = (r * base)
    }
    return r
}

func int_power(_ base: Int, _ exp: Int) -> Int {
    if (exp >= (0)) {
        return int_power__power_square_multiply(base, exp)
    }
    return int_power__original(base, exp)
}

import Foundation

func cm_floormod(_ a: Int, _ b: Int) -> Int { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { return r + b }; return r }
func is_prime_level__is_prime_wheel_6k(_ n: Int) -> Bool {
    var d: Int = 0
    if (n < (2)) {
        return false
    }
    if (n < (4)) {
        return true
    }
    if ((cm_floormod(n, (2)) == (0)) || (cm_floormod(n, (3)) == (0))) {
        return false
    }
    d = (5)
    while ((d * d) <= n) {
        if ((cm_floormod(n, d) == (0)) || (cm_floormod(n, (d + (2))) == (0))) {
            return false
        }
        d = (d + (6))
    }
    return true
}

func is_prime_level(_ n: Int) -> Bool {
    return is_prime_level__is_prime_wheel_6k(n)
}

import Foundation

func is_texture_size__is_power_of_two_bit_trick(_ n: Int) -> Bool {
    return ((n > (0)) && ((n & (n - (1))) == (0)))
}

func is_texture_size(_ n: Int) -> Bool {
    return is_texture_size__is_power_of_two_bit_trick(n)
}

import Foundation

func cm_floordiv(_ a: Int, _ b: Int) -> Int { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { return q - 1 }; return q }
func isqrt_slow__isqrt_newton(_ n: Int) -> Int {
    var x: Int = 0
    var y: Int = 0
    if (n < (2)) {
        return n
    }
    x = n
    y = cm_floordiv((x + (1)), (2))
    while (y < x) {
        x = y
        y = cm_floordiv((x + cm_floordiv(n, x)), (2))
    }
    return x
}

func isqrt_slow__original(_ n: Int) -> Int {
    var r: Int = 0
    r = (0)
    while (((r + (1)) * (r + (1))) <= n) {
        r = (r + (1))
    }
    return r
}

func isqrt_slow(_ n: Int) -> Int {
    if (n >= (0)) {
        return isqrt_slow__isqrt_newton(n)
    }
    return isqrt_slow__original(n)
}

import Foundation

func cm_gcd(_ a0: Int, _ b0: Int) -> Int { var a = a0 < 0 ? -a0 : a0; var b = b0 < 0 ? -b0 : b0; while b != 0 { let t = a % b; a = b; b = t }; return a }
func reduce_ratio__gcd_builtin(_ a: Int, _ b: Int) -> Int {
    return cm_gcd(a, b)
}

func reduce_ratio(_ a: Int, _ b: Int) -> Int {
    return reduce_ratio__gcd_builtin(a, b)
}

import Foundation

func set_bits__popcount_kernighan(_ flags: Int) -> Int {
    var flags: Int = flags
    var c: Int = 0
    c = (0)
    while (flags != (0)) {
        flags = (flags & (flags - (1)))
        c = (c + (1))
    }
    return c
}

func set_bits__original(_ flags: Int) -> Int {
    var flags: Int = flags
    var c: Int = 0
    c = (0)
    while (flags != (0)) {
        c = (c + (flags & (1)))
        flags = (flags >> (1))
    }
    return c
}

func set_bits(_ flags: Int) -> Int {
    if (flags >= (0)) {
        return set_bits__popcount_kernighan(flags)
    }
    return set_bits__original(flags)
}

import Foundation

func cm_floordiv(_ a: Int, _ b: Int) -> Int { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { return q - 1 }; return q }
func total_points__sum_1_to_n_closed_form(_ n: Int) -> Int {
    if (n <= (0)) {
        return (0)
    }
    return cm_floordiv((n * (n + (1))), (2))
}

func total_points(_ n: Int) -> Int {
    return total_points__sum_1_to_n_closed_form(n)
}

import Foundation

func wave_size__fibonacci_iterative(_ n: Int) -> Int {
    var a: Int = 0
    var b: Int = 0
    var cm_u: Int = 0
    var cm_it1: Int = 0
    var cm_stop2: Int = 0
    var cm_t3: Int = 0
    var cm_t4: Int = 0
    a = (0)
    b = (1)
    cm_it1 = (0)
    cm_stop2 = n
    while (cm_it1 < cm_stop2) {
        cm_u = cm_it1
        cm_it1 = (cm_it1 + (1))
        cm_t3 = b
        cm_t4 = (a + b)
        a = cm_t3
        b = cm_t4
    }
    return a
}

func wave_size__original(_ n: Int) -> Int {
    if (n < (2)) {
        return n
    }
    return (wave_size((n - (1))) + wave_size((n - (2))))
}

func wave_size(_ n: Int) -> Int {
    if (n >= (0)) {
        return wave_size__fibonacci_iterative(n)
    }
    return wave_size__original(n)
}
