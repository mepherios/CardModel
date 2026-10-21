// Canonical JSON, JavaScript form (ported from Ting static/app/enc.js).
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;
class EncodingError extends Error {}
function isPlainObject(value) {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const proto = Object.getPrototypeOf(value);
  return proto === Object.prototype || proto === null;
}
function checkString(text) { if (LONE_SURROGATE.test(text)) throw new EncodingError('lone surrogate'); }
function encode(value, out, depth) {
  if (depth > 64) throw new EncodingError('nesting too deep');
  if (value === null) out.push('null');
  else if (value === true) out.push('true');
  else if (value === false) out.push('false');
  else if (typeof value === 'bigint') throw new EncodingError('integer out of range');
  else if (typeof value === 'number') {
    if (!Number.isSafeInteger(value)) throw new EncodingError('integer out of range');
    out.push(String(value));
  } else if (typeof value === 'string') { checkString(value); out.push(JSON.stringify(value)); }
  else if (Array.isArray(value)) {
    out.push('[');
    value.forEach((item, i) => { if (i) out.push(','); encode(item, out, depth + 1); });
    out.push(']');
  } else if (isPlainObject(value)) {
    const keys = Object.keys(value);
    keys.forEach(checkString);
    keys.sort();
    out.push('{');
    keys.forEach((key, i) => { if (i) out.push(','); out.push(JSON.stringify(key), ':'); encode(value[key], out, depth + 1); });
    out.push('}');
  } else throw new EncodingError(`type not allowed: ${typeof value}`);
}
export function canon_str(value) { const out = []; encode(value, out, 0); return out.join(''); }
