#!/usr/bin/env python3
"""require_toolchains — fail unless every language with a code generator is runnable on this host.

CI installs every toolchain, so a codegen language that probes as unavailable there means a broken install
or a broken probe, not a missing tool, and translation checks in that language would pass vacuously.

usage: python3 -B tools/require_toolchains.py [--allow LANG,...]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--allow", default="", help="codegen languages that may be missing (comma separated)")
    args = ap.parse_args(argv)
    allow = {x for x in args.allow.split(",") if x}
    env = dict(os.environ, CARDMODEL_SELF="0")
    out = subprocess.run([sys.executable, "-B", "-m", "cardmodel", "--json", "probe"], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True).stdout
    langs = json.loads(out)
    missing = {k: v["detail"] for k, v in sorted(langs.items())
               if v.get("codegen") and not v["available"] and k not in allow}
    for k, v in sorted(langs.items()):
        print(f"  {'ok' if v['available'] else '--'}  {k:<12} {v['detail']}")
    if missing:
        print(f"\ncodegen languages unavailable: {', '.join(f'{k} ({d})' for k, d in missing.items())}")
        return 1
    print("\nevery codegen language is runnable")
    return 0


if __name__ == "__main__":
    sys.exit(main())
