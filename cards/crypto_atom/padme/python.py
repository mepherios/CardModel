def padme(length: int) -> int:
    """Padme length (Nikitin et al., PURBs, PETS 2019)."""
    e = length.bit_length() - 1
    s = e.bit_length() if e > 0 else 0
    mask = (1 << (e - s)) - 1 if e - s > 0 else 0
    return (length + mask) & ~mask


def pad(data: bytes, mode: str) -> bytes:
    need = len(data) + 1
    if mode == "padme":
        target = padme(need)
    elif mode == "buckets":
        target = next((b for b in (256, 1024, 4096, 16384, 65536) if b >= need), None)
        if target is None:
            raise ValueError("too large for the largest bucket")
    elif mode == "none":
        target = need
    else:
        raise ValueError("padding mode")
    if target > 65536:
        raise ValueError("too large")
    return data + b"\x80" + b"\x00" * (target - need)
