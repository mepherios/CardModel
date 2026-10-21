import { createHash } from 'node:crypto';
export function sha256(msg) { return new Uint8Array(createHash('sha256').update(msg).digest()); }
