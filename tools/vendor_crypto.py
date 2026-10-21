"""vendor_crypto — form code for the crypto atoms ported from Ting (stdlib Python + node:crypto).

Ting's own forms use noble (browser) and cryptography/PyNaCl (Python). The
model must run with no third-party packages, so its forms are:
  * Python: hashlib/hmac, plus pure-Python X25519 (RFC 7748 section 5) and
    Ed25519 (RFC 8032 section 6 reference algorithm). Slow, exact, stdlib-only.
  * JavaScript: Node's built-in node:crypto (no npm packages).
The witnesses are Ting's known-answer vectors (RFC 7748, RFC 8032, RFC 5869,
FIPS 180-4, RFC 4231, the GCM spec, RFC 6979, NIST CAVS) converted to the
model's generic {args, out} shape.
"""

PY = {}
JS = {}

PY["sha256"] = '''import hashlib


def sha256(msg: bytes) -> bytes:
    return hashlib.sha256(msg).digest()
'''
JS["sha256"] = '''import { createHash } from 'node:crypto';
export function sha256(msg) { return new Uint8Array(createHash('sha256').update(msg).digest()); }
'''

PY["hmac_sha256"] = '''import hashlib
import hmac


def hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()
'''
JS["hmac_sha256"] = '''import { createHmac } from 'node:crypto';
export function hmac_sha256(key, msg) { return new Uint8Array(createHmac('sha256', key).update(msg).digest()); }
'''

PY["hkdf_sha256"] = '''import hashlib
import hmac


def hkdf_sha256(ikm: bytes, salt: bytes, info: bytes, length: int) -> bytes:
    """RFC 5869 extract-then-expand with HMAC-SHA256 (empty salt = 32 zero bytes)."""
    prk = hmac.new(salt or bytes(32), ikm, hashlib.sha256).digest()
    out, block, i = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([i]), hashlib.sha256).digest()
        out += block
        i += 1
    return out[:length]
'''
JS["hkdf_sha256"] = '''import { hkdfSync } from 'node:crypto';
export function hkdf_sha256(ikm, salt, info, length) {
  return new Uint8Array(hkdfSync('sha256', ikm, salt, info, Number(length)));
}
'''

PY["padme"] = '''def padme(length: int) -> int:
    """Padme length (Nikitin et al., PURBs, PETS 2019)."""
    e = length.bit_length() - 1
    s = e.bit_length() if e > 0 else 0
    mask = (1 << (e - s)) - 1 if e - s > 0 else 0
    return (length + mask) & ~mask


def pad(data: bytes, mode: str) -> bytes:
    need = len(data) + 1
    if mode == "padme":
        target = padme(need)
    elif mode == "buckets":
        target = next((b for b in (256, 1024, 4096, 16384, 65536) if b >= need), None)
        if target is None:
            raise ValueError("too large for the largest bucket")
    elif mode == "none":
        target = need
    else:
        raise ValueError("padding mode")
    if target > 65536:
        raise ValueError("too large")
    return data + b"\\x80" + b"\\x00" * (target - need)
'''
JS["padme"] = '''export function padme(length) {
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
'''

PY["canon_json"] = '''"""Canonical JSON, Python form (identical to cardmodel.kernel.canon; ported from Ting core/encoding.py)."""
import json

MAX_SAFE_INT = 2**53


class CanonError(ValueError):
    pass


def _check_str(text):
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonError("lone surrogate") from exc


def _encode(value, out, depth):
    if depth > 64:
        raise CanonError("nesting too deep")
    if value is None:
        out.append("null")
    elif value is True:
        out.append("true")
    elif value is False:
        out.append("false")
    elif type(value) is int:
        if not -MAX_SAFE_INT < value < MAX_SAFE_INT:
            raise CanonError("integer out of range")
        out.append(str(value))
    elif type(value) is str:
        _check_str(value)
        out.append(json.dumps(value, ensure_ascii=False))
    elif type(value) in (list, tuple):
        out.append("[")
        for i, item in enumerate(value):
            if i:
                out.append(",")
            _encode(item, out, depth + 1)
        out.append("]")
    elif type(value) is dict:
        for key in value:
            if type(key) is not str:
                raise CanonError("object keys must be strings")
            _check_str(key)
        out.append("{")
        for i, key in enumerate(sorted(value, key=lambda k: k.encode("utf-16-be", "surrogatepass"))):
            if i:
                out.append(",")
            out.append(json.dumps(key, ensure_ascii=False))
            out.append(":")
            _encode(value[key], out, depth + 1)
        out.append("}")
    else:
        raise CanonError(f"type not allowed: {type(value).__name__}")


def canon_str(value) -> str:
    out = []
    _encode(value, out, 0)
    return "".join(out)
'''
JS["canon_json"] = '''// Canonical JSON, JavaScript form (ported from Ting static/app/enc.js).
const LONE_SURROGATE = /[\\uD800-\\uDBFF](?![\\uDC00-\\uDFFF])|(?<![\\uD800-\\uDBFF])[\\uDC00-\\uDFFF]/;
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
'''

PY["x25519"] = '''"""X25519 (RFC 7748 section 5), pure Python. Constant-time is NOT a goal of this reference form."""
P = 2**255 - 19
A24 = 121665


def _clamp(k: bytes) -> int:
    b = bytearray(k)
    b[0] &= 248
    b[31] &= 127
    b[31] |= 64
    return int.from_bytes(b, "little")


def _ladder(k: bytes, u: bytes) -> bytes:
    if len(k) != 32 or len(u) != 32:
        raise ValueError("x25519 needs 32-byte inputs")
    kn = _clamp(k)
    x1 = int.from_bytes(u, "little") & ((1 << 255) - 1)
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in reversed(range(255)):
        kt = (kn >> t) & 1
        swap ^= kt
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        a = (x2 + z2) % P
        aa = a * a % P
        b = (x2 - z2) % P
        bb = b * b % P
        e = (aa - bb) % P
        c = (x3 + z3) % P
        d = (x3 - z3) % P
        da = d * a % P
        cb = c * b % P
        x3 = (da + cb) ** 2 % P
        z3 = x1 * (da - cb) ** 2 % P
        x2 = aa * bb % P
        z2 = e * (aa + A24 * e) % P
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * pow(z2, P - 2, P) % P).to_bytes(32, "little")


def x25519_public(seed: bytes) -> bytes:
    return _ladder(seed, (9).to_bytes(32, "little"))


def x25519_dh(sk: bytes, pk: bytes) -> bytes:
    out = _ladder(sk, pk)
    if out == bytes(32):
        raise ValueError("all-zero shared secret (low-order point)")
    return out
'''
JS["x25519"] = '''import { createPrivateKey, createPublicKey, diffieHellman } from 'node:crypto';
const PKCS8 = Buffer.from('302e020100300506032b656e04220420', 'hex');
const SPKI = Buffer.from('302a300506032b656e032100', 'hex');
const priv = (sk) => createPrivateKey({ key: Buffer.concat([PKCS8, Buffer.from(sk)]), format: 'der', type: 'pkcs8' });
export function x25519_public(seed) {
  const der = createPublicKey(priv(seed)).export({ format: 'der', type: 'spki' });
  return new Uint8Array(der.subarray(der.length - 32));
}
export function x25519_dh(sk, pk) {
  const pub = createPublicKey({ key: Buffer.concat([SPKI, Buffer.from(pk)]), format: 'der', type: 'spki' });
  const out = diffieHellman({ privateKey: priv(sk), publicKey: pub });
  if (out.every((b) => b === 0)) throw new Error('all-zero shared secret (low-order point)');
  return new Uint8Array(out);
}
'''

PY["ed25519"] = '''"""Ed25519 (RFC 8032 section 6 reference algorithm), pure Python. Not constant-time."""
import hashlib

P = 2**255 - 19
Q = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _h(m: bytes) -> bytes:
    return hashlib.sha512(m).digest()


def _add(p1, p2):
    a = (p1[1] - p1[0]) * (p2[1] - p2[0]) % P
    b = (p1[1] + p1[0]) * (p2[1] + p2[0]) % P
    c = 2 * p1[3] * p2[3] * D % P
    d = 2 * p1[2] * p2[2] % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def _mul(s: int, pt):
    q = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _add(pt, pt)
        s >>= 1
    return q


def _equal(p1, p2) -> bool:
    return (p1[0] * p2[2] - p2[0] * p1[2]) % P == 0 and (p1[1] * p2[2] - p2[1] * p1[2]) % P == 0


def _recover_x(y: int, sign: int):
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P)
    if x2 % P == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_GY = 4 * pow(5, P - 2, P) % P
_GX = _recover_x(_GY, 0)
G = (_GX, _GY, 1, _GX * _GY % P)


def _compress(pt) -> bytes:
    zinv = pow(pt[2], P - 2, P)
    x, y = pt[0] * zinv % P, pt[1] * zinv % P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


def _decompress(s: bytes):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _expand(secret: bytes):
    if len(secret) != 32:
        raise ValueError("ed25519 secret must be 32 bytes")
    h = _h(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public(secret: bytes) -> bytes:
    a, _ = _expand(secret)
    return _compress(_mul(a, G))


def ed25519_sign(secret: bytes, msg: bytes) -> bytes:
    a, prefix = _expand(secret)
    pk = _compress(_mul(a, G))
    r = int.from_bytes(_h(prefix + msg), "little") % Q
    rs = _compress(_mul(r, G))
    k = int.from_bytes(_h(rs + pk + msg), "little") % Q
    return rs + ((r + k * a) % Q).to_bytes(32, "little")


def ed25519_verify(pk: bytes, msg: bytes, sig: bytes) -> bool:
    if len(pk) != 32 or len(sig) != 64:
        return False
    a = _decompress(pk)
    r = _decompress(sig[:32])
    if a is None or r is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= Q:
        return False
    k = int.from_bytes(_h(sig[:32] + pk + msg), "little") % Q
    return _equal(_mul(s, G), _add(r, _mul(k, a)))
'''
JS["ed25519"] = '''import { createPrivateKey, createPublicKey, sign, verify } from 'node:crypto';
const PKCS8 = Buffer.from('302e020100300506032b657004220420', 'hex');
const SPKI = Buffer.from('302a300506032b6570032100', 'hex');
const priv = (sk) => createPrivateKey({ key: Buffer.concat([PKCS8, Buffer.from(sk)]), format: 'der', type: 'pkcs8' });
export function ed25519_public(seed) {
  const der = createPublicKey(priv(seed)).export({ format: 'der', type: 'spki' });
  return new Uint8Array(der.subarray(der.length - 32));
}
export function ed25519_sign(seed, msg) { return new Uint8Array(sign(null, Buffer.from(msg), priv(seed))); }
export function ed25519_verify(pk, msg, sig) {
  try {
    const pub = createPublicKey({ key: Buffer.concat([SPKI, Buffer.from(pk)]), format: 'der', type: 'spki' });
    return verify(null, Buffer.from(msg), pub, Buffer.from(sig));
  } catch { return false; }
}
'''

JS["aes256gcm"] = '''import { createCipheriv } from 'node:crypto';
export function aes256gcm_seal(key, nonce, pt, aad) {
  const c = createCipheriv('aes-256-gcm', key, nonce);
  c.setAAD(aad);
  const body = Buffer.concat([c.update(pt), c.final()]);
  return new Uint8Array(Buffer.concat([body, c.getAuthTag()]));
}
'''
PY["aes256gcm"] = '''from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def aes256gcm_seal(key: bytes, nonce: bytes, pt: bytes, aad: bytes) -> bytes:
    return AESGCM(key).encrypt(nonce, pt, aad)
'''

JS["p256"] = '''import { createECDH, createPublicKey, verify, ECDH } from 'node:crypto';
const b64u = (b) => Buffer.from(b).toString('base64url');
export function p256_dh(sk, pk) {
  const e = createECDH('prime256v1');
  e.setPrivateKey(Buffer.from(sk));
  return new Uint8Array(e.computeSecret(Buffer.from(pk)));
}
export function ecdsa_p256_verify(pk, msg, sig) {
  try {
    const raw = ECDH.convertKey(Buffer.from(pk), 'prime256v1', undefined, undefined, 'uncompressed');
    const key = createPublicKey({ key: { kty: 'EC', crv: 'P-256', x: b64u(raw.subarray(1, 33)), y: b64u(raw.subarray(33, 65)) }, format: 'jwk' });
    return verify('sha256', Buffer.from(msg), { key, dsaEncoding: 'ieee-p1363' }, Buffer.from(sig));
  } catch { return false; }
}
'''


def b(hexstr: str) -> dict:
    return {"$bytes": hexstr}


def convert(atom: str, vectors: list[dict]) -> dict[str, list[dict]]:
    """Ting vectors -> {entry: [{name, args, out|error, source}]}."""
    out: dict[str, list[dict]] = {}

    def add(entry, v, args, res=None, error=False):
        row = {"name": v.get("name"), "args": args, "source": v.get("source", "Ting vectors.json")}
        if error:
            row["error"] = True
        else:
            row["out"] = res
        out.setdefault(entry, []).append(row)

    for v in vectors:
        op = v.get("op")
        if atom == "sha256":
            add("sha256", v, [b(v["msg"])], b(v["out"]))
        elif atom == "hmac_sha256":
            add("hmac_sha256", v, [b(v["key"]), b(v["msg"])], b(v["out"]))
        elif atom == "hkdf_sha256":
            add("hkdf_sha256", v, [b(v["ikm"]), b(v["salt"]), b(v["info"]), v["len"]], b(v["out"]))
        elif atom == "canon_json":
            add("canon_str", v, [v["in"]], v.get("out"), error=bool(v.get("error")))
        elif atom == "padme" and op == "padme":
            add("padme", v, [v["in"]], v["out"])
        elif atom == "padme" and op == "pad":
            add("pad", v, [b(v["data"]), v["mode"]], b(v["out"]) if "out" in v else None, error=bool(v.get("error")))
        elif atom == "x25519_kem" and op == "keygen":
            add("x25519_public", v, [b(v["seed"])], b(v["pk"]))
        elif atom == "x25519_kem" and op == "dh":
            add("x25519_dh", v, [b(v["sk"]), b(v["pk"])], b(v["out"]) if "out" in v else None,
                error=bool(v.get("error")))
        elif atom == "ed25519" and op == "sign":
            add("ed25519_public", v, [b(v["sk"])], b(v["pk"]))
            add("ed25519_sign", v, [b(v["sk"]), b(v["msg"])], b(v["sig"]))
            add("ed25519_verify", v, [b(v["pk"]), b(v["msg"]), b(v["sig"])], True)
        elif atom == "ed25519" and op == "verify":
            add("ed25519_verify", v, [b(v["pk"]), b(v["msg"]), b(v["sig"])], bool(v["valid"]))
        elif atom == "aes256gcm":
            add("aes256gcm_seal", v, [b(v["key"]), b(v["nonce"]), b(v["pt"]), b(v["aad"])], b(v["out"]))
        elif atom == "ecdsa_p256":
            add("ecdsa_p256_verify", v, [b(v["pk"]), b(v["msg"]), b(v["sig"])], bool(v.get("valid", True)))
        elif atom == "p256_kem" and op == "dh":
            add("p256_dh", v, [b(v["sk"]), b(v["pk"])], b(v["out"]))
    return out


# atom -> (cards to create: [(card name, entry, statement, py form key or None, js form key or None, py probe)])
PLAN = {
    "sha256": [("sha256", "sha256", "SHA-256 (FIPS 180-4)", "sha256", "sha256", None)],
    "hmac_sha256": [("hmac_sha256", "hmac_sha256", "HMAC-SHA256 (RFC 2104 / RFC 4231)", "hmac_sha256", "hmac_sha256", None)],
    "hkdf_sha256": [("hkdf_sha256", "hkdf_sha256", "HKDF-SHA256 (RFC 5869)", "hkdf_sha256", "hkdf_sha256", None)],
    "canon_json": [("canon_json", "canon_str", "Canonical JSON (Ting; RFC 8785-like: UTF-16 key order, no floats)",
                    "canon_json", "canon_json", None)],
    "padme": [("padme", "padme", "Padme length (PURBs, PETS 2019)", "padme", "padme", None),
              ("pad_padme", "pad", "Pad with 0x80 marker to padme/bucket length", "padme", "padme", None)],
    "x25519_kem": [("x25519_public", "x25519_public", "X25519 public key from a 32-byte secret (RFC 7748)", "x25519",
                    "x25519", None),
                   ("x25519_dh", "x25519_dh", "X25519 shared secret; all-zero result rejected (Ting rule)", "x25519",
                    "x25519", None)],
    "ed25519": [("ed25519_public", "ed25519_public", "Ed25519 public key from a 32-byte seed (RFC 8032)", "ed25519",
                 "ed25519", None),
                ("ed25519_sign", "ed25519_sign", "Ed25519 signature (deterministic, RFC 8032)", "ed25519", "ed25519", None),
                ("ed25519_verify", "ed25519_verify", "Ed25519 verification (RFC 8032 cofactorless check)", "ed25519",
                 "ed25519", None)],
    "aes256gcm": [("aes256gcm_seal", "aes256gcm_seal", "AES-256-GCM seal: ciphertext || 16-byte tag", "aes256gcm",
                   "aes256gcm", {"kind": "python_module", "module": "cryptography"})],
    "ecdsa_p256": [("ecdsa_p256_verify", "ecdsa_p256_verify", "ECDSA P-256 / SHA-256 verify (r||s, compressed or "
                    "uncompressed public key)", None, "p256", None)],
    "p256_kem": [("p256_dh", "p256_dh", "P-256 ECDH shared secret (x coordinate)", None, "p256", None)],
}
