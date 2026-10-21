import { createHmac } from 'node:crypto';
export function hmac_sha256(key, msg) { return new Uint8Array(createHmac('sha256', key).update(msg).digest()); }
