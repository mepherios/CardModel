<?php
function gcd(int $a, int $b): int {
    while ($b != 0) {
        $t = $a % $b;
        $a = $b;
        $b = $t;
    }
    return abs($a);
}

function collatz($n) {
    $steps = 0;
    while ($n > 1) {
        if ($n % 2 == 0) {
            $n = intdiv($n, 2);
        } elseif ($n > 0) {
            $n = 3 * $n + 1;
        }
        $steps++;
    }
    return $steps;
}

function avg(int $a, int $b): float {
    return ($a + $b) / 2;
}
