import { createPrivateKey, createPublicKey, sign, verify } from 'node:crypto';
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
