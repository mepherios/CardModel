using System;

public static class Algos {
    public static long Gcd(long a, long b) {
        while (b != 0) {
            var t = a % b;
            a = b;
            b = t;
        }
        return Math.Abs(a);
    }

    static double Area(double r) {
        return Math.PI * r * r;
    }
}
