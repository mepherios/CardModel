public class CardModule {
    static long combo_bonus__sum_1_to_n_closed_form(long hits) {
    if ((hits <= (0L))) {
        return (0L);
    }
    return Math.floorDiv((hits * (hits + (1L))), (2L));
    }

    static long combo_bonus(long hits) {
    return ((5L) * combo_bonus__sum_1_to_n_closed_form(hits));
    }
}

public class CardModule {
    static long damage(long attack, long defense, boolean crit) {
    long base = 0L;
    base = (((attack * (2L)) + (0L)) - defense);
    if ((base < (1L))) {
        base = (1L);
    }
    if (crit) {
        return (base * (2L));
    }
    return base;
    }
}

public class CardModule {
    static long distance_sq(long x1, long y1, long x2, long y2) {
    return (((x2 - x1) * (x2 - x1)) + ((y2 - y1) * (y2 - y1)));
    }
}

public class CardModule {
    static boolean in_range(long x1, long y1, long x2, long y2, long radius) {
    return (distance_sq(x1, y1, x2, y2) <= (radius * radius));
    }
}

public class CardModule {
    static double lerp(double a, double b, double t) {
    return (a + ((b - a) * t));
    }
}

public class CardModule {
    static long xp_for_level__sum_of_squares_closed_form(long level) {
    if ((level <= (0L))) {
        return (0L);
    }
    return Math.floorDiv(((level * (level + (1L))) * (((2L) * level) + (1L))), (6L));
    }

    static long xp_for_level(long level) {
    return ((10L) * xp_for_level__sum_of_squares_closed_form(level));
    }

    static long level_from_xp(long xp) {
    long level = 0L;
    level = (0L);
    while ((xp_for_level((level + (1L))) <= xp)) {
        level = (level + (1L));
    }
    return level;
    }
}

public class CardModule {
    static long next_seed(long seed) {
    return Math.floorMod(((seed * (1103515245L)) + (12345L)), (2147483648L));
    }
}

public class CardModule {
    static long tiles_in_circle(long r) {
    long count = 0L;
    long x = 0L;
    long cm_it1 = 0L;
    long cm_stop2 = 0L;
    long y = 0L;
    long cm_it3 = 0L;
    long cm_stop4 = 0L;
    count = (0L);
    cm_it1 = (-r);
    cm_stop2 = (r + (1L));
    while ((cm_it1 < cm_stop2)) {
        x = cm_it1;
        cm_it1 = (cm_it1 + (1L));
        cm_it3 = (-r);
        cm_stop4 = (r + (1L));
        while ((cm_it3 < cm_stop4)) {
            y = cm_it3;
            cm_it3 = (cm_it3 + (1L));
            if ((((x * x) + (y * y)) <= (r * r))) {
                count = (count + (1L));
            }
        }
    }
    return count;
    }
}

public class CardModule {
    static long cm_ipow(long a, long b) { long r = 1; while (b > 0) { if ((b & 1) == 1) r *= a; b >>= 1; if (b > 0) a *= a; } return r; }
    static long trajectory_y(long a, long b, long c, long d, long t) {
    return ((((a * cm_ipow(t, (3L))) + (b * cm_ipow(t, (2L)))) + (c * t)) + d);
    }
}
