/* Fixed-width C: hashes and checksums that rely on unsigned wrap-around (lifted with WRAPU / WRAPS). */
#include <stdint.h>
#include <stdbool.h>

uint32_t xorshift32(uint32_t x) {
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    return x;
}

/* FNV-1a over the eight bytes of v, low byte first */
uint32_t fnv1a64(int64_t v) {
    uint32_t h = 2166136261u;
    for (int i = 0; i < 8; i++) {
        h ^= (uint8_t)(v >> (8 * i));
        h *= 16777619u;
    }
    return h;
}

/* CRC-32 (IEEE, reflected) of a byte buffer */
uint32_t crc32(const uint8_t *buf, int n) {
    uint32_t c = 0xFFFFFFFFu;
    for (int i = 0; i < n; i++) {
        c ^= buf[i];
        for (int k = 0; k < 8; k++)
            c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return ~c;
}

uint32_t adler32(const uint8_t *buf, int n) {
    uint32_t a = 1, b = 0;
    for (int i = 0; i < n; i++) {
        a = (a + buf[i]) % 65521;
        b = (b + a) % 65521;
    }
    return (b << 16) | a;
}

uint16_t rotl16(uint16_t x, int k) {
    k &= 15;
    return (uint16_t)((x << k) | (x >> (16 - k)));
}

uint8_t add_u8(uint8_t a, uint8_t b) { return a + b; }

int8_t to_i8(int x) { return (int8_t)x; }

int16_t sum_i16(int16_t a, int16_t b) {
    int16_t s = a;
    s += b;
    return s;
}

/* the usual arithmetic conversions: -1 < 1u is false in C */
bool lt_mixed(int a, unsigned b) { return a < b; }

int64_t div_mixed(int a, unsigned b) {
    if (b == 0) return 0;
    return a / b;
}

unsigned scramble(int n) {
    unsigned s = 0;
    for (int i = 1; i <= n; i++)
        s = (s << 3) ^ (s >> 29) ^ (unsigned)(i * 2654435761u);
    return s;
}
