"""Float literals keep their exact value and the sign of zero in every codegen language (CM17).

Go constants have no negative zero, so ``float64(-0.0)`` is +0: the emitted code computed with the wrong zero and
nothing noticed, because the matrix compared -0.0 and +0.0 as equal. These tests run the emitted literal through a
sign-sensitive function (atan2(z, -1) is -pi for -0.0 and +pi for +0.0, independent of how a target prints a
zero) in every language installed here, and check the comparison the matrix uses.
"""
import math
import unittest

from helpers import SEED, model_ctx, seed_note

from cardmodel.engines import conformance, frontends
from cardmodel.engines import values as V
from cardmodel.engines.codegen import Emitter
from cardmodel.engines.runners import run_program

# codegen targets with a float type (Lean's codegen has none)
LANGS = ("c", "cpp", "go", "java", "javascript", "typescript", "python", "ruby", "rust", "lua", "swift")
# finite doubles at the edges: zeros, the smallest subnormal, the smallest normal, the largest double
SPECIAL = (-0.0, 0.0, 5e-324, -5e-324, 1e-310, 2.2250738585072014e-308, 1.7976931348623157e308,
           -1.7976931348623157e308, 0.1, -2.5)


def _fn(name, value, params=()):
    return {"name": name, "params": [{"name": p, "type": "float"} for p in params], "returns": "float",
            "locals": {}, "body": [{"k": "return", "value": value}]}


def _program():
    """Functions returning each literal as is, atan2(literal, -1.0), atan2(argument, -1.0) and -(literal)."""
    fns, calls, want = [], [], []
    for i, v in enumerate(SPECIAL):
        fns.append(_fn(f"lit{i}", ["float", v]))
        calls.append((f"lit{i}", []))
        want.append(("exact", v))
    for i, v in enumerate((-0.0, 0.0)):
        fns.append(_fn(f"sgn{i}", ["ATAN2", ["float", v], ["float", -1.0]]))
        calls.append((f"sgn{i}", []))
        want.append(("exact", math.atan2(v, -1.0)))
    fns.append(_fn("arg", ["ATAN2", ["var", "x"], ["float", -1.0]], ["x"]))
    fns.append(_fn("ident", ["var", "x"], ["x"]))
    for v in (-0.0, 0.0):
        calls.append(("arg", [v]))
        want.append(("exact", math.atan2(v, -1.0)))
    for v in SPECIAL:
        calls.append(("ident", [v]))
        want.append(("exact", v))
    fns.append(_fn("neg", ["NEG", ["float", -2.5]]))          # C once wrote this as (--2.5): a decrement
    fns.append(_fn("negz", ["ATAN2", ["NEG", ["float", -0.0]], ["float", -1.0]]))
    calls += [("neg", []), ("negz", [])]
    want += [("exact", 2.5), ("exact", math.pi)]
    return {"entry": "arg", "functions": fns}, calls, want


def _same_bits(a, b) -> bool:
    return isinstance(b, float) and a == b and math.copysign(1.0, a) == math.copysign(1.0, b)


class FloatLiterals(unittest.TestCase):
    def test_literals_keep_value_and_sign_of_zero(self):
        ctx = model_ctx()
        module, calls, want = _program()
        ran = []
        for lang in LANGS:
            if not ctx.available(lang)[0]:
                continue
            src = Emitter(ctx.store, lang, ctx.ops).program(module, calls)
            res = run_program(ctx.language(lang), src, ctx.state_root)
            self.assertEqual(res.status, "ok", f"{lang}: {res.detail or res.stderr}")
            self.assertEqual(len(res.values), len(want), lang)
            for (name, args), (_, exp), got in zip(calls, want, res.values):
                self.assertTrue(_same_bits(exp, got), f"{lang} {name}{tuple(args)}: expected {exp!r}, got {got!r}")
            ran.append(lang)
        if not ran:
            self.skipTest("no codegen toolchain on this host")

    def test_go_negative_zero_is_not_a_constant(self):
        """Toolchain-free: Go's literal for -0.0 must not be a constant expression (float64(-0.0) is +0)."""
        ctx = model_ctx()
        em = Emitter(ctx.store, "go", ctx.ops)
        self.assertNotIn("-0.0", em.lit("float", -0.0))
        self.assertEqual(em.lit("float", 0.0), "float64(0.0)")
        self.assertEqual(em.lit("float", -1.5), "float64(-1.5)")
        self.assertIn("-0.0", Emitter(ctx.store, "python", ctx.ops).lit("float", -0.0))

    def test_go_source_harness_passes_negative_zero(self):
        """The harness that runs an original Go source also writes -0.0 so that Go keeps the sign."""
        ctx = model_ctx()
        if not ctx.available("go")[0]:
            self.skipTest("no Go toolchain on this host")
        src = "package algos\n\nfunc inv(x float64) float64 {\n\treturn 1 / x\n}\n"
        module = {"entry": "inv", "functions": [{"name": "inv", "params": [{"name": "x", "type": "float"}],
                                                  "returns": "float", "locals": {}, "body": []}]}
        prog = frontends.source_program(ctx, "go", src, module, [[-0.0], [0.0]], ["float64"])
        res = run_program(ctx.language("go"), prog, ctx.state_root)
        self.assertEqual(res.status, "ok", res.detail or res.stderr)
        self.assertEqual(res.values, [-math.inf, math.inf])

    def test_matrix_compares_zeros_by_sign(self):
        self.assertTrue(V.same(-0.0, 0.0))                       # the default comparison is unchanged
        self.assertFalse(V.same(-0.0, 0.0, signed_zero=True))
        self.assertTrue(V.same(-0.0, -0.0, signed_zero=True))
        self.assertTrue(V.same(1e-13, -1e-13, signed_zero=True))  # only exact zeros are sign-checked
        self.assertFalse(V.same([1.0, -0.0], [1.0, 0.0], signed_zero=True))
        self.assertEqual(conformance._with_negative_zero([(0.0, 1.0), (2.0, 3.0), (-0.0, 1.0)]),
                         [(0.0, 1.0), (2.0, 3.0), (-0.0, 1.0)])
        self.assertEqual(conformance._with_negative_zero([(0.0, 0, 0.0)]), [(0.0, 0, 0.0), (-0.0, 0, -0.0)])

    def test_matrix_catches_a_lost_negative_zero(self):
        """A Go literal template that writes -0.0 as a constant again must fail the matrix (CM07)."""
        ctx = model_ctx()
        if not ctx.available("go")[0]:
            self.skipTest("no Go toolchain on this host")
        go = ctx.store.get("language/go")
        lit = dict(go["codegen"]["lit"])
        lit.pop("float_neg_zero")
        bad = dict(go, codegen=dict(go["codegen"], lit=lit))
        orig_get = ctx.store.get
        ctx.store.get = lambda key, *a, **k: bad if key == "language/go" else orig_get(key, *a, **k)
        try:
            rep = conformance.matrix(ctx, langs=["go"], seed=SEED, samples=2, ops=["NEG", "SIN"])
        finally:
            ctx.store.get = orig_get
        cells = rep["languages"]["go"]["cells"]
        self.assertEqual(cells["t_neg_f"]["status"], "fail", f"{cells['t_neg_f']} {seed_note(self)}")
        self.assertEqual(cells["t_neg_f"]["args"], [-0.0])
        self.assertEqual(cells["t_sin_f"]["status"], "fail", cells["t_sin_f"])


if __name__ == "__main__":
    unittest.main()
