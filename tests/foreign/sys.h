#ifndef CM_SYS_H
#define CM_SYS_H
#if defined(__mips__)
#define SYS_EXIT 4001
#define SYS_READ 4003
#define SYS_WRITE 4004
#define SYS_BRK 4045
#else
#define SYS_EXIT 1
#define SYS_READ 2
#define SYS_WRITE 3
#define SYS_BRK 4
#endif
long sys3(long n, long a, long b, long c);
void out(const char *s);
void out_u(unsigned long v);
void out_i(long v);
void out_x(unsigned long v);
#endif
