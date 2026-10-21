import { createCipheriv } from 'node:crypto';
export function aes256gcm_seal(key, nonce, pt, aad) {
  const c = createCipheriv('aes-256-gcm', key, nonce);
  c.setAAD(aad);
  const body = Buffer.concat([c.update(pt), c.final()]);
  return new Uint8Array(Buffer.concat([body, c.getAuthTag()]));
}
