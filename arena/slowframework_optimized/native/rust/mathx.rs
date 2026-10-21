#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floordiv(a: i64, b: i64) -> i64 { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q } }
fn cm_floormod(a: i64, b: i64) -> i64 { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { r + b } else { r } }
fn checksum_pow__modpow_square_multiply(a: i64, b: i64, m: i64) -> i64 {
    let mut r: i64 = 0;
    let mut x: i64 = 0;
    let mut e: i64 = 0;
    r = cm_floormod((1i64), m);
    x = cm_floormod(a, m);
    e = b;
    while (e > (0i64)) {
        if (cm_floormod(e, (2i64)) == (1i64)) {
            r = cm_floormod((r * x), m);
        }
        x = cm_floormod((x * x), m);
        e = cm_floordiv(e, (2i64));
    }
    return r;
}

fn checksum_pow__original(a: i64, b: i64, m: i64) -> i64 {
    let mut r: i64 = 0;
    let mut cm_u: i64 = 0;
    let mut cm_it1: i64 = 0;
    let mut cm_stop2: i64 = 0;
    r = cm_floormod((1i64), m);
    cm_it1 = (0i64);
    cm_stop2 = b;
    while (cm_it1 < cm_stop2) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + (1i64));
        r = cm_floormod((r * a), m);
    }
    return r;
}

fn checksum_pow(a: i64, b: i64, m: i64) -> i64 {
    if ((b >= (0i64)) && (m >= (1i64))) {
        return checksum_pow__modpow_square_multiply(a, b, m);
    }
    return checksum_pow__original(a, b, m);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floordiv(a: i64, b: i64) -> i64 { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q } }
fn cm_min_i(a: i64, b: i64) -> i64 { if b < a { b } else { a } }
fn choose__binomial_multiplicative(n: i64, k: i64) -> i64 {
    let mut k: i64 = k;
    let mut c: i64 = 0;
    let mut i: i64 = 0;
    let mut cm_it1: i64 = 0;
    let mut cm_stop2: i64 = 0;
    if ((k < (0i64)) || (k > n)) {
        return (0i64);
    }
    k = cm_min_i(k, (n - k));
    c = (1i64);
    cm_it1 = (0i64);
    cm_stop2 = k;
    while (cm_it1 < cm_stop2) {
        i = cm_it1;
        cm_it1 = (cm_it1 + (1i64));
        c = cm_floordiv((c * (n - i)), (i + (1i64)));
    }
    return c;
}

fn choose__original(n: i64, k: i64) -> i64 {
    let mut a: i64 = 0;
    let mut i: i64 = 0;
    let mut cm_it1: i64 = 0;
    let mut cm_stop2: i64 = 0;
    let mut b: i64 = 0;
    let mut cm_it3: i64 = 0;
    let mut cm_stop4: i64 = 0;
    let mut c: i64 = 0;
    let mut cm_it5: i64 = 0;
    let mut cm_stop6: i64 = 0;
    if ((k < (0i64)) || (k > n)) {
        return (0i64);
    }
    a = (1i64);
    cm_it1 = (2i64);
    cm_stop2 = (n + (1i64));
    while (cm_it1 < cm_stop2) {
        i = cm_it1;
        cm_it1 = (cm_it1 + (1i64));
        a = (a * i);
    }
    b = (1i64);
    cm_it3 = (2i64);
    cm_stop4 = (k + (1i64));
    while (cm_it3 < cm_stop4) {
        i = cm_it3;
        cm_it3 = (cm_it3 + (1i64));
        b = (b * i);
    }
    c = (1i64);
    cm_it5 = (2i64);
    cm_stop6 = ((n - k) + (1i64));
    while (cm_it5 < cm_stop6) {
        i = cm_it5;
        cm_it5 = (cm_it5 + (1i64));
        c = (c * i);
    }
    return cm_floordiv(a, (b * c));
}

fn choose(n: i64, k: i64) -> i64 {
    if (n >= (0i64)) {
        return choose__binomial_multiplicative(n, k);
    }
    return choose__original(n, k);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_abs_i(a: i64) -> i64 { if a < 0 { -a } else { a } }
fn cm_floordiv(a: i64, b: i64) -> i64 { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q } }
fn cm_gcd(a: i64, b: i64) -> i64 { let mut a = if a < 0 { -a } else { a }; let mut b = if b < 0 { -b } else { b }; while b != 0 { let t = a % b; a = b; b = t; } a }
fn common_period__lcm_via_gcd(a: i64, b: i64) -> i64 {
    let mut a: i64 = a;
    let mut b: i64 = b;
    a = cm_abs_i(a);
    b = cm_abs_i(b);
    if ((a == (0i64)) || (b == (0i64))) {
        return (0i64);
    }
    return (cm_floordiv(a, cm_gcd(a, b)) * b);
}

fn common_period(a: i64, b: i64) -> i64 {
    return common_period__lcm_via_gcd(a, b);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_abs_i(a: i64) -> i64 { if a < 0 { -a } else { a } }
fn cm_floormod(a: i64, b: i64) -> i64 { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { r + b } else { r } }
fn digit_root__digital_root_closed_form(n: i64) -> i64 {
    let mut n: i64 = n;
    n = cm_abs_i(n);
    if (n == (0i64)) {
        return (0i64);
    }
    return ((1i64) + cm_floormod((n - (1i64)), (9i64)));
}

fn digit_root(n: i64) -> i64 {
    return digit_root__digital_root_closed_form(n);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floordiv(a: i64, b: i64) -> i64 { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q } }
fn cm_floormod(a: i64, b: i64) -> i64 { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { r + b } else { r } }
fn divisor_sum__sum_of_divisors_sqrt_pairs(n: i64) -> i64 {
    let mut s: i64 = 0;
    let mut d: i64 = 0;
    if (n <= (0i64)) {
        return (0i64);
    }
    s = (0i64);
    d = (1i64);
    while ((d * d) <= n) {
        if (cm_floormod(n, d) == (0i64)) {
            s = (s + d);
            if ((d * d) != n) {
                s = (s + cm_floordiv(n, d));
            }
        }
        d = (d + (1i64));
    }
    return s;
}

fn divisor_sum(n: i64) -> i64 {
    return divisor_sum__sum_of_divisors_sqrt_pairs(n);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floordiv(a: i64, b: i64) -> i64 { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q } }
fn cm_floormod(a: i64, b: i64) -> i64 { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { r + b } else { r } }
fn int_power__power_square_multiply(base: i64, exp: i64) -> i64 {
    let mut r: i64 = 0;
    let mut x: i64 = 0;
    let mut e: i64 = 0;
    r = (1i64);
    x = base;
    e = exp;
    while (e > (0i64)) {
        if (cm_floormod(e, (2i64)) == (1i64)) {
            r = (r * x);
        }
        x = (x * x);
        e = cm_floordiv(e, (2i64));
    }
    return r;
}

fn int_power__original(base: i64, exp: i64) -> i64 {
    let mut r: i64 = 0;
    let mut cm_u: i64 = 0;
    let mut cm_it1: i64 = 0;
    let mut cm_stop2: i64 = 0;
    r = (1i64);
    cm_it1 = (0i64);
    cm_stop2 = exp;
    while (cm_it1 < cm_stop2) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + (1i64));
        r = (r * base);
    }
    return r;
}

fn int_power(base: i64, exp: i64) -> i64 {
    if (exp >= (0i64)) {
        return int_power__power_square_multiply(base, exp);
    }
    return int_power__original(base, exp);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floormod(a: i64, b: i64) -> i64 { let r = a % b; if r != 0 && ((r < 0) != (b < 0)) { r + b } else { r } }
fn is_prime_level__is_prime_wheel_6k(n: i64) -> bool {
    let mut d: i64 = 0;
    if (n < (2i64)) {
        return false;
    }
    if (n < (4i64)) {
        return true;
    }
    if ((cm_floormod(n, (2i64)) == (0i64)) || (cm_floormod(n, (3i64)) == (0i64))) {
        return false;
    }
    d = (5i64);
    while ((d * d) <= n) {
        if ((cm_floormod(n, d) == (0i64)) || (cm_floormod(n, (d + (2i64))) == (0i64))) {
            return false;
        }
        d = (d + (6i64));
    }
    return true;
}

fn is_prime_level(n: i64) -> bool {
    return is_prime_level__is_prime_wheel_6k(n);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn is_texture_size__is_power_of_two_bit_trick(n: i64) -> bool {
    return ((n > (0i64)) && ((n & (n - (1i64))) == (0i64)));
}

fn is_texture_size(n: i64) -> bool {
    return is_texture_size__is_power_of_two_bit_trick(n);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floordiv(a: i64, b: i64) -> i64 { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q } }
fn isqrt_slow__isqrt_newton(n: i64) -> i64 {
    let mut x: i64 = 0;
    let mut y: i64 = 0;
    if (n < (2i64)) {
        return n;
    }
    x = n;
    y = cm_floordiv((x + (1i64)), (2i64));
    while (y < x) {
        x = y;
        y = cm_floordiv((x + cm_floordiv(n, x)), (2i64));
    }
    return x;
}

fn isqrt_slow__original(n: i64) -> i64 {
    let mut r: i64 = 0;
    r = (0i64);
    while (((r + (1i64)) * (r + (1i64))) <= n) {
        r = (r + (1i64));
    }
    return r;
}

fn isqrt_slow(n: i64) -> i64 {
    if (n >= (0i64)) {
        return isqrt_slow__isqrt_newton(n);
    }
    return isqrt_slow__original(n);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_gcd(a: i64, b: i64) -> i64 { let mut a = if a < 0 { -a } else { a }; let mut b = if b < 0 { -b } else { b }; while b != 0 { let t = a % b; a = b; b = t; } a }
fn reduce_ratio__gcd_builtin(a: i64, b: i64) -> i64 {
    return cm_gcd(a, b);
}

fn reduce_ratio(a: i64, b: i64) -> i64 {
    return reduce_ratio__gcd_builtin(a, b);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn set_bits__popcount_kernighan(flags: i64) -> i64 {
    let mut flags: i64 = flags;
    let mut c: i64 = 0;
    c = (0i64);
    while (flags != (0i64)) {
        flags = (flags & (flags - (1i64)));
        c = (c + (1i64));
    }
    return c;
}

fn set_bits__original(flags: i64) -> i64 {
    let mut flags: i64 = flags;
    let mut c: i64 = 0;
    c = (0i64);
    while (flags != (0i64)) {
        c = (c + (flags & (1i64)));
        flags = (flags >> (1i64));
    }
    return c;
}

fn set_bits(flags: i64) -> i64 {
    if (flags >= (0i64)) {
        return set_bits__popcount_kernighan(flags);
    }
    return set_bits__original(flags);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn cm_floordiv(a: i64, b: i64) -> i64 { let q = a / b; if (a % b != 0) && ((a < 0) != (b < 0)) { q - 1 } else { q } }
fn total_points__sum_1_to_n_closed_form(n: i64) -> i64 {
    if (n <= (0i64)) {
        return (0i64);
    }
    return cm_floordiv((n * (n + (1i64))), (2i64));
}

fn total_points(n: i64) -> i64 {
    return total_points__sum_1_to_n_closed_form(n);
}

#![allow(unused_parens, unused_mut, unused_assignments, unused_variables, dead_code, non_snake_case)]

fn wave_size__fibonacci_iterative(n: i64) -> i64 {
    let mut a: i64 = 0;
    let mut b: i64 = 0;
    let mut cm_u: i64 = 0;
    let mut cm_it1: i64 = 0;
    let mut cm_stop2: i64 = 0;
    let mut cm_t3: i64 = 0;
    let mut cm_t4: i64 = 0;
    a = (0i64);
    b = (1i64);
    cm_it1 = (0i64);
    cm_stop2 = n;
    while (cm_it1 < cm_stop2) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + (1i64));
        cm_t3 = b;
        cm_t4 = (a + b);
        a = cm_t3;
        b = cm_t4;
    }
    return a;
}

fn wave_size__original(n: i64) -> i64 {
    if (n < (2i64)) {
        return n;
    }
    return (wave_size((n - (1i64))) + wave_size((n - (2i64))));
}

fn wave_size(n: i64) -> i64 {
    if (n >= (0i64)) {
        return wave_size__fibonacci_iterative(n);
    }
    return wave_size__original(n);
}
