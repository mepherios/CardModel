#![allow(dead_code)]

fn gcd(mut a: i64, mut b: i64) -> i64 {
    while b != 0 {
        let t = a % b;
        a = b;
        b = t;
    }
    a.abs()
}

fn collatz(n: i64) -> i64 {
    let mut n = n;
    let mut steps = 0;
    while n > 1 {
        n = if n % 2 == 0 { n / 2 } else { 3 * n + 1 };
        steps += 1;
    }
    steps
}

fn sum_squares(n: i64) -> i64 {
    let mut s: i64 = 0;
    for i in 0..n {
        s += i * i;
    }
    s
}

fn countdown(n: i64) -> i64 {
    let mut acc = 0;
    for i in (0..n).rev() {
        acc = acc * 2 + i;
        if acc > 1_000_000 {
            break;
        }
    }
    acc
}

fn ratio(a: i64, b: f64) -> f64 {
    (a as f64 / b).floor() + b.sqrt().abs()
}

fn classify(x: i64) -> i64 {
    if x < 0 {
        -1
    } else if x == 0 {
        0
    } else {
        1
    }
}

fn wrap(a: i64, m: i64) -> i64 {
    a.rem_euclid(m)
}

fn main() {
    println!("{}", gcd(12, 18));
}
