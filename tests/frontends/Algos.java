package demo;

import java.util.List;

public class Algos {
    static long gcd(long a, long b) {
        while (b != 0) {
            long t = a % b;
            a = b;
            b = t;
        }
        return Math.abs(a);
    }

    public static long collatz(long n) {
        long steps = 0;
        while (n > 1) {
            n = (n % 2 == 0) ? n / 2 : 3 * n + 1;
            steps += 1;
        }
        return steps;
    }

    static int floorPair(int a, int b) {
        if (b == 0) return 0;
        return Math.floorDiv(a, b) * 1000 + Math.floorMod(a, b);
    }

    static boolean even(long n) {
        return n % 2 == 0;
    }

    static double avg(long a, long b) {
        return (a + b) / 2.0;
    }

    public static void main(String[] args) {
        System.out.println(gcd(12, 18));
    }
}
