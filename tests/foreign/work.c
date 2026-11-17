/* Self-written sample: a compute workload whose size is argv[1] (sieve, a small matrix product, a hash over a
 * buffer), for speed measurements of the foreign program against the same source built for this computer. */
#include "sys.h"

typedef unsigned int u32;
static unsigned char sieve[200000];
static u32 ma[24][24], mb[24][24], mc[24][24];

static long parse(const char *s) { long v = 0; while (*s >= '0' && *s <= '9') v = v * 10 + (*s++ - '0'); return v; }

int main(int argc, char **argv) {
    long rounds = argc > 1 ? parse(argv[1]) : 1;
    u32 h = 2166136261u;
    for (long r = 0; r < rounds; r++) {
        int n = 200000, count = 0;
        for (int i = 0; i < n; i++) sieve[i] = 1;
        for (int i = 2; i * i < n; i++) if (sieve[i]) for (int j = i * i; j < n; j += i) sieve[j] = 0;
        for (int i = 2; i < n; i++) count += sieve[i];
        for (int i = 0; i < 24; i++) for (int j = 0; j < 24; j++) { ma[i][j] = (u32)(i * 31 + j + r); mb[i][j] = (u32)(j * 17 - i); }
        for (int i = 0; i < 24; i++) for (int j = 0; j < 24; j++) {
            u32 s = 0;
            for (int k = 0; k < 24; k++) s += ma[i][k] * mb[k][j];
            mc[i][j] = s;
        }
        for (int i = 0; i < 24; i++) for (int j = 0; j < 24; j++) { h ^= mc[i][j]; h *= 16777619u; }
        h ^= (u32)count;
        h *= 16777619u;
    }
    out("work "); out_x(h); out("\n");
    return 0;
}
