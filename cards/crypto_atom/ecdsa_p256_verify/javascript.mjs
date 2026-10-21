import { createECDH, createPublicKey, verify, ECDH } from 'node:crypto';
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
