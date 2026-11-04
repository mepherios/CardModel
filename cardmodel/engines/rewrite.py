"""rewrite — pick the cheapest equivalent form (hub rewrite_engine + rea-cards availability).

Selection rule, shared by every caller (L27 / CM05):
  1. candidates = forms whose domain accepts the request domain: a request
     for "any" accepts every form; a form tagged "any" accepts every
     request; otherwise the request must equal the form's domain or be a
     sub-domain of it (domain cards declare ``parents``: u32 -> int -> any);
  2. ``lang`` (optional) keeps forms in that language;
  3. runnable_only drops documentation-only forms;
  4. available_only drops forms whose probe (or language) is unavailable here;
  5. minimum cost wins; ties keep declaration order.

``cost="measured"`` ranks by host measurements (metric cards) when every
candidate has one; otherwise it falls back to the anchors and says so, so
two cost units are never mixed.

Cost vectors (CARD_MODEL.md): ``rank`` takes weights, ``pareto`` takes
dimensions; ``dimension_direction`` comes from the card or its registry.

Honest limits (L1): anchors are heuristic until ``cardmodel optimize``
measures them; domain matching is by name and declared parents only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import probes


@dataclass
class Form:
    card: str
    name: str
    cost: float
    domains: tuple[str, ...]
    lang: str
    runnable: bool
    notes: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def domain(self) -> str:
        return self.domains[0] if len(self.domains) == 1 else ("any" if "any" in self.domains else self.domains[0])


def forms_of(card) -> list[Form]:
    out = []
    for f in card.get("forms") or []:
        if not isinstance(f, dict) or "name" not in f:
            continue
        doms = f.get("domains") or [f.get("domain", "any")]
        runnable = bool(f.get("runnable", True)) and bool(f.get("code") or f.get("file") or f.get("exec"))
        out.append(Form(card.get("name", ""), f["name"], float(f.get("cost", card.get("cost") or 1.0) or 0.0),
                        tuple(doms), f.get("lang", "python"), runnable, f.get("notes", ""), f))
    return out


def ancestors(store, domain: str) -> set[str]:
    seen, todo = set(), [domain]
    while todo:
        d = todo.pop()
        card = store.get(f"domain/{d}") if store is not None else None
        for p in (card.get("parents") if card else None) or []:
            if p not in seen:
                seen.add(p)
                todo.append(p)
    return seen


def accepts(store, form_domains, request: str) -> bool:
    if request == "any" or "any" in form_domains or request in form_domains:
        return True
    return bool(ancestors(store, request) & set(form_domains))


def available(store, form: Form) -> tuple[bool, str]:
    if not form.runnable:
        return False, "documentation-only form (no code)"
    if form.raw.get("probe"):
        return probes.probe(form.raw["probe"])
    if form.lang == "python":
        for lib in form.raw.get("libs") or []:
            if store is not None and store.get(f"lib/{lib}") is None:
                return False, f"lib card {lib!r} missing"
        return True, "python (in-process)"
    lang = store.get(f"language/{form.lang}") if store is not None else None
    if lang is None:
        return False, f"no language card {form.lang!r}"
    from .codegen import resolve_language
    return probes.probe(resolve_language(store, form.lang).get("probe"))


def measured_ns(store, card_name: str, form_name: str, host: str | None = None) -> float | None:
    """The measured per-call cost of a form on ``host`` (default: this machine). A metric card keeps one entry per
    host id (``by_host``); a card without one is used as it is (measured before hosts were kept apart), and an
    unresolved measurement (a slope lost in noise) counts as not measured."""
    m = store.get(f"metric/metric__{card_name}__{form_name}") if store is not None else None
    if not m:
        return None
    by_host = m.get("by_host")
    if by_host:
        if host is None:
            from .optimize import host_id
            host = host_id()
        m = by_host.get(host)
        if not m:
            return None
    if m.get("resolved") is False or "median_ns" not in m:
        return None
    return float(m["median_ns"])


def rank_targets(store, card, host: str | None = None) -> list[dict]:
    """Every form of ``card`` measured on ``host``, fastest first: which language should this run in here."""
    if isinstance(card, str):
        card = store.get(card)
    if card is None:
        return []
    rows = []
    for f in forms_of(card):
        ns = measured_ns(store, card["name"], f.name, host)
        if ns is not None:
            rows.append({"form": f.name, "lang": f.lang, "ns": ns})
    rows.sort(key=lambda r: r["ns"])
    for r in rows:
        r["x_vs_fastest"] = round(r["ns"] / max(rows[0]["ns"], 1e-9), 2)
    return rows


def candidates(store, card, domain: str = "any", lang: str | None = None, runnable_only: bool = True,
               available_only: bool = True, exclude: set[str] | None = None,
               include_hints: bool = False) -> list[Form]:
    exclude = exclude or set()
    out = []
    for f in forms_of(card):
        if f.name in exclude or not accepts(store, f.domains, domain):
            continue
        if f.raw.get("role") == "hint" and not include_hints and lang != f.lang:
            continue
        if lang and f.lang != lang:
            continue
        if runnable_only and not f.runnable:
            continue
        if available_only and not available(store, f)[0]:
            continue
        out.append(f)
    return out


def cheapest(store, card, domain: str = "any", lang: str | None = None, runnable_only: bool = True,
             available_only: bool = True, exclude: set[str] | None = None, cost: str = "anchor",
             include_hints: bool = False) -> Form | None:
    """The selection rule. Forms with ``role: hint`` (another language's spelling of the op, kept for
    verification) are candidates only when ``lang`` names their language or ``include_hints`` is set."""
    if isinstance(card, str):
        card = store.get(card)
        if card is None:
            return None
    cands = candidates(store, card, domain, lang, runnable_only, available_only, exclude, include_hints)
    if not cands:
        return None
    if cost == "measured":
        # measured forms are compared with each other only (ns and anchor units do not mix); with fewer than two
        # measured here, the anchors decide
        ms = [(f, measured_ns(store, card["name"], f.name)) for f in cands]
        ms = [(f, m) for f, m in ms if m is not None]
        if len(ms) >= 2 or (len(ms) == 1 and len(cands) == 1):
            return min(ms, key=lambda p: p[1])[0]
    return min(cands, key=lambda f: f.cost)


def suggest_rewrite(store, card, current_form: str = "native", domain: str = "any", cost: str = "anchor") -> dict | None:
    """Cheapest runnable+available alternative to ``current_form`` (None if current is already optimal)."""
    if isinstance(card, str):
        card = store.get(card)
    if card is None:
        return None
    cur = next((f for f in forms_of(card) if f.name == current_form), None)
    if cur is None:
        return None
    alt = cheapest(store, card, domain=domain, exclude={current_form}, cost=cost)
    if alt is None or alt.cost >= cur.cost:
        return None
    return {"card": card["name"], "from": cur.name, "to": alt.name, "speedup": round(cur.cost / max(alt.cost, 0.01), 2),
            "from_cost": cur.cost, "to_cost": alt.cost, "to_domain": alt.domain, "notes": alt.notes,
            "basis": "anchor"}


def all_rewrites(store, domain: str = "any", category: str = "op") -> list[dict]:
    """For every card, rewrites away from its canonical (first) form."""
    out = []
    for card in store.cards(category):
        fs = forms_of(card)
        if not fs:
            continue
        r = suggest_rewrite(store, card, fs[0].name, domain)
        if r:
            out.append(r)
    return sorted(out, key=lambda r: -r["speedup"])


def enumerate_forms(store, card) -> list[dict]:
    rows = []
    for f in sorted(forms_of(card), key=lambda f: f.cost):
        ok, why = available(store, f)
        rows.append({"form": f.name, "cost": f.cost, "domain": f.domain, "lang": f.lang, "runnable": f.runnable,
                     "available": ok, "reason": why, "notes": f.notes,
                     "measured_ns": measured_ns(store, card["name"], f.name)})
    return rows


# -- cost vectors -----------------------------------------------------------------
def directions(store, card) -> dict:
    d = dict(card.get("dimension_direction") or {})
    view = store.registry(card.registry or card.get("category", "")) if store is not None else None
    for k, v in ((view.meta.get("dimension_direction") if view else None) or {}).items():
        d.setdefault(k, v)
    return d


def rank(store, cards: list, weights: dict[str, float]) -> list[tuple[float, object]]:
    """Weighted score (lower is better) after min-max normalisation per dimension; 'higher' dims are inverted."""
    dims = list(weights)
    lo = {k: min(c.cost_vector.get(k, 0.0) for c in cards) for k in dims}
    hi = {k: max(c.cost_vector.get(k, 0.0) for c in cards) for k in dims}
    scored = []
    for c in cards:
        dirs = directions(store, c)
        s = 0.0
        for k, w in weights.items():
            span = (hi[k] - lo[k]) or 1.0
            x = (c.cost_vector.get(k, 0.0) - lo[k]) / span
            s += w * (1.0 - x if dirs.get(k, "lower") == "higher" else x)
        scored.append((round(s, 6), c))
    return sorted(scored, key=lambda p: p[0])


def pareto(store, cards: list, dims: list[str]) -> list:
    """Cards not dominated on ``dims`` (respecting each dimension's direction)."""
    def better_eq(a, b, k, dirs):
        x, y = a.cost_vector.get(k, 0.0), b.cost_vector.get(k, 0.0)
        return x >= y if dirs.get(k, "lower") == "higher" else x <= y

    out = []
    for a in cards:
        dirs = directions(store, a)
        dominated = False
        for b in cards:
            if b is a:
                continue
            if all(better_eq(b, a, k, dirs) for k in dims) and any(not better_eq(a, b, k, dirs) for k in dims):
                dominated = True
                break
        if not dominated:
            out.append(a)
    return out
