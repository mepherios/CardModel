func gcd(_ a: Int, _ b: Int) -> Int {
    var a = a
    var b = b
    while b != 0 {
        (a, b) = (b, a % b)
    }
    return abs(a)
}

func stepped(_ n: Int) -> Int {
    var s = 0
    for i in stride(from: 0, to: n, by: 3) {
        s += i
    }
    for j in 1...3 {
        s += j
    }
    return s
}

func scale(_ x: Int, by f: Double) -> Double {
    return Double(x) * f
}
