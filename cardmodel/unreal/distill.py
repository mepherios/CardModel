"""distill — the mathematics of every lifted engine function: canonical form, identity, Gödel numbers, use.

For a lifted function:
  real view      its terms over ℝ (rounding to binary32 and int -> float conversion are the identity there)
  canonical      each output's normal form (engines/realnorm.py), with the inputs renamed by position (x0, x1, ...
                 in the order the function takes them), so the form is the function's and not its spelling's
  hash           the semantic hash of the canonical outputs: two functions with one hash are one function
  content        the Gödel content vector of the canonical terms (each operation an atom, with multiplicity),
                 its number over the ledger's primes, and per output the structural tokens (Gödel's positional
                 numbering, kept as its exponent sequence: the number is prod p_i ** token_i)
  named          the engine functions it calls, by name: its content in the engine's own Gödel set
  use            what the function is for (vector algebra, rotation, interpolation, geometry, ...), from the
                 engine's own organisation (its type, its header) and its name

Across functions:
  identities     classes of functions with one hash (the same truth spelled twice, or a float and a double version)
  uses           per use: its members, and the GCD (what every member's logic contains) and LCM of their content
  carry          the map from the engine's Gödel set (its named functions as atoms) to the core atoms: each named
                 function goes to the content of its canonical form; what it cannot send (the gaps) is listed

Honest limits (L1): the canonical form decides equality for the polynomial fragment with uninterpreted atoms
(realnorm's limits); the use is read from the engine's names and organisation, not proved; structural tokens are
those of the canonical term, so they identify the normal form, not the engine's spelling of it.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

from ..engines import godel as G
from ..engines import realnorm as RN

# the engine's own organisation: a type (record) names a use; FMath and free functions are read by name
RECORD_USES = [   # matched against the record's own name (its namespace dropped)
    (r"^TVector<", "vector"), (r"^TVector2<", "vector2d"), (r"^TVector4<", "vector4"),
    (r"^TQuat<", "rotation.quaternion"), (r"^TRotator<", "rotation.euler"), (r"^TDualQuat<", "rotation.dual_quaternion"),
    (r"^T\w*Matrix\w*<|^TMatrix<|^FMatrix2x2|^TMatrix2x2", "matrix"),
    (r"^TTransform<|^TScale|^TShear2|^TQuat2|^TTransform2|^TransformConverter|^FDFMatrix|^FDFInverseMatrix", "transform"),
    (r"^TPlane<", "geometry.plane"), (r"^TRay<", "geometry.ray"),
    (r"^TBox<|^TBox2<|^TBoxSphereBounds<|^TSphere<|^TCapsule|^FOrientedBox|^TBounds", "bounds"),
    (r"^TInt\w*<|^FIntRect|^TIntRect", "integer.vector"),
    (r"^FLinearColor|^FColor|^FFloat16Color|^FDXT", "color"),
    (r"^FFloat16|^FFloat32|^TFloatPacker|^FFloat3Packed|^FFixedRGBA|^FPackedNormal|^FPackedRGB|^FVector2DHalf|"
     r"^FFloatInfo|^FPackedRGBA16N", "packing"),
    (r"^FRandomStream|^FSobol|^FHalton|^FLFSR|^Halton|^FLinearFeedbackShiftRegister", "random"),
    (r"^TInterval|^FFloatInterval|^FDoubleInterval|^FInt32Interval|^TRange|^TRangeBound|^TIntervalTraits|"
     r"^F\w*Range$|^F\w*RangeBound$", "interval"),
    (r"^FInterpCurve|^TInterpCurve|^FCurveEdInterface|^FInterpCurvePoint", "curves"),
    (r"^FUnitConversion|^FNumericUnit|^EUnit", "units"), (r"^TNumericLimits", "numeric.limits"),
    (r"^FU?Int128|^TBigInt|^FDFScalar|^FDFVector|^FLargeWorldRenderScalar", "numeric.extended"),
    (r"^FTwoVectors|^FEdge|^ConvexHull2D|^SegmentDistToSegment", "geometry"),
    (r"^FSHVector|^TSHVector|^FSHVectorRGB|^TSHVectorRGB", "spherical.harmonics"),
    (r"^FBoxCenterAndExtent|^FOctree|^TOctree|^FOctreeNodeContext|^FOctreeChildNodeRef|^FOctreeChildNodeSubset",
     "spatial.octree"),
    (r"^SpringMath|^FSpring", "physics.spring"),
    (r"Expression|Evaluator|TokenDefinitions", "expressions"),
    (r"^FScopedFTZFloatMode", "float.environment"),
]
NAME_USES = [
    (r"Interp|Lerp|SmoothStep|Ease|Hermite|Bezier|CubicCR|Cubic", "interpolation"),
    (r"Spring|Damp|CriticallyDamped", "physics.spring"),
    (r"Rand|Sobol|Halton|Seed|Noise", "random"),
    (r"Intersect|ClosestPoint|PointDist|SegmentDist|Bary|LineBox|LineExtentBox|LineSphere|PlaneAABB|Sphere|Cone|"
     r"GetDotDistance|Azimuth|Tetrahedron|Triangle|RayPlane|LinePlane|SegmentPlane|PointsAreCoplanar|"
     r"PointBoxIntersection|BoxPushOut|GetTForSegmentPlaneIntersect|ComputeProjectedSphere|IsPointInside",
     "geometry"),
    (r"Sin|Cos|Tan|Atan|Asin|Acos|Angle|Radians|Degrees|Unwind|Hypot", "trigonometry"),
    (r"Floor|Ceil|Round|Trunc|Frac|Fmod|Modf|Modulo|GridSnap|DivideAndRound|Wrap", "rounding"),
    (r"Sqrt|InvSqrt|Exp|Log|Pow|Square|Cube|Cbrt", "powers"),
    (r"FloorLog2|CeilLog2|CountLeadingZeros|CountTrailingZeros|CountBits|PowerOfTwo|Morton|Bit", "bits"),
    (r"IsNaN|IsFinite|IsNegativeOrNegativeZero|IsNegative|IsInfinite|AsUInt|AsFloat|FloatSelect", "float.bits"),
    (r"Abs|Sign|Min|Max|Clamp|IsNearly|IsWithin|Select|SafeDivide|Overflow", "scalar"),
]
SIMD = re.compile(r"^(Vector|MakeVectorRegister|GlobalVectorConstants::|VectorRegister)")


def use_of(f: dict) -> str:
    rec = f.get("record") or ""
    own = rec.split("<", 1)[0].split("::")[-1] + ("<" + rec.split("<", 1)[1] if "<" in rec else "")
    for pat, use in RECORD_USES:
        if re.search(pat, own):
            return use
    qual, name = f["qual"], f["name"]
    if SIMD.search(qual) or "UnrealMathFPU.h" in f["file"] or "UnrealMathVectorCommon" in f["file"] or \
            "UnrealMathVectorConstants" in f["file"]:
        return "simd.register"
    if "UnitConversion" in f["file"]:
        return "units"
    for pat, use in NAME_USES:
        if re.search(pat, name):
            return use
    if rec in ("FMath", "FGenericPlatformMath", "FClangPlatformMath", "FApplePlatformMath", "FMacPlatformMath",
               "FPlatformMath") or not rec:
        return "scalar"
    return "other"


def content(term) -> Counter:
    """Operations of a term with multiplicity, as ledger atoms (``op/NAME``): engines/godel.term_content over every
    head, since a canonical real term has no signature of its own. Constants and variables are not atoms; a
    shared subterm counts once per reference, computed once."""
    return G.term_content(term, None)


MAX_TOKENS = 4096


def tokens(term, index: dict, names: list[str]) -> list[int] | None:
    """Gödel's positional tokens of a term (engines/godel.tokens: atom k -> 3k+1, integer c -> 3*zig(c)+2,
    variable j -> 3j+3; a bool constant as the integer the real view converts it to); None when an atom is not in
    the ledger, a float constant appears, or the term is past MAX_TOKENS (its number is still defined, but not
    written out)."""
    try:
        return G.tokens(term, index, names, max_tokens=MAX_TOKENS, bools_as_ints=True)
    except (KeyError, ValueError):
        return None


NUMBER_DIGITS = 400


def number(c: Counter, index: dict) -> str | None:
    """prod p ** e as a decimal string when it has at most NUMBER_DIGITS digits; past that, None (the content
    vector is its exact factorization; ``digits`` gives its size)."""
    if any(a not in index for a in c):
        return None
    if digits(c, index) > NUMBER_DIGITS:
        return None
    n = 1
    for a, e in c.items():
        n *= index[a]["prime"] ** e
    return str(n)


def digits(c: Counter, index: dict) -> int | None:
    import math
    if any(a not in index for a in c):
        return None
    return int(sum(e * math.log10(index[a]["prime"]) for a, e in c.items())) + 1


def distill_function(f: dict, index: dict) -> dict:
    """The mathematics of one lifted function (see the module docstring)."""
    pos = {nm: f"x{i}" for i, (nm, _k) in enumerate(f["inputs"])}
    norm = RN.Normalizer()
    outs = []
    total: Counter = Counter()
    for o in f["outputs"]:
        if o["term"] is None:
            continue
        canon = RN.canonical(RN.rename(o["term"], pos), norm)
        c = content(canon)
        total += c
        names: list[str] = []
        toks = tokens(canon, index, names)
        sized = RN.sized_witness(RN.rename(o["term"], pos), canon)
        outs.append({"name": o["name"], "kind": o["kind"], "canonical": canon, "content": dict(c),
                     "tokens": toks, "variables": names, "over_reals": sized})
    h = RN.digest([[o["kind"], o["canonical"]] for o in outs])
    return {"key": f["key"], "hash": h, "outputs": outs, "content": dict(total), "digits": digits(total, index),
            "size": sum(_size(o["canonical"]) for o in outs), "lifted_size": sum(_size(o["term"])
                                                                                   for o in f["outputs"])}


def _size(t) -> int:
    from .lift import size
    return size(t)


OPWORDS = [("<<=", "shl_assign"), (">>=", "shr_assign"), ("+=", "plus_assign"), ("-=", "minus_assign"),
           ("*=", "times_assign"), ("/=", "div_assign"), ("|=", "bar_assign"), ("^=", "caret_assign"),
           ("&=", "and_assign"), ("==", "eq"), ("!=", "ne"), ("<=", "le"), (">=", "ge"), ("<<", "shl"),
           (">>", "shr"), ("[]", "index"), ("()", "call"), ("+", "plus"), ("-", "minus"), ("*", "times"),
           ("/", "div"), ("^", "caret"), ("|", "bar"), ("&", "and"), ("<", "lt"), (">", "gt"), ("=", "assign"),
           ("!", "not"), ("~", "tilde"), ("%", "mod")]


def card_name(f: dict) -> str:
    """An engine function's card name, in the characters card names allow: its qualified name without UE::Math::,
    scopes by dots, template arguments after a double underscore, an operator by its word, and 8 hex digits of its
    mangled name (overloads and instantiations differ there): ``TMatrix__float.Mirror-64c13a93``."""
    q = f["qual"]
    if q.startswith("UE::Math::"):
        q = q[len("UE::Math::"):]
    m = re.search(r"operator(\W+)$", q)
    if m:
        word = next((w for s, w in OPWORDS if s == m.group(1)), "op")
        q = q[:m.start()] + "operator_" + word
    q = q.replace("::", ".")
    q = re.sub(r"\s*<\s*", "__", q)
    q = re.sub(r"\s*>\s*", "", q)
    q = re.sub(r"[^A-Za-z0-9_.-]+", "_", q).strip("_.") or "fn"
    if not (q[0].isalpha() or q[0] == "_"):
        q = "_" + q
    return f"{q}-{RN.digest(f['key'])[7:15]}"


def call_arity(f: dict) -> int:
    """An engine function's arguments as an atom of the Gödel set unreal: its parameters, and the object for a
    non-static member function (a constructor's object is what it makes, not an argument)."""
    member = bool(f.get("record")) and not f.get("static") and f["kind"] in ("method", "operator", "conversion",
                                                                             "destructor")
    return len(f.get("params") or []) + int(member)


def atom_name(f: dict) -> str:
    """A named engine function as an atom of the engine's Gödel set (its card name: the ledger names its cards
    from the atom)."""
    return f"unreal/{card_name(f)}"


def run(scan: dict, index: dict) -> dict:
    fns = [f for f in scan["functions"] if f["status"] != "outside"]
    lifted = [f for f in fns if f["status"] == "lifted"]
    by_key = {f["key"]: f for f in fns}
    by_qual: dict[str, list] = defaultdict(list)
    for f in fns:
        by_qual[f["qual"]].append(f)
    rows = {}
    for f in lifted:
        rows[f["key"]] = {**distill_function(f, index), "use": use_of(f)}
    for f in fns:
        if f["key"] not in rows:
            rows[f["key"]] = {"key": f["key"], "use": use_of(f)}
    # identities: one hash, several functions
    classes: dict[str, list] = defaultdict(list)
    for k, r in rows.items():
        if "hash" in r and r["outputs"] and r.get("content"):    # something computed, not only copied
            classes[r["hash"]].append(k)
    identities = [{"hash": h, "members": sorted(ks, key=lambda k: (by_key[k]["qual"], k))}
                  for h, ks in classes.items() if len(ks) > 1]
    identities.sort(key=lambda c: (-len(c["members"]), by_key[c["members"][0]]["qual"]))
    # uses: members, common logic (GCD) and everything needed (LCM)
    uses: dict[str, dict] = {}
    for k, r in rows.items():
        u = uses.setdefault(r["use"], {"members": [], "lifted": 0, "gcd": None, "lcm": Counter()})
        u["members"].append(k)
        if "content" in r and r["content"]:
            c = Counter(r["content"])
            u["lifted"] += 1
            u["gcd"] = c if u["gcd"] is None else G.gcd(u["gcd"], c)
            u["lcm"] = G.lcm(u["lcm"], c)
    for u in uses.values():
        u["gcd"] = dict(+(u["gcd"] or Counter()))
        u["lcm"] = dict(+u["lcm"])
        u["atoms"] = dict(Counter(a for k in u["members"] for a in (rows[k].get("content") or {})).most_common())
        # the logic most of the use shares: atoms in at least half of the lifted members, at the exponent every
        # member that has the atom reaches (the GCD of the majority; the strict GCD is empty as soon as one
        # member is trivial)
        lifted = [Counter(rows[k]["content"]) for k in u["members"] if rows[k].get("content")]
        common = {}
        for a, n in u["atoms"].items():
            if lifted and n * 2 >= len(lifted):
                common[a] = min(c[a] for c in lifted if c[a])
        u["common"] = common
    # carry: the engine's named functions -> core content; the gap is what has no image
    carry, gap = {}, {}
    for f in fns:
        a = atom_name(f)
        r = rows[f["key"]]
        if "content" in r:
            carry[a] = r["content"]
        else:
            gap[a] = f.get("cause") or f["status"]
    disjoint = G.preserves_gcd(carry)
    # the named view: each function's calls as atoms of the engine's set
    named = {}
    for f in lifted:
        calls = Counter()
        for q, n in (f.get("calls") or {}).items():
            for g in by_qual.get(q, []):
                calls[atom_name(g)] += n
                break
        named[f["key"]] = dict(calls)
    return {"rows": rows, "identities": identities, "uses": uses, "carry": {"image": carry, "gap": gap,
                                                                              "preserves_gcd": disjoint},
            "named": named}


def new_atoms(scan: dict, index: dict) -> list[str]:
    """Operations the lifted terms use that the ledger does not have yet (canonical terms use no others)."""
    seen: set = set()
    for f in scan["functions"]:
        for o in f.get("outputs") or []:
            seen |= set(content(o["term"]))
    seen |= {"op/DIV", "op/MUL", "op/ADD", "op/SUB", "op/NEG"}
    return sorted(a for a in seen if a not in index)


__all__ = ["atom_name", "call_arity", "card_name", "content", "distill_function", "new_atoms", "run", "tokens", "use_of"]
