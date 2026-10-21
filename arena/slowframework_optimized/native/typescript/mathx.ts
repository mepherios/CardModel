function cm_floordiv(a, b) { const q = a / b; return ((a % b !== 0n) && ((a < 0n) !== (b < 0n))) ? q - 1n : q; }
function cm_floormod(a, b) { const r = a % b; return (r !== 0n && ((r < 0n) !== (b < 0n))) ? r + b : r; }
function checksum_pow__modpow_square_multiply(a: bigint, b: bigint, m: bigint): bigint {
    let r: bigint = 0n;
    let x: bigint = 0n;
    let e: bigint = 0n;
    r = cm_floormod((1n), m);
    x = cm_floormod(a, m);
    e = b;
    while ((e > (0n))) {
        if ((cm_floormod(e, (2n)) === (1n))) {
            r = cm_floormod((r * x), m);
        }
        x = cm_floormod((x * x), m);
        e = cm_floordiv(e, (2n));
    }
    return r;
}

function checksum_pow__original(a: bigint, b: bigint, m: bigint): bigint {
    let r: bigint = 0n;
    let cm_u: bigint = 0n;
    let cm_it1: bigint = 0n;
    let cm_stop2: bigint = 0n;
    r = cm_floormod((1n), m);
    cm_it1 = (0n);
    cm_stop2 = b;
    while ((cm_it1 < cm_stop2)) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + (1n));
        r = cm_floormod((r * a), m);
    }
    return r;
}

function checksum_pow(a: bigint, b: bigint, m: bigint): bigint {
    if (((b >= (0n)) && (m >= (1n)))) {
        return checksum_pow__modpow_square_multiply(a, b, m);
    }
    return checksum_pow__original(a, b, m);
}

function cm_floordiv(a, b) { const q = a / b; return ((a % b !== 0n) && ((a < 0n) !== (b < 0n))) ? q - 1n : q; }
function cm_min_i(a, b) { return b < a ? b : a; }
function choose__binomial_multiplicative(n: bigint, k: bigint): bigint {
    let c: bigint = 0n;
    let i: bigint = 0n;
    let cm_it1: bigint = 0n;
    let cm_stop2: bigint = 0n;
    if (((k < (0n)) || (k > n))) {
        return (0n);
    }
    k = cm_min_i(k, (n - k));
    c = (1n);
    cm_it1 = (0n);
    cm_stop2 = k;
    while ((cm_it1 < cm_stop2)) {
        i = cm_it1;
        cm_it1 = (cm_it1 + (1n));
        c = cm_floordiv((c * (n - i)), (i + (1n)));
    }
    return c;
}

function choose__original(n: bigint, k: bigint): bigint {
    let a: bigint = 0n;
    let i: bigint = 0n;
    let cm_it1: bigint = 0n;
    let cm_stop2: bigint = 0n;
    let b: bigint = 0n;
    let cm_it3: bigint = 0n;
    let cm_stop4: bigint = 0n;
    let c: bigint = 0n;
    let cm_it5: bigint = 0n;
    let cm_stop6: bigint = 0n;
    if (((k < (0n)) || (k > n))) {
        return (0n);
    }
    a = (1n);
    cm_it1 = (2n);
    cm_stop2 = (n + (1n));
    while ((cm_it1 < cm_stop2)) {
        i = cm_it1;
        cm_it1 = (cm_it1 + (1n));
        a = (a * i);
    }
    b = (1n);
    cm_it3 = (2n);
    cm_stop4 = (k + (1n));
    while ((cm_it3 < cm_stop4)) {
        i = cm_it3;
        cm_it3 = (cm_it3 + (1n));
        b = (b * i);
    }
    c = (1n);
    cm_it5 = (2n);
    cm_stop6 = ((n - k) + (1n));
    while ((cm_it5 < cm_stop6)) {
        i = cm_it5;
        cm_it5 = (cm_it5 + (1n));
        c = (c * i);
    }
    return cm_floordiv(a, (b * c));
}

function choose(n: bigint, k: bigint): bigint {
    if ((n >= (0n))) {
        return choose__binomial_multiplicative(n, k);
    }
    return choose__original(n, k);
}

function cm_abs_i(a) { return a < 0n ? -a : a; }
function cm_floordiv(a, b) { const q = a / b; return ((a % b !== 0n) && ((a < 0n) !== (b < 0n))) ? q - 1n : q; }
function cm_gcd(a, b) { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b !== 0n) { const t = a % b; a = b; b = t; } return a; }
function common_period__lcm_via_gcd(a: bigint, b: bigint): bigint {
    a = cm_abs_i(a);
    b = cm_abs_i(b);
    if (((a === (0n)) || (b === (0n)))) {
        return (0n);
    }
    return (cm_floordiv(a, cm_gcd(a, b)) * b);
}

function common_period(a: bigint, b: bigint): bigint {
    return common_period__lcm_via_gcd(a, b);
}

function cm_abs_i(a) { return a < 0n ? -a : a; }
function cm_floormod(a, b) { const r = a % b; return (r !== 0n && ((r < 0n) !== (b < 0n))) ? r + b : r; }
function digit_root__digital_root_closed_form(n: bigint): bigint {
    n = cm_abs_i(n);
    if ((n === (0n))) {
        return (0n);
    }
    return ((1n) + cm_floormod((n - (1n)), (9n)));
}

function digit_root(n: bigint): bigint {
    return digit_root__digital_root_closed_form(n);
}

function cm_floordiv(a, b) { const q = a / b; return ((a % b !== 0n) && ((a < 0n) !== (b < 0n))) ? q - 1n : q; }
function cm_floormod(a, b) { const r = a % b; return (r !== 0n && ((r < 0n) !== (b < 0n))) ? r + b : r; }
function divisor_sum__sum_of_divisors_sqrt_pairs(n: bigint): bigint {
    let s: bigint = 0n;
    let d: bigint = 0n;
    if ((n <= (0n))) {
        return (0n);
    }
    s = (0n);
    d = (1n);
    while (((d * d) <= n)) {
        if ((cm_floormod(n, d) === (0n))) {
            s = (s + d);
            if (((d * d) !== n)) {
                s = (s + cm_floordiv(n, d));
            }
        }
        d = (d + (1n));
    }
    return s;
}

function divisor_sum(n: bigint): bigint {
    return divisor_sum__sum_of_divisors_sqrt_pairs(n);
}

function cm_floordiv(a, b) { const q = a / b; return ((a % b !== 0n) && ((a < 0n) !== (b < 0n))) ? q - 1n : q; }
function cm_floormod(a, b) { const r = a % b; return (r !== 0n && ((r < 0n) !== (b < 0n))) ? r + b : r; }
function int_power__power_square_multiply(base: bigint, exp: bigint): bigint {
    let r: bigint = 0n;
    let x: bigint = 0n;
    let e: bigint = 0n;
    r = (1n);
    x = base;
    e = exp;
    while ((e > (0n))) {
        if ((cm_floormod(e, (2n)) === (1n))) {
            r = (r * x);
        }
        x = (x * x);
        e = cm_floordiv(e, (2n));
    }
    return r;
}

function int_power__original(base: bigint, exp: bigint): bigint {
    let r: bigint = 0n;
    let cm_u: bigint = 0n;
    let cm_it1: bigint = 0n;
    let cm_stop2: bigint = 0n;
    r = (1n);
    cm_it1 = (0n);
    cm_stop2 = exp;
    while ((cm_it1 < cm_stop2)) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + (1n));
        r = (r * base);
    }
    return r;
}

function int_power(base: bigint, exp: bigint): bigint {
    if ((exp >= (0n))) {
        return int_power__power_square_multiply(base, exp);
    }
    return int_power__original(base, exp);
}

function cm_floormod(a, b) { const r = a % b; return (r !== 0n && ((r < 0n) !== (b < 0n))) ? r + b : r; }
function is_prime_level__is_prime_wheel_6k(n: bigint): boolean {
    let d: bigint = 0n;
    if ((n < (2n))) {
        return false;
    }
    if ((n < (4n))) {
        return true;
    }
    if (((cm_floormod(n, (2n)) === (0n)) || (cm_floormod(n, (3n)) === (0n)))) {
        return false;
    }
    d = (5n);
    while (((d * d) <= n)) {
        if (((cm_floormod(n, d) === (0n)) || (cm_floormod(n, (d + (2n))) === (0n)))) {
            return false;
        }
        d = (d + (6n));
    }
    return true;
}

function is_prime_level(n: bigint): boolean {
    return is_prime_level__is_prime_wheel_6k(n);
}

function is_texture_size__is_power_of_two_bit_trick(n: bigint): boolean {
    return ((n > (0n)) && ((n & (n - (1n))) === (0n)));
}

function is_texture_size(n: bigint): boolean {
    return is_texture_size__is_power_of_two_bit_trick(n);
}

function cm_floordiv(a, b) { const q = a / b; return ((a % b !== 0n) && ((a < 0n) !== (b < 0n))) ? q - 1n : q; }
function isqrt_slow__isqrt_newton(n: bigint): bigint {
    let x: bigint = 0n;
    let y: bigint = 0n;
    if ((n < (2n))) {
        return n;
    }
    x = n;
    y = cm_floordiv((x + (1n)), (2n));
    while ((y < x)) {
        x = y;
        y = cm_floordiv((x + cm_floordiv(n, x)), (2n));
    }
    return x;
}

function isqrt_slow__original(n: bigint): bigint {
    let r: bigint = 0n;
    r = (0n);
    while ((((r + (1n)) * (r + (1n))) <= n)) {
        r = (r + (1n));
    }
    return r;
}

function isqrt_slow(n: bigint): bigint {
    if ((n >= (0n))) {
        return isqrt_slow__isqrt_newton(n);
    }
    return isqrt_slow__original(n);
}

function cm_gcd(a, b) { a = a < 0n ? -a : a; b = b < 0n ? -b : b; while (b !== 0n) { const t = a % b; a = b; b = t; } return a; }
function reduce_ratio__gcd_builtin(a: bigint, b: bigint): bigint {
    return cm_gcd(a, b);
}

function reduce_ratio(a: bigint, b: bigint): bigint {
    return reduce_ratio__gcd_builtin(a, b);
}

function set_bits__popcount_kernighan(flags: bigint): bigint {
    let c: bigint = 0n;
    c = (0n);
    while ((flags !== (0n))) {
        flags = (flags & (flags - (1n)));
        c = (c + (1n));
    }
    return c;
}

function set_bits__original(flags: bigint): bigint {
    let c: bigint = 0n;
    c = (0n);
    while ((flags !== (0n))) {
        c = (c + (flags & (1n)));
        flags = (flags >> (1n));
    }
    return c;
}

function set_bits(flags: bigint): bigint {
    if ((flags >= (0n))) {
        return set_bits__popcount_kernighan(flags);
    }
    return set_bits__original(flags);
}

function cm_floordiv(a, b) { const q = a / b; return ((a % b !== 0n) && ((a < 0n) !== (b < 0n))) ? q - 1n : q; }
function total_points__sum_1_to_n_closed_form(n: bigint): bigint {
    if ((n <= (0n))) {
        return (0n);
    }
    return cm_floordiv((n * (n + (1n))), (2n));
}

function total_points(n: bigint): bigint {
    return total_points__sum_1_to_n_closed_form(n);
}

function wave_size__fibonacci_iterative(n: bigint): bigint {
    let a: bigint = 0n;
    let b: bigint = 0n;
    let cm_u: bigint = 0n;
    let cm_it1: bigint = 0n;
    let cm_stop2: bigint = 0n;
    let cm_t3: bigint = 0n;
    let cm_t4: bigint = 0n;
    a = (0n);
    b = (1n);
    cm_it1 = (0n);
    cm_stop2 = n;
    while ((cm_it1 < cm_stop2)) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + (1n));
        cm_t3 = b;
        cm_t4 = (a + b);
        a = cm_t3;
        b = cm_t4;
    }
    return a;
}

function wave_size__original(n: bigint): bigint {
    if ((n < (2n))) {
        return n;
    }
    return (wave_size((n - (1n))) + wave_size((n - (2n))));
}

function wave_size(n: bigint): bigint {
    if ((n >= (0n))) {
        return wave_size__fibonacci_iterative(n);
    }
    return wave_size__original(n);
}
