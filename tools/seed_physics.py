"""seed_physics — physics as a Gödel set (docs/GODEL_TARGET.md G13, §6 step 4): the SI base quantities as atoms,
the dimension model the IR's ops act through, the derived quantities as a carry map, and physical laws as cards
whose two sides must have one dimension.

  godel_set/physics    the set: its atoms (arity 0), its numbering (B0's scheme), its ``model`` (op -> action on
                       dimensions) and its ``derived`` quantities (name -> base content)
  physics_law/*        each law: lhs and rhs as IR terms over variables, and the dimension of every variable

Run: ``python3 -B tools/seed_physics.py`` (idempotent: existing cards are kept unless --force). It appends the
quantity atoms to the ledger the first time (engines/godel.sync: append-only, CM43).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cardmodel.engines import dimensions as D  # noqa: E402
from cardmodel.engines import godel as GD  # noqa: E402
from cardmodel.kernel.store import open_store  # noqa: E402

PROV = {"origin": "cardmodel", "tool": "tools/seed_physics.py"}

# how each op of the signature acts on the dimensions of its arguments (engines/dimensions.ACTIONS)
MODEL = {
    "MUL": "add", "DIV": "sub", "TRUNCDIV": "sub", "FLOORDIV": "sub",
    "ADD": "same", "SUB": "same", "MIN": "same", "MAX": "same", "NEG": "same", "ABS": "same", "MOD": "same",
    "REM": "same", "FMOD": "same", "COPYSIGN": "same", "TO_FLOAT": "same", "F32": "same", "FLOOR": "same",
    "CEIL": "same", "TRUNC": "same", "TRUNC_INT": "same",
    "POW": "scale", "FSQRT": "half",
    "CMP_EQ": "compare", "CMP_NE": "compare", "CMP_LT": "compare", "CMP_LE": "compare", "CMP_GT": "compare",
    "CMP_GE": "compare",
    "EXP": "none", "LOG": "none", "SIN": "none", "COS": "none", "TAN": "none", "ASIN": "none", "ACOS": "none",
    "ATAN": "none", "ATAN2": "none", "SINH": "none", "COSH": "none", "TANH": "none", "AND": "none", "OR": "none",
    "NOT": "none", "ISNAN": "none", "GCD": "same", "POW_MOD": "same",
    "IF_EXPR": "branches",
}

DERIVED = {
    "velocity": "length/time", "acceleration": "length/time^2", "momentum": "mass*length/time",
    "force": "mass*length/time^2", "energy": "mass*length^2/time^2", "power": "mass*length^2/time^3",
    "pressure": "mass*length^-1*time^-2", "density": "mass*length^-3", "frequency": "time^-1",
    "charge": "current*time", "voltage": "mass*length^2*time^-3*current^-1",
    "resistance": "mass*length^2*time^-3*current^-2", "entropy": "mass*length^2*time^-2*temperature^-1",
    "action": "mass*length^2/time", "gravitational_constant": "length^3*mass^-1*time^-2",
    "gas_constant": "mass*length^2*time^-2*temperature^-1*amount^-1",
    "coulomb_constant": "mass*length^3*time^-4*current^-2",
}


def v(name):
    return ["var", name]


def mul(*ts):
    out = ts[0]
    for t in ts[1:]:
        out = ["MUL", out, t]
    return out


LAWS = [
    ("newton_second", "F = m·a", v("F"), mul(v("m"), v("a")), {"F": "force", "m": "mass", "a": "acceleration"},
     "Newton (1687), Principia, Lex II"),
    ("momentum", "p = m·v", v("p"), mul(v("m"), v("v")), {"p": "momentum", "m": "mass", "v": "velocity"}, "definition"),
    ("kinetic_energy", "E = m·v² / 2", v("E"), ["DIV", mul(v("m"), ["POW", v("v"), ["int", 2]]), ["int", 2]],
     {"E": "energy", "m": "mass", "v": "velocity"}, "classical mechanics"),
    ("work_power", "P = W / t", v("P"), ["DIV", v("W"), v("t")], {"P": "power", "W": "energy", "t": "time"},
     "definition"),
    ("gravitation", "F = G·m₁·m₂ / r²", v("F"), ["DIV", mul(v("G"), v("m1"), v("m2")), ["POW", v("r"), ["int", 2]]],
     {"F": "force", "G": "gravitational_constant", "m1": "mass", "m2": "mass", "r": "length"},
     "Newton (1687), Principia, Book III"),
    ("hydrostatic_pressure", "p = ρ·g·h", v("p"), mul(v("rho"), v("g"), v("h")),
     {"p": "pressure", "rho": "density", "g": "acceleration", "h": "length"}, "fluid statics"),
    ("ideal_gas", "p·V = n·R·T", mul(v("p"), v("V")), mul(v("n"), v("R"), v("T")),
     {"p": "pressure", "V": "length^3", "n": "amount", "R": "gas_constant", "T": "temperature"},
     "Clapeyron (1834)"),
    ("ohm", "V = I·R", v("V"), mul(v("I"), v("R")), {"V": "voltage", "I": "current", "R": "resistance"},
     "Ohm (1827)"),
    ("coulomb", "F = k·q₁·q₂ / r²", v("F"), ["DIV", mul(v("k"), v("q1"), v("q2")), ["POW", v("r"), ["int", 2]]],
     {"F": "force", "k": "coulomb_constant", "q1": "charge", "q2": "charge", "r": "length"}, "Coulomb (1785)"),
    ("pendulum_period", "T = 2·π·√(L / g)", v("T"), mul(["int", 2], v("pi"), ["FSQRT", ["DIV", v("L"), v("g")]]),
     {"T": "time", "pi": "1", "L": "length", "g": "acceleration"}, "the small-angle pendulum"),
    ("mass_energy", "E = m·c²", v("E"), mul(v("m"), ["POW", v("c"), ["int", 2]]),
     {"E": "energy", "m": "mass", "c": "velocity"}, "Einstein (1905)"),
    ("planck", "E = h·f", v("E"), mul(v("h"), v("f")), {"E": "energy", "h": "action", "f": "frequency"},
     "Planck (1900)"),
    ("boltzmann_entropy", "S = k·ln W", v("S"), mul(v("k"), ["LOG", v("W")]),
     {"S": "entropy", "k": "entropy", "W": "1"}, "Boltzmann; W a count of microstates, dimensionless"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)
    store = open_store(project=False)
    store.ensure_registry(D.REGISTRY, "model", description="Physical laws as equations between terms over "
                          "variables with stated dimensions; consistent when both sides have one dimension "
                          "(engines/dimensions.py, the Gödel set physics).", tier=0)
    stats = {"written": 0, "kept": 0}

    def put(card):
        if store.get(f"{card['category']}/{card['name']}") is not None and not args.force:
            stats["kept"] += 1
            return
        _, changed = store.save(card, layer="model")
        stats["written" if changed else "kept"] += 1

    b0 = (store.get("godel_set/B0") or {}).get("numbering") or {}
    numbering = {k: b0[k] for k in ("cites", "code", "conditions", "content", "identity", "provability") if k in b0}
    numbering.update(objects="core terms over the IR's ops and those of B0, the base quantities as leaves (arity "
                             "0), integer constants and variables",
                     witness="tests/test_dimensions.py::Physics::test_the_set_is_admissible",
                     arities_from="stated on this card: every base quantity has arity 0",
                     samples=20, samples_why="its atoms are the latest in the ledger (indices 3418 to 3424), so a "
                     "quantity's token code is about 10,240 and each generated object codes to a number of about "
                     "200,000 bits; 20 generated objects witness the six conditions in about 8 s where 120 take "
                     "40 s (the decoding is by p-adic valuation already). The root fix is a per-set dense rank "
                     "for positional codes, which amends the numbering GM-4 states and is the user's call "
                     "(docs/GODEL_AUDIT.md).")
    put({"name": D.SET, "category": "godel_set", "tier": 0, "extends": "B0",
         "statement": "Physical dimension as content: the SI base quantities are atoms, a dimension is a signed "
                      "content vector over them (acceleration is length*time^-2), and an equation is dimensionally "
                      "consistent exactly when its two sides have one content. The IR's ops act on dimensions "
                      "through the model stated here, a second algebra of the signature whose carrier is the "
                      "content group; their numeric meaning stays the op cards' (FOUNDATIONS A2, D14).",
         "arities": {a: 0 for a in D.ATOMS}, "constants": list(D.ATOMS), "numbering": numbering, "model": MODEL,
         "derived": DERIVED,
         "provenance": PROV})
    for name, statement, lhs, rhs, dims, source in LAWS:
        put({"name": name, "category": D.REGISTRY, "tier": 0, "statement": statement, "lhs": lhs, "rhs": rhs,
             "dimensions": dims, "source": source, "provenance": PROV})
    store.invalidate()
    new = GD.sync(store, list(D.ATOMS), D.SET)
    stats["ledger_appended"] = len(new)
    stats["ledger"] = len(GD.ledger(store))
    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    sys.exit(main())
