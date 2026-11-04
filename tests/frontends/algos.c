#include <stdint.h>
#include <stdbool.h>
#include <math.h>

/* Euclid on C's truncating % */
int64_t gcd(int64_t a, int64_t b) {
    while (b != 0) {
        int64_t t = a % b;
        a = b;
        b = t;
    }
    return a < 0 ? -a : a;
}

long collatz(long n) {
    long steps = 0;
    while (n > 1) {
        if (n % 2 == 0) n /= 2;
        else n = 3 * n + 1;
        steps++;
    }
    return steps;
}

int64_t div_sum(int64_t a, int64_t b) {
    if (b == 0) return 0;
    return a / b + a % b;          // truncation toward zero, remainder with the sign of a
}

double harmonic_skip3(int n) {
    double s = 0;
    for (int i = 1; i <= n; i++) {
        if (i % 3 == 0) continue;
        s += 1.0 / i;
    }
    return s;
}

bool is_prime(int64_t n) {
    if (n < 2) return false;
    for (int64_t i = 2; i * i <= n; ++i)
        if (!(n % i)) return false;
    return true;
}

int64_t fib(int64_t n) {
    return n < 2 ? n : fib(n - 1) + fib(n - 2);
}

int64_t bits(int64_t x) {
    int64_t c = 0;
    x &= 0xFFFF;
    do {
        c += x & 1;
        x >>= 1;
    } while (x);
    return c;
}

double hyp_pow(double a, double b) {
    return sqrt(a * a + b * b) + fabs(a) * pow(2.0, 3);
}

int main(void) { return 0; }
