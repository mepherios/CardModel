import kotlin.math.abs

fun gcd(a0: Long, b0: Long): Long {
    var a = a0
    var b = b0
    while (b != 0L) {
        val t = a % b
        a = b
        b = t
    }
    return abs(a)
}

fun sumTo(n: Long): Long {
    var s = 0L
    for (i in 1..n) s += i
    return s
}

fun evens(n: Long): Long {
    var c = 0L
    for (i in 0 until n step 2) {
        c += 1
    }
    return c
}

fun sign(x: Long): Long = if (x > 0) 1 else if (x < 0) -1 else 0

fun half(x: Long): Double = x.toDouble() / 2
