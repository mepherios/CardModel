import { hkdfSync } from 'node:crypto';
export function hkdf_sha256(ikm, salt, info, length) {
  return new Uint8Array(hkdfSync('sha256', ikm, salt, info, Number(length)));
}
