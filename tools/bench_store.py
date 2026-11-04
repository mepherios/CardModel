"""Store start-up benchmark (docs/SCALING.md S-B): does a command's cost grow with the size of the card store?

Generates synthetic card trees of N cards (packs plus some directory cards) and times, in fresh processes,
`cardmodel show op/ADD`, `show ADD` (a bare name) and `list op` with the tree loaded via --cards.

    python3 tools/bench_store.py [--sizes 0,100000,1000000] [--out FILE.json]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGS = 50          # registries per synthetic tree
DIR_CARDS = 20     # directory cards per registry (the rest in packs)


def make_tree(root: Path, n: int) -> Path:
    tree = root / f"tree_{n}"
    if tree.exists():
        return tree
    per = max(1, n // REGS) if n else 0
    for r in range(REGS if n else 0):
        reg = tree / f"synth{r:03d}"
        reg.mkdir(parents=True)
        (reg / "_category.json").write_text(json.dumps({"name": f"synth{r:03d}", "description": "synthetic"}))
        with open(reg / "_pack_bulk.jsonl", "w") as f:
            for i in range(max(0, per - DIR_CARDS)):
                f.write(json.dumps({"name": f"s{r}_{i}", "category": f"synth{r:03d}", "body": {"i": i, "pad": "x" * 64}}) + "\n")
        for i in range(min(per, DIR_CARDS)):
            d = reg / f"d{r}_{i}"
            d.mkdir()
            (d / "card.json").write_text(json.dumps({"name": f"d{r}_{i}", "category": f"synth{r:03d}"}))
    tree.mkdir(parents=True, exist_ok=True)
    return tree


def timed(args: list[str], reps: int = 3) -> float:
    env = dict(os.environ, CARDMODEL_SELF="0")
    best = None
    for _ in range(reps):
        t = time.perf_counter()
        r = subprocess.run([sys.executable, "-B", "-m", "cardmodel", "--no-project", *args], cwd=ROOT, env=env,
                           capture_output=True, text=True)
        dt = time.perf_counter() - t
        if r.returncode != 0:
            raise SystemExit(f"{args}: rc={r.returncode}\n{r.stderr[-1500:]}")
        best = dt if best is None else min(best, dt)
    return round(best, 3)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="0,100000,1000000")
    ap.add_argument("--work", default=None, help="where synthetic trees are kept (default: a temp dir)")
    ap.add_argument("--out")
    a = ap.parse_args()
    work = Path(a.work or tempfile.mkdtemp(prefix="cardmodel_bench_"))
    rows = []
    for n in [int(s) for s in a.sizes.split(",")]:
        tree = make_tree(work, n)
        extra = ["--cards", str(tree)] if n else []
        row = {"extra_cards": n,
               "first run (builds the index)": timed(extra + ["show", "ADD"], reps=1),
               "show op/ADD": timed(extra + ["show", "op/ADD"]),
               "show ADD": timed(extra + ["show", "ADD"]),
               "list op": timed(extra + ["list", "op"]),
               "show in a big registry": timed(extra + ["show", "synth000/s0_7" if n else "op/ADD"])}
        rows.append(row)
        print(json.dumps(row), flush=True)
    if a.out:
        Path(a.out).write_text(json.dumps(rows, indent=1) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
