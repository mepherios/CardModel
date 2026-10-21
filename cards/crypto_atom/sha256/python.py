import hashlib


def sha256(msg: bytes) -> bytes:
    return hashlib.sha256(msg).digest()
