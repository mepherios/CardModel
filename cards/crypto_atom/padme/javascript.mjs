export function padme(length) {
  const n = Number(length);
  const e = 31 - Math.clz32(n);
  const s = 32 - Math.clz32(e);
  const bits = e - s;
  const mask = bits > 0 ? 2 ** bits - 1 : 0;
  return BigInt((n + mask) - ((n + mask) % (mask + 1)));
}
export function pad(data, mode) {
  const need = data.length + 1;
  let target;
  if (mode === 'padme') target = Number(padme(need));
  else if (mode === 'buckets') target = [256, 1024, 4096, 16384, 65536].find((b) => b >= need);
  else if (mode === 'none') target = need;
  else throw new Error('padding mode');
  if (target === undefined || target > 65536) throw new Error('too large');
  const out = new Uint8Array(target);
  out.set(data, 0);
  out[data.length] = 0x80;
  return out;
}
