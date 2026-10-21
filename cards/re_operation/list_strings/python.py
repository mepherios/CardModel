"""list_strings forms (ported from rea-cards runtime/reacards/native/strings.py and host/strings.py).

py_strings reproduces Apple cctools `strings - -n N -t d` under LC_ALL=C:
every byte is scanned, a run of bytes in 0x20..0x7e of length >= N is a
string (including a run that ends at EOF), text is cut at 1022 characters.
"""
import os
import re
import subprocess

TEXT_LIMIT = 1022


def py_strings(path: str, min_length: int) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    rx = re.compile(rb"[\x20-\x7e]{%d,}" % max(1, int(min_length)))
    return {"strings": [{"offset": m.start(), "text": m.group()[:TEXT_LIMIT].decode("ascii")} for m in rx.finditer(data)]}


def host_strings(path: str, min_length: int) -> dict:
    env = dict(os.environ, LC_ALL="C", LANG="C")
    p = subprocess.run(["strings", "-", "-n", str(int(min_length)), "-t", "d", path], capture_output=True,
                       timeout=60, env=env)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode(errors="replace")[:300])
    out = []
    for line in p.stdout.split(b"\n"):
        if not line.strip():
            continue
        off, _, text = line.lstrip().partition(b" ")
        out.append({"offset": int(off), "text": text.decode("ascii", errors="replace")})
    return {"strings": out}
