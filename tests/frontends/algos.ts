export function gcd(a: bigint, b: bigint): bigint {
  while (b !== 0n) {
    const t: bigint = a % b;
    a = b;
    b = t;
  }
  return a < 0n ? -a : a;
}

function area(r: number): number {
  return Math.PI * r ** 2;
}
