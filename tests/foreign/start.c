/* A freestanding start and the few system calls the samples use: Linux o32 on MIPS. Self-written for the card
 * model's tests; no C library. */
#include "sys.h"

int main(int argc, char **argv);

#if defined(__mips__)
long sys3(long n, long a, long b, long c) {
    register long v0 __asm__("$2") = n;
    register long a0 __asm__("$4") = a;
    register long a1 __asm__("$5") = b;
    register long a2 __asm__("$6") = c;
    register long a3 __asm__("$7");
    __asm__ volatile("syscall" : "+r"(v0), "=r"(a3) : "r"(a0), "r"(a1), "r"(a2)
                     : "$1", "$3", "$8", "$9", "$10", "$11", "$12", "$13", "$14", "$15", "$24", "$25", "hi", "lo", "memory");
    return a3 ? -v0 : v0;
}

__asm__(".text\n.globl __start\n.set noreorder\n__start:\n"
        "  lui $28, %hi(_gp)\n  addiu $28, $28, %lo(_gp)\n"
        "  lw $4, 0($29)\n"          /* argc */
        "  addiu $5, $29, 4\n"       /* argv */
        "  addiu $29, $29, -16\n"
        "  jal cm_start\n"
        "  nop\n"
        ".set reorder\n");
#else
#include <unistd.h>
#include <stdlib.h>
long sys3(long n, long a, long b, long c) {
    if (n == SYS_WRITE) return write((int)a, (const void *)b, (size_t)c);
    if (n == SYS_READ) return read((int)a, (void *)b, (size_t)c);
    if (n == SYS_EXIT) exit((int)a);
    return -1;
}
#endif

void cm_start(int argc, char **argv) {
    int r = main(argc, argv);
    sys3(SYS_EXIT, r, 0, 0);
    for (;;) {}
}

void out(const char *s) {
    long n = 0;
    while (s[n]) n++;
    sys3(SYS_WRITE, 1, (long)s, n);
}

void out_u(unsigned long v) {
    char b[24];
    int i = 23;
    b[i] = 0;
    do { b[--i] = (char)('0' + v % 10); v /= 10; } while (v);
    out(b + i);
}

void out_i(long v) {
    if (v < 0) { out("-"); out_u((unsigned long)(-(v + 1)) + 1); } else out_u((unsigned long)v);
}

void out_x(unsigned long v) {
    char b[12];
    int i = 11;
    b[i] = 0;
    do { b[--i] = "0123456789abcdef"[v & 15]; v >>= 4; } while (v);
    out(b + i);
}

/* the compiler may call these for struct copies and zeroing */
void *memcpy(void *d, const void *s, unsigned long n) {
    char *a = d; const char *b = s;
    while (n--) *a++ = *b++;
    return d;
}
void *memset(void *d, int c, unsigned long n) {
    char *a = d;
    while (n--) *a++ = (char)c;
    return d;
}
