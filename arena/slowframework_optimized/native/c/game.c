#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1; return q; }
static int64_t combo_bonus__sum_1_to_n_closed_form(int64_t hits) {
    if ((hits <= INT64_C(0))) {
        return INT64_C(0);
    }
    return cm_floordiv((hits * (hits + INT64_C(1))), INT64_C(2));
}

static int64_t combo_bonus(int64_t hits) {
    return (INT64_C(5) * combo_bonus__sum_1_to_n_closed_form(hits));
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t damage(int64_t attack, int64_t defense, bool crit) {
    int64_t base = 0;
    base = (((attack * INT64_C(2)) + INT64_C(0)) - defense);
    if ((base < INT64_C(1))) {
        base = INT64_C(1);
    }
    if (crit) {
        return (base * INT64_C(2));
    }
    return base;
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t distance_sq(int64_t x1, int64_t y1, int64_t x2, int64_t y2) {
    return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)));
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static bool in_range(int64_t x1, int64_t y1, int64_t x2, int64_t y2, int64_t radius) {
    return (distance_sq(x1, y1, x2, y2) <= (radius * radius));
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static double lerp(double a, double b, double t) {
    return (a + ((b - a) * t));
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floordiv(int64_t a, int64_t b) { int64_t q = a / b; if ((a % b != 0) && ((a < 0) != (b < 0))) q -= 1; return q; }
static int64_t xp_for_level__sum_of_squares_closed_form(int64_t level) {
    if ((level <= INT64_C(0))) {
        return INT64_C(0);
    }
    return cm_floordiv(((level * (level + INT64_C(1))) * ((INT64_C(2) * level) + INT64_C(1))), INT64_C(6));
}

static int64_t xp_for_level(int64_t level) {
    return (INT64_C(10) * xp_for_level__sum_of_squares_closed_form(level));
}

static int64_t level_from_xp(int64_t xp) {
    int64_t level = 0;
    level = INT64_C(0);
    while ((xp_for_level((level + INT64_C(1))) <= xp)) {
        level = (level + INT64_C(1));
    }
    return level;
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_floormod(int64_t a, int64_t b) { int64_t r = a % b; if (r != 0 && ((r < 0) != (b < 0))) r += b; return r; }
static int64_t next_seed(int64_t seed) {
    return cm_floormod(((seed * INT64_C(1103515245)) + INT64_C(12345)), INT64_C(2147483648));
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t tiles_in_circle(int64_t r) {
    int64_t count = 0;
    int64_t x = 0;
    int64_t cm_it1 = 0;
    int64_t cm_stop2 = 0;
    int64_t y = 0;
    int64_t cm_it3 = 0;
    int64_t cm_stop4 = 0;
    count = INT64_C(0);
    cm_it1 = (-r);
    cm_stop2 = (r + INT64_C(1));
    while ((cm_it1 < cm_stop2)) {
        x = cm_it1;
        cm_it1 = (cm_it1 + INT64_C(1));
        cm_it3 = (-r);
        cm_stop4 = (r + INT64_C(1));
        while ((cm_it3 < cm_stop4)) {
            y = cm_it3;
            cm_it3 = (cm_it3 + INT64_C(1));
            if ((((x * x) + (y * y)) <= (r * r))) {
                count = (count + INT64_C(1));
            }
        }
    }
    return count;
}

#include <stdint.h>
#include <stdbool.h>
#include <math.h>

static int64_t cm_ipow(int64_t a, int64_t b) { int64_t r = 1; while (b > 0) { if (b & 1) r *= a; b >>= 1; if (b) a *= a; } return r; }
static int64_t trajectory_y(int64_t a, int64_t b, int64_t c, int64_t d, int64_t t) {
    return ((((a * cm_ipow(t, INT64_C(3))) + (b * cm_ipow(t, INT64_C(2)))) + (c * t)) + d);
}
