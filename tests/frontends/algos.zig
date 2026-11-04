const std = @import("std");

fn gcd(a0: i64, b0: i64) i64 {
    var a = a0;
    var b = b0;
    while (b != 0) {
        const t = @rem(a, b);
        a = b;
        b = t;
    }
    return if (a < 0) -a else a;
}

pub fn triangle(n: i64) i64 {
    var s: i64 = 0;
    var i: i64 = 0;
    while (i < n) : (i += 1) {
        s += i;
    }
    return s;
}

fn floorMix(a: i64, b: i64) i64 {
    return @divFloor(a, b) + @mod(a, b) + @divTrunc(a, b);
}
