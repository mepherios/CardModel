/* Self-written sample: writes outside the process's memory; the machine must stop with an address error. */
#include "sys.h"
int main(int argc, char **argv) {
    out("before\n");
    volatile int *p = (volatile int *)0x7FFFFFF0;
    *p = 1;
    out("after\n");
    return 0;
}
