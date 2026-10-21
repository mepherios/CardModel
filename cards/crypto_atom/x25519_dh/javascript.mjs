import { createPrivateKey, createPublicKey, diffieHellman } from 'node:crypto';
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
