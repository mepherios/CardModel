from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def aes256gcm_seal(key: bytes, nonce: bytes, pt: bytes, aad: bytes) -> bytes:
    return AESGCM(key).encrypt(nonce, pt, aad)
