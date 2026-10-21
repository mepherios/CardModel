#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1; return q; }
static int64_t cm_floormod(int64_t a, int64_t b) { int64_t r = a % b; if (r != 0 && ((r < 0) != (b < 0))) r += b; return r; }
static int64_t checksum_pow__modpow_square_multiply(int64_t a, int64_t b, int64_t m) {
    int64_t r = 0;
    int64_t x = 0;
    int64_t e = 0;
    r = cm_floormod(INT64_C(1), m);
    x = cm_floormod(a, m);
    e = b;
    while ((e > INT64_C(0))) {
        if ((cm_floormod(e, INT64_C(2)) == INT64_C(1))) {
            r = cm_floormod((r * x), m);
        }
        x = cm_floormod((x * x), m);
        e = cm_floordiv(e, INT64_C(2));
    }
    return r;
}

static int64_t checksum_pow__original(int64_t a, int64_t b, int64_t m) {
    int64_t r = 0;
    int64_t cm_u = 0;
    int64_t cm_it1 = 0;
    int64_t cm_stop2 = 0;
    r = cm_floormod(INT64_C(1), m);
    cm_it1 = INT64_C(0);
    cm_stop2 = b;
    while ((cm_it1 < cm_stop2)) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + INT64_C(1));
        r = cm_floormod((r * a), m);
    }
    return r;
}

static int64_t checksum_pow(int64_t a, int64_t b, int64_t m) {
    if (((b >= INT64_C(0)) && (m >= INT64_C(1)))) {
        return checksum_pow__modpow_square_multiply(a, b, m);
    }
    return checksum_pow__original(a, b, m);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1; return q; }
static int64_t cm_min_i(int64_t a, int64_t b) { return b < a ? b : a; }
static int64_t choose__binomial_multiplicative(int64_t n, int64_t k) {
    int64_t c = 0;
    int64_t i = 0;
    int64_t cm_it1 = 0;
    int64_t cm_stop2 = 0;
    if (((k < INT64_C(0)) || (k > n))) {
        return INT64_C(0);
    }
    k = cm_min_i(k, (n - k));
    c = INT64_C(1);
    cm_it1 = INT64_C(0);
    cm_stop2 = k;
    while ((cm_it1 < cm_stop2)) {
        i = cm_it1;
        cm_it1 = (cm_it1 + INT64_C(1));
        c = cm_floordiv((c * (n - i)), (i + INT64_C(1)));
    }
    return c;
}

static int64_t choose__original(int64_t n, int64_t k) {
    int64_t a = 0;
    int64_t i = 0;
    int64_t cm_it1 = 0;
    int64_t cm_stop2 = 0;
    int64_t b = 0;
    int64_t cm_it3 = 0;
    int64_t cm_stop4 = 0;
    int64_t c = 0;
    int64_t cm_it5 = 0;
    int64_t cm_stop6 = 0;
    if (((k < INT64_C(0)) || (k > n))) {
        return INT64_C(0);
    }
    a = INT64_C(1);
    cm_it1 = INT64_C(2);
    cm_stop2 = (n + INT64_C(1));
    while ((cm_it1 < cm_stop2)) {
        i = cm_it1;
        cm_it1 = (cm_it1 + INT64_C(1));
        a = (a * i);
    }
    b = INT64_C(1);
    cm_it3 = INT64_C(2);
    cm_stop4 = (k + INT64_C(1));
    while ((cm_it3 < cm_stop4)) {
        i = cm_it3;
        cm_it3 = (cm_it3 + INT64_C(1));
        b = (b * i);
    }
    c = INT64_C(1);
    cm_it5 = INT64_C(2);
    cm_stop6 = ((n - k) + INT64_C(1));
    while ((cm_it5 < cm_stop6)) {
        i = cm_it5;
        cm_it5 = (cm_it5 + INT64_C(1));
        c = (c * i);
    }
    return cm_floordiv(a, (b * c));
}

static int64_t choose(int64_t n, int64_t k) {
    if ((n >= INT64_C(0))) {
        return choose__binomial_multiplicative(n, k);
    }
    return choose__original(n, k);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_abs_i(int64_t a) { return a < 0 ? -a : a; }
static int64_t cm_floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1; return q; }
static int64_t cm_gcd(int64_t a, int64_t b) { a = a < 0 ? -a : a; b = b < 0 ? -b : b; while (b != 0) { int64_t t = a % b; a = b; b = t; } return a; }
static int64_t common_period__lcm_via_gcd(int64_t a, int64_t b) {
    a = cm_abs_i(a);
    b = cm_abs_i(b);
    if (((a == INT64_C(0)) || (b == INT64_C(0)))) {
        return INT64_C(0);
    }
    return (cm_floordiv(a, cm_gcd(a, b)) * b);
}

static int64_t common_period(int64_t a, int64_t b) {
    return common_period__lcm_via_gcd(a, b);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_abs_i(int64_t a) { return a < 0 ? -a : a; }
static int64_t cm_floormod(int64_t a, int64_t b) { int64_t r = a % b; if (r != 0 && ((r < 0) != (b < 0))) r += b; return r; }
static int64_t digit_root__digital_root_closed_form(int64_t n) {
    n = cm_abs_i(n);
    if ((n == INT64_C(0))) {
        return INT64_C(0);
    }
    return (INT64_C(1) + cm_floormod((n - INT64_C(1)), INT64_C(9)));
}

static int64_t digit_root(int64_t n) {
    return digit_root__digital_root_closed_form(n);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1; return q; }
static int64_t cm_floormod(int64_t a, int64_t b) { int64_t r = a % b; if (r != 0 && ((r < 0) != (b < 0))) r += b; return r; }
static int64_t divisor_sum__sum_of_divisors_sqrt_pairs(int64_t n) {
    int64_t s = 0;
    int64_t d = 0;
    if ((n <= INT64_C(0))) {
        return INT64_C(0);
    }
    s = INT64_C(0);
    d = INT64_C(1);
    while (((d * d) <= n)) {
        if ((cm_floormod(n, d) == INT64_C(0))) {
            s = (s + d);
            if (((d * d) != n)) {
                s = (s + cm_floordiv(n, d));
            }
        }
        d = (d + INT64_C(1));
    }
    return s;
}

static int64_t divisor_sum(int64_t n) {
    return divisor_sum__sum_of_divisors_sqrt_pairs(n);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1; return q; }
static int64_t cm_floormod(int64_t a, int64_t b) { int64_t r = a % b; if (r != 0 && ((r < 0) != (b < 0))) r += b; return r; }
static int64_t int_power__power_square_multiply(int64_t base, int64_t exp) {
    int64_t r = 0;
    int64_t x = 0;
    int64_t e = 0;
    r = INT64_C(1);
    x = base;
    e = exp;
    while ((e > INT64_C(0))) {
        if ((cm_floormod(e, INT64_C(2)) == INT64_C(1))) {
            r = (r * x);
        }
        x = (x * x);
        e = cm_floordiv(e, INT64_C(2));
    }
    return r;
}

static int64_t int_power__original(int64_t base, int64_t exp) {
    int64_t r = 0;
    int64_t cm_u = 0;
    int64_t cm_it1 = 0;
    int64_t cm_stop2 = 0;
    r = INT64_C(1);
    cm_it1 = INT64_C(0);
    cm_stop2 = exp;
    while ((cm_it1 < cm_stop2)) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + INT64_C(1));
        r = (r * base);
    }
    return r;
}

static int64_t int_power(int64_t base, int64_t exp) {
    if ((exp >= INT64_C(0))) {
        return int_power__power_square_multiply(base, exp);
    }
    return int_power__original(base, exp);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floormod(int64_t a, int64_t b) { int64_t r = a % b; if (r != 0 && ((r < 0) != (b < 0))) r += b; return r; }
static bool is_prime_level__is_prime_wheel_6k(int64_t n) {
    int64_t d = 0;
    if ((n < INT64_C(2))) {
        return false;
    }
    if ((n < INT64_C(4))) {
        return true;
    }
    if (((cm_floormod(n, INT64_C(2)) == INT64_C(0)) || (cm_floormod(n, INT64_C(3)) == INT64_C(0)))) {
        return false;
    }
    d = INT64_C(5);
    while (((d * d) <= n)) {
        if (((cm_floormod(n, d) == INT64_C(0)) || (cm_floormod(n, (d + INT64_C(2))) == INT64_C(0)))) {
            return false;
        }
        d = (d + INT64_C(6));
    }
    return true;
}

static bool is_prime_level(int64_t n) {
    return is_prime_level__is_prime_wheel_6k(n);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static bool is_texture_size__is_power_of_two_bit_trick(int64_t n) {
    return ((n > INT64_C(0)) && ((n & (n - INT64_C(1))) == INT64_C(0)));
}

static bool is_texture_size(int64_t n) {
    return is_texture_size__is_power_of_two_bit_trick(n);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1; return q; }
static int64_t isqrt_slow__isqrt_newton(int64_t n) {
    int64_t x = 0;
    int64_t y = 0;
    if ((n < INT64_C(2))) {
        return n;
    }
    x = n;
    y = cm_floordiv((x + INT64_C(1)), INT64_C(2));
    while ((y < x)) {
        x = y;
        y = cm_floordiv((x + cm_floordiv(n, x)), INT64_C(2));
    }
    return x;
}

static int64_t isqrt_slow__original(int64_t n) {
    int64_t r = 0;
    r = INT64_C(0);
    while ((((r + INT64_C(1)) * (r + INT64_C(1))) <= n)) {
        r = (r + INT64_C(1));
    }
    return r;
}

static int64_t isqrt_slow(int64_t n) {
    if ((n >= INT64_C(0))) {
        return isqrt_slow__isqrt_newton(n);
    }
    return isqrt_slow__original(n);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_gcd(int64_t a, int64_t b) { a = a < 0 ? -a : a; b = b < 0 ? -b : b; while (b != 0) { int64_t t = a % b; a = b; b = t; } return a; }
static int64_t reduce_ratio__gcd_builtin(int64_t a, int64_t b) {
    return cm_gcd(a, b);
}

static int64_t reduce_ratio(int64_t a, int64_t b) {
    return reduce_ratio__gcd_builtin(a, b);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t set_bits__popcount_kernighan(int64_t flags) {
    int64_t c = 0;
    c = INT64_C(0);
    while ((flags != INT64_C(0))) {
        flags = (flags & (flags - INT64_C(1)));
        c = (c + INT64_C(1));
    }
    return c;
}

static int64_t set_bits__original(int64_t flags) {
    int64_t c = 0;
    c = INT64_C(0);
    while ((flags != INT64_C(0))) {
        c = (c + (flags & INT64_C(1)));
        flags = (flags >> INT64_C(1));
    }
    return c;
}

static int64_t set_bits(int64_t flags) {
    if ((flags >= INT64_C(0))) {
        return set_bits__popcount_kernighan(flags);
    }
    return set_bits__original(flags);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1; return q; }
static int64_t total_points__sum_1_to_n_closed_form(int64_t n) {
    if ((n <= INT64_C(0))) {
        return INT64_C(0);
    }
    return cm_floordiv((n * (n + INT64_C(1))), INT64_C(2));
}

static int64_t total_points(int64_t n) {
    return total_points__sum_1_to_n_closed_form(n);
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t wave_size__fibonacci_iterative(int64_t n) {
    int64_t a = 0;
    int64_t b = 0;
    int64_t cm_u = 0;
    int64_t cm_it1 = 0;
    int64_t cm_stop2 = 0;
    int64_t cm_t3 = 0;
    int64_t cm_t4 = 0;
    a = INT64_C(0);
    b = INT64_C(1);
    cm_it1 = INT64_C(0);
    cm_stop2 = n;
    while ((cm_it1 < cm_stop2)) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + INT64_C(1));
        cm_t3 = b;
        cm_t4 = (a + b);
        a = cm_t3;
        b = cm_t4;
    }
    return a;
}

static int64_t wave_size__original(int64_t n) {
    if ((n < INT64_C(2))) {
        return n;
    }
    return (wave_size((n - INT64_C(1))) + wave_size((n - INT64_C(2))));
}

static int64_t wave_size(int64_t n) {
    if ((n >= INT64_C(0))) {
        return wave_size__fibonacci_iterative(n);
    }
    return wave_size__original(n);
}
