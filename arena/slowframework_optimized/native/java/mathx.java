public class CardModule {
    static long checksum_pow__modpow_square_multiply(long a, long b, long m) {
    long r = 0L;
    long x = 0L;
    long e = 0L;
    r = Math.floorMod((1L), m);
    x = Math.floorMod(a, m);
    e = b;
    while ((e > (0L))) {
        if ((Math.floorMod(e, (2L)) == (1L))) {
            r = Math.floorMod((r * x), m);
        }
        x = Math.floorMod((x * x), m);
        e = Math.floorDiv(e, (2L));
    }
    return r;
    }

    static long checksum_pow__original(long a, long b, long m) {
    long r = 0L;
    long cm_u = 0L;
    long cm_it1 = 0L;
    long cm_stop2 = 0L;
    r = Math.floorMod((1L), m);
    cm_it1 = (0L);
    cm_stop2 = b;
    while ((cm_it1 < cm_stop2)) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + (1L));
        r = Math.floorMod((r * a), m);
    }
    return r;
    }

    static long checksum_pow(long a, long b, long m) {
    if (((b >= (0L)) && (m >= (1L)))) {
        return checksum_pow__modpow_square_multiply(a, b, m);
    }
    return checksum_pow__original(a, b, m);
    }
}

public class CardModule {
    static long choose__binomial_multiplicative(long n, long k) {
    long c = 0L;
    long i = 0L;
    long cm_it1 = 0L;
    long cm_stop2 = 0L;
    if (((k < (0L)) || (k > n))) {
        return (0L);
    }
    k = Math.min(k, (n - k));
    c = (1L);
    cm_it1 = (0L);
    cm_stop2 = k;
    while ((cm_it1 < cm_stop2)) {
        i = cm_it1;
        cm_it1 = (cm_it1 + (1L));
        c = Math.floorDiv((c * (n - i)), (i + (1L)));
    }
    return c;
    }

    static long choose__original(long n, long k) {
    long a = 0L;
    long i = 0L;
    long cm_it1 = 0L;
    long cm_stop2 = 0L;
    long b = 0L;
    long cm_it3 = 0L;
    long cm_stop4 = 0L;
    long c = 0L;
    long cm_it5 = 0L;
    long cm_stop6 = 0L;
    if (((k < (0L)) || (k > n))) {
        return (0L);
    }
    a = (1L);
    cm_it1 = (2L);
    cm_stop2 = (n + (1L));
    while ((cm_it1 < cm_stop2)) {
        i = cm_it1;
        cm_it1 = (cm_it1 + (1L));
        a = (a * i);
    }
    b = (1L);
    cm_it3 = (2L);
    cm_stop4 = (k + (1L));
    while ((cm_it3 < cm_stop4)) {
        i = cm_it3;
        cm_it3 = (cm_it3 + (1L));
        b = (b * i);
    }
    c = (1L);
    cm_it5 = (2L);
    cm_stop6 = ((n - k) + (1L));
    while ((cm_it5 < cm_stop6)) {
        i = cm_it5;
        cm_it5 = (cm_it5 + (1L));
        c = (c * i);
    }
    return Math.floorDiv(a, (b * c));
    }

    static long choose(long n, long k) {
    if ((n >= (0L))) {
        return choose__binomial_multiplicative(n, k);
    }
    return choose__original(n, k);
    }
}

public class CardModule {
    static long cm_gcd(long a, long b) { a = Math.abs(a); b = Math.abs(b); while (b != 0) { long t = a % b; a = b; b = t; } return a; }
    static long common_period__lcm_via_gcd(long a, long b) {
    a = Math.abs(a);
    b = Math.abs(b);
    if (((a == (0L)) || (b == (0L)))) {
        return (0L);
    }
    return (Math.floorDiv(a, cm_gcd(a, b)) * b);
    }

    static long common_period(long a, long b) {
    return common_period__lcm_via_gcd(a, b);
    }
}

public class CardModule {
    static long digit_root__digital_root_closed_form(long n) {
    n = Math.abs(n);
    if ((n == (0L))) {
        return (0L);
    }
    return ((1L) + Math.floorMod((n - (1L)), (9L)));
    }

    static long digit_root(long n) {
    return digit_root__digital_root_closed_form(n);
    }
}

public class CardModule {
    static long divisor_sum__sum_of_divisors_sqrt_pairs(long n) {
    long s = 0L;
    long d = 0L;
    if ((n <= (0L))) {
        return (0L);
    }
    s = (0L);
    d = (1L);
    while (((d * d) <= n)) {
        if ((Math.floorMod(n, d) == (0L))) {
            s = (s + d);
            if (((d * d) != n)) {
                s = (s + Math.floorDiv(n, d));
            }
        }
        d = (d + (1L));
    }
    return s;
    }

    static long divisor_sum(long n) {
    return divisor_sum__sum_of_divisors_sqrt_pairs(n);
    }
}

public class CardModule {
    static long int_power__power_square_multiply(long base, long exp) {
    long r = 0L;
    long x = 0L;
    long e = 0L;
    r = (1L);
    x = base;
    e = exp;
    while ((e > (0L))) {
        if ((Math.floorMod(e, (2L)) == (1L))) {
            r = (r * x);
        }
        x = (x * x);
        e = Math.floorDiv(e, (2L));
    }
    return r;
    }

    static long int_power__original(long base, long exp) {
    long r = 0L;
    long cm_u = 0L;
    long cm_it1 = 0L;
    long cm_stop2 = 0L;
    r = (1L);
    cm_it1 = (0L);
    cm_stop2 = exp;
    while ((cm_it1 < cm_stop2)) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + (1L));
        r = (r * base);
    }
    return r;
    }

    static long int_power(long base, long exp) {
    if ((exp >= (0L))) {
        return int_power__power_square_multiply(base, exp);
    }
    return int_power__original(base, exp);
    }
}

public class CardModule {
    static boolean is_prime_level__is_prime_wheel_6k(long n) {
    long d = 0L;
    if ((n < (2L))) {
        return false;
    }
    if ((n < (4L))) {
        return true;
    }
    if (((Math.floorMod(n, (2L)) == (0L)) || (Math.floorMod(n, (3L)) == (0L)))) {
        return false;
    }
    d = (5L);
    while (((d * d) <= n)) {
        if (((Math.floorMod(n, d) == (0L)) || (Math.floorMod(n, (d + (2L))) == (0L)))) {
            return false;
        }
        d = (d + (6L));
    }
    return true;
    }

    static boolean is_prime_level(long n) {
    return is_prime_level__is_prime_wheel_6k(n);
    }
}

public class CardModule {
    static boolean is_texture_size__is_power_of_two_bit_trick(long n) {
    return ((n > (0L)) && ((n & (n - (1L))) == (0L)));
    }

    static boolean is_texture_size(long n) {
    return is_texture_size__is_power_of_two_bit_trick(n);
    }
}

public class CardModule {
    static long isqrt_slow__isqrt_newton(long n) {
    long x = 0L;
    long y = 0L;
    if ((n < (2L))) {
        return n;
    }
    x = n;
    y = Math.floorDiv((x + (1L)), (2L));
    while ((y < x)) {
        x = y;
        y = Math.floorDiv((x + Math.floorDiv(n, x)), (2L));
    }
    return x;
    }

    static long isqrt_slow__original(long n) {
    long r = 0L;
    r = (0L);
    while ((((r + (1L)) * (r + (1L))) <= n)) {
        r = (r + (1L));
    }
    return r;
    }

    static long isqrt_slow(long n) {
    if ((n >= (0L))) {
        return isqrt_slow__isqrt_newton(n);
    }
    return isqrt_slow__original(n);
    }
}

public class CardModule {
    static long cm_gcd(long a, long b) { a = Math.abs(a); b = Math.abs(b); while (b != 0) { long t = a % b; a = b; b = t; } return a; }
    static long reduce_ratio__gcd_builtin(long a, long b) {
    return cm_gcd(a, b);
    }

    static long reduce_ratio(long a, long b) {
    return reduce_ratio__gcd_builtin(a, b);
    }
}

public class CardModule {
    static long set_bits__popcount_kernighan(long flags) {
    long c = 0L;
    c = (0L);
    while ((flags != (0L))) {
        flags = (flags & (flags - (1L)));
        c = (c + (1L));
    }
    return c;
    }

    static long set_bits__original(long flags) {
    long c = 0L;
    c = (0L);
    while ((flags != (0L))) {
        c = (c + (flags & (1L)));
        flags = (flags >> (1L));
    }
    return c;
    }

    static long set_bits(long flags) {
    if ((flags >= (0L))) {
        return set_bits__popcount_kernighan(flags);
    }
    return set_bits__original(flags);
    }
}

public class CardModule {
    static long total_points__sum_1_to_n_closed_form(long n) {
    if ((n <= (0L))) {
        return (0L);
    }
    return Math.floorDiv((n * (n + (1L))), (2L));
    }

    static long total_points(long n) {
    return total_points__sum_1_to_n_closed_form(n);
    }
}

public class CardModule {
    static long wave_size__fibonacci_iterative(long n) {
    long a = 0L;
    long b = 0L;
    long cm_u = 0L;
    long cm_it1 = 0L;
    long cm_stop2 = 0L;
    long cm_t3 = 0L;
    long cm_t4 = 0L;
    a = (0L);
    b = (1L);
    cm_it1 = (0L);
    cm_stop2 = n;
    while ((cm_it1 < cm_stop2)) {
        cm_u = cm_it1;
        cm_it1 = (cm_it1 + (1L));
        cm_t3 = b;
        cm_t4 = (a + b);
        a = cm_t3;
        b = cm_t4;
    }
    return a;
    }

    static long wave_size__original(long n) {
    if ((n < (2L))) {
        return n;
    }
    return (wave_size((n - (1L))) + wave_size((n - (2L))));
    }

    static long wave_size(long n) {
    if ((n >= (0L))) {
        return wave_size__fibonacci_iterative(n);
    }
    return wave_size__original(n);
    }
}
