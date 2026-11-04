// BigInt functions lift as int; Number functions as float
export function gcd(a, b) {
  while (b !== 0n) {
    [a, b] = [b, a % b];
  }
  return a < 0n ? -a : a;
}

function collatz(n) {
  let steps = 0n;
  while (n > 1n) {
    if (n % 2n === 0n) n /= 2n;
    else n = 3n * n + 1n;
    steps++;
  }
  return steps;
}

function hyp(a, b) {
  return Math.sqrt(a * a + b * b);
}

function mixed(x, k) {
  let s = 0;
  for (let i = 0n; i < k; i++) {
    s += x / Number(i + 1n);
  }
  return s;
}

const notAFunction = 3;
