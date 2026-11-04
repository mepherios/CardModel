"""equivalence — the equivalence relations the model identifies things under (docs/FOUNDATIONS.md D9, rule A4).

An identity hash means "these two are the same", and there is more than one sense of same. Every identity record
names its relation (``identity.under``), so two hashes are compared only when they were taken under one relation,
and a reader knows what an equal hash proves.

  laws       ≈_E: equal under the sorted laws, by e-graph saturation (engines/egraph.py); sound for the model M
  real       ≡_ℝ: equal as rational functions over a field (engines/realnorm.py); sound on int polynomials, an
             approximation on floating point
  behaviour  ≡_beh: the same recurrence and initial terms (engines/funcalg.py), checked on unused terms
  alpha      ≡_α: the same term up to the names of its variables (engines/numbering.py)
  syntax     =: the same term; no reasoning applied
"""
from __future__ import annotations

RELATIONS = {
    "laws": "≈_E: equal under the sorted laws (e-graph saturation)",
    "real": "≡_ℝ: equal as rational functions over a field (realnorm)",
    "behaviour": "≡_beh: the same recurrence and initial terms (funcalg)",
    "alpha": "≡_α: the same term up to variable names",
    "syntax": "=: the same term, no reasoning applied",
}


def comparable(a: dict, b: dict) -> bool:
    """Two identity records can be compared: both name the same relation."""
    return bool(a.get("under")) and a.get("under") == b.get("under") and a.get("under") in RELATIONS


__all__ = ["RELATIONS", "comparable"]
