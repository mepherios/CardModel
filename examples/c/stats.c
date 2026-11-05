/* Arrays: a pointer or array parameter with its length is a list the function reads; a local array is a list. */
#include <stdint.h>

int64_t sum(const int64_t *xs, int64_t n) {
    int64_t s = 0;
    for (int64_t i = 0; i < n; i++) s += xs[i];
    return s;
}

int64_t max_of(const int64_t xs[], int64_t n) {
    int64_t m = xs[0];
    for (int64_t i = 1; i < n; i++)
        if (xs[i] > m) m = xs[i];
    return m;
}

double mean(const double *xs, int n) {
    if (n == 0) return 0.0;
    double s = 0;
    for (int i = 0; i < n; i++) s += xs[i];
    return s / n;
}

int64_t dot(const int64_t *a, const int64_t *b, int64_t n) {
    int64_t s = 0;
    for (int64_t i = 0; i < n; i++) s += a[i] * b[i];
    return s;
}

/* the best prefix sum, through a local array */
int64_t best_prefix(const int64_t *xs, int64_t n) {
    int64_t acc[64];
    int64_t best = 0;
    if (n > 64) return -1;
    for (int64_t i = 0; i < n; i++) {
        acc[i] = (i ? acc[i - 1] : 0) + xs[i];
        if (acc[i] > best) best = acc[i];
    }
    return best;
}

int64_t distinct_small(const int *xs, int n) {
    int seen[101] = {0};
    int64_t c = 0;
    for (int i = 0; i < n; i++) {
        int v = xs[i] < 0 ? -xs[i] : xs[i];
        if (v > 100) v = 100;
        if (!seen[v]) {
            seen[v] = 1;
            c++;
        }
    }
    return c;
}

int64_t horner(int64_t x) {
    int64_t c[] = {3, -2, 0, 5};
    int64_t r = 0;
    for (int i = 3; i >= 0; i--) r = r * x + c[i];
    return r;
}
