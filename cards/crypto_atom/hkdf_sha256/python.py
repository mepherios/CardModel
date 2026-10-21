import hashlib
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
