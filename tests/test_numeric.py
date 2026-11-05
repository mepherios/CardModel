"""Numeric models (docs/ENVIRONMENTS.md V-B; engines/numeric.py): fp_contract, denormal_flush, reduction_order, the
laws that say when two runners agree bit for bit and the bound otherwise, measured by probes on this host."""
import math
import platform
import random
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import analyse as A
from cardmodel.engines import matrix as M
from cardmodel.engines import numeric as N
from cardmodel.engines import values as V

X86 = platform.machine().lower() in ("x86_64", "amd64")
LINUX_GCC = platform.system() == "Linux"


class DeclaredTest(unittest.TestCase):
    """The declared model: the runner's flags read against its language card's numeric block."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        cls.c = cls.ctx.language("c")

    def test_gcc_iso_mode_does_not_contract(self):
        m = N.declare(self.c, ["-O2", "-std=c11"], "gcc", "x86_64", frozenset())
        self.assertEqual(m["fp_contract"]["permits"], "off")
        self.assertIs(N.strict(m), True)
        gnu = N.declare(self.c, ["-O2", "-std=gnu11"], "gcc", "aarch64", frozenset())
        self.assertEqual((gnu["fp_contract"]["permits"], gnu["fp_contract"]["value"]), ("fast", True))

    def test_contraction_needs_an_fma_instruction(self):
        fast = ["-O2", "-std=c11", "-ffast-math"]
        x86 = N.declare(self.c, fast, "gcc", "x86_64", frozenset({"fma"}))
        self.assertEqual((x86["fp_contract"]["permits"], x86["fp_contract"]["value"]), ("fast", False))
        native = N.declare(self.c, fast + ["-march=native"], "gcc", "x86_64", frozenset({"fma"}))
        self.assertIs(native["fp_contract"]["value"], True)
        arm = N.declare(self.c, fast, "gcc", "aarch64", frozenset())
        self.assertIs(arm["fp_contract"]["value"], True)
        clang = N.declare(self.c, ["-O2", "-std=c11"], "clang", "aarch64", frozenset())
        self.assertIs(clang["fp_contract"]["value"], True)        # clang's default: fusion inside an expression
        off = N.declare(self.c, ["-O2", "-ffast-math", "-ffp-contract=off"], "clang", "aarch64", frozenset())
        self.assertIs(off["fp_contract"]["value"], False)

    def test_fast_math_flushes_and_reassociates(self):
        m = N.declare(self.c, ["-O2", "-std=c11", "-ffast-math"], "gcc", "x86_64", frozenset())
        self.assertIs(m["denormal_flush"]["value"], True)
        self.assertEqual(m["reduction_order"]["value"], "reassociate")
        self.assertIs(m["strict_ieee"]["value"], False)
        self.assertEqual({m[c]["evidence"] for c in N.COMPONENTS}, {"declared"})

    def test_card_without_a_numeric_block_is_unknown(self):
        m = N.declare({"name": "nothing"}, [])
        self.assertIsNone(N.strict(m))
        self.assertEqual(N.agreement(N.REFERENCE, m)["mode"], "unknown")

    def test_inherited_by_extending_languages(self):
        cpp = self.ctx.language("cpp")
        self.assertEqual(cpp["numeric"], self.c["numeric"])
        m = N.declare(cpp, ["-O2", "-std=c++17"], "gcc", "aarch64", frozenset())
        self.assertIs(m["fp_contract"]["value"], False)


class LawsTest(unittest.TestCase):
    """The laws: exact under their premise, within their bound when it fails, refuted when a premise is false."""

    def test_agreement_is_exact_only_for_strict_models_and_rounded_ops(self):
        rust = N.declare(model_ctx().language("rust"), ["-O"])
        self.assertEqual(N.agreement(N.REFERENCE, rust)["mode"], "exact")
        ops = model_ctx().ops
        sin = {"functions": [{"name": "f", "body": [{"k": "return", "value": ["SIN", ["var", "x"]]}]}]}
        ag = N.agreement(N.REFERENCE, rust, sin, ops)
        self.assertEqual((ag["mode"], ag["gap"]), ("bounded", ["op/SIN"]))     # libm: no bit claim, named as the gap
        div = {"functions": [{"name": "f", "body": [{"k": "return", "value": ["DIV", ["var", "x"], ["var", "y"]]}]}]}
        self.assertEqual(N.agreement(N.REFERENCE, rust, div, ops)["mode"], "exact")
        fast = N.declare(model_ctx().language("c"), ["-ffast-math"], "gcc", "x86_64", frozenset())
        ag = N.agreement(N.REFERENCE, fast, div, ops)
        self.assertEqual((ag["mode"], ag["laws"]), ("bounded", ["denormal_flush", "reduction_order"]))
        self.assertEqual(ag["gap"], ["op/DIV"])              # DIV is an atom FTZ/DAZ changes: the carry map's gap

    def test_gap_is_godel_carry(self):
        """The gap is godel.carry's residual over the module's content (no private walk): same answer both ways."""
        from cardmodel.engines import godel
        ops = model_ctx().ops
        mod = {"functions": [{"name": "f", "body": [{"k": "return", "value": [
            "ADD", ["MUL", ["var", "a"], ["var", "x"]], ["EXP", ["var", "y"]]]}]}]}
        fast = N.declare(model_ctx().language("c"), ["-ffast-math", "-march=native"], "gcc", "x86_64",
                         frozenset({"fma"}))
        _img, g = godel.carry(godel.module_content(mod, ops), N.carry_map(fast, ops))
        self.assertEqual(N.gap(fast, mod, ops), sorted(g))
        self.assertEqual(N.gap(fast, mod, ops), ["op/ADD", "op/EXP", "op/MUL"])
        self.assertEqual(N.gap(N.REFERENCE, mod, ops), ["op/EXP"])

    def test_contract_bound_holds_and_is_needed(self):
        rng = random.Random(SEED)
        worst = 0.0
        for _ in range(3000):
            a, b = rng.uniform(-4, 4), rng.uniform(-4, 4)
            c = -a * b * (1 + rng.uniform(-1e-6, 1e-6)) if rng.random() < 0.5 else rng.uniform(-4, 4)
            fused = float(Fraction(a) * Fraction(b) + Fraction(c))
            unfused = a * b + c
            self.assertLessEqual(abs(fused - unfused), N.contract_bound(a, b, c), seed_note(self))
            if fused != unfused:
                worst = max(worst, abs(fused - unfused) / max(abs(fused), 1e-300))
        self.assertGreater(worst, 0.0, seed_note(self))     # the premise matters: the two forms do differ

    def test_reduction_bound_holds_for_any_two_orders(self):
        rng = random.Random(SEED)
        for _ in range(50):
            xs = [rng.uniform(-1, 1) * 10.0 ** rng.randint(-8, 8) for _ in range(rng.randint(2, 600))]
            seq = sum(xs[1:], xs[0])
            rev = sum(reversed(xs[:-1]), xs[-1])
            lanes = [sum(xs[k::4], 0.0) for k in range(4)]
            tree = (lanes[0] + lanes[1]) + (lanes[2] + lanes[3])
            bound = N.reduction_bound(xs)
            self.assertLessEqual(abs(seq - rev), bound, seed_note(self))
            self.assertLessEqual(abs(seq - tree), bound, seed_note(self))
        ints = [float(rng.randint(-10 ** 6, 10 ** 6)) for _ in range(500)]   # exact partial sums: any order agrees
        self.assertTrue(N.same_bits(sum(ints), sum(reversed(ints))))

    def test_flush_is_invisible_to_the_blanket_tolerance(self):
        self.assertTrue(V.same(2.5e-310, 0.0))                  # values.same's abs_tol hides a flushed result
        self.assertFalse(N.same_bits(2.5e-310, 0.0))
        self.assertLess(2.5e-310, N.flush_bound())
        self.assertFalse(N.same_bits(-0.0, 0.0))
        self.assertTrue(N.same_bits(-0.0, 0.0, signed_zero=False))
        self.assertTrue(N.same_bits(float("nan"), float("nan")))
        self.assertEqual(N.ulps(1.0, math.nextafter(1.0, 2.0)) if hasattr(math, "nextafter") else 1, 1)

    def test_combine_refutes_a_declared_row_the_probe_contradicts(self):
        e = N.probe_expected()
        strict = N.declare(model_ctx().language("c"), ["-O2", "-std=c11"], "gcc", "x86_64", frozenset())
        raw = {"contract": e["contract_fused"], "ftz": e["ftz"], "daz": e["daz"], "sum": e["sum"]}
        m = N.combine(strict, raw, e)
        self.assertEqual((m["fp_contract"]["value"], m["fp_contract"]["evidence"]), (True, "measured"))
        self.assertIn("refutes", m["fp_contract"])
        self.assertEqual(m["denormal_flush"]["evidence"], "measured")
        fast = N.declare(model_ctx().language("c"), ["-ffast-math"], "gcc", "x86_64", frozenset())
        m = N.combine(fast, {"contract": e["contract"], "ftz": 0.0, "daz": 0.0, "sum": e["sum"]}, e)
        self.assertEqual(m["denormal_flush"]["evidence"], "measured")
        self.assertEqual((m["reduction_order"]["value"], m["reduction_order"]["evidence"]), ("reassociate",
                                                                                            "declared"))


class ProbeTest(unittest.TestCase):
    """The probes compiled with each C runner's own compile line, run on this host."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        if not cls.ctx.available("c")[0]:
            raise unittest.SkipTest("no C compiler on this machine")
        cls.models = N.models(cls.ctx)

    def test_strict_runners_give_the_reference_bits(self):
        for name in ("c@O0", "c@O2", "c@ubsan"):
            m = self.models[name]
            self.assertTrue(N.strict(m), name)
            for c in N.COMPONENTS:
                self.assertEqual(m[c]["evidence"], "measured", (name, c))
            for row in N.check(self.models["c@O0"], m):
                self.assertEqual((row["law"], row["verdict"]), ("numeric_exact", "holds"), (name, row))

    def test_every_law_holds_on_the_probes(self):
        names = [n for n in self.models if n.startswith("c@") and "probe" in self.models[n]]
        for a in names:
            for b in names:
                for row in N.check(self.models[a], self.models[b]):
                    self.assertEqual(row["verdict"], "holds", (a, b, row))

    @unittest.skipUnless(LINUX_GCC and X86, "FTZ/DAZ under -ffast-math is measured on x86-64 Linux")
    def test_fast_math_flushes_subnormals_here(self):
        m = self.models["c@fastmath"]
        self.assertEqual((m["denormal_flush"]["value"], m["denormal_flush"]["evidence"]), (True, "measured"))
        self.assertTrue(m["probe"]["observed"]["ftz"] and m["probe"]["observed"]["daz"])

    def test_contraction_when_the_target_has_fma(self):
        m = self.models["c@native_contract"]
        if not m["fp_contract"]["fma_instruction"]:
            self.skipTest("this host's ISA has no FMA instruction")
        self.assertTrue(m["probe"]["observed"]["contract_is_fused"])
        self.assertEqual((m["fp_contract"]["value"], m["fp_contract"]["evidence"]), (True, "measured"))

    def test_a_false_premise_refutes_the_exact_law(self):
        """Claim c@native_contract is strict (a wrong declared row): the exact law then predicts the reference's
        bits and the probe refutes it at the contracted expression."""
        m = self.models["c@native_contract"]
        if not m["probe"]["observed"]["fp_contract"]:
            self.skipTest("nothing contracted on this host")
        forged = dict(m, fp_contract=dict(m["fp_contract"], value=False))
        rows = {r["probe"]: r for r in N.check(self.models["c@O2"], forged)}
        self.assertEqual((rows["contract"]["law"], rows["contract"]["verdict"]), ("numeric_exact", "refuted"))
        self.assertEqual(rows["sum"]["verdict"], "holds")

    def test_vectorized_sum_is_reassociated_at_O3(self):
        m = self.models["c@O3_fast_native"]
        self.assertEqual(m["reduction_order"]["value"], "reassociate")
        if m["probe"]["observed"]["reduction_order"] == "reassociate":
            self.assertEqual(m["reduction_order"]["evidence"], "measured")


PY = '''
def axpy(a: float, x: float, y: float) -> float:
    return a * x + y

def total(n: int, x: float) -> float:
    s = 0.0
    for i in range(n):
        s = s + x * i
    return s
'''


class AnalyseTest(unittest.TestCase):
    """The three laws in the analyser: where they fire, and the comparison each runner gets."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = model_ctx()
        d = Path(tempfile.mkdtemp(prefix="cardmodel_numeric_"))
        p = d / "fl.py"
        p.write_text(PY, encoding="utf-8")
        cards, _ = M.frontend_for(p).cards(cls.ctx, p, SEED)
        cls.cards = {c["ir"]["entry"]: c for c in cards}

    def test_laws_fire_in_the_reference(self):
        laws = {n: {f["law"] for f in A.analyse_card(self.ctx, c, run=False, seed=SEED).findings}
                for n, c in self.cards.items()}
        self.assertIn("fp_contract", laws["axpy"])
        self.assertIn("denormal_flush", laws["axpy"], seed_note(self))    # 1e-310 is a boundary input
        self.assertIn("reduction_order", laws["total"])
        self.assertNotIn("reduction_order", laws["axpy"])
        why = A.explain(self.ctx, self.cards["axpy"]["ir"], [1e-310, 0.5, 0.0])
        self.assertIn("denormal_flush", [w["law"] for w in why])
        self.assertEqual(A.explain(self.ctx, self.cards["axpy"]["ir"], [1.0, 2.0, 3.0]), [])

    def test_comparison_follows_the_numeric_model(self):
        rs = A.runners(self.ctx, ["c", "ruby"])
        modes = A.comparisons(self.ctx, rs, self.cards["axpy"]["ir"])
        if "c@O2" in modes:
            self.assertEqual(modes["c@O2"]["mode"], "exact")
            self.assertEqual(modes["c@fastmath"]["mode"], "bounded")
            self.assertTrue(modes["c@fastmath"]["bits_visible"])
        if "ruby" in modes:
            self.assertEqual(modes["ruby"]["mode"], "unknown")
        self.assertTrue(A._agree({"value": 2.5e-310}, {"value": 0.0}))              # tolerance hides it
        self.assertFalse(A._agree({"value": 2.5e-310}, {"value": 0.0}, exact=True))

    @unittest.skipUnless(LINUX_GCC and X86, "FTZ/DAZ under -ffast-math is measured on x86-64 Linux")
    def test_flush_is_witnessed_in_a_loop(self):
        if not self.ctx.available("c")[0]:
            self.skipTest("no C compiler")
        card = self.cards["total"]
        card = dict(card, vectors=[{"args": [20000, 1e-310]}])
        a = A.analyse_card(self.ctx, card, run=True, seed=SEED, pool=A.runners(self.ctx, ["c@O2", "c@fastmath"]))
        fl = [f for f in a.findings if f["law"] == "denormal_flush"]
        self.assertTrue(fl, seed_note(self))
        self.assertIn("c@fastmath", set().union(*(f["differs"] for f in fl)), seed_note(self))
        self.assertNotIn("c@O2", set().union(*(f["differs"] for f in fl)), seed_note(self))
        self.assertEqual(a.numeric["c@O2"]["mode"], "exact")
        # the flushed sum (0.0 against 2.0e-302) is inside values.same's absolute tolerance: only the bit-for-bit
        # comparison the numeric laws choose sees it
        t = next(t for f in fl for t in f["triggers"] if "c@fastmath" in t["runners"]
                 and t["runners"]["c@fastmath"]["agrees"] is False)
        self.assertTrue(V.same(t["ref"]["value"], t["runners"]["c@fastmath"]["value"]))


if __name__ == "__main__":
    unittest.main()
