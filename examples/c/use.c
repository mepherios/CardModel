/* Calls into the other files resolve as a linker resolves them (lift_project). */
#include <stdint.h>

uint32_t xorshift32(uint32_t x);
int64_t sum(const int64_t *xs, int64_t n);

uint32_t xorshift_n(uint32_t x, int n) {
    for (int i = 0; i < n; i++) x = xorshift32(x);
    return x;
}

int64_t centred_sum(const int64_t *xs, int64_t n, int64_t c) {
    return sum(xs, n) - c * n;
}
