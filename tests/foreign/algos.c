/* Self-written sample program for the foreign-platform tests: integer work that touches most of the MIPS
 * instruction cards (multiply, divide, shifts, byte and halfword memory, unaligned struct fields, recursion,
 * function pointers, switch tables) and prints what it computed. The same source built for this computer must
 * print the same thing. */
#include "sys.h"

typedef unsigned int u32;

static u32 crc32(const unsigned char *p, int n) {
    u32 c = 0xFFFFFFFFu;
    for (int i = 0; i < n; i++) {
        c ^= p[i];
        for (int k = 0; k < 8; k++) c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1)));
    }
    return ~c;
}

static int fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }

static void sort(int *a, int n) {
    for (int i = 1; i < n; i++) {
        int v = a[i], j = i - 1;
        while (j >= 0 && a[j] > v) { a[j + 1] = a[j]; j--; }
        a[j + 1] = v;
    }
}

static long long mulmod(long long a, long long b, long long m) { return (a * b) % m; }

static int is_prime(u32 n) {
    if (n < 2) return 0;
    for (u32 d = 2; d * d <= n; d++) if (n % d == 0) return 0;
    return 1;
}

static int op_add(int a, int b) { return a + b; }
static int op_sub(int a, int b) { return a - b; }
static int op_mul(int a, int b) { return a * b; }
static int op_div(int a, int b) { return b ? a / b : 0; }

static const char *name_of(int k) {
    switch (k) {
    case 0: return "zero"; case 1: return "one"; case 2: return "two"; case 3: return "three";
    case 4: return "four"; case 5: return "five"; case 6: return "six"; default: return "many";
    }
}

struct __attribute__((packed)) rec { char tag; int value; short small; };

static unsigned char heap_area[4096];

int main(int argc, char **argv) {
    out("argc "); out_i(argc); out("\n");
    if (argc > 1) { out("argv[1] "); out(argv[1]); out("\n"); }
    const char *msg = "The quick brown fox jumps over the lazy dog";
    int n = 0;
    while (msg[n]) n++;
    out("crc32 "); out_x(crc32((const unsigned char *)msg, n)); out("\n");
    out("fib(20) "); out_i(fib(20)); out("\n");
    int a[16];
    u32 s = 12345;
    for (int i = 0; i < 16; i++) { s = s * 1103515245u + 12345u; a[i] = (int)(s >> 16) % 1000 - 500; }
    sort(a, 16);
    out("sorted");
    for (int i = 0; i < 16; i++) { out(" "); out_i(a[i]); }
    out("\n");
    long long x = 1;
    for (int i = 0; i < 40; i++) x = mulmod(x, 1234567891LL, 998244353LL);
    out("mulmod "); out_i((long)x); out("\n");
    int primes = 0;
    for (u32 i = 0; i < 2000; i++) primes += is_prime(i);
    out("primes<2000 "); out_i(primes); out("\n");
    int (*ops[4])(int, int) = {op_add, op_sub, op_mul, op_div};
    int acc = 7;
    for (int i = 0; i < 12; i++) acc = ops[i & 3](acc, i + 3);
    out("ops "); out_i(acc); out("\n");
    for (int k = 0; k < 9; k += 2) { out(name_of(k)); out(k < 8 ? "," : "\n"); }
    struct rec r[3];
    for (int i = 0; i < 3; i++) { r[i].tag = (char)('a' + i); r[i].value = -1000 * (i + 1) + i; r[i].small = (short)(-7 * i); }
    long sum = 0;
    for (int i = 0; i < 3; i++) sum += r[i].tag + r[i].value + r[i].small;
    out("packed "); out_i(sum); out("\n");
    for (int i = 0; i < 4096; i++) heap_area[i] = (unsigned char)(i * 7);
    out("bytes "); out_x(crc32(heap_area, 4096)); out("\n");
    int sd = -17, dv = 5;
    out("divmod "); out_i(sd / dv); out(" "); out_i(sd % dv); out(" "); out_u((u32)sd / (u32)dv); out("\n");
    u32 sh = 0x80000001u;
    out("shifts "); out_x(sh >> 3); out(" "); out_x((u32)((int)sh >> 3)); out(" "); out_x(sh << 5); out("\n");
    char line[64];
    long got = sys3(SYS_READ, 0, (long)line, 63);
    if (got > 0) { line[got] = 0; out("read "); out(line); }
    return 3;
}
