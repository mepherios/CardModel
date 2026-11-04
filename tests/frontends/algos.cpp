#include <cstdint>
#include <cmath>
#include <algorithm>

static std::int64_t gcd(std::int64_t a, std::int64_t b) {
    while (b) {
        auto t = a % b;
        a = b;
        b = t;
    }
    return std::abs(a);
}

int64_t clamp3(int64_t x, int64_t lo, int64_t hi) {
    return std::max(lo, std::min(x, hi));
}

double mean(double a, double b, int n) {
    return (a + b) / static_cast<double>(n);
}

long long tri(long long n) {
    long long s = 0;
    for (long long i = 0; i < n; i++) s += i;
    return s;
}
