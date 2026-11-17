/* Self-written sample: a system call the os card does not model answers ENOSYS (89 on MIPS) and is counted. */
#include "sys.h"
int main(int argc, char **argv) {
    long r = sys3(4999 + 0 * argc, 0, 0, 0);
    out("result "); out_i(r); out("\n");
    return 0;
}
